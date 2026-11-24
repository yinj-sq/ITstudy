# -*- coding: utf-8 -*-
"""仿真实验中心：化学仿真与硬件仿真的统一入口。

只做信息架构合并：两个仿真保留各自路由、权限与数据模型。
"""
from flask import Blueprint, render_template, request

from app.decorators import authenticated_required

sim_lab_bp = Blueprint('sim_lab', __name__, url_prefix='')


@sim_lab_bp.route('/sim-lab', strict_slashes=False)
@authenticated_required
def sim_lab():
    tab = (request.args.get('tab') or 'chem').strip().lower()
    if tab not in ('chem', 'hardware'):
        tab = 'chem'
    return render_template('sim_lab.html', active_tab=tab)
