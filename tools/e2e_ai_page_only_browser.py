# -*- coding: utf-8 -*-
"""学生 AI「仅限当前页面内容」真实浏览器验证（Playwright + Edge 无头）

T1 教师在 AI 助手面板看到「学生限本页」按钮，点击后开关变为「开」
T2 学生端：「基于页面内容」按钮被锁定为「仅限本页内容」，欢迎语提示老师已限定
T3 学生提问：请求带上课件框架（#docFrame）里的正文，模型收到的系统提示含
   「老师已限定」与该正文（上游 AI 在同进程内替换，不发真实请求）
T4 教师关闭开关后，学生刷新页面即恢复可切换
T5 管理员 AI 配置页的同名开关即时生效
全程页面 JS 错误须为 0。

运行：venv/Scripts/python.exe -X utf8 tools/e2e_ai_page_only_browser.py
环境：隔离库 itstudy_e2e、端口 5018、缓存独立；测后还原配置并清理。失败退出码 1。
"""
import io
import json
import os
import sys
import threading
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ['DB_NAME'] = 'itstudy_e2e'
os.environ['CACHE_DIR'] = os.path.join(os.getcwd(), 'data', 'cache_e2e_0928')
os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_PORT', '5432')
os.environ.setdefault('DB_USER', 'postgres')
os.environ.setdefault('DB_PASS', '@@')
os.environ['SECRET_KEY'] = 'e2e-0928-key'
sys.path.insert(0, os.getcwd())

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from sqlalchemy import text as _text  # noqa: E402

app = create_app()
assert app.config['DB_NAME'] == 'itstudy_e2e', app.config['DB_NAME']
from e2e_common import reset_shared_state, uncheck_readonly_mode  # noqa: E402
reset_shared_state(app)

from app.blueprints import ai as ai_mod  # noqa: E402
from app.models import (AdminAccount, AIConfig, AIImageConfig, Class,  # noqa: E402
                        ClassroomSetting, Student, SystemConfig, Teacher)

KEY = ai_mod.STUDENT_PAGE_ONLY_KEY
CLS, STU, TEA, ADM = 'E0928班', 'E0928S1', 'e0928_teacher', 'e0928_admin'
PWD = 'E0928pass!'
LESSON_TEXT = 'E0928 课件正文：for 循环用于遍历序列'
AI_IMAGE_ROOT = os.path.join('data', 'ai_images')


def _cleanup():
    """清理本脚本的账号与生成图片。

    生图文件按「生成者」分目录存放（data/ai_images/student_<id>/）。此前收尾
    直接 rmtree 整个 data/ai_images——从源码目录运行应用时，那里也是真实
    生成图片的存放处，跑一次本脚本就把全部图片删光。现只删本脚本学生的目录。
    """
    import shutil
    with app.app_context():
        student_ids = [row[0] for row in db.session.execute(
            _text('SELECT id FROM student WHERE student_number=:s'),
            {'s': STU}).all()]
        for sql in (
            "DELETE FROM ai_chat_message WHERE student_id IN (SELECT id FROM student WHERE student_number=:s)",
            "DELETE FROM ai_image WHERE actor IN (SELECT 'student:'||id FROM student WHERE student_number=:s)",
            "DELETE FROM attendance_record WHERE student_id IN (SELECT id FROM student WHERE student_number=:s)",
            "DELETE FROM student WHERE student_number=:s",
            "DELETE FROM teacher WHERE username=:t",
            "DELETE FROM admin_account WHERE username=:a",
            "DELETE FROM log WHERE action='AI 页面限定'",
        ):
            db.session.execute(_text(sql), {'s': STU, 't': TEA, 'a': ADM})
        db.session.commit()
    for sid in student_ids:
        shutil.rmtree(os.path.join(AI_IMAGE_ROOT, f'student_{sid}'),
                      ignore_errors=True)
    try:
        os.rmdir(AI_IMAGE_ROOT)   # 仅当目录已空时移除；有其它图片则原样保留
    except OSError:
        pass


