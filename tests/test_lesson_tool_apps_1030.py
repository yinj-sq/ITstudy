# -*- coding: utf-8 -*-
"""课堂图板迁移回归（2026-10-30）。

覆盖：
- 流程拓扑图画板 / 思维导图静态应用与课堂页 iframe 接入
- 课件目录 tool-docs 保存/列表/读取（教师写、学生读、隐藏资源 403）
- flow-*.json 不进入普通资源文件卡片
- /api/ai/lesson_eval 使用当前登录身份解析的 AI 配置，客户端不能覆盖
"""
import pathlib
import shutil
import uuid

import pytest

from app import create_app
from app.extensions import cache, db
from app.models import Log, Resource, Student

ROOT = pathlib.Path(__file__).resolve().parent.parent
UPLOADS = ROOT / 'static' / 'uploads'
CSRF = 'tool-doc-csrf'


@pytest.fixture(scope='module')
def app():
    return create_app()


@pytest.fixture(scope='module')
def student_id(app):
    with app.app_context():
        stu = Student(name='__tool_doc_student__',
                      student_number=f'__td_{uuid.uuid4().hex[:10]}',
                      password_hash='x', is_activated=True,
                      has_changed_password=True)
        db.session.add(stu)
        db.session.commit()
        sid = stu.id
    yield sid
    with app.app_context():
        Student.query.filter_by(id=sid).delete(synchronize_session=False)
        db.session.commit()
    cache.delete(f'session:check:{sid}')


def test_static_apps_and_lesson_template_wired():
    flow = ROOT / 'static' / 'lesson-tools' / 'flow' / 'index.html'
    mm_dir = ROOT / 'static' / 'lesson-tools' / 'mindmap'
    assert flow.is_file()
    assert (mm_dir / 'index.html').is_file()
    assert (mm_dir / 'styles.css').is_file()
    assert (mm_dir / 'js' / 'lesson-bridge.js').is_file()

    flow_html = flow.read_text(encoding='utf-8')
    assert 'ITSTUDY_HOSTED' in flow_html
    assert '/api/ai/lesson_eval' in flow_html
    assert 'itstudy-lesson-tool' in flow_html
    assert 'itstudy-lesson-host' in flow_html
    # 集成模式下不再把用户填写的 Key 存进 localStorage 再直连上游
    assert 'Authorization' in flow_html  # 独立离线模式仍保留
    assert mm_dir.joinpath('js', 'app.js').is_file()

    page = (ROOT / 'templates' / 'study_lesson.html').read_text(encoding='utf-8')
    assert 'id="flowFrame"' in page and 'id="mindmapFrame"' in page
    assert 'lesson-tools/flow/index.html' in page
    assert 'lesson-tools/mindmap/index.html' in page
    assert 'drawflow.min.js' not in page and 'jsmind.js' not in page
    assert 'id="toolNameModal"' in page


def test_tool_doc_save_list_get_and_permissions(app, student_id):
    sfx = uuid.uuid4().hex[:8]
    title = f'__tool_doc_res_{sfx}'
    dir_name = f'__tool_doc_dir_{sfx}'
    hidden_title = f'__tool_doc_hidden_{sfx}'
    rid = hid = None
    target = UPLOADS / dir_name
    try:
        target.mkdir(parents=True, exist_ok=True)
        (target / 'index.html').write_text('<html>x</html>', encoding='utf-8')
        with app.app_context():
            res = Resource(title=title,
                           url=f'/static/uploads/{dir_name}/index.html',
                           show_in_student=True, show_in_classroom=True,
                           is_public=True, quiz_mode='none')
            hidden = Resource(title=hidden_title,
                              url=f'https://example.com/hidden-{sfx}',
                              show_in_student=False, show_in_classroom=False,
                              quiz_mode='none')
            db.session.add_all([res, hidden])
            db.session.commit()
            rid, hid = res.id, hidden.id

        admin = app.test_client()
        with admin.session_transaction() as s:
            s.update(is_admin=True, admin_name='管理员', csrf_token=CSRF)

        payload = {'tool': 'flow', 'name': f'课堂{sfx}', 'data': {
            'app': '流程拓扑图画板', 'v': 7,
            'nodes': [{'id': 'n1', 'shape': 'startend', 'text': '开始'}],
            'edges': [],
        }}
        resp = admin.post(f'/study/lesson/{rid}/tool-docs/save', json=payload,
                          headers={'X-CSRFToken': CSRF})
        assert resp.status_code == 200 and resp.get_json()['success']
        filename = f'flow-课堂{sfx}.json'
        assert (target / filename).is_file()

        listed = admin.get(f'/study/lesson/{rid}/tool-docs/list?tool=flow').get_json()
        assert filename in listed['files']
        got = admin.get(
            f'/study/lesson/{rid}/tool-docs/get?tool=flow&name={filename}'
        ).get_json()
        assert got['success'] and got['data']['nodes'][0]['text'] == '开始'

        # 旧思维导图前缀与新接口共存；不能拿 mindmap 名去读 flow
        bad = admin.get(
            f'/study/lesson/{rid}/tool-docs/get?tool=mindmap&name={filename}')
        assert bad.status_code == 400
        assert admin.get(
            f'/study/lesson/{rid}/tool-docs/list?tool=ppt').status_code == 400
        assert admin.post(
            f'/study/lesson/{rid}/tool-docs/save',
            json={'tool': 'flow', 'name': '../evil', 'data': {'nodes': []}},
            headers={'X-CSRFToken': CSRF}).status_code == 400
        assert admin.post(
            f'/study/lesson/{rid}/tool-docs/save',
            json={'tool': 'flow', 'name': 'x', 'data': {}},
            headers={'X-CSRFToken': CSRF}).status_code == 400  # 空画布拒绝
        assert admin.post(
            f'/study/lesson/{rid}/tool-docs/save',
            json={'tool': 'flow', 'name': 'y', 'data': []},
            headers={'X-CSRFToken': CSRF}).status_code == 400
        assert admin.post(
            f'/study/lesson/{rid}/tool-docs/save',
            json={'tool': 'mindmap', 'name': 'm', 'data': {'root': {'text': '主题'}}},
            headers={'X-CSRFToken': CSRF}).status_code == 200
        assert (target / 'mindmap-m.json').is_file()

        # 隐藏资源不可写
        assert admin.post(
            f'/study/lesson/{hid}/tool-docs/save', json=payload,
            headers={'X-CSRFToken': CSRF}).status_code == 403

        # 学生：可见资源可读、不可写；隐藏资源不可读
        student = app.test_client()
        with student.session_transaction() as s:
            s.update(student_id=student_id, student_name='测试学生',
                     csrf_token=CSRF)
        assert student.get(
            f'/study/lesson/{rid}/tool-docs/list?tool=flow').status_code == 200
        assert student.get(
            f'/study/lesson/{rid}/tool-docs/get?tool=flow&name={filename}'
        ).status_code == 200
        assert student.post(
            f'/study/lesson/{rid}/tool-docs/save', json=payload,
            headers={'X-CSRFToken': CSRF}).status_code == 403
        assert student.get(
            f'/study/lesson/{hid}/tool-docs/list?tool=flow').status_code == 403
        assert student.get(
            f'/study/lesson/{hid}/tool-docs/get?tool=flow&name={filename}'
        ).status_code == 403

        # 资源编辑页不把 flow-*.json 当成普通课件文件
        edit = admin.get(f'/admin/resources/edit/{rid}').get_data(as_text=True)
        assert filename not in edit
        assert 'index.html' in edit
    finally:
        with app.app_context():
            for item_id in (rid, hid):
                if item_id is not None:
                    Log.query.filter(Log.detail.contains(
                        title if item_id == rid else hidden_title)).delete(
                        synchronize_session=False)
                    Resource.query.filter_by(id=item_id).delete(synchronize_session=False)
            db.session.commit()
            cache.delete(f'study:files:{dir_name}')
        shutil.rmtree(target, ignore_errors=True)


