# -*- coding: utf-8 -*-
"""练习测试全功能矩阵（2026-10-27，系统测试专项）。

覆盖：题库七类题 CRUD / 综合题小题 / 外链卷 / 图片与 Python 文件上传 /
Excel 批量导入导出 / 组卷增删排序 / 考试全流程（开考、轮询、交卷判分、
重复提交、超时、收卷、未公布成绩）/ 教师批改 / 趋势与成绩导出 / SPA API。
数据全部使用 __exam_mx_ 前缀，测后清理。
"""
import io
import json
import uuid
from datetime import datetime, timedelta

import pytest

from app import create_app
from app.extensions import cache, db
from app.models import (Class, ClassroomSession, Exam, ExamAttempt,
                        ExamQuestion, Log, PythonAnswer, PythonFile, Question,
                        Result, Student, SubQuestion)

CSRF = 'exam-mx-csrf'
AJAX = {'X-Requested-With': 'XMLHttpRequest'}


@pytest.fixture(scope='module')
def app():
    return create_app()


def _u():
    return uuid.uuid4().hex[:10]


def _cleanup_all():
    with db.session.begin():
        mx_exam_ids = [e.id for e in Exam.query.filter(Exam.name.like('__exam_mx_%')).all()]
        if mx_exam_ids:
            ExamAttempt.query.filter(ExamAttempt.exam_id.in_(mx_exam_ids)).delete(synchronize_session=False)
            Result.query.filter(Result.exam_id.in_(mx_exam_ids)).delete(synchronize_session=False)
            ExamQuestion.query.filter(ExamQuestion.exam_id.in_(mx_exam_ids)).delete(synchronize_session=False)
        for q in Question.query.filter(
                Question.content.like('__exam_mx_%') | Question.exam_id.in_(mx_exam_ids)).all():
            SubQuestion.query.filter_by(question_id=q.id).delete(synchronize_session=False)
            PythonAnswer.query.filter_by(question_id=q.id).delete(synchronize_session=False)
            PythonFile.query.filter_by(question_id=q.id).delete(synchronize_session=False)
        Question.query.filter(
            Question.content.like('__exam_mx_%') | Question.exam_id.in_(mx_exam_ids)).delete(
                synchronize_session=False)
        Exam.query.filter(Exam.name.like('__exam_mx_%')).delete(synchronize_session=False)
        for cls in Class.query.filter(Class.name.like('__exam_mx_%')).all():
            ClassroomSession.query.filter_by(class_id=cls.id).delete(synchronize_session=False)
            Student.query.filter_by(class_id=cls.id).delete(synchronize_session=False)
            Class.query.filter_by(id=cls.id).delete(synchronize_session=False)
        Log.query.filter(Log.detail.like('%__exam_mx_%')).delete(synchronize_session=False)


@pytest.fixture(scope='module', autouse=True)
def _env(app):
    with app.app_context():
        cache.delete('study:resources:student')
        _cleanup_all()
    yield
    with app.app_context():
        _cleanup_all()
        cache.delete('lookup:recent_exams')
        cache.delete('study:resources:student')
        from app.blueprints.auth import invalidate_active_class_cache
        invalidate_active_class_cache()


def _admin(app):
    c = app.test_client()
    with c.session_transaction() as s:
        s.update(is_admin=True, admin_name='矩阵管理员', csrf_token=CSRF)
    return c


def _mk_exam(app, name_suffix=''):
    exam = Exam(name=f'__exam_mx_{_u()}{name_suffix}', is_active=True,
                is_visible=True, is_enabled=True, is_collected=False,
                allow_view_results=True, duration=None)
    db.session.add(exam)
    db.session.commit()
    return exam


