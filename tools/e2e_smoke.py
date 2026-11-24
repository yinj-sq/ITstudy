# -*- coding: utf-8 -*-
"""端到端冒烟验证 v5
管理员→班级/学生→上课班级→学生登录/改密→学生端→教师→教师端→管理员端→删除链路

运行：venv/Scripts/python.exe tools/e2e_smoke.py
环境：隔离库 itstudy_e2e（与其它 e2e_* 工具同库）、缓存独立；测后清理。
任一检查项失败 → 退出码 1。

v5 之前本脚本不设 DB_NAME，直接连 postgresql.txt / 内置默认的**生产库**，
且收尾无条件把 classroom_setting.active_class_id 置空（上课中途跑一次 =
全体学生被踢出）；管理员口令也硬编码在源码里。现改为隔离库 + 临时 DB
管理员账号（随机口令）+ 收尾还原上课班级设置。
"""
import io
import os
import secrets
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
E2E_DB = 'itstudy_e2e'
os.environ['DB_NAME'] = E2E_DB
os.environ['CACHE_DIR'] = os.path.join(os.getcwd(), 'data', 'cache_e2e_smoke')
os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_PORT', '5432')
os.environ.setdefault('DB_USER', 'postgres')
os.environ.setdefault('DB_PASS', '@@')
os.environ['SECRET_KEY'] = 'e2e-smoke-key'
sys.path.insert(0, os.getcwd())  # 支持任意 cwd 下直接运行（与其它 e2e_* 工具一致）

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from sqlalchemy import text  # noqa: E402

app = create_app()
if app.config['DB_NAME'] != E2E_DB:
    raise SystemExit(f'拒绝运行：解析出的数据库为 {app.config["DB_NAME"]!r}，不是隔离库 {E2E_DB!r}')
from e2e_common import reset_shared_state  # noqa: E402
reset_shared_state(app)

client = app.test_client()
CSRF = None
ADMIN_USER = 'smoke_admin'
ADMIN_PASS = secrets.token_urlsafe(18)
CLASS_NAME = 'SMOKE测试班'
STU_NUM = 'SMK20260001'
TEACHER_USER = 'smoke_teacher01'
FAILED = []


def _cleanup():
    with app.app_context():
        conn = db.session.connection()
        for stmt in (
            "DELETE FROM attendance_record WHERE student_id IN"
            " (SELECT id FROM student WHERE student_number LIKE 'SMK%')",
            "DELETE FROM student WHERE student_number LIKE 'SMK%'",
            "DELETE FROM classroom_session WHERE class_id IN"
            " (SELECT id FROM classes WHERE name = :cls)",
            "DELETE FROM class_schedule WHERE class_name = :cls",
            "UPDATE teaching_session SET class_id = NULL WHERE class_id IN"
            " (SELECT id FROM classes WHERE name = :cls)",
            "DELETE FROM teacher_class WHERE teacher_id IN"
            " (SELECT id FROM teacher WHERE username = :tu)",
            "DELETE FROM teacher_subject WHERE teacher_id IN"
            " (SELECT id FROM teacher WHERE username = :tu)",
            "DELETE FROM resource_share WHERE teacher_id IN"
            " (SELECT id FROM teacher WHERE username = :tu)",
            "DELETE FROM classes WHERE name = :cls",
            "DELETE FROM teacher WHERE username = :tu",
            "DELETE FROM admin_account WHERE username = :au",
        ):
            conn.execute(text(stmt), {'cls': CLASS_NAME, 'tu': TEACHER_USER,
                                      'au': ADMIN_USER})
        db.session.commit()


def get_csrf():
    global CSRF
    if CSRF is None:
        r = client.get('/admin/login')
        for header in r.headers.getlist('Set-Cookie'):
            if header.startswith('csrf_token='):
                CSRF = header.split('csrf_token=', 1)[1].split(';', 1)[0]
    return CSRF


