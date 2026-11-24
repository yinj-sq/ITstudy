# -*- coding: utf-8 -*-
"""学习活动文档预览回归（2026-11-02）。

覆盖：
- document_preview.html 的预览类型与 JitViewer EXTENSION_MAP 对齐
  （PPTX/PPT、代码、CAD、3D 不再误判为不支持；图片/音视频走原生；
  HTML 出于同源 XSS 风险保持下载）
- 学生端活动 PPTX 文档：活动页入口、预览页、inline 文件响应
"""
import pathlib
import re
import uuid

import pytest
from pptx import Presentation

from app import create_app
from app.extensions import cache, db
from app.models import (Class, ClassroomSession, LearningActivity, Resource,
                        Student, Teacher, TeachingSession)

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / 'templates' / 'document_preview.html'
BUNDLE = ROOT / 'static' / 'js' / 'jit-viewer.min.js'


def _template_list(name):
    src = TEMPLATE.read_text(encoding='utf-8')
    m = re.search(rf'var {name} = \[(.*?)\];', src, re.S)
    assert m, f'{name} 未找到'
    return set(re.findall(r"'([^']+)'", m.group(1)))


def _jitviewer_extensions():
    src = BUNDLE.read_text(encoding='utf-8', errors='ignore')
    m = re.search(r'const EXTENSION_MAP=\{(.*?)\},MIME_MAP=', src, re.S)
    assert m, 'JitViewer EXTENSION_MAP 未找到'
    by_type = {}
    for ext, typ in re.findall(r'([A-Za-z0-9_.-]+):"([a-z0-9]+)"', m.group(1)):
        by_type.setdefault(typ, set()).add(ext)
    return by_type


def test_preview_type_lists_cover_all_jitviewer_extensions():
    by_type = _jitviewer_extensions()
    jit = _template_list('jitSupported')
    native = _template_list('nativeSupported')
    sandboxed = _template_list('sandboxedHtml')

    # PPTX/PPT 是本次修复的核心：活动/作业/网盘预览都走 JitViewer
    assert {'pptx', 'ppt'} <= jit
    # 代码、CAD、3D 全量覆盖
    assert by_type['code'] <= jit
    assert by_type['cad'] <= jit
    assert by_type['model3d'] <= jit
    # 其余文档类型（除图片/音视频/HTML）全部走 JitViewer
    jit_types = set(by_type) - {'html', 'image', 'audio', 'video'}
    assert set().union(*(by_type[t] for t in jit_types)) <= jit
    # 图片/音视频走原生，不加载 9.7MB 预览脚本
    for typ in ('image', 'audio', 'video'):
        assert by_type[typ] <= native
    # HTML 安全排除出 JitViewer，改走 sandbox + srcdoc 内联预览
    assert by_type['html'] == {'htm', 'html'}
    assert by_type['html'] <= sandboxed
    assert 'html' not in jit and 'htm' not in jit
    # 页面可见的支持格式清单
    page = TEMPLATE.read_text(encoding='utf-8')
    for label in ('PPTX', 'XLSX', 'OFD', 'CAD', '3D', 'HTML'):
        assert label in page


@pytest.fixture(scope='module')
def app():
    return create_app()


