# -*- coding: utf-8 -*-
"""注入前检测、多文件成绩隔离与 QuickForm 入口回归（2026-10-23）。

覆盖：
- 上传保存只登记待检测文件，不修改原 HTML
- 模拟演练回报、通过后才应用注入
- 多 HTML 文件成绩不互相覆盖
- 课堂编排 QuickForm 成绩入口白名单与渲染
"""
import io
import json
import pathlib
import shutil
import uuid

import pytest

from app import create_app
from app.extensions import db
from app.models import (
    Log, Resource, ResourceQuizResult, Student, Subject, Teacher,
    teacher_subject,
)
from app.blueprints.resources import _sanitize_lesson_tree
from app.utils import inject_quiz_collector

ROOT = pathlib.Path(__file__).resolve().parent.parent
UPLOADS = ROOT / 'static' / 'uploads'
CSRF = 'quiz-check-csrf'


@pytest.fixture(scope='module')
def app():
    return create_app()


def _client(app, **sess):
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(sess)
        s['csrf_token'] = CSRF
    return client


def _cleanup(title, usernames, subject_names, dir_names, student_numbers):
    with db.session.begin():
        Log.query.filter(Log.detail.contains(title)).delete(
            synchronize_session=False)
        res_ids = [r.id for r in Resource.query.filter_by(title=title).all()]
        if res_ids:
            ResourceQuizResult.query.filter(
                ResourceQuizResult.resource_id.in_(res_ids)).delete(
                    synchronize_session=False)
        Resource.query.filter_by(title=title).delete(synchronize_session=False)
        if student_numbers:
            Student.query.filter(Student.student_number.in_(student_numbers)).delete(
                synchronize_session=False)
        db.session.execute(teacher_subject.delete())
        if usernames:
            Teacher.query.filter(Teacher.username.in_(usernames)).delete(
                synchronize_session=False)
        if subject_names:
            Subject.query.filter(Subject.name.in_(subject_names)).delete(
                synchronize_session=False)
    for dir_name in dir_names:
        if dir_name:
            shutil.rmtree(UPLOADS / dir_name, ignore_errors=True)


def _make_teacher(subject_name, username, display_name):
    subj = Subject(name=subject_name, sort_order=950)
    teacher = Teacher(username=username, display_name=display_name)
    teacher.set_password('pass123456')
    teacher.subjects = [subj]
    db.session.add_all([subj, teacher])
    db.session.commit()
    return subj, teacher


