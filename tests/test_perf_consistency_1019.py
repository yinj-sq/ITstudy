# -*- coding: utf-8 -*-
"""2026-10-19 性能/一致性迭代回归。

覆盖：
- AI 上游 JSON 响应 2MB 上限与读取超时保护；
- 在考学生刷新时豁免被临时关闭的试卷开关（HTML/SPA 同口径）；
- 新建作业 commit 失败时回收已落盘附件（不留下孤儿目录）；
- 网盘投递 used_map 仅在 commit 成功后由调用方累加（失败不污染配额）；
- 跨进程限流锁基本可用。
"""
import io
import os
import uuid
from datetime import datetime

import pytest
from sqlalchemy import text

from app import create_app
from app.extensions import db
from app.models import (Class, Exam, ExamAttempt, PythonFile, Question,
                        Student)
from app.services.student_drive_service import save_drive_file_for_student
from app.utils import _rate_limit_process_lock, delete_file_from_disk

_CSRF = 't'
PREFIX = '1019性能'


@pytest.fixture(scope='module')
def app():
    app = create_app()
    with app.app_context():
        _cleanup()
    yield app
    with app.app_context():
        _cleanup()


def _cleanup():
    conn = db.session.connection()
    conn.execute(text("DELETE FROM exam_attempt WHERE exam_id IN "
                      "(SELECT id FROM exam WHERE name LIKE :p)"), {'p': PREFIX + '%'})
    conn.execute(text("DELETE FROM exam_question WHERE exam_id IN "
                      "(SELECT id FROM exam WHERE name LIKE :p)"), {'p': PREFIX + '%'})
    conn.execute(text("DELETE FROM question WHERE content LIKE :p"), {'p': PREFIX + '%'})
    conn.execute(text("DELETE FROM homework WHERE title LIKE :p"), {'p': PREFIX + '%'})
    conn.execute(text("DELETE FROM student_drive_file WHERE original_filename LIKE :p"),
                 {'p': PREFIX + '%'})
    conn.execute(text("DELETE FROM student WHERE student_number LIKE :p"), {'p': PREFIX + '%'})
    conn.execute(text("DELETE FROM classes WHERE name LIKE :p"), {'p': PREFIX + '%'})
    conn.execute(text("DELETE FROM exam WHERE name LIKE :p"), {'p': PREFIX + '%'})
    db.session.commit()


def _mk_student(suffix, changed=True):
    s = Student(name=PREFIX + '学生' + suffix, student_number=PREFIX + suffix,
                is_activated=True, has_changed_password=changed)
    db.session.add(s)
    db.session.flush()
    return s


def _student_login(client, sid):
    with client.session_transaction() as s:
        s.clear()
        s['student_id'] = sid
        s['csrf_token'] = _CSRF


def test_ai_json_read_limit():
    from app.blueprints.ai import _read_limited_json, _AI_MAX_JSON_BYTES

    class FakeResp:
        encoding = 'utf-8'

        def __init__(self, chunks):
            self.chunks = chunks
            self.closed = False

        def iter_content(self, chunk_size=16384):
            yield from self.chunks

        def close(self):
            self.closed = True

    assert _read_limited_json(FakeResp([b'{"a": 1}']), 5) == {'a': 1}
    with pytest.raises(ValueError):
        _read_limited_json(FakeResp([b'x' * (_AI_MAX_JSON_BYTES + 1)]), 5)


def test_active_attempt_bypasses_closed_exam_switches(app):
    c = app.test_client()
    with app.app_context():
        stu = _mk_student('在考')
        e = Exam(name=PREFIX + '·关闭卷', is_active=False, is_visible=False,
                 is_enabled=False, duration=30)
        db.session.add(e)
        db.session.flush()
        q = Question(exam_id=e.id, question_type='single', content=PREFIX + '题',
                     options='A.1|B.2', answer='A', score=2)
        db.session.add(q)
        db.session.add(ExamAttempt(student_id=stu.id, exam_id=e.id,
                                   start_time=datetime.now()))
        db.session.commit()
        eid, sid = e.id, stu.id

    _student_login(c, sid)
    # 在考学生：HTML 页与 SPA 详情接口均应放行
    r = c.get(f'/online_exam/{eid}')
    assert r.status_code == 200, r.status_code
    r = c.get(f'/api/exams/{eid}')
    assert r.status_code == 200, (r.status_code, r.get_data(as_text=True))

    # 无开考记录的学生仍被开关拦截
    with app.app_context():
        stu2 = _mk_student('未开考')
        db.session.commit()
        sid2 = stu2.id
    c2 = app.test_client()
    _student_login(c2, sid2)
    assert c2.get(f'/online_exam/{eid}').status_code == 302
    assert c2.get(f'/api/exams/{eid}').status_code == 403


