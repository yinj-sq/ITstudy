from flask import Blueprint, request, render_template, redirect, url_for, session, jsonify, flash
from flask import current_app
from datetime import datetime
import time
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models import (QUESTION_TYPE_LABELS, Exam, Result, SubQuestion,
                        PythonAnswer, PythonFile, Student, Log, ExamAttempt)
from app.decorators import login_required
from app.utils import measure_time, read_file_from_disk, get_subjects_cached, json_body_or_empty
from app.services.scoring_service import auto_score, score_python_file, \
    decode_python_source, bump_trend_cache, EXAM_SUBMIT_GRACE_SECONDS
import json

online_exam_bp = Blueprint('online_exam', __name__, url_prefix='')


def _is_exam_available_to_student(exam):
    return bool(
        exam and exam.is_active and exam.is_visible and
        getattr(exam, 'is_enabled', True)
    )


@online_exam_bp.route('/exam')
@login_required
def exam():
    """学生考试页面，显示可用试卷和历史记录"""
    # joinedload：模板逐卷渲染 exam.subject.name，懒加载会按卷各查一次
    from sqlalchemy.orm import joinedload as _joinedload
    active_exams = Exam.query.options(
        _joinedload(Exam.subject)
    ).filter_by(is_active=True, is_visible=True, is_enabled=True).all()
    student_id = session.get('student_id')
    results = []
    exam_scores = {}
    published_exam_ids = set()
    results_pagination = None
    if student_id:
        from app.utils import paginate_query
        # 成绩历史分页（试卷卡片保持全量——试卷数有限）
        results_pagination = paginate_query(
            Result.query.filter_by(student_id=student_id).order_by(
                Result.submit_time.desc()),
            default_per_page=20, max_per_page=100
        )
        results = results_pagination.items
        # 试卷卡片统计必须对"全部"成绩聚合：此前按当前页（默认 20 条）累加，
        # 考了 25 次的学生卡片显示"已考 20 次"、最高分也取自最近 20 次的子集。
        # 用一次 group_by 聚合替代逐行累加，页数无关且消除 N+1。
        from sqlalchemy import func as _func
        stat_rows = db.session.query(
            Result.exam_id, _func.count(Result.id),
            _func.max(Result.total_score)
        ).filter(Result.student_id == student_id).group_by(Result.exam_id).all()
        stat_exam_ids = {row[0] for row in stat_rows if row[0] is not None}
        name_rows = Exam.query.with_entities(
            Exam.id, Exam.name, Exam.allow_view_results).filter(
            Exam.id.in_(stat_exam_ids)).all() if stat_exam_ids else []
        name_map = {eid: name for eid, name, _ in name_rows}
        # 已公布成绩的卷（含已结束、不在 active_exams 里的历史卷）：
        # 未公布的卷在列表/卡片上不显示分数
        published_exam_ids = {eid for eid, _, pub in name_rows if pub}
        for stat_exam_id, cnt, best in stat_rows:
            exam_scores[stat_exam_id] = {
                'exam_name': name_map.get(stat_exam_id, '已删除的试卷'),
                'best': best or 0,
                'count': cnt,
            }
    subjects = get_subjects_cached()
    # 外链卷判定：模板此前写 `exam.questions[0].question_type == 'link'`，
    # 每张卷都会懒加载**整卷题目行**只为看第一题的题型（N 卷 = N 次查询）。
    # 改为一次 DISTINCT ON 取每卷位次最前的题目——与 api_exams 的
    # 「卷内最前题为 link 型」口径一致（Exam.questions 亦按 position 排序）。
    from app.models import ExamQuestion, Question
    first_q_type_by_exam = {}
    link_url_by_exam = {}
    if active_exams:
        rows = db.session.query(
            ExamQuestion.exam_id, Question.question_type, Question.content
        ).join(Question, Question.id == ExamQuestion.question_id).filter(
            ExamQuestion.exam_id.in_([e.id for e in active_exams])
        ).distinct(ExamQuestion.exam_id).order_by(
            ExamQuestion.exam_id, ExamQuestion.position).all()
        for eid, qtype, content in rows:
            first_q_type_by_exam[eid] = qtype
            if qtype == 'link':
                link_url_by_exam[eid] = content or ''
    exams_map_obj = {e.id: e for e in active_exams}
    return render_template('exam.html', exams=active_exams, exam_scores=exam_scores,
                           results=results, subjects=subjects, exams_map=exams_map_obj,
                           published_exam_ids=published_exam_ids,
                           first_q_type_by_exam=first_q_type_by_exam,
                           link_url_by_exam=link_url_by_exam,
                           results_pagination=results_pagination)


