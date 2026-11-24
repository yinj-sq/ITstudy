# -*- coding: utf-8 -*-
"""管理员全局破坏性动作隔离库实测（2026-10-19）。

在 conftest 钉住的 itstudy_test 上真实执行：
操作日志清空、在线学生清空、新一课清空签到、课程表清空、作息表全量导入、
课程表导入、网盘闲置文件立即清理、系统开关保存、全局网盘配额保存、
网盘清理配置保存、Python 孤儿文件清理。结束后恢复配置与课堂设置。
"""
import io
import pathlib
import uuid
from unittest.mock import patch
from datetime import datetime, timedelta

import openpyxl

from app import create_app
from app.extensions import db
from app.models import (Class, ClassSchedule, ClassroomSession,
                        ClassroomSetting, Log, Schedule,
                        Student, StudentDriveFile, SystemConfig)
from sqlalchemy import or_
from app.services.student_drive_service import get_cleanup_config

ROOT = pathlib.Path(__file__).resolve().parent.parent
UPLOADS = ROOT / 'static' / 'uploads'
CLASS_NAME = '破坏测试班'
STUDENT_NUMBER = '破坏测试生'
OLD_PERIOD = '破坏测试旧节次'
IMPORTED_PERIOD = '破坏测试导入节次'
IMPORT_CLASS = '破坏测试导入班'
CSRF = 't'


def _cleanup_app_data():
    setting = ClassroomSetting.query.first()
    if setting:
        setting.active_class_id = None
        setting.current_schedule_id = None
    for row in StudentDriveFile.query.filter(
            StudentDriveFile.original_filename.like('破坏测试%')).all():
        if row.file_path:
            (ROOT / 'static' / 'uploads' / row.file_path).unlink(missing_ok=True)
        db.session.delete(row)
    db.session.query(Log).filter(or_(Log.action.like('破坏测试%'),
                                     Log.action == '清除日志')).delete(
        synchronize_session=False)
    db.session.query(ClassSchedule).filter(
        ClassSchedule.class_name.in_([CLASS_NAME, IMPORT_CLASS])).delete(
        synchronize_session=False)
    db.session.query(Schedule).filter(
        Schedule.period_name.in_([OLD_PERIOD, IMPORTED_PERIOD])).delete(
        synchronize_session=False)
    db.session.query(Student).filter_by(student_number=STUDENT_NUMBER).delete(
        synchronize_session=False)
    test_class_ids = [cid for (cid,) in db.session.query(Class.id).filter(
        Class.name.in_([CLASS_NAME, IMPORT_CLASS])).all()]
    if test_class_ids:
        db.session.query(ClassroomSession).filter(
            ClassroomSession.class_id.in_(test_class_ids)).delete(
            synchronize_session=False)
    db.session.query(Class).filter(
        Class.name.in_([CLASS_NAME, IMPORT_CLASS])).delete(
        synchronize_session=False)
    db.session.commit()


def _post(client, path, data=None, files=None):
    data = dict(data or {})
    data['csrf_token'] = CSRF
    if files:
        data.update(files)
        return client.post(path, data=data,
                           content_type='multipart/form-data',
                           headers={'X-CSRFToken': CSRF})
    return client.post(path, data=data, headers={'X-CSRFToken': CSRF})


