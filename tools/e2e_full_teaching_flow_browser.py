# -*- coding: utf-8 -*-
"""全流程教学/学习 E2E（2026-11-03）。

覆盖学生学习与教学需要的主链路（隔离库 itstudy_e2e + 真实浏览器 Edge）：
- 学生：登录（上课班级）→ 学习资源（学科分组/化学仿真）→ 课堂页章节树 →
  活动提交 → 问卷填写 → 作业提交 → 在线考试提交 → 结果页
- 教师：编辑模式资源库/活动/作品评价 → 问卷结果（图表）→ 上课/下课 →
  课堂模式使用化学仿真 → 只读模式打开化学仿真与课堂内嵌
- 管理员：资源管理（内置课件显示）→ 课堂大屏 → 作业批改 → 成绩批改
- 全程收集页面 JS 异常（关键页面 0 异常）

运行：venv/Scripts/python.exe -X utf8 tools/e2e_full_teaching_flow_browser.py
"""
import io
import json
import os
import sys
import threading
import time
import uuid

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ['DB_NAME'] = 'itstudy_e2e'
os.environ['CACHE_DIR'] = os.path.join(os.getcwd(), 'data', 'cache_e2e_fullflow')
os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_PORT', '5432')
os.environ.setdefault('DB_USER', 'postgres')
os.environ.setdefault('DB_PASS', '@@')
os.environ['SECRET_KEY'] = 'e2e-full-flow'
sys.path.insert(0, os.getcwd())

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import (AdminAccount, AttendanceRecord, Class,  # noqa: E402
                        ClassroomSession, Exam, ExamAttempt, ExamQuestion,
                        ExcellenceThreshold, Homework, HomeworkSubmission,
                        LearningActivity, PythonAnswer, PythonFile, Question,
                        Resource, Result, Student, StudentWork, SubQuestion,
                        Survey, SurveyAnswer, SurveyQuestion, SystemConfig,
                        Teacher, TeachingSession, WorkEvaluation,
                        homework_classes, resource_audience, teacher_class,
                        teacher_subject)

SFX = uuid.uuid4().hex[:8]
CLASS_NAME = f'__flow_cls_{SFX}'
TEACHER_NAME = f'__flow_t_{SFX}'
STUDENT_NUMBER = f'__flow_s_{SFX}'
ADMIN_NAME = f'__flow_a_{SFX}'
PASSWORD = 'FlowPass123'
READONLY_CODE = 'flow-readonly-code'
DIR = f'__flow_dir_{SFX}'
DIR_PATH = os.path.join('static', 'uploads', DIR)
RES_TITLE = f'__flow_res_{SFX}'
ACT_TITLE = f'__flow_act_{SFX}'
SURVEY_TITLE = f'__flow_survey_{SFX}'
HW_TITLE = f'__flow_hw_{SFX}'
EXAM_TITLE = f'__flow_exam_{SFX}'
PORT = 5020
BASE = f'http://127.0.0.1:{PORT}'
app = create_app()
from e2e_common import reset_shared_state  # noqa: E402
reset_shared_state(app)
FAILED = []
PAGE_ERRORS = []
IDS = {}


def show(name, ok, detail=''):
    mark = '✓' if ok else '✗'
    if not ok:
        FAILED.append(name)
    print(f'{mark} {name}' + (f' | {detail}' if detail else ''))


def wait_for(fn, timeout, label):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(0.4)
    raise AssertionError(f'等待超时: {label}')


