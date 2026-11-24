"""
@file compress_images.py
@brief 批量压缩静态资源目录下的图片文件，支持WebP转换和更多高级优化选项
@usage 直接运行 python tools/compress_images.py [options]
"""
import os
import argparse
from PIL import Image, ImageOps
import time
import multiprocessing
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib

def create_thumbnail(img_path, output_path=None, max_width=None, max_height=None, quality=85):
    """
    创建图片缩略图
    
    参数:
    - img_path: 输入图片路径
    - output_path: 输出图片路径(None表示使用原路径但添加_thumb后缀)
    - max_width: 最大宽度
    - max_height: 最大高度
    - quality: 图片质量(1-100)
    
    返回:
    - 缩略图路径
    """
    try:
        img = Image.open(img_path)
        
        # 如果没有指定最大宽度或高度，则保持原图大小
        if not max_width and not max_height:
            return img_path
            
        # 计算缩放比例
        width, height = img.size
        
        if max_width and not max_height:
            # 按宽度等比例缩放
            if width <= max_width:
                return img_path
            ratio = max_width / width
            new_height = int(height * ratio)
            new_width = max_width
        elif max_height and not max_width:
            # 按高度等比例缩放
            if height <= max_height:
                return img_path
            ratio = max_height / height
            new_width = int(width * ratio)
            new_height = max_height
        else:
            # 同时指定了宽度和高度，保持长宽比
            width_ratio = max_width / width
            height_ratio = max_height / height
            ratio = min(width_ratio, height_ratio)
            
            if ratio >= 1:
                return img_path  # 原图尺寸比目标尺寸小，无需缩放
                
            new_width = int(width * ratio)
            new_height = int(height * ratio)
        
        # 调整图片大小
        img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # 确定输出路径
        if not output_path:
            name, ext = os.path.splitext(img_path)
            output_path = f"{name}_thumb{ext}"
        
        # 保存缩略图
        img.save(output_path, quality=quality, optimize=True)
        print(f"创建缩略图成功: {output_path}")
        return output_path
    except Exception as e:
        print(f"创建缩略图失败: {img_path}, 错误: {e}")
        return None

def optimize_image(img_path, output_path=None, convert_to_webp=False, max_width=1200, quality=85, 
                   create_thumbnails=False, thumbnail_width=300, enable_progressive=False, 
                   optimize_transparency=False):
    """
    优化图片：调整大小、转换格式、压缩质量、创建缩略图等
    
    参数:
    - img_path: 输入图片路径
    - output_path: 输出图片路径(None表示覆盖原图)
    - convert_to_webp: 是否转换为WebP格式
    - max_width: 最大宽度
    - quality: 图片质量(1-100)
    - create_thumbnails: 是否创建缩略图
    - thumbnail_width: 缩略图最大宽度
    - enable_progressive: 是否启用渐进式加载(仅JPEG支持)
    - optimize_transparency: 是否优化PNG透明度
    
    返回:
    - 优化后的图片路径和缩略图路径(如果有)的元组
    """
    try:
        img = Image.open(img_path)
        
        # 生成图片哈希(用于文件名和缓存控制)
        img_hash = hashlib.md5(img.tobytes()).hexdigest()[:8]
        
        # 保持纵横比的情况下调整图片大小
        if max(img.size) > max_width:
            width, height = img.size
            if width > height:
                new_width = max_width
                new_height = int(height * (max_width / width))
            else:
                new_height = max_width
                new_width = int(width * (max_width / height))
            
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # 决定输出路径
        if not output_path:
            if convert_to_webp:
                output_path = os.path.splitext(img_path)[0] + '.webp'
            else:
                output_path = img_path
        
        # 应用优化选项
        thumbnail_path = None
        
        # 保存优化后的图片
        if convert_to_webp:
            # WebP转换
            img.save(output_path, 'WEBP', quality=quality)
            print(f"WebP转换成功: {img_path} -> {output_path}")
            
            # 创建WebP缩略图
            if create_thumbnails:
                thumb_name = os.path.splitext(output_path)[0] + f"_thumb_{img_hash}.webp"
                thumbnail_path = create_thumbnail(output_path, thumb_name, thumbnail_width, None, quality)
                
        elif img_path.lower().endswith(('.jpg', '.jpeg')):
            # JPEG优化，支持渐进式加载
            img = img.convert('RGB')
            img.save(output_path, format='JPEG', quality=quality, optimize=True, 
                    progressive=enable_progressive)
            print(f"JPEG优化成功: {output_path}" + (" (渐进式)" if enable_progressive else ""))
            
            # 创建JPEG缩略图
            if create_thumbnails:
                thumb_name = os.path.splitext(output_path)[0] + f"_thumb_{img_hash}.jpg"
                thumbnail_path = create_thumbnail(output_path, thumb_name, thumbnail_width, None, quality)
                
        elif img_path.lower().endswith('.png'):
            # PNG优化，支持透明度优化
            if optimize_transparency and img.mode == 'RGBA':
                # 优化透明度通道
                r, g, b, a = img.split()
                img = Image.merge('RGBA', (r, g, b, ImageOps.autocontrast(a)))
            
            img.save(output_path, format='PNG', optimize=True, compress_level=9)
            print(f"PNG优化成功: {output_path}" + (" (透明度优化)" if optimize_transparency else ""))
            
            # 创建PNG缩略图
            if create_thumbnails:
                thumb_name = os.path.splitext(output_path)[0] + f"_thumb_{img_hash}.png"
                thumbnail_path = create_thumbnail(output_path, thumb_name, thumbnail_width, None, quality)
        
        # 返回优化后的图片路径和缩略图路径
        return (output_path, thumbnail_path)
    except Exception as e:
        print(f"图片优化失败: {img_path}, 错误: {e}")
        return (img_path, None)

