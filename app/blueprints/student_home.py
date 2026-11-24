# -*- coding: utf-8 -*-
"""学生“今日学习”首页。

设计目标：先给一个明确的下一步，再展示今日节奏、任务、学习路径和最近反馈；
知识路径只做「学科 → 资源/章节」的可解释版本，不虚构细粒度概念图谱。
"""
import json
from datetime import datetime, timedelta

from flask import Blueprint, redirect, render_template, session, url_for

from app.decorators import login_required
from app.extensions import db
from app.models import (Class, ClassSchedule, ClassroomSession, Exam,
                        Homework, HomeworkSubmission, LearningActivity,
                        Resource, ResourceQuizResult, Result, Student,
                        StudentWork, Subject, Survey, SurveyAnswer,
                        TeachingSession, homework_classes)
from app.services.resource_access import (student_can_access_resource,
                                          student_classroom_scoped_resources)
from app.utils import get_schedules_cached

student_home_bp = Blueprint('student_home', __name__, url_prefix='')

_WEEKDAY_NAMES = ClassSchedule.WEEKDAY_NAMES
_GRADE_PCT = {'优秀': 90, '良好': 80, '合格': 60, '不合格': 40}


def _resource_url(res):
    if not res:
        return url_for('resources.study')
    if (res.url or '').startswith('/chem-lab'):
        return url_for('chem_lab.chem_lab_index')
    if (res.url or '').startswith(('http://', 'https://')):
        return url_for('resources.study_link', url=res.url, title=res.title,
                       resource_id=res.id, quiz_mode=res.quiz_mode or 'inject')
    return url_for('resources.study_lesson', resource_id=res.id)


def _due_label(deadline, now):
    if not deadline:
        return '不限时', 'secondary', 9
    if deadline < now:
        return '已逾期', 'danger', 0
    days = (deadline.date() - now.date()).days
    if days == 0:
        return f'今天 {deadline:%H:%M}', 'danger', 1
    if days == 1:
        return f'明天 {deadline:%H:%M}', 'warning', 2
    return deadline.strftime('%m-%d %H:%M'), 'secondary', 5


def _chapter_title(res):
    try:
        tree = json.loads(res.lesson_tree or '[]')
        if isinstance(tree, list) and tree and isinstance(tree[0], dict):
            return str(tree[0].get('title') or '').strip()
    except Exception:
        pass
    return ''


def _quiz_pct(row):
    if row is None:
        return None
    try:
        if row.max_score and row.total_score is not None:
            return max(0.0, min(100.0, row.total_score / row.max_score * 100))
        if row.question_count and row.correct_count is not None:
            return max(0.0, min(100.0, row.correct_count / row.question_count * 100))
    except Exception:
        pass
    return _GRADE_PCT.get((row.grade or '').strip())


def _mastery(pct):
    if pct is None:
        return '未评估', 'secondary'
    if pct >= 85:
        return '已掌握', 'success'
    if pct >= 60:
        return '学习中', 'primary'
    return '需加强', 'danger'