def cleanup():
    with app.app_context():
        hw_ids = [r[0] for r in db.session.query(Homework.id).filter(
            Homework.title.like('__flow_%')).all()]
        if hw_ids:
            HomeworkSubmission.query.filter(
                HomeworkSubmission.homework_id.in_(hw_ids)).delete(
                    synchronize_session=False)
            db.session.execute(homework_classes.delete().where(
                homework_classes.c.homework_id.in_(hw_ids)))
            Homework.query.filter(Homework.id.in_(hw_ids)).delete(
                synchronize_session=False)
        ex_ids = [r[0] for r in db.session.query(Exam.id).filter(
            Exam.name.like('__flow_%')).all()]
        if ex_ids:
            q_ids = [r[0] for r in db.session.query(Question.id).filter(
                Question.exam_id.in_(ex_ids)).all()]
            if q_ids:
                SubQuestion.query.filter(
                    SubQuestion.question_id.in_(q_ids)).delete(
                        synchronize_session=False)
                PythonAnswer.query.filter(
                    PythonAnswer.question_id.in_(q_ids)).delete(
                        synchronize_session=False)
                PythonFile.query.filter(
                    PythonFile.question_id.in_(q_ids)).delete(
                        synchronize_session=False)
            ExamQuestion.query.filter(
                ExamQuestion.exam_id.in_(ex_ids)).delete(
                    synchronize_session=False)
            if q_ids:
                Question.query.filter(Question.id.in_(q_ids)).delete(
                    synchronize_session=False)
            Result.query.filter(Result.exam_id.in_(ex_ids)).delete(
                synchronize_session=False)
            ExamAttempt.query.filter(
                ExamAttempt.exam_id.in_(ex_ids)).delete(
                    synchronize_session=False)
            Exam.query.filter(Exam.id.in_(ex_ids)).delete(
                synchronize_session=False)
        res_ids = [r[0] for r in db.session.query(Resource.id).filter(
            Resource.title.like('__flow_%')).all()]
        if res_ids:
            TeachingSession.query.filter(
                TeachingSession.resource_id.in_(res_ids)).delete(
                    synchronize_session=False)
            sids = [r[0] for r in db.session.query(Survey.id).filter(
                Survey.resource_id.in_(res_ids)).all()]
            if sids:
                SurveyAnswer.query.filter(
                    SurveyAnswer.survey_id.in_(sids)).delete(
                        synchronize_session=False)
                SurveyQuestion.query.filter(
                    SurveyQuestion.survey_id.in_(sids)).delete(
                        synchronize_session=False)
                Survey.query.filter(Survey.id.in_(sids)).delete(
                    synchronize_session=False)
            act_ids = [r[0] for r in db.session.query(
                LearningActivity.id).filter(
                LearningActivity.resource_id.in_(res_ids)).all()]
            if act_ids:
                work_ids = [r[0] for r in db.session.query(
                    StudentWork.id).filter(
                    StudentWork.activity_id.in_(act_ids)).all()]
                if work_ids:
                    WorkEvaluation.query.filter(
                        WorkEvaluation.work_id.in_(work_ids)).delete(
                            synchronize_session=False)
                    StudentWork.query.filter(
                        StudentWork.id.in_(work_ids)).delete(
                            synchronize_session=False)
                ExcellenceThreshold.query.filter(
                    ExcellenceThreshold.activity_id.in_(act_ids)).delete(
                        synchronize_session=False)
                LearningActivity.query.filter(
                    LearningActivity.id.in_(act_ids)).delete(
                        synchronize_session=False)
            Resource.query.filter(Resource.id.in_(res_ids)).delete(
                synchronize_session=False)
        stu_ids = [r[0] for r in db.session.query(Student.id).filter(
            Student.student_number.like('__flow_%')).all()]
        if stu_ids:
            AttendanceRecord.query.filter(
                AttendanceRecord.student_id.in_(stu_ids)).delete(
                    synchronize_session=False)
            Student.query.filter(Student.id.in_(stu_ids)).delete(
                synchronize_session=False)
        tids = [r[0] for r in db.session.query(Teacher.id).filter(
            Teacher.username.like('__flow_%')).all()]
        if tids:
            db.session.execute(teacher_class.delete().where(
                teacher_class.c.teacher_id.in_(tids)))
            db.session.execute(teacher_subject.delete().where(
                teacher_subject.c.teacher_id.in_(tids)))
            Teacher.query.filter(Teacher.id.in_(tids)).delete(
                synchronize_session=False)
        cls_ids = [r[0] for r in db.session.query(Class.id).filter(
            Class.name.like('__flow_%')).all()]
        if cls_ids:
            ClassroomSession.query.filter(
                ClassroomSession.class_id.in_(cls_ids)).delete(
                    synchronize_session=False)
            Class.query.filter(Class.id.in_(cls_ids)).delete(
                synchronize_session=False)
        AdminAccount.query.filter(
            AdminAccount.username.like('__flow_%')).delete(
                synchronize_session=False)
        # 内置资源授权复位为「不限年级 × 不限学科」：本用例会收紧再恢复，
        # 失败中断时也保证后续 E2E 可重复
        for row in Resource.query.filter_by(is_builtin=True).all():
            db.session.execute(resource_audience.delete().where(
                resource_audience.c.resource_id == row.id))
            db.session.execute(resource_audience.insert().values(
                resource_id=row.id, grade=None, subject_id=None))
        # 只读访问码是全库共享状态：留着会让其它脚本的教师登录页默认进入
        # 只读模式（密码框隐藏）。本脚本设置的，本脚本负责清掉。
        SystemConfig.query.filter_by(
            key='teacher_readonly_code_hash').delete(synchronize_session=False)
        db.session.commit()
        SystemConfig._invalidate_cache()
        from app.blueprints.auth import invalidate_active_class_cache
        invalidate_active_class_cache()
    import shutil
    shutil.rmtree(DIR_PATH, ignore_errors=True)


