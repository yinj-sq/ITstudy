# -*- coding: utf-8 -*-
"""inline 预览响应不得带 Content-Disposition（2026-09-13 审查发现并修复）

**缺陷**：Chromium 对 `Content-Disposition: inline` + **非文本**
Content-Type 的 fetch/XHR 响应不给 JS body —— 状态码被改写成 204、
body 为空。全站预览页都是 fetch 取 `?inline=1` 再喂 JitViewer，于是
PDF / 图片 / Office 文档预览一律拿到 0 字节，预览器报「文件为空／
格式不正确」。个人网盘与小组网盘的预览全中。

实测矩阵（Edge headed、同源、同一路由，仅改响应头）：

    Content-Type              Content-Disposition    fetch() 结果
    application/pdf           无                     200 / 完整
    application/pdf           inline                 204 / 空
    application/octet-stream  inline                 204 / 空
    text/plain                inline                 200 / 完整   ← 文本豁免
    application/pdf           attachment             200 / 完整
    application/octet-stream  无                     200 / 完整

服务端**完全看不到**该故障：after_request 记录的仍是 200 且带完整
Content-Length，裸 HTTP 直取也正常。本项目因此误判过两轮——先归因
「无头环境特异」，再归因「启发式缓存 × Range 交互」并加 no-store，
两次处置均无效。故用本文件把不变量钉死在真实路由上。

**本文件会写生产库**（与 test_review_fixes_0910.py 同一前提）：建 1 个
班级、1 名学生、1 个小组、1 条网盘文件记录、1 条小组文件记录，以及
static/uploads 下的 1 个临时文件；结束后按固定名前缀清理。
"""
import os
from urllib.parse import quote

import pytest

from app import create_app
from app.extensions import db
from app.models import (Class, GroupFile, LearningActivity, Resource, Student,
                        StudentDriveFile, StudentWork, StudyGroup)

CLS_NAME = '审查0913班'
GROUP_NAME = '审查0913组'      # study_group.name 为 VARCHAR(10)，勿加长
STU_NUM = 'REV0913CD01'
CSRF = 'review-0913-csrf'
UP_DIR = os.path.join('static', 'uploads')
FILE_NAME = '审查0913内联预览.pdf'
WORKS_FILE = '审查0913作品.pdf'
ACT_TITLE = '审查0913活动'
WORK_TOKEN = 'rev0913inlinepreviewtoken'
# 固定字节：断言长度与 Range 边界都靠它
PDF_BYTES = (b'%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n'
             b'2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n'
             b'trailer<</Root 1 0 R/Size 4>>\n%%EOF')


@pytest.fixture(scope='module')
def app():
    application = create_app()
    _seed(application)
    yield application
    with application.app_context():
        _cleanup()
    # 逐个 try：Windows 上句柄未释放会删不掉，前一个失败不能挡住后一个
    for rel in (FILE_NAME, WORKS_FILE):
        try:
            os.remove(os.path.join(UP_DIR, rel))
        except OSError:
            pass


