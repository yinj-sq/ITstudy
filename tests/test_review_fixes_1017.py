# -*- coding: utf-8 -*-
"""2026-10-17 全面审查修复的回归用例（docs/审查与升级记录.md）。

数据一律用 rev1017 / REV1017 前缀命名，模块前后各清一次（DB 行 + 磁盘文件），
跑完仍须复跑 tools/review_db_residue_check.py。
"""
import os
import shutil

import pytest

from app import create_app
from app.extensions import cache, db
from app.models import (Exam, LearningActivity, Log, Resource, Result, Student,
                        SystemConfig)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_UPLOADS = os.path.join(_ROOT, 'static', 'uploads')
_CSRF = 'rev1017-csrf-token'
RES_PREFIX = 'rev1017_'
_RES_DIR = 'rev1017_课件'
_EXAM_NAME = 'rev1017卷'
_STU_NUM = 'REV1017-1'


@pytest.fixture(scope='module')
def app():
    app = create_app()
    with app.app_context():
        _cleanup()
    yield app
    with app.app_context():
        _cleanup()


def _cleanup():
    db.session.rollback()
    res_ids = [r.id for r in Resource.query.filter(Resource.title.like('rev1017%')).all()]
    if res_ids:
        LearningActivity.query.filter(
            LearningActivity.resource_id.in_(res_ids)).delete(synchronize_session=False)
        Resource.query.filter(Resource.id.in_(res_ids)).delete(synchronize_session=False)
    exam_ids = [e.id for e in Exam.query.filter(Exam.name.like('rev1017%')).all()]
    if exam_ids:
        Result.query.filter(Result.exam_id.in_(exam_ids)).delete(synchronize_session=False)
        Exam.query.filter(Exam.id.in_(exam_ids)).delete(synchronize_session=False)
    stu_ids = [s.id for s in Student.query.filter(
        Student.student_number.like('REV1017%')).all()]
    if stu_ids:
        Result.query.filter(Result.student_id.in_(stu_ids)).delete(synchronize_session=False)
        Student.query.filter(Student.id.in_(stu_ids)).delete(synchronize_session=False)
    Log.query.filter(Log.detail.like('%rev1017%')).delete(synchronize_session=False)
    db.session.commit()
    shutil.rmtree(os.path.join(_UPLOADS, _RES_DIR), ignore_errors=True)
    cache.delete('courseware:dir_map')


def _admin_client(app):
    client = app.test_client()
    with client.session_transaction() as s:
        s.clear()
        s['is_admin'] = True
        s['csrf_token'] = _CSRF
    return client


# ══════════════════════════════════════════════════════════════
#  判分：多选全角答案归一 / python_fill 在线空格归一
# ══════════════════════════════════════════════════════════════

def test_multiple_choice_fullwidth_answer_normalized():
    """管理端用中文输入法录入全角 'ＡＢＣ' 时，学生半角 'ABC' 仍应判满分。

    此前 `[^A-Za-z0-9]` 把全角字母整段剥除 → 标准答案归一为空串 →
    score_multiple 的 `std` 为空分支对任何作答都判 0（对全体学生静默失分）。
    """
    from app.services.scoring_service import (
        score_multiple, _normalize_multi_answer, auto_score)
    from types import SimpleNamespace as NS
    assert _normalize_multi_answer('ＡＢＣ') == 'ABC'   # 全角折叠
    assert _normalize_multi_answer('Ａ|Ｂ|Ｄ') == 'ABD'
    q = NS(question_type='multiple', answer='ＡＢＣ', score=10)
    assert score_multiple(q, 'ABC') == 10
    assert score_multiple(q, 'ＡＢＣ') == 10
    assert score_multiple(q, 'AB') == 0
    assert auto_score(q, 'ABC') == 10


