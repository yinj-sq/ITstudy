from flask import Blueprint, request, render_template, session, jsonify, send_file
from flask import current_app
from datetime import datetime
import json
import math
import os
import re
import zipfile
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename
from io import BytesIO
from app.extensions import db
from app.models import Question, PythonFile, PythonAnswer, Exam
from app.decorators import login_required, admin_login_required
from app.utils import (save_file_to_disk, get_file_absolute_path, delete_file_from_disk)

python_files_bp = Blueprint('python_files', __name__, url_prefix='')


def _is_question_available_to_student(question):
    """题目对学生是否可用：解耦后归属看 ExamQuestion 中间表——
    存在任一关联卷满足（启用+可见+开放）即可用。来源卷 question.exam
    在纯题库题/来源卷被删后为 None，按旧口径会将在考实操题误判 403
    （下载/上传全部静默失败）。与 _is_answer_locked 同一口径。"""
    from app.models import ExamQuestion as _EQ, Exam as _Exam
    if question is None:
        return False
    return bool(
        db.session.query(_Exam.id)
        .join(_EQ, _EQ.exam_id == _Exam.id)
        .filter(_EQ.question_id == question.id,
                _Exam.is_active.is_(True),
                _Exam.is_visible.is_(True),
                _Exam.is_enabled.is_(True))
        .first()
    )


def _is_answer_locked(question, student_id):
    """答案文件是否已锁定（不可覆盖）：该题任一关联卷已收卷，或学生
    在该题任一关联卷已交卷——解耦后一题可属多卷，任一考试上下文结束
    即锁定，防止考后借"另一卷仍开放"替换文件作弊。未挂卷的纯题库题
    无考试上下文，不锁。"""
    from app.models import Result as _Result, ExamQuestion as _EQ, Exam as _Exam
    if question is None:
        return False
    exam_ids = [eid for (eid,) in db.session.query(_EQ.exam_id)
                .filter(_EQ.question_id == question.id).all()]
    if not exam_ids:
        return False
    if db.session.query(_Exam.id).filter(
            _Exam.id.in_(exam_ids),
            _Exam.is_collected.is_(True)).first():
        return True
    if student_id:
        if _Result.query.filter(_Result.student_id == student_id,
                                _Result.exam_id.in_(exam_ids)).first():
            return True
    return False


