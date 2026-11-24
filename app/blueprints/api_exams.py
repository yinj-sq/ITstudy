"""由 API 门面模块加载的领域路由。"""

from flask import current_app, jsonify, request, session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.extensions import cache, db
from app.models import (
    Exam, SubQuestion, Question,
)
from app.decorators import admin_login_required, api_login_required
from app.utils import parse_int
from app.services.scoring_service import has_active_attempt, attempt_is_stale
from app.blueprints.api import (
    api_bp, _invalidate_exam_list_cache,
    _is_exam_available_to_student,
)

# ──────────────────────────────────────────────
#  Exams
# ──────────────────────────────────────────────


@api_bp.route('/exams', methods=['GET'])
@api_login_required
def get_exams():
    """试卷列表（含题目数量；学生视图附带最近一次考试结果）"""
    is_admin_user = session.get('is_admin', False)
    student_id = None if is_admin_user else session.get('student_id')
    # 仅缓存管理员视图（全局数据）。学生视图按学生附加 existing_result，
    # 缓存对象会被 _attach_student_results 原地改写——一旦缓存学生视图，
    # 学生 A 的个人成绩将写进共享缓存对象、泄漏给其他命中缓存的学生。
    # 此前存在 'api:exams:list:student' 死键（只读不写），为杜绝未来误启用
    # 该键造成跨学生数据泄漏，学生视图一律实时查询（列表本身轻量）。
    cached = cache.get('api:exams:list:admin') if is_admin_user else None
    if cached is not None:
        return jsonify(cached)
    query = Exam.query
    if not is_admin_user:
        query = query.filter_by(is_active=True, is_visible=True, is_enabled=True)
    exams = query.order_by(Exam.create_time.desc()).all()
    # 题数：按解耦后的 exam_question 关联表聚合。
    # 只聚合本次可见的试卷 id：此前对 exam_question 全表 GROUP BY，
    # 历史卷/题库增长后每次学生刷新都扫全表（与可见卷数量无关）。
    from app.models import ExamQuestion
    exam_ids = [e.id for e in exams]
    counts = {}
    if exam_ids:
        counts = dict(
            db.session.query(ExamQuestion.exam_id, func.count(ExamQuestion.question_id))
            .filter(ExamQuestion.exam_id.in_(exam_ids))
            .group_by(ExamQuestion.exam_id).all()
        )
    # 外链卷透出（与 SSR exam.html 同口径：卷内最前题目为 link 型 →
    # 列表入口渲染"打开链接"而非进入答题页；此前 SPA 把外链卷渲染成
    # 答题页，学生可提交一张 0 分卷）。仅对含 link 题的卷做最小位置比对。
    link_rows = []
    if exam_ids:
        link_rows = (
            db.session.query(ExamQuestion.exam_id, ExamQuestion.position, Question.content)
            .join(Question, Question.id == ExamQuestion.question_id)
            .filter(ExamQuestion.exam_id.in_(exam_ids),
                    Question.question_type == 'link').all()
        )
    link_url_by_exam = {}
    if link_rows:
        min_pos = dict(
            db.session.query(ExamQuestion.exam_id, func.min(ExamQuestion.position))
            .filter(ExamQuestion.exam_id.in_(exam_ids))
            .group_by(ExamQuestion.exam_id).all()
        )
        for eid, pos, content in link_rows:
            if eid not in link_url_by_exam and min_pos.get(eid) == pos:
                link_url_by_exam[eid] = content or ''
    data = [{
        'id': exam.id,
        'name': exam.name,
        'is_active': exam.is_active,
        # 状态透出：SPA 据此禁用入口 + 渲染管理端控制开关
        'is_collected': exam.is_collected,
        'is_enabled': exam.is_enabled,
        'is_visible': exam.is_visible,
        'allow_view_results': getattr(exam, 'allow_view_results', False),
        'create_time': exam.create_time.strftime('%Y-%m-%d %H:%M:%S') if exam.create_time else None,
        'question_count': counts.get(exam.id, 0),
        'is_link': exam.id in link_url_by_exam,
        'link_url': link_url_by_exam.get(exam.id, ''),
    } for exam in exams]
    result = {'success': True, 'data': data, 'message': 'ok'}
    if is_admin_user:
        cache.set('api:exams:list:admin', result, timeout=60)
    return jsonify(_attach_student_results(data, student_id))


