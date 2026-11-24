# -*- coding: utf-8 -*-
"""2026-09-13 下午增审轮（第 11 轮）修复回归。

覆盖（详见 2026-09-13 审查报告本轮章节，原文 git show 8d47f69:docs/全面审查报告-2026-09-13.md）：
- webp 流式上传魔数校验：validate_image_magic_head 读 12 字节头，合法 webp
  不再被 8 字节截断误判（此前学生网盘/作业投递 .webp 100% 失败）
- 作业附件投递逐条提交：单条 commit 失败只损失该条，已投递记录持久、
  失败条目的磁盘文件被回收（此前整批一次 commit，失败 → 全回滚 + 孤儿文件）
- 投递线程单飞：start_homework_delivery 并发调用只启动一个投递线程
- DANGEROUS_INLINE_EXTS 补 css：私有上传目录 .css 以 text/plain 交付

清理约定：全部数据用 PM13 前缀命名，模块 teardown 定向清理
（DB 行 + 磁盘文件），跑完仍须复跑 tools/review_db_residue_check.py。
"""
import io
import json
import os
import shutil
import threading

import pytest
import sqlalchemy.exc
import sqlalchemy.orm

from app import create_app
from app.extensions import db
from app.models import (Class, Student, Homework, StudentDriveFile,
                        StudentDriveQuota, homework_classes)
from app.utils import validate_image_magic_head, safe_inline_mimetype

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DRIVE_DIR = os.path.join(_ROOT, 'static', 'uploads', 'cloud_drive')

# 真 webp 头：RIFF + 4 字节长度 + WEBP（validate_image_magic 取 [8:12]）
_WEBP_OK = b'RIFF\x24\x00\x00\x00WEBP' + b'\x00' * 32
# 伪 webp：RIFF 开头但 8-12 字节不是 WEBP（伪装内容）
_WEBP_FAKE = b'RIFF\x24\x00\x00\x00EXEF' + b'\x00' * 32


class _FakeStorage:
    """最小 FileStorage 替身。

    validate_image_magic_head 只用 .stream；save_stream_to_disk 走
    .save(abs_path) 直接落盘——此前替身缺 save 方法，真实保存路径
    必然 AttributeError→「文件保存失败」，测试根本没跑到魔数校验。
    """

    def __init__(self, content):
        self.stream = io.BytesIO(content)

    def save(self, dst, buffer_size=65536):
        self.stream.seek(0)
        with open(dst, 'wb') as out:
            shutil.copyfileobj(self.stream, out, buffer_size)
        self.stream.seek(0)


@pytest.fixture(scope='module')
def app():
    app = create_app()
    with app.app_context():
        _cleanup()  # 先扫残留：前次运行 teardown 失败沉积的数据会让
    yield app       # 共享班级里冒出额外投递目标，断言全部失真
    with app.app_context():
        _cleanup()


def _cleanup():
    """清掉本模块 PM13 前缀的数据行与磁盘文件。

    删除顺序必须满足外键依赖：网盘文件行、配额行（FK→student）都先于
    student 删除——此前先删 student，quota 行仍在，FK 违反导致整个清理
    事务回滚，残留跨运行累积（污染后续运行的投递目标集合）。
    """
    from app.utils import delete_file_from_disk
    db.session.rollback()
    students = Student.query.filter(
        Student.student_number.like('PM13-%')).all()
    stu_ids = [s.id for s in students]
    if stu_ids:
        for rel in db.session.query(StudentDriveFile.file_path).filter(
                StudentDriveFile.student_id.in_(stu_ids)).all():
            if rel[0]:
                try:
                    delete_file_from_disk(rel[0])
                except OSError:
                    pass
        db.session.query(StudentDriveFile).filter(
            StudentDriveFile.student_id.in_(stu_ids)).delete(
            synchronize_session=False)
        db.session.query(StudentDriveQuota).filter(
            StudentDriveQuota.student_id.in_(stu_ids)).delete(
            synchronize_session=False)
    hws = Homework.query.filter(Homework.title.like('PM13%')).all()
    if hws:
        for h in hws:
            db.session.execute(
                homework_classes.delete().where(
                    homework_classes.c.homework_id == h.id))
            db.session.delete(h)
    if stu_ids:
        db.session.query(Student).filter(Student.id.in_(stu_ids)).delete(
            synchronize_session=False)
    db.session.query(Class).filter(Class.name.like('PM13%')).delete(
        synchronize_session=False)
    db.session.commit()
    # 磁盘兜底：删掉测试学生网盘目录（可能存在无 DB 行的残留文件）
    for sid in stu_ids:
        shutil.rmtree(os.path.join(_DRIVE_DIR, str(sid)), ignore_errors=True)


