# -*- coding: utf-8 -*-
"""JitViewer/PPTist 修复链路动态验证（独立测试库 itstudy_e2e，测后清理）

覆盖：
A. 个人网盘：pptx 分流 PPTist embed（sandbox 同源）/ pdf 走 JitViewer /
   inline 无 CD 头 / json 版本语义(404→解析, _v 校验) / save-json 净化与归属 /
   edit 仅本人 / 管理员只读预览
B. 小组网盘：drive_download inline 去 CD 头（此前全挂的致命点）+ 预览传 inline
C. 全局：CSP worker-src、静态 .html no-cache、构建产物 index.html 可达
"""
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ['DB_NAME'] = 'itstudy_e2e'
os.environ['CACHE_DIR'] = os.path.join(os.getcwd(), 'data', 'cache_e2e_pptist')
os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_PORT', '5432')
os.environ.setdefault('DB_USER', 'postgres')
os.environ.setdefault('DB_PASS', '@@')
os.environ['SECRET_KEY'] = 'e2e-pptist-key'
sys.path.insert(0, os.getcwd())

from app import create_app
from app.extensions import db

results = []


def check(name, cond, extra=''):
    results.append(bool(cond))
    print(f'[{"PASS" if cond else "FAIL"}] {name}' + (f' | {extra}' if extra else ''))


app = create_app()
from e2e_common import reset_shared_state  # noqa: E402
reset_shared_state(app)
client = app.test_client()

# ══ 幂等清理：启动时清上次中断的残留，退出时（atexit，异常退出也执行）清本次夹具 ══
from sqlalchemy import text as _text
import glob as _glob


def _purge():
    with app.app_context():
        db.session.rollback()
        conn = db.session.connection()
        for stmt in (
            "DELETE FROM classroom_setting",
            "DELETE FROM group_file WHERE group_id IN"
            " (SELECT id FROM study_group WHERE name LIKE 'G%')",
            "DELETE FROM student_drive_file WHERE student_id IN"
            " (SELECT id FROM student WHERE student_number LIKE 'JP%')",
            "DELETE FROM attendance_record WHERE student_id IN"
            " (SELECT id FROM student WHERE student_number LIKE 'JP%')",
            "DELETE FROM student WHERE student_number LIKE 'JP%'",
            "DELETE FROM study_group WHERE name LIKE 'G%'",
            "DELETE FROM classroom_session WHERE class_id IN"
            " (SELECT id FROM classes WHERE name = 'PPt动态班')",
            "DELETE FROM classes WHERE name = 'PPt动态班'",
        ):
            conn.execute(_text(stmt))
        db.session.commit()
        from app.blueprints.auth import invalidate_active_class_cache
        invalidate_active_class_cache()
    for pat in ('static/uploads/_jit_t_*', 'static/uploads/drive/_jit_g_*'):
        for fp in _glob.glob(pat):
            try:
                os.remove(fp)
            except OSError:
                pass


_purge()
import atexit  # noqa: E402
atexit.register(_purge)

_PPTX_MIME = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'


def csrf():
    client.get('/')
    c = client.get_cookie('csrf_token')
    return c.value.decode() if c else ''


def hdr(name):
    return client.get_cookie(name)


def as_student(sid):
    with client.session_transaction() as s:
        s.clear()
        s['csrf_token'] = 't'
        s['student_id'] = sid
        s['student_name'] = '测试学生'
        s['has_changed_password'] = True


def as_admin():
    with client.session_transaction() as s:
        s.clear()
        s['csrf_token'] = 't'
        s['is_admin'] = True


# ══ 数据准备（ORM 直建，隔离库）══
# 注意：load_student_name 钩子会校验 active_class_id 与学生班级一致，
# 残留的 ClassroomSetting 会导致学生会话被清 → 全部 302。
# e2e 库独占：预清理全表，种子显式插入本班设置
from sqlalchemy import text as _pre
with app.app_context():
    db.session.execute(_pre('DELETE FROM classroom_setting'))
    db.session.commit()

from app.models import Class, Student, StudyGroup, GroupFile, StudentDriveFile, ClassroomSetting