def test_homework_create_commit_failure_cleans_attachments(app, tmp_path, monkeypatch):
    import app.blueprints.homework as hw_module
    monkeypatch.setattr(hw_module, 'HOMEWORK_DIR', str(tmp_path / 'homework'))
    monkeypatch.setattr(hw_module, 'SUBMISSION_DIR', str(tmp_path / 'submissions'))
    c = app.test_client()
    with c.session_transaction() as s:
        s['is_teacher'] = True
        s['teacher_id'] = 1
        s['teacher_name'] = PREFIX + '教师'
        s['csrf_token'] = _CSRF
    with app.app_context():
        cls = Class(name=PREFIX + '班')
        db.session.add(cls)
        db.session.commit()
        cid = cls.id

    def boom(*a, **kw):
        raise RuntimeError('simulated commit failure')

    monkeypatch.setattr(db.session, 'commit', boom)
    data = {
        'title': PREFIX + '作业',
        'description': '',
        'class_ids': [str(cid)],
    }
    data['files'] = (io.BytesIO(b'hello'), 'a.txt')
    resp = c.post('/admin/homework/create', data=data,
                  headers={'X-CSRFToken': _CSRF})
    assert resp.status_code in (302, 303), resp.status_code
    # 附件目录已回滚清理（只可能剩下空父目录）
    leftovers = [p for p in tmp_path.rglob('*') if p.is_file()]
    assert leftovers == [], leftovers


def test_question_delete_commit_failure_keeps_files(app, monkeypatch):
    """删题提交失败时不得先删磁盘文件（否则回滚后记录在、文件 404）。"""
    c = app.test_client()
    with c.session_transaction() as s:
        s['is_admin'] = True
        s['csrf_token'] = _CSRF
    rel = f'python_files/{uuid.uuid4().hex}_ref.py'
    abs_path = os.path.join(app.static_folder, 'uploads', rel)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, 'w', encoding='utf-8') as f:
        f.write('print(1)')
    with app.app_context():
        q = Question(question_type='python_fill', content=PREFIX + '删题文件',
                     options='', answer='', score=2)
        db.session.add(q)
        db.session.flush()
        db.session.add(PythonFile(question_id=q.id, file_name='ref.py',
                                  file_path=rel))
        db.session.commit()
        qid = q.id

    def boom(*a, **kw):
        raise RuntimeError('simulated commit failure')

    monkeypatch.setattr(db.session, 'commit', boom)
    resp = c.post(f'/admin/questions/delete/{qid}',
                  headers={'X-CSRFToken': _CSRF})
    monkeypatch.undo()
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert os.path.isfile(abs_path), '提交失败后磁盘文件被误删'
    with app.app_context():
        q = db.session.get(Question, qid)
        pf = PythonFile.query.filter_by(question_id=qid).first()
        assert q is not None and pf is not None
        db.session.delete(pf)
        db.session.delete(q)
        db.session.commit()
    try:
        os.remove(abs_path)
    except OSError:
        pass


def test_drive_preload_used_map_not_incremented_before_commit(app):
    with app.app_context():
        stu = _mk_student('网盘')
        db.session.commit()
        sid = stu.id
        preload = {'quota_map': {sid: 20 * 1024 * 1024},
                   'default_quota': 20 * 1024 * 1024,
                   'used_map': {sid: 0}}
        rel = save_drive_file_for_student(
            sid, b'hello', PREFIX + '.txt', commit=False, _preload=preload)
        assert preload['used_map'][sid] == 0
        db.session.rollback()
        delete_file_from_disk(rel)


def test_process_rate_limit_lock_context():
    with _rate_limit_process_lock():
        pass
    with _rate_limit_process_lock():
        pass
