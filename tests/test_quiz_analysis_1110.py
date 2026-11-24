"""逐题采集、统计口径及权限回归（2026-11-10）。"""
import json
import uuid
from types import SimpleNamespace

import pytest

from app import create_app
from app.extensions import db
from app.models import Resource, ResourceQuizResult, Student, Teacher
from app.services.quiz_analytics import (
    aggregate_questions, normalize_questions, question_verdict,
)

CSRF = 'quiz-analysis-1110'


def _question(qid='q1', answer=None, **overrides):
    return dict({
        'id': qid, 'prompt': 'Python 中用于遍历序列的语句是？', 'type': 'single',
        'options': [{'value': 'A', 'label': 'A. if 条件判断'},
                    {'value': 'B', 'label': 'B. for 循环'}],
        'answer': ['B'] if answer is None else answer,
        'correct_answer': ['B'], 'is_correct': None, 'evidence': 'data-attribute',
    }, **overrides)


def _row(student_id, questions=None, answers=None):
    return SimpleNamespace(student_id=student_id,
                           question_details=json.dumps(questions) if questions is not None else None,
                           answers=json.dumps(answers or {}))


def test_accuracy_and_option_counts_deduplicate_students_and_multiple_choices():
    def multiple(answer):
        return _question('q2', answer, type='multiple', correct_answer=['A', 'B'])
    result = aggregate_questions([
        _row(1, [_question(), multiple(['A', 'B', 'B'])]),
        _row(2, [_question(answer=['A']), multiple(['B'])]),
        _row(1, [_question(answer=['A'])]),  # 同一学生较旧的一次不计
    ])
    assert result['student_count'] == 2
    single, multi = result['questions']
    assert single['correct_rate'] == multi['correct_rate'] == 50.0
    assert [option['selected_count'] for option in single['options']] == [1, 1]
    assert [option['selected_count'] for option in multi['options']] == [1, 2]
    assert multi['options'][1]['selection_rate'] == 100.0


def test_question_order_does_not_follow_student_click_order():
    result = aggregate_questions([_row(1, [
        _question('q10'), _question('q3'), _question('q2'),
    ])])
    assert [question['id'] for question in result['questions']] == ['q2', 'q3', 'q10']


def test_unknown_answers_and_legacy_rows_never_invent_correctness():
    result = aggregate_questions([
        _row(1, [_question(correct_answer=None, evidence='unknown')]),
        _row(2, answers={'旧题号': '完整原始作答'}),
    ])
    assert result['legacy_records'] == 1
    assert all(question['correct_rate'] is None for question in result['questions'])
    assert result['questions'][1]['answer_distribution'] == [{'answer': '完整原始作答', 'count': 1}]
    assert question_verdict(_question(answer=['unknown'], is_correct=True)) is None


def test_question_versions_and_conflicting_answer_keys_are_not_mixed():
    result = aggregate_questions([
        _row(1, [_question()]),
        _row(2, [_question(correct_answer=['A'])]),
        _row(3, [_question(prompt='完全不同的另一题')]),
    ])
    assert len(result['questions']) == 2
    original = result['questions'][0]
    assert original['answer_key_conflict'] is True
    assert original['correct_rate'] is None and original['unknown_count'] == 2
    assert result['questions'][1]['correct_rate'] == 100.0


@pytest.mark.parametrize('payload', [
    {}, [_question(), _question()], [{'id': ''}],
    [_question(options=[{'value': 'A'}, {'value': 'A'}])],
    [_question(answer={'bad': 'object'})], [_question(is_correct='yes')],
    [_question(prompt='x' * 4001)], [_question(options=[None])],
])
def test_question_payload_validation(payload):
    with pytest.raises(ValueError):
        normalize_questions(payload)


def test_invalid_type_fields_do_not_crash_or_imply_a_verdict():
    normalized = normalize_questions([_question(type={}, evidence=[])])[0]
    assert normalized['type'] == 'unknown' and normalized['evidence'] == 'unknown'


@pytest.fixture(scope='module')
def app():
    return create_app()


@pytest.fixture
def data(app, tmp_path, monkeypatch):
    from app.blueprints import resources
    monkeypatch.setattr(resources, '_BASE', str(tmp_path))
    folder = tmp_path / 'static/uploads/analysis1110'
    folder.mkdir(parents=True)
    for name in ('index.html', 'other.html'):
        (folder / name).write_text('<html>测验</html>', encoding='utf-8')
    suffix = uuid.uuid4().hex[:8]
    with app.app_context():
        teachers = [Teacher(username=f'__qa_t{i}_{suffix}', display_name='采集测试教师') for i in range(2)]
        for teacher in teachers:
            teacher.set_password('test-analysis-1110')
        students = [Student(name=f'__qa_s{i}_{suffix}', student_number=f'__qa_s{i}_{suffix}',
                            has_changed_password=True) for i in range(25)]
        db.session.add_all(teachers + students)
        db.session.flush()
        resource = Resource(title=f'__qa_res_{suffix}', url='/static/uploads/analysis1110/index.html',
                            quiz_mode='inject', is_public=True, creator_type='teacher',
                            creator_teacher_id=teachers[0].id)
        db.session.add(resource)
        db.session.commit()
        ids = {'resource': resource.id, 'students': [s.id for s in students],
               'teachers': [t.id for t in teachers]}
    yield ids
    with app.app_context():
        ResourceQuizResult.query.filter_by(resource_id=ids['resource']).delete(synchronize_session=False)
        Resource.query.filter_by(id=ids['resource']).delete(synchronize_session=False)
        Student.query.filter(Student.id.in_(ids['students'])).delete(synchronize_session=False)
        Teacher.query.filter(Teacher.id.in_(ids['teachers'])).delete(synchronize_session=False)
        db.session.commit()