def compress_images(folder, convert_to_webp=False, max_width=1200, quality=85, 
                    create_thumbnails=False, thumbnail_width=300, enable_progressive=False,
                    optimize_transparency=False, use_multiprocessing=False):
    """
    批量压缩指定文件夹下的图片
    
    参数:
    - folder: 图片所在文件夹
    - convert_to_webp: 是否转换为WebP格式
    - max_width: 最大宽度
    - quality: 图片质量(1-100)
    - create_thumbnails: 是否创建缩略图
    - thumbnail_width: 缩略图最大宽度
    - enable_progressive: 是否启用渐进式JPEG
    - optimize_transparency: 是否优化PNG透明度
    - use_multiprocessing: 是否使用多线程处理
    """
    if not os.path.exists(folder):
        print(f"目录不存在: {folder}")
        return
    
    print(f"正在处理目录: {folder}" + 
          (" (转换为WebP)" if convert_to_webp else "") +
          (" (创建缩略图)" if create_thumbnails else "") +
          (" (渐进式JPEG)" if enable_progressive else "") +
          (" (优化PNG透明度)" if optimize_transparency else ""))
    
    start_time = time.time()
    total_files = 0
    processed_files = 0
    saved_bytes = 0
    image_files = []
    
    # 首先收集所有图片文件
    for root, _, files in os.walk(folder):
        for fname in files:
            fpath = os.path.join(root, fname)
            ext = os.path.splitext(fname)[-1].lower()
            
            if ext not in ['.jpg', '.jpeg', '.png']:
                continue
                
            total_files += 1
            image_files.append(fpath)
    
    # 根据是否使用多线程选择处理方式
    if use_multiprocessing and total_files > 3:
        # 使用线程池并行处理
        num_workers = min(multiprocessing.cpu_count(), total_files)
        print(f"使用多线程处理，线程数: {num_workers}")
        
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            # 提交所有任务
            future_to_path = {}
            for fpath in image_files:
                if convert_to_webp:
                    output_path = os.path.splitext(fpath)[0] + '.webp'
                else:
                    output_path = fpath
                
                future = executor.submit(
                    optimize_image, fpath, output_path, convert_to_webp,
                    max_width, quality, create_thumbnails, thumbnail_width,
                    enable_progressive, optimize_transparency
                )
                future_to_path[future] = fpath
            
            # 处理结果
            for future in as_completed(future_to_path):
                fpath = future_to_path[future]
                try:
                    output_path, thumbnail_path = future.result()
                    
                    # 计算节省的空间
                    if output_path and os.path.exists(output_path):
                        original_size = os.path.getsize(fpath)
                        new_size = os.path.getsize(output_path)
                        saved = original_size - new_size
                        saved_bytes += saved if saved > 0 else 0
                        
                        if saved > 0:
                            saved_percent = (saved / original_size) * 100
                            print(f"  - 优化: {os.path.basename(fpath)} -> 减小 {saved_percent:.1f}% ({saved/1024:.1f}KB)")
                        
                        processed_files += 1
                    
                    # 如果转换为WebP，删除原图
                    if convert_to_webp and os.path.exists(output_path) and output_path != fpath:
                        os.remove(fpath)
                except Exception as e:
                    print(f"处理失败: {os.path.basename(fpath)}, 错误: {e}")
    else:
        # 单线程顺序处理
        for fpath in image_files:
            try:
                # 获取原始文件大小
                original_size = os.path.getsize(fpath)
                
                # 优化图片
                if convert_to_webp:
                    output_path = os.path.splitext(fpath)[0] + '.webp'
                else:
                    output_path = fpath
                    
                output_path, thumbnail_path = optimize_image(
                    fpath, output_path, convert_to_webp, max_width, quality,
                    create_thumbnails, thumbnail_width, enable_progressive, optimize_transparency
                )
                
                # 计算节省的空间
                if os.path.exists(output_path):
                    new_size = os.path.getsize(output_path)
                    saved = original_size - new_size
                    saved_bytes += saved if saved > 0 else 0
                    
                    if saved > 0:
                        saved_percent = (saved / original_size) * 100
                        print(f"  - 优化: {os.path.basename(fpath)} -> 减小 {saved_percent:.1f}% ({saved/1024:.1f}KB)")
                    
                    processed_files += 1
                
                # 如果转换为WebP，删除原图
                if convert_to_webp and os.path.exists(output_path) and output_path != fpath:
                    os.remove(fpath)
                    
            except Exception as e:
                print(f"处理失败: {os.path.basename(fpath)}, 错误: {e}")
    
    # 输出统计信息
    duration = time.time() - start_time
    print("\n处理完成:")
    print(f"  - 已处理: {processed_files}/{total_files} 张图片")
    print(f"  - 节省空间: {saved_bytes/1024/1024:.2f} MB")
    print(f"  - 用时: {duration:.2f} 秒")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='批量压缩和优化图片')
    parser.add_argument('--webp', action='store_true', help='转换图片为WebP格式')
    parser.add_argument('--quality', type=int, default=85, help='图片质量(1-100)')
    parser.add_argument('--max-width', type=int, default=1200, help='最大图片宽度')
    parser.add_argument('--folders', nargs='+', default=['static/question_img', 'static/images'], 
                        help='要处理的文件夹列表')
    parser.add_argument('--thumbnails', action='store_true', help='创建缩略图')
    parser.add_argument('--thumb-width', type=int, default=300, help='缩略图宽度')
    parser.add_argument('--progressive', action='store_true', help='启用渐进式JPEG')
    parser.add_argument('--optimize-transparency', action='store_true', help='优化PNG透明度')
    parser.add_argument('--multiprocessing', action='store_true', help='使用多线程处理')
    
    args = parser.parse_args()
    
    print("===== 图片优化工具 =====")
    print(f"WebP转换: {'启用' if args.webp else '禁用'}")
    print(f"质量设置: {args.quality}")
    print(f"最大宽度: {args.max_width}px")
    print(f"创建缩略图: {'启用' if args.thumbnails else '禁用'}")
    if args.thumbnails:
        print(f"缩略图宽度: {args.thumb_width}px")
    print(f"渐进式JPEG: {'启用' if args.progressive else '禁用'}")
    print(f"优化PNG透明度: {'启用' if args.optimize_transparency else '禁用'}")
    print(f"多线程处理: {'启用' if args.multiprocessing else '禁用'}")
    print("=======================")
    
    for folder in args.folders:
        if os.path.exists(folder):
            compress_images(
                folder, args.webp, args.max_width, args.quality,
                args.thumbnails, args.thumb_width, args.progressive,
                args.optimize_transparency, args.multiprocessing
            )
        else:
            print(f"目录不存在: {folder}") 