@online_exam_bp.route('/online_exam/<int:exam_id>')
@login_required
@measure_time
def online_exam(exam_id):
    """
    @function online_exam
    @brief 学生在线考试页面
    @param exam_id 试卷ID
    @return 渲染online_exam.html模板
    """
    exam = db.get_or_404(Exam, exam_id)
    student_id = session.get('student_id')
    # 在考学生豁免“可见/开放/启用”开关：管理员误关或收卷时，已开考学生
    # 刷新页面不应被 403/重定向（否则已作答内容丢失），与 submit_exam/
    # exam_status 的“持有未超时 attempt”口径一致。
    from app.services.scoring_service import attempt_is_stale
    attempt = ExamAttempt.query.filter_by(
        student_id=student_id, exam_id=exam_id).first() if student_id else None
    live_attempt = bool(attempt and not attempt_is_stale(exam, attempt))
    if not _is_exam_available_to_student(exam) and not live_attempt:
        flash('试卷暂不可访问', 'warning')
        return redirect(url_for('online_exam.exam'))

    # 检查是否已有提交记录（先于开考记录创建：已提交学生重访不应再
    # 重建 ExamAttempt 垃圾行——提交时已清理，重访又新建则行数只增不减）
    existing_result = Result.query.filter_by(student_id=student_id, exam_id=exam_id).first()

    # 服务端记录开考时间（仅首次进入时记录；刷新/重复进入**不重置**，
    # 防止反复刷新无限续时）。重考场景由 delete_exam_result 清理
    # ExamAttempt 后自然重建开考记录。
    # 无时长卷同样创建开考记录：此前 exam.duration 门跳过创建，而
    # submit_exam 对无 attempt 学生一律 403"请先开始考试"——存量无时长卷
    # 学生答完全卷提交必 403，答卷丢失。
    # 收卷后不再新建开考记录：从未开考的学生收卷后打开考试页会获得
    # start_time=now 的记录，随后即可在宽限期内补交答卷，击穿 submit_exam
    # 的"收卷后拒绝未开考学生提交"防护（开考中收卷的学生已有记录，不受影响）。
    exam_start_time = None
    if student_id and not existing_result:
        if attempt and attempt_is_stale(exam, attempt):
            # 超时残留开考记录（开考后弃考/断网，超过 时长+5 分钟宽限）：
            # 提交通道已被 submit_exam 关闭，继续渲染只会得到必然 403 的
            # 自动交卷循环+报错弹窗。不删除记录（删除后重进=重新计时，
            # 可借弃考重置倒计时），管理员可在试卷列表"清除超时开考记录"
            # 后允许该生重考。
            flash('考试时间已结束，未提交的答卷无法再提交；如需重考请联系教师', 'warning')
            return redirect(url_for('online_exam.exam'))
        if not attempt:
            if exam.is_collected:
                # 收卷后从未开考的学生：直接给出明确结束态（此前渲染
                # start_time=now 的满时长倒计时页，收卷轮询 5s 内触发
                # 自动交卷并弹"考试已收卷"错误框）
                flash('考试已收卷，无法再作答', 'warning')
                return redirect(url_for('online_exam.exam'))
            # GET 页面会创建开考记录并起跑倒计时：跨站顶层导航（SameSite=Lax
            # 会携带会话 Cookie）可被攻击者用来静默开考/耗尽宽限时间。
            # 与 api_exams 的 Sec-Fetch-Site 守卫同口径，要求从站内进入。
            if request.headers.get('Sec-Fetch-Site') == 'cross-site':
                flash('请从考试列表进入考试', 'warning')
                return redirect(url_for('online_exam.exam'))
            try:
                attempt = ExamAttempt(
                    student_id=student_id, exam_id=exam_id,
                    start_time=datetime.now())
                db.session.add(attempt)
                db.session.commit()
            except IntegrityError:
                # 并发开考竞态：另一请求已创建开考记录，回滚后复用已有记录
                db.session.rollback()
                attempt = ExamAttempt.query.filter_by(
                    student_id=student_id, exam_id=exam_id).first()
        # 供前端倒计时基准使用（服务端时间戳，刷新后不重新计时）；
        # 收卷时在考的学生同样返回真实开考时间（自动交卷在宽限内完成）
        if attempt:
            exam_start_time = attempt.start_time.timestamp()

    # 获取学生信息
    student = db.session.get(Student, student_id) if student_id else None

    # 获取试卷所有题目
    from app.models import exam_questions_flat
    questions = exam_questions_flat(exam_id)

    # 一次性批量加载所有综合题的小题，消除 N+1
    comprehensive_ids = [q.id for q in questions if q.question_type == 'comprehensive']
    if comprehensive_ids:
        all_subs = SubQuestion.query.filter(
            SubQuestion.question_id.in_(comprehensive_ids)
        ).order_by(SubQuestion.order).all()
        subs_by_q = {}
        for s in all_subs:
            subs_by_q.setdefault(s.question_id, []).append(s)
        # 必须用 set_committed_value 而非 `question.sub_questions = [...]`：
        # 后者要维护 backref 反向指针，会先把旧集合**整个加载一遍**，等于把
        # N+1 从模板挪到赋值行，查询数一条没省（实测每道综合题 1 次 SELECT）
        from sqlalchemy.orm.attributes import set_committed_value
        for question in questions:
            if question.question_type == 'comprehensive':
                set_committed_value(question, 'sub_questions',
                                    subs_by_q.get(question.id, []))

    # 试卷总分（Exam 模型无 total_score 字段，此前模板引用 exam.total_score
    # 恒为空串，考试信息面板"总分：分"缺失数字）。综合题分值挂在小题上。
    exam_total_score = sum(
        (q.score or 0) if q.question_type != 'comprehensive'
        else sum((s.score or 0) for s in q.sub_questions)
        for q in questions)

    return render_template('online_exam.html',
                           type_labels=QUESTION_TYPE_LABELS,
                           exam=exam,
                           questions=questions,
                           existing_result=existing_result,
                           student=student,
                           exam_start_time=exam_start_time,
                           exam_total_score=exam_total_score)