_cleanup()
with app.app_context():
    cfg = AIConfig.query.first()
    cfg_created = cfg is None
    if cfg_created:
        cfg = AIConfig()
        db.session.add(cfg)
    saved_cfg = (cfg.enabled, cfg.config_mode, cfg.api_url, cfg.model, cfg._api_key,
                 cfg.page_context_default, cfg.vision_enabled)
    cfg.enabled, cfg.config_mode, cfg.page_context_default = True, 'admin', True
    cfg.api_url, cfg.model, cfg.api_key = 'https://api.example.com/v1', 'e0928-model', 'sk-e0928'
    cfg.vision_enabled = True
    cls = Class.query.filter_by(name=CLS).first() or Class(name=CLS)
    db.session.add(cls)
    db.session.flush()
    stu = Student(name='E0928学生', student_number=STU, class_id=cls.id, student_class=CLS,
                  is_activated=True, has_changed_password=True)
    stu.set_password(PWD)
    t = Teacher(username=TEA, display_name='E0928教师')
    t.set_password(PWD)
    a = AdminAccount(username=ADM, display_name='E0928')
    a.set_password(PWD)
    db.session.add_all([stu, t, a])
    setting = ClassroomSetting.query.first()
    setting_created = setting is None
    if setting_created:
        setting = ClassroomSetting()
        db.session.add(setting)
    saved_active = setting.active_class_id
    setting.active_class_id = cls.id
    saved_flag = SystemConfig.get(KEY, '0')
    SystemConfig.set(KEY, '0')
    image_cfg = AIImageConfig.query.first()
    image_created = image_cfg is None
    if image_created:
        image_cfg = AIImageConfig()
        db.session.add(image_cfg)
    saved_image_cfg = (image_cfg.enabled, image_cfg.provider, image_cfg.api_url,
                       image_cfg.model, image_cfg.size, image_cfg.max_images,
                       image_cfg.timeout_seconds, image_cfg.allow_student,
                       image_cfg.allow_teacher, image_cfg._api_key)
    image_cfg.enabled = True
    image_cfg.provider = 'openai_images'
    image_cfg.api_url = 'https://image.example.com/v1'
    image_cfg.model = 'e0928-image'
    image_cfg.size = '1024x1024'
    image_cfg.max_images = 1
    image_cfg.timeout_seconds = 30
    image_cfg.allow_student = True
    image_cfg.allow_teacher = True
    image_cfg.api_key = 'sk-e0928-image'
    db.session.commit()
    SystemConfig._invalidate_cache()
    CLS_ID = cls.id

# ── 上游 AI 替身：同进程 Waitress 线程直接调用模块全局 _call_chat ──
captured = []


class _FakeStream:
    def iter_lines(self, decode_unicode=True):
        yield 'data: ' + json.dumps({'choices': [{'delta': {'content': 'E0928答复'}}]})
        yield 'data: [DONE]'

    def close(self):
        pass


def fake_call(provider, api_key, api_url, model, messages, *a, **k):
    captured.append(messages)
    if k.get('stream') or (len(a) >= 3 and a[2]):
        return True, _FakeStream(), 200, None
    return True, 'E0928答复', 200, 'stop'


ai_mod._call_chat = fake_call
# 生图替身：返回一张有效的最小 PNG，验证前端「生图」模式与图片鉴权展示
PNG = __import__('base64').b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk'
    '+A8AAQUBAScY42YAAAAASUVORK5CYII=')
ai_mod._image_api_generate = lambda prompt, cfg: (True, [(PNG, 'image/png')])

PORT = 5018
BASE = f'http://127.0.0.1:{PORT}'
threading.Thread(target=lambda: __import__('waitress').serve(
    app, host='127.0.0.1', port=PORT, threads=8), daemon=True).start()
time.sleep(2.5)

from playwright.sync_api import sync_playwright  # noqa: E402

results, page_errors = [], []


def check(name, cond, extra=''):
    results.append(bool(cond))
    print(f'[{"PASS" if cond else "FAIL"}] {name}' + (f' | {extra}' if extra else ''))


def new_page(browser):
    ctx = browser.new_context(
        base_url=BASE, viewport={'width': 1400, 'height': 900},
        permissions=['clipboard-read', 'clipboard-write'])
    page = ctx.new_page()
    page.on('pageerror', lambda e: page_errors.append((page.url, str(e))))
    page.on('dialog', lambda d: d.dismiss())
    return page


def wait_js(page, expr, timeout=10.0):
    """轮询页面表达式（站点 CSP 禁 unsafe-eval，Playwright 的 wait_for_function
    会在页面内 eval 谓词而被拦截；page.evaluate 走 CDP 不受影响）。"""
    end = time.time() + timeout
    while time.time() < end:
        try:
            if page.evaluate('() => !!(' + expr + ')'):
                return True
        except Exception:
            pass
        time.sleep(0.2)
    raise TimeoutError(expr)


