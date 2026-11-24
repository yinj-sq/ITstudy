# -*- coding: utf-8 -*-
"""题库/试卷解耦 + 组卷功能 回归测试

覆盖：
- 建题带 exam_id 自动挂卷（旧流程兼容）；exam_id=NULL 纯题库题 0 卷
- 组卷 add/remove/reorder；总分 = 各题分值汇总
- 题型分组序（single 在 judge 前）与全局题号连续
- 一题多卷；有成绩锁组卷（409）；删卷不再被题目阻碍；删题级联链接
"""
import pytest
from sqlalchemy import text

from app import create_app
from app.extensions import db
from app.models import (Class, Exam, ExamQuestion, Question,
                        exam_questions_flat, exam_questions_ordered,
                        exam_total_score)

_CSRF = 't'


@pytest.fixture(scope='module')
def app():
    app = create_app()
    # 幂等预清理（上次中断残留；顺序：成绩→在考→关联→题目→试卷）
    with app.app_context():
        conn = db.session.connection()
        conn.execute(text("DELETE FROM result WHERE exam_id IN "
                          "(SELECT id FROM exam WHERE name LIKE '组卷测试%')"))
        conn.execute(text("DELETE FROM exam_attempt WHERE exam_id IN "
                          "(SELECT id FROM exam WHERE name LIKE '组卷测试%')"))
        conn.execute(text("DELETE FROM exam_question WHERE exam_id IN "
                          "(SELECT id FROM exam WHERE name LIKE '组卷测试%')"))
        conn.execute(text("DELETE FROM question WHERE content LIKE '组卷测试题%'"))
        conn.execute(text("DELETE FROM exam WHERE name LIKE '组卷测试%'"))
        conn.execute(text("DELETE FROM classes WHERE name='组卷测试班'"))
        db.session.commit()
    yield app
    with app.app_context():
        conn = db.session.connection()
        conn.execute(text("DELETE FROM result WHERE exam_id IN "
                          "(SELECT id FROM exam WHERE name LIKE '组卷测试%')"))
        conn.execute(text("DELETE FROM exam_attempt WHERE exam_id IN "
                          "(SELECT id FROM exam WHERE name LIKE '组卷测试%')"))
        conn.execute(text('DELETE FROM exam_question WHERE exam_id IN '
                          '(SELECT id FROM exam WHERE name LIKE \'组卷测试%\')'))
        conn.execute(text('DELETE FROM question WHERE id > 0 AND exam_id IS NULL'
                          ' AND content LIKE \'组卷测试题%\''))
        conn.execute(text('DELETE FROM question WHERE content LIKE \'组卷测试题%\''))
        conn.execute(text('DELETE FROM exam WHERE name LIKE \'组卷测试%\''))
        db.session.commit()


def _login(client):
    with client.session_transaction() as s:
        s.clear()
        s['is_admin'] = True
        s['csrf_token'] = _CSRF


def _mk_q(content, qtype='single', score=2.0, exam_id=None):
    q = Question(exam_id=exam_id, question_type=qtype, content=content,
                 options='A.1|B.2', answer='A', score=score)
    db.session.add(q)
    db.session.flush()
    return q


def _mk_exam(name):
    e = Exam(name=name, is_active=True, duration=30)
    db.session.add(e)
    db.session.flush()
    return e


def test_auto_link_and_bank_only(app):
    """建题带 exam_id 自动挂卷（兼容旧流程）；NULL=纯题库题 0 卷"""
    with app.app_context():
        e = _mk_exam('组卷测试·自动挂卷')
        q1 = _mk_q('组卷测试题·旧流程', exam_id=e.id)   # 旧流程：建题即入卷
        q2 = _mk_q('组卷测试题·纯题库')                  # 解耦：0 卷
        db.session.commit()
        assert [q.id for q in e.questions] == [q1.id]
        assert q2.exam_links == []
        assert q2.exam_id is None
        # 清理（fixture 前缀删除不含该卷名）
        db.session.delete(q1)
        db.session.delete(q2)
        db.session.delete(e)
        db.session.commit()


