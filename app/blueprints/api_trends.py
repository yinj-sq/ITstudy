"""由 API 门面模块加载的领域路由。"""
import json

from flask import jsonify, request, session

from app.extensions import db

from app.models import (
    Exam, Result, Student,
)
from app.decorators import admin_login_required, api_login_required
from app.blueprints.api import (
    api_bp,
)

# ──────────────────────────────────────────────
#  Trends
# ──────────────────────────────────────────────


@api_bp.route('/trend/<int:exam_id>', methods=['GET'])
@admin_login_required
def get_exam_trend(exam_id):
    """成绩趋势数据（复用 scores.py admin_trend 统计逻辑）

    性能：全量 Result（含大 TEXT 列）+ 全量 Question 读取后 Python 聚合，
    管理端每次筛选都全量重算。TTL 60s 缓存（key 含 exam_id + class_filter），
    连点筛选与多教师同卷查看不再重复全量计算。
    """
    exam = db.get_or_404(Exam, exam_id)
    class_filter = request.args.get('class_filter', '')
    from app.extensions import cache as _tr_cache
    from app.services.scoring_service import trend_cache_epoch
    # key 含换代号：成绩提交/删除（bump_trend_cache）后旧 key 立即失效，
    # 60s TTL 内不再读到删除前的旧趋势（SimpleCache 无枚举删除）
    cache_key = (f'api:trend:{exam_id}:{trend_cache_epoch(exam_id)}:'
                 f'{class_filter or "all"}')
    cached = _tr_cache.get(cache_key)
    if cached is not None:
        return jsonify({'success': True, 'data': cached, 'message': ''})
    # 列裁剪：仅加载统计所需列（id/student_id/total_score/submit_time/scores），
    # 此前全列加载会把 answers/manual_scores 两个大 TEXT 列一并取出
    # （500 人 × 10-30KB ≈ 5-15MB/请求）
    results = Result.query.with_entities(
        Result.id, Result.student_id, Result.total_score,
        Result.submit_time, Result.scores
    ).filter_by(exam_id=exam_id).order_by(Result.submit_time.desc()).all()

    if not results:
        trend_data = {
            'exam': {'id': exam.id, 'name': exam.name},
            'distribution': [],
            'class_stats': {},
            'student_details': [],
            'question_stats': [],
            'available_classes': []
        }
        _tr_cache.set(cache_key, trend_data, timeout=60)
        return jsonify({'success': True, 'data': trend_data, 'message': '暂无数据'})

    # 分数段分布
    score_bins = [0, 60, 70, 80, 90, 100]
    dist = [0] * 5

    class_stats = {}
    from app.models import exam_questions_flat
    questions = exam_questions_flat(exam_id)
    available_classes = set()
    student_details = []
    q_stats = []

    # 初始化问题统计
    for q in questions:
        q_stat = {
            'id': q.id,
            'type': q.question_type,
            'content': q.content,
            'correct_count': 0,
            'attempt_count': 0,
            'correct_rate': 0
        }
        q_stats.append(q_stat)

    # 批量加载学生，消除 N+1
    student_ids = {r.student_id for r in results}
    students_by_id = {
        s.id: s for s in Student.query.filter(Student.id.in_(student_ids)).all()
    } if student_ids else {}
    # python_fill 作答判定：Result.scores 对 python_fill 无条件写键（未作答
    # 也写 0），attempt 必须以 PythonAnswer 记录存在为准（与 HTML 趋势页/
    # Excel 导出共用 load_python_attempt_set，口径一致）
    from app.blueprints.scores import load_python_attempt_set as _py_attempts
    python_attempts = _py_attempts(exam_id)

    for result in results:
        student = students_by_id.get(result.student_id)
        if not student:
            continue

        class_name = student.student_class or '未分班'
        available_classes.add(class_name)
        if class_filter and class_name != class_filter:
            continue

        score = result.total_score or 0
        for i, threshold in enumerate(score_bins[1:]):
            if score < threshold:
                dist[i] += 1
                break
            elif i == 4:
                dist[i] += 1

        if class_name not in class_stats:
            class_stats[class_name] = {
                'count': 0, 'total': 0, 'average': 0,
                'max': score, 'min': score
            }
        cs = class_stats[class_name]
        cs['count'] += 1
        cs['total'] += score
        cs['max'] = max(cs['max'], score)
        cs['min'] = min(cs['min'], score)
        cs['average'] = round(cs['total'] / cs['count'], 2)

        student_item = {
            'student_id': student.id,
            'name': student.name,
            'class': class_name,
            'total_score': score,
            'submit_time': result.submit_time.strftime('%Y-%m-%d %H:%M:%S') if result.submit_time else None,
            'result_id': result.id
        }
        student_details.append(student_item)

        # 问题正确率统计
        try:
            scores_data = json.loads(result.scores) if result.scores else {}
            for i, q in enumerate(questions):
                qid_str = str(q.id)
                if qid_str in scores_data:
                    if q.question_type == 'python_fill' and \
                            (result.student_id, q.id) not in python_attempts:
                        continue  # 未作答：scores 键为交卷流程无条件写入的 0 分
                    q_score = float(scores_data[qid_str])
                    q_stats[i]['attempt_count'] += 1
                    if abs(q_score - float(q.score)) < 0.01:
                        q_stats[i]['correct_count'] += 1
        except (json.JSONDecodeError, ValueError):
            pass

    for q_stat in q_stats:
        if q_stat['attempt_count'] > 0:
            q_stat['correct_rate'] = round(
                q_stat['correct_count'] / q_stat['attempt_count'] * 100, 2
            )

    trend_data = {
        'exam': {'id': exam.id, 'name': exam.name},
        # 分段标签与 app/blueprints/scores.py 的 admin_trend 同口径（左闭右开
        # [0,60)/[60,70)/…；此前两段都叫"优秀"且区间文案重叠，SPA 与 SSR 分叉）
        'distribution': [{'label': '不及格(<60)', 'count': dist[0]},
                         {'label': '及格(60-69)', 'count': dist[1]},
                         {'label': '良好(70-79)', 'count': dist[2]},
                         {'label': '优秀(80-89)', 'count': dist[3]},
                         {'label': '优秀(90-100)', 'count': dist[4]}],
        'class_stats': class_stats,
        'student_details': student_details,
        'question_stats': q_stats,
        'available_classes': sorted(available_classes)
    }
    _tr_cache.set(cache_key, trend_data, timeout=60)
    return jsonify({'success': True, 'data': trend_data, 'message': 'ok'})


