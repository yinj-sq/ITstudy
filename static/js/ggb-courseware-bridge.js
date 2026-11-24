(function () {
  'use strict';

  function mount(options) {
    var frame = options.frame;
    var root = decodeURIComponent(new URL(options.resourceRoot, location.origin).pathname);
    var sequence = 0;
    var activeToken = null;
    var pending = null;
    var errorBox = document.createElement('div');
    errorBox.className = 'ggb-course-error';
    errorBox.hidden = true;
    options.container.appendChild(errorBox);
    var overlay = document.createElement('div');
    overlay.className = 'ggb-course-overlay';
    overlay.hidden = true;
    overlay.innerHTML = '<div class="ggb-course-bar"><button type="button">返回课件目录</button>' +
      '<strong></strong><span>GeoGebra 本地引擎</span></div>' +
      '<iframe title="GeoGebra 本地课件播放器" sandbox="allow-scripts allow-same-origin allow-forms allow-modals allow-downloads" allow="fullscreen"></iframe>';
    options.container.appendChild(overlay);
    var engine = overlay.querySelector('iframe');
    var heading = overlay.querySelector('strong');
    var style = document.createElement('style');
    style.textContent = '.ggb-course-overlay{position:absolute;inset:0;z-index:30;display:flex;flex-direction:column;background:#fff}' +
      '.ggb-course-overlay[hidden]{display:none!important}' +
      '.ggb-course-bar{display:flex;align-items:center;gap:12px;padding:6px 10px;background:#1f2937;color:#fff;font:13px system-ui}' +
      '.ggb-course-bar strong{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '.ggb-course-bar button{border:1px solid #64748b;border-radius:6px;padding:5px 10px;background:#334155;color:#fff;cursor:pointer}' +
      '.ggb-course-overlay iframe{flex:1;min-height:0;width:100%;border:0}' +
      '.ggb-course-error{position:absolute;inset:0;z-index:31;display:flex;align-items:center;justify-content:center;padding:24px;background:#fff;color:#b91c1c;font:14px system-ui;text-align:center}' +
      '.ggb-course-error[hidden]{display:none!important}';
    document.head.appendChild(style);

    function close() {
      if (!overlay.hidden) {
        // 普通课件仍是 opaque origin，关闭消息不携带数据且只投递给该帧。
        frame.contentWindow.postMessage({ type: 'ITSTUDY_GGB_CLOSE', token: activeToken }, '*');
      }
      overlay.hidden = true;
      engine.src = 'about:blank';
    }

    function open(url, title) {
      try {
        var file = new URL(url, location.href);
        var path = decodeURIComponent(file.pathname);
        if (file.origin !== location.origin || !path.startsWith(root)) return;
        var relative = path.slice(root.length);
        if (!/\.ggb$/i.test(relative) || /[\\\u0000-\u001f\u007f]/.test(relative) ||
            relative.split('/').some(function (part) {
              return !part || part === '.' || part === '..' || /[. ]$|:|%2e/i.test(part) ||
                /^[^.]{1,8}~[0-9]{1,6}(?:\.[^.]{0,3})?$/i.test(part);
            })) return;
        heading.textContent = title || relative.split('/').pop();
        engine.src = '/study/geogebra/' + options.resourceId + '?' +
          new URLSearchParams({ file: relative, embed: '1' }).toString();
        overlay.hidden = false;
      } catch (e) { /* 非本资源的请求不进入受信播放器 */ }
    }

    window.addEventListener('message', function (event) {
      if (event.source !== frame.contentWindow ||
          (event.origin !== 'null' && event.origin !== location.origin)) return;
      var data = event.data || {};
      if (activeToken && data.token === activeToken && data.type === 'ITSTUDY_GGB_OPEN' && typeof data.url === 'string') {
        open(data.url, typeof data.title === 'string' ? data.title : '');
      }
    });
    overlay.querySelector('button').addEventListener('click', close);

    function load(url, baseUrl) {
      var current = ++sequence;
      close();
      errorBox.hidden = true;
      activeToken = null;
      if (pending) pending.abort();
      var controller = new AbortController();
      pending = controller;
      frame.removeAttribute('srcdoc');
      frame.dataset.sourceUrl = baseUrl || url;
      var source;
      try {
        source = new URL(baseUrl || url, location.href);
      } catch (e) { source = null; }
      if (!source || source.origin !== location.origin ||
          !decodeURIComponent(source.pathname).startsWith(root) ||
          !/\.html?$/i.test(source.pathname)) {
        frame.src = url;
        pending = null;
        return;
      }
      var relative = decodeURIComponent(source.pathname).slice(root.length);
      if (relative.split('/').some(function (part) { return !part || part === '.' || part === '..'; })) {
        errorBox.textContent = '课件路径无效，请返回资源列表重新打开。';
        errorBox.hidden = false;
        pending = null;
        return;
      }
      // 凭证放在路径段，子页面、模块与数据的相对请求不会丢失授权。
      var access = options.access ? Promise.resolve(options.access) :
        fetch('/study/courseware-access/' + options.resourceId + '?' +
          new URLSearchParams({file: relative}).toString(),
          {credentials: 'same-origin', signal: controller.signal})
          .then(function (response) {
            if (!response.ok) throw new Error('课件访问失败（HTTP ' + response.status + '）');
            return response.json();
          });
      access.then(function (data) {
        if (current !== sequence) return;
        var target = new URL(data.base_url, location.href);
        if (target.origin !== location.origin || !data.bridge_token) {
          throw new Error('课件访问凭证无效');
        }
        activeToken = data.bridge_token;
        frame.src = target.href + relative.split('/').map(encodeURIComponent).join('/') +
          source.search + source.hash;
      }).catch(function (error) {
        if (current !== sequence || error.name === 'AbortError') return;
        frame.src = 'about:blank';
        errorBox.textContent = (error.message || '课件加载失败') + '，请返回资源列表重新打开。';
        errorBox.hidden = false;
      }).finally(function () {
        if (pending === controller) pending = null;
      });
    }

    function cancel() {
      sequence++;
      close();
      errorBox.hidden = true;
      activeToken = null;
      if (pending) pending.abort();
      pending = null;
      frame.removeAttribute('srcdoc');
      delete frame.dataset.sourceUrl;
      frame.src = 'about:blank';
    }

    return { load: load, close: close, cancel: cancel };
  }

  window.GGBCoursewareBridge = { mount: mount };
})();
