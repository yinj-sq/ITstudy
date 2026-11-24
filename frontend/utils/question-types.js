/**
 * 题目类型常量定义
 */
(function () {
  /**
   * 题目类型映射（标识 → 中文名）
   */
  const QUESTION_TYPES = {
    single: '单选题',
    multiple: '多选题',
    judge: '判断题',
    fill: '填空题',
    python_fill: 'Python填空题',
    comprehensive: '综合题',
    link: '外链资源'
  };

  /**
   * 题目类型对应的颜色（用于 UI 标签）
   */
  const TYPE_COLORS = {
    single: 'blue',
    multiple: 'purple',
    judge: 'green',
    fill: 'orange',
    python_fill: 'cyan',
    comprehensive: 'red',
    link: 'gray'
  };

  /**
   * 获取题目类型的中文名称
   * @param {string} type
   * @returns {string}
   */
  function getTypeLabel(type) {
    return QUESTION_TYPES[type] || type || '未知类型';
  }

  /**
   * 获取题目类型对应的颜色
   * @param {string} type
   * @returns {string}
   */
  function getTypeColor(type) {
    return TYPE_COLORS[type] || 'gray';
  }

  /**
   * 获取所有题目类型列表
   * @returns {Array<{value: string, label: string}>}
   */
  function getTypeOptions() {
    return Object.keys(QUESTION_TYPES).map(function (key) {
      return { value: key, label: QUESTION_TYPES[key] };
    });
  }

  /**
   * 判断题目类型是否为客观题（可自动评分）
   * @param {string} type
   * @returns {boolean}
   */
  function isAutoGradable(type) {
    return ['single', 'multiple', 'judge', 'fill'].indexOf(type) !== -1;
  }

  // 暴露到全局
  window.QUESTION_TYPES = QUESTION_TYPES;
  window.TYPE_COLORS = TYPE_COLORS;
  window.getTypeLabel = getTypeLabel;
  window.getTypeColor = getTypeColor;
  window.getTypeOptions = getTypeOptions;
  window.isAutoGradable = isAutoGradable;
})();
