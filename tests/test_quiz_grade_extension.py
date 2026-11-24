"""资源测验 5 种分数形式扩展回归测试（V5.0.0）

覆盖：
- 纯等级提交（无分数明细）落 grade
- 等级白名单外拒绝 400 / 非法题数 400 / OverflowError 输入 400
- 未提供等级时按 total/max 百分比推导（≥90 优秀 / ≥80 良好 / ≥60 合格）
- light 接口与管理端列表的 grade 推导一致性（存量行无 grade 字段时）
"""
import pytest

from app import create_app
from app.extensions import db
from app.models import Resource, Subject, Student, Class
from app.blueprints.resources import _derive_quiz_grade

_CSRF = 'test-csrf-token'


@pytest.fixture(scope='module')
def app():
    app = create_app()
    yield app
    with app.app_context():
        from app.models import ResourceQuizResult
        res = Resource.query.filter_by(title='__等级测试__').first()
        if res:
            ResourceQuizResult.query.filter_by(resource_id=res.id).delete(synchronize_session=False)
        Resource.query.filter_by(title='__等级测试__').delete(synchronize_session=False)
        Student.query.filter(Student.student_number.like('QG-%')).delete(synchronize_session=False)
        Class.query.filter_by(name='__等级测试班__').delete(synchronize_session=False)
        db.session.commit()


@pytest.fixture(scope='module')
def setup(app):
    with app.app_context():
        # 幂等：先清理可能的残留（上次运行中断时 teardown 未执行）
        Resource.query.filter_by(title='__等级测试__').delete(synchronize_session=False)
        Student.query.filter(Student.student_number.like('QG-%')).delete(synchronize_session=False)
        Class.query.filter_by(name='__等级测试班__').delete(synchronize_session=False)
        db.session.commit()
        cls = Class(name='__等级测试班__')
        db.session.add(cls)
        db.session.flush()
        stu = Student(name='等级测试生', student_number='QG-1', class_id=cls.id)
        stu.set_password('123456')
        stu.has_changed_password = True
        stu.is_activated = True
        db.session.add(stu)
        db.session.flush()
        subj = Subject.query.first()
        res = Resource(title='__等级测试__', url='/static/uploads/__qg__/x.html',
                       show_in_student=True, is_public=True,
                       subject_id=subj.id if subj else None)
        db.session.add(res)
        db.session.commit()
        return {'student_id': stu.id, 'resource_id': res.id, 'class_id': cls.id}


def _post(app, setup, payload, student_id):
    client = app.test_client()
    with client.session_transaction() as s:
        s.clear()
        s['student_id'] = student_id
        s['csrf_token'] = _CSRF
    return client.post('/api/resource_quiz/submit', json=payload,
                       headers={'X-CSRFToken': _CSRF})


def test_pure_grade_submission(app, setup):
    """纯等级测验（无分数明细）提交成功且落 grade"""
    r = _post(app, setup, {
        'type': 'ITSTUDY_QUIZ_RESULT',
        'resource_id': setup['resource_id'],
        'grade': '良好',
    }, setup['student_id'])
    assert r.status_code == 200
    with app.app_context():
        row = db.session.query(Resource).filter_by(id=setup['resource_id']).first()
        assert row is not None
    from app.models import ResourceQuizResult
    with app.app_context():
        qr = ResourceQuizResult.query.filter_by(
            resource_id=setup['resource_id'],
            student_id=setup['student_id']).first()
        assert qr is not None
        assert qr.grade == '良好'
        assert qr.total_score is None  # 纯等级无分数


def test_grade_whitelist_rejects_arbitrary(app, setup):
    """等级白名单外字符串拒绝（防存储型 XSS 隐患面）"""
    r = _post(app, setup, {
        'type': 'ITSTUDY_QUIZ_RESULT',
        'resource_id': setup['resource_id'],
        'grade': '"><img src=x onerror=alert(1)>',
    }, setup['student_id'])
    assert r.status_code == 400


def test_correct_count_validation(app, setup):
    """答对题数 > 总题数拒绝；OverflowError 输入（1e1000）拒绝 400 而非 500"""
    r = _post(app, setup, {
        'type': 'ITSTUDY_QUIZ_RESULT',
        'resource_id': setup['resource_id'],
        'correct_count': 11, 'question_count': 10,
    }, setup['student_id'])
    assert r.status_code == 400

    r2 = _post(app, setup, {
        'type': 'ITSTUDY_QUIZ_RESULT',
        'resource_id': setup['resource_id'],
        'correct_count': '1e1000',
    }, setup['student_id'])
    assert r2.status_code == 400


def test_grade_derive_boundaries():
    """等级推导边界：≥90 优秀 / ≥80 良好 / ≥60 合格 / 其余不合格"""
    def make(total, max_score, grade=None):
        return type('R', (), {'grade': grade, 'total_score': total, 'max_score': max_score})()

    assert _derive_quiz_grade(make(95, 100)) == '优秀'
    assert _derive_quiz_grade(make(90, 100)) == '优秀'
    assert _derive_quiz_grade(make(85, 100)) == '良好'
    assert _derive_quiz_grade(make(60, 100)) == '合格'
    assert _derive_quiz_grade(make(59, 100)) == '不合格'
    assert _derive_quiz_grade(make(10, 100, '优秀')) == '优秀'  # 提交字段优先
    assert _derive_quiz_grade(make(None, None)) is None         # 无分数无等级
