/* ════════════════════════════════════════════════════════════
 * 课堂页主逻辑（study_lesson.js）
 *   章节树渲染 / 中央双模播放器（视频 + PPTist 放映）/ 文档与活动视图 /
 *   自动播放连播 / 全屏 / 侧栏折叠 / 工具栏调度
 *   依赖：lesson_tools.js（LessonTools）、页面注入的 LESSON_PAGE
 * ════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var PAGE = window.LESSON_PAGE || {};
  var T = window.LessonTools;

  var UPLOAD_BASE = '/static/uploads/';
  var itemMap = {};        // id -> item
  var currentItemId = null;
  var pptistReady = false;
  var pptxLoadSeq = 0;          // 每次进入课件递增，丢弃旧 fetch 结果
  var currentPptxRequestId = null;
  var pptxLoadTimer = null;
  var coursewareGgbBridge = null;
  var coursewareWorkerRelay = null;

  /* ══ 阅读位置记忆（按资源 + 条目，浏览器本地保存） ══ */
  var ReadingState = {
    key: 'lesson.readpos.v1.' + (PAGE.resourceId || 'unknown'),
    data: { v: 1, entries: {} },
    load: function () {
      try {
        var raw = localStorage.getItem(this.key);
        var data = raw ? JSON.parse(raw) : null;
        if (data && data.v === 1 && data.entries && typeof data.entries === 'object') {
          this.data = data;
        }
      } catch (e) { /* localStorage 不可用时静默降级 */ }
    },
    persist: function () {
      try { localStorage.setItem(this.key, JSON.stringify(this.data)); } catch (e) { /* ignore */ }
    },
    entry: function (itemId) {
      if (!itemId) return null;
      if (!this.data.entries[itemId]) this.data.entries[itemId] = {};
      return this.data.entries[itemId];
    },
    set: function (itemId, patch) {
      if (!itemId || !patch) return;
      var e = this.entry(itemId);
      Object.keys(patch).forEach(function (k) { e[k] = patch[k]; });
      e.updatedAt = Date.now();
      this.persist();
    },
    pickScrollable: function (frame) {
      try {
        var doc = frame && frame.contentDocument;
        if (!doc || !doc.documentElement) return null;
        var scrolling = doc.scrollingElement || doc.documentElement;
        var candidates = [scrolling];
        ['.jv-pdf-scroll', '.jv-file-render--docx', '.jv-file-render--excel',
         '.jv-file-render--ofd', '[class*="scroll"]'].forEach(function (sel) {
          try {
            var nodes = doc.querySelectorAll(sel);
            for (var i = 0; i < nodes.length; i++) candidates.push(nodes[i]);
          } catch (e) { /* ignore */ }
        });
        candidates.push(doc.documentElement, doc.body);
        var best = null;
        candidates.forEach(function (el) {
          if (!el || el.scrollHeight <= el.clientHeight + 4) return;
          var style = null;
          try { style = frame.contentWindow.getComputedStyle(el); } catch (e) {}
          if (style && style.overflowY === 'hidden') return;
          if (!best) { best = el; return; }
          // 标准/怪异模式下滚动主体分别是 html/body；优先滚动主体，
          // 但 JitViewer 内部独立滚动容器高度更大时使用内部容器。
          if (el === scrolling && best !== scrolling) { best = el; return; }
          if (best === scrolling && el !== scrolling &&
              el.scrollHeight > best.scrollHeight) { best = el; return; }
          if (best !== scrolling && el !== scrolling &&
              (el.scrollTop || 0) > (best.scrollTop || 0)) best = el;
        });
        return best;
      } catch (e) { return null; }
    },
    scrollInfo: function (frame) {
      var best = this.pickScrollable(frame);
      if (!best) return { top: 0, ratio: 0 };
      var max = Math.max(1, best.scrollHeight - best.clientHeight);
      return { top: best.scrollTop || 0, ratio: (best.scrollTop || 0) / max };
    },
    applyScroll: function (frame, state) {
      if (!state) return false;
      var best = this.pickScrollable(frame);
      if (!best) return false;
      var max = Math.max(0, best.scrollHeight - best.clientHeight);
      var top = Number(state.ratio)
        ? Math.round(Number(state.ratio) * max)
        : (Number(state.top) || 0);
      best.scrollTop = Math.min(max, Math.max(0, top));
      return true;
    },
    saveCurrent: function () {
      var item = itemMap[currentItemId];
      if (!item) return;
      var entry = this.entry(currentItemId);
      entry.kind = item.kind;
      entry.src = item.src || '';
      if (item.kind === 'doc' && !isImage(item.src)) {
        var info = this.scrollInfo($('docFrame'));
        if (info) entry.doc = info;
      } else if (item.kind === 'link') {
        var info2 = this.scrollInfo($('linkFrame'));
        if (info2) entry.link = info2;
      } else if (item.kind === 'video' && $('videoPlayer')) {
        entry.video = { currentTime: $('videoPlayer').currentTime || 0 };
      } else if (item.kind === 'pptx' && typeof lastPptxSlide[currentItemId] !== 'undefined') {
        entry.pptx = { slideIndex: lastPptxSlide[currentItemId] };
      }
      this.persist();
    },
    restoreFrame: function (frame, itemId, key) {
      var self = this, tries = 0;
      var entry = this.data.entries[itemId];
      if (!entry || !entry[key]) return;
      function attempt() {
        tries++;
        if (self.applyScroll(frame, entry[key]) || tries >= 40) return;
        setTimeout(attempt, 200);
      }
      setTimeout(attempt, 100);
    },
    restorePptx: function (itemId, delay) {
      var entry = this.data.entries[itemId];
      if (!entry || !entry.pptx) return;
      var idx = Number(entry.pptx.slideIndex);
      if (!isFinite(idx) || idx < 0) return;
      // enterSubmodeView 会在 loaded 后把页码重置到 0，延迟后再跳页；
      // pptxImported 路径的 enterSubmodeView 在 500ms 后执行，需更晚恢复。
      setTimeout(function () {
        if (itemMap[currentItemId] && currentItemId === itemId) {
          sendToPptist({ action: 'gotoSlide', index: idx });
        }
      }, delay || 350);
    }
  };
  ReadingState.load();
  window.addEventListener('beforeunload', function () { ReadingState.saveCurrent(); });
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') ReadingState.saveCurrent();
  });

  function $(id) { return document.getElementById(id); }
  function show(el) { if (el) el.classList.remove('hidden'); }
  function hide(el) { if (el) el.classList.add('hidden'); }

  var IMG_EXTS = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg'];
  var AUDIO_HINT = ['mp3', 'wav', 'ogg', 'm4a', 'flac', 'aac', 'opus', 'weba', 'aiff', 'aif'];

  function extOf(src) {
    var m = (src || '').split('?')[0].split('.');
    return m.length > 1 ? m.pop().toLowerCase() : '';
  }
  function uploadsUrl(src) {
    // HTML 条目的 src 已是站内绝对路径，不能再次拼接课件目录。
    return isLocalUploadSrc(src) ? src : UPLOAD_BASE + PAGE.dirName + '/' + src;
  }
  function isAudio(src) { return AUDIO_HINT.indexOf(extOf(src)) >= 0; }
  function isImage(src) { return IMG_EXTS.indexOf(extOf(src)) >= 0; }

  /* 自定义编排树：条目文件走带权限的课堂条目路由。
     教师在编排里勾选「学生可见」后，即使文件级展示为 false，也应能播放；
     默认树条目 id 每次渲染随机，不能跨请求复用，仍走静态路径。 */
  function itemFileUrl(item) {
    if (PAGE.hasCustomTree && item && item.id) {
      return '/study/lesson/' + PAGE.resourceId + '/item/' +
        encodeURIComponent(item.id) + '/file';
    }
    return uploadsUrl(item.src);
  }
  function itemPreviewUrl(item) {
    if (PAGE.hasCustomTree && item && item.id) {
      return '/study/preview?lesson_res=' + PAGE.resourceId +
        '&lesson_item=' + encodeURIComponent(item.id) + '&embed=1';
    }
    return '/study/preview?file=' + encodeURIComponent(uploadsUrl(item.src)) +
      '&name=' + encodeURIComponent(item.title || item.src) + '&embed=1';
  }
  function isLocalUploadSrc(src) {
    return typeof src === 'string' && src.indexOf('/static/uploads/') === 0;
  }

  function isExternalLinkSource(src) {
    try {
      var url = new URL(src, window.location.href);
      return (url.protocol === 'http:' || url.protocol === 'https:') &&
        url.origin !== window.location.origin;
    } catch (e) {
      return false;
    }
  }

  /* 课堂链接帧沙箱：上传 HTML/外链一律 opaque；仅平台自有页面恢复同源。
     平台页面（化学/硬件仿真、GeoGebra 播放器、预览页等）需要 localStorage、
     同源 postMessage 或同源脚本注入；上传课件与外部页面则保持隔离。 */
  var LINK_SANDBOX = 'allow-scripts allow-forms allow-modals allow-downloads allow-popups';
  var TRUSTED_LINK_PREFIXES = [
    '/chem-lab', '/sim-lab', '/hardware-sim',
    '/study/geogebra/', '/study/preview', '/study/link', '/static/'
  ];

  function isTrustedLinkSource(src) {
    try {
      var url = new URL(src, window.location.href);
      if (url.origin !== window.location.origin) return false;
      var path = url.pathname;
      if (path.indexOf('/static/uploads/') === 0 ||
          path.indexOf('/study/courseware-view/') === 0 ||
          path.indexOf('/study/courseware/') === 0 ||
          path.indexOf('/study/lesson/') === 0) return false;
      return TRUSTED_LINK_PREFIXES.some(function (prefix) {
        return path === prefix || path.indexOf(prefix) === 0;
      });
    } catch (e) {
      return false;
    }
  }

  function setLinkFrameSandbox(frame, src) {
    if (!frame) return;
    var sandbox = LINK_SANDBOX;
    if (isTrustedLinkSource(src)) {
      sandbox += ' allow-same-origin';
    } else if (isExternalLinkSource(src)) {
      // 外部站点的登录/SSO 常用顶层跳转或新窗口；仅外部源恢复这两项，
      // 上传课件与平台页面仍保持严格沙箱（顶层跳转需用户点击触发）。
      sandbox += ' allow-top-navigation-by-user-activation' +
        ' allow-popups-to-escape-sandbox';
    }
    if (frame.getAttribute('sandbox') !== sandbox) frame.setAttribute('sandbox', sandbox);
  }

  /* ══ 章节树渲染 ══ */
  var KIND_ICON = {
    video: 'bi-play-circle-fill k-video',
    pptx: 'bi-file-earmark-slides k-pptx',
    doc: 'bi-file-earmark-text k-doc',
    geogebra: 'bi-box k-geogebra',
    activity: 'bi-controller k-activity',
    survey: 'bi-clipboard-data k-survey',
    link: 'bi-globe2 k-link'
  };

  function buildTree() {
    var box = $('chapterTree');
    box.innerHTML = '';
    (PAGE.tree || []).forEach(function (sec) { box.appendChild(renderSection(sec)); });
  }

  function renderSection(sec) {
    var wrap = document.createElement('div');
    wrap.className = 'ch-sec';
    var head = document.createElement('div');
    head.className = 'ch-sec-head';
    head.setAttribute('role', 'button');
    head.setAttribute('tabindex', '0');
    head.setAttribute('aria-expanded', 'true');
    head.innerHTML = '<i class="bi bi-caret-down-fill ch-caret"></i><span>' + escapeHtml(sec.title) + '</span>';
    function toggleSection() {
      var closed = wrap.classList.toggle('closed');
      head.setAttribute('aria-expanded', closed ? 'false' : 'true');
    }
    head.addEventListener('click', toggleSection);
    head.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
        e.preventDefault(); toggleSection();
      }
    });
    var body = document.createElement('div');
    body.className = 'ch-sec-body';
    (sec.items || []).forEach(function (it) {
      itemMap[it.id] = it;
      var el = document.createElement('div');
      el.className = 'ch-item';
      el.dataset.id = it.id;
      el.setAttribute('role', 'button');
      el.setAttribute('tabindex', '0');
      el.innerHTML = '<i class="bi ' + (KIND_ICON[it.kind] || KIND_ICON.doc) + '"></i><span>' +
        escapeHtml(it.title) + '</span>';
      function openThis() { Lesson.openItem(it.id); }
      el.addEventListener('click', openThis);
      el.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
          e.preventDefault(); openThis();
        }
      });
      body.appendChild(el);
    });
    (sec.children || []).forEach(function (child) {
      body.appendChild(renderSection(child));
    });
    wrap.appendChild(head);
    wrap.appendChild(body);
    return wrap;
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function highlightItem(id) {
    document.querySelectorAll('.ch-item').forEach(function (el) {
      el.classList.toggle('active', el.dataset.id === id);
    });
    var el = document.querySelector('.ch-item[data-id="' + id + '"]');
    if (el) {
      // 确保所属章节展开且滚动可见
      var sec = el.closest('.ch-sec');
      if (sec) sec.classList.remove('closed');
      el.scrollIntoView({ block: 'nearest' });
    }
  }

  /* ══ 视图切换 ══ */
  function setView(name) {
    ['viewVideo', 'viewPptist', 'viewDoc', 'viewActivity', 'viewLink'].forEach(function (id) {
      $(id).classList.toggle('active', id === name);
    });
    var stageEmptyDocs = { viewPptist: true, viewDoc: true, viewLink: true };
    if (!stageEmptyDocs[name]) return;
    // 空 stage 提示与内容互斥
    if (name === 'viewPptist') {
      $('pptistFrame').classList.contains('hidden') ? show($('viewPptist').querySelector('.stage-empty'))
        : hide($('viewPptist').querySelector('.stage-empty'));
    }
  }

  /* ══ 视频 ══ */
  function setupVideo() {
    var video = $('videoPlayer');
    var hint = $('videoHint');
    $('bigPlay').addEventListener('click', function () {
      video.play().catch(function () { T.toast('浏览器阻止了自动播放，请再点一次', 3000); });
    });
    video.addEventListener('playing', function () { hide(hint); });
    video.addEventListener('pause', function () {
      if (!video.ended) show(hint);
    });
    video.addEventListener('ended', function () {
      if (autoplayOn()) {
        var next = nextVideoItem(currentItemId);
        if (next) { Lesson.openItem(next.id, { autoplay: true }); return; }
        T.toast('本堂课视频已播完');
      }
      show(hint);
    });
    // 倍速
    document.querySelectorAll('#rateBar button').forEach(function (b) {
      b.addEventListener('click', function () {
        video.playbackRate = parseFloat(b.dataset.rate) || 1;
        document.querySelectorAll('#rateBar button').forEach(function (x) { x.classList.remove('active'); });
        b.classList.add('active');
      });
    });
  }

  function autoplayOn() {
    try { return localStorage.getItem('lesson.autoplay') === '1'; } catch (e) { return false; }
  }

  /* 树的扁平遍历顺序（与侧栏一致） */
  function flatItems() {
    var out = [];
    (function walk(nodes) {
      (nodes || []).forEach(function (n) {
        (n.items || []).forEach(function (it) { out.push(it); });
        walk(n.children);
      });
    })(PAGE.tree);
    return out;
  }

  function nextVideoItem(fromId) {
    var items = flatItems();
    var idx = items.findIndex(function (it) { return it.id === fromId; });
    for (var i = idx + 1; i < items.length; i++) {
      if (items[i].kind === 'video') return items[i];
    }
    return null;
  }

  /* ══ PPTist 放映 ══ */
  var currentPptx = null;       // 待发送/已发送的加载数据
  var currentPptxSrc = null;    // 当前课件相对路径（保存缓存用）
  var currentPptxItemId = null; // 当前 PPTX 条目，用于阅读位置恢复
  var lastPptxSlide = {};       // itemId -> slideIndex（PPTist 主动上报）
  var pptistEditing = false;

  function setupPptist() {
    var frame = $('pptistFrame');
    window.addEventListener('message', function (e) {
      if (e.source !== frame.contentWindow) return;
      var msg = e.data;
      if (!msg || msg.source !== 'pptist-embed') return;
      if (msg.action === 'ready') {
        pptistReady = true;
        if (currentPptx) sendToPptist(currentPptx);
      } else if (msg.action === 'loaded') {
        if (!pptxMessageCurrent(msg)) return;
        clearPptxLoadTimer();
        $('pptistStatus').textContent = '';
        hide($('pptistStatus'));
        ReadingState.restorePptx(currentPptxItemId, 350);
      } else if (msg.action === 'pptxImported') {
        if (!pptxMessageCurrent(msg)) return;
        // 导入完成只作为内部状态，不把“解析完成”留在放映画面中央；
        // 部分 PPTist 版本导入后不再发 loaded，故这里主动收起。
        clearPptxLoadTimer();
        $('pptistStatus').textContent = '';
        hide($('pptistStatus'));
        ReadingState.restorePptx(currentPptxItemId, 800);
      } else if (msg.action === 'slideState') {
        if (msg.requestId && currentPptxRequestId &&
            msg.requestId !== currentPptxRequestId) return;
        if (currentPptxItemId && typeof msg.index !== 'undefined') {
          // 只更新当前会话页码；带状态的持久化在切换/离开时统一写入，
          // 避免 loaded 前 PPTist 上报的 0 页覆盖已保存的阅读位置。
          lastPptxSlide[currentPptxItemId] = Number(msg.index) || 0;
        }
      } else if (msg.action === 'data') {
        // 编辑器返回数据 → 保存为课件缓存（成功后同步内存载荷，
        // 避免"返回放映"仍重发编辑前旧数据）
        var data = msg.data;
        if (!data || !currentPptxSrc) return;
        T.apiFetch('/study/lesson/' + PAGE.resourceId + '/pptist/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ src: currentPptxSrc, data: data })
        }).then(function (d) {
          if (d && d.success) currentPptx = {
            action: 'load', slidesData: data, requestId: currentPptxRequestId
          };
          T.toast((d && (d.msg || d.message)) || (d && d.success ? '课件已保存' : '保存失败'), 2500);
        }).catch(function () { T.toast('保存失败', 2500); });
      } else if (msg.action === 'error') {
        if (!pptxMessageCurrent(msg)) return;
        clearPptxLoadTimer();
        $('pptistStatus').textContent = '放映失败：' + (msg.message || '未知错误');
        show($('pptistStatus'));
      }
    });
    // 教师：编辑/放映切换与保存
    var editToggle = $('pptistEditToggle');
    if (editToggle) {
      var saveBtn = $('pptistSaveBtn');
      editToggle.addEventListener('click', function () {
        pptistEditing = !pptistEditing;
        pptistReady = false;
        frame.src = '/static/pptist/index.html?mode=embed&submode=' + (pptistEditing ? 'editor' : 'preview');
        editToggle.innerHTML = pptistEditing
          ? '<i class="bi bi-easel"></i> 返回放映'
          : '<i class="bi bi-pencil-square"></i> 编辑课件';
        if (pptistEditing) {
          saveBtn.classList.remove('hidden');
          T.toast('编辑模式：修改后点击「保存课件」', 2600);
        } else {
          saveBtn.classList.add('hidden');
        }
      });
      saveBtn.addEventListener('click', function () {
        if (!currentPptxSrc) { T.toast('请先选择一个课件', 2000); return; }
        saveBtn.disabled = true;
        sendToPptist({ action: 'getData' });
        setTimeout(function () { saveBtn.disabled = false; }, 800);
      });
    }
  }

  function clearPptxLoadTimer() {
    if (pptxLoadTimer) {
      clearTimeout(pptxLoadTimer);
      pptxLoadTimer = null;
    }
  }

  function pptxMessageCurrent(msg) {
    // 带请求号的异步消息必须属于当前课件；旧课件迟到的 loaded/error
    // 不能提前关闭新课件状态或把错误显示到新课件上。
    return !currentPptxRequestId || msg.requestId === currentPptxRequestId;
  }

  function sendToPptxWhenReady(payload) {
    if (currentPptxRequestId && !payload.requestId) {
      payload.requestId = currentPptxRequestId;
    }
    currentPptx = payload;
    if (pptistReady) {
      sendToPptist(payload);
    } else {
      show($('pptistStatus'));
      $('pptistStatus').textContent = '正在连接放映组件…';
    }
  }

  function sendToPptist(payload) {
    var out = Object.assign({ source: 'pptist-host' }, payload);
    if (currentPptxRequestId && !out.requestId) out.requestId = currentPptxRequestId;
    $('pptistFrame').contentWindow.postMessage(out, window.location.origin);
  }

  function showPptx(item) {
    var frame = $('pptistFrame');
    var loadSeq = ++pptxLoadSeq;
    currentPptxItemId = item.id;
    currentPptxRequestId = 'pptx-load-' + loadSeq + '-' + Date.now();
    setView('viewPptist');
    show(frame);
    hide($('viewPptist').querySelector('.stage-empty'));
    show($('pptistStatus'));
    $('pptistStatus').textContent = '正在加载课件…';
    clearPptxLoadTimer();
    pptxLoadTimer = setTimeout(function () {
      if (loadSeq !== pptxLoadSeq || !pptxMessageCurrent({
          requestId: currentPptxRequestId
        })) return;
      $('pptistStatus').textContent = '课件加载超时，请重新点击该课件';
      show($('pptistStatus'));
    }, 35000);
    currentPptxSrc = item.src;
    var url = itemFileUrl(item);
    // 优先读取教师保存的 PPTist 缓存（<课件>.pptist.json），无缓存回退
    // 解析原始 PPTX；加时间戳绕过浏览器缓存（服务端对课件 JSON 已 no-cache，
    // 双保险应对旧版浏览器/代理）
    var cacheUrl = (PAGE.hasCustomTree && item.id)
      ? ('/study/lesson/' + PAGE.resourceId + '/item/' +
         encodeURIComponent(item.id) + '/pptist-cache')
      : (url + '.pptist.json');
    fetch(cacheUrl + '?t=' + Date.now(), { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) throw new Error('no cache');
        return r.json();
      })
      .then(function (data) {
        if (loadSeq !== pptxLoadSeq || currentPptxItemId !== item.id) return;
        if (!data || !Array.isArray(data.slides) || !data.slides.length) throw new Error('bad cache');
        sendToPptxWhenReady({ action: 'load', slidesData: data });
      })
      .catch(function () {
        if (loadSeq !== pptxLoadSeq || currentPptxItemId !== item.id) return;
        sendToPptxWhenReady({ action: 'loadPPTX', url: url, filename: item.title || item.src });
      });
  }

  /* ══ 文档 / 图片 / 活动 / 外链 ══ */
  function showDoc(item) {
    setView('viewDoc');
    var img = $('docImage'), frame = $('docFrame');
    var empty = $('viewDoc').querySelector('.stage-empty');
    if (isImage(item.src)) {
      hide(frame); show(img);
      hide(empty);
      img.src = itemFileUrl(item);
    } else {
      hide(img); show(frame);
      hide(empty);
      frame.onload = function () {
        ReadingState.restoreFrame(frame, item.id, 'doc');
      };
      frame.src = itemPreviewUrl(item);
    }
  }

  function showActivity(item) {
    setView('viewActivity');
    $('activityTitle').textContent = item.title;
    $('activityLink').href = item.url || '#';
    $('activityLink').innerHTML = (item.kind === 'survey' ? '进入问卷 ' : '进入活动 ') +
      '<i class="bi bi-arrow-right-circle"></i>';
  }

  function showLink(item) {
    setView('viewLink');
    var frame = $('linkFrame');
    if (coursewareWorkerRelay) coursewareWorkerRelay.reset();
    var qfBox = $('quickFormBox');
    hide($('viewLink').querySelector('.stage-empty'));
    var src = item.src || '';
    // 防御性归一：课件相对路径以课堂页 URL 为基准解析会 404
    if (!/^https?:/i.test(src) && src.charAt(0) !== '/') src = uploadsUrl(src);
    var originalSrc = src;
    // 站内课件文件走带条目权限的课堂路由（编排里勾选学生可见后不受
    // 文件级展示开关拦截）；外链与 QuickForm 保持原地址
    if (item.purpose !== 'quickform_results' && isLocalUploadSrc(src)) {
      src = itemFileUrl(item);
    }
    // 上传课件/外链保持 opaque；平台自有页面（化学/硬件/GeoGebra/预览）
    // 才恢复 allow-same-origin，避免教师上传 HTML 在课堂页同源执行。
    setLinkFrameSandbox(frame, isLocalUploadSrc(originalSrc) ? originalSrc : src);
    if (item.purpose === 'quickform_results') {
      $('quickFormTitle').textContent = item.title || 'QuickForm 成绩';
      $('quickFormOpen').href = src;
      if (item.open_mode === 'newtab') {
        frame.onload = null;
        frame.src = 'about:blank';
        hide(frame);
        show(qfBox);
        return;
      }
      hide(qfBox);
      show(frame);
    } else {
      hide(qfBox);
      show(frame);
    }
    frame.onload = function () {
      ReadingState.restoreFrame(frame, item.id, 'link');
    };
    if (PAGE.dirName && isLocalUploadSrc(originalSrc) && /\.html?(?:[?#]|$)/i.test(originalSrc)) {
      if (!coursewareGgbBridge) {
        coursewareGgbBridge = window.GGBCoursewareBridge.mount({
          frame: frame, container: $('viewLink'), resourceId: PAGE.resourceId,
          resourceRoot: UPLOAD_BASE + PAGE.dirName + '/'
        });
      }
      coursewareGgbBridge.load(src, originalSrc);
    } else {
      frame.removeAttribute('srcdoc');
      delete frame.dataset.sourceUrl;
      frame.src = src;
    }
  }

  /* ══ 条目打开（对外：文档抽屉也调用） ══ */
  var Lesson = {
    openItem: function (id, opts) {
      opts = opts || {};
      var item = itemMap[id];
      if (!item) return;
      ReadingState.saveCurrent();
      if (coursewareGgbBridge) coursewareGgbBridge.cancel();
      currentItemId = id;
      highlightItem(id);
      var video = $('videoPlayer');
      // 切离视频视图时停止播放
      if (item.kind !== 'video') video.pause();
      switch (item.kind) {
        case 'video':
          setView('viewVideo');
          $('rateBar').classList.add('show');
          $('videoPlayer').src = itemFileUrl(item);
          var videoState = (ReadingState.data.entries[id] || {}).video;
          if (videoState && Number(videoState.currentTime) > 0) {
            video.addEventListener('loadedmetadata', function restoreVideo() {
              video.removeEventListener('loadedmetadata', restoreVideo);
              try { video.currentTime = Number(videoState.currentTime); } catch (e) {}
            });
          }
          video.playbackRate = 1;
          // 倍速条高亮复位（切视频后速率重置为 1x）
          document.querySelectorAll('#rateBar button').forEach(function (x) {
            x.classList.toggle('active', x.dataset.rate === '1');
          });
          show($('videoHint'));
          if (isAudio(item.src)) {
            // 音频无画面：隐藏大播放按钮居中遮罩观感更好
            hide($('videoHint'));
            video.play().catch(function () { show($('videoHint')); });
          } else if (opts.autoplay || autoplayOn()) {
            video.play().catch(function () { /* 显示大播放按钮等待点击 */ });
          }
          break;
        case 'pptx':
          $('rateBar').classList.remove('show');
          showPptx(item);
          break;
        case 'doc':
          $('rateBar').classList.remove('show');
          showDoc(item);
          break;
        case 'activity':
          $('rateBar').classList.remove('show');
          showActivity(item);
          break;
        case 'survey':
          $('rateBar').classList.remove('show');
          showActivity(item);
          break;
        case 'geogebra':
          $('rateBar').classList.remove('show');
          // .ggb 走独立播放器路由（本地 GeoGebra 离线包），在课堂舞台内嵌
          showLink({ id: item.id, title: item.title,
                     src: item.player_url || '' });
          break;
        case 'link':
          $('rateBar').classList.remove('show');
          showLink(item);
          break;
      }
    }
  };
  window.Lesson = Lesson;

  /* ══ 章节 iframe 成绩转发 ══
     章节 HTML 里的 quiz-collector 在 iframe 中只向父页 postMessage；
     /study/link 有转发，课堂页此前没有，导致学生答完但成绩不入库。 */
  function setupQuizResultForwarding() {
    var frame = $('linkFrame');
    if (!frame) return;
    window.addEventListener('message', function (e) {
      var msg = e.data;
      if (!msg || msg.type !== 'ITSTUDY_QUIZ_RESULT') return;
      if (!frame.contentWindow || e.source !== frame.contentWindow) return;
      // 上传 HTML 现在是 opaque origin（e.origin === 'null'），按帧原始来源
      // 区分站内课件与外部页面；外部页面即使拿到自己的 contentWindow 引用
      // 也不能伪造成绩。
      var frameSameOrigin = false;
      try {
        frameSameOrigin = new URL(frame.dataset.sourceUrl || frame.src,
                                  window.location.href).origin
          === window.location.origin;
      } catch (err) { frameSameOrigin = false; }
      if (e.origin !== window.location.origin
          && !(frameSameOrigin && e.origin === 'null')) return;
      var payload = {};
      Object.keys(msg).forEach(function (k) {
        if (k !== 'type') payload[k] = msg[k];
      });
      // 资源 id 一律以当前课堂页为准，不采信帧内自报
      payload.resource_id = PAGE.resourceId;
      fetch('/api/resource_quiz/submit', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': window.CSRF_TOKEN || ''
        },
        body: JSON.stringify(payload)
      }).then(function (r) { return r.json(); })
        .then(function (data) {
          if (data && data.success && T && T.toast) {
            T.toast('测验成绩已记录', 1800);
          }
        }).catch(function () {});
    });
  }

  function setupCoursewareWorkerRelay() {
    var frame = $('linkFrame');
    if (!frame || !window.CoursewareWorkerRelay) return;
    coursewareWorkerRelay = window.CoursewareWorkerRelay.mount(
      frame, ['/study/courseware-view/', '/study/courseware/']);
  }

  /* ══ 自动播放开关 ══ */
  function setupAutoplay() {
    var cb = $('autoplayToggle');
    try { cb.checked = autoplayOn(); } catch (e) { /* ignore */ }
    cb.addEventListener('change', function () {
      try { localStorage.setItem('lesson.autoplay', cb.checked ? '1' : '0'); } catch (e) { /* ignore */ }
      T.toast(cb.checked ? '视频自动播放：开' : '视频自动播放：关', 1200);
    });
  }

  /* ══ 全屏 / 侧栏 / 工具栏 ══ */
  function setupChrome() {
    $('btnFullscreen').addEventListener('click', function () {
      if (document.fullscreenElement) document.exitFullscreen();
      else document.documentElement.requestFullscreen().catch(function () {});
    });
    $('sidebarToggle').addEventListener('click', function () {
      document.body.classList.toggle('sidebar-collapsed');
      var icon = $('sidebarToggle').querySelector('i');
      icon.className = document.body.classList.contains('sidebar-collapsed')
        ? 'bi bi-chevron-right' : 'bi bi-chevron-left';
      // 画布尺寸随舞台变化
      setTimeout(function () {
        if (window.LessonTools.drawPen.active) window.LessonTools.drawPen.resize(true);
      }, 250);
    });
    document.querySelectorAll('.tool-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        T.open(btn.dataset.tool);
      });
    });

    // 底部工具栏可收起：播放视频/课件时只留一个小图标，点一下再展开
    var toolbar = $('lessonToolbar');
    var toolbarToggle = $('lessonToolbarToggle');
    if (toolbar && toolbarToggle) {
      function setToolbarCollapsed(collapsed, persist) {
        toolbar.classList.toggle('collapsed', collapsed);
        var icon = toolbarToggle.querySelector('i');
        if (icon) {
          icon.className = collapsed ? 'bi bi-chevron-up' : 'bi bi-chevron-down';
        }
        toolbarToggle.title = collapsed ? '展开工具栏' : '收起工具栏';
        toolbarToggle.setAttribute('aria-label', toolbarToggle.title);
        toolbarToggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
        if (persist) {
          try {
            localStorage.setItem('lesson.toolbarCollapsed', collapsed ? '1' : '0');
          } catch (e) { /* ignore */ }
        }
      }
      var initiallyCollapsed = false;
      try {
        initiallyCollapsed = localStorage.getItem('lesson.toolbarCollapsed') === '1';
      } catch (e) { /* ignore */ }
      setToolbarCollapsed(initiallyCollapsed, false);
      toolbarToggle.addEventListener('click', function () {
        setToolbarCollapsed(!toolbar.classList.contains('collapsed'), true);
      });
    }
  }

  /* ══ 启动 ══ */
  function init() {
    buildTree();
    setupVideo();
    setupPptist();
    setupQuizResultForwarding();
    setupCoursewareWorkerRelay();
    setupAutoplay();
    setupChrome();
    // 默认选中第一个条目（不自动播放）
    var first = flatItems()[0];
    if (first) Lesson.openItem(first.id);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
