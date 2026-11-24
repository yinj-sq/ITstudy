from flask import Blueprint, request, render_template, redirect, url_for, flash, jsonify
from flask import current_app
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models import Exam
from app.decorators import admin_login_required
from app.utils import get_subjects_cached, invalidate_exam_list_cache, json_body_or_empty
from app.services.scoring_service import has_active_attempt

exam_mgmt_bp = Blueprint('exam_management', __name__, url_prefix='')


def _invalidate_exam_list_cache():
    # 委托 app.utils 的唯一实现（含 lookup:recent_exams）——此前本地实现
    # 漏删导航"最近试卷"下拉缓存，与 api.py 通道键集漂移
    invalidate_exam_list_cache()


@exam_mgmt_bp.route('/admin/exams', methods=['GET', 'POST'])
@admin_login_required
def admin_exams():
    """管理员试卷管理页面"""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('试卷名称不能为空')
            return redirect(url_for('exam_management.admin_exams'))
        try:
            subject_id = request.form.get('subject_id', '').strip()
            duration = request.form.get('duration', '').strip()
            # 时长必填（与 API 创建一致）：没有时长的试卷跳过服务端超时
            # 强校验，学生可绕过前端倒计时无限时作答
            if not duration:
                flash('考试时长必填（分钟）')
                return redirect(url_for('exam_management.admin_exams'))
            try:
                duration_int = int(duration)
            except (TypeError, ValueError):
                flash('考试时长必须是整数分钟')
                return redirect(url_for('exam_management.admin_exams'))
            if duration_int < 1:
                flash('考试时长必须大于0分钟')
                return redirect(url_for('exam_management.admin_exams'))
            # 试卷名称全局唯一（批量导入按卷命名也依赖此约定，防同名校验失败）
            if Exam.query.filter_by(name=name).first():
                flash('试卷名称已存在，请使用其他名称')
                return redirect(url_for('exam_management.admin_exams'))
            exam = Exam(name=name, is_active=True,
                        subject_id=int(subject_id) if subject_id else None,
                        duration=duration_int)
            db.session.add(exam)
            db.session.commit()
            _invalidate_exam_list_cache()
            flash('试卷添加成功')
            current_app.logger.info(f"试卷添加成功: {name}")
        except IntegrityError:
            # 数据库唯一约束兜底：并发创建同名卷时给出友好提示而非 500
            db.session.rollback()
            flash('试卷名称已存在，请使用其他名称')
        except Exception as e:
            flash('添加试卷失败')
            current_app.logger.error(f"添加试卷失败: {str(e)}", exc_info=True)
        return redirect(url_for('exam_management.admin_exams'))
    from app.utils import paginate_query
    from sqlalchemy.orm import joinedload as _jl
    pagination = paginate_query(
        Exam.query.options(_jl(Exam.subject)).order_by(Exam.create_time.desc()),
        default_per_page=20, max_per_page=100
    )
    subjects = get_subjects_cached()
    return render_template('admin_exams.html', exams=pagination.items,
                           subjects=subjects, pagination=pagination)


@exam_mgmt_bp.route('/admin/exams/edit/<int:exam_id>', methods=['GET', 'POST'])
@admin_login_required
def edit_exam(exam_id):
    """编辑试卷信息"""
    exam = db.get_or_404(Exam, exam_id)
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('试卷名称不能为空')
            return redirect(url_for('exam_management.edit_exam', exam_id=exam_id))
        # 改名重名校验（排除自身）
        dup = Exam.query.filter(Exam.name == name, Exam.id != exam_id).first()
        if dup:
            flash('试卷名称已存在，请使用其他名称')
            return redirect(url_for('exam_management.edit_exam', exam_id=exam_id))
        try:
            duration = request.form.get('duration', '').strip()
            if duration:
                try:
                    duration_int = int(duration)
                except (TypeError, ValueError):
                    flash('考试时长必须是整数分钟')
                    return redirect(url_for('exam_management.edit_exam', exam_id=exam_id))
                if duration_int < 1:
                    flash('考试时长必须大于0分钟')
                    return redirect(url_for('exam_management.edit_exam', exam_id=exam_id))
            else:
                # 留空 = 保持原值：存量无时长试卷（创建必填策略前的历史数据）
                # 编辑时不被误覆盖为 None；时长一旦设置不得清空
                duration_int = exam.duration
            # 在考保护：题目/提交/超时判定始终读取"当前 duration"，
            # 考试进行中改时长会立即改变所有在考学生的截止时间（调小=直接
            # 判超时、调大=静默加时）。存在未超时开考记录时禁止修改。
            if duration_int != exam.duration and has_active_attempt(exam):
                flash('考试进行中，不能修改考试时长；请等待交卷或先清理在考记录')
                return redirect(url_for('exam_management.edit_exam', exam_id=exam_id))
            exam.name = name
            exam.duration = duration_int
            db.session.commit()
            _invalidate_exam_list_cache()
            flash('试卷修改成功')
            current_app.logger.info(f"试卷修改成功: {exam_id} -> {name}, 时长={exam.duration}")
        except IntegrityError:
            # 数据库唯一约束兜底：并发改名撞名时友好提示
            db.session.rollback()
            flash('试卷名称已存在，请使用其他名称')
        except Exception as e:
            flash('修改试卷失败')
            current_app.logger.error(f"修改试卷失败: {str(e)}", exc_info=True)
        return redirect(url_for('exam_management.admin_exams'))
    return render_template('edit_exam.html', exam=exam)