with app.app_context():
    cls = Class(name='PPt动态班')
    db.session.add(cls)
    db.session.flush()
    s1 = Student(name='甲', student_number=f'JP{os.getpid()}1',
                 student_class='PPt动态班', class_id=cls.id,
                 is_activated=True, has_changed_password=True)
    s2 = Student(name='乙', student_number=f'JP{os.getpid()}2',
                 student_class='PPt动态班', class_id=cls.id,
                 is_activated=True, has_changed_password=True)
    db.session.add_all([s1, s2])
    db.session.flush()
    grp = StudyGroup(name=f'G{os.getpid() % 10000}', class_id=cls.id)
    db.session.add(grp)
    db.session.flush()
    s1.group_id = grp.id
    db.session.add(ClassroomSetting(active_class_id=cls.id))
    db.session.flush()
    sid1, sid2, gid, cid = s1.id, s2.id, grp.id, cls.id

    # 物理文件
    up = os.path.join('static', 'uploads')
    os.makedirs(os.path.join(up, 'drive'), exist_ok=True)
    p_personal = f'_jit_t_{os.getpid()}.pptx'
    p_group = os.path.join('drive', f'_jit_g_{os.getpid()}.pptx')
    p_pdf = f'_jit_t_{os.getpid()}.pdf'
    for rel in (p_personal, p_group, p_pdf):
        with open(os.path.join(up, rel), 'wb') as f:
            f.write(b'%PDF-fake' if rel.endswith('.pdf') else b'PK\x03\x04fakepptx')

    df = StudentDriveFile(student_id=sid1, sender_type='student', sender_id=sid1,
                          filename=p_personal, original_filename='课件.pptx',
                          file_size=12, file_path=p_personal)
    gf = GroupFile(group_id=gid, uploader_id=sid1, filename=p_group,
                   original_filename='小组.pptx', file_size=12,
                   file_path=p_group)
    df_pdf = StudentDriveFile(student_id=sid1, sender_type='student', sender_id=sid1,
                              filename=p_pdf, original_filename='讲义.pdf',
                              file_size=8, file_path=p_pdf)
    db.session.add_all([df, gf, df_pdf])
    db.session.commit()
    did, gfid, pdfid = df.id, gf.id, df_pdf.id
print(f'—— 数据就绪 sid1={sid1} sid2={sid2} gid={gid} did={did} gfid={gfid} ——')

# ══ A. 个人网盘 ══
as_student(sid1)

r = client.get(f'/student/drive/preview/{did}')
check('A1 pptx 预览分流 PPTist embed 页', r.status_code == 200
      and b'mode=embed&submode=preview' in r.data, str(r.status_code))
check('A2 sandbox 含 allow-same-origin（opaque 修复）',
      b'allow-same-origin' in r.data)
check('A3 JSON/保存地址指向个人网盘路由',
      b'/student/drive/json/' in r.data and b'/student/drive/save-json/' in r.data)
check('A4 PPTX 拉取为 inline URL（无 CD 头前提）',
      b'download_url = &#34;/student/drive/download/' in r.data
      or b'inline=1' in r.data)

r = client.get(f'/student/drive/download/{did}?inline=1')
check('A5 inline 响应无 Content-Disposition attachment',
      r.status_code == 200 and 'attachment' not in
      (r.headers.get('Content-Disposition') or ''),
      r.headers.get('Content-Disposition'))
r = client.get(f'/student/drive/download/{did}')
check('A6 默认下载仍带 attachment',
      'attachment' in (r.headers.get('Content-Disposition') or ''))

r = client.get(f'/student/drive/json/{did}')
check('A7 无缓存 JSON 返回 404（触发浏览器慢路径）', r.status_code == 404)

r = client.post(f'/student/drive/save-json/{did}',
                json={'slides': [{'id': 'x1'}], 'theme': {}},
                headers={'X-CSRFToken': 't'})
check('A8 save-json 正常保存', r.status_code == 200 and r.get_json().get('ok') is True)

r = client.get(f'/student/drive/json/{did}')
body = r.get_data(as_text=True)
check('A9 回读带版本标记 _v=2', r.status_code == 200 and '"_v":2' in body.replace(' ', ''))

r = client.post(f'/student/drive/save-json/{did}',
                json={'slides': [{'id': 'x1',
                                  'note': '<script>alert(1)</script>hello'}]},
                headers={'X-CSRFToken': 't'})
