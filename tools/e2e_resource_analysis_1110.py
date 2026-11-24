# -*- coding: utf-8 -*-
"""2026-11-10 资源功能真实浏览器回归：上传、相对链接、逐题分析。

运行：venv/Scripts/python.exe -X utf8 tools/e2e_resource_analysis_1110.py
使用 itstudy_test 隔离库、随机本地端口和临时账号，完成后清理测试数据。
截图保存在 data/e2e_resource_1110/，不写入 Git。
"""
import json
import os
import pathlib
import shutil
import sys
import tempfile
import threading
import uuid

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding='utf-8')
os.environ['DB_NAME'] = 'itstudy_test'
SUFFIX = uuid.uuid4().hex[:10]
os.environ['CACHE_DIR'] = str(pathlib.Path(tempfile.gettempdir()) / f'itstudy_e2e_1110_{SUFFIX}')

from app.config import Config
assert Config.SQLALCHEMY_DATABASE_URI.rsplit('/', 1)[-1] == 'itstudy_test'
from app import create_app
from app.extensions import db
from app.models import (AttendanceRecord, Class, ClassroomSession, Log, Resource,
                        ResourceQuizResult, Student, Subject, Teacher, teacher_class, teacher_subject)
from app.utils import inject_quiz_collector
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

app = create_app()
from e2e_common import reset_shared_state  # noqa: E402
reset_shared_state(app)
ARTIFACTS = ROOT / 'data/e2e_resource_1110'
ARTIFACTS.mkdir(parents=True, exist_ok=True)
NAME = f'__e2e1110_{SUFFIX}'
PASSWORD = uuid.uuid4().hex
UPLOAD_TITLE = NAME + '_upload'
COURSE_DIR = NAME + '_course'
folder = ROOT / 'static/uploads' / COURSE_DIR
folder.mkdir(parents=True)
ids = {'resources': [], 'students': [], 'teachers': [], 'subjects': [], 'class': None}
upload_ids = set()
errors = []
checks = []

