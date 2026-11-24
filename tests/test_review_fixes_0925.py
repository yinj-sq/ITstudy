# -*- coding: utf-8 -*-
"""2026-09-25 全面审查修复的回归用例（docs/全面审查报告-2026-09-25.md）。

数据一律用 rev0925 / REV0925 前缀命名，模块前后各清一次（DB 行 + 磁盘文件），
跑完仍须复跑 tools/review_db_residue_check.py。
"""
import io
import os
import shutil
import threading
from datetime import datetime
from types import SimpleNamespace

import pytest

from app import create_app
from app.extensions import cache, db
from app.models import (Class, ClassSchedule, Exam, LearningActivity, Log,
                        Resource, Result, Student, SystemConfig)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_UPLOADS = os.path.join(_ROOT, 'static', 'uploads')
_CSRF = 'rev0925-csrf-token'
CLASS_NAME = 'rev0925班A'
CLASS_RENAMED = 'rev0925班B'
STU_NUM = 'REV0925-1'
EXAM_NAME = 'rev0925卷'
RES_PREFIX = 'rev0925_'
_COURSEWARE_DIRS = ('rev0925_hidden', 'rev0925_visible', 'rev0925_renamed', 'rev0925_shared')


@pytest.fixture(scope='module')
def app():
    app = create_app()
    with app.app_context():
        _cleanup()
    yield app
    with app.app_context():
        _cleanup()


def _cleanup():
    db.session.rollback()
    res_ids = [r.id for r in Resource.query.filter(Resource.title.like('rev0925%')).all()]
    if res_ids:
        LearningActivity.query.filter(LearningActivity.resource_id.in_(res_ids)).delete(
            synchronize_session=False)
        Resource.query.filter(Resource.id.in_(res_ids)).delete(synchronize_session=False)
    stu_ids = [s.id for s in Student.query.filter(Student.student_number.like('REV0925%')).all()]
    exam_ids = [e.id for e in Exam.query.filter(Exam.name.like('rev0925%')).all()]
    if exam_ids:
        Result.query.filter(Result.exam_id.in_(exam_ids)).delete(synchronize_session=False)
        Exam.query.filter(Exam.id.in_(exam_ids)).delete(synchronize_session=False)
    if stu_ids:
        from app.models import AIChatMessage
        AIChatMessage.query.filter(AIChatMessage.student_id.in_(stu_ids)).delete(
            synchronize_session=False)
        Result.query.filter(Result.student_id.in_(stu_ids)).delete(synchronize_session=False)
        Student.query.filter(Student.id.in_(stu_ids)).delete(synchronize_session=False)
    from app.models import AIChatMessage as _AIM
    _AIM.query.filter(_AIM.content.like('%rev0925%')).delete(synchronize_session=False)
    Log.query.filter(Log.action == 'AI 页面限定').delete(synchronize_session=False)
    ClassSchedule.query.filter(ClassSchedule.class_name.like('rev0925%')).delete(
        synchronize_session=False)
    Class.query.filter(Class.name.like('rev0925%')).delete(synchronize_session=False)
    from app.models import Homework
    Homework.query.filter(Homework.title.like('rev0925%')).delete(synchronize_session=False)
    Log.query.filter(Log.detail.like('%rev0925%')).delete(synchronize_session=False)
    db.session.commit()
    for d in _COURSEWARE_DIRS:
        shutil.rmtree(os.path.join(_UPLOADS, d), ignore_errors=True)
    cache.delete('courseware:dir_map')


def _admin_client(app):
    client = app.test_client()
    with client.session_transaction() as s:
        s.clear()
        s['is_admin'] = True
        s['csrf_token'] = _CSRF
    return client


def _make_courseware(dir_name):
    os.makedirs(os.path.join(_UPLOADS, dir_name), exist_ok=True)
    with open(os.path.join(_UPLOADS, dir_name, 'index.html'), 'w', encoding='utf-8') as f:
        f.write('<p>rev0925</p>')


# ── Host 白名单：不得落入 Flask 3.1 原生 TRUSTED_HOSTS ──────────────

def test_host_allowlist_parse_strips_blanks():
    from app.config import _parse_host_allowlist
    assert _parse_host_allowlist('a.example, b.example ,,') == ['a.example', 'b.example']
    assert _parse_host_allowlist('') == []
    assert _parse_host_allowlist(None) == []


def test_flask_native_trusted_hosts_stays_disabled():
    from app.config import Config
    assert Config.TRUSTED_HOSTS is None


