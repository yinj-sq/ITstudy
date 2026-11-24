/* 化学仿真工作台：离线 Ketcher 2D 绘制 + 3Dmol.js 实时 3D + 可视化化学/分子库 */
(function () {
  'use strict';

  var root = document.getElementById('chemLab');
  if (!root) return;
  document.documentElement.classList.add('chem-lab-root');

  var uid = root.dataset.uid || 'anon';
  var embed = root.dataset.embed === '1' || window.self !== window.top;
  if (embed) {
    document.body.classList.add('chem-lab-active', 'chem-embedded');
    root.classList.add('chem-embed');
  } else {
    document.body.classList.add('chem-lab-active');
  }

  var els = {
    nav: root.querySelectorAll('.chem-nav-item'),
    panes: root.querySelectorAll('.chem-pane'),
    helpBtn: document.getElementById('chemHelpBtn'),
    help: document.getElementById('chemHelp'),
    fullBtn: document.getElementById('chemFullBtn'),
    current: document.getElementById('chemCurrent'),
    status: document.getElementById('chemSourceStatus'),
    loadStatus: document.getElementById('chemLoadStatus'),
    infoTitle: document.getElementById('chemInfoTitle'),
    infoFormula: document.getElementById('chemInfoFormula'),
    infoSource: document.getElementById('chemInfoSource'),
    infoPoints: document.getElementById('chemInfoPoints'),
    viewer: document.getElementById('chemViewer'),
    viewStatus: document.getElementById('chemViewStatus'),
    viewLoading: document.getElementById('chemViewLoading'),
    viewStyle: document.getElementById('chemViewStyle'),
    viewBg: document.getElementById('chemViewBg'),
    viewSpin: document.getElementById('chemViewSpin'),
    viewReset: document.getElementById('chemViewReset'),
    viewShot: document.getElementById('chemViewShot'),
    viewFull: document.getElementById('chemViewFull'),
    viewUpload: document.getElementById('chemViewUpload'),
    visualGallery: document.getElementById('chemVisualGallery'),
    visualStage: document.getElementById('chemVisualStage'),
    visualFrame: document.getElementById('chemVisualFrame'),
    visualTitle: document.getElementById('chemVisualTitle'),
    visualBack: document.getElementById('chemVisualBack'),
    visualFull: document.getElementById('chemVisualFull'),
    visualCopy: document.getElementById('chemVisualCopy'),
    visualOpen: document.getElementById('chemVisualOpen'),
    ketcherFrame: document.getElementById('chemKetcherFrame'),
    sketchStatus: document.getElementById('chemSketchStatus'),
    sketchSample: document.getElementById('chemSketchSample'),
    sketchClear: document.getElementById('chemSketchClear'),
    sketchDownload: document.getElementById('chemSketchDownload'),
    sketchCopy: document.getElementById('chemSketchCopy'),
    sketchFull: document.getElementById('chemSketchFull'),
    mol3d: document.getElementById('chem3dmol'),
    mol3dWrap: document.querySelector('.chem-studio-right'),
    mol3dEmpty: document.getElementById('chem3dEmpty'),
    mol3dLoading: document.getElementById('chem3dLoading'),
    mol3dStatus: document.getElementById('chem3dStatus'),
    style3d: document.getElementById('chem3dStyle'),
    bg3d: document.getElementById('chem3dBg'),
    spin3d: document.getElementById('chem3dSpin'),
    reset3d: document.getElementById('chem3dReset'),
    shot3d: document.getElementById('chem3dShot'),
    full3d: document.getElementById('chem3dFull')
  };

  /* ── 通用状态 ── */
  var viewerReady = false;
  var viewerQueue = [];
  var spinOn = false;
  var shareUrl = '/chem-lab';
  var currentVisualSlug = '';
  var librarySelectionVersion = 0;

  function setViewStatus(text, state) {
    if (!els.viewStatus) return;
    els.viewStatus.textContent = text;
    els.viewStatus.dataset.state = state || 'ready';
  }

  function syncViewState(data) {
    if (data.style) {
      els.viewStyle.value = data.style;
      els.viewStatus.dataset.style = data.style;
    }
    if (typeof data.cartoonAvailable === 'boolean') {
      var option = els.viewStyle.querySelector('option[value="cartoon"]');
      option.disabled = !data.cartoonAvailable;
      option.title = data.cartoonAvailable ? '' : '此结构不含蛋白质或核酸主链';
    }
    if (typeof data.spinning === 'boolean') {
      spinOn = data.spinning;
      els.viewSpin.classList.toggle('active', spinOn);
      els.viewSpin.setAttribute('aria-pressed', spinOn ? 'true' : 'false');
    }
    if (data.title) els.viewStatus.dataset.title = data.title;
    if (typeof data.elementCount === 'number') {
      els.viewStatus.dataset.atoms = String(data.elementCount);
    }
  }

  function setStatus(text, cls) {
    if (!els.status) return;
    els.status.innerHTML = text;
    els.status.className = cls || '';
  }

  function setLoadStatus(text) {
    if (els.loadStatus) els.loadStatus.textContent = text || '';
  }

  function setCurrent(title, formula, source, points) {
    if (els.current) {
      els.current.innerHTML = '<i class="fas fa-circle-info"></i> ';
      els.current.appendChild(document.createTextNode(title || '未选择结构'));
    }
    if (els.infoTitle) els.infoTitle.textContent = title || '—';
    if (els.infoFormula) els.infoFormula.textContent = formula || '—';
    if (els.infoSource) els.infoSource.textContent = source || '—';
    if (els.infoPoints) {
      els.infoPoints.textContent = points ||
        '从分子库或可视化化学中选择一个结构，这里会显示观察要点。';
    }
  }

  function copyText(text, okMessage) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        setLoadStatus(okMessage + text);
      }).catch(function () { window.prompt(okMessage, text); });
    } else {
      window.prompt(okMessage, text);
    }
  }

  function downloadText(text, filename) {
    var blob = new Blob([text], { type: 'chemical/x-mdl-molfile' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  function switchTab(name) {
    els.nav.forEach(function (btn) {
      btn.classList.toggle('active', btn.dataset.tab === name);
    });
    els.panes.forEach(function (pane) {
      pane.classList.toggle('active', pane.dataset.pane === name);
    });
    if (name === 'library') ensureViewer();
    if (name === 'sketch') {
      ensure3dmol();
      resize3d();
    }
  }

  els.nav.forEach(function (btn) {
    btn.addEventListener('click', function () { switchTab(btn.dataset.tab); });
  });

  if (els.helpBtn) {
    els.helpBtn.addEventListener('click', function () {
      els.help.hidden = !els.help.hidden;
    });
  }
  if (els.fullBtn) {
    els.fullBtn.addEventListener('click', function () {
      if (document.fullscreenElement) document.exitFullscreen();
      else if (root.requestFullscreen) root.requestFullscreen();
    });
  }

  /* ── 离线 Ketcher 绘制 ── */
  var ketcherReady = false;
  var pendingKetcherLoad = null;
  var lastMolfile = '';
  var lastSmiles = '';
  var lastInfo = null;
  var sketchTimer = null;

  function setSketchStatus(text) {
    if (els.sketchStatus) els.sketchStatus.innerHTML = text || '';
  }

  function sendToKetcher(msg) {
    if (!els.ketcherFrame) return;
    if (!ketcherReady) {
      pendingKetcherLoad = msg;
      return;
    }
    els.ketcherFrame.contentWindow.postMessage(msg, location.origin);
  }

  function loadSketch(data) {
    sendToKetcher({ type: 'chem-sketch-load', data: data });
  }

  if (els.ketcherFrame) {
    els.ketcherFrame.addEventListener('load', function () {
      setTimeout(function () {
        if (els.ketcherFrame.contentWindow) {
          els.ketcherFrame.contentWindow.postMessage(
            { type: 'chem-sketch-ping' }, location.origin);
        }
      }, 400);
    });
    sketchTimer = setTimeout(function () {
      if (!ketcherReady) {
        setSketchStatus('<i class="fas fa-triangle-exclamation"></i> 绘制引擎加载较慢，请稍候或刷新页面');
      }
    }, 25000);
  }

  if (els.sketchSample) {
    els.sketchSample.addEventListener('change', function () {
      var value = els.sketchSample.value;
      if (!value) return;
      var label = els.sketchSample.options[els.sketchSample.selectedIndex].text;
      els.sketchSample.value = '';
      shareUrl = '/chem-lab?smiles=' + encodeURIComponent(value);
      loadSketch(value);
      setSketchStatus('<i class="fas fa-spinner fa-spin"></i> 已载入示例：' + label);
      setLoadStatus('已载入示例：' + label);
    });
  }

  if (els.sketchClear) {
    els.sketchClear.addEventListener('click', function () {
      sendToKetcher({ type: 'chem-sketch-clear' });
      lastMolfile = '';
      lastSmiles = '';
      lastInfo = null;
      shareUrl = '/chem-lab';
      clear3d('画布为空');
      setSketchInfo(null);
      setSketchStatus('画布为空');
    });
  }

  if (els.sketchDownload) {
    els.sketchDownload.addEventListener('click', function () {
      if (!lastMolfile || !lastMolfile.trim()) {
        setLoadStatus('画布为空，暂无可保存的结构');
        return;
      }
      downloadText(lastMolfile, 'itstudy-structure.mol');
      setLoadStatus('结构已保存为 mol 文件');
    });
  }

  if (els.sketchCopy) {
    els.sketchCopy.addEventListener('click', function () {
      var path = lastSmiles
        ? '/chem-lab?smiles=' + encodeURIComponent(lastSmiles)
        : '/chem-lab';
      copyText(location.origin + path, '教学链接已复制：');
    });
  }

  if (els.sketchFull) {
    els.sketchFull.addEventListener('click', function () {
      var board = document.querySelector('.chem-studio-left');
      if (document.fullscreenElement) document.exitFullscreen();
      else if (board && board.requestFullscreen) board.requestFullscreen();
    });
  }

  function setSketchInfo(info) {
    if (!info) {
      if (els.current) {
        els.current.innerHTML = '<i class="fas fa-pen-ruler"></i> 绘制结构';
      }
      if (els.infoTitle) els.infoTitle.textContent = '绘制结构';
      if (els.infoFormula) els.infoFormula.textContent = '—';
      if (els.infoSource) els.infoSource.textContent = '本机离线绘制';
      if (els.infoPoints) {
        els.infoPoints.textContent =
          '在左侧画布中绘制分子，右侧会自动生成 3D 构象；也可从示例下拉框载入常见分子。';
      }
      return;
    }
    if (els.current) {
      els.current.innerHTML = '<i class="fas fa-pen-ruler"></i> 绘制结构' +
        (info.formula ? ' · ' + info.formula : '');
    }
    if (els.infoTitle) els.infoTitle.textContent = '绘制结构';
    if (els.infoFormula) els.infoFormula.textContent = info.formula || '—';
    if (els.infoSource) els.infoSource.textContent = '本机离线绘制';
    if (els.infoPoints) {
      els.infoPoints.textContent = '相对分子质量 ' + info.weight +
        '；重原子 ' + info.atoms + ' 个。右侧为自动生成的 3D 构象，' +
        '可旋转、缩放并切换球棍/棍状/空间填充/线框显示。';
    }
  }

  /* ── 3Dmol.js 实时 3D ── */
  var mol3dViewer = null;
  var initial3dView = null;
  var spin3dOn = false;
  var EMPTY_3D_TEXT = '在左侧绘制结构，3D 构象会自动生成';

  function set3dStatus(text) {
    if (els.mol3dStatus) els.mol3dStatus.textContent = text || '';
  }

  function set3dLoading(show) {
    if (els.mol3dLoading) els.mol3dLoading.hidden = !show;
    if (show && els.mol3dEmpty) els.mol3dEmpty.hidden = true;
  }

  function show3dEmpty(message) {
    if (!els.mol3dEmpty) return;
    els.mol3dEmpty.innerHTML = '<i class="fas fa-cubes-stacked"></i><p></p>';
    els.mol3dEmpty.querySelector('p').textContent = message || EMPTY_3D_TEXT;
    els.mol3dEmpty.hidden = false;
  }

  function clear3d(message) {
    initial3dView = null;
    spin3dOn = false;
    els.spin3d.classList.remove('active');
    els.spin3d.setAttribute('aria-pressed', 'false');
    if (mol3dViewer) {
      try {
        mol3dViewer.spin(false);
        mol3dViewer.removeAllModels();
        mol3dViewer.removeAllShapes();
        mol3dViewer.render();
      } catch (e) { /* 引擎尚未就绪 */ }
    }
    set3dLoading(false);
    show3dEmpty(message);
    set3dStatus(message || '等待结构');
  }

  function ensure3dmol() {
    if (mol3dViewer || !els.mol3d || !window.$3Dmol) return mol3dViewer;
    try {
      mol3dViewer = window.$3Dmol.createViewer(els.mol3d, {
        backgroundColor: '#0f1724',
        backgroundAlpha: 1,
        antialias: true
      });
      if (window.ResizeObserver) {
        var ro = new ResizeObserver(function () { resize3d(); });
        ro.observe(els.mol3d);
      }
    } catch (e) {
      set3dStatus('3D 引擎初始化失败：' + e.message);
      show3dEmpty('浏览器无法初始化 WebGL，请更换现代浏览器');
    }
    return mol3dViewer;
  }

  function resize3d() {
    if (!mol3dViewer) return;
    try {
      mol3dViewer.resize();
      mol3dViewer.render();
    } catch (e) { /* 容器不可见时忽略 */ }
  }

  function style3dValue() {
    return els.style3d ? els.style3d.value : 'ball-and-stick';
  }

  function apply3dStyle(render) {
    if (!mol3dViewer) return;
    var styles = {
      'ball-and-stick': { stick: { radius: 0.13 }, sphere: { scale: 0.26 } },
      stick: { stick: { radius: 0.17 } },
      sphere: { sphere: { scale: 1.0 } },
      line: { line: { linewidth: 2 } }
    };
    mol3dViewer.setStyle({}, styles[style3dValue()] || styles['ball-and-stick']);
    if (render !== false) mol3dViewer.render();
  }

  function render3d(molfile, info) {
    var viewer = ensure3dmol();
    if (!viewer) {
      set3dLoading(false);
      show3dEmpty('3D 引擎未加载，请刷新页面重试');
      set3dStatus('3D 引擎未加载');
      return;
    }
    try {
      viewer.spin(false);
      viewer.removeAllModels();
      viewer.addModel(molfile, 'mol');
      viewer.setView([0, 0, 0, 0, 0, 0, 0, 1]);
      apply3dStyle(false);
      viewer.zoomTo();
      viewer.render();
      initial3dView = viewer.getView().slice();
      if (spin3dOn) viewer.spin('y', 2);
      set3dLoading(false);
      if (els.mol3dEmpty) els.mol3dEmpty.hidden = true;
      set3dStatus('3D 已更新' + (info && info.formula ? ' · ' + info.formula : ''));
    } catch (e) {
      set3dLoading(false);
      show3dEmpty('3D 渲染失败：' + e.message);
      set3dStatus('3D 渲染失败');
    }
  }

  if (els.style3d) {
    els.style3d.addEventListener('change', function () {
      var label = els.style3d.options[els.style3d.selectedIndex].text;
      set3dStatus('显示模式：' + label);
      // 先让下拉框完成关闭与状态文字绘制，再重建 3D 表示，避免低配机
      // 上「点了没反应」的观感。
      requestAnimationFrame(function () { apply3dStyle(); });
    });
  }
  if (els.bg3d) {
    els.bg3d.addEventListener('change', function () {
      if (!ensure3dmol()) return;
      var colors = { dark: '#0f1724', white: '#ffffff', light: '#eef2f7' };
      mol3dViewer.setBackgroundColor(colors[els.bg3d.value] || colors.dark, 1);
      mol3dViewer.render();
    });
  }
  if (els.spin3d) {
    els.spin3d.addEventListener('click', function () {
      if (!ensure3dmol()) return;
      spin3dOn = !spin3dOn;
      els.spin3d.classList.toggle('active', spin3dOn);
      els.spin3d.setAttribute('aria-pressed', spin3dOn ? 'true' : 'false');
      mol3dViewer.spin(spin3dOn ? 'y' : false, spin3dOn ? 2 : 0);
      if (spin3dOn) mol3dViewer.render();
      set3dStatus(spin3dOn ? '自动旋转：开' : '自动旋转：关');
    });
  }
  if (els.reset3d) {
    els.reset3d.addEventListener('click', function () {
      if (!mol3dViewer || !initial3dView) return;
      mol3dViewer.spin(false);
      spin3dOn = false;
      els.spin3d.classList.remove('active');
      els.spin3d.setAttribute('aria-pressed', 'false');
      mol3dViewer.setView(initial3dView.slice());
      set3dStatus('视角已重置');
    });
  }
  if (els.shot3d) {
    els.shot3d.addEventListener('click', function () {
      if (!mol3dViewer) return;
      try {
        downloadDataUrl(mol3dViewer.pngURI(), 'chem-lab-3d.png');
      } catch (e) {
        setLoadStatus('3D 截图失败：' + e.message);
      }
    });
  }
  if (els.full3d) {
    els.full3d.addEventListener('click', function () {
      if (document.fullscreenElement) document.exitFullscreen();
      else if (els.mol3dWrap && els.mol3dWrap.requestFullscreen) {
        els.mol3dWrap.requestFullscreen();
      }
    });
  }
  document.addEventListener('fullscreenchange', function () {
    setTimeout(resize3d, 120);
  });
  window.addEventListener('resize', resize3d);

  /* ── 本地 Molstar 3D（分子库） ── */
  function ensureViewer() {
    if (els.viewer && !els.viewer.src) els.viewer.src = '/chem-lab/frame';
  }

  function sendViewer(msg) {
    ensureViewer();
    if (!viewerReady) { viewerQueue.push(msg); return; }
    els.viewer.contentWindow.postMessage(msg, location.origin);
  }

  function downloadDataUrl(dataUrl, filename) {
    var a = document.createElement('a');
    a.href = dataUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  function loadViewerStructure(data, format, title, formula, points, source) {
    setCurrent(title, formula, source, points);
    switchTab('library');
    setViewStatus('正在载入结构…', 'working');
    if (els.viewLoading) els.viewLoading.hidden = false;
    sendViewer({
      type: 'chem-load', data: data, format: format || 'sdf',
      title: title || '', style: els.viewStyle.value
    });
  }

  async function loadFromUrl(url, format, title, formula, points, source) {
    var selection = ++librarySelectionVersion;
    setViewStatus('正在读取结构文件…', 'working');
    setLoadStatus('正在读取结构文件…');
    try {
      var resp = await fetch(url, { credentials: 'same-origin' });
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      var text = await resp.text();
      if (selection !== librarySelectionVersion) return;
      loadViewerStructure(text, format, title, formula, points, source);
    } catch (err) {
      if (selection !== librarySelectionVersion) return;
      setViewStatus('读取结构失败：' + err.message, 'error');
      setLoadStatus('读取结构失败：' + err.message);
    }
  }

  window.addEventListener('message', function (event) {
    if (event.origin !== location.origin) return;
    var data = event.data || {};
    if (String(data.type || '').startsWith('chem-viewer-') &&
        event.source !== els.viewer.contentWindow) return;
    if (String(data.type || '').startsWith('chem-sketch-') &&
        event.source !== els.ketcherFrame.contentWindow) return;
    if (data.type === 'chem-viewer-ready') {
      viewerReady = true;
      var queue = viewerQueue.slice();
      viewerQueue = [];
      queue.forEach(function (msg) {
        els.viewer.contentWindow.postMessage(msg, location.origin);
      });
    } else if (data.type === 'chem-viewer-loaded') {
      if (els.viewLoading) els.viewLoading.hidden = true;
      syncViewState(data);
      setViewStatus('已载入 ' + data.elementCount + ' 个原子');
      setLoadStatus('3D 结构已加载');
    } else if (data.type === 'chem-viewer-style') {
      syncViewState(data);
      var label = els.viewStyle.options[els.viewStyle.selectedIndex].text;
      setViewStatus(data.notice || '显示模式：' + label);
    } else if (data.type === 'chem-viewer-spin') {
      syncViewState({ spinning: data.enabled });
      setViewStatus(data.enabled ? '自动旋转：开' : '自动旋转：关');
    } else if (data.type === 'chem-viewer-reset') {
      syncViewState(data);
      setViewStatus('视角已重置，自动旋转已关闭');
    } else if (data.type === 'chem-viewer-error') {
      if (els.viewLoading) els.viewLoading.hidden = true;
      setViewStatus(data.message || '3D 操作失败', 'error');
      setLoadStatus('3D 操作失败：' + (data.message || '未知错误'));
    } else if (data.type === 'chem-viewer-shot') {
      downloadDataUrl(data.dataUrl, 'chem-lab-3d.png');
    } else if (data.type === 'chem-sketch-ready') {
      ketcherReady = true;
      clearTimeout(sketchTimer);
      setSketchStatus('<i class="fas fa-circle-check"></i> 离线绘制引擎已就绪 · 数据不离开本机');
      if (pendingKetcherLoad) {
        var pending = pendingKetcherLoad;
        pendingKetcherLoad = null;
        els.ketcherFrame.contentWindow.postMessage(pending, location.origin);
      }
    } else if (data.type === 'chem-sketch-change') {
      lastMolfile = data.molfile || '';
      lastSmiles = data.smiles || '';
      lastInfo = data.info || null;
      setSketchInfo(lastInfo);
      if (lastInfo && lastInfo.atoms > 0) {
        set3dLoading(true);
        set3dStatus('正在生成 3D…');
      } else {
        clear3d('画布为空');
      }
    } else if (data.type === 'chem-sketch-3d') {
      if (data.molfile) render3d(data.molfile, lastInfo);
    } else if (data.type === 'chem-sketch-3d-empty') {
      clear3d('画布为空');
    } else if (data.type === 'chem-sketch-3d-error') {
      set3dLoading(false);
      var reason = data.message || '未知错误';
      if (/failed to fetch|networkerror|load failed/i.test(reason)) {
        reason = '本地 3D 资源加载失败，请强制刷新页面或重新安装';
      }
      show3dEmpty('无法生成 3D：' + reason);
      set3dStatus('3D 不可用');
    } else if (data.type === 'chem-sketch-error') {
      setSketchStatus('<i class="fas fa-triangle-exclamation"></i> ' +
        (data.message || '绘制引擎提示错误'));
    }
  });

  if (els.viewStyle) {
    els.viewStyle.addEventListener('change', function () {
      setViewStatus('正在切换显示模式…', 'working');
      sendViewer({ type: 'chem-style', style: els.viewStyle.value });
    });
  }
  if (els.viewBg) {
    els.viewBg.addEventListener('change', function () {
      sendViewer({ type: 'chem-bg', value: els.viewBg.value });
    });
  }
  if (els.viewSpin) {
    els.viewSpin.addEventListener('click', function () {
      spinOn = !spinOn;
      els.viewSpin.classList.toggle('active', spinOn);
      sendViewer({ type: 'chem-spin', enabled: spinOn });
    });
  }
  if (els.viewReset) {
    els.viewReset.addEventListener('click', function () {
      sendViewer({ type: 'chem-reset' });
    });
  }
  if (els.viewShot) {
    els.viewShot.addEventListener('click', function () {
      sendViewer({ type: 'chem-shot' });
    });
  }
  if (els.viewFull) {
    els.viewFull.addEventListener('click', function () {
      var wrap = document.querySelector('.chem-library-view');
      if (document.fullscreenElement) document.exitFullscreen();
      else if (wrap && wrap.requestFullscreen) wrap.requestFullscreen();
    });
  }
  if (els.viewUpload) {
    els.viewUpload.addEventListener('change', function () {
      var file = els.viewUpload.files && els.viewUpload.files[0];
      if (!file) return;
      var selection = ++librarySelectionVersion;
      var name = file.name.toLowerCase();
      var format = 'sdf';
      if (name.endsWith('.pdb')) format = 'pdb';
      else if (name.endsWith('.cif') || name.endsWith('.mmcif')) format = 'mmcif';
      else if (name.endsWith('.xyz')) format = 'xyz';
      var reader = new FileReader();
      reader.onload = function () {
        if (selection !== librarySelectionVersion) return;
        loadViewerStructure(String(reader.result), format, file.name,
          '', '本地文件（仅在浏览器内渲染）', '上传');
      };
      reader.onerror = function () { setLoadStatus('文件读取失败'); };
      reader.readAsText(file);
      els.viewUpload.value = '';
    });
  }

  /* ── 分子库 ── */
  root.querySelectorAll('.chem-library-card').forEach(function (card) {
    card.addEventListener('click', function () {
      shareUrl = '/chem-lab?mol=' + encodeURIComponent(card.dataset.id || '');
      loadFromUrl(card.dataset.src, card.dataset.format || 'sdf',
        card.dataset.title, card.dataset.formula,
        card.dataset.points, '内置分子库');
    });
  });

  /* ── 可视化化学 ── */
  root.querySelectorAll('.chem-visual-card').forEach(function (card) {
    card.addEventListener('click', function () {
      var slug = card.dataset.slug;
      var title = card.dataset.title || '可视化化学';
      var file = card.dataset.file || '';
      currentVisualSlug = slug;
      shareUrl = '/chem-lab?visual=' + encodeURIComponent(slug);
      switchTab('visual');
      els.visualTitle.textContent = title;
      els.visualFrame.src = '/chem-lab/visual-chem/' + encodeURI(file) + '?v=6.1.0-3';
      els.visualOpen.href = els.visualFrame.src;
      els.visualGallery.hidden = true;
      els.visualStage.hidden = false;
    });
  });
  if (els.visualBack) {
    els.visualBack.addEventListener('click', function () {
      els.visualStage.hidden = true;
      els.visualGallery.hidden = false;
      els.visualFrame.src = '';
      currentVisualSlug = '';
    });
  }
  if (els.visualFull) {
    els.visualFull.addEventListener('click', function () {
      if (document.fullscreenElement) document.exitFullscreen();
      else if (els.visualStage.requestFullscreen) {
        els.visualStage.requestFullscreen();
      }
    });
  }
  if (els.visualCopy) {
    els.visualCopy.addEventListener('click', function () {
      copyText(location.origin + shareUrl, '教学链接已复制：');
    });
  }

  /* ── 运行状态 ── */
  function updateOnline() {
    if (navigator.onLine) {
      setStatus('<i class="fas fa-shield-halved"></i> 本地运行：绘制、3D、可视化与分子库均可用（本模块不访问外网）', 'chem-ok');
    } else {
      setStatus('<i class="fas fa-plug-circle-xmark"></i> 离线运行：全部功能本地可用', 'chem-ok');
    }
  }
  window.addEventListener('online', updateOnline);
  window.addEventListener('offline', updateOnline);
  updateOnline();

  /* ── 深链与初始化 ── */
  var initial = {};
  try {
    initial = JSON.parse((document.getElementById('chemInitial') || {}).textContent || '{}');
  } catch (e) { initial = {}; }
  switchTab('sketch');
  setSketchInfo(null);
  ensure3dmol();
  if (initial.visual) {
    var vcard = root.querySelector(
      '.chem-visual-card[data-slug="' + initial.visual + '"]');
    if (vcard) vcard.click();
  } else if (initial.mol && initial.mol.file) {
    shareUrl = '/chem-lab?mol=' + encodeURIComponent(initial.mol.id || '');
    loadFromUrl('/static/chem-lab/molecules/' + initial.mol.file,
      initial.mol.format || 'sdf', initial.mol.title,
      initial.mol.formula, initial.mol.points, '内置分子库');
  } else if (initial.smiles) {
    shareUrl = '/chem-lab?smiles=' + encodeURIComponent(initial.smiles);
    loadSketch(initial.smiles);
    setSketchStatus('<i class="fas fa-spinner fa-spin"></i> 正在载入链接中的结构…');
  }
})();
