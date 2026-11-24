# -*- coding: utf-8 -*-
"""页面渲染级按钮/显示检查：登录各角色渲染关键页面，断言按钮与数据显示"""
import io
import os
import secrets
import sys

os.environ['DB_NAME'] = 'itstudy_btncheck'
# 缓存目录按测试库隔离：get_classes_cached 等共享缓存键（lookup:classes 等）不区分数据库，
# 不隔离会让测试库数据（如'按钮检查班'）污染主库页面的缓存命中
os.environ['CACHE_DIR'] = os.path.join(os.getcwd(), 'data', 'cache_test')
os.environ['DB_HOST'] = 'localhost'
os.environ['DB_PORT'] = '5432'
os.environ['DB_USER'] = 'postgres'
os.environ['DB_PASS'] = '@@'
os.environ['SECRET_KEY'] = 'btn-check-key'
sys.path.insert(0, os.getcwd())

from app import create_app
from app.extensions import db

results = []
# 管理员凭据每次随机生成并建在隔离库里：仓库里不留任何真实口令，
# 也不依赖安装机的 admin_account.txt。
ADMIN_USER = 'btn_admin'
ADMIN_PASS = secrets.token_urlsafe(18)


def check(mod, name, cond, extra=''):
    results.append((mod, name, bool(cond)))
    mark = 'PASS' if cond else 'FAIL'
    print(f'[{mark}] [{mod}] {name}{" | " + str(extra) if extra else ""}')


app = create_app()
client = app.test_client()


def csrf():
    client.get('/')
    c = client.get_cookie('csrf_token')
    return c.value if c else ''


def post(url, data=None, j=None):
    h = {'X-CSRFToken': csrf()}
    if j is not None:
        return client.post(url, json=j, headers=h)
    return client.post(url, data=data or {}, headers=h)


def get(url, **kw):
    return client.get(url, **kw)


# ── 准备数据 ──
with app.app_context():
    from app.models import (AdminAccount, Class, Student, Teacher, ClassroomSetting, Exam,
                            Question, Subject, Homework, Resource, LearningActivity)
    cls = Class(name='按钮检查班')
    db.session.add(cls)
    db.session.flush()
    stu = Student(name='检查生', student_number='B001', class_id=cls.id)
    stu.set_password('123456')
    stu.has_changed_password = True  # 新安全策略：测试学生视为已改密，跳过强制改密拦截
    db.session.add(stu)
    db.session.flush()
    subj = Subject(name='按钮检查学科', sort_order=0)
    db.session.add(subj)
    db.session.flush()
    cs = ClassroomSetting.query.first()
    if not cs:
        cs = ClassroomSetting(active_class_id=cls.id)
        db.session.add(cs)
    else:
        cs.active_class_id = cls.id
    t = Teacher(username='btn_teacher', display_name='按钮老师')
    t.set_password('teach123')
    db.session.add(t)
    db.session.flush()
    # 教师资源页/作品页按「课堂可见 + 创建者或共享」过滤：夹具须给资源
    # 设置 show_in_classroom 并挂到该教师名下，否则页面本就应为空
    teacher_id = t.id
    exam = Exam(name='按钮检查卷', is_active=True, is_visible=True,
                is_enabled=True, subject_id=subj.id)
    db.session.add(exam)
    db.session.flush()
    exam_id = exam.id
    q1 = Question(exam_id=exam_id, question_type='single', content='按钮题?',
                  options='A.是|B.否', answer='A', score=10)
    db.session.add(q1)
    db.session.flush()
    q1_id = q1.id
    hw = Homework(title='按钮检查作业', subject_id=subj.id)
    db.session.add(hw)
    db.session.flush()
    hw_id = hw.id
    hw.classes.append(cls)
    res = Resource(title='按钮检查资源', url='https://example.com',
                   show_in_student=True, show_in_classroom=True,
                   creator_type='teacher', creator_teacher_id=teacher_id,
                   creator_name='按钮老师')
    db.session.add(res)
    db.session.flush()
    res_id = res.id
    act = LearningActivity(resource_id=res_id, title='按钮检查活动',
                           description='d', require_upload=True, is_active=True)
    db.session.add(act)
    from app.models import StudyGroup
    g = StudyGroup(name='按钮检查小组', class_id=cls.id)
    db.session.add(g)
    adm = AdminAccount(username=ADMIN_USER, display_name='按钮检查管理员')
    adm.set_password(ADMIN_PASS)
    db.session.add(adm)
    db.session.commit()

# ═══ 管理员页面按钮检查 ═══
r = post('/api/auth/admin-login', j={'username': ADMIN_USER, 'password': ADMIN_PASS})
check('管理员', '登录', r.status_code == 200)

pages_btns = [
    ('/admin/exams', ['启用', '收卷', '编辑', '删除']),
    ('/admin/classes', ['添加班级', '编辑', '学生', '小组', '删除']),
    ('/admin/students', ['添加学生', '批量导入', '批量删除', '重置密码', '导出']),
    ('/admin/groups', ['添加小组']),
    ('/admin/homework', ['发布作业', '批改', '编辑', '删除']),
    ('/admin/resources', ['上传资源', '删除']),
    ('/admin/questions', ['导入', '批量删除', '编辑', '删除']),
    ('/admin/statistics', ['导出', '删除']),
    ('/admin/attendance', ['自动刷新', '未签到']),
    ('/admin/schedule', ['添加作息', '编辑', '删除']),
    ('/admin/student-drive', ['筛选', '管理网盘']),
    ('/admin/ai_config', ['保存', '获取模型']),
    ('/admin/system', ['保存']),
    ('/admin/backup', ['备份', '下载']),
    ('/admin/logs', ['清除日志']),
    ('/admin/classroom', ['当前上课班级']),
]
for path, btns in pages_btns:
    resp = get(path)
    body = resp.get_data(as_text=True) if resp.status_code == 200 else ''
    missing = [b for b in btns if b not in body]
    check('管理员页面', f'{path} 渲染+按钮', resp.status_code == 200 and not missing,
          f'缺按钮: {missing}' if missing else f'({resp.status_code})')