def open_panel(page):
    page.wait_for_selector('#aiFab', timeout=15000)
    page.click('#aiFab')
    page.wait_for_selector('#aiChatPanel.show', timeout=5000)
    # 面板自右侧滑入（#aiChatPanel transform translateX(100%)→0，0.3s 过渡）。
    # 仅等 .show 类出现在时序上不够：过渡未结束时面板仍在视口右缘之外，
    # 内部按钮的命中点落在视口外，Playwright click 抛
    # "Element is outside of the viewport"（时序型 flake，非产品缺陷）。
    # 等过渡结束（transform 为恒等矩阵）再操作面板内元素。
    wait_js(page, "getComputedStyle(document.getElementById('aiChatPanel')).transform"
                  "==='matrix(1, 0, 0, 1, 0, 0)'", 5.0)


try:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)

        # ── T1 教师开启 ──
        tp = new_page(browser)
        tp.goto('/teacher/login')
        uncheck_readonly_mode(tp)
        tp.fill('input[name="username"]', TEA)
        tp.fill('input[name="password"]', PWD)
        tp.click('button[type="submit"]')
        tp.wait_for_load_state('networkidle')
        tp.goto('/study?mode=classroom')
        tp.wait_for_load_state('networkidle')
        open_panel(tp)
        btn = tp.locator('#aiPageOnlyBtn')
        check('T1 教师面板显示「学生限本页」按钮', btn.is_visible(), btn.inner_text())
        btn.click()
        wait_js(tp, "document.querySelector('#aiPageOnlyBtn .ai-page-only-label').textContent.includes('开')", 5.0)
        with app.app_context():
            SystemConfig._invalidate_cache()
            on = SystemConfig.get_bool(KEY, False)
        check('T1b 点击后开关写入为开启', on, tp.locator('#aiPageOnlyBtn').inner_text())
        check('T1c 教师自身的上下文按钮不被锁定',
              tp.locator('#aiContextToggle').is_enabled())

        # ── T2/T3 学生端 ──
        sp = new_page(browser)
        sp.goto('/')
        sp.fill('input[name="student_number"]', STU)
        sp.locator('input[name="password"]').first.fill(PWD)
        sp.locator('button[type="submit"]').first.click()
        sp.wait_for_load_state('networkidle')
        sp.goto('/study')
        sp.wait_for_load_state('networkidle')
        open_panel(sp)
        ctx_btn = sp.locator('#aiContextToggle')
        check('T2 学生「基于页面内容」按钮被锁定', ctx_btn.is_disabled(), ctx_btn.inner_text())
        check('T2b 按钮文案为「仅限本页内容」', '仅限本页内容' in ctx_btn.inner_text())
        welcome = sp.locator('.ai-welcome-sub').inner_text()
        check('T2c 欢迎语提示老师已限定', '老师已限定' in welcome, welcome)
        ctx_btn.click(force=True)
        check('T2d 强行点击也无法切到自由对话', '仅限本页内容' in ctx_btn.inner_text())

        # 模拟课堂页的课件框架（同源 srcdoc），检查请求带上的是课件正文
        sp.evaluate("""(t) => { const f = document.createElement('iframe');
            f.id = 'docFrame'; f.srcdoc = '<p>' + t + '</p>';
            f.style.width = '300px'; f.style.height = '80px';
            document.body.appendChild(f); }""", LESSON_TEXT)
        # 同源页面图片：应被自动压缩后随消息发送给视觉模型
        sp.evaluate("""() => { const img = document.createElement('img');
            img.id = 'e2ePageImage'; img.src = '/static/pptist/logo.png';
            img.style.width = '160px'; img.style.height = '160px';
            document.body.appendChild(img); }""")
        sp.wait_for_timeout(800)
        sent = {}
        sp.on('request', lambda r: sent.setdefault('body', r.post_data)
              if r.url.endswith('/api/ai/chat/stream') else None)
        sp.fill('#aiInput', 'E0928 这一页讲什么')
        sp.click('#aiSendBtn')
        wait_js(sp, "document.getElementById('aiMessages').innerText.includes('E0928答复')", 15.0)
        body = json.loads(sent.get('body') or '{}')
        check('T3 请求带上课件框架里的正文', LESSON_TEXT in body.get('page_content', ''),
              body.get('page_content', '')[:40])
        system = captured[-1][0]['content'] if captured else ''
        check('T3b 模型收到「老师已限定」系统提示且含课件正文',
              '老师已限定' in system and LESSON_TEXT in system)

        # 复制/重新生成按钮：不得重叠；复制内容必须是回复正文而非空值/旧剪贴板
        last_assistant = sp.locator('.ai-msg-assistant').last
        last_assistant.hover()
        copy_btn = last_assistant.locator('[data-action="copy"]')
        regen_btn = last_assistant.locator('[data-action="regenerate"]')
        cb, rb = copy_btn.bounding_box(), regen_btn.bounding_box()
        separated = bool(cb and rb) and (cb['x'] + cb['width'] <= rb['x'] + 0.5)
        check('T3c 复制/重新生成按钮不重叠', separated,
              f"copy={cb and (round(cb['x']), round(cb['width']))} "
              f"regen={rb and (round(rb['x']), round(rb['width']))}")
        copy_btn.click()
        sp.wait_for_timeout(500)
        clip = sp.evaluate('() => navigator.clipboard.readText()')
        check('T3d 复制的是 AI 回复正文', 'E0928答复' in (clip or '') and 'sk-' not in (clip or ''),
              (clip or '')[:60])
        request_body = json.loads(sent.get('body') or '{}')
        check('T3e 页面图片自动随请求发送', bool(request_body.get('images')),
              f"images={len(request_body.get('images') or [])}")
        last_messages = captured[-1] if captured else []
        user_contents = [m.get('content') for m in last_messages if m.get('role') == 'user']
        has_image_block = bool(user_contents) and isinstance(user_contents[-1], list) and any(
            isinstance(b, dict) and b.get('type') == 'image_url' for b in user_contents[-1])
        check('T3f 图片以多模态内容送入模型', has_image_block)

        # ── T3g-T3p 教学技能选择（默认费曼 / 全不选 / 多选）──
        skill_btn = sp.locator('#aiSkillBtn')
        check('T3g 默认启用费曼式简化解释',
              '费曼简化' in skill_btn.inner_text(), skill_btn.inner_text())
        skill_btn.click()
        wait_js(sp, "document.getElementById('aiSkillMenu').classList.contains('show')", 5.0)
        check('T3h 技能下拉列出三项',
              sp.locator('#aiSkillMenu input[data-skill]').count() == 3)
        check('T3i 默认勾选费曼',
              sp.locator('#aiSkillMenu input[data-skill="feynman"]').is_checked())
        sp.locator('#aiSkillClear').click()
        check('T3j 可取消全部技能', '不使用' in skill_btn.inner_text(), skill_btn.inner_text())

        skill_bodies = []
        sp.on('request', lambda r: skill_bodies.append(json.loads(r.post_data or '{}'))
              if r.url.endswith('/api/ai/chat/stream') else None)
        sp.fill('#aiInput', '不使用技能再解释一次')
        sp.click('#aiSendBtn')
        wait_js(sp, "Array.from(document.querySelectorAll('.ai-msg-assistant'))"
                    ".slice(-1)[0].innerText.includes('E0928答复')", 15.0)
        check('T3k 全不选时请求 skills 为空',
              skill_bodies[-1].get('skills') == [], skill_bodies[-1].get('skills'))
        check('T3l 全不选时系统提示无教学技能块',
              '本轮启用了以下教学技能' not in captured[-1][0]['content'])

        skill_btn.click()
        sp.locator('#aiSkillMenu input[data-skill="socratic"]').check()
        sp.locator('#aiSkillMenu input[data-skill="antivibe"]').check()
        sp.locator('#aiSkillDone').click()
        check('T3m 多选后按钮显示 2 项', '2 项' in skill_btn.inner_text(),
              skill_btn.inner_text())
        sp.fill('#aiInput', '这段代码为什么这样写')
        sp.click('#aiSendBtn')
        wait_js(sp, "Array.from(document.querySelectorAll('.ai-msg-assistant'))"
                    ".slice(-1)[0].innerText.includes('E0928答复')", 15.0)
        check('T3n 多选请求按固定顺序提交',
              skill_bodies[-1].get('skills') == ['socratic', 'antivibe'],
              skill_bodies[-1].get('skills'))
        skill_system = captured[-1][0]['content']
        check('T3o 多选技能注入系统提示',
              '苏格拉底式提问' in skill_system and '代码审计式学习' in skill_system)
        check('T3p 未选的费曼不注入', '费曼式简化解释' not in skill_system)

        # ── T4 教师关闭 → 学生刷新恢复 ──
        tp.click('#aiPageOnlyBtn')
        wait_js(tp, "document.querySelector('#aiPageOnlyBtn .ai-page-only-label').textContent.includes('关')", 5.0)
        with app.app_context():
            SystemConfig._invalidate_cache()
        sp.reload()
        sp.wait_for_load_state('networkidle')
        open_panel(sp)
        check('T4a 技能选择刷新后保留', '2 项' in sp.locator('#aiSkillBtn').inner_text(),
              sp.locator('#aiSkillBtn').inner_text())
        ctx_btn = sp.locator('#aiContextToggle')
        check('T4 关闭后学生按钮恢复可用', ctx_btn.is_enabled(), ctx_btn.inner_text())
        ctx_btn.click()
        check('T4b 学生可切回自由对话', '自由对话' in ctx_btn.inner_text())

        # 生图模式：页面限定关闭后可见，生成结果以受鉴权图片地址展示
        image_btn = sp.locator('#aiImageModeBtn')
        check('T4c 生图入口在未限本页时可见', image_btn.is_visible())
        image_btn.click()
        check('T4d 生图模式可开启', '生图：开' in image_btn.inner_text(),
              image_btn.inner_text())
        sp.fill('#aiInput', '画一只猫')
        sp.click('#aiSendBtn')
        sp.wait_for_selector('.ai-msg-text img', timeout=15000)
        img_src = sp.locator('.ai-msg-text img').last.get_attribute('src') or ''
        check('T4e 生图结果使用受鉴权图片地址',
              img_src.startswith('/api/ai/images/'), img_src[:80])

        # ── T5 管理员配置页开关 ──
        ap = new_page(browser)
        ap.goto('/admin/login')
        ap.fill('input[name="username"]', ADM)
        ap.fill('input[name="password"]', PWD)
        ap.click('button[type="submit"]')
        ap.wait_for_load_state('networkidle')
        ap.goto('/admin/ai_config')
        ap.wait_for_load_state('networkidle')
        sw = ap.locator('#studentPageOnlySwitch')
        check('T5 管理员配置页开关初值与当前状态一致（关）', not sw.is_checked())
        sw.click()
        wait_js(ap, "document.getElementById('pageOnlyMsg').textContent.includes('已开启')", 5.0)
        with app.app_context():
            SystemConfig._invalidate_cache()
            on = SystemConfig.get_bool(KEY, False)
        check('T5b 管理员开关即时生效', on)

        browser.close()
