# -*- coding: utf-8 -*-
"""并发交卷压力测试（2026-10-27，dev-only，随 e2e_*.py 一起不随安装包分发）。

隔离库 itstudy_e2e + Waitress(48 线程)：
- 200 名学生并发登录、并发开考（ExamAttempt 竞态路径）
- 同时并发提交混合题型试卷（单选/多选/判断/填空/简答/综合题小题）
- 度量：提交延迟 p50/p95/max、成功率、500 计数
- 正确性：200/200 成绩落库、唯一约束、每份 total_score == 预期 24、
  简答全部 pending_review、无 UNHANDLED 错误日志增量
"""
import io
import os
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ['DB_NAME'] = 'itstudy_e2e'
os.environ['CACHE_DIR'] = os.path.join(os.getcwd(), 'data', 'cache_e2e_exam_stress')
os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_PORT', '5432')
os.environ.setdefault('DB_USER', 'postgres')
os.environ.setdefault('DB_PASS', '@@')
os.environ['SECRET_KEY'] = 'e2e-exam-stress-key'
sys.path.insert(0, os.getcwd())

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import (Class, ClassroomSession, Exam, ExamAttempt,  # noqa: E402
                        ExamQuestion, Log, Question, Result, Student,  # noqa: E402
                        SubQuestion)  # noqa: E402

PORT = 5052
BASE = f'http://127.0.0.1:{PORT}'
N_STUDENTS = 200
WORKERS = 48
SFX = uuid.uuid4().hex[:8]
EXAM = f'__stress_exam_{SFX}'
CLASS = f'__stress_cls_{SFX}'
PASS = 'Stress123'
FAILED = []

app = create_app()
assert app.config['DB_NAME'] == 'itstudy_e2e', app.config['DB_NAME']
from e2e_common import reset_shared_state  # noqa: E402
reset_shared_state(app)
LOG_FILE = os.path.join(os.getcwd(), 'logs', 'app.log')


def log_error_count():
    try:
        with open(LOG_FILE, encoding='utf-8', errors='ignore') as f:
            return sum(1 for line in f if 'UNHANDLED' in line)
    except OSError:
        return 0


def show(name, ok, detail=''):
    if not ok:
        FAILED.append(name)
    print(('✓' if ok else '✗') + f' {name} {detail}')


def cleanup():
    with app.app_context():
        eids = [e.id for e in Exam.query.filter(Exam.name.like('__stress_%')).all()]
        if eids:
            ExamAttempt.query.filter(ExamAttempt.exam_id.in_(eids)).delete(
                synchronize_session=False)
            Result.query.filter(Result.exam_id.in_(eids)).delete(
                synchronize_session=False)
            ExamQuestion.query.filter(ExamQuestion.exam_id.in_(eids)).delete(
                synchronize_session=False)
        qids = [q.id for q in Question.query.filter(
            Question.content.like('__stress_%')).all()]
        if qids:
            SubQuestion.query.filter(SubQuestion.question_id.in_(qids)).delete(
                synchronize_session=False)
            Question.query.filter(Question.id.in_(qids)).delete(
                synchronize_session=False)
        Exam.query.filter(Exam.name.like('__stress_%')).delete(
            synchronize_session=False)
        for cls in Class.query.filter(Class.name.like('__stress_%')).all():
            ClassroomSession.query.filter_by(class_id=cls.id).delete(
                synchronize_session=False)
            sids = [s.id for s in Student.query.filter_by(class_id=cls.id).all()]
            if sids:
                from sqlalchemy import text as _t
                db.session.execute(_t(
                    'DELETE FROM attendance_record WHERE student_id = ANY(:ids)'),
                    {'ids': sids})
            Student.query.filter_by(class_id=cls.id).delete(
                synchronize_session=False)
            Class.query.filter_by(id=cls.id).delete(synchronize_session=False)
        Log.query.filter(Log.detail.like('%__stress_%')).delete(
            synchronize_session=False)
        db.session.commit()


