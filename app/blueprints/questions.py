"""
题库管理 Blueprint
"""
from flask import Blueprint, request, render_template, redirect, url_for, flash, send_file, jsonify
from flask import current_app
from datetime import datetime
from app.extensions import db
from app.models import Question, Exam, SubQuestion, PythonFile, PythonAnswer, Log, normalize_options
from app.decorators import admin_login_required
from app.utils import (allowed_file, save_file_to_disk, delete_file_from_disk)
from werkzeug.utils import secure_filename
from sqlalchemy import func
import openpyxl
from openpyxl import Workbook
from io import BytesIO
import os
import json
import math
import uuid


def _touch_exam_list_cache():
    """题目增删改后失效管理端试卷列表缓存（api:exams:list:* 含
    question_count，TTL 60s——写路径主动失效使题数即时可见；
    exam_management 与批量导入 python_files 路径均已失效，此处补齐）。"""
    from app.blueprints.exam_management import _invalidate_exam_list_cache
    _invalidate_exam_list_cache()


_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

questions_bp = Blueprint('questions', __name__, url_prefix='')
# 综合题小题可用题型（判分器 auto_score 支持的客观题 + 简答）
_SUB_QUESTION_TYPES = frozenset({'single', 'multiple', 'judge', 'fill', 'short_answer'})


def _is_valid_score(value):
    """校验分值是否合法：必须能转为有限浮点数且 > 0（分值必须为正数）。

    拒绝 NaN/Infinity/负数/0 —— 这些值会污染成绩统计与总分计算。
    与 api_questions.py 的 _safe_score 语义不同：此处不静默回退，由调用方决定拒绝保存。
    """
    try:
        s = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(s) and s > 0


def _question_has_result(question):
    """题目任一关联卷存在成绩记录（解耦后一题可属多卷，任一卷有成绩
    即视为"已有成绩"，删除/改动保护按此判定）"""
    from app.models import Result as _Result, ExamQuestion as _EQ
    exam_ids = [eid for (eid,) in db.session.query(_EQ.exam_id)
                .filter(_EQ.question_id == question.id).all()]
    if not exam_ids:
        return False
    return db.session.query(_Result.id).filter(
        _Result.exam_id.in_(exam_ids)).first() is not None


def _question_lock_message(question, include_collected=False):
    """题目关联卷是否处于“不可改题”状态（在考；结构改动还含已收卷）。

    考试进行中改题干/答案/分值/小题，会让学生看到的卷面与交卷时使用的
    题目对象不一致（同一场考试出现两套满分）；加/删小题还会改变试卷满分。
    与组卷锁 `exam_compose_lock_message` 同源判定，但按改动类型区分是否
    包含“已收卷”（收卷后仅改文字/答案不影响已存成绩，允许教师修正）。
    """
    from app.models import Exam as _Exam, ExamQuestion as _EQ
    from app.services.scoring_service import has_active_attempt
    exam_ids = [eid for (eid,) in db.session.query(_EQ.exam_id)
                .filter(_EQ.question_id == question.id).all()]
    for eid in exam_ids:
        exam = db.session.get(_Exam, eid)
        if not exam:
            continue
        if has_active_attempt(exam):
            return '该试卷有学生正在考试，题目已锁定'
        if include_collected and exam.is_collected:
            return '该试卷已收卷，题目结构已锁定'
    return None


def _has_link_question(exam_id):
    """
    检查试卷是否已为外链试卷（已有 link 类型题目）
    @param exam_id: 试卷ID
    @return: Link 类型的 Question 对象，如果不存在则返回 None
    """
    from app.models import ExamQuestion
    return (Question.query
            .join(ExamQuestion, ExamQuestion.question_id == Question.id)
            .filter(ExamQuestion.exam_id == exam_id,
                    Question.question_type == 'link').first())


def _get_non_link_exams():
    """
    获取所有未设置为外链试卷的试卷列表（单条查询消除 N+1）
    @return: 不包含 link 类型题目的试卷列表
    """
    from app.models import ExamQuestion
    all_exams = Exam.query.order_by(Exam.name).all()
    link_exam_ids = {
        eid for (eid,) in db.session.query(ExamQuestion.exam_id)
        .join(Question, Question.id == ExamQuestion.question_id)
        .filter(Question.question_type == 'link').all()
    }
    return [exam for exam in all_exams if exam.id not in link_exam_ids]


@questions_bp.route('/admin/questions', methods=['GET'])
@admin_login_required
def admin_questions():
    """
    @function admin_questions
    @brief 题库管理页面，支持按试卷和题型筛选
    @return 渲染admin_questions.html模板
    """
    # 获取筛选参数
    selected_exam_id = request.args.get('exam_id', type=int)
    selected_type = request.args.get('question_type')

    # 构建查询条件
    query = Question.query

    if selected_exam_id:
        # 解耦：按"关联试卷"筛选（中间表），同一题可属多卷
        from app.models import ExamQuestion
        query = (query.join(ExamQuestion,
                            ExamQuestion.question_id == Question.id)
                 .filter(ExamQuestion.exam_id == selected_exam_id))

    if selected_type:
        query = query.filter_by(question_type=selected_type)

    # 获取题目列表（eager load exam/sub_questions，消除模板逐行 lazy 查询的 N+1；
    # 分页渲染，避免题库增长后单页全量加载）
    from sqlalchemy.orm import joinedload, selectinload
    from app.utils import paginate_query
    pagination = paginate_query(
        query.options(
            joinedload(Question.exam),
            selectinload(Question.sub_questions)
        ).order_by(Question.id.desc()),
        default_per_page=20, max_per_page=100
    )

    # 获取所有试卷
    exams = Exam.query.order_by(Exam.name).all()

    # 可用于外链试卷的试卷（没有 link 类型题目的试卷）
    link_available_exams = _get_non_link_exams()

    return render_template('admin_questions.html',
                           questions=pagination.items,
                           exams=exams,
                           link_available_exams=link_available_exams,
                           selected_exam_id=selected_exam_id,
                           selected_type=selected_type,
                           pagination=pagination)


