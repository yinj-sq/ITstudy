# -*- coding: utf-8 -*-
"""学生学习活动文档预览 E2E（Playwright + Edge 无头）。

覆盖：学生活动页 → 预览活动文档
- DOCX / PPTX / PDF / TXT 由 JitViewer 正常渲染
- HTML 以 sandbox + srcdoc 内联预览，页内脚本不能影响父页
- 无页面 JS 异常

运行：venv/Scripts/python.exe -X utf8 tools/e2e_activity_preview_browser.py
环境：隔离库 itstudy_e2e、端口 5015、独立缓存；测后清理。
"""
import io
import os
import sys
import threading
import time
import uuid
import zipfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ['DB_NAME'] = 'itstudy_e2e'
os.environ['CACHE_DIR'] = os.path.join(os.getcwd(), 'data', 'cache_e2e_activity_preview')
os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_PORT', '5432')
os.environ.setdefault('DB_USER', 'postgres')
os.environ.setdefault('DB_PASS', '@@')
os.environ['SECRET_KEY'] = 'e2e-activity-preview'
sys.path.insert(0, os.getcwd())

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import (AttendanceRecord, Class, ClassroomSession,  # noqa: E402
                        LearningActivity, Resource, Student)

SFX = uuid.uuid4().hex[:8]
CLASS_NAME = f'__ap_cls_{SFX}'
STUDENT_NUMBER = f'__ap_stu_{SFX}'
PASSWORD = 'ApPass123'
PORT = 5015
BASE = f'http://127.0.0.1:{PORT}'
app = create_app()
from e2e_common import reset_shared_state  # noqa: E402
reset_shared_state(app)
FAILED = []
FILES = []
DIRS = []


def show(name, ok, detail=''):
    mark = '✓' if ok else '✗'
    if not ok:
        FAILED.append(name)
    print(f'{mark} {name}' + (f' | {detail}' if detail else ''))


def cleanup():
    with app.app_context():
        stu = Student.query.filter_by(student_number=STUDENT_NUMBER).first()
        if stu:
            AttendanceRecord.query.filter_by(student_id=stu.id).delete(
                synchronize_session=False)
            db.session.delete(stu)
        for act in LearningActivity.query.filter(
                LearningActivity.title.like(f'__ap_act_{SFX}%')).all():
            if act.document_path:
                p = os.path.join(app.static_folder, 'uploads', act.document_path)
                if os.path.exists(p):
                    FILES.append(p)
                    DIRS.append(os.path.dirname(p))
            db.session.delete(act)
        for res in Resource.query.filter(
                Resource.title.like(f'__ap_res_{SFX}%')).all():
            db.session.delete(res)
        cls = Class.query.filter_by(name=CLASS_NAME).first()
        if cls:
            ClassroomSession.query.filter_by(class_id=cls.id).delete(
                synchronize_session=False)
            db.session.delete(cls)
        db.session.commit()
        from app.blueprints.auth import invalidate_active_class_cache
        invalidate_active_class_cache()
    for p in FILES:
        try:
            if os.path.exists(p):
                os.remove(p)
        except OSError:
            pass
    for d in DIRS:
        try:
            os.rmdir(d)
        except OSError:
            pass


def make_docx(path):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>''')
        z.writestr('_rels/.rels', '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>''')
        z.writestr('word/document.xml', '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>DOCX 预览测试</w:t></w:r></w:p></w:body></w:document>''')


