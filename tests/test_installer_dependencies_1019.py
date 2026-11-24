# -*- coding: utf-8 -*-
"""安装依赖漂移回归（2026-10-20 其他设备 No module named 'psycopg'）。

根因：在线安装未带 constraints，Flask-SQLAlchemy 解析到未验证的新版
SQLAlchemy，`postgresql://` 默认驱动与项目安装的 psycopg2 不一致。
本组用例锁定显式驱动、SQLAlchemy 2.0.x 与安装器 constraints 传递。
"""
import pathlib

from app.config import Config

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_sqlalchemy_uri_explicitly_uses_psycopg2():
    assert Config.SQLALCHEMY_DATABASE_URI.startswith('postgresql+psycopg2://')


def test_requirements_pin_sqlalchemy_20_and_constraints_are_packaged():
    requirements = (ROOT / 'requirements.txt').read_text(encoding='utf-8')
    constraints = (ROOT / 'constraints.txt').read_text(encoding='utf-8')
    nsi = (ROOT / 'pack' / 'installer.nsi').read_text(encoding='utf-8')
    assert 'SQLAlchemy>=2.0,<2.1' in requirements
    assert 'sqlalchemy==2.0.52' in constraints
    assert 'File "..\\constraints.txt"' in nsi
    assert '-c "$INSTDIR\\constraints.txt"' in nsi
