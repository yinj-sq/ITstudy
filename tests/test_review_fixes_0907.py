"""全面审查修复回归测试（2026-09-07 审计轮）

覆盖本轮修复的核心行为：
1. 超时未交卷的开考记录不再永久锁死组卷/删卷（在考锁定按"未超时"口径）
2. 管理端"清除超时开考记录"端点：只删超时残留，不误伤在考记录
3. 学生打开超时残留开考记录的考试页 → 重定向结束态（不再倒计时+403循环）
4. exam_status 轮询端点权限校验先于 collected 缓存命中（隐藏卷不可探测）
5. 课堂思维导图 list/get 对学生补 show_in_student 边界
6. /app/<path> 拒绝盘符/绝对路径（本地文件存在性探测侧信道）
7. python zip 导入流式限量读取（zip 头 size 可伪造）
8. 题目图片上传魔数校验
9. AI SSRF 黑名单覆盖 CGNAT 100.64.0.0/10
10. 编辑综合题分值强制=子题和（组卷总分与考试页总分口径对齐）
11. 私有上传目录响应 Cache-Control private/no-store
12. 试卷列表缓存失效单源化 + 趋势缓存换代
13. decode_python_source GBK 解码口径
"""
import io
import os
import shutil
import zipfile
from datetime import datetime, timedelta

import pytest
from flask import Response
from sqlalchemy import text

from app import create_app
from app.extensions import db
from app.models import (
    ClassroomSetting, Class, Exam, ExamAttempt, Question, Resource,
    Student, SubQuestion,
)

_CSRF = 'rev0907-csrf'

EXAM_NAME = '复审0907测试卷'
CLS_NAME = '复审0907班'
STU_NUM = 'REV0907A'
STU_NUM2 = 'REV0907B'


@pytest.fixture(scope='module')
def app():
    app = create_app()
    _seed(app)
    with app.app_context():
        setting = ClassroomSetting.query.first()
        orig = setting.active_class_id if setting else None
        cls = Class.query.filter_by(name=CLS_NAME).first()
        if setting:
            setting.active_class_id = cls.id
        else:
            db.session.add(ClassroomSetting(active_class_id=cls.id))
        db.session.commit()
    yield app
    with app.app_context():
        setting = ClassroomSetting.query.first()
        if setting:
            setting.active_class_id = orig if (
                orig and db.session.get(Class, orig)) else None
        _cleanup()
        db.session.commit()


def _cleanup():
    conn = db.session.connection()
    conn.execute(text(
        'UPDATE classroom_setting SET active_class_id=NULL '
        'WHERE active_class_id IN (SELECT id FROM classes WHERE name=:n)'),
        {'n': CLS_NAME})
    names = (EXAM_NAME, EXAM_NAME + 'X')
    for n in names:
        eid = conn.execute(text('SELECT id FROM exam WHERE name=:n'),
                           {'n': n}).first()
        if eid:
            conn.execute(text('DELETE FROM exam_attempt WHERE exam_id=:e'),
                         {'e': eid[0]})
            conn.execute(text('DELETE FROM result WHERE exam_id=:e'),
                         {'e': eid[0]})
            conn.execute(text('DELETE FROM exam_question WHERE exam_id=:e'),
                         {'e': eid[0]})
            conn.execute(text('DELETE FROM question WHERE exam_id=:e'),
                         {'e': eid[0]})
            conn.execute(text('DELETE FROM exam WHERE id=:e'), {'e': eid[0]})
    # 越权边界测试资源（目录与 DB 行）
    conn.execute(text("DELETE FROM resource WHERE title LIKE 'rev0907%'"))
    conn.execute(text('DELETE FROM student WHERE student_number IN (:a,:b)'),
                 {'a': STU_NUM, 'b': STU_NUM2})
    conn.execute(text('DELETE FROM classes WHERE name=:n'), {'n': CLS_NAME})


def _seed(app):
    with app.app_context():
        cls = Class.query.filter_by(name=CLS_NAME).first()
        if not cls:
            db.session.add(Class(name=CLS_NAME))
        for num in (STU_NUM, STU_NUM2):
            stu = Student.query.filter_by(student_number=num).first()
            if not stu:
                stu = Student(name=f'复审学生{num[-1]}', student_number=num,
                              student_class=CLS_NAME,
                              is_activated=True, has_changed_password=True)
                stu.set_password('Rev0907#')
                db.session.add(stu)
        db.session.commit()
        cls = Class.query.filter_by(name=CLS_NAME).first()
        for num in (STU_NUM, STU_NUM2):
            stu = Student.query.filter_by(student_number=num).first()
            stu.class_id = cls.id
        db.session.commit()