@online_exam_bp.route('/exam/<int:exam_id>/status')
@login_required
def exam_status(exam_id):
    """返回试卷状态（用于前端轮询收卷）

    性能：全班学生每 20s 轮询一次该端点（250 人 ≈ 12 req/s）。
    权限校验结果按（考试,学生）缓存 60s、is_collected 缓存 2s——
    轮询稳态近似零 DB 查询，且权限校验**必须先于 collected 缓存命中
    路径执行**（此前校验在 collected 未命中分支内，2s 命中窗口完全
    跳过，可探测任意隐藏试卷的收卷状态）。
    """
    from app.extensions import cache as _st_cache
    student_id = session.get('student_id')
    allowed_key = f'exam:status:allowed:{exam_id}:{student_id}'
    exam = None
    if _st_cache.get(allowed_key) is None:
        exam = db.get_or_404(Exam, exam_id)
        # 最小权限校验：未开考学生仅可轮询对自身可见（is_active+is_visible
        # +is_enabled，与考试页 _is_exam_available_to_student 同口径）的考试；
        # 已开考/已交卷学生豁免——不因 is_active/is_enabled 拒绝，管理员在
        # 考试中停用/隐藏试卷后，在考学生仍需轮询到收卷状态以触发自动交卷
        # （此前 403 会中断轮询）
        if student_id and not (exam.is_active and exam.is_visible
                               and getattr(exam, 'is_enabled', True)):
            from app.models import ExamAttempt as _EA, Result as _R
            has_relation = (
                db.session.query(
                    _EA.query.filter_by(
                        student_id=student_id, exam_id=exam_id).exists()
                ).scalar()
                or db.session.query(
                    _R.query.filter_by(
                        student_id=student_id, exam_id=exam_id).exists()
                ).scalar()
            )
            if not has_relation:
                return jsonify({'success': False, 'message': '试卷不可访问'}), 403
        # 15s：管理员隐藏/停用试卷后，无关系学生对隐藏卷收卷状态的残留
        # 探测窗口（此前 60s——权限许可缓存与收卷状态缓存的窗口不一致，
        # 收卷 2s / 许可 60s，最坏情形把 2s 修复扩大成 60s 探测窗）
        _st_cache.set(allowed_key, 1, timeout=15)
    cache_key = f'exam:collected:{exam_id}'
    collected = _st_cache.get(cache_key)
    if collected is None:
        if exam is None:
            exam = db.session.get(Exam, exam_id)
            if exam is None:
                # 允许缓存命中但试卷已删除（≤60s 窗口）
                return jsonify({'success': False, 'message': '试卷不存在'}), 404
        collected = exam.is_collected
        _st_cache.set(cache_key, collected, timeout=2)
    return jsonify({'is_collected': collected})