def test_diagram_eval_endpoint_uses_logged_in_ai_config(app, student_id, monkeypatch):
    from app.blueprints import ai as ai_module

    seen = {}

    def fake_resolve():
        return True, {
            'api_key': 'server-side-key', 'api_url': 'https://ai.example/v1',
            'model': 'server-model', 'provider': 'openai',
            'max_tokens': 2048, 'temperature': 0.7,
            'needs_dns_pinning': False, 'config_mode': 'admin',
            'vision_enabled': False,
        }, 200

    def fake_call(provider, api_key, api_url, model, messages, max_tokens,
                  temperature, stream=False, needs_dns_pinning=False,
                  timeout=120, deepseek_options=None):
        seen.update(provider=provider, api_key=api_key, api_url=api_url,
                    model=model, messages=messages, max_tokens=max_tokens,
                    temperature=temperature, stream=stream, timeout=timeout)
        return True, '三条建议', 200, 'stop', None

    monkeypatch.setattr(ai_module, '_resolve_effective_config', fake_resolve)
    monkeypatch.setattr(ai_module, '_call_chat', fake_call)

    client = app.test_client()
    with client.session_transaction() as s:
        s.update(student_id=student_id, student_name='测试学生', csrf_token=CSRF)

    resp = client.post('/api/ai/lesson_eval', json={
        'mode': 'flow',
        'score': 76,
        'issues': ['判断框只有一条出边'],
        'nodes': [
            {'id': 'n1', 'shape': 'startend', 'text': '开始'},
            {'id': 'n2', 'shape': 'decision', 'text': '下雨吗'},
        ],
        'edges': [{'from': 'n1', 'to': 'n2', 'label': ''}],
        # 客户端试图覆盖配置，服务端必须忽略
        'api_key': 'client-key', 'api_url': 'https://evil.example', 'model': 'evil-model',
    }, headers={'X-CSRFToken': CSRF})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {'success': True, 'reply': '三条建议', 'model': 'server-model'}
    assert seen['api_key'] == 'server-side-key'
    assert seen['api_url'] == 'https://ai.example/v1'
    assert seen['model'] == 'server-model'
    assert seen['max_tokens'] == 800 and seen['timeout'] == 60
    user_prompt = seen['messages'][1]['content']
    assert '[开始/结束] 开始' in user_prompt
    assert '[判断] 下雨吗' in user_prompt
    assert '「开始」→「下雨吗」' in user_prompt
    assert '判断框只有一条出边' in user_prompt
    assert 'evil' not in str(seen)
    assert 'server-side-key' not in str(body)

    # 空画布拒绝，不调用上游
    seen.clear()
    empty = client.post('/api/ai/lesson_eval', json={'nodes': [], 'edges': []},
                        headers={'X-CSRFToken': CSRF})
    assert empty.status_code == 400
    assert not seen


def test_diagram_eval_prompt_is_bounded():
    from app.blueprints.ai import _build_diagram_eval_prompt

    nodes = [{'id': f'n{i}', 'shape': 'process', 'text': 'x' * 500}
             for i in range(500)]
    prompt = _build_diagram_eval_prompt({
        'mode': 'topo', 'score': 88, 'nodes': nodes,
        'edges': [{'from': 'n0', 'to': 'n1', 'label': 'y' * 200}],
        'issues': ['问题' * 100] * 100,
    })
    assert '网络拓扑图' in prompt
    assert len(prompt) <= 12100
    assert prompt.endswith('（内容过长，已截断）')
