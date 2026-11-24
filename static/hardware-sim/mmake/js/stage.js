/* ============================================================
 * stage.js —— 舞台模式：全矢量 SVG 场景
 * 关键改动（相比 canvas 版）：
 *   1. 使用 SVG 渲染，任何屏幕尺寸下放大都保持矢量清晰，不再模糊；
 *   2. 内置 devicePixelRatio 无关的 viewBox 自适应，布局按比例缩放；
 *   3. 场景元素可拖动（鼠标/触摸），位置持久化；
 *   4. 元素库来自 stage-scene.js，可一键布置常见生活情景。
 * ============================================================ */
(function (global) {
  'use strict';
  var ZKB = global.ZKB || (global.ZKB = {});
  var SVGNS = 'http://www.w3.org/2000/svg';
  var $ = function (id) { return document.getElementById(id); };

  var root = null;          // <svg>
  var gBg = null, gItems = null, gFx = null, gUi = null, night = null;
  var bubble = null, bubbleHideAt = 0;
  /* 第二十四轮：串口/控制台输出气泡 —— 画在 SVG 里并跟随掌控小助手，
     不再用 HTML 浮层（会挡住下方按钮）。gSay 由 makeSayBubble 懒创建。 */
  var gSay = null, sayText = '', sayLines = [], sayHideAt = 0;
  /* 气泡专用图层：独立挂在 root 上，**不能放gUi**——
     UI 面板（元素库/属性卡）每帧用 gUi.innerHTML = html 重绘，会把气泡一起清掉。*/
  var gSayLayer = null;
  var rafId = 0;
  var t0 = performance.now();

  /* 舞台逻辑坐标系（viewBox）—— 可由用户手动调节宽高 */
  var VW = 800, VH = 560;

  /* 元素位置存储：[{uid, k, x, y, rot, scale, z}] */
  var items = [];
  var seq = 1;

  /* 自定义素材（用户上传的元素），key 前缀 'cus_' */
  var customs = {};   // id -> {id,name,url,w,h}

  /* 掌控小助手位置（可拖动） */
  var assistant = { x: VW / 2 + 120, y: 500 };

  /* 元素库（由 stage-scene.js 提供） */
  var LIB = function () { return ZKB.SceneLib ? ZKB.SceneLib.LIB : {}; };

  /* ============================================================
   * 初始化
   * ============================================================ */
  function init() {
    /* 注意：只清空舞台容器 #stage-host，绝不能清空整个 #stage-view，
       否则会把工具栏（情景/元素下拉）、气泡与提示条一并删除。 */
    var host = document.getElementById('stage-host');
    bubble = document.getElementById('stage-bubble');
    /* 兼容旧结构：若仍存在 canvas 则移除 */
    var old = document.getElementById('stage-canvas');
    if (old && old.parentNode) old.parentNode.removeChild(old);

    if (host) {
      host.innerHTML = '';
      root = document.createElementNS(SVGNS, 'svg');
      root.setAttribute('id', 'stage-svg');
      root.setAttribute('viewBox', '0 0 ' + VW + ' ' + VH);
      root.setAttribute('preserveAspectRatio', 'xMidYMid meet');
      root.setAttribute('class', 'stage-svg');
      host.appendChild(root);
      applyStageSize();

      var defs = document.createElementNS(SVGNS, 'defs');
      defs.innerHTML = ZKB.SceneLib ? ZKB.SceneLib.GRAD_DEFS : '';
      root.appendChild(defs);

      gBg = layer('g', 'stage-layer-bg');
      gItems = layer('g', 'stage-layer-items');
      gFx = layer('g', 'stage-layer-fx');
      gUi = layer('g', 'stage-layer-ui');
      gSayLayer = layer('g', 'stage-layer-say');
      root.appendChild(gBg); root.appendChild(gItems);
      root.appendChild(gFx); root.appendChild(gUi);
      root.appendChild(gSayLayer);   /* 气泡层永远最上，不被 UI 面板重绘影响 */

      buildBackground();
      /* 夜色遮罩（第十六轮）：盖在元素之上、UI 之下，光线不足时压暗整个舞台 */
      night = el('rect', {
        id: 'zk-night', x: 0, y: 0, width: VW, height: VH,
        fill: '#0a1630', opacity: '0', 'pointer-events': 'none'
      }, gFx);
      bindDrag();
      bindCtxDismiss();
      bindFullscreenWatch();
      restoreScene();
      loadOpts();
      applyLockState();
    }

    cancelAnimationFrame(rafId);
    rafId = requestAnimationFrame(frame);
  }

  function layer(tag, cls) {
    var e = document.createElementNS(SVGNS, tag);
    e.setAttribute('class', cls);
    return e;
  }
  function el(tag, attrs, parent) {
    var e = document.createElementNS(SVGNS, tag);
    if (attrs) for (var k in attrs) if (attrs[k] !== undefined && attrs[k] !== null) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }

  /* ============================================================
   * 背景：教室 / 户外场景（矢量，随光线变化）
   * ============================================================ */
  function buildBackground() {
    gBg.innerHTML = '';
    /* 天空渐变 */
    var defs = document.createElementNS(SVGNS, 'defs');
    defs.innerHTML =
      '<linearGradient id="zkSky" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0" stop-color="#bfe6ff"/><stop offset="1" stop-color="#eaf7ff"/></linearGradient>';
    root.insertBefore(defs, gBg);

    /* 草地分界线（随高度比例） */
    var grassY = Math.round(VH * 0.645);
    var roadY = Math.round(VH * 0.84);

    el('rect', { x: 0, y: 0, width: VW, height: VH, fill: 'url(#zkSky)' }, gBg);

    /* 远山 */
    el('path', {
      d: 'M0,' + (grassY - 60) + ' Q' + (VW * 0.14) + ',' + (grassY - 145) + ' ' + (VW * 0.28) + ',' +
        (grassY - 70) + ' Q' + (VW * 0.41) + ',' + (grassY - 155) + ' ' + (VW * 0.55) + ',' +
        (grassY - 75) + ' Q' + (VW * 0.7) + ',' + (grassY - 145) + ' ' + (VW * 0.85) + ',' +
        (grassY - 78) + ' Q' + (VW * 0.93) + ',' + (grassY - 120) + ' ' + VW + ',' + (grassY - 82) +
        ' L' + VW + ',' + VH + ' L0,' + VH + ' Z',
      fill: '#bfe0c8', opacity: '.85'
    }, gBg);

    /* 草地 */
    el('path', {
      d: 'M0,' + grassY + ' Q' + (VW * 0.25) + ',' + (grassY - 20) + ' ' + (VW * 0.5) + ',' +
        (grassY + 2) + ' Q' + (VW * 0.75) + ',' + (grassY + 24) + ' ' + VW + ',' + (grassY - 2) +
        ' L' + VW + ',' + VH + ' L0,' + VH + ' Z',
      fill: '#9fd49a'
    }, gBg);
    /* 小草丛 */
    var grass = el('g', { opacity: '.55' }, gBg);
    var gc = Math.max(12, Math.round(VW / 20));
    for (var i = 0; i < gc; i++) {
      var gx = (i * 137) % (VW - 20) + 10;
      var gy = grassY + 20 + ((i * 53) % Math.max(40, VH - grassY - 40));
      el('path', {
        d: 'M' + gx + ',' + gy + ' q2,-8 4,0 M' + (gx + 3) + ',' + gy + ' q2,-9 5,-1',
        stroke: '#6fb56c', 'stroke-width': 1.4, fill: 'none', 'stroke-linecap': 'round'
      }, grass);
    }

    /* 教学楼（固定在左上，尺寸随舞台宽度略缩放） */
    var b = el('g', {}, gBg);
    var sc = Math.min(1, VW / 800);
    b.setAttribute('transform', 'scale(' + sc.toFixed(3) + ')');
    el('rect', { x: 56, y: 190, width: 150, height: 130, rx: 6, fill: '#dfe8f2' }, b);
    for (var r = 0; r < 3; r++) {
      for (var c = 0; c < 4; c++) {
        el('rect', { x: 72 + c * 33, y: 206 + r * 38, width: 22, height: 24, rx: 2, fill: '#cdd9e8' }, b);
      }
    }
    el('path', { d: 'M46,190 L131,142 L216,190 Z', fill: '#c9b79a' }, b);
    el('rect', { x: 118, y: 292, width: 26, height: 28, rx: 3, fill: '#b7a288' }, b);

    /* 太阳（随光线强度变化） */
    var sun = el('g', { id: 'zk-sun' }, gBg);
    el('circle', { cx: 0, cy: 0, r: 34, fill: '#ffe27a', opacity: '.55' }, sun);
    el('circle', { cx: 0, cy: 0, r: 22, fill: '#ffd24a' }, sun);

    /* 月亮（光线不足时出现，第十六轮） */
    var moon = el('g', { id: 'zk-moon', opacity: '0' }, gBg);
    el('circle', { cx: 0, cy: 0, r: 30, fill: '#cfd8ea', opacity: '.22' }, moon);
    el('circle', { cx: 0, cy: 0, r: 19, fill: '#e8ecf6' }, moon);
    el('circle', { cx: 7, cy: -6, r: 16, fill: '#2b3a52', opacity: '.92' }, moon);
    el('circle', { cx: -6, cy: -8, r: 2.4, fill: '#c8d2e6', opacity: '.7' }, moon);
    el('circle', { cx: -2, cy: 4, r: 1.8, fill: '#c8d2e6', opacity: '.6' }, moon);

    /* 小路 */
    el('path', {
      d: 'M0,' + roadY + ' Q' + (VW * 0.25) + ',' + (roadY - 15) + ' ' + (VW * 0.52) + ',' +
        (roadY + 8) + ' Q' + (VW * 0.8) + ',' + (roadY + 30) + ' ' + VW + ',' + (roadY + 2) +
        ' L' + VW + ',' + VH + ' L0,' + VH + ' Z',
      fill: '#e2d6bb'
    }, gBg);
  }

  /* ============================================================
   * 舞台尺寸（逻辑坐标系）—— 可手动调节宽高
   * ============================================================ */
  var SIZE_KEY = 'zkb_stage_size_v1';
  var SIZE_MIN = 400, SIZE_MAX = 1600;

  function loadSize() {
    var s = ZKB.Store && ZKB.Store.getLocal(SIZE_KEY);
    if (s && s.w && s.h) {
      VW = clampSize(s.w); VH = clampSize(s.h);
    }
  }
  function clampSize(v) {
    return Math.max(SIZE_MIN, Math.min(SIZE_MAX, Math.round(Number(v) || 800)));
  }
  /* 应用尺寸（逻辑坐标系） */
  var fullscreen = false;
  function applyStageSize() {
    if (!root) return;
    root.setAttribute('viewBox', '0 0 ' + VW + ' ' + VH);
    /* 全屏时自动按比例放大 viewBox 边距，让元素铺满可视区 */
    if (fullscreen) {
      var pad = 0.94;   /* 保留 6% 边距 */
      var vw = VW / pad, vh = VH / pad;
      root.setAttribute('viewBox', (-(vw - VW) / 2) + ' ' + (-(vh - VH) / 2) + ' ' + vw + ' ' + vh);
    }
  }
  function toggleFullscreen() {
    fullscreen = !fullscreen;
    document.body.classList.toggle('zk-stage-full', fullscreen);
    var view = $('stage-view');
    if (view) view.classList.toggle('fullscreen', fullscreen);
    applyStageSize();
    if (fullscreen) {
      /* 尝试进入浏览器全屏（失败也不影响自定义全屏） */
      var el0 = $('stage-view');
      if (el0 && el0.requestFullscreen) {
        try { el0.requestFullscreen().catch(function () { }); } catch (e) {}
      }
      ZKB.toast('已进入全屏：自适应放大显示，右键元素可调整');
    } else {
      if (document.fullscreenElement && document.exitFullscreen) {
        try { document.exitFullscreen().catch(function () { }); } catch (e) {}
      }
      ZKB.toast('已退出全屏');
    }
    /* 第三十五轮：全屏切换后右键菜单要挪到新的宿主里，
       否则浏览器全屏时菜单（挂在 body 上）会看不见 */
    setTimeout(rehostCtxMenu, 60);
    return fullscreen;
  }
  function isFullscreen() { return fullscreen; }

  /* 文字显隐 / 锁定 */
  function textVisible() { return stageOpts.showText; }
  function toggleText() {
    stageOpts.showText = !stageOpts.showText;
    saveOpts(); applyTextVisibility();
    return stageOpts.showText;
  }
  function isLocked() { return stageOpts.locked; }
  function toggleLock() {
    stageOpts.locked = !stageOpts.locked;
    saveOpts(); applyLockState();
    toastPill(stageOpts.locked
      ? '已锁定背景元素，点击"锁定"按钮可解除，硬件元素可移动'
      : '已解除锁定');
    return stageOpts.locked;
  }
  /* 设置舞台宽高（逻辑单位）；元素位置按比例缩放以保持相对布局 */
  function setSize(w, h) {
    var nw = clampSize(w), nh = clampSize(h);
    if (nw === VW && nh === VH) return { w: VW, h: VH };
    var sx = nw / VW, sy = nh / VH;
    items.forEach(function (it) {
      it.x = Math.round(it.x * sx);
      it.y = Math.round(it.y * sy);
    });
    assistant.x = Math.round(assistant.x * sx);
    assistant.y = Math.round(assistant.y * sy);
    VW = nw; VH = nh;
    applyStageSize();
    saveSize();
    /* 重建背景（草地/教学楼随尺寸变化） */
    buildBackground();
    /* 重绘所有元素 */
    items.forEach(renderItem);
    saveScene();
    return { w: VW, h: VH };
  }
  function saveSize() {
    if (ZKB.Store) ZKB.Store.setLocal(SIZE_KEY, { w: VW, h: VH });
  }
  function getSize() { return { w: VW, h: VH }; }

  /* ============================================================
   * 元素管理
   * ============================================================ */
  function makeItem(k, x, y) {
    var def = LIB()[k];
    if (!def) return null;
    return {
      uid: 'it' + (seq++), k: k,
      x: Math.round(x), y: Math.round(y),
      rot: 0, scale: 1, w: def.w, h: def.h,
      /* 第三十轮：运动 / 外观模块用到的状态 */
      visible: true,     /* 显示 / 隐藏 */
      opacity: 1,        /* 透明度 0~1 */
      ghost: 0           /* 虚像效果 0~100（Scratch 的 ghost effect） */
    };
  }

  function addItem(k, x, y, silent) {
    var it = makeItem(k, x, y);
    if (!it) return null;
    items.push(it);
    renderItem(it);
    /* 新增元素立即显示状态标签（如「湿度 800」「台灯·开」） */
    updateItemLabel(it);
    if (!silent) { toastPill('已添加「' + LIB()[k].name + '」'); saveScene(); }
    return it;
  }

  /* 设置元素位置（供拖动结束、程序化布置与测试调用；会立即同步 DOM 并持久化） */
  function setItemPos(uid, x, y, persist) {
    var it = items.filter(function (i) { return i.uid === uid; })[0];
    if (!it) return null;
    var def = LIB()[it.k] || { w: 40, h: 40 };
    it.x = Math.round(Math.max(-def.w / 2, Math.min(VW - def.w / 2, x)));
    it.y = Math.round(Math.max(-def.h / 2, Math.min(VH - def.h / 2, y)));
    /* 带运动学的元素（模拟小车用 _sx/_sy 记录物理位置）：
       同步物理坐标，否则下一帧 tickCar 会把这里设置的位置覆盖回去 */
    if (it._sx !== undefined) {
      it._sx = it.x;
      it._sy = it.y + (it._yOff != null ? it._yOff : 20);
    }
    var g = gItems.querySelector('[data-uid="' + uid + '"]');
    if (g) applyTransform(g.querySelector('g'), it);
    updateItemLabel(it);
    if (persist !== false) saveScene();
    return it;
  }

  function removeItem(uid) {
    items = items.filter(function (i) { return i.uid !== uid; });
    var g = gItems.querySelector('[data-uid="' + uid + '"]');
    if (g) g.remove();
    saveScene();
  }

  function clearItems() {
    items = [];
    selUid = null;
    if (typeof updateSelInfo === 'function') updateSelInfo();
    gItems.innerHTML = '';
    /* 清空联动索引，否则下次 syncDevices 会认为元素已存在而不再重建 */
    linkedItems = {};
    saveScene();
  }

  function renderItem(it) {
    var old = gItems.querySelector('[data-uid="' + it.uid + '"]');
    if (old) old.remove();

    var g = el('g', {
      'data-uid': it.uid, 'data-kind': it.k,
      class: 'stage-item' + (clickable(it.k) ? ' stage-item-clickable' : '')
    }, gItems);
    var inner = el('g', { transform: 'translate(' + it.x + ',' + it.y + ')' }, g);
    var def = LIB()[it.k];
    el('title', {}, inner).textContent = (def ? def.name : (it.custom ? it.custom.name : it.k)) + '（可拖动）';
    var body = el('g', { class: 'stage-item-body' }, inner);

    /* 自定义上传元素：用 <image> 渲染 */
    if (it.custom) {
      it.w = it.custom.w || 120;
      it.h = it.custom.h || 90;
      body.innerHTML = '<image href="' + it.custom.url + '" x="0" y="0" width="' + it.w +
        '" height="' + it.h + '" preserveAspectRatio="xMidYMid meet"/>';
    } else if (def) {
      body.innerHTML = def.build(ZKB.state);
    }
    applyTransform(inner, it);
    if (it.k === 'car') initCar(it);
    /* 第三十四轮：元素右上角的「设置」按钮（选中后显示） */
    buildItemCfgBtn(g, it);
    return g;
  }

  /* ============================================================
   * 元素「设置」按钮（第三十四轮 / 第四十二轮改样式）
   *
   * 选中元素后，在元素右上角出现一个小齿轮；
   * 点它弹出与右键相同的「更多选项」菜单，
   * 这样在触屏 / 无法右键的设备上也能改元素属性。
   *
   * 【第四十二轮】原来圆底是白色、齿轮描边也是白色，
   * 两者叠在一起在浅色元素上就只剩一个「白点」，
   * 完全看不出是设置按钮。
   * 现在把圆底改成主色实心、齿轮保留白色描边，
   * 就是一枚清晰的「设置」图标按钮了。 */
  function buildItemCfgBtn(g, it) {
    var btn = el('g', {
      class: 'stage-item-cfg', 'data-uid': it.uid,
      transform: 'translate(0,0)'
    }, g);
    btn.innerHTML =
      '<circle class="cfg-bg" cx="0" cy="0" r="11"></circle>' +
      '<g class="cfg-gear" fill="none" stroke="#fff" stroke-width="1.9" stroke-linecap="round">' +
      '<circle cx="0" cy="0" r="3.1"></circle>' +
      '<path d="M0,-7.2 V-4.8 M0,4.8 V7.2 M-7.2,0 H-4.8 M4.8,0 H7.2 ' +
      'M-5.1,-5.1 L-3.6,-3.6 M3.6,3.6 L5.1,5.1 M5.1,-5.1 L3.6,-3.6 M-3.6,3.6 L-5.1,5.1"></path>' +
      '</g>';
    btn.addEventListener('pointerdown', function (e) {
      e.stopPropagation();
      e.preventDefault();
    });
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      e.preventDefault();
      /* 在按钮旁弹出与右键相同的「更多选项」菜单 */
      var r = btn.getBoundingClientRect();
      showCtxMenu(r.left + r.width / 2, r.bottom + 6, it, { expandMore: true });
    });
    placeItemCfgBtn(it);
    return btn;
  }
  /* 把设置按钮摆到元素右上角（跟随旋转 / 缩放） */
  function placeItemCfgBtn(it) {
    var g = gItems.querySelector('[data-uid="' + it.uid + '"]');
    if (!g) return;
    var btn = g.querySelector('.stage-item-cfg');
    if (!btn) return;
    var p = itemCornerPos(it, it.w, 0);
    btn.setAttribute('transform', 'translate(' + p.x.toFixed(1) + ',' + (p.y - 12).toFixed(1) + ')');
  }
  /* 元素局部坐标 → 舞台坐标（考虑旋转与缩放） */
  function itemCornerPos(it, lx, ly) {
    var w = it.w, h = it.h, s = it.scale || 1;
    var cx = w / 2, cy = h / 2;
    /* 先绕中心缩放 */
    var px = cx + (lx - cx) * s;
    var py = cy + (ly - cy) * s;
    /* 再绕中心旋转 */
    var r = (it.rot || 0) * Math.PI / 180;
    var dx = px - cx, dy = py - cy;
    var rx = cx + dx * Math.cos(r) - dy * Math.sin(r);
    var ry = cy + dx * Math.sin(r) + dy * Math.cos(r);
    return { x: rx + it.x, y: ry + it.y };
  }

  /* 是否为可点击（切换状态）的元素 */
  function clickable(k) {
    var def = LIB()[k];
    return !!(def && def.clickable);
  }

  /* 添加自定义（上传的）元素 */
  function addCustom(rec, x, y) {
    if (!rec) return null;
    var it = {
      uid: 'it' + (seq++), k: 'cus_' + rec.id,
      x: Math.round(x), y: Math.round(y),
      rot: 0, scale: 1,
      w: rec.w || 120, h: rec.h || 90,
      custom: rec
    };
    customs[rec.id] = rec;
    items.push(it);
    renderItem(it);
    updateItemLabel(it);
    toastPill('已添加元素「' + rec.name + '」');
    saveScene();
    return it;
  }

  /* ============================================================
   * 元素右键菜单：删除 / 调整大小 / 隐藏文字 / 锁定 / 复制
   * ============================================================ */
  var CTX_KEY = 'zkb_stage_opts_v1';
  var stageOpts = {
    showText: true,      // 是否显示元素文字
    locked: false        // 锁定后背景元素不可移动/编辑
  };
  function loadOpts() {
    var o = ZKB.Store && ZKB.Store.getLocal(CTX_KEY);
    if (o) {
      if (typeof o.showText === 'boolean') stageOpts.showText = o.showText;
      if (typeof o.locked === 'boolean') stageOpts.locked = o.locked;
    }
    applyTextVisibility();
  }
  function saveOpts() {
    if (ZKB.Store) ZKB.Store.setLocal(CTX_KEY, stageOpts);
  }
  function applyTextVisibility() {
    if (!gItems) return;
    gItems.classList.toggle('hide-labels', !stageOpts.showText);
    /* 逐个元素刷新（每个元素可能单独隐藏了文字） */
    items.forEach(function (it) { updateItemLabel(it); });
  }

  /* 右键菜单 DOM
   *
   * 第三十五轮：全屏时右键菜单不显示的修复。
   * 原因：进入浏览器全屏后，浏览器只渲染 fullscreenElement 的子树，
   * 而菜单原先挂在 document.body 上 → 全屏里根本看不见。
   * 解决：菜单宿主随全屏状态切换，全屏时挂进全屏元素内部。
   */
  function ctxMenuHost() {
    var fs = document.fullscreenElement;
    /* 只有舞台自己进入全屏才把菜单塞进去（避免误挂到别的全屏元素） */
    if (fs && (fs.id === 'stage-view' || (root && fs.contains && fs.contains(root)))) return fs;
    return document.body;
  }
  function ensureCtxMenu() {
    var m = $('stage-ctx');
    if (!m) {
      m = document.createElement('div');
      m.id = 'stage-ctx';
      m.className = 'stage-ctx hidden';
    }
    /* 宿主可能随全屏状态变化，这里保证它待在正确的父节点上 */
    var host = ctxMenuHost();
    if (m.parentNode !== host) host.appendChild(m);
    return m;
  }
  /* 全屏状态变化时把菜单挪到正确的宿主里 */
  function rehostCtxMenu() {
    var m = $('stage-ctx');
    if (!m) return;
    var host = ctxMenuHost();
    if (m.parentNode !== host) host.appendChild(m);
  }
  function showCtxMenu(x, y, it, opts) {
    opts = opts || {};
    var m = ensureCtxMenu();
    var isAssistant = !it;
    var lockable = !isAssistant;   /* 小助手始终可移动 */
    var html = '';
    html += '<div class="ctx-title">' + (isAssistant ? '掌控小助手' :
      ((LIB()[it.k] || {}).name || '元素')) + '</div>';
    if (!isAssistant) {
      html += '<button data-act="front">置于顶层</button>';
      html += '<button data-act="back">置于底层</button>';
    }
    html += '<div class="ctx-sep"></div>';
    html += '<div class="ctx-row"><span>大小</span>' +
      '<input type="range" data-act="scale" min="30" max="300" value="' +
      Math.round((it ? (it.scale || 1) : (assistant.scale || 1)) * 100) + '">' +
      '<b data-out="scale">' + Math.round((it ? (it.scale || 1) : (assistant.scale || 1)) * 100) + '%</b></div>';
    if (!isAssistant) {
      html += '<div class="ctx-row"><span>旋转</span>' +
        '<input type="range" data-act="rot" min="-180" max="180" value="' + Math.round(it.rot || 0) + '">' +
        '<b data-out="rot">' + Math.round(it.rot || 0) + '°</b></div>';
    }
    html += '<div class="ctx-row"><span>不透明度</span>' +
      '<input type="range" data-act="alpha" min="20" max="100" value="' +
      Math.round((it ? (it.opacity != null ? it.opacity : 1) : (assistant.opacity != null ? assistant.opacity : 1)) * 100) + '">' +
      '<b data-out="alpha">' + Math.round((it ? (it.opacity != null ? it.opacity : 1) : (assistant.opacity != null ? assistant.opacity : 1)) * 100) + '%</b></div>';
    html += '<div class="ctx-sep"></div>';
    if (!isAssistant) {
      html += '<button data-act="dup" class="ctx-dup">复制一个</button>';
      html += '<button data-act="del" class="ctx-del">删除该元素</button>';
    } else {
      html += '<button data-act="reset-assistant">恢复默认大小</button>';
    }
    if (lockable) {
      html += '<button data-act="lock">' + (stageOpts.locked ? '🔓 解除锁定' : '🔒 锁定背景元素') + '</button>';
      html += '<button data-act="lock-item">' +
        (it.locked ? '🔓 解锁此元素' : '🔒 单独锁定此元素') + '</button>';
      /* 第三十四轮：单独隐藏 / 显示此元素的文字 */
      html += '<button data-act="hide-text">' +
        (it.hideText ? '👁 显示此元素文字' : '🚫 隐藏此元素文字') + '</button>';
    }
    /* 更多选项（可折叠分组） */
    html += '<button class="ctx-more" data-act="more">' +
      '<span class="ctx-more-caret">▸</span> 更多选项</button>';
    html += '<div class="ctx-more-panel hidden">' +
      (isAssistant ? moreForAssistant(it) : moreForItem(it, isAssistant)) +
      '</div>';
    m.innerHTML = html;
    m.classList.remove('hidden');
    /* 贴边保护 */
    var r = m.getBoundingClientRect();
    var px = Math.min(x, window.innerWidth - r.width - 8);
    var py = Math.min(y, window.innerHeight - r.height - 8);
    m.style.left = Math.max(4, px) + 'px';
    m.style.top = Math.max(4, py) + 'px';

    /* 绑定菜单交互 */
    m.querySelectorAll('[data-act]').forEach(function (n) {
      var act = n.getAttribute('data-act');
      if (n.tagName === 'INPUT') {
        n.addEventListener('input', function () {
          var out = m.querySelector('[data-out="' + act + '"]');
          if (out) out.textContent = (act === 'rot' ? n.value + '°' : n.value + '%');
          applyCtxValue(act, Number(n.value), it, isAssistant);
        });
        return;
      }
      /* 「更多选项」展开/收起 */
      if (act === 'more') {
        n.addEventListener('click', function (e) {
          e.stopPropagation();
          var panel = m.querySelector('.ctx-more-panel');
          var caret = m.querySelector('.ctx-more-caret');
          if (!panel) return;
          var open = panel.classList.toggle('open');
          panel.classList.toggle('hidden', !open);
          if (caret) caret.textContent = open ? '▾' : '▸';
          n.classList.toggle('on', open);
          if (open) bindMorePanel(panel, it, isAssistant);
        });
        return;
      }
      /* 二级面板里的动作 */
      if (n.closest('.ctx-more-panel')) {
        n.addEventListener('click', function () {
          applyCtxAction2(act, it, isAssistant);
        });
        return;
      }
      n.addEventListener('click', function () {
        applyCtxAction(act, it, isAssistant);
        hideCtxMenu();
      });
    });

    /* 第三十四轮：点元素右上角的「设置」按钮进来时，直接展开「更多选项」 */
    if (opts.expandMore) {
      var moreBtn = m.querySelector('[data-act="more"]');
      if (moreBtn) moreBtn.click();
    }
  }

  /* 为二级面板里的滑块单独绑定 input */
  function bindMorePanel(panel, it, isAssistant) {
    panel.querySelectorAll('input[data-act]').forEach(function (n) {
      if (n.dataset.bound) return;
      n.dataset.bound = '1';
      var act = n.getAttribute('data-act');
      n.addEventListener('input', function () {
        var out = panel.querySelector('[data-out="' + act + '"]');
        if (out) out.textContent = n.value + '°';
        applyCtxValue(act, Number(n.value), it, isAssistant);
      });
    });
  }
  function hideCtxMenu() {
    var m = $('stage-ctx');
    if (m) m.classList.add('hidden');
  }

  /* ============================================================
   * 「更多选项」二级面板
   * ============================================================ */
  function moreForItem(it) {
    var def = LIB()[it.k] || {};
    var h = '';
    h += '<div class="ctx-sub">旋转角度</div>';
    h += '<div class="ctx-row"><span>旋转</span>' +
      '<input type="range" data-act="rot" min="-180" max="180" step="1" value="' +
      Math.round(it.rot || 0) + '"><b data-out="rot">' + Math.round(it.rot || 0) + '°</b></div>';
    h += '<div class="ctx-sub">对齐</div>' +
      '<div class="ctx-btns">' +
      '<button data-act="align-l">左对齐</button>' +
      '<button data-act="align-cx">水平居中</button>' +
      '<button data-act="align-r">右对齐</button>' +
      '</div>' +
      '<div class="ctx-btns">' +
      '<button data-act="align-t">顶对齐</button>' +
      '<button data-act="align-cy">垂直居中</button>' +
      '<button data-act="align-b">底对齐</button>' +
      '</div>';
    h += '<div class="ctx-sub">快捷缩放</div>' +
      '<div class="ctx-btns">' +
      '<button data-act="scale-50">50%</button>' +
      '<button data-act="scale-75">75%</button>' +
      '<button data-act="scale-100">100%</button>' +
      '<button data-act="scale-150">150%</button>' +
      '<button data-act="scale-200">200%</button>' +
      '</div>';
    h += '<div class="ctx-sep"></div>';
    h += '<div class="ctx-btns">' +
      '<button data-act="send-back">再置底</button>' +
      '<button data-act="bring-front">再置顶</button>' +
      '</div>';
    /* 第三十四轮：单独隐藏 / 显示此元素的文字 */
    h += '<div class="ctx-sub">元素文字</div>' +
      '<div class="ctx-btns">' +
      '<button data-act="hide-text">' + (it.hideText ? '显示文字' : '隐藏文字') + '</button>' +
      '</div>';
    if (it.dev) {
      h += '<div class="ctx-tip">该元素与虚拟仿真的「' +
        esc(((ZKB.deviceMeta && ZKB.deviceMeta(it.dev)) || {}).name || it.dev) +
        '」联动，程序运行时会同步显示效果</div>';
    }
    if (def.name) {
      h += '<div class="ctx-tip">元素类型：' + esc(def.name) + '</div>';
    }
    return h;
  }
  function moreForAssistant() {
    var h = '';
    h += '<div class="ctx-sub">快捷缩放</div>';
    h += '<div class="ctx-btns">' +
      '<button data-act="ascale-75">75%</button>' +
      '<button data-act="ascale-100">100%</button>' +
      '<button data-act="ascale-125">125%</button>' +
      '<button data-act="ascale-150">150%</button>' +
      '<button data-act="ascale-200">200%</button>' +
      '</div>';
    h += '<div class="ctx-sub">位置</div>';
    h += '<div class="ctx-btns">' +
      '<button data-act="acenter-x">水平居中</button>' +
      '<button data-act="acenter-b">移到底部</button>' +
      '</div>';
    h += '<div class="ctx-sep"></div>';
    h += '<div class="ctx-tip">屏幕内容与虚拟仿真同步；<br>' +
      '上方 A / B 键、下方 PYTHON 焊盘都可直接点击操作</div>';
    return h;
  }

  /* 更多选项里的动作 */
  function applyCtxAction2(act, it, isAssistant) {
    /* 缩放快捷键 */
    if (/^(a?scale-?\d+)$/.test(act)) {
      var v = parseInt(act.replace(/[^\d]/g, ''), 10) / 100;
      if (isAssistant) {
        assistant.scale = v; renderAssistant(); saveAssistantPos();
      } else {
        it.scale = v;
        applyTransform(gItems.querySelector('[data-uid="' + it.uid + '"] g'), it);
        saveScene();
      }
      return;
    }
    /* 对齐 */
    if (act.indexOf('align-') === 0) {
      var w = it.w * (it.scale || 1), h = it.h * (it.scale || 1);
      if (act === 'align-l') it.x = Math.round(w / 2);
      else if (act === 'align-r') it.x = VW - Math.round(w / 2);
      else if (act === 'align-cx') it.x = Math.round(VW / 2);
      else if (act === 'align-t') it.y = Math.round(h / 2);
      else if (act === 'align-b') it.y = VH - Math.round(h / 2);
      else if (act === 'align-cy') it.y = Math.round(VH / 2);
      setItemPos(it.uid, it.x, it.y);
      return;
    }
    if (act === 'send-back') {
      var g1 = gItems.querySelector('[data-uid="' + it.uid + '"]');
      if (g1) gItems.insertBefore(g1, gItems.firstChild);
      ZKB.toast('已置于底层');
      return;
    }
    if (act === 'bring-front') {
      var g2 = gItems.querySelector('[data-uid="' + it.uid + '"]');
      if (g2) gItems.appendChild(g2);
      ZKB.toast('已置于顶层');
      return;
    }
    if (act === 'acenter-x') {
      assistant.x = Math.round(VW / 2); saveAssistantPos(); renderAssistant();
      return;
    }
    if (act === 'acenter-b') {
      assistant.y = VH - 70; saveAssistantPos(); renderAssistant();
      return;
    }
  }

  /* 全屏状态变化时把菜单挪到正确的宿主里
   * （用户按 ESC 退出全屏时不会走 toggleFullscreen，只能靠这个事件） */
  function bindFullscreenWatch() {
    if (bindFullscreenWatch.done) return;
    bindFullscreenWatch.done = true;
    document.addEventListener('fullscreenchange', function () {
      rehostCtxMenu();
      /* 退出全屏后按钮文案也要复位 */
      if (!document.fullscreenElement) {
        var b = $('stg-full');
        if (b) { b.textContent = '⛶ 全屏'; b.classList.remove('on'); }
      }
    });
  }

  /* 舞台空白处点击 / Esc → 关闭菜单 */
  function bindCtxDismiss() {
    if (bindCtxDismiss.done) return;
    bindCtxDismiss.done = true;
    document.addEventListener('mousedown', function (e) {
      var m = $('stage-ctx');
      if (!m || m.classList.contains('hidden')) return;
      if (m.contains(e.target)) return;          /* 点菜单内部不关闭 */
      if (e.target.closest && e.target.closest('.stage-ctx')) return;
      hideCtxMenu();
    }, true);
    document.addEventListener('touchstart', function (e) {
      var m = $('stage-ctx');
      if (m && !m.classList.contains('hidden') && !m.contains(e.target)) hideCtxMenu();
    }, true);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') hideCtxMenu();
    });
  }

  function applyCtxValue(act, v, it, isAssistant) {
    if (act === 'scale') {
      if (isAssistant) { assistant.scale = v / 100; renderAssistant(); }
      else { it.scale = v / 100; applyTransform(gItems.querySelector('[data-uid="' + it.uid + '"] g'), it); }
    } else if (act === 'rot') {
      it.rot = v;
      applyTransform(gItems.querySelector('[data-uid="' + it.uid + '"] g'), it);
    } else if (act === 'alpha') {
      if (isAssistant) { assistant.opacity = v / 100; renderAssistant(); }
      else {
        it.opacity = v / 100;
        var g = gItems.querySelector('[data-uid="' + it.uid + '"]');
        if (g) g.setAttribute('opacity', it.opacity);
      }
    }
    if (!isAssistant) saveScene(); else saveAssistantPos();
  }

  function applyCtxAction(act, it, isAssistant) {
    switch (act) {
      case 'del':
        if (it) { removeItem(it.uid); ZKB.toast('已删除元素'); }
        break;
      case 'dup': {
        var def = LIB()[it.k];
        var copy = addItem(it.k, it.x + 24, it.y + 24);
        if (copy) { copy.scale = it.scale; copy.rot = it.rot; copy.opacity = it.opacity; }
        break;
      }
      case 'front':
        if (it) {
          var g = gItems.querySelector('[data-uid="' + it.uid + '"]');
          if (g) gItems.appendChild(g);
          ZKB.toast('已置于顶层');
        }
        break;
      case 'back':
        if (it) {
          var g2 = gItems.querySelector('[data-uid="' + it.uid + '"]');
          if (g2) gItems.insertBefore(g2, gItems.firstChild);
          ZKB.toast('已置于底层');
        }
        break;
      case 'lock':
        stageOpts.locked = !stageOpts.locked;
        saveOpts();
        applyLockState();
        toastPill(stageOpts.locked
          ? '已锁定背景元素，点击"锁定"按钮可解除，硬件元素可移动'
          : '已解除锁定');
        break;
      /* 单独锁定 / 解锁某一个元素 */
      case 'lock-item':
        if (it) {
          it.locked = !it.locked;
          var gi = gItems.querySelector('[data-uid="' + it.uid + '"]');
          if (gi) gi.classList.toggle('locked', !!it.locked);
          saveScene();
          var nm = (LIB()[it.k] || {}).name || '元素';
          ZKB.toast(it.locked ? '已锁定「' + nm + '」' : '已解锁「' + nm + '」');
        }
        break;
      /* 第三十四轮：单独隐藏 / 显示某一个元素的文字 */
      case 'hide-text':
        if (it) {
          it.hideText = !it.hideText;
          applyItemTextHidden(it);
          saveScene();
          var nm2 = (LIB()[it.k] || {}).name || '元素';
          ZKB.toast(it.hideText ? '已隐藏「' + nm2 + '」的文字' : '已显示「' + nm2 + '」的文字');
        }
        break;
      case 'reset-assistant':
        assistant.scale = 1; assistant.opacity = 1;
        renderAssistant(); saveAssistantPos();
        ZKB.toast('小助手已恢复默认');
        break;
    }
  }

  /* 锁定：背景元素不可拖动，只有「联动的硬件元素」可编辑 */
  function applyLockState() {
    if (!gItems) return;
    items.forEach(function (it) {
      var g = gItems.querySelector('[data-uid="' + it.uid + '"]');
      if (!g) return;
      /* 硬件联动元素（dev:xxx）始终可编辑 */
      var linked = !!it.dev;
      var blocked = (stageOpts.locked && !linked) || !!it.locked;
      g.classList.toggle('locked', blocked);
    });
  }
  /* 标记某个元素为「硬件联动元素」 */
  function markLinked(uid) {
    var it = items.filter(function (i) { return i.uid === uid; })[0];
    if (it) {
      it.dev = true;
      applyLockState();
    }
  }

  function applyTransform(g, it) {
    var t = 'translate(' + it.x + ',' + it.y + ')';
    if (it.rot) t += ' rotate(' + it.rot + ' ' + (it.w / 2) + ' ' + (it.h / 2) + ')';
    if (it.scale !== 1) t += ' translate(' + (it.w / 2) + ',' + (it.h / 2) + ') scale(' + it.scale + ') translate(' +
      (-it.w / 2) + ',' + (-it.h / 2) + ')';
    g.setAttribute('transform', t);
  }

  function updateItems() {
    items.forEach(function (it) {
      var g = gItems.querySelector('[data-uid="' + it.uid + '"]');
      if (!g) { renderItem(it); return; }
      var def = LIB()[it.k];
      var inner = g.querySelector('g');
      var body = g.querySelector('.stage-item-body');
      /* 动态元素重建内容（视觉随状态变化）；自定义上传元素不重建 */
      if (!it.custom && def && def.dynamic) {
        body.innerHTML = def.build(ZKB.state);
      }
      /* 动画回调（蒸汽 / 扇叶 / 车轮…） */
      if (def && def.tick && inner) {
        try { def.tick(inner, ZKB.state, (performance.now() - t0) / 1000); } catch (e) {}
      }
      applyTransform(inner, it);
      /* 状态标签随传感器读数实时刷新（如湿度 / 温度） */
      if (def && def.label) updateItemLabel(it);
    });
    /* 元素右上角的「设置」按钮跟随选中元素移动 */
    if (selUid) placeItemCfgBtnByUid(selUid);
  }
  /* 按 uid 摆放「设置」按钮（只处理选中元素，避免每帧遍历全部元素） */
  function placeItemCfgBtnByUid(uid) {
    var it = items.filter(function (i) { return i.uid === uid; })[0];
    if (it) placeItemCfgBtn(it);
  }

  /* ============================================================
   * 拖动（鼠标 + 触摸）
   * ============================================================ */
  var drag = null;
  function svgPoint(evt) {
    var pt = root.createSVGPoint ? root.createSVGPoint() : null;
    if (pt) {
      pt.x = evt.clientX; pt.y = evt.clientY;
      var m = root.getScreenCTM();
      if (m) return pt.matrixTransform(m.inverse());
    }
    var r = root.getBoundingClientRect();
    return { x: (evt.clientX - r.left) * (VW / r.width), y: (evt.clientY - r.top) * (VH / r.height) };
  }

  function bindDrag() {
    /* 第三十四轮：禁用浏览器默认右键菜单，
       舞台内一律使用自绘的「更多选项」菜单 */
    root.addEventListener('contextmenu', function (e) {
      e.preventDefault();
      e.stopPropagation();
      var g = e.target.closest ? e.target.closest('.stage-item') : null;
      var uid = g ? g.getAttribute('data-uid') : null;
      var hit = uid ? (items.filter(function (i) { return i.uid === uid; })[0] || null) : null;
      showCtxMenu(e.clientX, e.clientY, hit);
    });
    /* 第五十轮：小助手实体键（A/B 与 PYTHON 焊盘）的按住状态
       ⚠ 只记「键名」不记 DOM 节点：小助手每帧都会重建 innerHTML，
         pointerdown 拿到的那个圆点下一帧就失效了，
         松手时再去读它的 data-key 会读不到（键卡在按下态）。
         键名是稳定的，用它释放最可靠。 */
    var hold = null;
    function pressKey(target, down) {
      if (!target || !ZKB.SimBoard) return false;
      var k = target.getAttribute('data-key');
      var tp = target.getAttribute('data-touch');
      if (!k && !tp) return false;
      return pressKeyVal(k, tp, down);
    }
    function pressKeyVal(k, tp, down) {
      if (k) ZKB.SimBoard.pressBtn(k, down);
      if (tp) ZKB.SimBoard.pressTouch(tp, down);
      return true;
    }
    function releaseHold() {
      if (!hold) return;
      pressKeyVal(hold.key, hold.touch, false);
      try { root.releasePointerCapture(hold.id); } catch (err) { }
      hold = null;
    }

    root.addEventListener('pointerdown', function (e) {
      /* 第五十轮：先判断是不是点在小助手的按键 / 触摸焊盘上。
         这块命中区在小助手（.stage-item）内部，必须先于拖动处理，
         否则按下键会变成「拖动小助手」。 */
      var kEl = e.target.closest ? e.target.closest('[data-key],[data-touch]') : null;
      if (kEl && pressKey(kEl, true)) {
        e.preventDefault();
        e.stopPropagation();
        hold = {
          key: kEl.getAttribute('data-key'),
          touch: kEl.getAttribute('data-touch'),
          id: e.pointerId
        };
        try { root.setPointerCapture(e.pointerId); } catch (err) { }
        return;
      }

      var g = e.target.closest ? e.target.closest('.stage-item') : null;
      if (!g) { selectItem(null); return; }   /* 点空白 → 取消选中并隐藏信息条 */
      var uid = g.getAttribute('data-uid');

      /* 右键 → 弹出上下文菜单（不进入拖动） */
      if (e.button === 2) {
        e.preventDefault();
        var hit = items.filter(function (i) { return i.uid === uid; })[0] || null;
        showCtxMenu(e.clientX, e.clientY, hit);
        return;
      }

      /* 小助手：单独处理，可自由拖动 */
      if (uid === 'assistant') {
        var pa = svgPoint(e);
        drag = { assistant: true, dx: pa.x - assistant.x, dy: pa.y - assistant.y, moved: false };
        g.classList.add('dragging');
        try { root.setPointerCapture(e.pointerId); } catch (err) {}
        e.preventDefault();
        return;
      }

      var it = items.filter(function (i) { return i.uid === uid; })[0];
      if (!it) return;
      /* 单元素锁定优先判断 */
      if (it.locked) {
        ZKB.toast('「' + ((LIB()[it.k] || {}).name || '元素') + '」已被单独锁定，右键可解锁');
        return;
      }
      /* 全局锁定：只有硬件联动元素可移动 */
      if (stageOpts.locked && !it.dev) {
        ZKB.toast('已锁定背景元素，点击"锁定"按钮可解除，硬件元素可移动');
        return;
      }
      var p = svgPoint(e);
      selectItem(uid);
      drag = { it: it, dx: p.x - it.x, dy: p.y - it.y, moved: false, tap: true };
      g.classList.add('dragging');
      try { root.setPointerCapture(e.pointerId); } catch (err) {}
      e.preventDefault();
    });

    root.addEventListener('pointermove', function (e) {
      if (!drag) return;
      var p = svgPoint(e);

      if (drag.assistant) {
        /* 小助手：夹在舞台范围内
           第五十轮：上方多了 A/B 按键（画到 y≈-95），
           原来的下限 70 会让按键被舞台顶边裁掉，提高到 110。 */
        assistant.x = Math.round(Math.max(50, Math.min(VW - 50, p.x - drag.dx)));
        assistant.y = Math.round(Math.max(110, Math.min(VH - 40, p.y - drag.dy)));
        var ag = document.getElementById('zk-assistant');
        if (ag) ag.setAttribute('transform', 'translate(' + assistant.x + ',' + assistant.y + ')');
        drag.moved = true;
        e.preventDefault();
        return;
      }

      /* 拖动过程中不落盘（避免每像素写缓存），松手时统一保存 */
      setItemPos(drag.it.uid, p.x - drag.dx, p.y - drag.dy, false);
      if (drag.it.uid === selUid) updateSelInfo();
      if (drag.moved) drag.tap = false;
      drag.moved = true;
      e.preventDefault();
    });

    function endDrag(e) {
      if (!drag) return;
      var d = drag;
      drag = null;
      try { root.releasePointerCapture(e.pointerId); } catch (err) {}
      document.querySelectorAll('.stage-item.dragging').forEach(function (x) {
        x.classList.remove('dragging');
      });

      if (d.assistant) {
        if (d.moved) { saveAssistantPos(); toastPill('已移动掌控小助手'); }
        return;
      }
      if (!d.it) return;

      /* 点击（未移动）且元素可点击 → 触发其切换行为 */
      if (d.tap && !d.moved && clickable(d.it.k)) {
        handleClickItem(d.it);
        return;
      }
      if (d.moved) {
        saveScene();
        updateItemLabel(d.it);
      }
    }
    root.addEventListener('pointerup', endDrag);
    root.addEventListener('pointercancel', endDrag);
    /* 第五十轮：松开小助手实体键（与 endDrag 互不干扰：
       endDrag 只看 drag，这里只看 hold） */
    root.addEventListener('pointerup', releaseHold);
    root.addEventListener('pointercancel', releaseHold);
    /* 兜底：指针被系统抢走（切窗口 / 右键菜单）时不要把键卡在按下态。
       再在 document 上兜一层——小助手每帧重建 innerHTML，
       万一松手时命中的是已被替换掉的旧节点，事件冒泡不到 root。 */
    root.addEventListener('pointerleave', releaseHold);
    document.addEventListener('pointerup', releaseHold);
    document.addEventListener('pointercancel', releaseHold);
  }

  /* 可点击元素的行为 */
  function handleClickItem(it) {
    var st = ZKB.state;
    if (!st) return;
    if (!st.sceneFlags) st.sceneFlags = {};

    if (it.k === 'trafficLight') {
      /* 红灯 → 黄灯 → 绿灯 循环 */
      var order = ['r', 'y', 'g'];
      var cur = st.sceneFlags.light || 'r';
      var nx = order[(order.indexOf(cur) + 1) % order.length];
      st.sceneFlags.light = nx;
      toastPill('红绿灯：' + ({ r: '红灯（停车）', y: '黄灯（等待）', g: '绿灯（通行）' })[nx]);
      renderItem(it);
      saveScene();
      /* 绿灯时允许小车前进（与虚拟仿真小车状态联动） */
      if (st.devices && st.devices.car) {
        st.sceneFlags.greenGo = (nx === 'g');
      }
      return;
    }
    if (it.k === 'switch') {
      toggleSceneSwitch();
      return;
    }
  }

  function saveAssistantPos() {
    if (ZKB.Store) ZKB.Store.setLocal('zkb_assistant_v1', { x: assistant.x, y: assistant.y });
  }

  /* 场景开关状态（台灯 / 开关 / 风扇 共用） */
  function toggleSceneSwitch() {
    var st = ZKB.state;
    if (!st) return;
    if (!st.sceneFlags) st.sceneFlags = {};
    st.sceneFlags.lamp = !st.sceneFlags.lamp;
    if (st.devices && st.devices.fan) {
      st.devices.fan.on = st.sceneFlags.lamp;
      st.devices.fan.power = st.sceneFlags.lamp ? 60 : 0;
    }
    updateItems();
    saveScene();
    toastPill(st.sceneFlags.lamp ? '场景开关：开' : '场景开关：关');
  }

  /* ============================================================
   * 小车运动学（保留原有逻辑）
   * ============================================================ */
  var CAR_SPEED = 150, CAR_TURN = 2.4, CONE_R = 12;
  function initCar(it) {
    if (it._inited) return;
    it._inited = true;
    it._sx = it.x; it._sy = it.y + 20; it._sdeg = 0;
    it.cones = [];
  }

  function tickCar(it, dt) {
    if (!it._inited) initCar(it);
    var c = ZKB.state && ZKB.state.devices && ZKB.state.devices.car;
    if (!c) return;
    var left = (c.l || 0) / 100, right = (c.r || 0) / 100;
    var vLin = (left + right) / 2 * CAR_SPEED;
    var wRot = (left - right) * CAR_TURN;

    /* —— 交通情景联动：红灯时在停止线前停车 —— */
    var st = ZKB.state;
    var stopped = false;
    if (st && st.sceneFlags && st.sceneFlags.light === 'r') {
      var tl = trafficLightPos(it);
      if (tl) {
        /* 车头越过停止线则强制停车 */
        var rad0 = it._sdeg * Math.PI / 180;
        var fx = Math.cos(rad0), fy = Math.sin(rad0);
        var nx = it._sx + fx * 26, ny = it._sy + fy * 26;
        if (nx >= tl.stopX && Math.abs(ny - tl.y) < 46) {
          vLin = 0; wRot = 0; stopped = true;
        }
      }
    }

    var rad0b = it._sdeg * Math.PI / 180;
    var nx = it._sx + Math.cos(rad0b) * vLin * dt;
    var ny = it._sy + Math.sin(rad0b) * vLin * dt;

    /* 锥桶碰撞：沿切向滑动绕过 */
    var hit = function (px, py) {
      for (var i = 0; i < it.cones.length; i++) {
        var dx = it.cones[i].x - px, dy = it.cones[i].y - py;
        if (dx * dx + dy * dy < 26 * 26) return true;
      }
      return false;
    };
    var blocked = false;
    if (Math.abs(vLin) > 1) {
      if (!hit(nx, ny)) { it._sx = nx; it._sy = ny; }
      else if (!hit(nx, it._sy)) { it._sx = nx; }
      else if (!hit(it._sx, ny)) { it._sy = ny; }
      else blocked = true;
    }
    it._sdeg += wRot * dt * 180 / Math.PI;
    /* 限制在舞台内 */
    it._sx = Math.max(30, Math.min(VW - 30, it._sx));
    it._sy = Math.max(Math.round(VH * 0.60), Math.min(VH - 40, it._sy));
    it.x = Math.round(it._sx); it.y = Math.round(it._sy - 20);
    it._stopped = stopped;

    /*—— 车头前方超声波测距（积木「小车前方距离」读的就是这个值）——
       沿车头方向发射射线，命中最近的行人 / 路树 / 红绿灯等元素（2px = 1cm） */
    var cdist = 200, cname = '';
    var rad1 = it._sdeg * Math.PI / 180;
    var sdx = Math.cos(rad1), sdy = Math.sin(rad1);
    var sc1 = it.scale || 1;
    var scx = it.x + it.w * sc1 / 2, scy = it.y + it.h * sc1 / 2;
    var bestT = null, bestN = '';
    items.forEach(function (o) {
      if (o.uid === it.uid || o.k === 'ultraSensor' || NON_OBSTACLE[o.k]) return;
      var osc = o.scale || 1;
      var t = rayRect(scx, scy, sdx, sdy, o.x, o.y, o.x + o.w * osc, o.y + o.h * osc);
      if (t !== null && (bestT === null || t < bestT)) {
        bestT = t; bestN = (LIB()[o.k] || {}).name || '障碍物';
      }
    });
    if (bestT !== null) {
      cdist = Math.max(2, Math.min(200, Math.round(bestT / ULTRA_PX_PER_CM)));
      cname = bestN;
    }
    if (c) { c._dist = cdist; c._target = cname; }
    /* 同步虚拟仿真小车卡片的距离读数 */
    var cdEl = document.getElementById('v-car-dist');
    if (cdEl) cdEl.textContent = cname ? (cname + ' ' + cdist) : cdist;

    /* 车身移动 → 重绘内部（车轮转动 / 前灯 / 刹车灯 + 车头探测提示线） */
    var g = gItems.querySelector('[data-uid="' + it.uid + '"] .stage-item-body');
    if (g) g.innerHTML = carBody(it, blocked, vLin, cdist, cname);
  }

  /* ============================================================
   * 车头前方元素查询：用于「前方 N cm 内有行人 / 车辆 / 障碍物吗」
   * kinds 为元素键数组（['pedestrian'] / ['vehicle'] / null=全部障碍）
   * 返回 {dist, name, uid, x, y}
   * ============================================================ */
  function frontScan(it, kinds, maxCm) {
    if (!it || !it._inited) initCar(it);
    var rad = it._sdeg * Math.PI / 180;
    var dx = Math.cos(rad), dy = Math.sin(rad);
    var sc = it.scale || 1;
    var cx = it.x + it.w * sc / 2, cy = it.y + it.h * sc / 2;
    var best = null, bestT = null;
    var list = kinds && kinds.length ? items.filter(function (o) {
      return o.uid !== it.uid && kinds.indexOf(o.k) >= 0;
    }) : items.filter(function (o) {
      return o.uid !== it.uid && o.k !== 'ultraSensor' && !NON_OBSTACLE[o.k];
    });
    list.forEach(function (o) {
      var osc = o.scale || 1;
      var t = rayRect(cx, cy, dx, dy, o.x, o.y, o.x + o.w * osc, o.y + o.h * osc);
      if (t !== null && (bestT === null || t < bestT)) {
        bestT = t;
        /* ⚠ 第四十轮：显示值与判定值分开。
           dist 是给「超声波读数」显示用的，钳在 2~200cm（模拟传感器最小读数）；
           但阈值判断（如「5cm 内有没有障碍」）必须用**真实几何距离** rawDist，
           否则物体贴得很近时被钳成 2cm，阈值判断永远命中，语义就错了。 */
        var rawCm = Math.round(t / ULTRA_PX_PER_CM);
        best = {
          dist: Math.max(2, Math.min(200, rawCm)),
          rawDist: Math.max(0, Math.min(200, rawCm)),
          name: (LIB()[o.k] || {}).name || '障碍物',
          uid: o.uid, k: o.k, x: o.x, y: o.y
        };
      }
    });
    if (best && maxCm && best.rawDist > maxCm) return null;
    return best;
  }

  /* ============================================================
   * 元素行走（第二十一轮）：「让元素从上往下走到 y」
   * 由 tick 每帧推进 it._walk，到达后 _walk.done = true；
   * 供 S.stage.walkTo 轮询等待（程序会阻塞直到走完）。
   * ============================================================ */
  var WALKABLE = { pedestrian: 1, vehicle: 1, trafficCar: 1, traceCar: 1, deliverBot: 1 };
  function walkTo(uid, ty, spd) {
    var it = findItem(uid);
    if (!it) return false;
    if (!WALKABLE[it.k]) return false;
    it._walk = { ty: Math.round(ty), spd: Math.max(20, Math.min(240, spd || 90)), done: false };
    return true;
  }
  function walkState(uid) {
    var it = findItem(uid);
    if (!it) return null;
    if (!it._walk) return { moving: false, done: true, y: it.y, ty: it.y, k: it.k };
    return {
      moving: !it._walk.done, done: it._walk.done,
      y: it.y, ty: it._walk.ty, k: it.k,
      name: (LIB()[it.k] || {}).name || it.k
    };
  }
  function tickWalk(it, dt) {
    if (!it._walk || it._walk.done) return;
    var dy = it._walk.ty - it.y;
    var step = it._walk.spd * dt;
    if (Math.abs(dy) <= Math.max(1, step)) {
      setItemPos(it.uid, it.x, it._walk.ty, false);
      it._walk.done = true;
      return;
    }
    setItemPos(it.uid, it.x, it.y + Math.sign(dy) * step, false);
  }

  /* 交通情景中红绿灯/停止线的位置（用于判断停车） */
  function trafficLightPos(carIt) {
    var tl = items.filter(function (i) { return i.k === 'trafficLight'; })[0];
    var sl = items.filter(function (i) { return i.k === 'stopLine'; })[0];
    if (!tl && !sl) return null;
    var y = tl ? (tl.y + 80) : (sl ? sl.y + 12 : 0);
    var stopX = sl ? (sl.x + sl.w) : (tl ? tl.x - 30 : 0);
    return { x: tl ? tl.x : 0, y: y, stopX: stopX };
  }

  function carBody(it, blocked, vLin, cdist, cname) {
    var t = (performance.now() - t0) / 1000;
    var c = ZKB.state.devices.car;
    var s = '<ellipse cx="30" cy="34" rx="26" ry="13" fill="rgba(30,50,80,.18)"/>';
    /* 车轮 */
    var spin = (c.r || 0) * t * 2;
    var wy = (Math.abs(c.r) > 1 || Math.abs(c.l) > 1) ? spin : 0;
    [-16, 10].forEach(function (dx) {
      [-13, 10].forEach(function (dy) {
        s += '<rect x="' + (dx + 30) + '" y="' + (dy + 22) + '" width="11" height="5" rx="2" fill="#22262c"/>';
        s += '<rect x="' + (dx + 31 + Math.cos(wy) * 2.5) + '" y="' + (dy + 22.5 + Math.sin(wy) * 2.5) +
          '" width="9" height="3.4" rx="1.5" fill="#4a525c"/>';
      });
    });
    /* 车身（车头朝 +x） */
    s += '<rect x="10" y="24" width="42" height="20" rx="6" fill="#3d7ea6"/>';
    s += '<rect x="34" y="26.5" width="10" height="15" rx="2" fill="#bfe3f2"/>';
    s += '<rect x="18" y="26.5" width="9" height="15" rx="2" fill="#9fc3d6"/>';
    s += '<rect x="51" y="29" width="2" height="10" fill="#2c5b7a"/>';
    /* 前灯 / 刹车灯：被挡、停车、倒车时显示红灯 */
    var braking = blocked || it._stopped || vLin < -1;
    if (braking) {
      s += '<circle cx="53" cy="28" r="3.4" fill="#ff4040"/>' +
        '<circle cx="53" cy="40" r="3.4" fill="#ff4040"/>' +
        '<circle cx="9" cy="30" r="2.6" fill="#ff4040"/>' +
        '<circle cx="9" cy="38" r="2.6" fill="#ff4040"/>';
    } else if (Math.abs(vLin) > 1) {
      s += '<circle cx="53" cy="28" r="2.6" fill="#fff096"/><circle cx="53" cy="40" r="2.6" fill="#fff096"/>';
    }
    /* —— 车头前方探测距离提示线（第二十一轮）——
       从车头沿行驶方向画一条测距射线，长度 = 实测距离，
       近距离红色告警（<30cm）、中距离橙色、远距离绿色，并在末端标注距离。 */
    var dpx = Math.max(10, Math.min(150, (cdist === undefined ? 0 : cdist) * 2));
    var col = dpx < 60 ? '#ff5252' : dpx < 120 ? '#ffa733' : '#4ad07a';
    s += '<g opacity=".92">' +
      '<line x1="54" y1="34" x2="' + (54 + dpx) + '" y2="34" stroke="' + col +
      '" stroke-width="2" stroke-dasharray="5 4"/>';
    s += '<circle cx="54" cy="34" r="2.6" fill="' + col + '"/>';
    /* 末端目标点 */
    s += '<circle cx="' + (54 + dpx) + '" cy="34" r="3.4" fill="none" stroke="' + col +
      '" stroke-width="1.8"/>';
    /* 刻度：每 50cm 一小格 */
    for (var gx = 50; gx <= 150; gx += 50) {
      s += '<line x1="' + (54 + gx) + '" y1="30" x2="' + (54 + gx) +
        '" y2="38" stroke="' + col + '" stroke-width="1" opacity=".45"/>';
    }
    s += '<text x="' + (58 + dpx) + '" y="26" font-size="10" fill="' + col +
      '" font-weight="700">' + (cdist === undefined ? '' : (cname ? cname + ' ' + cdist : cdist + 'cm')) +
      '</text></g>';
    /* 锥桶 */
    (it.cones || []).forEach(function (o) {
      var dx = o.x - it._sx + 30, dy = o.y - it._sy + 22;
      s += '<g><ellipse cx="' + dx + '" cy="' + (dy + 3) + '" rx="12" ry="8" fill="rgba(0,0,0,.14)"/>' +
        '<ellipse cx="' + dx + '" cy="' + dy + '" rx="11" ry="7.5" fill="#c95e10"/>' +
        '<ellipse cx="' + dx + '" cy="' + dy + '" rx="7.5" ry="5" fill="#f28c28"/>' +
        '<ellipse cx="' + dx + '" cy="' + dy + '" rx="6" ry="4" fill="none" stroke="#fff" stroke-width="1.8"/>' +
        '<circle cx="' + dx + '" cy="' + dy + '" r="2.4" fill="#ffb066"/></g>';
    });
    return s;
  }

  /* ============================================================
   * 超声波舞台测距：传感器向「正前方」发射测距射线，
   * 计算到最近障碍物元素（行人 / 路树 / 红绿灯 …）的距离并写入
   * state.devices.ultrasonic.cm —— 积木程序读到的就是这个值。
   * 仅在舞台视图激活且已添加超声波设备时测距，
   * 避免与虚拟仿真视图的滑杆 / 小车地图测距争抢。
   * ============================================================ */
  var ULTRA_PX_PER_CM = 2, ULTRA_MAX_CM = 200;
  /* 背景 / 地面类元素不计入障碍物 */
  var NON_OBSTACLE = {
    road: 1, crosswalk: 1, crosswalkV: 1, stopLine: 1, trackLine: 1,
    playground: 1, desk: 1, counter: 1, window: 1,
    deliverTrack: 1, greenStart: 1, redEnd: 1
  };

  /* 射线与轴对齐矩形求交：返回沿射线的距离(px)，不相交返回 null */
  function rayRect(sx, sy, dx, dy, x1, y1, x2, y2) {
    var tmin = -Infinity, tmax = Infinity, ta, tb;
    if (Math.abs(dx) < 1e-9) { if (sx < x1 || sx > x2) return null; }
    else {
      ta = (x1 - sx) / dx; tb = (x2 - sx) / dx;
      tmin = Math.max(tmin, Math.min(ta, tb)); tmax = Math.min(tmax, Math.max(ta, tb));
    }
    if (Math.abs(dy) < 1e-9) { if (sy < y1 || sy > y2) return null; }
    else {
      ta = (y1 - sy) / dy; tb = (y2 - sy) / dy;
      tmin = Math.max(tmin, Math.min(ta, tb)); tmax = Math.min(tmax, Math.max(ta, tb));
    }
    if (tmax < 0 || tmin > tmax) return null;
    return tmin >= 0 ? tmin : 0;
  }

  function tickUltra(it) {
    var st = ZKB.state;
    if (!st || !st.devices || !st.devices.ultrasonic) return;
    var sv = document.getElementById('stage-view');
    var stageActive = sv && sv.classList.contains('active');
    if (!stageActive || st.added.indexOf('ultrasonic') < 0) return;
    var u = st.devices.ultrasonic;
    var rot = (it.rot || 0) * Math.PI / 180;
    var dx = Math.cos(rot), dy = Math.sin(rot);
    var sc = it.scale || 1;
    /* 发射点：传感器正前沿（元素朝向 +x 方向，随 rot 旋转） */
    var cx = it.x + it.w * sc / 2, cy = it.y + it.h * sc / 2;
    var sx = cx + dx * it.w * sc / 2, sy = cy + dy * it.h * sc / 2;
    var best = null, bestName = '';
    items.forEach(function (o) {
      if (o === it || o.k === 'ultraSensor' || NON_OBSTACLE[o.k]) return;
      var osc = o.scale || 1;
      var t = rayRect(sx, sy, dx, dy, o.x, o.y, o.x + o.w * osc, o.y + o.h * osc);
      if (t !== null && (best === null || t < best)) {
        best = t;
        var def = LIB()[o.k];
        bestName = (def && def.name) || o.name || '障碍物';
      }
    });
    u._stage = true;
    if (best === null) {
      u.cm = ULTRA_MAX_CM;
      u._hit = false; u._target = '';
    } else {
      u.cm = Math.max(2, Math.min(ULTRA_MAX_CM, Math.round(best / ULTRA_PX_PER_CM)));
      u._hit = true; u._target = bestName;
    }
    /* 同步虚拟仿真传感器卡片读数（若存在） */
    var el = document.getElementById('v-ultra');
    if (el) el.textContent = u.cm;
  }
  function ultraScanAll() {
    items.forEach(function (it) { if (it.k === 'ultraSensor') tickUltra(it); });
  }

  /* ============================================================
   * 巡线机器人（第十四轮：原「送餐机器人」改为通用「机器人」）
   *   沿「巡线轨迹」元素的 path 折线巡线：
   *   绿色点出发 → 黑色轨迹 → 红色点自动停止。
   *   状态写入 st.devices.deliverRobot（地面颜色 / 超声波距离 / 摄像头目标），
   *   积木 zk_robot_* 读取的就是这里的数据。
   * ============================================================ */
  /* 点到折线的最短距离 */
  function distToPolyline(px, py, wps) {
    var best = Infinity;
    for (var i = 0; i < wps.length - 1; i++) {
      var ax = wps[i].x, ay = wps[i].y, bx = wps[i + 1].x, by = wps[i + 1].y;
      var abx = bx - ax, aby = by - ay;
      var len2 = abx * abx + aby * aby;
      var t = len2 ? ((px - ax) * abx + (py - ay) * aby) / len2 : 0;
      t = Math.max(0, Math.min(1, t));
      var qx = ax + t * abx, qy = ay + t * aby;
      var d = Math.sqrt((px - qx) * (px - qx) + (py - qy) * (py - qy));
      if (d < best) best = d;
    }
    return best;
  }

  function robotWaypoints() {
    var track = items.filter(function (o) { return o.k === 'deliverTrack'; })[0];
    if (!track) return null;
    var def = LIB().deliverTrack;
    var sc = track.scale || 1;
    return (def.path || []).map(function (p) {
      return { x: track.x + p[0] * sc, y: track.y + p[1] * sc };
    });
  }

  function tickRobot(it, dt) {
    var st = ZKB.state;
    if (!st || !st.devices) return;
    var rs = it._robot || (it._robot = {
      running: false, arrived: false, wp: 0, speed: 60,
      ground: '白色', dist: 200, target: ''
    });
    var sc = it.scale || 1;
    var cx = it.x + it.w * sc / 2, cy = it.y + it.h * sc / 2;
    var wps = robotWaypoints();

    /* ---- 地面颜色识别：起点绿 / 终点红 / 轨迹黑 / 其它白 ---- */
    var g = '白色';
    items.forEach(function (o) {
      if (o.k !== 'greenStart' && o.k !== 'redEnd') return;
      var osc = o.scale || 1;
      if (cx >= o.x - 4 && cx <= o.x + o.w * osc + 4 &&
        cy >= o.y - 4 && cy <= o.y + o.h * osc + 4) {
        g = o.k === 'greenStart' ? '绿色' : '红色';
      }
    });
    if (g === '白色' && wps && distToPolyline(cx, cy, wps) < 17) g = '黑色';
    rs.ground = g;

    /* ---- 机器人搭载超声波 + AI 摄像头（朝车头方向） ---- */
    var rot = (it.rot || 0) * Math.PI / 180;
    var dx = Math.cos(rot), dy = Math.sin(rot);
    var best = null, bn = '';
    items.forEach(function (o) {
      if (o === it || NON_OBSTACLE[o.k] || o.k === 'deliverBot') return;
      var osc = o.scale || 1;
      var t2 = rayRect(cx, cy, dx, dy, o.x, o.y, o.x + o.w * osc, o.y + o.h * osc);
      if (t2 !== null && (best === null || t2 < best)) {
        best = t2;
        bn = (LIB()[o.k] || {}).name || '障碍物';
      }
    });
    rs.dist = best === null ? 200 : Math.max(2, Math.min(200, Math.round(best / 2)));
    /* 摄像头：识别 120cm 内的前方物体 */
    rs.target = (best !== null && rs.dist <= 120) ? bn : '';

    /* ---- 巡线移动 ---- */
    if (rs.running && wps && wps.length) {
      if (rs.wp >= wps.length) {
        rs.running = false;
      } else {
        var tp = wps[rs.wp];
        var ddx = tp.x - cx, ddy = tp.y - cy;
        var dd = Math.sqrt(ddx * ddx + ddy * ddy);
        if (dd < 9) {
          rs.wp++;
        } else {
          var sp = (Math.max(10, Math.min(100, rs.speed || 60)) / 100) * 150 * dt;
          var ux = ddx / dd, uy = ddy / dd;
          it.x += ux * sp;
          it.y += uy * sp;
          it.rot = Math.atan2(uy, ux) * 180 / Math.PI;
        }
      }
    }
    /* ---- 到达红色终点自动停止 ---- */
    if (g === '红色' && rs.running) {
      rs.running = false;
      rs.arrived = true;
      say('机器人到达终点！');
    }
    /* 离开终点后再次出发可重新送达 */
    if (g !== '红色') rs.arrived = false;

    /* 状态镜像到 devices（元素标签与积木读取） */
    st.devices.deliverRobot = rs;

    /* 同步 DOM 位置 */
    var gEl = gItems && gItems.querySelector('[data-uid="' + it.uid + '"]');
    if (gEl) applyTransform(gEl.querySelector('g'), it);
  }
  function tickRobotAll(dt) {
    items.forEach(function (it) { if (it.k === 'deliverBot') tickRobot(it, dt); });
  }

  /* 积木 API：S.robot.* 的落地实现 */
  function firstRobot() {
    return items.filter(function (it) { return it.k === 'deliverBot'; })[0] || null;
  }
  function robotState() {
    var it = firstRobot();
    if (!it) return null;
    if (!it._robot) tickRobot(it, 0);
    return it._robot;
  }
  function robotCmd(cmd, v) {
    var it = firstRobot();
    if (!it) return false;
    var rs = it._robot || (it._robot = {
      running: false, arrived: false, wp: 0, speed: 60,
      ground: '白色', dist: 200, target: ''
    });
    if (cmd === 'go') {
      var wps = robotWaypoints();
      if (!wps || !wps.length) {
        ZKB.toast && ZKB.toast('请先添加「巡线轨迹」元素（素材库 → 机器人）');
        return false;
      }
      /* 若已在终点或走完全程，重新从起点出发 */
      if (rs.arrived || rs.wp >= wps.length) {
        rs.wp = 0;
        var tr = items.filter(function (o) { return o.k === 'deliverTrack'; })[0];
        var sc2 = tr ? (tr.scale || 1) : 1;
        it.x = wps[0].x - it.w * sc2 / 2;
        it.y = wps[0].y - it.h * sc2 / 2;
        rs.arrived = false;
      }
      rs.running = true;
      return true;
    }
    if (cmd === 'stop') { rs.running = false; return true; }
    if (cmd === 'speed') {
      rs.speed = Math.max(0, Math.min(100, Math.round(Number(v) || 0)));
      return true;
    }
    return false;
  }

  /* ============================================================
   * 巡线小车（第十四轮）
   *   数据源：st.devices.traceCar（拓展库「巡线小车」设备 / 积木 zk_trace_*）
   *   自动巡线：沿舞台「赛道黑线」元素行驶，并做横向追踪修正
   *   手动模式：按电机积木给出的左右轮速度做差速转向
   *   循线状态写入 tc.line（居中/偏左/偏右/离线），超声波写入 tc.dist
   * ============================================================ */
  var TC_MAXSPEED = 1.6;      /* 满速像素/秒（按 dt 缩放） */
  function traceTrack() {
    return items.filter(function (o) { return o.k === 'trackLine'; })[0] || null;
  }
  function traceState() {
    var st = ZKB.state;
    if (!st) return null;
    if (!st.devices) st.devices = {};
    if (!st.devices.traceCar) {
      st.devices.traceCar = { l: 0, r: 0, auto: true, line: '离线', dist: 200, target: '' };
    }
    return st.devices.traceCar;
  }
  function tickTraceCar(it, dt) {
    var tc = traceState();
    var sc = it.scale || 1;
    var cx = it.x + it.w * sc / 2, cy = it.y + it.h * sc / 2;
    var tr = traceTrack();

    /* ---- 循迹器 5 路探针：判断黑线相对车头的偏移 ---- */
    var line = '离线';
    if (tr) {
      var tsc = tr.scale || 1;
      var ty = tr.y + tr.h * tsc / 2;          /*赛道中心线 y */
      var inX = cx >= tr.x - 10 && cx <= tr.x + tr.w * tsc + 10;
      var dy = ty - cy;                        /* >0 表示车在赛道下方 */
      if (inX) {
        if (Math.abs(dy) <= 9) line = '居中';
        else if (dy > 9 && dy < 26) line = '偏右';
        else if (dy < -9 && dy > -26) line = '偏左';
      }
      /* 自动巡线行驶方向：默认朝 +x（车头朝右） */
      if (tc.dir !== -1 && tc.dir !== 1) tc.dir = 1;
      if (tc.auto && !inX) {
        /* 驶出赛道尽头 → 到终点停车 */
        if ((tc.dir === 1 && cx > tr.x + tr.w * tsc - 4) ||
          (tc.dir === -1 && cx < tr.x + 4)) {
          tc.l = tc.r = 0;
          tc.line = '居中';
          tc.done = true;
        } else {
          tc.done = false;
        }
      } else if (inX) tc.done = false;
    }
    tc.line = line;

    /* ---- 超声波：车头前方最近障碍物 ---- */
    var rot = (it.rot || 0) * Math.PI / 180;
    var dx = Math.cos(rot), dy2 = Math.sin(rot);
    var best = null, bn = '';
    items.forEach(function (o) {
      if (o === it || NON_OBSTACLE[o.k] || o.k === 'ultraSensor') return;
      var osc = o.scale || 1;
      var t2 = rayRect(cx, cy, dx, dy2, o.x, o.y, o.x + o.w * osc, o.y + o.h * osc);
      if (t2 !== null && (best === null || t2 < best)) {
        best = t2; bn = (LIB()[o.k] || {}).name || '障碍物';
      }
    });
    tc.dist = best === null ? 200 : Math.max(2, Math.min(200, Math.round(best / 2)));
    tc.target = (best !== null && tc.dist <= 120) ? bn : '';

    /* ---- 运动 ---- */
    if (tc.auto) {
      if (tr && !tc.done) {
        var tsc2 = tr.scale || 1;
        var ty2 = tr.y + tr.h * tsc2 / 2;
        var err = ty2 - cy;                       /* 横向误差 */
        var spd = TC_MAXSPEED * Math.max(0.25, Math.min(1, (Math.abs(tc.l) || 55) / 100)) * dt * 60;
        it.x += (tc.dir === 1 ? 1 : -1) * spd;
        /* 横向追踪：误差越大修正越快（临界阻尼式，避免抖动） */
        it.y += Math.max(-2.6, Math.min(2.6, err * 0.22)) * Math.min(1.6, dt * 60);
        /* 车头朝向赛道方向（带一点点跟随误差的偏转） */
        var want = (tc.dir === 1 ? 0 : 180) + (err > 0 ? 6 : -6) * Math.min(1, Math.abs(err) / 20);
        it.rot = want;
        tc.l = Math.round(55 + err * 0.6);
        tc.r = Math.round(55 - err * 0.6);
      } else {
        tc.l = tc.r = 0;
      }
    } else {
      /* 手动模式：左右轮差速 */
      var vl = Math.max(-100, Math.min(100, Number(tc.l) || 0));
      var vr = Math.max(-100, Math.min(100, Number(tc.r) || 0));
      var v = (vl + vr) / 2 / 100 * TC_MAXSPEED * dt * 60;
      it.x += Math.cos(rot) * v;
      it.y += Math.sin(rot) * v;
      it.rot += (vr - vl) * 0.9 * dt;
      if (it.rot > 360) it.rot -= 360;
      if (it.rot < 0) it.rot += 360;
    }

    /* 同步 DOM 位置与元素内部朝向 */
    var gEl = gItems && gItems.querySelector('[data-uid="' + it.uid + '"]');
    if (gEl) applyTransform(gEl.querySelector('g'), it);
  }
  function tickTraceCarAll(dt) {
    items.forEach(function (it) { if (it.k === 'traceCar') tickTraceCar(it, dt); });
  }

  /* ---- 光照联动（第十六轮）：光线弱 → 舞台变暗 + 太阳变月亮 + 台灯亮起 ---- */
  function lightScene(t) {
    var st = ZKB.state;
    if (!st) return;
    /* 动画时间戳（供台灯呼吸光晕等元素使用） */
    st._animT = t;

    var lv = sceneLightLevel(st);
    var norm = Math.max(0, Math.min(1, lv / 1200));          /* 1200 以上视为全亮 */
    var dark = Math.max(0, Math.min(1, (520 - lv) / 520));   /* 520 → 0，0 → 1 */

    /* 夜色遮罩 */
    if (night) night.setAttribute('opacity', (dark * 0.55).toFixed(3));
    /* 太阳 / 月亮切换 */
    var sun = document.getElementById('zk-sun');
    if (sun) {
      var pos = (VW - 90) + ',' + (40 + (1 - norm) * 20);
      sun.setAttribute('transform', 'translate(' + pos + ')');
      sun.setAttribute('opacity', (dark > 0.45 ? 0 : (0.25 + norm * 0.75)).toFixed(2));
    }
    var moon = document.getElementById('zk-moon');
    if (moon) {
      moon.setAttribute('transform', 'translate(' + (VW - 86) + ',' + 52 + ')');
      moon.setAttribute('opacity', Math.max(0, Math.min(1, (dark - 0.25) / 0.45)).toFixed(2));
    }
    /* 状态供其它模块判断 */
    st.stageDark = dark;
  }
  /* 舞台取光照度：优先拓展光线传感器，其次板载 */
  function sceneLightLevel(st) {
    if (!st) return 2000;
    var dev = st.devices || {};
    if (dev.lightExt && dev.lightExt.v != null) return dev.lightExt.v;
    return st.light != null ? st.light : 2000;
  }

  /* ============================================================
   * 选中元素信息条（第十九轮）
   *   单击元素 → 舞台下方显示：名称 / 坐标 x,y / 大小 w×h / 缩放 / 旋转 / 层级
   *   拖动时实时刷新；点击空白处取消选中并隐藏
   * ============================================================ */
  var selUid = null;

  function selectedInfo() {
    if (!selUid) return null;
    var idx = -1;
    items.forEach(function (it, i) { if (it.uid === selUid) idx = i; });
    if (idx < 0) return null;
    var it = items[idx];
    var sc = it.scale || 1;
    return {
      uid: it.uid, k: it.k, name: nameOf(it.uid),
      x: Math.round(it.x), y: Math.round(it.y),
      w: Math.round(it.w * sc), h: Math.round(it.h * sc),
      rawW: Math.round(it.w), rawH: Math.round(it.h),
      scale: Math.round(sc * 100),
      rot: Math.round(it.rot || 0),
      layer: idx + 1, total: items.length,
      opacity: it.opacity != null ? Math.round(it.opacity * 100) : 100
    };
  }
  function updateSelInfo() {
    var box = document.getElementById('zk-stage-info');
    if (!box) return;
    var d = selectedInfo();
    if (!d) { box.classList.add('hidden'); box.innerHTML = ''; return; }
    box.classList.remove('hidden');
    box.innerHTML =
      '<span class="zi-name">' + esc(d.name) + '</span>' +
      '<span class="zi-tag">x ' + d.x + '</span>' +
      '<span class="zi-tag">y ' + d.y + '</span>' +
      '<span class="zi-tag">大小 ' + d.w + ' × ' + d.h + '</span>' +
      '<span class="zi-tag">缩放 ' + d.scale + '%</span>' +
      '<span class="zi-tag">旋转 ' + d.rot + '°</span>' +
      '<span class="zi-tag">层级 ' + d.layer + ' / ' + d.total + '</span>' +
      (d.opacity < 100 ? '<span class="zi-tag">透明 ' + d.opacity + '%</span>' : '');
  }
  function selectItem(uid) {
    selUid = uid || null;
    root.querySelectorAll('.stage-item.sel').forEach(function (n) { n.classList.remove('sel'); });
    if (selUid) {
      var g = gItems.querySelector('[data-uid="' + selUid + '"]');
      if (g) g.classList.add('sel');
    }
    updateSelInfo();
  }

  /* ============================================================
   * 每帧渲染
   * ============================================================ */
  function frame(ts) {
    if (!root) { rafId = requestAnimationFrame(frame); return; }
    var t = (ts - t0) / 1000;
    var dt = Math.min(0.05, (ts - (frame._last || ts)) / 1000);
    frame._last = ts;
    var st = ZKB.state;

    /* 光照联动：夜色遮罩 + 太阳/月亮 + 亮度时间戳 */
    lightScene(t);

    /* 小车运动 */
    items.forEach(function (it) { if (it.k === 'car') tickCar(it, dt); });

    /* 串口输出气泡跟随小助手（第二十四轮） */
    if (gSay) drawSayBubble();

    /* 元素行走（第二十一轮）：行人 / 车辆从上往下走到指定 y（按真实 dt 推进） */
    items.forEach(function (it) { if (it._walk && !it._walk.done) tickWalk(it, dt); });

    /* 超声波舞台测距（到前方障碍物元素的距离） */
    ultraScanAll();

    /* 送餐机器人巡线（地面颜色 / 超声波 / 摄像头同步） */
    tickRobotAll(dt);

    /* 巡线小车（电机 / 循迹器 / 超声波） */
    tickTraceCarAll(dt);

    /* 更新所有元素外观 */
    updateItems();

    /* 变量监视器 */
    drawMonitors();

    /* 小助手（掌握小助手表情随屏幕同步） */
    updateAssistant(t);

    /* 气泡 */
    if (bubble && !bubble.classList.contains('hidden') && Date.now() > bubbleHideAt) hideBubble();

    rafId = requestAnimationFrame(frame);
  }

  /* ============================================================
   * 变量 / 列表监视器（SVG 卡片）
   * ============================================================ */
  function drawMonitors() {
    var vars = {}, lists = {}, values = {};
    if (ZKB.SimEngine && ZKB.SimEngine.isRunning && ZKB.SimEngine.isRunning()) {
      var m = ZKB.SimEngine.getMonitors();
      vars = m.vars; lists = m.lists; values = m.values;
    } else if (global.Blockly && Blockly.getMainWorkspace) {
      var w = Blockly.getMainWorkspace();
      if (w) w.getAllVariables().forEach(function (vm) {
        if (vm.type === 'LIST') lists[vm.name] = true; else vars[vm.name] = true;
      });
    }
    var y = 8;
    var html = '';
    Object.keys(vars).forEach(function (name) {
      var val = values[name];
      var txt = (val === undefined || val === null) ? '0' : String(val);
      html += '<g transform="translate(' + (VW - 150) + ',' + y + ')">' +
        '<rect width="142" height="26" rx="6" fill="rgba(255,255,255,.94)" stroke="#d4d9e0"/>' +
        '<rect width="4" height="26" rx="2" fill="#e06a2b"/>' +
        '<text x="10" y="17" font-size="11" fill="#5b6470">' + esc(cut(name, 6)) + '</text>' +
        '<rect x="92" y="4" width="46" height="18" rx="9" fill="#e06a2b"/>' +
        '<text x="115" y="17" font-size="11" font-weight="700" text-anchor="middle" fill="#fff">' +
        esc(cut(txt, 6)) + '</text></g>';
      y += 30;
    });
    Object.keys(lists).forEach(function (name) {
      var arr = values[name];
      var its = Array.isArray(arr) ? arr : [];
      var h = 24 + Math.max(1, its.length) * 15 + 6;
      html += '<g transform="translate(' + (VW - 150) + ',' + y + ')">' +
        '<rect width="142" height="' + h + '" rx="6" fill="rgba(255,255,255,.94)" stroke="#d4d9e0"/>' +
        '<rect width="4" height="' + h + '" rx="2" fill="#e06a2b"/>' +
        '<text x="10" y="15" font-size="10" fill="#5b6470">' + esc(cut(name, 7)) + '</text>' +
        '<text x="136" y="15" font-size="9" text-anchor="end" fill="#c04a12">长度 ' + its.length + '</text>';
      its.slice(0, 6).forEach(function (v, i) {
        var ry = 20 + i * 15;
        html += '<rect x="6" y="' + ry + '" width="130" height="13" rx="3" fill="' + (i % 2 ? '#f3f5f8' : '#e9edf2') + '"/>' +
          '<text x="10" y="' + (ry + 10) + '" font-size="9" fill="#3a424d">' + esc(cut(String(v), 14)) + '</text>';
      });
      html += '</g>';
      y += h + 8;
    });
    gUi.innerHTML = html;
  }
  function cut(s, n) { s = String(s); return s.length > n ? s.slice(0, n) + '…' : s; }
  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

  /* ============================================================
   * 掌控小助手（表情与掌控板屏幕同步）
   * ============================================================ */
  /* ============================================================
   * 掌控小助手：可缩放 / 可移动，显示 RGB 灯光、屏幕文字与屏幕图片
   * 屏幕内容与虚拟仿真中掌控板的 OLED 保持同步。
   * ============================================================ */
  function updateAssistant(t) {
    var g = document.getElementById('zk-assistant');
    if (!g) {
      g = el('g', { id: 'zk-assistant', class: 'stage-item stage-item-clickable' }, gFx);
    }
    var st = ZKB.state;
    var bob = Math.sin(t * 1.8) * 3;
    /* 缩放 + 不透明度（右键可调） */
    var sc = assistant.scale || 1;
    var t1 = 'translate(' + assistant.x + ',' + (assistant.y + bob) + ')';
    if (sc !== 1) t1 += ' scale(' + sc + ')';
    g.setAttribute('transform', t1);
    if (assistant.opacity != null) g.setAttribute('opacity', assistant.opacity);
    g.setAttribute('data-uid', 'assistant');

    var s = '';
    /* 天线 */
    s += '<line x1="0" y1="-62" x2="0" y2="-84" stroke="#37414d" stroke-width="3.5"/>';
    s += '<circle cx="0" cy="-88" r="6" fill="#ff5d5d"/>';
    /* 提手（提示可拖动） */
    s += '<path d="M-16,-56 q16,-9 32,0" fill="none" stroke="#4a5560" stroke-width="3.5" ' +
      'stroke-linecap="round" opacity=".7"/>';
    /* 身体（加大） */
    s += '<rect x="-58" y="-64" width="116" height="108" rx="16" fill="#2b2f36"/>';
    s += '<rect x="-58" y="-64" width="116" height="108" rx="16" fill="none" ' +
      'stroke="#454f5a" stroke-width="1.5"/>';
    /* 屏幕外框 */
    s += '<rect x="-44" y="-52" width="88" height="58" rx="7" fill="#111820"/>';
    s += '<rect x="-40" y="-48" width="80" height="50" rx="4" fill="#0b1410"/>';
    /* 屏幕内容：优先显示屏幕图片，其次显示表情 */
    s += assistantScreen();
    /* RGB 灯（显示灯光状态） */
    if (st) {
      for (var i = 0; i < 3; i++) {
        var c = st.rgb.dots[i], br = st.rgb.brightness;
        var col = 'rgb(' + ((c[0] * br) | 0) + ',' + ((c[1] * br) | 0) + ',' + ((c[2] * br) | 0) + ')';
        s += '<circle cx="' + (-22 + i * 22) + '" cy="-58" r="4.5" fill="' + col + '"/>';
        /* 点亮时加光晕 */
        var lum = (c[0] + c[1] + c[2]) * br;
        if (lum > 30) {
          s += '<circle cx="' + (-22 + i * 22) + '" cy="-58" r="9" fill="' + col + '" opacity=".3"/>';
        }
      }
    }
    /* 屏幕下方文字（第五十轮：上移 3px，给下面的触摸焊盘腾出间距） */
    s += '<text x="0" y="17" font-size="10" font-weight="600" text-anchor="middle" fill="#8a939e">' +
      esc(assistantScreenText()) + '</text>';
    /* 第五十轮：A / B 按键（身体上方两侧，避开天线与提手）
       和真板一样是「金色外圈 + 白色键帽」，按下时键帽下沉、外圈发光。
       点击后走 ZKB.SimBoard.pressBtn()，与虚拟仿真里的按键共用同一份状态，
       所以「当按键 A 被按下」「按键 B 被按下？」在舞台模式下同样有效。 */
    s += assistantKey('A', -42, -80);
    s += assistantKey('B', 42, -80);
    /* 第五十轮：PYTHON 六个触摸焊盘（身体下方，与真板底部金手指同位置）
       点击 → ZKB.SimBoard.pressTouch()，驱动「当触摸 P 被触摸」等积木。 */
    var PADS = ['P', 'Y', 'T', 'H', 'O', 'N'];
    for (var pi = 0; pi < PADS.length; pi++) {
      s += assistantTouchPad(PADS[pi], -40 + pi * 16, 35);
    }
    /* 名称 */
    s += '<text x="0" y="62" font-size="14" font-weight="700" text-anchor="middle" fill="#37414d">掌 控 小 助 手</text>';
    /* 脚下底座 */
    s += '<ellipse cx="0" cy="48" rx="34" ry="6" fill="rgba(30,50,80,.14)"/>';
    g.innerHTML = s;
  }

  /* ============================================================
   * 第五十轮：小助手上的实体按键 / 触摸焊盘
   *
   * 【为什么要做】原来舞台模式下只能看屏幕，按不了键 ——
   * 学生写的「当按键 A 被按下 → 亮灯」在舞台里永远不触发，
   * 只能切回虚拟仿真去点。这里把小助手的按键与焊盘画出来，
   * 点击直接复用 ZKB.SimBoard.pressBtn / pressTouch，
   * 两种模式共用同一份 state.btn / state.touch，程序行为完全一致。
   *
   * 视觉：A/B = 金色外圈 + 白色键帽（真板同款）；按下键帽下沉变暗、
   *       外圈透出暖黄光晕。
   *       PYTHON = 金色圆焊盘；被触摸时整颗点亮并出现波纹。
   * ⚠ 命中区（透明圆）必须画在最后，否则会被上面的图形挡住点不到。
   * ============================================================ */
  function assistantKey(k, cx, cy) {
    var st = ZKB.state;
    var down = !!(st && st.btn && st.btn[k]);
    var o = '';
    /* 投影 */
    o += '<ellipse cx="' + cx + '" cy="' + (cy + 5) + '" rx="12" ry="3.6" fill="rgba(0,0,0,.16)"/>';
    /* 按下时的暖黄光晕（画在金圈下面，向外溢出） */
    if (down) {
      o += '<circle cx="' + cx + '" cy="' + cy + '" r="16" fill="#ffd24a" opacity=".32"/>';
    }
    /* 金色外圈 */
    o += '<circle cx="' + cx + '" cy="' + cy + '" r="11.5" fill="' +
      (down ? '#d8b23c' : '#e8c24a') + '" stroke="#a8862a" stroke-width="1.2"/>';
    /* 白色键帽（按下时下沉 1.2px 并变暗） */
    o += '<circle cx="' + cx + '" cy="' + (cy + (down ? 1.2 : 0)) + '" r="7.8" fill="' +
      (down ? '#c6ced6' : '#f5f7f9') + '" stroke="#c2c9d1" stroke-width=".8"/>';
    /* 字母 */
    o += '<text x="' + cx + '" y="' + (cy + 3.4 + (down ? 1.2 : 0)) +
      '" text-anchor="middle" font-size="9" font-weight="700" fill="#5a636e" ' +
      'style="pointer-events:none">' + k + '</text>';
    /* 命中区（最后画，保证在最上层） */
    o += '<circle class="zk-key" data-key="' + k + '" cx="' + cx + '" cy="' + cy + '" r="15" ' +
      'fill="transparent" style="cursor:pointer">' +
      '<title>按下 ' + k + ' 键（与虚拟仿真共用状态）</title></circle>';
    return o;
  }

  function assistantTouchPad(p, cx, cy) {
    var st = ZKB.state;
    var down = !!(st && st.touch && st.touch[p]);
    var o = '';
    /* 被触摸时的波纹 */
    if (down) {
      o += '<circle cx="' + cx + '" cy="' + cy + '" r="11" fill="#ffd24a" opacity=".3"/>';
    }
    /* 焊盘本体 */
    o += '<circle cx="' + cx + '" cy="' + cy + '" r="7" fill="' +
      (down ? '#ffd24a' : '#c9a23c') + '" stroke="' +
      (down ? '#b8922e' : '#8a6f22') + '" stroke-width="1"/>';
    /* 字母 */
    o += '<text x="' + cx + '" y="' + (cy + 2.7) + '" text-anchor="middle" font-size="6.6" ' +
      'font-weight="700" fill="' + (down ? '#4a3a00' : '#3a2f10') + '" ' +
      'style="pointer-events:none">' + p + '</text>';
    /* 命中区 */
    o += '<circle class="zk-tp" data-touch="' + p + '" cx="' + cx + '" cy="' + cy + '" r="9.5" ' +
      'fill="transparent" style="cursor:pointer">' +
      '<title>触摸 ' + p + ' 焊盘（与虚拟仿真共用状态）</title></circle>';
    return o;
  }

  /* 小助手屏幕内容（与虚拟仿真 OLED 同步）
     优先级：程序实时绘制内容（文字/图形）→ 屏幕图片/表情图 → 表情 */
  var oledMirrorCache = { ver: -1, url: '' };
  function assistantScreen() {
    var st = ZKB.state;
    /* 0) 程序在 OLED 上绘制了内容（文字/图形/图片）→ 镜像整个屏幕 */
    if (st && st.oledLive) {
      var cv = (ZKB.Board3D && ZKB.Board3D.oledCanvas && ZKB.Board3D.oledCanvas()) ||
        document.getElementById('oled-canvas');
      if (cv && cv.toDataURL) {
        try {
          if (oledMirrorCache.ver !== st.oledVer) {
            oledMirrorCache.ver = st.oledVer;
            oledMirrorCache.url = cv.toDataURL('image/png');
          }
          if (oledMirrorCache.url) {
            return '<image href="' + oledMirrorCache.url + '" x="-40" y="-48" width="80" height="50" ' +
              'preserveAspectRatio="xMidYMid meet" image-rendering="pixelated"/>' +
              '<rect x="-40" y="-48" width="80" height="50" rx="4" fill="none" ' +
              'stroke="#2a3a30" stroke-width="1"/>';
          }
        } catch (e) { /* jsdom 等环境不支持 toDataURL 时回退到表情 */ }
      }
    }
    /* 1) 有屏幕图片 → 显示图片 */
    var rec = getScreenBits();
    if (rec) {
      try {
        var url = ZKB.OledImage.bitsToDataURL(rec);
        if (url) {
          return '<image href="' + url + '" x="-40" y="-48" width="80" height="50" ' +
            'preserveAspectRatio="xMidYMid meet" image-rendering="pixelated"/>' +
            '<rect x="-40" y="-48" width="80" height="50" rx="4" fill="none" ' +
            'stroke="#2a3a30" stroke-width="1"/>';
        }
      } catch (e) { /* 忽略 */ }
    }
    /* 2) 否则显示表情 */
    var mood = (st && st.oledMood) || 'idle';
    return moodFace(mood, -22);
  }

  /* 取当前屏幕位图（表情图也走位图） */
  function getScreenBits() {
    if (!ZKB.OledImage || !ZKB.OledImage.current) return null;
    var rec = ZKB.OledImage.current();
    return (rec && rec.bits) ? rec.bits : null;
  }

  /* 小助手屏幕下方文字（跟随屏幕内容） */
  function assistantScreenText() {
    var st = ZKB.state;
    /* 1) 程序绘制的文字优先 */
    if (st && st.oledLive && st.oledLastText) return st.oledLastText;
    /* 2) 屏幕图片 / 表情图名称 */
    var rec = ZKB.OledImage && ZKB.OledImage.current && ZKB.OledImage.current();
    if (rec && rec.name) return rec.name;
    /* 3) 程序绘制了内容（无文字） */
    if (st && st.oledLive) return '屏幕显示中';
    var mood = (st && st.oledMood) || '';
    if (mood && mood !== 'idle') {
      var F = (ZKB.OledImage && ZKB.OledImage.FACES) || {};
      return (F[mood] && F[mood].name) || '屏幕显示中';
    }
    return '掌控板屏幕';
  }
  /* 仅重绘小助手（供右键菜单 / 屏幕变化时调用） */
  function renderAssistant() {
    var g = document.getElementById('zk-assistant');
    if (!g) return;
    /* 触发一帧即可完成重绘 */
    updateAssistant((performance.now() - t0) / 1000);
  }

  function moodFace(mood, oy) {
    var eyeY = -22 + oy;
    /* 颜色按情绪区分（与内置表情一一对应） */
    var C = {
      happy: '#7fe0c8', angry: '#ff6b6b', sad: '#8ab4ff', calm: '#9ad9b8',
      wow: '#ffd24a', think: '#c9b6ff', love: '#ff8fb1', sleep: '#b9c6d6',
      cry: '#7fb6ff', star: '#ffe07a', surprised: '#ffd24a', idle: '#7fe0c8'
    };
    var col = C[mood] || C.idle;
    /* 弯弯眼（喜 / 乐） */
    if (mood === 'happy' || mood === 'star') {
      s = '<path d="M-20,' + (eyeY + 4) + ' q5,-7 10,0" stroke="' + col + '" stroke-width="2.4" fill="none" stroke-linecap="round"/>' +
        '<path d="M10,' + (eyeY + 4) + ' q5,-7 10,0" stroke="' + col + '" stroke-width="2.4" fill="none" stroke-linecap="round"/>';
      if (mood === 'star') {
        s += '<path d="M-15,' + (eyeY + 1) + ' l3,3 l-3,3 l-3,-3 z" fill="#ffe07a"/>' +
          '<path d="M15,' + (eyeY + 1) + ' l3,3 l-3,3 l-3,-3 z" fill="#ffe07a"/>';
      }
      return s + smile(col, eyeY, 13);
    }
    if (mood === 'angry') {
      return '<path d="M-22,' + (eyeY - 4) + ' l12,5 M22,' + (eyeY - 4) + ' l-12,5" stroke="' + col + '" stroke-width="2.4" stroke-linecap="round"/>' +
        '<circle cx="-15" cy="' + (eyeY + 5) + '" r="3.6" fill="' + col + '"/>' +
        '<circle cx="15" cy="' + (eyeY + 5) + '" r="3.6" fill="' + col + '"/>' +
        '<path d="M-13,' + (eyeY + 19) + ' q6,-7 13,-1 q7,-6 13,1" stroke="' + col + '" stroke-width="2.4" fill="none" stroke-linecap="round"/>';
    }
    if (mood === 'sad' || mood === 'cry') {
      var s2 = '<circle cx="-15" cy="' + (eyeY + 6) + '" r="3.6" fill="' + col + '"/>' +
        '<circle cx="15" cy="' + (eyeY + 6) + '" r="3.6" fill="' + col + '"/>' +
        '<path d="M-12,' + (eyeY + 20) + ' q12,-10 24,0" stroke="' + col + '" stroke-width="2.4" fill="none" stroke-linecap="round"/>' +
        '<circle cx="-24" cy="' + (eyeY + 12) + '" r="2.6" fill="' + col + '" opacity=".7"/>';
      if (mood === 'cry') {
        s2 += '<path d="M-15,' + (eyeY + 10) + ' v6" stroke="' + col + '" stroke-width="2" stroke-linecap="round"/>' +
          '<path d="M15,' + (eyeY + 10) + ' v6" stroke="' + col + '" stroke-width="2" stroke-linecap="round"/>';
      }
      return s2;
    }
    if (mood === 'wow' || mood === 'surprised') {
      return '<circle cx="-15" cy="' + (eyeY + 4) + '" r="4.6" fill="none" stroke="' + col + '" stroke-width="2.2"/>' +
        '<circle cx="15" cy="' + (eyeY + 4) + '" r="4.6" fill="none" stroke="' + col + '" stroke-width="2.2"/>' +
        '<ellipse cx="0" cy="' + (eyeY + 18) + '" rx="6" ry="7" fill="none" stroke="' + col + '" stroke-width="2.2"/>';
    }
    if (mood === 'think') {
      return '<path d="M-20,' + (eyeY + 4) + ' q5,-6 10,0" stroke="' + col + '" stroke-width="2.4" fill="none" stroke-linecap="round"/>' +
        '<circle cx="15" cy="' + (eyeY + 3) + '" r="3.6" fill="' + col + '"/>' +
        '<line x1="-8" y1="' + (eyeY + 16) + '" x2="8" y2="' + (eyeY + 14) + '" stroke="' + col + '" stroke-width="2.2" stroke-linecap="round"/>' +
        '<circle cx="24" cy="' + (eyeY - 8) + '" r="2" fill="' + col + '" opacity=".8"/>' +
        '<circle cx="29" cy="' + (eyeY - 14) + '" r="2.6" fill="' + col + '" opacity=".6"/>';
    }
    if (mood === 'love') {
      return '<path d="M-15,' + (eyeY + 3) + ' c-5,-6 -12,0 0,7 c12,-7 5,-13 0,-7 z" fill="#ff8fb1"/>' +
        '<path d="M15,' + (eyeY + 3) + ' c-5,-6 -12,0 0,7 c12,-7 5,-13 0,-7 z" fill="#ff8fb1"/>' +
        '<circle cx="-24" cy="' + (eyeY + 12) + '" r="2.6" fill="#ff8fb1" opacity=".6"/>' +
        '<circle cx="24" cy="' + (eyeY + 12) + '" r="2.6" fill="#ff8fb1" opacity=".6"/>' +
        smile('#ff8fb1', eyeY, 11);
    }
    if (mood === 'sleep') {
      return '<path d="M-20,' + (eyeY + 1) + ' q5,6 10,0" stroke="' + col + '" stroke-width="2.4" fill="none" stroke-linecap="round"/>' +
        '<path d="M10,' + (eyeY + 1) + ' q5,6 10,0" stroke="' + col + '" stroke-width="2.4" fill="none" stroke-linecap="round"/>' +
        '<ellipse cx="0" cy="' + (eyeY + 15) + '" rx="4" ry="4.6" fill="none" stroke="' + col + '" stroke-width="2.2"/>' +
        '<text x="22" y="' + (eyeY - 6) + '" font-size="13" font-weight="700" fill="' + col + '">z</text>' +
        '<text x="30" y="' + (eyeY - 15) + '" font-size="10" font-weight="700" fill="' + col + '">z</text>';
    }
    /* idle / calm */
    var cc = (mood === 'calm') ? C.calm : C.idle;
    return '<circle cx="-14" cy="' + eyeY + '" r="3.8" fill="' + cc + '"/>' +
      '<circle cx="14" cy="' + eyeY + '" r="3.8" fill="' + cc + '"/>' +
      '<path d="M-8,' + (eyeY + 12) + ' q8,7 16,0" stroke="' + cc + '" stroke-width="2.2" fill="none" stroke-linecap="round"/>';
  }
  /* 小助手微笑弧（joy 为 true 时加深） */
  function smile(col, eyeY, w) {
    w = w || 12;
    return '<path d="M-' + w + ',' + (eyeY + 12) + ' q' + w + ',13 ' + (w * 2) + ',0" stroke="' + col +
      '" stroke-width="2.4" fill="none" stroke-linecap="round"/>';
  }

  /* ============================================================
   * 元素标签（状态提示，如「湿度 800」「热水壶 65°C」）
   * 每帧会调用，故做增量更新：文本不变则不碰 DOM，避免性能抖动。
   *
   * 第三十四轮修正：标签原本挂在未变换的 .stage-item 分组上，
   * 于是所有元素的文字全都堆在舞台左上角。现在按元素实际坐标
   * 计算，标签稳稳落在各自元素正下方。
   * ============================================================ */
  function updateItemLabel(it) {
    var def = LIB()[it.k];
    if (!def || !def.label) return;
    var g = gItems.querySelector('[data-uid="' + it.uid + '"]');
    if (!g) return;
    var lg = g.querySelector('.stage-item-label');
    /* 单独隐藏此元素文字（第三十四轮）：移除标签节点 */
    if (it.hideText) {
      if (lg) lg.remove();
      return;
    }
    /* 全局隐藏时由 CSS（hide-labels）负责，不必动 DOM */
    if (!stageOpts.showText) return;
    var txt = def.label(ZKB.state);
    if (!txt) return;
    txt = String(txt);

    /* 文本未变：仅在缺失时补建 */
    if (lg && lg.getAttribute('data-txt') === txt) {
      placeItemLabel(it, lg);
      return;
    }
    if (!lg) {
      lg = el('g', { class: 'stage-item-label' }, g);
    }
    var wpx = Math.max(46, txt.length * 11 + 14);
    lg.setAttribute('data-txt', txt);
    /* 内容以原点为中心绘制，由 placeItemLabel 用 transform 定位到元素下方 */
    lg.innerHTML = '<rect x="' + (-wpx / 2) + '" y="0" width="' + wpx +
      '" height="20" rx="10" fill="rgba(30,50,80,.82)"/>' +
      '<text x="0" y="14" font-size="11" text-anchor="middle" fill="#fff">' +
      esc(txt) + '</text>';
    placeItemLabel(it, lg);
  }
  /* 把标签定位到元素正下方（元素有旋转 / 缩放时按包围盒估算） */
  function placeItemLabel(it, lg) {
    if (!lg) return;
    var p = itemCornerPos(it, it.w / 2, it.h);
    lg.setAttribute('transform', 'translate(' + p.x.toFixed(1) + ',' + (p.y + 6).toFixed(1) + ')');
  }
  /* 单独隐藏 / 显示某个元素的文字 */
  function applyItemTextHidden(it) {
    var g = gItems.querySelector('[data-uid="' + it.uid + '"]');
    if (!g) return;
    var old = g.querySelector('.stage-item-label');
    if (old) old.remove();
    updateItemLabel(it);
  }

  /* ============================================================
   * 提示气泡 / 元素库面板
   * ============================================================ */
  /* 舞台提示气泡：靠右下方显示，避免遮挡顶部工具栏与右上角按钮 */
  function toastPill(text) {
    if (!bubble) return;
    bubble.textContent = text;
    bubble.classList.remove('hidden');
    bubble.classList.add('toast-right');
    bubble.style.left = '';
    bubble.style.top = '';
    bubbleHideAt = Date.now() + 2200;
  }

  /* 串口输出气泡：显示在小助手旁边（默认左侧偏上），随小助手一起移动 */
  function say(text) {
    if (text === undefined || text === null || text === '') return;
    sayText = String(text);
    /* 按宽度折行（每行最多 16 个中文字符 / 32 个西文字符） */
    var maxCh = 40, out = [], line = '';
    for (var i = 0; i < sayText.length; i++) {
      line += sayText[i];
      var w = 0, k;
      for (k = 0; k < line.length; k++) w += line.charCodeAt(k) > 255 ? 2 : 1;
      if (w >= maxCh) { out.push(line); line = ''; }
    }
    if (line) out.push(line);
    sayLines = out.slice(0, 4);
    sayHideAt = Date.now() + 4000;
    if (!gSay) makeSayBubble();
    drawSayBubble();
  }

  /* 创建 SVG 气泡组（放在 UI 层最上，永远显示在最前） */
  function makeSayBubble() {
    if (gSay && gSay.parentNode) return;
    /* 图层可能因重建设备而失效，这里按需重建 */
    if (!gSayLayer || !gSayLayer.parentNode) {
      gSayLayer = document.getElementById('stage-layer-say');
      if (!gSayLayer && root) {
        gSayLayer = layer('g', 'stage-layer-say');
        root.appendChild(gSayLayer);
      }
    }
    if (!gSayLayer) return;
    gSay = el('g', { id: 'zk-say', class: 'zk-say' }, gSayLayer);
    gSay.style.pointerEvents = 'none';
  }

  /* 绘制气泡（内容 + 位置），每帧调用以跟随小助手 */
  function drawSayBubble() {
    if (!gSay) return;
    if (!sayLines.length) { gSay.innerHTML = ''; gSay.style.display = 'none'; return; }
    /* 超时自动隐藏 */
    if (Date.now() > sayHideAt) { gSay.style.display = 'none'; gSay.innerHTML = ''; sayLines = []; return; }
    gSay.style.display = '';

    var fs = 20, lh = 27, padX = 15, padY = 11;   /* 第二十五轮：字号 15→20 更大更易读 */
    var maxW = 0, k;
    for (k = 0; k < sayLines.length; k++) {
      var w = 0, j;
      for (j = 0; j < sayLines[k].length; j++) w += sayLines[k].charCodeAt(j) > 255 ? fs : fs * 0.56;
      if (w > maxW) maxW = w;
    }
    var bw = Math.min(400, Math.ceil(maxW) + padX * 2);
    var bh = sayLines.length * lh + padY * 2;

    /* 位置：小助手左侧（空间不够时改到右侧），垂直居中偏上 */
    var ax = assistant.x, ay = assistant.y - 46;
    var bx = ax - bw - 26, by = ay - bh / 2;
    if (bx < 8) bx = ax + 26;                     /* 左侧放不下 → 挪到右侧 */
    bx = Math.max(8, Math.min(VW - bw - 8, bx));
    by = Math.max(8, Math.min(VH - bh - 8, by));

    var html = '<rect x="' + bx + '" y="' + by + '" width="' + bw + '" height="' + bh +
      '" rx="12" fill="rgba(255,255,255,.96)" stroke="#2b2f36" stroke-width="2"/>';
    /* 指向小助手的小尖角 */
    var tipX = (bx + bw / 2 < ax) ? bx + bw : bx;
    var tipDir = (bx + bw / 2 < ax) ? 1 : -1;
    html += '<path d="M' + tipX + ',' + (by + bh / 2 - 9) +
      ' l' + (15 * tipDir) + ',9 l' + (-15 * tipDir) + ',9 z" fill="rgba(255,255,255,.96)" stroke="#2b2f36" stroke-width="2"/>';
    /* 左侧尖角描边覆盖（避免中间竖线） */
    html += '<line x1="' + tipX + '" y1="' + (by + bh / 2 - 9) + '" x2="' + tipX +
      '" y2="' + (by + bh / 2 + 9) + '" stroke="rgba(255,255,255,.96)" stroke-width="3"/>';
    /* 串口图标 + 文字（标签字号 14） */
    html += '<text x="' + (bx + padX) + '" y="' + (by + padY + 12) +
      '" font-size="14" fill="#15a89a" font-weight="700">&#x2325; 串口</text>';
    for (k = 0; k < sayLines.length; k++) {
      html += '<text x="' + (bx + padX) + '" y="' + (by + padY + fs + 6 + k * lh) +
        '" font-size="' + fs + '" fill="#1f2430">' + escXML(sayLines[k]) + '</text>';
    }
    gSay.innerHTML = html;
  }
  function escXML(t) {
    return String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function hideBubble() { bubble && bubble.classList.add('hidden'); }

  /* ============================================================
   * 硬件联动：虚拟仿真中添加的设备，在舞台上出现对应元素
   * ============================================================ */
  var DEV_ELEMENT = {
    dht: 'dhtSensor', ultrasonic: 'ultraSensor',
    ir: 'irObstacle', heater: 'heater', car: 'car', pump: 'pump',
    soil: 'pot', button: 'wallSwitch',
    robot: 'deliverBot', powerMeter: 'powerMeterBox', irRx: 'irObstacle',
    tracker: 'trackerPad',
    ledModule: 'deskLamp', rgbStrip: 'rgbStrip', relay: 'appliance',
    /* 第十二轮补全：更多拓展库硬件的舞台元素 */
    servo: 'servoArm', motor: 'dcMotor',
    /* 第五十轮：原来 fan 映射到 'fan'，但元素库里根本没有这个 key，
       于是「添加风扇」在舞台上永远看不到东西。改指向节能风扇。 */
    fan: 'energyFan',
    /* 第五十轮：补齐原来没有舞台元素的三类设备 */
    pir: 'pirSensor', mp3: 'mp3Box',
    color: 'colorSensor', gravity: 'as7341Sensor', camera: 'aiCamera',
    mic: 'micSensor', lightExt: 'lightSensor', angle: 'angleSensor',
    pm25: 'pm25Sensor', baro: 'baroSensor',
    irTx: 'irTxModule', remote: 'irRemote',
    /* 第十四轮：巡线小车（机器人模型由舞台情景自行布置元素） */
    traceCar: 'traceCar'
  };
  var linkedItems = {};   /* devId → uid */

  /* 把虚拟仿真中「已添加」的硬件映射为舞台元素：
     添加设备 → 舞台同步出现对应元素；移除设备 → 舞台同步移除 */
  function syncDevicesToStage() {
    if (!ZKB.SimBoard || !ZKB.SimBoard.getDevices) return;
    /* 舞台还没渲染出来（初始化阶段 setDevices 被提前调用）时直接跳过，
       等 init 之后 syncDevices 会再跑一次 */
    if (!root || !gItems) return;
    var devs = ZKB.SimBoard.getDevices();
    /* 移除已断开的联动元素 */
    Object.keys(linkedItems).forEach(function (d) {
      if (devs.indexOf(d) >= 0) return;
      var uid = linkedItems[d];
      var g = gItems.querySelector('[data-uid="' + uid + '"]');
      if (g) g.remove();
      /* 同时从 items 移除，否则元素仍被计入 getItems() 与场景持久化 */
      items = items.filter(function (x) { return x.uid !== uid; });
      delete linkedItems[d];
    });
    /* 新增联动元素 */
    devs.forEach(function (d, i) {
      if (linkedItems[d]) return;
      var key = DEV_ELEMENT[d];
      if (!key || !LIB()[key]) return;
      /* ⚠ 第三十二轮：场景本身往往已经摆了同一个元素
         （如 traffic 情景里已有 car 与 pedestrian）。
         再加一个联动的 car 会挡住真车的探测线 ——
         实测「小车测到前方行人距离」直接被顶到 200 上限。
         所以这里先看舞台上有没有同类元素，有就复用它、只补 dev 标记。 */
      var exist = items.filter(function (x) { return x.k === key; })[0];
      if (exist) {
        exist.dev = d;
        linkedItems[d] = exist.uid;
        updateItemLabel(exist);
        return;
      }
      var pos = findFreeSpot(i);
      var it = addItem(key, pos.x, pos.y, true);
      if (!it) return;
      it.dev = d;                       /* 标记联动：锁定时仍可移动 */
      linkedItems[d] = it.uid;
      updateItemLabel(it);
    });
    applyLockState();
    saveScene();
  }

  /* 为联动元素安排摆位（沿舞台下方错开） */
  function findFreeSpot(i) {
    var x = 90 + (i % 6) * 112;
    var y = Math.round(VH * 0.78) + Math.floor(i / 6) * 92;
    return {
      x: Math.min(VW - 60, Math.max(50, x)),
      y: Math.min(VH - 50, Math.max(130, y))
    };
  }

  /* 场景恢复后重建联动索引 */
  function rebuildLinked() {
    linkedItems = {};
    items.forEach(function (it) { if (it.dev) linkedItems[it.dev] = it.uid; });
  }


    /* ============================================================
   * 场景持久化（localStorage：体积小、刷新即恢复）
   * ============================================================ */
  var SKEY = 'zkb_stage_scene_v1';
  function saveScene() {
    if (!ZKB.Store) return;
    var customList = [];
    items.forEach(function (i) {
      if (i.custom) customList.push({ id: i.custom.id, name: i.custom.name, url: i.custom.url, w: i.w, h: i.h });
    });
    ZKB.Store.setLocal(SKEY, {
      items: items.map(function (i) {
        return {
          k: i.k, x: i.x, y: i.y, rot: i.rot || 0, scale: i.scale || 1,
          opacity: i.opacity != null ? i.opacity : null,
          dev: i.dev || null,
          locked: i.locked ? 1 : 0,
          hideText: i.hideText ? 1 : 0,
          custom: i.custom || null
        };
      }),
      assistant: { x: assistant.x, y: assistant.y },
      /* 第三十八轮：记录当前生效的情景 key，
         恢复场景时用来同步「情景」下拉框与情景名。 */
      sceneKey: curSceneKey || '',
      savedAt: Date.now()
    });
  }

  function restoreScene() {
    var raw = ZKB.Store && ZKB.Store.getLocal(SKEY);
    /* 先恢复尺寸，再恢复元素（坐标按新尺寸解释） */
    loadSize();
    var aPos = ZKB.Store && ZKB.Store.getLocal('zkb_assistant_v1');
    if (aPos && aPos.x) { assistant.x = aPos.x; assistant.y = aPos.y; }

    if (!raw || !raw.items || !raw.items.length) {
      applyScene('study', true);
      return;
    }
    raw.items.forEach(function (r) {
      if (r.custom) {
        /* 自定义上传元素 */
        var it = {
          uid: 'it' + (seq++), k: 'cus_' + r.custom.id,
          x: r.x, y: r.y, rot: r.rot || 0, scale: r.scale || 1,
          w: r.custom.w || 120, h: r.custom.h || 90, custom: r.custom
        };
        customs[r.custom.id] = r.custom;
        items.push(it);
        renderItem(it);
      } else {
        var def = LIB()[r.k];
        if (!def) return;
        var it2 = makeItem(r.k, r.x, r.y);
        if (!it2) return;
        it2.rot = r.rot || 0; it2.scale = r.scale || 1;
        if (r.opacity != null) it2.opacity = r.opacity;
        if (r.dev) it2.dev = r.dev;
        if (r.locked) it2.locked = true;
        if (r.hideText) it2.hideText = true;
        items.push(it2);
        renderItem(it2);
        if (r.opacity != null) {
          var gg = gItems.querySelector('[data-uid="' + it2.uid + '"]');
          if (gg) gg.setAttribute('opacity', r.opacity);
        }
        if (r.locked) {
          var gl2 = gItems.querySelector('[data-uid="' + it2.uid + '"]');
          if (gl2) gl2.classList.add('locked');
        }
      }
    });
    items.forEach(updateItemLabel);
    rebuildLinked();
    /* 第三十八轮：恢复上次场景时同步「情景」下拉框与右侧情景名 */
    if (raw.sceneKey) syncSceneSelect(raw.sceneKey);
  }

  /* 第三十八轮：当前生效的情景 key（供保存 / 恢复时同步下拉框） */
  var curSceneKey = '';

  function applyScene(key, silent) {
    var sc = ZKB.SceneLib && ZKB.SceneLib.SCENES[key];
    if (!sc) return;
    /* 第三十八轮：记录当前情景 key */
    curSceneKey = key;
    clearItems();
    sc.items.forEach(function (r) {
      var ni = addItem(r.k, r.x, r.y, true);
      if (!ni) return;
      if (r.rot) setItemRot(ni.uid, r.rot);
      if (r.scale) setItemScale(ni.uid, r.scale);
      if (r.layer) setLayer(ni.uid, r.layer);
    });
    items.forEach(updateItemLabel);
    /* 情景建议的联动设备：自动加入虚拟仿真（保证编程区积木可用） */
    if (sc.devices && sc.devices.length && ZKB.SimBoard) {
      var cur = ZKB.SimBoard.getDevices() || [];
      var need = sc.devices.filter(function (d) { return cur.indexOf(d) < 0; });
      if (need.length) {
        ZKB.SimBoard.setDevices(cur.concat(need));
        if (ZKB.onDevicesChanged) ZKB.onDevicesChanged(ZKB.SimBoard.getDevices());
      }
    }
    /* ⚠ 第三十二轮修：上面只在「有新增设备」时才触发联动，
       但 applyScene 开头已经 clearItems() 把舞台全清了——
       于是「设备本来就都在、只是切了个场景」的情况下，
       联动元素（dhtSensor / ultraSensor …）不会被重建，
       表现为切场景后这些设备在舞台上凭空消失。
       场景里的 items 本身不带 dev 标记，rebuildLinked 扫不到它们。 */
    syncDevicesToStage();
    /* 第三十八轮：同步舞台工具栏的「情景」下拉框，
       让下拉框显示的始终是当前生效的情景（程序化切换时也一致）。 */
    syncSceneSelect(key);
    if (!silent) toastPill('已布置：' + sc.name);
    saveScene();
  }

  /* 第三十八轮：把舞台工具栏的「情景」下拉框同步到指定情景。
     供 applyScene / 载入示例等程序化切换路径调用。 */
  function syncSceneSelect(key) {
    var sel = document.getElementById('stg-scene');
    if (!sel || !key) return;
    if (sel.value !== key) {
      /* 只有选项存在时才赋值（自定义情景不在下拉里） */
      var has = false;
      for (var i = 0; i < sel.options.length; i++) {
        if (sel.options[i].value === key) { has = true; break; }
      }
      if (has) sel.value = key;
    }
    /* 情景名同步显示在下拉框右侧的提示里 */
    var sc = ZKB.SceneLib && ZKB.SceneLib.SCENES[key];
    var tip = document.getElementById('stg-scene-name');
    if (tip && sc) tip.textContent = sc.name;
  }

  /* 应用用户自建情景 */
  function applyCustomScene(sc) {
    if (!sc) return;
    clearItems();
    (sc.items || []).forEach(function (r) {
      if (r.custom) { addCustom(r.custom, r.x, r.y); return; }
      addItem(r.k, r.x, r.y, true);
    });
    items.forEach(updateItemLabel);
    if (sc.devices && sc.devices.length && ZKB.SimBoard) {
      var cur = ZKB.SimBoard.getDevices() || [];
      var need = sc.devices.filter(function (d) { return cur.indexOf(d) < 0; });
      if (need.length) {
        ZKB.SimBoard.setDevices(cur.concat(need));
        if (ZKB.onDevicesChanged) ZKB.onDevicesChanged(ZKB.SimBoard.getDevices());
      }
    }
    toastPill('已布置：' + sc.name);
  }

  /* ============================================================
   * 导出接口
   * ============================================================ */
  /* ============================================================
   * 舞台元素程序化控制（zk_stage_* 积木的落地实现）
   *   仅作用于非背景元素：位置 / 层级 / 大小
   * ============================================================ */
  function findItem(uid) {
    return items.filter(function (i) { return i.uid === uid; })[0] || null;
  }
  function nameOf(uid) {
    var it = findItem(uid);
    if (!it) return '';
    if (it.k === '__bitmap') return '屏幕图片';
    var def = LIB()[it.k];
    return (def && def.name) || it.k;
  }
  /* DOM 顺序 = items 数组顺序（SVG 后画者在上） */
  function syncDomOrder() {
    if (!gItems) return;
    items.forEach(function (it) {
      var g = gItems.querySelector('[data-uid="' + it.uid + '"]');
      if (g) gItems.appendChild(g);
    });
  }
  function setLayer(uid, op) {
    var i = -1;
    items.forEach(function (it, k) { if (it.uid === uid) i = k; });
    if (i < 0) return false;
    var it = items[i];
    if (op === 'up') {
      if (i >= items.length - 1) return true;
      items.splice(i, 1); items.splice(i + 1, 0, it);
    } else if (op === 'down') {
      if (i <= 0) return true;
      items.splice(i, 1); items.splice(i - 1, 0, it);
    } else if (op === 'front') {
      items.splice(i, 1); items.push(it);
    } else if (op === 'back') {
      items.splice(i, 1); items.unshift(it);
    } else {
      return false;
    }
    syncDomOrder();
    saveScene();
    return true;
  }
  /* 第三十二轮：移到「第 N 层」。层号从 1 开始，1 是最底层。
     n 大于总层数时钳到顶层，小于 1 时钳到底层（不报错，贴近课堂使用习惯）。 */
  function setLayerIndex(uid, n) {
    var i = -1;
    items.forEach(function (it, k) { if (it.uid === uid) i = k; });
    if (i < 0) return false;
    var it = items[i];
    items.splice(i, 1);
    var target = Math.round(Number(n) || 1) - 1;
    if (target < 0) target = 0;
    if (target > items.length) target = items.length;
    items.splice(target, 0, it);
    syncDomOrder();
    saveScene();
    return true;
  }
  /* 读层级：1 = 最底层 */
  function getLayerIndex(uid) {
    for (var i = 0; i < items.length; i++) {
      if (items[i].uid === uid) return i + 1;
    }
    return 0;
  }
  function getLayerCount() { return items.length; }

  function setItemScale(uid, pct) {
    var it = findItem(uid);
    if (!it) return false;
    pct = Math.max(30, Math.min(300, Math.round(Number(pct) || 100)));
    it.scale = pct / 100;
    var g = gItems && gItems.querySelector('[data-uid="' + uid + '"]');
    if (g) applyTransform(g.querySelector('g'), it);
    updateItemLabel(it);
    saveScene();
    return true;
  }

  /* 元素方向（第十九轮）：上=0° 右=90° 下=180° 左=270°（默认面向右侧 90°）
     带运动学的元素（模拟小车）同时同步航向角_ sdeg */
  function setItemRot(uid, deg) {
    var it = findItem(uid);
    if (!it) return false;
    var d = Number(deg);
    if (isNaN(d)) d = 90;
    d = ((Math.round(d) % 360) + 360) % 360;
    it.rot = d;
    if (it._sdeg !== undefined) it._sdeg = d;      /* 小车物理航向同步 */
    var g = gItems && gItems.querySelector('[data-uid="' + uid + '"]');
    if (g) applyTransform(g.querySelector('g'), it);
    updateItemLabel(it);
    if (selUid === uid) updateSelInfo();
    saveScene();
    return true;
  }

  /* ============================================================
   * 第三十轮：运动 / 外观模块的舞台能力
   *
   * 设计原则对齐 Scratch：
   *   · 方向 0° = 正上，90° = 正右，180° = 正下，270° = 正左（与本项目一致）
   *   · 移动按「方向 + 步数」换算：dx = sin(deg)·n，dy = −cos(deg)·n
   *   · 碰到边缘反弹：找到最近的边，把方向镜像过去并夹回舞台内
   *   · 坐标以舞台中心为原点（Scratch 语义），与 setItemPos 的左上角坐标换算
   * ============================================================ */

  function itemByUid(uid) {
    return findItem(uid);
  }

  /* 舞台中心原点坐标（Scratch 语义）←→ 左上角坐标（本项目内部用） */
  function toCenterX(uid) { var it = itemByUid(uid); return it ? it.x - VW / 2 : 0; }
  function toCenterY(uid) { var it = itemByUid(uid); return it ? it.y - VH / 2 : 0; }

  function moveSteps(uid, steps) {
    var it = itemByUid(uid);
    if (!it) return false;
    var n = Number(steps) || 0;
    var rad = (it.rot || 0) * Math.PI / 180;
    /* 0°朝上 → dy 为负；90°朝右 → dx 为正 */
    var dx = Math.sin(rad) * n;
    var dy = -Math.cos(rad) * n;
    return moveBy(uid, dx, dy);
  }
  function moveBy(uid, dx, dy) {
    var it = itemByUid(uid);
    if (!it) return false;
    return !!setItemPos(uid, it.x + (Number(dx) || 0), it.y + (Number(dy) || 0));
  }
  function gotoXY(uid, cx, cy) {
    var it = itemByUid(uid);
    if (!it) return false;
    /* 外部用中心原点坐标，这里换算成左上角坐标 */
    return !!setItemPos(uid, (Number(cx) || 0) + VW / 2, (Number(cy) || 0) + VH / 2);
  }
  function turnBy(uid, deg) {
    var it = itemByUid(uid);
    if (!it) return false;
    return setItemRot(uid, (it.rot || 0) + (Number(deg) || 0));
  }
  function changeXY(uid, axis, delta) {
    var it = itemByUid(uid);
    if (!it) return false;
    var d = Number(delta) || 0;
    return axis === 'x' ? moveBy(uid, d, 0) : moveBy(uid, 0, d);
  }
  function setXYAbs(uid, axis, val) {
    var it = itemByUid(uid);
    if (!it) return false;
    var v = Number(val) || 0;
    return axis === 'x' ? moveBy(uid, v - toCenterX(uid), 0)
      : moveBy(uid, 0, v - toCenterY(uid));
  }
  function getXY(uid, axis) {
    var it = itemByUid(uid);
    if (!it) return 0;
    return Math.round(axis === 'x' ? toCenterX(uid) : toCenterY(uid));
  }
  function getDir(uid) {
    var it = itemByUid(uid);
    return it ? Math.round(it.rot || 0) : 90;
  }
  function pointTowards(uid, targetUid) {
    var it = itemByUid(uid), tg = itemByUid(targetUid);
    if (!it || !tg) return false;
    var dx = tg.x - it.x, dy = tg.y - it.y;
    if (dx === 0 && dy === 0) return false;
    return setItemRot(uid, Math.round(Math.atan2(dx, -dy) * 180 / Math.PI));
  }

  /* 碰到边缘就反弹（对齐 scratch3_motion.ifOnEdgeBounce 的做法） */
  function ifOnEdgeBounce(uid) {
    var it = itemByUid(uid);
    if (!it) return false;
    var def = LIB()[it.k] || { w: 40, h: 40 };
    var sc = it.scale || 1;
    var hw = def.w * sc / 2, hh = def.h * sc / 2;
    /* 到四条边的距离（负数 = 已经越界） */
    var dL = it.x - hw, dR = VW - it.x - hw;
    var dT = it.y - hh, dB = VH - it.y - hh;
    var min = Math.min(dL, dR, dT, dB);
    if (min > 0) return false;               /* 没贴边，什么都不做 */
    var rad = (it.rot || 0) * Math.PI / 180;
    var dx = Math.sin(rad), dy = -Math.cos(rad);
    if (min === dL) dx = Math.max(0.3, Math.abs(dx));
    else if (min === dR) dx = -Math.max(0.3, Math.abs(dx));
    else if (min === dT) dy = Math.max(0.3, Math.abs(dy));
    else dy = -Math.max(0.3, Math.abs(dy));
    setItemRot(uid, Math.round(Math.atan2(dx, -dy) * 180 / Math.PI));
    /* 夹回舞台内 */
    setItemPos(uid, Math.max(hw, Math.min(VW - hw, it.x)),
      Math.max(hh, Math.min(VH - hh, it.y)));
    return true;
  }

  /* 滑行：在 duration 毫秒内线性移动到目标坐标（由仿真引擎驱动） */
  function glideXY(uid, cx, cy, duration, onDone) {
    var it = itemByUid(uid);
    if (!it) return false;
    var sx = it.x, sy = it.y;
    var tx = (Number(cx) || 0) + VW / 2, ty = (Number(cy) || 0) + VH / 2;
    var ms = Math.max(1, Number(duration) || 300);
    var t0 = Date.now();
    if (typeof onDone !== 'function') {
      /* 无回调（同步调用）时直接落位 */
      setItemPos(uid, tx, ty);
      return true;
    }
    (function step() {
      var t = Math.min(1, (Date.now() - t0) / ms);
      setItemPos(uid, sx + (tx - sx) * t, sy + (ty - sy) * t);
      if (t < 1) requestAnimationFrame(step);
      else onDone();
    })();
    return true;
  }

  /* ---------- 外观 ---------- */
  function setVisible(uid, on) {
    var it = itemByUid(uid);
    if (!it) return false;
    it.visible = !!on;
    var g = gItems && gItems.querySelector('[data-uid="' + uid + '"]');
    if (g) g.style.display = on ? '' : 'none';
    saveScene();
    return true;
  }
  function isVisible(uid) {
    var it = itemByUid(uid);
    return it ? it.visible !== false : false;
  }
  function setOpacity(uid, pct) {
    var it = itemByUid(uid);
    if (!it) return false;
    it.opacity = Math.max(0, Math.min(100, Number(pct) || 0)) / 100;
    applyLook(uid);
    saveScene();
    return true;
  }
  function setGhost(uid, pct) {
    var it = itemByUid(uid);
    if (!it) return false;
    it.ghost = Math.max(0, Math.min(100, Number(pct) || 0));
    applyLook(uid);
    saveScene();
    return true;
  }
  /* 颜色特效：用一个 CSS filter 近似（色相 / 饱和度 / 亮度） */
  function setColorEffect(uid, kind, val) {
    var it = itemByUid(uid);
    if (!it) return false;
    it.colorFx = it.colorFx || {};
    it.colorFx[kind] = Number(val) || 0;
    applyLook(uid);
    saveScene();
    return true;
  }
  function clearEffects(uid) {
    var it = itemByUid(uid);
    if (!it) return false;
    it.opacity = 1; it.ghost = 0; it.colorFx = null;
    applyLook(uid);
    saveScene();
    return true;
  }
  /* 合并透明度 / 虚像 / 颜色特效到 DOM */
  function applyLook(uid) {
    var it = itemByUid(uid);
    if (!it) return;
    var g = gItems && gItems.querySelector('[data-uid="' + uid + '"] .stage-item-body');
    if (!g) return;
    var o = (it.opacity == null ? 1 : it.opacity) * (1 - (it.ghost || 0) / 100);
    var css = [];
    var fx = it.colorFx;
    if (fx) {
      if (fx.hue) css.push('hue-rotate(' + fx.hue + 'deg)');
      if (fx.sat) css.push('saturate(' + (100 + fx.sat) + '%)');
      if (fx.bright) css.push('brightness(' + Math.max(0, (100 + fx.bright) / 100) + ')');
    }
    g.setAttribute('opacity', o.toFixed(3));
    g.style.filter = css.length ? css.join(' ') : '';
  }
  /* 外观相关读数
       ⚠ 函数名必须与本文件已有的 getSize()（返回舞台尺寸）区分开。
       JS 的函数声明会提升，同名后者覆盖前者，
       一旦重名，getSize() 就会返回元素大小百分比而不是舞台宽高，
       影响到所有依赖舞台尺寸的地方（边缘反弹、随机定位、滑行边界）。 */
  function getItemScalePct(uid) {
    var it = itemByUid(uid);
    return it ? Math.round((it.scale || 1) * 100) : 100;
  }

  ZKB.Stage = {
    init: init,
    say: say,
    hide: hideBubble,
    netEvent: function () { },
    /* 元素库 */
    lib: function () { return LIB(); },
    add: addItem,
    remove: removeItem,
    /* 硬件联动：虚拟仿真设备 → 舞台元素 */
    syncDevices: syncDevicesToStage,
    /* 超声波舞台测距（每帧自动执行；导出供测试直接调用） */
    ultraScan: ultraScanAll,
    clear: clearItems,
    applyScene: applyScene,
    /* 第三十八轮：同步舞台工具栏的「情景」下拉框与情景名 */
    syncSceneSelect: syncSceneSelect,
    getItems: function () { return items.slice(); },
    setItemPos: setItemPos,
    /* 选中元素信息（第十九轮）：名称 / 坐标 / 大小 / 缩放 / 旋转 / 层级 */
    selectedInfo: selectedInfo,
    selectItem: selectItem,
    updateSelInfo: updateSelInfo,
    /* 舞台积木（zk_stage_*）：程序化控制元素 */
    moveItem: function (uid, x, y) { return setItemPos(uid, Number(x) || 0, Number(y) || 0); },
    setLayer: setLayer,
    setLayerIndex: setLayerIndex,
    getLayerIndex: getLayerIndex,
    getLayerCount: getLayerCount,
    setItemScale: setItemScale,
    setItemRot: setItemRot,
    /* ---------- 第三十轮：运动 / 外观 ---------- */
    moveSteps: moveSteps,
    moveBy: moveBy,
    gotoXY: gotoXY,
    turnBy: turnBy,
    changeXY: changeXY,
    setXYAbs: setXYAbs,
    getXY: getXY,
    getDir: getDir,
    pointTowards: pointTowards,
    ifOnEdgeBounce: ifOnEdgeBounce,
    glideXY: glideXY,
    setVisible: setVisible,
    isVisible: isVisible,
    setOpacity: setOpacity,
    setGhost: setGhost,
    setColorEffect: setColorEffect,
    clearEffects: clearEffects,
    getItemSize: getItemScalePct,
    /* 元素是否支持某种外观效果（部分元素如背景不可调） */
    editable: function (uid) {
      var it = findItem(uid);
      return !!it && !NON_OBSTACLE[it.k];
    },
    /* 前方元素扫描 / 元素行走（第二十一轮：示例④行人让行） */
    frontScan: frontScan,
    /* 串口输出气泡（第二十四轮）：跟随小助手，显示在其旁边 */
    drawSayBubble: drawSayBubble,
    assistantPos: function () { return { x: assistant.x, y: assistant.y }; },
    moveAssistant: function (x, y) {
      assistant.x = Math.round(Math.max(50, Math.min(VW - 50, x)));
      assistant.y = Math.round(Math.max(70, Math.min(VH - 40, y)));
      renderAssistant();
      if (gSay) drawSayBubble();
    },
    walkTo: walkTo,
    walkState: walkState,
    WALKABLE: WALKABLE,
    nameOf: nameOf,
    /* 送餐机器人（zk_robot_*） */
    robotState: robotState,
    robotCmd: robotCmd,
    /* 巡线小车（zk_trace_*）：状态读写 + 赛道检测 */
    traceState: traceState,
    traceTrack: traceTrack,
    tickTraceCar: tickTraceCarAll,
    /* 可编辑元素下拉（排除背景/地面元素，供 zk_stage_* 积木使用） */
    getEditable: function () {
      return items.filter(function (it) {
        return !NON_OBSTACLE[it.k];
      }).map(function (it) {
        return { uid: it.uid, name: nameOf(it.uid), k: it.k };
      });
    },
    /* 舞台尺寸（逻辑坐标系） */
    getSize: getSize,
    setSize: setSize,
    /* 全屏显示 */
    toggleFullscreen: toggleFullscreen,
    isFullscreen: isFullscreen,
    /* 文字显隐 / 元素锁定 */
    textVisible: textVisible,
    toggleText: toggleText,
    isLocked: isLocked,
    toggleLock: toggleLock,
    opts: function () { return { showText: stageOpts.showText, locked: stageOpts.locked }; },
    /* 右键菜单 */
    showCtxMenu: showCtxMenu,
    /* 标记为硬件联动元素（锁定时仍可移动） */
    markLinked: markLinked,
    /* 刷新小助手屏幕（与虚拟仿真 OLED 同步） */
    refreshAssistant: renderAssistant,
    /* 自定义（上传）元素 */
    addCustom: addCustom,
    /* 应用用户自建情景 */
    applyCustomScene: applyCustomScene,
    /* 小助手位置 */
    assistantPos: function () { return { x: assistant.x, y: assistant.y }; },
    setAssistantPos: function (x, y) {
      assistant.x = Math.round(Math.max(50, Math.min(VW - 50, x)));
      assistant.y = Math.round(Math.max(70, Math.min(VH - 40, y)));
      saveAssistantPos();
    },
    /* 立即把当前布局落盘（拖动结束 / 手动保存时调用） */
    save: saveScene,
    setMood: function (m) { if (ZKB.state) ZKB.state.oledMood = m; },
    /* 供图片模块在舞台上放置自定义位图 */
    addBitmap: function (dataUrl, x, y, w, h) {
      var uid = 'bm' + (seq++);
      var g = el('g', { 'data-uid': uid, class: 'stage-item' }, gItems);
      var w2 = w || 160, h2 = h || 120;
      g.innerHTML = '<g transform="translate(' + x + ',' + y + ')">' +
        '<rect x="-4" y="-4" width="' + (w2 + 8) + '" height="' + (h2 + 8) + '" rx="8" fill="rgba(20,30,45,.82)"/>' +
        '<image href="' + dataUrl + '" x="0" y="0" width="' + w2 + '" height="' + h2 +
        '" preserveAspectRatio="xMidYMid meet" style="image-rendering:pixelated"/>' +
        '<text x="' + (w2 / 2) + '" y="' + (h2 + 18) + '" font-size="11" text-anchor="middle" fill="#fff">掌控板屏幕图片</text>' +
        '</g>';
      items.push({ uid: uid, k: '__bitmap', x: x, y: y, w: w2, h: h2, rot: 0, scale: 1 });
      saveScene();
      return uid;
    }
  };

})(window);