def test_upload_defers_injection_until_check(app):
    sfx = uuid.uuid4().hex[:8]
    title = f'__qic_res_{sfx}'
    subject_name = f'__qic_sub_{sfx}'
    username = f'__qic_teacher_{sfx}'
    other_name = f'__qic_other_{sfx}'
    dir_name = None
    rid = None
    try:
        with app.app_context():
            subj, teacher = _make_teacher(subject_name, username, '检测教师')
            other = Teacher(username=other_name, display_name='其他教师')
            other.set_password('pass123456')
            db.session.add(other)
            db.session.commit()
            tid, sid, oid = teacher.id, subj.id, other.id
            dir_name = f't{tid}_{title}'
            target = UPLOADS / dir_name
            target.mkdir(parents=True, exist_ok=True)
            html = '<html><head><title>检测</title></head><body><button>提交</button></body></html>'
            (target / 'index.html').write_text(html, encoding='utf-8')
            (target / 'quiz2.html').write_text(html, encoding='utf-8')

        client = _client(app, is_teacher=True, teacher_id=tid,
                         teacher_name='检测教师', teacher_mode='edit')
        payload = {
            'title': title, 'directory': title, 'subject_id': sid,
            'homepage': 'index.html', 'homework': [],
            'inject_files': ['index.html', 'quiz2.html'],
            'permissions': {
                'index.html': {'show': True, 'download': True},
                'quiz2.html': {'show': True, 'download': True},
            },
            'delete_files': [], 'show_in_student': True,
            'show_in_classroom': True, 'quiz_mode': 'inject',
        }
        resp = client.post('/admin/resources/save_with_settings', json=payload,
                           headers={'X-CSRFToken': CSRF})
        assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
        body = resp.get_json()
        assert body['success'] and '/quiz-check' in body['redirect']
        with app.app_context():
            res = Resource.query.filter_by(title=title).first()
            rid = res.id
            pending = json.loads(res.quiz_pending_files or '[]')
            assert pending == ['index.html', 'quiz2.html']
            assert res.quiz_inject_state == 'pending'
            assert 'ITSTUDY_QUIZ_COLLECTOR' not in (
                target / 'index.html').read_text(encoding='utf-8')

        page = client.get(f'/teacher/resources/{rid}/quiz-check')
        assert page.status_code == 200
        text = page.get_data(as_text=True)
        assert 'index.html' in text and 'quiz2.html' in text
        assert '开始模拟' in text

        # 编辑页新增 HTML 也必须进入待检测，而不是立即注入
        up = client.post(
            f'/admin/resources/{rid}/upload_files',
            data={'files': (io.BytesIO(b'<html><body>new</body></html>'),
                            'quiz3.html'), 'replace': '0'},
            content_type='multipart/form-data',
            headers={'X-CSRFToken': CSRF})
        assert up.status_code == 200 and up.get_json()['needs_check']
        with app.app_context():
            res = db.session.get(Resource, rid)
            pending = json.loads(res.quiz_pending_files or '[]')
            assert 'quiz3.html' in pending
            assert 'ITSTUDY_QUIZ_COLLECTOR' not in (
                target / 'quiz3.html').read_text(encoding='utf-8')

        other = _client(app, is_teacher=True, teacher_id=oid,
                        teacher_name='其他教师', teacher_mode='edit')
        assert other.get(f'/teacher/resources/{rid}/quiz-check').status_code == 403

        readonly = _client(app, is_teacher=True, teacher_id=tid,
                           teacher_name='检测教师', teacher_mode='readonly')
        assert readonly.get(f'/teacher/resources/{rid}/quiz-check').status_code != 200
    finally:
        with app.app_context():
            _cleanup(title, [username, other_name], [subject_name],
                     [dir_name], [])


