# -*- coding: utf-8 -*-
"""教师跨班批改整链路 E2E（补 2026-09-13 审查报告 §5.3 #2 / §9 #3，原文 git show 8d47f69:docs/全面审查报告-2026-09-13.md）

场景：**一套试卷被两个班共用**，教师当前上课班级是 A 班。此前只做到
「SQL 带上 `student_id` 边界」的用例级验证（`tests/test_review_fixes_0913.py`），
本文件把整条链路按真实 HTTP 走一遍：

1. 批改列表只列 A 班学生（B 班学生不出现在 HTML 里）；
2. A 班学生的批改页上「下一名学生」是**禁用态**（导航集合里没有 B 班）；
3. 「保存并下一个」提交后**绝不跳到 B 班成绩**——这正是修复前的缺陷：
   导航按 `exam_id` 全卷检索 → 跳到外班学生 → 被 `grade_student` 的边界
   检查弹回列表，连续批改在此断流（非越权，是可用性缺陷）；
4. 直连 B 班成绩 URL 会被边界弹回（纵深防御）。

**注意**：教师可见班级取自 `ClassroomSetting.active_class_id`（带 5s 缓存），
直接改库会影响线上课堂大屏的「上课班级」，故本用例用 monkeypatch 注入该
函数——不改任何线上状态。

**会写生产库**（2 班 2 生 1 卷 1 题 + 2 条成绩），按前缀定向清理（含 `log`），
跑完须复跑 `tools/review_db_residue_check.py` 确认零残留。
"""
import json
from datetime import datetime, timedelta

import pytest

from app import create_app
from app.extensions import db
from app.models import Class, Exam, Question, Result, Student

CLASS_NAME = '审查0913边界班'
EXAM_NAME = '审查0913边界卷'
STU_NUM = '0913BD'
STU_NAME = '0913BD生'
A_ANSWER = 'boundary-a-answer-0913'
B_ANSWER = 'boundary-b-answer-0913'
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
            'DELETE FROM result WHERE exam_id IN '
            '(SELECT id FROM exam WHERE name LIKE :p)'), p_exam)
        s.execute(db.text(
            'DELETE FROM exam_attempt WHERE exam_id IN '
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


def _teacher_client(app):
    client = app.test_client()
    with client.session_transaction() as s:
        s.clear()
        s['is_teacher'] = True
        s['teacher_name'] = STU_NAME
        s['csrf_token'] = _CSRF
        s.permanent = True
    return client


def _setup(app):
    """建两个班、两名学生、一套共用卷与两条待批改成绩。

    submit_time：A 班在前、B 班在后——若导航漏了班级边界，A 班的
    「下一个」必然是 B 班，缺陷会以跳转目标的形式暴露。
    """
    with app.app_context():
        cls_a = Class(name=CLASS_NAME + 'A')
        cls_b = Class(name=CLASS_NAME + 'B')
        db.session.add_all([cls_a, cls_b])
        db.session.commit()
        cls_a_id, cls_b_id = cls_a.id, cls_b.id

        stu_a = Student(name=STU_NAME + 'A', student_number=STU_NUM + 'A',
                        class_id=cls_a_id, student_class=CLASS_NAME + 'A',
                        is_activated=True, has_changed_password=True)
        stu_b = Student(name=STU_NAME + 'B', student_number=STU_NUM + 'B',
                        class_id=cls_b_id, student_class=CLASS_NAME + 'B',
                        is_activated=True, has_changed_password=True)
        for st in (stu_a, stu_b):
            st.set_password('Test@0913')
            db.session.add(st)
        db.session.commit()
        stu_a_id, stu_b_id = stu_a.id, stu_b.id

        exam = Exam(name=EXAM_NAME, is_active=True, is_visible=True, duration=30)
        db.session.add(exam)
        db.session.flush()
        exam_id = exam.id
        q = Question(exam_id=exam_id, question_type='short_answer',
                     content='请简述边界场景', answer='', score=10)
        db.session.add(q)
        db.session.commit()
        qid = q.id

        base = datetime.now() - timedelta(hours=1)
        rows = []
        for offset, (sid, text) in enumerate(((stu_a_id, A_ANSWER),
                                              (stu_b_id, B_ANSWER))):
            manual = {str(qid): {'max_score': 10, 'manual_score': None,
                                 'student_answer': text}}
            rows.append(Result(
                student_id=sid, exam_id=exam_id,
                answers=json.dumps({str(qid): text}),
                scores=json.dumps({str(qid): 0}),
                manual_scores=json.dumps(manual),
                total_score=0.0, grading_status='pending_review',
                submit_time=base + timedelta(minutes=offset)))
        db.session.add_all(rows)
        db.session.commit()
        return exam_id, rows[0].id, rows[1].id, cls_a_id


def test_teacher_grading_stays_inside_active_class(app, monkeypatch):
    exam_id, r_a, r_b, cls_a_id = _setup(app)
    # 多班支持后教师边界取自其任教班级集合，不再取全局单一上课班
    from app.services import resource_access
    monkeypatch.setattr(resource_access, 'teacher_class_ids',
                        lambda teacher_id: [cls_a_id])
    client = _teacher_client(app)

    # ① 列表只列本班学生
    r = client.get(f'/admin/grading/{exam_id}')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert (STU_NAME + 'A') in html, '列表未列出本班学生的成绩'
    assert (STU_NAME + 'B') not in html, '列表泄漏了外班学生成绩'

    # ② 批改页的「下一名学生」为禁用态（导航集合里没有外班）
    r = client.get(f'/admin/grading/{exam_id}/{r_a}')
    assert r.status_code == 200
    assert 'disabled>下一名学生' in r.get_data(as_text=True), (
        '「下一名学生」可用 → 导航集合里混进了外班成绩')

    # ③ 保存并下一个：跳转目标绝不可是外班成绩
    r = client.post(f'/admin/grading/{exam_id}/{r_a}',
                    data={'action': 'next'},
                    headers={'X-CSRFToken': _CSRF})
    assert r.status_code == 302
    loc = r.headers['Location']
    assert not loc.rstrip('/').endswith(f'/{r_b}'), f'跨班跳转：{loc}'
    assert loc.rstrip('/').endswith(f'/admin/grading/{exam_id}'), (
        f'本班已无下一名时应回到列表，实际跳转：{loc}')

    # ④ 直连外班成绩被边界弹回（纵深防御）
    r = client.get(f'/admin/grading/{exam_id}/{r_b}', follow_redirects=True)
    assert r.status_code == 200
    assert B_ANSWER not in r.get_data(as_text=True), '外班答卷内容被渲染出来了'
