"""由 API 门面模块加载的领域路由。"""
import json

from flask import current_app, jsonify, request, session

from app.extensions import db
from app.blueprints.resources import _derive_quiz_grade
from app.models import (
    Exam, PythonAnswer, Resource, ResourceQuizResult, Result, Student,
    SubQuestion,
)
from app.decorators import admin_login_required, api_login_required, teacher_login_required
from app.utils import (
    read_file_from_disk,
)
from app.blueprints.api import (
    api_bp,
)
from app.services.resource_access import teacher_can_edit, teacher_class_ids

# ──────────────────────────────────────────────
#  Results
# ──────────────────────────────────────────────


@api_bp.route('/results/<int:result_id>', methods=['GET'])
@api_login_required
def get_result(result_id):
    """考试结果详情"""
    result = db.get_or_404(Result, result_id)
    is_admin_user = session.get('is_admin', False)
    is_teacher_user = session.get('is_teacher', False)
    # 权限检查：管理员可查看任意结果，学生只能查看自己的
    if not is_admin_user and not is_teacher_user and session.get('student_id') != result.student_id:
        return jsonify({'success': False, 'message': '无权查看该考试结果'}), 403
    # 教师数据边界：仅能查看当前上课班级学生的成绩；管理员全部放行
    if is_teacher_user and not is_admin_user:
        class_ids = teacher_class_ids(session.get('teacher_id'))
        student = db.session.get(Student, result.student_id)
        if not class_ids or not student or student.class_id not in class_ids:
            return jsonify({'success': False, 'message': '无权查看该考试结果'}), 403

    exam = db.session.get(Exam, result.exam_id)
    is_pending = getattr(result, 'grading_status', 'auto_graded') == 'pending_review'
    # 「公布成绩」开关只约束学生（含待批改成绩，与 SSR 结果页同口径）；教师
    # （上面已按上课班级限定边界）需要查看本班成绩做批改/讲评
    if not (is_admin_user or is_teacher_user) and exam and not exam.allow_view_results:
        return jsonify({'success': False, 'message': '成绩尚未公布'}), 403
    # 参考答案仅在已收卷后展示，避免考试进行中先交卷的学生/教师
    # 获取答案并分享给未交卷同学（此前教师恒可看，未收卷即泄露标准答案）
    show_solutions = bool(
        exam and exam.is_collected and not is_pending and
        (is_admin_user or is_teacher_user or exam.allow_view_results))
    student = db.session.get(Student, result.student_id)
    from app.models import exam_questions_flat
    questions = exam_questions_flat(result.exam_id)

    answers = json.loads(result.answers) if result.answers else {}
    scores_data = json.loads(result.scores) if result.scores else {}

    # 批量加载 Python 答案文件内容（消除逐题查询的 N+1）
    python_files = {}
    py_q_ids = [q.id for q in questions if q.question_type == 'python_fill']
    if py_q_ids:
        py_ans_by_qid = {
            a.question_id: a for a in PythonAnswer.query.filter(
                PythonAnswer.question_id.in_(py_q_ids),
                PythonAnswer.student_id == result.student_id
            ).all()
        }
        for qid in py_q_ids:
            py_ans = py_ans_by_qid.get(qid)
            if not py_ans:
                continue
            try:
                from app.services.scoring_service import decode_python_source
                python_files[str(qid)] = {
                    'file_name': py_ans.file_name,
                    # UTF-8→GBK→容错（decode_python_source 统一口径）：
                    # 此前按 UTF-8 硬解，GBK 编码的 .py 在 SPA 端回看为空
                    # （判分/SSR 端均有 GBK 兜底，仅此端口径分叉）
                    'file_content': decode_python_source(
                        read_file_from_disk(py_ans.file_path)),
                    'score': py_ans.score,
                    'status': py_ans.status
                }
            except Exception:
                current_app.logger.debug(
                    '读取 Python 答案文件失败: qid=%s, sid=%s',
                    qid, result.student_id, exc_info=True
                )

    # 批量加载所有综合题的小题，消除 N+1
    comprehensive_ids = [q.id for q in questions if q.question_type == 'comprehensive']
    subs_by_q = {}
    if comprehensive_ids:
        for s in SubQuestion.query.filter(
                SubQuestion.question_id.in_(comprehensive_ids)
        ).order_by(SubQuestion.order).all():
            subs_by_q.setdefault(s.question_id, []).append(s)

    questions_data = []
    for q in questions:
        qd = {
            'id': q.id,
            'question_type': q.question_type,
            'content': q.content,
            'options': q.options,
            'image_options': q.image_options,
            # python_answers 为 Python 填空题标准答案，必须与 answer 一样
            # 受 show_solutions 门控，否则考试未收卷时先交卷的学生可通过
            # 成绩接口获取标准答案分享给未交卷同学（作弊通道）。
            'python_answers': q.python_answers if show_solutions else None,
            'score': q.score,
            'answer': q.answer if show_solutions else None,
            'background': q.background if show_solutions else None,
            'footer_content': q.footer_content,
            'image_url': q.image_url,
            'sub_questions': []
        }
        if q.question_type == 'comprehensive':
            subs = subs_by_q.get(q.id, [])
            for sub in subs:
                qd['sub_questions'].append({
                    'id': sub.id,
                    'question_type': sub.question_type,
                    'content': sub.content,
                    'options': sub.options,
                    'answer': sub.answer if show_solutions else None,
                    'score': sub.score,
                    'order': sub.order
                })
        questions_data.append(qd)

    return jsonify({
        'success': True,
        'data': {
            'result': {
                'id': result.id,
                'exam_id': result.exam_id,
                'student_id': result.student_id,
                'total_score': result.total_score,
                # 批改状态透出：学生端展示"待批改/已批改"提示条（SSR 版有、SPA 缺）
                'grading_status': getattr(result, 'grading_status', None),
                'submit_time': result.submit_time.strftime('%Y-%m-%d %H:%M:%S') if result.submit_time else None
            },
            'exam': {'id': exam.id, 'name': exam.name} if exam else None,
            'student': {
                'id': student.id, 'name': student.name, 'class': student.student_class
            } if student else None,
            'questions': questions_data,
            'answers': answers,
            'scores': scores_data,
            'python_files': python_files
        },
        'message': 'ok'
    })


