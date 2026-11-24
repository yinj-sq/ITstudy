# -*- coding: utf-8 -*-
"""组卷功能 真实浏览器端到端测试（Playwright + Edge 无头）

链路：管理员登录 → 试卷管理 → 组卷页 → 题库勾选（乱序题型）加入 →
断言总分汇总/题数/分组顺序（single 组在 judge 前）→ 再加一题 →
上移/移除 → 总分与结构更新 → 学生登录考试页 → 断言题型分组标题条、
连续题号与题目顺序一致。

运行：venv/Scripts/python.exe -X utf8 tools/e2e_exam_compose.py
环境：隔离库 itstudy_e2e、端口 5014、缓存独立；测后清理。
"""
import io
import os
import sys
import time
import threading

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ['DB_NAME'] = 'itstudy_e2e'
os.environ['CACHE_DIR'] = os.path.join(os.getcwd(), 'data', 'cache_e2e_compose')
os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_PORT', '5432')
os.environ.setdefault('DB_USER', 'postgres')
os.environ.setdefault('DB_PASS', '@@')
os.environ['SECRET_KEY'] = 'e2e-compose-key'
sys.path.insert(0, os.getcwd())

from app import create_app
from app.extensions import db

app = create_app()
from e2e_common import reset_shared_state  # noqa: E402
reset_shared_state(app)

# ── 幂等清理：启动时清上次中断的残留，退出时（atexit，异常退出也执行）清本次夹具 ──
from sqlalchemy import text as _text


def _purge():
    with app.app_context():
        db.session.rollback()
        conn = db.session.connection()
        for stmt in (
            "DELETE FROM exam_attempt WHERE exam_id IN"
            " (SELECT id FROM exam WHERE name LIKE '组卷E2E%')",
            "DELETE FROM result WHERE exam_id IN"
            " (SELECT id FROM exam WHERE name LIKE '组卷E2E%')",
            "DELETE FROM exam_question WHERE exam_id IN"
            " (SELECT id FROM exam WHERE name LIKE '组卷E2E%')",
            "DELETE FROM question WHERE content LIKE '组卷E2E题%'",
            "DELETE FROM exam WHERE name LIKE '组卷E2E%'",
            "DELETE FROM attendance_record WHERE student_id IN"
            " (SELECT id FROM student WHERE student_number LIKE 'CP%')",
            "DELETE FROM student WHERE student_number LIKE 'CP%'",
            "DELETE FROM classroom_setting",
            "DELETE FROM classroom_session WHERE class_id IN"
            " (SELECT id FROM classes WHERE name='组卷E2E班')",
            "DELETE FROM study_group WHERE name LIKE 'CP%'",
            "DELETE FROM classes WHERE name='组卷E2E班'",
            "DELETE FROM admin_account WHERE username='compose_admin'",
        ):
            conn.execute(_text(stmt))
        db.session.commit()
        from app.blueprints.auth import invalidate_active_class_cache
        invalidate_active_class_cache()


_purge()
import atexit  # noqa: E402
atexit.register(_purge)

from app.models import (Class, Student, Exam, Question, ClassroomSetting, AdminAccount)

UP = 'static/uploads'
STU_NUM = f'CP{os.getpid()}'


def _mk_q(content, qtype, score):
    return Question(exam_id=None, question_type=qtype, content=content,
                    options='A.甲|B.乙' if qtype in ('single', 'multiple') else None,
                    answer='A' if qtype in ('single', 'multiple') else '对',
                    score=score)