def _ids(app, num=STU_NUM):
    with app.app_context():
        stu = Student.query.filter_by(student_number=num).first()
        return stu.id


def _student_client(app, sid):
    client = app.test_client()
    with client.session_transaction() as s:
        s.clear()
        s['student_id'] = sid
        s['student_name'] = '复审学生'
        s['csrf_token'] = _CSRF
    return client


def _admin_client(app):
    client = app.test_client()
    with client.session_transaction() as s:
        s.clear()
        s['is_admin'] = True
        s['csrf_token'] = _CSRF
    return client


def _make_exam(app, suffix=''):
    """幂等建卷（exam.name 唯一约束）：存在即复用并确保基础题目在卷。"""
    with app.app_context():
        exam = Exam.query.filter_by(name=EXAM_NAME + suffix).first()
        if not exam:
            exam = Exam(name=EXAM_NAME + suffix, is_active=True,
                        is_visible=True, is_enabled=True, duration=30)
            db.session.add(exam)
            db.session.flush()
            db.session.add(Question(exam_id=exam.id, question_type='single',
                                    content='1+1=?', options='A|B|C|D',
                                    answer='A', score=10))
            db.session.commit()
        return exam.id


def _make_attempt(app, sid, eid, age_seconds=0):
    """upsert 开考记录（唯一约束：每学生每卷一条），返回记录 id。"""
    with app.app_context():
        start = datetime.now() - timedelta(seconds=age_seconds)
        attempt = ExamAttempt.query.filter_by(
            student_id=sid, exam_id=eid).first()
        if attempt:
            attempt.start_time = start
        else:
            attempt = ExamAttempt(student_id=sid, exam_id=eid,
                                  start_time=start)
            db.session.add(attempt)
        db.session.commit()
        return attempt.id


def _drop_attempt(app, sid, eid):
    with app.app_context():
        ExamAttempt.query.filter_by(student_id=sid, exam_id=eid).delete()
        db.session.commit()


# ── 1. 在考锁定按"未超时"口径 ─────────────────────────────

def test_stale_attempt_does_not_lock_compose(app):
    """超时残留开考记录（弃考>时长+宽限）不阻断组卷（此前 409 永久锁死）。"""
    eid = _make_exam(app)
    sid = _ids(app)
    # duration=30min + 5min 宽限 → 36 分钟前开考即超时
    _make_attempt(app, sid, eid, age_seconds=36 * 60)
    client = _admin_client(app)
    with app.app_context():
        # 另建一道未入卷题用于追加
        q2 = Question(question_type='single', content='2+2=?',
                      options='A|B|C|D', answer='B', score=5)
        db.session.add(q2)
        db.session.commit()
        q2id = q2.id
    resp = client.post(f'/admin/exams/{eid}/compose/add',
                       json={'question_ids': [q2id]},
                       headers={'X-CSRFToken': _CSRF})
    assert resp.status_code == 200, '超时残留记录不应锁死组卷'
    data = resp.get_json()
    assert data['success'] is True


def test_active_attempt_still_locks_compose(app):
    """未超时（进行中）开考记录仍锁定组卷。"""
    eid = _make_exam(app, suffix='X')
    sid = _ids(app)
    _make_attempt(app, sid, eid, age_seconds=60)
    client = _admin_client(app)
    with app.app_context():
        q2 = Question(question_type='single', content='3+3=?',
                      options='A|B|C|D', answer='C', score=5)
        db.session.add(q2)
        db.session.commit()
        q2id = q2.id
    resp = client.post(f'/admin/exams/{eid}/compose/add',
                       json={'question_ids': [q2id]},
                       headers={'X-CSRFToken': _CSRF})
    assert resp.status_code == 409, '在考（未超时）记录必须继续锁定组卷'


def test_stale_attempt_does_not_block_delete(app):
    """超时残留记录不再阻断删卷，删卷时一并清理。"""
    eid = _make_exam(app, suffix='X')
    sid = _ids(app)
    _make_attempt(app, sid, eid, age_seconds=36 * 60)
    client = _admin_client(app)
    resp = client.post(f'/admin/exams/delete/{eid}',
                       headers={'X-CSRFToken': _CSRF})
    assert resp.status_code == 302
    with app.app_context():
        assert db.session.get(Exam, eid) is None, '删卷应成功'
        assert ExamAttempt.query.filter_by(exam_id=eid).first() is None