finally:
    with app.app_context():
        cfg = AIConfig.query.first()
        if cfg_created:
            db.session.delete(cfg)
        else:
            (cfg.enabled, cfg.config_mode, cfg.api_url, cfg.model, cfg._api_key,
             cfg.page_context_default, cfg.vision_enabled) = saved_cfg
        setting = ClassroomSetting.query.first()
        if setting_created:
            db.session.delete(setting)
        else:
            setting.active_class_id = saved_active
        image_cfg = AIImageConfig.query.first()
        if image_cfg is not None:
            if image_created:
                db.session.delete(image_cfg)
            else:
                (image_cfg.enabled, image_cfg.provider, image_cfg.api_url,
                 image_cfg.model, image_cfg.size, image_cfg.max_images,
                 image_cfg.timeout_seconds, image_cfg.allow_student,
                 image_cfg.allow_teacher, image_cfg._api_key) = saved_image_cfg
        SystemConfig.set(KEY, saved_flag)
        db.session.commit()
        SystemConfig._invalidate_cache()
    _cleanup()
    with app.app_context():
        db.session.execute(_text('DELETE FROM classes WHERE id=:c'), {'c': CLS_ID})
        db.session.commit()

print('—— 页面 JS 错误 ——')
for u, e in page_errors[:5]:
    print(' ', u[-40:], e[:150])
check('T6 全程页面 JS 错误为 0', not page_errors)
failed = results.count(False)
print(f'===== AI 页面限定浏览器验证：{len(results) - failed}/{len(results)} 通过 =====')
sys.exit(1 if failed else 0)