def _make_student(app, number, name, quota_mb=20, class_name='PM13班级'):
    """建学生（默认独占 class_name 班级）。

    class_name 缺省值仅供 webp 单学生测试用；投递类测试必须传各自独立
    的班级名——共享班级会让先前测试的学生混入投递目标集合（实测导致
    delivered 计数虚高、断言全盘失真）。
    """
    with app.app_context():
        cls = Class.query.filter_by(name=class_name).first()
        if not cls:
            cls = Class(name=class_name)
            db.session.add(cls)
            db.session.flush()
        stu = Student(name=name, student_number=number, class_id=cls.id,
                      student_class=class_name)
        stu.set_password('123456')
        stu.is_activated = True
        db.session.add(stu)
        db.session.flush()
        db.session.add(StudentDriveQuota(student_id=stu.id, quota_mb=quota_mb))
        db.session.commit()
        return stu.id


# ────────────────────────────────────────────────
# webp 魔数头校验（8 字节截断缺陷的回归）
# ────────────────────────────────────────────────

def test_webp_head_valid_passes():
    assert validate_image_magic_head(_FakeStorage(_WEBP_OK), '图.webp') is True


def test_webp_head_fake_content_fails():
    # RIFF 开头但 8-12 字节非 WEBP：8 字节截断时代这段必漏判/误判
    assert validate_image_magic_head(_FakeStorage(_WEBP_FAKE), '图.webp') is False


def test_webp_head_short_stream_fails():
    # 流只有 8 字节（截断/超短文件）：旧实现 read(8) 时 content[8:12] 恒空
    # → 合法与否全靠运气；新实现读满 12 字节后按内容判定
    assert validate_image_magic_head(_FakeStorage(_WEBP_OK[:8]), '图.webp') is False


def test_png_head_still_works():
    png = b'\x89PNG\r\n\x1a\n' + b'\x00' * 24
    assert validate_image_magic_head(_FakeStorage(png), 'a.png') is True
    assert validate_image_magic_head(_FakeStorage(b'MZ' + b'\x00' * 30), 'a.png') is False


def test_non_image_ext_skips_stream():
    st = _FakeStorage(b'whatever')
    assert validate_image_magic_head(st, 'doc.txt') is True
    assert st.stream.tell() == 0  # 未读流


def test_webp_streaming_upload_end_to_end(app):
    """学生网盘流式路径上传合法 webp：旧代码必报「图片内容校验失败」。"""
    from app.services.student_drive_service import save_drive_file_for_student
    stu_id = _make_student(app, 'PM13-WEBP', '网盘学生')
    with app.app_context():
        rel = save_drive_file_for_student(
            stu_id, None, 'webp图.webp',
            sender_type='teacher', sender_name='回归',
            file_storage=_FakeStorage(_WEBP_OK), commit=True)
        row = StudentDriveFile.query.filter_by(student_id=stu_id).one()
        assert row.file_path == rel
        assert os.path.getsize(os.path.join(
            _ROOT, 'static', 'uploads', rel)) == len(_WEBP_OK)


# ────────────────────────────────────────────────
# 作业投递逐条提交（整批 commit 缺陷的回归）
# ────────────────────────────────────────────────

def _make_homework_with_attachment(app, class_name='PM13班级',
                                   attachment_bytes=b'PM13-attachment'):
    """建作业 + 附件目录文件（作业发给 class_name 班级），返回 (hw_id, hw_dir)。"""
    with app.app_context():
        hw = Homework(title='PM13投递作业', is_active=True, teacher_id=None)
        hw.attachments = json.dumps(['pm13附件.txt'])
        cls = Class.query.filter_by(name=class_name).one()
        hw.classes.append(cls)
        db.session.add(hw)
        db.session.commit()
        hw_dir = os.path.join(_ROOT, 'static', 'homework', f'PM13hw{hw.id}')
        os.makedirs(hw_dir, exist_ok=True)
        with open(os.path.join(hw_dir, 'pm13附件.txt'), 'wb') as f:
            f.write(attachment_bytes)
        return hw.id, hw_dir