def _attach_student_results(exams_data, student_id):
    """为学生视图的每张试卷附带最近一次考试结果（existing_result），
    供前端 ExamList 显示「已提交」并跳转结果页。个人数据不入全局缓存。
    """
    if not student_id:
        return {'success': True, 'data': exams_data, 'message': 'ok'}
    # 每考试取最新一条成绩：DB 层 DISTINCT ON 替代全量加载后 Python 去重
    # （此前 filter_by(...).all() 加载该学生全部成绩记录，长期使用后
    # 记录无上限增长，列表接口耗时线性增加）
    from sqlalchemy import text as _text
    rows = db.session.execute(
        _text(
            'SELECT DISTINCT ON (exam_id) exam_id, id, total_score, submit_time'
            ' FROM result WHERE student_id = :sid'
            ' ORDER BY exam_id, submit_time DESC NULLS LAST'
        ),
        {'sid': student_id}
    ).fetchall()
    latest_by_exam = {r[0]: r for r in rows}
    for item in exams_data:
        r = latest_by_exam.get(item['id'])
        item['existing_result'] = {
            'id': r[1],
            # 未公布成绩的卷不下发分数（前端显示"已提交"即可）
            'total_score': r[2] if item.get('allow_view_results') else None,
            'submit_time': r[3].strftime('%Y-%m-%d %H:%M:%S') if r[3] else None
        } if r else None
    return {'success': True, 'data': exams_data, 'message': 'ok'}