def test_python_fill_online_whitespace_normalized():
    """标准答案含不规则空格时，在线判分应与文件判分同口径（归一内部空格）。"""
    import json
    from app.services.scoring_service import auto_score

    class _PyFillQ:
        question_type = 'python_fill'

        def __init__(self, answers, blank_scores, score):
            self.python_answers = json.dumps(answers)
            self.blank_scores = json.dumps(blank_scores)
            self.score = score

        @property
        def python_answers_dict(self):
            try:
                return json.loads(self.python_answers)
            except Exception:
                return {}

        @property
        def blank_scores_list(self):
            try:
                return json.loads(self.blank_scores)
            except Exception:
                return []

    q = _PyFillQ({'1': 'a  +  b'}, [10], 10)
    # 学生按规范空格作答：此前在线路径只做精确匹配 → 误判 0
    assert auto_score(q, {'1': 'a + b'}) == 10
    assert auto_score(q, {'1': 'a  +  b'}) == 10
    assert auto_score(q, {'1': 'a + c'}) == 0


# ══════════════════════════════════════════════════════════════
#  资源：API URL 白名单与 HTML 路径同口径
# ══════════════════════════════════════════════════════════════

def test_allowed_resource_url_helper():
    from app.blueprints.api_resources import _is_allowed_resource_url as ok
    assert ok('http://a.example/x')
    assert ok('https://a.example/x')
    assert ok('/static/uploads/rev1017_课件/index.html')
    assert not ok('javascript:alert(1)')
    assert not ok('data:text/html;base64,PHNjcmlwdD4=')
    assert not ok('/static/uploads/../secret')
    assert not ok('')


def test_api_create_resource_rejects_dangerous_url(app):
    """API 创建资源须与 HTML 路径同口径拒绝非 http(s)/站内路径。"""
    client = _admin_client(app)
    r = client.post('/api/resources', json={'title': 'rev1017危险', 'url': 'javascript:alert(1)'},
                    headers={'X-CSRFToken': _CSRF})
    assert r.status_code == 400
    # 正常外链仍可创建，并清理
    r2 = client.post('/api/resources', json={'title': 'rev1017OK', 'url': 'https://a.example/x'},
                     headers={'X-CSRFToken': _CSRF})
    assert r2.status_code == 200
    with app.app_context():
        Resource.query.filter(Resource.title.like('rev1017%')).delete(
            synchronize_session=False)
        db.session.commit()


# ══════════════════════════════════════════════════════════════
#  资源可见性切换：课件鉴权映射即时失效
# ══════════════════════════════════════════════════════════════

def test_toggle_visibility_invalidates_courseware_dir_map(app):
    """切换 show_in_student 后必须失效 courseware:dir_map（否则隐藏资源
    直链鉴权最长 300s 滞后，仍可下载）。"""
    with app.app_context():
        r = Resource(title='rev1017可见', url='/static/uploads/rev1017_课件/index.html',
                     show_in_student=True)
        db.session.add(r)
        db.session.commit()
        rid = r.id
    client = _admin_client(app)
    cache.set('courseware:dir_map', {'dummy': []}, timeout=300)
    resp = client.post(f'/admin/resources/toggle_vis/{rid}',
                       data={'flag': 'show_in_student', 'value': 'false'},
                       headers={'X-CSRFToken': _CSRF})
    assert resp.status_code == 200
    assert cache.get('courseware:dir_map') is None
    with app.app_context():
        Resource.query.filter(Resource.id == rid).delete(synchronize_session=False)
        db.session.commit()


# ══════════════════════════════════════════════════════════════
#  删除主页文件：res.url 自动指向剩余文件（不再悬空）
# ══════════════════════════════════════════════════════════════

