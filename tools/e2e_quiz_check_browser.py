# -*- coding: utf-8 -*-
"""注入检测与 QuickForm 入口真实浏览器 E2E（2026-10-23）。

隔离库 itstudy_e2e；验证：
  1. 编辑模式教师打开注入检测页；
  2. 演练页试答后检测页显示通过；
  3. 应用后 HTML 写入受管采集块；
  4. 课堂编排器出现「添加 QuickForm 成绩」按钮。
"""
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
os.environ['CACHE_DIR'] = os.path.join(os.getcwd(), 'data', 'cache_e2e_quiz_check')
os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_PORT', '5432')
os.environ.setdefault('DB_USER', 'postgres')
os.environ.setdefault('DB_PASS', '@@')
os.environ['SECRET_KEY'] = 'e2e-quiz-check-key'
sys.path.insert(0, os.getcwd())

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Log, Resource, ResourceQuizResult, Subject, Teacher, teacher_subject  # noqa: E402

PORT = 5034
BASE = f'http://127.0.0.1:{PORT}'
TEACHER = 'qic_e2e_teacher'
SUBJECT = 'QIC注入检测学科'
TITLE = 'QIC注入检测资源'
DIR_NAME = 'qic_e2e_quiz_check'
FAILED = []

HTML = r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>注入检测 E2E</title></head><body>
<div id="quiz-container">
  <h4>问题 <span id="qnum">1</span>/2</h4>
  <button id="option-0" onclick="selectAnswer(0)">A. 选项一</button>
  <button id="option-1" onclick="selectAnswer(1)">B. 选项二</button>
</div>
<div id="test-result" style="display:none">
  <div>测试完成</div><div id="total-questions">2</div>
  <div id="correct-count">1</div><div id="accuracy">50%</div>
</div>
<script>
var current=1;
function selectAnswer(i){
  if(current===1){current=2;document.getElementById('qnum').textContent='2';}
  else {document.getElementById('quiz-container').innerHTML='';
        document.getElementById('test-result').style.display='block';}
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
        ids = [r.id for r in Resource.query.filter_by(title=TITLE).all()]
        if ids:
            ResourceQuizResult.query.filter(
                ResourceQuizResult.resource_id.in_(ids)).delete(
                    synchronize_session=False)
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
(target / 'index.html').write_text(HTML, encoding='utf-8')
with app.app_context():
    subj = Subject(name=SUBJECT, sort_order=911)
    teacher = Teacher(username=TEACHER, display_name='QIC检测教师')
    teacher.set_password('QicPass123')
    teacher.subjects = [subj]
    db.session.add_all([subj, teacher])
    db.session.commit()
    res = Resource(
        title=TITLE, url=f'/static/uploads/{DIR_NAME}/index.html',
        subject_id=subj.id, show_in_student=True, show_in_classroom=True,
        quiz_mode='inject', creator_type='teacher',
        creator_teacher_id=teacher.id, creator_name=teacher.display_name,
        quiz_pending_files=json.dumps(['index.html']),
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
        page.goto('/teacher/login')
        page.uncheck('#readonlyMode')
        page.fill('input[name="username"]', TEACHER)
        page.fill('input[name="password"]', 'QicPass123')
        page.click('button[type="submit"]')
        page.wait_for_url('**/teacher/*', timeout=15000)

        # 编排器 QuickForm 专用按钮
        page.on('dialog', lambda d: d.accept())
        page.goto(f'/teacher/resource-library/edit/{res_id}')
        page.click('#lessonEditorOpen')
        page.wait_for_selector('.le-addrow', timeout=10000)
        show('编排器出现 QuickForm 成绩按钮',
             page.locator('.le-addrow button:has-text("添加 QuickForm 成绩")').count() >= 1)
        page.locator('.le-addrow button:has-text("添加 QuickForm 成绩")').first.click()
        page.fill('[data-qf="url"]', 'https://quickform.example/task/9')
        page.click('[data-qf="confirm"]')
        show('QuickForm 条目已加入编排',
             page.locator('.le-item:has-text("QuickForm 成绩")').count() >= 1)
        page.click('.le-head [data-le="save"]')
        page.wait_for_timeout(1500)
        with app.app_context():
            saved_tree = json.loads(db.session.get(Resource, res_id).lesson_tree or '[]')
            qf_items = [it for sec in saved_tree for it in sec.get('items', [])
                        if it.get('purpose') == 'quickform_results']
            show('QuickForm 条目保存并通过白名单',
                 len(qf_items) == 1 and qf_items[0].get('open_mode') == 'newtab',
                 qf_items)

        # 注入检测
        page.goto(f'/teacher/resources/{res_id}/quiz-check')
        page.wait_for_selector('.start-btn', timeout=10000)
        show('注入检测页显示待检测文件', 'index.html' in page.content())
        with page.expect_popup() as pop_info:
            page.locator('.start-btn').first.click()
        popup = pop_info.value
        popup.on('pageerror', lambda exc: FAILED.append('preview error: ' + str(exc)))
        popup.wait_for_load_state()
        show('演练页带模拟模式标记', '模拟检测模式' in popup.content())

        def answer_twice():
            popup.locator('#option-0').click()
            # 采集器 dry-run 上报有 500ms 节流；留足间隔，避免批次高负载下
            # 第二次（带成绩的）上报被首次仅答案上报吞掉
            popup.wait_for_timeout(700)
            popup.locator('#option-0').click()
            popup.wait_for_timeout(1200)

        answer_twice()
        try:
            page.wait_for_selector('.status-badge:has-text("通过")', timeout=12000)
        except Exception:
            # 偶发浏览器/上报延迟：重载演练页再答一次（检测页仍在轮询）
            popup.reload()
            popup.wait_for_load_state()
            answer_twice()
            page.wait_for_selector('.status-badge:has-text("通过")', timeout=15000)
        show('检测页收到通过状态', True)
        page.click('#applyBtn')
        page.wait_for_timeout(1800)
        injected = (target / 'index.html').read_text(encoding='utf-8')
        show('应用后写入受管采集块',
             'ITSTUDY_QUIZ_COLLECTOR:BEGIN' in injected and
             '__ITSTUDY_QUIZ_SOURCE_FILE__' in injected)
        with app.app_context():
            saved = db.session.get(Resource, res_id)
            show('资源状态更新为已注入',
                 bool(saved and saved.injected and
                      saved.quiz_inject_state == 'verified'),
                 (saved.injected, saved.quiz_inject_state) if saved else 'missing')
        browser.close()
finally:
    cleanup()

print()
print('注入检测浏览器 E2E：%s' % ('全部通过' if not FAILED else f'{len(FAILED)} 项失败：{FAILED}'))
sys.exit(1 if FAILED else 0)
