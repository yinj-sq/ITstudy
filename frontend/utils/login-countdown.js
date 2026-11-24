/* login-countdown.js — 登录限流提示倒计时
 * 将后端“请 N 秒后再试”的错误文案拆成每秒递减的响应式状态，
 * 供 SPA 登录页禁用提交按钮并直观展示剩余等待时间。 */
(function () {
  window.useLoginCountdown = function (errorRef) {
    var remaining = Vue.ref(0);
    var timer = null;
    var baseText = '';

    function stop() {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    }

    function reset() {
      stop();
      remaining.value = 0;
    }

    function start(message) {
      reset();
      var text = String(message || '');
      var m = text.match(/(\d+)\s*秒后再试/);
      if (!m) return false;
      var secs = parseInt(m[1], 10);
      if (!secs || secs <= 0) return false;
      baseText = text;
      remaining.value = secs;
      errorRef.value = text;
      timer = setInterval(function () {
        remaining.value -= 1;
        if (remaining.value <= 0) {
          reset();
          errorRef.value = '等待时间已结束，可以重新尝试登录';
          return;
        }
        errorRef.value = baseText.replace(
          /(\d+)(\s*秒后再试)/, remaining.value + '$2');
      }, 1000);
      return true;
    }

    if (Vue.onUnmounted) Vue.onUnmounted(reset);
    else if (Vue.onBeforeUnmount) Vue.onBeforeUnmount(reset);

    return { remaining: remaining, start: start, reset: reset };
  };
})();