with app.app_context():
    cls = Class(name='组卷E2E班')
    db.session.add(cls)
    db.session.flush()
    stu = Student(name='组卷甲', student_number=STU_NUM, class_id=cls.id,
                  student_class='组卷E2E班', is_activated=True,
                  has_changed_password=True)
    stu.set_password('CpPass123')
    db.session.add(stu)
    db.session.flush()
    db.session.add(ClassroomSetting(active_class_id=cls.id))
    admin = AdminAccount(username='compose_admin', display_name='组卷管理员')
    admin.set_password('CpAdmin123')
    db.session.add(admin)
    db.session.flush()

    exam = Exam(name=f'组卷E2E·卷{os.getpid() % 9000}', is_active=True,
                is_visible=True, is_enabled=True, duration=30)
    db.session.add(exam)
    db.session.flush()

    # 题库 5 题（不同题型/分值；故意乱序创建）
    qs = [
        _mk_q('组卷E2E题·判断1', 'judge', 3.0),
        _mk_q('组卷E2E题·单选A', 'single', 2.0),
        _mk_q('组卷E2E题·单选B', 'single', 2.5),
        _mk_q('组卷E2E题·填空1', 'fill', 4.0),
        _mk_q('组卷E2E题·单选C', 'single', 1.5),
    ]
    for q in qs:
        db.session.add(q)
    db.session.commit()
    EID = exam.id
    SID = stu.id
    QIDS = [q.id for q in qs]          # [judge, sA, sB, fill, sC]
    print(f'—— 数据就绪 eid={EID} sid={SID} qids={QIDS} ——')

PORT = 5014
BASE = f'http://127.0.0.1:{PORT}'
t = threading.Thread(target=lambda: __import__('waitress').serve(
    app, host='127.0.0.1', port=PORT, threads=16), daemon=True)
t.start()
time.sleep(2.5)

from playwright.sync_api import sync_playwright

results = []
console_errors = []


def check(name, cond, extra=''):
    results.append(bool(cond))
    print(f'[{"PASS" if cond else "FAIL"}] {name}' + (f' | {extra}' if extra else ''))


def wait_for(fn, timeout, label):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(0.4)
    print(f'  [超时] {label}')
    return False


def paper_state(page):
    """读取已选列表结构：[(qid, type, seq)] 与总分/题数"""
    return page.evaluate("""()=>{
        const items=[...document.querySelectorAll('#paperBody [data-qid]')]
          .map(el=>({qid:+el.dataset.qid, type:el.dataset.qtype,
                     seq:+(el.dataset.seq||0)}));
        return {items,
                total: document.getElementById('totalScore').textContent.trim(),
                count: document.getElementById('qCount').textContent.trim()};
    }""")