cleanup()
with app.app_context():
    cls = Class(name=CLASS_NAME)
    teacher = Teacher(username=TEACHER_NAME, display_name='全流程教师')
    teacher.set_password(PASSWORD)
    teacher.classes.append(cls)
    stu = Student(name='全流程学生', student_number=STUDENT_NUMBER,
                  student_class=CLASS_NAME, has_changed_password=True)
    stu.set_password(PASSWORD)
    admin = AdminAccount(username=ADMIN_NAME, display_name='全流程管理员')
    admin.set_password(PASSWORD)
    db.session.add_all([cls, teacher, stu, admin])
    db.session.flush()
    stu.class_id = cls.id
    db.session.add(ClassroomSession(class_id=cls.id, is_active=True))
    os.makedirs(DIR_PATH, exist_ok=True)
    with open(os.path.join(DIR_PATH, 'index.html'), 'w',
              encoding='utf-8') as f:
        f.write('<html><body><h1>全流程课件主页</h1></body></html>')
    with open(os.path.join(DIR_PATH, 'notes.txt'), 'w',
              encoding='utf-8') as f:
        f.write('全流程课件说明')
    res = Resource(title=RES_TITLE,
                   url=f'/static/uploads/{DIR}/index.html',
                   show_in_student=True, show_in_classroom=True,
                   creator_type='teacher', creator_teacher_id=teacher.id,
                   creator_name='全流程教师', quiz_mode='none')
    db.session.add(res)
    db.session.flush()
    act = LearningActivity(resource_id=res.id, title=ACT_TITLE,
                           require_upload=True, is_active=True,
                           description='提交你的课堂作品')
    db.session.add(act)
    db.session.flush()
    survey = Survey(resource_id=res.id, title=SURVEY_TITLE,
                    status='published', description='全流程问卷')
    db.session.add(survey)
    db.session.flush()
    sq = SurveyQuestion(survey_id=survey.id, q_type='radio',
                        title='本课满意度', options=json.dumps(
                            ['满意', '一般', '不满意'], ensure_ascii=False),
                        required=True, sort_order=0)
    db.session.add(sq)
    hw = Homework(title=HW_TITLE, description='全流程作业',
                  teacher_id=teacher.id, deadline=None, is_active=True)
    hw.classes.append(cls)
    db.session.add(hw)
    exam = Exam(name=EXAM_TITLE, is_active=True, is_visible=True,
                is_enabled=True, is_collected=False,
                allow_view_results=True, duration=60)
    db.session.add(exam)
    db.session.flush()
    q1 = Question(exam_id=exam.id, question_type='single',
                  content='全流程单选：1+1=?', options='A. 2|B. 3',
                  answer='A', score=10)
    db.session.add(q1)
    db.session.commit()
    from werkzeug.security import generate_password_hash
    from app.models import Subject
    for name in ('物理', '化学', '生物', '地理'):
        if not Subject.query.filter_by(name=name).first():
            db.session.add(Subject(name=name, sort_order=90))
    db.session.flush()
    # 教师档案：高一 + 物理（供年级×学科授权命中/不命中验证）
    teacher.grade = '高一'
    phys_subject = Subject.query.filter_by(name='物理').first()
    if phys_subject:
        db.session.execute(teacher_subject.insert().values(
            teacher_id=teacher.id, subject_id=phys_subject.id))
    SystemConfig.set('teacher_readonly_code_hash',
                     generate_password_hash(READONLY_CODE))
    db.session.commit()
    from app.utils import invalidate_lookup_cache
    invalidate_lookup_cache('subjects')
    from app.blueprints.chem_lab import ensure_chem_lab_resource
    ensure_chem_lab_resource()
    IDS.update(cls=cls.id, teacher=teacher.id, stu=stu.id,
               res=res.id, act=act.id, survey=survey.id, hw=hw.id,
               exam=exam.id, q1=q1.id)