@pytest.fixture
def host_app(monkeypatch):
    from app import config as _config
    monkeypatch.setattr(_config.Config, 'HOST_ALLOWLIST',
                        _config._parse_host_allowlist('itstudy.example, ::1'))
    return create_app()


def test_healthz_exempt_from_host_allowlist(host_app):
    """容器 HEALTHCHECK 走 127.0.0.1：白名单不含它时 healthz 仍须 200。"""
    resp = host_app.test_client().get('/api/healthz', headers={'Host': '127.0.0.1:8000'})
    assert resp.status_code == 200


def test_untrusted_host_rejected(host_app):
    resp = host_app.test_client().get('/admin/login', headers={'Host': 'evil.example'})
    assert resp.status_code == 400


def test_trusted_host_with_port_and_second_entry_accepted(host_app):
    """第二个条目带前导空格也要命中；请求 Host 带端口时按主机名比较。"""
    client = host_app.test_client()
    assert client.get('/admin/login', headers={'Host': 'itstudy.example:8081'}).status_code == 200
    assert client.get('/admin/login', headers={'Host': '[::1]'}).status_code == 200
    assert client.get('/admin/login', headers={'Host': '[::1]:5000'}).status_code == 200


# ── 文件名/目录名清洗：不得产出 '.'/'..' 或点开头 ─────────────────────

def test_secure_filename_never_yields_dot_segments():
    from app.utils import secure_filename_with_unicode as f
    assert f('#.#.') == ''
    assert f('..') == ''
    assert f('!.htaccess') == 'htaccess'
    assert f('课件 一.pptx') == '课件_一.pptx'
    assert f('a/../b') == 'a_._b'


def test_resource_dir_name_rejects_reserved_and_empty():
    from app.blueprints.resources import _resource_dir_name
    for bad in ('drive', 'cloud_drive', 'Student_Works', 'activity_docs', '#.#.', ''):
        assert _resource_dir_name(bad) == '', bad
    assert _resource_dir_name('rev0925 课件') == 'rev0925_课件'


def test_resource_upload_rejects_escaping_title(app):
    client = _admin_client(app)
    for title in ('#.#.', 'drive'):
        resp = client.post('/admin/resources/upload', data={
            'title': title, 'csrf_token': _CSRF,
            'files': (io.BytesIO(b'x'), 'rev0925.txt'),
        }, content_type='multipart/form-data')
        assert resp.status_code == 400, title
    assert not os.path.exists(os.path.join(_ROOT, 'static', 'rev0925.txt'))


# ── 课件目录可见性守卫 ──────────────────────────────────────────

@pytest.fixture
def courseware_public(app):
    with app.app_context():
        old = SystemConfig.get('courseware_public_enabled', 'true')
        SystemConfig.set('courseware_public_enabled', 'true')
        db.session.commit()
    yield
    with app.app_context():
        SystemConfig.set('courseware_public_enabled', old)
        db.session.commit()


def _add_resource(app, title, dir_name, show, perms):
    with app.app_context():
        r = Resource(title=title, url=f'/static/uploads/{dir_name}/index.html',
                     show_in_student=show, file_permissions=perms)
        db.session.add(r)
        db.session.commit()
        cache.delete('courseware:dir_map')
        return r.id


def test_hidden_courseware_denied_even_with_saved_permissions(app, courseware_public):
    """元组解包错位时，file_permissions='{}'（真值）被当成 show → 隐藏资源可直链。"""
    _make_courseware('rev0925_hidden')
    _add_resource(app, 'rev0925_hidden', 'rev0925_hidden', False, '{}')
    resp = app.test_client().get('/static/uploads/rev0925_hidden/index.html')
    assert resp.status_code == 403


def test_visible_courseware_without_permissions_allowed(app, courseware_public):
    """反向：可见资源 file_permissions 为空时此前被误拒。"""
    _make_courseware('rev0925_visible')
    _add_resource(app, 'rev0925_visible', 'rev0925_visible', True, None)
    resp = app.test_client().get('/static/uploads/rev0925_visible/index.html')
    assert resp.status_code == 200


def test_renamed_hidden_courseware_still_denied(app, courseware_public):
    """改标题不改目录：映射只按新标题建键时旧目录落入"未知目录 → 公开"。"""
    _make_courseware('rev0925_renamed')
    _add_resource(app, 'rev0925 改名后的标题', 'rev0925_renamed', False, None)
    resp = app.test_client().get('/static/uploads/rev0925_renamed/index.html')
    assert resp.status_code == 403


