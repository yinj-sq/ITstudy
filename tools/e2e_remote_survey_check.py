# -*- coding: utf-8 -*-
"""远程真实环境：调查问卷全链路实测（教师发布→学生填写→回收→可视化→CSV）。

用前准备（环境变量，避免把密码写进文件/命令历史）：
  ITSTUDY_BASE_URL       默认 http://172.19.21.36:8081
  ITSTUDY_TEACHER_USER   教师账号（编辑模式）
  ITSTUDY_TEACHER_PASS   教师编辑密码
  ITSTUDY_STUDENT_NUMBER 学生学号（需处于上课班级）
  ITSTUDY_STUDENT_PASS   学生密码
可选：
  ITSTUDY_RESOURCE_ID    指定资源 ID（默认取教师资源库第一个有问卷入口的资源）
  ITSTUDY_SURVEY_TITLE   问卷标题（默认带时间戳，便于识别）

行为：创建一份最小问卷（单选，必答）并发布 → 学生填写 → 校验「1 份答卷」、
图表 canvas、CSV 内容 → 删除该问卷（仅删除本次创建的问卷，不动资源）。
运行：venv/Scripts/python.exe -X utf8 tools/e2e_remote_survey_check.py
"""
import io
import os
import re
import sys
import time
import uuid

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = os.environ.get('ITSTUDY_BASE_URL', 'http://172.19.21.36:8081').rstrip('/')
T_USER = os.environ.get('ITSTUDY_TEACHER_USER', '')
T_PASS = os.environ.get('ITSTUDY_TEACHER_PASS', '')
S_NUM = os.environ.get('ITSTUDY_STUDENT_NUMBER', '')
S_PASS = os.environ.get('ITSTUDY_STUDENT_PASS', '')
ADMIN_USER = os.environ.get('ITSTUDY_ADMIN_USER', '')
ADMIN_PASS = os.environ.get('ITSTUDY_ADMIN_PASS', '')
ROLE = os.environ.get('ITSTUDY_ROLE', '').strip().lower()
CREATE_TEMP_STUDENT = os.environ.get('ITSTUDY_CREATE_TEST_STUDENT') == '1'
TEST_CLASS_NAME = os.environ.get('ITSTUDY_TEST_CLASS_NAME', '').strip()
CLEANUP_ID = os.environ.get('ITSTUDY_CLEANUP_SURVEY_ID', '').strip()
RES_ID = os.environ.get('ITSTUDY_RESOURCE_ID', '').strip()
TITLE = os.environ.get('ITSTUDY_SURVEY_TITLE') or (
    f'远程问卷测试-{time.strftime("%m%d%H%M")}-{uuid.uuid4().hex[:4]}')
QUESTION = '本次远程测试：你对问卷功能满意吗？'
OPTIONS = ['满意', '一般', '不满意']
SHOT_DIR = os.path.join('data', 'remote_survey_check')
FAILED = []


def check(name, ok, detail=''):
    print(('✓ ' if ok else '✗ ') + name + (f' | {detail}' if detail else ''))
    if not ok:
        FAILED.append(name)


def wait_for(fn, timeout, label):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(0.4)
    raise AssertionError(f'等待超时: {label}')


def _alerts(page):
    try:
        alerts = page.locator('.alert')
        return ' | '.join(a.strip() for a in alerts.all_inner_texts()
                          if a.strip())[:300]
    except Exception:
        return ''


def _resolve_role():
    if ROLE in ('teacher', 'admin'):
        return ROLE
    if T_USER and T_PASS:
        return 'teacher'
    if ADMIN_USER and ADMIN_PASS:
        return 'admin'
    return 'teacher'


