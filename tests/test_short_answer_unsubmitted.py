# -*- coding: utf-8 -*-
"""完全未提交的简答题必须出现在教师批改页（2026-09-13 审查修复）

**缺陷**：`submit_exam` 的普通题分支整体包在 `if q_id in answers_data:` 里。
学生**完全没提交**某题时（答案 JSON 里根本没有这个键）该分支直接落空——
该题既不入 `scores`、也不入 `manual_scores`。后果不是"少记 0 分"（总分本
就是 0），而是教师批改页上**整题消失**：既不在待批列表、也不在已批列表，
连"学生未作答"都看不到。教师无从判断是学生漏答、还是系统丢了数据。

**修复**：键缺失的**开放式试题**按空答案处理，与「已提交但为空」完全同规——
记入 `auto_graded_items`（`manual_score=0, auto_graded=True`），批改页渲染为
标「自动批改」的**可编辑**卡片，`scores` 记 0。**不改** `grading_status`：
不产生待批改人数，教师无需逐条处理。

**刻意不动的边界**：非开放式试题（判断/单选/填空等有标准答案的题）键缺失时
行为保持原样——它们本就由判分器自动出分、教师无需介入，凭空补进 `scores`
只会改变趋势页正确率统计的分母（无产品收益的行为变更）。

**本文件会写生产库**（与 test_review_fixes_0910.py 同一前提）：每例建 1 卷
3 题 1 生 + 1 条交卷记录，全部按固定名前缀清理并在清理函数内提交事务。
"""
import json
import re

import pytest

from app import create_app
from app.extensions import db
from app.models import Exam, ExamAttempt, Question, Result, Student

CSRF = 'review-0913-sa-csrf'
# 清理按前缀命中：这里是唯一的"命名契约"，改名必须同步 _cleanup_all
EXAM_PREFIX = '__审查0913简答未提交__'
STU_PREFIX = 'REV0913SA'


# ── 基建 ──────────────────────────────────────────

@pytest.fixture(scope='module')
def app():
    application = create_app()
    yield application
    with application.app_context():
        _cleanup_all()


def _seed(app, tag):
    """建 1 卷 3 题 1 生 1 开考记录。

    三题分别是：两个简答题（开放式，需教师批改）+ 一个判断题（自动出分）。
    返回 dict，键为 'exam'/'student'/'sa1'/'sa2'/'judge'。
    """
    with app.app_context():
        exam = Exam(name=f'{EXAM_PREFIX}{tag}', is_visible=True,
                    is_active=True, is_enabled=True, is_collected=False,
                    duration=None)  # duration=None：不触发服务端时长校验
        db.session.add(exam)
        db.session.flush()

        # Question(exam_id=...) 由 models 的 after_insert 事件自动挂卷，
        # 无需手工写 exam_question
        sa1 = Question(exam_id=exam.id, question_type='short_answer',
                       content=f'请简述 {tag} 题一', answer='参考答案一',
                       score=10)
        sa2 = Question(exam_id=exam.id, question_type='short_answer',
                       content=f'请简述 {tag} 题二', answer='参考答案二',
                       score=10)
        judge = Question(exam_id=exam.id, question_type='judge',
                         content=f'{tag} 判断题', answer='对', score=5)
        db.session.add_all([sa1, sa2, judge])
        db.session.flush()

        stu = Student(name=f'审查0913简答生{tag}',
                      student_number=f'{STU_PREFIX}{tag}')
        stu.set_password('Rev0913#')
        stu.has_changed_password = True
        stu.is_activated = True
        db.session.add(stu)
        db.session.flush()
        # 有开考记录才允许交卷（未开考且未收卷会被 403 拦下）
        db.session.add(ExamAttempt(student_id=stu.id, exam_id=exam.id))
        db.session.commit()

        return {'exam': exam.id, 'student': stu.id,
                'sa1': sa1.id, 'sa2': sa2.id, 'judge': judge.id}


def _cleanup_all():
    """按前缀清空本文件产生的一切行（含 Log，交卷会写日志）。

    每条语句只带自己用得到的绑定参数：db.text() 的参数字典多给键
    未必安全，不依赖驱动的宽容行为。
    """
    conn = db.session.connection()
    p = {'p': EXAM_PREFIX + '%'}
    s = {'s': STU_PREFIX + '%'}
    q = "SELECT id FROM exam WHERE name LIKE :p"
    for sql, params in (
        ("DELETE FROM log WHERE user_type='student' AND user_id IN "
         "(SELECT id FROM student WHERE student_number LIKE :s)", s),
        (f"DELETE FROM result WHERE exam_id IN ({q})", p),
        (f"DELETE FROM exam_attempt WHERE exam_id IN ({q})", p),
        (f"DELETE FROM exam_question WHERE exam_id IN ({q})", p),
        (f"DELETE FROM question WHERE exam_id IN ({q})", p),
        ("DELETE FROM exam WHERE name LIKE :p", p),
        ("DELETE FROM student WHERE student_number LIKE :s", s),
    ):
        conn.execute(db.text(sql), params)
    # 必须提交：session.connection() 开启事务，会话销毁时未提交即回滚，
    # 清理会静默失效（test_review_fixes_0910.py 就踩过这个坑）
    db.session.commit()


def _student_client(app, student_id, tag):
    client = app.test_client()
    with client.session_transaction() as s:
        s.clear()
        s['student_id'] = student_id
        s['student_name'] = f'审查0913简答生{tag}'
        s['student_class_id'] = None
        s['csrf_token'] = CSRF
    return client