@questions_bp.route('/admin/questions/add', methods=['GET', 'POST'])
@admin_login_required
def add_question():
    """
    @function add_question
    @brief 添加题目
    @return 渲染add_question.html模板或处理添加请求
    """
    if request.method == 'POST':
        # 检查是否是AJAX请求
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        # 获取表单数据
        exam_id = request.form.get('exam_id', type=int)
        question_type = request.form.get('question_type')
        content = request.form.get('content', '').strip()
        options = request.form.get('options', '')
        answer = request.form.get('answer', '').strip()
        score = request.form.get('score', type=float, default=1.0)

        # 分值校验：NaN/Infinity/负数/0 会污染成绩统计与总分计算，拒绝保存
        if not _is_valid_score(score):
            if is_ajax:
                return jsonify({'success': False, 'msg': '分值必须为正数'}), 400
            flash('分值必须为正数')
            return redirect(url_for('questions.add_question'))

        if not question_type or not content:
            # 对AJAX请求返回JSON错误（exam_id 可选：空=仅存题库，不入卷）
            if is_ajax:
                return jsonify({
                    'success': False,
                    'msg': '请填写完整的题目信息'
                }), 400
            # 对普通请求使用flash消息
            flash('请填写完整的题目信息')
            return redirect(url_for('questions.add_question'))

        # 检查该试卷是否为外链试卷（已有link类型题目则不可再添加其他题目）
        if _has_link_question(exam_id):
            if is_ajax:
                return jsonify({
                    'success': False,
                    'msg': '该试卷已设置为外链试卷，不可再添加其他试题'
                }), 400
            flash('该试卷已设置为外链试卷，不可再添加其他试题')
            return redirect(url_for('questions.add_question'))

        # 带卷建题会由 after_insert 自动挂卷、改变试卷满分：与组卷页同一把锁
        from app.blueprints.exam_management import exam_compose_lock_message
        lock_msg = exam_compose_lock_message(exam_id)
        if lock_msg:
            if is_ajax:
                return jsonify({'success': False, 'msg': lock_msg}), 409
            flash(lock_msg)
            return redirect(url_for('questions.add_question'))

        try:
            # 创建题目
            question = Question(
            exam_id=exam_id,
                question_type=question_type,
                content=content,
                options=normalize_options(options),
                answer=answer,
                score=score
            )

            # 处理选项图片
            image_options = request.form.get('image_options')
            if image_options:
                current_app.logger.info(f"收到图片选项: {image_options}")
                question.image_options = image_options

            # Python填空题特殊处理
            if question_type == 'python_fill':
                python_answers = request.form.get('python_answers', '')
                question.python_answers = python_answers

            # 综合题特殊处理
            if question_type == 'comprehensive':
                background = request.form.get('background', '').strip()
                question.background = background
                footer_content = request.form.get('footer_content', '').strip()
                question.footer_content = footer_content
                current_app.logger.info(f"综合题背景设置 {background}")

                # 获取子题目数据
                sub_questions_json = request.form.get('sub_questions')

                # 处理子题目数据
                if sub_questions_json:
                    try:
                        sub_questions_data = json.loads(sub_questions_json)
                        current_app.logger.info(f"收到子题目数据 {len(sub_questions_data)} 个子题目")

                        # 用 flush 获取ID（保持单事务：子题创建失败时主题目整体回滚，
                        # 不会留下无子题的空壳综合题）
                        db.session.add(question)
                        db.session.flush()

                        # 添加子题目
                        for sub_data in sub_questions_data:
                            try:
                                sub_score = float(sub_data.get('score', 1.0))
                            except (TypeError, ValueError):
                                sub_score = float('nan')
                            # 子题分值同样必须为正有限数（NaN/负数会污染综合题总分）
                            if not _is_valid_score(sub_score):
                                raise ValueError(
                                    f'子题分值必须为正数: {str(sub_data.get("content", ""))[:30]}')
                            sub_question = SubQuestion(
                                question_id=question.id,
                                question_type=sub_data.get('type'),
                                content=sub_data.get('content'),
                                options=normalize_options(sub_data.get('options', '')),
                                answer=sub_data.get('answer'),
                                score=sub_score,
                                order=int(sub_data.get('order', 1)),
                                image_url=sub_data.get('image_url', '') or None,
                                image_options=sub_data.get('image_options', '') or None
                            )
                            db.session.add(sub_question)
                            current_app.logger.info(f"添加子题目 类型={sub_data.get('type')}, 内容={sub_data.get('content')[:20]}...")

                        # 更新主题目总分
                        question.score = sum(float(sub.get('score', 0)) for sub in sub_questions_data)
                        current_app.logger.info(f"更新综合题总分: {question.score}")
                    except Exception as e:
                        current_app.logger.error(f"处理子题目数据失败: {str(e)}", exc_info=True)
                        db.session.rollback()
                        raise

            # 保存题目到数据库（综合题且带子题目时已在上方 add + flush）
            if question_type != 'comprehensive' or not request.form.get('sub_questions'):
                db.session.add(question)
            db.session.commit()

            # 处理Python文件上传（只针对Python填空题）
            if question_type == 'python_fill' and 'python_file' in request.files:
                python_file = request.files['python_file']
                if python_file and python_file.filename:
                    # 获取文件路径或使用原始文件名
                    python_file_path = request.form.get('python_file_path', '')
                    filename = python_file_path if python_file_path else secure_filename(python_file.filename)

                    # 流式落盘 + 大小限制（save 直写磁盘，超限按 getsize 校验并删除）
                    from app.utils import save_stream_to_disk
                    ok, msg, rel_path, _size = save_stream_to_disk(
                        python_file, 'python_files', filename,
                        max_bytes=20 * 1024 * 1024)
                    if not ok:
                        # 文件超限/落盘失败：回滚已保存的题目，
                        # 避免"报错但题目已存在"的部分成功
                        db.session.delete(question)
                        db.session.commit()
                        raise ValueError('Python文件不能超过20MB')

                    # 检查是否已存在文件记录
                    existing_file = PythonFile.query.filter_by(question_id=question.id).first()
                    if existing_file:
                        delete_file_from_disk(existing_file.file_path)
                        existing_file.file_name = filename
                        existing_file.file_path = rel_path
                    else:
                        # 创建新文件记录
                        python_file_record = PythonFile(
                            question_id=question.id,
                            file_name=filename,
                            file_path=rel_path
                        )
                        db.session.add(python_file_record)

                    db.session.commit()
                    current_app.logger.info(f"Python文件已上传: question_id={question.id}, file={filename}")

            # 日志记录
            current_app.logger.info(f"题目添加成功: ID={question.id}, 类型={question_type}")
            _touch_exam_list_cache()

            # 对AJAX请求返回JSON响应
            if is_ajax:
                return jsonify({
                    'success': True,
                    'msg': '题目添加成功',
                    'question_id': question.id,
                    'redirect': url_for('questions.admin_questions') if question_type != 'comprehensive' else url_for('questions.manage_sub_questions', question_id=question.id)
                }), 200

            # 对普通请求使用flash消息和重定向
            flash('题目添加成功')

            # 如果是综合题，重定向到管理小题页
            if question_type == 'comprehensive':
                return redirect(url_for('questions.manage_sub_questions', question_id=question.id))

            return redirect(url_for('questions.admin_questions'))
        except Exception as e:
            # 错误日志
            current_app.logger.error(f"添加题目失败: {str(e)}", exc_info=True)

            # 对AJAX请求返回JSON错误
            if is_ajax:
                return jsonify({
                    'success': False,
                    'msg': '添加题目失败'
                }), 500

            # 对普通请求使用flash消息
            flash('添加题目失败')
            return redirect(url_for('questions.add_question'))

    # GET请求，渲染添加题目页（排除外链试卷）
    exams = _get_non_link_exams()
    return render_template('add_question.html', exams=exams)


