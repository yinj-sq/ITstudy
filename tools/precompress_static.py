# -*- coding: utf-8 -*-
"""静态资源 gzip 预压缩工具 — 生成 .gz 文件供 nginx gzip_static 使用。

背景：nginx 已开启 gzip_static（docs/itstudy.conf），命中 .gz 文件时
直接发送、不消耗每请求 CPU。jit-viewer.min.js 9.7MB → ~2.5MB，
首次加载文档预览页提速约 4 倍。

本工具只生成 .gz 副本，不修改原文件；已存在且内容与源文件一致的 .gz 跳过。
已有 .gz 的文件不受 --min-size 限制（陈旧 .gz 会被 nginx 原样下发）。

用法（需在项目根目录执行）:
    python tools/precompress_static.py              # 全部静态资源
    python tools/precompress_static.py --min-size 1024   # 阈值 1KB
    python tools/precompress_static.py --dry-run    # 只列出将生成的
    python tools/precompress_static.py --refresh-only   # 只校准已存在的 .gz（打包前必跑）

说明：
- 只处理 JS/CSS/JSON/SVG 等文本类资源（图片/音视频本身已压缩，gzip 无效）
- gzip 级别 9（预压缩一次生成，永久复用，级别高更划算）
- 建议部署后/每次更新静态资源后运行一次
"""
import argparse
import gzip
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / 'static'

COMPRESSIBLE_EXTS = {'.js', '.css', '.json', '.svg', '.html', '.txt', '.csv'}
DEFAULT_MIN_SIZE = 8 * 1024  # 8KB 以下资源 gzip 收益小，跳过


def find_candidates(min_size):
    """收集可压缩的静态资源（相对路径）。

    排除 uploads/ 与 chunks/（上传内容/分块临时文件，非版本化静态资源，
    且会被孤儿清理等运维任务处理）。
    """
    candidates = []
    for root, _, files in os.walk(STATIC_DIR):
        rel = os.path.relpath(root, STATIC_DIR)
        if rel.split(os.sep)[0] in ('uploads', 'chunks'):
            continue
        for fn in files:
            if fn.endswith('.gz'):
                continue
            ext = Path(fn).suffix.lower()
            if ext not in COMPRESSIBLE_EXTS:
                continue
            fp = Path(root) / fn
            # 已有 .gz 的文件无视阈值一律纳入：陈旧的 .gz 比没有 .gz 危险得多
            # （nginx gzip_static 只要 .gz 存在就直接发它）
            if fp.stat().st_size < min_size and not Path(str(fp) + '.gz').exists():
                continue
            candidates.append(fp)
    return candidates


def is_fresh(fp):
    """.gz 存在且解压后与源文件逐字节一致。

    不能按 mtime 判断：git checkout / 解包会重置时间戳，源文件被改过而 .gz
    未重建时 mtime 仍可能显示 .gz 更新——2026-09-25 实测 5 个 .gz 陈旧，其中
    pptist/index.html.gz 停留在 V5.0.1 之前（缺 PPTX 导入桥接），nginx 部署下
    浏览器拿到的一直是旧页面。
    """
    gz_path = Path(str(fp) + '.gz')
    if not gz_path.exists():
        return False
    try:
        return gzip.decompress(gz_path.read_bytes()) == fp.read_bytes()
    except (OSError, EOFError, gzip.BadGzipFile):
        return False


def precompress(fp, dry_run=False, verbose=False):
    """为单个文件生成 .gz（内容已一致则跳过）。"""
    gz_path = Path(str(fp) + '.gz')
    if is_fresh(fp):
        return 'skip'
    if dry_run:
        return 'would'
    try:
        # mtime=0：输出只取决于内容，重复运行不产生无意义的二进制差异
        gz_path.write_bytes(gzip.compress(fp.read_bytes(), compresslevel=9, mtime=0))
        return 'done'
    except OSError as e:
        print(f'  失败: {fp} ({e})', file=sys.stderr)
        return 'fail'


def main():
    parser = argparse.ArgumentParser(description='静态资源 gzip 预压缩（nginx gzip_static 配合）')
    parser.add_argument('--min-size', type=int, default=DEFAULT_MIN_SIZE,
                        help=f'最小文件大小阈值（字节，默认 {DEFAULT_MIN_SIZE}）')
    parser.add_argument('--dry-run', action='store_true', help='只列出将生成的 .gz')
    parser.add_argument('--verbose', action='store_true', help='显示跳过项')
    parser.add_argument('--refresh-only', action='store_true',
                        help='只刷新已存在的 .gz（不为新文件生成；打包前校准用）')
    args = parser.parse_args()

    candidates = find_candidates(args.min_size)
    if args.refresh_only:
        candidates = [fp for fp in candidates if Path(str(fp) + '.gz').exists()]
    if not candidates:
        print(f'{STATIC_DIR} 下无超过 {args.min_size} 字节的可压缩文本资源')
        return

    stats = {'done': 0, 'skip': 0, 'would': 0, 'fail': 0}
    saved_total = 0
    for fp in sorted(candidates):
        orig = fp.stat().st_size
        result = precompress(fp, dry_run=args.dry_run)
        stats[result] += 1
        if result == 'done':
            gz_size = Path(str(fp) + '.gz').stat().st_size
            saved = orig - gz_size
            saved_total += saved
            print(f'  {fp.relative_to(BASE_DIR)}: {orig / 1024:.0f}KB → {gz_size / 1024:.0f}KB '
                  f'(省 {saved / 1024:.0f}KB)')
        elif result == 'would':
            print(f'  {fp.relative_to(BASE_DIR)}: {orig / 1024:.0f}KB（将生成）')
        elif args.verbose and result == 'skip':
            print(f'  {fp.relative_to(BASE_DIR)}: 已存在（跳过）')

    print(f'\n完成: 生成 {stats["done"]} 个, 已存在跳过 {stats["skip"]} 个'
          f'{", 失败 " + str(stats["fail"]) if stats["fail"] else ""}')
    if stats['done']:
        print(f'预计节省磁盘/传输: {saved_total / 1024 / 1024:.1f}MB')
    if args.dry_run:
        print('（dry-run 未实际生成）')


if __name__ == '__main__':
    main()