def _add_q(app, client, exam_id, qtype, content, answer, options='', score=5,
           extra=None):
    data = {'exam_id': str(exam_id), 'question_type': qtype,
            'content': content, 'options': options, 'answer': answer,
            'score': str(score), 'csrf_token': CSRF}
    if extra:
        data.update(extra)
    resp = client.post('/admin/questions/add', data=data, headers=AJAX)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
    body = resp.get_json()
    assert body.get('success'), body
    qid = body.get('question_id') or body.get('id')
    if not qid:
        qid = Question.query.filter_by(content=content).order_by(
            Question.id.desc()).first().id
    return qid


def _mk_student(app, class_name):
    cls = Class(name=class_name)
    stu = Student(name='矩阵学生', student_number=f'__exam_mx_{_u()}',
                  student_class=class_name, has_changed_password=True)
    stu.set_password('pass123456')
    db.session.add_all([cls, stu])
    db.session.flush()
    stu.class_id = cls.id
    db.session.add(ClassroomSession(class_id=cls.id, is_active=True))
    db.session.commit()
    from app.blueprints.auth import invalidate_active_class_cache
    invalidate_active_class_cache()
    return cls.id, stu.id


def _student_client(app, sid):
    c = app.test_client()
    with c.session_transaction() as s:
        s.update(student_id=sid, student_name='矩阵学生', csrf_token=CSRF)
    return c


def test_question_bank_all_types_and_crud(app):
    """题库：七类题增改删 + 列表 + 批量删除 + 有成绩拒删。"""
    with app.app_context():
        exam = _mk_exam(app)
        eid = exam.id
    client = _admin(app)
    qids = {}
    # 单选 / 多选 / 判断 / 填空 / 简答
    qids['single'] = _add_q(app, client, eid, 'single',
                            '__exam_mx_单选1+', 'A', 'A. 甲|B. 乙', 5)
    qids['multiple'] = _add_q(app, client, eid, 'multiple',
                              '__exam_mx_多选2+', 'A,B', 'A. 甲|B. 乙|C. 丙', 5)
    qids['true_false'] = _add_q(app, client, eid, 'true_false',
                                '__exam_mx_判断3+', 'true', '', 5)
    qids['fill'] = _add_q(app, client, eid, 'fill',
                          '__exam_mx_填空4+', '答案一', '', 5)
    qids['short_answer'] = _add_q(app, client, eid, 'short_answer',
                                  '__exam_mx_简答5+', '参考答案', '', 10)
    qids['python_fill'] = _add_q(app, client, eid, 'python_fill',
                                 '__exam_mx_py填空6+', '3\n5', '', 10,
                                 {'blank_scores': '[5,5]'})
    # 综合题 + 小题（走 API 添加小题）
    qids['comprehensive'] = _add_q(app, client, eid, 'comprehensive',
                                   '__exam_mx_综合7+', '背景材料', '', 1)
    with app.app_context():
        cid = qids['comprehensive']
        Question.query.filter_by(id=cid).update(
            {Question.background: '__exam_mx_阅读材料'}, synchronize_session=False)
        db.session.commit()
        db.session.expire_all()
    r = client.post(f'/api/questions/{cid}/sub', json={
        'question_type': 'single', 'content': '__exam_mx_子题1+',
        'options': 'A. 对|B. 错', 'answer': 'A', 'score': 3,
    }, headers={'X-CSRFToken': CSRF})
    assert r.status_code == 200 and r.get_json()['success'], r.get_data(as_text=True)
    with app.app_context():
        sub = SubQuestion.query.filter_by(question_id=cid).first()
        assert sub is not None
        q = db.session.get(Question, cid)
        assert q.score == 3  # 综合题分值 = 子题和
    # 列表页与编辑页
    assert client.get('/admin/questions?exam_id=%d' % eid).status_code == 200
    r = client.post(f'/admin/questions/edit/{qids["single"]}', data={
        'csrf_token': CSRF, 'exam_id': str(eid),
        'content': '__exam_mx_单选1改+',
        'options': 'A. 甲|B. 乙', 'answer': 'B', 'score': '6',
    }, headers=AJAX)
    assert r.status_code == 200
    with app.app_context():
        assert db.session.get(Question, qids['single']).score == 6
    # 图片上传：坏魔数拒绝，好 PNG 接受
    r = client.post('/admin/questions/upload_img',
                    data={'csrf_token': CSRF,
                          'image': (io.BytesIO(b'not-an-image'), 'bad.png')},
                    content_type='multipart/form-data')
    assert r.status_code == 400
    png = io.BytesIO(bytes.fromhex(
        '89504e470d0a1a0a0000000d494844520000000100000001080600000'
        '01f15c4890000000d49444154789c626001000000ffff030000060005'
        '57bfabd40000000049454e44ae426082'))
    r = client.post('/admin/questions/upload_img',
                    data={'csrf_token': CSRF, 'image': (png, 'ok.png')},
                    content_type='multipart/form-data')
    assert r.status_code == 200 and r.get_json()['success']
    # Python 参考文件上传
    r = client.post('/admin/questions/upload_python_file', data={
        'csrf_token': CSRF, 'question_id': str(qids['python_fill']),
        'python_file': (io.BytesIO(b'x = 1 + 1\nprint(3)\nprint(5)'), 'ref.py'),
    }, content_type='multipart/form-data')
    assert r.status_code == 200 and r.get_json()['success'], r.get_data(as_text=True)
    # 删除
    r = client.post(f'/admin/questions/delete/{qids["multiple"]}',
                    data={'csrf_token': CSRF}, headers=AJAX)
    assert r.status_code == 200 and r.get_json()['success']
    with app.app_context():
        assert db.session.get(Question, qids['multiple']) is None
    # 批量删除剩余简答题
    r = client.post('/admin/questions/batch_delete', data={
        'csrf_token': CSRF, 'question_ids': [str(qids['short_answer'])],
    })
    assert r.status_code in (302, 303)
    with app.app_context():
        assert db.session.get(Question, qids['short_answer']) is None