def _client(app, **session):
    client = app.test_client()
    with client.session_transaction() as values:
        values.update(session, csrf_token=CSRF)
    return client


def _submit(client, rid, source='index.html', questions=None):
    return client.post('/api/resource_quiz/submit', json={
        'resource_id': rid, 'source_file': source, 'schema_version': 3,
        'quiz_name': '逐题采集', 'answers': {'q1': 'B'},
        'questions': [_question()] if questions is None else questions,
    }, headers={'X-CSRFToken': CSRF})


def test_submit_stores_full_questions_and_latest_attempt_only(app, data):
    rid = data['resource']
    student = _client(app, student_id=data['students'][0])
    assert _submit(student, rid, questions=[_question(answer=['A'])]).status_code == 200
    assert _submit(student, rid).status_code == 200
    assert _submit(student, rid, source='other.html', questions=[_question(answer=['A'])]).status_code == 200
    with app.app_context():
        rows = ResourceQuizResult.query.filter_by(resource_id=rid).all()
        assert len(rows) == 2
        saved = next(row for row in rows if row.source_file == 'index.html')
        saved_id = saved.id
        assert saved.adapter_version == 3
        assert json.loads(saved.question_details)[0]['options'][1]['label'] == 'B. for 循环'
    admin = _client(app, is_admin=True)
    detail = admin.get(f'/api/results/quiz/{saved_id}')
    assert detail.status_code == 200
    question = detail.json['data']['questions'][0]
    assert question['is_correct'] is True and question['answer'] == ['B']
    summary = admin.get(f'/admin/resources/quiz_analysis/{rid}?source_file=index.html')
    assert summary.status_code == 200
    assert len(summary.json['data']['pages']) == 2
    assert summary.json['data']['student_count'] == 1
    assert summary.json['data']['questions'][0]['correct_rate'] == 100.0
    bad = _submit(student, rid, questions=[_question(), _question()])
    assert bad.status_code == 400


def test_analysis_uses_all_pages_of_records_and_owner_permissions(app, data):
    rid = data['resource']
    with app.app_context():
        for sid in data['students']:
            db.session.add(ResourceQuizResult(student_id=sid, resource_id=rid, quiz_key='page1110',
                                              source_file='index.html', answers='{}',
                                              question_details=json.dumps([_question()])))
        db.session.commit()
    owner = _client(app, is_teacher=True, teacher_id=data['teachers'][0], teacher_mode='edit')
    other = _client(app, is_teacher=True, teacher_id=data['teachers'][1], teacher_mode='edit')
    response = owner.get(f'/admin/resources/quiz_analysis/{rid}')
    assert response.status_code == 200
    assert response.json['data']['student_count'] == 25
    assert response.json['data']['questions'][0]['options'][1]['selected_count'] == 25
    assert other.get(f'/admin/resources/quiz_analysis/{rid}').status_code == 403
    assert _client(app, student_id=data['students'][0]).get(
        f'/admin/resources/quiz_analysis/{rid}').status_code != 200
    page = owner.get(f'/admin/resources/quiz_results/{rid}')
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert '逐题分析' in html and 'quizAnalysisFile' in html and 'quiz_analysis.js' in html


def test_analysis_cache_hits_and_submit_invalidates(app, data):
    rid = data['resource']
    url = f'/admin/resources/quiz_analysis/{rid}?source_file=index.html'
    admin = _client(app, is_admin=True)
    first = admin.get(url)
    assert first.status_code == 200
    assert 'cached' not in first.json['data']
    assert first.json['data']['student_count'] == 0
    second = admin.get(url)
    assert second.json['data']['cached'] is True
    assert second.json['data']['student_count'] == 0
    # 提交新成绩后版本号失效：下一次必须重新统计
    student = _client(app, student_id=data['students'][0])
    assert _submit(student, rid).status_code == 200
    third = admin.get(url)
    assert 'cached' not in third.json['data']
    assert third.json['data']['student_count'] == 1
    assert third.json['data']['questions'][0]['correct_rate'] == 100.0


def test_analysis_cache_can_be_disabled(app, data, monkeypatch):
    rid = data['resource']
    url = f'/admin/resources/quiz_analysis/{rid}?source_file=index.html'
    admin = _client(app, is_admin=True)
    monkeypatch.setitem(app.config, 'QUIZ_ANALYSIS_CACHE_SECONDS', 0)
    assert 'cached' not in admin.get(url).json['data']
    assert 'cached' not in admin.get(url).json['data']
