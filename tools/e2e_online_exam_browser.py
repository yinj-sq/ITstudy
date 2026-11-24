# -*- coding: utf-8 -*-
"""在线考试浏览器级 E2E（2026-10-27）：倒计时、自动交卷、收卷、批改。

隔离库 itstudy_e2e + Waitress + Playwright(Edge 无头)。
覆盖：倒计时渲染与走秒 / 手动提交确认弹窗 / 临近超时自动交卷 /
管理员收卷后自动交卷 / 教师批改打分 / 成绩未公布隐藏。
"""
import io
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ['DB_NAME'] = 'itstudy_e2e'
os.environ['CACHE_DIR'] = os.path.join(os.getcwd(), 'data', 'cache_e2e_online_exam')
os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_PORT', '5432')
os.environ.setdefault('DB_USER', 'postgres')
os.environ.setdefault('DB_PASS', '@@')
os.environ['SECRET_KEY'] = 'e2e-online-exam-key'
sys.path.insert(0, os.getcwd())

from app import create_app  # noqa: E402
from app.extensions import cache, db  # noqa: E402
from app.models import (Class, ClassroomSession, Exam, ExamAttempt,  # noqa: E402
                        ExamQuestion, Log, Question, Result, Student)  # noqa: E402

PORT = 5050
BASE = f'http://127.0.0.1:{PORT}'
SFX = uuid.uuid4().hex[:8]
EXAM = f'__oe_exam_{SFX}'
CLASS = f'__oe_cls_{SFX}'
FAILED = []

app = create_app()
assert app.config['DB_NAME'] == 'itstudy_e2e', app.config['DB_NAME']
from e2e_common import reset_shared_state  # noqa: E402
reset_shared_state(app)


def show(name, ok, detail=''):
    if not ok:
        FAILED.append(name)
    print(('✓' if ok else '✗') + f' {name} {detail}')


def cleanup():
    with app.app_context():
        eids = [e.id for e in Exam.query.filter(Exam.name.like('__oe_%')).all()]
        if eids:
            ExamAttempt.query.filter(ExamAttempt.exam_id.in_(eids)).delete(
                synchronize_session=False)
            Result.query.filter(Result.exam_id.in_(eids)).delete(
                synchronize_session=False)
            ExamQuestion.query.filter(ExamQuestion.exam_id.in_(eids)).delete(
                synchronize_session=False)
        qids = [q.id for q in Question.query.filter(
            Question.content.like('__oe_%')).all()]
        if qids:
            Question.query.filter(Question.id.in_(qids)).delete(
                synchronize_session=False)
        Exam.query.filter(Exam.name.like('__oe_%')).delete(
            synchronize_session=False)
        for cls in Class.query.filter(Class.name.like('__oe_%')).all():
            ClassroomSession.query.filter_by(class_id=cls.id).delete(
                synchronize_session=False)
            sids = [s.id for s in Student.query.filter_by(class_id=cls.id).all()]
            if sids:
                from sqlalchemy import text as _text
                db.session.execute(_text(
                    'DELETE FROM attendance_record WHERE student_id = ANY(:ids)'),
                    {'ids': sids})
            Student.query.filter_by(class_id=cls.id).delete(
                synchronize_session=False)
            Class.query.filter_by(id=cls.id).delete(synchronize_session=False)
        Log.query.filter(Log.detail.like('%__oe_%')).delete(
            synchronize_session=False)
        db.session.commit()


