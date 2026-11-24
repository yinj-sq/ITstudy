# -*- coding: utf-8 -*-
"""教师趋势页整页回归：python_fill 每空正确率口径 + `str()` 兜底

补 2026-09-13 审查报告（git show 8d47f69:docs/全面审查报告-2026-09-13.md）§5.3 的第 1 项缺口。那两处逻辑内联在
`admin_trend` 的统计大循环里，此前判定「脱离整页与库无法单测」而只留人工
验证；这里改用**真实数据跑整页**，断言页面渲染出的每空正确率：

- 标准答案 `money // m`（一空多解）：学生答 `money` 应判对 → 该空 100%。
  这是本轮 P2 修复的判分/统计口径分叉——未复用 `_parse_acceptable_answers`
  时该空会渲染成 0%（判分器给满分、教师端记答错）。
- 嵌套作答值为**非字符串**（`true`）：走 `str()` 兜底。原来的
  `.strip()` 会抛 AttributeError，而它不在外层 except 之列 → 整页 500，
  等于任一学生可构造请求打挂教师端。
- 同日补做 §9 #2 的余项：`fill`（普通填空题）在同一段循环里的每空正确率
  分支（`test_trend_page_renders_fill_per_blank_rates`）——见该用例 docstring。

**会写生产库**（1 班 1 生 1 卷 1 题 + `PythonAnswer`/`Result` 各 1 行），
按前缀定向清理（含 `log` 表），跑完须复跑
`tools/review_db_residue_check.py` 确认零残留。
"""
import json
import re

import pytest

from app import create_app
from app.extensions import db
from app.models import (Class, Exam, PythonAnswer, Question, Result, Student)

EXAM_NAME = '审查0913趋势卷'
CLASS_NAME = '审查0913趋势班'
STU_NUM = '0913TR'
STU_NAME = '0913TR生'
_CSRF = 'C' * 32


@pytest.fixture(scope='module')
def app():
    return create_app()


@pytest.fixture(autouse=True)
def _isolated(app):
    _purge(app)
    yield
    _purge(app)


def _purge(app):
    """按本模块命名前缀定向清理，函数内 commit（见模块 docstring）。"""
    p_exam = {'p': EXAM_NAME + '%'}
    p_stu = {'p': STU_NUM + '%'}
    with app.app_context():
        s = db.session
        s.execute(db.text(
            'DELETE FROM python_answer WHERE student_id IN '
            '(SELECT id FROM student WHERE student_number LIKE :p)'), p_stu)
        s.execute(db.text(
            'DELETE FROM result WHERE exam_id IN '
            '(SELECT id FROM exam WHERE name LIKE :p)'), p_exam)
        s.execute(db.text(
            'DELETE FROM exam_question WHERE exam_id IN '
            '(SELECT id FROM exam WHERE name LIKE :p)'), p_exam)
        s.execute(db.text(
            'DELETE FROM question WHERE exam_id IN '
            '(SELECT id FROM exam WHERE name LIKE :p)'), p_exam)
        s.execute(db.text('DELETE FROM exam WHERE name LIKE :p'), p_exam)
        s.execute(db.text('DELETE FROM student WHERE student_number LIKE :p'),
                  p_stu)
        s.execute(db.text('DELETE FROM classes WHERE name LIKE :p'),
                  {'p': CLASS_NAME + '%'})
        for lit in (EXAM_NAME, CLASS_NAME, STU_NUM, STU_NAME):
            s.execute(db.text('DELETE FROM log WHERE detail LIKE :p'),
                      {'p': '%' + lit + '%'})
        s.commit()


def _admin_client(app):
    client = app.test_client()
    with client.session_transaction() as s:
        s.clear()
        s['is_admin'] = True
        s['csrf_token'] = _CSRF
        s.permanent = True
    return client


def _chart_rates(html, qid):
    """取出趋势页里该题填空点图表的正确率序列（Chart.js datasets.data）。

    锚点必须是 **JS 构造行** `const pyDetailChart<id> = new Chart(`：同一 id 在
    页面上先出现在卡片（`<canvas id=...>` 与图表类型下拉框的 onchange）里，
    从那里往后扫 `data: [` 会越过本图的 JS 命中别的图表（实测命中成绩分布图
    的 5 个区间值）。
    """
    m = re.search(r'const pyDetailChart%d\s*=\s*new Chart\(.*?data:\s*\[([^\]]*)\]'
                  % qid, html, re.S)
    assert m, f'页面未渲染题目 {qid} 的填空点图表'
    return [float(x) for x in re.findall(r'\d+(?:\.\d+)?', m.group(1))]


