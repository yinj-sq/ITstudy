"""资源测验的逐题数据规范化与汇总；客户端判分始终标记为未核实。"""
import hashlib
import json
import math
import re
from collections import Counter

MAX_QUESTIONS = 500
MAX_QUESTION_BYTES = 1024 * 1024
QUESTION_TYPES = {'single', 'multiple', 'text', 'unknown'}
EVIDENCE_TYPES = {'explicit', 'data-attribute', 'dom-feedback', 'unknown'}


def _text(value, limit, label):
    if isinstance(value, bool):
        value = 'true' if value else 'false'
    if isinstance(value, (int, float)):
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError(f'{label}格式无效')
        value = str(value)
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f'{label}格式无效或过长')
    return value


def _answer(value):
    if value is None:
        return None
    if isinstance(value, list):
        if len(value) > 100:
            raise ValueError('单题选项答案过多')
        return [_text(item, 4000, '答案') for item in value]
    return _text(value, 4000, '答案')


def normalize_questions(raw):
    """旧 SDK 可不传 questions；新数据保留文本，不执行/信任客户端 HTML。"""
    if raw is None:
        return None
    if not isinstance(raw, list) or len(raw) > MAX_QUESTIONS:
        raise ValueError('逐题数据必须为列表，且不超过 500 题')
    questions, seen = [], set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError('逐题数据格式无效')
        qid = _text(entry.get('id', ''), 200, '题目编号').strip()
        if not qid or qid in seen:
            raise ValueError('题目编号不能为空或重复')
        seen.add(qid)
        options = entry.get('options') or []
        if not isinstance(options, list) or len(options) > 100:
            raise ValueError('选项必须为列表，且不超过 100 项')
        normalized, values = [], set()
        for option in options:
            if isinstance(option, str):
                option = {'value': option, 'label': option}
            if not isinstance(option, dict):
                raise ValueError('选项格式无效')
            value = _text(option.get('value', ''), 4000, '选项值')
            label = _text(option.get('label', value), 4000, '选项内容')
            if not value or value in values:
                raise ValueError('选项值不能为空或重复')
            values.add(value)
            normalized.append({'value': value, 'label': label})
        verdict = entry.get('is_correct')
        if verdict is not None and not isinstance(verdict, bool):
            raise ValueError('逐题判定必须为布尔值或 null')
        questions.append({
            'id': qid, 'prompt': _text(entry.get('prompt') or '', 4000, '题干'),
            'type': entry.get('type') if isinstance(entry.get('type'), str)
            and entry['type'] in QUESTION_TYPES else 'unknown',
            'options': normalized, 'answer': _answer(entry.get('answer')),
            'correct_answer': _answer(entry.get('correct_answer')),
            'is_correct': verdict,
            'evidence': entry.get('evidence') if isinstance(entry.get('evidence'), str)
            and entry['evidence'] in EVIDENCE_TYPES else 'unknown',
        })
    if len(json.dumps(questions, ensure_ascii=False).encode('utf-8')) > MAX_QUESTION_BYTES:
        raise ValueError('逐题数据超过 1MB 限制')
    return questions


def answer_values(value):
    return [str(item).strip() for item in (value if isinstance(value, list) else [value])
            if item is not None and str(item).strip()]


def question_verdict(question):
    """仅明确的标准答案或逐题布尔判定参与正确率，不从总分/正分猜测。"""
    answer = answer_values(question.get('answer'))
    correct = answer_values(question.get('correct_answer'))
    options = {option['value'] for option in question.get('options', [])}
    if options and (not set(answer).issubset(options) or not set(correct).issubset(options)):
        return None
    if correct:
        if question.get('type') == 'multiple':
            return set(answer) == set(correct)
        return answer == correct
    return question.get('is_correct') if question.get('evidence') != 'unknown' else None