def test_activity_pptx_preview_for_student_teacher_admin(app, monkeypatch):
    sfx = uuid.uuid4().hex[:8]
    sid = tid = rid = aid = cls_id = None
    rel = None
    abs_path = None
    try:
        with app.app_context():
            cls = Class(name=f'__doc_prev_cls_{sfx}')
            stu = Student(name='__doc_prev_stu__',
                          student_number=f'__dp_{sfx}',
                          student_class=cls.name,
                          password_hash='x', is_activated=True,
                          has_changed_password=True)
            teacher = Teacher(username=f'__dp_t_{sfx}',
                              display_name='__doc_prev_teacher__')
            teacher.set_password('pass123456')
            db.session.add_all([cls, stu, teacher])
            db.session.flush()
            sid, tid = stu.id, teacher.id
            cls_id = cls.id
            stu.class_id = cls.id
            res = Resource(title=f'__doc_prev_res_{sfx}', url='',
                           show_in_student=True, show_in_classroom=True,
                           creator_type='teacher', creator_teacher_id=tid,
                           creator_name=teacher.display_name)
            db.session.add(res)
            db.session.flush()
            # 学生资源范围跟随授课教师：教师正在该班上课
            db.session.add(TeachingSession(
                resource_id=res.id, teacher_id=teacher.id,
                teacher_name=teacher.display_name, class_id=cls.id,
                status='active'))
            db.session.add(ClassroomSession(class_id=cls.id, is_active=True))
            rid = res.id
            rel = f'activity_docs/{rid}/slides.pptx'
            abs_path = ROOT / 'static' / 'uploads' / 'activity_docs' / str(rid) / 'slides.pptx'
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            prs = Presentation()
            slide = prs.slides.add_slide(prs.slide_layouts[0])
            slide.shapes.title.text = '活动课件'
            slide.placeholders[1].text = 'PPTX 预览回归'
            prs.save(str(abs_path))
            act = LearningActivity(resource_id=rid, title=f'__doc_prev_act_{sfx}',
                                   is_active=True, document_path=rel,
                                   document_name='slides.pptx')
            db.session.add(act)
            db.session.commit()
            aid = act.id

        from app.blueprints import auth as auth_module
        monkeypatch.setattr(auth_module, '_get_active_class_ids', lambda: set())
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['student_id'] = sid
            sess['student_name'] = '__doc_prev_stu__'
            sess['csrf_token'] = 't'

        page = client.get(f'/study/activity/{aid}').get_data(as_text=True)
        assert '预览活动文档' in page

        preview = client.get(f'/activity/document/{aid}/preview')
        assert preview.status_code == 200
        html = preview.get_data(as_text=True)
        assert 'JitViewer' in html
        assert "'pptx'" in html
        # 学生默认返回学生活动页；伪造 source=activities 也不能拿到教师页面
        assert '返回活动' in html and f'/study/activity/{aid}' in html
        forged = client.get(
            f'/activity/document/{aid}/preview?source=activities')
        forged_html = forged.get_data(as_text=True)
        assert '返回活动' in forged_html
        assert '返回学习活动' not in forged_html

        inline = client.get(f'/activity/document/{aid}?inline=1')
        assert inline.status_code == 200
        ctype = inline.headers.get('Content-Type') or ''
        assert ('presentationml.presentation' in ctype or 'octet-stream' in ctype)
        assert len(inline.get_data()) > 0
        inline.close()

        # 教师（资源创建者）与管理员走同一个预览模板/路由
        with client.session_transaction() as sess:
            sess.clear()
            sess['is_teacher'] = True
            sess['teacher_id'] = tid
            sess['teacher_name'] = '__doc_prev_teacher__'
            sess['teacher_mode'] = 'edit'
            sess['csrf_token'] = 't'
        t_resp = client.get(f'/activity/document/{aid}/preview')
        assert t_resp.status_code == 200
        assert "'pptx'" in t_resp.get_data(as_text=True)
        # 教师学习活动列表的预览链接带 source=activities；预览页返回到学习活动
        act_list = client.get(f'/teacher/resources/{rid}/activities')
        assert act_list.status_code == 200
        assert 'source=activities' in act_list.get_data(as_text=True)
        t_back = client.get(
            f'/activity/document/{aid}/preview?source=activities')
        t_back_html = t_back.get_data(as_text=True)
        assert '返回学习活动' in t_back_html
        assert f'/resources/{rid}/activities' in t_back_html

        with client.session_transaction() as sess:
            sess.clear()
            sess['is_admin'] = True
            sess['admin_name'] = '__doc_prev_admin__'
            sess['csrf_token'] = 't'
        a_resp = client.get(f'/activity/document/{aid}/preview')
        assert a_resp.status_code == 200
        assert "'pptx'" in a_resp.get_data(as_text=True)
    finally:
        with app.app_context():
            if aid:
                LearningActivity.query.filter_by(id=aid).delete(synchronize_session=False)
            if rid:
                TeachingSession.query.filter_by(resource_id=rid).delete(
                    synchronize_session=False)
                Resource.query.filter_by(id=rid).delete(synchronize_session=False)
            if sid:
                Student.query.filter_by(id=sid).delete(synchronize_session=False)
            if tid:
                Teacher.query.filter_by(id=tid).delete(synchronize_session=False)
            if cls_id:
                ClassroomSession.query.filter_by(class_id=cls_id).delete(
                    synchronize_session=False)
                Class.query.filter_by(id=cls_id).delete(synchronize_session=False)
            db.session.commit()
        if tid:
            cache.delete(f'session:teacher:{tid}')
        if abs_path and abs_path.exists():
            abs_path.unlink()
            try:
                abs_path.parent.rmdir()
            except OSError:
                pass