def require_env():
    role = _resolve_role()
    missing = []
    if role == 'teacher' and not (T_USER and T_PASS):
        missing += ['ITSTUDY_TEACHER_USER', 'ITSTUDY_TEACHER_PASS']
    if role == 'admin' and not (ADMIN_USER and ADMIN_PASS):
        missing += ['ITSTUDY_ADMIN_USER', 'ITSTUDY_ADMIN_PASS']
    if CREATE_TEMP_STUDENT:
        # 临时学生由管理员创建：必须提供管理员账号
        if not (ADMIN_USER and ADMIN_PASS):
            missing += ['ITSTUDY_ADMIN_USER/ITSTUDY_ADMIN_PASS'
                        '（CREATE_TEST_STUDENT 需要）']
    elif not CLEANUP_ID and not (S_NUM and S_PASS):
        missing += ['ITSTUDY_STUDENT_NUMBER', 'ITSTUDY_STUDENT_PASS']
    if missing:
        print('缺少环境变量：' + '、'.join(missing))
        print('示例（PowerShell）：')
        print('  $env:ITSTUDY_TEACHER_USER="<教师账号>"')
        print('  $env:ITSTUDY_TEACHER_PASS="<教师编辑密码>"')
        print('  # 学生为初始密码未改密时，用管理员账号自动建临时学生：')
        print('  $env:ITSTUDY_CREATE_TEST_STUDENT="1"')
        print('  $env:ITSTUDY_ADMIN_USER="<管理员账号>"')
        print('  $env:ITSTUDY_ADMIN_PASS="<管理员密码>"')
        print('  # 或改用管理员执行发布侧（ITSTUDY_ROLE=admin）并指定学生：')
        print('  $env:ITSTUDY_STUDENT_NUMBER="<学生学号>"')
        print('  $env:ITSTUDY_STUDENT_PASS="<学生密码>"')
        sys.exit(2)
    return role


def login_teacher(page):
    page.goto('/teacher/login', wait_until='domcontentloaded')
    page.fill('input[name="username"]', T_USER)
    mode = page.locator('#readonlyMode')
    if mode.count() and mode.is_enabled() and mode.is_checked():
        mode.uncheck()
        page.wait_for_timeout(150)
    page.fill('input[name="password"]', T_PASS)
    page.locator('form').filter(
        has=page.locator('input[name="username"]')).locator(
        'button[type="submit"]').click()
    try:
        page.wait_for_url('**/teacher/*', timeout=20000)
    except Exception:
        page.screenshot(path=f'{SHOT_DIR}/login_teacher_fail.png')
        raise AssertionError(
            '教师编辑登录失败（未跳转资源库）。'
            f'当前 URL={page.url}；页面提示：{_alerts(page) or "无"}。'
            '请确认 ITSTUDY_TEACHER_PASS 是编辑模式密码（不是只读访问码）；'
            '也可改设 ITSTUDY_ROLE=admin 用管理员账号执行同一套链路。')


def login_admin(page):
    page.goto('/admin/login', wait_until='domcontentloaded')
    page.fill('input[name="username"]', ADMIN_USER)
    page.fill('input[name="password"]', ADMIN_PASS)
    page.locator('form').filter(
        has=page.locator('input[name="username"]')).locator(
        'button[type="submit"]').click()
    try:
        page.wait_for_url(
            lambda url: '/admin/login' not in url, timeout=20000)
    except Exception:
        page.screenshot(path=f'{SHOT_DIR}/login_admin_fail.png')
        raise AssertionError(
            '管理员登录失败。'
            f'当前 URL={page.url}；页面提示：{_alerts(page) or "无"}。'
            '请确认远程管理员登录已开启且密码正确。')


def login_student(page, temp=None):
    number = temp['number'] if temp else S_NUM
    password = temp['initial'] if temp else S_PASS
    page.goto('/', wait_until='domcontentloaded')
    page.fill('input[name="student_number"]', number)
    page.fill('input[name="password"]', password)
    page.locator('form').filter(
        has=page.locator('input[name="student_number"]')).locator(
        'button[type="submit"]').click()
    try:
        page.wait_for_url('**/study*', timeout=20000)
    except Exception:
        if '/change-password' in page.url:
            if temp is None:
                raise AssertionError(
                    '该学生仍为初始密码，登录后被强制改密——脚本不会修改真实'
                    '学生密码。请改用已修改密码的学生，或设置 '
                    'ITSTUDY_CREATE_TEST_STUDENT=1（需管理员账号）让脚本'
                    '自动创建临时测试学生并在用后删除。')
            # 仅临时学生：完成首次改密（不触碰真实学生）
            page.fill('input[name="old_password"]', temp['initial'])
            page.fill('input[name="new_password"]', temp['new'])
            page.fill('input[name="confirm_password"]', temp['new'])
            page.locator('form').filter(
                has=page.locator('input[name="old_password"]')).locator(
                'button[type="submit"]').click()
            page.wait_for_url('**/study*', timeout=20000)
            return
        page.screenshot(path=f'{SHOT_DIR}/login_student_fail.png')
        alert = _alerts(page)
        hint = ''
        if '上课班级' in alert:
            hint = ('【原因】当前没有上课班级，或管理端开启了「课程表自动切换'
                    '班级」：非作息时段访问课堂大屏会把手工设置的班级自动'
                    '清空。请在管理端「课堂大屏」重新设置班级，并**取消勾选'
                    '「课程表自动切换班级」**（或在该班作息时段内测试），'
                    '然后重跑脚本。')
        raise AssertionError(
            '学生登录失败。'
            f'当前 URL={page.url}；页面提示：{alert or "无"}。'
            '请确认学生学号/密码正确，且所属班级正在上课。' + hint)


