/* 硬件仿真宿主：标签切换、iframe 懒加载、全高布局与安全上下文提示 */
(function () {
  'use strict';

  var SIMS = {
    mmake: {
      tab: 'hwTabMmake',
      frame: 'hwFrameMmake',
      label: '图形编程仿真',
      desc: '拖拽积木生成 MicroPython 代码，配合虚拟掌控板运行 2D 仿真；支持 Web Serial 上传真机。'
    },
    esp32: {
      tab: 'hwTabEsp32',
      frame: 'hwFrameEsp32',
      label: 'ESP32-S3 仿真',
      desc: '浏览 ESP32-S3 实验课程，打开引脚图、交互仿真、固件代码阅读器与芯片参考手册。'
    }
  };

  var page = document.querySelector('.hw-sim-page');
  if (!page) return;

  var loading = document.getElementById('hwSimLoading');
  var loadingText = document.getElementById('hwSimLoadingText');
  var openLink = document.getElementById('hwSimOpen');
  var desc = document.getElementById('hwSimDesc');
  var secureHint = document.getElementById('hwSimSecureHint');
  var tipsBtn = document.getElementById('hwSimTipsBtn');
  var tips = document.getElementById('hwSimTips');
  var immersiveBtn = document.getElementById('hwSimImmersiveBtn');
  var tabs = Array.prototype.slice.call(document.querySelectorAll('.hw-sim-tab'));
  var current = null;
  var loadTimer = null;

  function storedTab() {
    try {
      return localStorage.getItem('hwSim.tab') || '';
    } catch (e) { return ''; }
  }

  function rememberTab(key) {
    try { localStorage.setItem('hwSim.tab', key); } catch (e) { /* ignore */ }
  }

  function urlTab() {
    try {
      return new URLSearchParams(window.location.search).get('tab') || '';
    } catch (e) { return ''; }
  }

  function syncUrl(key) {
    try {
      var url = new URL(window.location.href);
      url.searchParams.set('tab', key);
      window.history.replaceState(null, '', url.pathname + url.search + url.hash);
    } catch (e) { /* ignore */ }
  }

  function activeFrame() {
    return current ? document.getElementById(SIMS[current].frame) : null;
  }

  function showLoading(text) {
    if (!loading) return;
    loading.classList.remove('hidden');
    if (loadingText && text) loadingText.textContent = text;
  }

  function hideLoading() {
    if (loading) loading.classList.add('hidden');
  }

  function frameLoaded(frame) {
    return !!frame && frame.dataset.loaded === '1';
  }

  function ensureFrame(frame) {
    if (!frame || frame.getAttribute('src')) return;
    var src = frame.getAttribute('data-src');
    if (!src) return;
    frame.dataset.loaded = '';
    showLoading('正在加载' + (SIMS[current] ? SIMS[current].label : '仿真') + '…');
    frame.src = src;
    if (loadTimer) clearTimeout(loadTimer);
    loadTimer = setTimeout(function () {
      if (current && !frameLoaded(activeFrame()) && loadingText) {
        loadingText.textContent = '加载较慢，可点击右上角「新窗口打开」';
      }
    }, 30000);
  }

  function dispatchResize(frame) {
    if (!frame || !frame.contentWindow) return;
    try {
      frame.contentWindow.dispatchEvent(new Event('resize'));
    } catch (e) { /* ignore */ }
  }

  function activate(key, opts) {
    var conf = SIMS[key];
    if (!conf) return;
    current = key;

    tabs.forEach(function (tab) {
      var on = tab.getAttribute('data-sim') === key;
      tab.classList.toggle('active', on);
      tab.setAttribute('aria-selected', on ? 'true' : 'false');
      tab.tabIndex = on ? 0 : -1;
    });

    Array.prototype.forEach.call(document.querySelectorAll('.hw-sim-frame'), function (frame) {
      frame.classList.toggle('active', frame.getAttribute('data-sim') === key);
    });

    var frame = activeFrame();
    if (desc) desc.textContent = conf.desc;
    if (openLink && frame) openLink.href = frame.getAttribute('data-src') || '#';

    if (frameLoaded(frame)) {
      hideLoading();
    } else {
      ensureFrame(frame);
    }

    rememberTab(key);
    if (!opts || opts.updateUrl !== false) syncUrl(key);
    dispatchResize(frame);
    layout();
  }

  function layout() {
    var top = page.getBoundingClientRect().top;
    var h = Math.max(360, window.innerHeight - top - 12);
    page.style.setProperty('--hw-h', h + 'px');
  }

  var resizeTimer = null;
  function onResize() {
    layout();
    if (resizeTimer) clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      dispatchResize(activeFrame());
    }, 120);
  }

  tabs.forEach(function (tab) {
    tab.addEventListener('click', function () {
      activate(tab.getAttribute('data-sim'));
    });
    tab.addEventListener('keydown', function (e) {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      var idx = tabs.indexOf(tab);
      var next = tabs[(idx + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
      if (next) {
        e.preventDefault();
        next.focus();
        activate(next.getAttribute('data-sim'));
      }
    });
  });

  Array.prototype.forEach.call(document.querySelectorAll('.hw-sim-frame'), function (frame) {
    frame.addEventListener('load', function () {
      if (frame.getAttribute('src')) {
        frame.dataset.loaded = '1';
        if (frame === activeFrame()) hideLoading();
      }
    });
  });

  if (!window.isSecureContext && secureHint) {
    secureHint.classList.add('warn');
    secureHint.innerHTML = '<i class="fas fa-exclamation-triangle"></i> ' +
      '当前不是 HTTPS/localhost：Web Serial 上传、摄像头/麦克风/定位可能不可用，仿真仍可使用。';
  }

  function setTips(open) {
    if (!tips || !tipsBtn) return;
    if (open) {
      tips.removeAttribute('hidden');
    } else {
      tips.setAttribute('hidden', '');
    }
    tipsBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
    layout();
  }

  if (tipsBtn && tips) {
    tipsBtn.addEventListener('click', function () {
      setTips(tips.hasAttribute('hidden'));
    });
  }

  function setImmersive(on) {
    document.body.classList.toggle('hw-sim-immersive', on);
    if (immersiveBtn) {
      immersiveBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
      immersiveBtn.innerHTML = on
        ? '<i class="fas fa-compress"></i> 退出沉浸'
        : '<i class="fas fa-expand"></i> 沉浸模式';
    }
    setTimeout(layout, 60);
  }

  if (immersiveBtn) {
    immersiveBtn.addEventListener('click', function () {
      setImmersive(!document.body.classList.contains('hw-sim-immersive'));
    });
  }

  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    if (tips && !tips.hasAttribute('hidden')) {
      setTips(false);
    } else if (document.body.classList.contains('hw-sim-immersive')) {
      setImmersive(false);
    }
  });

  var initial = urlTab();
  if (!SIMS[initial]) initial = storedTab();
  if (!SIMS[initial]) initial = 'mmake';

  window.addEventListener('resize', onResize);
  window.addEventListener('load', layout);
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(layout).catch(function () { });
  }
  // 学生欢迎/提示条关闭后页面顶部上移，重新计算 iframe 高度
  Array.prototype.forEach.call(
    document.querySelectorAll('.container > .alert .btn-close'),
    function (btn) {
      btn.addEventListener('click', function () { setTimeout(layout, 350); });
    }
  );

  activate(initial, { updateUrl: false });
  layout();
})();
