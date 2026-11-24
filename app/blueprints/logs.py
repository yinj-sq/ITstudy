from flask import (Blueprint, request, render_template, redirect, url_for,
                   flash, jsonify, session)
from flask import current_app
from datetime import datetime, timedelta
import os
import re
from app.extensions import db
from sqlalchemy import or_
from app.models import Log
from app.decorators import admin_login_required

logs_bp = Blueprint('logs', __name__, url_prefix='')


def _log_dir():
    """日志文件目录（项目根下的 logs/，与 app/__init__.py 写入端保持一致）。

    current_app.root_path 指向 app 包目录，其父目录即项目根。
    """
    return os.path.join(os.path.dirname(current_app.root_path), 'logs')


def _is_python_log_line(line):
    """Python 填空题相关日志行（查看页、API、清除三处同一口径；此前 HTML 页
    按 python_fill、API 按 python_file 匹配，两边看到的行不一致）。"""
    return 'Python填空题' in line or 'python_fill' in line or 'python_file' in line


@logs_bp.route('/admin/logs')
@admin_login_required
def admin_logs():
    """管理员查看操作日志（分页渲染）"""
    from app.utils import paginate_query
    pagination = paginate_query(
        Log.query.order_by(Log.time.desc()),
        default_per_page=50, max_per_page=200
    )
    return render_template('admin_logs.html', logs=pagination.items,
                           pagination=pagination)


@logs_bp.route('/admin/logs/clear', methods=['POST'])
@admin_login_required
def clear_logs():
    """清除所有操作日志"""
    try:
        db.session.query(Log).delete()
        db.session.commit()
        new_log = Log(
            user_id=0,
            user_type='admin',
            action='清除日志',
            detail='管理员清除了所有操作日志',
            time=datetime.now()
        )
        db.session.add(new_log)
        db.session.commit()
        flash('操作日志已清除', 'success')
    except Exception as e:
        db.session.rollback()
        flash('清除日志失败', 'danger')
        current_app.logger.error(f"清除操作日志失败: {str(e)}")
    return redirect(url_for('logs.admin_logs'))