@exam_mgmt_bp.route('/admin/exams/delete/<int:exam_id>', methods=['POST'])
@admin_login_required
def delete_exam(exam_id):
    """删除试卷"""
    exam = db.get_or_404(Exam, exam_id)
    from app.models import Result, ExamAttempt
    try:
        # 前置检查先于任何破坏性语句：此前先执行关联清理 SQL 再检查成绩数，
        # 失败路径依赖 teardown 隐式回滚（易在改动中埋雷）
        # 在考拦截（与 API 版 api_exams.delete_exam 同口径）：存在"进行中"
        # （未超时）开考记录 = 考试进行中，删卷会使在考学生的提交通道失效。
        # 超时残留记录（弃考/断网超过 时长+宽限）不阻断——其提交通道已被
        # 服务端时长校验关闭，下方清理语句会一并删除
        from app.services.scoring_service import has_active_attempt
        if has_active_attempt(exam):
            flash('无法删除：该试卷有学生正在考试，请先收卷或等待交卷'
                  '（超时未交卷的弃考记录可用"清除超时开考记录"清理）')
            return redirect(url_for('exam_management.admin_exams'))
        # 有成绩记录的试卷直接删除会触发外键 IntegrityError，
        # 提前检查并给出明确提示（需先清空成绩）
        result_count = Result.query.filter_by(exam_id=exam_id).count()
        if result_count > 0:
            flash(f'无法删除：该试卷已有 {result_count} 条成绩记录，请先删除成绩')
            return redirect(url_for('exam_management.admin_exams'))
        # 题库/试卷解耦：删卷不再被题目阻碍（题目本体留在题库；
        # 关联行随删卷清理；来源卷引用置空——question.exam_id 仅溯源）
        from app.models import ExamQuestion
        from sqlalchemy import text as _sql_text
        ExamQuestion.query.filter_by(exam_id=exam_id).delete(
            synchronize_session=False)
        db.session.execute(
            _sql_text('UPDATE question SET exam_id = NULL WHERE exam_id = :e'),
            {'e': exam_id})
        # 清理残留开考记录（瞬态数据）：上方在考拦截通过后"进行中"记录已空，
        # 此处删除的是超时残留，兜底并发窗口内的 FK 无级联 500
        ExamAttempt.query.filter(ExamAttempt.exam_id == exam_id).delete(
            synchronize_session=False)
        db.session.delete(exam)
        db.session.commit()
        _invalidate_exam_list_cache()
        flash('试卷删除成功')
        current_app.logger.info(f"试卷删除成功: {exam_id} {exam.name}")
    except Exception as e:
        db.session.rollback()
        flash('删除试卷失败')
        current_app.logger.error(f"删除试卷失败: {str(e)}", exc_info=True)
    return redirect(url_for('exam_management.admin_exams'))


@exam_mgmt_bp.route('/admin/exams/<int:exam_id>/clear-stale-attempts',
                    methods=['POST'])
