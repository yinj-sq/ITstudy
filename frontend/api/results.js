/**
 * 考试结果相关 API
 */
(function () {
  const resultsAPI = {
    /**
     * 获取单个考试结果
     * @param {number|string} id - 结果 ID
     * @returns {Promise}
     */
    get: function (id) {
      return window.apiClient.get('/results/' + id);
    },

    /**
     * 删除考试结果
     * @param {number|string} id - 结果 ID
     * @returns {Promise}
     */
    delete: function (id) {
      return window.apiClient.delete('/results/' + id);
    },

    /**
     * 批量删除考试结果
     * @param {number|string} examId - 考试 ID
     * @param {number[]} ids - 结果 ID 数组
     * @returns {Promise}
     */
    batchDelete: function (examId, ids) {
      return window.apiClient.post('/results/batch-delete', {
        exam_id: examId,
        ids: ids
      });
    },

    /**
     * 获取考试成绩趋势（管理员端）
     * @param {number|string} examId - 考试 ID
     * @param {Object} params - 查询参数
     * @returns {Promise}
     */
    trend: function (examId, params) {
      return window.apiClient.get('/trend/' + examId, { params: params });
    },

    /**
     * 获取学生个人成绩趋势
     * @param {string} studentId - 学生学号
     * @returns {Promise}
     */
    studentTrend: function (studentId) {
      var id = studentId || 'me';
      return window.apiClient.get('/trend/student/' + id);
    }
  };

  window.resultsAPI = resultsAPI;
})();
