# -*- coding: utf-8 -*-
"""2026-09-08 全面审查修复回归测试

覆盖本轮修复（详见 git show 8d47f69:docs/全面审查报告-2026-09-08.md）：
- P1-1  SPA 试卷状态开关 404（toggle 端点回归守卫：表单编码根路径可用）
- P2-A  API 删卷"先检查后破坏"（有成绩 409 且关联行不被破坏）
- P2-B  趋势缓存换代移到 commit 之后（delete_exam_result 不再提前 bump）
- P2-C  SPA 收卷宽限重入（在考学生收卷后 get_exam 返回 exam_start_time）
- P2-D  无时长试卷提交通道（进入考试页创建 attempt 后可正常交卷）
- P3    clear-stale-attempts force、exam_status is_enabled、
        has_active_attempt SQL 口径、代理密钥门、JSON 无长度拒绝、
        模型探测限流、外链卷列表透出
"""
import io
from datetime import datetime, timedelta

import pytest

from app import create_app
from app.extensions import db
from app.models import (
    ClassroomSetting, Class, Exam, ExamAttempt, ExamQuestion, Question,
    Result, Student,
)

CSRF = 'rev0908-csrf'
EXAM_NAME = '审查0908测试卷'
LINK_EXAM_NAME = '审查0908外链卷'
NODUR_EXAM_NAME = '审查0908无时长卷'
# 清理用的公共前缀：三张卷名与若干日志明细都以它开头，按前缀清才兜得住
# `EXAM_NAME + 'X'` 这类派生命名
EXAM_PREFIX = '审查0908'
CLS_NAME = '审查0908班'
STU_NUM = 'REV0908A'
TEACHER_NAME = '审查0908教师'


@pytest.fixture(scope='module')
def app():
    app = create_app()
    _seed(app)
    with app.app_context():
        setting = ClassroomSetting.query.first()
        orig = setting.active_class_id if setting else None
        cls = Class.query.filter_by(name=CLS_NAME).first()
        if setting:
            setting.active_class_id = cls.id
        else:
            db.session.add(ClassroomSetting(active_class_id=cls.id))
        db.session.commit()
    yield app
    with app.app_context():
        setting = ClassroomSetting.query.first()
        if setting:
            setting.active_class_id = orig if (
                orig and db.session.get(Class, orig)) else None
        _cleanup()
        db.session.commit()


def _cleanup():
    conn = db.session.connection()
    # 先置空 classroom_setting.active_class_id（FK 引用本测试班级时阻断删班）
    conn.execute(db.text(
        'UPDATE classroom_setting SET active_class_id=NULL '
        'WHERE active_class_id IN (SELECT id FROM classes WHERE name=:n)'),
        {'n': CLS_NAME})
    # 按**前缀**清理，不逐个列举卷名：本模块有 `EXAM_NAME + 'X'` 这类派生
    # 卷名（test_exam_status_requires_is_enabled），先前逐个列举漏掉了它，
    # 于是每跑一次就永久留下 1 卷 + 1 题 + 1 条 exam_question
    # （2026-09-13 审查发现）。前缀匹配对后续再拼后缀的写法同样兜得住。
    for (eid,) in conn.execute(db.text(
            "SELECT id FROM exam WHERE name LIKE :p"),
            {'p': EXAM_PREFIX + '%'}).fetchall():
        conn.execute(db.text(
            'DELETE FROM exam_attempt WHERE exam_id=:e'), {'e': eid})
        conn.execute(db.text(
            'DELETE FROM result WHERE exam_id=:e'), {'e': eid})
        conn.execute(db.text(
            'DELETE FROM exam_question WHERE exam_id=:e'), {'e': eid})
        conn.execute(db.text(
            'DELETE FROM question WHERE exam_id=:e'), {'e': eid})
        conn.execute(db.text(
            'DELETE FROM exam WHERE id=:e'), {'e': eid})
    # 交卷/导入等路径会写操作日志；日志不在上面的外键链上，必须单独清，
    # 否则会留下"已删学生的提交记录"这类悬空审计行（本模块此前从未清）
    conn.execute(db.text("DELETE FROM log WHERE detail LIKE :p"),
                 {'p': '%' + EXAM_PREFIX + '%'})
    conn.execute(db.text(
        'DELETE FROM student WHERE student_number=:n'), {'n': STU_NUM})
    conn.execute(db.text('DELETE FROM classes WHERE name=:n'),
                 {'n': CLS_NAME})