@api_bp.route('/exams/<int:exam_id>', methods=['GET'])
@api_login_required
def get_exam(exam_id):
    """试卷详情（含题目列表）— 学生和管理员均可访问

    注意：学生访问时不返回正确答案，仅管理员可查看答案。
    """
    exam = db.get_or_404(Exam, exam_id)
    is_admin_user = session.get('is_admin', False)
    from app.models import ExamAttempt
    attempt = None
    live_attempt = True
    if not is_admin_user:
        attempt = ExamAttempt.query.filter_by(
            student_id=session.get('student_id'), exam_id=exam_id).first()
        # 在考学生豁免“可见/开放/启用”开关：管理员误关时已开考学生刷新
        # 不应被 403（否则已作答内容丢失），与 submit_exam 口径一致
        live_attempt = bool(attempt and not attempt_is_stale(exam, attempt))
    if not is_admin_user and not _is_exam_available_to_student(exam) and not live_attempt:
        return jsonify({'success': False, 'message': '试卷不可访问'}), 403

    # 学生已提交：短路返回标记（不加载题目、不创建开考记录），
    # 前端据此跳转结果页，避免已提交学生重复看到答题界面/误以为可重考
    if not is_admin_user:
        from app.models import Result as _Result
        existing = _Result.query.filter_by(
            student_id=session.get('student_id'), exam_id=exam_id).first()
        if existing:
            return jsonify({
                'success': False,
                'already_submitted': True,
                'message': '您已提交过该试卷',
                'result_id': existing.id,
            }), 200

    # 学生开考记录：与 HTML 考试页（online_exam.py）保持一致——
    # 首次进入创建开考时间（刷新不重置），供服务端超时强校验与前端倒计时基准。
    # 无时长卷同样创建开考记录（此前 exam.duration 门把存量无时长卷的
    # attempt 创建整体跳过，submit_exam 对无 attempt 学生一律 403"请先
    # 开始考试"——学生答完全卷提交必 403，答卷丢失）。
    # 收卷后不新建开考记录（防从未开考学生获得 start_time=now 击穿提交
    # 校验）；但收卷时在考的学生已有记录——返回其真实开考时间让 SPA
    # 进入宽限补交流程（收卷轮询 5s 内自动交卷，submit_exam 收卷分支接受），
    # 与 SSR 通道行为一致（此前 SPA 整块跳过 attempt 处理直接拦截，
    # 学生刷新后无法补交已作答内容）。
    exam_start_time = None
    exam_ended = False
    if not is_admin_user:
        from datetime import datetime
        # CSRF 兜底：本端点虽为 GET，但会创建开考记录（写副作用），而全局
        # CSRF 校验只覆盖 POST/PUT/PATCH/DELETE——攻击者可用跨站顶层导航
        # （SameSite=Lax 仍会带会话 Cookie）让受害者在不知情下"开考"，倒计时
        # 提前起跑。浏览器对跨站请求必带 Sec-Fetch-Site: cross-site，据此跳过
        # 写操作（仍返回只读题目数据）；无该头的非浏览器/旧客户端保持原行为，
        # 不影响 SPA 正常调用。
        _cross_site = (request.headers.get('Sec-Fetch-Site', '') or '').strip().lower() == 'cross-site'
        if attempt and attempt_is_stale(exam, attempt):
            # 超时残留开考记录（弃考/断网超过 时长+宽限）：提交通道已被
            # submit_exam 关闭，标记结束态让 SPA 直接提示，而非渲染
            # 倒计时归零→自动交卷→403 报错弹窗的循环
            exam_ended = True
        elif not attempt and not exam.is_collected and not _cross_site:
            try:
                attempt = ExamAttempt(
                    student_id=session.get('student_id'), exam_id=exam_id,
                    start_time=datetime.now())
                db.session.add(attempt)
                db.session.commit()
            except IntegrityError:
                # 并发开考竞态：另一请求已创建开考记录，回滚后复用已有记录
                db.session.rollback()
                attempt = ExamAttempt.query.filter_by(
                    student_id=session.get('student_id'), exam_id=exam_id).first()
        if attempt and not exam_ended:
            exam_start_time = attempt.start_time.timestamp()

    # 卷内题目：题型分组序（单选→多选→判断→填空→简答→Python→综合），seq=全局题号
    from app.models import exam_questions_flat, QUESTION_TYPE_ORDER
    questions = exam_questions_flat(exam_id)
    # 一次性聚合所有题目的子题数量，消除 N+1
    q_ids = [q.id for q in questions]
    sub_counts = {}
    if q_ids:
        sub_counts = dict(
            db.session.query(SubQuestion.question_id, func.count(SubQuestion.id))
            .filter(SubQuestion.question_id.in_(q_ids))
            .group_by(SubQuestion.question_id).all()
        )
    # 批量加载综合题的小题（考试页作答需要完整子题列表）
    comprehensive_ids = [q.id for q in questions if q.question_type == 'comprehensive']
    subs_by_q = {}
    if comprehensive_ids:
        for s in SubQuestion.query.filter(
                SubQuestion.question_id.in_(comprehensive_ids)
        ).order_by(SubQuestion.order).all():
            subs_by_q.setdefault(s.question_id, []).append(s)
    questions_data = [{
        'id': q.id,
        'seq': seq,  # 全局题号（题型分组序，跨题型连续 1..N）
        'type_order': QUESTION_TYPE_ORDER.get(q.question_type, 8),
        'question_type': q.question_type,
        'content': q.content,
        'options': q.options,
        'answer': q.answer if is_admin_user else None,  # 仅管理员可见答案
        'score': q.score,
        'image_url': q.image_url,
        # 综合题背景与选项/子题图片：SSR 考试页本就向学生渲染，
        # SPA 必须同口径下发，否则同一试卷两种通道看到的信息不一致
        'background': q.background,
        'image_options': q.image_options_dict,
        # 综合题“结尾说明/参考代码”：出题页明示应显示在所有子题之后，
        # 此前仅管理端可见、考试页从不渲染（功能缺失）
        'footer_content': q.footer_content,
        'created_at': q.created_at.strftime('%Y-%m-%d %H:%M:%S') if q.created_at else None,
        'sub_count': sub_counts.get(q.id, 0),
        'sub_questions': [{
            'id': sub.id,
            'question_type': sub.question_type,
            'content': sub.content,
            'options': sub.options,
            'answer': sub.answer if is_admin_user else None,
            'score': sub.score,
            'order': sub.order,
            'image_url': sub.image_url,
            'image_options': sub.image_options_dict
        } for sub in subs_by_q.get(q.id, [])]
    } for seq, q in enumerate(questions, 1)]
    return jsonify({
        'success': True,
        'data': {
            'id': exam.id,
            'name': exam.name,
            'is_active': exam.is_active,
            'is_collected': exam.is_collected,
            'is_enabled': exam.is_enabled,
            'duration': exam.duration,
            'exam_start_time': exam_start_time,
            'exam_ended': exam_ended,
            'create_time': exam.create_time.strftime('%Y-%m-%d %H:%M:%S') if exam.create_time else None,
            'questions': questions_data
        },
        'message': 'ok'
    })