def test_compose_add_total_and_type_order(app):
    """组卷添加 + 总分汇总 + 题型分组序（judge 组在 single 前? 否——single 序 0 最前）"""
    c = app.test_client()
    _login(c)
    with app.app_context():
        e = _mk_exam('组卷测试·汇总')
        q_j = _mk_q('组卷测试题·判断', qtype='judge', score=3.0)
        q_s1 = _mk_q('组卷测试题·单选1', qtype='single', score=2.0)
        q_s2 = _mk_q('组卷测试题·单选2', qtype='single', score=2.5)
        db.session.commit()
        eid, jid, s1, s2 = e.id, q_j.id, q_s1.id, q_s2.id
    # 乱序加入：判断题先加 → 分组序仍 single 组在前
    r = c.post(f'/admin/exams/{eid}/compose/add', json={'question_ids': [jid, s1, s2]},
               headers={'X-CSRFToken': _CSRF})
    d = r.get_json()
    assert d['success'] and d['added'] == 3, d
    data = d['data']
    assert data['question_count'] == 3
    assert abs(data['total_score'] - 7.5) < 0.01        # 总分=Σ题分
    seqs = [q['seq'] for q in data['questions']]
    assert seqs == [1, 2, 3]                            # 全局题号连续
    types = [q['question_type'] for q in data['questions']]
    assert types == ['single', 'single', 'judge']       # 分组：single(0) → judge(2)

    # 重复添加幂等
    r2 = c.post(f'/admin/exams/{eid}/compose/add', json={'question_ids': [s1]},
                headers={'X-CSRFToken': _CSRF})
    assert r2.get_json()['added'] == 0

    with app.app_context():
        db.session.execute(text('DELETE FROM exam_question WHERE exam_id=:e'),
                           {'e': eid})
        db.session.delete(db.session.get(Exam, eid))
        db.session.commit()


def test_compose_remove_reorder_multi_exam(app):
    """移除/排序 + 一题多卷"""
    c = app.test_client()
    _login(c)
    with app.app_context():
        e1 = _mk_exam('组卷测试·卷A')
        e2 = _mk_exam('组卷测试·卷B')
        q = _mk_q('组卷测试题·共享', score=4.0)
        db.session.commit()
        e1id, e2id, qid = e1.id, e2.id, q.id
    # 同一题加入两卷（多卷归属）
    r1 = c.post(f'/admin/exams/{e1id}/compose/add', json={'question_ids': [qid]},
                headers={'X-CSRFToken': _CSRF})
    r2 = c.post(f'/admin/exams/{e2id}/compose/add', json={'question_ids': [qid]},
                headers={'X-CSRFToken': _CSRF})
    assert r1.get_json()['added'] == 1 and r2.get_json()['added'] == 1
    with app.app_context():
        assert len(db.session.get(Question, qid).exam_links) == 2

    # 再加一题到卷A，随后移除共享题 → 卷A剩1题且序号重排
    with app.app_context():
        q2 = _mk_q('组卷测试题·卷A独有', score=1.0)
        db.session.commit()
        q2id = q2.id
    c.post(f'/admin/exams/{e1id}/compose/add', json={'question_ids': [q2id]},
           headers={'X-CSRFToken': _CSRF})
    rr = c.post(f'/admin/exams/{e1id}/compose/remove', json={'question_id': qid},
                headers={'X-CSRFToken': _CSRF})
    d = rr.get_json()
    assert d['removed'] and d['data']['question_count'] == 1
    assert d['data']['questions'][0]['seq'] == 1
    assert abs(d['data']['total_score'] - 1.0) < 0.01
    # 共享题仍在卷B
    with app.app_context():
        assert [q.id for q in exam_questions_flat(e2id)] == [qid]

    # reorder：把 q2 排到自身（唯一）→ 幂等
    ro = c.post(f'/admin/exams/{e1id}/compose/reorder', json={'order': [q2id]},
                headers={'X-CSRFToken': _CSRF})
    assert ro.get_json()['success']

    # 清理
    with app.app_context():
        for eid in (e1id, e2id):
            db.session.execute(text(
                'DELETE FROM exam_question WHERE exam_id=:e'), {'e': eid})
            db.session.delete(db.session.get(Exam, eid))
        db.session.delete(db.session.get(Question, qid))
        db.session.delete(db.session.get(Question, q2id))
        db.session.commit()


