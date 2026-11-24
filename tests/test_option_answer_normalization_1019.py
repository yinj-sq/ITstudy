# -*- coding: utf-8 -*-
"""选项 ABCD 与多选答案不同写法的识别回归（2026-10-19）。

真实使用中 Excel/手工录入常见：全角字母与标点、中文冒号/括号、
纯字母 ABCD、空格/逗号分隔标签；单选题标准答案也可能带尾部分隔符。
本组用例锁定 normalize_options / _normalize_choice_letter /
_normalize_multi_answer 的归一结果，避免导入后显示重复标签或判分失分。
"""
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import text

from app import create_app
from app.extensions import db
from app.models import Exam, Question, normalize_options
from app.services.scoring_service import (
    _normalize_choice_letter, _normalize_multi_answer, score_multiple,
    score_single,
)


@pytest.mark.parametrize('raw, expected', [
    # 常见分隔符
    ('A.选项1|B.选项2', 'A.选项1|B.选项2'),
    ('A、选项1|B、选项2', 'A.选项1|B.选项2'),
    ('A)选项1|B)选项2', 'A.选项1|B.选项2'),
    ('A）选项1|B）选项2', 'A.选项1|B.选项2'),
    ('A:选项1|B:选项2', 'A.选项1|B.选项2'),
    ('A：选项1|B：选项2', 'A.选项1|B.选项2'),
    ('A-选项1|B-选项2', 'A.选项1|B.选项2'),
    ('A 选项1|B 选项2', 'A.选项1|B.选项2'),
    ('A,选项1|B,选项2', 'A.选项1|B.选项2'),
    ('A，选项1|B，选项2', 'A.选项1|B.选项2'),
    ('A;选项1|B;选项2', 'A.选项1|B.选项2'),
    ('A。选项1|B。选项2', 'A.选项1|B.选项2'),
    ('a.选项1|b.选项2', 'A.选项1|B.选项2'),
    # 全角字母/标点（中文输入法）
    ('Ａ．选项1|Ｂ．选项2', 'A.选项1|B.选项2'),
    ('Ａ、选项1|Ｂ、选项2', 'A.选项1|B.选项2'),
    ('Ａ：选项1|Ｂ：选项2', 'A.选项1|B.选项2'),
    # 括号包裹
    ('（A）选项1|（B）选项2', 'A.选项1|B.选项2'),
    ('(A)选项1|(B)选项2', 'A.选项1|B.选项2'),
    # 纯字母标签：竖线/空格/逗号/顿号
    ('A|B|C|D', 'A.|B.|C.|D.'),
    ('A B C D', 'A.|B.|C.|D.'),
    ('A,B,C,D', 'A.|B.|C.|D.'),
    ('A、B、C、D', 'A.|B.|C.|D.'),
    ('a b c d', 'A.|B.|C.|D.'),
    # 无前缀自动补标签；乱序排序；重复标签去重
    ('选项1|选项2', 'A.选项1|B.选项2'),
    ('B.选项2|A.选项1', 'A.选项1|B.选项2'),
    ('A.选项1|A.重复', 'A.选项1'),
    # 重复前缀只剥离同字母层，内容中其他字母前缀不被吞掉
    ('A.A.选项1|B.B.选项2', 'A.选项1|B.选项2'),
    ('A.B.C|D.E.F', 'A.B.C|D.E.F'),
])
def test_option_writings_are_normalized(raw, expected):
    assert normalize_options(raw) == expected