def _seed(app):
    with app.app_context():
        cls = Class.query.filter_by(name=CLS_NAME).first()
        if not cls:
            db.session.add(Class(name=CLS_NAME))
        stu = Student.query.filter_by(student_number=STU_NUM).first()
        if not stu:
            stu = Student(name='审查0908学生', student_number=STU_NUM,
                          student_class=CLS_NAME,
                          is_activated=True, has_changed_password=True)
            stu.set_password('Rev0908#')
            db.session.add(stu)
        db.session.commit()
        cls = Class.query.filter_by(name=CLS_NAME).first()
        stu = Student.query.filter_by(student_number=STU_NUM).first()
        stu.class_id = cls.id
        db.session.commit()


def _sid(app):
    with app.app_context():
        return Student.query.filter_by(student_number=STU_NUM).first().id


def _student_client(app, sid):
    client = app.test_client()
    with client.session_transaction() as s:
        s.clear()
        s['student_id'] = sid
        s['student_name'] = '审查0908学生'
        s['csrf_token'] = CSRF
    return client


def _admin_client(app):
    client = app.test_client()
    with client.session_transaction() as s:
        s.clear()
        s['is_admin'] = True
        s['csrf_token'] = CSRF
    return client


def _teacher_client(app):
    client = app.test_client()
    with client.session_transaction() as s:
        s.clear()
        s['is_teacher'] = True
        s['teacher_id'] = 1
        s['csrf_token'] = CSRF
    return client


def _make_exam(app, name=EXAM_NAME, duration=30, link=False, collected=False):
    """幂等建卷；link=True 时卷内首题为 link 型（外链卷）。

    注意：Question 带 exam_id 提交时由 models.py 的事件自动挂卷
    （exam_question 行），此处不得再显式建 ExamQuestion（唯一约束冲突）。
    """
    with app.app_context():
        exam = Exam.query.filter_by(name=name).first()
        if not exam:
            exam = Exam(name=name, is_active=True, is_visible=True,
                        is_enabled=True, duration=duration)
            db.session.add(exam)
            db.session.flush()
            if link:
                db.session.add(Question(exam_id=exam.id, question_type='link',
                                        content='https://example.com/0908',
                                        score=0))
            else:
                db.session.add(Question(exam_id=exam.id,
                                        question_type='single',
                                        content='0908LINK? 1+1=?',
                                        options='A|B|C|D',
                                        answer='A', score=10))
            db.session.commit()
        exam.is_collected = collected
        db.session.commit()
        return exam.id


def _make_result(app, sid, eid):
    """为删除路径测试造一条已提交成绩。"""
    with app.app_context():
        r = Result.query.filter_by(student_id=sid, exam_id=eid).first()
        if not r:
            r = Result(student_id=sid, exam_id=eid, total_score=10,
                       scores='{}', answers='{}',
                       submit_time=datetime.now())
            db.session.add(r)
            db.session.commit()
        return r.id


def _make_attempt(app, sid, eid, age_seconds=0):
    with app.app_context():
        start = datetime.now() - timedelta(seconds=age_seconds)
        attempt = ExamAttempt.query.filter_by(
            student_id=sid, exam_id=eid).first()
        if attempt:
            attempt.start_time = start
        else:
            attempt = ExamAttempt(student_id=sid, exam_id=eid,
                                  start_time=start)
            db.session.add(attempt)
        db.session.commit()


def _drop_attempt(app, sid, eid):
    with app.app_context():
        ExamAttempt.query.filter_by(student_id=sid, exam_id=eid).delete()
        db.session.commit()


# ── P2-A：API 删卷先检查后破坏 ─────────────────────────────

def test_api_delete_exam_checks_before_destroy(app):
    """有成绩的试卷 API 删除 409，且 exam_question 关联行不被先行破坏。"""
    eid = _make_exam(app)
    sid = _sid(app)
    _make_result(app, sid, eid)
    client = _admin_client(app)
    resp = client.delete(f'/api/exams/{eid}', headers={'X-CSRFToken': CSRF})
    assert resp.status_code == 409, '有成绩记录应 409 拒绝删除'
    with app.app_context():
        # 关键回归点：检查在破坏性语句之前——409 后关联行必须原样保留
        assert db.session.get(Exam, eid) is not None, '试卷本体不应被删除'
        assert ExamQuestion.query.filter_by(exam_id=eid).count() == 1, \
            '409 路径 exam_question 关联行不应被清理（此前先删后查）'
        q = Question.query.filter(
            Question.exam_id == eid,
            Question.content == '0908LINK? 1+1=?').first()
        assert q is not None, '409 路径题目不应被解绑（exam_id 置空）'


