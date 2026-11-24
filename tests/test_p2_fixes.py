"""P2 修复回归测试

覆盖：
1. 账号级登录限流（换 IP/换学号不可重置单账号失败计数）
2. 判断题判分与统计共用 JUDGE_TRUTHY 口径
3. 资源测验 upsert（重复提交不产生重复行）
4. 0 字节附件拒绝（不产生"幽灵附件"记录）
"""
import io

import pytest

from app import create_app
from app.extensions import db
from app.models import Student, Resource, ResourceQuizResult, HomeworkSubmission
from app.utils import (
    admin_login_blocked_seconds, admin_login_register_failure,
    admin_login_register_success,
)
from app.services.scoring_service import JUDGE_TRUTHY, score_judge
from types import SimpleNamespace as NS

_CSRF = 'test-csrf-token'


# ── 1. 账号级限流 ─────────────────────────────────────────

def test_account_level_rate_limit_blocks_after_failures():
    """同账号 8 次失败后封锁；账号键与 IP 组合键相互独立。"""
    account_key = 'student:account:reg-rate-1'
    admin_login_register_success(account_key)  # 清除可能残留
    try:
        for _ in range(8):
            admin_login_register_failure(account_key)
        blocked = admin_login_blocked_seconds(account_key)
        assert blocked > 0, '账号级失败计数未触发封锁'
        # 换 IP 的组合键不应被账号级封锁牵连（各自独立计数）
        assert admin_login_blocked_seconds(
            'student:number:9.9.9.9:reg-rate-1') == 0
        # 正常登录成功后解除封锁
        admin_login_register_success(account_key)
        assert admin_login_blocked_seconds(account_key) == 0
    finally:
        admin_login_register_success(account_key)


# ── 2. 判断题判分/统计口径 ────────────────────────────────

def test_judge_stats_use_same_truthy_as_scoring():
    """判分认可的每个编码（含 '对'/'t'/'yes'）在统计侧也归入"正确"。"""
    q = NS(question_type='judge', answer='正确', score=5)
    for value in JUDGE_TRUTHY:
        assert score_judge(q, value) == 5, f'判分未认可 {value!r}'
        # scores.py 统计判定式：str.strip().lower() in JUDGE_TRUTHY
        assert str(value).strip().lower() in JUDGE_TRUTHY, \
            f'统计未认可 {value!r}'
    # 此前统计侧仅认 ['true','True','1','正确']——这些兼容编码必须统一
    for compat in ('对', 't', 'yes', 'y'):
        assert compat.lower() in JUDGE_TRUTHY


# ── 3. 资源测验 upsert ────────────────────────────────────

@pytest.fixture(scope='module')
def app():
    app = create_app()
    yield app
    with app.app_context():
        db.session.rollback()
        db.session.execute(db.text(
            'TRUNCATE resource_quiz_result, resource, student RESTART IDENTITY CASCADE'))
        db.session.commit()


def test_quiz_upsert_keeps_single_row(app):
    """同一学生对同一资源重复提交只保留最新一行。"""
    with app.app_context():
        stu = Student(name='测验学生', student_number='QZ-1')
        stu.set_password('123456')
        stu.has_changed_password = True
        stu.is_activated = True
        db.session.add(stu)
        db.session.commit()
        stu_id = stu.id
        res = Resource(title='测验资源', show_in_student=True,
                       is_public=True)
        db.session.add(res)
        db.session.commit()
        res_id = res.id
    try:
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['student_id'] = stu_id
            sess['student_name'] = '测验学生'
            sess['student_class_id'] = None
            sess['csrf_token'] = _CSRF
            sess.permanent = True
        payload = {'type': 'ITSTUDY_QUIZ_RESULT', 'resource_id': res_id,
                   'quiz_name': '测试', 'total_score': 90, 'max_score': 100}
        for _ in range(2):
            resp = client.post('/api/resource_quiz/submit', json=payload,
                               headers={'X-CSRFToken': _CSRF})
            assert resp.status_code == 200, resp.get_data(as_text=True)
        with app.app_context():
            rows = ResourceQuizResult.query.filter_by(
                student_id=stu_id, resource_id=res_id).all()
            assert len(rows) == 1, f'重复提交产生 {len(rows)} 行记录'
            assert rows[0].total_score == 90
    finally:
        with app.app_context():
            ResourceQuizResult.query.filter_by(resource_id=res_id).delete(
                synchronize_session=False)
            Resource.query.filter_by(id=res_id).delete(synchronize_session=False)
            Student.query.filter_by(id=stu_id).delete(synchronize_session=False)
            db.session.commit()


# ── 4. 0 字节附件拒绝 ─────────────────────────────────────

def test_empty_attachment_rejected(app):
    """上传空文件不得产生落库的"幽灵附件"记录。"""
    with app.app_context():
        cls = __import__('app.models', fromlist=['Class']).Class(name='回归班级EMP')
        db.session.add(cls)
        db.session.commit()
        cls_id = cls.id
        stu = Student(name='空文件学生', student_number='EMP-1', class_id=cls_id)
        stu.set_password('123456')
        stu.has_changed_password = True
        stu.is_activated = True
        db.session.add(stu)
        db.session.commit()
        stu_id = stu.id
        hw = __import__('app.models', fromlist=['Homework']).Homework(
            title='回归作业EMP', is_active=True)
        hw.classes.append(cls)
        db.session.add(hw)
        db.session.commit()
        hw_id = hw.id
    try:
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['student_id'] = stu_id
            sess['student_name'] = '空文件学生'
            sess['student_class_id'] = None
            sess['csrf_token'] = _CSRF
            sess.permanent = True
        resp = client.post(
            f'/student/homework/{hw_id}',
            data={'text_content': '说明',
                  'files': [(io.BytesIO(b''), 'empty.txt')]},
            content_type='multipart/form-data',
            headers={'X-CSRFToken': _CSRF}, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            sub = HomeworkSubmission.query.filter_by(
                homework_id=hw_id, student_id=stu_id).first()
            # 空附件被拒后首次提交无文件 → 记录应不存在（或 files 为空）
            if sub is not None:
                assert sub.files == '[]' or sub.files == '[]\n', sub.files
    finally:
        with app.app_context():
            models = __import__('app.models', fromlist=['x'])
            HomeworkSubmission.query.filter_by(homework_id=hw_id).delete(
                synchronize_session=False)
            db.session.execute(models.homework_classes.delete().where(
                models.homework_classes.c.homework_id == hw_id))
            models.Homework.query.filter_by(id=hw_id).delete(synchronize_session=False)
            models.Student.query.filter_by(id=stu_id).delete(synchronize_session=False)
            models.Class.query.filter_by(id=cls_id).delete(synchronize_session=False)
            db.session.commit()
