# -*- coding: utf-8 -*-
"""课堂页（/study/lesson/<id>）真实浏览器端到端测试（Playwright + Edge 无头）

链路：隔离库建资源+课件目录+编排树 → 匿名学生视角打开课堂页
→ 章节树渲染/视图切换（视频/PPTist/文档/外链）→ 自动播放开关
→ 黑板/画笔/倒计时（含秒表模式）→ 思维导图（.xmind 导入渲染）→ 流程图（加节点）
→ 电子文档抽屉分类（角色过滤）→ 截图留档 → 清理。

运行：venv/Scripts/python.exe -X utf8 tools/e2e_lesson_browser.py
环境：隔离库 itstudy_e2e、端口 5011、缓存独立；测后清理。
"""
import io
import json
import os
import re
import sys
import time
import threading
import zipfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ['DB_NAME'] = 'itstudy_e2e'
os.environ['CACHE_DIR'] = os.path.join(os.getcwd(), 'data', 'cache_e2e_lesson')
os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_PORT', '5432')
os.environ.setdefault('DB_USER', 'postgres')
os.environ.setdefault('DB_PASS', '@@')
os.environ['SECRET_KEY'] = 'e2e-lesson-key'
sys.path.insert(0, os.getcwd())

from app import create_app
from app.extensions import db

app = create_app()
from e2e_common import reset_shared_state  # noqa: E402
reset_shared_state(app)

UP = os.path.join('static', 'uploads')


def _purge():
    """清理本脚本的夹具（含历次中断遗留，按命名前缀）。

    夹具名带 PID 后缀：此前只在脚本末尾按本次 id 清理，中途崩溃的那次
    运行会永久留下一个带活跃课堂会话的班级（实测残留 BR课堂班_29592
    连带其它脚本的学生无法登录）。启动时与退出时（atexit，异常退出也执行）
    各清一次。
    """
    import glob
    import shutil
    from app.blueprints.auth import invalidate_active_class_cache
    from app.models import (AttendanceRecord, Class, ClassroomSession, Resource,
                            ResourceQuizResult, Student, TeachingSession)
    with app.app_context():
        db.session.rollback()
        res_ids = [r.id for r in Resource.query.filter(
            Resource.title.like('BR课堂E2E%')).all()]
        if res_ids:
            ResourceQuizResult.query.filter(
                ResourceQuizResult.resource_id.in_(res_ids)).delete(
                    synchronize_session=False)
            TeachingSession.query.filter(
                TeachingSession.resource_id.in_(res_ids)).delete(
                    synchronize_session=False)
            Resource.query.filter(Resource.id.in_(res_ids)).delete(
                synchronize_session=False)
        stu_ids = [s.id for s in Student.query.filter(
            Student.student_number.like('br\\_stu\\_%', escape='\\')).all()]
        if stu_ids:
            AttendanceRecord.query.filter(
                AttendanceRecord.student_id.in_(stu_ids)).delete(
                    synchronize_session=False)
            Student.query.filter(Student.id.in_(stu_ids)).delete(
                synchronize_session=False)
        cls_ids = [c.id for c in Class.query.filter(
            Class.name.like('BR课堂班%')).all()]
        if cls_ids:
            ClassroomSession.query.filter(
                ClassroomSession.class_id.in_(cls_ids)).delete(
                    synchronize_session=False)
            Class.query.filter(Class.id.in_(cls_ids)).delete(
                synchronize_session=False)
        db.session.commit()
        invalidate_active_class_cache()
    for path in glob.glob(os.path.join(UP, '_br_lesson_*')):
        shutil.rmtree(path, ignore_errors=True)


_purge()
import atexit  # noqa: E402
atexit.register(_purge)

# ── 数据准备 ──
DIR = f'_br_lesson_{os.getpid()}'
DIR_PATH = os.path.join(UP, DIR)
os.makedirs(DIR_PATH, exist_ok=True)

open(os.path.join(DIR_PATH, 'intro.mp4'), 'wb').write(b'0' * 64)
open(os.path.join(DIR_PATH, 'quiz.html'), 'w', encoding='utf-8').write(
    '<html><body><h1>HTML课件E2E</h1></body></html>')
open(os.path.join(DIR_PATH, 'guide.pdf'), 'wb').write(
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]>>endobj\n"
    b"trailer<</Root 1 0 R/Size 4>>\n%%EOF")
# 真实 PPTX（PPTist 导入回归；第二个文件用于切换/重复导入）
from openpyxl import Workbook  # noqa: E402
from pptx import Presentation  # noqa: E402