@admin_login_required
def clear_stale_attempts(exam_id):
    """清除超时未交卷的开考记录（弃考补救入口，列表页按钮触发）。

    学生开考后弃考（关机/断网/关页）会留下开考记录：提交通道已被
    submit_exam 的时长强校验关闭，但记录本身让学生无法重进考试
    （重进重置计时=可借弃考重置倒计时的作弊通道）。本端点默认仅删除
    超过"时长+宽限"的残留记录，删除后学生可重新开考（相当于教师
    点名重考）；"进行中"（未超时）记录不受影响。

    force=1：清除该试卷**全部**开考记录。覆盖默认口径覆盖不到的死角：
    无时长试卷的开考记录没有超时判定（attempt_is_stale 恒为"未超时"），
    学生打开过考试页却从未交卷时该记录会永久锁死组卷/删卷，且"清超时"
    按钮对其恒报"没有可清除的"——管理员此前无任何补救出口（只能改库）。
    """
    exam = db.get_or_404(Exam, exam_id)
    from app.models import ExamAttempt
    from app.services.scoring_service import attempt_is_stale
    force = request.form.get('force', '') == '1'
    attempts = ExamAttempt.query.filter_by(exam_id=exam_id).all()
    if force:
        stale = list(attempts)
    else:
        stale = [a for a in attempts if attempt_is_stale(exam, a)]
    for a in stale:
        db.session.delete(a)
    db.session.commit()
    if stale:
        scope = '全部' if force else '超时未交卷的'
        if exam.is_collected:
            flash(f'已清除 {len(stale)} 条{scope}开考记录；'
                  '试卷当前已收卷，如需学生重考请先取消收卷')
        else:
            flash(f'已清除 {len(stale)} 条{scope}开考记录，'
                  '相关学生可重新参加该考试')
        current_app.logger.info(
            f"清除开考记录: exam_id={exam_id}, count={len(stale)}, force={force}")
    else:
        flash('没有可清除的超时开考记录（仅"超过时长+5分钟仍未交卷"的记录可清除；'
              '无时长试卷的残留记录需用"强制清除全部开考记录"）')
    return redirect(url_for('exam_management.admin_exams'))


@exam_mgmt_bp.route('/admin/exams/toggle/<int:exam_id>', methods=['POST'])
@admin_login_required
def toggle_exam_flag(exam_id):
    """切换试卷4个状态标志"""
    exam = db.get_or_404(Exam, exam_id)
    flag = request.form.get('flag', '')
    value = request.form.get('value', '') == 'true'
    if flag in ('is_visible', 'is_enabled', 'is_collected', 'allow_view_results'):
        setattr(exam, flag, value)
        db.session.commit()
        _invalidate_exam_list_cache()
        # 收卷状态缓存失效：exam_status 轮询端点（2s TTL）及时感知
        from app.extensions import cache as _flag_cache
        _flag_cache.delete(f'exam:collected:{exam_id}')
        # 收卷通知**不走 SSE**：学生端收卷检测已改为 5s 轮询
        # /exam/<id>/status（见 online_exam.html 的 startCollectionPolling——
        # 250 人考试下每人一条常驻 SSE 连接会占满 Waitress 48 线程池）。
        # 此处原有一句 `sse_bump(f'exam_collected_{exam_id}')`，注释宣称
        # 「在考学生收到 refresh 后立即自动交卷」，但全项目无任何订阅者
        # （grep /api/events 只有 classroom 一个活通道），是"后端推、前端
        # 无人听"的死通道，故于 2026-09-13 移除，避免误导后来者。
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': '无效标志'}), 400


# ═══════════════════════════════════════════════════════════════
#  组卷（题库/试卷解耦）：从题库选题填充试卷
#  —— 总分 = 卷内各题分值汇总（exam_total_score 实时计算）；
#  —— 卷内自动按题型分组（单选→多选→判断→填空→简答→Python→综合），
#     组内按添加顺序，全局题号 1..N（exam_questions_ordered 统一生成）；
#  —— 已有成绩的试卷锁定编辑（防成绩口径漂移）。
# ═══════════════════════════════════════════════════════════════


def exam_compose_lock_message(exam_id):
    """试卷当前不允许改动题集/分值时返回原因，否则 None。

    组卷页之外，"带卷建题 / Excel 导入到卷 / 改题目归属到新卷 / 给综合题加小题"
    同样会改动试卷满分——都必须过同一把锁，否则已有成绩的卷满分被悄悄改掉。
    """
    exam = db.session.get(Exam, exam_id) if exam_id else None
    if not exam:
        return None
    from app.models import Result
    from app.services.scoring_service import has_active_attempt
    if db.session.query(Result.id).filter_by(exam_id=exam_id).first():
        return '该试卷已有成绩记录，组卷已锁定。如需调整请先删除该卷全部成绩'
    if exam.is_collected:
        return '试卷已收卷，组卷已锁定'
    # 在考锁定：学生作答中改题集/排序会使答题界面与成绩口径错位。
    # 按"存在未超时开考记录"判定——超时残留记录（弃考/断网超过
    # 时长+宽限）的提交通道已被 submit_exam 关闭，不会再产生成绩，
    # 不应永久锁死组卷（此前一个弃考学生即锁死整卷）
    if has_active_attempt(exam):
        return '该试卷有学生正在考试，组卷已锁定'
    return None