def _admin_client(app):
    """批改页走 @teacher_login_required，管理员默认拥有教师权限。"""
    client = app.test_client()
    with client.session_transaction() as s:
        s.clear()
        s['is_admin'] = True
        s['csrf_token'] = CSRF
    return client


def _result(app, ids):
    with app.app_context():
        r = Result.query.filter_by(student_id=ids['student'],
                                   exam_id=ids['exam']).first()
        assert r is not None, '交卷未落库'
        # 提前把值取出来：会话关闭后惰性属性会 DetachedInstanceError
        return {'id': r.id, 'total_score': r.total_score,
                'grading_status': r.grading_status,
                'scores': json.loads(r.scores or '{}'),
                'manual_scores': json.loads(r.manual_scores or 'null')}


# ── 核心回归 ──────────────────────────────────────

def test_unsubmitted_short_answer_recorded_as_auto_graded(app):
    """学生整卷未作答：两道简答题都须以「自动批改 0 分」出现在批改数据里。

    修复前这两题在 scores 与 manual_scores 中**都不存在**，教师批改页
    直接跳回列表并提示「该学生没有需要批改的开放式试题」。
    """
    ids = _seed(app, 'missing')
    client = _student_client(app, ids['student'], 'missing')
    resp = client.post(f"/submit_exam/{ids['exam']}", json={},
                       headers={'X-CSRFToken': CSRF})

    assert resp.status_code == 200
    assert resp.get_json()['success'] is True

    r = _result(app, ids)
    for key in (str(ids['sa1']), str(ids['sa2'])):
        assert r['scores'][key] == 0, '开放式试题未提交应记 0 分'
        info = r['manual_scores'][key]
        assert info['manual_score'] == 0
        assert info['auto_graded'] is True
        assert info['student_answer'] == ''
        assert info['max_score'] == 10
    assert r['total_score'] == 0
    # 状态不变：不产生待批改人数（教师无需逐条处理）
    assert r['grading_status'] == 'auto_graded'


def test_non_open_ended_missing_key_leaves_scores_untouched(app):
    """判断题（非开放式）键缺失时行为不变：不得被凭空补进 scores。

    它们本就由判分器自动出分、教师无需介入；补进去只会改变趋势页
    正确率统计的分母。
    """
    ids = _seed(app, 'judge')
    client = _student_client(app, ids['student'], 'judge')
    client.post(f"/submit_exam/{ids['exam']}", json={},
                headers={'X-CSRFToken': CSRF})

    r = _result(app, ids)

    assert str(ids['judge']) not in r['scores']
    assert str(ids['judge']) not in r['manual_scores']


def test_submitted_blank_short_answer_same_shape_as_missing(app):
    """「已提交但答案为空」与「键缺失」必须同规——这是原就正确的路径，
    修复不得把它带偏。"""
    ids = _seed(app, 'blank')
    client = _student_client(app, ids['student'], 'blank')
    client.post(f"/submit_exam/{ids['exam']}",
                json={str(ids['sa1']): '   ', str(ids['sa2']): '   '},
                headers={'X-CSRFToken': CSRF})

    r = _result(app, ids)

    for key in (str(ids['sa1']), str(ids['sa2'])):
        assert r['scores'][key] == 0
        assert r['manual_scores'][key]['manual_score'] == 0
        assert r['manual_scores'][key]['auto_graded'] is True
    assert r['grading_status'] == 'auto_graded'


def test_answered_short_answer_still_needs_manual_grading(app):
    """有作答内容的简答题仍须进人工批改队列（不得被误并入自动批改）。"""
    ids = _seed(app, 'answered')
    client = _student_client(app, ids['student'], 'answered')
    client.post(f"/submit_exam/{ids['exam']}",
                json={str(ids['sa1']): '我的作答内容', str(ids['sa2']): ''},
                headers={'X-CSRFToken': CSRF})

    r = _result(app, ids)

    assert r['manual_scores'][str(ids['sa1'])]['manual_score'] is None
    assert r['manual_scores'][str(ids['sa1'])]['auto_graded'] is False
    # 同一份卷里"未提交的那道"依然按自动批改记录，两者互不干扰
    assert r['manual_scores'][str(ids['sa2'])]['auto_graded'] is True
    assert r['grading_status'] == 'pending_review'


# ── 教师可见结果（用户侧可感知的最终形态）─────────────

def test_grading_page_renders_editable_auto_graded_card(app):
    """批改页必须显示标「自动批改」且**可改分**的卡片，而不是跳回列表。

    这是本轮修复对教师唯一可见的产出：修复前 GET 该页会 302 回列表并
    flash「该学生没有需要批改的开放式试题」，教师看不到任何东西。
    """
    ids = _seed(app, 'page')
    client = _student_client(app, ids['student'], 'page')
    client.post(f"/submit_exam/{ids['exam']}", json={},
                headers={'X-CSRFToken': CSRF})
    result_id = _result(app, ids)['id']

    resp = _admin_client(app).get(
        f"/admin/grading/{ids['exam']}/{result_id}")

    assert resp.status_code == 200, '修复前这里是 302 跳回列表'
    html = resp.get_data(as_text=True)
    assert '自动批改' in html
    assert '学生未作答' in html
    # 可编辑：输入框存在且初值为自动批改的 0（教师可直接改分）
    m = re.search(rf'id="score_{ids["sa1"]}".*?value="([^"]*)"',
                  html, re.S)
    assert m, '批改卡片缺少分值输入框'
    assert m.group(1) == '0'
    # 满分上限来自题目分值（Question.score 为 Float，渲染成 10.0）
    assert 'max="10.0"' in html, '满分上限必须来自题目分值'