@api_bp.route('/trend/student/me', methods=['GET'])
@api_login_required
def get_my_trend():
    """当前登录学生的个人成绩趋势"""
    student_id = session.get('student_id')
    if not student_id:
        return jsonify({'success': False, 'message': '未登录'}), 401
    return _build_student_trend(student_id)


@api_bp.route('/trend/student/<int:student_id>', methods=['GET'])
@api_login_required
def get_student_trend(student_id):
    """学生个人成绩趋势（指定ID）"""
    # 检查权限：管理员可查看任意学生，学生只能查看自己
    if not session.get('is_admin') and session.get('student_id') != student_id:
        return jsonify({'success': False, 'message': '无权查看其他学生的成绩'}), 403
    return _build_student_trend(student_id)


def _build_student_trend(student_id):
    """构建学生成绩趋势数据"""
    student = db.get_or_404(Student, student_id)
    results = Result.query.filter_by(student_id=student_id).order_by(Result.submit_time).all()

    scores_list = []
    times_list = []
    exam_results = {}

    # 批量加载 Exam，消除 N+1
    exam_ids = {r.exam_id for r in results}
    exams_by_id = {e.id: e for e in Exam.query.filter(Exam.id.in_(exam_ids)).all()} if exam_ids else {}

    # 学生本人查看时跳过未公布成绩的卷（管理员/教师视图不受影响）
    hide_unpublished = not (session.get('is_admin') or session.get('is_teacher'))
    for result in results:
        exam = exams_by_id.get(result.exam_id)
        if not exam:
            continue
        if hide_unpublished and not exam.allow_view_results:
            continue
        if exam.id not in exam_results:
            exam_results[exam.id] = {
                'name': exam.name,
                'scores': [],
                'dates': [],
                'result_ids': []
            }
        # total_score or 0：与 admin_trend 口径一致，防存量 NULL 行致图表断线
        _score = result.total_score or 0
        exam_results[exam.id]['scores'].append(_score)
        exam_results[exam.id]['dates'].append(
            result.submit_time.strftime('%Y-%m-%d') if result.submit_time else ''
        )
        # 与 scores/dates 一一对应的结果 ID，供前端跳转结果详情页
        exam_results[exam.id]['result_ids'].append(result.id)
        scores_list.append(_score)
        times_list.append(
            result.submit_time.strftime('%Y-%m-%d') if result.submit_time else ''
        )

    return jsonify({
        'success': True,
        'data': {
            'student': {
                'id': student.id,
                'name': student.name,
                'class': student.student_class
            },
            'scores': scores_list,
            'times': times_list,
            'exam_results': exam_results
        },
        'message': 'ok'
    })

