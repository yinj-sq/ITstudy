/**
 * 认证状态组合式函数 (Composable)
 * 提供登录状态管理和认证操作
 */
(function () {
  function useAuth() {
    // ========== 响应式状态 ==========
    var user = Vue.reactive({
      studentId: null,
      isAdmin: false,
      name: ''
    });

    var loading = Vue.ref(true);
    var error = Vue.ref(null);

    // ========== 认证状态缓存（供路由守卫复用） ==========
    // 路由守卫每次导航都请求 /auth/status 会产生不必要的网络往返；
    // 这里在 TTL 内复用内存状态。login/adminLogin/logout 成功时会刷新
    // 缓存标记，保证登录/登出后首次导航立即读到最新状态。
    var _authCacheTs = 0;
    var AUTH_CACHE_TTL = 60 * 1000; // 60 秒

    function _touchAuthCache() {
      _authCacheTs = Date.now();
    }

    /**
     * 认证状态缓存是否仍然新鲜（TTL 内视为新鲜，可跳过 /auth/status 请求）
     * @returns {boolean}
     */
    function isAuthCacheFresh() {
      return Date.now() - _authCacheTs < AUTH_CACHE_TTL;
    }

    // ========== 方法 ==========

    /**
     * 检查当前登录状态
     * 调用 /api/auth/status 接口验证会话
     */
    async function checkAuth() {
      loading.value = true;
      error.value = null;

      try {
        var response = await window.authAPI.status();
        var data = response.data;

        if (data && data.success) {
          user.studentId = data.data ? data.data.student_id || null : null;
          user.isAdmin = data.data ? !!data.data.is_admin : false;
          user.name = data.data ? data.data.name || '' : '';
        } else {
          resetUser();
        }
      } catch (e) {
        // 未登录或网络异常
        resetUser();
      } finally {
        loading.value = false;
        _touchAuthCache();
      }
    }

    /**
     * 重置用户状态
     */
    function resetUser() {
      user.studentId = null;
      user.isAdmin = false;
      user.name = '';
    }

    /**
     * 学生登录
     * @param {Object} credentials - { student_number?, name?, password }
     * @returns {Promise<Object>} 登录结果
     */
    async function login(credentials) {
      error.value = null;

      try {
        var response = await window.authAPI.login(credentials);
        var data = response.data;

        if (data && data.success) {
          user.studentId = data.data ? data.data.student_id || null : null;
          user.name = data.data ? data.data.name || '' : '';
          user.isAdmin = false;
        }

        _touchAuthCache();
        return data;
      } catch (e) {
        var errMsg = '登录失败，请重试';
        if (e.response && e.response.data && e.response.data.message) {
          errMsg = e.response.data.message;
        }
        error.value = errMsg;
        throw e;
      }
    }

    /**
     * 管理员登录
     * @param {string} username - 用户名
     * @param {string} password - 密码
     * @returns {Promise<Object>} 登录结果
     */
    async function adminLogin(username, password) {
      error.value = null;

      try {
        var response = await window.authAPI.adminLogin({
          username: username,
          password: password
        });
        var data = response.data;

        if (data && data.success) {
          user.studentId = null;
          user.name = data.data ? data.data.username || username : username;
          user.isAdmin = true;
        }

        _touchAuthCache();
        return data;
      } catch (e) {
        var errMsg = '登录失败，请检查用户名和密码';
        if (e.response && e.response.data && e.response.data.message) {
          errMsg = e.response.data.message;
        }
        error.value = errMsg;
        throw e;
      }
    }

    /**
     * 退出登录
     * @returns {Promise<Object>}
     */
    async function logout() {
      error.value = null;

      try {
        var response = await window.authAPI.logout();
        var data = response.data;
        resetUser();
        _touchAuthCache();
        return data;
      } catch (e) {
        resetUser();
        _touchAuthCache();
        throw e;
      }
    }

    /**
     * 判断当前用户是否已登录
     * @returns {boolean}
     */
    function isAuthenticated() {
      return !!(user.studentId || user.isAdmin);
    }

    /**
     * 获取当前用户角色
     * @returns {string} 'student' | 'admin' | 'guest'
     */
    function getUserRole() {
      if (user.isAdmin) return 'admin';
      if (user.studentId) return 'student';
      return 'guest';
    }

    return {
      user: user,
      loading: loading,
      error: error,
      checkAuth: checkAuth,
      login: login,
      adminLogin: adminLogin,
      logout: logout,
      isAuthenticated: isAuthenticated,
      getUserRole: getUserRole,
      isAuthCacheFresh: isAuthCacheFresh
    };
  }

  // 暴露到全局
  window.useAuth = useAuth;
})();
