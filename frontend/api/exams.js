/**
 * 考试/试卷相关 API
 */
(function () {
  const examsAPI = {
    /**
     * 获取考试列表
     * @returns {Promise}
     */
    list: function () {
      return window.apiClient.get('/exams');
    },

    /**
     * 获取单个考试详情
     * @param {number|string} id - 考试 ID
     * @returns {Promise}
     */
    get: function (id) {
      return window.apiClient.get('/exams/' + id);
    },

    /**
     * 创建考试
     * @param {Object} data - 考试数据
     * @returns {Promise}
     */
    create: function (data) {
      return window.apiClient.post('/exams', data);
    },

    /**
     * 更新考试
     * @param {number|string} id - 考试 ID
     * @param {Object} data - 更新数据
     * @returns {Promise}
     */
    update: function (id, data) {
      return window.apiClient.put('/exams/' + id, data);
    },

    /**
     * 删除考试
     * @param {number|string} id - 考试 ID
     * @returns {Promise}
     */
    delete: function (id) {
      return window.apiClient.delete('/exams/' + id);
    }
  };

  window.examsAPI = examsAPI;
})();
