/**
 * 认证相关 API
 */
(function () {
  const authAPI = {
    /**
     * 获取当前登录状态
     * @returns {Promise}
     */
    status: function () {
      return window.apiClient.get('/auth/status');
    },

    /**
     * 学生登录
     * @param {Object} data - { name, class_name }
     * @returns {Promise}
     */
    login: function (data) {
      return window.apiClient.post('/auth/login', data);
    },

    /**
     * 管理员登录
     * @param {Object} data - { username, password }
     * @returns {Promise}
     */
    adminLogin: function (data) {
      return window.apiClient.post('/auth/admin-login', data);
    },

    /**
     * 退出登录
     * @returns {Promise}
     */
    logout: function () {
      return window.apiClient.post('/auth/logout');
    }
  };

  window.authAPI = authAPI;
})();