# ── P2-B：趋势缓存换代在 commit 后 ────────────────────────

def test_trend_bump_moved_after_commit(app):
    """delete_exam_result 不再在 commit 前 bump；finalize 统一收口。"""
    from app.services.scoring_service import (
        delete_exam_result, finalize_exam_result_deletion, trend_cache_epoch)
    eid = _make_exam(app)
    sid = _sid(app)
    rid = _make_result(app, sid, eid)
    with app.app_context():
        e0 = trend_cache_epoch(eid)
        result = db.session.get(Result, rid)
        info = delete_exam_result(result)
        db.session.commit()
        e1 = trend_cache_epoch(eid)
        assert e1 == e0, 'delete_exam_result 本身不应 bump（bump 已移至收口）'
        finalize_exam_result_deletion(info)
        e2 = trend_cache_epoch(eid)
        assert e2 == e1 + 1, 'finalize_exam_result_deletion 应换代趋势缓存'
        assert info.get('pending_files') is not None, \
            '返回值应携带延迟删除的磁盘文件清单'


# ── P2-C：SPA 收卷宽限重入 ────────────────────────────────

def test_spa_collected_exam_reentry_in_grace(app):
    """收卷时在考的学生：get_exam 返回真实开考时间（宽限补交）；从未开考
    与超时残留分别给出"无 start_time"与 exam_ended。"""
    eid = _make_exam(app, collected=True)
    sid = _sid(app)
    client = _student_client(app, sid)

    # 1) 从未开考 + 已收卷：无开考时间（前端拦截进入）
    _drop_attempt(app, sid, eid)
    data = client.get(f'/api/exams/{eid}', headers={'X-CSRFToken': CSRF}).get_json()
    assert data['success'] and not data['data'].get('exam_start_time')

    # 2) 在考中收卷（开考 1 分钟，远未超时）：返回开考时间、无结束标记
    _make_attempt(app, sid, eid, age_seconds=60)
    data = client.get(f'/api/exams/{eid}', headers={'X-CSRFToken': CSRF}).get_json()
    assert data['data'].get('exam_start_time'), \
        '收卷时在考的学生应拿到 exam_start_time（宽限补交，与 SSR 同口径）'
    assert not data['data'].get('exam_ended')

    # 3) 超时残留 + 已收卷：exam_ended 结束态
    _make_attempt(app, sid, eid, age_seconds=36 * 60)
    data = client.get(f'/api/exams/{eid}', headers={'X-CSRFToken': CSRF}).get_json()
    assert data['data'].get('exam_ended'), '超时残留应标记结束态'
    _drop_attempt(app, sid, eid)


# ── P2-D：无时长试卷提交通道 ──────────────────────────────

def test_no_duration_exam_attempt_and_submit(app):
    """无时长卷进入考试页创建开考记录，提交不再 403"请先开始考试"。"""
    eid = _make_exam(app, name=NODUR_EXAM_NAME, duration=None)
    sid = _sid(app)
    _drop_attempt(app, sid, eid)
    client = _student_client(app, sid)

    resp = client.get(f'/online_exam/{eid}', headers={'X-CSRFToken': CSRF})
    assert resp.status_code == 200
    with app.app_context():
        assert ExamAttempt.query.filter_by(
            student_id=sid, exam_id=eid).first() is not None, \
            '无时长卷进入考试页也应创建开考记录（此前 duration 门跳过）'

    resp = client.post(f'/submit_exam/{eid}',
                       json={},
                       headers={'X-CSRFToken': CSRF,
                                'X-Requested-With': 'XMLHttpRequest'})
    assert resp.status_code == 200, \
        f'无时长卷开考后提交应成功: {resp.get_json()}'
    data = resp.get_json()
    assert data.get('success'), '提交应成功（此前 403 答案丢失）'
    # 清理：提交产生的成绩与 attempt（delete_exam_result 语义不可用——走 DB）
    with app.app_context():
        from sqlalchemy import text as _t
        conn = db.session.connection()
        conn.execute(_t('DELETE FROM result WHERE exam_id=:e'), {'e': eid})
        conn.execute(_t('DELETE FROM exam_attempt WHERE exam_id=:e'), {'e': eid})
        db.session.commit()


# ── P3：clear-stale force（无时长卷死角）─────────────────