@questions_bp.route('/admin/questions/edit/<int:question_id>', methods=['GET', 'POST'])
@admin_login_required
def edit_question(question_id):
    """
    @function edit_question
    @brief 编辑题目
    @param question_id 题目ID
    @return 渲染edit_question.html模板或处理编辑请求
    """
    question = db.get_or_404(Question, question_id)

    if request.method == 'POST':
        # 检查是否是AJAX请求（Werkzeug 3 已移除 request.is_xhr，仅用请求头判断）
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

        # 获取表单数据
        exam_id = request.form.get('exam_id', type=int)
        content = request.form.get('content', '').strip()
        options = request.form.get('options', '')
        answer = request.form.get('answer', '').strip()
        score = request.form.get('score', type=float, default=1.0)

        # 分值校验：NaN/Infinity/负数/0 会污染成绩统计与总分计算，拒绝保存
        if not _is_valid_score(score):
            if is_ajax:
                return jsonify({
                    'success': False,
                    'msg': '分值必须为正数'
                }), 400
            flash('分值必须为正数')
            return redirect(url_for('questions.edit_question', question_id=question_id))

        if not content:
            # exam_id 可选（来源卷，可空=仅题库）
            if is_ajax:
                return jsonify({
                    'success': False,
                    'msg': '请填写完整的题目信息'
                }), 400
            flash('请填写完整的题目信息')
            return redirect(url_for('questions.edit_question', question_id=question_id))

        try:
            # 在考锁定：考试进行中不得改题干/答案/分值（学生在考的卷面
            # 与交卷判分必须使用同一份题目对象）
            _lock_msg = _question_lock_message(question)
            if _lock_msg:
                flash(_lock_msg, 'danger')
                return redirect(url_for('questions.edit_question',
                                        question_id=question_id))
            # 解耦保护：改"来源卷"触发重挂，关联卷已有成绩则拒绝
            #（防"分数在、题目缺失"的破损成绩单）。真实归属在
            # exam_question 中间表；只看 question.exam_id 会把
            # “来源为空、已组卷”的题挂成多卷。
            _old_exam_id = question.exam_id
            from app.models import ExamQuestion as _EQEdit
            _linked_ids = [r[0] for r in db.session.query(_EQEdit.exam_id)
                           .filter_by(question_id=question.id).all()]
            _move_needed = (_old_exam_id != exam_id
                            or bool(set(_linked_ids) - ({exam_id} if exam_id else set())))
            if _move_needed and _question_has_result(question):
                flash('该题所属试卷已有成绩记录，禁止更改归属；如需调整请先删除相关成绩',
                      'danger')
                return redirect(url_for('questions.edit_question',
                                        question_id=question_id))
            if _move_needed:
                # 所有受影响的卷（当前关联/来源/目标）不能已有成绩/收卷/在考
                from app.blueprints.exam_management import exam_compose_lock_message
                _affected_exams = set(_linked_ids)
                if _old_exam_id:
                    _affected_exams.add(_old_exam_id)
                if exam_id:
                    _affected_exams.add(exam_id)
                for _eid in sorted(_affected_exams):
                    lock_msg = exam_compose_lock_message(_eid)
                    if lock_msg:
                        flash(f'相关试卷不可调整：{lock_msg}', 'danger')
                        return redirect(url_for('questions.edit_question',
                                                question_id=question_id))
            if (question.question_type != 'comprehensive'
                    and abs((question.score or 0) - score) > 1e-9
                    and _question_has_result(question)):
                flash('该题所属试卷已有成绩记录，禁止修改分值（会改变试卷满分）；'
                      '题干/选项等仍可修改', 'danger')
                return redirect(url_for('questions.edit_question',
                                        question_id=question_id))
            question.exam_id = exam_id
            question.content = content
            question.options = normalize_options(options)
            question.answer = answer
            question.score = score

            # 综合题父题分值强制=子题分值之和：组卷总分按 sum(question.score)
            # 汇总，考试页/判分按子题求和——此前编辑页允许改父题分值导致
            # 两端口径分叉（组卷页显示 20 分、考试页按子题 10 分）。
            # 管理子题端点（manage_sub_questions）按同一口径维护父题分值
            if question.question_type == 'comprehensive':
                question.score = db.session.query(
                    func.coalesce(func.sum(SubQuestion.score), 0)
                ).filter(SubQuestion.question_id == question.id).scalar() or 0

            # 处理选项图片
            image_options = request.form.get('image_options')
            if image_options:
                current_app.logger.info(f"更新图片选项: {image_options}")
                question.image_options = image_options

            # Python填空题特殊处理
            if question.question_type == 'python_fill':
                python_answers = request.form.get('python_answers', '')
                question.python_answers = python_answers

            # 综合题特殊处理
            if question.question_type == 'comprehensive':
                background = request.form.get('background', '').strip()
                question.background = background
                footer_content = request.form.get('footer_content', '').strip()
                question.footer_content = footer_content
                current_app.logger.info(f"更新综合题背景: {background}")

            from app.models import (link_question_to_exam,
                                    unlink_question_from_exam)
            if _move_needed:
                for _eid in _linked_ids:
                    if _eid != exam_id:
                        unlink_question_from_exam(question.id, _eid)
                if exam_id and exam_id not in _linked_ids:
                    # 外链卷互斥校验：目标卷已有 link 题则不允许挂入普通题
                    if question.question_type != 'link' and _has_link_question(exam_id):
                        db.session.rollback()
                        msg = '目标试卷已为外链试卷，不可加入其他试题'
                        if is_ajax:
                            return jsonify({'success': False, 'msg': msg}), 400
                        flash(msg)
                        return redirect(url_for('questions.edit_question',
                                                question_id=question_id))
                    link_question_to_exam(question.id, exam_id)
                # 重排受影响卷序号保持紧凑
                from app.models import resequence_exam
                for _eid in {*_linked_ids, *([exam_id] if exam_id else [])}:
                    if _eid != exam_id:
                        resequence_exam(_eid)
                if exam_id:
                    resequence_exam(exam_id)

            db.session.commit()
            _touch_exam_list_cache()

            # 根据请求类型返回不同的响应
            if is_ajax:
                return jsonify({
                    'success': True,
                    'msg': '题目修改成功',
                    'redirect': url_for('questions.admin_questions')
                })

            flash('题目修改成功')
            current_app.logger.info(f"题目修改成功: ID={question.id}")

            return redirect(url_for('questions.admin_questions'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"修改题目失败: {str(e)}", exc_info=True)

            if is_ajax:
                return jsonify({
                    'success': False,
                    'msg': '修改题目失败'
                }), 500

            flash('修改题目失败')
            return redirect(url_for('questions.edit_question', question_id=question_id))

    # GET请求，渲染编辑题目页
    exams = Exam.query.order_by(Exam.name).all()
    return render_template('edit_question.html', question=question, exams=exams)


@questions_bp.route('/admin/questions/delete/<int:question_id>', methods=['POST'])
@admin_login_required
def delete_question(question_id):
    """
    @function delete_question
    @brief 删除题目
    @param question_id 题目ID
    @return JSON响应
    """
    question = db.get_or_404(Question, question_id)

    # 有成绩记录时拒绝删除（与 delete_sub_question 策略一致）：已收卷成绩
    # 中该题分数仍计入 total_score，但题目行删除后明细页/趋势页无法加载
    # 题目内容 → "题目缺失但分数在"，成绩单不完整。
    if _question_has_result(question):
        return jsonify({
            'success': False,
            'msg': '该题关联的试卷已有学生成绩记录，删除后已存成绩会不完整，请先删除相关试卷的成绩'
        }), 400

    try:
        # 获取题目类型用于日志记录
        question_type = question.question_type

        # 先收集待删磁盘文件，DB 提交成功后再删盘：此前 commit 前删文件，
        # 提交失败回滚后题目/答案记录仍在而文件已 404。
        orphan_paths = []
        from app.models import PythonFile
        python_files = PythonFile.query.filter_by(question_id=question_id).all()
        for pf in python_files:
            if pf.file_path:
                orphan_paths.append(pf.file_path)
            db.session.delete(pf)
        # 学生提交的 Python 答案记录 FK 指向 question.id 且无级联，
        # 不清理会在 commit 时抛 IntegrityError 导致删除失败
        py_answers = PythonAnswer.query.filter_by(question_id=question_id).all()
        for pa in py_answers:
            if pa.file_path:
                orphan_paths.append(pa.file_path)
        PythonAnswer.query.filter_by(question_id=question_id).delete(synchronize_session=False)

        # 删除题目
        db.session.delete(question)
        db.session.commit()
        for rel_path in orphan_paths:
            try:
                from app.utils import delete_file_from_disk
                delete_file_from_disk(rel_path)
            except Exception:
                current_app.logger.debug('删除题目关联文件失败（忽略）: %s', rel_path)
        _touch_exam_list_cache()

        current_app.logger.info(f"题目删除成功: ID={question_id}, 类型={question_type}")

        # 返回JSON响应以支持AJAX删除
        return jsonify({
            'success': True,
            'msg': '题目删除成功'
        })
    except Exception as e:
        # 必须 rollback：否则 session 进入 PendingRollbackError，
        # 同请求内后续任何 DB 操作（含日志写入）都会连锁报错
        db.session.rollback()
        current_app.logger.error(f"删除题目失败: {str(e)}", exc_info=True)

        # 返回JSON响应以支持AJAX删除
        return jsonify({
            'success': False,
            'msg': '删除题目失败'
        })


@questions_bp.route('/admin/questions/batch_delete', methods=['POST'])
@admin_login_required
def batch_delete_questions():
    """
    @function batch_delete_questions
    @brief 批量删除题目
    @return 重定向回题库管理页面
    """
    # 获取要删除的题目ID列表
    question_ids = request.form.getlist('question_ids')

    # 获取筛选参数，用于返回相同的筛选视图
    exam_id = request.form.get('exam_id')
    question_type = request.form.get('question_type')

    if not question_ids:
        flash('未选择任何题目', 'warning')
        redirect_url = url_for('questions.admin_questions')
        if exam_id:
            redirect_url = f"{redirect_url}?exam_id={exam_id}"
            if question_type:
                redirect_url = f"{redirect_url}&question_type={question_type}"
        elif question_type:
            redirect_url = f"{redirect_url}?question_type={question_type}"
        return redirect(redirect_url)

    deleted_count = 0
    error_count = 0
    deleted_questions = []
    disk_paths = []

    try:
        # 成绩保护批量预取：一次查出「所属卷已有成绩」的题目 id 集合，
        # 避免循环内每题 2 次查询（200 题 = 400 次 SQL）
        from app.models import ExamQuestion as _EQ, Result as _Result
        locked_qids = {
            qid for (qid,) in db.session.query(_EQ.question_id).filter(
                _EQ.exam_id.in_(db.session.query(_Result.exam_id))
            ).distinct().all()
        }
        for question_id in question_ids:
            try:
                question_id = int(question_id)
                question = db.session.get(Question, question_id)

                if question:
                    # 成绩保护：所属试卷已有成绩记录的题目跳过（与单删
                    # 路径/delete_sub_question 策略一致）
                    if question.id in locked_qids:
                        error_count += 1
                        current_app.logger.warning(
                            f"题目ID {question.id} 所属试卷已有成绩记录，跳过删除")
                        continue
                    question_info = {
                        'id': question.id,
                        'type': question.question_type,
                        'content': question.content[:30] + ('...' if len(question.content) > 30 else '')
                    }
                    deleted_questions.append(question_info)
                    # 清理 Python 参考文件（FK 指向 question.id 且无级联，
                    # 不清理会在 commit 时抛 IntegrityError 使删除失败）。
                    # 磁盘文件在 commit 成功后统一删：先删文件再 commit 时
                    # 一旦回滚，记录仍在而文件已丢。
                    from app.models import PythonFile
                    python_files = PythonFile.query.filter_by(question_id=question.id).all()
                    for pf in python_files:
                        if pf.file_path:
                            disk_paths.append(pf.file_path)
                        db.session.delete(pf)
                    # 学生提交的 Python 答案记录同样指向 question.id，一并清理
                    py_answers = PythonAnswer.query.filter_by(question_id=question.id).all()
                    disk_paths.extend(pa.file_path for pa in py_answers if pa.file_path)
                    PythonAnswer.query.filter_by(question_id=question.id).delete(synchronize_session=False)
                    db.session.delete(question)
                    deleted_count += 1
                else:
                    error_count += 1
                    current_app.logger.warning(f"题目ID {question_id} 不存在")
            except Exception as e:
                error_count += 1
                current_app.logger.error(f"处理删除题目ID {question_id} 时出错: {str(e)}")

        # 一次性提交所有删除
        if deleted_count > 0:
            db.session.commit()
            # DB 提交成功后再删磁盘文件（回滚时记录仍在，文件不能已删）
            from app.utils import delete_file_from_disk
            for rel in disk_paths:
                try:
                    delete_file_from_disk(rel)
                except Exception:
                    current_app.logger.debug(
                        '删除题目关联磁盘文件失败（忽略）: %s', rel)
            # 失效试卷列表缓存：题数变化（此前单题增删改/导入均失效，唯批量
            # 删除遗漏——60s 内 api:exams:list:admin 的 question_count 为旧值）
            _touch_exam_list_cache()
            current_app.logger.info(f"批量删除题目完成: 共{deleted_count}个题目已删除")
        else:
            db.session.rollback()

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"批量删除题目失败: {str(e)}", exc_info=True)
        flash('批量删除失败', 'danger')
        redirect_url = url_for('questions.admin_questions')
        if exam_id:
            redirect_url = f"{redirect_url}?exam_id={exam_id}"
            if question_type:
                redirect_url = f"{redirect_url}&question_type={question_type}"
        elif question_type:
            redirect_url = f"{redirect_url}?question_type={question_type}"
        return redirect(redirect_url)

    # 记录批量删除操作
    if deleted_questions:
        deleted_contents = ", ".join([q['content'] for q in deleted_questions[:5]])
        if len(deleted_questions) > 5:
            deleted_contents += f" 等{len(deleted_questions)}个题目"
        current_app.logger.info(f"管理员批量删除题目成功：共{deleted_count}个题目，内容：{deleted_contents}")

    if deleted_count > 0:
        flash(f'已成功删除 {deleted_count} 个题目', 'success')
    if error_count > 0:
        flash(f'删除过程中有 {error_count} 个题目出错', 'warning')

    # 保留原来的筛选参数
    redirect_url = url_for('questions.admin_questions')
    if exam_id:
        redirect_url = f"{redirect_url}?exam_id={exam_id}"
        if question_type:
            redirect_url = f"{redirect_url}&question_type={question_type}"
    elif question_type:
        redirect_url = f"{redirect_url}?question_type={question_type}"

    return redirect(redirect_url)