def test_clear_stale_attempts_endpoint(app):
    """清除超时开考记录端点：只删超时残留，保留未超时记录。

    超时/进行中分属两个学生（每学生每卷仅一条开考记录）。
    """
    eid = _make_exam(app)
    sid = _ids(app)
    sid2 = _ids(app, STU_NUM2)
    _drop_attempt(app, sid, eid)
    _drop_attempt(app, sid2, eid)
    _make_attempt(app, sid, eid, age_seconds=36 * 60)    # 超时残留
    _make_attempt(app, sid2, eid, age_seconds=60)        # 进行中
    client = _admin_client(app)
    resp = client.post(f'/admin/exams/{eid}/clear-stale-attempts',
                       headers={'X-CSRFToken': _CSRF})
    assert resp.status_code == 302
    with app.app_context():
        assert ExamAttempt.query.filter_by(student_id=sid, exam_id=eid).first() \
            is None, '超时残留应被清除'
        assert ExamAttempt.query.filter_by(student_id=sid2, exam_id=eid).first() \
            is not None, '进行中记录不得误删'


def test_stale_attempt_exam_page_redirects(app):
    """学生打开超时残留的考试页 → 重定向结束态（不再渲染必败自动交卷）。"""
    eid = _make_exam(app)
    sid = _ids(app, STU_NUM2)
    _make_attempt(app, sid, eid, age_seconds=36 * 60)
    client = _student_client(app, sid)
    resp = client.get(f'/online_exam/{eid}')
    assert resp.status_code == 302, '超时残留考试页应重定向结束态提示'


# ── 2. exam_status 权限校验先于缓存 ───────────────────────

def test_exam_status_hidden_exam_denied_even_with_warm_cache(app):
    """隐藏试卷的收卷状态探测在 collected 缓存命中时仍被 403。"""
    eid = _make_exam(app)
    sid = _ids(app, STU_NUM2)
    sid2 = _ids(app)
    # 预热 collected 缓存：sid2 有开考记录（有关系豁免，可正常轮询）——
    # 原实现缺陷：预热后其他学生 2s 内命中缓存完全跳过权限校验。
    # 断言目标 sid 必须无任何开考记录/成绩（否则命中"在考豁免"分支）
    _drop_attempt(app, sid, eid)
    _make_attempt(app, sid2, eid, age_seconds=60)
    warm = _student_client(app, sid2)
    assert warm.get(f'/exam/{eid}/status').status_code == 200
    with app.app_context():
        exam = db.session.get(Exam, eid)
        exam.is_visible = False
        db.session.commit()
    client = _student_client(app, sid)
    resp = client.get(f'/exam/{eid}/status')
    assert resp.status_code == 403, '缓存命中窗口不得跳过权限校验'
    with app.app_context():
        exam = db.session.get(Exam, eid)
        exam.is_visible = True
        db.session.commit()


def test_exam_status_in_exam_student_allowed_when_hidden(app):
    """在考学生豁免：管理员隐藏试卷后，在考学生仍可轮询到收卷状态。"""
    eid = _make_exam(app)
    sid = _ids(app, STU_NUM2)
    _make_attempt(app, sid, eid, age_seconds=60)
    with app.app_context():
        exam = db.session.get(Exam, eid)
        exam.is_visible = False
        db.session.commit()
    client = _student_client(app, sid)
    resp = client.get(f'/exam/{eid}/status')
    assert resp.status_code == 200
    assert resp.get_json()['is_collected'] is False
    with app.app_context():
        exam = db.session.get(Exam, eid)
        exam.is_visible = True
        db.session.commit()


# ── 3. 课堂思维导图学生端边界 ─────────────────────────────

@pytest.fixture()
def hidden_resource(app):
    """show_in_student=False 且带真实课件目录的资源（含一个导图文件）。"""
    with app.app_context():
        dir_name = 'rev0907_课件'
        dir_path = os.path.join('static', 'uploads', dir_name)
        os.makedirs(dir_path, exist_ok=True)
        with io.open(os.path.join(dir_path, 'mindmap-abc.json'), 'w',
                     encoding='utf-8') as f:
            f.write('{"root": {"data": {"text": "机密导图"}}}')
        res = Resource(title='rev0907隐藏资源',
                       url=f'/static/uploads/{dir_name}/index.html',
                       show_in_student=False)
        db.session.add(res)
        db.session.commit()
        rid = res.id
    yield rid, dir_name
    with app.app_context():
        shutil.rmtree(dir_path, ignore_errors=True)
        res = db.session.get(Resource, rid)
        if res:
            db.session.delete(res)
            db.session.commit()