# ── 删除资源：活动文档目录按资源 id；共用目录不整删 ─────────────────

def test_delete_resource_removes_own_activity_docs_only(app):
    docs_root = os.path.join(_UPLOADS, 'activity_docs')
    with app.app_context():
        r = Resource(title='rev0925_actres')
        db.session.add(r)
        db.session.flush()
        acts = []
        for i in range(3):
            a = LearningActivity(resource_id=r.id, title=f'rev0925活动{i}')
            db.session.add(a)
            db.session.flush()
            acts.append(a.id)
        db.session.commit()
        rid = r.id
    aid = next(a for a in acts if a != rid)
    own_dir = os.path.join(docs_root, str(rid))
    other_dir = os.path.join(docs_root, str(aid))   # 模拟"id 恰等于该活动 id 的另一资源"
    os.makedirs(own_dir, exist_ok=True)
    os.makedirs(other_dir, exist_ok=True)
    keep = os.path.join(other_dir, 'rev0925_keep.txt')
    with open(os.path.join(own_dir, 'rev0925_doc.txt'), 'w') as f:
        f.write('own')
    with open(keep, 'w') as f:
        f.write('other')
    try:
        resp = _admin_client(app).post(f'/admin/resources/delete/{rid}',
                                       data={'csrf_token': _CSRF})
        assert resp.status_code == 302
        assert not os.path.exists(own_dir), '本资源活动文档目录应被清理'
        assert os.path.exists(keep), '不得删掉 id 恰等于活动 id 的其它资源的文档'
    finally:
        if os.path.exists(keep):
            os.remove(keep)
        try:
            os.rmdir(other_dir)
        except OSError:
            pass


def test_delete_resource_keeps_shared_directory(app):
    _make_courseware('rev0925_shared')
    r1 = _add_resource(app, 'rev0925_shared', 'rev0925_shared', True, None)
    r2 = _add_resource(app, 'rev0925_shared', 'rev0925_shared', True, None)
    client = _admin_client(app)
    client.post(f'/admin/resources/delete/{r1}', data={'csrf_token': _CSRF})
    assert os.path.isdir(os.path.join(_UPLOADS, 'rev0925_shared')), '另一资源仍引用该目录'
    client.post(f'/admin/resources/delete/{r2}', data={'csrf_token': _CSRF})
    assert not os.path.exists(os.path.join(_UPLOADS, 'rev0925_shared'))


# ── compare_digest 非 ASCII 输入不得 500 ──────────────────────────

def test_non_ascii_csrf_header_is_403_not_500(app):
    resp = app.test_client().post('/admin/login', headers={'X-CSRFToken': 'é'})
    assert resp.status_code == 403


def test_admin_login_with_chinese_username_not_500(app):
    client = app.test_client()
    with client.session_transaction() as s:
        s['csrf_token'] = _CSRF
    resp = client.post('/admin/login', data={
        'username': '管理员rev0925', 'password': 'x', 'csrf_token': _CSRF})
    assert resp.status_code in (200, 302, 429)


# ── 凭据解密：缓存派生密钥 / 解密失败降级 ───────────────────────────

def test_derive_key_is_cached():
    from app.credential_crypto import _derive_key
    assert _derive_key('rev0925-secret') is _derive_key('rev0925-secret')


def test_undecryptable_api_key_degrades_to_empty():
    from app.models import AIConfig
    cfg = AIConfig()
    cfg._api_key = 'enc:v1:not-a-valid-token'
    assert cfg.api_key == ''


def test_stream_slot_released_when_context_prep_raises(app, monkeypatch):
    from app.blueprints import ai as ai_mod

    def boom():
        raise RuntimeError('rev0925 prep failure')
    monkeypatch.setattr(ai_mod, '_prepare_chat_context', boom)
    client = _admin_client(app)
    resp = client.post('/api/ai/chat/stream', json={'message': 'hi'},
                       headers={'X-CSRFToken': _CSRF})
    assert resp.status_code == 500
    assert ai_mod._stream_count.get('admin', 0) == 0, '异常路径必须归还并发名额'


# ── 主动内容：按 MIME 兜底 ───────────────────────────────────────

