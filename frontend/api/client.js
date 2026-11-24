/**
 * Axios 实例和拦截器
 * 全局 API 客户端配置
 *
 * 加载时序说明：本文件以同步 <script> 加载，而 axios 由 resource-loader
 * 多源异步注入（libs-ready 流程，见 index.html）。此前缺陷：文件执行瞬间
 * window.axios 为 undefined → configureAxiosCsrf(undefined) 抛 TypeError
 * → IIFE 中止 → window.apiClient 从未挂载，整个 SPA 的 API 层不可用。
 * 修复：初始化前轮询等待 axios 就绪（与 app.js startAppWhenReady 同策略）。
 */
(function () {
  var _waitMs = 0;

  function initApiClient() {
    if (typeof window.axios === 'undefined') {
      _waitMs += 50;
      if (_waitMs % 2000 === 0) {
        console.warn('[client] 等待 axios 加载中... (' + (_waitMs / 1000) + 's)');
      }
      setTimeout(initApiClient, 50);
      return;
    }
    const { axios } = window;

  function getCookie(name) {
    const parts = document.cookie ? document.cookie.split(';') : [];
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i].trim();
      if (part.indexOf(name + '=') === 0) {
        return decodeURIComponent(part.substring(name.length + 1));
      }
    }
    return '';
  }

  function isMutating(method) {
    return ['POST', 'PUT', 'PATCH', 'DELETE'].includes(String(method || 'GET').toUpperCase());
  }

  function isSameOrigin(url) {
    try {
      return new URL(url, window.location.href).origin === window.location.origin;
    } catch (e) {
      return true;
    }
  }

  function configureAxiosCsrf(instance) {
    // CSRF 头统一由 static/js/ui-feedback.js 的 XHR/fetch 补丁注入：
    // axios 内建 XSRF 与补丁同时注入会把请求头写成 "token, token"，
    // 服务端 compare_digest 恒失败（SPA 登录 403）。此处只保留凭据设置。
    instance.defaults.withCredentials = true;
  }

  // 全局 axios 的 CSRF 由 static/js/ui-feedback.js 统一配置（base.html /
  // index.html 均已同步加载）；此处只配置 SPA 自己的实例，避免重复注入。

  // 创建 Axios 实例
  const apiClient = axios.create({
    baseURL: '/api',
    withCredentials: true,
    // 不配置 xsrfCookieName/xsrfHeaderName：CSRF 头统一由
    // static/js/ui-feedback.js 的 XHR/fetch 补丁注入；axios 内建 XSRF
    // 与补丁同时生效会把头写成 "token, token"（服务端校验恒失败）
    headers: {
      'Content-Type': 'application/json'
    }
  });
  configureAxiosCsrf(apiClient);

  // ========== 请求拦截器 ==========
  apiClient.interceptors.request.use(
    function (config) {
      // 添加 X-Requested-With 头，标识 AJAX 请求
      config.headers['X-Requested-With'] = 'XMLHttpRequest';
      return config;
    },
    function (error) {
      return Promise.reject(error);
    }
  );

  // ========== 响应拦截器 ==========
  apiClient.interceptors.response.use(
    function (response) {
      return response;
    },
    function (error) {
      if (error.response) {
        const status = error.response.status;

        // 401 Unauthorized → 跳转对应登录页
        if (status === 401) {
          // 先重置本地登录态：否则守卫在 60s TTL 内仍视为"已登录"，
          // 会把跳转回 guest 页的用户再重定向回业务页 → 反复 401 死循环
          if (window._appAuth) {
            window._appAuth.resetUser();
          }
          // 获取当前路由（如果 Vue Router 已初始化）
          if (window._appRouter) {
            const currentRoute = window._appRouter.currentRoute.value;
            // 如果是需要认证的页面，跳转到对应角色的登录页
            if (currentRoute && currentRoute.meta && currentRoute.meta.auth) {
              // 管理员页面 → 管理员登录页；学生页面 → 学生登录页
              const loginPath = currentRoute.meta.auth === 'admin' ? '/admin/login' : '/';
              window._appRouter.push(loginPath);
            }
          } else {
            // 兜底：直接重定向
            window.location.href = '/';
          }
        }

        // 403 Forbidden
        if (status === 403) {
          console.error('权限不足:', error.response.data);
          if (window.UI && window.UI.showToast) {
            const msg = (error.response.data && error.response.data.message) || '没有权限执行此操作';
            window.UI.showToast(msg, 'error');
          }
        }

        // 500 Server Error
        if (status >= 500) {
          console.error('服务器错误:', error.response.data);
          if (window.UI && window.UI.showToast) {
            const msg = (error.response.data && error.response.data.message) || '服务器错误，请稍后重试';
            window.UI.showToast(msg, 'error');
          }
        }
      } else if (error.request) {
        // 网络错误（无响应）
        console.error('网络请求失败，请检查网络连接');
      }

      return Promise.reject(error);
    }
  );

  // 暴露到全局
  window.apiClient = apiClient;
  }

  initApiClient();
})();