_wb = Workbook()
_ws = _wb.active
_ws.title = '成绩表'
_ws.append(['姓名', '分数'])
_ws.append(['张三', 95])
_ws.append(['李四', 88])
_wb.save(os.path.join(DIR_PATH, 'scores.xlsx'))


def _make_pptx(filename, title, slide_count):
    prs = Presentation()
    for i in range(slide_count):
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        slide.shapes.title.text = f'{title} {i + 1}'
        try:
            slide.placeholders[1].text = 'ITstudy 课堂 PPTist E2E'
        except (KeyError, IndexError):
            pass
    prs.save(os.path.join(DIR_PATH, filename))


_make_pptx('lesson.pptx', '智慧城市课件', 2)
_make_pptx('lesson2.pptx', '第二份课件', 3)
# 真结构 .xmind（zip + content.json，新版格式）
XMIND_JSON = json.dumps([{
    "id": "sheet1", "class": "sheet", "title": "sheet1",
    "rootTopic": {"id": "root", "class": "topic", "title": "智慧城市",
                  "children": {"attached": [
                      {"id": "t1", "title": "交通"},
                      {"id": "t2", "title": "教育",
                       "children": {"attached": [{"id": "t21", "title": "在线课堂"}]}}]}}
}], ensure_ascii=False)
with zipfile.ZipFile(os.path.join(DIR_PATH, 'mind.xmind'), 'w') as z:
    z.writestr('content.json', XMIND_JSON.encode('utf-8'))
# 供导入的 markdown
with open(os.path.join(DIR_PATH, 'mind.md'), 'w', encoding='utf-8') as f:
    f.write('# 根主题\n## 第一\n## 第二\n- 细节\n')

# 真实 xlsx（课堂电子文档表格预览回归）
from openpyxl import Workbook  # noqa: E402

_wb = Workbook()
_ws = _wb.active
_ws.title = '成绩表'
_ws.append(['姓名', '分数'])
_ws.append(['张三', 95])
_ws.append(['李四', 88])
_wb.save(os.path.join(DIR_PATH, 'scores.xlsx'))

TREE = [{"id": "ch1", "title": "第一关 智慧的家", "type": "section", "children": [
            {"id": "ch1-1", "title": "拓展", "type": "section", "children": [], "items": [
                {"id": "itLink", "title": "外部网页", "kind": "link",
                 "src": "https://example.com/", "visible": {"teacher": True, "student": True}},
                # 课件相对路径：服务端保存编排时应规范化为 /static/uploads/<dir>/quiz.html
                {"id": "itHtml", "title": "HTML 课件", "kind": "link",
                 "src": "quiz.html", "visible": {"teacher": True, "student": True}}]},
         ], "items": [
            {"id": "itVideo", "title": "课程导入视频", "kind": "video", "src": "intro.mp4",
             "visible": {"teacher": True, "student": True}},
            {"id": "itPptx", "title": "智慧城市课件", "kind": "pptx", "src": "lesson.pptx",
             "visible": {"teacher": True, "student": True}},
            {"id": "itPptx2", "title": "第二份课件", "kind": "pptx", "src": "lesson2.pptx",
             "visible": {"teacher": True, "student": True}},
            {"id": "itGuide", "title": "课堂活动单", "kind": "doc", "src": "guide.pdf",
             "doc_category": "activity_sheet", "visible": {"teacher": True, "student": True}},
            {"id": "itXlsx", "title": "成绩表", "kind": "doc", "src": "scores.xlsx",
             "doc_category": "material", "visible": {"teacher": True, "student": True}},
            {"id": "itDesign", "title": "教学设计", "kind": "doc", "src": "design.docx",
             "doc_category": "design", "visible": {"teacher": True, "student": False}},
         ]}]

from app.models import Class, ClassroomSession, Resource, Student

CLASS_NAME = f'BR课堂班_{os.getpid()}'
STUDENT_NUMBER = f'br_stu_{os.getpid()}'
STUDENT_PASSWORD = 'pass123456'

with app.app_context():
    cls = Class(name=CLASS_NAME)
    stu = Student(name='BR课堂E2E学生', student_number=STUDENT_NUMBER,
                  student_class=CLASS_NAME, has_changed_password=True)
    stu.set_password(STUDENT_PASSWORD)
    db.session.add_all([cls, stu])
    db.session.flush()
    stu.class_id = cls.id
    db.session.add(ClassroomSession(class_id=cls.id, is_active=True))
    res = Resource(title=f'BR课堂E2E_{os.getpid()}',
                   url=f'/static/uploads/{DIR}/intro.mp4',
                   show_in_student=True, show_in_classroom=True,
                   is_public=True,
                   lesson_tree=json.dumps(TREE, ensure_ascii=False))
    db.session.add(res)
    db.session.commit()
    RID = res.id
    CID = cls.id
    SID = stu.id