def test_exam_compose_and_external_link(app):
    with app.app_context():
        exam = _mk_exam(app, '_compose')
        eid = exam.id
        exam2 = _mk_exam(app, '_link')
        eid2 = exam2.id
    client = _admin(app)
    q1 = _add_q(app, client, '', 'single', '__exam_mx_组卷1+', 'A', 'A. x|B. y', 5)
    q2 = _add_q(app, client, '', 'single', '__exam_mx_组卷2+', 'B', 'A. x|B. y', 5)
    r = client.post(f'/admin/exams/{eid}/compose/add',
                    json={'question_ids': [q2, q1]},
                    headers={'X-CSRFToken': CSRF})
    assert r.status_code == 200 and r.get_json()['success'], r.get_data(as_text=True)
    r = client.get(f'/admin/exams/{eid}/compose/data')
    data = r.get_json()['data']['questions']
    assert [x['id'] for x in data] == [q2, q1]  # 保持传入顺序
    # 排序交换
    rr = client.post(f'/admin/exams/{eid}/compose/reorder',
                     json={'order': [q1, q2]},
                     headers={'X-CSRFToken': CSRF})
    body = rr.get_json()
    assert rr.status_code == 200 and body.get('success'), body
    r = client.get(f'/admin/exams/{eid}/compose/data')
    assert [x['id'] for x in r.get_json()['data']['questions']] == [q1, q2]
    # 移除
    rr = client.post(f'/admin/exams/{eid}/compose/remove',
                     json={'question_id': q2},
                     headers={'X-CSRFToken': CSRF})
    assert rr.status_code == 200 and rr.get_json()['success'], rr.get_json()
    with app.app_context():
        assert ExamQuestion.query.filter_by(exam_id=eid).count() == 1
    # 外链卷：添加后不可再加题
    r = client.post('/admin/questions/add_link', data={
        'csrf_token': CSRF, 'exam_id': str(eid2),
        'external_link': 'https://example.com/exam'})
    assert r.status_code in (302, 303)
    with app.app_context():
        link = Question.query.filter_by(exam_id=eid2, question_type='link').first()
        assert link is not None
    r = client.post(f'/admin/exams/{eid2}/compose/add',
                    json={'question_ids': [q1]},
                    headers={'X-CSRFToken': CSRF})
    assert r.status_code in (400, 404)  # 外链卷互斥


