/* ════════════════════════════════════════════════════════════
 * 课堂编排器（lesson_editor.js）
 *   管理端 edit_resource 页内：章节/分支/条目的增删改、排序、
 *   类型绑定与角色可见性；保存到 Resource.lesson_tree
 *
 *   文件选择统一走“资源根目录”浏览器：
 *   GET /admin/resources/<id>/lesson_files?path=…
 *   支持文件夹导航、按类型筛选、隐藏文件（仅教师）与多选添加。
 * ════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var DATA = window.LESSON_EDITOR_DATA || {};
  var tree = deepCopy(DATA.tree || []);
  var picker = null;

  var KINDS = [
    ['video', '视频/音频'], ['pptx', 'PPTX 课件'], ['doc', '电子文档'],
    ['geogebra', 'GeoGebra 3D'], ['activity', '互动活动'],
    ['survey', '调查问卷'], ['link', '外链/网页']
  ];
  var DOC_CATS = [
    ['activity_sheet', '活动单'], ['guide', '导学案'], ['design', '教学设计'],
    ['handout', '教材分析'], ['exercise', '习题'], ['answer', '参考答案'],
    ['material', '素材'], ['other', '其他']
  ];
  var KIND_LABEL = {
    video: '视频/音频', pptx: 'PPTX', doc: '电子文档',
    geogebra: 'GeoGebra', link: '网页', other: '不支持',
    activity: '互动活动', survey: '调查问卷', dir: '文件夹'
  };
  var PICKER_TABS = [
    ['all', '全部'], ['video', '视频/音频'], ['pptx', 'PPTX'],
    ['doc', '电子文档'], ['geogebra', 'GeoGebra'],
    ['link', '网页'], ['activity', '互动活动'], ['survey', '调查问卷']
  ];

  function deepCopy(o) { return JSON.parse(JSON.stringify(o || null)); }
  function genId() { return 'n' + Math.random().toString(36).slice(2, 10); }
  function el(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html !== undefined) e.innerHTML = html;
    return e;
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function baseName(name) {
    var parts = String(name).split('/');
    return (parts[parts.length - 1] || name).replace(/\.[^.]+$/, '');
  }
  function fmtSize(n) {
    n = Number(n) || 0;
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    return (n / 1024 / 1024).toFixed(1) + ' MB';
  }
  function pathJoin(root, rel) {
    return String(root || '').replace(/\/+$/, '') + '/' + String(rel || '').replace(/^\/+/, '');
  }

  /* ══ 保存 / 重置 ══ */
  function save() {
    if (!tree.length) {
      if (!window.confirm('章节树为空，保存后课堂页将回退默认编排。继续？')) return;
    }
    fetch('/admin/resources/' + DATA.resourceId + '/lesson_tree', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': window.CSRF_TOKEN || ''
      },
      body: JSON.stringify({ tree: tree })
    }).then(function (r) { return r.json(); }).then(function (d) {
      if (d.success) { window.alert(d.msg || '已保存'); window.location.reload(); }
      else window.alert(d.msg || '保存失败');
    }).catch(function () { window.alert('保存失败（网络错误）'); });
  }
  function resetTree() {
    if (!window.confirm('恢复默认编排将清除已保存的课堂章节树，继续？')) return;
    fetch('/admin/resources/' + DATA.resourceId + '/lesson_tree', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': window.CSRF_TOKEN || '' },
      body: JSON.stringify({ reset: true })
    }).then(function (r) { return r.json(); }).then(function (d) {
      if (d.success) { window.alert(d.msg || '已恢复默认'); window.location.reload(); }
      else window.alert(d.msg || '操作失败');
    }).catch(function () { window.alert('操作失败（网络错误）'); });
  }

  /* ══ 遮罩与骨架 ══ */
  function buildOverlay() {
    var ov = el('div', 'le-overlay');
    ov.innerHTML =
      '<div class="le-panel">' +
      '  <div class="le-head">' +
      '    <strong><i class="fas fa-sitemap me-1"></i>课堂编排器</strong>' +
      '    <div class="d-flex gap-2">' +
      '      <button class="btn btn-sm btn-outline-secondary" data-le="addSec"><i class="fas fa-folder-plus me-1"></i>添加章节</button>' +
      '      <button class="btn btn-sm btn-outline-secondary" data-le="addBranch"><i class="fas fa-code-branch me-1"></i>为选中章节添加分支</button>' +
      '      <button class="btn btn-sm btn-success" data-le="save"><i class="fas fa-save me-1"></i>保存</button>' +
      '      <button class="btn btn-sm btn-secondary" data-le="close">关闭</button>' +
      '    </div>' +
      '  </div>' +
      '  <div class="le-tip">点击章节标题可选中（添加分支的目标）；在章节内可从「资源根目录」选择 PPTX、视频/音频、电子文档、网页，或添加互动活动。</div>' +
      '  <div class="le-body" id="leBody"></div>' +
      '</div>';
    document.body.appendChild(ov);
    ov.querySelector('[data-le="addSec"]').addEventListener('click', function () {
      tree.push({ id: genId(), title: '新章节', type: 'section', children: [], items: [] });
      render();
    });
    ov.querySelector('[data-le="addBranch"]').addEventListener('click', function () {
      var target = ov.querySelector('.le-node.selected');
      var sec = target ? findSec(tree, target.dataset.id) : null;
      if (!sec) { window.alert('请先点击选中一个章节'); return; }
      sec.children.push({ id: genId(), title: '新分支', type: 'section', children: [], items: [] });
      render();
    });
    ov.querySelector('[data-le="save"]').addEventListener('click', save);
    ov.querySelector('[data-le="close"]').addEventListener('click', close);
    ov.addEventListener('click', function (e) { if (e.target === ov) close(); });
    return ov;
  }
  function findSec(nodes, id) {
    for (var i = 0; i < nodes.length; i++) {
      if (nodes[i].id === id) return nodes[i];
      var f = findSec(nodes[i].children || [], id);
      if (f) return f;
    }
    return null;
  }

  /* ══ 渲染编排树 ══ */
  function render() {
    var body = document.getElementById('leBody');
    if (!body) return;
    body.innerHTML = '';
    if (!tree.length) {
      body.appendChild(el('div', 'le-empty', '暂无章节，点击上方「添加章节」开始编排。保存为空则课堂页回退默认编排。'));
    }
    tree.forEach(function (sec, i) {
      body.appendChild(renderSection(sec, tree, i, 0));
    });
  }

  function moveBtn(label, fn, disabled) {
    var b = el('button', 'btn btn-sm btn-outline-secondary le-btn', label);
    b.type = 'button';
    b.disabled = !!disabled;
    b.addEventListener('click', fn);
    return b;
  }
  function delBtn(fn) {
    var b = el('button', 'btn btn-sm btn-outline-danger le-btn', '<i class="fas fa-trash"></i>');
    b.type = 'button';
    b.addEventListener('click', fn);
    return b;
  }

  function renderSection(sec, siblings, index, depth) {
    var node = el('div', 'le-node');
    node.dataset.id = sec.id;
    var head = el('div', 'le-sec-head');
    var title = el('input', 'form-control form-control-sm le-sec-title');
    title.value = sec.title;
    title.placeholder = '章节标题';
    title.addEventListener('input', function () { sec.title = title.value; });
    head.addEventListener('click', function (e) {
      if (e.target === title) return;
      document.querySelectorAll('.le-node.selected').forEach(function (n) { n.classList.remove('selected'); });
      node.classList.add('selected');
    });
    head.appendChild(el('span', 'le-sec-icon', '<i class="fas fa-folder' + (depth ? '-open' : '') + '"></i>'));
    head.appendChild(title);
    head.appendChild(moveBtn('↑', function () {
      if (index <= 0) return;
      siblings.splice(index, 1);
      siblings.splice(index - 1, 0, sec);
      render();
    }, index === 0));
    head.appendChild(moveBtn('↓', function () {
      if (index >= siblings.length - 1) return;
      siblings.splice(index, 1);
      siblings.splice(index + 1, 0, sec);
      render();
    }, index === siblings.length - 1));
    head.appendChild(delBtn(function () {
      if (!window.confirm('删除章节「' + sec.title + '」及其全部内容？')) return;
      siblings.splice(index, 1);
      render();
    }));
    node.appendChild(head);

    var childBox = el('div', 'le-children');
    (sec.items || []).forEach(function (it, j) {
      childBox.appendChild(renderItem(it, sec.items, j));
    });
    var addRow = el('div', 'le-addrow');
    var addFiles = el('button', 'btn btn-sm btn-outline-primary le-btn',
      '<i class="fas fa-folder-open me-1"></i>从资源根目录选择文件');
    addFiles.type = 'button';
    addFiles.addEventListener('click', function () {
      openPicker({ mode: 'add', section: sec });
    });
    addRow.appendChild(addFiles);
    var addAct = el('button', 'btn btn-sm btn-outline-secondary le-btn',
      '<i class="fas fa-controller me-1"></i>添加互动活动');
    addAct.type = 'button';
    addAct.addEventListener('click', function () {
      openPicker({ mode: 'add', section: sec, tab: 'activity' });
    });
    addRow.appendChild(addAct);
    var addQf = el('button', 'btn btn-sm btn-outline-warning le-btn',
      '<i class="fas fa-chart-column me-1"></i>添加 QuickForm 成绩');
    addQf.type = 'button';
    addQf.addEventListener('click', function () { openQuickFormDialog(sec); });
    addRow.appendChild(addQf);
    childBox.appendChild(addRow);
    node.appendChild(childBox);

    (sec.children || []).forEach(function (child, k) {
      childBox.appendChild(renderSection(child, sec.children, k, depth + 1));
    });
    return node;
  }

  function renderItem(it, siblings, index) {
    var row = el('div', 'le-item');
    row.dataset.src = it.src || '';
    var title = el('input', 'form-control form-control-sm le-it-title');
    title.value = it.title;
    title.placeholder = '条目标题';
    title.addEventListener('input', function () { it.title = title.value; });

    var kindSel = el('select', 'form-select form-select-sm le-it-kind');
    kindSel.innerHTML = KINDS.map(function (kv) {
      return '<option value="' + kv[0] + '"' + (it.kind === kv[0] ? ' selected' : '') + '>' + kv[1] + '</option>';
    }).join('');
    kindSel.addEventListener('change', function () { it.kind = kindSel.value; render(); });

    row.appendChild(title);
    row.appendChild(kindSel);

    if (it.kind === 'video' || it.kind === 'pptx' || it.kind === 'doc' ||
        it.kind === 'geogebra') {
      row.appendChild(renderFileChoice(it));
      if (it.kind === 'doc') {
        var catSel = el('select', 'form-select form-select-sm le-it-cat');
        catSel.innerHTML = DOC_CATS.map(function (kv) {
          return '<option value="' + kv[0] + '"' + ((it.doc_category || 'guide') === kv[0] ? ' selected' : '') + '>' + kv[1] + '</option>';
        }).join('');
        catSel.addEventListener('change', function () { it.doc_category = catSel.value; });
        row.appendChild(catSel);
      }
    } else if (it.kind === 'activity') {
      row.appendChild(el('span', 'le-it-meta', '活动 #' + (it.activity_id || '?')));
      var pickAct = el('button', 'btn btn-sm btn-outline-secondary le-btn', '更换活动');
      pickAct.type = 'button';
      pickAct.addEventListener('click', function () {
        openPicker({ mode: 'edit', item: it, tab: 'activity' });
      });
      row.appendChild(pickAct);
    } else if (it.kind === 'survey') {
      row.appendChild(el('span', 'le-it-meta', '问卷 #' + (it.survey_id || '?')));
      var pickSrv = el('button', 'btn btn-sm btn-outline-secondary le-btn', '更换问卷');
      pickSrv.type = 'button';
      pickSrv.addEventListener('click', function () {
        openPicker({ mode: 'edit', item: it, tab: 'survey' });
      });
      row.appendChild(pickSrv);
    } else if (it.kind === 'link') {
      var url = el('input', 'form-control form-control-sm le-it-url');
      url.value = it.src || '';
      url.placeholder = 'https://… 或站内 /path';
      url.addEventListener('input', function () { it.src = url.value; row.dataset.src = url.value; });
      row.appendChild(url);
      if (it.purpose === 'quickform_results') {
        row.appendChild(el('span', 'le-it-meta', 'QuickForm 成绩'));
        var openMode = el('select', 'form-select form-select-sm le-it-kind');
        openMode.innerHTML =
          '<option value="newtab"' + (it.open_mode !== 'embed' ? ' selected' : '') + '>新标签页</option>' +
          '<option value="embed"' + (it.open_mode === 'embed' ? ' selected' : '') + '>课堂内嵌</option>';
        openMode.addEventListener('change', function () { it.open_mode = openMode.value; });
        row.appendChild(openMode);
      } else {
        var pickLink = el('button', 'btn btn-sm btn-outline-secondary le-btn', '选择网页');
        pickLink.type = 'button';
        pickLink.addEventListener('click', function () {
          openPicker({ mode: 'edit', item: it, tab: 'link' });
        });
        row.appendChild(pickLink);
      }
    }

    var vis = el('label', 'le-it-vis');
    vis.title = '学生端是否可见（教师端始终可见）';
    vis.innerHTML = '<input type="checkbox"' + ((it.visible || {}).student !== false ? ' checked' : '') + '> 学生可见';
    vis.querySelector('input').addEventListener('change', function (e) {
      it.visible = Object.assign({ teacher: true, student: true }, it.visible || {});
      it.visible.student = e.target.checked;
    });
    row.appendChild(vis);

    row.appendChild(moveBtn('↑', function () {
      if (index <= 0) return;
      siblings.splice(index, 1);
      siblings.splice(index - 1, 0, it);
      render();
    }, index === 0));
    row.appendChild(moveBtn('↓', function () {
      if (index >= siblings.length - 1) return;
      siblings.splice(index, 1);
      siblings.splice(index + 1, 0, it);
      render();
    }, index === siblings.length - 1));
    row.appendChild(delBtn(function () {
      siblings.splice(index, 1);
      render();
    }));
    return row;
  }

  function renderFileChoice(it) {
    var wrap = el('span', 'le-it-file');
    var label = el('span', 'le-it-srcname', esc(it.src || '未选择文件'));
    label.title = it.src || '';
    var btn = el('button', 'btn btn-sm btn-outline-secondary le-btn', '选择文件');
    btn.type = 'button';
    btn.addEventListener('click', function () {
      openPicker({ mode: 'edit', item: it, tab: it.kind });
    });
    wrap.appendChild(label);
    wrap.appendChild(btn);
    return wrap;
  }

  /* ══ QuickForm 成绩入口弹窗 ══ */
  function closeQuickFormDialog() {
    var ov = document.querySelector('.le-qf-overlay');
    if (ov) ov.remove();
  }
  function openQuickFormDialog(section) {
    if (!section) return;
    closeQuickFormDialog();
    var ov = el('div', 'le-qf-overlay');
    ov.innerHTML =
      '<div class="le-qf-panel">' +
      '  <div class="le-qf-head"><strong><i class="fas fa-chart-column me-1"></i>添加 QuickForm 成绩入口</strong>' +
      '    <button type="button" class="btn btn-sm btn-outline-secondary" data-qf="close">关闭</button></div>' +
      '  <div class="le-qf-body">' +
      '    <label class="form-label">标题</label>' +
      '    <input type="text" class="form-control form-control-sm" data-qf="title" value="QuickForm 成绩">' +
      '    <label class="form-label mt-3">QuickForm 数据结果页 URL</label>' +
      '    <input type="url" class="form-control form-control-sm" data-qf="url" placeholder="https://quickform.cn/...">' +
      '    <label class="form-label mt-3">打开方式</label>' +
      '    <select class="form-select form-select-sm" data-qf="mode">' +
      '      <option value="newtab">新标签页（默认，兼容性最好）</option>' +
      '      <option value="embed">课堂内嵌 iframe</option>' +
      '    </select>' +
      '    <label class="form-check mt-3"><input type="checkbox" class="form-check-input" data-qf="student"> 学生端可见</label>' +
      '    <div class="text-muted small mt-2">QuickForm 成绩页可能包含全班数据，默认仅教师可见。外部页面若禁止嵌入，请使用新标签页。</div>' +
      '  </div>' +
      '  <div class="le-qf-foot"><button type="button" class="btn btn-sm btn-secondary" data-qf="cancel">取消</button>' +
      '    <button type="button" class="btn btn-sm btn-primary" data-qf="confirm">添加</button></div>' +
      '</div>';
    document.body.appendChild(ov);
    ov.querySelector('[data-qf="close"]').addEventListener('click', closeQuickFormDialog);
    ov.querySelector('[data-qf="cancel"]').addEventListener('click', closeQuickFormDialog);
    ov.addEventListener('click', function (e) { if (e.target === ov) closeQuickFormDialog(); });
    ov.querySelector('[data-qf="confirm"]').addEventListener('click', function () {
      var title = (ov.querySelector('[data-qf="title"]').value || '').trim() || 'QuickForm 成绩';
      var url = (ov.querySelector('[data-qf="url"]').value || '').trim();
      var parsedUrl = null;
      try { parsedUrl = new URL(url); } catch (e) { parsedUrl = null; }
      if (!parsedUrl || !/^https?:$/.test(parsedUrl.protocol) || !parsedUrl.hostname) {
        window.alert('请填写有效的 http:// 或 https:// QuickForm 结果页地址');
        return;
      }
      var mode = ov.querySelector('[data-qf="mode"]').value === 'embed' ? 'embed' : 'newtab';
      var student = ov.querySelector('[data-qf="student"]').checked;
      section.items.push({
        id: genId(), title: title, kind: 'link', src: url,
        purpose: 'quickform_results', open_mode: mode,
        visible: { teacher: true, student: student }
      });
      closeQuickFormDialog();
      render();
    });
    var input = ov.querySelector('[data-qf="url"]');
    if (input) input.focus();
  }

  /* ══ 资源根目录选择器 ══ */
  function openPicker(opts) {
    closePicker();
    var tab = opts.tab || 'all';
    if (opts.item && opts.item.kind && opts.item.kind !== 'activity' &&
        PICKER_TABS.some(function (t) { return t[0] === opts.item.kind; })) {
      tab = opts.item.kind;
    }
    picker = {
      mode: opts.mode || 'add',
      section: opts.section || null,
      item: opts.item || null,
      tab: tab,
      path: '', supported: true, root: null, breadcrumb: [],
      entries: [], selected: {}, loading: false, error: ''
    };
    buildPicker();
    loadPickerDir('');
  }

  function closePicker() {
    var ov = document.querySelector('.le-picker-overlay');
    if (ov) ov.remove();
    picker = null;
  }

  function buildPicker() {
    var ov = el('div', 'le-picker-overlay');
    ov.innerHTML =
      '<div class="le-picker-panel">' +
      '  <div class="le-picker-head">' +
      '    <strong><i class="fas fa-folder-open me-1"></i>从资源根目录选择</strong>' +
      '    <span class="le-picker-root" id="lePickerRoot">资源根目录</span>' +
      '    <button type="button" class="btn btn-sm btn-outline-secondary" data-p="close">关闭</button>' +
      '  </div>' +
      '  <div class="le-picker-tabs" id="lePickerTabs"></div>' +
      '  <div class="le-picker-pathbar" id="lePickerPathbar">' +
      '    <button type="button" class="btn btn-sm btn-outline-secondary" data-p="up">↑ 上级</button>' +
      '    <div class="le-picker-crumb" id="lePickerCrumb"></div>' +
      '    <button type="button" class="btn btn-sm btn-outline-secondary" data-p="root">定位根目录</button>' +
      '  </div>' +
      '  <div class="le-picker-status" id="lePickerStatus"></div>' +
      '  <div class="le-picker-list" id="lePickerList"></div>' +
      '  <div class="le-picker-foot">' +
      '    <span id="lePickerCount" class="le-picker-count"></span>' +
      '    <button type="button" class="btn btn-sm btn-secondary" data-p="cancel">取消</button>' +
      '    <button type="button" class="btn btn-sm btn-primary" id="lePickerConfirm" data-p="confirm" disabled>加入当前章节</button>' +
      '  </div>' +
      '</div>';
    document.body.appendChild(ov);
    // 标签页
    var tabs = ov.querySelector('#lePickerTabs');
    PICKER_TABS.forEach(function (t) {
      var b = el('button', 'le-picker-tab' + (picker.tab === t[0] ? ' active' : ''), t[1]);
      b.type = 'button';
      b.dataset.tab = t[0];
      b.addEventListener('click', function () {
        picker.tab = t[0];
        renderPicker();
      });
      tabs.appendChild(b);
    });
    ov.querySelector('[data-p="close"]').addEventListener('click', closePicker);
    ov.querySelector('[data-p="cancel"]').addEventListener('click', closePicker);
    ov.querySelector('[data-p="root"]').addEventListener('click', function () {
      loadPickerDir('');
    });
    ov.querySelector('[data-p="up"]').addEventListener('click', function () {
      if (!picker || !picker.path) return;
      var parts = picker.path.split('/');
      parts.pop();
      loadPickerDir(parts.join('/'));
    });
    ov.querySelector('[data-p="confirm"]').addEventListener('click', confirmPicker);
    ov.addEventListener('click', function (e) { if (e.target === ov) closePicker(); });
  }

  function loadPickerDir(path) {
    if (!picker) return;
    picker.loading = true;
    picker.error = '';
    renderPicker();
    fetch('/admin/resources/' + DATA.resourceId + '/lesson_files?path=' +
          encodeURIComponent(path || ''), { credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!picker) return;
        picker.loading = false;
        if (!d.success) {
          picker.error = d.msg || '资源目录读取失败';
          renderPicker();
          return;
        }
        picker.supported = d.supported !== false;
        if (!picker.supported) {
          picker.root = null;
          picker.error = d.msg || '该资源没有可用的本地课件目录';
          picker.entries = [];
          renderPicker();
          return;
        }
        picker.root = d.root || null;
        picker.path = d.path || '';
        picker.breadcrumb = d.breadcrumb || [];
        picker.entries = d.entries || [];
        renderPicker();
      })
      .catch(function () {
        if (!picker) return;
        picker.loading = false;
        picker.error = '资源目录读取失败（网络错误）';
        renderPicker();
      });
  }

  function renderPicker() {
    if (!picker) return;
    var rootEl = document.getElementById('lePickerRoot');
    if (rootEl) {
      rootEl.textContent = picker.root
        ? '资源根目录：' + picker.root.label + ' / ' + picker.root.dir
        : '资源根目录';
    }
    document.querySelectorAll('.le-picker-tab').forEach(function (b) {
      b.classList.toggle('active', b.dataset.tab === picker.tab);
    });
    var pathbar = document.getElementById('lePickerPathbar');
    if (pathbar) {
      pathbar.style.display = (picker.tab === 'activity' || picker.tab === 'survey')
        ? 'none' : '';
    }
    renderCrumb();
    renderStatus();
    renderList();
    updatePickerFoot();
  }

  function renderCrumb() {
    var box = document.getElementById('lePickerCrumb');
    if (!box) return;
    box.innerHTML = '';
    if (!picker || !picker.breadcrumb.length) return;
    picker.breadcrumb.forEach(function (c, i) {
      if (i) box.appendChild(el('span', 'le-picker-crumb-sep', '/'));
      var b = el('button', 'le-picker-crumb-btn', esc(c.name));
      b.type = 'button';
      b.addEventListener('click', function () { loadPickerDir(c.path || ''); });
      box.appendChild(b);
    });
  }

  function renderStatus() {
    var s = document.getElementById('lePickerStatus');
    if (!s) return;
    if (picker.loading) { s.textContent = '正在读取资源目录…'; return; }
    if (picker.tab === 'activity') {
      s.textContent = '互动活动来自当前资源，可直接加入当前章节。';
      return;
    }
    if (picker.tab === 'survey') {
      s.textContent = '调查问卷来自当前资源（仅已发布问卷会出现在学生课堂）。';
      return;
    }
    if (picker.error) { s.textContent = picker.error; return; }
    var dirs = picker.entries.filter(function (e) { return e.is_dir; }).length;
    var files = picker.entries.filter(function (e) { return !e.is_dir; }).length;
    s.textContent = '当前目录：' + (picker.path || '根目录') +
      '，' + dirs + ' 个文件夹、' + files + ' 个文件';
  }

  function renderList() {
    var list = document.getElementById('lePickerList');
    if (!list) return;
    list.innerHTML = '';
    if (picker.loading) {
      list.appendChild(el('div', 'le-picker-empty', '正在读取…'));
      return;
    }
    if (picker.tab === 'activity') {
      renderActivities(list);
      return;
    }
    if (picker.tab === 'survey') {
      renderSurveys(list);
      return;
    }
    if (picker.error || !picker.supported) {
      list.appendChild(el('div', 'le-picker-empty', picker.error || '资源目录不可用'));
      return;
    }
    var filter = picker.tab;
    var visible = picker.entries.filter(function (e) {
      return e.is_dir || filter === 'all' || e.kind === filter;
    });
    if (!visible.length) {
      list.appendChild(el('div', 'le-picker-empty', '当前目录没有符合条件的文件。'));
      return;
    }
    visible.forEach(function (entry) {
      if (entry.is_dir) list.appendChild(renderDirRow(entry));
      else list.appendChild(renderFileRow(entry));
    });
  }

  function renderDirRow(entry) {
    var row = el('div', 'le-picker-row le-picker-dir');
    row.title = entry.path;
    row.innerHTML =
      '<span class="le-picker-folder"><i class="fas fa-folder"></i></span>' +
      '<span class="le-picker-name">' + esc(entry.name) + '</span>' +
      '<span class="le-picker-badge">文件夹</span>';
    row.addEventListener('click', function () { loadPickerDir(entry.path); });
    return row;
  }

  function renderFileRow(entry) {
    var row = el('div', 'le-picker-row' + (entry.kind === 'other' ? ' disabled' : ''));
    row.title = entry.path;
    var key = 'file:' + entry.path;
    var checked = !!picker.selected[key];
    if (checked) row.classList.add('selected');
    var checkHtml = '';
    if (picker.mode === 'add' && entry.kind !== 'other') {
      checkHtml = '<input type="checkbox" class="le-picker-check"' +
        (checked ? ' checked' : '') + ' aria-label="选择文件">';
    }
    var badges = '<span class="le-picker-badge">' + (KIND_LABEL[entry.kind] || '文件') + '</span>';
    if (entry.can_show === false) badges += '<span class="le-picker-badge warn">仅教师</span>';
    if (entry.kind === 'doc' && entry.previewable === false) {
      badges += '<span class="le-picker-badge muted">下载查看</span>';
    }
    if (entry.is_homepage) badges += '<span class="le-picker-badge">主页</span>';
    row.innerHTML =
      checkHtml +
      '<span class="le-picker-file-icon"><i class="fas ' +
      (entry.kind === 'video' ? 'fa-play-circle' : entry.kind === 'pptx' ? 'fa-file-powerpoint' :
        entry.kind === 'link' ? 'fa-globe' :
        entry.kind === 'geogebra' ? 'fa-cubes' : 'fa-file-alt') + '"></i></span>' +
      '<span class="le-picker-name">' + esc(entry.name) + '</span>' +
      badges +
      '<span class="le-picker-size">' + (entry.kind === 'other' ? '不支持编排' : fmtSize(entry.size)) + '</span>';
    if (picker.mode === 'edit' && entry.kind !== 'other') {
      var choose = el('button', 'btn btn-sm btn-outline-primary le-btn', '使用');
      choose.type = 'button';
      choose.addEventListener('click', function (e) {
        e.stopPropagation();
        applyPickedFile(entry);
      });
      row.appendChild(choose);
    }
    if (picker.mode === 'add' && entry.kind !== 'other') {
      var cb = row.querySelector('.le-picker-check');
      if (cb) {
        cb.addEventListener('click', function (e) { e.stopPropagation(); });
        cb.addEventListener('change', function () {
          toggleSelected(key, entry);
          renderPicker();
        });
      }
      row.addEventListener('click', function () {
        toggleSelected(key, entry);
        renderPicker();
      });
    } else if (picker.mode === 'edit' && entry.kind !== 'other') {
      row.addEventListener('click', function () { applyPickedFile(entry); });
    }
    return row;
  }

  function renderActivities(list) {
    var acts = DATA.activities || [];
    if (!acts.length) {
      list.appendChild(el('div', 'le-picker-empty', '当前资源还没有互动活动，请先在资源编辑页创建活动。'));
      return;
    }
    acts.forEach(function (act) {
      var key = 'act:' + act.id;
      var checked = !!picker.selected[key];
      var row = el('div', 'le-picker-row' + (checked ? ' selected' : ''));
      row.innerHTML =
        (picker.mode === 'add' ? '<input type="checkbox" class="le-picker-check"' +
          (checked ? ' checked' : '') + ' aria-label="选择活动">' : '') +
        '<span class="le-picker-file-icon"><i class="fas fa-controller"></i></span>' +
        '<span class="le-picker-name">' + esc(act.title) + '</span>' +
        '<span class="le-picker-badge">互动活动</span>';
      if (picker.mode === 'edit') {
        var choose = el('button', 'btn btn-sm btn-outline-primary le-btn', '使用');
        choose.type = 'button';
        choose.addEventListener('click', function (e) {
          e.stopPropagation();
          applyPickedActivity(act);
        });
        row.appendChild(choose);
        row.addEventListener('click', function () { applyPickedActivity(act); });
      } else {
        var cb = row.querySelector('.le-picker-check');
        if (cb) {
          cb.addEventListener('click', function (e) { e.stopPropagation(); });
          cb.addEventListener('change', function () {
            toggleSelected(key, act);
            renderPicker();
          });
        }
        row.addEventListener('click', function () {
          toggleSelected(key, act);
          renderPicker();
        });
      }
      list.appendChild(row);
    });
  }

  function renderSurveys(list) {
    var surveys = DATA.surveys || [];
    if (!surveys.length) {
      list.appendChild(el('div', 'le-picker-empty',
        '当前资源还没有调查问卷，请先在资源编辑页创建并发布问卷。'));
      return;
    }
    surveys.forEach(function (srv) {
      var key = 'srv:' + srv.id;
      var checked = !!picker.selected[key];
      var row = el('div', 'le-picker-row' + (checked ? ' selected' : ''));
      row.innerHTML =
        (picker.mode === 'add' ? '<input type="checkbox" class="le-picker-check"' +
          (checked ? ' checked' : '') + ' aria-label="选择问卷">' : '') +
        '<span class="le-picker-file-icon"><i class="fas fa-poll"></i></span>' +
        '<span class="le-picker-name">' + esc(srv.title) + '</span>' +
        '<span class="le-picker-badge">调查问卷</span>';
      if (picker.mode === 'edit') {
        var choose = el('button', 'btn btn-sm btn-outline-primary le-btn', '使用');
        choose.type = 'button';
        choose.addEventListener('click', function (e) {
          e.stopPropagation();
          applyPickedSurvey(srv);
        });
        row.appendChild(choose);
        row.addEventListener('click', function () { applyPickedSurvey(srv); });
      } else {
        var cb = row.querySelector('.le-picker-check');
        if (cb) {
          cb.addEventListener('click', function (e) { e.stopPropagation(); });
          cb.addEventListener('change', function () {
            toggleSelected(key, { id: srv.id, title: srv.title, srv: true });
            renderPicker();
          });
        }
        row.addEventListener('click', function () {
          toggleSelected(key, { id: srv.id, title: srv.title, srv: true });
          renderPicker();
        });
      }
      list.appendChild(row);
    });
  }

  function toggleSelected(key, obj) {
    if (picker.selected[key]) delete picker.selected[key];
    else picker.selected[key] = obj;
  }

  function selectedCount() {
    return picker ? Object.keys(picker.selected).length : 0;
  }

  function updatePickerFoot() {
    var btn = document.getElementById('lePickerConfirm');
    var count = document.getElementById('lePickerCount');
    if (!btn || !count) return;
    if (picker.mode === 'edit') {
      btn.style.display = 'none';
      count.textContent = '点击文件行的「使用」即可替换';
      return;
    }
    btn.style.display = '';
    var n = selectedCount();
    count.textContent = n ? '已选择 ' + n + ' 项' : '请选择要加入的文件或活动';
    btn.disabled = n === 0 || !picker.section;
    btn.textContent = n ? '加入当前章节（' + n + '）' : '加入当前章节';
  }

  function confirmPicker() {
    if (!picker || picker.mode !== 'add' || !picker.section) return;
    var items = Object.keys(picker.selected).map(function (k) { return picker.selected[k]; });
    if (!items.length) return;
    items.forEach(function (entry) {
      if (entry.srv) {
        // 调查问卷
        picker.section.items.push({
          id: genId(), title: entry.title, kind: 'survey', src: '',
          survey_id: entry.id, visible: { teacher: true, student: true }
        });
        return;
      }
      if (entry.id !== undefined && entry.title !== undefined && entry.kind === undefined) {
        // 互动活动
        picker.section.items.push({
          id: genId(), title: entry.title, kind: 'activity', src: '',
          activity_id: entry.id, visible: { teacher: true, student: true }
        });
        return;
      }
      if (entry.is_dir || entry.kind === 'other') return;
      var src = entry.kind === 'link'
        ? pathJoin('/static/uploads', pathJoin(picker.root ? picker.root.dir : '', entry.path))
        : entry.path;
      var item = {
        id: genId(), title: baseName(entry.name), kind: entry.kind, src: src,
        visible: { teacher: true, student: entry.can_show !== false }
      };
      if (entry.kind === 'doc') item.doc_category = 'guide';
      picker.section.items.push(item);
    });
    closePicker();
    render();
  }

  function applyPickedFile(entry) {
    if (!picker || !picker.item) return;
    var item = picker.item;
    item.src = entry.kind === 'link'
      ? pathJoin('/static/uploads', pathJoin(picker.root ? picker.root.dir : '', entry.path))
      : entry.path;
    item.kind = entry.kind;
    item.title = baseName(entry.name) || item.title;
    if (item.kind === 'doc' && !item.doc_category) item.doc_category = 'guide';
    if (entry.can_show === false) {
      item.visible = Object.assign({ teacher: true, student: true }, item.visible || {});
      item.visible.student = false;
    }
    closePicker();
    render();
  }

  function applyPickedActivity(act) {
    if (!picker || !picker.item) return;
    var item = picker.item;
    item.kind = 'activity';
    item.src = '';
    item.activity_id = act.id;
    item.title = act.title;
    closePicker();
    render();
  }

  function applyPickedSurvey(srv) {
    if (!picker || !picker.item) return;
    var item = picker.item;
    item.kind = 'survey';
    item.src = '';
    item.survey_id = srv.id;
    item.title = srv.title;
    closePicker();
    render();
  }

  /* ══ 打开 / 关闭 ══ */
  function focusCurrentSection() {
    // 打开编排器时定位到包含当前主页文件的章节；找不到时定位第一节。
    var current = DATA.currentFile || '';
    var target = null;
    document.querySelectorAll('.le-item').forEach(function (row) {
      if (current && row.dataset.src && row.dataset.src === current) target = row;
    });
    var section = target ? target.closest('.le-node') : document.querySelector('.le-node');
    if (!section) return;
    document.querySelectorAll('.le-node.selected').forEach(function (n) {
      n.classList.remove('selected');
    });
    section.classList.add('selected');
    section.scrollIntoView({ block: 'center' });
  }

  function open() {
    if (document.querySelector('.le-overlay')) return;
    buildOverlay();
    render();
    focusCurrentSection();
  }
  function close() {
    closePicker();
    var ov = document.querySelector('.le-overlay');
    if (ov) ov.remove();
  }

  document.addEventListener('DOMContentLoaded', function () {
    var openBtn = document.getElementById('lessonEditorOpen');
    if (openBtn) openBtn.addEventListener('click', open);
    var resetBtn = document.getElementById('lessonTreeReset');
    if (resetBtn) resetBtn.addEventListener('click', resetTree);
  });
})();