cleanup()
with app.app_context():
    exam = Exam(name=EXAM, is_active=True, is_visible=True, is_enabled=True,
                is_collected=False, allow_view_results=True, duration=120)
    db.session.add(exam)
    db.session.flush()
    eid = exam.id
    # 混合题型：单选 5 + 多选 5 + 判断 5 + 填空 5 + 综合题(小题 4) + 简答 10
    q_single = Question(exam_id=eid, question_type='single',
                        content='__stress_单选+', options='A. x|B. y|C. z|D. w',
                        answer='A', score=5)
    q_multi = Question(exam_id=eid, question_type='multiple',
                       content='__stress_多选+', options='A. x|B. y|C. z|D. w',
                       answer='A,C', score=5)
    q_judge = Question(exam_id=eid, question_type='judge',
                       content='__stress_判断+', answer='true', score=5)
    q_fill = Question(exam_id=eid, question_type='fill',
                      content='__stress_填空+', answer='abc', score=5)
    q_comp = Question(exam_id=eid, question_type='comprehensive',
                      content='__stress_综合+', answer='', score=4)
    q_sa = Question(exam_id=eid, question_type='short_answer',
                    content='__stress_简答+', answer='参考', score=10)
    db.session.add_all([q_single, q_multi, q_judge, q_fill, q_comp, q_sa])
    db.session.flush()
    comp_sub = SubQuestion(question_id=q_comp.id, question_type='single',
                           content='__stress_子题+', options='A. x|B. y',
                           answer='A', score=4, order=1)
    db.session.add(comp_sub)
    db.session.commit()
    q1, q2, q3, q4, q5, q6 = (q_single.id, q_multi.id, q_judge.id, q_fill.id,
                              q_comp.id, q_sa.id)
    comp_sub_id = comp_sub.id
    cls = Class(name=CLASS)
    students = []
    for i in range(N_STUDENTS):
        stu = Student(name=f'压测生{i}', student_number=f'__stress_{i}_{SFX}',
                      student_class=CLASS, has_changed_password=True)
        stu.set_password(PASS)
        students.append(stu)
    db.session.add_all([cls] + students)
    db.session.flush()
    for stu in students:
        stu.class_id = cls.id
    db.session.add(ClassroomSession(class_id=cls.id, is_active=True))
    db.session.commit()
    from app.blueprints.auth import invalidate_active_class_cache
    invalidate_active_class_cache()

error_baseline = log_error_count()

from waitress import serve  # noqa: E402
threading.Thread(target=lambda: serve(app, host='127.0.0.1', port=PORT,
                                      threads=WORKERS), daemon=True).start()
time.sleep(1.5)

import requests  # noqa: E402
from requests.adapters import HTTPAdapter  # noqa: E402

# requests 默认每会话连接池仅 10：200 并发会话会互相等连接槽导致超时，
# 统一挂大池适配器模拟真实浏览器（每个会话独立 TCP 池上限）。
POOL = HTTPAdapter(pool_connections=16, pool_maxsize=16)


# ── 并发登录 ──
login_lat = []


def login(i):
    s = requests.Session()
    s.mount('http://', POOL)
    s.mount('https://', POOL)
    t0 = time.perf_counter()
    r = s.get(BASE + '/', timeout=60)
    token = ''
    try:
        token = r.text.split('name="csrf-token" content="')[1].split('"')[0]
    except IndexError:
        token = s.cookies.get('csrf_token', '')
    r = s.post(BASE + '/', data={'csrf_token': token,
                                 'student_number': f'__stress_{i}_{SFX}',
                                 'password': PASS}, timeout=60,
               allow_redirects=False)
    login_lat.append(time.perf_counter() - t0)
    if r.status_code != 302:
        raise RuntimeError(f'login {i} -> {r.status_code}')
    return s


with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    sessions = list(ex.map(login, range(N_STUDENTS)))
show('200 名学生并发登录全部成功',
     len(sessions) == N_STUDENTS,
     '登录 p95 %.0fms' % (sorted(login_lat)[int(len(login_lat) * .95)] * 1000))