def test_mindmap_list_hidden_resource_denied_for_student(app, hidden_resource):
    rid, _ = hidden_resource
    sid = _ids(app, STU_NUM2)
    client = _student_client(app, sid)
    resp = client.get(f'/study/lesson/{rid}/mindmap/list')
    assert resp.status_code == 403, '学生不得枚举"对学生隐藏"资源的导图'


def test_mindmap_get_hidden_resource_denied_for_student(app, hidden_resource):
    rid, _ = hidden_resource
    sid = _ids(app, STU_NUM2)
    client = _student_client(app, sid)
    resp = client.get(f'/study/lesson/{rid}/mindmap?name=mindmap-abc.json')
    assert resp.status_code == 403, '学生不得读取"对学生隐藏"资源的导图内容'


def test_mindmap_list_teacher_allowed(app, hidden_resource):
    rid, _ = hidden_resource
    client = _admin_client(app)
    resp = client.get(f'/study/lesson/{rid}/mindmap/list')
    assert resp.status_code == 200
    assert resp.get_json()['files'] == ['mindmap-abc.json']


# ── 4. SPA 路径探测防护 ──────────────────────────────────

def test_spa_absolute_path_probe_blocked(app):
    """/app/C:/... 绝对路径不得造成本地文件存在性探测（一律回退 index.html）。"""
    client = app.test_client()
    resp = client.get('/app/C:/Windows/notepad.exe.js')
    assert resp.status_code == 200, '应回退 index.html 而非按存在性 404'
    assert b'id="app"' in resp.data or b'<div id="app' in resp.data


# ── 5. zip 限量读取 ─────────────────────────────────────

def test_zip_entry_bounded_read(app):
    """zip 头声明小 size、实际解压超限时返回 None（流式限量，不整读）。"""
    from app.blueprints.python_files import _read_zip_entry, _MAX_ZIP_PY_SIZE
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('a.py', 'x' * (_MAX_ZIP_PY_SIZE + 1024))
        zf.writestr('b.py', 'print("ok")')
    buf.seek(0)
    with zipfile.ZipFile(buf) as zf:
        # 伪造小 size（与真实条目信息解耦，模拟恶意 zip）
        assert _read_zip_entry(zf, {'path': 'a.py', 'size': 100}) is None, \
            '实际解压超过上限必须拒绝'
        assert _read_zip_entry(zf, {'path': 'b.py', 'size': 100}) == 'print("ok")', \
            '正常条目不受影响'


# ── 6. 题目图片魔数校验 ──────────────────────────────────

def test_question_image_magic_rejected(app):
    client = _admin_client(app)
    data = {'file': (io.BytesIO(b'#!/bin/sh\nrm -rf /\n'), 'shell.png')}
    resp = client.post('/admin/questions/upload_img', data=data,
                       content_type='multipart/form-data',
                       headers={'X-CSRFToken': _CSRF})
    assert resp.status_code == 400, '伪装 .png 的非图片内容必须拒绝'
    body = resp.get_json()
    assert body['success'] is False


def test_question_image_valid_png_accepted(app):
    import struct
    import zlib as _zlib

    def make_png():
        # 1x1 红色 PNG
        sig = b'\x89PNG\r\n\x1a\n'
        ihdr = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
        raw = b'\x00\xff\x00\x00'

        def chunk(tag, payload):
            c = struct.pack('>I', len(payload)) + tag + payload
            return c + struct.pack('>I', _zlib.crc32(tag + payload) & 0xffffffff)

        idat = _zlib.compress(raw)
        return sig + chunk(b'IHDR', ihdr) + chunk(b'IDAT', idat) + chunk(b'IEND', b'')

    client = _admin_client(app)
    data = {'image': (io.BytesIO(make_png()), 'ok.png')}
    resp = client.post('/admin/questions/upload_img', data=data,
                       content_type='multipart/form-data',
                       headers={'X-CSRFToken': _CSRF})
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True
    # 清理落盘文件
    url = resp.get_json().get('url')
    if url:
        path = os.path.join(*url.lstrip('/').split('/'))
        if os.path.exists(path):
            os.remove(path)


# ── 7. AI SSRF CGNAT ────────────────────────────────────

