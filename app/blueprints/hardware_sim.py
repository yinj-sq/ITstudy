# -*- coding: utf-8 -*-
"""硬件仿真入口：图形编程仿真 / ESP32-S3 仿真。"""
from flask import Blueprint, render_template, session

from app.decorators import authenticated_required

hardware_sim_bp = Blueprint('hardware_sim', __name__, url_prefix='')


def _hardware_sim_uid():
    """按登录账号生成静态应用本地存储的命名空间。"""
    if session.get('student_id'):
        return f'student_{session["student_id"]}'
    if session.get('teacher_id'):
        return f'teacher_{session["teacher_id"]}'
    if session.get('admin_account_id'):
        return f'admin_{session["admin_account_id"]}'
    return 'admin'  # 兼容没有 admin_account_id 的旧会话


@hardware_sim_bp.route('/hardware-sim', strict_slashes=False)
@authenticated_required
def hardware_sim():
    return render_template('hardware_sim.html', hw_uid=_hardware_sim_uid())