def _seed(app):
    """幂等建数据；重跑不产生重复行。"""
    with app.app_context():
        os.makedirs(UP_DIR, exist_ok=True)
        with open(os.path.join(UP_DIR, FILE_NAME), 'wb') as f:
            f.write(PDF_BYTES)

        cls = Class.query.filter_by(name=CLS_NAME).first()
        if not cls:
            cls = Class(name=CLS_NAME)
            db.session.add(cls)
            db.session.flush()

        group = StudyGroup.query.filter_by(name=GROUP_NAME).first()
        if not group:
            group = StudyGroup(name=GROUP_NAME, class_id=cls.id,
                               drive_enabled=True)
            db.session.add(group)
            db.session.flush()

        stu = Student.query.filter_by(student_number=STU_NUM).first()
        if not stu:
            stu = Student(name='审查0913内联生', student_number=STU_NUM,
                          student_class=cls.name, class_id=cls.id,
                          group_id=group.id, is_activated=True,
                          has_changed_password=True)
            stu.set_password('Rev0913#')
            db.session.add(stu)
            db.session.flush()

        if not StudentDriveFile.query.filter_by(
                student_id=stu.id, filename=FILE_NAME).first():
            db.session.add(StudentDriveFile(
                student_id=stu.id, sender_type='student', sender_id=stu.id,
                filename=FILE_NAME, original_filename=FILE_NAME,
                file_size=len(PDF_BYTES), file_path=FILE_NAME))
        if not GroupFile.query.filter_by(filename=FILE_NAME).first():
            db.session.add(GroupFile(
                group_id=group.id, uploader_id=stu.id, filename=FILE_NAME,
                original_filename=FILE_NAME, file_size=len(PDF_BYTES),
                file_path=FILE_NAME))

        # 活动文档 / 作品文件：activities.py 里另三处同款调用点
        with open(os.path.join(UP_DIR, WORKS_FILE), 'wb') as f:
            f.write(PDF_BYTES)
        res = Resource.query.filter_by(title=ACT_TITLE).first()
        if not res:
            res = Resource(title=ACT_TITLE)
            db.session.add(res)
            db.session.flush()
        act = LearningActivity.query.filter_by(title=ACT_TITLE).first()
        if not act:
            act = LearningActivity(resource_id=res.id, title=ACT_TITLE,
                                   document_path=FILE_NAME,
                                   document_name=FILE_NAME, is_active=True)
            db.session.add(act)
            db.session.flush()
        if not StudentWork.query.filter_by(public_token=WORK_TOKEN).first():
            db.session.add(StudentWork(
                activity_id=act.id, student_id=stu.id, title=ACT_TITLE,
                work_type='file', original_filename=WORKS_FILE,
                file_path=WORKS_FILE, file_size=len(PDF_BYTES),
                status='submitted', public_token=WORK_TOKEN,
                is_excellent=True))
        db.session.commit()


def _cleanup():
    conn = db.session.connection()
    conn.execute(db.text(
        'DELETE FROM student_work WHERE student_id IN '
        '(SELECT id FROM student WHERE student_number=:n)'), {'n': STU_NUM})
    conn.execute(db.text(
        'DELETE FROM learning_activity WHERE resource_id IN '
        '(SELECT id FROM resource WHERE title=:n)'), {'n': ACT_TITLE})
    conn.execute(db.text(
        'DELETE FROM resource WHERE title=:n'), {'n': ACT_TITLE})
    conn.execute(db.text(
        'DELETE FROM student_drive_file WHERE student_id IN '
        '(SELECT id FROM student WHERE student_number=:n)'), {'n': STU_NUM})
    conn.execute(db.text(
        'DELETE FROM group_file WHERE group_id IN '
        '(SELECT id FROM study_group WHERE name=:n)'), {'n': GROUP_NAME})
    conn.execute(db.text(
        'DELETE FROM student WHERE student_number=:n'), {'n': STU_NUM})
    conn.execute(db.text(
        'DELETE FROM study_group WHERE name=:n'), {'n': GROUP_NAME})
    conn.execute(db.text(
        'DELETE FROM classes WHERE name=:n'), {'n': CLS_NAME})
    # 必须提交：session.connection() 会开启事务，会话销毁时未提交即回滚，
    # 清理会静默失效（本测试首版就踩了这个坑，生产库留下 5 行垃圾数据）。
    db.session.commit()


def _client(app):
    client = app.test_client()
    with client.session_transaction() as s:
        s.clear()
        s['is_admin'] = True     # 管理员身份绕过班级边界，直接命中下载分支
        s['csrf_token'] = CSRF
    return client


def _student_client(app):
    """小组网盘走 @login_required（只认学生会话），管理员会被 302 弹回。"""
    with app.app_context():
        sid = Student.query.filter_by(student_number=STU_NUM).first().id
    client = app.test_client()
    with client.session_transaction() as s:
        s.clear()
        s['student_id'] = sid
        s['student_name'] = '审查0913内联生'
        s['csrf_token'] = CSRF
    return client


def _drive_url(app):
    with app.app_context():
        rec = StudentDriveFile.query.filter_by(filename=FILE_NAME).first()
        return f'/student/drive/download/{rec.id}'


def _group_url(app):
    with app.app_context():
        rec = GroupFile.query.filter_by(filename=FILE_NAME).first()
        return f'/groups/drive/download/{rec.id}'


