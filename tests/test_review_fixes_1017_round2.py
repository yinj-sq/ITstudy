# -*- coding: utf-8 -*-
"""2026-10-17 第二轮修复的回归用例：
① 撤销 AI 屏蔽词/内容过滤（模块与字典删除）；
② 活动创建、网盘发送在 commit 失败时回收磁盘孤儿文件（复用 _discard_orphan）。

数据用 rev1017b 前缀，模块前后各清一次；跑完仍须跑 review_db_residue_check.py。
"""
import io
import os
import shutil

import pytest

from app import create_app
from app.extensions import db
from app.models import LearningActivity, Log, Resource, Student, StudentDriveFile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_UPLOADS = os.path.join(_ROOT, 'static', 'uploads')
_CSRF = 'rev1017b-csrf-token'
_STU_NUM = 'REV1017B-1'
_DIR_ACT = 'rev1017b_活动资源'


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
    res_ids = [r.id for r in Resource.query.filter(Resource.title.like('rev1017b%')).all()]
    if res_ids:
        LearningActivity.query.filter(
            LearningActivity.resource_id.in_(res_ids)).delete(synchronize_session=False)
        Resource.query.filter(Resource.id.in_(res_ids)).delete(synchronize_session=False)
    stu_ids = [s.id for s in Student.query.filter(
        Student.student_number.like('REV1017B%')).all()]
    if stu_ids:
        StudentDriveFile.query.filter(
            StudentDriveFile.student_id.in_(stu_ids)).delete(synchronize_session=False)
        Student.query.filter(Student.id.in_(stu_ids)).delete(synchronize_session=False)
    Log.query.filter(Log.detail.like('%rev1017b%')).delete(synchronize_session=False)
    db.session.commit()
    shutil.rmtree(os.path.join(_UPLOADS, _DIR_ACT), ignore_errors=True)
    for sid in stu_ids:
        shutil.rmtree(os.path.join(_UPLOADS, 'cloud_drive', str(sid)), ignore_errors=True)


def _admin_client(app):
    client = app.test_client()
    with client.session_transaction() as s:
        s.clear()
        s['is_admin'] = True
        s['csrf_token'] = _CSRF
    return client


# ══════════════════════════════════════════════════════════════
#  ① AI 屏蔽词/内容过滤已撤销
# ══════════════════════════════════════════════════════════════

def test_content_filter_module_removed():
    with pytest.raises(ImportError):
        import app.content_filter  # noqa: F401
    assert not os.path.exists(os.path.join(_ROOT, 'docs', '屏蔽词字典.txt'))
    # ai.py 不得再引用自建过滤函数（DeepSeek 上游的 finish_reason
    # 'content_filter' 是协议字段，不属于本项目过滤模块）。
    src = open(os.path.join(_ROOT, 'app', 'blueprints', 'ai.py'),
               encoding='utf-8').read()
    assert 'import app.content_filter' not in src
    assert 'content_filter(' not in src
    assert 'filter_user_input' not in src
    assert 'filter_ai_output' not in src


# ══════════════════════════════════════════════════════════════
#  ② commit 失败时回收磁盘孤儿文件
# ══════════════════════════════════════════════════════════════

def _install_commit_failure(monkeypatch):
    """让下一次 db.session.commit() 抛异常（模拟提交失败）。"""
    def boom(*_a, **_k):
        raise RuntimeError('forced commit failure')
    monkeypatch.setattr(db.session, 'commit', boom)


def test_activity_create_reclaims_orphan_on_commit_failure(app, monkeypatch):
    with app.app_context():
        r = Resource(title='rev1017b活动资源', url=f'/static/uploads/{_DIR_ACT}')
        db.session.add(r)
        db.session.commit()
        rid = r.id
        db.session.remove()

    from app.blueprints import activities as act_mod
    seen = []
    real = act_mod._discard_orphan

    def spy(rel):
        seen.append(rel)
        return real(rel)

    monkeypatch.setattr(act_mod, '_discard_orphan', spy)
    _install_commit_failure(monkeypatch)

    client = _admin_client(app)
    resp = client.post(
        f'/admin/resources/{rid}/activities/new',
        data={'title': 'rev1017b孤儿活动',
              'document': (io.BytesIO(b'hello'), 'doc.txt')},
        headers={'X-CSRFToken': _CSRF},
        content_type='multipart/form-data')
    assert resp.status_code == 302
    assert seen, '提交失败时未回收孤儿文档'
    # 真实回收生效：活动文档目录已清空
    d = os.path.join(_UPLOADS, 'activity_docs', str(rid))
    assert (not os.path.isdir(d)) or (not os.listdir(d))

    monkeypatch.undo()   # 解除 commit 失败注入，供清理提交使用
    with app.app_context():
        LearningActivity.query.filter(
            LearningActivity.resource_id == rid).delete(synchronize_session=False)
        Resource.query.filter(Resource.id == rid).delete(synchronize_session=False)
        db.session.commit()
        db.session.remove()
    shutil.rmtree(os.path.join(_UPLOADS, 'activity_docs', str(rid)), ignore_errors=True)


def test_student_drive_send_reclaims_orphan_on_commit_failure(app, monkeypatch):
    with app.app_context():
        stu = Student(name='rev1017b生', student_number=_STU_NUM, is_activated=True)
        stu.set_password('rev1017bpass')
        db.session.add(stu)
        db.session.commit()
        sid = stu.id
        db.session.remove()

    from app.blueprints import student_drive as sd_mod
    seen = []
    real = sd_mod._discard_orphan

    def spy(rel):
        seen.append(rel)
        return real(rel)

    monkeypatch.setattr(sd_mod, '_discard_orphan', spy)
    _install_commit_failure(monkeypatch)

    client = _admin_client(app)
    resp = client.post(
        f'/admin/student-drive/{sid}/send',
        data={'note': 'rev1017b发送', 'files': (io.BytesIO(b'hello'), 'note.txt')},
        headers={'X-CSRFToken': _CSRF},
        content_type='multipart/form-data')
    assert resp.status_code == 302
    assert seen, '提交失败时未回收网盘孤儿文件'
    assert all(rel for rel in seen)          # rel 非空才回收
    # 真实回收生效：云盘目录已清空
    d = os.path.join(_UPLOADS, 'cloud_drive', str(sid))
    assert (not os.path.isdir(d)) or (not os.listdir(d))

    monkeypatch.undo()   # 解除 commit 失败注入，供清理提交使用
    with app.app_context():
        StudentDriveFile.query.filter(
            StudentDriveFile.student_id == sid).delete(synchronize_session=False)
        Student.query.filter(Student.id == sid).delete(synchronize_session=False)
        db.session.commit()
        db.session.remove()
    shutil.rmtree(os.path.join(_UPLOADS, 'cloud_drive', str(sid)), ignore_errors=True)