@questions_bp.route('/admin/questions/manage_sub/<int:question_id>', methods=['GET', 'POST'])
@admin_login_required
def manage_sub_questions(question_id):
    """
    @function manage_sub_questions
    @brief 管理综合题的小题
    @param question_id 综合题ID
    @return 渲染manage_sub_questions.html模板
    """
    question = db.get_or_404(Question, question_id)

    # 确保是综合题
    if question.question_type != 'comprehensive':
        flash('只能为综合题管理小题')
        return redirect(url_for('questions.admin_questions'))

    if request.method == 'POST':
        # 结构改动（排序/添加小题）会改变试卷满分：在考/收卷期间锁定
        _lock_msg = _question_lock_message(question, include_collected=True)
        if _lock_msg:
            flash(_lock_msg, 'danger')
            return redirect(url_for('questions.manage_sub_questions',
                                    question_id=question_id))
        # 处理排序请求
        if 'orders' in request.form:
            try:
                orders = request.form.get('orders')
                orders_data = json.loads(orders) if orders else {}

                # 更新所有小题的顺序
                for sub_id, order in orders_data.items():
                    sub_question = db.session.get(SubQuestion, int(sub_id))
                    if sub_question and sub_question.question_id == question_id:
                        sub_question.order = order

                db.session.commit()
                flash('小题顺序更新成功')
                current_app.logger.info(f"小题顺序更新成功: 综合题ID={question_id}")
            except Exception as e:
                flash('更新小题顺序失败')
                current_app.logger.error(f"更新小题顺序失败: {str(e)}", exc_info=True)

            return redirect(url_for('questions.manage_sub_questions', question_id=question_id))

        # 处理添加小题请求
        sub_type = request.form.get('sub_type')
        sub_content = request.form.get('sub_content', '').strip()
        sub_options = request.form.get('sub_options', '')
        sub_image_options = request.form.get('sub_image_options', '')
        sub_answer = request.form.get('sub_answer', '').strip()
        sub_score = request.form.get('sub_score', type=float, default=1.0)
        # 分值校验：NaN/Infinity/负数/0 会污染综合题总分，拒绝保存
        if not _is_valid_score(sub_score):
            flash('分值必须为正数')
            return redirect(url_for('questions.manage_sub_questions', question_id=question_id))
        sub_image_url = request.form.get('sub_image_url', '').strip()

        # 获取最大的order
        max_order = db.session.query(func.max(SubQuestion.order)).filter(
            SubQuestion.question_id == question_id).scalar() or 0
        sub_order = max_order + 1

        if not sub_type or not sub_content or not sub_answer:
            flash('请填写完整的小题信息')
            return redirect(url_for('questions.manage_sub_questions', question_id=question_id))
        if sub_type not in _SUB_QUESTION_TYPES:
            flash('不支持的小题题型')
            return redirect(url_for('questions.manage_sub_questions', question_id=question_id))
        # 加小题会改变父题分值（= 试卷满分）：与删小题同一守卫
        if _question_has_result(question):
            flash('该题所属试卷已有成绩记录，禁止添加小题；如需调整请先删除相关成绩')
            return redirect(url_for('questions.manage_sub_questions', question_id=question_id))

        try:
            # 添加小题
            sub_question = SubQuestion(
                question_id=question_id,
                question_type=sub_type,
                content=sub_content,
                options=normalize_options(sub_options),
                image_options=sub_image_options,
                answer=sub_answer,
                score=sub_score,
                order=sub_order,
                image_url=sub_image_url if sub_image_url else None
            )

            db.session.add(sub_question)

            # 更新综合题总分
            question.score = db.session.query(func.sum(SubQuestion.score)).filter(
                SubQuestion.question_id == question_id).scalar() or 0

            db.session.commit()
            flash('小题添加成功')
            current_app.logger.info(f"小题添加成功: 综合题ID={question_id}, 小题ID={sub_question.id}, 当前总分={question.score}")
        except Exception as e:
            # 必须回滚：否则下面重新查询小题列表时在失败事务上抛
            # PendingRollbackError，整页 500
            db.session.rollback()
            flash('添加小题失败')
            current_app.logger.error(f"添加小题失败: {str(e)}", exc_info=True)

    # 获取所有小题
    sub_questions = SubQuestion.query.filter_by(question_id=question_id).order_by(SubQuestion.order).all()

    return render_template('manage_sub_questions.html',
                           question=question,
                           sub_questions=sub_questions,
                           title=f'小题管理 - {question.content[:20] or f"题{question.id}"}')