def test_clear_stale_force_clears_no_duration_attempts(app):
    """无时长卷的开考记录无超时判定：默认清不掉，force=1 可清除。"""
    eid = _make_exam(app, name=NODUR_EXAM_NAME, duration=None)
    sid = _sid(app)
    _make_attempt(app, sid, eid, age_seconds=0)
    client = _admin_client(app)
    resp = client.post(f'/admin/exams/{eid}/clear-stale-attempts',
                       data={}, headers={'X-CSRFToken': CSRF})
    assert resp.status_code == 302, '成功后重定向回试卷列表'
    with app.app_context():
        assert ExamAttempt.query.filter_by(
            student_id=sid, exam_id=eid).first() is not None, \
            '无时长卷记录不满足超时口径，默认清除不应删它'
    resp = client.post(f'/admin/exams/{eid}/clear-stale-attempts',
                       data={'force': '1'}, headers={'X-CSRFToken': CSRF})
    assert resp.status_code == 302
    with app.app_context():
        assert ExamAttempt.query.filter_by(
            student_id=sid, exam_id=eid).first() is None, \
            'force=1 应清除该卷全部开考记录（无时长卷补救出口）'


# ── P3：exam_status 补 is_enabled ─────────────────────────

def test_exam_status_requires_is_enabled(app):
    """停用（is_enabled=false）试卷：无关系学生轮询 403，在考学生豁免。"""
    eid = _make_exam(app, name=EXAM_NAME + 'X', duration=30)
    sid = _sid(app)
    client = _student_client(app, sid)
    with app.app_context():
        Exam.query.filter_by(id=eid).update(
            {'is_enabled': False, 'is_visible': True, 'is_active': True})
        db.session.commit()
    resp = client.get(f'/exam/{eid}/status')
    assert resp.status_code == 403, '停用试卷无关系学生应 403'
    _make_attempt(app, sid, eid, age_seconds=0)
    resp = client.get(f'/exam/{eid}/status')
    assert resp.status_code == 200, '在考学生豁免（需轮询到收卷状态自动交卷）'
    _drop_attempt(app, sid, eid)


# ── P3：has_active_attempt SQL 口径 ───────────────────────

def test_has_active_attempt_sql_equivalence(app):
    """SQL 侧判定与原 Python 口径等价：未超时=进行中、超时=不锁定。"""
    from app.services.scoring_service import has_active_attempt
    eid = _make_exam(app, duration=30)
    sid = _sid(app)
    _drop_attempt(app, sid, eid)
    with app.app_context():
        exam = db.session.get(Exam, eid)
        assert has_active_attempt(exam) is False, '无记录=无在考'
    _make_attempt(app, sid, eid, age_seconds=60)
    with app.app_context():
        exam = db.session.get(Exam, eid)
        assert has_active_attempt(exam) is True, '未超时记录=考试进行中'
    _make_attempt(app, sid, eid, age_seconds=36 * 60)
    with app.app_context():
        exam = db.session.get(Exam, eid)
        assert has_active_attempt(exam) is False, '超时残留不锁定组卷/删卷'
    _drop_attempt(app, sid, eid)


# ── P3：代理密钥门（TRUST_PROXY_HEADERS=1 直连伪造 XFF）───

def test_proxy_secret_gate_blocks_spoofed_xff(app, monkeypatch):
    """配置 PROXY_SECRET 后：直连请求伪造 XFF 不被采信；携正确密钥才信任。"""
    from app import config as _config
    from app.utils import get_client_ip
    monkeypatch.setattr(_config.Config, 'TRUST_PROXY_HEADERS', True)
    monkeypatch.setattr(_config.Config, 'PROXY_SECRET', 'rev0908-secret')
    probe = create_app()

    @probe.route('/probe_ip_0908')
    def _probe():
        return {'ip': get_client_ip()}

    client = probe.test_client()
    # 直连伪造 XFF：密钥缺失 → 不采信 XFF，取 TCP 对端地址
    resp = client.get(
        '/probe_ip_0908', environ_base={'REMOTE_ADDR': '10.9.0.7'},
        headers={'X-Forwarded-For': '127.0.0.1'})
    assert resp.get_json()['ip'] == '10.9.0.7', \
        '直连伪造 XFF 不应被采信（is_local/限流键旁路面）'
    # 携带正确密钥：XFF 末条被信任
    resp = client.get(
        '/probe_ip_0908', environ_base={'REMOTE_ADDR': '10.9.0.7'},
        headers={'X-Forwarded-For': '9.9.9.9, 172.16.0.5',
                 'X-Proxy-Secret': 'rev0908-secret'})
    assert resp.get_json()['ip'] == '172.16.0.5', \
        '正确密钥的代理请求应采信 XFF 末条'
    # 密钥错误：同直连
    resp = client.get(
        '/probe_ip_0908', environ_base={'REMOTE_ADDR': '10.9.0.7'},
        headers={'X-Forwarded-For': '127.0.0.1',
                 'X-Proxy-Secret': 'wrong-secret'})
    assert resp.get_json()['ip'] == '10.9.0.7'


