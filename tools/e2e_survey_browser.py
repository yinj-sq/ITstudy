# -*- coding: utf-8 -*-
"""调查问卷浏览器 E2E（2026-11-03；V6.1.0 起铜匠实验室已外置）。

验证：问卷全链路：教师编辑模式创建问卷（单选+多选+矩阵评分+填空）→ 发布 →
学生填写提交 → 教师结果页图表渲染与计数 → CSV 下载 → 学生已填回看。

运行：venv/Scripts/python.exe -X utf8 tools/e2e_survey_browser.py
"""
import io
import os
import sys
import threading
import time
import uuid

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ['DB_NAME'] = 'itstudy_e2e'
os.environ['CACHE_DIR'] = os.path.join(os.getcwd(), 'data', 'cache_e2e_survey')
os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_PORT', '5432')
os.environ.setdefault('DB_USER', 'postgres')
os.environ.setdefault('DB_PASS', '@@')
os.environ['SECRET_KEY'] = 'e2e-survey'
sys.path.insert(0, os.getcwd())

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import (AttendanceRecord, Class, ClassroomSession,  # noqa: E402
                        Resource, Student, Survey, SurveyAnswer,
                        SurveyQuestion, SystemConfig, Teacher, teacher_class)

SFX = uuid.uuid4().hex[:8]
CLASS_NAME = f'__csl_cls_{SFX}'
TEACHER_NAME = f'__csl_t_{SFX}'
STUDENT_NUMBER = f'__csl_s_{SFX}'
PASSWORD = 'CslPass123'
READONLY_CODE = 'csl-readonly-code'
RES_TITLE = f'__csl_res_{SFX}'
SURVEY_TITLE = f'课堂反馈小调查_{SFX}'
PORT = 5018
BASE = f'http://127.0.0.1:{PORT}'
app = create_app()
from e2e_common import reset_shared_state  # noqa: E402
reset_shared_state(app)
FAILED = []
IDS = {}


def check(name, ok, detail=''):
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
        if IDS.get('res'):
            sids = [row[0] for row in db.session.query(Survey.id).filter(
                Survey.resource_id == IDS['res']).all()]
            if sids:
                SurveyAnswer.query.filter(
                    SurveyAnswer.survey_id.in_(sids)).delete(
                        synchronize_session=False)
                SurveyQuestion.query.filter(
                    SurveyQuestion.survey_id.in_(sids)).delete(
                        synchronize_session=False)
                Survey.query.filter(Survey.id.in_(sids)).delete(
                    synchronize_session=False)
            Resource.query.filter_by(id=IDS['res']).delete(
                synchronize_session=False)
        if IDS.get('teacher'):
            db.session.execute(teacher_class.delete().where(
                teacher_class.c.teacher_id == IDS['teacher']))
            Teacher.query.filter_by(id=IDS['teacher']).delete(
                synchronize_session=False)
        if IDS.get('stu'):
            # 学生登录会写考勤记录（FK 引用），先清
            AttendanceRecord.query.filter_by(
                student_id=IDS['stu']).delete(synchronize_session=False)
            Student.query.filter_by(id=IDS['stu']).delete(
                synchronize_session=False)
        if IDS.get('cls'):
            ClassroomSession.query.filter_by(
                class_id=IDS['cls']).delete(synchronize_session=False)
            Class.query.filter_by(id=IDS['cls']).delete(
                synchronize_session=False)
        # 只读访问码是全库共享状态：留着会让其它脚本的教师登录页默认进入
        # 只读模式（密码框隐藏）。本脚本设置的，本脚本负责清掉。
        SystemConfig.query.filter_by(
            key='teacher_readonly_code_hash').delete(synchronize_session=False)
        db.session.commit()
        SystemConfig._invalidate_cache()
        # 课堂会话缓存立即失效，避免残留影响后续运行
        from app.blueprints.auth import invalidate_active_class_cache
        invalidate_active_class_cache()


