# -*- coding: utf-8 -*-
"""安装/卸载上传数据目录回归（2026-10-21）。

真实上传根目录是 static\\uploads（以及 homework/submissions/chunks/
question_img），旧版根目录 uploads 仅用于历史外链 .url。安装器必须预建
真实数据目录，卸载「保留数据」必须保留 static 整树，避免出现"留下的
uploads 是空目录、真实数据反而丢掉"的误解与风险。
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
NSI = ROOT / 'pack' / 'installer.nsi'


def test_installer_creates_real_upload_dirs_not_legacy_root():
    src = NSI.read_text(encoding='utf-8')
    for rel in ('static\\uploads', 'static\\homework', 'static\\submissions',
                'static\\chunks', 'static\\question_img'):
        assert f'CreateDirectory "$INSTDIR\\{rel}"' in src
    assert 'CreateDirectory "$INSTDIR\\uploads"' not in src


def test_uninstall_keeps_static_uploads_and_cleans_legacy_root():
    src = NSI.read_text(encoding='utf-8')
    keep = src[src.index('  keep_data:'):src.index('  del_prog:')]
    assert 'RMDir /r "$INSTDIR\\static"' not in keep
    # 旧版根 uploads 仅在为空时移除，含历史 .url 时保留
    assert 'RMDir "$INSTDIR\\uploads"' in keep

    delete = src[src.index('  del_data:'):src.index('  keep_data:')]
    assert 'RMDir /r "$INSTDIR\\static"' in delete
    assert 'RMDir /r "$INSTDIR\\uploads"' in delete

    assert 'static\\uploads 等上传数据' in src