@student_home_bp.route('/student/home')
@login_required
def student_home():
    student = db.session.get(Student, session.get('student_id'))
    if not student:
        return redirect(url_for('auth.login'))
    now = datetime.now()
    cls = db.session.get(Class, student.class_id) if student.class_id else None
    class_name = cls.name if cls else ''
    schedules = get_schedules_cached()
    weekday = now.isoweekday()
    today_rows = (ClassSchedule.query.filter_by(
        class_name=class_name, weekday=weekday).all() if class_name else [])
    period_numbers = {row.period_number for row in today_rows}

    # ── 今日课堂与当前教学资源 ──
    day_start = datetime(now.year, now.month, now.day)
    day_end = day_start + timedelta(days=1)
    today_sessions = (TeachingSession.query.filter(
        TeachingSession.class_id == student.class_id,
        TeachingSession.start_time >= day_start,
        TeachingSession.start_time < day_end,
    ).order_by(TeachingSession.start_time).all()
        if student.class_id else [])
    active_classroom = (ClassroomSession.query.filter_by(
        class_id=student.class_id, is_active=True).first()
        if student.class_id else None)
    current_teaching = (TeachingSession.query.filter_by(
        class_id=student.class_id, end_time=None).order_by(
            TeachingSession.start_time.desc()).first()
        if student.class_id else None)
    active_resource = None
    if current_teaching:
        candidate = db.session.get(Resource, current_teaching.resource_id)
        if candidate and student_can_access_resource(candidate, student):
            active_resource = candidate

    # ── 今日作业/测试/活动/问卷 ──
    submitted = db.session.query(HomeworkSubmission.homework_id).filter(
        HomeworkSubmission.student_id == student.id)
    homeworks = (Homework.query.join(
        homework_classes, homework_classes.c.homework_id == Homework.id)
        .filter(homework_classes.c.class_id == student.class_id,
                Homework.is_active.is_(True),
                ~Homework.id.in_(submitted)).all()
        if student.class_id else [])
    homeworks.sort(key=lambda h: (h.deadline is None,
                                  h.deadline or datetime.max))
    done_exams = db.session.query(Result.exam_id).filter(
        Result.student_id == student.id)
    exams = Exam.query.filter(
        Exam.is_active.is_(True), Exam.is_visible.is_(True),
        Exam.is_enabled.is_(True), ~Exam.id.in_(done_exams)
    ).order_by(Exam.create_time.desc()).all()

    scoped_resources = student_classroom_scoped_resources(student.class_id)
    scoped_ids = [r.id for r in scoped_resources]
    activities = (LearningActivity.query.filter(
        LearningActivity.resource_id.in_(scoped_ids),
        LearningActivity.is_active.is_(True)).order_by(
            LearningActivity.sort_order).all() if scoped_ids else [])
    done_activity_ids = {
        row[0] for row in db.session.query(StudentWork.activity_id).filter(
            StudentWork.student_id == student.id,
            StudentWork.activity_id.in_(
                [a.id for a in activities] or [0])).all()
    }
    pending_activities = [
        a for a in activities
        if a.require_upload and a.id not in done_activity_ids
        and (a.start_time is None or a.start_time <= now)
        and (a.end_time is None or a.end_time >= now)
    ]
    surveys = (Survey.query.filter(
        Survey.resource_id.in_(scoped_ids),
        Survey.status == 'published').order_by(
            Survey.sort_order, Survey.created_at.desc()).all()
        if scoped_ids else [])
    done_survey_ids = {
        row[0] for row in db.session.query(SurveyAnswer.survey_id).filter(
            SurveyAnswer.student_id == student.id,
            SurveyAnswer.survey_id.in_(
                [s.id for s in surveys] or [0])).all()
    }
    pending_surveys = [
        s for s in surveys
        if s.id not in done_survey_ids
        and (s.start_time is None or s.start_time <= now)
        and (s.end_time is None or s.end_time >= now)
    ]

    # ── 今日节奏 ──
    timeline = []
    for idx, sched in enumerate(schedules, 1):
        if idx not in period_numbers:
            continue
        if now.strftime('%H:%M') < sched.start_time:
            state = 'upcoming'
        elif sched.start_time <= now.strftime('%H:%M') <= sched.end_time:
            state = 'current'
        else:
            state = 'past'
        session_row = next((row for row in today_sessions
                            if sched.start_time <= row.start_time.strftime(
                                '%H:%M') <= sched.end_time), None)
        resource = session_row.resource if session_row else None
        timeline.append({
            'period': sched.period_name,
            'start': sched.start_time,
            'end': sched.end_time,
            'state': state,
            'resource': resource.title if resource else '',
            'subject': (resource.subject.name
                        if resource and resource.subject else ''),
            'url': _resource_url(resource) if resource else '',
        })
    current_period = next((item for item in timeline
                           if item['state'] == 'current'), None)
    next_period = next((item for item in timeline
                        if item['state'] == 'upcoming'), None)

    # ── 任务 ──
    tasks = []

    def add_task(kind, title, meta, badge, css, url, order=5):
        tasks.append({'kind': kind, 'title': title, 'meta': meta,
                      'badge': badge, 'css': css, 'url': url,
                      'order': order})

    for hw in homeworks[:3]:
        label, css, order = _due_label(hw.deadline, now)
        subject = hw.subject.name if hw.subject else ''
        teacher = hw.teacher.display_name if hw.teacher else ''
        add_task('homework', hw.title,
                 ' · '.join(x for x in (subject, teacher) if x),
                 label, css,
                 url_for('homework.student_homework_submit', hw_id=hw.id),
                 order)
    for exam in exams[:1]:
        add_task('exam', exam.name,
                 exam.subject.name if exam.subject else '在线测试',
                 '待完成', 'primary',
                 url_for('online_exam.online_exam', exam_id=exam.id), 4)
    for act in pending_activities[:1]:
        add_task('activity', act.title,
                 act.resource.title if act.resource else '学习活动',
                 '需提交', 'warning',
                 url_for('activities.student_activity', act_id=act.id), 4)
    for sv in pending_surveys[:1]:
        add_task('survey', sv.title,
                 sv.resource.title if sv.resource else '调查问卷',
                 '待填写', 'primary',
                 url_for('surveys.student_survey', sid=sv.id), 4)
    tasks.sort(key=lambda item: item['order'])
    tasks = tasks[:5]

    # ── 最近反馈 ──
    feedback = None
    sub = HomeworkSubmission.query.filter(
        HomeworkSubmission.student_id == student.id,
        HomeworkSubmission.grade.isnot(None)).order_by(
            HomeworkSubmission.submit_time.desc()).first()
    result = Result.query.join(
        Exam, Result.exam_id == Exam.id).filter(
            Result.student_id == student.id,
            Exam.allow_view_results.is_(True)).order_by(
                Result.submit_time.desc()).first()
    result_exam = (db.session.get(Exam, result.exam_id)
                   if result else None)
    if sub and (not result or (sub.submit_time or datetime.min) >=
                (result.submit_time or datetime.min)):
        feedback = {
            'title': f'作业反馈：{sub.homework.title if sub.homework else "作业"}',
            'detail': f'等级 {sub.grade}' + (
                f' · {sub.feedback}' if sub.feedback else ''),
            'url': url_for('homework.student_homework_result',
                           hw_id=sub.homework_id),
        }
    elif result:
        feedback = {
            'title': f'试卷：{result_exam.name if result_exam else "测试"}',
            'detail': (f'得分 {result.total_score:g}'
                       if result.total_score is not None else '已完成'),
            'url': url_for('online_exam.show_result', result_id=result.id),
        }

    # ── 继续学习 ──
    continue_item = None
    last_session = (TeachingSession.query.filter(
        TeachingSession.class_id == student.class_id,
        TeachingSession.resource_id.isnot(None)).order_by(
            TeachingSession.start_time.desc()).first()
        if student.class_id else None)
    if last_session:
        last_res = db.session.get(Resource, last_session.resource_id)
        if (last_res and last_res is not active_resource
                and student_can_access_resource(last_res, student)):
            continue_item = {
                'title': last_res.title,
                'meta': '上次课堂',
                'url': _resource_url(last_res),
            }

    # ── 学习路径（学科 → 资源/章节；可解释、不虚构细粒度图谱）──
    subject_id = None
    if active_resource and active_resource.subject_id:
        subject_id = active_resource.subject_id
    if not subject_id and homeworks and homeworks[0].subject_id:
        subject_id = homeworks[0].subject_id
    if not subject_id and result_exam and result_exam.subject_id:
        subject_id = result_exam.subject_id
    if not subject_id and scoped_resources:
        # 优先教师/校本资源所属学科，避免首页总被内置公共资源带偏
        candidates = [r for r in scoped_resources if not r.is_builtin]
        candidates = candidates or scoped_resources
        subject_id = next((r.subject_id for r in candidates
                           if r.subject_id), None)
    path_resources = [r for r in scoped_resources
                      if r.subject_id == subject_id][:4] if subject_id else []
    if not path_resources:
        path_resources = scoped_resources[:4]
    quiz_rows = (ResourceQuizResult.query.filter(
        ResourceQuizResult.student_id == student.id,
        ResourceQuizResult.resource_id.in_([r.id for r in path_resources])
    ).order_by(ResourceQuizResult.submit_time.desc()).all()
        if path_resources else [])
    latest_quiz = {}
    for row in quiz_rows:
        latest_quiz.setdefault(row.resource_id, row)
    path_nodes = []
    for res in path_resources:
        pct = _quiz_pct(latest_quiz.get(res.id))
        label, css = _mastery(pct)
        path_nodes.append({
            'title': res.title,
            'chapter': _chapter_title(res),
            'url': _resource_url(res),
            'mastery': label,
            'css': css,
            'pct': pct,
            'evidence': (f'最近检测 {pct:.0f}%' if pct is not None
                         else '暂无检测记录'),
        })
    path_recommend = None
    if path_nodes:
        weak = [n for n in path_nodes
                if n['pct'] is not None and n['pct'] < 60]
        unknown = [n for n in path_nodes if n['pct'] is None]
        evaluated = [n for n in path_nodes if n['pct'] is not None]
        path_recommend = (weak[0] if weak else
                          unknown[0] if unknown else
                          min(evaluated, key=lambda n: n['pct']))
    path_subject = (db.session.get(Subject, subject_id)
                    if subject_id else None)
    if path_subject is None and path_resources:
        path_subject = next((r.subject for r in path_resources if r.subject),
                            None)

    # ── 今日主线：只给一个下一步 ──
    if active_classroom and active_resource:
        primary = {'title': f'进入《{active_resource.title}》课堂',
                   'detail': '老师已开启本节课的学习资源',
                   'reason': '你班正在上课，优先进入当前课堂',
                   'cta': '进入课堂', 'icon': 'fa-chalkboard-teacher',
                   'url': _resource_url(active_resource)}
    elif active_classroom:
        primary = {'title': '老师已开启课堂',
                   'detail': '进入学习资源查看本节课内容',
                   'reason': '你班正在上课',
                   'cta': '进入学习资源', 'icon': 'fa-chalkboard-teacher',
                   'url': url_for('resources.study')}
    elif homeworks:
        hw = homeworks[0]
        label, _css, _order = _due_label(hw.deadline, now)
        primary = {'title': f'提交《{hw.title}》',
                   'detail': label,
                   'reason': '这是最近到期的作业',
                   'cta': '去完成', 'icon': 'fa-tasks',
                   'url': url_for('homework.student_homework_submit',
                                  hw_id=hw.id)}
    elif exams:
        exam = exams[0]
        primary = {'title': f'完成《{exam.name}》',
                   'detail': '在线测试待完成',
                   'reason': '目前没有待交作业，先完成可用试卷',
                   'cta': '去测试', 'icon': 'fa-file-alt',
                   'url': url_for('online_exam.online_exam',
                                  exam_id=exam.id)}
    elif pending_activities:
        act = pending_activities[0]
        primary = {'title': f'完成活动《{act.title}》',
                   'detail': act.resource.title if act.resource else '',
                   'reason': '这是一项需要提交的学习活动',
                   'cta': '去完成', 'icon': 'fa-list-check',
                   'url': url_for('activities.student_activity',
                                  act_id=act.id)}
    elif pending_surveys:
        sv = pending_surveys[0]
        primary = {'title': f'填写《{sv.title}》',
                   'detail': sv.resource.title if sv.resource else '',
                   'reason': '这份问卷还未填写',
                   'cta': '去填写', 'icon': 'fa-poll',
                   'url': url_for('surveys.student_survey', sid=sv.id)}
    elif continue_item:
        primary = {'title': f'继续学习《{continue_item["title"]}》',
                   'detail': continue_item['meta'],
                   'reason': '今天暂时没有待办，继续上次课堂内容',
                   'cta': '继续', 'icon': 'fa-book-open',
                   'url': continue_item['url']}
    else:
        primary = {'title': '去学习资源看看',
                   'detail': '今天暂无待办',
                   'reason': '可以浏览资源或进行自主复习',
                   'cta': '浏览资源', 'icon': 'fa-book',
                   'url': url_for('resources.study')}

    if now.hour < 12:
        greeting = '早上好'
    elif now.hour < 18:
        greeting = '下午好'
    else:
        greeting = '晚上好'
    current_label = (current_period['period'] if current_period
                     else '课间 / 无课')
    current_time = (f"{current_period['start']}-{current_period['end']}"
                    if current_period else '按今日课表显示')

    return render_template(
        'student_home.html', student=student, cls=cls,
        greeting=greeting, now=now,
        date_label=f'{now:%Y年%m月%d日} {_WEEKDAY_NAMES.get(weekday, "")}',
        current_label=current_label, current_time=current_time,
        next_period=next_period, timeline=timeline,
        primary=primary, tasks=tasks,
        homework_count=len(homeworks), exam_count=len(exams),
        activity_count=len(pending_activities),
        survey_count=len(pending_surveys),
        feedback=feedback, continue_item=continue_item,
        path_nodes=path_nodes, path_recommend=path_recommend,
        path_subject=path_subject,
        welcome=session.pop('show_welcome', False))


@student_home_bp.route('/student/home/review/<int:resource_id>')
@login_required
def review_resource(resource_id):
    """“5 分钟复习”入口：校验资源范围后进入原资源/课堂页。"""
    res = db.session.get(Resource, resource_id)
    student = db.session.get(Student, session.get('student_id'))
    if not res or not student or not student_can_access_resource(res, student):
        return redirect(url_for('student_home.student_home'))
    return redirect(_resource_url(res))