def create_temp_student(browser):
    """用管理员账号创建临时测试学生（指定班级），返回上下文信息。

    注意：**不访问 /admin/classroom**——管理端该页会在管理员访问时执行
    「课程表自动切换班级」（auto_switch），非作息时段会把手工设置的上课
    班级自动清空（表现为“一运行就变成未设置”）。班级由环境变量指定。
    """
    if not TEST_CLASS_NAME:
        raise AssertionError(
            '请设置 ITSTUDY_TEST_CLASS_NAME 指定临时学生所在班级（如 "11"）。'
            '脚本不再读取课堂大屏页面（该页会触发课程表自动切班，可能清空'
            '手工设置的上课班级）。')
    actx = browser.new_context(base_url=BASE,
                               viewport={'width': 1440, 'height': 900})
    ap = actx.new_page()
    login_admin(ap)
    number = '__survey_' + time.strftime('%m%d%H%M%S')
    name = '问卷测试学生' + number[-4:]
    initial = 'Tmp' + uuid.uuid4().hex[:8]
    new = 'Tmp' + uuid.uuid4().hex[:8]
    ap.goto('/admin/students', wait_until='domcontentloaded')
    ap.locator('button[data-bs-target="#addStudentModal"]').first.click()
    modal = ap.locator('#addStudentModal')
    modal.locator('input[name="name"]').fill(name)
    modal.locator('input[name="student_number"]').fill(number)
    try:
        modal.locator('select[name="class_id"]').select_option(
            label=TEST_CLASS_NAME)
    except Exception:
        options = modal.locator(
            'select[name="class_id"] option').all_inner_texts()
        actx.close()
        raise AssertionError(
            f'学生添加表单中未找到班级「{TEST_CLASS_NAME}」。'
            f'现有班级：{"、".join(o for o in options if o and o != "未分班")}。'
            '请用 ITSTUDY_TEST_CLASS_NAME 指定准确班级名。')
    modal.locator('input[name="password"]').fill(initial)
    modal.locator('button[type="submit"]').click()
    # 学生列表默认按 id 升序分页，新学生不一定在第 1 页：按学号搜索确认
    ap.wait_for_load_state('domcontentloaded')
    ap.goto(f'/admin/students?search={number}',
            wait_until='domcontentloaded')
    try:
        wait_for(lambda: number in ap.content(), 20, '临时学生创建')
    except Exception:
        actx.close()
        raise AssertionError(
            '临时学生创建失败（按学号检索不到）。'
            f'页面提示：{_alerts(ap) or "无"}。'
            '请确认班级名「' + TEST_CLASS_NAME + '」正确且管理员有学生管理权限。')
    check('已创建临时测试学生', True,
          f'{name}（{number}，班级：{TEST_CLASS_NAME}）')
    return {'ctx': actx, 'page': ap, 'number': number, 'name': name,
            'initial': initial, 'new': new, 'class_name': TEST_CLASS_NAME}


def delete_temp_student(temp):
    ap, ctx = temp['page'], temp['ctx']
    try:
        ap.goto(f'/admin/students?search={temp["number"]}',
                wait_until='domcontentloaded')
        ap.on('dialog', lambda d: d.accept())
        row = ap.locator('tr', has_text=temp['number'])
        if row.count():
            row.locator('button[onclick^="deleteStudent"]').first.click()
            wait_for(lambda: temp['number'] not in ap.content(), 20,
                     '临时学生删除')
            check('临时测试学生已删除', True, temp['number'])
    except Exception as e:
        print(f'⚠ 临时学生清理失败（学号 {temp["number"]}，'
              f'姓名 {temp["name"]}）：{e}')
    finally:
        ctx.close()