@api_bp.route('/results/quiz/<int:result_id>', methods=['GET'])
@teacher_login_required
def get_quiz_result_light(result_id):
    """资源测验成绩单条轻量接口 — 管理员或资源创建教师可读。"""
    r = db.get_or_404(ResourceQuizResult, result_id)
    resource = db.session.get(Resource, r.resource_id)
    if not session.get('is_admin') and not teacher_can_edit(
            resource, session.get('teacher_id'), False):
        return jsonify({'success': False, 'message': '无权查看该资源成绩'}), 403
    s = db.session.get(Student, r.student_id)
    from app.services.quiz_analytics import result_questions, question_verdict
    questions = result_questions(r)
    for question in questions:
        question['is_correct'] = question_verdict(question)
    return jsonify({
        'success': True,
        'data': {
            'id': r.id,
            'student_name': s.name if s else '未知',
            'student_number': s.student_number if s else '',
            'source_file': getattr(r, 'source_file', None) or '',
            'quiz_key': getattr(r, 'quiz_key', None) or '',
            'quiz_name': r.quiz_name or '',
            'answers': r.answers,
            'questions': questions,
            'scores': r.scores,
            'total_score': r.total_score,
            'max_score': r.max_score,
            # 与管理端列表共用同一推导（存量行 grade 为 NULL 时按 total/max
            # 推导，避免两接口字段漂移）
            'grade': _derive_quiz_grade(r),
            'correct_count': getattr(r, 'correct_count', None),
            'question_count': getattr(r, 'question_count', None),
            'duration': r.duration,
            'submit_time': r.submit_time.strftime('%Y-%m-%d %H:%M:%S') if r.submit_time else '',
            # 分数由客户端自报（判分在资源文件内执行），服务端未核实
            'client_reported': True
        },
        'message': 'ok'
    })


@api_bp.route('/results/<int:result_id>', methods=['DELETE'])
@admin_login_required
def delete_result(result_id):
    """删除成绩（复用统一删除服务，避免与 homework/scores 删除逻辑漂移）"""
    result = db.get_or_404(Result, result_id)
    student_id = result.student_id
    try:
        from app.services.scoring_service import (
            delete_exam_result, finalize_exam_result_deletion)
        info = delete_exam_result(result, log_action='删除学生成绩')
        db.session.commit()
        # 趋势缓存换代 + 磁盘答案文件清理：commit 成功后执行（此前 bump 在
        # commit 前，竞态窗口内趋势页以新 epoch 读到未提交删除前的旧数据）
        finalize_exam_result_deletion(info)
        current_app.logger.info(
            f"API 删除成绩成功: result_id={result_id}, student_id={student_id}"
        )
        return jsonify({'success': True, 'message': '成绩已删除'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"API 删除成绩失败: {str(e)}")
        return jsonify({'success': False, 'message': '删除失败'}), 500


@api_bp.route('/results/batch-delete', methods=['POST'])
@admin_login_required
def batch_delete_results():
    """批量删除成绩 {ids: [...], exam_id: ...}"""
    data = request.get_json(force=True, silent=True)
    if not data or 'ids' not in data:
        return jsonify({'success': False, 'message': '请提供要删除的成绩 ID 列表'}), 400

    result_ids = data['ids']
    exam_id = data.get('exam_id')
    if not result_ids:
        return jsonify({'success': False, 'message': '未选择任何成绩'}), 400

    deleted_count = 0
    error_count = 0
    deleted_infos = []

    for rid in result_ids:
        try:
            result = db.session.get(Result, int(rid))
            if not result:
                error_count += 1
                continue
            if exam_id and result.exam_id != exam_id:
                error_count += 1
                continue

            from app.services.scoring_service import delete_exam_result
            deleted_infos.append(
                delete_exam_result(result, log_action='批量删除学生成绩'))
            deleted_count += 1
        except Exception as e:
            error_count += 1
            current_app.logger.error(f"API 批量删除成绩 ID {rid} 时出错: {str(e)}")

    try:
        db.session.commit()
        # 趋势缓存换代 + 磁盘答案文件清理：commit 成功后统一执行
        if deleted_infos:
            from app.services.scoring_service import finalize_exam_result_deletion
            finalize_exam_result_deletion(*deleted_infos)
        current_app.logger.info(f"API 批量删除成绩成功: 共 {deleted_count} 条")
        msg = f'已成功删除 {deleted_count} 条成绩'
        if error_count > 0:
            msg += f', {error_count} 条失败'
        return jsonify({
            'success': True,
            'data': {'deleted': deleted_count, 'errors': error_count},
            'message': msg
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"API 批量删除成绩提交失败: {str(e)}")
        return jsonify({'success': False, 'message': '批量删除失败'}), 500
