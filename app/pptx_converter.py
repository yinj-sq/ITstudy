"""
PPTX → PPTist JSON 转换器

将上传的 .pptx 文件转换为 PPTist 兼容的内部 JSON 格式。
转换后的 JSON 直接存入数据库，供前端 PPTist 编辑器加载。
"""
import base64
import html as html_mod
import io
import json
import logging
import secrets
import string

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

logger = logging.getLogger(__name__)

# ── helpers ──────────────────────────────────────────────

def _random_id(length=10):
    """生成随机 ID（与 PPTist 前端一致）"""
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))


def _emu_to_px(emu):
    """EMU → 像素（PPTist 默认 96 DPI）"""
    if emu is None:
        return 0
    return round(emu / 9525)  # 1px ≈ 9525 EMU at 96 DPI


def _rgb_to_hex(rgb):
    """RGB 元组 → #rrggbb"""
    if rgb is None:
        return None
    return '#{:02x}{:02x}{:02x}'.format(*rgb)


def _get_fill_info(shape):
    """提取形状填充信息"""
    try:
        fill = shape.fill
        if fill.type is None:
            return None
        if hasattr(fill, 'fore_color') and fill.fore_color and fill.fore_color.type is not None:
            try:
                return _rgb_to_hex(fill.fore_color.rgb)
            except Exception:
                logger.debug('无法读取形状前景色 RGB', exc_info=True)
    except Exception:
        logger.debug('无法读取形状填充信息', exc_info=True)
    return None


def _build_text_content(para):
    """将 python-pptx 段落转换为 PPTist HTML 内容"""
    runs_html = []
    for run in para.runs:
        text = html_mod.escape(run.text)
        if not text:
            continue
        if run.font.bold:
            text = f'<strong>{text}</strong>'
        if run.font.italic:
            text = f'<em>{text}</em>'
        if run.font.size:
            size_pt = run.font.size.pt
            text = f'<span style="font-size: {size_pt}px;">{text}</span>'
        try:
            if run.font.color and run.font.color.type is not None:
                color = _rgb_to_hex(run.font.color.rgb)
                if color:
                    text = f'<span style="color: {color};">{text}</span>'
        except Exception:
            logger.debug('字体颜色解析失败（_PrstColor 等无 rgb 属性），已忽略', exc_info=True)
        runs_html.append(text)
    return ''.join(runs_html)


def _extract_text_elements(shape, slide_width_px, slide_height_px):
    """从形状中提取文本元素"""
    elements = []
    if not shape.has_text_frame:
        return elements

    tf = shape.text_frame
    left = _emu_to_px(shape.left)
    top = _emu_to_px(shape.top)
    width = _emu_to_px(shape.width)
    height = _emu_to_px(shape.height)

    paragraphs_html = []
    for para in tf.paragraphs:
        content = _build_text_content(para)
        if content.strip():
            # Handle alignment
            align = 'left'
            if para.alignment is not None:
                align_map = {0: 'left', 1: 'center', 2: 'right', 3: 'justify'}
                align = align_map.get(para.alignment, 'left')
            paragraphs_html.append(f'<p style="text-align: {align};">{content}</p>')

    if not paragraphs_html:
        return elements

    content = ''.join(paragraphs_html)

    element = {
        'type': 'text',
        'id': _random_id(),
        'left': left,
        'top': top,
        'width': width,
        'height': height,
        'content': content,
        'rotate': round(shape.rotation, 1) if shape.rotation else 0,
        'defaultFontName': '',
        'defaultColor': '#333',
        'lineHeight': 1.2,
    }
    elements.append(element)
    return elements