@online_exam_bp.route('/submit_exam/<int:exam_id>', methods=['POST'])
@login_required
@measure_time
def submit_exam(exam_id):
    """提交试卷 — 处理学生提交试卷"""
    exam = db.get_or_404(Exam, exam_id)
    student_id = session.get('student_id')
    if not student_id:
        return jsonify({'success': False, 'message': '未登录'}), 401

    # 检查是否已有提交记录（重复提交保护，优先于收卷/超时检查）
    existing_result = Result.query.filter_by(student_id=student_id, exam_id=exam_id).first()
    if existing_result:
        current_app.logger.info(f"学生已提交过(收卷重复提交): student_id={student_id}, exam_id={exam_id}, existing_result={existing_result.id}")
        # 清理残留的开考记录
        ExamAttempt.query.filter(
            ExamAttempt.student_id == student_id,
            ExamAttempt.exam_id == exam_id
        ).delete(synchronize_session=False)
        db.session.commit()
        return jsonify({
            'success': True,
            'already_submitted': True,
            'result_id': existing_result.id,
        })

    # 开考记录：收卷/超时判定依据（从未开考的学生收卷后不允许提交）
    attempt = ExamAttempt.query.filter_by(
        student_id=student_id, exam_id=exam_id).first()

    # 不可见试卷仅拒绝"从未开考"的学生：交卷与 is_active/is_enabled 一样
    # 豁免 is_visible——考试中管理员隐藏试卷（改题/误操作）时，在考学生
    # 仍须能提交，否则前端收卷轮询自动提交同样 403，答卷永久丢失（此前缺陷）。
    if not attempt and not exam.is_visible:
        return jsonify({'success': False, 'message': '试卷不可访问'}), 403

    # 未开考且未收卷：拒绝直接 POST 交卷（防 0 分垃圾提交/绕过时长校验）
    if not attempt and not exam.is_collected:
        return jsonify({'success': False, 'message': '请先开始考试'}), 403

    if exam.is_collected:
        # 收卷 = 考试强制结束：在考学生接受最后一次提交（等同强制收卷），
        # 避免未提交学生的答案永久丢失；从未开考的学生拒绝。
        if not attempt:
            current_app.logger.info(f"考试已收卷且学生未开考，拒绝提交: exam_id={exam_id}, student_id={student_id}")
            return jsonify({'success': False, 'message': '考试已收卷，无法提交'}), 403
        # 收卷分支同样执行服务端时长强校验（与正常分支一致，含 5 分钟宽限），
        # 防止学生开考后长时间不交卷、收卷时趁机补交严重超时的答卷
        if exam.duration:
            elapsed = time.time() - attempt.start_time.timestamp()
            if elapsed > exam.duration * 60 + EXAM_SUBMIT_GRACE_SECONDS:
                current_app.logger.info(
                    f"收卷后超时拒绝提交: exam_id={exam_id}, student_id={student_id}, "
                    f"elapsed={elapsed:.0f}s")
                return jsonify({'success': False, 'message': '考试时间已到，无法提交'}), 403
        current_app.logger.info(f"收卷后接受在考学生提交: exam_id={exam_id}, student_id={student_id}")
    elif exam.duration and attempt:
        # 服务端时长强校验（开考时间持久化于 exam_attempt 表，不依赖易失缓存）。
        # 超时后拒绝提交；前端倒计时以服务端开考时间为基准，到点自动提交通常
        # 恰好落在宽限内，避免误伤正常到点交卷（含刷新场景）。
        elapsed = time.time() - attempt.start_time.timestamp()
        if elapsed > exam.duration * 60 + EXAM_SUBMIT_GRACE_SECONDS:
            current_app.logger.info(
                f"考试超时拒绝提交: exam_id={exam_id}, student_id={student_id}, "
                f"elapsed={elapsed:.0f}s")
            return jsonify({'success': False, 'message': '考试时间已到，无法提交'}), 403

    # 获取学生答案
    answers_data = json_body_or_empty()
    if not isinstance(answers_data, dict):
        return jsonify({'success': False, 'message': '答案数据格式无效'}), 400

    # 所有题目 + 综合题小题（提前加载，用于答案键过滤与后续评分）
    from app.models import exam_questions_flat
    questions = exam_questions_flat(exam_id)
    comprehensive_ids = [q.id for q in questions if q.question_type == 'comprehensive']
    subs_by_q = {}
    if comprehensive_ids:
        for s in SubQuestion.query.filter(
                SubQuestion.question_id.in_(comprehensive_ids)).all():
            subs_by_q.setdefault(s.question_id, []).append(s)

    # 显式过滤未知答案键：答案只允许引用本试卷真实题目（主题目 id 与子题 sub_<id>）。
    # 此前未知键在评分循环中被隐式忽略，行为不变；显式过滤可防止伪造键名污染存档答案。
    valid_keys = {str(q.id) for q in questions}
    valid_keys.update(f'sub_{s.id}' for subs in subs_by_q.values() for s in subs)
    unknown_keys = [k for k in answers_data if k not in valid_keys]
    if unknown_keys:
        current_app.logger.info(
            f"过滤未知答案键: exam_id={exam_id}, student_id={student_id}, "
            f"丢弃 {len(unknown_keys)} 个: {unknown_keys[:10]}")
        answers_data = {k: v for k, v in answers_data.items() if k in valid_keys}

    try:
        encoded_answers = json.dumps(answers_data, ensure_ascii=False)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': '答案数据无法序列化'}), 400
    if len(encoded_answers.encode('utf-8')) > 2 * 1024 * 1024:
        return jsonify({'success': False, 'message': '答案数据不能超过2MB'}), 413
    for key, value in answers_data.items():
        if not isinstance(key, str) or not isinstance(value, (str, int, float, bool, type(None))):
            return jsonify({'success': False, 'message': '答案字段类型无效'}), 400
        if isinstance(value, str) and len(value) > 100_000:
            return jsonify({'success': False, 'message': '单题答案内容过长'}), 413
    # 统一转字符串：前端/API 可能提交 bool/int（判断题 false、填空 5），
    # 结果页模板按字符串调用 .lower()/成员判断，原样存储会让 SSR 结果页
    # 500（'bool' object has no attribute 'lower'）。判分函数本就以 str 兜底。
    answers_data = {k: ('' if v is None else str(v)) for k, v in answers_data.items()}
    current_app.logger.debug('收到考试答案: exam_id=%s, student_id=%s, fields=%d',
                             exam_id, student_id, len(answers_data))

    # 计算得分
    total_score = 0
    scores = {}
    open_ended_questions = []  # 需人工批改的开放式试题
    auto_graded_items = []  # 学生未作答，系统自动批改为0分的试题

    def is_open_ended_type(q):
        """判断是否为需人工批改的开放式题型"""
        if q.question_type == 'short_answer':
            return True
        if q.question_type == 'fill' and (not q.answer or not q.answer.strip()):
            return True
        return False

    # Python 填空题判分所需的答案文件/参考文件一次性预取：
    # 此前循环内逐题 PythonAnswer.query.filter_by(...).first() +
    # PythonFile.query.filter_by(question_id=...).first()，每题 2 次查询；
    # 交卷高峰（整班同时提交）下 40-50 个线程各做数十次串行查询，DB 排队明显。
    _py_qids = [q.id for q in questions if q.question_type == 'python_fill']
    _py_answer_by_q = {}
    _py_ref_by_q = {}
    if _py_qids:
        for _pa in PythonAnswer.query.filter(
                PythonAnswer.question_id.in_(_py_qids),
                PythonAnswer.student_id == student_id).all():
            _py_answer_by_q.setdefault(_pa.question_id, _pa)
        for _pf in PythonFile.query.filter(
                PythonFile.question_id.in_(_py_qids)).all():
            _py_ref_by_q.setdefault(_pf.question_id, _pf)

    for question in questions:
        # 综合题处理
        if question.question_type == 'comprehensive':
            q_score = 0
            sub_questions = subs_by_q.get(question.id, [])
            for sub_q in sub_questions:
                sub_key = f"sub_{sub_q.id}"
                if sub_key in answers_data:
                    sub_ans = answers_data[sub_key]
                    current_app.logger.debug(f"处理综合题子题答案: 子题ID={sub_q.id}, 类型={sub_q.question_type}, 答案={sub_ans}")
                    sub_score = auto_score(sub_q, sub_ans)
                    if sub_score is None:
                        # 开放式试题子题（有作答内容），需人工批改
                        open_ended_questions.append({
                            'key': sub_key, 'question': sub_q,
                            'student_answer': sub_ans, 'max_score': sub_q.score
                        })
                        sub_score = 0
                    elif is_open_ended_type(sub_q) and (not sub_ans or not str(sub_ans).strip()):
                        # 学生未作答的开放式试题，系统自动批改为0分
                        auto_graded_items.append({
                            'key': sub_key, 'question': sub_q,
                            'student_answer': sub_ans, 'max_score': sub_q.score,
                            'auto_score': 0
                        })
                    q_score += sub_score
                    scores[sub_key] = sub_score
                elif is_open_ended_type(sub_q):
                    # 前端留空的输入框不提交键：与顶层题同规（见下方普通题分支），
                    # 键缺失的开放式小题按空答案自动 0 分并进入可改的自动批改列表，
                    # 否则它在教师批改页整题消失（既不待批也不已批）
                    auto_graded_items.append({
                        'key': sub_key, 'question': sub_q,
                        'student_answer': '', 'max_score': sub_q.score,
                        'auto_score': 0
                    })
                    scores[sub_key] = 0
                else:
                    current_app.logger.warning(f"未找到子题答案: 子题ID={sub_q.id}, 类型={sub_q.question_type}")
            scores[str(question.id)] = q_score
            total_score += q_score
        # Python填空题处理
        elif question.question_type == 'python_fill':
            q_id = str(question.id)
            q_score = 0

            # 检查是否有Python答案文件（预取映射，见循环前注释）
            python_answer = _py_answer_by_q.get(question.id)

            # 如果有Python答案文件，进行文件判分
            if python_answer:
                try:
                    current_app.logger.info(f"处理Python填空题文件答案: 题目ID={question.id}, 文件名={python_answer.file_name}")
                    raw_content = read_file_from_disk(python_answer.file_path)
                    try:
                        file_content = raw_content.decode('utf-8')
                    except UnicodeDecodeError:
                        # GBK 编码兜底（decode_python_source 统一口径）：
                        # 教师/学生用 Windows 编辑器保存的 .py 常为 GBK/GB2312，
                        # 直接按 UTF-8 解码失败会导致整题 0 分且无任何提示
                        file_content = decode_python_source(raw_content)
                        current_app.logger.warning(
                            f"Python答案文件非UTF-8编码（已按GBK/容错模式解码）: "
                            f"题目ID={question.id}, 学生ID={student_id}，请教师复核该题成绩")

                    # 获取题目参考文件（预取映射）
                    python_file = _py_ref_by_q.get(question.id)
                    if python_file:
                        current_app.logger.debug(f"已找到题目参考文件: {python_file.file_name}")

                    # 记录文件内容摘要（用于调试）
                    file_lines = file_content.splitlines()
                    current_app.logger.debug(f"Python答案文件行数: {len(file_lines)}")
                    if len(file_lines) > 0:
                        current_app.logger.debug(f"文件开始几行: {file_lines[:min(5, len(file_lines))]}")

                    # 调用评分函数（把上面预取的参考文件传进去：此前只喂给了
                    # debug 日志，评分函数内部又按题反查一遍，预取白做）
                    q_score = score_python_file(question, file_content, python_file)
                    current_app.logger.info(f"Python填空题评分结果: 题目ID={question.id}, 得分={q_score}")
                except Exception as e:
                    current_app.logger.error(f"Python文件评分失败: {str(e)}", exc_info=True)
            else:
                current_app.logger.warning(f"未找到学生上传的Python答案文件: 题目ID={question.id}, 学生ID={student_id}")

            # 如果有在线填写的答案，也进行判分（取文件分与文本分的较高者）
            if q_id in answers_data:
                current_app.logger.debug(f"发现Python填空题在线答案: 题目ID={q_id}, 答案={answers_data[q_id]}")
                text_score = auto_score(question, answers_data[q_id])
                current_app.logger.debug(f"Python填空题在线答案评分: 题目ID={q_id}, 得分={text_score}")
                # 取较高分
                q_score = max(q_score, text_score)

            # PythonAnswer.score 存合并后的最终分，与 Result.scores 保持一致
            # （此前先赋值文件分、后做 max 合并，导致成绩页/趋势页分数低于总分）
            if python_answer:
                python_answer.score = q_score
                python_answer.status = 'graded'
                python_answer.graded_at = datetime.now()

            scores[q_id] = q_score

            total_score += q_score
            current_app.logger.info(f"Python填空题最终得分: 题目ID={question.id}, 得分={q_score}")
        else:
            # 普通题处理
            q_id = str(question.id)
            if q_id in answers_data:
                current_app.logger.debug(f"处理普通题答案: 题目ID={q_id}, 类型={question.question_type}")
                q_score = auto_score(question, answers_data[q_id])
                if q_score is None:
                    # 开放式试题（有作答内容），需人工批改
                    open_ended_questions.append({
                        'key': q_id, 'question': question,
                        'student_answer': answers_data[q_id], 'max_score': question.score
                    })
                    q_score = 0
                elif is_open_ended_type(question) and not str(answers_data[q_id]).strip():
                    # 学生未作答的开放式试题，系统自动批改为0分
                    auto_graded_items.append({
                        'key': q_id, 'question': question,
                        'student_answer': answers_data[q_id], 'max_score': question.score,
                        'auto_score': 0
                    })
                scores[q_id] = q_score
                total_score += q_score
            elif is_open_ended_type(question):
                # 学生**完全未提交**该题（answers_data 里根本没有这个键）。
                # 此前这里直接落空：该题既不入 scores 也不入 manual_scores，
                # 教师批改页上整题消失——连"学生未作答"都看不到，教师无从
                # 判断是漏答还是系统丢了数据。
                # 按空答案处理，与上一分支的"已提交但为空"完全同规：
                # 自动 0 分、标注「自动批改」、教师可在批改页改分。
                auto_graded_items.append({
                    'key': q_id, 'question': question,
                    'student_answer': '', 'max_score': question.score,
                    'auto_score': 0
                })
                scores[q_id] = 0

    # 构建开放式试题手动批改数据
    manual_scores_data = None
    grading_status = 'auto_graded'

    # 判断是否有真正需要教师批改的试题（非自动批改的）
    has_pending_review = len(open_ended_questions) > 0

    if open_ended_questions or auto_graded_items:
        manual_scores_data = {}
        # 需要教师批改的试题（学生有作答内容）
        for oe in open_ended_questions:
            manual_scores_data[oe['key']] = {
                'max_score': oe['max_score'],
                'student_answer': oe['student_answer'],
                'manual_score': None,
                'question_type': oe['question'].question_type,
                'content': oe['question'].content[:200],
                'auto_graded': False
            }
        # 系统自动批改的试题（学生未作答）
        for ag in auto_graded_items:
            manual_scores_data[ag['key']] = {
                'max_score': ag['max_score'],
                'student_answer': ag['student_answer'],
                'manual_score': 0,
                'question_type': ag['question'].question_type,
                'content': ag['question'].content[:200],
                'auto_graded': True
            }

    if has_pending_review:
        grading_status = 'pending_review'
    elif auto_graded_items:
        grading_status = 'auto_graded'

    # 保存考试结果
    try:
        result = Result(
            student_id=student_id,
            exam_id=exam_id,
            answers=encoded_answers,
            scores=json.dumps(scores),
            total_score=total_score,
            submit_time=datetime.now(),
            grading_status=grading_status,
            manual_scores=json.dumps(manual_scores_data) if manual_scores_data else None
        )
        db.session.add(result)

        # 记录日志
        log_detail = f'试卷: {exam.name}, 得分: {total_score}'
        if grading_status == 'pending_review':
            log_detail += f', 含{len(open_ended_questions)}道开放式试题待批改'
        if auto_graded_items:
            log_detail += f', {len(auto_graded_items)}道未作答题自动批改为0分'
        log = Log(
            user_id=student_id,
            user_type='student',
            action='提交试卷',
            detail=log_detail,
            time=datetime.now()
        )
        db.session.add(log)
        # 提交成功，清理开考记录（避免 exam_attempt 表无限增长）
        if attempt:
            db.session.delete(attempt)
        db.session.commit()
        # 趋势缓存换代：新成绩立即反映到 SPA 趋势页（60s TTL 内不再读旧缓存）
        bump_trend_cache(exam_id)

        # 未公布成绩（allow_view_results=False）时不回传分数：此前交卷响应直接
        # 带总分与每题得分，考试进行中先交卷的学生对照作答即可推出客观题答案
        can_view = bool(exam.allow_view_results)
        return jsonify({
            'success': True,
            'total_score': total_score if can_view else None,
            'scores': scores if can_view else {},
            'result_id': result.id,
            'grading_status': grading_status,
            'open_ended_count': len(open_ended_questions),
            'auto_graded_count': len(auto_graded_items),
            'message': '试卷提交成功' + ('，含开放式试题需教师批改' if grading_status == 'pending_review' else '') + (f'，{len(auto_graded_items)}道未作答题已自动批改为0分' if auto_graded_items else '')
        })
    except Exception as e:
        from sqlalchemy.exc import IntegrityError
        if isinstance(e, IntegrityError) or (hasattr(e, '__cause__') and isinstance(getattr(e, '__cause__', None), IntegrityError)):
            # 唯一约束冲突（并发重复提交）：必须先回滚，否则后续查询会在
            # 脏 session 上抛 PendingRollbackError，导致本应友好的分支自身 500。
            db.session.rollback()
            current_app.logger.info(f"重复提交检测: student_id={student_id}, exam_id={exam_id}")
            existing = Result.query.filter_by(student_id=student_id, exam_id=exam_id).first()
            if existing:
                return jsonify({
                    'success': True,
                    'already_submitted': True,
                    'result_id': existing.id,
                    'total_score': existing.total_score if exam.allow_view_results else None,
                    'message': '试卷已提交，即将跳转至结果页'
                })
            return jsonify({'success': False, 'message': '提交冲突，请刷新页面后重试'}), 409
        db.session.rollback()
        current_app.logger.error(f"提交试卷失败: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'message': '提交失败'
        })