def test_compose_locked_with_results(app):
    """有成绩的试卷：组卷增/删/排序一律 409 锁定"""
    c = app.test_client()
    _login(c)
    with app.app_context():
        cls = Class(name='组卷测试班')
        db.session.add(cls)
        db.session.flush()
        e = _mk_exam('组卷测试·锁定')
        q = _mk_q('组卷测试题·锁定', score=5.0)
        db.session.commit()
        from app.models import Result
        res = Result(student_id=None, exam_id=e.id, answers='{}', scores='{}',
                     total_score=0, grading_status='auto_graded')
        db.session.add(res)
        db.session.commit()
        eid, qid, clsid = e.id, q.id, cls.id
    for action, payload in (('add', {'question_ids': [qid]}),
                            ('remove', {'question_id': qid}),
                            ('reorder', {'order': [qid]})):
        r = c.post(f'/admin/exams/{eid}/compose/{action}', json=payload,
                   headers={'X-CSRFToken': _CSRF})
        assert r.status_code == 409, (action, r.status_code)
    # 删卷也被成绩阻碍（既有保护保持）
    r = c.post(f'/admin/exams/delete/{eid}', follow_redirects=False,
               headers={'X-CSRFToken': _CSRF})
    assert r.status_code == 302  # flash 拒绝并重定向
    with app.app_context():
        db.session.execute(text('DELETE FROM result WHERE exam_id=:e'), {'e': eid})
        db.session.execute(text('DELETE FROM exam_question WHERE exam_id=:e'), {'e': eid})
        db.session.delete(db.session.get(Exam, eid))
        db.session.delete(db.session.get(Question, qid))
        db.session.delete(db.session.get(Class, clsid))
        db.session.commit()


def test_delete_exam_keeps_questions_and_deletes_links(app):
    """解耦核心：删卷不再被题目阻碍；题目本体保留题库；关联行清理"""
    c = app.test_client()
    _login(c)
    with app.app_context():
        e = _mk_exam('组卷测试·删卷保留题')
        q = _mk_q('组卷测试题·幸存', exam_id=e.id, score=2.0)  # 自动挂卷
        db.session.commit()
        eid, qid = e.id, q.id
    r = c.post(f'/admin/exams/delete/{eid}', follow_redirects=False,
               headers={'X-CSRFToken': _CSRF})
    assert r.status_code == 302  # 成功（flash），不再因"包含题目"被拒
    with app.app_context():
        assert db.session.get(Exam, eid) is None
        assert ExamQuestion.query.filter_by(exam_id=eid).count() == 0
        q = db.session.get(Question, qid)
        assert q is not None and q.exam_links == []
        # 题目仍在题库，可再次组卷复用
        e2 = _mk_exam('组卷测试·复用')
        db.session.commit()
        _login(c)
        ra = c.post(f'/admin/exams/{e2.id}/compose/add',
                     json={'question_ids': [qid]},
                     headers={'X-CSRFToken': _CSRF})
        assert ra.get_json()['added'] == 1
        db.session.execute(text('DELETE FROM exam_question WHERE exam_id=:e'),
                           {'e': e2.id})
        db.session.delete(db.session.get(Exam, e2.id))
        db.session.delete(db.session.get(Question, qid))
        db.session.commit()


def test_type_grouped_order_helper(app):
    """统一排序助手：题型分组 + position + 全局题号（跨页共用口径）"""
    with app.app_context():
        e = _mk_exam('组卷测试·排序口径')
        qc = _mk_q('组卷测试题·综合', qtype='comprehensive', score=10.0)
        qs = _mk_q('组卷测试题·单选', qtype='single', score=2.0)
        qf = _mk_q('组卷测试题·填空', qtype='fill', score=6.0)
        db.session.commit()
        # 添加顺序：综合→单选→填空（乱序）→ 分组序应为 单选→填空→综合
        for q in (qc, qs, qf):
            db.session.add(ExamQuestion(exam_id=e.id, question_id=q.id,
                                        position=1))
        db.session.commit()
        pairs = exam_questions_ordered(e.id)
        assert [q.question_type for q, _ in pairs] == ['single', 'fill', 'comprehensive']
        assert [seq for _, seq in pairs] == [1, 2, 3]
        assert abs(exam_total_score(e.id) - 18.0) < 0.01
        db.session.execute(text('DELETE FROM exam_question WHERE exam_id=:e'),
                           {'e': e.id})
        for q in (qc, qs, qf):
            db.session.delete(q)
        db.session.delete(e)
        db.session.commit()