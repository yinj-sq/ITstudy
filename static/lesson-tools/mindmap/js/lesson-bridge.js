/* ============================================================
   lesson-bridge.js — 课堂 iframe 集成桥
   仅在被课堂页以 iframe 嵌入时生效：向宿主页提供当前文档的导出，
   并接收宿主页发来的课件文档（保存到课件目录后重新打开）。
   ============================================================ */
(function () {
  if (window.self === window.top) return;

  var TOOL = 'mindmap';
  var ready = false;
  var pending = null;

  function post(action, payload) {
    try {
      parent.postMessage({
        source: 'itstudy-lesson-tool',
        tool: TOOL,
        action: action,
        payload: payload || {},
      }, location.origin);
    } catch (e) { /* ignore */ }
  }

  function sendExport() {
    try {
      post('export-result', { data: Store.toJSON() });
    } catch (e) {
      post('error', { msg: '导出失败：' + ((e && e.message) || '未知错误') });
    }
  }

  function fromJsMind(node) {
    return {
      text: String((node && node.topic) || ''),
      children: ((node && node.children) || []).map(fromJsMind),
    };
  }

  function importDoc(data) {
    // 兼容旧课堂 jsMind 版本保存的 mindmap-*.json（node_tree 格式）
    if (data && data.format === 'node_tree' && data.data) {
      data = {
        root: fromJsMind(data.data),
        links: [],
        title: (data.meta && data.meta.name) || '思维导图',
      };
    }
    if (!Store.setDoc(data)) throw new Error('文件结构不正确');
    Renderer.render();
    Renderer.fit(true);
    post('imported', {});
  }

  window.addEventListener('message', function (e) {
    if (e.origin !== location.origin || e.source !== parent) return;
    var d = e.data || {};
    if (d.source !== 'itstudy-lesson-host' || d.tool !== TOOL) return;
    if (d.action === 'export-request') { sendExport(); return; }
    if (d.action === 'import') {
      var data = d.payload && d.payload.data;
      if (!data) return;
      if (!ready) { pending = data; return; }
      try { importDoc(data); }
      catch (err) { post('error', { msg: '打开失败：' + ((err && err.message) || '文件格式不正确') }); }
    }
  });

  function waitReady() {
    if (typeof App !== 'undefined' && typeof Store !== 'undefined' &&
        typeof Renderer !== 'undefined' && Renderer.result) {
      ready = true;
      post('ready');
      if (pending) {
        try { importDoc(pending); } catch (e) { /* ignore */ }
        pending = null;
      }
      return;
    }
    setTimeout(waitReady, 80);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', waitReady);
  } else {
    waitReady();
  }
})();
