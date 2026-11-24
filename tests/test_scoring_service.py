"""评分服务回归测试

重点覆盖：题目标准答案缺失（None/空）时不得抛异常，
否则单道脏数据题目会导致整份试卷 submit_exam 崩溃、学生答案丢失。
"""
from types import SimpleNamespace as NS

from app.services.scoring_service import (
    score_single, score_judge, score_multiple, auto_score,
)


def _q(qtype, answer, score=5):
    return NS(question_type=qtype, answer=answer, score=score)


def test_missing_answer_does_not_crash():
    """标准答案为 None/空时返回 0 分而非抛异常。"""
    for qtype, scorer in (
        ('single', score_single),
        ('judge', score_judge),
        ('multiple', score_multiple),
    ):
        assert scorer(_q(qtype, None), 'A') == 0
        assert scorer(_q(qtype, ''), 'A') == 0
        assert scorer(_q(qtype, '   '), 'A') == 0
        # 经由主入口分发同样不崩溃
        assert auto_score(_q(qtype, None), 'A') == 0


def test_non_string_user_answer_is_tolerated():
    """学生答案为非字符串（如数字）时也不崩溃。"""
    assert score_single(_q('single', '1'), 1) == 5
    assert score_multiple(_q('multiple', 'A'), 1) == 0


def test_single_choice_grading():
    q = _q('single', 'B')
    assert score_single(q, 'B') == 5
    assert score_single(q, ' B ') == 5
    assert score_single(q, 'A') == 0


def test_judge_grading():
    q = _q('judge', 'true')
    assert score_judge(q, 'true') == 5
    assert score_judge(q, '对') == 5
    assert score_judge(q, 'false') == 0


def test_multiple_choice_requires_exact_set():
    q = _q('multiple', 'A|C')
    assert score_multiple(q, 'A|C') == 5
    assert score_multiple(q, 'C|A') == 5  # 顺序无关
    assert score_multiple(q, 'A') == 0     # 少选不得分
    assert score_multiple(q, 'A|B|C') == 0  # 多选不得分


def test_multiple_answer_encoding_compatibility():
    """多种编码（无分隔符/|分隔/逗号分隔/乱序/大小写）应判为同一答案。"""
    q = _q('multiple', 'ABD', score=5)
    # 标准答案 'ABD' 与各种学生编码
    assert score_multiple(q, 'ABD') == 5
    assert score_multiple(q, 'A|B|D') == 5
    assert score_multiple(q, 'D|B|A') == 5
    assert score_multiple(q, 'A,B,D') == 5
    assert score_multiple(q, 'abd') == 5
    # 错误答案
    assert score_multiple(q, 'AB') == 0
    assert score_multiple(q, 'ABCD') == 0
    # SPA 管理端创建的带 | 标准答案，Jinja 学生端无分隔符提交
    q2 = _q('multiple', 'A|B|D', score=5)
    assert score_multiple(q2, 'ABD') == 5
    assert score_multiple(q2, 'A|B|D') == 5
    # 数字选项（如 1|2|3）
    q3 = _q('multiple', '1|2|3', score=5)
    assert score_multiple(q3, '123') == 5
    assert score_multiple(q3, '3|2|1') == 5
    assert score_multiple(q3, '12') == 0


# ── python_fill 整数除法消歧回归测试（修复：'python' → 'python_fill' 死代码）──

def _py_fill_q(answers_json, score=10):
    """构造 python_fill 题目对象（与真实模型属性对齐）。"""
    import json as _json

    class _PyFillQ:
        question_type = 'python_fill'

        def __init__(self, answers, score):
            self.python_answers = _json.dumps(answers)
            self.score = score

        @property
        def python_answers_dict(self):
            try:
                return _json.loads(self.python_answers)
            except Exception:
                return {}

    return _PyFillQ(answers_json, score)


