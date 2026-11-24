(function () {
  'use strict';
  window.__ITSTUDY_BOOTSTRAP_LOADED__ = true;
  var currentScript = document.currentScript || {};
  // 沙箱文档的 location.origin 可能是 "null"，但 href 仍保留真实站点地址；
  // 路由逻辑与同源校验使用 URL 解析出的来源，避免 Host 去端口导致不一致。
  var pageOrigin = new URL(location.href).origin;
  var token = currentScript.getAttribute('data-token') || '';
  var contentRoot = currentScript.getAttribute('data-content-root') || '';
  var resourceRoot = currentScript.getAttribute('data-resource-root') || '';
  var contentBase = null;
  try { contentBase = contentRoot ? new URL(contentRoot, location.href) : null; } catch (e) { contentBase = null; }

  // opaque sandbox 读取 localStorage/sessionStorage 会抛 SecurityError，
  // 课件的导航/状态脚本可能在点击时中断。沙箱内改用内存实现，非沙箱
  // 页面继续使用浏览器原生存储。
  function memoryStorage() {
    var data = Object.create(null);
    var api = {
      getItem: function (key) {
        key = String(key);
        return Object.prototype.hasOwnProperty.call(data, key) ? data[key] : null;
      },
      setItem: function (key, value) { data[String(key)] = String(value); },
      removeItem: function (key) { delete data[String(key)]; },
      clear: function () { data = Object.create(null); },
      key: function (index) {
        var keys = Object.keys(data);
        return index >= 0 && index < keys.length ? keys[index] : null;
      }
    };
    try {
      Object.defineProperty(api, 'length', {
        get: function () { return Object.keys(data).length; }
      });
    } catch (e) { /* ignore */ }
    return api;
  }
  function shimStorage(name) {
    var blocked = false;
    try { void window[name].length; } catch (e) { blocked = true; }
    if (!blocked) return;
    var storage = memoryStorage();
    try {
      Object.defineProperty(window, name, {configurable: true, value: storage});
    } catch (e) {
      try { window[name] = storage; } catch (e2) { /* ignore */ }
    }
  }
  shimStorage('localStorage');
  shimStorage('sessionStorage');

  // opaque 沙箱里图片一律按跨源请求处理。课件用 new Image() 加载纹理后
  // 再 canvas.getImageData()（地质/地形类）时，未声明 CORS 会污染画布。
  // 仅对本资源镜像目录内（镜像响应带 ACAO:*）及 data:/blob: 图片，
  // 在设置 src 前补 crossOrigin；页面显式设置的值保持不变。
  function contentOwnedImage(value) {
    try {
      if (/^(?:data|blob):/i.test(value)) return true;
      if (!contentBase) return false;
      var url = new URL(value, document.baseURI);
      if (url.origin !== contentBase.origin) return false;
      return decodeURIComponent(url.pathname).indexOf(
        decodeURIComponent(contentBase.pathname)) === 0;
    } catch (e) { return false; }
  }
  try {
    var imageSrc = Object.getOwnPropertyDescriptor(
      HTMLImageElement.prototype, 'src');
    if (imageSrc && imageSrc.set) {
      Object.defineProperty(HTMLImageElement.prototype, 'src', {
        configurable: true,
        get: imageSrc.get,
        set: function (value) {
          try {
            if (!this.crossOrigin && contentOwnedImage(String(value))) {
              this.crossOrigin = 'anonymous';
            }
          } catch (e) { /* ignore */ }
          return imageSrc.set.call(this, value);
        }
      });
    }
  } catch (e) { /* ignore */ }

  // 课件直接引用官方 deployggb.js 时，官方默认/手写 codebase 仍指向
  // geogebra.org（已被 CSP 拦截）。适配层把引导脚本改写为本地副本，
  // 这里在 GGBApplet 出现时接管构造函数：优先把带 .ggb 的内联 applet
  // 转交同源受信播放器（opaque 沙箱内 GWT 无法访问自己的子帧），其余
  // 情况把官网 codebase 固定到随包完整引擎；课件自带的本地 codebase
  // 保持不动。
  var GGB_LOCAL_CODEBASE = '/static/geogebra/GeoGebra/HTML5/5.0/web3d/';

  function validResourceRel(rel) {
    return !!rel && rel.split('/').every(function (part) {
      return part && part !== '.' && part !== '..' &&
        !/[\\\u0000-\u001f\u007f]/.test(part);
    });
  }

  function appletResource(raw) {
    if (typeof raw !== 'string' || !raw) return null;
    try {
      var target = new URL(raw, document.baseURI);
      var path = decodeURIComponent(target.pathname);
      if (!resourceRoot) return null;
      var resourceUrl = new URL(resourceRoot, location.href);
      var resourcePath = decodeURIComponent(resourceUrl.pathname);
      if (target.origin === resourceUrl.origin &&
          path.indexOf(resourcePath) === 0) {
        var direct = path.slice(resourcePath.length);
        return validResourceRel(direct) && /\.ggb$/i.test(direct)
          ? target.href : null;
      }
      if (!contentBase) return null;
      var contentPath = decodeURIComponent(contentBase.pathname);
      if (target.origin !== contentBase.origin ||
          path.indexOf(contentPath) !== 0) return null;
      var rel = path.slice(contentPath.length);
      if (!validResourceRel(rel) || !/\.ggb$/i.test(rel)) return null;
      return new URL(rel.split('/').map(encodeURIComponent).join('/'),
        resourceUrl).href;
    } catch (e) { return null; }
  }

  function wrapGGBApplet(Native) {
    if (typeof Native !== 'function' || Native.__itstudyOffline) return Native;
    function OfflineGGBApplet() {
      var args = Array.prototype.slice.call(arguments);
      var params = null;
      for (var i = 0; i < args.length; i++) {
        if (args[i] && typeof args[i] === 'object' &&
            typeof args[i].is3D === 'undefined') {
          params = args[i];
          break;
        }
      }
      var applet = new (Function.prototype.bind.apply(Native, [null].concat(args)))();
      try {
        var nativeSet = applet.setHTML5Codebase;
        if (typeof nativeSet === 'function') {
          applet.setHTML5Codebase = function (codebase, offline) {
            var value = codebase === null || codebase === undefined
              ? '' : String(codebase);
            if (!value || /^(?:https?:)?\/\//i.test(value) ||
                value.indexOf('geogebra.org') >= 0) {
              value = GGB_LOCAL_CODEBASE;
            }
            return nativeSet.call(applet, value, true);
          };
          applet.setHTML5Codebase(GGB_LOCAL_CODEBASE, true);
        }
      } catch (e) { /* 非官方版本无此 API 时保持默认 */ }
      // opaque 沙箱运行的 GWT 引擎会因跨帧 document 访问被拒绝；显示
      // 时把本资源的 .ggb 交给宿主已有的受信播放器。
      try {
        var nativeInject = applet.inject;
        applet.inject = function () {
          var item = null;
          if (token && window.parent !== window && params) {
            var file = params.filename || params.fileName;
            var url = appletResource(file);
            if (url) {
              item = {url: url,
                      title: params.title || document.title || ''};
            }
          }
          if (item) {
            report(item);
            return applet;
          }
          return nativeInject.apply(applet, arguments);
        };
      } catch (e) { /* ignore */ }
      return applet;
    }
    OfflineGGBApplet.prototype = Native.prototype;
    try {
      Object.defineProperty(OfflineGGBApplet, '__itstudyOffline', {value: true});
    } catch (e) { /* ignore */ }
    return OfflineGGBApplet;
  }
  if (typeof window.GGBApplet === 'function') {
    window.GGBApplet = wrapGGBApplet(window.GGBApplet);
  } else {
    var nativeGGBApplet;
    try {
      Object.defineProperty(window, 'GGBApplet', {
        configurable: true,
        get: function () { return nativeGGBApplet; },
        set: function (value) { nativeGGBApplet = wrapGGBApplet(value); }
      });
    } catch (e) { /* 个别内核不可重定义时由课件自行加载本地引擎 */ }
  }

  // 局域网 HTTP（非安全上下文）不提供 crypto.randomUUID；知了等上传 SPA
  // 会在启动路径直接调用。getRandomValues 在非安全上下文可用，按规范生成
  // RFC 4122 v4 UUID，避免整个 SPA 在 `crypto.randomUUID is not a function`
  // 处中断（HTTPS/localhost 下保留原生实现）。
  if (window.crypto && typeof crypto.randomUUID !== 'function') {
    var randomUuid = function () {
      var bytes = crypto.getRandomValues(new Uint8Array(16));
      bytes[6] = (bytes[6] & 0x0f) | 0x40;
      bytes[8] = (bytes[8] & 0x3f) | 0x80;
      var hex = Array.prototype.map.call(bytes, function (b) {
        return ('0' + b.toString(16)).slice(-2);
      }).join('');
      return hex.slice(0, 8) + '-' + hex.slice(8, 12) + '-' +
        hex.slice(12, 16) + '-' + hex.slice(16, 20) + '-' + hex.slice(20);
    };
    try {
      Object.defineProperty(crypto, 'randomUUID',
        {value: randomUuid, configurable: true, writable: true});
    } catch (e) {
      try { crypto.randomUUID = randomUuid; } catch (e2) { /* ignore */ }
    }
  }

  // opaque sandbox 不能直接构造跨源 Worker（浏览器在发请求前即拒绝）；
  // 交给同源宿主页创建 Worker 并按消息 id 中继（courseware-worker-relay.js）。
  // 某些内核的 location.origin 仍返回 URL 来源，window.origin 才是沙箱来源。
  if ((window.origin === 'null' || location.origin === 'null') &&
      window.parent !== window && window.Worker) {
    if (window.console && console.error) {
      console.error('[ITSTUDY-WORKER-SHIM-ON]', location.href.slice(0, 120));
    }
    document.documentElement.setAttribute('data-itstudy-worker-shim', '1');
    window.__ITSTUDY_WORKER_RELAY__ = true;
    var NativeWorker = window.Worker;
    var workerSeq = 0;
    window.Worker = function (url, options) {
      var id = 'w' + (++workerSeq) + '-' +
        Math.random().toString(36).slice(2, 10);
      var onmessage = null;
      var onerror = null;
      var messageListeners = [];
      var errorListeners = [];
      var queued = [];
      function emitMessage(data) {
        var event = {data: data};
        if (onmessage) onmessage(event);
        messageListeners.forEach(function (fn) { fn(event); });
      }
      function emitError(info) {
        if (onerror) onerror(info);
        errorListeners.forEach(function (fn) { fn(info); });
        if (window.console && console.error) {
          console.error('[ITSTUDY-WORKER-ERROR]', info.message || 'Worker failed');
        }
      }
      var proxy = {
        postMessage: function (data) {
          window.parent.postMessage(
            {type: 'ITSTUDY_WORKER_POST', id: id, data: data}, '*');
        },
        terminate: function () {
          window.parent.postMessage(
            {type: 'ITSTUDY_WORKER_TERMINATE', id: id}, '*');
        },
        addEventListener: function (type, fn) {
          if (type === 'message') messageListeners.push(fn);
          else if (type === 'error') errorListeners.push(fn);
        },
        removeEventListener: function (type, fn) {
          var list = type === 'message' ? messageListeners :
            type === 'error' ? errorListeners : null;
          if (!list) return;
          var index = list.indexOf(fn);
          if (index >= 0) list.splice(index, 1);
        }
      };
      Object.defineProperty(proxy, 'onmessage', {
        get: function () { return onmessage; },
        set: function (fn) {
          onmessage = typeof fn === 'function' ? fn : null;
          while (onmessage && queued.length) onmessage({data: queued.shift()});
        }
      });
      Object.defineProperty(proxy, 'onerror', {
        get: function () { return onerror; },
        set: function (fn) { onerror = typeof fn === 'function' ? fn : null; }
      });
      window.addEventListener('message', function (event) {
        var data = event.data || {};
        if (event.source !== window.parent || data.id !== id) return;
        if (data.type === 'ITSTUDY_WORKER_MESSAGE') {
          if (onmessage) onmessage({data: data.data});
          else queued.push(data.data);
          messageListeners.forEach(function (fn) { fn({data: data.data}); });
        } else if (data.type === 'ITSTUDY_WORKER_ERROR') {
          emitError({message: data.message, filename: data.filename,
                     lineno: data.lineno, colno: data.colno});
        }
      });
      var absolute;
      try { absolute = new URL(String(url), document.baseURI).href; }
      catch (e) { absolute = String(url); }
      window.parent.postMessage({
        type: 'ITSTUDY_WORKER_CREATE', id: id, url: absolute,
        options: {type: options && options.type || ''}
      }, '*');
      return proxy;
    };
    window.Worker.prototype = NativeWorker.prototype;
  }
  if (!token) return;

  if (location.hash.indexOf('#/') === 0) {
    var entry = new URL(location.href);
    entry.hash = '';
    var logicalRoute = location.hash.slice(1);
    var realHistory = window.history;
    var realPush = realHistory.pushState.bind(realHistory);
    var realReplace = realHistory.replaceState.bind(realHistory);

    function routeLocation() {
      var hash = location.hash;
      var url = new URL(hash.indexOf('#/') === 0 ? hash.slice(1) : logicalRoute, pageOrigin + '/');
      url.assign = location.assign.bind(location);
      url.replace = location.replace.bind(location);
      return url;
    }

    function routeState(nativeWrite, state, title, url) {
      if (typeof url === 'string' && url.indexOf('#/') === 0) {
        logicalRoute = url.slice(1);
      } else if (url !== undefined && url !== null && url !== '') {
        var next = new URL(url, routeLocation().href);
        if (next.origin !== pageOrigin) return nativeWrite(state, title, url);
        logicalRoute = next.pathname + next.search + next.hash;
      }
      var physical = new URL(entry.href);
      physical.hash = logicalRoute;
      nativeWrite(state, title, physical.href);
    }

    var routerHistory = {
      get state() { return realHistory.state; },
      get length() { return realHistory.length; },
      go: realHistory.go.bind(realHistory),
      pushState: function (state, title, url) { routeState(realPush, state, title, url); },
      replaceState: function (state, title, url) { routeState(realReplace, state, title, url); }
    };
    // BrowserRouter 读取逻辑路由；真实地址只改 hash，保留沙箱权限与资源基址。
    globalThis.__ITSTUDY_COURSEWARE_ROUTER_WINDOW__ = new Proxy(window, {
      get: function (target, key) {
        if (key === 'location') return routeLocation();
        if (key === 'history') return routerHistory;
        var value = Reflect.get(target, key, target);
        return typeof value === 'function' ? value.bind(target) : value;
      }
    });
    realHistory.pushState = routerHistory.pushState;
    realHistory.replaceState = routerHistory.replaceState;
    // 浏览器前进/后退产生 popstate；先同步逻辑路由，Router 的监听器随后
    // 读取 Proxy window.location 即可得到正确路径。
    window.addEventListener('popstate', function () {
      if (location.hash.indexOf('#/') === 0) logicalRoute = location.hash.slice(1);
    });
  }
  if (window.parent === window) return;

  function report(item) {
    // 嵌套的 opaque 父帧不能作为 targetOrigin；宿主另验窗口、握手和资源路径。
    window.parent.postMessage({type: 'ITSTUDY_GGB_OPEN', token: token,
      url: item.url, title: item.title || ''}, '*');
  }

  function selection(src) {
    try {
      if (!contentBase) return null;
      var viewer = new URL(src, document.baseURI);
      var file = viewer.searchParams.get('file');
      var viewerPath = decodeURIComponent(viewer.pathname);
      var contentPath = decodeURIComponent(contentBase.pathname);
      if (viewer.origin !== contentBase.origin || !viewerPath.startsWith(contentPath) ||
          !/\.html?$/i.test(viewer.pathname) || !file || !/\.ggb$/i.test(file)) return null;
      var target = new URL(file.split('/').map(encodeURIComponent).join('/'), viewer);
      if (resourceRoot) {
        var path = decodeURIComponent(target.pathname);
        if (!path.startsWith(contentPath)) return null;
        target = new URL(path.slice(contentPath.length).split('/').map(encodeURIComponent).join('/'),
          new URL(resourceRoot, location.href));
      }
      return {url: target.href, title: viewer.searchParams.get('title') || ''};
    } catch (e) { return null; }
  }

  function inspect(frame) {
    var item = selection(frame.getAttribute('src') || '');
    if (!item) return;
    frame.src = 'about:blank';
    report(item);
  }

  function scan(node) {
    if (node.nodeType !== 1) return;
    if (node.tagName === 'IFRAME') inspect(node);
    node.querySelectorAll('iframe[src]').forEach(inspect);
  }

  new MutationObserver(function (records) {
    records.forEach(function (record) {
      if (record.type === 'attributes') {
        if (record.target.tagName === 'IFRAME') inspect(record.target);
      } else record.addedNodes.forEach(scan);
    });
  }).observe(document.documentElement, {
    childList: true, subtree: true, attributes: true, attributeFilter: ['src']
  });

  document.addEventListener('click', function (event) {
    var link = event.target.closest && event.target.closest('a[href]');
    if (!link || link.hasAttribute('download')) return;
    var item = selection(link.href);
    if (!item) return;
    event.preventDefault();
    report(item);
  }, true);

  window.addEventListener('message', function (event) {
    var data = event.data || {};
    if (data.type === 'ITSTUDY_GGB_OPEN' && data.token === token &&
        (event.origin === 'null' || event.origin === pageOrigin) &&
        Array.from(document.querySelectorAll('iframe')).some(function (frame) {
          return event.source === frame.contentWindow;
        })) {
      report(data);
      return;
    }
    if (event.source !== window.parent ||
        (event.origin !== pageOrigin && event.origin !== 'null')) return;
    if (data.type === 'ITSTUDY_GGB_CLOSE' && data.token === token) {
      document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
      document.querySelectorAll('iframe').forEach(function (frame) {
        frame.contentWindow.postMessage(data, '*');
      });
    }
  });
})();