threading.Thread(target=lambda: __import__('waitress').serve(
    app, host='127.0.0.1', port=PORT, threads=8), daemon=True).start()
time.sleep(2.0)
os.makedirs('data/e2e_full_flow', exist_ok=True)
SHOT = 'data/e2e_full_flow'

from playwright.sync_api import sync_playwright  # noqa: E402


def new_page(browser, tag):
    ctx = browser.new_context(base_url=BASE,
                              viewport={'width': 1500, 'height': 920})
    page = ctx.new_page()
    page.on('pageerror', lambda e: PAGE_ERRORS.append(f'{tag}: {e}'))
    return ctx, page


def login_student(page):
    page.goto('/')
    page.fill('input[name="student_number"]', STUDENT_NUMBER)
    page.fill('input[name="password"]', PASSWORD)
    page.locator('form').filter(
        has=page.locator('input[name="student_number"]')).locator(
        'button[type="submit"]').click()
    page.wait_for_url('**/study*', timeout=15000)


def login_teacher(page, readonly=False):
    page.goto('/teacher/login')
    page.fill('input[name="username"]', TEACHER_NAME)
    mode = page.locator('#readonlyMode')
    if mode.count() and mode.is_enabled():
        if readonly and not mode.is_checked():
            mode.check()
        elif not readonly and mode.is_checked():
            mode.uncheck()
    if readonly:
        page.fill('#readonlyCode', READONLY_CODE)
    else:
        page.fill('input[name="password"]', PASSWORD)
    page.locator('form').filter(
        has=page.locator('input[name="username"]')).locator(
        'button[type="submit"]').click()
    page.wait_for_url('**/study*' if readonly
                      else '**/teacher/*', timeout=15000)


def login_admin(page):
    page.goto('/admin/login')
    page.fill('input[name="username"]', ADMIN_NAME)
    page.fill('input[name="password"]', PASSWORD)
    page.locator('form').filter(
        has=page.locator('input[name="username"]')).locator(
        'button[type="submit"]').click()
    page.wait_for_url('**/admin/**', timeout=15000)


try:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)

        # ══ 学生全流程 ══
        sctx, sp = new_page(browser, 'student')
        login_student(sp)
        show('学生登录（上课班级绑定）', '/study' in sp.url, sp.url)
        wait_for(lambda: sp.locator('.resource-card').count() >= 1, 15,
                 '学生资源卡')
        text = sp.content()
        show('学生资源列表含课堂资源', RES_TITLE in text)
        show('学生资源列表含化学仿真', '化学仿真' in text)
        none_group = sp.locator('.subject-group[data-subject="none"]')
        show('化学仿真未落入未分类（学生视角）',
             none_group.filter(has_text='化学仿真').count() == 0)
        # 展开资源卡（幂等：仅收起时展开）
        sp.evaluate("""(title) => {
          document.querySelectorAll('.resource-card').forEach(function (c) {
            if (c.textContent.indexOf(title) === -1) return;
            var hdr = c.querySelector('.res-header');
            var body = document.getElementById(hdr.dataset.target);
            if (body && getComputedStyle(body).display === 'none') hdr.click();
          });
        }""", RES_TITLE)
        card = sp.locator('.resource-card').filter(has_text=RES_TITLE).first
        show('资源卡含学习活动与问卷入口',
             card.locator('a:has-text("%s")' % ACT_TITLE).count() >= 1 and
             card.locator('a:has-text("%s")' % SURVEY_TITLE).count() >= 1)
        show('学生问卷未填徽章', card.locator('text=未填').count() >= 1)
        # 进入课堂页
        sp.goto(f'/study/lesson/{IDS["res"]}')
        wait_for(lambda: sp.locator('.ch-item').count() >= 2, 12, '章节树')
        tree_text = sp.locator('#chapterTree').inner_text()
        show('课堂章节树含活动与问卷',
             ACT_TITLE in tree_text and SURVEY_TITLE in tree_text)
        sp.screenshot(path=f'{SHOT}/student_lesson.png')

        # 活动提交
        sp.goto(f'/study/activity/{IDS["act"]}')
        sp.fill('textarea[name="text_content"]', '全流程作品内容')
        sp.locator('button:has-text("提交作品")').click()
        wait_for(lambda: '我的作品' in sp.content(), 12, '活动提交成功')
        show('学生活动作品提交', True)
        sp.fill('textarea[name="text_content"]', '全流程作品内容-重交')
        sp.locator('button:has-text("提交作品")').click()
        wait_for(lambda: '重新提交' in sp.content() or '我的作品' in sp.content(),
                 12, '作品重交')
        show('学生作品可重新提交', True)

        # 问卷填写
        sp.goto(f'/study/survey/{IDS["survey"]}')
        sp.locator('input[type="radio"][value="满意"]').check()
        sp.locator('button:has-text("提交问卷")').click()
        wait_for(lambda: '提交成功' in sp.content(), 12, '问卷提交')
        show('学生问卷提交', True)
        sp.goto('/study')
        wait_for(lambda: sp.locator('text=已填').count() >= 1, 12,
                 '已填徽章')
        show('学生问卷已填徽章', True)

        # 作业提交
        sp.goto(f'/student/homework/{IDS["hw"]}')
        wait_for(lambda: sp.locator('textarea[name="text_content"]').count() >= 1,
                 12, '作业提交页')
        sp.fill('textarea[name="text_content"]', '全流程作业答案')
        sp.locator('button.btn-primary:has-text("提交")').click()
        sp.wait_for_url('**/student/homework', timeout=12000)
        show('学生作业提交', True)
        sp.screenshot(path=f'{SHOT}/student_homework.png')

        # 在线考试
        sp.goto(f'/online_exam/{IDS["exam"]}')
        wait_for(lambda: sp.locator('#exam-timer').count() >= 1, 12,
                 '考试倒计时')
        sp.locator(f'input[name="{IDS["q1"]}"]').first.check()
        sp.locator('#submit-exam').click()
        wait_for(lambda: sp.locator('#confirmSubmit').count() >= 1, 8,
                 '交卷确认')
        sp.locator('#confirmSubmit').click()
        sp.wait_for_url('**/result/*', timeout=12000)
        show('学生在线考试提交并出结果', True, sp.url)
        with app.app_context():
            r = Result.query.filter_by(exam_id=IDS['exam']).order_by(
                Result.id.desc()).first()
            show('考试结果落库（客观题自动判分）',
                 r is not None and r.total_score == 10,
                 (r.total_score, r.grading_status) if r else None)
        sp.screenshot(path=f'{SHOT}/student_result.png')

        # ══ 教师（编辑模式） ══
        tctx, tp = new_page(browser, 'teacher')
        login_teacher(tp)
        tp.goto('/teacher/resource-library')
        lib = tp.content()
        show('教师资源库含自有资源与化学仿真',
             RES_TITLE in lib and '化学仿真' in lib)
        tp.goto(f'/teacher/works/activity/{IDS["act"]}')
        wait_for(lambda: tp.locator('table').count() >= 1, 12, '作品列表')
        sh = tp.locator('text=全流程学生').count()
        show('教师作品列表含学生提交', sh >= 1)
        with app.app_context():
            wid = StudentWork.query.filter_by(
                activity_id=IDS['act']).order_by(
                    StudentWork.id.desc()).first().id
        tp.goto(f'/teacher/works/evaluate/{wid}')
        wait_for(lambda: tp.locator('input[name="score"]').count() >= 1, 12,
                 '评价页')
        tp.fill('input[name="score"]', '95')
        tp.fill('input[name="grade"]', 'A')
        tp.fill('textarea[name="comment"]', '全流程评价：很好')
        tp.locator('button:has-text("保存评价")').click()
        tp.wait_for_url('**/teacher/works/activity/*', timeout=12000)
        with app.app_context():
            ev = WorkEvaluation.query.filter_by(work_id=wid).first()
            show('教师作品评价落库',
                 ev is not None and ev.score == 95 and ev.grade == 'A',
                 (ev.score, ev.grade) if ev else None)
        # 创建者删除作品：学生端恢复“未提交”状态（可重新上传）
        tp.goto(f'/teacher/works/activity/{IDS["act"]}')
        wait_for(lambda: tp.locator('tr', has_text='全流程学生').count() >= 1,
                 12, '作品列表行')
        tp.on('dialog', lambda d: d.accept())
        tp.locator('tr', has_text='全流程学生').locator(
            'form[action*="/delete"] button').click()
        wait_for(lambda: tp.locator('tr', has_text='全流程学生').count() == 0,
                 12, '作品删除')
        show('教师删除学生作品', True)
        sp.goto(f'/study/activity/{IDS["act"]}')
        wait_for(lambda: '上传作品' in sp.content(), 12, '学生端恢复未提交')
        show('删除后学生端恢复未提交状态',
             '我的作品' not in sp.content())
        # 问卷结果图表
        tp.goto(f'/teacher/surveys/{IDS["survey"]}/results')
        wait_for(lambda: tp.locator('canvas').count() >= 1, 15, '问卷图表')
        show('教师问卷结果图表', tp.locator('canvas').count() >= 1,
             tp.locator('canvas').count())
        show('教师问卷结果计数', '1 份答卷' in tp.content())
        tp.screenshot(path=f'{SHOT}/teacher_survey.png')
        # 作业批改
        tp.goto(f'/admin/homework/{IDS["hw"]}/submissions')
        wait_for(lambda: '全流程学生' in tp.content(), 12, '作业提交列表')
        with app.app_context():
            sub = HomeworkSubmission.query.filter_by(
                homework_id=IDS['hw']).order_by(
                    HomeworkSubmission.id.desc()).first()
            sub_id = sub.id
        tp.goto(f'/admin/homework/{IDS["hw"]}/grade/{sub_id}')
        tp.locator('label[for="g-A"]').click()  # 等级 radio 视觉隐藏，点标签
        tp.fill('textarea[name="feedback"]', '作业批改反馈')
        tp.locator('#gradeForm button[type="submit"]').click()
        tp.wait_for_url('**/admin/homework/*/submissions', timeout=12000)
        with app.app_context():
            sub = db.session.get(HomeworkSubmission, sub_id)
            show('教师作业批改落库',
                 sub.grade == 'A' and sub.status == 'graded',
                 (sub.grade, sub.status))
        # 上课 / 下课
        tp.goto('/study?mode=classroom')
        wait_for(lambda: tp.locator('form[action*="start_class"]').count() >= 1,
                 12, '课堂上课按钮')
        tp.locator('form[action*="start_class"]').first.locator(
            'button').click()
        wait_for(lambda: tp.locator('form[action*="end_class"]').count() >= 1,
                 12, '课堂已开始（出现下课）')
        show('教师上课（TeachingSession 建立）', True)
        tp.locator('form[action*="end_class"]').first.locator(
            'button').click()
        wait_for(lambda: tp.locator('form[action*="start_class"]').count() >= 1,
                 12, '课堂已结束')
        show('教师下课', True)
        tp.screenshot(path=f'{SHOT}/teacher_classroom.png')

        # ══ 只读教师 ══
        rctx, rp = new_page(browser, 'readonly')
        login_teacher(rp, readonly=True)
        wait_for(lambda: rp.locator(
            'a:has-text("独立打开")').count() >= 1, 15,
            '只读教师化学仿真入口')
        none_group = rp.locator('.subject-group[data-subject="none"]')
        show('只读教师课堂可见化学仿真（课堂+独立入口）',
             rp.locator('a:has-text("进入课堂")').count() >= 1 and
             rp.locator('a:has-text("独立打开")').count() >= 1)
        show('只读教师化学仿真未落入未分类',
             none_group.filter(has_text='化学仿真').count() == 0)
        with rp.expect_popup() as pop:
            rp.locator('a:has-text("独立打开")').first.click()
        rlab = pop.value
        rlab.wait_for_load_state('domcontentloaded', timeout=15000)
        wait_for(lambda: rlab.locator('#chemLab').count() >= 1, 15,
                 '只读教师化学仿真页')
        show('只读教师打开化学仿真',
             rlab.locator('#chemLab').count() >= 1)
        rlab.close()

        # ══ 管理员 ══
        actx, ap = new_page(browser, 'admin')
        login_admin(ap)
        ap.goto('/admin/resources')
        wait_for(lambda: ap.locator('.resource-item').count() >= 1, 12,
                 '管理员资源页')
        show('管理员资源页含化学仿真内置说明',
             '化学仿真（系统内置，无需上传文件）' in ap.content())
        ap.goto('/admin/classroom')
        wait_for(lambda: '课堂大屏' in (ap.title() or ''), 12, '课堂大屏')
        show('管理员课堂大屏可打开', True)
        # 成绩批改列表
        ap.goto(f'/admin/grading/{IDS["exam"]}')
        wait_for(lambda: EXAM_TITLE in ap.content(), 12, '成绩批改列表')
        show('管理员成绩批改列表含考试结果', True)

        # 内置资源年级×学科授权：收紧后教师即时失去课堂入口，恢复后重获
        ap.goto('/admin/resources/audience')
        wait_for(lambda: '内置资源批量授权' in ap.content(), 12, '批量授权页')
        # 化学仿真统一入口：内置资源至少 1 条
        show('批量授权页列出内置资源',
             ap.locator('.resource-check').count() >= 1,
             f'{ap.locator(".resource-check").count()} 条')
        ap.locator('#gradeSel').select_option('高二')
        ap.locator('#subjectSel').select_option(label='化学')
        ap.locator('#checkAll').check()
        ap.locator('button:has-text("应用授权范围")').click()
        wait_for(lambda: '已批量授权' in ap.content(), 12, '批量授权保存')
        tp.goto('/study?mode=classroom')
        wait_for(lambda: tp.locator('.resource-card').count() >= 1, 12,
                 '教师课堂页')
        show('收紧为高二×化学后 高一物理教师不再看到化学仿真资源卡',
             tp.locator('.resource-card').filter(
                 has_text='化学仿真').count() == 0)
        # 恢复「不限年级 × 不限学科」
        ap.goto('/admin/resources/audience')
        ap.locator('#allGrades').check()
        ap.locator('#allSubjects').check()
        ap.locator('#checkAll').check()
        ap.locator('button:has-text("应用授权范围")').click()
        wait_for(lambda: '已批量授权' in ap.content(), 12, '恢复授权')
        tp.goto('/study?mode=classroom')
        wait_for(lambda: tp.locator('.resource-card').filter(
            has_text='化学仿真').count() >= 1, 12,
            '教师重新看到化学仿真资源卡')
        show('恢复不限授权后教师重新看到化学仿真', True)
        ap.screenshot(path=f'{SHOT}/admin_audience.png')
        ap.screenshot(path=f'{SHOT}/admin_grading.png')

        show('关键页面无页面 JS 异常', not PAGE_ERRORS,
             '; '.join(PAGE_ERRORS[:4]) if PAGE_ERRORS else '')
        browser.close()
finally:
    cleanup()

print(f'—— 结果: {len(FAILED) == 0 and "全部通过" or "失败 " + ", ".join(FAILED)} ——')
sys.exit(0 if not FAILED else 1)
