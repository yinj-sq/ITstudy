"""
@file optimize_static.py
@brief 静态资源优化自动化脚本，用于批量处理和优化静态资源
@usage python tools/optimize_static.py [options]
"""
import os
import argparse
import time
import subprocess
import re
import json

# 确保脚本可以从项目根目录运行
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
os.chdir(PROJECT_ROOT)

# 定义静态资源目录
STATIC_DIR = os.path.join(PROJECT_ROOT, 'static')
CSS_DIR = os.path.join(STATIC_DIR, 'css')
JS_DIR = os.path.join(STATIC_DIR, 'js')
IMAGE_DIRS = [
    os.path.join(STATIC_DIR, 'question_img'),
    os.path.join(STATIC_DIR, 'images')
]

# 定义CDN配置文件
CDN_CONFIG_FILE = os.path.join(PROJECT_ROOT, 'cdn_config.json')

def log(message, level='INFO'):
    """输出带时间戳的日志"""
    timestamp = time.strftime('%H:%M:%S', time.localtime())
    print(f"[{timestamp}] [{level}] {message}")

def ensure_dir(directory):
    """确保目录存在"""
    if not os.path.exists(directory):
        os.makedirs(directory)
        log(f"创建目录: {directory}")

def minify_css(source_file, output_file=None):
    """压缩CSS文件"""
    if not output_file:
        name, ext = os.path.splitext(source_file)
        output_file = f"{name}.min{ext}"
    
    try:
        with open(source_file, 'r', encoding='utf-8') as f:
            css = f.read()
        
        # 简单的CSS压缩规则
        css = re.sub(r'\s+', ' ', css)  # 替换多个空白字符为一个空格
        css = re.sub(r'\s*{\s*', '{', css)  # 去除括号前后的空白
        css = re.sub(r'\s*}\s*', '}', css)  # 去除括号前后的空白
        css = re.sub(r'\s*;\s*', ';', css)  # 去除分号前后的空白
        css = re.sub(r'\s*:\s*', ':', css)  # 去除冒号前后的空白
        css = re.sub(r',\s+', ',', css)  # 去除逗号后的空白
        css = re.sub(r'/\*.*?\*/', '', css)  # 去除注释
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(css)
        
        source_size = os.path.getsize(source_file)
        output_size = os.path.getsize(output_file)
        reduction = (source_size - output_size) / source_size * 100 if source_size > 0 else 0
        
        log(f"CSS压缩完成: {source_file} -> {output_file} (减小 {reduction:.1f}%)")
        return True
    except Exception as e:
        log(f"CSS压缩失败: {source_file}, 错误: {str(e)}", "ERROR")
        return False

def minify_js(source_file, output_file=None):
    """压缩JavaScript文件"""
    if not output_file:
        name, ext = os.path.splitext(source_file)
        output_file = f"{name}.min{ext}"
    
    try:
        with open(source_file, 'r', encoding='utf-8') as f:
            js = f.read()
        
        # 简单的JS压缩规则 (注意：这种简单压缩可能对复杂JS代码不够安全)
        js = re.sub(r'//.*?\n', '\n', js)  # 去除单行注释
        js = re.sub(r'/\*.*?\*/', '', js, flags=re.DOTALL)  # 去除多行注释
        js = re.sub(r'\s+', ' ', js)  # 替换多个空白字符为一个空格
        js = re.sub(r';\s*', ';', js)  # 去除分号后的空白
        js = re.sub(r'{\s*', '{', js)  # 去除左花括号后的空白
        js = re.sub(r'\s*}', '}', js)  # 去除右花括号前的空白
        js = re.sub(r',\s*', ',', js)  # 去除逗号后的空白
        js = re.sub(r'\s*\(\s*', '(', js)  # 去除左括号周围的空白
        js = re.sub(r'\s*\)\s*', ')', js)  # 去除右括号周围的空白
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(js)
        
        source_size = os.path.getsize(source_file)
        output_size = os.path.getsize(output_file)
        reduction = (source_size - output_size) / source_size * 100 if source_size > 0 else 0
        
        log(f"JS压缩完成: {source_file} -> {output_file} (减小 {reduction:.1f}%)")
        return True
    except Exception as e:
        log(f"JS压缩失败: {source_file}, 错误: {str(e)}", "ERROR")
        return False