@python_files_bp.route('/download_python_file/<int:question_id>')
@login_required
def download_python_file(question_id):
    """下载Python试题文件"""
    try:
        student_id = session.get('student_id')
        current_app.logger.info(f"开始处理Python文件下载请求: 题目ID={question_id}, 学生ID={student_id}")
        question = db.get_or_404(Question, question_id)
        if not _is_question_available_to_student(question):
            return jsonify({'success': False, 'message': '题目不可访问'}), 403
        if question.question_type != 'python_fill':
            current_app.logger.warning(f"尝试下载非Python题的文件: 题目ID={question_id}, 实际类型: {question.question_type}")
            return jsonify({'success': False, 'message': '此题目不是Python填空题'}), 400
        python_file = PythonFile.query.filter_by(question_id=question_id).first()
        if not python_file:
            current_app.logger.warning(f"题目{question_id}没有关联的Python文件，将从题目内容生成默认文件")
            content = question.content
            content = re.sub(r'<[^>]+>', '', content)
            file_name = f"python_question_{question_id}.py"
            file_content = f"# Python填空题 - 题目ID: {question_id}\n# 请在标记为____的地方填写代码\n\n{content}\n"
            file_content = file_content.encode('utf-8')
            return send_file(BytesIO(file_content), as_attachment=True,
                             download_name=file_name, mimetype="text/x-python")
        # 从磁盘读取
        abs_path = get_file_absolute_path(python_file.file_path)
        if not abs_path or not os.path.exists(abs_path):
            return jsonify({'success': False, 'message': '文件不存在'}), 404
        return send_file(abs_path, as_attachment=True,
                         download_name=python_file.file_name, mimetype="text/x-python")
    except Exception as e:
        current_app.logger.error(f"下载Python文件失败: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': '下载失败'}), 500


@python_files_bp.route('/upload_python_answer', methods=['POST'])
@login_required
def upload_python_answer():
    """上传Python答案文件"""
    try:
        student_id = session.get('student_id')
        question_id = request.form.get('question_id', type=int)
        current_app.logger.info(f"开始处理Python答案上传: 学生ID={student_id}, 题目ID={question_id}")
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': '未找到上传文件'}), 400
        file = request.files['file']
        if not file or not file.filename:
            return jsonify({'success': False, 'message': '未选择文件'}), 400
        if not question_id:
            return jsonify({'success': False, 'message': '未提供题目ID'}), 400
        question = db.get_or_404(Question, question_id)
        if not _is_question_available_to_student(question):
            return jsonify({'success': False, 'message': '题目不可访问'}), 403
        if question.question_type != 'python_fill':
            return jsonify({'success': False, 'message': '此题目不是Python填空题'}), 400
        if _is_answer_locked(question, student_id):
            return jsonify({'success': False, 'message': '考试已收卷或已交卷，无法修改答案'}), 403
        if not file.filename.endswith('.py'):
            return jsonify({'success': False, 'message': '请上传py文件'}), 400
        filename = secure_filename(file.filename)
        # 先按 Content-Length 预检再读流（此前 file.read() 全量读入内存后才
        # 校验 2MB——全局 200MB 上限的大文件会先撑内存再被拒）
        if file.content_length and file.content_length > 2 * 1024 * 1024:
            return jsonify({'success': False, 'message': 'Python答案文件不能超过2MB'}), 413
        file_content = file.read(2 * 1024 * 1024 + 1)
        # 单文件大小限制：全局 200MB 限制过宽，Python 答案文件设置更合理的 2MB。
        # read(max+1) 兜底：content_length 可被客户端伪造，需实读判定
        if len(file_content) > 2 * 1024 * 1024:
            return jsonify({'success': False, 'message': 'Python答案文件不能超过2MB'}), 413

        # 保存到磁盘
        rel_path = save_file_to_disk(file_content, 'python_answers', filename)

        existing_answer = PythonAnswer.query.filter_by(
            question_id=question_id, student_id=student_id).first()
        if existing_answer:
            old_path = existing_answer.file_path
            existing_answer.file_name = filename
            existing_answer.file_path = rel_path
            existing_answer.created_at = datetime.now()
            try:
                db.session.commit()
            except Exception:
                # DB 提交失败：新文件已成孤儿，删除后回滚，原答案文件保留
                db.session.rollback()
                delete_file_from_disk(rel_path)
                raise
            # commit 成功后再删旧文件（此前先删旧文件，DB 提交失败会丢原答案）
            delete_file_from_disk(old_path)
            return jsonify({'success': True, 'message': '文件更新成功', 'file_name': filename})
        python_answer = PythonAnswer(
            question_id=question_id, student_id=student_id,
            file_name=filename, file_path=rel_path,
            score=None, status='pending'
        )
        db.session.add(python_answer)
        try:
            db.session.commit()
        except IntegrityError:
            # 并发上传同一题（双标签页/网络重试）：uq_python_answer_student_question
            # 冲突，以先落库者为准，复用已有行而非产生重复
            db.session.rollback()
            delete_file_from_disk(rel_path)
            existing = PythonAnswer.query.filter_by(
                question_id=question_id, student_id=student_id).first()
            if existing:
                return jsonify({'success': True, 'message': '文件已上传',
                                'file_name': existing.file_name})
            raise
        return jsonify({'success': True, 'message': '文件上传成功', 'file_name': filename})
    except Exception as e:
        current_app.logger.error(f"上传Python答案失败: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': '上传失败'}), 500


@python_files_bp.route('/api/upload_python_answer', methods=['POST'])
@login_required
def api_upload_python_answer():
    """上传Python填空题答案(API版本)"""
    student_id = session.get('student_id', None)
    current_app.logger.info(f"学生{student_id}尝试通过API上传Python填空题答案")
    # 校验失败统一返回 400（此前全部返回 200，前端无法区分成功与失败）
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': '未提供文件'}), 400
    file = request.files['file']
    if not file or not file.filename:
        return jsonify({'success': False, 'message': '未选择文件'}), 400
    question_id = request.form.get('questionId', type=int)
    if not question_id:
        return jsonify({'success': False, 'message': '未提供题目ID'}), 400
    question = db.session.get(Question, question_id)
    if not question or question.question_type != 'python_fill':
        return jsonify({'success': False, 'message': '无效的题目或题目类型不匹配'}), 400
    if not _is_question_available_to_student(question):
        return jsonify({'success': False, 'message': '题目不可访问'}), 403
    if _is_answer_locked(question, student_id):
        return jsonify({'success': False, 'message': '考试已收卷或已交卷，无法修改答案'}), 403
    if not file.filename.endswith('.py'):
        return jsonify({'success': False, 'message': '请上传py文件'}), 400
    # 净化文件名后再入库：原始 file.filename 会被展示在教师批改页，未净化可能引入
    # 存储型 XSS/头注入。与非 API 版保持一致。
    filename = secure_filename(file.filename)
    try:
        # 先查大小再读入内存，避免无界读取耗尽内存
        file.stream.seek(0, 2)
        file_size = file.stream.tell()
        file.stream.seek(0)
        if file_size > 2 * 1024 * 1024:
            return jsonify({'success': False, 'message': 'Python答案文件不能超过2MB'}), 413
        raw = file.read()
        # 编码兼容（与 HTML 版/评分端一致）：学生用 Windows 编辑器保存的
        # .py 常为 GBK/GB2312，此前 API 版严格 UTF-8 直接 400
        for enc in ('utf-8', 'gbk'):
            try:
                content = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            content = raw.decode('utf-8', errors='replace')
        lines = content.split('\n')
        current_app.logger.info(f"学生{student_id}通过API上传Python答案 - 题目ID: {question_id}, 总行数: {len(lines)}")

        # 保存到磁盘
        rel_path = save_file_to_disk(content, 'python_answers', filename)

        answer = PythonAnswer.query.filter_by(
            student_id=student_id, question_id=question_id).first()
        if answer:
            old_path = answer.file_path
            answer.file_name = filename
            answer.file_path = rel_path
            answer.created_at = datetime.now()
            try:
                db.session.commit()
            except Exception:
                # DB 提交失败：新文件已成孤儿，删除后回滚，原答案文件保留
                db.session.rollback()
                delete_file_from_disk(rel_path)
                raise
            # commit 成功后再删旧文件（此前先删旧文件，DB 提交失败会丢原答案）
            delete_file_from_disk(old_path)
        else:
            answer = PythonAnswer(
                student_id=student_id, question_id=question_id,
                file_name=filename, file_path=rel_path,
                score=None, status='pending'
            )
            db.session.add(answer)
            try:
                db.session.commit()
            except IntegrityError:
                # 并发上传同一题：复用已有行（以先落库者为准）
                db.session.rollback()
                delete_file_from_disk(rel_path)
                existing = PythonAnswer.query.filter_by(
                    student_id=student_id, question_id=question_id).first()
                if existing:
                    return jsonify({'success': True, 'message': '文件已上传',
                                    'file_name': existing.file_name})
                raise
        return jsonify({'success': True, 'message': '文件上传成功', 'file_name': filename})
    except Exception as e:
        current_app.logger.error(f"学生{student_id}通过API上传Python答案处理过程中出错 - 题目ID: {question_id}, 错误: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': '处理文件时出错'}), 400


@python_files_bp.route('/python_marker_guide')
def python_marker_guide():
    """Python填空题特殊标记指南页面"""
    return render_template('python_special_marker_guide.html')


# ════ 批量导入（Python 填空题）════════════════════════════
# 输入两种模式（与 tools/python_fill_import_preview.html 预览工具对应）：
#   A) 文本模式：questions_text + answers_text + per_volume/duration/prefix
#      + zip_file —— 后端按预览工具同款规则识别题目/文件夹/文件/空数/答案
#   B) 校对结果模式：review_json（预览工具导出的 python_fill_review.json，
#      含 split 配置与已校对字段）+ zip_file —— 直接按校对结果建卷建题
# 两模式汇合后：按 split 每卷 N 题建卷（最后剩余组成一卷，卷名自动避让重名），
# 每题建 Question（python_answers / blank_scores / score）+ 关联 PythonFile。

_CIRCLE_MARKERS = '①②③④⑤⑥⑦⑧⑨⑩'
_MAX_ZIP_PY_SIZE = 20 * 1024 * 1024  # 单个 .py 上限（与单题添加一致）


def _calc_blank_scores(n):
    """每空分值约定（与预览工具一致）：3 空 3/3/4，4 空 2.5×4，
    2 空 5/5，5 空 2×5，其余均分（余数给最后一空）。
    n>10 无法合理分配（均分 <1 分/空），返回 None 由调用方拒绝导入。"""
    if not n or n <= 0 or n > 10:
        return None
    if n == 3:
        return [3, 3, 4]
    if n == 4:
        return [2.5, 2.5, 2.5, 2.5]
    if n == 2:
        return [5, 5]
    if n == 5:
        return [2, 2, 2, 2, 2]
    base = math.floor(10 / n)
    remain = 10 - base * n
    arr = [base] * n
    arr[n - 1] += remain
    return arr


def _parse_questions_text(text):
    """从试题文本识别题目：按【第N题】切分，提取文件夹名/文件名/空数/分值。

    识别规则与预览工具保持一致（覆盖题目表述差异），保证预览与导入一致。
    """
    questions = []
    current = None
    pat = re.compile(r'【\s*第\s*(\d+)\s*题\s*】')
    for line in text.splitlines():
        m = pat.search(line)
        if m:
            if current:
                questions.append(current)
            current = {'num': int(m.group(1)), 'raw': [], 'folder_name': None,
                       'file_name': None}
            rest = line[m.end():]
            if rest.strip():
                current['raw'].append(rest)
            continue
        if current:
            current['raw'].append(line)
    if current:
        questions.append(current)

    for q in questions:
        full = '\n'.join(q['raw']).strip()
        q['content'] = full
        # 文件夹名：打开"XX"文件夹 / 打开91文件夹 / 在"91"文件夹 /
        # “91”文件夹中的文件 / 文件夹“91”中的 xx.py —— 取路径最后一级
        fm = (re.search(r'打开["“]?\s*([^"”\n]+?)\s*["”]?\s*文件夹', full)
              or re.search(r'(?:在|到|于)["“]?\s*([^"”\n]+?)\s*["”]?\s*(?:文件夹|目录)', full)
              or re.search(r'(?:文件夹|目录)["“]\s*([^"”\n]+?)\s*["”]', full)
              or re.search(r'["“]([^"”\n]*?[\\/]?[^"”\n]*?)["”]\s*(?:文件夹|目录)', full))
        if fm:
            folder = fm.group(1).replace('\\', '/').strip()
            q['folder_name'] = folder.split('/')[-1].strip()
            q['folder_full'] = folder
        # py 文件名：文件"xx.py" / 文件 xx.py / 文件：xx.py / "xx.py"
        fnm = (re.search(r'文件(?:["“]|[:：]|\s)\s*([^"”\s、，,；;：:\n]+\.py)', full, re.I)
               or re.search(r'["“]([^"”\n]+\.py)["”]', full, re.I)
               or re.search(r'([a-zA-Z0-9_\-一-龥]+\.py)', full, re.I))
        if fnm:
            q['file_name'] = fnm.group(1).strip()
        # 空数：①②③…（____ 兜底）
        circles = len(re.findall(r'[①-⑩]', full))
        under = len(re.findall(r'_{3,}', full))
        q['blank_count'] = max(circles, under) or None
        q['blank_scores'] = _calc_blank_scores(q['blank_count'])
        q['answer_parts'] = []
        q['answer_text'] = None
    return questions


def _parse_answers_text(text, questions):
    """答案文本按文件夹名分节（91 / 91： / 【91】 / 91+制表符）；
    制表符切列 → 每列 = 一空的全部写法；单单元格续行并入上一列。
    结果写入 q['answer_parts']（cols[k] = 第 k+1 空写法列表）。"""
    q_by_folder = {q['folder_name']: q for q in questions if q.get('folder_name')}
    folders = list(q_by_folder)
    current = None
    for line in text.splitlines():
        t = line.strip()
        if not t:
            continue
        hit = None
        for fld in folders:
            if (t == fld or t.startswith(fld + '\t') or t.startswith(fld + '  ')
                    or t.startswith('【' + fld + '】') or t.startswith(fld + '：')):
                hit = fld
                break
        if hit:
            current = q_by_folder[hit]
            current['answer_rows'] = []
            rest = t[len(hit):].lstrip('\t ：、')
            if rest:
                current['answer_rows'].append(rest)
            continue
        if current and 'answer_rows' in current:
            current['answer_rows'].append(t)
    for q in questions:
        rows = q.get('answer_rows')
        if not rows:
            q['answer_parts'] = []
            q['answer_text'] = None
            continue
        cols = []
        for row in rows:
            cells = [x.strip() for x in re.split(r'\t+', row) if x.strip()]
            # 单单元格续行（Word 表格空列折叠后复制）：并入上一行最后一列
            if len(cells) == 1 and cols:
                if cells[0] not in cols[-1]:
                    cols[-1].append(cells[0])
                continue
            for c, cell in enumerate(cells):
                if not cell:
                    continue
                if len(cols) <= c:
                    cols.extend([] for _ in range(c + 1 - len(cols)))
                if cell not in cols[c]:
                    cols[c].append(cell)
        q['answer_parts'] = cols
        q['answer_text'] = '\n'.join(rows).strip()
    return questions


def _zip_entries(zf):
    """展开 zip 内非目录条目：{path, name, dir, size}（路径统一正斜杠）。
    size 取自 zip 目录头（file_size），供 _read_zip_entry 解压前预检——
    此前条目不含 size，超大压缩条目会先完整解压进内存才被拒绝。"""
    entries = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        path = info.filename.replace('\\', '/')
        parts = [p for p in path.split('/') if p]
        if not parts:
            continue
        entries.append({'path': path, 'name': parts[-1],
                        'dir': '/'.join(parts[:-1]), 'size': info.file_size})
    return entries


def _read_zip_entry(zf, entry):
    """读取 zip 条目为文本（utf-8 → gbk → latin-1 兜底）；超限返回 None。

    zf.open 流式限量读取：zip 头声明的 size 可被伪造（声明 100B 实际
    解压数 GB），此前"先信声明值再整读"会在 len 校验前把解压结果整份
    读入内存——读取上限本身即防线，声明值仅作快速预筛。
    """
    try:
        if entry.get('size', 0) > _MAX_ZIP_PY_SIZE:
            return None
        with zf.open(entry['path']) as fp:
            raw = fp.read(_MAX_ZIP_PY_SIZE + 1)
        if len(raw) > _MAX_ZIP_PY_SIZE:
            return None
        for enc in ('utf-8', 'gbk', 'latin-1'):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode('utf-8', errors='replace')
    except Exception:
        return None


def _match_question_zip(zf, q, entries):
    """模式 A：按文件夹名匹配 zip 目录，fileName 精确过滤；
    读取 .py 内容统计占位符空数（py 空数优先于题干）。"""
    q['zip_dir'] = None
    q['zip_files'] = []
    q['py_blanks'] = None
    target = q.get('folder_name')
    if not target or not entries:
        return
    # 目录段级锚定匹配（'91' 不得命中 'data/191/x.py' 这类含子串的路径）
    seg = '/' + target + '/'
    matched = [e for e in entries
               if e['dir'].split('/')[-1] == target
               or seg in '/' + e['dir'] + '/']
    if not matched:
        return
    q['zip_dir'] = matched[0]['dir']
    q['zip_files'] = [e['name'] for e in matched]
    if q.get('file_name'):
        exact = [e for e in matched if e['name'] == q['file_name']]
        if exact:
            q['zip_files'] = [e['name'] for e in exact]
    # 读 .py 统计占位符（前 200KB 足够；与预览工具一致优先采用 py 空数）
    for e in matched:
        if not e['name'].lower().endswith('.py'):
            continue
        if q.get('file_name') and e['name'] != q['file_name']:
            continue
        content = _read_zip_entry(zf, e)
        if content is None:
            continue
        circles = len(re.findall(r'[①-⑩]', content))
        if q['py_blanks'] is None or circles > 0:
            q['py_blanks'] = circles


def _extract_question_files(zf, entries, folder, files):
    """按 (目录, 文件名列表) 从 zip 提取 .py 模板内容。
    返回 [(file_name, content)]；目录精确匹配失败时按最后一级目录兜底。"""
    out = []
    wanted = [f for f in files if f]
    if not wanted:
        return out
    folder_last = folder.split('/')[-1] if folder else None
    for f in wanted:
        match = None
        for e in entries:
            if e['name'] != f:
                continue
            if (not folder or e['dir'] == folder
                    or e['path'].startswith(folder + '/')
                    or (folder_last and e['dir'].split('/')[-1] == folder_last)):
                match = e
                break
        if not match:
            continue
        content = _read_zip_entry(zf, match)
        if content is not None:
            out.append((f, content))
    return out


def _questions_from_review(review):
    """模式 B：从预览工具导出的 python_fill_review.json 构造题目清单。"""
    items = []
    for i, item in enumerate(review.get('questions') or [], 1):
        items.append({
            'num': item.get('num') or i,
            'content': (item.get('content') or '').strip(),
            'folder': (item.get('folder') or '').strip(),
            'files': [f for f in (item.get('files') or []) if f],
            'blank_count': item.get('blank_count'),
            'blank_scores': item.get('blank_scores'),
            'answers': [str(a) for a in (item.get('answers') or [])],
        })
    return items


def _unique_exam_name(base, used):
    """试卷名避让：已存在或批内已用时追加全角（2）（3）…"""
    def exists(name):
        return name in used or bool(Exam.query.filter_by(name=name).first())
    if not exists(base):
        return base
    n = 2
    while exists(f'{base}（{n}）'):
        n += 1
    return f'{base}（{n}）'


@python_files_bp.route('/admin/tools/import-python-fill', methods=['GET'])
@admin_login_required
def import_python_fill_page():
    """批量导入 Python 填空题页面"""
    return render_template('admin_import_python_fill.html')


@python_files_bp.route('/admin/tools/import-python-fill/import', methods=['POST'])
@admin_login_required
def import_python_fill():
    """批量导入 Python 填空题：
    - 模式 B：review_json（python_fill_review.json，含 split 配置）+ zip_file
    - 模式 A：questions_text + answers_text + per_volume/duration/prefix + zip_file
    按 split 每卷 N 题建卷（最后剩余组成一卷，卷名自动避让重名），
    每题建 Question（python_answers/blank_scores/score）+ 关联 PythonFile。
    文件缺失/空数未定等题跳过并在报告列出，其余题正常导入（部分成功）。
    """
    from app.models import Log as _Log
    try:
        review_file = request.files.get('review_json')
        zip_file = request.files.get('zip_file')
        use_review = bool(review_file and review_file.filename)
        if use_review:
            try:
                review = json.loads(review_file.read().decode('utf-8'))
            except Exception:
                return jsonify({'success': False, 'message': '校对结果 JSON 解析失败，'
                                                             '请确认是预览工具导出的 python_fill_review.json'}), 400
            questions = _questions_from_review(review)
            if not questions:
                return jsonify({'success': False, 'message': '校对结果中没有题目'}), 400
            split = review.get('split') or {}
        else:
            q_text = request.form.get('questions_text', '')
            if not q_text.strip():
                return jsonify({'success': False, 'message': '请提供试题文本或校对结果 JSON'}), 400
            questions = _parse_questions_text(q_text)
            if not questions:
                return jsonify({'success': False, 'message': '未识别到题目（需要【第N题】格式）'}), 400
            _parse_answers_text(request.form.get('answers_text', ''), questions)
            split = {
                'per_volume': request.form.get('per_volume', type=int),
                'duration': request.form.get('duration', type=int),
                'prefix': request.form.get('prefix', ''),
            }
        # 表单显式提供时覆盖 review.split（前端页面允许修改拆分配置）
        if request.form.get('per_volume'):
            split['per_volume'] = request.form.get('per_volume', type=int)
        if request.form.get('duration'):
            split['duration'] = request.form.get('duration', type=int)
        if request.form.get('prefix'):
            split['prefix'] = request.form.get('prefix')
        per_volume = int(split.get('per_volume') or 10)
        duration = int(split.get('duration') or 40)
        prefix = (split.get('prefix') or 'Python填空题').strip() or 'Python填空题'
        if per_volume < 1:
            per_volume = 10
        if duration < 1:
            duration = 40

        if not zip_file or not zip_file.filename:
            return jsonify({'success': False, 'message': '请上传包含各题 .py 文件的 zip'}), 400
        try:
            zf = zipfile.ZipFile(zip_file.stream)
        except zipfile.BadZipFile:
            return jsonify({'success': False, 'message': 'zip 文件损坏或格式不正确'}), 400
    except Exception as e:
        current_app.logger.error(f'批量导入 Python 填空题参数处理失败: {str(e)}', exc_info=True)
        return jsonify({'success': False, 'message': '导入参数处理失败'}), 400

    entries = _zip_entries(zf)
    created_exams = []
    created_questions = []
    skipped = []
    used_names = set()
    written_rel_paths = []   # 已落盘的 .py 相对路径（异常回滚后清理孤儿）

    for i, q in enumerate(questions):
        num = q.get('num') or i + 1
        try:
            # 1. 确定匹配目录与文件（模式 A 需先从 zip 匹配；模式 B 直接使用）
            if use_review:
                folder = q['folder']
                files = q['files']
            else:
                _match_question_zip(zf, q, entries)
                folder = q.get('zip_dir') or ''
                files = q.get('zip_files') or []
                # 空数最终确定：py 空数优先（仅当 >0——下划线占位模板无
                # ①②③标记时 circles=0，无条件覆盖会把题干已识别的空数
                # 清零，导致误报"空数未识别"或逐空判分错位），题干统计兜底
                if q.get('py_blanks'):
                    q['blank_count'] = q['py_blanks']
                q['blank_scores'] = _calc_blank_scores(q.get('blank_count'))

            # 2. 校验 + 提取 .py 模板文件
            if not q.get('content'):
                skipped.append({'num': num, 'reason': '题干为空'})
                continue
            extracted = _extract_question_files(zf, entries, folder, files)
            if not extracted:
                skipped.append({'num': num, 'reason': f'zip 中未找到文件（{",".join(files) or "无"}）'})
                continue

            # 3. 空数与分值定稿
            blank_count = q.get('blank_count')
            if not blank_count:
                blank_count = len(q.get('answers') or [])
            if not blank_count or blank_count <= 0:
                skipped.append({'num': num, 'reason': '空数未识别'})
                continue
            if blank_count > 10:
                # 均分 <1 分/空且余数分配失真，拒绝导入而非生成 0 分空
                skipped.append({'num': num,
                                'reason': f'空数 {blank_count} 超过上限 10，无法自动分配分值'})
                continue
            blank_scores = q.get('blank_scores')
            if (not isinstance(blank_scores, list)
                    or len(blank_scores) != blank_count
                    or not all(isinstance(s, (int, float)) and s > 0 for s in blank_scores)):
                blank_scores = _calc_blank_scores(blank_count)
            score = round(sum(blank_scores), 2)

            # 4. 答案对齐空数（不足补空、超出跳过；全空跳过）
            answers = (q.get('answers') or []) if use_review else [
                ' // '.join(parts) for parts in (q.get('answer_parts') or [])]
            if len(answers) > blank_count:
                # 答案列多于空数说明解析错位，直接跳过而非截断导入——
                # 截断会把错位答案挂到错误空位上且报告语义混乱
                skipped.append({'num': num,
                                'reason': f'答案列({len(answers)})多于空数({blank_count})，请在校对结果中修正'})
                continue
            if not any(a for a in answers if str(a).strip()):
                # 全空答案：无法自动判分，且空标准答案会让留空学生白得满分
                # （判分层已有空答案防护兜底，此处从源头拒绝导入）
                skipped.append({'num': num, 'reason': '答案缺失（答案解析为空）'})
                continue
            answers = answers + [''] * (blank_count - len(answers))
            python_answers = json.dumps(
                {str(k + 1): answers[k] for k in range(blank_count)},
                ensure_ascii=False)

            # 5. 建卷（每卷 per_volume 题，最后剩余组成一卷；名称避让重名）。
            # 按「已导入题数」而非原始题目索引分卷——此前被跳过的题目
            # 仍占据卷位，前卷全被跳过时会创建出 0 题空卷
            vol = len(created_questions) // per_volume + 1
            while len(created_exams) < vol:
                exam = Exam(name=_unique_exam_name(f'{prefix} 第{len(created_exams) + 1}卷', used_names),
                            is_active=True, is_visible=True, is_enabled=True,
                            subject_id=None, duration=duration)
                db.session.add(exam)
                db.session.flush()
                used_names.add(exam.name)
                created_exams.append(exam)

            # 6. 建题 + PythonFile
            question = Question(
                exam_id=created_exams[vol - 1].id,
                question_type='python_fill',
                content=q['content'],
                score=score,
                python_answers=python_answers,
                blank_scores=json.dumps(blank_scores, ensure_ascii=False),
            )
            db.session.add(question)
            db.session.flush()
            for file_name, content in extracted:
                rel_path = save_file_to_disk(content, 'python_files', file_name)
                written_rel_paths.append(rel_path)
                db.session.add(PythonFile(
                    question_id=question.id,
                    file_name=file_name,
                    file_path=rel_path))
            created_questions.append(question)
        except IntegrityError:
            db.session.rollback()
            # 事务回滚后 DB 记录消失，但已落盘的 .py 模板不随之删除
            for rel in written_rel_paths:
                delete_file_from_disk(rel)
            # 并发同名导入撞 uq_exam_name：友好提示而非泄露数据库报文
            return jsonify({'success': False,
                            'message': '导入失败：存在同名试卷，请更换卷名前缀后重试'}), 400
        except Exception as e:
            current_app.logger.error(f'批量导入第{num}题失败: {str(e)}', exc_info=True)
            db.session.rollback()
            # 事务回滚后 DB 记录消失，但已落盘的 .py 模板不随之删除——
            # 不清理会在 static/uploads/python_files/ 累积孤儿文件
            # （上传答案/添加题目路径均有对应清理，唯独批量导入遗漏）
            for rel in written_rel_paths:
                delete_file_from_disk(rel)
            return jsonify({'success': False,
                            'message': f'导入第{num}题时出错，详情见服务端日志'}), 500

    if not created_questions:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': '没有可导入的题目',
            'report': {'imported': 0, 'exams': [],
                       'skipped': skipped, 'errors': []},
        }), 400

    db.session.add(_Log(
        user_id=0, user_type='admin',
        action='批量导入Python填空题',
        detail=f'试卷: {",".join(e.name for e in created_exams)}, '
               f'题数: {len(created_questions)}, 跳过: {len(skipped)}',
        time=datetime.now(),
    ))
    db.session.commit()
    # 试卷列表缓存失效（列表页立即可见新卷）
    from app.blueprints.exam_management import _invalidate_exam_list_cache
    _invalidate_exam_list_cache()
    return jsonify({
        'success': True,
        'message': f'成功导入 {len(created_questions)} 题，'
                   f'创建 {len(created_exams)} 份试卷',
        'report': {
            'imported': len(created_questions),
            'exams': [e.name for e in created_exams],
            'skipped': skipped,
            'errors': [],
        },
    })


@python_files_bp.route('/python_answers_format')
def python_answers_format():
    """Python填空题答案格式说明页面"""
    return render_template('python_answers_format_help.html')