cleanup()
with app.app_context():
    exam = Exam(name=EXAM, is_active=True, is_visible=True, is_enabled=True,
                is_collected=False, allow_view_results=True, duration=1)
    db.session.add(exam)
    db.session.flush()
    eid = exam.id
    q_single = Question(exam_id=eid, question_type='single',
                        content='__oe_单选+', options='A. 甲|B. 乙',
                        answer='A', score=10)
    q_sa = Question(exam_id=eid, question_type='short_answer',
                    content='__oe_简答+', answer='参考答案', score=10)
    db.session.add_all([q_single, q_sa])
    db.session.flush()
    q1, q2 = q_single.id, q_sa.id
    # 建题带 exam_id 时由事件自动挂卷，无需手动 ExamQuestion
    students = {}
    for i in range(3):
        cls = Class(name=f'{CLASS}_{i}')
        stu = Student(name=f'OE学生{i}', student_number=f'__oe_{i}_{SFX}',
                      student_class=cls.name, has_changed_password=True)
        stu.set_password('OePass123')
        db.session.add_all([cls, stu])
        db.session.flush()
        stu.class_id = cls.id
        db.session.add(ClassroomSession(class_id=cls.id, is_active=True))
        students[i] = (cls.id, stu.id)
    db.session.commit()
    from app.blueprints.auth import invalidate_active_class_cache
    invalidate_active_class_cache()

from waitress import serve  # noqa: E402
threading.Thread(target=lambda: serve(app, host='127.0.0.1', port=PORT, threads=8),
                 daemon=True).start()
time.sleep(1.5)

from playwright.sync_api import sync_playwright  # noqa: E402


def login_student(browser, number):
    ctx = browser.new_context(base_url=BASE)
    page = ctx.new_page()
    page.on('pageerror', lambda e: FAILED.append('pageerror: ' + str(e)))
    page.goto('/')
    page.fill('input[name="student_number"]', number)
    page.fill('input[name="password"]', 'OePass123')
    page.locator('form').filter(has=page.locator('input[name="student_number"]')) \
        .locator('button[type="submit"]').click()
    page.wait_for_url('**/study*', timeout=15000)
    return ctx, page


def admin_client():
    c = app.test_client()
    with c.session_transaction() as s:
        s.update(is_admin=True, admin_name='OE管理员', csrf_token='oe-csrf')
    return c


try:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)

        # ── 场景 1+2：倒计时 + 手动提交确认弹窗 ──
        ctx, page = login_student(browser, f'__oe_0_{SFX}')
        page.goto(f'/online_exam/{eid}')
        page.wait_for_selector('#exam-timer', timeout=10000)
        t1 = page.locator('#exam-timer').inner_text()
        show('倒计时渲染', t1.startswith('剩余时间'), t1)
        page.wait_for_timeout(2200)
        t2 = page.locator('#exam-timer').inner_text()
        show('倒计时在走秒', t1 != t2, (t1, t2))
        page.locator(f'input[name="{q1}"]').first.check()
        page.locator(f'textarea[name="{q2}"]').fill('我的简答内容')
        page.locator('#submit-exam').click()
        page.wait_for_selector('#confirmSubmit', timeout=5000)
        show('提交确认弹窗出现', True)
        page.locator('#confirmSubmit').click()
        page.wait_for_url('**/result/*', timeout=10000)
        show('手动提交后跳转结果页', True, page.url)
        with app.app_context():
            result = Result.query.filter_by(exam_id=eid).order_by(
                Result.id.desc()).first()
            show('手动提交落库（含简答待批改）',
                 result is not None and result.grading_status == 'pending_review'
                 and result.total_score == 10,
                 (result.grading_status, result.total_score) if result else None)
        ctx.close()

        # ── 场景 3：临近超时自动交卷 ──
        ctx2, page2 = login_student(browser, f'__oe_1_{SFX}')
        page2.goto(f'/online_exam/{eid}')
        page2.wait_for_selector('#exam-timer', timeout=10000)
        with app.app_context():
            att = ExamAttempt.query.filter_by(
                exam_id=eid).order_by(ExamAttempt.id.desc()).first()
            att.start_time = datetime.now() - timedelta(seconds=58)
            db.session.commit()
        page2.reload()
        page2.wait_for_selector('#exam-timer', timeout=10000)
        t3 = page2.locator('#exam-timer').inner_text()
        show('临近超时显示剩余秒数', '剩余时间: 0:00:0' in t3, t3)
        page2.locator(f'input[name="{q1}"]').first.check()
        page2.wait_for_selector('#examEndOverlay', state='visible', timeout=15000)
        timer_text = page2.locator('#exam-timer').inner_text()
        show('到点自动交卷（时间到！）', timer_text.strip() == '时间到！', timer_text)
        with app.app_context():
            cnt = Result.query.filter_by(exam_id=eid).count()
            show('自动交卷落库', cnt == 2, cnt)
        ctx2.close()

        # ── 场景 4：管理员收卷 → 学生端自动交卷 ──
        ctx3, page3 = login_student(browser, f'__oe_2_{SFX}')
        page3.goto(f'/online_exam/{eid}')
        page3.wait_for_selector('#exam-timer', timeout=10000)
        page3.locator(f'input[name="{q1}"]').first.check()
        with app.app_context():
            exam = db.session.get(Exam, eid)
            exam.is_collected = True
            db.session.commit()
            cache.delete(f'exam:collected:{eid}')
        page3.wait_for_selector('#examEndOverlay', state='visible', timeout=15000)
        show('收卷后 5 秒轮询自动交卷', True)
        with app.app_context():
            cnt = Result.query.filter_by(exam_id=eid).count()
            show('收卷自动交卷落库', cnt == 3, cnt)
        ctx3.close()

        # ── 场景 5：教师批改（浏览器）──
        ac = admin_client()
        with app.app_context():
            res = Result.query.filter_by(exam_id=eid).order_by(
                Result.id).all()[0]
            rid = res.id
        actx = browser.new_context(base_url=BASE)
        apage = actx.new_page()
        apage.on('pageerror', lambda e: FAILED.append('admin pageerror: ' + str(e)))
        apage.goto('/admin/login')
        # 用测试客户端登录无法共享 Playwright cookie——直接调测试客户端批改
        # 页面渲染验证：用 admin 测试客户端 GET 页面确认控件存在
        detail = ac.get(f'/admin/grading/{eid}/{rid}')
        show('批改详情页可渲染', detail.status_code == 200, detail.status_code)
        html = detail.get_data(as_text=True)
        show('批改页含打分输入框', f'score_{q2}' in html, q2)
        r = ac.post(f'/admin/grading/{eid}/{rid}', data={
            'csrf_token': 'oe-csrf', f'score_{q2}': '7'})
        show('浏览器同款表单打分提交', r.status_code in (302, 303), r.status_code)
        with app.app_context():
            res = db.session.get(Result, rid)
            show('批改完成状态与总分', res.grading_status == 'fully_graded'
                 and res.total_score == 17, (res.grading_status, res.total_score))
        actx.close()

        # ── 场景 6：成绩未公布隐藏 ──
        with app.app_context():
            exam = db.session.get(Exam, eid)
            exam.allow_view_results = False
            db.session.commit()
        ctx4, page4 = login_student(browser, f'__oe_0_{SFX}')
        page4.goto(f'/result/{rid}')
        # 未公布时服务端 302 到 /exam 并把提示放在 flash 里；等重定向落定，
        # 避免批次运行时偶发读到跳转前的页面（失败详情保留 URL 供定位）
        try:
            page4.wait_for_url('**/exam*', timeout=5000)
        except Exception:
            pass
        text4 = page4.content()
        show('未公布成绩页不显示得分', '成绩尚未公布' in text4,
             (page4.url, '成绩尚未公布' in text4))
        with app.app_context():
            exam = db.session.get(Exam, eid)
            exam.allow_view_results = True
            db.session.commit()
        page4.goto(f'/result/{rid}')
        show('公布后成绩可见', '17' in page4.content(), True)
        ctx4.close()

        browser.close()
finally:
    cleanup()

print()
print('在线考试浏览器 E2E：%s' % ('全部通过' if not FAILED else f'{len(FAILED)} 项失败：{FAILED}'))
sys.exit(1 if FAILED else 0)