def test_no_duplicate_option_labels_after_normalization():
    for raw in ('Ａ．甲|Ｂ．乙', '（A）甲|（B）乙', 'A B', 'A,B'):
        result = normalize_options(raw)
        labels = [part.split('.', 1)[0] for part in result.split('|')]
        assert len(labels) == len(set(labels)), result
        assert all(label in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' for label in labels)


@pytest.mark.parametrize('answer', [
    'A', 'a', 'Ａ', ' A ', 'A.', 'A．', 'A、', '（A）', '(A)', 'A）',
    'A。', '[A]', '【A】',
])
def test_single_choice_answer_writings(answer):
    assert _normalize_choice_letter(answer) == 'A'


def test_single_choice_trailing_separator_full_score():
    q = NS(question_type='single', answer='Ａ．', score=5)
    assert score_single(q, 'A') == 5
    q2 = NS(question_type='single', answer='（A）', score=5)
    assert score_single(q2, 'a') == 5


def test_single_choice_punctuation_answer_not_treated_as_blank():
    """纯标点脏标准答案归一后不得变空串，否则空作答会被判满分。"""
    assert _normalize_choice_letter('...') == '...'
    q = NS(question_type='single', answer='...', score=5)
    assert score_single(q, '') == 0


@pytest.mark.parametrize('raw', [
    'ABD', 'A|B|D', 'A,B,D', 'A，B，D', 'A、B、D', 'A B D', 'A.B.D',
    'A/B/D', 'A-B-D', 'A；B；D', 'A和B和D', 'a,b,d', 'ＡＢＤ', 'AABBDD',
    '[A,B,D]', 'A.|B.|D.',
])
def test_multi_choice_answer_writings(raw):
    assert _normalize_multi_answer(raw) == 'ABD'


@pytest.mark.parametrize('std', ['ABD', 'A|B|D', 'A、B、D', 'A.B.D', 'ＡＢＤ'])
@pytest.mark.parametrize('user', ['ABD', 'A|B|D', 'a,b,d', 'A、B、D', 'ＡＢＤ', 'DBA'])
def test_multi_choice_variants_full_score(std, user):
    q = NS(question_type='multiple', answer=std, score=5)
    assert score_multiple(q, user) == 5


def test_multi_choice_wrong_sets_still_zero():
    q = NS(question_type='multiple', answer='A、B、D', score=5)
    assert score_multiple(q, 'AB') == 0
    assert score_multiple(q, 'ABCD') == 0
    assert score_multiple(q, '') == 0


def test_excel_import_recognizes_option_and_answer_writings():
    """真实走 /admin/questions/import_excel：选项与单选答案混用不同写法。"""
    import io

    import openpyxl

    app = create_app()
    exam_name = '选项归一测试卷'
    prefix = '选项归一测试题'
    with app.app_context():
        conn = db.session.connection()
        conn.execute(text("DELETE FROM exam_question WHERE exam_id IN "
                          "(SELECT id FROM exam WHERE name=:n)"), {'n': exam_name})
        conn.execute(text("DELETE FROM question WHERE content LIKE :p"),
                     {'p': prefix + '%'})
        conn.execute(text("DELETE FROM exam WHERE name=:n"), {'n': exam_name})
        conn.execute(text("DELETE FROM log WHERE action='批量导入题目' "
                          "AND detail LIKE :d"), {'d': f'试卷: {exam_name}%'})
        exam = Exam(name=exam_name, is_active=True, duration=30)
        db.session.add(exam)
        db.session.commit()
        exam_id = exam.id

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(['题目内容', '选项', '答案', '分值'])
    ws.append([prefix + '全角', 'Ａ．甲|Ｂ．乙', 'Ａ．', 2])
    ws.append([prefix + '纯字母', 'A B C D', 'A', 2])
    ws.append([prefix + '括号', '（A）甲|（B）乙', '（A）', 2])
    ws.append([prefix + '顿号小写', 'A、甲|B、乙', 'b', 2])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    client = app.test_client()
    with client.session_transaction() as s:
        s.clear()
        s['is_admin'] = True
        s['csrf_token'] = 't'
    resp = client.post(
        '/admin/questions/import_excel',
        data={'exam_id': str(exam_id),
              'excel_file': (buf, 'option_variants.xlsx')},
        headers={'X-CSRFToken': 't'},
        follow_redirects=True,
    )
    assert resp.status_code == 200

    try:
        with app.app_context():
            db.session.expire_all()
            questions = {
                q.content: q for q in Question.query.filter(
                    Question.content.like(prefix + '%')).all()
            }
            assert len(questions) == 4
            assert questions[prefix + '全角'].options == 'A.甲|B.乙'
            assert questions[prefix + '纯字母'].options == 'A.|B.|C.|D.'
            assert questions[prefix + '括号'].options == 'A.甲|B.乙'
            assert questions[prefix + '顿号小写'].options == 'A.甲|B.乙'
            assert score_single(questions[prefix + '全角'], 'A') == 2
            assert score_single(questions[prefix + '纯字母'], 'a') == 2
            assert score_single(questions[prefix + '括号'], 'A') == 2
            assert score_single(questions[prefix + '顿号小写'], 'B') == 2
    finally:
        with app.app_context():
            conn = db.session.connection()
            conn.execute(text("DELETE FROM exam_question WHERE exam_id=:e"),
                         {'e': exam_id})
            conn.execute(text("DELETE FROM question WHERE content LIKE :p"),
                         {'p': prefix + '%'})
            conn.execute(text("DELETE FROM exam WHERE id=:e"), {'e': exam_id})
            conn.execute(text("DELETE FROM log WHERE action='批量导入题目' "
                              "AND detail LIKE :d"),
                         {'d': f'试卷: {exam_name}%'})
            db.session.commit()
