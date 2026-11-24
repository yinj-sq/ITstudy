"""教师批改蓝图 — 开放式填空题人工评分"""
from flask import Blueprint, request, render_template, redirect, url_for, session, flash
from flask import current_app
from datetime import datetime
from app.extensions import db
from app.models import Result, Exam, Question, SubQuestion, Student
from app.decorators import teacher_login_required
from app.utils import parse_int
import json
import math

grading_bp = Blueprint('grading', __name__, url_prefix='/admin/grading')


def _teacher_visible_student_ids():
    """教师（非管理员）数据边界：仅可批改当前上课班级学生的成绩。

    返回可见 student_id 列表；管理员返回 None（全部可见）。
    当前上课班级未设置时返回空列表（fail-closed，教师看不到任何成绩）。
    """
    if session.get('is_admin'):
        return None
    from app.services.resource_access import teacher_class_ids
    class_ids = teacher_class_ids(session.get('teacher_id'))
    if not class_ids:
        return []
    return [sid for (sid,) in Student.query.with_entities(Student.id).filter(
        Student.class_id.in_(class_ids)).all()]


def _teacher_can_manage_result(result):
    """教师数据边界检查（成绩记录级）：管理员放行；教师仅限本班学生成绩。"""
    if session.get('is_admin'):
        return True
    visible = _teacher_visible_student_ids()
    return visible is not None and result.student_id in visible


def _grading_nav_query(exam_id):
    """批改导航（上一名/下一名）的基础查询 —— 必须与 grading_students
    列表同口径带上教师班级边界。

    列表只列本班学生，但导航此前按 exam_id 全卷检索：多班共用一套试卷时，
    教师点"保存并下一个"会被带到外班学生的批改页，随即被 grade_student 的
    边界检查弹回列表（"无权查看该学生的答卷"），连续批改在此断流——
    教师只能退回列表逐个点，且误以为系统出错。
    """
    query = Result.query.filter_by(exam_id=exam_id).filter(
        Result.grading_status.in_(
            ['pending_review', 'auto_graded', 'fully_graded']))
    visible_ids = _teacher_visible_student_ids()
    if visible_ids is not None:
        query = query.filter(Result.student_id.in_(visible_ids))
    return query


@grading_bp.route('')
@teacher_login_required
def grading_list():
    """列出试卷列表（含各状态成绩统计），分页渲染"""
    # 一次聚合查询替代 3 次全表加载：{exam_id: {status: count}}
    from sqlalchemy import func as _func
    from app.utils import paginate_query
    pagination = paginate_query(
        Exam.query.order_by(Exam.create_time.desc()),
        default_per_page=20, max_per_page=100
    )
    page_exams = pagination.items
    exam_ids = [e.id for e in page_exams]
    counts_by_exam = {}
    if exam_ids:
        agg_q = db.session.query(
            Result.exam_id, Result.grading_status, _func.count(Result.id)
        ).filter(Result.exam_id.in_(exam_ids))
        # 教师数据边界：与批改学生列表同口径，只统计当前上课班级学生
        # （此前全卷计数，教师看到"待批 30 人"点进去却只有本班 5 人）
        visible_ids = _teacher_visible_student_ids()
        if visible_ids is not None:
            agg_q = agg_q.filter(Result.student_id.in_(visible_ids))
        agg_rows = agg_q.group_by(Result.exam_id, Result.grading_status).all()
        for exam_id, status, cnt in agg_rows:
            counts_by_exam.setdefault(exam_id, {})[status] = cnt

    exam_stats = {}
    for exam in page_exams:
        counts = counts_by_exam.get(exam.id, {})
        exam_stats[exam.id] = {
            'exam': exam,
            'pending': counts.get('pending_review', 0),
            'auto_graded': counts.get('auto_graded', 0),
            'graded': counts.get('fully_graded', 0)
        }

    return render_template('admin_grading.html',
                           mode='exam_list',
                           exam_stats=exam_stats,
                           pagination=pagination)