# 具体按钮点击验证：添加学科表单
r = post('/admin/subjects', {'name': '新学科X'})
with app.app_context():
    from app.models import Subject as _S
    check('按钮功能', '添加学科按钮→提交生效',
          _S.query.filter_by(name='新学科X').first() is not None)

# ═══ 教师页面按钮检查 ═══
r = post('/teacher/login', {'username': 'btn_teacher', 'password': 'teach123'})
check('教师', '登录', r.status_code in (200, 302))
teacher_pages = [
    ('/teacher/resources', ['学习活动']),
    ('/teacher/student-drive', ['筛选']),
    ('/admin/homework', ['发布作业', '批改']),
    ('/admin/homework/create', ['发布']),
    ('/teacher/works', ['查看作品']),
]
for path, btns in teacher_pages:
    resp = get(path)
    body = resp.get_data(as_text=True) if resp.status_code == 200 else ''
    missing = [b for b in btns if b not in body]
    check('教师页面', f'{path} 渲染+按钮', resp.status_code == 200 and not missing,
          f'缺按钮: {missing}' if missing else '')

# ═══ 学生页面按钮检查 ═══
r = post('/api/auth/login', j={'mode': 'student', 'student_number': 'B001',
                               'password': '123456'})
check('学生', '登录', r.status_code == 200)
student_pages = [
    ('/exam', ['进入测试']),
    # AI 助手按钮由 ai-chat.js 按 /api/ai/status 动态注入（AI 未配置时
    # 不出现），静态页断言检查脚本接线而非按钮字面量
    ('/study', ['ai-chat.js', '资源']),
    ('/student/homework', ['提交作业']),
    ('/student/drive', ['上传']),
    ('/groups', ['申请', '加入']),
    ('/change-password', ['修改密码']),
]
for path, btns in student_pages:
    resp = get(path)
    body = resp.get_data(as_text=True) if resp.status_code == 200 else ''
    missing = [b for b in btns if b not in body]
    check('学生页面', f'{path} 渲染+按钮', resp.status_code == 200 and not missing,
          f'缺按钮: {missing}' if missing else '')

# 考试页答题控件
resp = get(f'/online_exam/{exam_id}')
body = resp.get_data(as_text=True)
check('学生考试页', '答题控件+提交按钮',
      resp.status_code == 200 and '提交' in body and '按钮题' in body)

# 提交答案 → 成绩显示
r = post(f'/submit_exam/{exam_id}', j={str(q1_id): 'A'})
check('学生考试', '提交答案按钮→生效', r.status_code == 200, r.get_json())
resp = get('/exam')
body = resp.get_data(as_text=True)
check('学生考试', '成绩显示在列表', '10' in body and '按钮检查卷' in body)

# 作业详情页按钮
resp = get(f'/student/homework/{hw_id}')
body = resp.get_data(as_text=True)
check('学生作业页', '提交按钮显示', resp.status_code == 200 and ('提交' in body or '重新提交' in body))

# 试卷启用开关（放在学生考试验证之后，避免影响考试入口显示）
r = post('/api/auth/admin-login', j={'username': ADMIN_USER, 'password': ADMIN_PASS})
r = post(f'/admin/exams/toggle/{exam_id}', {'flag': 'is_enabled', 'value': 'false'})
check('按钮功能', '试卷启用开关按钮生效', r.status_code in (200, 302))
with app.app_context():
    ex = db.session.get(Exam, exam_id)
    check('按钮功能', '试卷开关状态已变更', ex.is_enabled is False)

# 活动页（学生提交作品按钮）
resp = get('/study')
body = resp.get_data(as_text=True)
check('学习页', '活动入口显示', '按钮检查活动' in body or '按钮检查资源' in body)

# ═══ 修复项验证：add_question.html 图片上传端点 ═══
r = post('/api/auth/admin-login', j={'username': ADMIN_USER, 'password': ADMIN_PASS})
resp = get('/admin/questions')
# 上传图片接口真实可用（表单文件）
r = post('/admin/questions/upload_img',
         {'img': (io.BytesIO(b'GIF89a\x01\x00\x01\x00\x00\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'), 't.gif')})
j = r.get_json() if r.is_json else None
check('修复项', 'upload_img 接口可用(按钮后端)', r.status_code == 200 and j and j.get('success'),
      r.get_data(as_text=True)[:80])
# add_question.html 已不再引用 upload_image
content = open(os.path.join(os.getcwd(), 'templates', 'add_question.html'),
               encoding='utf-8').read()
check('修复项', '前端按钮指向正确端点', 'upload_image' not in content and 'upload_img' in content)

# ═══ 汇总与清理 ═══
passed = sum(1 for _, _, ok in results if ok)
total = len(results)
print(f'\n════════ 结果: {passed}/{total} 通过 ════════')
for mod, name, ok in results:
    if not ok:
        print(f'  失败: [{mod}] {name}')
try:
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
    conn = psycopg2.connect(host='localhost', port=5432, user='postgres',
                            password='@@', dbname='postgres')
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    cur.execute('DROP DATABASE IF EXISTS itstudy_btncheck WITH (FORCE)')
    cur.close()
    conn.close()
    print('测试库已清理')
except Exception as e:
    print('清理失败(忽略):', e)
sys.exit(1 if passed < total else 0)