QUIZ_HTML = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>Python 逐题采集联测</title></head>
<body><h1>Python 基础测验</h1>
<form id="quizForm">
<fieldset data-qid="q1" data-correct-answer="B"><legend>1. Python 用于遍历序列的语句是？</legend>
<label><input type="radio" name="q1" value="A" id="q1a">A. if 条件判断</label>
<label><input type="radio" name="q1" value="B" id="q1b">B. for 循环</label></fieldset>
<fieldset data-qid="q2" data-correct-answer='["A","C"]'><legend>2. 哪些属于 Python 常见数据类型？</legend>
<label><input type="checkbox" name="q2" id="q2a">A. list 列表</label>
<label><input type="checkbox" name="q2" id="q2b">B. 未定义类型</label>
<label><input type="checkbox" name="q2" id="q2c">C. dict 字典</label></fieldset>
<fieldset data-qid="q3" data-correct-answer="requests.get"><legend>3. requests 获取网页的方法名称是？</legend>
<input type="text" id="q3" name="q3"></fieldset>
<div id="dynamic"></div><button type="button" id="addQuestion">添加动态题目</button>
<section class="question" data-qid="q5" data-correct-answer="B"><h2>5. Python 的文件扩展名是？</h2>
<button type="button" class="option" data-option="A" id="q5a">A. .exe 可执行文件</button>
<button type="button" class="option" data-option="B" id="q5b">B. .py Python 源代码</button></section>
<label>姓名（不采集）<input name="student_name" value="不应采集的身份字段"></label>
<input type="password" name="password" value="not-an-answer">
<button type="submit" id="finish">提交答案</button></form>
<div id="test-result" hidden><h2>测试完成</h2><div id="total-questions">5</div>
<div id="correct-count">0</div><div id="accuracy">0%</div></div>
<script>
document.getElementById('addQuestion').onclick=function(){
 document.getElementById('dynamic').innerHTML='<fieldset data-qid="q4" data-correct-answer="C"><legend>4. Python 定义函数使用哪个关键字？</legend><label><input type="radio" name="q4" value="A" id="q4a">A. class</label><label><input type="radio" name="q4" value="C" id="q4c">C. def</label></fieldset>';
 this.hidden=true;
};
document.querySelectorAll('[data-qid="q5"] button').forEach(function(b){b.onclick=function(){
 document.querySelectorAll('[data-qid="q5"] button').forEach(function(x){x.classList.remove('selected');});
 this.classList.add('selected');
};});
document.getElementById('quizForm').onsubmit=function(event){event.preventDefault();
 var score=Number(document.getElementById('q1b').checked)+Number(document.getElementById('q2a').checked && document.getElementById('q2c').checked && !document.getElementById('q2b').checked)+Number(document.getElementById('q3').value==='requests.get')+Number(document.getElementById('q4c').checked)+Number(document.getElementById('q5b').classList.contains('selected'));
 document.getElementById('correct-count').textContent=score;
 document.getElementById('accuracy').textContent=(score*20)+'%';
 document.getElementById('test-result').hidden=false;
};
</script></body></html>'''


def check(name, condition):
    checks.append(name)
    if not condition:
        raise AssertionError(name)
    print('PASS', name)


def teacher_login(page):
    page.goto(base + '/teacher/login')
    page.locator('input[name=username]').fill(NAME)
    if page.locator('#readonlyMode').is_checked():
        page.locator('#readonlyMode').uncheck()
    page.locator('input[name=password]').fill(PASSWORD)
    page.locator('button[type=submit]').click()
    page.wait_for_url('**/teacher/*')


def save_files():
    (folder / '教材/章节').mkdir(parents=True)
    (folder / '测验').mkdir()
    (folder / '教材/index.html').write_text(
        '<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="theme.css"></head>'
        '<body><h1 id="topic">Python 进阶之爬虫：链接联测</h1><a id="next" href="章节/next.html">下一页</a>'
        '<a id="fragment" href="#topic">本页锚点</a></body></html>', encoding='utf-8')
    (folder / '教材/章节/next.html').write_text(
        '<!doctype html><html><head><meta charset="utf-8"><script src="../helpers.js"></script></head>'
        '<body><h1>子目录第二页</h1><a id="back" href="../index.html#topic">返回首页</a></body></html>', encoding='utf-8')
    (folder / '教材/theme.css').write_text('body {color: rgb(10, 40, 90); padding: 24px;}', encoding='utf-8')
    (folder / '教材/helpers.js').write_text('window.relativeScriptLoaded = true;', encoding='utf-8')
    (folder / '测验/forms.html').write_text(QUIZ_HTML, encoding='utf-8')


def cleanup():
    from app.blueprints.auth import invalidate_active_class_cache
    with app.app_context():
        db.session.rollback()
        resources = Resource.query.filter(Resource.title.like(NAME + '%')).all()
        resource_ids = [row.id for row in resources]
        if resource_ids:
            ResourceQuizResult.query.filter(ResourceQuizResult.resource_id.in_(resource_ids)).delete(synchronize_session=False)
            Resource.query.filter(Resource.id.in_(resource_ids)).delete(synchronize_session=False)
        AttendanceRecord.query.filter(AttendanceRecord.student_id.in_(ids['students'])).delete(synchronize_session=False)
        Log.query.filter(Log.user_id.in_(ids['students']), Log.user_type == 'student').delete(synchronize_session=False)
        Log.query.filter(Log.detail.contains(NAME)).delete(synchronize_session=False)
        Student.query.filter(Student.id.in_(ids['students'])).delete(synchronize_session=False)
        db.session.execute(teacher_class.delete().where(teacher_class.c.teacher_id.in_(ids['teachers'])))
        db.session.execute(teacher_subject.delete().where(teacher_subject.c.teacher_id.in_(ids['teachers'])))
        Teacher.query.filter(Teacher.id.in_(ids['teachers'])).delete(synchronize_session=False)
        Subject.query.filter(Subject.id.in_(ids['subjects'])).delete(synchronize_session=False)
        ClassroomSession.query.filter_by(class_id=ids['class']).delete(synchronize_session=False)
        Class.query.filter_by(id=ids['class']).delete(synchronize_session=False)
        db.session.commit()
        invalidate_active_class_cache()
    shutil.rmtree(folder, ignore_errors=True)
    for teacher_id in ids['teachers']:
        shutil.rmtree(ROOT / 'static/uploads' / f't{teacher_id}_{UPLOAD_TITLE}', ignore_errors=True)
    for upload_id in upload_ids:
        shutil.rmtree(ROOT / 'static/chunks' / upload_id, ignore_errors=True)
    shutil.rmtree(os.environ['CACHE_DIR'], ignore_errors=True)


server = None
try:
    save_files()
    with app.app_context():
        cls = Class(name=NAME + '_class')
        subject = Subject(name=NAME + '_subject')
        teacher = Teacher(username=NAME, display_name='资源联测教师')
        teacher.set_password(PASSWORD)
        teacher.classes = [cls]
        teacher.subjects = [subject]
        db.session.add_all([cls, subject, teacher])
        db.session.flush()
        ids['class'] = cls.id
        ids['subjects'] = [subject.id]
        ids['teachers'] = [teacher.id]
        db.session.add(ClassroomSession(class_id=cls.id, is_active=True))
        for number in range(3):
            student = Student(name=f'联测学生{number + 1}', student_number=f'{NAME}_s{number}',
                              class_id=cls.id, student_class=cls.name, has_changed_password=True)
            student.set_password(PASSWORD)
            db.session.add(student)
            db.session.flush()
            ids['students'].append(student.id)
        tree = [{'id': 'section', 'title': '测试课程', 'children': [], 'items': [
            {'id': 'intro', 'title': '嵌套网页', 'kind': 'link',
             'src': f'/static/uploads/{COURSE_DIR}/教材/index.html',
             'visible': {'teacher': True, 'student': True}},
            {'id': 'quiz', 'title': 'Python 测验', 'kind': 'link',
             'src': f'/static/uploads/{COURSE_DIR}/测验/forms.html',
             'visible': {'teacher': True, 'student': True}},
        ]}]
        resource = Resource(title=NAME + '_resource', url=f'/static/uploads/{COURSE_DIR}/教材/index.html',
                            creator_type='teacher', creator_teacher_id=teacher.id, is_public=True,
                            quiz_mode='inject', lesson_tree=json.dumps(tree, ensure_ascii=False),
                            file_permissions=json.dumps({'教材/index.html': {'show': False}}))
        db.session.add(resource)
        db.session.commit()
        rid = resource.id
        ids['resources'].append(rid)
        inject_quiz_collector(str(folder / '测验/forms.html'), rid, '测验/forms.html')
    server = make_server('127.0.0.1', 0, app, threaded=True)
    base = f'http://127.0.0.1:{server.server_port}'
    threading.Thread(target=server.serve_forever, daemon=True).start()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='msedge', headless=True)
        teacher_context = browser.new_context(viewport={'width': 1440, 'height': 1080})
        page = teacher_context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        teacher_login(page)
        page.goto(base + f'/study/lesson/{rid}?mode=classroom')
        page.locator('#chapterTree').get_by_text('嵌套网页', exact=True).click()
        frame = page.frame_locator('#linkFrame')
        frame.locator('#next').click()
        expect(frame.locator('h1')).to_have_text('子目录第二页')
        check('自定义课堂 HTML 子目录跳转和相对脚本',
              frame.locator('body').evaluate('() => window.relativeScriptLoaded === true'))
        frame.locator('#back').click()
        expect(frame.locator('h1')).to_contain_text('链接联测')
        frame.locator('#fragment').click()
        check('返回首页和同页锚点不产生 404', '链接联测' in frame.locator('h1').inner_text())
        page.screenshot(path=str(ARTIFACTS / 'classroom-links.png'))

        # 真正上传文件，再模拟最后一块响应未确认合并；前端应查询状态恢复。
        page.goto(base + '/teacher/resource-library/upload')
        altered = [False]
        def intercept(route):
            from urllib.parse import parse_qs
            if 'chunk_status?' in route.request.url:
                upload_ids.add(parse_qs(route.request.url.split('?', 1)[1])['upload_id'][0])
                route.continue_()
                return
            response = route.fetch()
            body = response.json()
            if body.get('is_complete') and not altered[0]:
                altered[0] = True
                route.fulfill(response=response, json={'success': True, 'is_complete': False})
            else:
                route.fulfill(response=response)
        page.route('**/admin/resources/chunk_*', intercept)
        page.locator('#title').fill(UPLOAD_TITLE)
        page.locator('#subjectId').select_option(str(ids['subjects'][0]))
        page.locator('#subfolder').fill('实验 子目录')
        page.locator('#quizNone').check()
        page.locator('#file').set_input_files([
            {'name': 'index.html', 'mimeType': 'text/html', 'buffer': b'<a href="next.html">Next</a>'},
            {'name': 'next.html', 'mimeType': 'text/html', 'buffer': b'<h1>UPLOAD NEXT PAGE</h1>'},
            {'name': 'empty.txt', 'mimeType': 'text/plain', 'buffer': b''},
        ])
        page.evaluate('CHUNK_SIZE = 16')
        page.locator('#uploadForm button[type=submit]').click()
        page.locator('#settingsPanel').wait_for(state='visible')
        check('分块未完成响应可恢复且空文件真正上传', altered[0] and
              page.locator('#fileTableBody tr').count() == 3 and
              page.evaluate('uploadedFiles.every(f => typeof f === "string" && f.startsWith("实验_子目录/"))'))
        page.screenshot(path=str(ARTIFACTS / 'upload-settings.png'))
        with page.expect_response(lambda response: '/save_with_settings' in response.url) as saved:
            page.locator('#saveResourceBtn').click()
        check('教师上传资源可保存', saved.value.status == 200 and saved.value.json().get('success'))
        page.wait_for_url('**/teacher/*')
        with app.app_context():
            uploaded = Resource.query.filter_by(title=UPLOAD_TITLE).one()
            uploaded_id = uploaded.id
        page.goto(base + f'/study/lesson/{uploaded_id}?mode=classroom')
        page.locator('#chapterTree').get_by_text('index', exact=True).click()
        upload_frame = page.frame_locator('#linkFrame')
        upload_frame.get_by_text('Next', exact=True).click()
        expect(upload_frame.locator('h1')).to_have_text('UPLOAD NEXT PAGE')
        check('未编排资源的默认课堂链接不重复拼接路径',
              upload_frame.locator('h1').inner_text() == 'UPLOAD NEXT PAGE')

        for number, sid in enumerate(ids['students']):
            context = browser.new_context()
            student_page = context.new_page()
            student_page.on('pageerror', lambda error: errors.append(str(error)))
            student_page.goto(base + '/')
            student_page.locator('input[name=student_number]').fill(f'{NAME}_s{number}')
            student_page.locator('#studentPassword').fill(PASSWORD)
            student_page.locator('#tab-password button[type=submit]').click()
            student_page.wait_for_url('**/study*')
            student_page.goto(base + f'/study/lesson/{rid}')
            student_page.locator('#chapterTree').get_by_text('Python 测验', exact=True).click()
            quiz = student_page.frame_locator('#linkFrame')
            quiz.locator('#addQuestion').click()
            quiz.locator('#q1a' if number == 1 else '#q1b').check()
            quiz.locator('#q2a').check()
            quiz.locator('#q2c').check()
            if number == 1:
                quiz.locator('#q2a').uncheck()
            quiz.locator('#q3').fill('requests.get' if number == 0 else ('requests.post' if number == 1 else ''))
            quiz.locator('#q4a' if number == 2 else '#q4c').check()
            quiz.locator('#q5a' if number == 1 else '#q5b').click()
            with student_page.expect_response(lambda response: '/api/resource_quiz/submit' in response.url and response.status == 200):
                quiz.locator('#finish').click()
            with app.app_context():
                result = ResourceQuizResult.query.filter_by(resource_id=rid, student_id=sid).one()
                details = json.loads(result.question_details)
                answers = json.loads(result.answers)
                check(f'学生 {number + 1}：原生/动态/按钮题保留完整题干与选项',
                      len(details) == 5 and all(question['prompt'] for question in details) and
                      'student_name' not in answers and 'password' not in answers)
            context.close()

        page.goto(base + f'/admin/resources/quiz_results/{rid}')
        page.locator('#quizQuestionTableBody tr').nth(4).wait_for()
        data = teacher_context.request.get(base + f'/admin/resources/quiz_analysis/{rid}').json()['data']
        questions = {question['id']: question for question in data['questions']}
        check('统计人数与逐题正确率准确', data['student_count'] == 3 and
              questions['q1']['correct_rate'] == 66.7 and questions['q3']['correct_rate'] == 33.3)
        check('多选取消勾选不残留，选项人数不重复',
              [option['selected_count'] for option in questions['q2']['options']] == [2, 0, 3])
        check('图表实际绘制', page.evaluate('Chart.getChart("quizAccuracyChart").data.datasets[0].data.length === 5'))
        page.locator('#quizAnalysisQuestion').select_option(questions['q2']['key'])
        page.locator('#quizAnalysis').screenshot(path=str(ARTIFACTS / 'quiz-analysis-light.png'))
        page.evaluate('document.documentElement.setAttribute("data-theme", "dark")')
        page.locator('#quizAnalysisTexture').check()
        page.locator('#quizAnalysis').screenshot(path=str(ARTIFACTS / 'quiz-analysis-dark.png'))
        page.evaluate('document.documentElement.setAttribute("data-theme", "light")')
        page.locator('button[onclick^="showDetail"]').first.click()
        page.locator('#detailBody .quiz-question-detail').first.wait_for()
        check('答题详情展示完整选项与判定', 'Python 源代码' in page.locator('#detailBody').inner_text())
        page.goto(base + '/study?mode=classroom')
        lab = page.locator('.resource-card[data-title="铜匠实验室"]')
        check('铜匠实验室只显示一个入口并归入仿真实验',
              lab.count() == 1 and '仿真实验' in lab.locator('xpath=ancestor::div[contains(@class,"subject-group")]').inner_text())
        check('全流程无页面 JavaScript 异常', not errors)
        browser.close()
finally:
    if server:
        server.shutdown()
        server.server_close()
    cleanup()

print(f'资源功能浏览器联测：{len(checks)} 项通过；截图目录：{ARTIFACTS}')