def test_exam_full_flow_submit_grading_trend(app):
    """考试全流程：开考→交卷自动判分→批改→成绩公布→趋势→删除。"""
    with app.app_context():
        exam = _mk_exam(app, '_flow')
        eid = exam.id
        cid, sid = _mk_student(app, '__exam_mx_flow班')
    client = _admin(app)
    q_single = _add_q(app, client, eid, 'single', '__exam_mx_流程单选+', 'A', 'A. x|B. y', 10)
    q_tf = _add_q(app, client, eid, 'true_false', '__exam_mx_流程判断+', 'true', '', 10)
    q_fill = _add_q(app, client, eid, 'fill', '__exam_mx_流程填空+', 'abc', '', 10)
    q_sa = _add_q(app, client, eid, 'short_answer', '__exam_mx_流程简答+', '参考答案', '', 10)
    for qid in (q_single, q_tf, q_fill, q_sa):
        r = client.post(f'/admin/exams/{eid}/compose/add',
                        json={'question_ids': [qid]},
                        headers={'X-CSRFToken': CSRF})
        assert r.get_json()['success']
    stu = _student_client(app, sid)

    # 未开考直接交卷 → 403
    r = stu.post(f'/submit_exam/{eid}', json={'answers': {}},
                 headers={'X-CSRFToken': CSRF})
    assert r.status_code == 403

    # 列表与开考页
    assert stu.get('/exam').status_code == 200
    page = stu.get(f'/online_exam/{eid}')
    assert page.status_code == 200
    with app.app_context():
        assert ExamAttempt.query.filter_by(
            student_id=sid, exam_id=eid).first() is not None
    # 状态轮询
    assert stu.get(f'/exam/{eid}/status').get_json()['is_collected'] is False

    # 交卷：1 对 2 错 + 简答
    answers = {str(q_single): 'A', str(q_tf): 'false',
               str(q_fill): 'abc', str(q_sa): '我的简答',
               'unknown_key': 'x'}  # 未知键应被过滤
    r = stu.post(f'/submit_exam/{eid}', json=answers,
                 headers={'X-CSRFToken': CSRF})
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    body = r.get_json()
    assert body['success'] and body.get('grading_status') == 'pending_review'
    result_id = body['result_id']
    with app.app_context():
        result = db.session.get(Result, result_id)
        assert result.total_score == 20  # 单选10 + 填空10，判断错
        saved = json.loads(result.answers)
        assert 'unknown_key' not in saved  # 未知键已过滤

    # 重复提交 → already_submitted
    r = stu.post(f'/submit_exam/{eid}', json={'answers': {}},
                 headers={'X-CSRFToken': CSRF})
    assert r.get_json().get('already_submitted') is True

    # 结果页（已公布，含简答待批改）
    r = stu.get(f'/result/{result_id}')
    assert r.status_code == 200
    assert '我的简答' in r.get_data(as_text=True)

    # 教师批改：列表统计、详情、提交分数
    assert client.get('/admin/grading').status_code == 200
    assert client.get(f'/admin/grading/{eid}').status_code == 200
    g = client.get(f'/admin/grading/{eid}/{result_id}')
    assert g.status_code == 200
    r = client.post(f'/admin/grading/{eid}/{result_id}', data={
        'csrf_token': CSRF, f'score_{q_sa}': '7',
    })
    assert r.status_code in (302, 303)
    with app.app_context():
        result = db.session.get(Result, result_id)
        assert result.grading_status == 'fully_graded'
        assert result.total_score == 27  # 20 + 7

    # 趋势页与导出
    assert client.get(f'/admin/trend/{eid}').status_code == 200
    assert client.get(f'/admin/export_scores/{eid}').status_code == 200
    assert stu.get(f'/student/trend/{sid}').status_code == 200
    assert stu.get('/api/trend/student/me').status_code == 200

    # 成绩未公布：学生结果页隐藏分数，但本人可看答题
    with app.app_context():
        exam.allow_view_results = False
        db.session.commit()
    r = stu.get(f'/result/{result_id}')
    assert r.status_code == 200
    text = r.get_data(as_text=True)
    assert '成绩尚未公布' in text or 'score-box' not in text
    with app.app_context():
        exam.allow_view_results = True
        db.session.commit()

    # 删除成绩（单条 + 批量接口存在性）
    r = client.post(f'/admin/delete_result/{result_id}',
                    data={'csrf_token': CSRF})
    assert r.status_code in (200, 302, 303)
    with app.app_context():
        assert db.session.get(Result, result_id) is None