cleanup()
with app.app_context():
    cls = Class(name=CLASS_NAME)
    stu = Student(name='活动预览E2E学生', student_number=STUDENT_NUMBER,
                  student_class=CLASS_NAME, has_changed_password=True)
    stu.set_password(PASSWORD)
    db.session.add_all([cls, stu])
    db.session.flush()
    stu.class_id = cls.id
    db.session.add(ClassroomSession(class_id=cls.id, is_active=True))
    # is_public：学生资源范围 =「任课教师范围 + 公开/内置」（V5.0.91 起）。
    # 夹具资源没有创建教师，不设公开时学生打不开活动页（404），
    # 「预览活动文档」链接根本不会出现。
    res = Resource(title=f'__ap_res_{SFX}', url='', show_in_student=True,
                   show_in_classroom=True, is_public=True)
    db.session.add(res)
    db.session.flush()
    base = os.path.join(app.static_folder, 'uploads', f'activity_docs/{res.id}')
    os.makedirs(base, exist_ok=True)
    DIRS.append(base)

    from pptx import Presentation
    docx_path = os.path.join(base, 'study.docx')
    make_docx(docx_path)
    pptx_path = os.path.join(base, 'slides.pptx')
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = '活动课件'
    slide.placeholders[1].text = 'PPTX 预览测试'
    prs.save(pptx_path)
    pdf_path = os.path.join(base, 'guide.pdf')
    with open(pdf_path, 'wb') as f:
        f.write(b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
                b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
                b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]>>endobj\n"
                b"trailer<</Root 1 0 R/Size 4>>\n%%EOF\n")
    txt_path = os.path.join(base, 'note.txt')
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write('TXT 活动文档预览测试')
    html_path = os.path.join(base, 'unsafe.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write('<html><body><script>document.title="XSS"</script>HTML 活动文档</body></html>')
    FILES.extend([docx_path, pptx_path, pdf_path, txt_path, html_path])

    ids = {}
    for kind, path in [('docx', docx_path), ('pptx', pptx_path),
                       ('pdf', pdf_path), ('txt', txt_path), ('html', html_path)]:
        rel = os.path.relpath(path, os.path.join(app.static_folder, 'uploads')).replace('\\', '/')
        act = LearningActivity(resource_id=res.id, title=f'__ap_act_{SFX}_{kind}',
                               is_active=True, document_path=rel,
                               document_name=os.path.basename(path))
        db.session.add(act)
        db.session.flush()
        ids[kind] = act.id
    db.session.commit()
    from app.blueprints.auth import invalidate_active_class_cache
    invalidate_active_class_cache()

from waitress import serve  # noqa: E402

threading.Thread(target=lambda: serve(app, host='127.0.0.1', port=PORT, threads=8),
                 daemon=True).start()
time.sleep(1.5)

from playwright.sync_api import sync_playwright  # noqa: E402

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        ctx = browser.new_context(base_url=BASE, viewport={'width': 1400, 'height': 900})
        page = ctx.new_page()
        page.goto('/')
        page.fill('input[name="student_number"]', STUDENT_NUMBER)
        page.fill('input[name="password"]', PASSWORD)
        page.locator('form').filter(
            has=page.locator('input[name="student_number"]')
        ).locator('button[type="submit"]').click()
        page.wait_for_url('**/study*', timeout=15000)

        markers = {'docx': 'DOCX 预览测试', 'pptx': 'PPTX 预览测试',
                   'pdf': 'guide.pdf', 'txt': 'TXT 活动文档预览测试'}
        for kind, aid in ids.items():
            page.goto(f'/study/activity/{aid}')
            with page.expect_popup() as pop:
                page.locator('a:has-text("预览活动文档")').click()
            pp = pop.value
            errors = []
            pp.on('pageerror', lambda e, errors=errors: errors.append(str(e)))
            pp.wait_for_load_state('domcontentloaded', timeout=15000)
            pp.wait_for_timeout(6000)
            text = pp.locator('#jitViewerContainer').inner_text()
            if kind == 'html':
                frame_count = pp.locator('.html-sandbox-frame').count()
                html_text = ''
                for f in pp.frames:
                    if f == pp.main_frame:
                        continue
                    try:
                        html_text = f.locator('body').inner_text()
                    except Exception:
                        pass
                note = pp.locator('.html-sandbox-note').inner_text()
                show('HTML 沙箱内联预览',
                     frame_count == 1 and 'HTML 活动文档' in html_text
                     and '安全沙箱预览' in note,
                     f'frame={frame_count} text={html_text[:40]}')
                show('HTML 脚本未影响父页标题',
                     'XSS' not in (pp.title() or ''), pp.title())
            else:
                show(f'{kind.upper()} 预览渲染', markers[kind] in text and '不支持' not in text,
                     text[:80].replace('\n', ' '))
            show(f'{kind.upper()} 无页面异常', not errors, '; '.join(errors[:2]))
            pp.close()
        browser.close()
finally:
    cleanup()

print(f'\n结果：{len(FAILED) == 0 and "全部通过" or "失败 " + ", ".join(FAILED)}')
sys.exit(0 if not FAILED else 1)