def test_delivery_per_record_commit(app, monkeypatch):
    """首次 commit 失败：该条记录回滚、磁盘文件被回收；第二条正常投递。

    旧实现（整批最后一次 commit）：任何一次 commit 失败都会把全部投递
    记录回滚，而已写盘的文件全部成为孤儿、结果还误报 delivered。
    flaky 只对「有待提交 StudentDriveFile 记录」的 commit 生效：应用启动
    会拉起后台线程（网盘清理/AI 归档），其偶发 commit 不得消耗失败槽位。
    """
    from app.services.student_drive_service import deliver_homework_attachments
    from app.models import StudentDriveFile as _SDF
    id_a = _make_student(app, 'PM13-DL-A', '投递学生A', class_name='PM13投递班1')
    id_b = _make_student(app, 'PM13-DL-B', '投递学生B', class_name='PM13投递班1')
    hw_id, hw_dir = _make_homework_with_attachment(app, class_name='PM13投递班1')
    try:
        with app.app_context():
            hw = db.session.get(Homework, hw_id)
            real_commit = sqlalchemy.orm.Session.commit
            calls = {'n': 0}

            def flaky_commit(self):
                if any(isinstance(o, _SDF) for o in list(self.new)):
                    calls['n'] += 1
                    if calls['n'] == 1:
                        raise sqlalchemy.exc.OperationalError(
                            'COMMIT', {}, Exception('模拟 commit 失败'))
                return real_commit(self)

            monkeypatch.setattr(sqlalchemy.orm.Session, 'commit', flaky_commit)
            result = deliver_homework_attachments(hw, hw_dir)
            monkeypatch.undo()
            assert calls['n'] == 2, f'两次投递应恰好各触发一次 commit: {calls}'
            assert result['delivered'] == 1
            assert len(result['failed']) == 1
            assert result['failed'][0]['reason'] == '投递异常'
            rows = StudentDriveFile.query.filter(
                StudentDriveFile.student_id.in_([id_a, id_b])).all()
            assert len(rows) == 1, '失败的投递不得留下 DB 记录'
            saved_sid = rows[0].student_id
            # 成功条目文件在盘上；失败条目目录为空/不存在（孤儿已回收）
            assert os.path.isfile(os.path.join(
                _ROOT, 'static', 'uploads', rows[0].file_path))
            orphan_dir = os.path.join(
                _DRIVE_DIR, str(id_b if saved_sid == id_a else id_a))
            assert not os.path.isdir(orphan_dir) or not os.listdir(orphan_dir)
    finally:
        shutil.rmtree(os.path.join(_ROOT, 'static', 'homework', f'PM13hw{hw_id}'),
                      ignore_errors=True)


def test_delivery_quota_fail_keeps_others(app):
    """容量不足学生跳过不阻断他人（既有容错语义在新提交模式下保持）。"""
    from app.services.student_drive_service import deliver_homework_attachments
    _make_student(app, 'PM13-DL-C', '投递学生C', class_name='PM13投递班2')
    _make_student(app, 'PM13-DL-D', '投递学生D', quota_mb=0,
                  class_name='PM13投递班2')
    hw_id, hw_dir = _make_homework_with_attachment(app, class_name='PM13投递班2')
    try:
        with app.app_context():
            hw = db.session.get(Homework, hw_id)
            result = deliver_homework_attachments(hw, hw_dir)
            assert result['delivered'] == 1
            assert len(result['insufficient']) == 1
            assert result['insufficient'][0]['student'] == '投递学生D'
            # 幂等去重：已投递的 C 有记录、不再重复；失败的 D 无记录，
            # 重跑会被重试（容量仍不足 → 仍跳过）——重试语义保证教师重新
            # 发布时容量已扩的学生能补收附件
            hw2 = db.session.get(Homework, hw_id)
            result2 = deliver_homework_attachments(hw2, hw_dir)
            assert result2['total'] == 1 and result2['delivered'] == 0
            assert len(result2['insufficient']) == 1
            assert result2['insufficient'][0]['student'] == '投递学生D'
    finally:
        shutil.rmtree(os.path.join(_ROOT, 'static', 'homework', f'PM13hw{hw_id}'),
                      ignore_errors=True)


# ────────────────────────────────────────────────
# 投递线程单飞（check-then-act 竞态的回归）
# ────────────────────────────────────────────────

def test_delivery_start_singleflight(app, monkeypatch):
    from app.services import delivery_worker as dw
    started = threading.Event()
    release = threading.Event()
    calls = []

    def fake_worker(_app, hw_id, _hw_dir, _sender):
        calls.append(hw_id)
        started.set()
        release.wait(5)

    monkeypatch.setattr(dw, '_delivery_worker', fake_worker)
    t1 = threading.Thread(target=lambda: _launch(app, dw, 999001))
    t2 = threading.Thread(target=lambda: _launch(app, dw, 999001))
    t1.start()
    assert started.wait(3), '首个投递线程未启动'
    t2.start()
    t1.join(5)
    t2.join(5)
    release.set()
    assert calls == [999001], f'投递线程被启动了 {len(calls)} 次'


def _launch(app, dw, hw_id):
    with app.app_context():
        dw.start_homework_delivery(app, hw_id, '.', sender_name='回归')


# ────────────────────────────────────────────────
# css 并入危险主动内容清单
# ────────────────────────────────────────────────

def test_css_forced_to_text_preview():
    assert safe_inline_mimetype('style.css') == 'text/plain; charset=utf-8'
    assert safe_inline_mimetype('a.JS') == 'text/plain; charset=utf-8'
    assert safe_inline_mimetype('notes.md') is None