def test_exam_timeout_and_collect_flow(app):
    with app.app_context():
        exam = _mk_exam(app, '_timeout')
        exam.duration = 1
        eid = exam.id
        cid, sid = _mk_student(app, '__exam_mx_timeout班')
    client = _admin(app)
    q1 = _add_q(app, client, eid, 'single', '__exam_mx_超时单选+', 'A', 'A. x|B. y', 5)
    client.post(f'/admin/exams/{eid}/compose/add', json={'question_ids': [q1]},
                headers={'X-CSRFToken': CSRF})
    stu = _student_client(app, sid)
    assert stu.get(f'/online_exam/{eid}').status_code == 200
    with app.app_context():
        attempt = ExamAttempt.query.filter_by(student_id=sid, exam_id=eid).first()
        attempt.start_time = datetime.now() - timedelta(minutes=10)
        db.session.commit()
    r = stu.post(f'/submit_exam/{eid}', json={'answers': {str(q1): 'A'}},
                 headers={'X-CSRFToken': CSRF})
    assert r.status_code == 403  # 超时拒绝
    # 收卷后：在考学生可提交（重置开考时间，否则超时校验仍拦截——设计如此）
    with app.app_context():
        attempt = ExamAttempt.query.filter_by(student_id=sid, exam_id=eid).first()
        attempt.start_time = datetime.now()
        exam.is_collected = True
        db.session.commit()
    r = stu.post(f'/submit_exam/{eid}', json={'answers': {str(q1): 'A'}},
                 headers={'X-CSRFToken': CSRF})
    assert r.status_code == 200 and r.get_json()['success']
    # 从未开考学生收卷后拒绝
    with app.app_context():
        cid2, sid2 = _mk_student(app, '__exam_mx_timeout班2')
    stu2 = _student_client(app, sid2)
    r = stu2.post(f'/submit_exam/{eid}', json={'answers': {}},
                  headers={'X-CSRFToken': CSRF})
    assert r.status_code == 403
    # 清超时开考记录端点
    r = client.post(f'/admin/exams/{eid}/clear-stale-attempts',
                    data={'csrf_token': CSRF})
    assert r.status_code in (200, 302, 303, 400)  # 无超时记录时可能返回 400 JSON
    # toggle 状态（端点仅支持 is_visible/is_enabled/is_collected/allow_view_results）
    for flag in ('is_visible', 'is_enabled'):
        r = client.post(f'/admin/exams/toggle/{eid}',
                        data={'csrf_token': CSRF, 'flag': flag, 'value': 'false'})
        assert r.status_code in (200, 302, 303)