def test_admin_global_destructive_actions(tmp_path):
    app = create_app()
    with app.app_context():
        _cleanup_app_data()
        setting = ClassroomSetting.query.first()
        original_setting = None
        if setting:
            original_setting = (setting.active_class_id, setting.current_schedule_id,
                                setting.display_message, setting.seat_offset,
                                setting.auto_switch)
        else:
            setting = ClassroomSetting()
            db.session.add(setting)
        original_config = {
            key: SystemConfig.get(key)
            for key in ('student_access_enabled', 'admin_remote_enabled',
                        'class_buttons_enabled', 'courseware_public_enabled',
                        'drive_default_quota_mb', 'drive_cleanup_enabled',
                        'drive_cleanup_idle_days', 'drive_cleanup_interval_hours')
        }
        cls = Class(name=CLASS_NAME, description='破坏性动作测试')
        db.session.add(cls)
        db.session.flush()
        student = Student(name=STUDENT_NUMBER, student_number=STUDENT_NUMBER,
                          student_class=CLASS_NAME, class_id=cls.id,
                          has_changed_password=True)
        student.set_password('student-pass')
        db.session.add(student)
        db.session.flush()
        setting.active_class_id = cls.id
        drive_dir = UPLOADS / 'drive' / str(student.id)
        drive_dir.mkdir(parents=True, exist_ok=True)
        drive_file = drive_dir / '破坏测试网盘.txt'
        drive_file.write_bytes(b'old drive file')
        drive = StudentDriveFile(
            student_id=student.id, sender_type='student', sender_name=student.name,
            filename='破坏测试网盘.txt', original_filename='破坏测试网盘.txt',
            file_size=14, file_path=f'drive/{student.id}/破坏测试网盘.txt',
            source_type='student_upload',
            created_at=datetime.now() - timedelta(days=200))
        db.session.add(drive)
        db.session.add(Schedule(period_name=OLD_PERIOD, start_time='07:00',
                                end_time='07:45', sort_order=9999, is_active=True))
        db.session.add(ClassSchedule(weekday=6, period_number=99,
                                     class_name=CLASS_NAME))
        db.session.add(Log(user_id=0, user_type='admin', action='破坏测试日志',
                           detail='待清空', time=datetime.now()))
        db.session.commit()
        sid = student.id
        drive_id = drive.id

    client = app.test_client()
    with client.session_transaction() as sess:
        sess['is_admin'] = True
        sess['admin_name'] = '破坏测试管理员'
        sess['csrf_token'] = CSRF

    try:
        # 1) 在线学生清空
        with app.app_context():
            s = db.session.get(Student, sid)
            s.last_seen = datetime.now()
            s.login_time = datetime.now()
            s.ip_address = '10.0.0.9'
            db.session.commit()
        resp = _post(client, '/admin/online_students/clear')
        assert resp.status_code in (302, 303)
        with app.app_context():
            s = db.session.get(Student, sid)
            assert s.last_seen is not None and s.last_seen < datetime.now() - timedelta(days=300)

        # 2) 新一课清空签到
        with app.app_context():
            s = db.session.get(Student, sid)
            s.last_seen = datetime.now()
            s.login_time = datetime.now()
            s.ip_address = '10.0.0.10'
            db.session.commit()
        resp = _post(client, '/admin/classroom/new_session')
        assert resp.status_code in (302, 303)
        with app.app_context():
            s = db.session.get(Student, sid)
            assert s.last_seen is None and s.login_time is None and s.ip_address is None

        # 3) 课程表清空
        resp = _post(client, '/admin/class_schedule/clear')
        assert resp.status_code in (302, 303)
        with app.app_context():
            assert ClassSchedule.query.filter_by(class_name=CLASS_NAME).count() == 0

        # 4) 作息表全量导入（旧作息被替换）
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(['节次名称', '开始时间', '结束时间', '启用'])
        ws.append([IMPORTED_PERIOD, '10:00', '10:45', '是'])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        resp = _post(client, '/admin/schedule/import',
                     files={'file': (buf, 'destructive_schedule.xlsx')})
        assert resp.status_code in (302, 303)
        with app.app_context():
            assert Schedule.query.filter_by(period_name=OLD_PERIOD).count() == 0
            assert Schedule.query.filter_by(period_name=IMPORTED_PERIOD).count() == 1

        # 5) 课程表导入
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(['星期', '节次', '班级'])
        ws.append(['星期一', 1, IMPORT_CLASS])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        with app.app_context():
            db.session.add(Class(name=IMPORT_CLASS, description='导入课程表班级'))
            db.session.commit()
        resp = _post(client, '/admin/class_schedule/import',
                     files={'excel_file': (buf, 'destructive_class_schedule.xlsx')})
        assert resp.status_code in (302, 303)
        with app.app_context():
            assert ClassSchedule.query.filter_by(
                weekday=1, period_number=1, class_name=IMPORT_CLASS).count() == 1

        # 6) 网盘闲置文件立即清理（仅 student_upload）
        resp = _post(client, '/admin/student-drive/cleanup-run', data={})
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload.get('success') and payload.get('data', {}).get('deleted') >= 1
        with app.app_context():
            assert db.session.get(StudentDriveFile, drive_id) is None
        assert not drive_file.exists()

        # 7) 全局网盘配额保存/恢复
        resp = _post(client, '/admin/student-drive/quota/global',
                     {'quota_mb': '123'})
        assert resp.status_code == 200 and resp.get_json().get('success')
        with app.app_context():
            assert SystemConfig.get('drive_default_quota_mb') == '123'
        resp = _post(client, '/admin/student-drive/quota/global',
                     {'quota_mb': '120'})
        assert resp.status_code == 200

        # 8) 网盘清理配置保存/恢复
        resp = _post(client, '/admin/student-drive/cleanup-config', {
            'enabled': 'on', 'idle_days': '120', 'interval_hours': '12'})
        assert resp.status_code == 200 and resp.get_json().get('success')
        with app.app_context():
            cfg = get_cleanup_config()
            assert cfg['enabled'] is True and cfg['idle_days'] == 120
        resp = _post(client, '/admin/student-drive/cleanup-config', {
            'idle_days': '90', 'interval_hours': '24'})
        assert resp.status_code == 200

        # 9) Python 孤儿文件清理
        orphan_dir = UPLOADS / 'python_answers'
        orphan_dir.mkdir(parents=True, exist_ok=True)
        orphan = orphan_dir / f'破坏测试孤儿_{uuid.uuid4().hex[:6]}.py'
        orphan.write_text('print("orphan")', encoding='utf-8')
        resp = _post(client, '/admin/backup/cleanup-python-orphans')
        assert resp.status_code in (302, 303)
        assert not orphan.exists()

        # 10) 系统开关保存（四个键完整提交，避免只提交部分导致其余被置 false）
        resp = _post(client, '/admin/system', {
            'student_access_enabled': '1',
            'admin_remote_enabled': '1',
            'class_buttons_enabled': '1',
            'courseware_public_enabled': '1',
        })
        assert resp.status_code in (302, 303)
        with app.app_context():
            for key in ('student_access_enabled', 'admin_remote_enabled',
                        'class_buttons_enabled', 'courseware_public_enabled'):
                assert SystemConfig.get_bool(key, True) is True

        # 11) 操作日志清空（会保留一条“清除日志”审计记录）
        resp = _post(client, '/admin/logs/clear')
        assert resp.status_code in (302, 303)
        with app.app_context():
            assert Log.query.count() == 1
            assert Log.query.first().action == '清除日志'

        # 12) Python 日志清理：只删除 Python 相关行，普通审计行保留
        test_log = tmp_path / f'破坏测试_{uuid.uuid4().hex[:6]}.log'
        test_log.write_text(
            '普通审计行保留\nPython填空题评分结果: 1\npython_fill 调试\n',
            encoding='utf-8')
        with patch('app.blueprints.logs._log_dir', return_value=str(tmp_path)):
            resp = _post(client, '/admin/python_logs/clear')
        assert resp.status_code in (302, 303)
        remaining = test_log.read_text(encoding='utf-8')
        assert '普通审计行保留' in remaining
        assert 'Python填空题' not in remaining
        assert 'python_fill' not in remaining
        test_log.unlink(missing_ok=True)
    finally:
        with app.app_context():
            _cleanup_app_data()
            if original_setting:
                setting = ClassroomSetting.query.first()
                if setting:
                    (setting.active_class_id, setting.current_schedule_id,
                     setting.display_message, setting.seat_offset,
                     setting.auto_switch) = original_setting
            else:
                setting = ClassroomSetting.query.first()
                if setting:
                    setting.active_class_id = None
                    setting.current_schedule_id = None
                    setting.display_message = ''
                    setting.seat_offset = 0
                    setting.auto_switch = False
            for key, value in original_config.items():
                if value is None:
                    SystemConfig.query.filter_by(key=key).delete()
                else:
                    SystemConfig.set(key, value)
            db.session.commit()
            SystemConfig._invalidate_cache()
