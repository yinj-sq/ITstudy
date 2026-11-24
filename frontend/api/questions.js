/**
 * 题目相关 API
 */
(function () {
  const questionsAPI = {
    /**
     * 获取题目列表
     * @param {Object} params - 查询参数 { exam_id, type, page, page_size }
     * @returns {Promise}
     */
    list: function (params) {
      return window.apiClient.get('/questions', { params: params });
    },

    /**
     * 获取单个题目详情
     * @param {number|string} id - 题目 ID
     * @returns {Promise}
     */
    get: function (id) {
      return window.apiClient.get('/questions/' + id);
    },

    /**
     * 创建题目
     * @param {Object} data - 题目数据
     * @returns {Promise}
     */
    create: function (data) {
      return window.apiClient.post('/questions', data);
    },

    /**
     * 更新题目
     * @param {number|string} id - 题目 ID
     * @param {Object} data - 更新数据
     * @returns {Promise}
     */
    update: function (id, data) {
      return window.apiClient.put('/questions/' + id, data);
    },

    /**
     * 删除题目
     * @param {number|string} id - 题目 ID
     * @returns {Promise}
     */
    delete: function (id) {
      return window.apiClient.delete('/questions/' + id);
    },

    /**
     * 批量删除题目
     * @param {number[]} ids - 题目 ID 数组
     * @returns {Promise}
     */
    batchDelete: function (ids) {
      return window.apiClient.post('/questions/batch-delete', { ids: ids });
    },

    /**
     * 获取题目的所有子题（用于综合题）
     * @param {number|string} id - 父题目 ID
     * @returns {Promise}
     */
    getSubQuestions: function (id) {
      return window.apiClient.get('/questions/' + id + '/sub');
    },

    /**
     * 添加子题
     * @param {number|string} id - 父题目 ID
     * @param {Object} data - 子题数据
     * @returns {Promise}
     */
    addSubQuestion: function (id, data) {
      return window.apiClient.post('/questions/' + id + '/sub', data);
    },

    /**
     * 删除子题
     * @param {number|string} qid - 父题目 ID
     * @param {number|string} sid - 子题 ID
     * @returns {Promise}
     */
    deleteSubQuestion: function (qid, sid) {
      return window.apiClient.delete('/questions/' + qid + '/sub/' + sid);
    }
  };

  window.questionsAPI = questionsAPI;
})();
