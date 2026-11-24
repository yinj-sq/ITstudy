/**
 * 通用格式化工具函数
 */
(function () {
  const utils = {
    /**
     * 格式化日期时间字符串
     * @param {string} dateStr - ISO 日期字符串或时间戳
     * @param {boolean} [showTime=true] - 是否显示时分秒
     * @returns {string} 格式化后的日期字符串
     */
    formatDate: function (dateStr, showTime) {
      if (!dateStr) return '-';
      if (showTime === undefined) showTime = true;

      try {
        var date = new Date(dateStr);
        if (isNaN(date.getTime())) return '-';

        var year = date.getFullYear();
        var month = String(date.getMonth() + 1).padStart(2, '0');
        var day = String(date.getDate()).padStart(2, '0');

        if (!showTime) {
          return year + '-' + month + '-' + day;
        }

        var hours = String(date.getHours()).padStart(2, '0');
        var minutes = String(date.getMinutes()).padStart(2, '0');
        var seconds = String(date.getSeconds()).padStart(2, '0');

        return year + '-' + month + '-' + day + ' ' + hours + ':' + minutes + ':' + seconds;
      } catch (e) {
        return dateStr;
      }
    },

    /**
     * 格式化分数
     * @param {number} score - 分数值
     * @param {number} [decimals=1] - 保留小数位数
     * @returns {string}
     */
    formatScore: function (score, decimals) {
      if (score === null || score === undefined) return '-';
      if (decimals === undefined) decimals = 1;
      return Number(score).toFixed(decimals);
    },

    /**
     * 获取题目类型的中文标签
     * @param {string} type - 题目类型标识
     * @returns {string} 中文类型名
     */
    questionTypeLabel: function (type) {
      var labels = {
        single: '单选题',
        multiple: '多选题',
        judge: '判断题',
        fill: '填空题',
        python_fill: 'Python填空题',
        comprehensive: '综合题',
        link: '外链资源'
      };
      return labels[type] || type || '未知类型';
    },

    /**
     * 截断字符串
     * @param {string} str - 原字符串
     * @param {number} maxLength - 最大长度
     * @returns {string}
     */
    truncate: function (str, maxLength) {
      if (!str) return '';
      if (maxLength === undefined) maxLength = 50;
      if (str.length <= maxLength) return str;
      return str.substring(0, maxLength) + '...';
    },

    /**
     * 获取当前时间的中文问候语
     * @returns {string}
     */
    greeting: function () {
      var hour = new Date().getHours();
      if (hour < 6) return '夜深了';
      if (hour < 9) return '早上好';
      if (hour < 12) return '上午好';
      if (hour < 14) return '中午好';
      if (hour < 18) return '下午好';
      return '晚上好';
    }
  };

  // 暴露到全局
  window.formatDate = utils.formatDate;
  window.formatScore = utils.formatScore;
  window.questionTypeLabel = utils.questionTypeLabel;
  window.truncate = utils.truncate;
  window.greeting = utils.greeting;

  // 同时导出为命名空间
  window.formatUtils = utils;
})();
