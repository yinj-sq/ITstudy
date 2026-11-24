# -*- coding: utf-8 -*-
"""测试残留检查：跑完全量 pytest 后确认测试库零残留

**为什么需要它**：测试垃圾数据全靠 fixture 自清理，清理一旦静默失效，
残留会永久沉积。已经踩过两次，两次机制**不同**：

1. `test_review_fixes_0910.py`：`db.session.connection()` 后没提交，
   事务随会话销毁回滚 —— 清理**从未**生效（2026-09-10 起）。
2. `test_review_fixes_0908.py`：清理名单逐个列举卷名，漏掉了测试里
   `EXAM_NAME + 'X'` 这类**派生命名**，每次跑都留下一卷一题。

两次都不是「写了清理但写错」，而是「清理看起来在跑、其实没覆盖」。
所以事后手工拼 SQL 复查不可靠——复查本身也会漏。本脚本把「零残留」
固化成一条可复跑命令。

**扫哪个库**：2026-09-13 起 tests/ 由 `tests/conftest.py` 钉在独立测试库
`itstudy_test` 上（生产库 itstudy 已隔离，见 2026-09-13 审查报告 §9 #5，
原文 `git show 8d47f69:docs/全面审查报告-2026-09-13.md`），残留只可能沉积在测试库 —— 故本脚本**默认扫 itstudy_test**。
需要复查历史生产库是否干净时显式指定库名即可（见下方用法）。

**命名来源自动提取**：从 `tests/*.py` 里扫模块级字符串常量
（`XXX_NAME = '...'` / `XXX_NUM = '...'`），各自作为 LIKE 前缀去比对。
新增测试不需要改本脚本——只要用模块级常量命名就自动纳入。
派生名（`EXAM_NAME + 'X'`）由前缀匹配天然覆盖。

用法：
    venv/Scripts/python.exe -m pytest tests/ -q
    venv/Scripts/python.exe tools/review_db_residue_check.py
    DB_NAME=itstudy venv/Scripts/python.exe tools/review_db_residue_check.py   # 复查生产库

退出码：有残留 = 1，零残留 = 0。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 与 tests/conftest.py 钉的同一个库；显式设 DB_NAME 可覆盖（如复查生产库）
os.environ.setdefault('DB_NAME', 'itstudy_test')

from app import create_app          # noqa: E402
from app.extensions import db       # noqa: E402

# 三处「测试数据命名」的写法，全部取字面量作前缀：
#   1) 模块级常量   EXAM_NAME = '审查0908测试卷'
#   2) 内联建行     Exam(name='__回归测试__') / Student(student_number='...')
#   3) f-string 常量 f'REG-{number}'  → 前缀 'REG-'
# 正则只认 name/student_number/title 三个「命名列」赋值位，不用「含中文字符」
# 之类的启发式——那样会把 '学生未作答' 这类**断言用期望值**也当命名，
# 拿它去匹配 log.detail 必然误报。
PREFIX_RES = [
    re.compile(r"^[A-Z][A-Z0-9_]*(?:NAME|NUM|TITLE)[A-Z0-9_]*\s*=\s*'([^']+)'",
               re.M),
    re.compile(r"\b(?:name|student_number|title)\s*=\s*'([^']+)'"),
    re.compile(r"\b(?:name|student_number|title)\s*=\s*f'([^'{]+)\{"),
]


def _test_literals():
    """收集 tests/ 下所有测试数据命名前缀（去重排序）。

    取**前缀**而非整串：派生名（`EXAM_NAME + 'X'`）与再拼后缀的写法
    都靠前缀匹配兜住——`test_review_fixes_0908.py` 漏的正是这一类。
    """
    tests_dir = os.path.join(ROOT, 'tests')
    found = set()
    for fn in sorted(os.listdir(tests_dir)):
        if not (fn.startswith('test_') and fn.endswith('.py')):
            continue
        with open(os.path.join(tests_dir, fn), encoding='utf-8') as f:
            text = f.read()
        for rx in PREFIX_RES:
            for lit in rx.findall(text):
                # 短于 2 字符或含路径分隔符的一律不是库内命名
                if len(lit) >= 2 and '/' not in lit and '\\' not in lit:
                    found.add(lit)
    return sorted(found)

# (表名, 比对列)：测试会在这里落下带常量名的行
TARGETS = [
    ('exam', 'name'),
    ('classes', 'name'),
    ('student', 'student_number'),
    ('study_group', 'name'),
    ('resource', 'title'),
    ('learning_activity', 'title'),
]

# 孤儿行：测试删了主表却留下从表（名称扫描看不到这类残留）
ORPHANS = [
    ('result', 'exam_id', 'exam'),
    ('exam_attempt', 'exam_id', 'exam'),
    ('exam_question', 'exam_id', 'exam'),
    ('question', 'exam_id', 'exam'),
]


def main():
    literals = _test_literals()
    app = create_app()
    residue = []
    with app.app_context():
        conn = db.session.connection()
        for lit in literals:
            for table, col in TARGETS:
                n = conn.execute(db.text(
                    f'SELECT count(*) FROM {table} WHERE {col} LIKE :p'),
                    {'p': lit + '%'}).scalar()
                if n:
                    residue.append((table, col, lit, n))
            n = conn.execute(db.text(
                "SELECT count(*) FROM log WHERE detail LIKE :p"),
                {'p': '%' + lit + '%'}).scalar()
            if n:
                residue.append(('log', 'detail', lit, n))

        print(f'扫描 {len(literals)} 个测试数据命名前缀，'
              f'{len(TARGETS)} 张表 + log')

        orphans = []
        for child, fk, parent in ORPHANS:
            n = conn.execute(db.text(
                f'SELECT count(*) FROM {child} c LEFT JOIN {parent} p '
                f'ON p.id = c.{fk} WHERE c.{fk} IS NOT NULL '
                f'AND p.id IS NULL')).scalar()
            if n:
                orphans.append((child, n))

    if residue:
        print('\n!! 发现残留（fixture 清理未覆盖）：')
        for table, col, lit, n in residue:
            print(f'   {table}.{col} LIKE {lit}%  ->  {n} 行')
    else:
        print('\nOK 零残留')
    if orphans:
        print('\n注意 孤儿行（名称扫描看不到，可能是测试删卷未清从表）：')
        for child, n in orphans:
            print(f'   {child}: {n} 行')
    return 1 if residue else 0


if __name__ == '__main__':
    sys.exit(main())