def show(name, ok, detail=''):
    mark = '✓' if ok else '✗'
    if not ok:
        FAILED.append(name)
    print(f'{mark} {name} {detail}')


def admin_login():
    r = client.post('/admin/login', data={'username': ADMIN_USER, 'password': ADMIN_PASS,
                                          'csrf_token': get_csrf()}, follow_redirects=False)
    return r.status_code == 302


# ══ 0. 幂等预清理 + 临时管理员 + 记录原上课班级设置 ══
_cleanup()
from app.models import AdminAccount, Class, Student, Teacher  # noqa: E402
with app.app_context():
    _adm = AdminAccount(username=ADMIN_USER, display_name='冒烟管理员')
    _adm.set_password(ADMIN_PASS)
    db.session.add(_adm)
    db.session.commit()
    ORIG_CLASSROOM = [tuple(r) for r in db.session.execute(text(
        'SELECT id, active_class_id, current_schedule_id FROM classroom_setting')).all()]

try:
    # ══ 1. 管理员 + 数据准备 ══
    show('管理员登录', admin_login())
    client.post('/admin/classes/add', data={'name': CLASS_NAME, 'csrf_token': get_csrf()})
    with app.app_context():
        cid = Class.query.filter_by(name=CLASS_NAME).first().id
    client.post('/admin/students/add', data={'name': '冒烟学生1', 'student_number': STU_NUM,
                                             'password': '123456', 'class_id': cid,
                                             'csrf_token': get_csrf()})
    with app.app_context():
        sid = Student.query.filter_by(student_number=STU_NUM).first().id
    client.post('/admin/classroom/settings', data={'active_class_id': str(cid),
                                                   'csrf_token': get_csrf()})
    show('数据准备(班级/学生/上课班级)', True, f'cid={cid} sid={sid}')

    # ══ 2. 学生流程 ══
    r = client.post('/', data={'student_number': STU_NUM, 'password': '123456',
                               'csrf_token': get_csrf()}, follow_redirects=False)
    show('学生登录', r.status_code == 302, f'-> {r.status_code}')
    r = client.get('/exam', follow_redirects=False)
    show('未改密被拦截(预期302→改密页)', r.status_code == 302, f'-> {r.status_code}')
    r = client.post('/change-password', data={'old_password': '123456', 'new_password': '654321',
                                              'confirm_password': '654321', 'csrf_token': get_csrf()},
                    follow_redirects=False)
    show('学生改密', r.status_code in (302, 200), f'-> {r.status_code}')

    student_pages = [('/exam', '考试列表', 200), ('/study', '学习资源', 200),
                     ('/student/homework', '学生作业', 200), ('/student/drive', '个人网盘', 200),
                     ('/groups', '学习小组', 200), (f'/student/trend/{sid}', '成绩趋势', 200),
                     ('/pptist', 'PPTist(重定向到编辑器)', 302),
                     ('/change-password', '改密页', 200)]
    for path, name, expect in student_pages:
        r = client.get(path, follow_redirects=False)
        show(f'学生端:{name}', r.status_code == expect, f'-> {r.status_code}')

    # ══ 3. 学生 API 越权 ══
    r = client.get('/api/results/99999')
    show('学生查他人成绩被拒(API 403/404)', r.status_code in (403, 404), f'-> {r.status_code}')
    r = client.get('/static/uploads/cloud_drive/99999/x.txt')
    show('学生访问他人网盘文件被拒', r.status_code in (403, 404), f'-> {r.status_code}')

    # ══ 4. 教师流程 ══
    admin_login()
    from app.models import Subject as _Subject, Class as _Class
    with app.app_context():
        _smoke_subject = _Subject.query.first()
        _smoke_class = _Class.query.first()
    _subject_ids = [str(_smoke_subject.id)] if _smoke_subject else []
    _class_ids = [str(_smoke_class.id)] if _smoke_class else []
    r = client.post('/admin/teacher_account', data={'action': 'create', 'username': TEACHER_USER,
                                                    'password': 'Smoke123456', 'display_name': '冒烟教师1',
                                                    'subject_ids': _subject_ids,
                                                    'grade': '高一',
                                                    'class_ids': _class_ids,
                                                    'csrf_token': get_csrf()})
    show('管理员创建教师', r.status_code in (302, 200), f'-> {r.status_code}')
    r = client.post('/teacher/login', data={'username': TEACHER_USER, 'password': 'Smoke123456',
                                            'csrf_token': get_csrf()}, follow_redirects=False)
    show('教师登录', r.status_code == 302, f'-> {r.status_code}')

    teacher_pages = [('/teacher/resources', '教师资源', 200), ('/teacher/student-drive', '教师网盘管理', 200),
                     ('/teacher/teaching-sessions', '教学记录', 200), ('/admin/homework', '作业管理', 200),
                     ('/admin/classroom', '教师课堂大屏', 200)]
    for path, name, expect in teacher_pages:
        r = client.get(path)
        show(f'教师端:{name}', r.status_code == expect, f'-> {r.status_code}')

    # 教师访问管理端专属页面应被拒（预期302）
    r = client.get('/admin/students', follow_redirects=False)
    show('教师访问学生管理被拒(预期302)', r.status_code == 302, f'-> {r.status_code}')

    # ══ 5. 管理员端页面 ══
    admin_login()
    admin_pages = [('/admin/students', '学生管理'), ('/admin/classroom', '课堂大屏'),
                   ('/admin/schedule', '课程表'), ('/admin/statistics', '统计'),
                   ('/admin/logs', '日志'), ('/admin/groups', '小组管理'),
                   ('/admin/online_students', '在线学生'), ('/admin/ai_config', 'AI配置'),
                   ('/admin/exams', '试卷管理'), ('/admin/questions', '题库管理'),
                   ('/admin/resources', '资源管理'), ('/admin/teacher_account', '教师账号'),
                   ('/admin/student-drive', '学生网盘管理'), ('/admin/backup', '备份'),
                   ('/admin/attendance', '考勤'),
                   ('/admin/python_logs', 'Python日志'), ('/admin/class_schedule', '班级课程表')]
    for path, name in admin_pages:
        r = client.get(path)
        show(f'管理端:{name}', r.status_code == 200, f'-> {r.status_code}')

    # ══ 6. 删除链路验证（路由层）══
    r = client.post(f'/admin/students/{sid}/delete', data={'csrf_token': get_csrf()})
    show('管理端删除学生(路由层)', r.status_code in (302, 200), f'-> {r.status_code}')
    with app.app_context():
        gone = db.session.get(Student, sid) is None
    show('学生记录已删除', gone)
    with app.app_context():
        t = Teacher.query.filter_by(username=TEACHER_USER).first()
        tid = t.id if t else None
    show('教师账号已创建', tid is not None)
    if tid:
        client.post('/admin/teacher_account', data={'action': 'delete', 'teacher_id': str(tid),
                                                    'csrf_token': get_csrf()})
        with app.app_context():
            show('管理端删除教师', db.session.get(Teacher, tid) is None)
finally:
    # ══ 7. 收尾：还原上课班级设置（而非无条件置空）+ 按前缀清理 ══
    with app.app_context():
        for row_id, active_cid, sched_id in ORIG_CLASSROOM:
            db.session.execute(text(
                'UPDATE classroom_setting SET active_class_id = :a, current_schedule_id = :s '
                'WHERE id = :i'), {'a': active_cid, 's': sched_id, 'i': row_id})
        if not ORIG_CLASSROOM:
            db.session.execute(text('DELETE FROM classroom_setting'))
        db.session.commit()
    _cleanup()
    print('测试数据清理完成')

print(f'══ 冒烟测试结束：{"全部通过" if not FAILED else f"{len(FAILED)} 项失败"} ══')
sys.exit(1 if FAILED else 0)