def expand_card(page, title):
    page.evaluate("""(title) => {
      document.querySelectorAll('.resource-card, .card').forEach(function (c) {
        if (c.textContent.indexOf(title) === -1) return;
        var hdr = c.querySelector('.res-header');
        if (!hdr) return;
        var body = document.getElementById(hdr.dataset.target);
        if (body && getComputedStyle(body).display === 'none') hdr.click();
      });
    }""", title)


def main():
    role = require_env()
    print(f'执行角色：{role}')
    os.makedirs(SHOT_DIR, exist_ok=True)
    from playwright.sync_api import sync_playwright
    created_survey_id = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge', headless=True)
            tctx = browser.new_context(base_url=BASE,
                                       viewport={'width': 1440, 'height': 900})
            tp = tctx.new_page()
            if role == 'admin':
                login_admin(tp)
                check('管理员登录', '/admin/login' not in tp.url, tp.url)
                start_url = '/admin/resources'
                survey_base = '/admin'
            else:
                login_teacher(tp)
                check('教师编辑模式登录', ('/teacher/dashboard' in tp.url or '/teacher/resource-library' in tp.url))
                start_url = '/teacher/resource-library'
                survey_base = '/teacher'

            # 清理模式：只删除指定问卷（支持逗号分隔多个，用于遗留测试问卷）
            if CLEANUP_ID:
                if not RES_ID:
                    print('清理模式需要同时指定 ITSTUDY_RESOURCE_ID')
                    sys.exit(2)
                tp.goto(f'{survey_base}/resources/{RES_ID}/surveys')
                tp.on('dialog', lambda d: d.accept())
                for sid in [x.strip() for x in CLEANUP_ID.split(',')
                            if x.strip()]:
                    row = tp.locator(
                        f'tr:has(form[action*="/surveys/{sid}/delete"])')
                    if row.count():
                        row.locator('form[action*="/delete"] button').click()
                        wait_for(lambda: tp.locator(
                            f'form[action*="/surveys/{sid}/delete"]'
                        ).count() == 0, 20, '遗留问卷删除')
                        print(f'✓ 已删除遗留测试问卷 ID={sid}')
                    else:
                        print(f'未找到问卷 ID={sid}（可能已删除）')
                browser.close()
                return

            # 选择资源（默认第一个带问卷入口的资源）
            res_id = RES_ID
            if not res_id:
                tp.goto(start_url)
                hrefs = tp.eval_on_selector_all(
                    'a[href*="/surveys"]', 'els => els.map(e => e.href)')
                m = re.search(r'/resources/(\d+)/surveys', ' '.join(hrefs))
                if not m:
                    print('未找到带问卷入口的资源，请先创建资源或通过 '
                          'ITSTUDY_RESOURCE_ID 指定')
                    sys.exit(3)
                res_id = m.group(1)
            check('选定测试资源', True, f'resource={res_id}')

            # 创建并发布问卷
            tp.goto(f'{survey_base}/resources/{res_id}/surveys')
            wait_for(lambda: '新增问卷' in tp.content(), 15, '问卷列表')
            tp.locator('a:has-text("新增问卷")').click()
            tp.wait_for_selector('#surveyForm', timeout=20000)
            tp.fill('input[name="title"]', TITLE)
            tp.locator('#addQuestion').click()
            card = tp.locator('.sq-card').first
            card.locator('.sq-type-select').select_option('radio')
            card.locator('input[name="q_title"]').fill(QUESTION)
            card.locator('textarea[name="q_options"]').fill('\n'.join(OPTIONS))
            card.locator('input[name="q_required"]').check()
            tp.locator('#sqPublish').check()
            tp.locator('#surveyForm button[type="submit"]').click()
            wait_for(lambda: TITLE in tp.content() and '已发布' in tp.content(),
                     20, '问卷创建并发布')
            check('教师/管理员创建并发布问卷', True, TITLE)
            # 取问卷 id（结果链接）
            href = tp.eval_on_selector_all(
                'a[href*="/results"]', 'els => els.map(e => e.href)')
            m = re.search(r'/surveys/(\d+)/results', ' '.join(href))
            created_survey_id = m.group(1) if m else None
            check('问卷结果入口存在', created_survey_id is not None,
                  f'survey={created_survey_id}')
            tp.screenshot(path=f'{SHOT_DIR}/teacher_survey_list.png')

            # 学生填写（可用管理员账号自动创建临时测试学生）
            temp_student = None
            try:
                if CREATE_TEMP_STUDENT:
                    temp_student = create_temp_student(browser)
                sctx = browser.new_context(
                    base_url=BASE, viewport={'width': 1440, 'height': 900})
                sp = sctx.new_page()
                login_student(sp, temp=temp_student)
                check('学生登录（上课班级内）', '/study' in sp.url)
                try:
                    wait_for(lambda: TITLE in sp.content(), 20,
                             '学生端问卷可见')
                except Exception:
                    raise AssertionError(
                        '学生端未看到测试问卷。请检查：① 资源已勾选'
                        '「学生端可见」；② 问卷已发布；③ 当前上课教师'
                        '（或管理员授权范围）包含该资源与学生班级。')
                check('学生端问卷可见', True)
                expand_card(sp, TITLE)
                sp.locator(f'a:has-text("{TITLE}")').first.click()
                wait_for(lambda: QUESTION in sp.content(), 20, '学生问卷页')
                sp.locator('input[type="radio"][value="满意"]').check()
                sp.locator('button:has-text("提交问卷")').click()
                wait_for(lambda: '提交成功' in sp.content(), 20, '学生提交成功')
                check('学生填写并提交', True)
                sp.screenshot(path=f'{SHOT_DIR}/student_submitted.png')

                # 回收与可视化
                assert created_survey_id, '未取到问卷 ID，无法校验结果页'
                tp.goto(f'{survey_base}/surveys/{created_survey_id}/results')
                wait_for(lambda: '1 份答卷' in tp.content(), 20, '结果页答卷数')
                check('问卷回收（1 份答卷）', '1 份答卷' in tp.content())
                wait_for(lambda: tp.locator('canvas').count() >= 1, 20,
                         '图表渲染')
                check('结果可视化（Chart.js 图表）',
                      tp.locator('canvas').count() >= 1,
                      f'{tp.locator("canvas").count()} 个图表')
                check('结果页含选项占比', '100.0%' in tp.content())
                tp.screenshot(path=f'{SHOT_DIR}/survey_results.png',
                              full_page=True)
                with tp.expect_download() as dl:
                    tp.locator('a:has-text("导出 CSV")').click()
                csv_path = os.path.join(SHOT_DIR, 'survey_results.csv')
                dl.value.save_as(csv_path)
                with io.open(csv_path, encoding='utf-8-sig') as f:
                    csv_text = f.read()
                check('CSV 导出含答卷',
                      '满意' in csv_text and QUESTION in csv_text,
                      csv_text.splitlines()[0][:60] if csv_text else '')
            finally:
                # 无论成功失败都清理测试数据：只删本次问卷与临时学生
                try:
                    tp.goto(f'{survey_base}/resources/{res_id}/surveys')
                    tp.on('dialog', lambda d: d.accept())
                    row = tp.locator('tr', has_text=TITLE)
                    if row.count():
                        row.locator('form[action*="/delete"] button').click()
                        wait_for(lambda: TITLE not in tp.content(), 20,
                                 '测试问卷删除')
                        created_survey_id = None
                        check('测试问卷已删除（未影响资源）', True)
                except Exception as e:
                    print(f'⚠ 问卷清理失败：{e}')
                if temp_student:
                    delete_temp_student(temp_student)
            browser.close()
    finally:
        if created_survey_id:
            print(f'⚠ 清理未完成，请在教师端删除问卷 ID={created_survey_id}'
                  f'（标题：{TITLE}）')
    print('—— 结果:', '全部通过' if not FAILED else '失败 ' + ', '.join(FAILED),
          '——')
    sys.exit(0 if not FAILED else 1)


if __name__ == '__main__':
    main()
