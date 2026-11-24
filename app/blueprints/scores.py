from flask import Blueprint, request, render_template, redirect, url_for, session, flash, send_file
from flask import current_app
from app.extensions import db
from app.models import Result, Exam, Question, SubQuestion, Student, PythonAnswer, ExamQuestion
from app.decorators import admin_login_required, login_required
from app.utils import measure_time, get_special_markers, excel_safe
from app.services.scoring_service import (
    JUDGE_TRUTHY, _normalize_choice_letter, _normalize_multi_answer)
from openpyxl import Workbook
from io import BytesIO
import json

scores_bp = Blueprint('scores', __name__, url_prefix='')


def load_python_attempt_set(exam_id):
    """返回该试卷 {(student_id, question_id)} 集合：有 PythonAnswer 作答
    记录的学生-题目对。

    python_fill 统计口径的唯一正确 attempt 判定——Result.scores 在交卷时
    对 python_fill 无条件写键（未作答也写 0 分），不能以 scores 有键判断
    "有作答"。api_trends / admin_trend / export_scores 三处共用，
    避免统计口径漂移。
    """
    # 归属看 exam_question 中间表（解耦后来源卷不再等于归属）
    py_q_ids = [
        qid for (qid,) in db.session.query(Question.id)
        .join(ExamQuestion, ExamQuestion.question_id == Question.id)
        .filter(ExamQuestion.exam_id == exam_id,
                Question.question_type == 'python_fill').all()
    ]
    if not py_q_ids:
        return set()
    rows = db.session.query(PythonAnswer.student_id, PythonAnswer.question_id).filter(
        PythonAnswer.question_id.in_(py_q_ids)
    ).all()
    return {(sid, qid) for sid, qid in rows}