check('A10 危险脚本按剥离式净化处理', r.status_code == 200)
if r.status_code == 200:
    r2 = client.get(f'/student/drive/json/{did}')
    body2 = r2.get_data(as_text=True)
    check('A10b 回读不含 script 且保留正文', '<script' not in body2
          and 'hello' in body2)

r = client.post(f'/student/drive/save-json/{did}', json='not-a-dict',
                headers={'X-CSRFToken': 't'})
check('A11 裸标量数据 400', r.status_code == 400)

as_student(sid2)
r = client.get(f'/student/drive/json/{did}')
check('A12 非归属学生读 JSON 403', r.status_code == 403)
r = client.post(f'/student/drive/save-json/{did}', json={'slides': []},
                headers={'X-CSRFToken': 't'})
check('A13 非归属学生保存 403', r.status_code == 403)
r = client.get(f'/student/drive/edit/{did}')
check('A14 编辑页仅本人可开', r.status_code == 403)

as_student(sid1)
r = client.get(f'/student/drive/edit/{did}')
check('A15 本人编辑页 editor 子模式', r.status_code == 200
      and b'mode=embed&submode=editor' in r.data)

as_admin()
r = client.get(f'/student/drive/preview/{did}')
check('A16 管理员预览（只读 embed）可达', r.status_code == 200
      and b'submode=preview' in r.data)

# 版本过期语义
with app.app_context():
    row = db.session.get(StudentDriveFile, did)
    row.pptist_json = '{"_v":1,"slides":[]}'
    db.session.commit()
as_student(sid1)
r = client.get(f'/student/drive/json/{did}')
check('A17 旧版本(_v=1)数据 404 触发重解析', r.status_code == 404)

# pdf 走 JitViewer
r = client.get(f'/student/drive/preview/{pdfid}')
txt = r.get_data(as_text=True)
check('A18 pdf 走 JitViewer 页', r.status_code == 200 and 'jit-viewer.min.js' in txt)
_jit_match = re.search(r'var jitSupported = \[(.*?)\];', txt, re.S)
_jit_exts = set(re.findall(r"'([^']+)'", _jit_match.group(1))) if _jit_match else set()
check('A19 分派表与 JitViewer 对齐（含 pptx/ppt，供活动/作业入口）', bool(_jit_match)
      and {'pdf', 'docx', 'pptx', 'ppt'} <= _jit_exts)
check('A20 xls OLE2 特例已内置', "ext === 'xls'" in txt)

# ══ B. 小组网盘 ══
as_student(sid1)
r = client.get(f'/groups/drive/download/{gfid}?inline=1')
check('B1 小组网盘 inline 无 CD 头（致命点修复）',
      r.status_code == 200 and 'attachment' not in
      (r.headers.get('Content-Disposition') or ''),
      r.headers.get('Content-Disposition'))

r = client.get(f'/groups/drive/download/{gfid}')
check('B2 默认下载保留 attachment', 'attachment' in
      (r.headers.get('Content-Disposition') or ''))

r = client.get(f'/groups/drive/preview/{gfid}')
check('B3 小组 pptx 预览 embed + inline 拉取', r.status_code == 200
      and b'submode=preview' in r.data and b'inline=1' in r.data)

# ══ C. 全局响应头与静态产物 ══
r = client.get('/static/pptist/index.html')
check('C1 构建入口 no-cache（升级安全）', r.status_code == 200 and
      'no-cache' in (r.headers.get('Cache-Control') or ''),
      r.headers.get('Cache-Control'))
check('C2 内联协议层随产物下发（pptist-host 处理器）',
      b"action === 'load'" in r.data or b"'loadPPTX'" in r.data)

csp = None
for resp in [client.get('/student/drive')]:
    csp = resp.headers.get('Content-Security-Policy')
check('C3 CSP 含 worker-src blob:', csp is not None and 'worker-src' in csp
      and 'blob:' in csp.split('worker-src', 1)[1][:30])

# 清理由 atexit 注册的 _purge() 完成（正常结束与异常退出都会执行）

failed = [i for i, ok in enumerate(results) if not ok]
print(f'\n===== 动态验证完成：{len(results) - len(failed)}/{len(results)} 通过 =====')
sys.exit(1 if failed else 0)