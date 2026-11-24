"""评分服务 — 将所有评分逻辑从路由中抽离为纯函数

包含:
- auto_score: 根据题目类型自动评分
- score_python_file: 评分 Python 填空题文件
- extract_answer_from_line: 从学生答案行提取实际填写内容
- delete_exam_result: 删除考试结果及其关联数据（统一入口，供多个蓝图调用）
- attempt_is_stale / has_active_attempt: 开考记录超时口径（在考锁定统一判定）
- decode_python_source: Python 答案文件解码（判分/SSR 回看/SPA 回看统一）
- bump_trend_cache / trend_cache_epoch: 趋势缓存换代失效
"""
import json
import re
import difflib
import logging
import time
from datetime import datetime

from flask import current_app

logger = logging.getLogger(__name__)


# ── 跨蓝图共享工具 ─────────────────────────────────────

# 交卷超时宽限（秒）：与 online_exam.submit_exam 的服务端时长强校验保持
# 同一口径。超过"时长+宽限"仍未交卷的开考记录视为超时残留——其提交通道
# 已被 submit_exam 关闭（403），不再构成"考试进行中"，组卷/删卷的在考
# 锁定按"存在未超时开考记录"判定，否则一个学生开考后弃考（关机/断网）
# 就会永久锁死该卷的组卷与删除（此前缺陷）。
EXAM_SUBMIT_GRACE_SECONDS = 300


def attempt_is_stale(exam, attempt):
    """开考记录是否已超时（超过 时长+宽限 仍未交卷）。

    无时长试卷没有超时口径（submit_exam 对其也不做时长校验），
    开考记录恒为"进行中"。
    """
    if not getattr(exam, 'duration', None):
        return False
    try:
        elapsed = time.time() - attempt.start_time.timestamp()
    except Exception:
        # 脏数据（start_time 为空等）按未超时处理，交由人工清理
        return False
    return elapsed > exam.duration * 60 + EXAM_SUBMIT_GRACE_SECONDS


def has_active_attempt(exam):
    """试卷是否存在"考试进行中"（未超时）的开考记录——组卷/删卷在考锁定的统一判定口径。

    SQL 侧按 cutoff 比较（此前全量加载 ExamAttempt 后 Python any() 判定，
    弃考记录累积时每次组卷/删卷全量实例化 ORM 对象）。与 attempt_is_stale
    同阈值：active = elapsed <= 时长*60 + 宽限，等价于
    start_time >= now - (时长*60 + 宽限)（本地 naive datetime 与
    .timestamp() 的本地时区解释一致，见 attempt_is_stale 时区注释）。
    无时长试卷没有超时口径，任何开考记录都算"进行中"。
    """
    from app.models import ExamAttempt
    from app.extensions import db
    if not getattr(exam, 'duration', None):
        return db.session.query(
            ExamAttempt.query.filter_by(exam_id=exam.id).exists()).scalar()
    cutoff = datetime.fromtimestamp(
        time.time() - (exam.duration * 60 + EXAM_SUBMIT_GRACE_SECONDS))
    return db.session.query(
        ExamAttempt.query.filter(
            ExamAttempt.exam_id == exam.id,
            ExamAttempt.start_time >= cutoff,
        ).exists()).scalar()


def _blank_score_map(question_obj, blank_ids):
    """逐空分值 {blank_id: 分值}；不可用时返回 {}，调用方回退均分。

    可用条件：每个空都能按 1 基序号取到数值，且合计等于题目分值。
    blank_scores 只在批量导入 / 子题分值设置时写入，编辑题目改分值或改空数
    不会同步——此前只看"数量够不够"就直接用，改成 20 分的题全对仍只得旧的
    10 分、从 3 空改成 2 空满分变成前两空之和。
    """
    scores = getattr(question_obj, 'blank_scores_list', None)
    if not isinstance(scores, list) or not blank_ids:
        return {}
    mapping = {}
    for bid in blank_ids:
        try:
            idx = int(bid) - 1
        except (TypeError, ValueError):
            return {}
        if not 0 <= idx < len(scores):
            return {}
        val = scores[idx]
        if isinstance(val, bool) or not isinstance(val, (int, float)) or val < 0:
            return {}
        mapping[bid] = val
    try:
        if abs(sum(mapping.values()) - float(question_obj.score or 0)) > 0.01:
            return {}
    except (TypeError, ValueError):
        return {}
    return mapping


