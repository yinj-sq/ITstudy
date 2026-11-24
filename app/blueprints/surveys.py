# -*- coding: utf-8 -*-
"""调查问卷模块（题型与统计口径借鉴 SurveyKing v1.13.0，MIT，原生实现）。

- 教师编辑模式/管理员：创建、编辑、发布/关闭、删除问卷；可视化结果与 CSV 导出
- 学生：每生每问卷一份答卷；必答校验、填写时间窗、关闭状态控制
"""
from datetime import datetime
import csv
import io
import json
from urllib.parse import quote

from flask import (Blueprint, request, render_template, redirect, url_for,
                   session, flash, abort, Response)
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Resource, Survey, SurveyQuestion, SurveyAnswer
from app.decorators import teacher_login_required, authenticated_required
from app.blueprints.activities import (_teacher_can_manage_resource,
                                       _teacher_resource_visible)

surveys_bp = Blueprint('surveys', __name__, url_prefix='')

Q_TYPES = ['radio', 'checkbox', 'select', 'text', 'textarea', 'score',
           'matrix_radio', 'matrix_score']
CHOICE_TYPES = ('radio', 'checkbox', 'select')
MATRIX_TYPES = ('matrix_radio', 'matrix_score')
Q_TYPE_NAMES = {
    'radio': '单选题', 'checkbox': '多选题', 'select': '下拉题',
    'text': '填空题', 'textarea': '多行文本', 'score': '评分题（1-5分）',
    'matrix_radio': '矩阵单选', 'matrix_score': '矩阵评分',
}
STATUS_NAMES = {'draft': '草稿', 'published': '已发布', 'closed': '已关闭'}


def _invalidate():
    """问卷变更统一失效 /study 资源缓存（含班级范围签名版本）。"""
    from app.blueprints.resources import _invalidate_study_caches
    _invalidate_study_caches()


def _survey_accepting(survey):
    """问卷当前是否处于可填写状态（发布 + 时间窗内）。返回 (ok, message)。"""
    if survey.status != 'published':
        return False, '问卷当前不可填写'
    now = datetime.now()
    if survey.start_time and now < survey.start_time:
        return False, '问卷尚未开始'
    if survey.end_time and now > survey.end_time:
        return False, '问卷已截止'
    return True, ''


def _parse_question_form():
    """解析编辑器表单的题目数组；返回 (questions, error)。

    表单字段：q_type[]/q_title[]/q_options[]/q_rows[] 按行对齐，
    q_required[] 为勾选题目的类型值（q_required 的 value 与 q_type 同行）。
    """
    types = request.form.getlist('q_type')
    titles = request.form.getlist('q_title')
    options_raw = request.form.getlist('q_options')
    rows_raw = request.form.getlist('q_rows')
    required_flags = set(request.form.getlist('q_required'))
    questions = []
    for idx, q_type in enumerate(types):
        title = (titles[idx] if idx < len(titles) else '').strip()
        if not title:
            continue
        if q_type not in Q_TYPES:
            return None, f'第 {idx + 1} 题包含不支持的题型'
        opts = [o.strip() for o in (options_raw[idx] if idx < len(options_raw)
                                    else '').splitlines() if o.strip()]
        rows = [r.strip() for r in (rows_raw[idx] if idx < len(rows_raw)
                                    else '').splitlines() if r.strip()]
        if q_type in CHOICE_TYPES and len(opts) < 2:
            return None, f'「{title}」至少需要 2 个选项'
        if q_type in MATRIX_TYPES:
            if len(opts) < 2:
                return None, f'「{title}」矩阵题至少需要 2 个列选项'
            if not rows:
                return None, f'「{title}」矩阵题至少需要 1 个行标题'
        questions.append({
            'q_type': q_type,
            'title': title,
            'options': json.dumps(opts, ensure_ascii=False),
            'row_titles': json.dumps(rows, ensure_ascii=False) if rows else None,
            'required': q_type in required_flags,
        })
    if not questions:
        return None, '至少需要一道题目'
    return questions, None