def _compose_guard(exam_id):
    """组卷编辑前置校验：返回 (exam, error_response)"""
    exam = db.get_or_404(Exam, exam_id)
    msg = exam_compose_lock_message(exam_id)
    if msg:
        return exam, (jsonify({'success': False, 'message': msg}), 409)
    return exam, None


def _compose_payload(exam):
    """组卷页/接口的统一数据：已选题（分组序+题号）+ 总分"""
    from app.models import exam_questions_ordered
    pairs = exam_questions_ordered(exam.id)
    total = 0.0
    questions = [{
        'id': q.id,
        'seq': seq,
        'question_type': q.question_type,
        'score': q.score,
        'content': (q.content or '')[:120],
    } for q, seq in pairs]
    total = round(sum(q.score or 0 for q, _ in pairs), 2)   # 就地汇总，省一次全量查询
    return {
        'exam_id': exam.id,
        'exam_name': exam.name,
        'questions': questions,
        'total_score': total,
        'question_count': len(questions),
    }


@exam_mgmt_bp.route('/admin/exams/<int:exam_id>/compose', methods=['GET'])
@admin_login_required
def exam_compose_page(exam_id):
    """组卷页面"""
    exam = db.get_or_404(Exam, exam_id)
    # locked 与后端写操作（_compose_guard → exam_compose_lock_message）同口径：
    # 还须包含「有学生正在考试」。此前只判「有成绩 or 已收卷」，在考时页面显示
    # 未锁定、可编辑，保存却一律 409，UI 与后端分叉。
    locked = bool(exam_compose_lock_message(exam_id))
    return render_template('admin_exam_compose.html', exam=exam, locked=locked)


@exam_mgmt_bp.route('/admin/exams/<int:exam_id>/compose/data', methods=['GET'])
@admin_login_required
def exam_compose_data(exam_id):
    """组卷数据：已选题 + 总分（页面轮询/保存后刷新用）"""
    exam = db.get_or_404(Exam, exam_id)
    return jsonify({'success': True, 'data': _compose_payload(exam)})


@exam_mgmt_bp.route('/admin/exams/<int:exam_id>/compose/add', methods=['POST'])
@admin_login_required
def exam_compose_add(exam_id):
    """选题入卷：body {question_ids: [id,...]}，追加到卷尾（保持传入顺序）"""
    exam, err = _compose_guard(exam_id)
    if err:
        return err
    data = json_body_or_empty()
    ids = data.get('question_ids')
    if not isinstance(ids, list) or not ids or \
            not all(isinstance(i, int) and i > 0 for i in ids):
        return jsonify({'success': False, 'message': 'question_ids 必须为非空正整数数组'}), 400
    from app.models import Question, ExamQuestion, resequence_exam
    # 去重已入卷的；校验存在性
    existing = {qid for (qid,) in db.session.query(ExamQuestion.question_id)
                .filter(ExamQuestion.exam_id == exam_id,
                        ExamQuestion.question_id.in_(ids)).all()}
    found = {q.id: q for q in Question.query.filter(Question.id.in_(ids)).all()}
    missing = [i for i in ids if i not in found]
    if missing:
        return jsonify({'success': False,
                        'message': f'题目不存在: {missing[:5]}'}), 404
    added = 0
    to_link = []
    # 外链卷互斥（一次性预检，避免循环内逐题查询）：
    # 目标卷已有 link 题 → 只能继续加 link 题；目标卷已有普通题 → 拒加 link
    from app.models import ExamQuestion as _EQ
    has_link = (db.session.query(_EQ.id)
                .join(Question, Question.id == _EQ.question_id)
                .filter(_EQ.exam_id == exam_id,
                        Question.question_type == 'link').first())
    has_normal = (db.session.query(_EQ.id)
                  .join(Question, Question.id == _EQ.question_id)
                  .filter(_EQ.exam_id == exam_id,
                          Question.question_type != 'link').first())
    # 批次整体互斥：只在循环前看存量、循环内不更新时，批量提交
    # [普通题, 外链题] 会把两种题同时挂进同一卷（此后 is_link 判定失效、
    # 外链题在考试页永远 0 分）。先把本批次类型合并进判定。
    _batch_types = {found[qid].question_type for qid in ids
                    if qid in found and qid not in existing}
    if (has_link or 'link' in _batch_types) and \
            (has_normal or any(t != 'link' for t in _batch_types)):
        return jsonify({'success': False,
                        'message': '同一试卷不能同时包含外链题与普通题'}), 400
    # 实操题跨卷共享禁令：PythonAnswer 按（题,学生）建键，同一实操题入多卷
    # 会跨卷串答/追溯改分——python_fill/comprehensive 仅允许归属一套试卷
    from app.models import Question as _Q
    practical_other = {
        qid for (qid,) in db.session.query(_EQ.question_id)
        .join(_Q, _Q.id == _EQ.question_id)
        .filter(_EQ.exam_id != exam_id,
                _Q.question_type.in_(('python_fill', 'comprehensive')))
    }
    for qid in ids:
        if qid in existing:
            continue
        q = found[qid]
        if has_link and q.question_type != 'link':
            return jsonify({'success': False,
                            'message': '该试卷已为外链试卷，只能包含外链题'}), 400
        if q.question_type == 'link':
            if has_normal:
                return jsonify({'success': False,
                                'message': '该试卷已含普通题，不能加入外链题'}), 400
            if has_link:
                continue
        if q.question_type in ('python_fill', 'comprehensive')                 and qid in practical_other:
            return jsonify({'success': False,
                            'message': '实操题（Python填空/综合题）暂不支持多卷共享'
                                       '（答案按题-学生存储，跨卷会串答）；'
                                       '如需复用请在题库复制新题'}), 400
        to_link.append(qid)
    # 校验全部通过后一次性挂载（见 models.link_questions_to_exam_bulk：
    # 逐题挂载在数百题选题下产生数百次 SELECT/flush）
    from app.models import link_questions_to_exam_bulk
    added = link_questions_to_exam_bulk(to_link, exam_id)
    resequence_exam(exam_id)
    db.session.commit()
    _invalidate_exam_list_cache()
    return jsonify({'success': True, 'added': added,
                    'data': _compose_payload(exam)})


