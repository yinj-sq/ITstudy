# -*- coding: utf-8 -*-
"""管理员密码重置工具 — 管理员遗忘/丢失密码时用命令行重置。

用法（需在项目根目录、venv 激活状态下执行）:
    python tools/reset_admin_password.py                 # 生成随机新密码并打印
    python tools/reset_admin_password.py --password 你的强密码
    python tools/reset_admin_password.py --password-file pass.txt   # 从文件读取（避免命令行历史泄露）

说明：直接覆写 admin_account.txt 的密码哈希（与登录读取路径一致），
重置后旧密码立即失效；Windows 上同步收紧文件 ACL。
"""
import argparse
import getpass
import secrets
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from werkzeug.security import generate_password_hash  # noqa: E402

from app.utils import _write_admin_account, get_admin_account_file  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description='重置 ITstudy 管理员密码')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--password', help='新密码（明文参数，注意命令行历史）')
    group.add_argument('--password-file', help='从文件读取新密码（推荐，防历史泄露）')
    args = parser.parse_args()

    if args.password_file:
        try:
            password = Path(args.password_file).read_text(encoding='utf-8').strip()
        except OSError as e:
            print(f'读取密码文件失败: {e}', file=sys.stderr)
            sys.exit(1)
    elif args.password:
        password = args.password
    else:
        password = getpass.getpass('输入新密码（留空则生成随机密码）: ')
        if not password:
            password = secrets.token_urlsafe(12)
            print(f'已生成随机密码: {password}')

    if len(password) < 8:
        print('警告: 密码长度不足 8 位，建议使用更强的密码', file=sys.stderr)

    _write_admin_account('admin', generate_password_hash(password))
    print(f'管理员密码已重置（账号: admin）。文件: {get_admin_account_file()}')


if __name__ == '__main__':
    main()