def _parse_survey_time(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M')
    except ValueError:
        return None


def _student_name(answer):
    return (answer.student.name if answer.student else '学生已删除')


def _answer_value(answer, qid):
    """取某题的答案值（防御非法 JSON）。"""
    try:
        data = json.loads(answer.answers or '{}')
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    return data.get(str(qid))


def _aggregate(survey, answers):
    """服务端聚合结果统计（图表数据注入页面，无前端计算）。"""
    questions = sorted(survey.questions, key=lambda q: q.sort_order or 0)
    total = len(answers)
    stats = []
    for q in questions:
        try:
            opts = json.loads(q.options) if q.options else []
            rows = json.loads(q.row_titles) if q.row_titles else []
        except ValueError:
            opts, rows = [], []
        st = {'id': q.id, 'title': q.title, 'q_type': q.q_type,
              'options': opts, 'rows': rows, 'required': q.required}
        if q.q_type in ('radio', 'select'):
            counts = {o: 0 for o in opts}
            for a in answers:
                v = _answer_value(a, q.id)
                if v in counts:
                    counts[v] += 1
            st['counts'] = counts
        elif q.q_type == 'checkbox':
            counts = {o: 0 for o in opts}
            for a in answers:
                vs = _answer_value(a, q.id)
                if isinstance(vs, list):
                    for v in vs:
                        if v in counts:
                            counts[v] += 1
            st['counts'] = counts
        elif q.q_type == 'score':
            dist = {str(i): 0 for i in range(1, 6)}
            score_sum = score_cnt = 0
            for a in answers:
                v = _answer_value(a, q.id)
                try:
                    v = int(v)
                except (TypeError, ValueError):
                    continue
                if 1 <= v <= 5:
                    dist[str(v)] += 1
                    score_sum += v
                    score_cnt += 1
            st['dist'] = dist
            st['avg'] = round(score_sum / score_cnt, 2) if score_cnt else None
        elif q.q_type in ('text', 'textarea'):
            st['texts'] = [{'name': (_student_name(a) if not survey.is_anonymous
                                     else '匿名'),
                            'value': (_answer_value(a, q.id) or '').strip()}
                           for a in answers]
        elif q.q_type == 'matrix_radio':
            per_row = {}
            for r in rows:
                counts = {o: 0 for o in opts}
                for a in answers:
                    v = _answer_value(a, q.id)
                    if isinstance(v, dict) and v.get(r) in counts:
                        counts[v[r]] += 1
                per_row[r] = counts
            st['per_row'] = per_row
        elif q.q_type == 'matrix_score':
            per_row = {}
            for r in rows:
                dist = {str(i): 0 for i in range(1, 6)}
                score_sum = score_cnt = 0
                for a in answers:
                    v = _answer_value(a, q.id)
                    val = v.get(r) if isinstance(v, dict) else None
                    try:
                        val = int(val)
                    except (TypeError, ValueError):
                        continue
                    if 1 <= val <= 5:
                        dist[str(val)] += 1
                        score_sum += val
                        score_cnt += 1
                per_row[r] = {'dist': dist,
                              'avg': round(score_sum / score_cnt, 2)
                              if score_cnt else None}
            st['per_row'] = per_row
        stats.append(st)
    return stats, total


def _csv_value(q, value):
    """CSV 单元格文本：列表/字典展开为中文顿号连接。"""
    if isinstance(value, list):
        return '、'.join(str(v) for v in value)
    if isinstance(value, dict):
        return '；'.join(f'{k}: {v}' for k, v in value.items())
    if value is None:
        return ''
    return str(value)


def _back_url():
    return (url_for('resources.admin_resources')
            if session.get('is_admin')
            else url_for('resources.teacher_resource_library'))


# ── 管理端：问卷列表 ──
@surveys_bp.route('/admin/resources/<int:res_id>/surveys')
@surveys_bp.route('/teacher/resources/<int:res_id>/surveys')
@teacher_login_required
def survey_list(res_id):
    resource = db.get_or_404(Resource, res_id)
    can_manage = _teacher_can_manage_resource(resource)
    if not can_manage and not _teacher_resource_visible(resource):
        flash('无权查看该资源的调查问卷', 'danger')
        return redirect(_back_url())
    surveys = Survey.query.filter_by(resource_id=res_id).order_by(
        Survey.sort_order, Survey.created_at.desc()).all()
    answer_counts = {}
    if surveys:
        rows = db.session.query(
            SurveyAnswer.survey_id, func.count(SurveyAnswer.id)
        ).filter(SurveyAnswer.survey_id.in_([s.id for s in surveys])
                 ).group_by(SurveyAnswer.survey_id).all()
        answer_counts = dict(rows)
    return render_template('survey_list.html', resource=resource,
                           surveys=surveys, can_manage=can_manage,
                           answer_counts=answer_counts,
                           status_names=STATUS_NAMES, back_url=_back_url())


# ── 管理端：新建/编辑问卷 ──
@surveys_bp.route('/admin/resources/<int:res_id>/surveys/new',
                  methods=['GET', 'POST'])
@surveys_bp.route('/teacher/resources/<int:res_id>/surveys/new',
                  methods=['GET', 'POST'])
@teacher_login_required
def survey_new(res_id):
    resource = db.get_or_404(Resource, res_id)
    if not _teacher_can_manage_resource(resource):
        flash('只有资源创建者可以创建问卷', 'danger')
        return redirect(_back_url())
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        if not title:
            flash('问卷标题不能为空', 'danger')
            return redirect(request.url)
        questions, err = _parse_question_form()
        if err:
            flash(err, 'danger')
            return redirect(request.url)
        survey = Survey(
            resource_id=res_id, title=title,
            description=request.form.get('description', '').strip(),
            is_anonymous=request.form.get('is_anonymous') == '1',
            status=request.form.get('status') in ('published', 'closed')
            and request.form.get('status') or 'draft',
            start_time=_parse_survey_time(request.form.get('start_time')),
            end_time=_parse_survey_time(request.form.get('end_time')),
        )
        db.session.add(survey)
        db.session.flush()
        for order, q in enumerate(questions):
            db.session.add(SurveyQuestion(survey_id=survey.id,
                                          sort_order=order, **q))
        db.session.commit()
        _invalidate()
        flash('问卷已创建' + ('并发布' if survey.status == 'published' else ''),
              'success')
        return redirect(url_for('surveys.survey_list', res_id=res_id))
    return render_template('survey_editor.html', resource=resource,
                           survey=None, questions=[],
                           q_type_names=Q_TYPE_NAMES, q_types=Q_TYPES,
                           back_url=url_for('surveys.survey_list',
                                            res_id=res_id))


@surveys_bp.route('/admin/surveys/<int:sid>/edit', methods=['GET', 'POST'])
@surveys_bp.route('/teacher/surveys/<int:sid>/edit', methods=['GET', 'POST'])
@teacher_login_required
def survey_edit(sid):
    survey = db.get_or_404(Survey, sid)
    if not _teacher_can_manage_resource(survey.resource):
        flash('只有资源创建者可以编辑问卷', 'danger')
        return redirect(_back_url())
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        if not title:
            flash('问卷标题不能为空', 'danger')
            return redirect(request.url)
        questions, err = _parse_question_form()
        if err:
            flash(err, 'danger')
            return redirect(request.url)
        old_title = survey.title
        survey.title = title
        survey.description = request.form.get('description', '').strip()
        survey.is_anonymous = request.form.get('is_anonymous') == '1'
        survey.status = request.form.get('status') in ('published', 'closed') \
            and request.form.get('status') or 'draft'
        survey.start_time = _parse_survey_time(request.form.get('start_time'))
        survey.end_time = _parse_survey_time(request.form.get('end_time'))
        SurveyQuestion.query.filter_by(survey_id=survey.id).delete(
            synchronize_session=False)
        for order, q in enumerate(questions):
            db.session.add(SurveyQuestion(survey_id=survey.id,
                                          sort_order=order, **q))
        _sync_survey_lesson_tree(survey.resource, survey.id,
                                 old_title=old_title, new_title=title)
        db.session.commit()
        _invalidate()
        flash('问卷已更新', 'success')
        return redirect(url_for('surveys.survey_list',
                                res_id=survey.resource_id))
    questions = sorted(survey.questions, key=lambda q: q.sort_order or 0)
    for q in questions:
        # 编辑器预填：JSON 选项/矩阵行还原为每行一条的文本
        try:
            q.options_text = '\n'.join(json.loads(q.options or '[]'))
        except ValueError:
            q.options_text = ''
        try:
            q.rows_text = '\n'.join(json.loads(q.row_titles or '[]'))
        except ValueError:
            q.rows_text = ''
    return render_template('survey_editor.html', resource=survey.resource,
                           survey=survey, questions=questions,
                           q_type_names=Q_TYPE_NAMES, q_types=Q_TYPES,
                           back_url=url_for('surveys.survey_list',
                                            res_id=survey.resource_id))


@surveys_bp.route('/admin/surveys/<int:sid>/delete', methods=['POST'])
@surveys_bp.route('/teacher/surveys/<int:sid>/delete', methods=['POST'])
@teacher_login_required
def survey_delete(sid):
    survey = db.get_or_404(Survey, sid)
    if not _teacher_can_manage_resource(survey.resource):
        flash('只有资源创建者可以删除问卷', 'danger')
        return redirect(_back_url())
    res_id = survey.resource_id
    _sync_survey_lesson_tree(survey.resource, survey.id, remove=True)
    SurveyAnswer.query.filter_by(survey_id=sid).delete(
        synchronize_session=False)
    SurveyQuestion.query.filter_by(survey_id=sid).delete(
        synchronize_session=False)
    db.session.delete(survey)
    db.session.commit()
    _invalidate()
    flash('问卷已删除', 'success')
    return redirect(url_for('surveys.survey_list', res_id=res_id))


@surveys_bp.route('/admin/surveys/<int:sid>/toggle', methods=['POST'])
@surveys_bp.route('/teacher/surveys/<int:sid>/toggle', methods=['POST'])
@teacher_login_required
def survey_toggle(sid):
    survey = db.get_or_404(Survey, sid)
    if not _teacher_can_manage_resource(survey.resource):
        abort(403)
    if survey.status == 'published':
        survey.status = 'closed'
    else:
        survey.status = 'published'
    db.session.commit()
    _invalidate()
    flash('问卷已' + ('关闭' if survey.status == 'closed' else '发布'),
          'success')
    return redirect(url_for('surveys.survey_list',
                            res_id=survey.resource_id))


# ── 管理端：结果可视化与 CSV ──
@surveys_bp.route('/admin/surveys/<int:sid>/results')
@surveys_bp.route('/teacher/surveys/<int:sid>/results')
@teacher_login_required
def survey_results(sid):
    survey = db.get_or_404(Survey, sid)
    if not _teacher_can_manage_resource(survey.resource):
        flash('只有资源创建者可以查看问卷结果', 'danger')
        return redirect(_back_url())
    answers = SurveyAnswer.query.filter_by(survey_id=sid).order_by(
        SurveyAnswer.submitted_at).all()
    stats, total = _aggregate(survey, answers)
    return render_template('survey_results.html', survey=survey,
                           stats=stats, total=total,
                           status_names=STATUS_NAMES,
                           q_type_names=Q_TYPE_NAMES,
                           back_url=url_for('surveys.survey_list',
                                            res_id=survey.resource_id))


@surveys_bp.route('/admin/surveys/<int:sid>/results.csv')
@surveys_bp.route('/teacher/surveys/<int:sid>/results.csv')
@teacher_login_required
def survey_results_csv(sid):
    survey = db.get_or_404(Survey, sid)
    if not _teacher_can_manage_resource(survey.resource):
        abort(403)
    questions = sorted(survey.questions, key=lambda q: q.sort_order or 0)
    answers = SurveyAnswer.query.filter_by(survey_id=sid).order_by(
        SurveyAnswer.submitted_at).all()
    out = io.StringIO()
    writer = csv.writer(out)
    header = ['提交时间']
    if not survey.is_anonymous:
        header.append('学生')
    for q in questions:
        if q.q_type in MATRIX_TYPES:
            try:
                rows = json.loads(q.row_titles or '[]')
            except ValueError:
                rows = []
            for r in rows:
                header.append(f'{q.title}｜{r}')
        else:
            header.append(q.title)
    writer.writerow(header)
    for a in answers:
        try:
            data = json.loads(a.answers or '{}')
        except ValueError:
            data = {}
        row = [a.submitted_at.strftime('%Y-%m-%d %H:%M')
               if a.submitted_at else '']
        if not survey.is_anonymous:
            row.append(_student_name(a))
        for q in questions:
            v = data.get(str(q.id)) if isinstance(data, dict) else None
            if q.q_type in MATRIX_TYPES:
                try:
                    rows = json.loads(q.row_titles or '[]')
                except ValueError:
                    rows = []
                if isinstance(v, dict):
                    for r in rows:
                        row.append(v.get(r, ''))
                else:
                    row.extend([''] * len(rows))
            else:
                row.append(_csv_value(q, v))
        writer.writerow(row)
    buf = io.BytesIO(('﻿' + out.getvalue()).encode('utf-8'))
    filename = f'{survey.title}_答卷.csv'.replace('/', '_').replace('\\', '_')
    resp = Response(buf.getvalue(),
                    content_type='text/csv; charset=utf-8')
    resp.headers['Content-Disposition'] = (
        f"attachment; filename*=UTF-8''{quote(filename, safe='')}")
    return resp


# ── 学生端：填写问卷 ──
@surveys_bp.route('/study/survey/<int:sid>', methods=['GET', 'POST'])
@authenticated_required
def student_survey(sid):
    survey = db.get_or_404(Survey, sid)
    from app.blueprints.activities import _resource_visible_to_current_user
    if not _resource_visible_to_current_user(survey.resource):
        return '无权访问', 403
    student_id = session.get('student_id')
    answer = SurveyAnswer.query.filter_by(survey_id=sid,
                                          student_id=student_id).first() \
        if student_id else None
    is_teacher_view = bool(session.get('is_admin') or session.get('is_teacher'))
    if survey.status == 'draft' and not is_teacher_view:
        return '问卷尚未发布', 403
    if survey.status == 'closed' and not answer and not is_teacher_view:
        return '问卷已关闭', 403
    if request.method == 'POST':
        if not student_id:
            return redirect(url_for('auth.login'))
        if answer:
            flash('你已经提交过这份问卷', 'warning')
            return redirect(url_for('surveys.student_survey', sid=sid))
        ok, msg = _survey_accepting(survey)
        if not ok:
            flash(msg, 'danger')
            return redirect(url_for('surveys.student_survey', sid=sid))
        questions = sorted(survey.questions, key=lambda q: q.sort_order or 0)
        values = {}
        for q in questions:
            key = f'q{q.id}'
            if q.q_type == 'checkbox':
                vals = [v.strip() for v in request.form.getlist(key)
                        if v.strip()]
            elif q.q_type in MATRIX_TYPES:
                # 矩阵行以序号索引（q<id>__m<行序>），行标题含特殊字符也稳定
                try:
                    rows = json.loads(q.row_titles or '[]')
                except ValueError:
                    rows = []
                row_vals = {}
                for idx, r in enumerate(rows):
                    rv = request.form.get(f'{key}__m{idx}', '').strip()
                    if rv:
                        row_vals[r] = rv
                vals = row_vals
            else:
                vals = request.form.get(key, '').strip()
            missing = False
            if q.required:
                if isinstance(vals, (list, dict)):
                    if not vals:
                        missing = True
                    elif q.q_type in MATRIX_TYPES:
                        try:
                            expected = len(json.loads(q.row_titles or '[]'))
                        except ValueError:
                            expected = 0
                        if len(vals) < expected:
                            missing = True
                elif not str(vals).strip():
                    missing = True
            if missing:
                flash(f'请完成必答题：{q.title}', 'danger')
                return redirect(url_for('surveys.student_survey', sid=sid))
            values[str(q.id)] = vals
        # 唯一约束兜底（并发双击提交）
        try:
            db.session.add(SurveyAnswer(survey_id=sid, student_id=student_id,
                                        answers=json.dumps(values,
                                                           ensure_ascii=False)))
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash('你已经提交过这份问卷', 'warning')
            return redirect(url_for('surveys.student_survey', sid=sid))
        flash('问卷提交成功，感谢你的反馈！', 'success')
        return redirect(url_for('surveys.student_survey', sid=sid))
    questions = sorted(survey.questions, key=lambda q: q.sort_order or 0)
    try:
        saved = json.loads(answer.answers) if answer and answer.answers else {}
    except ValueError:
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    for q in questions:
        # 模板渲染用：选项/矩阵行列表与已答显示文本
        try:
            q.opts = json.loads(q.options or '[]')
        except ValueError:
            q.opts = []
        try:
            q.rows = json.loads(q.row_titles or '[]')
        except ValueError:
            q.rows = []
        val = saved.get(str(q.id))
        if q.q_type == 'checkbox' and isinstance(val, list):
            q.display_value = '、'.join(str(v) for v in val) or '（未选择）'
        elif q.q_type in MATRIX_TYPES and isinstance(val, dict):
            parts = []
            for r in q.rows:
                parts.append(f'{r}: {val.get(r, "未答")}')
            q.display_value = '；'.join(parts)
        else:
            q.display_value = str(val) if val not in (None, '') else '（未填写）'
    accepting_ok, accepting_msg = _survey_accepting(survey)
    return render_template('student_survey.html', survey=survey,
                           questions=questions, answer=answer,
                           saved=saved,
                           accepting_ok=accepting_ok,
                           accepting_msg=accepting_msg,
                           q_type_names=Q_TYPE_NAMES)


# ── 课堂章节树同步 ──
def _sync_survey_lesson_tree(resource, survey_id, old_title=None,
                             new_title=None, remove=False):
    """同步问卷改名/删除到课堂章节树（与活动同款逻辑，仅 kind='survey'）。"""
    if not resource or not resource.lesson_tree:
        return False
    try:
        tree = json.loads(resource.lesson_tree)
    except (TypeError, ValueError):
        return False
    if not isinstance(tree, list):
        return False
    changed = False

    def clean_node(node):
        nonlocal changed
        if not isinstance(node, dict):
            return None
        items = []
        for item in node.get('items', []) or []:
            if (isinstance(item, dict) and item.get('kind') == 'survey'
                    and str(item.get('survey_id') or '') == str(survey_id)):
                if remove:
                    changed = True
                    continue
                if new_title and item.get('title') == old_title:
                    item['title'] = new_title
                    changed = True
            items.append(item)
        node['items'] = items
        children = []
        for child in node.get('children', []) or []:
            cleaned = clean_node(child)
            if cleaned is not None:
                children.append(cleaned)
        node['children'] = children
        if not items and not children:
            return None
        return node

    cleaned_tree = []
    for root in tree:
        cleaned = clean_node(root)
        if cleaned is not None:
            cleaned_tree.append(cleaned)
    if changed:
        resource.lesson_tree = json.dumps(cleaned_tree, ensure_ascii=False)
    return changed