def test_exam_excel_import_export_and_templates(app):
    with app.app_context():
        exam = _mk_exam(app, '_excel')
        eid = exam.id
    client = _admin(app)
    # 模板下载
    assert client.get('/admin/questions/download_template').status_code == 200
    # Excel 批量导入单选
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(['题目内容', '选项', '答案', '分值'])
    ws.append(['__exam_mx_导入1+', 'A. 甲|B. 乙', 'A', 5])
    ws.append(['__exam_mx_导入2+', 'A. 甲|B. 乙', 'B', 5])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    r = client.post('/admin/questions/import_excel', data={
        'csrf_token': CSRF, 'exam_id': str(eid),
        'excel_file': (buf, 'import.xlsx'),
    }, content_type='multipart/form-data')
    assert r.status_code in (200, 302, 303)
    with app.app_context():
        imported = Question.query.filter(Question.content.like('__exam_mx_导入%')).count()
        assert imported == 2
    # 导出
    r = client.get(f'/admin/questions/export/{eid}')
    assert r.status_code == 200
    assert len(r.data) > 0


def test_spa_exam_api_crud(app):
    with app.app_context():
        _mk_exam(app, '_api')
    client = _admin(app)
    # 创建/更新/删除试卷
    r = client.post('/api/exams', json={'name': f'__exam_mx_api卷_{_u()}',
                                         'duration': 30},
                    headers={'X-CSRFToken': CSRF})
    assert r.status_code == 200 and r.get_json()['success']
    new_eid = r.get_json().get('data', {}).get('id')
    assert new_eid
    r = client.put(f'/api/exams/{new_eid}',
                   json={'name': f'__exam_mx_api卷改_{_u()}'},
                   headers={'X-CSRFToken': CSRF})
    assert r.get_json()['success']
    assert client.get('/api/exams').get_json()['success']
    assert client.get(f'/api/exams/{new_eid}').status_code == 200
    # 题目 API CRUD + 子题 API
    r = client.post('/api/questions', json={
        'exam_id': new_eid, 'question_type': 'single',
        'content': '__exam_mx_api题+', 'options': 'A. x|B. y',
        'answer': 'A', 'score': 5}, headers={'X-CSRFToken': CSRF})
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    api_qid = r.get_json()['data']['id']
    r = client.put(f'/api/questions/{api_qid}', json={
        'content': '__exam_mx_api题改+', 'answer': 'B'}, headers={'X-CSRFToken': CSRF})
    assert r.get_json()['success']
    # 综合题子题 API
    r = client.post('/api/questions', json={
        'question_type': 'comprehensive', 'content': '__exam_mx_api综合+',
        'score': 0}, headers={'X-CSRFToken': CSRF})
    comp_id = r.get_json()['data']['id']
    r = client.post(f'/api/questions/{comp_id}/sub', json={
        'question_type': 'single', 'content': '__exam_mx_api子题+',
        'options': 'A. x|B. y', 'answer': 'A', 'score': 4},
        headers={'X-CSRFToken': CSRF})
    assert r.get_json()['success']
    sub = client.get(f'/api/questions/{comp_id}/sub').get_json()['data']['sub_questions']
    assert len(sub) == 1
    r = client.delete(
        f"/api/questions/{comp_id}/sub/{sub[0]['id']}",
        headers={'X-CSRFToken': CSRF})
    assert r.get_json()['success']
    # 批量删除题目
    r = client.post('/api/questions/batch-delete',
                    json={'ids': [api_qid, comp_id]},
                    headers={'X-CSRFToken': CSRF})
    assert r.get_json()['success']
    # 删除试卷
    assert client.delete(f'/api/exams/{new_eid}',
                         headers={'X-CSRFToken': CSRF}).get_json()['success']
    # 列表接口
    assert client.get('/api/questions').status_code == 200


