/**
 * 学习资源相关 API
 */
(function () {
  const resourcesAPI = {
    /**
     * 获取资源列表
     * @returns {Promise}
     */
    list: function () {
      return window.apiClient.get('/resources');
    },

    /**
     * 创建资源
     * @param {Object} data - 资源数据
     * @returns {Promise}
     */
    create: function (data) {
      return window.apiClient.post('/resources', data);
    },

    /**
     * 更新资源
     * @param {number|string} id - 资源 ID
     * @param {Object} data - 更新数据
     * @returns {Promise}
     */
    update: function (id, data) {
      return window.apiClient.put('/resources/' + id, data);
    },

    /**
     * 删除资源
     * @param {number|string} id - 资源 ID
     * @returns {Promise}
     */
    delete: function (id) {
      return window.apiClient.delete('/resources/' + id);
    }
  };

  window.resourcesAPI = resourcesAPI;
})();