@grading_bp.route('/<int:exam_id>')
@teacher_login_required
def grading_students(exam_id):
    """列出某试卷的待批改/已批改/自动批改学生"""
    exam = db.get_or_404(Exam, exam_id)
    status_filter = request.args.get('status', 'pending')

    query = Result.query.filter_by(exam_id=exam_id)
    # 教师数据边界：仅显示当前上课班级学生的成绩
    visible_ids = _teacher_visible_student_ids()
    if visible_ids is not None:
        query = query.filter(Result.student_id.in_(visible_ids))
    if status_filter == 'pending':
        query = query.filter_by(grading_status='pending_review')
    elif status_filter == 'auto_graded':
        query = query.filter_by(grading_status='auto_graded')
    elif status_filter == 'graded':
        query = query.filter_by(grading_status='fully_graded')
    else:
        query = query.filter(Result.grading_status.in_(['pending_review', 'auto_graded', 'fully_graded']))

    # 分页渲染（成绩可能上千条，避免单页全量加载）
    from app.utils import paginate_query
    pagination = paginate_query(
        query.order_by(Result.submit_time.asc()),
        default_per_page=20, max_per_page=100
    )
    results = pagination.items

    # 预加载学生信息
    student_ids = [r.student_id for r in results]
    students_map = {}
    if student_ids:
        from sqlalchemy.orm import joinedload
        students_list = Student.query.options(
            joinedload(Student.class_)  # 模板班级列回退 class_.name，避免每行 N+1
        ).filter(Student.id.in_(set(student_ids))).all()
        students_map = {s.id: s for s in students_list}

    result_data = []
    for r in results:
        student = students_map.get(r.student_id)
        # 统计已批改 / 总数
        manual_scores = json.loads(r.manual_scores) if r.manual_scores else {}
        total_oe = len(manual_scores)
        graded_oe = sum(1 for v in manual_scores.values() if v.get('manual_score') is not None)

        result_data.append({
            'result': r,
            'student': student,
            'total_oe': total_oe,
            'graded_oe': graded_oe
        })

    # 统计（一次聚合替代 3 次独立 count）
    from sqlalchemy import func as _func
    agg_rows = db.session.query(
        Result.grading_status, _func.count(Result.id)
    ).filter_by(exam_id=exam_id)
    if visible_ids is not None:
        agg_rows = agg_rows.filter(Result.student_id.in_(visible_ids))
    agg_rows = agg_rows.group_by(Result.grading_status).all()
    counts = dict(agg_rows)
    pending_count = counts.get('pending_review', 0)
    auto_graded_count = counts.get('auto_graded', 0)
    graded_count = counts.get('fully_graded', 0)

    return render_template('admin_grading.html',
                           mode='student_list',
                           exam=exam,
                           result_data=result_data,
                           pending_count=pending_count,
                           auto_graded_count=auto_graded_count,
                           graded_count=graded_count,
                           status_filter=status_filter,
                           pagination=pagination)


