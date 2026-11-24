# -*- coding: utf-8 -*-
"""流程图「导出 JSON」归类回归（2026-11-04）。

UX 约定：输入（打开/导入）与输出（保存图片/导出 JSON/分享）分组清晰。
- 「导出 JSON」从「打开 / 导入」弹窗移到顶部工具栏，与「保存图片」相邻；
- 导入弹窗仅保留「选文件 / 导入到画布」；
- 新增按钮后原 1200px 紧凑断点前移至 1320px，避免 1240–1280 宽度溢出；
- 思维导图工具已采用独立「导出」菜单（一致性参照）。
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
FLOW = ROOT / 'static' / 'lesson-tools' / 'flow' / 'index.html'
MINDMAP = ROOT / 'static' / 'lesson-tools' / 'mindmap' / 'index.html'


def test_export_json_grouped_with_save_image():
    html = FLOW.read_text(encoding='utf-8')
    # 顶部工具栏：保存图片后紧跟 JSON 导出（同一输出分组）
    assert 'id="btnExport"' in html
    assert 'id="btnExportJson"' in html
    assert html.index('id="btnExport"') < html.index('id="btnExportJson"')
    assert html.index('id="btnExportJson"') < html.index('id="btnImport"')
    # 打开 / 导入弹窗内不再出现导出入口
    start = html.index('id="ioModal"')
    end = html.index('id="aiModal"')
    io_block = html[start:end]
    assert 'ioJson' not in io_block
    assert '导出 JSON' not in io_block
    # JS 绑定指向顶部按钮
    assert '$("#btnExportJson").onclick = exportJSON;' in html
    assert '#ioJson' not in html
    # 紧凑断点覆盖新增按钮，避免中等宽度溢出
    assert '@media (max-width:1320px)' in html


def test_mindmap_has_dedicated_export_menu():
    """思维导图工具以独立「导出」菜单承载图片/备份等输出（一致性依据）。"""
    html = MINDMAP.read_text(encoding='utf-8')
    assert 'data-menu="export"' in html
    assert 'data-menu="doc"' in html
