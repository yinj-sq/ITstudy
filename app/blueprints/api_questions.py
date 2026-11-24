"""由 API 门面模块加载的领域路由。"""

import math

from flask import current_app, jsonify, request
from sqlalchemy import func

from app.extensions import db
from app.filters import sanitize_rich_text
from app.models import (
    Exam, PythonAnswer, PythonFile, Question,
    SubQuestion, normalize_options,
)
from app.decorators import admin_login_required
from app.utils import (
    parse_int, read_file_from_disk, delete_file_from_disk,
)
from app.blueprints.api import (
    api_bp,
)


def _safe_score(value, default=1.0):
    """安全解析分数：非有限数（NaN/Infinity）或负数时返回默认值。"""
    try:
        s = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(s) or math.isinf(s) or s < 0:
        return default
    return s


def _safe_int(value, default=1):
    """安全解析整数：转换失败时返回默认值。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _cleanup_question_fks(question):
    """删除题目前的 FK 清理（不删磁盘文件，返回待删路径列表）。

    磁盘文件必须在 DB commit 成功后再删：此前先删盘后提交，提交失败
    回滚后题目/答案记录仍在而文件已 404。
    """
    orphan_paths = []
    for pf in PythonFile.query.filter_by(question_id=question.id).all():
        if pf.file_path:
            orphan_paths.append(pf.file_path)
        db.session.delete(pf)
    # PythonAnswer 磁盘文件同样延后删除（此前只删 DB 行 → 孤儿文件）
    for pa in PythonAnswer.query.filter_by(question_id=question.id).all():
        if pa.file_path:
            orphan_paths.append(pa.file_path)
    PythonAnswer.query.filter_by(question_id=question.id).delete(synchronize_session=False)
    return orphan_paths


def _delete_orphan_paths(paths):
    for rel_path in paths:
        try:
            delete_file_from_disk(rel_path)
        except Exception:
            current_app.logger.debug('删除题目关联文件失败（忽略）: %s', rel_path)


# ──────────────────────────────────────────────
#  Questions
# ──────────────────────────────────────────────


@api_bp.route('/questions', methods=['GET'])
@admin_login_required
def get_questions():
    """题目列表（支持 exam_id / question_type 筛选 + 分页）

    分页：仅当显式传 page 时启用（默认 20 条/页，上限 100）。
    此前全量加载 + 全量 Text 列序列化，题库上千题时响应体积线性膨胀，
    SPA 每次筛选/翻页全量重拉。
    """
    query = Question.query
    exam_id = request.args.get('exam_id', type=int)
    question_type = request.args.get('question_type')
    if exam_id:
        # 解耦：按关联试卷（中间表）筛选
        from app.models import ExamQuestion
        query = (query.join(ExamQuestion,
                            ExamQuestion.question_id == Question.id)
                 .filter(ExamQuestion.exam_id == exam_id))
    if question_type:
        query = query.filter_by(question_type=question_type)
    page = request.args.get('page', type=int)
    if page is not None:
        # SQL 层分页（offset/limit），避免全量加载
        page_size = min(max(request.args.get('page_size', type=int) or 20, 1), 100)
        total = query.count()
        total_pages = max((total + page_size - 1) // page_size, 1)
        questions = query.order_by(Question.id.desc()).offset(
            max(page - 1, 0) * page_size).limit(page_size).all()
    else:
        # 未传 page：维持原全量行为（兼容其他调用方）
        total = 0
        total_pages = 1
        page_size = 20
        questions = query.order_by(Question.id.desc()).all()
    # 一次性聚合当前页所有题目的子题数量，消除 N+1
    q_ids = [q.id for q in questions]
    sub_counts = {}
    if q_ids:
        sub_counts = dict(
            db.session.query(SubQuestion.question_id, func.count(SubQuestion.id))
            .filter(SubQuestion.question_id.in_(q_ids))
            .group_by(SubQuestion.question_id).all()
        )
    # 关联卷映射（一次聚合；解耦后一题可属多卷）
    exam_ids_map = {}
    if q_ids:
        from app.models import ExamQuestion
        for qid, eid in db.session.query(
                ExamQuestion.question_id, ExamQuestion.exam_id
        ).filter(ExamQuestion.question_id.in_(q_ids)).all():
            exam_ids_map.setdefault(qid, []).append(eid)
    data = [{
        'id': q.id,
        'exam_id': q.exam_id,          # 来源卷（溯源，可空）
        'exam_ids': exam_ids_map.get(q.id, []),  # 关联的全部试卷
        'question_type': q.question_type,
        'content': q.content,
        'options': q.options,
        'answer': q.answer,
        'score': q.score,
        'image_url': q.image_url,
        'background': q.background,
        'created_at': q.created_at.strftime('%Y-%m-%d %H:%M:%S') if q.created_at else None,
        'sub_count': sub_counts.get(q.id, 0)
    } for q in questions]
    resp = {'success': True, 'data': data, 'message': 'ok'}
    if page is not None:
        resp.update({'total': total, 'page': page, 'page_size': page_size,
                     'total_pages': total_pages})
    return jsonify(resp)


@api_bp.route('/questions/<int:question_id>', methods=['GET'])
@admin_login_required
def get_question(question_id):
    """题目详情（含小题、Python 文件等）"""
    question = db.get_or_404(Question, question_id)
    sub_questions = SubQuestion.query.filter_by(question_id=question_id).order_by(SubQuestion.order).all()
    python_file = PythonFile.query.filter_by(question_id=question_id).first()

    data = {
        'id': question.id,
        'exam_id': question.exam_id,
        'question_type': question.question_type,
        'content': question.content,
        'options': question.options,
        'image_options': question.image_options,
        'answer': question.answer,
        'score': question.score,
        'image_url': question.image_url,
        'background': question.background,
        'created_at': question.created_at.strftime('%Y-%m-%d %H:%M:%S') if question.created_at else None,
        'python_answers': question.python_answers,
        'sub_questions': [],
        'python_file': None
    }

    for sub in sub_questions:
        sub_data = {
            'id': sub.id,
            'question_type': sub.question_type,
            'content': sub.content,
            'options': sub.options,
            'image_options': sub.image_options,
            'answer': sub.answer,
            'score': sub.score,
            'order': sub.order,
            'blank_scores': sub.blank_scores_list
        }
        data['sub_questions'].append(sub_data)

    if python_file:
        try:
            file_content = read_file_from_disk(python_file.file_path).decode('utf-8')
        except Exception:
            file_content = None
        data['python_file'] = {
            'id': python_file.id,
            'file_name': python_file.file_name,
            'file_content': file_content
        }

    return jsonify({'success': True, 'data': data, 'message': 'ok'})


@api_bp.route('/questions', methods=['POST'])
@admin_login_required
def create_question():
    """创建题目（完整逻辑同 questions.py add_question）"""
    data = request.get_json(force=True, silent=True) or request.form
    # data 可能是普通 dict(JSON)或 MultiDict(form)；统一用 parse_int 解析，
    # 避免对 dict 调用不支持关键字参数的 .get(..., type=int) 抛 TypeError。
    exam_id = parse_int(data.get('exam_id'))
    question_type = data.get('question_type')
    # 服务端净化（纵深防御）：前端已有 DOMPurify/sanitize.js，入库前再
    # 剥离一次脚本/事件属性——防净化器边角（SVG/foreignObject 等）绕过
    content = str(sanitize_rich_text(str(data.get('content') or '').strip()))
    options = data.get('options', '')
    answer = str(data.get('answer') or '').strip()
    score = _safe_score(data.get('score', 1.0), default=1.0)

    # exam_id 可选：空 = 仅存题库（解耦后题目可 0 卷归属）
    if not question_type or not content:
        return jsonify({'success': False, 'message': '请填写完整的题目信息'}), 400

    exam = db.session.get(Exam, exam_id) if exam_id else None
    if exam_id and not exam:
        return jsonify({'success': False, 'message': '试卷不存在'}), 404

    # 外链卷互斥（与 HTML 端 add_question 同口径）：外链试卷只允许含
    # link 题，普通题经 API 建入会破坏该不变量
    if exam_id and question_type != 'link':
        from app.models import ExamQuestion as _EQ
        if (Question.query.join(_EQ, _EQ.question_id == Question.id)
                .filter(_EQ.exam_id == exam_id,
                        Question.question_type == 'link').first()):
            return jsonify({'success': False,
                            'message': '该试卷已设置为外链试卷，不可再添加其他试题'}), 400
    # 对称互斥：普通卷不能直接建入外链题（否则卷内两种题型混存，
    # is_link 判定按“首题”失效，外链题在考试页无作答控件且恒 0 分）
    if exam_id and question_type == 'link':
        from app.models import ExamQuestion as _EQ2
        if (Question.query.join(_EQ2, _EQ2.question_id == Question.id)
                .filter(_EQ2.exam_id == exam_id,
                        Question.question_type != 'link').first()):
            return jsonify({'success': False,
                            'message': '该试卷已含普通题，不能加入外链题'}), 400
    # 带卷建题会自动挂卷、改变试卷满分：与组卷页同一把锁
    if exam_id:
        from app.blueprints.exam_management import exam_compose_lock_message
        lock_msg = exam_compose_lock_message(exam_id)
        if lock_msg:
            return jsonify({'success': False, 'message': lock_msg}), 409

    try:
        question = Question(
            exam_id=exam_id,
            question_type=question_type,
            content=content,
            options=normalize_options(options),
            answer=answer,
            score=score
        )

        # 处理图片选项（JSON 字符串）
        image_options = data.get('image_options')
        if image_options:
            question.image_options = image_options

        # Python 填空题特殊处理
        if question_type == 'python_fill':
            python_answers = data.get('python_answers', '')
            question.python_answers = python_answers

        # 综合题特殊处理
        if question_type == 'comprehensive':
            background = data.get('background', '').strip()
            question.background = background

            sub_questions_data = data.get('sub_questions')
            if sub_questions_data:
                # 用 flush 在同一事务内获取 question.id（而非提前 commit），
                # 子题创建失败时整体 rollback，避免留下无子题的空壳综合题
                db.session.add(question)
                db.session.flush()

                for sub_data in sub_questions_data:
                    sub_question = SubQuestion(
                        question_id=question.id,
                        question_type=sub_data.get('type'),
                        content=sub_data.get('content', ''),
                        options=normalize_options(sub_data.get('options', '')),
                        answer=sub_data.get('answer', ''),
                        score=_safe_score(sub_data.get('score', 1.0), default=1.0),
                        order=_safe_int(sub_data.get('order', 1), default=1)
                    )
                    db.session.add(sub_question)

                # 更新主题目总分
                question.score = sum(
                    _safe_score(sub.get('score', 0), default=0) for sub in sub_questions_data
                )
            else:
                db.session.add(question)
        else:
            db.session.add(question)

        db.session.commit()

        current_app.logger.info(
            f"API 创建题目成功: ID={question.id}, 类型={question_type}"
        )
        return jsonify({
            'success': True,
            'data': {'id': question.id},
            'message': '题目创建成功'
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"API 创建题目失败: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': '创建题目失败'}), 500


@api_bp.route('/questions/<int:question_id>', methods=['PUT'])
@admin_login_required
def update_question(question_id):
    """编辑题目"""
    question = db.get_or_404(Question, question_id)
    # 在考锁定：考试进行中改题干/答案/分值会让学生卷面与判分口径错位
    from app.blueprints.questions import _question_lock_message
    _lock_msg = _question_lock_message(question)
    if _lock_msg:
        return jsonify({'success': False, 'message': _lock_msg}), 409
    data = request.get_json(force=True, silent=True) or request.form

    exam_id = parse_int(data.get('exam_id'))
    # 服务端净化（同创建路径，防净化器边角绕过）
    content = str(sanitize_rich_text(str(data.get('content') or '').strip()))
    options = data.get('options', '')
    answer = str(data.get('answer') or '').strip()
    score = _safe_score(data.get('score', question.score), default=question.score)

    if not content:
        return jsonify({'success': False, 'message': '请填写完整的题目信息'}), 400

    if exam_id:
        exam = db.session.get(Exam, exam_id)
        if not exam:
            return jsonify({'success': False, 'message': '试卷不存在'}), 404

    try:
        # 解耦保护：改"来源卷"会触发 unlink/link 重挂——若该题任一关联卷
        # 已有成绩，重挂将使成绩单出现"分数在、题目缺失"的破损口径。
        # 真实归属在 exam_question 中间表：question.exam_id 仅来源溯源，
        # 不能只按它 unlink（否则题已在 A 卷、来源为空时改选 B 会挂成 A+B）。
        _old_exam_id = question.exam_id
        from app.models import ExamQuestion as _EQ, Result as _Res
        _linked_ids = [r[0] for r in db.session.query(_EQ.exam_id)
                       .filter_by(question_id=question.id).all()]
        _move_needed = (_old_exam_id != exam_id
                        or bool(set(_linked_ids) - ({exam_id} if exam_id else set())))
        if _move_needed:
            _has_res = bool(_linked_ids and _Res.query.filter(
                _Res.exam_id.in_(_linked_ids)).first())
            if _has_res:
                return jsonify({'success': False,
                                'message': '该题所属试卷已有成绩记录，禁止更改归属；'
                                           '如需调整请先删除相关成绩'}), 409
            # 所有受影响的卷（当前关联 + 来源 + 目标）都必须未在考/未收卷
            from app.blueprints.exam_management import exam_compose_lock_message
            _affected_exams = set(_linked_ids)
            if _old_exam_id:
                _affected_exams.add(_old_exam_id)
            if exam_id:
                _affected_exams.add(exam_id)
            for _eid in sorted(_affected_exams):
                lock_msg = exam_compose_lock_message(_eid)
                if lock_msg:
                    return jsonify({'success': False,
                                    'message': f'相关试卷不可调整：{lock_msg}'}), 409
        if (question.question_type != 'comprehensive'
                and abs((question.score or 0) - score) > 1e-9
                and _question_has_result(question)):
            return jsonify({'success': False,
                            'message': '该题所属试卷已有成绩记录，禁止修改分值'}), 409
        question.exam_id = exam_id
        question.content = content
        question.options = normalize_options(options)
        question.answer = answer
        question.score = score

        # 综合题父题分值强制 = 子题分值之和：与 HTML 编辑路径
        # （questions.py 同名逻辑）及 manage_sub_questions 保持同一口径。
        # SPA 表单对综合题也提交可编辑的分值字段，若原样写入会出现"父题 0 分、
        # 子题合计 10 分"——组卷/结果页按父题取满分、判分按子题求和，同卷两口径。
        if question.question_type == 'comprehensive':
            from app.models import SubQuestion as _SQ
            question.score = db.session.query(
                func.coalesce(func.sum(_SQ.score), 0)
            ).filter(_SQ.question_id == question.id).scalar() or 0

        image_options = data.get('image_options')
        if image_options:
            question.image_options = image_options

        if question.question_type == 'python_fill' and 'python_answers' in data:
            # 仅在前端显式提交 python_answers 时更新，
            # 避免表单未携带该字段时静默清空已存的 Python 答案字典
            question.python_answers = data.get('python_answers', '')

        if question.question_type == 'comprehensive':
            background = data.get('background', '').strip()
            question.background = background

        # 来源卷变化 → 同步卷归属（从所有旧卷移除、新卷挂尾；
        # 来源为空的已组卷题也一并从既有卷移出，实现真正的“移动”而非追加）
        if _move_needed:
            from app.models import (link_question_to_exam,
                                    unlink_question_from_exam, resequence_exam)
            for _eid in _linked_ids:
                if _eid != exam_id:
                    unlink_question_from_exam(question.id, _eid)
            if exam_id and exam_id not in _linked_ids:
                if question.question_type != 'link':
                    from app.models import ExamQuestion as _EQ
                    from app.models import Question as _Q
                    has_link = (db.session.query(_EQ.id)
                                .join(_Q, _Q.id == _EQ.question_id)
                                .filter(_EQ.exam_id == exam_id,
                                        _Q.question_type == 'link').first())
                    if has_link:
                        db.session.rollback()
                        return jsonify({'success': False,
                                        'message': '目标试卷已为外链试卷，'
                                                   '不可加入其他试题'}), 400
                link_question_to_exam(question.id, exam_id)
            for _eid in {*_linked_ids, *([exam_id] if exam_id else [])}:
                if _eid != exam_id:
                    resequence_exam(_eid)
            if exam_id:
                resequence_exam(exam_id)

        db.session.commit()
        current_app.logger.info(f"API 修改题目成功: ID={question.id}")
        return jsonify({'success': True, 'data': {'id': question.id}, 'message': '题目修改成功'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"API 修改题目失败: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': '修改题目失败'}), 500


def _question_has_result(question):
    """题目任一关联卷存在成绩记录（解耦后一题可属多卷，任一卷有成绩
    即保护）——与 HTML 端 questions.py 同名助手同口径，防 SPA 删题
    造成"分数在、题目缺失"的破损成绩单"""
    from app.models import Result as _Result, ExamQuestion as _EQ
    exam_ids = [eid for (eid,) in db.session.query(_EQ.exam_id)
                .filter(_EQ.question_id == question.id).all()]
    if not exam_ids:
        return False
    return db.session.query(_Result.id).filter(
        _Result.exam_id.in_(exam_ids)).first() is not None


@api_bp.route('/questions/<int:question_id>', methods=['DELETE'])
@admin_login_required
def delete_question(question_id):
    """删除题目"""
    question = db.get_or_404(Question, question_id)
    # 成绩守卫（与 HTML 端 questions.py 单删一致）：已有成绩的题删除后
    # Result.scores 引用的题目键悬空，明细/趋势/导出全部错位
    if _question_has_result(question):
        return jsonify({'success': False,
                        'message': '无法删除：该题目所属试卷已有成绩记录，'
                                   '请先删除相关成绩'}), 409
    try:
        # 先清理 FK 引用（PythonFile/PythonAnswer 指向 question.id 且无级联），
        # 否则 commit 时抛 IntegrityError 导致删除失败；磁盘文件延后删除
        orphan_paths = _cleanup_question_fks(question)
        db.session.delete(question)
        db.session.commit()
        _delete_orphan_paths(orphan_paths)
        current_app.logger.info(f"API 删除题目成功: ID={question_id}")
        return jsonify({'success': True, 'message': '题目删除成功'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"API 删除题目失败: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': '删除题目失败'}), 500


@api_bp.route('/questions/batch-delete', methods=['POST'])
@admin_login_required
def batch_delete_questions():
    """批量删除题目 {ids: [...]}"""
    data = request.get_json(force=True, silent=True)
    if not data or 'ids' not in data:
        return jsonify({'success': False, 'message': '请提供要删除的题目 ID 列表'}), 400

    ids = data['ids']
    if not ids:
        return jsonify({'success': False, 'message': '未选择任何题目'}), 400

    deleted_count = 0
    error_count = 0
    orphan_paths = []
    for qid in ids:
        try:
            question = db.session.get(Question, int(qid))
            if question:
                # 成绩保护：所属试卷已有成绩记录的题目跳过（与单删路径/
                # HTML 端批删策略一致）
                if _question_has_result(question):
                    error_count += 1
                    current_app.logger.warning(
                        f"API 批量删除跳过 ID {qid}：所属试卷已有成绩记录")
                    continue
                # 与单删路径一致：先清理 FK 引用，磁盘文件延后到 commit 后
                orphan_paths.extend(_cleanup_question_fks(question))
                db.session.delete(question)
                deleted_count += 1
            else:
                error_count += 1
        except Exception as e:
            error_count += 1
            current_app.logger.error(f"API 批量删除题目 ID {qid} 时出错: {str(e)}")

    try:
        db.session.commit()
        _delete_orphan_paths(orphan_paths)
        current_app.logger.info(f"API 批量删除题目成功: 共 {deleted_count} 个")
        msg = f'已成功删除 {deleted_count} 个题目'
        if error_count > 0:
            msg += f', {error_count} 个失败'
        return jsonify({'success': True, 'data': {'deleted': deleted_count, 'errors': error_count}, 'message': msg})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"API 批量删除题目提交失败: {str(e)}")
        return jsonify({'success': False, 'message': '批量删除失败'}), 500


@api_bp.route('/questions/<int:question_id>/sub', methods=['GET'])
@admin_login_required
def get_sub_questions(question_id):
    """获取小题列表"""
    question = db.get_or_404(Question, question_id)
    sub_questions = SubQuestion.query.filter_by(question_id=question_id).order_by(SubQuestion.order).all()
    data = []
    for sub in sub_questions:
        data.append({
            'id': sub.id,
            'question_type': sub.question_type,
            'content': sub.content,
            'options': sub.options,
            'image_options': sub.image_options,
            'answer': sub.answer,
            'score': sub.score,
            'order': sub.order,
            'blank_scores': sub.blank_scores_list
        })
    return jsonify({
        'success': True,
        'data': {
            'question_id': question_id,
            'question_type': question.question_type,
            'sub_questions': data
        },
        'message': 'ok'
    })


@api_bp.route('/questions/<int:question_id>/sub', methods=['POST'])
@admin_login_required
def add_sub_question(question_id):
    """添加小题"""
    question = db.get_or_404(Question, question_id)
    if question.question_type != 'comprehensive':
        return jsonify({'success': False, 'message': '只能为综合题添加小题'}), 400
    from app.blueprints.questions import _question_lock_message
    _lock_msg = _question_lock_message(question, include_collected=True)
    if _lock_msg:
        return jsonify({'success': False, 'message': _lock_msg}), 409
    # 加小题改变父题分值（= 试卷满分）：与删小题同一守卫
    if _question_has_result(question):
        return jsonify({'success': False,
                        'message': '该题所属试卷已有成绩记录，禁止添加小题'}), 409

    data = request.get_json(force=True, silent=True) or request.form
    # 兼容两种字段名：SPA 前端提交 question_type，Jinja 端提交 type。
    # 后续校验与入库统一使用 sub_type 变量。
    sub_type = data.get('type') or data.get('question_type')
    # 服务端净化（同题目创建路径）
    sub_content = str(sanitize_rich_text(str(data.get('content', '')).strip()))
    sub_options = data.get('options', '')
    sub_answer = data.get('answer', '').strip()
    sub_score = _safe_score(data.get('score', 1.0), default=1.0)

    if not sub_type or not sub_content or not sub_answer:
        return jsonify({'success': False, 'message': '请填写完整的小题信息'}), 400

    max_order = db.session.query(db.func.max(SubQuestion.order)).filter(
        SubQuestion.question_id == question_id
    ).scalar() or 0

    try:
        sub_question = SubQuestion(
            question_id=question_id,
            question_type=sub_type,
            content=sub_content,
            options=normalize_options(sub_options),
            answer=sub_answer,
            score=sub_score,
            order=max_order + 1
        )
        db.session.add(sub_question)

        # 更新综合题总分
        question.score = db.session.query(db.func.sum(SubQuestion.score)).filter(
            SubQuestion.question_id == question_id
        ).scalar() or 0

        db.session.commit()
        current_app.logger.info(f"API 添加小题成功: 综合题ID={question_id}, 小题ID={sub_question.id}")
        return jsonify({
            'success': True,
            'data': {'id': sub_question.id},
            'message': '小题添加成功'
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"API 添加小题失败: {str(e)}")
        return jsonify({'success': False, 'message': '添加小题失败'}), 500


@api_bp.route('/questions/<int:question_id>/sub/<int:sub_id>', methods=['DELETE'])
@admin_login_required
def delete_sub_question(question_id, sub_id):
    """删除小题"""
    sub_question = db.get_or_404(SubQuestion, sub_id)
    if sub_question.question_id != question_id:
        return jsonify({'success': False, 'message': '小题不属于该题目'}), 400

    # 删除已提交过的小题会导致该试卷已存成绩总分被静默扣减
    # （submit_grading 重算聚合分时仅统计仍存在的小题）。与 HTML 版
    # questions.py 一致，有成绩记录或在考/收卷时拒绝删除。
    try:
        parent = db.session.get(Question, question_id)
        from app.blueprints.questions import _question_has_result, _question_lock_message
        if parent:
            _lock_msg = _question_lock_message(parent, include_collected=True)
            if _lock_msg:
                return jsonify({'success': False, 'message': _lock_msg}), 409
        if parent and _question_has_result(parent):
            return jsonify({
                'success': False,
                'message': '该综合题已有学生成绩记录，删除小题会导致已批改成绩总分变化，请先删除该试卷的成绩'
            }), 400
    except Exception:
        pass

    try:
        db.session.delete(sub_question)

        # 更新综合题总分
        question = db.session.get(Question, question_id)
        if question:
            question.score = db.session.query(db.func.sum(SubQuestion.score)).filter(
                SubQuestion.question_id == question_id
            ).scalar() or 0

        db.session.commit()
        current_app.logger.info(f"API 删除小题成功: ID={sub_id}")
        return jsonify({'success': True, 'message': '小题删除成功'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"API 删除小题失败: {str(e)}")
        return jsonify({'success': False, 'message': '删除小题失败'}), 500