@scores_bp.route('/admin/trend/<int:exam_id>')
@admin_login_required
@measure_time
def admin_trend(exam_id):
    """
    成绩趋势分析页面

    注意：
    - 对于Python填空题，得分被标准化为10分制，便于在表格中显示
    - 正确率则是根据实际得分除以10计算的百分比
    """

    exam = db.get_or_404(Exam, exam_id)

    # 获取班级筛选参数
    class_filter = request.args.get('class_filter', '')

    # 所有该考试的成绩记录
    # 列裁剪：统计仅需 answers/scores/total_score 等，排除 manual_scores
    # 批改明细大 TEXT 列（500 人 × 10-30KB ≈ 5-15MB/请求）
    results = Result.query.with_entities(
        Result.id, Result.student_id, Result.total_score,
        Result.submit_time, Result.answers, Result.scores
    ).filter_by(exam_id=exam_id).order_by(Result.submit_time.desc()).all()

    if not results:
        flash('暂无学生提交该试卷', 'warning')
        return render_template('admin_trend.html', exam=exam, results=None)

    # Python填空题清单：归属看 exam_question 中间表（解耦后来源卷
    # 不再等于归属；与 load_python_attempt_set 同一口径）
    from app.models import ExamQuestion as _EQ
    py_ids = [qid for (qid,) in db.session.query(Question.id)
              .join(_EQ, _EQ.question_id == Question.id)
              .filter(_EQ.exam_id == exam_id,
                      Question.question_type == 'python_fill').all()]
    python_questions = Question.query.filter(Question.id.in_(py_ids)).all()         if py_ids else []

    # 一次性批量加载所有 Python 答案（消除 N+1）：
    # attempt 判定用全量记录（有作答即计入，无论是否已批改）；
    # 分数仅用 graded 记录（未批改的分数不可靠）
    python_attempts = load_python_attempt_set(exam_id)
    python_scores = {}
    if python_questions:
        py_q_ids = [q.id for q in python_questions]
        answers = PythonAnswer.query.filter(
            PythonAnswer.question_id.in_(py_q_ids),
            PythonAnswer.status == 'graded'
        ).all()
        for answer in answers:
            if answer.student_id not in python_scores:
                python_scores[answer.student_id] = {}
            # 存储整数ID和字符串ID形式的分数，以确保兼容性
            python_scores[answer.student_id][answer.question_id] = answer.score
            python_scores[answer.student_id][str(answer.question_id)] = answer.score

    # 初始化统计数据
    # 判定逻辑：score < threshold 落入对应区间，即 [0,60) / [60,70) / [70,80) / [80,90) / [90,100]
    # 标签文案与左闭右开边界保持一致（原"不及格(0-60)"与"及格(60-70)"在 60 分处重叠）
    score_bins = [0, 60, 70, 80, 90, 100]
    bin_labels = ['不及格(<60)', '及格(60-69)', '良好(70-79)', '优秀(80-89)', '优秀(90-100)']
    dist = [0] * 5

    # 班级统计
    class_stats = {}

    # 获取该试卷的所有问题
    from app.models import exam_questions_flat
    questions = exam_questions_flat(exam_id)

    # 一次性批量加载所有综合题的小题，消除 N+1
    comprehensive_ids = [q.id for q in questions if q.question_type == 'comprehensive']
    subs_by_q = {}
    if comprehensive_ids:
        for s in SubQuestion.query.filter(
                SubQuestion.question_id.in_(comprehensive_ids)
        ).order_by(SubQuestion.order).all():
            subs_by_q.setdefault(s.question_id, []).append(s)
        # 回填到模板要用的 Question 对象上：下面的大循环只把 subs_by_q 用于
        # 统计，模板表头（两处）仍遍历 question.sub_questions（lazy=True）——
        # 不回填则每道综合题各发 1 次 SELECT，"批量预加载"白做。
        # 必须用 set_committed_value 而非 `q.sub_questions = [...]`：后者要
        # 维护 backref 反向指针，会先把旧集合**整个加载一遍**，等于把 N+1
        # 从模板挪到赋值行，查询数一条没省（实测）。
        from sqlalchemy.orm.attributes import set_committed_value
        for _q in questions:
            if _q.question_type == 'comprehensive':
                set_committed_value(_q, 'sub_questions',
                                    subs_by_q.get(_q.id, []))

    # 初始化问题统计数组
    q_stats = []
    for q in questions:
        q_stat = {
            'id': q.id,
            'type': q.question_type,
            'content_html': q.content.replace('\n', '<br>') if q.content else '',
            'correct_count': 0,
            'attempt_count': 0,
            'option_count': {}
        }

        # 为判断题初始化选项计数
        if q.question_type == 'judge':
            q_stat['option_count'] = {'正确': 0, '错误': 0}

        # 处理综合题的子问题
        if q.question_type == 'comprehensive':
            q_stat['sub_questions'] = []
            # 使用预加载的小题
            sub_questions = subs_by_q.get(q.id, [])
            for sub_q in sub_questions:
                sub_stat = {
                    'id': sub_q.id,
                    'content': sub_q.content,
                    'correct_count': 0,
                    'attempt_count': 0
                }
                q_stat['sub_questions'].append(sub_stat)

        # 处理Python填空题
        elif q.question_type == 'python_fill':
            q_stat['detail_rates'] = {}
            special_markers = get_special_markers(q.content)
            if special_markers:
                for i, marker in enumerate(special_markers):
                    q_stat['detail_rates'][f'填空点{i+1}'] = {
                        'correct_count': 0,
                        'attempt_count': 0,
                        'rate': 0
                    }
            else:
                # 回退：使用 python_answers_dict 的键作为填空点
                answers_dict = q.python_answers_dict
                for j, blank_id in enumerate(sorted(answers_dict.keys(), key=lambda x: int(x) if x.isdigit() else x)):
                    q_stat['detail_rates'][f'填空点{j+1}'] = {
                        'correct_count': 0,
                        'attempt_count': 0,
                        'rate': 0
                    }

        # 处理填空题
        elif q.question_type == 'fill':
            q_stat['detail_rates'] = {}
            answer = q.answer or ''
            blanks = [b.strip() for b in answer.split('|') if b.strip()]
            for i, blank in enumerate(blanks):
                q_stat['detail_rates'][f'填空点{i+1}'] = {
                    'correct_count': 0,
                    'attempt_count': 0,
                    'rate': 0
                }

        q_stats.append(q_stat)

    # 学生详细信息列表
    student_details = []

    # 记录所有可用班级
    available_classes = set()

    # 预加载所有相关学生（避免 N+1 查询）
    student_ids = [r.student_id for r in results]
    students_map = {}
    if student_ids:
        students_list = Student.query.filter(Student.id.in_(set(student_ids))).all()
        students_map = {s.id: s for s in students_list}

    # 分析每个成绩记录
    for result in results:
        # 获取学生信息（从预加载的字典中获取）
        student = students_map.get(result.student_id)
        if not student:
            continue

        # 获取班级名称
        class_name = student.student_class if student.student_class else '未分班'
        available_classes.add(class_name)

        # 如果设置了班级筛选，且不匹配当前班级，则跳过
        if class_filter and class_name != class_filter:
            continue

        # 计算分数分布（total_score 可能为 None，需兜底避免比较报错）
        score = result.total_score or 0
        for i, threshold in enumerate(score_bins[1:]):
            if score < threshold:
                dist[i] += 1
                break
            elif i == 4:  # 最后一个区间
                dist[i] += 1

        # 班级统计
        if class_name not in class_stats:
            class_stats[class_name] = {
                'count': 0,
                'total': 0,
                'average': 0,
                'max': score,
                'min': score
            }

        current_class = class_stats[class_name]
        current_class['count'] += 1
        current_class['total'] += score
        current_class['max'] = max(current_class['max'], score)
        current_class['min'] = min(current_class['min'], score)
        current_class['average'] = round(current_class['total'] / current_class['count'], 2)

        # 学生详细信息
        student_info = {
            'name': student.name,
            'class': class_name,
            'total_score': score,
            'submit_time': result.submit_time,
            'question_scores': {},
            'student_id': student.id,  # 添加学生ID以便后续处理
            'result_id': result.id     # 添加结果ID用于删除功能
        }

        # 处理各个问题的正确率
        try:
            answers = json.loads(result.answers) if result.answers else {}
            scores = json.loads(result.scores) if result.scores else {}

            for i, q in enumerate(questions):
                question_id = str(q.id)
                int_question_id = q.id

                if q.question_type in ['single', 'multiple', 'judge']:
                    # 选择题与判断题处理
                    if question_id in answers and question_id in scores:
                        is_correct = False
                        score = scores.get(question_id, 0)
                        if abs(float(score) - float(q.score)) < 0.01:  # 得分接近满分，视为正确
                            is_correct = True

                        # 记录学生得分
                        student_info['question_scores'][question_id] = score

                        # 更新问题统计
                        q_stats[i]['attempt_count'] += 1
                        if is_correct:
                            q_stats[i]['correct_count'] += 1

                        # 选项计数（单选和多选）：复用判分归一化，避免
                        # SPA 提交的 'A|B|D' / 'A,B' 把分隔符也计成选项，
                        # 同时消除大小写/全角差异（与判分口径一致）
                        if q.question_type in ['single', 'multiple'] and question_id in answers:
                            user_answer = answers[question_id]
                            if q.question_type == 'multiple':
                                answer_str = _normalize_multi_answer(user_answer)
                                for ch in answer_str:
                                    q_stats[i]['option_count'][ch] = \
                                        q_stats[i]['option_count'].get(ch, 0) + 1
                            else:
                                answer_key = _normalize_choice_letter(user_answer)
                                if answer_key:
                                    q_stats[i]['option_count'][answer_key] = \
                                        q_stats[i]['option_count'].get(answer_key, 0) + 1

                        # 判断题选项计数（与判分共用 JUDGE_TRUTHY 口径：
                        # '对'/'t'/'yes' 等兼容编码也应计入"正确"）
                        elif q.question_type == 'judge' and question_id in answers:
                            user_answer = answers[question_id]
                            if isinstance(user_answer, str):
                                if user_answer.strip().lower() in JUDGE_TRUTHY:
                                    q_stats[i]['option_count']['正确'] += 1
                                else:
                                    q_stats[i]['option_count']['错误'] += 1

                elif q.question_type == 'fill':
                    # 填空题处理
                    if question_id in answers and question_id in scores:
                        score = scores.get(question_id, 0)
                        student_info['question_scores'][question_id] = score

                        q_stats[i]['attempt_count'] += 1
                        if abs(float(score) - float(q.score)) < 0.01:
                            q_stats[i]['correct_count'] += 1

                        # 跟踪每空正确率（口径与 scoring_service.score_fill 对齐）：
                        # 逐空按下标对齐而非过滤空段——此前对 std/user 各自
                        # 过滤空串，'a||c' 这类部分作答会整体错位（第 2 空与
                        # 第 3 空串位），且 'money // m' 用 split('//') 判分与
                        # 评分模块的多解口径不一致，教师看到的正确率恒偏低。
                        user_ans = answers.get(question_id, '')
                        std_parts = (q.answer or '').split('|')
                        user_parts = str(user_ans if user_ans is not None else '').split('|')
                        key_idx = 0
                        for j, expected in enumerate(std_parts):
                            # 空标准答案不参与统计（与 detail_rates 构建时的
                            # 非空过滤保持一致，键序号连续）
                            if not expected.strip():
                                continue
                            key_idx += 1
                            fill_key = f'填空点{key_idx}'
                            if fill_key in q_stats[i].get('detail_rates', {}):
                                q_stats[i]['detail_rates'][fill_key]['attempt_count'] += 1
                                if j < len(user_parts) and user_parts[j].strip():
                                    from app.services.scoring_service import (
                                        _parse_acceptable_answers)
                                    acceptable = _parse_acceptable_answers(expected, q)
                                    if user_parts[j].strip() in acceptable:
                                        q_stats[i]['detail_rates'][fill_key]['correct_count'] += 1

                elif q.question_type == 'python_fill':
                    # Python填空题处理 - 优先从PythonAnswer记录获取分数
                    python_score = None

                    # 1. 首先尝试从数据库映射中获取Python答案文件的分数
                    if student.id in python_scores:
                        # 尝试整数ID
                        if int_question_id in python_scores[student.id]:
                            python_score = python_scores[student.id][int_question_id]
                            current_app.logger.info(f"从映射获取Python填空题分数(整数ID) - 题目ID={int_question_id}, 学生ID={student.id}, 分数={python_score}")
                        # 尝试字符串ID
                        elif question_id in python_scores[student.id]:
                            python_score = python_scores[student.id][question_id]
                            current_app.logger.info(f"从映射获取Python填空题分数(字符串ID) - 题目ID={question_id}, 学生ID={student.id}, 分数={python_score}")

                    # 2. 从 result.scores 中获取（兜底）
                    if python_score is None:
                        if question_id in scores:
                            python_score = float(scores.get(question_id, 0))
                        elif str(int_question_id) in scores:
                            python_score = float(scores.get(str(int_question_id), 0))

                    # 3. 以上均未命中 → 默认为 0（预加载已覆盖所有 graded 记录）
                    if python_score is None:
                        python_score = 0

                    # 记录最终的分数，同时使用字符串和整数ID
                    student_info['question_scores'][question_id] = python_score
                    student_info['question_scores'][int_question_id] = python_score

                    # 更新统计信息：有作答（PythonAnswer 记录存在，不分是否
                    # 已批改）即计入 attempt_count —— 不得以分数 > 0 过滤
                    # （此前缺陷：得 0 分的全错作答被排除，正确率分母偏小、
                    # 数值虚高，且与其他题型的统计口径不一致）。判定用全量
                    # attempt 集合而非 graded 分数映射（未批改作答同样算作答）
                    has_answer = (student.id, int_question_id) in python_attempts
                    if has_answer:
                        q_stats[i]['attempt_count'] += 1
                        # 修改Python填空题的正确率计算方式，使用原始得分与满分比较
                        if abs(python_score - float(q.score)) < 0.01:
                            q_stats[i]['correct_count'] += 1

                        # 处理详细填空点数据
                        python_answers_dict = q.python_answers_dict
                        user_answers = {}

                        if question_id in answers:
                            if isinstance(answers[question_id], dict):
                                user_answers = answers[question_id]
                            elif isinstance(answers[question_id], str) and '{' in answers[question_id]:
                                try:
                                    user_answers = json.loads(answers[question_id])
                                except (json.JSONDecodeError, TypeError):
                                    continue

                        special_markers = get_special_markers(q.content)
                        if special_markers:
                            blank_ids = [str(j + 1) for j in range(len(special_markers))]
                        else:
                            # 无 ①②③ 标记（SPA 建题常见）：按 python_answers
                            # 的键遍历——此前只遍历 special_markers（空列表），
                            # detail_rates 初始化了但计数循环从不执行，恒 0%。
                            blank_ids = sorted(
                                python_answers_dict.keys(),
                                key=lambda x: int(x) if str(x).isdigit() else str(x))
                        for j, blank_id in enumerate(blank_ids):
                            fill_key = f'填空点{j+1}'

                            if fill_key in q_stats[i]['detail_rates'] and blank_id in user_answers:
                                q_stats[i]['detail_rates'][fill_key]['attempt_count'] += 1

                                # 使用原始数据判断正确性。
                                # 口径与 scoring_service._parse_acceptable_answers
                                # 一致：python_answers 为 "a|b" 字符串（多组答案
                                # | 分隔），兼容 list/str 两种形态——此前直接迭代
                                # 字符串按字符比较，单字符与整串恒不相等 →
                                # correct_count 恒为 0。
                                # 必须走 _parse_acceptable_answers 而非仅按 '|'
                                # 拆分：判分器对 'money // m' 这类"一空多解"会
                                # 接受 money/m/整串三种写法，此处只按 '|' 拆则
                                # 仅整串算对——答 money 的学生判分得满分、教师
                                # 每空正确率却计为答错，两端口径分叉（注释曾
                                # 声称一致，实现并未对齐）
                                from app.services.scoring_service import (
                                    _parse_acceptable_answers)
                                expected_raw = python_answers_dict.get(blank_id, [])
                                if isinstance(expected_raw, str):
                                    expected_answer = _parse_acceptable_answers(
                                        expected_raw, q)
                                else:
                                    # list 形态：每个元素本身也可能含 // 多解
                                    expected_answer = []
                                    for e in expected_raw:
                                        expected_answer.extend(
                                            _parse_acceptable_answers(str(e), q))
                                # str() 兜底：作答值可能是数字/布尔（该 dict 来自
                                # 学生提交的 JSON 字符串内部，submit_exam 只校验
                                # 顶层值类型，嵌套值未受约束）。直接 .strip() 会抛
                                # AttributeError——它不在外层 except 捕获之列，会让
                                # 整个趋势页 500，等于任一学生可构造请求打挂教师端
                                user_answer = str(user_answers.get(blank_id, ''))

                                # 判断答案是否正确
                                is_correct = False
                                for expected in expected_answer:
                                    if expected == user_answer.strip():
                                        is_correct = True
                                        break

                                if is_correct:
                                    q_stats[i]['detail_rates'][fill_key]['correct_count'] += 1

                elif q.question_type == 'comprehensive':
                    # 综合题处理
                    if question_id in scores:
                        main_score = scores.get(question_id, 0)
                        student_info['question_scores'][question_id] = main_score

                        q_stats[i]['attempt_count'] += 1
                        if abs(float(main_score) - float(q.score)) < 0.01:
                            q_stats[i]['correct_count'] += 1

                        # 子问题处理（复用上方已批量预加载的 subs_by_q，消除 N+1）
                        sub_q_list = subs_by_q.get(q.id, [])

                        for j, sub_q in enumerate(sub_q_list):
                            sub_key = f"sub_{sub_q.id}"
                            if sub_key in scores:
                                sub_score = scores.get(sub_key, 0)
                                student_info['question_scores'][sub_key] = sub_score

                                if j < len(q_stats[i]['sub_questions']):
                                    q_stats[i]['sub_questions'][j]['attempt_count'] += 1
                                    if abs(float(sub_score) - float(sub_q.score)) < 0.01:
                                        q_stats[i]['sub_questions'][j]['correct_count'] += 1

        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            current_app.logger.error(f"Error processing result {result.id}: {str(e)}")

        # 添加学生详细信息
        student_details.append(student_info)

    # 计算每道题的正确率
    for q_stat in q_stats:
        if q_stat['attempt_count'] > 0:
            q_stat['correct_rate'] = round(q_stat['correct_count'] / q_stat['attempt_count'] * 100, 2)
        else:
            q_stat['correct_rate'] = 0

        # 处理综合题子问题的正确率
        if q_stat['type'] == 'comprehensive':
            for sub_stat in q_stat['sub_questions']:
                if sub_stat['attempt_count'] > 0:
                    sub_stat['correct_rate'] = round(sub_stat['correct_count'] / sub_stat['attempt_count'] * 100, 2)
                else:
                    sub_stat['correct_rate'] = 0

        # 处理Python填空题和填空题填空点的正确率
        elif q_stat['type'] in ['python_fill', 'fill'] and 'detail_rates' in q_stat:
            for point, data in q_stat['detail_rates'].items():
                if data['attempt_count'] > 0:
                    data['rate'] = round(data['correct_count'] / data['attempt_count'] * 100, 2)
                else:
                    data['rate'] = 0

    # 将可用班级列表转换为有序列表
    available_classes = sorted(list(available_classes))

    # 学生明细表格分页（统计聚合保持全量，表格每页 20 名学生）
    from types import SimpleNamespace
    _per_page = 20
    _page = max(1, request.args.get('page', 1, type=int))
    _total = len(student_details)
    _pages = max(1, ( _total + _per_page - 1) // _per_page) if _total else 1
    if _page > _pages:
        _page = _pages
    detail_pagination = SimpleNamespace(
        items=student_details[(_page - 1) * _per_page: _page * _per_page],
        page=_page, per_page=_per_page, total=_total, pages=_pages,
        has_prev=_page > 1, has_next=_page < _pages,
        prev_num=_page - 1 if _page > 1 else 1,
        next_num=_page + 1 if _page < _pages else _pages,
    )

    # 最终结果渲染
    return render_template('admin_trend.html',
                          exam=exam,
                          results=results,
                          dist=dist,
                          bin_labels=bin_labels,
                          q_stats=q_stats,
                          class_stats=class_stats,
                          student_details=detail_pagination.items,
                          detail_pagination=detail_pagination,
                          questions=questions,
                          available_classes=available_classes,
                          class_filter=class_filter)


@scores_bp.route('/student/trend/<int:student_id>')
@login_required
def student_trend(student_id):
    """
    @function student_trend
    @brief 学生查看自己的成绩趋势
    @param student_id 学生ID
    @return 渲染trend.html模板
    """
    # 检查是否是当前登录的学生
    if student_id != session.get('student_id'):
        flash('您无权查看其他学生的成绩')
        return redirect(url_for('online_exam.exam'))

    student = db.get_or_404(Student, student_id)

    # 获取该学生的所有成绩记录
    results = Result.query.filter_by(student_id=student_id).order_by(Result.submit_time).all()

    # 准备图表和表格数据
    scores = []
    times = []
    trend_rows = []

    # 按试卷分组（批量加载 Exam，消除 N+1）
    exam_results = {}
    exam_ids = {r.exam_id for r in results}
    exams_by_id = {
        e.id: e for e in Exam.query.filter(Exam.id.in_(exam_ids)).all()
    } if exam_ids else {}
    for result in results:
        exam = exams_by_id.get(result.exam_id)
        # 未公布成绩（allow_view_results=False）的卷不进学生趋势，否则
        # "不公布成绩"只挡住了详情页，趋势图照样画出分数
        if exam and exam.allow_view_results:
            if exam.id not in exam_results:
                exam_results[exam.id] = {
                    'name': exam.name,
                    'scores': [],
                    'dates': []
                }

            # total_score or 0：存量行可能被手工清空 total_score（NULL），
            # 直接进图表会出现 null 断线（admin_trend 已有 or 0 口径）
            _score = result.total_score or 0
            exam_results[exam.id]['scores'].append(_score)
            exam_results[exam.id]['dates'].append(result.submit_time.strftime('%Y-%m-%d'))

            # 添加到图表数据
            scores.append(_score)
            times.append(result.submit_time.strftime('%Y-%m-%d'))

            # 添加到表格数据
            trend_rows.append((exam.name, _score, result.submit_time.strftime('%Y-%m-%d %H:%M')))

    # 如果没有考试记录，显示提示信息
    if not results:
        flash('您还没有参加过任何考试')

    return render_template('trend.html',
                           student=student,
                           results=results,
                           exam_results=exam_results,
                           scores=scores,
                           times=times,
                           trend_rows=trend_rows)


@scores_bp.route('/admin/export_scores/<int:exam_id>')
@admin_login_required
def export_scores(exam_id):
    """
    导出考试成绩为Excel文件
    """
    exam = db.get_or_404(Exam, exam_id)
    results = Result.query.filter_by(exam_id=exam_id).order_by(Result.submit_time.desc()).all()

    if not results:
        flash('暂无学生提交该试卷', 'warning')
        return redirect(url_for('scores.admin_trend', exam_id=exam_id))

    # 获取该试卷的所有问题
    from app.models import exam_questions_flat
    questions = exam_questions_flat(exam_id)

    # 批量加载 SubQuestion + Student，消除 N+1
    comprehensive_ids = [q.id for q in questions if q.question_type == 'comprehensive']
    subs_by_q = {}
    if comprehensive_ids:
        for s in SubQuestion.query.filter(
                SubQuestion.question_id.in_(comprehensive_ids)).order_by(SubQuestion.order).all():
            subs_by_q.setdefault(s.question_id, []).append(s)

    student_ids = {r.student_id for r in results}
    students_by_id = {
        s.id: s for s in Student.query.filter(Student.id.in_(student_ids)).all()
    } if student_ids else {}

    # write_only 模式：逐行流式写入，内存占用与数据量无关
    # （此前常规模式 500 学生 × 50 题全量驻留内存 + BytesIO；标题行
    # 不再支持单元格加粗样式，属轻微视觉变化）
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("学生成绩")

    # 设置标题行
    headers = ['班级', '姓名', '总分', '提交时间']
    for i, q in enumerate(questions, 1):
        headers.append(f'第{i}题')
        if q.question_type == 'comprehensive':
            for j, sub_q in enumerate(subs_by_q.get(q.id, []), 1):
                headers.append(f'第{i}-{j}小题')
    ws.append(headers)

    # 预解析所有成绩 JSON 一次（此前每行/每题循环内重复 json.loads，
    # 500 学生 × 50 题 ≈ 数百次重复解析）
    parsed_scores = []
    for result in results:
        try:
            parsed_scores.append(json.loads(result.scores) if result.scores else {})
        except (json.JSONDecodeError, TypeError, ValueError):
            parsed_scores.append({})

    # 写入数据行（逐行 append 流式写入）
    for result, scores in zip(results, parsed_scores):
        student = students_by_id.get(result.student_id)
        if not student:
            continue
        # 姓名/班级等用户可控文本套 excel_safe 防公式注入，数字不套
        row = [
            excel_safe(student.student_class or '未分班'),
            excel_safe(student.name),
            result.total_score,
            excel_safe(result.submit_time.strftime('%Y-%m-%d %H:%M')),
        ]
        for q in questions:
            question_id = str(q.id)
            row.append(float(scores[question_id]) if question_id in scores else 0)
            if q.question_type == 'comprehensive':
                for sub_q in subs_by_q.get(q.id, []):
                    sub_key = f'sub_{sub_q.id}'
                    row.append(float(scores[sub_key]) if sub_key in scores else 0)
        ws.append(row)

    # 第二个工作表：每题正确率（单遍统计：外层按学生遍历一次，
    # 此前双重循环 O(题目×学生) + 每题循环内重复 json.loads）
    # python_fill 的 attempt 判定与趋势页一致（PythonAnswer 记录存在），
    # 未作答学生（scores 有 0 分键）不计入分母
    python_attempts = load_python_attempt_set(exam_id)
    q_attempt = [0] * len(questions)
    q_correct = [0.0] * len(questions)
    sub_attempt = {}
    sub_correct = {}
    for result, scores in zip(results, parsed_scores):
        for i, q in enumerate(questions):
            question_id = str(q.id)
            if question_id in scores:
                if q.question_type == 'python_fill':
                    if (result.student_id, q.id) not in python_attempts:
                        continue  # 未作答（scores 键由交卷流程无条件写入）
                    value = float(scores[question_id])
                    # 正确率口径与趋势页/其他题型统一为"满分才算正确"
                    # （此前部分得分按比例计入，同一试卷导出与页面数字不一致）
                    if abs(value - float(q.score)) < 0.01:
                        q_correct[i] += 1
                else:
                    value = float(scores[question_id])
                    if abs(value - float(q.score)) < 0.01:
                        q_correct[i] += 1
                q_attempt[i] += 1
            if q.question_type == 'comprehensive':
                for sub_q in subs_by_q.get(q.id, []):
                    sub_key = f'sub_{sub_q.id}'
                    if sub_key in scores:
                        sub_attempt[sub_q.id] = sub_attempt.get(sub_q.id, 0) + 1
                        if abs(float(scores[sub_key]) - float(sub_q.score)) < 0.01:
                            sub_correct[sub_q.id] = sub_correct.get(sub_q.id, 0) + 1

    ws2 = wb.create_sheet("题目分析")
    ws2.append(['题号', '题型', '正确率'])
    type_map = {
        'single': '单选题', 'multiple': '多选题', 'judge': '判断题',
        'fill': '填空题', 'python_fill': 'Python填空题', 'comprehensive': '综合题',
    }
    for i, q in enumerate(questions, 1):
        if q_attempt[i - 1] > 0:
            correct_rate = round(q_correct[i - 1] / q_attempt[i - 1] * 100, 2)
        else:
            correct_rate = 0
        ws2.append([f'第{i}题', type_map.get(q.question_type, q.question_type),
                    f'{correct_rate}%'])
        if q.question_type == 'comprehensive':
            for j, sub_q in enumerate(subs_by_q.get(q.id, []), 1):
                sub_a = sub_attempt.get(sub_q.id, 0)
                sub_c = sub_correct.get(sub_q.id, 0)
                sub_rate = round(sub_c / sub_a * 100, 2) if sub_a > 0 else 0
                sub_type = {
                    'single': '单选题', 'multiple': '多选题',
                    'judge': '判断题', 'fill': '填空题',
                }.get(sub_q.question_type, sub_q.question_type)
                ws2.append([f'第{i}-{j}小题', sub_type, f'{sub_rate}%'])

    # 第三个工作表：班级统计
    ws3 = wb.create_sheet("班级统计")
    ws3.append(['班级', '人数', '平均分', '最高分', '最低分'])

    # 班级统计
    class_stats = {}
    for result in results:
        student = students_by_id.get(result.student_id)
        if not student:
            continue

        class_name = student.student_class if student.student_class else '未分班'
        if class_name not in class_stats:
            class_stats[class_name] = {
                'count': 0,
                'total': 0,
                'scores': []
            }

        class_stats[class_name]['count'] += 1
        # total_score 可能为 NULL（历史/人工置空记录，本文件与 api_trends
        # 均已按此口径兜底），此处直接相加会 TypeError → 导出 500
        row_total = result.total_score or 0
        class_stats[class_name]['total'] += row_total
        class_stats[class_name]['scores'].append(row_total)

    # 写入班级统计数据（班级名属用户可控文本，套 excel_safe 防公式注入）
    for class_name, stats in class_stats.items():
        if stats['count'] > 0:
            average = round(stats['total'] / stats['count'], 2)
            max_score = max(stats['scores'])
            min_score = min(stats['scores'])
            ws3.append([excel_safe(class_name), stats['count'], average, max_score, min_score])

    # 保存到内存流并返回
    file_stream = BytesIO()
    wb.save(file_stream)
    file_stream.seek(0)

    return send_file(
        file_stream,
        as_attachment=True,
        download_name=f'{exam.name}_成绩分析.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


@scores_bp.route('/admin/delete_result/<int:result_id>', methods=['POST'])
@admin_login_required
def delete_result(result_id):
    """
    @function delete_result
    @brief 删除学生考试结果，以允许学生重新作答
    @param result_id 结果ID
    @return 重定向回成绩趋势页面
    """
    from app.services.scoring_service import delete_exam_result
    result = db.get_or_404(Result, result_id)
    exam_id = result.exam_id

    try:
        info = delete_exam_result(result)
        db.session.commit()
        # 趋势缓存换代 + 磁盘答案文件清理：commit 成功后执行
        from app.services.scoring_service import finalize_exam_result_deletion
        finalize_exam_result_deletion(info)
        current_app.logger.info(
            f"管理员删除学生成绩成功：学生ID={info['student_id']}, "
            f"姓名={info['student_name']}, 班级={info['student_class']}, "
            f"试卷ID={info['exam_id']}, 删除Python答案数={info['deleted_answers']}"
        )
        exam = db.session.get(Exam, exam_id)
        if exam and exam.is_collected:
            flash(f"已删除学生 {info['student_name']} 的成绩；"
                  '试卷当前已收卷，如需该生重考请先在试卷管理中取消收卷', 'success')
        else:
            flash(f"已删除学生 {info['student_name']} 的成绩，该学生现在可以重新参加考试", 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"删除学生成绩失败: {str(e)}", exc_info=True)
        flash('删除成绩失败', 'danger')

    # 保留原来的班级筛选参数
    class_filter = request.args.get('class_filter', '')
    redirect_url = url_for('scores.admin_trend', exam_id=exam_id)
    if class_filter:
        redirect_url = f"{redirect_url}?class_filter={class_filter}"

    return redirect(redirect_url)


@scores_bp.route('/admin/trend/<int:exam_id>/batch_delete', methods=['POST'])
@admin_login_required
def batch_delete_results(exam_id):
    """
    @function batch_delete_results
    @brief 批量删除学生考试结果
    @param exam_id 试卷ID
    @return 重定向回成绩趋势页面
    """
    from app.services.scoring_service import delete_exam_result
    # 获取要删除的结果ID列表
    result_ids = request.form.getlist('result_ids')
    class_filter = request.form.get('class_filter', '')
    redirect_url = url_for('scores.admin_trend', exam_id=exam_id)
    if class_filter:
        redirect_url = f"{redirect_url}?class_filter={class_filter}"

    if not result_ids:
        flash('未选择任何学生成绩', 'warning')
        return redirect(redirect_url)

    deleted_count = 0
    error_count = 0
    deleted_students = []
    deleted_infos = []

    for result_id in result_ids:
        try:
            rid = int(result_id)
            result = db.session.get(Result, rid)

            if result and result.exam_id == exam_id:
                info = delete_exam_result(result, log_action='批量删除学生成绩')
                deleted_count += 1
                deleted_students.append(info['student_name'])
                deleted_infos.append(info)
            else:
                error_count += 1
                current_app.logger.warning(f"结果ID {rid} 不存在或不属于试卷 {exam_id}")
        except Exception as e:
            error_count += 1
            current_app.logger.error(f"删除结果ID {result_id} 时出错: {str(e)}")

    try:
        # 提交所有更改
        db.session.commit()

        # 趋势缓存换代 + 磁盘答案文件清理：commit 成功后统一执行
        if deleted_infos:
            from app.services.scoring_service import finalize_exam_result_deletion
            finalize_exam_result_deletion(*deleted_infos)

        # 记录批量删除操作
        deleted_names = ", ".join(deleted_students[:10])
        if len(deleted_students) > 10:
            deleted_names += f" 等{len(deleted_students)}名学生"

        current_app.logger.info(f"管理员批量删除学生成绩成功：共{deleted_count}名学生，试卷ID={exam_id}，学生：{deleted_names}")

        if deleted_count > 0:
            flash(f'已成功删除 {deleted_count} 名学生的成绩', 'success')
        if error_count > 0:
            flash(f'删除过程中有 {error_count} 条记录出错', 'warning')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"批量删除学生成绩时提交数据库更改失败: {str(e)}", exc_info=True)
        flash('删除成绩失败', 'danger')

    return redirect(redirect_url)