def extract_critical_css(html_file, output_file):
    """从HTML文件中提取关键CSS"""
    try:
        with open(html_file, 'r', encoding='utf-8') as f:
            html = f.read()
        
        # 提取<style>标签中的CSS
        style_tags = re.findall(r'<style[^>]*>(.*?)</style>', html, re.DOTALL)
        
        # 合并所有样式
        critical_css = "\n".join(style_tags)
        
        # 保存提取的CSS
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(critical_css)
        
        log(f"提取关键CSS成功: {html_file} -> {output_file} ({len(critical_css)} 字节)")
        return True
    except Exception as e:
        log(f"提取关键CSS失败: {html_file}, 错误: {str(e)}", "ERROR")
        return False

def process_css_files(extract_critical=False, template_dir=None):
    """处理所有CSS文件"""
    log("开始处理CSS文件...")
    ensure_dir(CSS_DIR)
    
    css_files = [f for f in os.listdir(CSS_DIR) if f.endswith('.css') and not f.endswith('.min.css')]
    if not css_files:
        log("没有找到需要处理的CSS文件")
        return
    
    for css_file in css_files:
        source_file = os.path.join(CSS_DIR, css_file)
        output_file = os.path.join(CSS_DIR, css_file.replace('.css', '.min.css'))
        minify_css(source_file, output_file)
    
    # 提取关键CSS
    if extract_critical and template_dir:
        ensure_dir(os.path.join(CSS_DIR, 'critical'))
        
        if not os.path.exists(template_dir):
            log(f"模板目录不存在: {template_dir}", "ERROR")
            return
            
        # 处理主要模板文件
        base_template = os.path.join(template_dir, 'base.html')
        if os.path.exists(base_template):
            extract_critical_css(
                base_template, 
                os.path.join(CSS_DIR, 'critical', 'base.css')
            )
        
        # 处理其他可能的关键模板
        critical_templates = ['login.html', 'study.html', 'exam.html']
        for template in critical_templates:
            template_path = os.path.join(template_dir, template)
            if os.path.exists(template_path):
                extract_critical_css(
                    template_path,
                    os.path.join(CSS_DIR, 'critical', f"{template.split('.')[0]}.css")
                )

def process_js_files():
    """处理所有JavaScript文件"""
    log("开始处理JavaScript文件...")
    ensure_dir(JS_DIR)
    
    js_files = [f for f in os.listdir(JS_DIR) if f.endswith('.js') and not f.endswith('.min.js')]
    if not js_files:
        log("没有找到需要处理的JavaScript文件")
        return
    
    for js_file in js_files:
        source_file = os.path.join(JS_DIR, js_file)
        output_file = os.path.join(JS_DIR, js_file.replace('.js', '.min.js'))
        minify_js(source_file, output_file)

def generate_cdn_config(use_local=False):
    """生成CDN配置文件。

    注意：cdn_config.json 现为手工维护清单（resource-loader 的 13 项
    多源回退映射含 SRI），本函数内置的 4 项映射仅为初始模板且已过时
    （jquery 实际文件为 jquery-3.7.1.min.js）。为避免每次执行
    optimize_static.py 都把手写清单覆盖回旧模板，仅在文件不存在时生成。"""
    log("生成CDN配置文件...")
    if os.path.exists(CDN_CONFIG_FILE):
        log(f"检测到已存在的 {CDN_CONFIG_FILE}（手工维护的多源回退清单），"
            f"跳过覆盖；如需重置请先手动删除该文件")
        return

    # 定义CDN资源映射
    cdn_map = {
        "bootstrap-css": {
            "cdn": "https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css",
            "local": "/static/bootstrap/css/bootstrap.min.css",
            "integrity": "sha384-T3c6CoIi6uLrA9TneNEoa7RxnatzjcDSCmG1MXxSR1GAsXEV/Dwwykc2MPK8M2HN"
        },
        "bootstrap-js": {
            "cdn": "https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js",
            "local": "/static/bootstrap/js/bootstrap.bundle.min.js",
            "integrity": "sha384-C6RzsynM9kWDrMNeT87bh95OGNyZPhcTNXj1NW7RuBCsyN/o0jlpcV8Qyq46cDfL"
        },
        "fontawesome": {
            "cdn": "https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.4.2/css/all.min.css",
            "local": "/static/fontawesome/css/all.min.css",
            "integrity": "sha384-uLOy0bKRRmFN7n6gSz9KrOvnhL9JQ25GKZSYePHGJeMeZhJb9KeHbQk4ggdhdMEw"
        },
        "jquery": {
            "cdn": "https://cdn.jsdelivr.net/npm/jquery@3.7.1/dist/jquery.min.js",
            "local": "/static/jquery/jquery.min.js",
            "integrity": "sha256-/JqT3SQfawRcv/BIHPThkBvs0OEvtFFmqPF/lYI/Cxo="
        }
    }
    
    # 设置默认优先使用本地或CDN
    if use_local:
        for resource in cdn_map:
            cdn_map[resource]["priority"] = "local"
    else:
        for resource in cdn_map:
            cdn_map[resource]["priority"] = "cdn"
    
    # 保存配置文件
    with open(CDN_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cdn_map, f, indent=2)
    
    log(f"CDN配置文件已生成: {CDN_CONFIG_FILE}")