def _activity_url(app):
    with app.app_context():
        act = LearningActivity.query.filter_by(title=ACT_TITLE).first()
        return f'/activity/document/{act.id}'


def _work_url(app):
    with app.app_context():
        w = StudentWork.query.filter_by(public_token=WORK_TOKEN).first()
        return f'/works/file/{w.id}'


PUBLIC_WORK_URL = f'/works/public/{WORK_TOKEN}/file'


# ── 个人网盘 ──────────────────────────────────────

def test_inline_preview_omits_content_disposition(app):
    """inline=1 不能带 CD 头——带上就是预览全挂（见模块 docstring）。"""
    r = _client(app).get(_drive_url(app) + '?inline=1')

    assert r.status_code == 200
    assert 'Content-Disposition' not in r.headers
    # 类型仍须正确：JitViewer 按 blob.type 决定用哪个预览器
    assert r.headers['Content-Type'] == 'application/pdf'
    assert r.data == PDF_BYTES


def test_inline_preview_keeps_range_support(app):
    """去掉 CD 不能连带打掉 conditional=True 的断点续传能力。"""
    r = _client(app).get(_drive_url(app) + '?inline=1',
                         headers={'Range': 'bytes=0-9'})

    assert r.status_code == 206
    assert r.headers['Content-Range'] == f'bytes 0-9/{len(PDF_BYTES)}'
    assert 'Content-Disposition' not in r.headers


def test_download_branch_still_attaches(app):
    """真实下载（无 inline=1）必须保留 attachment 与文件名，不能误伤。"""
    r = _client(app).get(_drive_url(app))

    assert r.status_code == 200
    cd = r.headers['Content-Disposition']
    assert cd.startswith('attachment')
    # 中文名走 RFC5987 的 filename*（百分号编码），filename= 只留 ASCII 回退
    assert quote(FILE_NAME) in cd


# ── 小组网盘（同款写法，独立回归）───────────────────

def test_group_drive_inline_preview_omits_content_disposition(app):
    r = _student_client(app).get(_group_url(app) + '?inline=1')

    assert r.status_code == 200
    assert 'Content-Disposition' not in r.headers
    assert r.data == PDF_BYTES


def test_group_drive_download_branch_still_attaches(app):
    r = _student_client(app).get(_group_url(app))

    assert r.status_code == 200
    assert r.headers['Content-Disposition'].startswith('attachment')


# ── 活动文档 / 作品文件（activities.py 三处同款写法）────

def test_activity_document_inline_preview_omits_content_disposition(app):
    r = _client(app).get(_activity_url(app) + '?inline=1')

    assert r.status_code == 200
    assert 'Content-Disposition' not in r.headers
    assert r.data == PDF_BYTES


def test_activity_document_download_branch_still_attaches(app):
    r = _client(app).get(_activity_url(app))

    assert r.status_code == 200
    assert r.headers['Content-Disposition'].startswith('attachment')


def test_work_file_inline_preview_omits_content_disposition(app):
    r = _client(app).get(_work_url(app) + '?inline=1')

    assert r.status_code == 200
    assert 'Content-Disposition' not in r.headers
    assert r.data == PDF_BYTES


def test_public_work_file_inline_preview_omits_content_disposition(app):
    """公开分享路由**无鉴权**，是这三处里对外暴露面最大的一个。"""
    r = app.test_client().get(PUBLIC_WORK_URL + '?inline=1')

    assert r.status_code == 200
    assert 'Content-Disposition' not in r.headers
    assert r.data == PDF_BYTES


# ── 助手本体 ──────────────────────────────────────

def test_strip_helper_is_idempotent_and_narrow():
    """只摘 CD，不动其它头；对没有 CD 的响应也安全。"""
    from flask import Flask
    from app.utils import strip_inline_content_disposition

    resp = Flask(__name__).response_class(b'x')
    resp.headers['Content-Disposition'] = 'inline; filename=a.bin'
    resp.headers['Content-Type'] = 'application/octet-stream'

    strip_inline_content_disposition(resp)
    assert 'Content-Disposition' not in resp.headers
    assert resp.headers['Content-Type'] == 'application/octet-stream'

    # 二次调用（以及原本就没有 CD 的响应）不得抛错
    strip_inline_content_disposition(resp)
