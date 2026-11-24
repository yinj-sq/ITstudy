(function () {
  'use strict';

  var viewer = null;
  var component = null;
  var initialCamera = null;
  var representations = new Map();
  var currentStyle = 'ball-and-stick';
  var spinning = false;
  var loadVersion = 0;
  var commands = Promise.resolve();
  var loadingEl = document.getElementById('chem-viewer-loading');
  var errorEl = document.getElementById('chem-viewer-error');
  var COLORS = { dark: 0x0f1724, white: 0xffffff, light: 0xf1f5f9 };
  var TYPES = {
    'ball-and-stick': 'ball-and-stick',
    spacefill: 'spacefill',
    wireframe: 'line',
    cartoon: 'cartoon'
  };

  function post(message) {
    if (window.parent !== window) window.parent.postMessage(message, location.origin);
  }

  function showError(message) {
    errorEl.textContent = message;
    errorEl.style.display = 'block';
    post({ type: 'chem-viewer-error', message: message });
  }

  function state() {
    return {
      style: currentStyle,
      cartoonAvailable: !!(component && component.obj.data.polymerResidueCount > 0),
      elementCount: component ? component.obj.data.elementCount : 0,
      spinning: spinning
    };
  }

  function enqueue(task) {
    commands = commands.then(task).catch(function (err) {
      loadingEl.classList.add('hidden');
      showError(err && err.message ? err.message : String(err));
    });
  }

  function afterDraw() {
    return new Promise(function (resolve, reject) {
      var canvas = viewer.plugin.canvas3d;
      var armed = false;
      var timer = setTimeout(function () {
        subscription.unsubscribe();
        reject(new Error('3D 画面未完成绘制，请重试'));
      }, 10000);
      var subscription = canvas.didDraw.subscribe(function () {
        if (!armed) return;
        armed = false;
        clearTimeout(timer);
        subscription.unsubscribe();
        requestAnimationFrame(resolve);
      });
      armed = true;
      canvas.requestDraw(true);
    });
  }

  function setBackground(value) {
    if (!viewer) return;
    var color = COLORS[value] || COLORS.dark;
    viewer.plugin.canvas3d.setProps({ renderer: { backgroundColor: color } });
    document.body.style.background = '#' + color.toString(16).padStart(6, '0');
  }

  function spin(enabled, report) {
    if (!viewer) return;
    spinning = enabled;
    viewer.plugin.canvas3d.setProps({
      trackball: {
        animate: enabled
          ? { name: 'spin', params: { speed: 0.15, axis: [0, -1, 0] } }
          : { name: 'off', params: {} }
      }
    });
    if (report) post({ type: 'chem-viewer-spin', enabled: enabled });
  }

  async function applyStyle(requestedStyle, report) {
    if (!component) return;
    var style = TYPES[requestedStyle] ? requestedStyle : 'ball-and-stick';
    var notice = '';
    if (style === 'cartoon' && !state().cartoonAvailable) {
      style = 'ball-and-stick';
      notice = '此结构不含聚合物主链，使用球棍模型';
    }
    var representation = representations.get(style);
    if (!representation) {
      representation = await viewer.plugin.builders.structure.representation.addRepresentation(
        component, {
          type: TYPES[style],
          typeParams: { quality: 'medium', ignoreHydrogens: false },
          color: style === 'cartoon' ? 'chain-id' : 'element-symbol'
        });
      representations.set(style, representation);
    }
    // 保留已生成的几何，只切可见性，避免重复删除/生成与根表示叠加。
    representations.forEach(function (repr, name) {
      viewer.plugin.state.data.updateCellState(repr.ref, { isHidden: name !== style });
    });
    currentStyle = style;
    if (report) {
      await afterDraw();
      post(Object.assign({ type: 'chem-viewer-style', notice: notice }, state()));
    }
  }

  async function loadStructure(data, format, title, style, version) {
    if (!viewer || !data || version !== loadVersion) return;
    loadingEl.classList.remove('hidden');
    errorEl.style.display = 'none';
    spin(false, false);
    component = null;
    initialCamera = null;
    representations.clear();
    var plugin = viewer.plugin;
    await plugin.clear();
    var raw = await plugin.builders.data.rawData({ data: data, label: title || '结构' });
    var normalized = String(format || 'sdf').toLowerCase();
    if (normalized === 'cif') normalized = 'mmcif';
    if (normalized === 'mol') normalized = 'sdf';
    var trajectory = await plugin.builders.structure.parseTrajectory(raw, normalized);
    var model = await plugin.builders.structure.createModel(trajectory);
    var structure = await plugin.builders.structure.createStructure(model);
    component = await plugin.builders.structure.tryCreateComponentStatic(structure, 'all');
    if (!component || !component.obj.data.elementCount) throw new Error('结构文件中没有原子');
    if (version !== loadVersion) return;
    await applyStyle(style, false);
    await afterDraw();
    plugin.managers.camera.reset(undefined, 0);
    await afterDraw();
    initialCamera = plugin.canvas3d.camera.getSnapshot();
    loadingEl.classList.add('hidden');
    if (version === loadVersion) {
      post(Object.assign({ type: 'chem-viewer-loaded', title: title }, state()));
    }
  }

  async function resetCamera() {
    if (!viewer || !initialCamera) return;
    spin(false, false);
    viewer.plugin.managers.camera.setSnapshot(initialCamera, 0);
    await afterDraw();
    post(Object.assign({ type: 'chem-viewer-reset' }, state()));
  }

  async function shot() {
    if (!viewer) return;
    var dataUrl = await viewer.plugin.helpers.viewportScreenshot.getImageDataUri();
    post({ type: 'chem-viewer-shot', dataUrl: dataUrl });
  }

  window.addEventListener('message', function (event) {
    if (event.origin !== location.origin || event.source !== window.parent) return;
    var data = event.data || {};
    if (data.type === 'chem-load') {
      var version = ++loadVersion;
      enqueue(function () {
        return loadStructure(data.data, data.format, data.title,
          data.style || currentStyle, version);
      });
    } else if (data.type === 'chem-style') {
      var styleVersion = loadVersion;
      enqueue(function () {
        if (styleVersion === loadVersion) return applyStyle(data.style, true);
      });
    } else if (data.type === 'chem-bg') {
      enqueue(function () { setBackground(data.value); });
    } else if (data.type === 'chem-spin') {
      enqueue(function () { spin(!!data.enabled, true); });
    } else if (data.type === 'chem-reset') {
      enqueue(resetCamera);
    } else if (data.type === 'chem-shot') {
      enqueue(shot);
    }
  });

  async function init() {
    if (!window.molstar || !window.molstar.Viewer) {
      throw new Error('3D 引擎加载失败，请刷新页面重试');
    }
    viewer = await window.molstar.Viewer.create('molstar-container', {
      layoutIsExpanded: false,
      layoutShowControls: false,
      layoutShowLeftPanel: false,
      layoutShowSequence: false,
      layoutShowLog: false,
      viewportShowExpand: false,
      viewportShowSelectionMode: false,
      viewportShowAnimation: false
    });
    viewer.plugin.canvas3d.setProps({ camera: { manualReset: true } });
    setBackground('dark');
    loadingEl.classList.add('hidden');
    post({ type: 'chem-viewer-ready' });
  }

  init().catch(function (err) { showError(err.message || String(err)); });
})();
