/**
 * 全局请求/UI 反馈工具
 *  - fetchWithFeedback: 自动 loading 指示 + 错误提示
 *  - showToast: 轻量级消息提示
 *  - confirmAction: 统一确认弹窗（替代原生 confirm）
 */
(function () {
  if (window.__UI_FEEDBACK__) return;
  window.__UI_FEEDBACK__ = true;

  // ---- CSRF 工具 ----
  function getCookie(name) {
    var parts = document.cookie ? document.cookie.split(';') : [];
    for (var i = 0; i < parts.length; i++) {
      var part = parts[i].trim();
      if (part.indexOf(name + '=') === 0) {
        return decodeURIComponent(part.substring(name.length + 1));
      }
    }
    return '';
  }

  function getCsrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return (meta && meta.getAttribute('content')) || window.CSRF_TOKEN || getCookie('csrf_token') || '';
  }

  function isMutatingMethod(method) {
    return ['POST', 'PUT', 'PATCH', 'DELETE'].indexOf(String(method || 'GET').toUpperCase()) !== -1;
  }

  function isSameOrigin(url) {
    try {
      return new URL(url, window.location.href).origin === window.location.origin;
    } catch (e) {
      return true;
    }
  }

  function ensureFormCsrf(form) {
    if (!form || !isMutatingMethod(form.getAttribute('method'))) return;
    var action = form.getAttribute('action') || window.location.href;
    if (!isSameOrigin(action)) return;
    var token = getCsrfToken();
    if (!token) return;
    var input = form.querySelector('input[name="csrf_token"]');
    if (!input) {
      input = document.createElement('input');
      input.type = 'hidden';
      input.name = 'csrf_token';
      form.appendChild(input);
    }
    input.value = token;
  }

  function configureForms() {
    document.querySelectorAll('form').forEach(ensureFormCsrf);
  }

  document.addEventListener('submit', function (event) {
    ensureFormCsrf(event.target);
  }, true);

  if (window.HTMLFormElement && !window.__ITSTUDY_CSRF_FORM_SUBMIT_PATCHED__) {
    window.__ITSTUDY_CSRF_FORM_SUBMIT_PATCHED__ = true;
    var nativeFormSubmit = window.HTMLFormElement.prototype.submit;
    window.HTMLFormElement.prototype.submit = function () {
      ensureFormCsrf(this);
      return nativeFormSubmit.call(this);
    };
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', configureForms);
  } else {
    configureForms();
  }

  if (window.fetch && !window.__ITSTUDY_CSRF_FETCH_PATCHED__) {
    window.__ITSTUDY_CSRF_FETCH_PATCHED__ = true;
    var nativeFetch = window.fetch.bind(window);
    window.fetch = function (input, init) {
      var options = init ? Object.assign({}, init) : {};
      var method = (options.method || (input && input.method) || 'GET').toUpperCase();
      var url = (typeof input === 'string') ? input : (input && input.url) || window.location.href;
      if (isMutatingMethod(method) && isSameOrigin(url)) {
        var token = getCsrfToken();
        if (token) {
          var headers = new Headers(options.headers || (input && input.headers) || {});
          if (!headers.has('X-CSRFToken') && !headers.has('X-CSRF-Token')) {
            headers.set('X-CSRFToken', token);
          }
          options.headers = headers;
        }
        if (!options.credentials) options.credentials = 'same-origin';
      }
      return nativeFetch(input, options);
    };
  }

  // XHR 补丁：原生 XMLHttpRequest 不会自动带 CSRF 头，而全局 CSRF 校验
  // 对所有写请求强制校验 token（app/__init__.py _csrf_protect）。
  // 分块上传等场景使用原生 XHR，此处统一注入 X-CSRFToken，避免 403。
  if (window.XMLHttpRequest && !window.__ITSTUDY_CSRF_XHR_PATCHED__) {
    window.__ITSTUDY_CSRF_XHR_PATCHED__ = true;
    var NativeXHR = window.XMLHttpRequest;
    var patchedXHR = function () {
      var xhr = new NativeXHR();
      var nativeOpen = xhr.open;
      xhr.open = function (method, url) {
        // 必须先 open 再设头：UNSENT 状态下 setRequestHeader 抛 InvalidStateError。
        // 此前先设头后 open，异常被吞，补丁从未生效（分块上传逐块 403）
        var result = nativeOpen.apply(this, arguments);
        var m = String(method || 'GET').toUpperCase();
        if (isMutatingMethod(m) && isSameOrigin(String(url || ''))) {
          var token = getCsrfToken();
          if (token) {
            try {
              xhr.setRequestHeader('X-CSRFToken', token);
            } catch (e) { /* 调用方已自行设置时忽略 */ }
          }
        }
        return result;
      };
      return xhr;
    };
    patchedXHR.prototype = NativeXHR.prototype;
    // 保持静态属性透传（如 DONE/UNSENT 常量）
    Object.keys(NativeXHR).forEach(function (k) {
      if (typeof NativeXHR[k] !== 'function') patchedXHR[k] = NativeXHR[k];
    });
    window.XMLHttpRequest = patchedXHR;
  }

  function configureAxios() {
    if (!window.axios || window.axios.__ITSTUDY_CSRF_CONFIGURED__) return;
    window.axios.__ITSTUDY_CSRF_CONFIGURED__ = true;
    // CSRF 头统一由下方 XHR/fetch 补丁注入。不能同时启用 axios 内建 XSRF：
    // 两者各写一次同名头，最终值为 "token, token"，服务端校验恒失败
    // （SPA 登录/写操作 403）。
    window.axios.defaults.withCredentials = true;
  }

  configureAxios();
  window.addEventListener('libs-ready', configureAxios);
  var axiosPolls = 0;
  var axiosTimer = setInterval(function () {
    configureAxios();
    axiosPolls++;
    if ((window.axios && window.axios.__ITSTUDY_CSRF_CONFIGURED__) || axiosPolls > 40) {
      clearInterval(axiosTimer);
    }
  }, 250);

  window.getCsrfToken = getCsrfToken;

  // ---- Loading 指示器 ----
  var loadingCount = 0;
  var loadingEl = null;

  function ensureLoader() {
    if (loadingEl) return loadingEl;
    loadingEl = document.createElement('div');
    loadingEl.id = '__topLoader__';
    loadingEl.style.cssText = [
      'position:fixed', 'top:0', 'left:0', 'right:0', 'height:3px',
      'background:linear-gradient(90deg,#0d6efd,#6610f2,#0dcaf0)',
      'z-index:99999', 'transform-origin:left', 'transform:scaleX(0)',
      'transition:transform 0.2s ease', 'pointer-events:none'
    ].join(';');
    document.body.appendChild(loadingEl);
    return loadingEl;
  }

  function showLoader() {
    var el = ensureLoader();
    el.style.transform = 'scaleX(0.7)';
    el.style.opacity = '1';
  }

  function hideLoader() {
    if (!loadingEl) return;
    loadingEl.style.opacity = '0';
    setTimeout(function () {
      if (loadingEl) loadingEl.style.transform = 'scaleX(0)';
    }, 200);
  }

  // ---- Toast 提示 ----
  function showToast(message, type) {
    type = type || 'info';
    var colors = {
      success: '#198754',
      error: '#dc3545',
      warning: '#ffc107',
      info: '#0d6efd'
    };
    var icons = {
      success: 'fa-check-circle',
      error: 'fa-times-circle',
      warning: 'fa-exclamation-triangle',
      info: 'fa-info-circle'
    };
    var color = colors[type] || colors.info;
    var icon = icons[type] || icons.info;
    var toast = document.createElement('div');
    toast.style.cssText = [
      'position:fixed', 'top:20px', 'right:20px', 'z-index:99998',
      'background:#fff', 'border-left:4px solid ' + color,
      'padding:12px 18px', 'border-radius:6px',
      'box-shadow:0 4px 12px rgba(0,0,0,0.15)',
      'min-width:240px', 'max-width:380px',
      'display:flex', 'align-items:center', 'gap:10px',
      'color:#333', 'font-size:14px',
      'transform:translateX(120%)', 'transition:transform 0.3s ease',
      'pointer-events:auto'
    ].join(';');
    toast.innerHTML = '<i class="fas ' + icon + '" style="color:' + color + ';font-size:18px"></i>' +
      '<span style="flex:1"></span>' +
      '<i class="fas fa-times" style="cursor:pointer;color:#999"></i>';
    toast.querySelector('span').textContent = message;
    toast.querySelector('.fa-times').onclick = function () {
      document.body.removeChild(toast);
    };
    document.body.appendChild(toast);
    setTimeout(function () { toast.style.transform = 'translateX(0)'; }, 10);
    setTimeout(function () {
      toast.style.transform = 'translateX(120%)';
      setTimeout(function () {
        if (toast.parentNode) document.body.removeChild(toast);
      }, 300);
    }, 3500);
  }

  // ---- 确认弹窗（替代原生 confirm） ----
  function confirmAction(message, onConfirm, onCancel) {
    if (window.confirm(message)) {
      onConfirm && onConfirm();
    } else {
      onCancel && onCancel();
    }
  }

  // ---- 增强的 fetch 包装 ----
  /**
   * @param {string} url
   * @param {object} options - fetch 选项
   * @param {object} cfg - { loading: true|false, successMsg, errorMsg, silent }
   */
  function fetchWithFeedback(url, options, cfg) {
    cfg = cfg || {};
    options = options || {};
    var showLoading = cfg.loading !== false;
    if (showLoading) {
      loadingCount++;
      if (loadingCount === 1) showLoader();
    }
    return fetch(url, options)
      .then(function (resp) {
        if (!resp.ok) {
          return resp.json().catch(function () {
            throw { message: '请求失败 (' + resp.status + ')' };
          }).then(function (data) {
            throw { message: data.message || ('请求失败 (' + resp.status + ')') };
          });
        }
        return resp.json().catch(function () { return {}; });
      })
      .then(function (data) {
        if (data && data.success === false) {
          throw { message: data.message || '操作失败' };
        }
        if (cfg.successMsg) showToast(cfg.successMsg, 'success');
        return data;
      })
      .catch(function (err) {
        var msg = (err && err.message) || (cfg.errorMsg || '网络错误');
        if (!cfg.silent) showToast(msg, 'error');
        throw err;
      })
      .finally(function () {
        if (showLoading) {
          loadingCount = Math.max(0, loadingCount - 1);
          if (loadingCount === 0) hideLoader();
        }
      });
  }

  window.UI = window.UI || {};
  window.UI.showToast = showToast;
  window.UI.confirmAction = confirmAction;
  window.UI.fetchWithFeedback = fetchWithFeedback;
})();