def test_python_fill_integer_division_answer_scores():
    """标准答案含整数除法表达式（a // b）时，学生照写应得分。

    回归：旧实现判断 question_type == 'python'（实际为 'python_fill'），
    导致 // 表达式被错误拆分，答对的学生被判 0 分。
    """
    q = _py_fill_q({'blank1': 'a // b'})
    assert auto_score(q, {'blank1': 'a // b'}) == 10
    # 空格差异应容忍（strip 后命中）
    assert auto_score(q, {'blank1': '  a // b  '}) == 10


def test_python_fill_integer_division_multiple_blanks():
    """多空 + 管道多组 + 整数除法混合场景。"""
    q = _py_fill_q({'blank1': 'a // b | c // d', 'blank2': 'x // y'})
    assert auto_score(q, {'blank1': 'a // b', 'blank2': 'x // y'}) == 10
    assert auto_score(q, {'blank1': 'c // d', 'blank2': 'x // y'}) == 10


def test_python_fill_normal_answers_still_work():
    """普通答案（无整数除法）不受影响。"""
    q = _py_fill_q({'blank1': 'print(1)'})
    assert auto_score(q, {'blank1': 'print(1)'}) == 10
    assert auto_score(q, {'blank1': 'wrong'}) == 0


def _py_fill_q_scores(answers_json, blank_scores, score=10):
    """带逐空分值（blank_scores）的 python_fill 题目（批量导入约定）。"""
    q = _py_fill_q(answers_json, score)
    q.blank_scores_list = blank_scores
    return q


def test_python_fill_blank_scores_per_blank():
    """逐空分值判分：3 空 3/3/4 —— 全对 10、对 2 空 6、仅空 3 得 4。"""
    q = _py_fill_q_scores({'1': '6', '2': 'money', '3': 'money'}, [3, 3, 4])
    assert auto_score(q, {'1': '6', '2': 'money', '3': 'money'}) == 10
    assert auto_score(q, {'1': '6', '2': 'money', '3': 'wrong'}) == 6
    assert auto_score(q, {'1': 'w1', '2': 'w2', '3': 'money'}) == 4
    assert auto_score(q, {'1': 'w1', '2': 'w2', '3': 'w3'}) == 0


def test_python_fill_blank_scores_fallback_average():
    """无 blank_scores 的存量题回退均分（10/3 每空，行为不变）。"""
    q = _py_fill_q({'1': '6', '2': 'money', '3': 'money'})
    assert auto_score(q, {'1': '6', '2': 'wrong', '3': 'wrong'}) == round(10 / 3, 2)
    # 逐空分值存在但只对部分空判对时，未判对空不计分
    q2 = _py_fill_q_scores({'1': 'a', '2': 'b'}, [5, 5])
    assert auto_score(q2, {'1': 'a'}) == 5


def test_python_fill_empty_std_answer_gets_no_credit():
    """回归：空标准答案（导入数据缺失被补空串）时，学生留空不得分。

    此前 '' 匹配 '' 判对，学生留空/原样提交模板即可在该空白得满分。
    """
    q = _py_fill_q_scores({'1': '6', '2': '', '3': ''}, [3, 3, 4])
    # 学生只答对空1，空2/3留空 → 仅空1 的 3 分
    assert auto_score(q, {'1': '6', '2': '', '3': ''}) == 3
    # 全部留空 → 0 分（此前为 7 分）
    assert auto_score(q, {'1': '', '2': '', '3': ''}) == 0
    # 空标准答案但学生填了内容 → 同样不计分（无法判对）
    assert auto_score(q, {'1': '6', '2': 'anything', '3': ''}) == 3


def test_python_fill_non_string_answer_value_tolerated():
    """回归：答案 JSON 中某空为数字（前端序列化差异）时不崩溃、其余空正常判分。"""
    q = _py_fill_q_scores({'1': '6', '2': 'money'}, [5, 5])
    assert auto_score(q, {'1': 6, '2': 'money'}) == 10
    assert auto_score(q, {'1': 6, '2': 'wrong'}) == 5