def test_active_mimetype_detection():
    from app.utils import is_active_mimetype, safe_inline_mimetype
    assert is_active_mimetype('text/xml')
    assert is_active_mimetype('application/xslt+xml; charset=utf-8')
    assert is_active_mimetype('image/svg+xml')
    assert not is_active_mimetype(
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    assert not is_active_mimetype('application/pdf')
    assert safe_inline_mimetype('evil.xsl') == 'text/plain; charset=utf-8'
    assert safe_inline_mimetype('ok.pdf') is None


# ── 作业附件：重交允许覆盖同名 ─────────────────────────────────────

def test_homework_attachment_overwrite_flag(tmp_path):
    from werkzeug.datastructures import FileStorage
    from app.blueprints.homework import _save_homework_attachment
    (tmp_path / 'a.txt').write_bytes(b'old')
    ok, _, _ = _save_homework_attachment(
        FileStorage(io.BytesIO(b'new'), filename='a.txt'), str(tmp_path), 1)
    assert not ok, '默认仍拒绝同名'
    ok, _, fname = _save_homework_attachment(
        FileStorage(io.BytesIO(b'new'), filename='a.txt'), str(tmp_path), 1, overwrite=True)
    assert ok and fname == 'a.txt'
    assert (tmp_path / 'a.txt').read_bytes() == b'new'


# ── 判分 ─────────────────────────────────────────────────────────

def test_blank_score_map_requires_sum_to_match_score():
    from app.services.scoring_service import _blank_score_map
    q = SimpleNamespace(score=10.0, blank_scores_list=[3, 3, 4])
    assert _blank_score_map(q, ['1', '2', '3']) == {'1': 3, '2': 3, '3': 4}
    q.score = 20.0   # 编辑改了总分，blank_scores 未同步
    assert _blank_score_map(q, ['1', '2', '3']) == {}
    q.score = 10.0   # 改成 2 空：前两空之和 6 ≠ 10
    assert _blank_score_map(q, ['1', '2']) == {}
    assert _blank_score_map(SimpleNamespace(score=5, blank_scores_list=None), ['1']) == {}


def test_python_file_circled_marker_not_hijacked_by_list_index(app):
    from app.services.scoring_service import score_python_file
    ref = 'a = [1, 2]\nn = ①\nprint(a[1])\n'
    stu = 'a = [1, 2]\nn = 5\nprint(a[1])\n'
    q = SimpleNamespace(id=0, score=10.0, question_type='python_fill',
                        python_answers_dict={'1': '5'}, blank_scores_list=None)
    pf = SimpleNamespace(file_name='ref.py', read_content=lambda folder: ref)
    with app.app_context():
        assert score_python_file(q, stu, pf) == 10.0


def test_python_reference_file_gbk_decoded(app):
    from app.models import PythonFile
    rel = 'rev0925_gbk_ref.py'
    path = os.path.join(_UPLOADS, rel)
    with open(path, 'wb') as f:
        f.write('# 中文注释\nx = ①\n'.encode('gbk'))
    try:
        with app.app_context():
            pf = PythonFile(question_id=0, file_name=rel, file_path=rel)
            content = pf.read_content(app.config['UPLOAD_FOLDER'])
        assert '中文注释' in content and 'x = ①' in content
    finally:
        os.remove(path)


def test_short_answer_non_string_does_not_raise():
    from app.services.scoring_service import auto_score
    q = SimpleNamespace(question_type='short_answer', answer='', score=5)
    assert auto_score(q, 1) is None
    assert auto_score(q, '   ') == 0


# ── 未公布成绩：学生考试页不显示分数 ────────────────────────────────

def _make_student(app, class_name=CLASS_NAME, number=STU_NUM):
    with app.app_context():
        cls = Class.query.filter_by(name=class_name).first()
        if not cls:
            cls = Class(name=class_name)
            db.session.add(cls)
            db.session.flush()
        stu = Student.query.filter_by(student_number=number).first()
        if not stu:
            stu = Student(name='rev0925学生', student_number=number, class_id=cls.id,
                          student_class=class_name, is_activated=True,
                          has_changed_password=True)
            stu.set_password('Old12345')
            db.session.add(stu)
        db.session.commit()
        return stu.id, cls.id


def _student_client(app, sid, monkeypatch):
    from app.blueprints import auth as auth_mod
    monkeypatch.setattr(auth_mod, '_get_active_class_id', lambda: None)
    client = app.test_client()
    with app.app_context():
        from app.utils import password_fingerprint
        fp = password_fingerprint(db.session.get(Student, sid).password_hash)
    with client.session_transaction() as s:
        s.clear()
        s['student_id'] = sid
        s['csrf_token'] = _CSRF
        s['pwd_fp'] = fp
    return client


def test_unpublished_score_hidden_on_exam_page(app, monkeypatch):
    sid, _ = _make_student(app)
    with app.app_context():
        ex = Exam(name=EXAM_NAME, is_active=False, allow_view_results=False)
        db.session.add(ex)
        db.session.flush()
        db.session.add(Result(student_id=sid, exam_id=ex.id, total_score=87.5,
                              answers='{}', scores='{}', submit_time=datetime.now()))
        db.session.commit()
        eid = ex.id
    client = _student_client(app, sid, monkeypatch)
    body = client.get('/exam').get_data(as_text=True)
    assert '87.5' not in body and '未公布' in body
    with app.app_context():
        db.session.get(Exam, eid).allow_view_results = True
        db.session.commit()
    body = client.get('/exam').get_data(as_text=True)
    assert '87.5' in body, '已结束（不在开放列表）但已公布的卷仍应显示分数'


# ── 会话随改密失效 ───────────────────────────────────────────────

def test_old_session_invalidated_after_password_change(app, monkeypatch):
    sid, _ = _make_student(app)
    client = _student_client(app, sid, monkeypatch)
    legacy = app.test_client()      # 升级前签发、不带指纹的旧会话
    with legacy.session_transaction() as s:
        s['student_id'] = sid
    cache.delete(f'session:check:{sid}')
    assert client.get('/student/homework').status_code == 200
    assert legacy.get('/student/homework').status_code == 200, '旧会话首访补写指纹'

    with app.app_context():
        stu = db.session.get(Student, sid)
        stu.set_password('New12345')      # 管理员重置 / 本人在别处改密
        db.session.commit()
    cache.delete(f'session:check:{sid}')
    assert client.get('/student/homework').status_code == 302
    assert legacy.get('/student/homework').status_code == 302


def test_self_password_change_keeps_own_session(app, monkeypatch):
    sid, _ = _make_student(app)
    with app.app_context():
        stu = db.session.get(Student, sid)
        stu.set_password('Old12345')
        db.session.commit()
    cache.delete(f'session:check:{sid}')
    client = _student_client(app, sid, monkeypatch)
    resp = client.post('/change-password', data={
        'old_password': 'Old12345', 'new_password': 'Mine12345',
        'confirm_password': 'Mine12345', 'csrf_token': _CSRF})
    assert resp.status_code == 302
    assert client.get('/student/homework').status_code == 200


# ── 班级改名同步课表 ─────────────────────────────────────────────

def test_class_rename_propagates_to_schedule(app):
    sid, cid = _make_student(app)
    with app.app_context():
        db.session.add(ClassSchedule(weekday=7, period_number=97, class_name=CLASS_NAME))
        db.session.commit()
    resp = _admin_client(app).post(f'/admin/classes/{cid}/edit', data={
        'name': CLASS_RENAMED, 'description': '', 'csrf_token': _CSRF})
    assert resp.status_code == 302
    with app.app_context():
        assert ClassSchedule.query.filter_by(weekday=7, period_number=97).first().class_name \
            == CLASS_RENAMED
        assert db.session.get(Student, sid).student_class == CLASS_RENAMED
        # 还原，供其它用例继续按原名取班级
        db.session.get(Class, cid).name = CLASS_NAME
        db.session.commit()


# ── 输入校验不得 500 ─────────────────────────────────────────────

def test_schedule_import_rejects_xls_and_corrupt_files(app):
    client = _admin_client(app)
    for name, payload in (('rev0925.xls', b'\xd0\xcf\x11\xe0'), ('rev0925.xlsx', b'not a zip')):
        resp = client.post('/admin/class_schedule/import', data={
            'csrf_token': _CSRF, 'excel_file': (io.BytesIO(payload), name),
        }, content_type='multipart/form-data')
        assert resp.status_code == 302, name


def test_classroom_settings_nonexistent_class_not_500(app):
    resp = _admin_client(app).post('/admin/classroom/settings', data={
        'csrf_token': _CSRF, 'active_class_id': '987654321'})
    assert resp.status_code == 302


def test_python_log_clear_keeps_other_lines(app, tmp_path, monkeypatch):
    from app.blueprints import logs as logs_mod
    log = tmp_path / 'app.log'
    log.write_text('2026-09-25 [INFO] Python填空题 ID:1 评分完成\n'
                   '2026-09-25 [WARNING] 登录失败 rev0925\n', encoding='utf-8')
    monkeypatch.setattr(logs_mod, '_log_dir', lambda: str(tmp_path))
    resp = _admin_client(app).post('/admin/python_logs/clear', data={'csrf_token': _CSRF})
    assert resp.status_code == 302
    text = log.read_text(encoding='utf-8')
    assert 'Python填空题' not in text and '登录失败 rev0925' in text


# ── 静态资源预压缩副本必须与源文件一致 ──────────────────────────────

def test_all_precompressed_gz_match_sources():
    """nginx gzip_static 只要 .gz 存在就直接下发：改了源文件没重建 .gz，
    浏览器拿到的就是旧脚本（本轮实测 5 个陈旧，含 PPTist 入口页）。
    修复后改静态资源须跑 tools/precompress_static.py --refresh-only。"""
    import gzip
    import pathlib
    stale = []
    static_dir = pathlib.Path(_ROOT, 'static')
    for gz in static_dir.rglob('*.gz'):
        if gz.relative_to(static_dir).parts[0] in ('uploads', 'chunks'):
            continue   # 用户上传内容，不是版本化静态资源
        src = pathlib.Path(str(gz)[:-3])
        if not src.exists() or gzip.decompress(gz.read_bytes()) != src.read_bytes():
            stale.append(str(gz.relative_to(_ROOT)))
    assert not stale, f'陈旧的预压缩副本（请运行 precompress_static.py --refresh-only）: {stale}'


# ── 性能优化轮（同日续做）─────────────────────────────────────────

def test_send_temp_zip_streams_from_disk_and_cleans_up(app, tmp_path):
    """必须模拟**真实 WSGI 服务器**的发送路径：服务器用 environ['wsgi.file_wrapper']
    包装文件、发送完只关闭它交出的 app_iter，不会调用 Flask Response.close()。
    早先版本靠 response.call_on_close 删文件——测试客户端下是绿的，Waitress 下
    回调从不执行、每次下载都在临时目录留一份 zip（真实起服实测）。"""
    import zipfile
    from werkzeug.test import EnvironBuilder
    from werkzeug.wsgi import FileWrapper
    from app.utils import send_temp_zip

    wrapped = []

    class ServerFileWrapper(FileWrapper):   # 代表 Waitress 的 ReadOnlyFileBasedBuffer
        def __init__(self, f, *a):
            super().__init__(f, *a)
            wrapped.append(f)

    environ = EnvironBuilder(path='/').get_environ()
    environ['wsgi.file_wrapper'] = ServerFileWrapper
    with app.request_context(environ):
        resp = send_temp_zip(lambda zf: zf.writestr('a.txt', 'rev0925'), 'rev0925.zip')
    assert resp.mimetype == 'application/zip'
    assert 'rev0925.zip' in resp.headers['Content-Disposition']
    assert resp.content_length and resp.headers.get('Accept-Ranges') == 'bytes'
    app_iter = resp.get_app_iter(environ)
    tmp_file = wrapped[0].name
    assert os.path.exists(tmp_file), 'zip 应写在磁盘临时文件上，而非内存'
    body = b''.join(app_iter)
    app_iter.close()                          # 服务器只做这一步
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        assert zf.read('a.txt') == b'rev0925'
    assert not os.path.exists(tmp_file), '服务器关闭 app_iter 后临时 zip 必须删除'


def test_send_temp_zip_supports_range(app):
    from werkzeug.test import EnvironBuilder
    from app.utils import send_temp_zip
    environ = EnvironBuilder(path='/', headers={'Range': 'bytes=0-9'}).get_environ()
    with app.request_context(environ):
        resp = send_temp_zip(lambda zf: zf.writestr('a.txt', 'x' * 500), 'r.zip')
    try:
        assert resp.status_code == 206 and resp.content_length == 10
    finally:
        resp.close()


def test_send_temp_zip_removes_file_when_build_fails(app, monkeypatch):
    import tempfile
    from app.utils import send_temp_zip
    made = []
    real = tempfile.mkstemp

    def spy(*a, **k):
        fd, p = real(*a, **k)
        made.append(p)
        return fd, p
    monkeypatch.setattr(tempfile, 'mkstemp', spy)

    def boom(zf):
        raise RuntimeError('rev0925 build failure')
    with app.test_request_context(), pytest.raises(RuntimeError):
        send_temp_zip(boom, 'x.zip')
    assert made and not os.path.exists(made[0])


def test_no_legacy_query_get_in_app():
    """Query.get() 是 SQLAlchemy 2.x 遗留 API（测试期 90 条告警），统一用
    db.session.get / db.get_or_404。"""
    import pathlib
    import re
    hits = [f'{p.relative_to(_ROOT)}:{i}'
            for p in pathlib.Path(_ROOT, 'app').rglob('*.py')
            for i, line in enumerate(p.read_text(encoding='utf-8').splitlines(), 1)
            if re.search(r'\.query\.get(_or_404)?\(', line)]
    assert not hits, hits


def test_constraints_match_offline_wheels():
    """容器通道（constraints.txt）与 NSIS 离线通道（pack/wheels）版本一致。"""
    import pathlib
    import re
    wheels = pathlib.Path(_ROOT, 'pack', 'wheels')
    if not wheels.is_dir():
        pytest.skip('pack/wheels 为构建产物，不在仓库中')
    norm = lambda s: re.sub(r'[-_.]+', '-', s).lower()  # noqa: E731
    from_wheels = {}
    for w in wheels.glob('*.whl'):
        name, ver = w.name.split('-')[:2]
        from_wheels[norm(name)] = ver
    pinned = {}
    for line in pathlib.Path(_ROOT, 'constraints.txt').read_text(encoding='utf-8').splitlines():
        line = line.split(';')[0].strip()
        if line and not line.startswith('#'):
            name, ver = line.split('==')
            pinned[norm(name)] = ver.strip()
    assert pinned == from_wheels


# ── 待批改成绩同样受「公布成绩」开关约束（2026-09-27 产品确认）───────────

def test_pending_result_hidden_until_published(app, monkeypatch):
    sid, _ = _make_student(app)
    with app.app_context():
        ex = Exam(name=EXAM_NAME + '待批', is_active=False, allow_view_results=False)
        db.session.add(ex)
        db.session.flush()
        r = Result(student_id=sid, exam_id=ex.id, total_score=5, answers='{}', scores='{}',
                   grading_status='pending_review', submit_time=datetime.now())
        db.session.add(r)
        db.session.commit()
        eid, rid = ex.id, r.id
    client = _student_client(app, sid, monkeypatch)
    assert client.get(f'/result/{rid}').status_code == 302, 'SSR 结果页：待批改也不得查看'
    assert client.get(f'/api/results/{rid}').status_code == 403, 'SPA 接口同口径'
    with app.app_context():
        db.session.get(Exam, eid).allow_view_results = True
        db.session.commit()
    assert client.get(f'/result/{rid}').status_code == 200
    assert client.get(f'/api/results/{rid}').status_code == 200


# ── 教师可限定学生 AI 仅围绕当前页面内容 ─────────────────────────────

@pytest.fixture
def ai_env(app, monkeypatch):
    """启用 admin 模式 AI 配置 + 截获上游调用（不发真实请求），结束后还原。"""
    from app.blueprints import ai as ai_mod
    from app.models import AIConfig
    from app.blueprints.ai import STUDENT_PAGE_ONLY_KEY
    with app.app_context():
        cfg = AIConfig.query.first()
        created = cfg is None
        if created:
            cfg = AIConfig()
            db.session.add(cfg)
        saved = dict(enabled=cfg.enabled, config_mode=cfg.config_mode,
                     api_url=cfg.api_url, model=cfg.model, raw_key=cfg._api_key)
        cfg.enabled, cfg.config_mode = True, 'admin'
        cfg.api_url, cfg.model = 'https://api.example.com/v1', 'rev0925-model'
        cfg.api_key = 'sk-rev0925'
        old_flag = SystemConfig.get(STUDENT_PAGE_ONLY_KEY, '0')
        db.session.commit()
    captured = []

    def fake_call(provider, api_key, api_url, model, messages, *a, **k):
        captured.append(messages)
        return True, 'rev0925 回复', 200, 'stop', None
    monkeypatch.setattr(ai_mod, '_call_chat', fake_call)
    ai_mod._call_deque.clear()
    yield captured
    with app.app_context():
        cfg = AIConfig.query.first()
        if created:
            db.session.delete(cfg)
        else:
            cfg.enabled, cfg.config_mode = saved['enabled'], saved['config_mode']
            cfg.api_url, cfg.model, cfg._api_key = saved['api_url'], saved['model'], saved['raw_key']
        SystemConfig.set(STUDENT_PAGE_ONLY_KEY, old_flag)
        db.session.commit()
        SystemConfig._invalidate_cache()


def _teacher_client(app):
    client = _admin_client(app)
    with client.session_transaction() as s:
        s.pop('is_admin', None)
        s['is_teacher'] = True
        s['teacher_id'] = 0
    return client


def _set_page_only(client, enabled):
    return client.post('/teacher/ai/page-only', json={'enabled': enabled},
                       headers={'X-CSRFToken': _CSRF})


def test_page_only_toggle_permissions(app, ai_env, monkeypatch):
    sid, _ = _make_student(app)
    student = _student_client(app, sid, monkeypatch)
    resp = student.post('/teacher/ai/page-only', json={'enabled': True},
                        headers={'X-CSRFToken': _CSRF})
    assert resp.status_code in (302, 403), '学生不得切换'
    teacher = _teacher_client(app)
    assert teacher.post('/teacher/ai/page-only', json={'enabled': 'yes'},
                        headers={'X-CSRFToken': _CSRF}).status_code == 400
    assert _set_page_only(teacher, True).get_json()['enabled'] is True
    assert teacher.get('/teacher/ai/page-only').get_json()['enabled'] is True
    status = teacher.get('/api/ai/status').get_json()
    assert status['can_control_page_only'] and status['student_page_only']
    assert status['page_only_enforced'] is False, '教师自身不受限'
    st = student.get('/api/ai/status').get_json()
    assert st['page_only_enforced'] is True and st['can_control_page_only'] is False
    assert _set_page_only(_admin_client(app), False).get_json()['enabled'] is False


def test_page_only_forces_page_context_for_students(app, ai_env, monkeypatch):
    captured = ai_env
    sid, _ = _make_student(app)
    student = _student_client(app, sid, monkeypatch)
    _set_page_only(_teacher_client(app), True)

    # 无页面内容 → 拒绝（否则等于自由对话）
    resp = student.post('/api/ai/chat', json={
        'message': 'rev0925 讲个笑话', 'use_page_context': False, 'page_content': ''},
        headers={'X-CSRFToken': _CSRF})
    assert resp.status_code == 400 and resp.get_json()['code'] == 'page_only_no_content'
    assert not captured, '被拒请求不得调用上游'

    # 客户端声称 use_page_context=false 也无效：服务端强制带上本页内容 + 限定提示
    resp = student.post('/api/ai/chat', json={
        'message': 'rev0925 这是什么', 'use_page_context': False,
        'page_content': 'rev0925 本页讲 for 循环'}, headers={'X-CSRFToken': _CSRF})
    body = resp.get_json()
    assert resp.status_code == 200 and body['page_only'] is True
    system = captured[-1][0]['content']
    assert '老师已限定' in system and 'rev0925 本页讲 for 循环' in system

    # 关闭后恢复学生自主选择
    _set_page_only(_teacher_client(app), False)
    resp = student.post('/api/ai/chat', json={
        'message': 'rev0925 自由问题', 'use_page_context': False,
        'page_content': 'rev0925 本页讲 for 循环'}, headers={'X-CSRFToken': _CSRF})
    assert resp.status_code == 200 and resp.get_json()['page_only'] is False
    system = captured[-1][0]['content']
    assert '老师已限定' not in system and 'rev0925 本页讲 for 循环' not in system


def test_page_only_does_not_restrict_teachers(app, ai_env):
    captured = ai_env
    _set_page_only(_teacher_client(app), True)
    resp = _admin_client(app).post('/api/ai/chat', json={
        'message': 'rev0925 备课提问', 'use_page_context': False, 'page_content': ''},
        headers={'X-CSRFToken': _CSRF})
    assert resp.status_code == 200 and resp.get_json()['page_only'] is False
    assert '老师已限定' not in captured[-1][0]['content']


# ── 作业投递：进行中再次触发 → 本轮结束后补跑 ────────────────────────

def test_delivery_retrigger_while_running_is_rerun(app, monkeypatch):
    from app.models import Homework
    from app.services import delivery_worker, student_drive_service
    with app.app_context():
        hw = Homework(title='rev0925作业')
        db.session.add(hw)
        db.session.commit()
        hw_id = hw.id
    gate = threading.Event()
    calls = []

    def fake_deliver(homework, hw_dir, sender_name='', progress=None):
        calls.append(hw_dir)
        if len(calls) == 1:
            gate.wait(5)
        return {'total': 0, 'delivered': 0, 'insufficient': [], 'failed': []}
    monkeypatch.setattr(student_drive_service, 'deliver_homework_attachments', fake_deliver)
    delivery_worker.start_homework_delivery(app, hw_id, 'dir-1')
    for _ in range(50):
        if calls:
            break
        threading.Event().wait(0.05)
    delivery_worker.start_homework_delivery(app, hw_id, 'dir-2')
    gate.set()
    for _ in range(100):
        if len(calls) >= 2:
            break
        threading.Event().wait(0.05)
    assert calls == ['dir-1', 'dir-2']
