# -*- coding: utf-8 -*-
"""批量导入 Python 填空题 回归测试

覆盖：
- 模式 A（文本识别）：questions_text/answers_text + zip → 识别建卷建题、
  blank_scores 精确判分（3 空 3/3/4 → 全对 10 / 对 2 空 6 / 仅空 3 得 4）
- 重复导入卷名避让（重名卷自动追加（2））
- 模式 B（预览工具校对结果）：python_fill_review.json（含 split 配置）+ zip
- 导入页面 GET 路由；表单显式覆盖 split 配置生效
- zip 文件缺失的题跳过并进入报告
"""
import io
import json
import os
import zipfile

import pytest
from sqlalchemy import text

from app import create_app
from app.extensions import db
from app.models import Exam, Question, PythonFile
from app.services.scoring_service import score_python_file

_CSRF = 't'

EXAM_PREFIX_LIKE = "name LIKE 'Python填空题%' OR name LIKE '覆盖前缀%'"


@pytest.fixture(scope='module')
def app():
    app = create_app()
    yield app
    with app.app_context():
        _clean_exams(app)


def _clean_exams(app):
    """纯 SQL 清理测试卷（ORM bulk delete 与已加载对象冲突会 StaleDataError）"""
    with app.app_context():
        conn = db.session.connection()
        rows = conn.execute(text(
            f'SELECT id FROM exam WHERE {EXAM_PREFIX_LIKE}')).fetchall()
        for (eid,) in rows:
            qids = [r[0] for r in conn.execute(
                text('SELECT id FROM question WHERE exam_id=:e'), {'e': eid})]
            for qid in qids:
                for p in PythonFile.query.filter_by(question_id=qid).all():
                    fp = os.path.join('static', 'uploads', p.file_path)
                    if os.path.exists(fp):
                        os.remove(fp)
                conn.execute(text(
                    'DELETE FROM python_file WHERE question_id=:q'), {'q': qid})
            conn.execute(text(
                'DELETE FROM exam_question WHERE exam_id=:e'), {'e': eid})
            conn.execute(text(
                'DELETE FROM question WHERE exam_id=:e'), {'e': eid})
            conn.execute(text('DELETE FROM exam WHERE id=:e'), {'e': eid})
        # 导入会写操作日志（log 不在上面的外键链上，必须按名字单独清，
        # 否则每跑一次都留下若干"已删试卷"的悬空审计行）
        conn.execute(text(
            "DELETE FROM log WHERE detail LIKE '%Python填空题%' "
            "OR detail LIKE '%覆盖前缀%'"))
        db.session.commit()


def _login(client):
    with client.session_transaction() as s:
        s.clear()
        s['is_admin'] = True
        s['csrf_token'] = _CSRF