@questions_bp.route('/admin/questions/delete_sub/<int:sub_id>', methods=['POST'])
@admin_login_required
def delete_sub_question(sub_id):
    """
    @function delete_sub_question
    @brief 删除小题
    @param sub_id 小题ID
    @return 重定向到小题管理页面
    """
    sub_question = db.get_or_404(SubQuestion, sub_id)
    question_id = sub_question.question_id
    parent_question = db.session.get(Question, question_id)
    _lock_msg = (_question_lock_message(parent_question, include_collected=True)
                 if parent_question else None)
    if _lock_msg:
        flash(_lock_msg, 'danger')
        return redirect(url_for('questions.manage_sub_questions',
                                question_id=question_id))

    # 删除已提交过的小题会导致该试卷已存成绩总分被静默扣减
    # （submit_grading 重算聚合分时仅统计仍存在的小题）。有成绩记录时拒绝删除。
    from app.models import Question as _Q
    try:
        parent = db.session.get(_Q, question_id)
        if parent and _question_has_result(parent):
            flash('该综合题已有学生成绩记录，删除小题会导致已批改成绩总分变化，请先删除该试卷的成绩', 'danger')
            return redirect(url_for('questions.manage_sub_questions', question_id=question_id))
    except Exception:
        pass

    try:
        db.session.delete(sub_question)
        db.session.commit()

        # 删除小题后，重新计算综合题总分
        question = db.session.get(Question, question_id)
        if question and question.question_type == 'comprehensive':
            total_score = db.session.query(func.sum(SubQuestion.score)).filter(
                SubQuestion.question_id == question_id).scalar() or 0
            question.score = total_score
            db.session.commit()
            current_app.logger.info(f"更新综合题总分: ID={question_id}, 新总分={total_score}")

        flash('小题删除成功')
        current_app.logger.info(f"小题删除成功: ID={sub_id}, 综合题ID={question_id}")
    except Exception as e:
        db.session.rollback()
        flash('删除小题失败')
        current_app.logger.error(f"删除小题失败: {str(e)}", exc_info=True)

    return redirect(url_for('questions.manage_sub_questions', question_id=question_id))