def _extract_image_elements(shape, slide_width_px, slide_height_px):
    """从形状中提取图片元素（base64 内嵌）"""
    elements = []
    if shape.shape_type != MSO_SHAPE_TYPE.PICTURE:
        return elements

    try:
        image = shape.image
        image_bytes = image.blob
        ext = image.content_type.split('/')[-1]
        if ext == 'jpeg':
            ext = 'jpg'
        b64 = base64.b64encode(image_bytes).decode('ascii')
        src = f'data:image/{ext};base64,{b64}'

        left = _emu_to_px(shape.left)
        top = _emu_to_px(shape.top)
        width = _emu_to_px(shape.width)
        height = _emu_to_px(shape.height)

        element = {
            'type': 'image',
            'id': _random_id(),
            'left': left,
            'top': top,
            'width': width,
            'height': height,
            'src': src,
            'fixedRatio': True,
            'rotate': round(shape.rotation, 1) if shape.rotation else 0,
        }
        elements.append(element)
    except Exception:
        logger.debug('提取图片元素失败', exc_info=True)
    return elements


def _extract_shape_elements(shape, slide_width_px, slide_height_px):
    """提取自选图形 / 占位符"""
    elements = []
    if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
        return elements
    if shape.has_text_frame and shape.text_frame.text.strip():
        return elements  # 文本单独处理

    fill = _get_fill_info(shape)
    if fill is None:
        return elements

    left = _emu_to_px(shape.left)
    top = _emu_to_px(shape.top)
    width = _emu_to_px(shape.width)
    height = _emu_to_px(shape.height)

    # 使用矩形路径
    element = {
        'type': 'shape',
        'id': _random_id(),
        'left': left,
        'top': top,
        'width': width,
        'height': height,
        'viewBox': [200, 200],
        'path': 'M 0 0 L 200 0 L 200 200 L 0 200 Z',
        'fill': fill,
        'fixedRatio': False,
        'rotate': round(shape.rotation, 1) if shape.rotation else 0,
    }
    elements.append(element)
    return elements


