# -*- coding: utf-8 -*-
"""前端可访问性与 CDN SRI 静态回归（2026-10-26）。"""
import json
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_generated_forms_have_labels_and_close_buttons_have_names():
    upload = (ROOT / 'templates' / 'admin_resources_upload.html').read_text(encoding='utf-8')
    assert 'for="subjectId"' in upload
    assert 'for="file"' in upload
    assert 'for="folderInput"' in upload
    login = (ROOT / 'templates' / 'index.html').read_text(encoding='utf-8')
    for field in ('studentNumber', 'studentPassword', 'studentName',
                  'studentNamePassword'):
        assert f'id="{field}"' in login
        assert f'for="{field}"' in login
    for path in (ROOT / 'templates').glob('*.html'):
        text = path.read_text(encoding='utf-8')
        for tag in re.findall(r'<button\b[^>]*class="[^"]*btn-close[^"]*"[^>]*>',
                              text):
            assert 'aria-label' in tag, f'{path.name}: {tag}'


def test_mobile_container_no_horizontal_overflow_override():
    base = (ROOT / 'templates' / 'base.html').read_text(encoding='utf-8')
    assert 'padding: 0 12px' in base
    assert 'input[placeholder]' in base
    assert '.subject-nav-item.active' in base
    spa = (ROOT / 'frontend' / 'index.html').read_text(encoding='utf-8')
    assert 'text-gray-600' in spa
    assert 'font-size:12px' in spa


def test_resource_action_buttons_wrap_on_narrow_screens():
    admin = (ROOT / 'templates' / 'admin_resources.html').read_text(encoding='utf-8')
    teacher = (ROOT / 'templates' / 'teacher_resource_library.html').read_text(encoding='utf-8')
    assert 'd-flex flex-wrap gap-2' in admin
    assert 'flex-wrap justify-content-between align-items-start' in admin
    assert 'white-space:normal' in teacher


def test_cdn_sri_hashes_are_verified_against_mirrors():
    """哈希于 2026-10-26 对 bootcdn 实际文件校验；防止回退链静默失效。"""
    loader = (ROOT / 'static' / 'js' / 'resource-loader.js').read_text(encoding='utf-8')
    expected = {
        'fontawesome_css': 'sha384-blOohCVdhjmtROpu8+CfTnUWham9nkX7P7OZQMst+RUnhtoY/9qemFAkIKOYxDI3',
        'jquery': 'sha256-/JqT3SQfawRcv/BIHPThkBvs0OEvtFFmqPF/lYI/Cxo=',
        'chart_js': 'sha384-DhxhYObIMeMNGyAG7iK11OHzBIKyEIeRL0ad1iFPAOwZB8iirUlTT0O/WJJUk8+o',
    }
    for key, digest in expected.items():
        assert f"{key}: '{digest}'" in loader
    # 无版本尾部（cdn.tailwindcss.com）不能固定 SRI，否则回退必失败
    assert "tailwind: 'sha384-" not in loader
    cdn = json.loads((ROOT / 'cdn_config.json').read_text(encoding='utf-8'))
    assert cdn['fontawesome']['integrity'] == expected['fontawesome_css']
    assert cdn['chart.js']['integrity'] == expected['chart_js']
    assert cdn['jquery']['integrity'] == expected['jquery']


def test_resource_loader_local_domestic_official_fallback():
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[2], 'utf8');

async function run(successIndex, online = true) {
  const calls = [];
  const head = {
    appendChild(el) {
      el.parentNode = head;
      calls.push({url: el.src || el.href, integrity: el.integrity || ''});
      setImmediate(() => calls.length - 1 === successIndex ? el.onload() : el.onerror());
    },
    removeChild() {},
  };
  const context = vm.createContext({
    window: {location: {origin: 'http://localhost'}, addEventListener() {}},
    navigator: {onLine: online},
    document: {readyState: 'loading', head, body: head,
      addEventListener() {}, querySelectorAll() {return [];},
      createElement() {return {};},
    },
    URL, console, setTimeout, clearTimeout,
  });
  vm.runInContext(source, context);
  const loader = context.window.resourceLoader;
  const config = loader.MIRROR_SOURCES.marked;
  const urls = [config.local, ...config.mirrors];
  let result, error;
  try { result = await loader.tryLoadByType('marked'); }
  catch (e) { error = e.message; }
  assert.deepEqual(calls.map(c => c.url), urls.slice(0, online && successIndex !== null
    ? successIndex + 1 : online ? urls.length : 1));
  assert.equal(calls[0].integrity, '');
  calls.slice(1).forEach(c => assert.match(c.integrity, /^sha384-/));
  if (successIndex !== null) assert.equal(result, urls[successIndex]);
  else assert.ok(error);
}
(async () => {
  await run(0);
  await run(1);
  await run(5);
  await run(null);
  await run(null, false);
  console.log('local/domestic/official/all-failed/offline passed');
})().catch(e => {console.error(e); process.exitCode = 1;});
"""
    result = subprocess.run(
        ['node', '-', str(ROOT / 'static/js/resource-loader.js')],
        input=script, text=True, capture_output=True, timeout=20,
        encoding='utf-8')
    assert result.returncode == 0, result.stdout + result.stderr


def test_csp_allows_domestic_and_official_cdn_fallback():
    from app import create_app
    app = create_app()
    response = app.test_client().get('/admin/login')
    policy = response.headers['Content-Security-Policy']
    directives = {
        part.strip().split()[0]: part.strip().split()[1:]
        for part in policy.split(';') if part.strip()
    }
    for kind in ('script-src', 'style-src', 'font-src'):
        assert "'self'" in directives[kind]
        for domain in ('https://cdn.bootcdn.net', 'https://cdn.staticfile.org',
                       'https://lib.baomitu.com', 'https://npm.elemecdn.com',
                       'https://cdn.jsdelivr.net', 'https://unpkg.com'):
            assert domain in directives[kind]
        assert '*' not in directives[kind]