def optimize_images(convert_to_webp=False, create_thumbnails=False):
    """优化图片资源"""
    log(f"开始优化图片资源 (WebP转换: {'启用' if convert_to_webp else '禁用'}, 缩略图: {'启用' if create_thumbnails else '禁用'})...")
    
    # 使用现有的图片压缩脚本
    try:
        from compress_images import compress_images
        
        for image_dir in IMAGE_DIRS:
            if os.path.exists(image_dir):
                log(f"处理图片目录: {image_dir}")
                compress_images(
                    image_dir, 
                    convert_to_webp=convert_to_webp,
                    create_thumbnails=create_thumbnails,
                    enable_progressive=True,
                    optimize_transparency=True,
                    use_multiprocessing=True
                )
    except ImportError:
        log("未找到compress_images模块，尝试使用命令行方式", "WARNING")
        
        # 尝试使用命令行方式运行图片压缩脚本
        compress_script = os.path.join('tools', 'compress_images.py')
        if os.path.exists(compress_script):
            cmd_args = []
            if convert_to_webp:
                cmd_args.append('--webp')
            if create_thumbnails:
                cmd_args.append('--thumbnails')
            
            cmd_args.extend(['--progressive', '--optimize-transparency', '--multiprocessing'])
            
            cmd = f"python {compress_script} {' '.join(cmd_args)}"
            try:
                subprocess.run(cmd, shell=True, check=True)
                log("图片压缩完成")
            except subprocess.SubprocessError as e:
                log(f"运行图片压缩脚本失败: {str(e)}", "ERROR")
        else:
            log("未找到图片压缩脚本", "ERROR")

def verify_local_resources():
    """验证所有本地资源是否存在"""
    log("验证本地资源完整性...")
    
    required_resources = [
        "bootstrap/css/bootstrap.min.css",
        "bootstrap/js/bootstrap.bundle.min.js",
        "fontawesome/css/all.min.css",
        "jquery/jquery.min.js"
    ]
    
    missing_resources = []
    
    for resource in required_resources:
        resource_path = os.path.join(STATIC_DIR, resource)
        if not os.path.exists(resource_path):
            missing_resources.append(resource)
            log(f"缺少资源: {resource}", "WARNING")
    
    if missing_resources:
        log(f"发现 {len(missing_resources)} 个缺失资源，请确保这些文件存在于static目录下", "WARNING")
        return False
    else:
        log("所有本地资源完整性验证通过")
        return True

def main():
    parser = argparse.ArgumentParser(description='静态资源优化工具')
    parser.add_argument('--css', action='store_true', help='处理CSS文件')
    parser.add_argument('--js', action='store_true', help='处理JavaScript文件')
    parser.add_argument('--images', action='store_true', help='处理图片文件')
    parser.add_argument('--webp', action='store_true', help='将图片转换为WebP格式')
    parser.add_argument('--thumbnails', action='store_true', help='创建图片缩略图')
    parser.add_argument('--all', action='store_true', help='处理所有静态资源')
    parser.add_argument('--verify', action='store_true', help='验证本地资源完整性')
    parser.add_argument('--critical-css', action='store_true', help='提取关键CSS')
    parser.add_argument('--local-priority', action='store_true', help='CDN配置优先使用本地资源')
    
    args = parser.parse_args()
    
    # 如果没有指定任何参数，默认处理所有资源
    if not any([args.css, args.js, args.images, args.all, args.verify, args.critical_css]):
        args.all = True
    
    start_time = time.time()
    log("===== 静态资源优化工具 =====")
    
    # 验证本地资源
    if args.verify or args.all:
        verify_local_resources()
    
    # 生成CDN配置
    generate_cdn_config(use_local=args.local_priority)
    
    if args.all or args.css:
        process_css_files(
            extract_critical=args.critical_css or args.all,
            template_dir=os.path.join(PROJECT_ROOT, 'templates')
        )
    
    if args.all or args.js:
        process_js_files()
    
    if args.all or args.images:
        optimize_images(
            convert_to_webp=args.webp,
            create_thumbnails=args.thumbnails or args.all
        )
    
    duration = time.time() - start_time
    log(f"===== 优化完成，用时: {duration:.2f}秒 =====")

if __name__ == '__main__':
    main() 