@questions_bp.route('/admin/questions/upload_img', methods=['POST'])
@admin_login_required
def upload_question_image():
    """
    @function upload_question_image
    @brief 处理题目图片上传
    @return JSON响应
    """
    MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB
    ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}

    try:
        current_app.logger.info("处理题目图片上传请求")

        # 检查请求的内容类型
        if not request.content_type or 'multipart/form-data' not in request.content_type.lower():
            current_app.logger.warning(f"不支持的内容类型: {request.content_type}")
            return jsonify({'success': False, 'msg': '不支持的请求类型'}), 400

        # 记录请求中的所有字段（用于调试）
        current_app.logger.debug(f"上传图片请求字段: {list(request.files.keys())}")

        # 检查是否有文件，同时支持'img'和'image'字段
        if 'img' not in request.files and 'image' not in request.files:
            current_app.logger.warning("未找到上传的图片文件")
            return jsonify({'success': False, 'msg': '未找到上传的图片文件'}), 400

        # 获取图片文件，优先使用'image'字段
        img_file = request.files.get('image') or request.files.get('img')

        if not img_file or not img_file.filename:
            current_app.logger.warning("未选择文件或文件名为空")
            return jsonify({'success': False, 'msg': '未选择文件'}), 400

        # 检查文件大小
        img_file.seek(0, 2)  # 定位到文件末尾
        file_size = img_file.tell()
        img_file.seek(0)  # 重置到文件开头

        if file_size > MAX_IMAGE_SIZE:
            current_app.logger.warning(f"图片文件过大: {file_size} bytes, 限制: {MAX_IMAGE_SIZE} bytes")
            return jsonify({'success': False, 'msg': f'图片文件不能超过 {MAX_IMAGE_SIZE // (1024*1024)}MB'}), 400

        # 检查文件类型（扩展名和内容）
        if not allowed_file(img_file.filename):
            current_app.logger.warning(f"不支持的文件类型: {img_file.filename}")
            return jsonify({'success': False, 'msg': '不支持的文件类型'}), 400

        # 额外验证文件扩展名
        file_ext = img_file.filename.rsplit('.', 1)[-1].lower() if '.' in img_file.filename else ''
        if file_ext not in ALLOWED_IMAGE_EXTENSIONS:
            current_app.logger.warning(f"不允许的图片格式: {file_ext}")
            return jsonify({'success': False, 'msg': f'只支持 {", ".join(ALLOWED_IMAGE_EXTENSIONS)} 格式'}), 400

        # 内容魔数校验（与网盘/作品等上传点对齐）：伪装 .png 的任意内容
        # 拒绝入库。本目录为公开内联目录，纵深防御不依赖 MIME 猜测
        from app.utils import validate_image_magic
        magic_head = img_file.stream.read(12)
        img_file.stream.seek(0)
        if not validate_image_magic(magic_head, img_file.filename):
            current_app.logger.warning(f"题目图片魔数校验失败: {img_file.filename}")
            return jsonify({'success': False, 'msg': '文件内容不是有效的图片'}), 400

        # 安全文件名
        filename = secure_filename(img_file.filename)

        # 生成唯一文件名
        unique_filename = f"{uuid.uuid4().hex}_{filename}"

        # 保存文件路径
        save_path = os.path.join(_BASE, 'static', 'question_img', unique_filename)

        # 确保目录存在
        os.makedirs(os.path.join(_BASE, 'static', 'question_img'), exist_ok=True)

        # 保存文件
        img_file.save(save_path)
        # Pillow 压缩（宽 >800px 等比缩到 800、JPEG quality 80）：
        # 此前原图直存，5MB 相机原图 × 数百题占用显著、页面全量传原图；
        # 压缩失败保留原图不影响上传
        from app.utils import compress_image_file
        compress_image_file(save_path)
        current_app.logger.info(f"图片保存成功: {save_path}, 大小: {file_size} bytes")

        # 返回图片URL
        img_url = f"/static/question_img/{unique_filename}"

        return jsonify({
            'success': True,
            'url': img_url,
            'msg': '图片上传成功'
        }), 200

    except Exception as e:
        current_app.logger.error(f"图片上传失败: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'msg': '上传失败'}), 500


@questions_bp.route('/admin/questions/import_excel', methods=['POST'])
@admin_login_required
def import_excel():
    """
    @function import_excel
    @brief 批量导入单选题
    @return JSON响应
    """
    try:
        current_app.logger.info("开始处理Excel导入请求")

        # 检查是否有文件
        if 'excel_file' not in request.files:
            current_app.logger.warning("未找到上传的Excel文件")
            flash('未找到Excel文件')
            return redirect(url_for('questions.admin_questions'))

        excel_file = request.files['excel_file']
        if not excel_file or not excel_file.filename:
            current_app.logger.warning("未选择文件或文件名为空")
            flash('未选择Excel文件')
            return redirect(url_for('questions.admin_questions'))

        # 检查文件类型
        if not excel_file.filename.endswith(('.xlsx', '.xls')):
            current_app.logger.warning(f"不支持的文件类型: {excel_file.filename}")
            flash('请上传xlsx或xls格式的Excel文件')
            return redirect(url_for('questions.admin_questions'))

        # 获取试卷ID
        exam_id = request.form.get('exam_id', type=int)
        if not exam_id:
            current_app.logger.warning("未提供有效的试卷ID")
            flash('请选择所属试卷')
            return redirect(url_for('questions.admin_questions'))

        # 验证试卷是否存在
        exam = db.session.get(Exam, exam_id)
        if not exam:
            current_app.logger.warning(f"试卷ID不存在: {exam_id}")
            flash('所选试卷不存在')
            return redirect(url_for('questions.admin_questions'))
        # 与单题添加同口径：外链卷不可再加题；已有成绩/已收卷/在考的卷锁定
        if _has_link_question(exam_id):
            flash('该试卷已设置为外链试卷，不可再添加其他试题')
            return redirect(url_for('questions.admin_questions'))
        from app.blueprints.exam_management import exam_compose_lock_message
        lock_msg = exam_compose_lock_message(exam_id)
        if lock_msg:
            flash(lock_msg)
            return redirect(url_for('questions.admin_questions'))

        # 加载Excel文件
        try:
            workbook = openpyxl.load_workbook(excel_file)
            sheet = workbook.active
        except Exception as e:
            current_app.logger.error(f"Excel文件加载失败: {str(e)}", exc_info=True)
            flash('Excel文件加载失败')
            return redirect(url_for('questions.admin_questions'))

        # 提取数据并创建题目
        success_count = 0
        error_count = 0
        error_messages = []

        # 从第2行开始（跳过标题行）
        for row_idx, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), 2):
            if not row[0]:  # 跳过空行
                continue

            try:
                content = str(row[0]).strip()
                options = str(row[1]).strip() if len(row) > 1 and row[1] else ""
                answer = str(row[2]).strip() if len(row) > 2 and row[2] else ""
                try:
                    score = float(row[3]) if len(row) > 3 and row[3] else 1.0
                except (TypeError, ValueError):
                    score = float('nan')

                # 验证必填字段
                if not content or not answer:
                    error_count += 1
                    error_messages.append(f"第{row_idx}行: 题目内容或答案为空")
                    continue

                # 分值校验：NaN/Infinity/负数/0 拒绝入库并跳过该行
                if not _is_valid_score(score):
                    error_count += 1
                    error_messages.append(f"第{row_idx}行: 分值无效（必须为正数）")
                    continue

                # 创建题目
                question = Question(
                    exam_id=exam_id,
                    question_type="single",
                    content=content,
                    options=normalize_options(options),
                    answer=answer,
                    score=score
                )

                db.session.add(question)
                success_count += 1

            except Exception as e:
                error_count += 1
                error_messages.append(f"第{row_idx}行")
                current_app.logger.error(f"处理第{row_idx}行时出错: {str(e)}", exc_info=True)

        # 提交数据库更改
        if success_count > 0:
            db.session.commit()
            _touch_exam_list_cache()
            current_app.logger.info(f"成功导入 {success_count} 个题目")

            # 记录日志（与全站 Log.time 一致：本地时间，便于管理端直接阅读）
            log = Log(
                user_id=0,
                user_type='admin',
                action='批量导入题目',
                detail=f'试卷: {exam.name}, 成功: {success_count}, 失败: {error_count}',
                time=datetime.now()
            )
            db.session.add(log)
            db.session.commit()

        if error_count > 0:
            flash(f'已导入 {success_count} 个题目，{error_count} 个题目导入失败')
            for msg in error_messages[:5]:  # 只显示前5个错误
                flash(msg)
            if len(error_messages) > 5:
                flash(f'... 还有 {len(error_messages) - 5} 个错误')
        else:
            flash(f'成功导入 {success_count} 个题目')

        return redirect(url_for('questions.admin_questions'))

    except Exception as e:
        current_app.logger.error(f"Excel导入失败: {str(e)}", exc_info=True)
        flash('导入失败')
        return redirect(url_for('questions.admin_questions'))