@online_exam_bp.route('/result/<int:result_id>')
@login_required
def show_result(result_id):
    """查看考试结果"""
    result = db.get_or_404(Result, result_id)
    exam = db.session.get(Exam, result.exam_id)
    # 待批改状态：允许查看但提示
    is_pending = getattr(result, 'grading_status', 'auto_graded') == 'pending_review'
    # 「公布成绩」关闭时一律不给学生看（含待批改）：此前待批改成绩豁免，
    # 学生仍能看到客观题逐题得分，与"未公布"语义矛盾（产品确认改为受开关控制）
    if exam and not exam.allow_view_results:
        flash('试卷已提交，成绩尚未公布，请等待老师公布', 'warning')
        return redirect(url_for('online_exam.exam'))
    student_id = session.get('student_id')

    # 检查是否是当前学生的考试记录
    if result.student_id != student_id:
        flash('您无权查看其他学生的考试结果')
        return redirect(url_for('online_exam.exam'))

    student = db.session.get(Student, result.student_id)

    # 获取学生答案和得分
    answers = json.loads(result.answers) if result.answers else {}
    scores = json.loads(result.scores) if result.scores else {}

    # 获取所有题目
    from app.models import exam_questions_flat
    questions = exam_questions_flat(result.exam_id)

    # 批量加载 Python 答案文件 + 综合题小题，消除 N+1
    py_question_ids = [q.id for q in questions if q.question_type == 'python_fill']
    if py_question_ids:
        py_answers = PythonAnswer.query.filter(
            PythonAnswer.question_id.in_(py_question_ids),
            PythonAnswer.student_id == student_id
        ).all()
        py_answers_by_qid = {pa.question_id: pa for pa in py_answers}
    else:
        py_answers_by_qid = {}

    comprehensive_ids = [q.id for q in questions if q.question_type == 'comprehensive']
    if comprehensive_ids:
        all_subs = SubQuestion.query.filter(
            SubQuestion.question_id.in_(comprehensive_ids)
        ).order_by(SubQuestion.order).all()
        subs_by_q = {}
        for s in all_subs:
            subs_by_q.setdefault(s.question_id, []).append(s)
    else:
        subs_by_q = {}

    # 获取Python答案文件内容
    python_files = {}
    for question in questions:
        if question.question_type == 'python_fill':
            python_answer = py_answers_by_qid.get(question.id)

            if python_answer:
                try:
                    raw_content = read_file_from_disk(python_answer.file_path)
                    # GBK 兜底统一走 decode_python_source（与判分端/SPA 端
                    # 同口径）：GBK 保存的 .py 能正常判分，回看页若按 UTF-8
                    # 硬解会显示"解码失败"，学生无法回看自己的代码
                    file_content = decode_python_source(raw_content)
                    python_files[str(question.id)] = file_content
                    current_app.logger.debug(f"找到Python答案文件 - 题目ID={question.id}, 学生ID={student_id}, 文件名={python_answer.file_name}")

                    # 优先使用PythonAnswer中的分数更新scores字典
                    # （统一字符串键，模板端 scores.get(question.id|string) 读取）
                    if python_answer.status == 'graded' and python_answer.score is not None:
                        q_id = str(question.id)
                        scores[q_id] = python_answer.score
                        current_app.logger.info(f"使用Python答案记录中的分数 - 题目ID={question.id}, 学生ID={student_id}, 分数={python_answer.score}")
                except Exception as e:
                    current_app.logger.error(f"解码Python答案文件失败 - 题目ID={question.id}, 学生ID={student_id}, 错误: {str(e)}")

    # 综合题关联小题（使用批量加载的结果）
    # set_committed_value 而非直接赋值：直接赋值会为维护 backref 先加载旧
    # 集合，N+1 只是从模板挪到赋值行（同 online_exam 页，实测）。
    from sqlalchemy.orm.attributes import set_committed_value
    for question in questions:
        if question.question_type == 'comprehensive':
            set_committed_value(question, 'sub_questions',
                                subs_by_q.get(question.id, []))

    # 参考答案展示控制（与 SPA api_results.show_result 同口径）：仅
    # "已收卷且非待批改"时展示——教师/管理员同样受收卷约束，避免考试
    # 进行中经教师会话先获取答案并分享给未交卷同学（此前 SSR 教师恒可看、
    # SPA 已收紧，两端口径分叉）
    is_admin_user = session.get('is_admin', False)
    is_teacher_user = session.get('is_teacher', False)
    show_solutions = bool(
        exam and exam.is_collected and not is_pending and
        (is_admin_user or is_teacher_user or exam.allow_view_results))
    if not show_solutions:
        for q in questions:
            # 置空串而非 None：模板对 answer 直接输出时不显示 "None"，
            # 且 .lower()/in 等链式调用在 None 上会抛 UndefinedError → 500
            # （判断题/填空子题/综合子题渲染路径，此前已复现 500）
            q.answer = ''
            q.python_answers = None  # 与 api_results.py 门控保持一致，防未收卷答案泄露
            if getattr(q, 'sub_questions', None):
                for sub in q.sub_questions:
                    sub.answer = ''

    # 试卷总分（Exam 无 total_score 字段）：questions 已按 result.exam_id
    # 全量加载，直接复用求和，避免重复查询（此前冗余二次全表查询）
    exam_total_score = None
    try:
        exam_total_score = sum(q.score or 0 for q in questions)
    except Exception:
        exam_total_score = None

    return render_template('result.html',
                           result=result,
                           exam=exam,
                           student=student,
                           questions=questions,
                           answers=answers,
                           scores=scores,
                           python_files=python_files,
                           exam_total_score=exam_total_score,
                           show_solutions=show_solutions)
