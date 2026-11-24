"""全面审查修复回归测试（2026-08 审计轮）

覆盖：
1. 收卷后打开考试页不再创建开考记录（未开考学生补交作弊通道封堵）
2. python_fill 在线判分 ' // ' 双解释兼容（一空多解 + 整除表达式）
3. python_fill 纯文本答案按第 1 空处理（json.loads 失败不再静默 0 分）
4. 作业提交列表/统计页筛选参数归一化（onchange JS 注入面收敛）
5. /app 无尾斜杠 301 到 /app/（SPA 相对资源基准修正）
6. 网盘闲置清理仅针对学生上传文件（教师投递/手动发送不清理）
7. 考试页总分 = 各题分值之和（Exam 无 total_score 字段，由路由计算）
"""
import datetime

import pytest
from types import SimpleNamespace as NS

from sqlalchemy import text

from app import create_app
from app.extensions import db
from app.models import (
    ClassroomSetting, Class, Exam, ExamAttempt, Question, Result, Student,
    StudentDriveFile,
)
from app.services.scoring_service import (
    _parse_acceptable_answers,
    auto_score,
)

_CSRF = 'audit-csrf'

EXAM_NAME = '审计回归测试卷'
CLS_NAME = '审计回归班'
STU_NUM = 'AUDIT2026'


@pytest.fixture(scope='module')
def app():
    app = create_app()
    _seed(app)
    # 上课班级指向审计班（auth.load_student 会把非活跃班级的学生踢出会话），
    # 记录原值以便恢复
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
            # 恢复原上课班级；原班级已被其他测试 TRUNCATE 清除时置空
            #（本套件部分用例会 RESTART IDENTITY 清空 classes/student）
            setting.active_class_id = orig if (
                orig and db.session.get(Class, orig)) else None
        _cleanup()
        db.session.commit()


def _cleanup():
    conn = db.session.connection()
    # 上课班级若仍指向审计班，先解引用（否则删班触发 FK）
    conn.execute(text(
        'UPDATE classroom_setting SET active_class_id=NULL '
        'WHERE active_class_id IN (SELECT id FROM classes WHERE name=:n)'),
        {'n': CLS_NAME})
    eid = conn.execute(text('SELECT id FROM exam WHERE name=:n'),
                       {'n': EXAM_NAME}).first()
    if eid:
        conn.execute(text('DELETE FROM exam_attempt WHERE exam_id=:e'), {'e': eid[0]})
        conn.execute(text('DELETE FROM result WHERE exam_id=:e'), {'e': eid[0]})
        conn.execute(text('DELETE FROM exam_question WHERE exam_id=:e'), {'e': eid[0]})
        conn.execute(text('DELETE FROM question WHERE exam_id=:e'), {'e': eid[0]})
        conn.execute(text('DELETE FROM exam WHERE id=:e'), {'e': eid[0]})
    conn.execute(text(
        "DELETE FROM student_drive_file WHERE original_filename LIKE 'audit%'"))
    conn.execute(text('DELETE FROM student WHERE student_number=:n'), {'n': STU_NUM})
    conn.execute(text('DELETE FROM classes WHERE name=:n'), {'n': CLS_NAME})


def _seed(app):
    with app.app_context():
        cls = Class.query.filter_by(name=CLS_NAME).first()
        if not cls:
            cls = Class(name=CLS_NAME)
            db.session.add(cls)
        stu = Student.query.filter_by(student_number=STU_NUM).first()
        if not stu:
            stu = Student(name='审计学生', student_number=STU_NUM,
                          student_class=CLS_NAME,
                          is_activated=True, has_changed_password=True)
            stu.set_password('Audit#2026')
            db.session.add(stu)
        exam = Exam.query.filter_by(name=EXAM_NAME).first()
        if not exam:
            exam = Exam(name=EXAM_NAME, is_active=True, is_visible=True,
                        is_enabled=True, duration=30)
            db.session.add(exam)
            db.session.flush()
            db.session.add(Question(
                exam_id=exam.id, question_type='python_fill',
                content='补全代码\nx = int(input())\nprint(____ * 2)',
                score=10, python_answers='{"1": "money // m"}',
                blank_scores='[10]'))
        # 学生挂到审计班（避免被上课班级校验踢出）
        stu.class_id = cls.id
        db.session.commit()
        return stu.id, exam.id