@questions_bp.route('/admin/questions/download_template')
@admin_login_required
def download_template():
    """
    @function download_template
    @brief 下载题目导入模板
    @return 发送Excel模板文件
    """
    try:
        # 创建工作簿
        wb = Workbook()
        ws = wb.active
        ws.title = "单选题导入模板"

        # 添加标题
        ws.append(["题目内容(必填)", "选项(竖线|分隔)", "答案(A/B/C/D,必填)", "分值(数字,必填)"])

        # 设置列宽
        ws.column_dimensions['A'].width = 40
        ws.column_dimensions['B'].width = 30
        ws.column_dimensions['C'].width = 20
        ws.column_dimensions['D'].width = 15

        # 添加示例数据
        ws.append(["以下哪个是Python的内置数据类型?", "Java|Python|C++|HTML", "B", 2])
        ws.append(["Flask是一个什么类型的框架?", "Web框架|游戏框架|数据分析框架|机器学习框架", "A", 2])

        # 保存到内存中
        output = BytesIO()
        wb.save(output)
        output.seek(0)

        # 发送文件
        return send_file(
            output,
            as_attachment=True,
            download_name="question_import_template.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except Exception as e:
        current_app.logger.error(f"模板下载失败: {str(e)}", exc_info=True)
        flash('模板下载失败')
        return redirect(url_for('questions.admin_questions'))


@questions_bp.route('/admin/questions/add_link', methods=['POST'])
@admin_login_required
def add_question_link():
    """
    @function add_question_link
    @brief 添加外链资源题目
    @return 重定向到题库管理页面
    """
    try:
        exam_id = request.form.get('exam_id', type=int)
        external_link = request.form.get('external_link', '').strip()

        if not exam_id or not external_link:
            flash('请填写完整的外链信息')
            return redirect(url_for('questions.admin_questions'))

        # 检查该试卷是否已有外链
        if _has_link_question(exam_id):
            flash('该试卷已设置为外链试卷，不可重复添加')
            return redirect(url_for('questions.admin_questions'))

        # 检查该试卷是否已有其他题目
        from app.models import ExamQuestion
        existing_questions = (db.session.query(ExamQuestion.id)
                              .filter_by(exam_id=exam_id).first())
        if existing_questions:
            flash('该试卷已有试题，不可设为外链试卷。请选择空试卷或创建新试卷。')
            return redirect(url_for('questions.admin_questions'))

        # 组卷锁：与其余建入试卷路径（add_question/import_excel/edit_question/
        # api_questions）同口径。此前外链题未过锁，学生已开考的空卷可被写入
        # 外链题绕过「在考锁定」
        from app.blueprints.exam_management import exam_compose_lock_message
        _lock_msg = exam_compose_lock_message(exam_id)
        if _lock_msg:
            flash(_lock_msg)
            return redirect(url_for('questions.admin_questions'))

        # 确保链接以http://或https://开头
        if not (external_link.startswith('http://') or external_link.startswith('https://')):
            external_link = 'http://' + external_link

        # 创建外链题目 - 将链接存储在content中
        question = Question(
            exam_id=exam_id,
            question_type="link",
            content=external_link,
            options="",
            answer="",
            score=0
        )

        db.session.add(question)
        db.session.commit()

        flash(f'外链试卷添加成功！试卷"{question.exam.name}"已生成为外链试卷，不可再添加其他试题。学生端点击该试卷将直接打开网址。')
        return redirect(url_for('questions.admin_questions'))
    except Exception as e:
        current_app.logger.error(f"添加外链试卷失败: {str(e)}", exc_info=True)
        flash('添加外链试卷失败')
        return redirect(url_for('questions.admin_questions'))


@questions_bp.route('/admin/questions/export/<int:exam_id>')
@admin_login_required
def export_questions(exam_id):
    """
    @function export_questions
    @brief 导出指定试卷的题目为Excel文件
    @param exam_id 试卷ID
    @return 发送Excel文件
    """
    try:
        # 检查试卷是否存在
        exam = db.get_or_404(Exam, exam_id)

        # 获取试卷的所有题目（题型分组序，与考试/成绩页一致）
        from app.models import exam_questions_flat
        questions = exam_questions_flat(exam_id)

        # 创建工作簿
        wb = Workbook()
        ws = wb.active
        ws.title = exam.name

        # 添加标题
        ws.append(["ID", "题型", "题目内容", "选项", "答案", "分值"])

        # 设置列宽
        ws.column_dimensions['A'].width = 5
        ws.column_dimensions['B'].width = 15
        ws.column_dimensions['C'].width = 40
        ws.column_dimensions['D'].width = 30
        ws.column_dimensions['E'].width = 20
        ws.column_dimensions['F'].width = 10

        # 添加数据
        for q in questions:
            question_type = {
                'single': '单选题',
                'multiple': '多选题',
                'judge': '判断题',
                'python_fill': 'Python填空题',
                'comprehensive': '综合题',
                'link': '外链试卷'
            }.get(q.question_type, q.question_type)

            ws.append([
                q.id,
                question_type,
                q.content,
                q.options,
                q.answer,
                q.score
            ])

        # 保存到内存中
        output = BytesIO()
        wb.save(output)
        output.seek(0)

        # 发送文件
        return send_file(
            output,
            as_attachment=True,
            download_name=f"{exam.name}_题库导出_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except Exception as e:
        current_app.logger.error(f"题库导出失败: {str(e)}", exc_info=True)
        flash('题库导出失败')
        return redirect(url_for('exam_management.admin_exams'))


@questions_bp.route('/admin/questions/upload_python_file', methods=['POST'])
@admin_login_required
def upload_python_file():
    """
    @function upload_python_file
    @brief 处理Python文件上传到题目
    @return JSON响应
    """
    MAX_PYTHON_FILE_SIZE = 2 * 1024 * 1024  # 2MB

    try:
        current_app.logger.info("处理Python文件上传请求")

        # 检查请求的内容类型
        if not request.content_type or 'multipart/form-data' not in request.content_type.lower():
            current_app.logger.warning(f"不支持的内容类型: {request.content_type}")
            return jsonify({'success': False, 'msg': '不支持的请求类型'}), 400

        # 检查是否有文件
        if 'python_file' not in request.files:
            current_app.logger.warning("未找到上传的Python文件")
            return jsonify({'success': False, 'msg': '未找到上传的Python文件'}), 400

        # 获取文件
        file = request.files['python_file']
        question_id = request.form.get('question_id', type=int)
        file_path = request.form.get('python_file_path', '')

        if not file or not file.filename:
            current_app.logger.warning("未选择文件或文件名为空")
            return jsonify({'success': False, 'msg': '未选择文件'}), 400

        if not question_id:
            current_app.logger.warning("未提供题目ID")
            return jsonify({'success': False, 'msg': '未提供题目ID'}), 400

        # 检查题目是否存在
        question = db.get_or_404(Question, question_id)

        # 检查题目类型
        if question.question_type != 'python_fill':
            current_app.logger.warning(f"题目类型不是Python填空题 {question.question_type}")
            return jsonify({'success': False, 'msg': '只能为Python填空题上传文件'}), 400

        # 检查文件类型
        if not file.filename.lower().endswith('.py'):
            current_app.logger.warning(f"不支持的文件类型: {file.filename}")
            return jsonify({'success': False, 'msg': '请上传py文件'}), 400

        # 检查文件大小
        file.seek(0, 2)  # 定位到文件末尾
        file_size = file.tell()
        file.seek(0)  # 重置到文件开头

        if file_size > MAX_PYTHON_FILE_SIZE:
            current_app.logger.warning(f"Python文件过大: {file_size} bytes, 限制: {MAX_PYTHON_FILE_SIZE} bytes")
            return jsonify({'success': False, 'msg': f'Python文件不能超过 {MAX_PYTHON_FILE_SIZE // (1024*1024)}MB'}), 400

        if file_size == 0:
            current_app.logger.warning("Python文件为空")
            return jsonify({'success': False, 'msg': 'Python文件不能为空'}), 400

        # 读取文件内容进行基本验证（语法验证必须完整读入；此前读两遍，
        # 内存峰值 2× 文件大小——改为单次读取复用）
        try:
            file_content = file.read(MAX_PYTHON_FILE_SIZE + 1)
            if len(file_content) > MAX_PYTHON_FILE_SIZE:
                return jsonify({'success': False,
                                'msg': f'Python文件不能超过 {MAX_PYTHON_FILE_SIZE // (1024*1024)}MB'}), 400
            # 验证是否为有效的Python代码（尝试编译）
            compile(file_content, file.filename, 'exec')
        except SyntaxError as e:
            current_app.logger.warning(f"Python文件语法错误: {str(e)}")
            return jsonify({'success': False, 'msg': 'Python文件语法错误'}), 400
        except Exception as e:
            current_app.logger.warning(f"Python文件内容验证失败: {str(e)}")
            return jsonify({'success': False, 'msg': 'Python文件内容验证失败'}), 400

        # 使用原始文件路径或安全文件名
        filename = file_path if file_path else secure_filename(file.filename)

        # 保存到磁盘（复用验证时读取的内容，不再二次读取）
        rel_path = save_file_to_disk(file_content, 'python_files', filename)

        current_app.logger.info(f"使用文件名: {filename}, 原始文件名: {file.filename}, 提供的路径: {file_path}")

        # 检查是否已存在该题目的Python文件
        existing_file = PythonFile.query.filter_by(question_id=question_id).first()

        if existing_file:
            # 更新现有文件
            delete_file_from_disk(existing_file.file_path)
            existing_file.file_name = filename
            existing_file.file_path = rel_path
            db.session.commit()
            current_app.logger.info(f"更新题目Python文件: question_id={question_id}, file={filename}")
        else:
            # 创建新文件记录
            python_file = PythonFile(
                question_id=question_id,
                file_name=filename,
                file_path=rel_path
            )
            db.session.add(python_file)
            db.session.commit()
            current_app.logger.info(f"添加题目Python文件: question_id={question_id}, file={filename}")

        return jsonify({
            'success': True,
            'msg': '文件上传成功',
            'file_name': filename,
            'file_path': filename
        }), 200

    except Exception as e:
        current_app.logger.error(f"Python文件上传失败: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'msg': '上传失败'}), 500


@questions_bp.route('/admin/questions/save_blank_scores/<int:sub_id>', methods=['POST'])
@admin_login_required
def save_blank_scores(sub_id):
    """
    @function save_blank_scores
    @brief 保存填空题的每空分值
    @param sub_id 小题ID
    @return JSON响应
    """
    sub_question = db.get_or_404(SubQuestion, sub_id)
    # 逐空分值是判分口径的一部分：在考/收卷期间锁定
    _parent = db.session.get(Question, sub_question.question_id)
    _lock_msg = (_question_lock_message(_parent, include_collected=True)
                 if _parent else None)
    if _lock_msg:
        return jsonify({'success': False, 'message': _lock_msg}), 409

    try:
        data = request.get_json()
        scores = data.get('scores', [])

        # 逐项校验：非数值/NaN/Infinity/负数一律拒绝。
        # 此前仅校验总和，json.loads 接受 NaN 字面量时
        # abs(NaN - score) 恒为 NaN、NaN > 0.01 为 False → NaN/负数组合
        # 可绕过并污染 total_score（趋势/导出/批改全线异常）
        if not isinstance(scores, list) or not scores:
            return jsonify({'success': False, 'message': '分值数据格式无效'}), 400
        import math as _math
        for s in scores:
            if isinstance(s, bool) or not isinstance(s, (int, float)) \
                    or not _math.isfinite(s) or s < 0:
                return jsonify({'success': False, 'message': '分值必须为非负有限数值'}), 400
        # 空数数量必须与标准答案空数一致（防错位）
        blank_count = len((sub_question.answer or '').split('|')) \
            if sub_question.answer else 0
        if len(scores) != blank_count:
            return jsonify({
                'success': False,
                'message': f'分值数量({len(scores)})与填空数量({blank_count})不一致'
            }), 400

        # 验证分值总和是否等于小题分值
        total = sum(scores)
        if abs(total - sub_question.score) > 0.01:
            return jsonify({
                'success': False,
                'message': f'分值总和({total})与题目总分({sub_question.score})不一致'
            })

        # 保存分值
        sub_question.blank_scores = json.dumps(scores)
        db.session.commit()

        current_app.logger.info(f"填空题分值设置保存成功 小题ID={sub_id}, 分值{scores}")

        return jsonify({
            'success': True,
            'message': '分值设置保存成功'
        })
    except Exception as e:
        current_app.logger.error(f"保存填空题分值失败: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'message': '保存失败'
        })