def _question_order(question):
    """q2 排在 q10 前，避免按学生实际点击顺序打乱题目。"""
    return [(1, int(part)) if part.isdecimal() else (0, part.casefold())
            for part in re.split(r'(\d+)', question['id'])]


def result_questions(result):
    """兼容历史仅 answers 的记录：保留原始作答，但不编造题干、选项或判分。"""
    try:
        details = json.loads(result.question_details or 'null')
        normalized = normalize_questions(details)
        if normalized:
            return sorted(normalized, key=_question_order)
    except (TypeError, ValueError, AttributeError):
        pass
    try:
        answers = json.loads(result.answers or '{}')
    except (TypeError, ValueError):
        return []
    if not isinstance(answers, dict):
        return []
    questions = []
    for qid, answer in list(answers.items())[:MAX_QUESTIONS]:
        try:
            questions.extend(normalize_questions([{
                'id': str(qid)[:200], 'answer': answer, 'type': 'unknown',
            }]))
        except ValueError:
            continue
    return questions


def aggregate_questions(results):
    """results 按最新优先且已限定到同一资源页；每位学生只计算一次。"""
    groups, students = {}, set()
    legacy_records = 0
    for result in results:
        if result.student_id in students:
            continue
        students.add(result.student_id)
        if not getattr(result, 'question_details', None):
            legacy_records += 1
        for question in result_questions(result):
            # 同编号的题干或选项变化后分开统计，防止资源改版/随机题混为一题。
            signature = json.dumps([
                question['id'], question['prompt'], question['type'],
                sorted((option['value'], option['label']) for option in question['options']),
            ], ensure_ascii=False)
            version = hashlib.sha256(signature.encode('utf-8')).hexdigest()[:12]
            key = question['id'] + ':' + version
            if key not in groups:
                groups[key] = {
                    'key': key, 'id': question['id'], 'version': version,
                    'prompt': question['prompt'], 'type': question['type'],
                    'response_count': 0, 'answered_count': 0, 'unanswered_count': 0,
                    'judged_count': 0, 'correct_count': 0, 'incorrect_count': 0,
                    'unknown_count': 0, 'correct_answer': question['correct_answer'],
                    'options': [dict(option, selected_count=0) for option in question['options']],
                    '_answers': Counter(), '_references': set(),
                }
            group = groups[key]
            group['response_count'] += 1
            answer = answer_values(question['answer'])
            group['answered_count' if answer else 'unanswered_count'] += 1
            verdict = question_verdict(question)
            if verdict is None:
                group['unknown_count'] += 1
            else:
                group['judged_count'] += 1
                group['correct_count' if verdict else 'incorrect_count'] += 1
            correct = answer_values(question['correct_answer'])
            if correct:
                if not answer_values(group['correct_answer']):
                    group['correct_answer'] = question['correct_answer']
                group['_references'].add(tuple(sorted(correct) if question['type'] == 'multiple' else correct))
            selected = set(answer)
            for option in group['options']:
                if option['value'] in selected:
                    option['selected_count'] += 1
            if answer:
                group['_answers']['、'.join(answer)] += 1
    questions = []
    for group in groups.values():
        references = group.pop('_references')
        group['answer_key_conflict'] = len(references) > 1
        if group['answer_key_conflict']:
            group['correct_answer'] = None
            group['judged_count'] = group['correct_count'] = group['incorrect_count'] = 0
            group['unknown_count'] = group['response_count']
        group['correct_rate'] = (round(100 * group['correct_count'] / group['judged_count'], 1)
                                 if group['judged_count'] else None)
        for option in group['options']:
            option['selection_rate'] = round(100 * option['selected_count'] / group['response_count'], 1)
        group['answer_distribution'] = [
            {'answer': answer, 'count': count} for answer, count in group.pop('_answers').most_common(20)]
        questions.append(group)
    questions.sort(key=_question_order)
    return {'student_count': len(students), 'legacy_records': legacy_records,
            'questions': questions, 'client_reported': True}