def _ids(app):
    with app.app_context():
        stu = Student.query.filter_by(student_number=STU_NUM).first()
        exam = Exam.query.filter_by(name=EXAM_NAME).first()
        return stu.id, exam.id


def _student_client(app, sid):
    client = app.test_client()
    with client.session_transaction() as s:
        s.clear()
        s['student_id'] = sid
        s['student_name'] = '审计学生'
        s['csrf_token'] = _CSRF
    return client


# ── 1. 收卷后不再创建开考记录 ────────────────────────────

def test_collected_exam_creates_no_attempt(app):
    sid, eid = _ids(app)
    with app.app_context():
        exam = db.session.get(Exam, eid)
        exam.is_collected = True
        db.session.commit()
        ExamAttempt.query.filter_by(student_id=sid, exam_id=eid).delete()
        db.session.commit()
    client = _student_client(app, sid)
    # 收卷后学生打开考试页：不创建开考记录，且直接重定向到结束态提示
    # （此前渲染 start_time=now 的满时长倒计时页，5 秒后自动交卷报错）
    resp = client.get(f'/online_exam/{eid}')
    assert resp.status_code == 302, '收卷后从未开考的学生应被重定向到结束态提示'
    with app.app_context():
        attempt = ExamAttempt.query.filter_by(student_id=sid, exam_id=eid).first()
        assert attempt is None, '收卷后打开考试页不应创建开考记录'
        exam = db.session.get(Exam, eid)
        exam.is_collected = False
        db.session.commit()


def test_uncollected_exam_creates_attempt(app):
    """未收卷时开考记录正常创建（不误伤正常流程）。"""
    sid, eid = _ids(app)
    with app.app_context():
        exam = db.session.get(Exam, eid)
        exam.is_collected = False
        db.session.commit()
    client = _student_client(app, sid)
    resp = client.get(f'/online_exam/{eid}')
    assert resp.status_code == 200
    with app.app_context():
        attempt = ExamAttempt.query.filter_by(student_id=sid, exam_id=eid).first()
        assert attempt is not None, '未收卷时打开考试页应创建开考记录'


def test_submitted_student_revisit_no_new_attempt(app):
    """已提交学生重访考试页不重建 ExamAttempt（提交时已清理）。"""
    sid, eid = _ids(app)
    with app.app_context():
        Result.query.filter_by(student_id=sid, exam_id=eid).delete()
        db.session.add(Result(student_id=sid, exam_id=eid, total_score=0,
                              scores='{}', submit_time=datetime.datetime.now()))
        ExamAttempt.query.filter_by(student_id=sid, exam_id=eid).delete()
        db.session.commit()
    client = _student_client(app, sid)
    client.get(f'/online_exam/{eid}')
    with app.app_context():
        attempt = ExamAttempt.query.filter_by(student_id=sid, exam_id=eid).first()
        assert attempt is None, '已提交学生重访不应重建开考记录'
        Result.query.filter_by(student_id=sid, exam_id=eid).delete()
        db.session.commit()


# ── 2/3. python_fill 判分口径 ────────────────────────────

def test_parse_acceptable_answers_dual_interpretation():
    q = NS(question_type='python_fill')
    # 带空格分隔符（批量导入写入的多解）：拆分后各解可接受
    got = _parse_acceptable_answers('money // m', q)
    assert 'money' in got and 'm' in got
    # 疑似整除表达式：原样保留也接受（双解释兼容，与文件判分一致）
    got2 = _parse_acceptable_answers('a // b', q)
    assert 'a // b' in got2 and 'a' in got2 and 'b' in got2
    # 无空格：按整除表达式保留原样
    assert _parse_acceptable_answers('n//2', q) == ['n//2']
    assert _parse_acceptable_answers('a|b', NS(question_type='fill')) == ['a', 'b']