@logs_bp.route('/admin/python_logs')
@admin_login_required
def admin_python_logs():
    """管理员查看Python填空题相关日志（流式分页，避免全量加载）"""
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    log_level = request.args.get('log_level', '')
    question_id = request.args.get('question_id', '')
    student_id = request.args.get('student_id', '')
    search_term = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    per_page = 50

    try:
        matched = []
        total_matched = 0
        skip = (page - 1) * per_page
        has_more = False

        log_dir = _log_dir()
        if not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        log_files = sorted(
            [f for f in os.listdir(log_dir) if f.endswith('.log')],
            key=lambda x: os.path.getmtime(os.path.join(log_dir, x)),
            reverse=True
        )[:5]

        for lf in log_files:
            if has_more:
                break
            log_file_path = os.path.join(log_dir, lf)
            # 容错解码：日志含 GBK 等非 UTF-8 内容（学生提交的 .py 文件名/
            # 内容被记录时）会抛 UnicodeDecodeError → 页面 500。逐行
            # errors='replace' 保证任何编码都能读取（不影响过滤逻辑）
            with open(log_file_path, 'r', encoding='utf-8',
                      errors='replace') as f:
                for line in f:
                    if not _is_python_log_line(line):
                        continue
                    if search_term and search_term.lower() not in line.lower():
                        continue
                    if log_level:
                        if log_level == "ERROR" and "ERROR" not in line:
                            continue
                        elif log_level == "WARNING" and "WARNING" not in line and "ERROR" not in line:
                            continue
                        elif log_level == "INFO" and "INFO" not in line and "WARNING" not in line and "ERROR" not in line:
                            continue
                    if question_id and f"题目ID={question_id}" not in line and f"题目{question_id}" not in line:
                        continue
                    if student_id and f"学生ID={student_id}" not in line:
                        continue
                    # 日期筛选：解析行首 YYYY-MM-DD 时间戳（此前缺陷：参数
                    # 读取后从未使用，日期筛选形同虚设；字符串比较即字典序）
                    if start_date or end_date:
                        _m = re.match(r'^(\d{4}-\d{2}-\d{2})', line.strip())
                        if _m:
                            _day = _m.group(1)
                            if start_date and _day < start_date:
                                continue
                            if end_date and _day > end_date:
                                continue
                        # 无时间戳的行不拦截（宽松处理）
                    total_matched += 1
                    if total_matched <= skip:
                        continue
                    if len(matched) >= per_page:
                        has_more = True
                        # 页满后不追加，但继续计数当前文件的剩余匹配行，
                        # 让 total 反映"已扫描到的匹配数"而非停留在每页上限
                        continue
                    log_class = ''
                    if "ERROR" in line:
                        log_class = 'danger'
                    elif "WARNING" in line:
                        log_class = 'warning'
                    elif "INFO" in line:
                        log_class = 'info'
                    elif "DEBUG" in line:
                        log_class = 'secondary'
                    matched.append({'text': line.strip(), 'class': log_class})

        # total 语义修正：流式扫描可能提前停止（has_more），此时 total 是
        # 已扫描到的匹配数而非全部日志总数；标注 is_truncated 供模板提示
        # "已显示 X 条（共扫描 N 条）"
        total = total_matched if has_more else (skip + len(matched))
        total_pages = max(1, (total + per_page - 1) // per_page)
        is_truncated = has_more

        return render_template('admin_python_logs.html',
                               logs=matched,
                               total=total,
                               page=page,
                               per_page=per_page,
                               total_pages=total_pages,
                               is_truncated=is_truncated,
                               start_date=start_date,
                               end_date=end_date,
                               log_level=log_level,
                               question_id=question_id,
                               student_id=student_id,
                               search_term=search_term)
    except Exception as e:
        current_app.logger.error(f"加载Python日志页面出错: {str(e)}", exc_info=True)
        flash('加载日志出错')
        return redirect(url_for('logs.admin_logs'))


@logs_bp.route('/api/logs/python')
@admin_login_required
def api_get_python_logs_auth():
    """API: 获取Python填空题日志（流式分页）"""
    log_level = request.args.get('log_level', '').upper()
    question_id = request.args.get('question_id', '')
    student_id = request.args.get('student_id', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    search_term = request.args.get('search_term', '')
    # 分页参数做类型与上限钳制：非数字参数会 500，超大 per_page 会一次性
    # 读入全部日志耗尽内存
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = min(500, max(1, int(request.args.get('per_page', 100))))
    except (TypeError, ValueError):
        per_page = 100

    log_dir = _log_dir()
    try:
        log_files = sorted(
            [os.path.join(log_dir, f) for f in os.listdir(log_dir) if f.endswith('.log')],
            key=os.path.getmtime,
            reverse=True
        )
    except Exception:
        return jsonify({"error": "读取日志目录失败", "success": False}), 500

    matched = []
    total_matched = 0
    skip = (page - 1) * per_page
    has_more = False

    for log_file in log_files[:5]:
        if has_more:
            break
        try:
            with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    if not _is_python_log_line(line):
                        continue
                    if log_level and not any(f"[{level}]" in line for level in log_level.split(',')):
                        continue
                    if question_id and f"题目ID={question_id}" not in line and f"question_id={question_id}" not in line:
                        continue
                    if student_id and f"学生ID={student_id}" not in line and f"student_id={student_id}" not in line:
                        continue
                    if search_term and search_term not in line:
                        continue
                    if start_date or end_date:
                        try:
                            log_date_str = line.split(' ')[0]
                            log_date = datetime.strptime(log_date_str, '%Y-%m-%d')
                            if start_date:
                                start = datetime.strptime(start_date, '%Y-%m-%d')
                                if log_date < start:
                                    continue
                            if end_date:
                                end = datetime.strptime(end_date, '%Y-%m-%d')
                                if log_date > end:
                                    continue
                        except (ValueError, IndexError):
                            # 日志行格式不匹配日期模式，跳过日期过滤
                            pass
                    total_matched += 1
                    if total_matched <= skip:
                        continue
                    if len(matched) >= per_page:
                        has_more = True
                        # 页满后不追加，但继续计数当前文件的剩余匹配行
                        continue
                    matched.append(line.strip())
        except Exception as e:
            current_app.logger.error(f"读取日志文件 {log_file} 失败: {str(e)}")
            continue

    # total 语义修正：流式扫描可能提前停止（has_more），total 为已扫描匹配数
    total = total_matched if has_more else (skip + len(matched))
    total_pages = max(1, (total + per_page - 1) // per_page)

    return jsonify({
        "success": True,
        "logs": matched,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "is_truncated": has_more
    })


@logs_bp.route('/admin/python_logs/clear', methods=['POST'])
@admin_login_required
def clear_python_logs():
    """清除 Python 填空题相关日志行（其余日志原样保留）。

    日志目录里的 app.log 是全站共用的：此前这里把所有 .log 整体截断，
    登录封锁、失败告警、500 堆栈等审计记录随"清除 Python 日志"一起消失。
    现只剔除与查看页同口径的 Python 相关行。
    """
    try:
        log_dir = _log_dir()
        removed = 0
        if os.path.exists(log_dir):
            for log_file in os.listdir(log_dir):
                if not log_file.endswith('.log'):
                    continue
                file_path = os.path.join(log_dir, log_file)
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                        lines = f.readlines()
                    kept = [ln for ln in lines if not _is_python_log_line(ln)]
                    if len(kept) == len(lines):
                        continue
                    removed += len(lines) - len(kept)
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.writelines(kept)
                except Exception as file_error:
                    current_app.logger.error(f"清理日志文件失败: {file_path}, 错误: {str(file_error)}")
        current_app.logger.info("管理员清理了 Python 题相关日志（%d 行）", removed)
        flash('Python填空题日志已清除', 'success')
    except Exception as e:
        flash('清除日志失败', 'danger')
        current_app.logger.error(f"清除Python日志失败: {str(e)}")
    return redirect(url_for('logs.admin_python_logs'))


_ACCOUNT_TYPE_LABELS = {'student': '学生', 'teacher': '教师', 'admin': '管理员'}
_ACCOUNT_TYPE_CSS = {'student': 'primary', 'teacher': 'success', 'admin': 'dark'}
_PAGE_LABELS = {
    'student_home.student_home': '今日学习',
    'resources.study': '学习资源',
    'resources.study_lesson': '课堂式学习页',
    'resources.study_link': '资源封装页',
    'resources.study_preview': '文件预览',
    'homework.student_homework': '我的作业',
    'homework.student_homework_submit': '提交作业',
    'homework.student_homework_result': '作业结果',
    'online_exam.exam': '在线测试',
    'online_exam.online_exam': '在线答题',
    'online_exam.show_result': '测试结果',
    'groups.student_groups': '学习小组',
    'student_drive.student_drive': '个人网盘',
    'activities.student_activity': '学习活动',
    'surveys.student_survey': '调查问卷',
    'sim_lab.sim_lab': '仿真实验中心',
    'chem_lab.chem_lab_index': '化学仿真',
    'hardware_sim.hardware_sim': '硬件仿真',
    'teacher_home.teacher_dashboard': '教师教学台',
    'resources.admin_resources': '资源管理',
    'resources.admin_classroom': '课堂大屏',
    'logs.admin_logs': '操作日志',
    'logs.admin_account_trail': '账号轨迹',
    'homework.admin_statistics': '数据统计',
}


def _account_status(row, now, stale_cutoff):
    if row.logout_at is not None:
        return '已退出', 'secondary'
    if row.last_seen_at and row.last_seen_at >= stale_cutoff:
        return '在线', 'success'
    return '可能离线', 'warning'


def _account_duration(row):
    end = row.logout_at or row.last_seen_at or row.login_at
    if not row.login_at or not end:
        return ''
    minutes = max(0, int((end - row.login_at).total_seconds() // 60))
    if minutes < 60:
        return f'{minutes} 分钟'
    return f'{minutes // 60} 小时 {minutes % 60} 分'


@logs_bp.route('/admin/account-trail')
@admin_login_required
def admin_account_trail():
    """账号登录会话与页面轨迹（同账号多终端分别展示）。"""
    from app.models import AccountSession
    from app.services.account_tracking import cleanup_old_account_tracking
    from app.utils import paginate_query
    cleanup_old_account_tracking(90)
    now = datetime.now()
    stale_cutoff = now - timedelta(minutes=10)
    query = AccountSession.query
    account_type = (request.args.get('type') or '').strip()
    if account_type in _ACCOUNT_TYPE_LABELS:
        query = query.filter(AccountSession.account_type == account_type)
    q = (request.args.get('q') or '').strip()
    if q:
        conditions = [AccountSession.account_name.ilike(f'%{q}%')]
        if q.isdigit():
            conditions.append(AccountSession.account_id == int(q))
        query = query.filter(or_(*conditions))
    ip = (request.args.get('ip') or '').strip()
    if ip:
        query = query.filter(AccountSession.login_ip.ilike(f'%{ip}%'))
    status = (request.args.get('status') or '').strip()
    if status == 'active':
        query = query.filter(AccountSession.logout_at.is_(None),
                             AccountSession.last_seen_at >= stale_cutoff)
    elif status == 'offline':
        query = query.filter(AccountSession.logout_at.is_(None),
                             AccountSession.last_seen_at < stale_cutoff)
    elif status == 'logged_out':
        query = query.filter(AccountSession.logout_at.isnot(None))
    date_from = (request.args.get('date_from') or '').strip()
    date_to = (request.args.get('date_to') or '').strip()
    try:
        if date_from:
            query = query.filter(AccountSession.login_at >= datetime.strptime(
                date_from, '%Y-%m-%d'))
        if date_to:
            query = query.filter(AccountSession.login_at < datetime.strptime(
                date_to, '%Y-%m-%d') + timedelta(days=1))
    except ValueError:
        pass
    pagination = paginate_query(
        query.order_by(AccountSession.login_at.desc()),
        default_per_page=50, max_per_page=200)
    rows = []
    for row in pagination.items:
        label, css = _account_status(row, now, stale_cutoff)
        rows.append({'row': row, 'status': label, 'status_css': css,
                     'duration': _account_duration(row),
                     'type_label': _ACCOUNT_TYPE_LABELS.get(
                         row.account_type, row.account_type),
                     'type_css': _ACCOUNT_TYPE_CSS.get(
                         row.account_type, 'secondary')})
    active_count = AccountSession.query.filter(
        AccountSession.logout_at.is_(None),
        AccountSession.last_seen_at >= stale_cutoff).count()
    today_start = datetime(now.year, now.month, now.day)
    today_sessions = AccountSession.query.filter(
        AccountSession.login_at >= today_start).count()
    active_accounts = db.session.query(
        AccountSession.account_type, AccountSession.account_id).filter(
            AccountSession.logout_at.is_(None),
            AccountSession.last_seen_at >= stale_cutoff).distinct().count()
    ip_warning = bool(
        request.headers.get('X-Forwarded-For')
        and not current_app.config.get('TRUST_PROXY_HEADERS'))
    return render_template(
        'admin_account_trail.html', rows=rows, pagination=pagination,
        account_type=account_type, q=q, ip=ip, status=status,
        date_from=date_from, date_to=date_to,
        active_count=active_count, today_sessions=today_sessions,
        active_accounts=active_accounts, ip_warning=ip_warning,
        type_labels=_ACCOUNT_TYPE_LABELS)


@logs_bp.route('/admin/account-trail/<session_id>')
@admin_login_required
def admin_account_trail_detail(session_id):
    from app.models import AccountPageView, AccountSession
    from app.utils import paginate_query
    row = db.session.get(AccountSession, session_id)
    if row is None:
        flash('登录会话不存在', 'warning')
        return redirect(url_for('logs.admin_account_trail'))
    pagination = paginate_query(
        AccountPageView.query.filter_by(session_id=session_id).order_by(
            AccountPageView.created_at.desc()),
        default_per_page=100, max_per_page=500)
    pages = []
    for page in pagination.items:
        pages.append({
            'time': page.created_at,
            'label': _PAGE_LABELS.get(page.endpoint) or page.endpoint
                     or page.path or '页面',
            'path': page.path or '',
        })
    return render_template(
        'admin_account_trail_detail.html', trail=row, pages=pages,
        pagination=pagination,
        type_label=_ACCOUNT_TYPE_LABELS.get(row.account_type,
                                            row.account_type),
        status=_account_status(row, datetime.now(),
                               datetime.now() - timedelta(
                                   minutes=10))[0])


def _delete_account_sessions(ids):
    """删除会话及其页面轨迹；返回实际删除的会话数。"""
    from app.models import AccountPageView, AccountSession
    ids = [str(x) for x in ids if x]
    if not ids:
        return 0
    rows = AccountSession.query.filter(AccountSession.id.in_(ids)).all()
    if not rows:
        return 0
    real_ids = [row.id for row in rows]
    AccountPageView.query.filter(
        AccountPageView.session_id.in_(real_ids)).delete(
            synchronize_session=False)
    AccountSession.query.filter(
        AccountSession.id.in_(real_ids)).delete(synchronize_session=False)
    return len(real_ids)


def _trail_next_url():
    nxt = (request.form.get('next') or '').strip()
    if nxt.startswith('/admin/account-trail') and '\\' not in nxt:
        return nxt
    return url_for('logs.admin_account_trail')


@logs_bp.route('/admin/account-trail/<session_id>/delete', methods=['POST'])
@admin_login_required
def admin_account_trail_delete(session_id):
    from app.models import AccountSession
    current_id = session.get('account_session_id')
    if current_id and session_id == current_id:
        flash('不能删除当前正在使用的登录会话', 'warning')
        return redirect(_trail_next_url())
    row = db.session.get(AccountSession, session_id)
    if row is None:
        flash('登录会话不存在或已删除', 'warning')
        return redirect(_trail_next_url())
    detail = (f'{row.account_type} {row.account_name or ""} '
              f'登录时间 {row.login_at} IP {row.login_ip or ""}')
    _delete_account_sessions([session_id])
    db.session.add(Log(
        user_id=session.get('admin_account_id') or 0, user_type='admin',
        action='删除账号轨迹', detail=f'删除 1 条：{detail}',
        time=datetime.now()))
    db.session.commit()
    flash('账号轨迹已删除', 'success')
    return redirect(_trail_next_url())


@logs_bp.route('/admin/account-trail/delete', methods=['POST'])
@admin_login_required
def admin_account_trail_delete_batch():
    from app.models import AccountSession
    ids = request.form.getlist('session_ids')
    current_id = session.get('account_session_id')
    if current_id and current_id in ids:
        ids = [x for x in ids if x != current_id]
        flash('当前正在使用的登录会话已跳过', 'warning')
    # 防止一次提交过大；界面分页每页最多 200
    ids = list(dict.fromkeys(ids))[:500]
    if not ids:
        flash('请选择要删除的账号轨迹', 'warning')
        return redirect(_trail_next_url())
    rows = AccountSession.query.filter(AccountSession.id.in_(ids)).all()
    if not rows:
        flash('所选账号轨迹不存在或已删除', 'warning')
        return redirect(_trail_next_url())
    names = '、'.join(sorted({f'{r.account_type}:{r.account_name or r.id}'
                             for r in rows}))[:500]
    deleted = _delete_account_sessions([r.id for r in rows])
    db.session.add(Log(
        user_id=session.get('admin_account_id') or 0, user_type='admin',
        action='删除账号轨迹', detail=f'批量删除 {deleted} 条：{names}',
        time=datetime.now()))
    db.session.commit()
    flash(f'已删除 {deleted} 条账号轨迹', 'success')
    return redirect(_trail_next_url())