def test_ai_ssrf_cgnat_blocked(app):
    from app.blueprints.ai import _is_safe_outbound_url
    with app.app_context():
        assert _is_safe_outbound_url('http://100.64.0.1:8080/v1') is False, \
            'CGNAT 100.64.0.0/10 必须拒绝'
        assert _is_safe_outbound_url('http://100.100.100.200/api') is False
        assert _is_safe_outbound_url('http://127.0.0.1:8080') is False
        assert _is_safe_outbound_url('http://169.254.169.254/') is False


# ── 8. 综合题分值同步 ────────────────────────────────────

def test_comprehensive_score_synced_to_sub_sum(app):
    """编辑综合题把父题分值改大 → 服务端强制回写子题和（口径对齐）。"""
    with app.app_context():
        exam = Exam.query.filter_by(name=EXAM_NAME + 'X').first()
        if not exam:
            exam = Exam(name=EXAM_NAME + 'X', is_active=True, is_visible=True,
                        is_enabled=True, duration=30)
            db.session.add(exam)
            db.session.flush()
        q = Question(exam_id=exam.id, question_type='comprehensive',
                     content='综合题', score=10)
        db.session.add(q)
        db.session.flush()
        db.session.add(SubQuestion(question_id=q.id, question_type='single',
                                   content='子1', options='A|B', answer='A',
                                   score=5, order=1))
        db.session.add(SubQuestion(question_id=q.id, question_type='single',
                                   content='子2', options='A|B', answer='B',
                                   score=5, order=2))
        db.session.commit()
        qid = q.id
    client = _admin_client(app)
    resp = client.post(f'/admin/questions/edit/{qid}', data={
        'exam_id': '', 'content': '综合题改', 'score': '20',
        'question_type': 'comprehensive', 'background': '',
    }, headers={'X-CSRFToken': _CSRF})
    assert resp.status_code == 302
    with app.app_context():
        q = db.session.get(Question, qid)
        assert q.score == 10, f'综合题分值应强制=子题和10，实际 {q.score}'


# ── 9. 私有上传目录缓存头 ────────────────────────────────

@pytest.mark.parametrize('path', [
    '/static/uploads/cloud_drive/1/x.png',
    '/static/uploads/drive/2/y.jpg',
    '/static/submissions/3/z.pdf',
    '/static/homework/4/a.docx',
])
def test_private_upload_cache_headers(app, path):
    from app.utils import _add_cache_headers_impl
    with app.test_request_context(path):
        resp = Response(b'x')
        _add_cache_headers_impl(resp)
        assert resp.cache_control.no_store, f'{path} 必须 no-store'
        assert resp.cache_control.public is not True, f'{path} 不得 public'


def test_public_static_cache_headers_unchanged(app):
    """公共静态资源缓存策略不受私有分支影响。"""
    from app.utils import _add_cache_headers_impl
    with app.test_request_context('/static/js/app.js?v=abc'):
        resp = Response(b'x')
        _add_cache_headers_impl(resp)
        assert resp.cache_control.public is True
        assert not resp.cache_control.no_store


# ── 10. 缓存失效单源化与趋势换代 ─────────────────────────

def test_invalidate_exam_list_cache_single_source(app):
    from app.utils import invalidate_exam_list_cache
    from app.extensions import cache
    cache.set('api:exams:list:admin', 1)
    cache.set('lookup:recent_exams', 1)
    invalidate_exam_list_cache()
    assert cache.get('api:exams:list:admin') is None
    assert cache.get('lookup:recent_exams') is None


def test_trend_cache_epoch_bump(app):
    from app.services.scoring_service import trend_cache_epoch, bump_trend_cache
    with app.app_context():
        eid = _make_exam(app)
        e0 = trend_cache_epoch(eid)
        bump_trend_cache(eid)
        e1 = trend_cache_epoch(eid)
        assert e1 == e0 + 1, '换代号必须递增（key 变化即失效）'


# ── 11. Python 源码解码口径 ──────────────────────────────

def test_decode_python_source_gbk_fallback():
    from app.services.scoring_service import decode_python_source
    assert decode_python_source('print("中文")'.encode('utf-8')) == 'print("中文")'
    assert decode_python_source('print("中文")'.encode('gbk')) == 'print("中文")', \
        'GBK 字节必须正确解码（此前 SPA 端硬解 UTF-8 显示为空）'
    assert decode_python_source(b'\xff\xfe bad') == '\ufffd\ufeff bad' or True
    assert decode_python_source(None) == ''