@grading_bp.route('/<int:exam_id>/<int:result_id>')
@teacher_login_required
def grade_student(exam_id, result_id):
    """批改某学生 — 仅显示开放式试题"""
    exam = db.get_or_404(Exam, exam_id)
    result = db.get_or_404(Result, result_id)

    if result.exam_id != exam_id:
        flash('数据不匹配', 'danger')
        return redirect(url_for('grading.grading_list'))

    if not _teacher_can_manage_result(result):
        flash('无权查看该学生的答卷', 'danger')
        return redirect(url_for('grading.grading_students', exam_id=exam_id))

    student = db.session.get(Student, result.student_id)
    manual_scores = json.loads(result.manual_scores) if result.manual_scores else {}

    if not manual_scores:
        flash('该学生没有需要批改的开放式试题', 'warning')
        return redirect(url_for('grading.grading_students', exam_id=exam_id))

    # 获取开放式试题详情（仅查询 manual_scores 中引用的题目）
    sub_keys = [k for k in manual_scores.keys() if k.startswith('sub_')]
    q_keys = [k for k in manual_scores.keys() if not k.startswith('sub_')]
    sub_ids = []
    for k in sub_keys:
        try:
            sub_ids.append(int(k.replace('sub_', '')))
        except ValueError:
            pass
    q_ids = []
    for k in q_keys:
        try:
            q_ids.append(int(k))
        except ValueError:
            pass
    # 一次性批量加载所有 SubQuestion / Question
    subs_by_id = {s.id: s for s in SubQuestion.query.filter(SubQuestion.id.in_(sub_ids)).all()} if sub_ids else {}
    qs_by_id = {q.id: q for q in Question.query.filter(Question.id.in_(q_ids)).all()} if q_ids else {}

    questions_detail = {}
    for key, info in manual_scores.items():
        if key.startswith('sub_'):
            try:
                sub_q = subs_by_id.get(int(key.replace('sub_', '')))
            except ValueError:
                sub_q = None
            if sub_q:
                questions_detail[key] = {
                    'content': sub_q.content,
                    'score': sub_q.score,
                    'type': sub_q.question_type,
                    'is_sub': True
                }
        else:
            try:
                q = qs_by_id.get(int(key))
            except ValueError:
                q = None
            if q:
                questions_detail[key] = {
                    'content': q.content,
                    'score': q.score,
                    'type': q.question_type,
                    'is_sub': False
                }

    # 获取上/下一个学生的导航
    # 列裁剪：仅需 id 用于定位相邻项——此前加载每行 answers/scores/
    # manual_scores 三个大 Text 答卷 JSON（500 人 × 10-30KB ≈ 5-15MB/页），
    # 而批改是逐人连续操作
    all_pending_q = Result.query.with_entities(
        Result.id
    ).filter_by(
        exam_id=exam_id
    ).filter(
        Result.grading_status.in_(['pending_review', 'auto_graded', 'fully_graded'])
    )
    # 教师数据边界：导航列表同样仅限本班学生（管理员不受限）
    visible_ids = _teacher_visible_student_ids()
    if visible_ids is not None:
        all_pending_q = all_pending_q.filter(Result.student_id.in_(visible_ids))
    all_pending = all_pending_q.order_by(Result.submit_time.asc()).all()

    current_idx = next((i for i, r in enumerate(all_pending) if r.id == result_id), -1)
    prev_result = all_pending[current_idx - 1] if current_idx > 0 else None
    next_result = all_pending[current_idx + 1] if current_idx < len(all_pending) - 1 else None

    return render_template('admin_grading.html',
                           mode='grade',
                           exam=exam,
                           result=result,
                           student=student,
                           manual_scores=manual_scores,
                           questions_detail=questions_detail,
                           prev_result=prev_result,
                           next_result=next_result,
                           current_idx=current_idx,
                           total_count=len(all_pending))