def test_trend_page_renders_per_blank_rates(app):
    """整页断言：多解标准答案判对、非字符串作答不炸页。"""
    with app.app_context():
        cls = Class(name=CLASS_NAME)
        db.session.add(cls)
        db.session.commit()
        cid = cls.id
        stu = Student(name=STU_NAME, student_number=STU_NUM, class_id=cid,
                      student_class=CLASS_NAME, is_activated=True,
                      has_changed_password=True)
        stu.set_password('Test@0913')
        db.session.add(stu)
        db.session.commit()
        sid = stu.id

        exam = Exam(name=EXAM_NAME, is_active=True, is_visible=True, duration=30)
        db.session.add(exam)
        db.session.flush()
        eid = exam.id

        q = Question(exam_id=eid, question_type='python_fill',
                     content='第 1 空：①  第 2 空：②', answer='', score=10,
                     python_answers=json.dumps({'1': 'money // m',
                                                '2': '8080'}),
                     blank_scores=json.dumps([5, 5]))
        db.session.add(q)
        db.session.commit()
        qid = q.id

        # attempt 判定看这张表（有记录即计入分母，与是否已批改无关）
        db.session.add(PythonAnswer(question_id=qid, student_id=sid,
                                    file_name='a.py', file_path='a.py',
                                    score=10.0, status='graded'))
        # 嵌套作答值故意给非字符串（true）→ 打 str() 兜底分支
        db.session.add(Result(
            student_id=sid, exam_id=eid,
            answers=json.dumps({str(qid): {'1': 'money', '2': True}}),
            scores=json.dumps({str(qid): 10.0}),
            total_score=10.0, grading_status='auto_graded'))
        db.session.commit()

    r = _admin_client(app).get(f'/admin/trend/{eid}')

    assert r.status_code == 200, '趋势页整页崩溃（str() 兜底未生效？）'
    rates = _chart_rates(r.get_data(as_text=True), qid)
    assert rates == [100.0, 0.0], (
        f'每空正确率不符：{rates}。期望 [100.0, 0.0]——第 1 空答 money 属'
        '「money // m」的可接受解之一（应判对），第 2 空答 true 非标准答案'
        '（应判错）。若为 [0.0, 0.0] 则是统计未复用判分口径（_parse_'
        'acceptable_answers），与判分器分叉')


def test_trend_page_renders_fill_per_blank_rates(app):
    """整页断言：`fill`（普通填空题）每空正确率（§9 #2 余项）。

    `fill` 与 `python_fill` 共用 `admin_trend` 大循环里同一段「每空正确率」
    代码，但两者取值方式不同（`fill` 拿 `q.answer` 按 `'|'` 拆、按**下标**
    与学生作答对齐），此前无任何用例覆盖。四条口径各配一个学生：

    - 学生 1 `'money|8080|python|django'`：四空全对（含多解写法）。
    - 学生 2 `'m||python|django'`：第 1 空用多解简写 `m`（应判对）、第 2 空留空
      （**不计正确数但仍计尝试数**）、第 3、4 空对——空段在位才能验证
      「按下标对齐」：若实现把 std/user 各自的空段都过滤掉，学生 2 的第 3、4
      空会整体前移串位，正确率随之改变。
    - 学生 3 `'money|9999|python|django'`：仅第 2 空错。
    - 学生 4 `'money // m|8080|py|django'`：第 1 空用**整串**写法（多解之一，
      应判对）、第 3 空错。

    期望 `[100.0, 50.0, 75.0, 100.0]`：第 1 空 4/4（三种写法均算对）、
    第 2 空 2/4（学生 2 未作答、学生 3 答错）、第 3 空 3/4、第 4 空 4/4。
    若第 1 空为 25%（仅整串算对）→ 未复用 `_parse_acceptable_answers`；
    若第 3 空为 50% 且第 4 空为 75% → 空段串位。
    """
    with app.app_context():
        cls = Class(name=CLASS_NAME + 'F')
        db.session.add(cls)
        db.session.commit()
        cid = cls.id

        exam = Exam(name=EXAM_NAME + 'F', is_active=True, is_visible=True,
                    duration=30)
        db.session.add(exam)
        db.session.flush()
        eid = exam.id

        q = Question(exam_id=eid, question_type='fill',
                     content='填空：① ② ③ ④',
                     answer='money // m|8080|python|django', score=10)
        db.session.add(q)
        db.session.commit()
        qid = q.id

        cases = [
            ('money|8080|python|django', 10.0),
            ('m||python|django', 0.0),
            ('money|9999|python|django', 5.0),
            ('money // m|8080|py|django', 7.5),
        ]
        for i, (ans, sc) in enumerate(cases, start=1):
            stu = Student(name=f'{STU_NAME}F{i}', student_number=f'{STU_NUM}F{i}',
                          class_id=cid, student_class=cls.name,
                          is_activated=True, has_changed_password=True)
            stu.set_password('Test@0913')
            db.session.add(stu)
            db.session.flush()
            db.session.add(Result(
                student_id=stu.id, exam_id=eid,
                answers=json.dumps({str(qid): ans}),
                scores=json.dumps({str(qid): sc}),
                total_score=sc, grading_status='auto_graded'))
        db.session.commit()

    r = _admin_client(app).get(f'/admin/trend/{eid}')

    assert r.status_code == 200, '趋势页整页崩溃'
    rates = _chart_rates(r.get_data(as_text=True), qid)
    assert rates == [100.0, 50.0, 75.0, 100.0], (
        f'fill 每空正确率不符：{rates}。期望 [100.0, 50.0, 75.0, 100.0]'
        '（多解写法算对 / 空段不计正确但计尝试 / 空段不得串位）')
