# -*- coding: utf-8 -*-
"""题目/子题图片功能回归（2026-10-19 真实环境实测发现）。

1. 综合题子题题干图片上传：add_question.html 用 const 接收 hidden 值，
   随后对同一变量赋值 → Assignment to constant variable，整个表单提交中断。
2. 结果页不执行前端 Markdown 图片转换（考试页有 JS 转换），题干/子题
   题干图片在结果页显示为 Markdown 原文；SSR 改为显式转换 + 净化。
"""
import pathlib

from app.filters import convert_md_images, sanitize_rich_text

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_add_question_sub_image_variable_is_reassignable():
    src = (ROOT / 'templates' / 'add_question.html').read_text(encoding='utf-8')
    assert 'let subImageUrl = sq.querySelector' in src
    assert 'const subImageUrl = sq.querySelector' not in src


def test_markdown_image_filter_chain_renders_safe_img():
    rendered = str(sanitize_rich_text(
        convert_md_images('题目 ![x](/static/question_img/a.png) 结束')))
    assert '<img' in rendered
    assert 'src="/static/question_img/a.png"' in rendered
    assert '![x]' not in rendered
    # 危险协议不得生成 img
    unsafe = str(sanitize_rich_text(
        convert_md_images('![x](javascript:alert(1))')))
    assert '<img' not in unsafe


def test_ssr_exam_and_result_templates_convert_markdown_images():
    for name in ('online_exam.html', 'result.html'):
        src = (ROOT / 'templates' / name).read_text(encoding='utf-8')
        assert 'convert_md_images|sanitize_rich_text' in src, name
    # 结果页必须显式渲染子题题干图片（考试页有、结果页曾漏）
    result_src = (ROOT / 'templates' / 'result.html').read_text(encoding='utf-8')
    assert 'sub_q.image_url' in result_src