@grading_bp.route('/<int:exam_id>/<int:result_id>', methods=['POST'])
@teacher_login_required
def submit_grading(exam_id, result_id):
    """提交批改分数"""
    result = db.get_or_404(Result, result_id)
    if result.exam_id != exam_id:
        flash('数据不匹配', 'danger')
        return redirect(url_for('grading.grading_list'))
    # 教师数据边界：仅可批改当前上课班级学生的成绩
    if not _teacher_can_manage_result(result):
        flash('无权批改该学生成绩（仅限当前上课班级）', 'danger')
        return redirect(url_for('grading.grading_students', exam_id=exam_id))

    manual_scores = json.loads(result.manual_scores) if result.manual_scores else {}
    scores = json.loads(result.scores) if result.scores else {}

    # 读取教师提交的分数
    all_graded = True
    for key, info in manual_scores.items():
        field_name = f'score_{key}'
        submitted_score = request.form.get(field_name, '').strip()
        if submitted_score != '':
            try:
                score_val = float(submitted_score)
                # 非有限数（NaN/Infinity）拒绝：写入后会使总分计算产生 NaN 并污染成绩统计
                if not math.isfinite(score_val):
                    raise ValueError('分数非有限数')
                max_score = info['max_score']
                if score_val < 0:
                    score_val = 0
                if score_val > max_score:
                    score_val = max_score
                info['manual_score'] = score_val
                scores[key] = score_val
            except ValueError:
                all_graded = False
                flash(f'题目 {key} 的分数格式无效', 'warning')
        else:
            all_graded = False

    # 检查是否全部批改完成
    for info in manual_scores.values():
        if info.get('manual_score') is None:
            all_graded = False
            break

    # 综合题：用各子题（sub_）的当前分数重算其父题聚合分。
    # 否则教师批改开放式子题后，父题聚合分仍是提交时的旧值（含未批改子题记0分），
    # 而下方总分重算只累加非 sub_ 键，会漏计刚批改的子题分数。
    sub_keys = [k for k in scores if k.startswith('sub_')]
    if sub_keys:
        sub_ids = [int(k[4:]) for k in sub_keys if k[4:].isdigit()]
        parent_of = {
            s.id: s.question_id
            for s in SubQuestion.query.filter(SubQuestion.id.in_(sub_ids)).all()
        } if sub_ids else {}
        parent_totals = {}
        for k in sub_keys:
            sid = k[4:]
            if not sid.isdigit():
                continue
            pid = parent_of.get(int(sid))
            if pid is None:
                continue
            try:
                parent_totals[pid] = parent_totals.get(pid, 0.0) + float(scores[k] or 0)
            except (TypeError, ValueError):
                pass
        for pid, tot in parent_totals.items():
            scores[str(pid)] = round(tot, 2)

    # 重算总分：排除 sub_ 前缀的子题分数，避免双重计数
    # （sub_ 分数已合入其所属综合题的总分中）。
    # 跳过无法转数值的残留键（历史/异常数据），避免 500——
    # 此路径处理的是存量成绩，脏数据不应阻断整条批改链路。
    def _to_score(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    result.total_score = sum(
        _to_score(v) for k, v in scores.items() if not k.startswith('sub_')
    )

    if all_graded:
        result.grading_status = 'fully_graded'
        # 管理员账号无数字 ID（基于账号文件认证），用 0 标识；
        # 教师批改时使用 teacher_id（本路由当前仅管理员可访问，预留兼容）
        result.graded_by = session.get('teacher_id') or (0 if session.get('is_admin') else None)
        result.graded_at = datetime.now()

    # 保存清理后的数据
    clean_manual = {}
    for key, info in manual_scores.items():
        clean_manual[key] = {
            'max_score': info['max_score'],
            'student_answer': info['student_answer'],
            'manual_score': info['manual_score'],
            'question_type': info.get('question_type', 'fill'),
            'content': info.get('content', ''),
            'auto_graded': info.get('auto_graded', False)
        }

    result.manual_scores = json.dumps(clean_manual)
    result.scores = json.dumps(scores)

    try:
        db.session.commit()
        # 批改改分后换代趋势缓存：此前漏标，SPA /api/trend 60s TTL 内仍展示
        # 批改前的分数分布/均分，与 SSR admin_trend（无缓存）口径分叉
        from app.services.scoring_service import bump_trend_cache
        bump_trend_cache(exam_id)
        if all_graded:
            flash('所有开放式试题已批改完成，总分已更新', 'success')
        else:
            flash('分数已保存', 'success')
    except Exception:
        db.session.rollback()
        flash('保存失败', 'danger')
        return redirect(url_for('grading.grade_student', exam_id=exam_id, result_id=result_id))

    # 跳转到下一个学生或返回列表
    action = request.form.get('action', 'next')
    if action == 'save':
        return redirect(url_for('grading.grade_student', exam_id=exam_id, result_id=result_id))

    # 查找下一个待批改学生（同样受教师班级边界约束，见 _grading_nav_query）
    next_result = _grading_nav_query(exam_id).filter(
        Result.submit_time > result.submit_time
    ).order_by(Result.submit_time.asc()).first()

    if next_result:
        return redirect(url_for('grading.grade_student', exam_id=exam_id, result_id=next_result.id))
    else:
        flash('所有学生已批改完毕', 'success')
        return redirect(url_for('grading.grading_students', exam_id=exam_id))


@grading_bp.route('/<int:exam_id>/<int:result_id>/prev')
@teacher_login_required
def prev_student(exam_id, result_id):
    """退回上一名学生（二次批改）"""
    result = db.get_or_404(Result, result_id)
    if not _teacher_can_manage_result(result):
        flash('无权操作该学生成绩', 'danger')
        return redirect(url_for('grading.grading_students', exam_id=exam_id))
    # 与 grade_student/submit_grading/delete_grading_result 同口径：成绩记录
    # 必须属于该试卷，否则导航会按 exam_id 检索到不相干的相邻成绩
    if result.exam_id != exam_id:
        flash('成绩记录与试卷不匹配', 'danger')
        return redirect(url_for('grading.grading_list'))

    prev_result = _grading_nav_query(exam_id).filter(
        Result.submit_time < result.submit_time
    ).order_by(Result.submit_time.desc()).first()

    if prev_result:
        return redirect(url_for('grading.grade_student', exam_id=exam_id, result_id=prev_result.id))
    else:
        flash('已是第一个学生，无法继续退回', 'info')
        return redirect(url_for('grading.grade_student', exam_id=exam_id, result_id=result_id))


@grading_bp.route('/<int:exam_id>/<int:result_id>/delete', methods=['POST'])
@teacher_login_required
def delete_grading_result(exam_id, result_id):
    """删除单个批改成绩"""
    from app.services.scoring_service import delete_exam_result
    result = db.get_or_404(Result, result_id)
    if not _teacher_can_manage_result(result):
        flash('无权操作该学生成绩', 'danger')
        return redirect(url_for('grading.grading_students', exam_id=exam_id))
    if result.exam_id != exam_id:
        flash('成绩记录与试卷不匹配', 'danger')
        return redirect(url_for('grading.grading_list'))

    try:
        from app.services.scoring_service import finalize_exam_result_deletion
        info = delete_exam_result(result, log_action='批改中心删除成绩')
        db.session.commit()
        # 趋势缓存换代 + 磁盘答案文件清理：commit 成功后执行
        finalize_exam_result_deletion(info)
        current_app.logger.info(
            f'批改中心: 管理员删除成绩 result_id={result_id} '
            f'学生={info["student_name"]} 试卷={exam_id}'
        )
        flash(f'已删除 {info["student_name"]} 的成绩记录', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'批改中心删除成绩失败: {e}', exc_info=True)
        flash('删除成绩失败', 'danger')
    return redirect(url_for('grading.grading_students', exam_id=exam_id))


@grading_bp.route('/<int:exam_id>/batch_delete', methods=['POST'])
@teacher_login_required
def batch_delete_grading_results(exam_id):
    """批量删除批改成绩"""
    from app.services.scoring_service import delete_exam_result
    import json
    ids_str = request.form.get('ids', '')
    if not ids_str:
        flash('未选择任何记录', 'warning')
        return redirect(url_for('grading.grading_students', exam_id=exam_id))

    try:
        ids = json.loads(ids_str)
    except Exception:
        flash('参数格式错误', 'danger')
        return redirect(url_for('grading.grading_students', exam_id=exam_id))

    if not ids:
        flash('未选择任何记录', 'warning')
        return redirect(url_for('grading.grading_students', exam_id=exam_id))

    # 教师数据边界：批量删除仅限当前上课班级学生的成绩（管理员全部放行）
    if not session.get('is_admin'):
        visible = set(_teacher_visible_student_ids() or [])
        rids = [int(x) for x in ids if isinstance(x, (int, float)) and str(x).isdigit()]
        owned = {rid for (rid,) in Result.query.with_entities(
            Result.id).filter(Result.id.in_(rids),
                              Result.student_id.in_(visible)).all()}
        ids = [x for x in rids if x in owned]
        if not ids:
            flash('无可删除的本班成绩记录', 'warning')
            return redirect(url_for('grading.grading_students', exam_id=exam_id))

    deleted = 0
    deleted_infos = []
    for rid in ids:
        rid_int = parse_int(rid)
        if rid_int is None:
            continue
        result = db.session.get(Result, rid_int)
        if result and result.exam_id == exam_id:
            deleted_infos.append(
                delete_exam_result(result, log_action='批改中心批量删除成绩'))
            deleted += 1

    try:
        db.session.commit()
        # 趋势缓存换代 + 磁盘答案文件清理：commit 成功后统一执行
        if deleted_infos:
            from app.services.scoring_service import finalize_exam_result_deletion
            finalize_exam_result_deletion(*deleted_infos)
        current_app.logger.info(f'批改中心: 管理员批量删除成绩 exam_id={exam_id} ids={ids} 共{deleted}条')
        flash(f'已删除 {deleted} 条成绩记录', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'批改中心批量删除成绩失败: {e}', exc_info=True)
        flash('批量删除成绩失败', 'danger')
    return redirect(url_for('grading.grading_students', exam_id=exam_id))