def test_dry_run_report_apply_and_partial(app):
    sfx = uuid.uuid4().hex[:8]
    title = f'__qic_apply_{sfx}'
    subject_name = f'__qic_apply_sub_{sfx}'
    username = f'__qic_apply_teacher_{sfx}'
    dir_name = None
    rid = None
    try:
        with app.app_context():
            subj, teacher = _make_teacher(subject_name, username, '应用教师')
            tid, sid = teacher.id, subj.id
            dir_name = f't{tid}_{title}'
            target = UPLOADS / dir_name
            target.mkdir(parents=True, exist_ok=True)
            html = '<html><head><title>应用</title></head><body>答题</body></html>'
            (target / 'index.html').write_text(html, encoding='utf-8')
            (target / 'quiz2.html').write_text(html, encoding='utf-8')

        client = _client(app, is_teacher=True, teacher_id=tid,
                         teacher_name='应用教师', teacher_mode='edit')
        resp = client.post('/admin/resources/save_with_settings', json={
            'title': title, 'directory': title, 'subject_id': sid,
            'homepage': 'index.html', 'homework': [],
            'inject_files': ['index.html', 'quiz2.html'],
            'permissions': {}, 'delete_files': [],
            'show_in_student': True, 'show_in_classroom': True,
            'quiz_mode': 'inject',
        }, headers={'X-CSRFToken': CSRF})
        assert resp.status_code == 200 and resp.get_json()['success']
        with app.app_context():
            rid = Resource.query.filter_by(title=title).first().id
        base = f'/teacher/resources/{rid}/quiz-check'

        # 未检测直接应用必须失败
        bad = client.post(base + '/apply', json={
            'tests': [{'file': 'index.html', 'token': 'a' * 32}]
        }, headers={'X-CSRFToken': CSRF}).get_json()
        assert not bad['success']
        assert '检测会话已失效' in json.dumps(bad, ensure_ascii=False)

        start = client.post(base + '/start', json={'file': 'index.html'},
                            headers={'X-CSRFToken': CSRF}).get_json()
        assert start['success'] and start['token']
        preview = client.get(start['preview_url'])
        assert preview.status_code == 200
        preview_text = preview.get_data(as_text=True)
        assert '__ITSTUDY_QUIZ_DRY_RUN__' in preview_text
        assert '__ITSTUDY_QUIZ_SOURCE_FILE__' in preview_text
        assert 'ITSTUDY_QUIZ_COLLECTOR' in preview_text

        report = client.post(
            f'{base}/report/{start["token"]}',
            json={'answers': {'q1': 'A'}, 'total_score': 10,
                  'max_score': 10, 'correct_count': 1, 'question_count': 1},
            headers={'X-CSRFToken': CSRF}).get_json()
        assert report['success'] and report['status'] == 'pass'
        status = client.get(
            f'{base}/status/{start["token"]}').get_json()
        assert status['success'] and status['status'] == 'pass'

        applied = client.post(base + '/apply', json={
            'tests': [{'file': 'index.html', 'token': start['token']}]
        }, headers={'X-CSRFToken': CSRF}).get_json()
        assert applied['success']
        assert applied['state'] == 'partial'
        assert applied['pending'] == ['quiz2.html']
        with app.app_context():
            res = db.session.get(Resource, rid)
            assert res.injected is True
            assert res.quiz_inject_state == 'partial'
            injected = (UPLOADS / dir_name / 'index.html').read_text(encoding='utf-8')
            assert 'ITSTUDY_QUIZ_COLLECTOR:BEGIN' in injected
            assert '__ITSTUDY_QUIZ_SOURCE_FILE__' in injected

        start_fail = client.post(base + '/start', json={'file': 'quiz2.html'},
                                 headers={'X-CSRFToken': CSRF}).get_json()
        assert start_fail['success']
        fail = client.post(
            f'{base}/report/{start_fail["token"]}', json={},
            headers={'X-CSRFToken': CSRF}).get_json()
        assert fail['status'] == 'fail'
        fail_apply = client.post(base + '/apply', json={
            'tests': [{'file': 'quiz2.html', 'token': start_fail['token']}]
        }, headers={'X-CSRFToken': CSRF}).get_json()
        assert not fail_apply['success']

        start2 = client.post(base + '/start', json={'file': 'quiz2.html'},
                             headers={'X-CSRFToken': CSRF}).get_json()
        assert start2['success']
        report2 = client.post(
            f'{base}/report/{start2["token"]}',
            json={'answers': {'q1': 'B'}},
            headers={'X-CSRFToken': CSRF}).get_json()
        assert report2['status'] == 'partial'
        # 前端已在确认框确认；服务端不再依赖 allow_partial 标志
        accepted = client.post(base + '/apply', json={
            'tests': [{'file': 'quiz2.html', 'token': start2['token']}]
        }, headers={'X-CSRFToken': CSRF}).get_json()
        assert accepted['success'] and accepted['state'] == 'verified'
        assert accepted['pending'] == []
        assert accepted['results'][0]['partial'] is True
    finally:
        with app.app_context():
            _cleanup(title, [username], [subject_name], [dir_name], [])


def test_quiz_submit_isolated_by_source_file(app):
    sfx = uuid.uuid4().hex[:8]
    title = f'__qic_results_{sfx}'
    student_number = f'__qic_stu_{sfx}'
    dir_name = f'__qic_results_dir_{sfx}'
    rid = None
    try:
        target = UPLOADS / dir_name
        target.mkdir(parents=True, exist_ok=True)
        (target / 'index.html').write_text('<html></html>', encoding='utf-8')
        (target / 'quiz2.html').write_text('<html></html>', encoding='utf-8')
        with app.app_context():
            stu = Student(name='多文件学生', student_number=student_number,
                          has_changed_password=True)
            stu.set_password('pass123456')
            res = Resource(title=title,
                           url=f'/static/uploads/{dir_name}/index.html',
                           show_in_student=True, show_in_classroom=True,
                           is_public=True, quiz_mode='inject')
            db.session.add_all([stu, res])
            db.session.commit()
            rid, student_id = res.id, stu.id

        client = _client(app, student_id=student_id)
        base = {'resource_id': rid, 'answers': {'q1': 'A'},
                'scores': {'q1': 10}, 'total_score': 10, 'max_score': 10,
                'quiz_name': '测验'}
        # 旧 SDK 没有 source_file → legacy；首次带 source_file 时原地升级
        assert client.post('/api/resource_quiz/submit', json=base,
                           headers={'X-CSRFToken': CSRF}).status_code == 200
        first = dict(base, source_file='index.html')
        assert client.post('/api/resource_quiz/submit', json=first,
                           headers={'X-CSRFToken': CSRF}).status_code == 200
        second = dict(base, source_file='quiz2.html', answers={'q1': 'B'})
        assert client.post('/api/resource_quiz/submit', json=second,
                           headers={'X-CSRFToken': CSRF}).status_code == 200
        assert client.post('/api/resource_quiz/submit', json=first,
                           headers={'X-CSRFToken': CSRF}).status_code == 200
        with app.app_context():
            rows = ResourceQuizResult.query.filter_by(
                resource_id=rid).order_by(ResourceQuizResult.id).all()
            assert len(rows) == 2
            assert {r.source_file for r in rows} == {'index.html', 'quiz2.html'}
            assert len({r.quiz_key for r in rows}) == 2

        bad = client.post('/api/resource_quiz/submit',
                          json=dict(base, source_file='../x.html'),
                          headers={'X-CSRFToken': CSRF})
        assert bad.status_code == 400
        missing = client.post('/api/resource_quiz/submit',
                              json=dict(base, source_file='missing.html'),
                              headers={'X-CSRFToken': CSRF})
        assert missing.status_code == 400
    finally:
        with app.app_context():
            _cleanup(title, [], [], [dir_name], [student_number])