def decode_python_source(raw):
    """Python 答案文件解码（唯一实现）：UTF-8 → GBK → 容错替换。

    Windows 编辑器保存的 .py 常为 GBK/GB2312。判分端此前已有 GBK 兜底，
    回看端（SSR/SPA）按 UTF-8 硬解会导致"判分正常、回看空白"的口径
    分叉——判分、SSR 结果页、SPA 结果页统一引用本函数。
    """
    if raw is None:
        return ''
    for enc in ('utf-8', 'gbk'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')


def trend_cache_epoch(exam_id):
    """趋势缓存的换代号：成绩写路径（提交/删除）bump 后 key 变化，
    旧键等待 TTL 自然过期。SimpleCache 不支持枚举删除，按过滤条件
    枚举 key 不可行，故用换代方案。"""
    from app.extensions import cache
    try:
        return cache.get(f'api:trend:epoch:{exam_id}') or 0
    except Exception:
        return 0


def bump_trend_cache(exam_id):
    """成绩写路径（提交/删除）后使趋势缓存立即失效（换代而非枚举删除）。"""
    from app.extensions import cache
    try:
        key = f'api:trend:epoch:{exam_id}'
        cache.set(key, (cache.get(key) or 0) + 1, timeout=86400)
    except Exception:
        # 缓存不可用时趋势查询本身也会降级，这里静默跳过
        pass

# ── 辅助函数 ─────────────────────────────────────────


def _is_valid_blank_id(blank_id, answers_dict):
    """检查填空 ID 是否有效"""
    return blank_id in answers_dict


# ── 题型评分函数 ──────────────────────────────────────

def _normalize_choice_letter(value):
    """单选题答案规范化：全角→半角、去空白/包裹括号/尾部分隔符、单字母大写。

    管理端可能把答案存成小写 'b'、全角 'Ｂ'、'A.'、'A、' 或 '（A）'
    （中文输入法常见的 Excel/手工录入写法），而学生端恒提交半角大写 'B'；
    此前逐字比较导致整题误判 0 分。仅在归一后是单个 ASCII 字母时才做
    大小写归并，其余（中文选项文本等）原样返回避免误判。
    """
    s = str(value).strip()
    s = ''.join(chr(ord(c) - 0xFEE0) if '\uFF01' <= c <= '\uFF5E' else c
                for c in s)
    s = s.strip()
    original = s
    # 包裹括号/书括号：（A）/(A)/[A]/【A】
    s = re.sub(r'^[(\[【]\s*', '', s)
    s = re.sub(r'\s*[)\]】]$', '', s)
    # 尾部标签分隔符：A. / A、 / A） / A。 等
    s = re.sub(r'[\s.:、,，;；)）\]】。]+$', '', s).strip()
    if len(s) == 1 and s.isascii() and s.isalpha():
        return s.upper()
    # 非单字母（中文答案、多字母/纯标点脏数据）保留原值，避免归一为空后
    # 与未作答（空串）误判相等而白送分。
    return original


def score_single(question_obj, user_answer):
    """单选题评分: 规范化后完全匹配得满分，否则0分"""
    # 题目未设置标准答案（脏数据）时无法自动判分，返回0分而非抛异常
    if not question_obj.answer or not question_obj.answer.strip():
        return 0
    return (question_obj.score
            if _normalize_choice_letter(user_answer)
            == _normalize_choice_letter(question_obj.answer) else 0)


# 判断题"正确"答案集合：判分与统计必须共用同一口径，
# 否则同一答案（如 '对'/'t'/'yes'）判分为对、统计为错（此前缺陷）。
JUDGE_TRUTHY = {'true', '1', 't', 'yes', 'y', '对', '正确'}


def score_judge(question_obj, user_answer):
    """判断题评分"""
    if not question_obj.answer or not question_obj.answer.strip():
        return 0
    user_bool = str(user_answer).lower() in JUDGE_TRUTHY
    std_bool = question_obj.answer.lower() in JUDGE_TRUTHY
    return question_obj.score if user_bool == std_bool else 0


def _normalize_multi_answer(value):
    """多选题答案规范化：全角→半角、提取字母数字字符、去重、排序。

    兼容两种管理端编码（Jinja 端存 'ABD'、SPA 端存 'A|B|D'）与
    两种学生端提交（'ABD' / 'A|B|D' / 'A, B, D'），统一归一为
    'ABD' 后比较，消除前后端编码不一致导致的误判 0 分。

    全角折叠与 `_normalize_choice_letter` 同口径：管理端用中文输入法录入
    'ＡＢＣ'（全角）时，此前 `[^A-Za-z0-9]` 会把全角字母整段剥除 → 标准答案
    归一为空串 → 任何作答都判 0 分（对全体学生静默失分）。
    """
    if value is None:
        return ''
    folded = ''.join(chr(ord(c) - 0xFEE0) if '！' <= c <= '～' else c
                     for c in str(value))
    chars = [c for c in re.sub(r'[^A-Za-z0-9]', '', folded).upper()]
    return ''.join(sorted(set(chars)))


def score_multiple(question_obj, user_answer):
    """多选题评分: 规范化后的选项集合完全相等才得分"""
    if not question_obj.answer or not question_obj.answer.strip():
        return 0
    std = _normalize_multi_answer(question_obj.answer)
    user = _normalize_multi_answer(user_answer)
    return question_obj.score if std and user == std else 0


def score_fill(question_obj, user_answer):
    """填空题评分: 支持多空('|'分隔)和可接受答案('//'分隔)
    若无答案设置且学生未作答则自动给0分，若有作答则需人工批改"""
    # 兜底：user_answer 可能为 None 或非字符串(前端把答案序列化为数字/数组等)，
    # 统一转为字符串，避免下方 .strip()/.split() 抛 AttributeError 导致整卷提交 500。
    user_answer = '' if user_answer is None else str(user_answer)
    if not question_obj.answer or not question_obj.answer.strip():
        # 开放式试题：学生未作答则自动批改为0分
        if not user_answer or not user_answer.strip():
            return 0
        return None  # 学生有作答，需人工批改

    user_answers = user_answer.strip().split('|')
    std_parts = question_obj.answer.split('|')

    # 防御：标准答案为空串时（脏数据）跳过评分，避免下方除以 0
    if not std_parts:
        return 0

    if len(user_answers) != len(std_parts):
        if len(user_answers) < len(std_parts):
            user_answers.extend([''] * (len(std_parts) - len(user_answers)))
        else:
            user_answers = user_answers[:len(std_parts)]

    blank_score_map = _blank_score_map(
        question_obj, [str(i + 1) for i in range(len(std_parts))])
    if blank_score_map:
        blank_scores = [blank_score_map[str(i + 1)] for i in range(len(std_parts))]
    else:
        per_blank = question_obj.score / len(std_parts)
        blank_scores = [per_blank] * len(std_parts)

    total = 0.0
    for i, std_part in enumerate(std_parts):
        user_part = user_answers[i] if i < len(user_answers) else ""
        if not user_part.strip():
            continue

        # 解析可接受答案（用//分隔，智能避免拆分整数除法）
        acceptable = _parse_acceptable_answers(std_part, question_obj)
        if user_part.strip() in acceptable:
            total += blank_scores[i]

    return round(total, 2)


def score_python_fill_online(question_obj, user_answer):
    """Python填空题在线答案评分"""
    try:
        answers_dict = question_obj.python_answers_dict
        if isinstance(user_answer, str):
            try:
                user_answers = json.loads(user_answer)
            except (ValueError, TypeError):
                # 非合法 JSON 的纯文本（如 API 客户端直接提交 'x'）：
                # 按第 1 空作答处理，而非抛异常被外层吞掉静默 0 分
                user_answers = {'1': user_answer}
        else:
            user_answers = user_answer

        if not answers_dict or not user_answers:
            return 0

        total_blanks = len(answers_dict)
        per_blank = question_obj.score / total_blanks
        # 逐空分值（与 score_python_file 同一约定）：校验通过时按空取分，否则均分
        blank_score_map = _blank_score_map(question_obj, list(answers_dict))
        total = 0.0

        for blank_id, std_ans in answers_dict.items():
            # 空标准答案防护：导入数据缺失/答案列为空的填空不得因学生留空
            # 而自动得分（此前 '' 匹配 '' 判对，白卷可拿满分）
            if std_ans is None or not str(std_ans).strip():
                continue
            if blank_id in user_answers:
                # 兜底：答案值可能为数字/布尔（前端序列化差异），统一转字符串，
                # 避免 .strip() 抛异常被外层吞掉导致整题 0 分
                user_ans = str(user_answers[blank_id]).strip()
                acceptable = _parse_acceptable_answers(std_ans, question_obj)
                if user_ans in acceptable:
                    total += blank_score_map.get(blank_id, per_blank)
                else:
                    # 宽松匹配：归一化内部空格（与文件判分 score_python_file
                    # 同口径）。标准答案含不规则空格（如 'a  +  b'）时，
                    # 在线判分此前只做精确匹配 → 学生提交 'a + b' 误判 0，
                    # 同一答案在线与文件两条判分路径结论不一致。
                    normalized_user = ' '.join(user_ans.split())
                    if normalized_user in (' '.join(a.split()) for a in acceptable):
                        total += blank_score_map.get(blank_id, per_blank)
        return round(total, 2)
    except Exception:
        return 0


def _parse_acceptable_answers(std_part, question_obj):
    """解析可接受答案列表，智能处理 // 分隔符

    与 score_python_file 的口径对齐：' // '（带空格）既可能是批量导入
    写入的"一空多解"分隔符（'money // m'），也可能是整数除法表达式
    （'a // b'）——两种解释都加入可接受集合（文件判分路径先按整除
    表达式匹配、再拆多解，同为双解释兼容）。否则只按整除保留原样时，
    在线作答填 'money' 判错而文件作答判对，同一题目两条路径结论不一致。
    """
    if '//' not in std_part:
        acceptable = [a.strip() for a in std_part.split('|')]
    else:
        acceptable = []
        for ans in std_part.split('|'):
            ans = ans.strip()
            # 原样保留整串：学生逐字复述教师设定的标准答案必须判对。
            # 此前 'https://www.python.org' 因按 '//' 拆成 ['https:',
            # 'www.python.org'] 而整串永不匹配——填对的学生得 0 分，
            # 只填 'www.python.org' 的反得满分（真实误判）。
            acceptable.append(ans)
            has_div = re.search(r'[a-zA-Z0-9_\)\]]\s*//\s*[a-zA-Z0-9_\(\[]', ans)
            is_py_fill = getattr(question_obj, 'question_type', '') == 'python_fill'
            if re.search(r'\s//\s', ans):
                # 带空格分隔符：按多解拆分（原串已在集合内，整除表达式
                # 无需再补）
                acceptable.extend(p.strip() for p in re.split(r'\s//\s', ans))
            elif has_div and is_py_fill:
                # Python 填空的整除表达式（'a // b'）不拆多解
                pass
            else:
                acceptable.extend(a.strip() for a in ans.split('//'))
    return acceptable


# ── 主评分入口 ───────────────────────────────────────

def auto_score(question_obj, user_answer):
    """自动评分入口，按题型分发"""
    q_type = question_obj.question_type

    # 填空题特殊处理：即使学生未作答，也需检查是否为开放式试题
    if q_type == 'fill':
        result = score_fill(question_obj, user_answer)
        if result is None:
            return None  # 开放式试题，透传
        return result

    # 简答题：未作答则自动批改为0分，有作答则需教师批改
    if q_type == 'short_answer':
        # str() 兜底：submit_exam 放行 int/bool 顶层值，直接 .strip() 会让交卷 500
        if user_answer is None or not str(user_answer).strip():
            return 0
        return None

    # 仅将"真正未作答"(None / 纯空白字符串)判为 0；其余值(如布尔 False、
    # 字符串 "0"/"false")交由各题型评分函数处理——它们内部均以 str() 兜底，
    # 不会因非字符串输入崩溃。避免判断题选"错误"被误判 0 分。
    if user_answer is None or (isinstance(user_answer, str) and not user_answer.strip()):
        return 0

    if q_type == 'single':
        return score_single(question_obj, user_answer)
    elif q_type == 'judge':
        return score_judge(question_obj, user_answer)
    elif q_type == 'multiple':
        return score_multiple(question_obj, user_answer)
    elif q_type == 'python_fill':
        return score_python_fill_online(question_obj, user_answer)
    return 0


# ── Python 文件评分 ────────────────────────────────────

def score_python_file(question, file_content, python_file=None):
    """评分 Python 填空题文件（权威实现）

    @param question: Question 对象
    @param file_content: 学生提交的文件内容（文本）
    @param python_file: 题目的参考文件（PythonFile 对象）。交卷判分是整班
        并发高峰，调用方（submit_exam）已按题**批量预取**参考文件，传入即可
        省掉每题一次按题反查；不传时下面自行查询，单题调用（测试/工具）不变
    @return: 得分

    说明：参考文件（含填空标记）作为题目模板，学生提交内容逐行对比，
    支持标准标记 (# YOUR ANSWER)、特殊标记 (①②③/[1][2][3]) 两种模式，
    并对 Python 整数除法 // 与答案分隔符 // 做消歧处理。
    """
    from app.models import PythonFile
    from app.utils import extract_possible_integer_division_expressions

    try:
        from flask import current_app
        upload_folder = current_app.config['UPLOAD_FOLDER']

        # 获取标准答案
        answers_dict = question.python_answers_dict
        if not answers_dict:
            logger.warning(f"Python填空题 ID:{question.id} 未设置答案")
            return 0

        # 获取题目参考文件（调用方未预取时自行查询）
        if python_file is None:
            python_file = PythonFile.query.filter_by(question_id=question.id).first()
        if not python_file:
            logger.warning(f"Python填空题 ID:{question.id} 未找到关联的Python文件")
            return 0

        # 学生答案为空直接 0 分
        if not file_content:
            logger.warning(f"Python填空题 ID:{question.id} 学生答案为空")
            return 0

        # 计算每空的分值：优先逐空分值（blank_scores，如 [3,3,4]），
        # 缺失/与题目分值对不上时回退均分（存量无 blank_scores 的题行为不变）
        correct_count = 0
        per_blank_score = question.score / len(answers_dict) if answers_dict else 0
        blank_score_map = _blank_score_map(question, list(answers_dict))

        # 加载题目参考文件（含标记）和学生答案
        reference_content = python_file.read_content(upload_folder)
        if not reference_content:
            logger.warning(f"Python填空题 ID:{question.id} 参考文件无法读取")
            return 0
        question_lines = reference_content.splitlines()
        student_lines = file_content.splitlines()

        # 支持多种填空标记方式
        marker_standard = "# YOUR ANSWER"  # 标准标记

        # 特殊标记列表（原始 + Unicode 码点 + ASCII 替代）
        markers_special = [
            "①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩",
            "[1]", "[2]", "[3]", "[4]", "[5]", "[6]", "[7]", "[8]", "[9]", "[10]"
        ]

        # 特殊标记映射到ID
        marker_id_map = {
            "①": "1", "[1]": "1",
            "②": "2", "[2]": "2",
            "③": "3", "[3]": "3",
            "④": "4", "[4]": "4",
            "⑤": "5", "[5]": "5",
            "⑥": "6", "[6]": "6",
            "⑦": "7", "[7]": "7",
            "⑧": "8", "[8]": "8",
            "⑨": "9", "[9]": "9",
            "⑩": "10", "[10]": "10"
        }

        # 圆圈标记在正常代码里不会出现；方括号标记 [1]..[10] 却与列表下标
        # 同形（a[1]）。文件里只要有圆圈标记就只认圆圈标记——否则后面的
        # print(a[1]) 会覆盖真正的 ① 空位，学生填对也被判 0 分
        _circled = markers_special[:10]
        if any(m in line for line in question_lines for m in _circled):
            markers_special = _circled

        # 检查题目文件中是否包含特殊标记
        contains_special_markers = False
        for line in question_lines:
            for marker in markers_special:
                if marker in line:
                    contains_special_markers = True
                    break
            if contains_special_markers:
                break

        # 查找题目文件中的特殊标记位置
        special_marker_positions = {}
        for i, line in enumerate(question_lines):
            for marker in markers_special:
                if marker in line:
                    marker_id = marker_id_map.get(marker, str(markers_special.index(marker) % 10 + 1))
                    special_marker_positions[i] = {
                        'line': line,
                        'marker': marker,
                        'marker_idx': int(marker_id)
                    }
                    break

        special_marker_count = len(special_marker_positions)

        # 创建填空位置映射（特殊标记ID -> 行号）
        marker_to_line = {}
        for line_idx, marker_info in special_marker_positions.items():
            marker_to_line[str(marker_info['marker_idx'])] = line_idx

        # 仅当确有特殊标记时才启用特殊标记评分
        using_special_markers = contains_special_markers and special_marker_count > 0

        # 遍历每个答案：逐空判对并累加该空分值（blank_scores 缺失时
        # 每空均分，行为与旧版 per_blank_score 完全一致）
        final_score = 0.0
        for blank_id, correct_answer in answers_dict.items():
            try:
                blank_score = blank_score_map.get(blank_id, per_blank_score)
                # 确定该填空对应的行索引
                if using_special_markers and blank_id in marker_to_line:
                    blank_idx = marker_to_line[blank_id]
                else:
                    try:
                        blank_idx = int(blank_id) - 1  # 转为0基索引
                    except ValueError:
                        logger.error(f"填空ID无法转换为索引: '{blank_id}'")
                        continue

                # 校验索引有效性
                if blank_idx < 0 or blank_idx >= len(question_lines):
                    continue
                if blank_idx >= len(student_lines):
                    continue

                question_line = question_lines[blank_idx]
                student_line = student_lines[blank_idx]

                # 提取学生答案
                student_answer = ""
                if student_line != question_line:
                    student_answer = student_line.strip()

                # 标准标记模式：提取标记后的内容
                if marker_standard in question_line and marker_standard in student_line:
                    marker_pos = student_line.find(marker_standard) + len(marker_standard)
                    student_answer = student_line[marker_pos:].strip()

                # 特殊标记模式：通过差异对比提取
                found_special_marker = any(m in question_line for m in markers_special)
                if found_special_marker:
                    extracted_answer = extract_answer_from_line(student_line, question_line, blank_id)
                    if extracted_answer:
                        student_answer = extracted_answer
                elif using_special_markers:
                    extracted_answer = extract_answer_from_line(student_line, question_line, blank_id)
                    if extracted_answer:
                        student_answer = extracted_answer

                # 比较答案
                correct_answer = correct_answer.strip() if correct_answer else ""
                student_answer = student_answer.strip()

                # 空标准答案防护：该空无标准答案时不计分（导入数据缺失/
                # 答案列不足被补空串的场景），防止学生留空/原样提交模板
                # 即匹配 '' 自动得满分
                if not correct_answer:
                    continue

                if student_answer == correct_answer:
                    correct_count += 1
                    final_score += blank_score
                    continue

                # 多组答案（| 分隔）
                multi_answers = [ans.strip() for ans in correct_answer.split('|')]

                # 特殊情况：标准答案含整数除法表达式
                if '//' in correct_answer and getattr(question, 'question_type', '') == 'python_fill':
                    expressions = extract_possible_integer_division_expressions(correct_answer)
                    if student_answer in expressions:
                        correct_count += 1
                        final_score += blank_score
                        continue

                # 对每组答案用 // 分隔（消歧整数除法）
                accepted_answers = []
                for ans in multi_answers:
                    if '//' in ans and getattr(question, 'question_type', '') == 'python_fill':
                        has_integer_div = False
                        integer_div_patterns = [
                            r'[a-zA-Z0-9_\)\]]\s*//\s*[a-zA-Z0-9_\(\[]',
                            r'\(\s*.*\s*//\s*.*\s*\)',
                            r'\[\s*.*\s*//\s*.*\s*\]',
                        ]
                        for pattern in integer_div_patterns:
                            if re.search(pattern, ans):
                                has_integer_div = True
                                break

                        # 明确带空格的分隔符 ' // '
                        if re.search(r'\s//\s', ans):
                            parts = re.split(r'\s//\s', ans)
                            accepted_answers.extend([p.strip() for p in parts])
                            continue

                        programming_patterns = [
                            r'n\s*//\s*\d+',
                            r'[a-zA-Z0-9_]+\s*//\s*[a-zA-Z0-9_]+',
                            r'\(.*\)\s*//\s*\d+',
                            r'\d+\s*//\s*\(.*\)',
                        ]
                        for pattern in programming_patterns:
                            if re.search(pattern, ans):
                                has_integer_div = True
                                break

                        text_patterns = [
                            r's\s*\+=\s*1\s*//\s*s\s*=\s*s\s*\+\s*1',
                            r'[a-zA-Z][a-zA-Z0-9_]*\s*=\s*.*\s*//\s*[a-zA-Z][a-zA-Z0-9_]*\s*=\s*.*',
                        ]
                        is_equivalent_form = any(re.search(p, ans) for p in text_patterns)

                        if is_equivalent_form or not has_integer_div:
                            accepted_answers.extend(option.strip() for option in ans.split('//'))
                        elif has_integer_div:
                            accepted_answers.append(ans)
                    else:
                        accepted_answers.extend(option.strip() for option in ans.split('//'))

                if student_answer in accepted_answers:
                    correct_count += 1
                    final_score += blank_score
                else:
                    # 宽松匹配：归一化内部空格
                    normalized_student = ' '.join(student_answer.split())
                    normalized_accepted = [' '.join(a.split()) for a in accepted_answers]
                    if normalized_student in normalized_accepted:
                        correct_count += 1
                        final_score += blank_score
            except Exception as e:
                logger.error(f"处理填空{blank_id}时出错: {str(e)}", exc_info=True)

        logger.info(f"Python填空题 ID:{question.id} 评分完成 - 正确数: {correct_count}/{len(answers_dict)}, 得分: {final_score}")
        return final_score
    except Exception as e:
        logger.error(f"评分Python文件失败: {str(e)}", exc_info=True)
        return 0


def extract_answer_from_line(student_line, question_line, blank_id):
    """通过对比题目行和学生行，提取学生填写的实际内容

    支持特殊标记的前缀/后缀上下文提取，以及最大差异块回退。
    """
    try:
        student_line = student_line.rstrip()
        question_line = question_line.rstrip()

        # 行完全相同则无答案
        if student_line == question_line:
            return ""

        markers_special = [
            "①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩",
            '①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩',
            "[1]", "[2]", "[3]", "[4]", "[5]", "[6]", "[7]", "[8]", "[9]", "[10]"
        ]

        # 题目行中包含的特殊标记
        found_markers = [m for m in markers_special if m in question_line]

        # difflib 识别差异块
        matcher = difflib.SequenceMatcher(None, question_line, student_line)
        diff_blocks = []
        for opcode, i1, i2, j1, j2 in matcher.get_opcodes():
            if opcode != 'equal':
                diff_blocks.append({
                    'opcode': opcode,
                    'question_part': question_line[i1:i2],
                    'student_part': student_line[j1:j2],
                })

        if not diff_blocks:
            return ""

        # 查找包含特殊标记的差异块
        marker_blocks = []
        for block in diff_blocks:
            for marker in markers_special:
                if marker in block['question_part']:
                    marker_blocks.append((marker, block))

        # 标记被学生替换 → 返回学生部分
        if marker_blocks:
            for marker, block in marker_blocks:
                if marker not in block['student_part']:
                    return block['student_part'].strip()

        # 上下文提取：用标记前后缀定位答案
        for marker in found_markers:
            if marker in question_line and marker not in student_line:
                q_parts = question_line.split(marker)
                if len(q_parts) >= 2:
                    prefix, suffix = q_parts[0], q_parts[1]
                    if prefix in student_line and suffix in student_line:
                        start_pos = student_line.find(prefix) + len(prefix)
                        end_pos = student_line.rfind(suffix)
                        if end_pos > start_pos:
                            return student_line[start_pos:end_pos].strip()

        # 回退：单一差异块直接返回
        if len(diff_blocks) == 1:
            return diff_blocks[0]['student_part'].strip()

        # 回退：返回最大的差异块
        return max(diff_blocks, key=lambda x: len(x['student_part']))['student_part'].strip()
    except Exception as e:
        logger.warning(f"提取填空{blank_id}的答案内容时出错: {str(e)}")
        return ""


# ── 结果删除（统一入口）───────────────────────────────


def delete_exam_result(result, log_action='删除学生成绩'):
    """删除考试结果及其关联的 PythonAnswer 记录，并写操作日志。

    统一 homework.py 与 scores.py 的删除逻辑，确保：
    1. 关联的 PythonAnswer 记录被清理（避免孤儿数据影响重考）
    2. 操作日志被记录
    3. 事务由调用方提交（便于批量场景一次性 commit）——因此：
       - 趋势缓存换代（bump_trend_cache）由**调用方在 commit 成功后**执行。
         此前本函数在 commit 前 bump：批量删除时第一个 bump 与 commit 间隔
         数百毫秒，期间 /api/trend 请求以新 epoch 读到未提交删除前的旧数据
         并写回缓存，commit 后 60s TTL 内被删学生仍出现在趋势页
       - 磁盘 .py 答案文件延迟到 commit 成功后删除（cleanup_deleted_files）。
         此前 commit 前删盘：commit 失败回滚后 DB 行恢复而文件已删，成绩
         回看/重考判分缺文件

    Args:
        result: Result 模型实例（必须已查询到）
        log_action: 日志中记录的操作名称

    Returns:
        dict: {'student_name', 'student_class', 'deleted_answers',
               'exam_id', 'student_id', 'pending_files'}
    """
    from app.extensions import db
    from app.models import Student, PythonAnswer, Question, Log, ExamAttempt

    exam_id = result.exam_id
    student_id = result.student_id

    student = db.session.get(Student, student_id) if student_id else None
    student_name = student.name if student else "未知学生"
    student_class = student.student_class if student else "未知班级"

    # 删除该试卷 python_fill 题型的关联 PythonAnswer 记录
    from app.models import ExamQuestion as _EQ
    python_q_ids = {
        qid for (qid,) in db.session.query(_EQ.question_id)
        .join(Question, Question.id == _EQ.question_id)
        .filter(_EQ.exam_id == exam_id,
                Question.question_type == 'python_fill').all()
    }
    deleted_answers = 0
    pending_files = []
    if python_q_ids and student_id:
        # 一次过滤查询，避免加载该学生全部 PythonAnswer 再逐个判断（N+1/全量加载）
        answers = PythonAnswer.query.filter(
            PythonAnswer.student_id == student_id,
            PythonAnswer.question_id.in_(python_q_ids)
        ).all()
        deleted_answers = len(answers)
        for answer in answers:
            # 磁盘文件延迟删除：路径随返回值交调用方，commit 成功后统一清理
            if answer.file_path:
                pending_files.append(answer.file_path)
            db.session.delete(answer)

    # 清理考试进行中记录（删除成绩后学生可重新开考，避免旧开考记录把
    # 重新提交永久锁死为超时 403）
    ExamAttempt.query.filter(
        ExamAttempt.student_id == student_id,
        ExamAttempt.exam_id == exam_id
    ).delete(synchronize_session=False)

    # 删除考试结果
    db.session.delete(result)

    # 写操作日志
    db.session.add(Log(
        user_id=0,
        user_type='admin',
        action=log_action,
        detail=f'试卷: {exam_id}, 学生ID: {student_id}, '
               f'姓名: {student_name}, 班级: {student_class}',
        time=datetime.now(),
    ))

    # 注意：此处**不得** bump_trend_cache——事务尚未提交，bump 后并发趋势
    # 查询会以新 epoch 读到未提交删除前的旧数据并写回缓存（P2-B 修复点）。
    # 换代与磁盘文件清理统一在调用方 commit 成功后调 finalize_exam_result_deletion。

    return {
        'student_name': student_name,
        'student_class': student_class,
        'deleted_answers': deleted_answers,
        'exam_id': exam_id,
        'student_id': student_id,
        'pending_files': pending_files,
    }


def finalize_exam_result_deletion(*infos):
    """成绩删除收尾（调用方 commit 成功后调用）：
    1. 趋势缓存换代——新 epoch 下的重算必读到已提交删除后的数据
    2. 清理延迟删除的磁盘 .py 答案文件（失败仅记日志，不回滚 DB）

    单条与批量删除统一入口：单条传 delete_exam_result 的返回值，
    批量收集后展开传入。
    """
    from app.utils import delete_file_from_disk as _del_disk

    bumped = set()
    for info in infos:
        if not info:
            continue
        eid = info.get('exam_id')
        if eid is not None and eid not in bumped:
            bumped.add(eid)
            bump_trend_cache(eid)
        for rel_path in info.get('pending_files') or ():
            try:
                _del_disk(rel_path)
            except Exception:
                current_app.logger.debug(
                    f'删除 Python 答案磁盘文件失败（忽略）: {rel_path}')