# ── 并发开考（ExamAttempt 竞态路径）──
open_lat = []


def open_exam(s):
    t0 = time.perf_counter()
    r = s.get(BASE + f'/online_exam/{eid}', timeout=60)
    open_lat.append(time.perf_counter() - t0)
    if r.status_code != 200:
        raise RuntimeError(f'open -> {r.status_code}')


with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    list(ex.map(open_exam, sessions))
with app.app_context():
    attempts = ExamAttempt.query.filter_by(exam_id=eid).count()
show('200 名学生并发开考记录齐全',
     attempts == N_STUDENTS,
     '开考 p95 %.0fms' % (sorted(open_lat)[int(len(open_lat) * .95)] * 1000))

# ── 并发交卷 ──
submit_lat = []
submit_status = []
errors = 0


def submit(i_s):
    i, s = i_s
    t0 = time.perf_counter()
    # 混合答案：客观题全对（预期 24 分），简答作答（待批改）
    payload = {
        str(q1): 'A',
        str(q2): 'A,C',
        str(q3): 'true',
        str(q4): 'abc',
        f'sub_{comp_sub_id}': 'A',
        str(q6): f'压测简答{i}',
    }
    try:
        r = s.post(BASE + f'/submit_exam/{eid}', json=payload,
                   headers={'X-CSRFToken': s.cookies.get('csrf_token', '')},
                   timeout=60)
        submit_lat.append(time.perf_counter() - t0)
        submit_status.append(r.status_code)
        if r.status_code != 200:
            return
        body = r.json()
        if not body.get('success'):
            submit_status[-1] = -1
    except Exception:
        submit_lat.append(time.perf_counter() - t0)
        submit_status.append(-2)


barrier = threading.Barrier(WORKERS)


def worker(ids):
    barrier.wait()
    for i in ids:
        submit((i, sessions[i]))


chunk = (N_STUDENTS + WORKERS - 1) // WORKERS
with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    list(ex.map(worker, [list(range(j * chunk, min(N_STUDENTS, (j + 1) * chunk)))
                         for j in range(WORKERS)]))

lat = sorted(submit_lat)
show('并发交卷全部返回 200', submit_status.count(200) == N_STUDENTS,
     {code: submit_status.count(code) for code in set(submit_status)})
show('提交 p50/p95/max 延迟',
     True, 'p50 %.0fms / p95 %.0fms / max %.0fms' % (
         lat[len(lat) // 2] * 1000, lat[int(len(lat) * .95)] * 1000,
         lat[-1] * 1000))

# ── 正确性核对 ──
with app.app_context():
    results = Result.query.filter_by(exam_id=eid).all()
    show('成绩行数 = 学生数（唯一约束生效）', len(results) == N_STUDENTS,
         len(results))
    bad = [r for r in results if r.total_score != 24]
    show('每份客观题总分 == 24（判分无串扰）', not bad, len(bad))
    sa_bad = [r for r in results if r.grading_status != 'pending_review']
    show('简答全部进入待批改', not sa_bad, len(sa_bad))
    from sqlalchemy import text as _t
    dup = db.session.execute(_t(
        'SELECT count(*) FROM (SELECT student_id FROM result '
        'WHERE exam_id = :e GROUP BY student_id HAVING count(*) > 1) t'),
        {'e': eid}).scalar()
    show('无重复成绩行', dup == 0, dup)
    stray = ExamAttempt.query.filter_by(exam_id=eid).count()
    show('开考记录随提交清理', stray == 0, stray)

after_errors = log_error_count()
show('本次压测未产生 UNHANDLED 错误',
     after_errors - error_baseline == 0,
     '基线 %d → 当前 %d' % (error_baseline, after_errors))

cleanup()
print()
print('并发交卷压力测试：%s' % ('全部通过' if not FAILED else f'{len(FAILED)} 项失败：{FAILED}'))
sys.exit(1 if FAILED else 0)