def _make_zip(files):
    """files: {zip_path: content} → BytesIO（Flask 上传后流被关闭，须每次新建）"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    buf.seek(0)
    return buf


Q_TEXT = ('【第1题】打开"91"文件夹中的文件"a4.py"，补充代码。\n'
          'rate = 0.0125\nfor year in range(1,①):\n    money = ②*(1+rate)\n'
          '【第2题】打开"92"文件夹中的文件"a5.py"，补充代码。\n'
          'while ①:\n    money = ②*(1+rate)\n    ③')
A_TEXT = '91\t\t6\tmoney\tmoney\n92\t\tmoney<60000\nmoney\tmoney\tyear=year+1'
ZIP_FILES = {'91/a4.py': 'rate = 0.0125\nfor year in range(1,①):\n'
                         '    money = ②*(1+rate)\nprint(③)',
             '92/a5.py': 'while ①:\n    money = ②*(1+rate)\n    ③'}


def test_text_mode_import_and_precise_scoring(app):
    """模式 A：文本识别导入 + blank_scores 精确判分（3 空 3/3/4）"""
    _clean_exams(app)
    c = app.test_client()
    _login(c)
    r = c.post('/admin/tools/import-python-fill/import',
               data={'questions_text': Q_TEXT, 'answers_text': A_TEXT,
                     'per_volume': '10', 'duration': '40',
                     'prefix': 'Python填空题',
                     'zip_file': (_make_zip(ZIP_FILES), 'q.zip')},
               headers={'X-CSRFToken': _CSRF})
    assert r.get_json()['success'], r.get_json()

    with app.app_context():
        exam = Exam.query.filter(Exam.name.like('Python填空题%')).first()
        assert exam and exam.duration == 40 and len(exam.questions) == 2
        q1 = exam.questions[0]
        assert json.loads(q1.blank_scores) == [3, 3, 4]
        ans = json.loads(q1.python_answers)
        assert ans['1'] == '6' and ans['3'] == 'money'
        pf = PythonFile.query.filter_by(question_id=q1.id).first()
        assert pf.file_name == 'a4.py' and '_' in pf.file_path.split('/')[-1]

        upload = os.path.join('static', 'uploads')
        q1_content = pf.read_content(upload)
        full_ok = q1_content.replace('①', '6').replace('②', 'money').replace('③', 'money')
        assert abs(score_python_file(q1, full_ok) - 10.0) < 0.01
        two_ok = q1_content.replace('①', '6').replace('②', 'money').replace('③', 'wrong')
        assert abs(score_python_file(q1, two_ok) - 6.0) < 0.01
        only3 = q1_content.replace('①', 'w1').replace('②', 'w2').replace('③', 'money')
        assert abs(score_python_file(q1, only3) - 4.0) < 0.01


def test_duplicate_import_avoids_exam_names(app):
    """重复导入同批题：新卷名自动避让为「…（2）」"""
    _clean_exams(app)
    c = app.test_client()
    _login(c)
    for _ in range(2):
        r = c.post('/admin/tools/import-python-fill/import',
                   data={'questions_text': Q_TEXT, 'answers_text': A_TEXT,
                         'per_volume': '10', 'duration': '40',
                         'prefix': 'Python填空题',
                         'zip_file': (_make_zip(ZIP_FILES), 'q.zip')},
                   headers={'X-CSRFToken': _CSRF})
        assert r.get_json()['success'], r.get_json()
    with app.app_context():
        exams = Exam.query.filter(
            Exam.name.like('Python填空题%')).order_by(Exam.id).all()
        assert len(exams) == 2
        assert exams[1].name.endswith('（2）')


def test_review_mode_import(app):
    """模式 B：预览工具导出的 python_fill_review.json + zip"""
    _clean_exams(app)
    c = app.test_client()
    _login(c)
    review = {'split': {'per_volume': 1, 'duration': 40, 'prefix': 'Python填空题'},
              'questions': [{'num': 3,
                             'content': '【第3题】测试 review 模式题',
                             'folder': '91', 'files': ['a4.py'],
                             'blank_count': 3, 'blank_scores': [3, 3, 4],
                             'answers': ['6', 'money', 'money']}]}
    r = c.post('/admin/tools/import-python-fill/import',
               data={'review_json': (io.BytesIO(
                   json.dumps(review).encode('utf-8')), 'r.json'),
                     'zip_file': (_make_zip(ZIP_FILES), 'q.zip')},
               headers={'X-CSRFToken': _CSRF})
    d = r.get_json()
    assert d['success'] and d['report']['imported'] == 1
    assert len(d['report']['exams']) == 1


def test_page_and_split_override(app):
    """导入页面 GET + 表单显式覆盖 review.split 配置"""
    _clean_exams(app)
    c = app.test_client()
    _login(c)
    r = c.get('/admin/tools/import-python-fill')
    assert r.status_code == 200 and '开始导入' in r.get_data(as_text=True)

    review = {'split': {'per_volume': 5, 'duration': 30, 'prefix': '测验'},
              'questions': [{'num': 1, 'content': '【第1题】补全循环',
                             'folder': '91', 'files': ['a4.py'],
                             'blank_count': 2, 'blank_scores': [5, 5],
                             'answers': ['10', 'i']}]}
    r2 = c.post('/admin/tools/import-python-fill/import',
                data={'review_json': (io.BytesIO(
                    json.dumps(review).encode('utf-8')), 'r.json'),
                      'zip_file': (_make_zip(ZIP_FILES), 'q.zip'),
                      'per_volume': '1', 'duration': '25',
                      'prefix': '覆盖前缀'},
                headers={'X-CSRFToken': _CSRF})
    d = r2.get_json()
    assert d['success'] and d['report']['exams'] == ['覆盖前缀 第1卷']
    with app.app_context():
        exam = Exam.query.filter_by(name='覆盖前缀 第1卷').first()
        assert exam and exam.duration == 25
        q = Question.query.filter_by(exam_id=exam.id).first()
        assert q.score == 10 and json.loads(q.blank_scores) == [5, 5]
        assert json.loads(q.python_answers) == {'1': '10', '2': 'i'}


def test_skipped_when_zip_file_missing(app):
    """zip 中找不到题目文件 → 该题跳过并进入报告（其余照常导入）"""
    _clean_exams(app)
    c = app.test_client()
    _login(c)
    review = {'split': {'per_volume': 10, 'duration': 40, 'prefix': 'Python填空题'},
              'questions': [
                  {'num': 1, 'content': '【第1题】有文件', 'folder': '91',
                   'files': ['a4.py'], 'blank_count': 2,
                   'blank_scores': [5, 5], 'answers': ['10', 'i']},
                  {'num': 2, 'content': '【第2题】缺文件', 'folder': '99',
                   'files': ['missing.py'], 'blank_count': 2,
                   'blank_scores': [5, 5], 'answers': ['10', 'i']}]}
    r = c.post('/admin/tools/import-python-fill/import',
               data={'review_json': (io.BytesIO(
                   json.dumps(review).encode('utf-8')), 'r.json'),
                     'zip_file': (_make_zip(ZIP_FILES), 'q.zip')},
               headers={'X-CSRFToken': _CSRF})
    d = r.get_json()
    assert d['success'] and d['report']['imported'] == 1
    assert len(d['report']['skipped']) == 1
    assert d['report']['skipped'][0]['num'] == 2
    assert '未找到文件' in d['report']['skipped'][0]['reason']


def test_skip_when_answers_empty(app):
    """回归：答案解析为空 → 跳过并报告，防止空标准答案+留空自动得分"""
    _clean_exams(app)
    c = app.test_client()
    _login(c)
    review = {'split': {'per_volume': 10, 'duration': 40, 'prefix': 'Python填空题'},
              'questions': [
                  {'num': 1, 'content': '【第1题】有答案', 'folder': '91',
                   'files': ['a4.py'], 'blank_count': 2,
                   'blank_scores': [5, 5], 'answers': ['10', 'i']},
                  {'num': 2, 'content': '【第2题】无答案', 'folder': '91',
                   'files': ['a4.py'], 'blank_count': 2,
                   'blank_scores': [5, 5], 'answers': []}]}
    r = c.post('/admin/tools/import-python-fill/import',
               data={'review_json': (io.BytesIO(
                   json.dumps(review).encode('utf-8')), 'r.json'),
                     'zip_file': (_make_zip(ZIP_FILES), 'q.zip')},
               headers={'X-CSRFToken': _CSRF})
    d = r.get_json()
    assert d['success'] and d['report']['imported'] == 1
    assert len(d['report']['skipped']) == 1
    assert d['report']['skipped'][0]['num'] == 2
    assert '答案缺失' in d['report']['skipped'][0]['reason']


def test_skip_when_answers_columns_exceed_blanks(app):
    """回归：答案列多于空数 → 整题跳过（此前截断导入且报告语义混乱）"""
    _clean_exams(app)
    c = app.test_client()
    _login(c)
    review = {'split': {'per_volume': 10, 'duration': 40, 'prefix': 'Python填空题'},
              'questions': [
                  {'num': 1, 'content': '【第1题】列多于空', 'folder': '91',
                   'files': ['a4.py'], 'blank_count': 2,
                   'blank_scores': [5, 5], 'answers': ['10', 'i', 'extra']}]}
    r = c.post('/admin/tools/import-python-fill/import',
               data={'review_json': (io.BytesIO(
                   json.dumps(review).encode('utf-8')), 'r.json'),
                     'zip_file': (_make_zip(ZIP_FILES), 'q.zip')},
               headers={'X-CSRFToken': _CSRF})
    d = r.get_json()
    # 全部被跳过 → 无题可导 → 明确失败而非静默建空卷
    assert not d['success'] and d['report']['imported'] == 0
    assert d['report']['skipped'][0]['num'] == 1
    assert '多于空数' in d['report']['skipped'][0]['reason']


def test_no_empty_exam_when_leading_question_skipped(app):
    """回归：前面的题被跳过时不得创建空卷（此前按原始索引分卷会产生 0 题卷）"""
    _clean_exams(app)
    c = app.test_client()
    _login(c)
    review = {'split': {'per_volume': 1, 'duration': 40, 'prefix': 'Python填空题'},
              'questions': [
                  {'num': 1, 'content': '【第1题】缺文件', 'folder': '99',
                   'files': ['missing.py'], 'blank_count': 2,
                   'blank_scores': [5, 5], 'answers': ['10', 'i']},
                  {'num': 2, 'content': '【第2题】有文件', 'folder': '91',
                   'files': ['a4.py'], 'blank_count': 2,
                   'blank_scores': [5, 5], 'answers': ['10', 'i']}]}
    r = c.post('/admin/tools/import-python-fill/import',
               data={'review_json': (io.BytesIO(
                   json.dumps(review).encode('utf-8')), 'r.json'),
                     'zip_file': (_make_zip(ZIP_FILES), 'q.zip')},
               headers={'X-CSRFToken': _CSRF})
    d = r.get_json()
    assert d['success'] and d['report']['imported'] == 1
    assert len(d['report']['exams']) == 1
    with app.app_context():
        exams = Exam.query.filter(
            Exam.name.like('Python填空题%')).order_by(Exam.id).all()
        assert len(exams) == 1
        assert len(exams[0].questions) == 1