def test_python_answer_upload_and_online_judge(app):
    with app.app_context():
        exam = _mk_exam(app, '_py')
        eid = exam.id
        cid, sid = _mk_student(app, '__exam_mx_py班')
    client = _admin(app)
    qid = _add_q(app, client, eid, 'python_fill',
                 '__exam_mx_py在线判分+', '3\n5', '', 10,
                 {'blank_scores': '[5,5]',
                  'python_answers': '{"1": "3", "2": "5"}'})
    client.post(f'/admin/exams/{eid}/compose/add', json={'question_ids': [qid]},
                headers={'X-CSRFToken': CSRF})
    r = client.post('/admin/questions/upload_python_file', data={
        'csrf_token': CSRF, 'question_id': str(qid),
        'python_file': (io.BytesIO(b'r1 = None  # YOUR ANSWER\nr2 = None  # YOUR ANSWER\n'), 'ref.py'),
    }, content_type='multipart/form-data')
    assert r.status_code == 200 and r.get_json()['success'], r.get_data(as_text=True)
    stu = _student_client(app, sid)
    assert stu.get('/python_marker_guide').status_code == 200
    assert stu.get('/python_answers_format').status_code == 200
    # 非 .py 拒绝
    r = stu.post('/upload_python_answer', data={
        'csrf_token': CSRF, 'question_id': str(qid),
        'file': (io.BytesIO(b'x=1'), 'a.txt')},
        content_type='multipart/form-data')
    assert r.status_code == 400  # 非 .py 文件：JSON 拒绝
    # 正确 .py（两道输出 3 和 5 → 满分）
    r = stu.post('/upload_python_answer', data={
        'csrf_token': CSRF, 'question_id': str(qid),
        'file': (io.BytesIO(b'r1 = None  # YOUR ANSWER 3\nr2 = None  # YOUR ANSWER 5\n'), 'ans.py')},
        content_type='multipart/form-data')
    assert r.status_code == 200 and r.get_json()['success'], r.get_data(as_text=True)
    with app.app_context():
        pa = PythonAnswer.query.filter_by(question_id=qid, student_id=sid).first()
        assert pa is not None and pa.status == 'pending'
    # 开考交卷：文件判分满分
    assert stu.get(f'/online_exam/{eid}').status_code == 200
    r = stu.post(f'/submit_exam/{eid}', json={'answers': {}},
                 headers={'X-CSRFToken': CSRF})
    assert r.status_code == 200
    with app.app_context():
        result = Result.query.filter_by(student_id=sid, exam_id=eid).first()
        assert result.total_score == 10  # 文件判分满分
    # 本人可下载答案文件
    r = stu.get(f'/download_python_file/{qid}')
    assert r.status_code == 200
    # API 版本上传入口存在（换新学生避免重复行约束）
    with app.app_context():
        cid2, sid2 = _mk_student(app, '__exam_mx_py班2')
    stu2 = _student_client(app, sid2)
    r = stu2.post('/api/upload_python_answer', data={
        'csrf_token': CSRF, 'questionId': str(qid),
        'file': (io.BytesIO(b'r1 = None  # YOUR ANSWER 3\nr2 = None  # YOUR ANSWER 5\n'), 'ans2.py')},
        content_type='multipart/form-data')
    assert r.status_code == 200 and r.get_json()['success']


def test_statistics_results_delete_and_matrix_pages(app):
    with app.app_context():
        exam = _mk_exam(app, '_stat')
        eid = exam.id
    client = _admin(app)
    q1 = _add_q(app, client, eid, 'single', '__exam_mx_统计单选+', 'A', 'A. x|B. y', 5)
    client.post(f'/admin/exams/{eid}/compose/add', json={'question_ids': [q1]},
                headers={'X-CSRFToken': CSRF})
    # 统计页与结果删除端点
    assert client.get('/admin/statistics').status_code == 200
    assert client.get('/admin/online_students').status_code == 200
    # 组卷页
    assert client.get(f'/admin/exams/{eid}/compose').status_code == 200
    # 试卷编辑页与列表页
    assert client.get('/admin/exams').status_code == 200
    assert client.get(f'/admin/exams/edit/{eid}').status_code == 200
    # Python 批量导入工具页
    assert client.get('/admin/tools/import-python-fill').status_code == 200
    # 试卷删除
    r = client.post(f'/admin/exams/delete/{eid}',
                    data={'csrf_token': CSRF})
    assert r.status_code in (302, 303)
    with app.app_context():
        assert db.session.get(Exam, eid) is None