cleanup()
with app.app_context():
    cls = Class(name=CLASS_NAME)
    teacher = Teacher(username=TEACHER_NAME, display_name='铜卷E2E教师')
    teacher.set_password(PASSWORD)
    teacher.classes.append(cls)
    stu = Student(name='铜卷E2E学生', student_number=STUDENT_NUMBER,
                  student_class=CLASS_NAME, has_changed_password=True)
    stu.set_password(PASSWORD)
    db.session.add_all([cls, teacher, stu])
    db.session.flush()
    stu.class_id = cls.id
    # 学生登录需要上课班级会话（登录时绑定课堂）
    db.session.add(ClassroomSession(class_id=cls.id, is_active=True))
    res = Resource(title=RES_TITLE, url='', show_in_student=True,
                   show_in_classroom=True, creator_type='teacher',
                   creator_teacher_id=teacher.id, creator_name='铜卷E2E教师')
    db.session.add(res)
    db.session.commit()
    IDS.update(cls=cls.id, teacher=teacher.id, stu=stu.id, res=res.id)

    # 模拟现场升级路径：种子资源先于学科配置创建 → 之后配好学科，
    # 启动补齐缺失分类；同时配置只读访问码供只读教师登录。
    from werkzeug.security import generate_password_hash
    from app.models import Subject as _Subject
    for name in ('物理', '化学', '生物', '地理'):
        if not _Subject.query.filter_by(name=name).first():
            db.session.add(_Subject(name=name, sort_order=90))
    SystemConfig.set('teacher_readonly_code_hash',
                     generate_password_hash(READONLY_CODE))
    db.session.commit()
    from app.utils import invalidate_lookup_cache
    invalidate_lookup_cache('subjects')
    from app.blueprints.chem_lab import ensure_chem_lab_resource
    ensure_chem_lab_resource()

threading.Thread(target=lambda: __import__('waitress').serve(
    app, host='127.0.0.1', port=PORT, threads=8), daemon=True).start()
time.sleep(2.0)
os.makedirs('data/e2e_survey', exist_ok=True)
SHOT = 'data/e2e_survey'

from playwright.sync_api import sync_playwright  # noqa: E402


def login_teacher(ctx, readonly=False):
    page = ctx.new_page()
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
    return page


def login_student(ctx):
    page = ctx.new_page()
    page.goto('/')
    page.fill('input[name="student_number"]', STUDENT_NUMBER)
    page.fill('input[name="password"]', PASSWORD)
    page.locator('form').filter(
        has=page.locator('input[name="student_number"]')).locator(
        'button[type="submit"]').click()
    page.wait_for_url('**/study*', timeout=15000)
    return page


try:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        ctx = browser.new_context(base_url=BASE,
                                  viewport={'width': 1500, 'height': 920})
        teacher_page = login_teacher(ctx)

        # ── 2) 问卷全链路 ──
        teacher_page.goto(f'/teacher/resources/{IDS["res"]}/surveys')
        wait_for(lambda: '新增问卷' in teacher_page.content(), 10, '问卷列表页')
        teacher_page.locator('a:has-text("新增问卷")').click()
        teacher_page.wait_for_selector('#surveyForm', timeout=15000)
        teacher_page.fill('input[name="title"]', SURVEY_TITLE)
        teacher_page.fill('textarea[name="description"]', '本课学习体验调查 E2E')
        teacher_page.locator('#sqAnonymous').check()

        def add_question(idx, qtype, title, options='', rows='',
                         required=False):
            teacher_page.locator('#addQuestion').click()
            card = teacher_page.locator('.sq-card').nth(idx)
            card.locator('.sq-type-select').select_option(qtype)
            card.locator('input[name="q_title"]').fill(title)
            if options:
                card.locator('textarea[name="q_options"]').fill(options)
            if rows:
                card.locator('textarea[name="q_rows"]').fill(rows)
            if required:
                card.locator('input[name="q_required"]').check()

        add_question(0, 'radio', '你喜欢本课吗？', '喜欢\n一般\n不喜欢',
                     required=True)
        add_question(1, 'checkbox', '你使用了哪些学习工具？', '电脑\n平板\n手机')
        add_question(2, 'matrix_score', '给以下方面打分（1-5 分）',
                     '1分\n2分\n3分\n4分\n5分', '教师讲解\n实验操作', required=True)
        add_question(3, 'text', '一句话建议', required=False)
        teacher_page.locator('#sqPublish').check()
        teacher_page.locator('#surveyForm button[type="submit"]').click()
        wait_for(lambda: SURVEY_TITLE in teacher_page.content()
                 and '已发布' in teacher_page.content(), 12, '创建并发布问卷')
        check('教师创建并发布问卷', True)
        with app.app_context():
            sid = Survey.query.filter_by(resource_id=IDS['res']).one().id
            qs = sorted(db.session.get(Survey, sid).questions,
                        key=lambda q: q.sort_order)
            QIDS = {q.title: q.id for q in qs}
        teacher_page.screenshot(path=f'{SHOT}/survey_list.png')

        # 学生填写
        stu_ctx = browser.new_context(viewport={'width': 1500, 'height': 920},
                                      base_url=BASE)
        stu_page = login_student(stu_ctx)
        stu_page.goto('/study')
        wait_for(lambda: stu_page.locator('text=未填').count() >= 1, 12,
                 '学生资源卡问卷未填徽章')
        check('学生端问卷入口与未填徽章', True)
        card = stu_page.locator('.resource-card').filter(
            has_text=RES_TITLE).first
        # 卡片可能已自动展开：仅在收起状态时展开（避免点击反把卡片收起）
        stu_page.evaluate("""(title) => {
          document.querySelectorAll('.resource-card').forEach(function (c) {
            if (c.textContent.indexOf(title) === -1) return;
            var hdr = c.querySelector('.res-header');
            var body = document.getElementById(hdr.dataset.target);
            if (body && getComputedStyle(body).display === 'none') hdr.click();
          });
        }""", RES_TITLE)
        card.locator('a:has-text("课堂反馈小调查")').click()
        stu_page.wait_for_selector('text=本课学习体验调查 E2E', timeout=15000)
        stu_page.locator('input[name^="q"][value="喜欢"]').first.check()
        stu_page.locator('input[type="checkbox"][value="电脑"]').check()
        stu_page.locator('input[type="checkbox"][value="平板"]').check()
        mq = QIDS['给以下方面打分（1-5 分）']
        stu_page.locator(f'input[name="q{mq}__m0"][value="5"]').check()
        stu_page.locator(f'input[name="q{mq}__m1"][value="4"]').check()
        stu_page.fill(f'input[name="q{QIDS["一句话建议"]}"]', '多讲点实验')
        stu_page.screenshot(path=f'{SHOT}/student_fill.png')
        stu_page.locator('button:has-text("提交问卷")').click()
        wait_for(lambda: '提交成功' in stu_page.content(), 12, '提交成功提示')
        wait_for(lambda: '我的答卷' in stu_page.content(), 10, '我的答卷回看')
        check('学生填写并提交问卷', True)
        stu_page.goto('/study')
        wait_for(lambda: stu_page.locator('text=已填').count() >= 1, 12,
                 '已填徽章')
        check('学生端已填徽章', True)

        # 教师结果页：图表渲染 + 计数 + CSV
        teacher_page.goto(f'/teacher/surveys/{sid}/results')
        wait_for(lambda: teacher_page.locator('canvas').count() >= 2, 15,
                 '结果页图表渲染')
        check('结果页柱状图渲染（Chart.js）',
              teacher_page.locator('canvas').count() >= 2,
              f'{teacher_page.locator("canvas").count()} 个图表')
        body = teacher_page.content()
        check('结果页答卷计数', '1 份答卷' in body)
        check('结果页含单选题选项', '喜欢' in body)
        check('矩阵评分平均分聚合', '平均' in body)
        teacher_page.screenshot(path=f'{SHOT}/survey_results.png', full_page=True)
        with teacher_page.expect_download() as dl:
            teacher_page.locator('a:has-text("导出 CSV")').click()
        download = dl.value
        csv_path = os.path.join(SHOT, 'survey_results_downloaded.csv')
        download.save_as(csv_path)
        with open(csv_path, encoding='utf-8-sig') as f:
            csv_text = f.read()
        check('CSV 下载含答卷', '喜欢' in csv_text and '多讲点实验' in csv_text,
              csv_text.splitlines()[0][:60] if csv_text else '')

        # 学生再次进入 → 已提交只读
        stu_page.goto(f'/study/survey/{sid}')
        wait_for(lambda: '我的答卷' in stu_page.content(), 10, '学生回看')
        check('学生重复进入显示已提交', '提交这份问卷' in stu_page.content())

        browser.close()
        stu_ctx.close()
finally:
    cleanup()

print(f'—— 结果: {len(FAILED) == 0 and "全部通过" or "失败 " + ", ".join(FAILED)} ——')
sys.exit(0 if not FAILED else 1)