# ── P3：无 Content-Length 的 JSON 请求 fail-closed ────────

def test_json_without_content_length_rejected(app):
    """chunked JSON 请求无长度声明 → 411（防 JSON 内存 DoS 防线退化）。"""
    from werkzeug.test import EnvironBuilder, run_wsgi_app
    builder = EnvironBuilder('/nonexistent-0908', method='POST',
                             input_stream=io.BytesIO(b'{}'),
                             content_type='application/json')
    environ = builder.get_environ()
    environ.pop('CONTENT_LENGTH', None)  # 模拟 Transfer-Encoding: chunked
    app_iter, status, headers = run_wsgi_app(app.wsgi_app, environ, buffered=True)
    assert status.startswith('411'), \
        f'无 Content-Length 的 JSON 请求应 411，实际 {status}'


# ── P3：模型探测限流 ─────────────────────────────────────

def test_student_fetch_models_rate_limited(app, monkeypatch):
    """student_fetch_models 每分钟限流：超限返回 429（此前无限流可打满线程池）。"""
    monkeypatch.setattr('app.blueprints.ai._fetch_models',
                        lambda *a, **k: (False, 'HTTP 404'))
    sid = _sid(app)
    client = _student_client(app, sid)
    payload = {'api_url': 'https://example.com/v1',
               'api_key': 'sk-test', 'provider': 'openai'}
    got_429 = False
    for _ in range(17):  # 限流阈值 15 次/分钟 → 第 16 次起 429
        resp = client.post('/api/ai/student_fetch_models', json=payload,
                           headers={'X-CSRFToken': CSRF})
        if resp.status_code == 429:
            got_429 = True
            break
    assert got_429, '连续调用应触发 429 限流'


# ── P3：外链卷列表透出 ───────────────────────────────────

def test_exam_list_exposes_link_fields(app):
    """列表接口透出 is_link/link_url（SPA 外链卷渲染"打开链接"的依据）。"""
    link_eid = _make_exam(app, name=LINK_EXAM_NAME, duration=10, link=True)
    normal_eid = _make_exam(app)
    sid = _sid(app)
    client = _student_client(app, sid)
    data = client.get('/api/exams', headers={'X-CSRFToken': CSRF}).get_json()
    assert data['success']
    by_id = {e['id']: e for e in data['data']}
    assert by_id[link_eid]['is_link'] is True
    assert by_id[link_eid]['link_url'] == 'https://example.com/0908'
    assert by_id[normal_eid]['is_link'] is False


# ── P3：教师答案可见性两端口径统一 ────────────────────────

def test_teacher_answer_visibility_unified(app):
    """答案可见性两端口径统一：未收卷时 SSR 结果页不出现标准答案
    （学生/教师/管理员一律受收卷约束，与 SPA api_results 同口径）。"""
    from sqlalchemy import text as _t
    eid = _make_exam(app, duration=30)
    sid = _sid(app)
    rid = _make_result(app, sid, eid)
    client = _student_client(app, sid)
    with app.app_context():
        Exam.query.filter_by(id=eid).update({'is_collected': False,
                                             'allow_view_results': True})
        db.session.commit()
    resp = client.get(f'/result/{rid}')
    assert resp.status_code == 200, '已公布成绩的学生应可打开结果页'
    html = resp.get_data(as_text=True)
    assert '0908LINK? 1+1=?' in html, '题干应正常展示'
    assert 'text-success' not in html, \
        '未收卷时标准答案不应展示（answer 置空 → 对错高亮失准不可见）'
    with app.app_context():
        Exam.query.filter_by(id=eid).update({'is_collected': True})
        db.session.commit()
    html2 = client.get(f'/result/{rid}').get_data(as_text=True)
    assert 'text-success' in html2, \
        '收卷后正确选项应绿色高亮（口径统一不删功能）'
    with app.app_context():
        db.session.execute(_t('DELETE FROM result WHERE id=:r'), {'r': rid})
        db.session.commit()