with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    ctx = browser.new_context(viewport={'width': 1600, 'height': 900},
                              base_url=BASE)
    page = ctx.new_page()
    page.on('pageerror', lambda e: console_errors.append(str(e)))

    def _on_dialog(d):
        print(f'  [dialog:{d.type}] {d.message[:120]}')
        d.accept()
    page.on('dialog', _on_dialog)

    # ── 管理员登录（真实表单）──
    page.goto('/admin/login')
    page.fill('input[name="username"]', 'compose_admin')
    page.fill('input[name="password"]', 'CpAdmin123')
    page.click('button[type="submit"]')
    wait_for(lambda: '/admin' in page.url and 'login' not in page.url, 15,
             '管理员登录')
    check('C0 管理员登录', 'login' not in page.url, page.url[-40:])

    # ── C1 试卷列表 → 组卷入口 ──
    page.goto('/admin/exams')
    btn = page.locator(f'a[href="/admin/exams/{EID}/compose"]')
    check('C1 试卷列表组卷按钮', btn.count() == 1)
    btn.first.click()
    wait_for(lambda: page.locator('#bankBody .bk-sel').count() >= 5, 20,
             '题库列表渲染')
    check('C2 组卷页题库列表 5 题', page.locator('#bankBody .bk-sel').count() == 5)

    # ── C3 乱序勾选：判断1 + 单选A + 单选B → 加入 ──
    for qid in (QIDS[0], QIDS[1], QIDS[2]):   # judge 先勾
        page.check(f'.bk-sel[value="{qid}"]')
    page.click('#btnAdd')
    wait_for(lambda: paper_state(page)['count'].startswith('3'), 15, '加入3题')
    st = paper_state(page)
    check('C3 加入3题且总分汇总 7.5',
          st['count'].startswith('3') and '7.5' in st['total'], st['total'])
    types = [i['type'] for i in st['items']]
    check('C4 分组顺序 single 组在 judge 前',
          types == ['single', 'single', 'judge'], str(types))
    seqs = [i['seq'] for i in st['items']]
    check('C5 全局题号连续 1..3', seqs == [1, 2, 3], str(seqs))
    page.screenshot(path='data/e2e_artifacts/c3_compose_added.png')

    # ── C6 再加填空题 → 总分 10.5 ──
    page.check(f'.bk-sel[value="{QIDS[3]}"]')
    page.click('#btnAdd')
    wait_for(lambda: paper_state(page)['count'].startswith('4'), 15, '加入第4题')
    st = paper_state(page)
    check('C6 加入填空后总分 11.5', '11.5' in st['total'], st['total'])

    # ── C7 组内上移：单选B 上移到单选组首位（跨组按钮已禁用）──
    before = [i['qid'] for i in st['items']]
    page.locator(f'#paperBody [data-qid="{QIDS[2]}"] button[data-action="up"]').click()
    wait_for(lambda: [i['qid'] for i in paper_state(page)['items']] !=
             before, 15, '组内上移生效')
    st = paper_state(page)
    after = [i['qid'] for i in st['items']]
    check('C7 组内上移生效', after[:3] == [QIDS[2], QIDS[1], QIDS[0]],
          str(after))
    # 跨组按钮禁用：填空题组内唯一，up/down 均 disabled
    sel = f'#paperBody [data-qid="{QIDS[3]}"] button[data-action="up"]'
    dis = page.evaluate(
        "sel => { const b = document.querySelector(sel);"
        " return b ? b.disabled : null; }", sel)
    check('C7b 跨组按钮禁用（填空组内唯一）', dis is True, str(dis))
    seqs = [i['seq'] for i in st['items']]
    check('C7b 移动后题号仍连续', seqs == [1, 2, 3, 4], str(seqs))

    # ── C8 移除单选B → 3 题、总分 8 ──
    page.locator(f'#paperBody [data-qid="{QIDS[2]}"] button[data-action="remove"]').click()
    wait_for(lambda: paper_state(page)['count'].startswith('3'), 15, '移除生效')
    st = paper_state(page)
    check('C8 移除后 3 题/总分 9.0', st['count'].startswith('3') and
          '9' in st['total'], f"{st['count']}/{st['total']}")
    page.screenshot(path='data/e2e_artifacts/c8_compose_final.png')

    # ── C9 学生考试页：分组标题条 + 连续题号 + 顺序一致 ──
    page2 = ctx.new_page()
    page2.goto('/')
    page2.fill('input[name="student_number"]', STU_NUM)
    page2.fill('input[name="password"]', 'CpPass123')
    page2.click('form:has(input[name="student_number"]) button[type="submit"]')
    wait_for(lambda: '/study' in page2.url, 15, '学生登录')
    page2.goto(f'/online_exam/{EID}')
    wait_for(lambda: page2.locator('.question').count() == 3, 20, '考试页渲染')
    headers = page2.locator('.question-type-header').all_inner_texts()
    uniq_types = list(dict.fromkeys(i['type'] for i in st['items']))
    check('C9 分组标题条与组卷分组一致', len(headers) == len(uniq_types) and
          '单选' in headers[0], f"{len(headers)}条 {headers}")
    qids = page2.evaluate(
        "[...document.querySelectorAll('.question')]"
        ".map(el=>+el.dataset.questionId)")
    check('C10 考试页题目顺序与组卷一致', qids == [i['qid'] for i in st['items']],
          str(qids))
    first_no = page2.locator('.question .fw-bold').first.inner_text().strip()
    check('C11 首题题号 1.', first_no.startswith('1'), first_no[:8])
    page2.screenshot(path='data/e2e_artifacts/c9_exam_grouped.png',
                     full_page=True)

    browser.close()

print('\n—— 控制台错误 ——')
for e in console_errors[:5]:
    print(' ', e[:150])

# 清理由 atexit 注册的 _purge() 完成（正常结束与异常退出都会执行）

failed = sum(1 for r in results if not r)
print(f'\n===== 组卷浏览器 E2E：{len(results)-failed}/{len(results)} 通过 =====')
sys.exit(1 if failed else 0)