def test_quickform_lesson_tree_and_classroom_entry(app):
    sfx = uuid.uuid4().hex[:8]
    title = f'__qic_qf_{sfx}'
    student_number = f'__qic_qf_stu_{sfx}'
    dir_name = f'__qic_qf_dir_{sfx}'
    rid = None
    try:
        target = UPLOADS / dir_name
        target.mkdir(parents=True, exist_ok=True)
        (target / 'index.html').write_text('<html></html>', encoding='utf-8')
        with app.app_context():
            stu = Student(name='QuickForm学生', student_number=student_number,
                          has_changed_password=True)
            stu.set_password('pass123456')
            res = Resource(title=title,
                           url=f'/static/uploads/{dir_name}/index.html',
                           show_in_student=True, show_in_classroom=True,
                           quiz_mode='none')
            db.session.add_all([stu, res])
            db.session.commit()
            rid = res.id

        tree = [{
            'id': 'sec1', 'title': '课堂', 'type': 'section', 'children': [],
            'items': [{
                'id': 'qf1', 'title': 'QuickForm 成绩', 'kind': 'link',
                'src': 'https://quickform.example/task/1',
                'purpose': 'quickform_results', 'open_mode': 'newtab',
                'visible': {'teacher': True, 'student': False},
            }],
        }]
        cleaned, err = _sanitize_lesson_tree(tree, dir_name)
        assert err is None
        assert cleaned[0]['items'][0]['purpose'] == 'quickform_results'
        assert cleaned[0]['items'][0]['open_mode'] == 'newtab'
        bad_tree = json.loads(json.dumps(tree))
        bad_tree[0]['items'][0]['src'] = 'javascript:alert(1)'
        _, bad_err = _sanitize_lesson_tree(bad_tree, dir_name)
        assert bad_err

        admin = _client(app, is_admin=True, admin_name='管理员')
        saved = admin.post(f'/admin/resources/{rid}/lesson_tree',
                           json={'tree': tree},
                           headers={'X-CSRFToken': CSRF})
        assert saved.status_code == 200 and saved.get_json()['success']
        page = admin.get(f'/study/lesson/{rid}')
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        assert 'quickform_results' in html
        assert 'https://quickform.example/task/1' in html
    finally:
        with app.app_context():
            _cleanup(title, [], [], [dir_name], [student_number])


def test_managed_injection_block_updates_source_file(tmp_path):
    fp = tmp_path / 'quiz.html'
    fp.write_text('<html><head></head><body>quiz</body></html>',
                  encoding='utf-8')
    assert inject_quiz_collector(str(fp), 7, 'a.html')
    content = fp.read_text(encoding='utf-8')
    assert content.count('ITSTUDY_QUIZ_COLLECTOR:BEGIN') == 1
    assert '"a.html"' in content
    assert inject_quiz_collector(str(fp), 7, 'b.html')
    content = fp.read_text(encoding='utf-8')
    assert content.count('ITSTUDY_QUIZ_COLLECTOR:BEGIN') == 1
    assert '"b.html"' in content
