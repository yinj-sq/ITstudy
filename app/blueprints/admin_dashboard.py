# -*- coding: utf-8 -*-
"""管理员“管理总览”：首次部署检查、首用步骤与关键指标。"""
import os
import shutil
from datetime import datetime, timedelta

from flask import Blueprint, current_app, render_template

from app.decorators import admin_login_required
from app.models import (AIConfig, AccountSession, Class, ClassSchedule,
                        ClassroomSession, Resource, Student, Teacher,
                        TeachingSession)
from app.utils import is_default_admin_account

admin_dashboard_bp = Blueprint('admin_dashboard', __name__, url_prefix='')

_STATIC_CHECKS = (
    ('化学仿真', 'chem-lab/ketcher/index.html'),
    ('硬件仿真', 'hardware-sim/mmake/index.html'),
    ('ESP32-S3 仿真', 'hardware-sim/esp32-s3/index.html'),
    ('GeoGebra 离线包', 'geogebra/GeoGebra/deployggb.js'),
)


@admin_dashboard_bp.route('/admin/dashboard')
@admin_login_required
def admin_dashboard():
    base_dir = os.path.dirname(current_app.root_path)
    static_dir = current_app.static_folder
    now = datetime.now()

    classes = Class.query.count()
    teachers = Teacher.query.count()
    students = Student.query.count()
    resources = Resource.query.count()
    class_schedules = ClassSchedule.query.count()
    active_sessions = ClassroomSession.query.filter_by(is_active=True).count()
    teaching_active = TeachingSession.query.filter(
        TeachingSession.end_time.is_(None)).count()

    missing_static = [label for label, rel in _STATIC_CHECKS
                      if not os.path.isfile(os.path.join(static_dir, rel))]
    has_precompressed = os.path.isfile(
        os.path.join(static_dir, 'js', 'ai-chat.js.gz'))
    try:
        disk = shutil.disk_usage(base_dir)
        free_pct = disk.free / disk.total * 100
    except Exception:
        free_pct = None
    proxy_ok = bool(current_app.config.get('TRUST_PROXY_HEADERS'))
    ai_config = AIConfig.query.first()
    ai_enabled = bool(ai_config and ai_config.enabled)
    default_password = is_default_admin_account()
    active_terminals = AccountSession.query.filter(
        AccountSession.logout_at.is_(None),
        AccountSession.last_seen_at >= now - timedelta(minutes=10)).count()
    today_start = datetime(now.year, now.month, now.day)
    today_logins = AccountSession.query.filter(
        AccountSession.login_at >= today_start).count()

    def item(key, label, status, detail, url='', action=''):
        return {'key': key, 'label': label, 'status': status,
                'detail': detail, 'url': url, 'action': action}

    checks = [
        item('class', '账号与班级',
             'ok' if classes else 'warn',
             (f'已建 {classes} 个班级；学生可在「学生信息」用 Excel 批量导入'
              if classes else
              '还没有班级：先建班，再在「学生信息」下载模板批量导入学生'),
             '/admin/classes', '去建班'),
        item('teachers', '教师账号',
             'ok' if teachers else 'warn',
             (f'已有 {teachers} 个教师账号' if teachers else
              '还没有教师账号；创建时需分配学科、年级和任课班级'),
             '/admin/teacher_account', '去创建'),
        item('students', '学生账号',
             'ok' if students else 'warn',
             (f'已导入 {students} 名学生' if students else
              '还没有学生账号；可在「学生信息」用 Excel/文本批量导入'
              '（模板：学号/姓名/班级/年级）'),
             '/admin/students', '去导入'),
        item('resources', '教学资源',
             'ok' if resources else 'warn',
             f'已有 {resources} 个资源' if resources else '还没有上传教学资源',
             '/admin/resources/upload_page', '上传资源'),
        item('schedule', '课程表',
             'ok' if class_schedules else 'manual',
             (f'已配置 {class_schedules} 条课程安排' if class_schedules else
              '可选：管理员可统一配置，教师也可在「作息/课表」添加本人班级；'
              '未配置时仍可手动开启课堂'),
             '/admin/class_schedule', '去配置'),
        item('static', '仿真/离线产物',
             'ok' if not missing_static else 'warn',
             '化学、硬件、ESP32-S3、GeoGebra 资源齐全' if not missing_static
             else '缺少：' + '、'.join(missing_static),
             '/admin/system', '检查部署'),
        item('precompress', '静态预压缩',
             'ok' if has_precompressed else 'warn',
             '检测到 .gz 预压缩产物' if has_precompressed
             else '未检测到预压缩产物，可运行 tools/precompress_static.py',
             '/admin/system', '查看说明'),
        item('proxy', '登录 IP 归因',
             'ok' if proxy_ok else 'warn',
             '已信任反向代理头' if proxy_ok
             else '未启用 TRUST_PROXY_HEADERS；经 Nginx 部署时审计 IP 可能为代理地址',
             '/admin/account-trail', '查看轨迹'),
        item('password', '管理员口令',
             'warn' if default_password else 'ok',
             '仍为默认 admin/admin123，请立即修改' if default_password
             else '已使用非默认管理员口令',
             '/admin/accounts', '修改口令'),
        item('disk', '磁盘空间',
             'ok' if free_pct is None or free_pct >= 10 else 'warn',
             '无法读取磁盘' if free_pct is None
             else f'剩余 {free_pct:.0f}%（{disk.free / (1024**3):.1f} GB）',
             '/admin/backup', '备份'),
        item('backup', '数据备份', 'manual',
             '建议定期在备份页下载数据库与上传目录压缩包',
             '/admin/backup', '去备份'),
        item('time', '服务器时间', 'manual',
             f'当前 {now:%Y-%m-%d %H:%M:%S}；请确认系统时间同步（NTP）',
             '', ''),
        item('ai', 'AI 助手', 'ok' if ai_enabled else 'manual',
             '已启用' if ai_enabled else '未启用（可选）',
             '/admin/ai_config', '去配置'),
    ]

    steps = [
        {'label': '建班级', 'done': classes > 0,
         'url': '/admin/classes', 'detail': f'{classes} 个班级'},
        {'label': '建教师账号', 'done': teachers > 0,
         'url': '/admin/teacher_account',
         'detail': '分配学科、年级和任课班级'},
        {'label': '导入学生', 'done': students > 0,
         'url': '/admin/students',
         'detail': f'{students} 名学生；支持 Excel/文本批量导入'},
        {'label': '上传资源', 'done': resources > 0,
         'url': '/admin/resources/upload_page', 'detail': f'{resources} 个资源'},
        {'label': '配置课程表（可选）', 'done': class_schedules > 0,
         'optional': True, 'url': '/admin/class_schedule',
         'detail': '管理员统一配置，或教师在「作息/课表」添加本人班级；'
                   '未配置也可手动开课堂'},
        {'label': '开始课堂', 'done': active_sessions > 0 or teaching_active > 0,
         'url': '/admin/classroom',
         'detail': f'{active_sessions} 个班级大屏开启'},
    ]

    return render_template(
        'admin_dashboard.html', now=now, checks=checks, steps=steps,
        classes=classes, students=students, resources=resources,
        active_sessions=active_sessions, active_terminals=active_terminals,
        today_logins=today_logins, missing_static=missing_static,
        free_pct=free_pct, ai_enabled=ai_enabled)