def test_delete_homepage_file_reassigns_url(app):
    """删除资源主页文件后 res.url 须指向剩余文件而非死链。

    此前比较 `url_path(<dir>/<file>) == safe_name(<file>)` 恒不成立，
    主页兜底分支从不执行。
    """
    with app.app_context():
        d = os.path.join(_UPLOADS, _RES_DIR)
        os.makedirs(d, exist_ok=True)
        for fn in ('index.html', 'keep.txt'):
            with open(os.path.join(d, fn), 'w', encoding='utf-8') as f:
                f.write('rev1017')
        r = Resource(title='rev1017主页', url=f'/static/uploads/{_RES_DIR}/index.html')
        db.session.add(r)
        db.session.commit()
        rid = r.id
    client = _admin_client(app)
    resp = client.post(f'/admin/resources/delete-file/{rid}',
                       data={'filename': 'index.html'},
                       headers={'X-CSRFToken': _CSRF})
    assert resp.status_code in (200, 302)
    with app.app_context():
        res = db.session.get(Resource, rid)
        assert res.url == f'/static/uploads/{_RES_DIR}/keep.txt'
        assert not os.path.exists(os.path.join(_UPLOADS, _RES_DIR, 'index.html'))
        Resource.query.filter(Resource.id == rid).delete(synchronize_session=False)
        db.session.commit()
    shutil.rmtree(os.path.join(_UPLOADS, _RES_DIR), ignore_errors=True)


# ══════════════════════════════════════════════════════════════
#  维护模式：作品/活动文档读取面 fail-closed
# ══════════════════════════════════════════════════════════════

def test_maintenance_blocks_works_and_activity(app):
    """学生端维护中时，/works 与 /activity 读取面须 503（此前 fail-open）。"""
    with app.app_context():
        SystemConfig.set('student_access_enabled', 'false')
        db.session.commit()
        SystemConfig._invalidate_cache()
    try:
        client = app.test_client()  # 匿名（非管理员/教师）
        assert client.get('/works/file/1').status_code == 503
        assert client.get('/activity/document/1').status_code == 503
    finally:
        with app.app_context():
            SystemConfig.set('student_access_enabled', 'true')
            db.session.commit()
            SystemConfig._invalidate_cache()


# ══════════════════════════════════════════════════════════════
#  系统设置：代理密钥仅显示是否已设置（不回显明文）
# ══════════════════════════════════════════════════════════════

def test_system_settings_masks_proxy_secret(app):
    client = _admin_client(app)
    html = client.get('/admin/system').get_data(as_text=True)
    assert 'PROXY_SECRET' in html
    assert '代理密钥' in html
    # 只呈现是否已设置，不回显密钥明文
    assert '已设置' in html or '（未设置）' in html


# ══════════════════════════════════════════════════════════════
#  批改导航：成绩记录须属于该试卷
# ══════════════════════════════════════════════════════════════

def test_grading_prev_student_rejects_exam_mismatch(app):
    """prev 导航传入不匹配的 (exam_id, result_id) 时应回列表而非跳到别的卷。"""
    with app.app_context():
        e1 = Exam(name='rev1017卷1', is_active=True, is_visible=True)
        e2 = Exam(name='rev1017卷2', is_active=True, is_visible=True)
        db.session.add_all([e1, e2])
        db.session.flush()
        stu = Student(name='rev1017生', student_number=_STU_NUM, is_activated=True)
        stu.set_password('rev1017pass')
        db.session.add(stu)
        db.session.flush()
        r = Result(student_id=stu.id, exam_id=e2.id, total_score=0,
                   answers='{}', scores='{}')
        db.session.add(r)
        db.session.commit()
        rid, e1_id = r.id, e1.id
    # 用管理员会话：管理员可管理任意成绩，使 exam_id 校验成为唯一的判定分支
    client = app.test_client()
    with client.session_transaction() as s:
        s.clear()
        s['is_admin'] = True
        s['csrf_token'] = _CSRF
    # e1 与 result(属于 e2) 不匹配 → 回批改列表（/grading）
    resp = client.get(f'/admin/grading/{e1_id}/{rid}/prev')
    assert resp.status_code in (301, 302)
    assert resp.headers.get('Location', '').rstrip('/').endswith('/grading')
    with app.app_context():
        Result.query.filter(Result.id == rid).delete(synchronize_session=False)
        Student.query.filter(Student.student_number == _STU_NUM).delete(
            synchronize_session=False)
        Exam.query.filter(Exam.name.like('rev1017%')).delete(synchronize_session=False)
        db.session.commit()