def test_plain_text_python_fill_answer_scores_blank_one():
    q = NS(question_type='python_fill', score=10,
           python_answers_dict={'1': 'money // m'}, blank_scores_list=[10])
    assert auto_score(q, 'money') == 10, '纯文本答案应按第 1 空判分'
    assert auto_score(q, 'm') == 10
    assert auto_score(q, 'x') == 0
    # JSON dict 形式仍正常
    assert auto_score(q, '{"1": "money"}') == 10


# ── 4. 筛选参数归一化（XSS 注入面收敛）─────────────────

def test_statistics_filter_params_normalized(app):
    client = app.test_client()
    with client.session_transaction() as s:
        s.clear()
        s['is_admin'] = True
        s['csrf_token'] = _CSRF
    payload = "'+alert(document.cookie);//"
    resp = client.get(f'/admin/statistics?class_id={payload}&exam_id={payload}')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # 危险形态是裸引号闭合 JS 字符串（'+alert…）；被 HTML 转义的文本无执行面
    assert "'+alert(" not in body, '恶意 class_id/exam_id 不应原样进入 onchange JS 字符串'


def test_homework_submissions_params_sanitized(app):
    """非法 class_id/status 归一化不抛错（页面正常返回或重定向）。"""
    client = app.test_client()
    with client.session_transaction() as s:
        s.clear()
        s['is_teacher'] = True
        s['teacher_id'] = 1
        s['csrf_token'] = _CSRF
    payload = "x'+alert(1);//"
    resp = client.get(
        f'/admin/homework/999999/submissions?class_id={payload}&status={payload}',
        follow_redirects=False)
    assert resp.status_code in (302, 404)


# ── 5. /app 尾斜杠重定向 ─────────────────────────────────

def test_app_root_redirects_with_slash(app):
    client = app.test_client()
    resp = client.get('/app', follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers['Location'].endswith('/app/')


# ── 6. 网盘闲置清理范围 ──────────────────────────────────

def test_idle_cleanup_targets_student_uploads_only(app):
    sid, _ = _ids(app)
    with app.app_context():
        old = datetime.datetime.now() - datetime.timedelta(days=365)
        rows = [
            StudentDriveFile(student_id=sid, filename='audit_up.bin',
                             original_filename='audit_up.bin', file_size=1,
                             file_path='cloud_drive/1/audit_up.bin',
                             source_type='student_upload', created_at=old),
            StudentDriveFile(student_id=sid, filename='audit_manual.bin',
                             original_filename='audit_manual.bin', file_size=1,
                             file_path='cloud_drive/1/audit_manual.bin',
                             source_type='manual', created_at=old),
            StudentDriveFile(student_id=sid, filename='audit_hw.bin',
                             original_filename='audit_hw.bin', file_size=1,
                             file_path='cloud_drive/1/audit_hw.bin',
                             source_type='homework', created_at=old),
        ]
        db.session.add_all(rows)
        db.session.commit()
        from app.services.student_drive_service import find_idle_drive_files
        found = {r.file_path for r, _ in find_idle_drive_files(90)}
        assert 'cloud_drive/1/audit_up.bin' in found
        assert 'cloud_drive/1/audit_manual.bin' not in found, '手动发送文件不应被闲置清理'
        assert 'cloud_drive/1/audit_hw.bin' not in found, '作业投递不应被闲置清理'


# ── 7. 考试页总分计算 ────────────────────────────────────

def test_exam_page_shows_total_score(app):
    sid, eid = _ids(app)
    with app.app_context():
        Result.query.filter_by(student_id=sid, exam_id=eid).delete()
        ExamAttempt.query.filter_by(student_id=sid, exam_id=eid).delete()
        exam = db.session.get(Exam, eid)
        exam.is_collected = False
        db.session.commit()
    client = _student_client(app, sid)
    resp = client.get(f'/online_exam/{eid}')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert '总分：</strong>' in body
    assert '总分：</strong>10.0分' in body.replace(' ', '') \
        or '总分：</strong>10.0分' in body, '考试信息面板应显示计算出的总分而非空值'
