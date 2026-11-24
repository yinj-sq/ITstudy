# -*- coding: utf-8 -*-
"""仅答案（partial）确认后应用的浏览器回归（2026-10-26）。"""
import io
import json
import os
import pathlib
import shutil
import sys
import threading
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ['DB_NAME'] = 'itstudy_e2e'
os.environ['CACHE_DIR'] = os.path.join(os.getcwd(), 'data', 'cache_e2e_quiz_partial')
os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_PORT', '5432')
os.environ.setdefault('DB_USER', 'postgres')
os.environ.setdefault('DB_PASS', '@@')
os.environ['SECRET_KEY'] = 'e2e-quiz-partial-key'
sys.path.insert(0, os.getcwd())

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Log, Resource, Subject, Teacher, teacher_subject  # noqa: E402

PORT = 5035
BASE = f'http://127.0.0.1:{PORT}'
TEACHER = 'qpart_e2e_teacher'
SUBJECT = 'QPART仅答案学科'
TITLE = 'QPART仅答案资源'
DIR_NAME = 'qpart_e2e_quiz_partial'
FAILED = []

HTML = r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>仅答案测验</title></head><body>
<div><h4>问题 <span id="qnum">1</span>/1</h4>
<button id="option-0" onclick="finish()">A. 选项一</button></div>
<div id="test-result" style="display:none">测试完成，答案已记录</div>
<script>
function finish(){
  var r=document.getElementById('test-result');
  r.innerHTML='测试完成，答案已记录';
  r.style.display='block';
}
</script>
</body></html>'''

app = create_app()
assert app.config['DB_NAME'] == 'itstudy_e2e', app.config['DB_NAME']
from e2e_common import reset_shared_state  # noqa: E402
reset_shared_state(app)
UPLOADS = pathlib.Path(os.getcwd()) / 'static' / 'uploads'


def show(name, ok, detail=''):
    if not ok:
        FAILED.append(name)
    print(('✓' if ok else '✗') + f' {name} {detail}')


def cleanup():
    with app.app_context():
        Log.query.filter(Log.detail.contains(TITLE)).delete(synchronize_session=False)
        Resource.query.filter_by(title=TITLE).delete(synchronize_session=False)
        tid = db.session.query(Teacher.id).filter_by(username=TEACHER).scalar()
        if tid:
            db.session.execute(teacher_subject.delete().where(
                teacher_subject.c.teacher_id == tid))
            Teacher.query.filter_by(id=tid).delete(synchronize_session=False)
        Subject.query.filter_by(name=SUBJECT).delete(synchronize_session=False)
        db.session.commit()
    shutil.rmtree(UPLOADS / DIR_NAME, ignore_errors=True)


cleanup()
target = UPLOADS / DIR_NAME
target.mkdir(parents=True, exist_ok=True)
(target / 'partial.html').write_text(HTML, encoding='utf-8')
with app.app_context():
    subj = Subject(name=SUBJECT, sort_order=912)
    teacher = Teacher(username=TEACHER, display_name='QPART教师')
    teacher.set_password('QpartPass123')
    teacher.subjects = [subj]
    db.session.add_all([subj, teacher])
    db.session.commit()
    res = Resource(
        title=TITLE, url=f'/static/uploads/{DIR_NAME}/partial.html',
        subject_id=subj.id, show_in_student=True, show_in_classroom=True,
        quiz_mode='inject', creator_type='teacher',
        creator_teacher_id=teacher.id, creator_name=teacher.display_name,
        quiz_pending_files=json.dumps(['partial.html']),
        quiz_inject_state='pending')
    db.session.add(res)
    db.session.commit()
    res_id = res.id

from waitress import serve  # noqa: E402
threading.Thread(
    target=lambda: serve(app, host='127.0.0.1', port=PORT, threads=8),
    daemon=True).start()
time.sleep(1.5)

from playwright.sync_api import sync_playwright  # noqa: E402

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        ctx = browser.new_context(base_url=BASE)
        page = ctx.new_page()
        page.on('pageerror', lambda exc: FAILED.append('pageerror: ' + str(exc)))
        page.on('dialog', lambda d: d.accept())
        page.goto('/teacher/login')
        page.uncheck('#readonlyMode')
        page.fill('input[name="username"]', TEACHER)
        page.fill('input[name="password"]', 'QpartPass123')
        page.click('button[type="submit"]')
        page.wait_for_url('**/teacher/*', timeout=15000)
        page.goto(f'/teacher/resources/{res_id}/quiz-check')
        page.wait_for_selector('.start-btn', timeout=10000)
        with page.expect_popup() as pop_info:
            page.locator('.start-btn').first.click()
        popup = pop_info.value
        popup.wait_for_load_state()
        popup.locator('#option-0').click()
        page.wait_for_selector('.status-badge:has-text("仅答案")', timeout=15000)
        show('仅答案状态已显示', True)
        page.click('#applyBtn')
        page.wait_for_timeout(1800)
        injected = (target / 'partial.html').read_text(encoding='utf-8')
        show('确认后仅答案文件已注入',
             'ITSTUDY_QUIZ_COLLECTOR:BEGIN' in injected)
        with app.app_context():
            saved = db.session.get(Resource, res_id)
            show('资源状态更新', bool(saved and saved.injected
                 and saved.quiz_inject_state == 'verified'),
                 (saved.injected, saved.quiz_inject_state) if saved else 'missing')
        browser.close()
finally:
    cleanup()

print()
print('仅答案应用浏览器 E2E：%s' % ('全部通过' if not FAILED else f'{len(FAILED)} 项失败：{FAILED}'))
sys.exit(1 if FAILED else 0)