@api_bp.route('/exams', methods=['POST'])
@admin_login_required
def create_exam():
    """创建试卷"""
    data = request.get_json(force=True, silent=True) or request.form
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'success': False, 'message': '试卷名称不能为空'}), 400
    # 与 web 版（exam_management）保持一致：支持科目与时长。
    # duration 必填：没有时长的试卷跳过服务端超时强校验（submit_exam 的
    # 5 分钟宽限判定依赖 duration），学生可绕过前端倒计时无限时作答
    subject_id = parse_int(data.get('subject_id'))
    duration_raw = data.get('duration')
    try:
        duration = int(duration_raw) if duration_raw not in (None, '') else None
        if duration is None or duration < 1:
            return jsonify({'success': False, 'message': '考试时长必须为正整数'}), 400
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': '考试时长格式无效'}), 400
    # 试卷名称全局唯一（批量导入按卷命名也依赖此约定）
    if Exam.query.filter_by(name=name).first():
        return jsonify({'success': False, 'message': '试卷名称已存在，请使用其他名称'}), 400
    try:
        exam = Exam(name=name, is_active=True, subject_id=subject_id, duration=duration)
        db.session.add(exam)
        db.session.commit()
        _invalidate_exam_list_cache()
        current_app.logger.info(f"API 创建试卷成功: {name}")
        return jsonify({
            'success': True,
            'data': {'id': exam.id, 'name': exam.name},
            'message': '试卷创建成功'
        })
    except IntegrityError:
        # 数据库唯一约束兜底：并发创建同名卷时友好提示而非 500
        db.session.rollback()
        return jsonify({'success': False, 'message': '试卷名称已存在，请使用其他名称'}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"API 创建试卷失败: {str(e)}")
        return jsonify({'success': False, 'message': '创建试卷失败'}), 500