def convert_pptx_to_pptist_json(file_content):
    """
    将 PPTX 二进制内容转换为 PPTist 兼容 JSON 字符串

    返回: (json_string, error_string)
      - 成功时 error_string 为 None
      - 失败时 json_string 为 None
    """
    # 防御性限制：恶意/异常 PPTX（zip 炸弹、巨量形状或超大图片）会造成
    # 解析期 CPU 耗尽与结果 JSON 无界膨胀（该 JSON 直接存库）
    MAX_PPTX_SIZE = 30 * 1024 * 1024          # 原始文件上限 30MB
    MAX_SLIDES = 200
    MAX_SHAPES_PER_SLIDE = 500
    MAX_IMAGE_SIZE = 5 * 1024 * 1024          # 单张图片上限 5MB（超出跳过）
    MAX_IMAGE_TOTAL = 100 * 1024 * 1024       # 全部图片累计上限 100MB
    MAX_OUTPUT_JSON = 50 * 1024 * 1024        # 输出 JSON 上限 50MB（直接存库）

    if len(file_content) > MAX_PPTX_SIZE:
        return None, f'PPTX 文件超过 {MAX_PPTX_SIZE // (1024 * 1024)}MB 限制'
    # zip 炸弹预扫描：30MB 压缩包可解压出数 GB（python-pptx 按成员整体解压，
    # 单张图片 blob 先解压再比大小），此处按中央目录元数据先做总量/压缩比校验
    import zipfile as _zipfile
    _MAX_ENTRIES = 5000
    _MAX_ENTRY_SIZE = 200 * 1024 * 1024
    _MAX_TOTAL_SIZE = 500 * 1024 * 1024
    _MAX_RATIO = 300
    try:
        with _zipfile.ZipFile(io.BytesIO(file_content)) as _zf:
            _infos = _zf.infolist()
            if len(_infos) > _MAX_ENTRIES:
                return None, f'PPTX 内部条目过多（>{_MAX_ENTRIES}），疑似恶意文件'
            _total = 0
            for _info in _infos:
                if _info.file_size > _MAX_ENTRY_SIZE:
                    return None, f'PPTX 单个内部文件过大（>{_MAX_ENTRY_SIZE // (1024 * 1024)}MB）'
                _total += _info.file_size
                if _total > _MAX_TOTAL_SIZE:
                    return None, f'PPTX 解压总量过大（>{_MAX_TOTAL_SIZE // (1024 * 1024)}MB）'
                if _info.compress_size > 0 and \
                        _info.file_size / _info.compress_size > _MAX_RATIO:
                    return None, 'PPTX 压缩比异常（疑似 zip 炸弹），已拒绝'
    except Exception:
        pass  # 非标准 zip 由下方 Presentation 解析兜底
    try:
        prs = Presentation(io.BytesIO(file_content))
    except Exception as e:
        logging.getLogger(__name__).warning('解析 PPTX 失败: %s', e, exc_info=True)
        return None, '无法解析 PPTX 文件，请确认文件格式正确'

    slide_width_px = _emu_to_px(prs.slide_width)
    slide_height_px = _emu_to_px(prs.slide_height)

    slides = []
    image_bytes_total = 0
    for slide_index, slide in enumerate(prs.slides):
        if slide_index >= MAX_SLIDES:
            logger.warning('PPTX 幻灯片数量超过 %d 张，已截断', MAX_SLIDES)
            break
        elements = []

        for shape_index, shape in enumerate(slide.shapes):
            if shape_index >= MAX_SHAPES_PER_SLIDE:
                logger.warning('单张幻灯片形状数量超过 %d 个，已截断', MAX_SHAPES_PER_SLIDE)
                break
            # 图片（重复分支已合并；单张 >5MB 跳过，累计 >100MB 拒绝）
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                try:
                    blob = shape.image.blob
                    if len(blob) > MAX_IMAGE_SIZE:
                        logger.warning('跳过超大图片（>5MB）: slide=%d shape=%d',
                                       slide_index + 1, shape_index + 1)
                        continue
                    image_bytes_total += len(blob)
                    if image_bytes_total > MAX_IMAGE_TOTAL:
                        return None, f'PPTX 图片总字节数超过 {MAX_IMAGE_TOTAL // (1024 * 1024)}MB 限制'
                except Exception:
                    pass
                elements.extend(_extract_image_elements(shape, slide_width_px, slide_height_px))
                continue

            # 文本
            if shape.has_text_frame and shape.text_frame.text.strip():
                elements.extend(_extract_text_elements(shape, slide_width_px, slide_height_px))

            # 形状（无文本的色块等）
            fill = _get_fill_info(shape)
            if fill and not (shape.has_text_frame and shape.text_frame.text.strip()):
                elements.extend(_extract_shape_elements(shape, slide_width_px, slide_height_px))

        # 背景
        background = {'type': 'solid', 'color': '#ffffff'}
        try:
            bg = slide.background
            if bg.fill and bg.fill.type is not None:
                try:
                    color = _rgb_to_hex(bg.fill.fore_color.rgb)
                    if color:
                        background = {'type': 'solid', 'color': color}
                except Exception:
                    logger.debug('幻灯片背景色解析失败', exc_info=True)
        except Exception:
            logger.debug('幻灯片背景提取失败', exc_info=True)

        slide_obj = {
            'id': _random_id(),
            'elements': elements,
            'background': background,
            'remark': '',
        }

        # 备注
        try:
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                slide_obj['remark'] = slide.notes_slide.notes_text_frame.text.strip()
        except Exception:
            logger.debug('幻灯片备注提取失败', exc_info=True)

        slides.append(slide_obj)

    result = json.dumps(slides, ensure_ascii=False, separators=(',', ':'))
    # 输出 JSON 总量封顶（存 PostgreSQL TEXT，无界膨胀会拖垮数据库）
    if len(result.encode('utf-8')) > MAX_OUTPUT_JSON:
        return None, f'转换结果超过 {MAX_OUTPUT_JSON // (1024 * 1024)}MB 上限，请精简 PPT 后重试'
    return result, None
