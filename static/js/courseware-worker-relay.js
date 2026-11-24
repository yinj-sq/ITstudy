/**
 * 上传课件 Worker 的同源父页中继。
 *
 * opaque sandbox 中的课件无法直接构造跨源 Worker（浏览器在发请求前即
 * 拒绝），因此在已登录/已鉴权的宿主页创建 Worker，并按消息 id 在宿主与
 * 帧之间转发。Worker URL 仅允许平台镜像路由，帧与宿主窗口双重校验来源。
 */
(function () {
  'use strict';

  function mount(frame, allowedPrefixes) {
    if (!frame || !window.Worker) return {reset: function () {}, destroy: function () {}};
    var workers = {};

    function send(id, type, extra) {
      if (!frame.contentWindow) return;
      var message = {type: type, id: id};
      if (extra) {
        Object.keys(extra).forEach(function (key) { message[key] = extra[key]; });
      }
      frame.contentWindow.postMessage(message, '*');
    }

    function create(id, rawUrl, options) {
      if (typeof id !== 'string' || !/^[A-Za-z0-9_-]{1,80}$/.test(id) ||
          workers[id]) return;
      var url;
      try {
        url = new URL(String(rawUrl), location.href);
      } catch (e) { return; }
      if (url.origin !== location.origin) return;
      var allowed = (allowedPrefixes || []).some(function (prefix) {
        return url.pathname === prefix || url.pathname.indexOf(prefix) === 0;
      });
      if (!allowed) return;
      var worker;
      try {
        worker = new Worker(url.href,
          options && options.type === 'module' ? {type: 'module'} : undefined);
      } catch (e) { return; }
      workers[id] = worker;
      worker.onmessage = function (event) {
        send(id, 'ITSTUDY_WORKER_MESSAGE', {data: event.data});
      };
      worker.onerror = function (event) {
        send(id, 'ITSTUDY_WORKER_ERROR', {
          message: event.message || '',
          filename: event.filename || '',
          lineno: event.lineno || 0,
          colno: event.colno || 0
        });
      };
      worker.onmessageerror = function () {
        send(id, 'ITSTUDY_WORKER_ERROR', {message: 'messageerror'});
      };
    }

    function onMessage(event) {
      if (!frame.contentWindow || event.source !== frame.contentWindow) return;
      if (event.origin !== 'null' && event.origin !== location.origin) return;
      var data = event.data || {};
      if (data.type === 'ITSTUDY_WORKER_CREATE') {
        create(data.id, data.url, data.options);
      } else if (data.type === 'ITSTUDY_WORKER_POST') {
        var worker = workers[data.id];
        if (worker) {
          try { worker.postMessage(data.data); } catch (e) { /* ignore */ }
        }
      } else if (data.type === 'ITSTUDY_WORKER_TERMINATE') {
        var target = workers[data.id];
        if (target) {
          try { target.terminate(); } catch (e) { /* ignore */ }
          delete workers[data.id];
        }
      }
    }

    window.addEventListener('message', onMessage);

    return {
      reset: function () {
        Object.keys(workers).forEach(function (id) {
          try { workers[id].terminate(); } catch (e) { /* ignore */ }
          delete workers[id];
        });
      },
      destroy: function () {
        this.reset();
        window.removeEventListener('message', onMessage);
      }
    };
  }

  window.CoursewareWorkerRelay = {mount: mount};
})();
