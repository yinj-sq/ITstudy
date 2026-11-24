import json
import re
from html import escape
from html.parser import HTMLParser
from markupsafe import Markup


_ALLOWED_TAGS = {
    'a', 'br', 'blockquote', 'code', 'div', 'em', 'i', 'img', 'li', 'ol',
    'p', 'pre', 'span', 'strong', 'b', 'table', 'tbody', 'td', 'th',
    'thead', 'tr', 'u', 'ul', 'hr'
}
_GLOBAL_ATTRS = {'class', 'id', 'title'}
_TAG_ATTRS = {
    'a': {'href', 'target', 'rel'},
    'img': {'src', 'alt', 'width', 'height'},
    'td': {'colspan', 'rowspan'},
    'th': {'colspan', 'rowspan'},
}
_VOID_TAGS = {'br', 'hr', 'img'}


def _is_safe_url(value, image=False):
    if not value:
        return False
    value = value.strip()
    if re.search(r'[\x00-\x1f\x7f]', value):
        return False
    if value.startswith('#'):
        return True
    if value.startswith('/') and not value.startswith('//'):
        return True
    if not value.startswith('//') and not re.match(r'^[a-z][a-z0-9+.-]*:', value, re.I):
        return True
    if re.match(r'^https?://', value, re.I):
        return True
    if not image and re.match(r'^mailto:', value, re.I):
        return True
    if image and re.match(r'^data:image/(png|jpe?g|gif|webp);base64,[a-z0-9+/=\s]+$', value, re.I):
        return True
    return False


class _RichTextSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.parts = []

    def _append_start_tag(self, tag, attrs, closed=False):
        tag = tag.lower()
        if tag not in _ALLOWED_TAGS:
            return
        clean_attrs = []
        allowed_attrs = _GLOBAL_ATTRS | _TAG_ATTRS.get(tag, set())
        for name, value in attrs:
            name = (name or '').lower()
            value = '' if value is None else str(value)
            if name.startswith('on') or name == 'style' or name not in allowed_attrs:
                continue
            if name in ('href', 'src') and not _is_safe_url(value, image=(tag == 'img')):
                continue
            if name == 'target' and value not in ('_blank', '_self'):
                continue
            clean_attrs.append(f'{name}="{escape(value, quote=True)}"')
        if tag == 'a':
            attr_names = {a.split('=', 1)[0] for a in clean_attrs}
            if 'rel' not in attr_names:
                clean_attrs.append('rel="noopener noreferrer"')
        attr_text = (' ' + ' '.join(clean_attrs)) if clean_attrs else ''
        suffix = ' />' if closed or tag in _VOID_TAGS else '>'
        self.parts.append(f'<{tag}{attr_text}{suffix}')

    def handle_starttag(self, tag, attrs):
        self._append_start_tag(tag, attrs)

    def handle_startendtag(self, tag, attrs):
        self._append_start_tag(tag, attrs, closed=True)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _ALLOWED_TAGS and tag not in _VOID_TAGS:
            self.parts.append(f'</{tag}>')

    def handle_data(self, data):
        self.parts.append(escape(data))

    def handle_entityref(self, name):
        self.parts.append(f'&{name};')

    def handle_charref(self, name):
        self.parts.append(f'&#{name};')


def sanitize_rich_text(text):
    """清洗题目富文本，保留安全排版标签并移除脚本/事件属性。"""
    if not text:
        return Markup('')
    parser = _RichTextSanitizer()
    parser.feed(str(text))
    parser.close()
    # parser.parts 仅包含白名单标签和经过 html.escape 的文本/属性。
    return Markup(''.join(parser.parts))  # nosec B704


def convert_md_images(text):
    """将Markdown格式的图片链接转换为HTML中的img标签"""
    if not text:
        return Markup("")
    pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
    parts = []
    pos = 0
    for match in re.finditer(pattern, str(text)):
        parts.append(escape(str(text)[pos:match.start()]))
        alt_text = match.group(1).strip() or '图片'
        url = match.group(2).strip()
        if _is_safe_url(url, image=True):
            parts.append(
                f'<img src="{escape(url, quote=True)}" '
                f'alt="{escape(alt_text, quote=True)}" class="img-fluid">'
            )
        else:
            parts.append(escape(match.group(0)))
        pos = match.end()
    parts.append(escape(str(text)[pos:]))
    # parts 中的原文、URL 和 alt 均已 escape，只有固定 img 标签为代码生成。
    return Markup(''.join(parts))  # nosec B704


def from_json(value):
    """将JSON字符串转换为Python对象的模板过滤器"""
    try:
        return json.loads(value)
    except Exception:
        return {}


def chr_filter(value, code=None):
    """将ASCII码转换为对应字符的模板过滤器"""
    if code is not None:
        return chr(code)
    return chr(value)


def ord_filter(value, char=None):
    """将字符转换为ASCII码的模板过滤器"""
    if char is not None:
        return ord(char)
    return ord(value)


def register_filters(app):
    """在 Flask 应用中注册所有 Jinja2 自定义过滤器"""
    app.jinja_env.filters['convert_md_images'] = convert_md_images
    app.jinja_env.filters['sanitize_rich_text'] = sanitize_rich_text
    app.jinja_env.filters['fromjson'] = from_json
    app.jinja_env.filters['chr'] = chr_filter
    app.jinja_env.filters['ord'] = ord_filter