@exam_mgmt_bp.route('/admin/exams/<int:exam_id>/compose/remove', methods=['POST'])
@admin_login_required
def exam_compose_remove(exam_id):
    """移出题目：body {question_id}"""
    exam, err = _compose_guard(exam_id)
    if err:
        return err
    data = json_body_or_empty()
    qid = data.get('question_id')
    if not isinstance(qid, int) or qid <= 0:
        return jsonify({'success': False, 'message': 'question_id 无效'}), 400
    from app.models import unlink_question_from_exam, resequence_exam
    removed = unlink_question_from_exam(qid, exam_id)
    if removed:
        resequence_exam(exam_id)
        db.session.commit()
        _invalidate_exam_list_cache()
    return jsonify({'success': True, 'removed': bool(removed),
                    'data': _compose_payload(exam)})


@exam_mgmt_bp.route('/admin/exams/<int:exam_id>/compose/reorder', methods=['POST'])
@admin_login_required
def exam_compose_reorder(exam_id):
    """卷内排序：body {order: [question_id,...]}（全量顺序，组内保持相对次序；
    题型分组序由统一排序规则决定——此处调整的是"组内 position"）"""
    exam, err = _compose_guard(exam_id)
    if err:
        return err
    data = json_body_or_empty()
    order = data.get('order')
    if not isinstance(order, list) or \
            not all(isinstance(i, int) and i > 0 for i in order):
        return jsonify({'success': False, 'message': 'order 必须为题号数组'}), 400
    from app.models import ExamQuestion, resequence_exam
    links = {lk.question_id: lk for lk in
             ExamQuestion.query.filter_by(exam_id=exam_id).all()}
    unknown = [i for i in order if i not in links]
    if unknown:
        return jsonify({'success': False,
                        'message': f'以下题目不在本卷: {unknown[:5]}'}), 400
    # 分组单调校验：order 的题型序列必须非降——展示排序以题型分组为最高
    # 优先级，跨组 order 写入的 position 会被覆盖（按钮"看似无效"）；
    # 手动排序仅允许组内调整，跨组序在此显式拒绝
    from app.models import Question as _Q, QUESTION_TYPE_ORDER
    type_of = dict(db.session.query(_Q.id, _Q.question_type)
                   .filter(_Q.id.in_(order)).all()) if order else {}
    _last_rank = -1
    for _qid in order:
        _rank = QUESTION_TYPE_ORDER.get(type_of.get(_qid), 8)
        if _rank < _last_rank:
            return jsonify({'success': False,
                            'message': '排序需保持题型分组顺序（仅支持组内调整）'}), 400
        _last_rank = _rank
    pos = 0
    for qid in order:
        pos += 1
        links[qid].position = pos
    # 未出现在 order 中的既有题保持相对次序追加在尾部
    for qid, link in sorted(links.items(), key=lambda kv: kv[1].position):
        if qid not in order:
            pos += 1
            link.position = pos
    resequence_exam(exam_id)
    db.session.commit()
    _invalidate_exam_list_cache()
    return jsonify({'success': True, 'data': _compose_payload(exam)})