@api_bp.route('/exams/<int:exam_id>', methods=['PUT'])
@admin_login_required
def update_exam(exam_id):
    """编辑试卷"""
    exam = db.get_or_404(Exam, exam_id)
    data = request.get_json(force=True, silent=True) or request.form
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'success': False, 'message': '试卷名称不能为空'}), 400
    # 改名重名校验（排除自身）
    dup = Exam.query.filter(Exam.name == name, Exam.id != exam_id).first()
    if dup:
        return jsonify({'success': False, 'message': '试卷名称已存在，请使用其他名称'}), 400
    try:
        exam.name = name
        if 'is_active' in data:
            exam.is_active = bool(data['is_active'])
        # duration 可选更新（SPA 编辑）：缺省保持原值，不覆盖存量设置
        if 'duration' in data and data.get('duration') not in (None, ''):
            try:
                duration_int = int(data['duration'])
            except (TypeError, ValueError):
                return jsonify({'success': False, 'message': '考试时长格式无效'}), 400
            if duration_int < 1:
                return jsonify({'success': False, 'message': '考试时长必须为正整数'}), 400
            # 在考保护：提交/超时按当前 duration 计算，考试中调小时长会
            # 直接把在考学生判超时（调大则静默加时）
            if duration_int != exam.duration and has_active_attempt(exam):
                return jsonify({'success': False,
                                'message': '考试进行中，不能修改考试时长'}), 409
            exam.duration = duration_int
        db.session.commit()
        _invalidate_exam_list_cache()
        current_app.logger.info(f"API 修改试卷成功: {exam_id} -> {name}")
        return jsonify({
            'success': True,
            'data': {'id': exam.id, 'name': exam.name, 'is_active': exam.is_active},
            'message': '试卷修改成功'
        })
    except IntegrityError:
        # 数据库唯一约束兜底：并发改名撞名时友好提示
        db.session.rollback()
        return jsonify({'success': False, 'message': '试卷名称已存在，请使用其他名称'}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"API 修改试卷失败: {str(e)}")
        return jsonify({'success': False, 'message': '修改试卷失败'}), 500


@api_bp.route('/exams/<int:exam_id>', methods=['DELETE'])
@admin_login_required
def delete_exam(exam_id):
    """删除试卷（有成绩则拒绝；题库解耦后题目不阻碍删卷，关联行清理）"""
    from app.models import Result, ExamAttempt, ExamQuestion
    exam = db.get_or_404(Exam, exam_id)
    try:
        # 前置检查先于任何破坏性语句（与 SSR 版 exam_management.delete_exam
        # 同口径）：此前先执行关联清理 SQL 再检查，409 路径无 rollback、
        # 依赖 teardown 隐式回滚并持有行锁——易在后续改动中落库半破坏状态
        result_count = Result.query.filter_by(exam_id=exam_id).count()
        if result_count > 0:
            # 有成绩记录的试卷直接删除会触发外键 IntegrityError，
            # 提前检查并给出明确提示（需先清空成绩）
            return jsonify({
                'success': False,
                'message': f'无法删除：该试卷已有 {result_count} 条成绩记录，请先删除成绩'
            }), 409
        # 在考拦截：存在"进行中"（未超时）开考记录 = 考试进行中，删卷会使
        # 在考学生提交通道失效。超时残留记录（弃考超过 时长+宽限）不阻断
        # ——其提交通道已被服务端时长校验关闭，下方清理语句一并删除
        if has_active_attempt(exam):
            return jsonify({'success': False,
                            'message': '无法删除：该试卷有学生正在考试，'
                                       '请先收卷或等待交卷'}), 409
        # 题库/试卷解耦：删卷不再被题目阻碍（exam_question 关联行随删卷清理，
        # 题目本体保留在题库可继续复用；来源卷引用置空）
        from sqlalchemy import text as _sql_text
        db.session.query(ExamQuestion).filter_by(exam_id=exam_id).delete(
            synchronize_session=False)
        db.session.execute(
            _sql_text('UPDATE question SET exam_id = NULL WHERE exam_id = :e'),
            {'e': exam_id})
        # 清理残留开考记录（瞬态数据，删除后学生需重新开考）
        ExamAttempt.query.filter_by(exam_id=exam_id).delete(synchronize_session=False)
        db.session.delete(exam)
        db.session.commit()
        _invalidate_exam_list_cache()
        current_app.logger.info(f"API 删除试卷成功: {exam_id} {exam.name}")
        return jsonify({'success': True, 'message': '试卷删除成功'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"API 删除试卷失败: {str(e)}")
        return jsonify({'success': False, 'message': '删除试卷失败'}), 500