print(f'—— 数据就绪 rid={RID} ——')

# ── 启动本地服务 ──
PORT = 5011
BASE = f'http://127.0.0.1:{PORT}'
t = threading.Thread(target=lambda: __import__('waitress').serve(
    app, host='127.0.0.1', port=PORT, threads=16), daemon=True)
t.start()
time.sleep(2.5)

# ── 浏览器测试 ──
from playwright.sync_api import sync_playwright

results = []
page_errors = []
SHOT = 'data/e2e_lesson'
os.makedirs(SHOT, exist_ok=True)


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


with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    ctx = browser.new_context(viewport={'width': 1600, 'height': 900},
                              base_url=BASE)
    page = ctx.new_page()
    page.on('pageerror', lambda e: page_errors.append(str(e)))
    # 避免上次运行留下的收起状态影响工具点击
    ctx.add_init_script("try { localStorage.removeItem('lesson.toolbarCollapsed'); } catch (e) {}")

    # 1) 课堂页加载与章节树
    page.goto(f'/study/lesson/{RID}')
    wait_for(lambda: page.locator('.ch-item').count() >= 7, 8, '章节树渲染')
    items = page.locator('.ch-item')
    check('页面加载: 顶栏标题', page.locator('.lesson-title').inner_text() != '')
    check('章节树: 学生可见条目数=7（教学设计被服务端过滤）', items.count() == 7,
          f'实际 {items.count()}')
    check('工具栏: 学生端 6 个工具（无点名器）', page.locator('.tool-btn').count() == 6,
          f'实际 {page.locator(".tool-btn").count()}')
    check('工具栏: 收起按钮存在', page.locator('#lessonToolbarToggle').count() == 1)
    page.locator('#lessonToolbarToggle').click()
    check('工具栏: 收起后隐藏按钮组', not page.locator('#lessonToolbarItems').is_visible())
    check('工具栏: 收起状态标记', 'collapsed' in (page.locator('#lessonToolbar').get_attribute('class') or ''))
    page.locator('#lessonToolbarToggle').click()
    check('工具栏: 再次点击展开', page.locator('#lessonToolbarItems').is_visible())
    check('AI 助手未注入（匿名访问者非学生）', page.locator('#aiFab').count() == 0)

    # 2) 视频视图
    page.locator('.ch-item').first.click()
    wait_for(lambda: page.locator('#viewVideo').evaluate("e => e.classList.contains('active')"), 5, '视频视图')
    vsrc = page.locator('#videoPlayer').get_attribute('src') or ''
    check('视频: 播放器载入课件目录视频',
          '/study/lesson/' in vsrc and 'item/itVideo/file' in vsrc, vsrc[-40:])
    check('视频: 大播放按钮显示', page.locator('#videoHint').is_visible())
    # 倍速条
    check('视频: 倍速条显示', page.locator('#rateBar').is_visible())

    # 3) 自动播放开关
    page.locator('.autoplay-toggle .switch').click()
    ls = page.evaluate("localStorage.getItem('lesson.autoplay')")
    check('自动播放: 开关写入 localStorage', ls == '1', f'值={ls}')
    page.locator('.autoplay-toggle .switch').click()

    # 4) PPTX 视图：首次导入、切走再切回、切换到第二份课件
    #    回归旧版全局 _importDone 闩锁不复位导致第二次导入永远显示“正在加载中”。
    page.locator('.ch-item[data-id="itPptx"]').click()
    wait_for(lambda: page.locator('#viewPptist').evaluate("e => e.classList.contains('active')"), 5, 'PPTist 视图')
    check('课件: 进入 PPTist 放映视图', page.locator('#viewPptist').is_visible())
    check('课件: 放映 iframe 存在', page.locator('#pptistFrame').count() == 1)
    wait_for(lambda: page.locator('#pptistStatus').evaluate(
        "e => e.classList.contains('hidden')"), 40, 'PPTX 首次导入')
    check('课件: 首次导入后状态栏收起',
          page.locator('#pptistStatus').evaluate("e => e.classList.contains('hidden')"))
    page.locator('.ch-item[data-id="itGuide"]').click()
    page.locator('.ch-item[data-id="itPptx"]').click()
    wait_for(lambda: page.locator('#pptistStatus').evaluate(
        "e => e.classList.contains('hidden')"), 40, 'PPTX 再次导入')
    check('课件: 切走再切回可重新加载',
          page.locator('#pptistStatus').evaluate("e => e.classList.contains('hidden')"))
    page.locator('.ch-item[data-id="itPptx2"]').click()
    wait_for(lambda: page.locator('#pptistStatus').evaluate(
        "e => e.classList.contains('hidden')"), 40, '第二份 PPTX 导入')
    check('课件: 切换到第二份 PPTX 不卡加载中',
          page.locator('#pptistStatus').evaluate("e => e.classList.contains('hidden')"))
    # 快速连续切换：旧导入的迟到消息不能把新课件状态卡住
    page.locator('.ch-item[data-id="itPptx"]').click()
    page.locator('.ch-item[data-id="itPptx2"]').click()
    wait_for(lambda: page.locator('#pptistStatus').evaluate(
        "e => e.classList.contains('hidden')"), 40, '快速连续切换 PPTX')
    check('课件: 快速连续切换后状态栏收起',
          page.locator('#pptistStatus').evaluate("e => e.classList.contains('hidden')"))
    page.screenshot(path=f'{SHOT}/lesson_pptx_switch.png')

    # 5) 文档视图（JitViewer）
    page.locator('.ch-item[data-id="itGuide"]').click()
    wait_for(lambda: page.locator('#viewDoc').evaluate("e => e.classList.contains('active')"), 5, '文档视图')
    dsrc = page.locator('#docFrame').get_attribute('src') or ''
    check('文档: JitViewer 预览参数正确',
          '/study/preview' in dsrc and 'lesson_item=itGuide' in dsrc,
          dsrc[:80])
    page.screenshot(path=f'{SHOT}/lesson_doc.png')

    # 5a) xlsx 走 SheetJS 表格预览，不再依赖 JitViewer
    page.locator('.ch-item[data-id="itXlsx"]').click()
    wait_for(lambda: page.locator('#viewDoc').evaluate("e => e.classList.contains('active')"), 5, 'xlsx 文档视图')
    xlsx_frame = page.frame_locator('#docFrame')
    wait_for(lambda: xlsx_frame.locator('.xlsx-table td').count() > 0, 12, 'xlsx 表格渲染')
    xlsx_text = xlsx_frame.locator('.xlsx-table').inner_text()
    check('xlsx: 表格预览渲染', xlsx_frame.locator('.xlsx-table td').count() >= 6,
          f'单元格 {xlsx_frame.locator(".xlsx-table td").count()}')
    check('xlsx: 单元格内容正确', '张三' in xlsx_text and '95' in xlsx_text,
          xlsx_text[:60].replace('\n', ' / '))
    page.screenshot(path=f'{SHOT}/lesson_xlsx.png')

    # 5b) 课件目录内 HTML 课件：相对路径应被规范化为站内绝对路径（防 404）
    page.locator('.ch-item[data-id="itHtml"]').click()
    wait_for(lambda: page.locator('#viewLink').evaluate("e => e.classList.contains('active')"), 5, 'HTML 课件视图')
    lsrc = page.locator('#linkFrame').get_attribute('src') or ''
    check('HTML 课件: 相对路径经课堂条目路由加载',
          '/study/lesson/' in lsrc and 'item/itHtml/file' in lsrc, lsrc[-60:])

    # 6) 电子文档抽屉（角色过滤：学生视角无"教学设计"内容）
    page.locator('#btnDocs').click()
    wait_for(lambda: page.locator('#docsDrawer').is_visible(), 5, '文档抽屉')
    groups = page.locator('.doc-group-title').all_inner_texts()
    check('文档抽屉: 分类标题', len(groups) == 8, ' / '.join(g.replace(chr(10), '') for g in groups))
    act_items = page.locator('#docsDrawer .doc-item').count()
    check('文档抽屉: 学生仅见活动单/素材（教学设计隐藏）', act_items == 2, f'实际 {act_items}')
    page.screenshot(path=f'{SHOT}/lesson_docs_drawer.png')
    page.locator('#docsClose').click()

    # 7) 黑板（护眼 + 粉笔色 + 点按落笔 + 多页翻页）
    page.locator('.tool-btn[data-tool="blackboard"]').click()
    wait_for(lambda: page.locator('#blackboard').is_visible(), 5, '黑板')
    bb_bg = page.locator('#blackboard').evaluate("e => getComputedStyle(e).backgroundColor")
    check('黑板: 护眼墨绿板面', '45, 74, 62' in bb_bg, bb_bg)
    box = page.locator('#blackboardCanvas').bounding_box()
    check('黑板: 画布全屏', box and box['width'] > 1500 and box['height'] > 800,
          f'{box and int(box["width"])}x{box and int(box["height"])}')
    colors = page.locator('.bb-chalk').evaluate_all(
        "els => els.map(e => getComputedStyle(e).backgroundColor)")
    check('黑板: 红/黄粉笔可见', 'rgb(255, 235, 59)' in colors and
          'rgb(255, 82, 82)' in colors, ','.join(colors))

    def canvas_alpha(css_x, css_y):
        return page.locator('#blackboardCanvas').evaluate(
            """(c, p) => {
              const dpr = window.devicePixelRatio || 1;
              const r = c.getBoundingClientRect();
              const x = Math.round((p.x - r.left) * dpr);
              const y = Math.round((p.y - r.top) * dpr);
              return c.getContext('2d').getImageData(x, y, 1, 1).data[3];
            }""", {'x': css_x, 'y': css_y})

    page.mouse.click(box['x'] + 100, box['y'] + 100)
    check('黑板: 单击落笔成点', canvas_alpha(100, 100) > 0, canvas_alpha(100, 100))
    check('黑板: 初始 1 页', page.locator('#bbPageInfo').inner_text() == '1 / 1')
    page.locator('#bbNew').click()
    check('黑板: 新建第 2 页', page.locator('#bbPageInfo').inner_text() == '2 / 2')
    check('黑板: 新页为空白', canvas_alpha(100, 100) == 0)
    page.mouse.click(box['x'] + 200, box['y'] + 200)
    check('黑板: 第 2 页可书写', canvas_alpha(200, 200) > 0)
    page.screenshot(path=f'{SHOT}/lesson_blackboard_page2.png')
    page.locator('#bbPrev').click()
    page.wait_for_timeout(300)
    check('黑板: 上一页回到第 1 页', page.locator('#bbPageInfo').inner_text() == '1 / 2')
    check('黑板: 第 1 页笔迹保留', canvas_alpha(100, 100) > 0 and canvas_alpha(200, 200) == 0)
    page.locator('#bbNext').click()
    page.wait_for_timeout(300)
    check('黑板: 下一页回到第 2 页', page.locator('#bbPageInfo').inner_text() == '2 / 2')
    check('黑板: 第 2 页笔迹保留', canvas_alpha(200, 200) > 0)
    page.locator('#bbClose').click()
    page.locator('.tool-btn[data-tool="blackboard"]').click()
    wait_for(lambda: page.locator('#blackboard').is_visible(), 5, '黑板重开')
    check('黑板: 重开保留页数', page.locator('#bbPageInfo').inner_text() == '2 / 2')
    check('黑板: 重开保留第 2 页内容', canvas_alpha(200, 200) > 0)
    page.screenshot(path=f'{SHOT}/lesson_blackboard.png')
    page.locator('#bbClose').click()

    # 8) 画笔开关
    page.locator('.tool-btn[data-tool="draw"]').click()
    check('画笔: 标注层开启', page.locator('#drawCanvas').is_visible())
    page.locator('.tool-btn[data-tool="draw"]').click()
    check('画笔: 再点关闭', not page.locator('#drawCanvas').is_visible())

    # 9) 倒计时
    page.locator('.tool-btn[data-tool="timer"]').click()
    wait_for(lambda: page.locator('#timerModal').is_visible(), 5, '倒计时弹窗')
    page.locator('.tm-presets button[data-min="5"]').click()
    tval = page.locator('#timerDisplay').inner_text()
    check('倒计时: 预设 5 分钟', tval == '05:00', tval)
    page.locator('#timerStart').click()
    time.sleep(1.2)
    tval2 = page.locator('#timerDisplay').inner_text()
    check('倒计时: 正在走秒', tval2 in ('04:58', '04:59'), tval2)

    # 秒表模式：运行中切换，预设隐藏、模式标签明确、正计时可暂停/恢复
    page.locator('#timerStopwatch').click()
    check('秒表: 模式标签', page.locator('#timerModeLabel').inner_text() == '秒表')
    check('秒表: 预设隐藏', not page.locator('.tm-presets').is_visible())
    check('秒表: 切换按钮', page.locator('#timerStopwatch').inner_text() == '倒计时模式')
    sw0 = page.locator('#timerDisplay').inner_text()
    check('秒表: 归零', sw0 == '00:00.0', sw0)
    page.locator('#timerStart').click()
    time.sleep(0.8)
    sw1 = page.locator('#timerDisplay').inner_text()
    check('秒表: 正计时（十分之一秒）', bool(re.match(r'00:00\.[1-9]', sw1)), sw1)
    page.locator('#timerPause').click()
    swPaused = page.locator('#timerDisplay').inner_text()
    time.sleep(0.5)
    check('秒表: 暂停后不再走', page.locator('#timerDisplay').inner_text() == swPaused, swPaused)
    page.locator('#timerStart').click()
    time.sleep(0.5)
    sw2 = page.locator('#timerDisplay').inner_text()
    check('秒表: 继续计时', sw2 != swPaused, sw2)
    page.locator('#timerStopwatch').click()
    check('秒表: 切回倒计时', page.locator('#timerModeLabel').inner_text() == '倒计时')
    check('秒表: 切回后恢复预设', page.locator('#timerDisplay').inner_text() == '05:00')
    page.locator('[data-close="timerModal"]').click()

    # 10) 思维导图：完整应用 iframe 渲染 + .xmind 导入
    page.locator('.tool-btn[data-tool="mindmap"]').click()
    wait_for(lambda: page.locator('#mindmapModal').is_visible(), 5, '导图弹窗')
    mm = page.frame_locator('#mindmapFrame')
    wait_for(lambda: mm.locator('.nodes .node').count() > 0, 15, '思维导图应用初始化')
    check('思维导图: 应用渲染', mm.locator('.nodes .node').count() >= 1)
    mm.locator('#fileInput').set_input_files(os.path.join(DIR_PATH, 'mind.xmind'))
    wait_for(lambda: mm.locator('.nodes .node').count() >= 3, 12, 'xmind 导入')
    n_nodes = mm.locator('.nodes .node').count()
    check('思维导图: .xmind 导入生成节点', n_nodes >= 3, f'{n_nodes} 个节点')
    mm.locator('#fileInput').set_input_files(os.path.join(DIR_PATH, 'mind.md'))
    time.sleep(1.0)
    n_nodes2 = mm.locator('.nodes .node').count()
    check('思维导图: .md 导入生成节点', n_nodes2 >= 3, f'{n_nodes2} 个节点')
    page.screenshot(path=f'{SHOT}/lesson_mindmap.png')
    page.locator('[data-close="mindmapModal"]').click()

    # 11) 流程拓扑图画板：完整应用 iframe 渲染 + 添加图形
    page.locator('.tool-btn[data-tool="flow"]').click()
    wait_for(lambda: page.locator('#flowModal').is_visible(), 5, '流程图弹窗')
    fl = page.frame_locator('#flowFrame')
    wait_for(lambda: fl.locator('#layerNodes g.node').count() > 0, 15, '流程图应用初始化')
    n_flow0 = fl.locator('#layerNodes g.node').count()
    fl.locator('#toolList .tool').first.click()
    wait_for(lambda: fl.locator('#layerNodes g.node').count() > n_flow0, 6, '节点添加')
    n_nodes3 = fl.locator('#layerNodes g.node').count()
    check('流程图: 添加节点', n_nodes3 > n_flow0, f'{n_flow0} → {n_nodes3}')
    page.screenshot(path=f'{SHOT}/lesson_flow.png')
    page.locator('[data-close="flowModal"]').click()

    # 12) 全屏按钮存在
    check('顶栏: 全屏/文档按钮', page.locator('#btnFullscreen').count() == 1
          and page.locator('#btnDocs').count() == 1)

    # 13) 教师视角：图板保存到课件 / 从课件打开
    admin = app.test_client()
    with admin.session_transaction() as s:
        s.update(is_admin=True, admin_name='管理员', csrf_token='e2e-tool-csrf')
    admin.get('/')
    for cookie_name in ('session', 'csrf_token'):
        ck = admin.get_cookie(cookie_name)
        if ck:
            ctx.add_cookies([{'name': ck.key, 'value': ck.value,
                              'domain': '127.0.0.1', 'path': '/'}])
    page.goto(f'/study/lesson/{RID}?mode=classroom')
    wait_for(lambda: page.locator('.tool-btn').count() >= 6, 8, '教师课堂页加载')
    check('教师: 保存到课件按钮可见', page.locator('#flowSaveBtn').count() == 1)

    page.locator('.tool-btn[data-tool="flow"]').click()
    wait_for(lambda: page.locator('#flowSaveBtn').is_enabled(), 15, '流程图应用就绪')
    fl = page.frame_locator('#flowFrame')
    wait_for(lambda: fl.locator('#layerNodes g.node').count() > 0, 15, '流程图应用渲染')
    n_before = fl.locator('#layerNodes g.node').count()
    page.locator('#flowSaveBtn').click()
    wait_for(lambda: page.locator('#toolNameModal').is_visible(), 8, '保存名称弹窗')
    name_flow = f'E2E流程{os.getpid()}'
    page.locator('#toolNameInput').fill(name_flow)
    page.locator('#toolNameOk').click()
    wait_for(lambda: os.path.isfile(os.path.join(
        DIR_PATH, f'flow-{name_flow}.json')), 10, '流程图写入课件目录')
    check('流程图: 保存到课件目录', os.path.isfile(os.path.join(
        DIR_PATH, f'flow-{name_flow}.json')))
    try:
        with page.expect_download(timeout=10000) as dl_info:
            fl.locator('#btnExport').click()
        download = dl_info.value
        check('流程图: 导出 PNG', download.suggested_filename.endswith('.png'),
              download.suggested_filename)
    except Exception as e:
        check('流程图: 导出 PNG', False, str(e)[:80])
    # 导出 JSON 应与保存图片同组（顶部工具栏），不再藏在「打开/导入」弹窗
    try:
        check('流程图: 打开弹窗不含导出 JSON',
              fl.locator('#ioModal #ioJson').count() == 0)
        check('流程图: 顶部有 JSON 导出按钮',
              fl.locator('#topbar #btnExportJson').count() == 1)
        with page.expect_download(timeout=10000) as dl_json:
            fl.locator('#btnExportJson').click()
        jd = dl_json.value
        check('流程图: 导出 JSON', jd.suggested_filename.endswith('.json'),
              jd.suggested_filename)
        check('流程图: 导出 JSON 不弹打开对话框',
              not fl.locator('#ioModal').is_visible())
    except Exception as e:
        check('流程图: 导出 JSON', False, str(e)[:80])
    page.locator('[data-close="flowModal"]').click()

    page.locator('.tool-btn[data-tool="mindmap"]').click()
    wait_for(lambda: page.locator('#mindmapSaveBtn').is_enabled(), 15, '思维导图应用就绪')
    mm = page.frame_locator('#mindmapFrame')
    wait_for(lambda: mm.locator('.nodes .node').count() > 0, 15, '思维导图应用渲染')
    mm.locator('#fileInput').set_input_files(os.path.join(DIR_PATH, 'mind.md'))
    time.sleep(0.8)
    page.locator('#mindmapSaveBtn').click()
    wait_for(lambda: page.locator('#toolNameModal').is_visible(), 8, '导图保存名称弹窗')
    name_mm = f'E2E导图{os.getpid()}'
    page.locator('#toolNameInput').fill(name_mm)
    page.locator('#toolNameOk').click()
    wait_for(lambda: os.path.isfile(os.path.join(
        DIR_PATH, f'mindmap-{name_mm}.json')), 10, '思维导图写入课件目录')
    check('思维导图: 保存到课件目录', os.path.isfile(os.path.join(
        DIR_PATH, f'mindmap-{name_mm}.json')))
    # 换成另一份内容后，再从课件里打开刚才保存的那份
    mm.locator('#fileInput').set_input_files(os.path.join(DIR_PATH, 'mind.xmind'))
    time.sleep(0.8)
    page.locator('#mindmapOpenList').select_option(label=name_mm)
    wait_for(lambda: mm.locator('.nodes .node').count() >= 3, 10, '从课件打开导图')
    check('思维导图: 从课件打开', mm.locator('.nodes .node').count() >= 3)
    try:
        mm.locator('[data-menu="export"]').click()
        with page.expect_download(timeout=15000) as dl_info:
            mm.locator('#menu-export .menu-item').filter(has_text='图片 PNG').click()
        download = dl_info.value
        check('思维导图: 导出 PNG', download.suggested_filename.endswith('.png'),
              download.suggested_filename)
    except Exception as e:
        check('思维导图: 导出 PNG', False, str(e)[:80])
    page.locator('[data-close="mindmapModal"]').click()

    # 流程图：新增节点后打开刚保存的版本，节点数应回到保存时
    page.locator('.tool-btn[data-tool="flow"]').click()
    wait_for(lambda: page.locator('#flowSaveBtn').is_enabled(), 10, '流程图应用再次就绪')
    fl = page.frame_locator('#flowFrame')
    fl.locator('#toolList .tool').first.click()
    time.sleep(0.5)
    check('流程图: 再次打开后追加节点', fl.locator('#layerNodes g.node').count() > n_before)
    page.locator('#flowOpenList').select_option(label=name_flow)
    wait_for(lambda: fl.locator('#layerNodes g.node').count() == n_before, 10, '从课件打开流程图')
    check('流程图: 从课件打开', fl.locator('#layerNodes g.node').count() == n_before,
          f'{n_before} 个节点')

    # AI 深入点评：验证浏览器侧走 /api/ai/lesson_eval（服务端配置由测试注入假上游）
    from app.blueprints import ai as ai_module
    ai_module._resolve_effective_config = lambda: (True, {
        'api_key': 'e2e-key', 'api_url': 'https://ai.invalid/v1',
        'model': 'e2e-model', 'provider': 'openai',
        'max_tokens': 2048, 'temperature': 0.7,
        'needs_dns_pinning': False, 'config_mode': 'admin',
        'vision_enabled': False,
    }, 200)
    ai_module._call_chat = lambda *a, **kw: (True, 'AI 点评：把判断框补成是/否两条路。', 200, 'stop')
    fl.locator('#btnReview').click()
    wait_for(lambda: fl.locator('#reviewModal').evaluate(
        "e => e.classList.contains('on')"), 6, '智能点评弹窗')
    fl.locator('#rvAI').click()
    wait_for(lambda: 'AI 点评' in (fl.locator('#aiOut').inner_text() or ''), 12, 'AI 点评返回')
    check('流程图: AI 点评走登录账号配置', 'AI 点评' in fl.locator('#aiOut').inner_text())
    page.screenshot(path=f'{SHOT}/lesson_tool_bridge.png')
    page.locator('[data-close="flowModal"]').click()

    # 17) 学生课堂：从课件打开教师刚保存的导图 / 流程图
    #    教师保存到课件目录后，学生端应能在自己的课堂页读取同一份文档。
    stu_ctx = browser.new_context(viewport={'width': 1600, 'height': 900},
                                  base_url=BASE)
    sp = stu_ctx.new_page()
    sp.on('pageerror', lambda e: page_errors.append(str(e)))
    sp.goto('/')
    sp.fill('input[name="student_number"]', STUDENT_NUMBER)
    sp.fill('input[name="password"]', STUDENT_PASSWORD)
    sp.locator('form').filter(
        has=sp.locator('input[name="student_number"]')).locator(
        'button[type="submit"]').click()
    sp.wait_for_url('**/study*', timeout=15000)
    sp.goto(f'/study/lesson/{RID}')
    wait_for(lambda: sp.locator('.tool-btn').count() >= 6, 8, '学生课堂页加载')

    sp.locator('.tool-btn[data-tool="mindmap"]').click()
    wait_for(lambda: sp.locator('#mindmapOpenList').is_enabled(), 15, '学生思维导图就绪')
    sp.locator('#mindmapOpenList').select_option(label=name_mm)
    smm = sp.frame_locator('#mindmapFrame')
    wait_for(lambda: smm.locator('.nodes .node').count() >= 3, 10,
             '学生从课件打开导图')
    check('学生: 思维导图从课件打开', smm.locator('.nodes .node').count() >= 3,
          f'{smm.locator(".nodes .node").count()} 个节点')
    sp.locator('[data-close="mindmapModal"]').click()

    sp.locator('.tool-btn[data-tool="flow"]').click()
    wait_for(lambda: sp.locator('#flowOpenList').is_enabled(), 15, '学生流程图就绪')
    sp.locator('#flowOpenList').select_option(label=name_flow)
    sfl = sp.frame_locator('#flowFrame')
    wait_for(lambda: sfl.locator('#layerNodes g.node').count() == n_before, 10,
             '学生从课件打开流程图')
    check('学生: 流程图从课件打开',
          sfl.locator('#layerNodes g.node').count() == n_before,
          f'{sfl.locator("#layerNodes g.node").count()} 个节点')
    sp.screenshot(path=f'{SHOT}/lesson_tool_bridge_student.png')
    stu_ctx.close()

    browser.close()

# 清理由 atexit 注册的 _purge() 完成（正常结束与异常退出都会执行）

total, ok = len(results), sum(results)
print(f'—— 结果: {ok}/{total} 通过；页面 JS 错误 {len(page_errors)} ——')
for e in page_errors[:5]:
    print('  pageerror:', e[:160])
sys.exit(0 if ok == total and not page_errors else 1)
