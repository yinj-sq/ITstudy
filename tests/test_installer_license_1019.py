# -*- coding: utf-8 -*-
"""安装包许可证编码回归（2026-10-19 安装向导中文乱码修复）。"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACK = ROOT / 'pack'


def test_installer_license_page_uses_unicode_rtf():
    nsi = (PACK / 'installer.nsi').read_text(encoding='utf-8')
    assert 'MUI_PAGE_LICENSE "license-v6.0.rtf"' in nsi
    assert not (PACK / 'license-v6.0.rtf').read_bytes().startswith(b'\xef\xbb\xbf')
    rtf = (PACK / 'license-v6.0.rtf').read_text(encoding='ascii')
    assert rtf.startswith('{\\rtf1')
    assert '\\u' in rtf


def test_installed_license_text_has_utf8_bom():
    data = (PACK / 'license-v6.0.txt').read_bytes()
    assert data.startswith(b'\xef\xbb\xbf')
    text = data.decode('utf-8-sig')
    assert 'ITstudy' in text and 'YINJUN' in text
