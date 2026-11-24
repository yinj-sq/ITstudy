# -*- coding: utf-8 -*-
"""操作日志归档工具 — 把指定日期前的 Log 记录导出为 JSON 文件并删除。

Log 表只增不删（仅管理员手动清空），长期运行会持续膨胀。
本工具按月归档：把截止日期前的记录导出到 backups/logs/ 后删除，
供审计留档，同时控制表体积。

用法（需在项目根目录、venv 激活状态下执行）:
    python tools/archive_logs.py                # 归档 90 天前的日志
    python tools/archive_logs.py --days 30      # 归档 30 天前的日志
    python tools/archive_logs.py --before 2026-01-01   # 归档指定日期前

说明：导出为 JSONL（每行一条），与 SQLite 的 dump 格式不同但易于检索；
删除操作在单个事务内完成，失败自动回滚。
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_PORT', '5432')
os.environ.setdefault('DB_USER', 'postgres')
os.environ.setdefault('DB_PASS', '@@')
os.environ.setdefault('DB_NAME', 'itstudy')

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Log  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description='归档并清理历史操作日志')
    parser.add_argument('--days', type=int, default=90, help='归档 N 天前的日志（默认 90）')
    parser.add_argument('--before', type=str, default='',
                        help='归档指定日期（YYYY-MM-DD）前的日志，优先于 --days')
    parser.add_argument('--keep', action='store_true',
                        help='仅导出不删除（试运行）')
    args = parser.parse_args()

    if args.before:
        try:
            cutoff = datetime.strptime(args.before, '%Y-%m-%d')
        except ValueError:
            print(f'日期格式无效: {args.before}（应为 YYYY-MM-DD）')
            return 1
    else:
        cutoff = datetime.now() - timedelta(days=args.days)

    app = create_app()
    with app.app_context():
        rows = Log.query.filter(Log.time < cutoff).all()
        if not rows:
            print(f'截止 {cutoff.date()} 前无日志记录，无需归档')
            return 0
        print(f'待归档 {len(rows)} 条记录（截止 {cutoff.date()}）')

        backup_dir = os.path.join(BASE_DIR, 'backups', 'logs')
        os.makedirs(backup_dir, exist_ok=True)
        backup_file = os.path.join(
            backup_dir, f'log_archive_{cutoff.strftime("%Y%m%d")}.jsonl')

        exported = 0
        with open(backup_file, 'w', encoding='utf-8') as f:
            for row in rows:
                f.write(json.dumps({
                    'id': row.id,
                    'user_id': row.user_id,
                    'user_type': row.user_type,
                    'action': row.action,
                    'detail': row.detail,
                    'time': row.time.strftime('%Y-%m-%d %H:%M:%S') if row.time else None,
                }, ensure_ascii=False) + '\n')
                exported += 1

        print(f'已导出 {exported} 条到 {backup_file}')

        if args.keep:
            print('--keep 模式：跳过删除')
            return 0

        deleted = Log.query.filter(Log.time < cutoff).delete(synchronize_session=False)
        db.session.commit()
        print(f'已删除 {deleted} 条历史日志')


if __name__ == '__main__':
    sys.exit(main())
