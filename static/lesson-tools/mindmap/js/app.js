/* ============================================================
   app.js — 交互、快捷键、演示模式、界面同步
   ============================================================ */
const App = (() => {
  const stage = document.getElementById('stage');
  const nodesEl = document.getElementById('nodes');
  const docTitle = document.getElementById('docTitle');
  const saveState = document.getElementById('saveState');
  const dock = document.getElementById('dock');
  const toastEl = document.getElementById('toast');
  const presentBar = document.getElementById('presentBar');
  const fileInput = document.getElementById('fileInput');

  let editing = null;       // { id, el, ed, isNew }
  let dropTargetId = null;
  let presenting = false;
  let composing = false;    // 输入法组词中
  let order = [];
  let reveal = 0;
  /* 挖空的揭示顺序。默认按渲染（DFS）顺序，老师讲课时逐层揭示才顺；
     "重来"会把它打乱——学生第二次练如果还是同一个顺序，记住的是位置不是内容。 */
  let blankSeq = [];

  /* ══════════ 提示 ══════════ */
  let toastTimer = null;
  function toast(msg) {
    toastEl.textContent = msg;
    toastEl.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove('show'), 1800);
  }

  /* 读屏播报 */
  const liveEl = document.getElementById('live');
  let liveTimer = null;
  function announce(msg) {
    if (!liveEl) return;
    liveEl.textContent = '';
    clearTimeout(liveTimer);
    liveTimer = setTimeout(() => { liveEl.textContent = msg; }, 40);
  }

  function esc(s) {
    return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  /* ══════════ 选中 ══════════ */
  function paintSelection() {
    const res = Renderer.result;
    if (!res) return;
    const selId = Store.selectedId || (Store.root && Store.root.id);
    res.nodes.forEach(r => {
      const el = Renderer.nodeEl(r.id);
      if (!el) return;
      const on = r.id === Store.selectedId;
      el.classList.toggle('sel', on);
      el.setAttribute('aria-selected', on ? 'true' : 'false');
      el.tabIndex = selId === r.id ? 0 : -1;
    });
    document.querySelectorAll('.edges .rel').forEach(g => {
      g.classList.toggle('sel', g.dataset.link === Store.selectedLinkId);
    });
  }

  function focusNode(id) {
    const el = Renderer.nodeEl(id);
    if (el) { try { el.focus({ preventScroll: true }); } catch (e) {} }
  }

  function select(id, scroll) {
    Store.selectedId = id;
    if (id) Store.selectedLinkId = null;
    paintSelection();
    if (scroll && id) Renderer.ensureVisible(id);
    syncDock();
  }

  function selectLink(id) {
    Store.selectedLinkId = id;
    Store.selectedId = null;
    paintSelection();
    syncDock();
    const l = Store.links.find(x => x.id === id);
    if (l) announce('已选中关系「' + l.label + '」，按 Delete 删除');
  }

  /* ══════════ 编辑 ══════════ */
  function startEdit(id, selectAll = true) {
    if (document.body.classList.contains('practicing')) return;   // 自测时只读
    if (editing && editing.id === id) return;
    if (editing) commitEdit();
    const node = Store.find(id);
    const el = Renderer.nodeEl(id);
    const rec = Renderer.result && Renderer.result.byId.get(id);
    if (!node || !el || !rec) return;

    el.classList.add('editing');
    el.style.height = 'auto';
    el.style.minHeight = rec.h + 'px';
    // 编辑时给一个舒适的宽度，避免文字挤成竖条
    const ew = Math.max(rec.w, 136);
    el.style.width = ew + 'px';
    if (rec.dir === 'l') el.style.transform = `translate(${rec.x - (ew - rec.w)}px,${rec.y}px)`;

    const box = el.querySelector('.nbox');
    box.dataset.key = '';
    box.innerHTML = '';

    const ed = document.createElement('div');
    ed.className = 'editor';
    ed.setAttribute('contenteditable', 'true');
    ed.spellcheck = false;
    ed.textContent = node.text;
    box.appendChild(ed);

    editing = { id, el, ed, isNew: node.text === '' };
    el.dataset.editing = '1';

    ed.focus({ preventScroll: true });
    if (selectAll && node.text) {
      const r = document.createRange();
      r.selectNodeContents(ed);
      const s = window.getSelection();
      s.removeAllRanges();
      s.addRange(r);
    }

    ed.addEventListener('keydown', onEditorKey);
    ed.addEventListener('compositionstart', () => { composing = true; });
    ed.addEventListener('compositionend', () => { composing = false; });
    ed.addEventListener('blur', () => { if (editing && editing.id === id) commitEdit(); });
  }

  function onEditorKey(e) {
    // 中文输入法组词期间（拼音还没上屏）不能提交，否则会把拼音写进节点
    if (composing || e.isComposing || e.keyCode === 229) return;
    e.stopPropagation();
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      commitEdit();
      return;
    }
    if (e.key === 'Tab') {
      e.preventDefault();
      const id = editing.id;
      const parent = Store.parentOf(id);
      commitEdit();
      // 空节点提交后可能被移除，此时挂到它的父节点下
      const target = Store.find(id) ? id : (parent ? parent.id : Store.root.id);
      const n = Store.addChild(target);
      Renderer.ensureVisible(n.id);
      startEdit(n.id, false);
      return;
    }
    if (e.key === 'Escape') {
      e.preventDefault();
      cancelEdit();
      return;
    }
    if (e.key === 'Enter' && e.shiftKey) {
      e.preventDefault();
      document.execCommand('insertText', false, '\n');
    }
  }

  function commitEdit() {
    if (!editing) return;
    const { id, ed, isNew } = editing;
    const node = Store.find(id);
    let raw = (ed.innerText || '').replace(/\u00a0/g, ' ').replace(/\s+$/g, '').trim();
    editing = null;
    const el = Renderer.nodeEl(id);
    if (el) { el.classList.remove('editing'); delete el.dataset.editing; el.style.minHeight = ''; }

    if (!node) { Renderer.render(); return; }
    if (raw === '') {
      if (isNew && !node.children.length) { Store.remove(id); return; }
      raw = '未命名';
    }
    if (raw !== node.text) Store.setText(id, raw);
    else Renderer.render();
  }

  function cancelEdit() {
    if (!editing) return;
    const { id, isNew } = editing;
    editing = null;
    const el = Renderer.nodeEl(id);
    if (el) { el.classList.remove('editing'); delete el.dataset.editing; el.style.minHeight = ''; }
    const node = Store.find(id);
    if (node && isNew && !node.text.trim() && !node.children.length) {
      Store.remove(id);
      return;
    }
    Renderer.render();
    select(id);
  }

  /* ══════════ 增删 ══════════ */
  function addChild() {
    const id = Store.selectedId || Store.root.id;
    if (editing) commitEdit();
    const n = Store.addChild(id);
    Renderer.ensureVisible(n.id);
    startEdit(n.id, false);
  }

  function addSibling() {
    const id = Store.selectedId || Store.root.id;
    if (editing) commitEdit();
    const n = Store.addSibling(id);
    Renderer.ensureVisible(n.id);
    startEdit(n.id, false);
  }

  function deleteNode() {
    const id = Store.selectedId;
    if (!id || id === Store.root.id) { toast('中心主题不能删除'); return; }
    Store.remove(id);
  }

  /* ══════════ 键盘导航 ══════════ */
  function navigate(dir) {
    const id = Store.selectedId;
    const node = Store.find(id);
    if (!node) return;
    const parent = Store.parentOf(id);
    const rec = Renderer.result && Renderer.result.byId.get(id);
    const vertical = Store.layout === 'org';

    const prevSib = () => {
      if (!parent) return null;
      const i = parent.children.indexOf(node);
      return i > 0 ? parent.children[i - 1].id : null;
    };
    const nextSib = () => {
      if (!parent) return null;
      const i = parent.children.indexOf(node);
      return i < parent.children.length - 1 ? parent.children[i + 1].id : null;
    };
    const firstChild = () => {
      if (!node.children.length || node.collapsed) return null;
      return node.children[0].id;
    };
    const toParent = () => (parent ? parent.id : null);

    let next = null;
    if (vertical) {
      if (dir === 'up') next = toParent();
      else if (dir === 'down') next = firstChild();
      else if (dir === 'left') next = prevSib();
      else next = nextSib();
    } else if (rec && rec.dir === 'l') {
      if (dir === 'right') next = toParent();
      else if (dir === 'left') next = firstChild();
      else if (dir === 'up') next = prevSib();
      else next = nextSib();
    } else {
      if (dir === 'left') next = toParent();
      else if (dir === 'right') next = firstChild();
      else if (dir === 'up') next = prevSib();
      else next = nextSib();
    }
    if (next) { select(next, true); focusNode(next); }
  }

  /* ══════════ 指针：平移 / 拖节点 / 双指缩放 ══════════ */
  const ptrs = new Map();      // pointerId -> {x, y}
  let gesture = null;          // {type:'pan'|'node'|'pinch'}

  function twoPts() {
    const it = ptrs.values();
    const a = it.next().value, b = it.next().value;
    return a && b ? { a, b } : null;
  }

  function pinchState() {
    const p = twoPts();
    if (!p) return null;
    return {
      d: Math.max(1, Math.hypot(p.a.x - p.b.x, p.a.y - p.b.y)),
      mx: (p.a.x + p.b.x) / 2,
      my: (p.a.y + p.b.y) / 2,
    };
  }

  function beginPinch() {
    const p = pinchState();
    if (!p) return;
    if (gesture && gesture.type === 'node') endNodeDrag(true);
    const v = Renderer.getView();
    gesture = { type: 'pinch', d0: p.d, s0: v.scale, vx: v.x, vy: v.y, mx: p.mx, my: p.my };
    stage.classList.add('panning');
  }

  function movePinch() {
    const p = pinchState();
    if (!p || !gesture || gesture.type !== 'pinch') return;
    const g = gesture;
    const s1 = U.clamp(g.s0 * (p.d / g.d0), 0.2, 2.5);
    const r = stage.getBoundingClientRect();
    const px = g.mx - r.left, py = g.my - r.top;
    const k = s1 / g.s0;
    Renderer.setView(
      px - (px - g.vx) * k + (p.mx - g.mx),
      py - (py - g.vy) * k + (p.my - g.my),
      s1
    );
  }

  function startPan(e) {
    const v = Renderer.getView();
    gesture = { type: 'pan', sx: e.clientX, sy: e.clientY, vx: v.x, vy: v.y };
    stage.classList.add('panning');
  }

  function clearDrop() {
    document.querySelectorAll('.node.drop-target').forEach(n => n.classList.remove('drop-target'));
    dropTargetId = null;
  }

  function startNodeDrag(e, id, el) {
    if (id === Store.root.id) { startPan(e); return; }
    const rec = Renderer.result.byId.get(id);
    if (!rec) { startPan(e); return; }
    gesture = { type: 'node', id, el, rec, sx: e.clientX, sy: e.clientY, dragging: false };
  }

  function moveNode(e) {
    const g = gesture;
    if (!g || g.type !== 'node') return;
    const dx = e.clientX - g.sx, dy = e.clientY - g.sy;
    if (!g.dragging && Math.hypot(dx, dy) > 6) {
      g.dragging = true;
      g.el.classList.add('dragging');
      g.el.style.pointerEvents = 'none';
    }
    if (!g.dragging) return;
    const s = Renderer.getView().scale;
    g.el.style.transform = `translate(${g.rec.x + dx / s}px,${g.rec.y + dy / s}px)`;

    const under = document.elementFromPoint(e.clientX, e.clientY);
    const target = under && under.closest ? under.closest('.node') : null;
    const tid = target ? target.dataset.id : null;
    if (tid !== dropTargetId) {
      clearDrop();
      if (tid && tid !== g.id && !Store.isDescendant(g.id, tid)) {
        dropTargetId = tid;
        target.classList.add('drop-target');
      }
    }
  }

  function endNodeDrag(cancel) {
    const g = gesture;
    if (!g || g.type !== 'node') return;
    gesture = null;
    g.el.style.pointerEvents = '';
    if (!g.dragging) return;
    g.el.classList.remove('dragging');
    const tid = dropTargetId;
    clearDrop();
    if (!cancel && tid && Store.moveTo(g.id, tid)) {
      toast('已移动到「' + (Store.find(tid).text || '未命名') + '」下');
      return;
    }
    Renderer.render();
  }

  function onPointerMove(e) {
    if (ptrs.has(e.pointerId)) ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (gesture && gesture.type === 'pinch') { movePinch(); return; }
    if (gesture && gesture.type === 'pan') {
      Renderer.setView(
        gesture.vx + e.clientX - gesture.sx,
        gesture.vy + e.clientY - gesture.sy,
        Renderer.getView().scale
      );
      return;
    }
    moveNode(e);
  }

  function onPointerUp(e) {
    ptrs.delete(e.pointerId);
    if (!gesture) return;
    if (gesture.type === 'pinch') {
      if (ptrs.size < 2) { gesture = null; stage.classList.remove('panning'); }
      return;
    }
    if (ptrs.size) return;        // 还有手指没抬起来，先不结束
    if (gesture.type === 'pan') { gesture = null; stage.classList.remove('panning'); return; }
    endNodeDrag(false);
  }

  /* ══════════ 关系边 ══════════ */
  const relPop = document.getElementById('relPop');
  const relInput = document.getElementById('relInput');
  let relFrom = null, relEditId = null, linkMode = false;

  function placePop(x, y) {
    relPop.hidden = false;
    const r = relPop.getBoundingClientRect();
    let px = x + 12, py = y + 14;
    if (px + r.width > window.innerWidth - 12) px = window.innerWidth - r.width - 12;
    if (py + r.height > window.innerHeight - 12) py = y - r.height - 14;
    relPop.style.left = Math.max(12, px) + 'px';
    relPop.style.top = Math.max(12, py) + 'px';
  }

  function openRel(fromId, toId, x, y, editId) {
    const a = Store.find(fromId), b = Store.find(toId);
    if (!a || !b) return;
    relFrom = fromId;
    relEditId = editId || null;
    document.getElementById('relTitle').textContent = editId ? '修改关系词' : '建立关系';
    document.getElementById('relFrom').textContent = a.text || '未命名';
    const toEl = document.getElementById('relTo');
    toEl.textContent = b.text || '未命名';
    toEl.dataset.id = toId;
    const cur = editId ? ((Store.links.find(l => l.id === editId) || {}).label || '') : '';
    relInput.value = cur;
    document.querySelectorAll('#relChips button').forEach(btn => {
      btn.classList.toggle('on', btn.dataset.w === cur);
    });
    placePop(x, y);
    setTimeout(() => { relInput.focus(); relInput.select(); }, 20);
  }

  function closeRel() {
    relPop.hidden = true;
    relFrom = null;
    relEditId = null;
  }

  function submitRel() {
    const label = (relInput.value || '').trim().slice(0, 8) || '关联';
    const toId = document.getElementById('relTo').dataset.id;
    if (relEditId) {
      Store.setLinkLabel(relEditId, label);
      toast('关系词已更新');
    } else {
      const l = Store.addLink(relFrom, toId, label);
      if (l) {
        toast('已建立关系「' + label + '」');
        announce('已建立关系 ' + label);
      } else {
        toast('这两个节点之间已经有关联了');
      }
    }
    closeRel();
  }

  function setLinkMode(on) {
    linkMode = on;
    document.body.classList.toggle('link-mode', on);
    if (on) {
      if (!Store.selectedId) {
        toast('先选中一个节点，再点「关系」');
        linkMode = false;
        document.body.classList.remove('link-mode');
        syncDock();
        return;
      }
      toast('关系模式：点另一个节点建立关系');
    }
    syncDock();
  }

  function bindRel() {
    document.getElementById('relOk').onclick = submitRel;
    document.getElementById('relCancel').onclick = closeRel;
    document.querySelectorAll('#relChips button').forEach(btn => {
      btn.onclick = () => {
        relInput.value = btn.dataset.w;
        document.querySelectorAll('#relChips button').forEach(b => b.classList.toggle('on', b === btn));
      };
    });
    relInput.addEventListener('keydown', e => {
      e.stopPropagation();
      if (e.isComposing || e.keyCode === 229) return;
      if (e.key === 'Enter') { e.preventDefault(); submitRel(); }
      else if (e.key === 'Escape') { e.preventDefault(); closeRel(); }
    });
    document.addEventListener('pointerdown', e => {
      if (!relPop.hidden && !e.target.closest('#relPop')) closeRel();
    }, true);
  }

  /* ══════════ 事件绑定 ══════════ */
  function bindStage() {
    stage.addEventListener('pointerdown', e => {
      if (e.pointerType === 'mouse' && e.button !== 0) return;
      ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (ptrs.size === 2) { beginPinch(); return; }   // 双指：进入缩放
      if (ptrs.size > 2) return;

      const target = e.target;
      if (target.closest('.cbtn')) return;

      /* 自测模式只读：点节点不能揭示答案（否则学生先点开看一眼再写，
         检索练习就失效了），也不能拖拽/选中。保留单指平移。 */
      if (document.body.classList.contains('practicing')) { startPan(e); return; }

      const nodeEl0 = target.closest('.node');
      if (editing) {
        if (nodeEl0 && nodeEl0.dataset.id === editing.id) return; // 点在编辑器内
        commitEdit();
      }
      // 提交编辑后布局可能变化，重新做一次命中检测
      const under = document.elementFromPoint(e.clientX, e.clientY);
      if (!under) return;

      const relG = under.closest ? under.closest('.rel') : null;
      if (relG) { selectLink(relG.dataset.link); return; }

      const nodeEl = under.closest('.node');
      if (nodeEl) {
        const id = nodeEl.dataset.id;
        if (nodeEl.classList.contains('hidden-node')) return;

        // Shift + 点击 / 关系模式：在两个节点之间建立关系
        if ((e.shiftKey || linkMode) && Store.selectedId && Store.selectedId !== id) {
          e.preventDefault();
          openRel(Store.selectedId, id, e.clientX, e.clientY);
          if (linkMode) setLinkMode(false);
          return;
        }

        select(id);
        // 挖空练习：点一下就揭示这个节点
        if (Store.blank && id !== Store.root.id && !Store.revealed.has(id)) {
          Store.reveal(id);
          syncBlankBar();
        }
        startNodeDrag(e, id, nodeEl);
      } else {
        select(null);
        startPan(e);
      }
    });

    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
    window.addEventListener('pointercancel', onPointerUp);

    nodesEl.addEventListener('click', e => {
      const btn = e.target.closest('.cbtn');
      if (!btn) return;
      if (document.body.classList.contains('practicing')) return;   // 自测时不许折叠题目
      const nodeEl = btn.closest('.node');
      if (nodeEl) Store.toggleCollapse(nodeEl.dataset.id);
    });

    nodesEl.addEventListener('dblclick', e => {
      if (document.body.classList.contains('practicing')) return;
      const nodeEl = e.target.closest('.node');
      if (nodeEl && !editing) startEdit(nodeEl.dataset.id);
    });

    // 双击关系线：改关系词
    stage.addEventListener('dblclick', e => {
      if (document.body.classList.contains('practicing')) return;
      const g = e.target.closest ? e.target.closest('.rel') : null;
      if (!g) return;
      const l = Store.links.find(x => x.id === g.dataset.link);
      if (l) openRel(l.from, l.to, e.clientX, e.clientY, l.id);
    });

    stage.addEventListener('wheel', e => {
      e.preventDefault();
      const dy = U.clamp(e.deltaY, -60, 60);
      Renderer.zoomAt(e.clientX, e.clientY, Math.exp(-dy * 0.0022));
    }, { passive: false });

    // 缩放条
    document.getElementById('zoombar').addEventListener('click', e => {
      const b = e.target.closest('[data-zoom]');
      if (!b) return;
      const a = b.dataset.zoom;
      if (a === 'in') Renderer.zoomBy(1.2);
      else if (a === 'out') Renderer.zoomBy(1 / 1.2);
      else if (a === 'fit') Renderer.fit();
      else if (a === 'reset') {
        const v = Renderer.getView();
        const r = stage.getBoundingClientRect();
        const wx = (r.width / 2 - v.x) / v.scale;
        const wy = (r.height / 2 - v.y) / v.scale;
        Renderer.setView(r.width / 2 - wx, r.height / 2 - wy, 1);
      }
    });

    // 工具岛
    dock.addEventListener('click', e => {
      const b = e.target.closest('[data-act]');
      if (!b || b.disabled) return;
      const a = b.dataset.act;
      if (a === 'add-child') addChild();
      else if (a === 'add-sibling') addSibling();
      else if (a === 'edit') { if (Store.selectedId) startEdit(Store.selectedId); }
      else if (a === 'link') setLinkMode(!linkMode);
      else if (a === 'delete') deleteNode();
      else if (a === 'collapse') { if (Store.selectedId) Store.toggleCollapse(Store.selectedId); }
      else if (a === 'undo') { Store.undo(); }
      else if (a === 'redo') { Store.redo(); }
    });
  }

  /* ══════════ 键盘焦点 ══════════
     全局快捷键只在「焦点不在控件上」时生效。之前 Tab/Enter 对所有元素都劫持：
     键盘用户按 Tab 想从顶栏走到下一个按钮，结果是加了一个子节点；
     按 Enter 想打开帮助，结果是加了一个同级节点。axe 查不出这种问题。 */
  function isFormCtrl(el) {
    return !!(el && el.closest &&
      el.closest('button,a,input,textarea,select,summary,[contenteditable="true"],[role="dialog"]'));
  }

  function trapTab(e, box) {
    if (!box) return;
    const items = [...box.querySelectorAll('button,[href],input,select,textarea,[tabindex]:not([tabindex="-1"])')]
      .filter(el => !el.disabled && el.offsetParent !== null);
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && (document.activeElement === first || !box.contains(document.activeElement))) {
      e.preventDefault(); last.focus();
    } else if (!e.shiftKey && (document.activeElement === last || !box.contains(document.activeElement))) {
      e.preventDefault(); first.focus();
    }
  }

  let helpReturnFocus = null;
  function helpTab(n) {
    const one = n === 1;
    const t1 = document.getElementById('helpTab1'), t2 = document.getElementById('helpTab2');
    document.getElementById('helpPane1').hidden = !one;
    document.getElementById('helpPane2').hidden = one;
    t1.classList.toggle('on', one); t2.classList.toggle('on', !one);
    t1.setAttribute('aria-selected', one ? 'true' : 'false');
    t2.setAttribute('aria-selected', one ? 'false' : 'true');
  }
  function openHelp() {
    helpTab(1);
    helpReturnFocus = document.activeElement;
    document.getElementById('helpMask').classList.add('show');
    setTimeout(() => { const el = document.getElementById('helpTab1'); if (el) el.focus(); }, 30);
  }
  function closeHelp() {
    document.getElementById('helpMask').classList.remove('show');
    if (helpReturnFocus && document.contains(helpReturnFocus)) helpReturnFocus.focus();
    helpReturnFocus = null;
  }

  function bindKeyboard() {
    document.addEventListener('keydown', e => {
      const t = e.target;
      if (t === docTitle) return;
      if (editing) return;

      const mod = e.ctrlKey || e.metaKey;
      const helpMask = document.getElementById('helpMask');
      const scoreMask = document.getElementById('scoreMask');
      const resultMask = document.getElementById('practiceResult');

      /* 弹窗打开时，键盘只在弹窗里活动 */
      if (helpMask.classList.contains('show')) {
        if (e.key === 'Escape') { e.preventDefault(); closeHelp(); return; }
        if (e.key === 'Tab') { trapTab(e, helpMask.querySelector('.modal')); return; }
        return;
      }
      if (scoreMask.classList.contains('show')) {
        if (e.key === 'Escape') { e.preventDefault(); closeScore(); return; }
        if (e.key === 'Tab') { trapTab(e, scoreMask.querySelector('.modal')); return; }
        return;
      }
      if (resultMask.classList.contains('show')) {
        if (e.key === 'Tab') { trapTab(e, resultMask.querySelector('.modal')); return; }
      }

      /* 自测是学生答题，不是编辑：Tab/Enter/Delete 这些画布快捷键一律让位。
         Esc 由 practice.js 的捕获监听处理（退出自测）。 */
      if (document.body.classList.contains('practicing')) return;

      if (presenting) {
        if (e.key === 'Escape') { e.preventDefault(); exitPresent(); return; }
        if (isFormCtrl(t)) return;
        if (e.code === 'Space' || e.key === 'ArrowRight' || e.key === 'PageDown') {
          e.preventDefault(); nextReveal(); return;
        }
        if (e.key === 'ArrowLeft' || e.key === 'PageUp') { e.preventDefault(); prevReveal(); return; }
        return;                       // 演示中不响应 Tab / Delete 这些编辑键
      }

      if (!relPop.hidden) {
        if (e.key === 'Escape') { e.preventDefault(); closeRel(); }
        return;                       // 关系浮层里的按钮自己处理 Enter / 空格
      }

      if (Store.blank) {
        if (e.key === 'Escape') { e.preventDefault(); setBlank(false); return; }
        if (isFormCtrl(t)) return;    // 挖空条上的按钮要能正常用键盘操作
        if (e.code === 'Space') { e.preventDefault(); nextBlank(); return; }
      }

      /* 控件获得焦点时，把 Tab / Enter / 空格 / 方向键还给控件本身 */
      if (isFormCtrl(t)) return;

      if (mod && (e.key === 'z' || e.key === 'Z')) {
        e.preventDefault();
        e.shiftKey ? Store.redo() : Store.undo();
        return;
      }
      if (mod && (e.key === 'y' || e.key === 'Y')) { e.preventDefault(); Store.redo(); return; }
      if (mod && e.key === 's') { e.preventDefault(); Store.save(); toast('已保存到本机'); return; }
      if (mod && e.key === '0') { e.preventDefault(); Renderer.fit(); return; }
      if (mod && (e.key === '/' || e.key === '?')) {
        e.preventDefault();
        if (Store.selectedId) Store.toggleCollapse(Store.selectedId);
        return;
      }
      if (mod) return;

      switch (e.key) {
        case 'Tab':
          /* Shift+Tab 必须能把焦点移出画布，否则键盘用户会被困在节点里 */
          if (e.shiftKey) return;
          e.preventDefault(); addChild(); break;
        case 'Enter': e.preventDefault(); addSibling(); break;
        case 'F2': e.preventDefault(); if (Store.selectedId) startEdit(Store.selectedId); break;
        case 'Delete': case 'Backspace':
          e.preventDefault();
          if (Store.selectedLinkId) {
            Store.removeLink(Store.selectedLinkId);
            Store.selectedLinkId = null;
            toast('关系已删除');
          } else deleteNode();
          break;
        case 'Escape':
          if (linkMode) setLinkMode(false);
          else if (Store.selectedLinkId) { Store.selectedLinkId = null; paintSelection(); }
          else select(null);
          break;
        case 'ArrowUp': e.preventDefault(); navigate('up'); break;
        case 'ArrowDown': e.preventDefault(); navigate('down'); break;
        case 'ArrowLeft': e.preventDefault(); navigate('left'); break;
        case 'ArrowRight': e.preventDefault(); navigate('right'); break;
        case '+': case '=': e.preventDefault(); Renderer.zoomBy(1.2); break;
        case '-': case '_': e.preventDefault(); Renderer.zoomBy(1 / 1.2); break;
      }
    });
  }

  /* ══════════ 菜单 ══════════ */
  function closeMenus() {
    document.querySelectorAll('.menu.open').forEach(m => m.classList.remove('open'));
    document.querySelectorAll('[data-menu]').forEach(b => b.setAttribute('aria-expanded', 'false'));
  }

  function toggleMenu(id, btn) {
    const m = document.getElementById(id);
    const isOpen = m.classList.contains('open');
    closeMenus();
    if (!isOpen) {
      m.classList.add('open');
      btn.setAttribute('aria-expanded', 'true');
      if (id === 'menu-template') buildTemplateMenu();   // 每次打开都回到「要做哪件事」这一层
      if (id === 'menu-theme') syncThemeMenu();
      if (id === 'menu-layout') syncLayoutMenu();
      if (id === 'menu-doc') buildDocMenu();
    }
  }

  const CHECK = '<svg class="check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 12.5l5 5 10-11"/></svg>';

  /* 模板菜单分两层：
     第一层问「你现在要做哪件事」，八个动作直接对应八种图型；
     第二层才是图型名和课堂模板，留给已经熟悉的人。
     原来第一层就是八个图形名（圆圈图、气泡图…），等于把「选工具」的负担
     丢给了还没掌握思维方法的人——先问「要做哪件事」，再决定用哪个图。 */
  function buildTemplateMenu() {
    const mt = document.getElementById('menu-template');
    if (!mt) return;
    mt.style.minWidth = '318px';

    const mainPanel = () => {
      mt.innerHTML = '<div class="menu-label">从哪儿开始</div>';
      /* 空白放在最前：想不清要做什么的人，最差也能拿到一张白纸，
         而不是被迫先读懂八个图型名。 */
      const blank = U.el('button', 'menu-item act-item',
        '<span class="act-name">就一张白纸</span><span class="mi-sub">新建 · 从中心那格开始写</span>');
      blank.onclick = async () => {
        closeMenus();
        await Store.newDoc('blank');
        Renderer.render(); Renderer.fit(true);
        toast('已新建一张空白导图');
      };
      mt.appendChild(blank);
      mt.appendChild(U.el('div', 'menu-sep'));
      Object.entries(THINKING_MAPS).forEach(([k, m]) => {
        const b = U.el('button', 'menu-item act-item',
          `<span class="act-name">${m.ask}</span><span class="mi-sub">${m.name} · ${m.desc}</span>`);
        b.dataset.key = k;
        b.title = m.tip;
        b.onclick = () => {
          Store.loadMap(k);
          closeMenus();
          toast('已套用「' + m.name + '」· ' + m.tip);
        };
        mt.appendChild(b);
      });
      mt.appendChild(U.el('div', 'menu-sep'));
      const more = U.el('button', 'menu-item back-item',
        '<span>直接选图型 / 课堂模板</span><span class="mi-sub">给已经熟悉的人</span>');
      more.onclick = e => { e.stopPropagation(); detailPanel(); };
      mt.appendChild(more);
    };

    const detailPanel = () => {
      mt.innerHTML = '';
      const back = U.el('button', 'menu-item back-item', '<span>← 回到「要做哪件事」</span>');
      back.onclick = e => { e.stopPropagation(); mainPanel(); };
      mt.appendChild(back);
      mt.appendChild(U.el('div', 'menu-sep'));
      mt.appendChild(U.el('div', 'menu-label', '思维图型'));
      Object.entries(THINKING_MAPS).forEach(([k, m]) => {
        const b = U.el('button', 'menu-item map-item',
          `<span class="mi-act">${m.action}</span><span>${m.name}</span><span class="mi-sub">${m.desc}</span>`);
        b.dataset.key = k;
        b.title = m.tip;
        b.onclick = () => {
          Store.loadMap(k);
          closeMenus();
          toast('已套用「' + m.name + '」· ' + m.tip);
        };
        mt.appendChild(b);
      });
      mt.appendChild(U.el('div', 'menu-sep'));
      mt.appendChild(U.el('div', 'menu-label', '课堂模板'));
      Object.entries(TEMPLATES).forEach(([k, t]) => {
        const b = U.el('button', 'menu-item',
          `<span class="mi-ico">${k === 'blank' ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3.5" y="4.5" width="17" height="15" rx="2.5" stroke-dasharray="3 3"/></svg>' : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="6" cy="12" r="2.2"/><circle cx="18" cy="6.6" r="2"/><circle cx="18" cy="17.4" r="2"/><path d="M8.2 12h4.4a2 2 0 0 0 2-2V8.6h1.4M12.6 12a2 2 0 0 1 2 2v1.4h1.4"/></svg>'}</span>
           <span>${t.name}</span><span class="mi-sub">${t.desc}</span>`);
        b.onclick = () => { Store.loadTemplate(k); closeMenus(); toast('已套用「' + t.name + '」模板'); };
        mt.appendChild(b);
      });
    };

    mainPanel();
  }

  function buildMenus() {
    buildTemplateMenu();

    // 版式
    const ml = document.getElementById('menu-layout');
    ml.style.minWidth = '290px';
    ml.innerHTML = '<div class="menu-label">节点怎么排</div>';
    LAYOUTS.forEach(l => {
      const b = U.el('button', 'menu-item',
        `<span class="mi-ico">${l.icon}</span><span>${l.name}</span><span class="mi-sub">${l.desc}</span>`);
      b.dataset.key = l.key;
      b.onclick = () => { Store.setLayout(l.key); closeMenus(); };
      ml.appendChild(b);
    });

    // 配色（连线样式也在这里——它和配色一样是「看起来怎么样」的事）
    const mth = document.getElementById('menu-theme');
    mth.style.minWidth = '224px';
    mth.innerHTML = '<div class="menu-label">配色与连线</div>';
    Object.entries(THEMES).forEach(([k, t]) => {
      const b = U.el('button', 'menu-item theme-item',
        `<span class="t-dot" style="background:${t.levels[0].bg}"></span>
         <span>${t.name}</span>
         <span class="t-chips">
           <i style="background:${t.levels[1].bg};border-color:${t.levels[1].border}"></i>
           <i style="background:${t.levels[2].bg};border-color:${t.levels[2].border}"></i>
         </span>${CHECK}`);
      b.dataset.key = k;
      b.onclick = () => { Store.setTheme(k); closeMenus(); };
      mth.appendChild(b);
    });
    mth.appendChild(U.el('div', 'menu-sep'));
    const lineRow = U.el('button', 'menu-item line-item',
      '<span>连线</span><span class="mi-sub" id="lineSub">曲线</span>' +
      '<span class="line-prev" aria-hidden="true">' +
      '<svg viewBox="0 0 34 12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">' +
      '<path id="linePrevPath" d="M2 9c6 0 6-6 12-6s6 6 12 6"/></svg></span>');
    lineRow.id = 'btnLine';
    mth.appendChild(lineRow);

    // 导出
    const me = document.getElementById('menu-export');
    me.innerHTML = '<div class="menu-label">导出什么</div>';
    const mkItem = (label, sub, fn) => {
      const b = U.el('button', 'menu-item', `<span>${label}</span><span class="mi-sub">${sub}</span>`);
      b.onclick = () => { closeMenus(); fn(); };
      me.appendChild(b);
      return b;
    };
    mkItem('图片 PNG', '适合放进课件', () => Exporter.exportPNG());
    mkItem('留白学案 PNG', '文字留空，可打印', () => Exporter.exportWorksheet());
    mkItem('备份文件 JSON', '以后还能导入回来', () => Exporter.exportJSON());
    me.appendChild(U.el('div', 'menu-sep'));
    mkItem('打印留白学案', '学生填空 · A4 横版', () => Exporter.printSheet('blank'));
    mkItem('打印完整导图', '带文字 · 教师版', () => Exporter.printSheet('full'));

    document.querySelectorAll('[data-menu]').forEach(btn => {
      btn.setAttribute('aria-expanded', 'false');
      btn.setAttribute('aria-haspopup', 'true');
      btn.addEventListener('click', e => {
        e.stopPropagation();
        toggleMenu('menu-' + btn.dataset.menu, btn);
      });
    });
    document.addEventListener('click', e => {
      if (!e.target.closest('.menu') && !e.target.closest('[data-menu]')) closeMenus();
    });

    fileInput.accept = Importer.ACCEPT;
    fileInput.addEventListener('change', () => {
      if (fileInput.files && fileInput.files[0]) importFile(fileInput.files[0]);
      fileInput.value = '';
    });
  }

  /* ══════════ 导入 ══════════ */
  async function importFile(file) {
    if (!file) return;
    if (file.size > 20 * 1024 * 1024) {
      toast('文件超过 20MB，不像是思维导图');
      return;
    }
    try {
      const r = await Importer.fromFile(file);
      const doc = Object.assign({}, r.doc, {
        /* 导入只搬结构和文字：别人的主题、线型、投影状态一律不带过来 */
        theme: r.doc.theme || Store.theme,
        lineStyle: r.doc.lineStyle || Store.lineStyle,
        layout: r.doc.layout || Store.layout,
      });
      if (!Store.setDoc(doc)) {
        toast('导入失败：文件结构不正确');
        return;
      }
      let extra = '';
      if (r.warnings.length) {
        extra = ' · ' + r.warnings.slice(0, 2).join('；');
        if (extra.length > 80) extra = extra.slice(0, 78) + '…';
      }
      toast('已导入「' + r.label + '」· ' + r.nodes + ' 个节点' + extra);
      announce('已导入 ' + r.label + ' 文件，' + r.nodes + ' 个节点');
    } catch (e) {
      toast('导入失败：' + ((e && e.message) || '无法识别这个文件'));
    }
  }

  /* 把文件拖到画布上也能导入——老师手里拿到 .xmind 时最顺手的动作 */
  function bindFileDrop() {
    const stage = document.getElementById('stage');
    let depth = 0;
    const hasFiles = e => !!(e.dataTransfer && Array.from(e.dataTransfer.types || []).indexOf('Files') >= 0);
    stage.addEventListener('dragenter', e => {
      if (!hasFiles(e)) return;
      e.preventDefault(); depth++; stage.classList.add('file-drop');
    });
    stage.addEventListener('dragover', e => {
      if (!hasFiles(e)) return;
      e.preventDefault(); e.dataTransfer.dropEffect = 'copy';
    });
    stage.addEventListener('dragleave', e => {
      if (!hasFiles(e)) return;
      depth = Math.max(0, depth - 1);
      if (!depth) stage.classList.remove('file-drop');
    });
    stage.addEventListener('drop', e => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth = 0;
      stage.classList.remove('file-drop');
      if (e.dataTransfer.files && e.dataTransfer.files[0]) importFile(e.dataTransfer.files[0]);
    });
  }

  function syncLayoutMenu() {
    document.querySelectorAll('#menu-layout .menu-item').forEach(b => {
      b.classList.toggle('active', b.dataset.key === Store.layout);
    });
  }
  function syncThemeMenu() {
    document.querySelectorAll('#menu-theme .theme-item').forEach(b => {
      b.classList.toggle('active', b.dataset.key === Store.theme);
    });
  }

  /* ══════════ 最近文档 ══════════ */
  function fmtTime(ts) {
    if (!ts) return '';
    const d = new Date(ts), now = new Date();
    const diff = Date.now() - ts;
    if (diff < 60e3) return '刚刚';
    if (diff < 3600e3) return Math.floor(diff / 60e3) + ' 分钟前';
    const hm = String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
    if (d.toDateString() === now.toDateString()) return '今天 ' + hm;
    if (d.getFullYear() === now.getFullYear()) return (d.getMonth() + 1) + '月' + d.getDate() + '日 ' + hm;
    return d.getFullYear() + '/' + (d.getMonth() + 1) + '/' + d.getDate();
  }

  async function buildDocMenu() {
    const m = document.getElementById('menu-doc');
    if (!m) return;
    m.style.minWidth = '286px';
    m.innerHTML = '<div class="menu-label">最近打开</div>';

    let list = [];
    try { list = await Store.listDocs(); } catch (e) { list = []; }
    // 当前文档可能尚未落盘，补一条占位
    if (!list.some(d => d.id === Store.docId)) {
      list.unshift({ id: Store.docId, title: Store.title, updatedAt: Date.now(), count: Store.count() });
    }

    const box = U.el('div', 'doc-list');
    list.forEach(d => {
      const active = d.id === Store.docId;
      const b = U.el('button', 'menu-item doc-item' + (active ? ' active' : ''),
        `<span class="di-row"><span class="di-title">${esc(d.title || '未命名')}</span>${active ? '<span class="di-badge">当前</span>' : ''}</span>
         <span class="di-meta">${d.count} 个节点 · ${fmtTime(d.updatedAt)}</span>`);
      b.onclick = async () => {
        closeMenus();
        if (active) return;
        const ok = await Store.openDoc(d.id);
        if (ok) {
          Renderer.render();
          Renderer.fit(true);
          toast('已打开「' + (d.title || '未命名') + '」');
          announce('已打开文档 ' + (d.title || '未命名'));
        } else {
          toast('这个文档读不出来');
        }
      };
      box.appendChild(b);
    });
    m.appendChild(box);
    m.appendChild(U.el('div', 'menu-sep'));

    const add = (label, sub, fn) => {
      const b = U.el('button', 'menu-item', `<span>${label}</span><span class="mi-sub">${sub}</span>`);
      b.onclick = () => { closeMenus(); fn(); };
      m.appendChild(b);
    };
    add('导入文件', 'XMind · FreeMind · OPML · 脑图 · Markdown', () => {
      const fi = document.getElementById('fileInput');
      if (fi) fi.click();
    });
    add('复制自测链接', '发给学生（需学生能访问这个地址）', () => {
      if (typeof Practice !== 'undefined') Practice.copyLink();
    });
    add('复制这份', '保留内容，另存一份', async () => {
      await Store.duplicateDoc();
      Renderer.render(); Renderer.fit(true);
      toast('已复制为新文档');
    });
    add('删除这份', '删除后无法恢复', async () => {
      if (!confirm('确定删除「' + Store.title + '」吗？删除后无法恢复。')) return;
      await Store.deleteDoc(Store.docId);
      Renderer.render(); Renderer.fit(true);
      toast('文档已删除');
    });
  }

  /* ══════════ 评估（结构成熟度） ══════════ */
  /* ══════════ 结构分历史曲线 ══════════
     一个老师真正想知道的是「这周比上周有没有变复杂」，不是「今天几分」。
     所以曲线只画同一条文档自己的历史，不做横向排名。 */
  function sparkline(list) {
    const W = 360, H = 86, PT = 12, PB = 18, PL = 4, PR = 4;
    /* 曲线跟主指标走：主指标是成熟度，曲线也画成熟度。
       旧记录里没有 maturity 字段，退回 score，不让老数据把线打断。 */
    const mv = d => (d.maturity != null ? d.maturity : d.score);
    const vals = list.map(mv);
    const mn = Math.min.apply(null, vals), mx = Math.max.apply(null, vals);
    const flat = mx === mn;
    const span = flat ? 1 : mx - mn;
    const iw = W - PL - PR, ih = H - PT - PB;
    const px = i => PL + (list.length === 1 ? iw / 2 : iw * i / (list.length - 1));
    const py = v => flat ? PT + ih / 2 : PT + ih * (1 - (v - mn) / span);
    const pts = list.map((d, i) => [+px(i).toFixed(1), +py(mv(d)).toFixed(1)]);
    const line = 'M' + pts.map(p => p[0] + ' ' + p[1]).join(' L');
    const base = H - PB;
    const area = 'M' + pts[0][0] + ' ' + base + ' L' +
      pts.map(p => p[0] + ' ' + p[1]).join(' L') + ' L' + pts[pts.length - 1][0] + ' ' + base + ' Z';
    const dots = pts.map((p, i) =>
      `<circle class="sp-dot${i === pts.length - 1 ? ' last' : ''}" cx="${p[0]}" cy="${p[1]}" r="${i === pts.length - 1 ? 3.4 : 2.6}"/>`
    ).join('');
    const first = mv(list[0]), last = mv(list[list.length - 1]);
    return `<svg class="sc-spark" viewBox="0 0 ${W} ${H}" role="img"
      aria-label="成熟度变化：共 ${list.length} 次记录，从 ${first}% 到 ${last}%">
      <path class="sp-area" d="${area}"/>
      <path class="sp-line" d="${line}"/>
      <line class="sp-axis" x1="${PL}" y1="${base}" x2="${W - PR}" y2="${base}"/>
      ${dots}
      <text class="sp-lbl" x="${pts[0][0]}" y="${H - 4}" text-anchor="start">${first}%</text>
      <text class="sp-lbl" x="${pts[pts.length - 1][0]}" y="${H - 4}" text-anchor="end">${last}%</text>
    </svg>`;
  }

  function scoreHistoryHtml(list) {
    if (!list || !list.length) return '';
    if (list.length === 1) {
      return `<div class="sc-hist">
        <div class="sc-hist-head"><b>成熟度变化</b><span>第 1 次记录</span></div>
        <p class="sc-hist-empty">改动结构后再看一次评估，这里会出现变化曲线。只和你自己的上一次比。</p>
      </div>`;
    }
    const mv = d => (d.maturity != null ? d.maturity : d.score);
    const first = list[0], last = list[list.length - 1];
    const d = Math.round((mv(last) - mv(first)) * 10) / 10;
    const cls = d > 0 ? 'up' : d < 0 ? 'down' : 'flat';
    const sign = d > 0 ? '+' : (d < 0 ? '−' : '±');
    const days = Math.round((last.at - first.at) / 864e5);
    const span = days <= 0 ? '同一天' : days === 1 ? '1 天内' : days + ' 天内';
    return `<div class="sc-hist">
      <div class="sc-hist-head">
        <b>成熟度变化</b>
        <span>${list.length} 次记录 · ${span}</span>
        <span class="sc-delta ${cls}">${sign}${Math.abs(d)}</span>
      </div>
      ${sparkline(list)}
    </div>`;
  }

  /* 一句话结论：先用人话说清楚「这张图现在缺什么」。
     专业词（命题 / 交叉连接）留到展开里再说——首屏读到 3.4 个术语/百字，
     等于每两句话就要停下来查一次。 */
  function leadSentence(r) {
    const branches = Store.root.children.length;
    if (r.total <= 2) return '还只有中心那一个词。先加两三个分支，才谈得上结构。';
    if (branches === 1) return '只有一条主线，这更像一份提纲。把其中一个分支拆成两个，骨架就出来了。';
    if (r.cross === 0) {
      return '有骨架，但分支之间还没连起来。补一两条跨分支的关系，比再加十个叶子有用。';
    }
    if (r.maturity >= 80) return '骨架、层级、关系都在，可以拿去讲给别人听了。';
    if (r.maxDepth < 2) return '分了两层，但还没往下走。挑一个分支再问一句「为什么」，深度就有了。';
    return '骨架有了，细节也够。下一步是把「所以呢」写出来——它和谁有关系。';
  }

  function openScore() {
    const r = Scorer.analyze();
    const grade = r.maturity >= 80 ? '结构成熟'
      : r.maturity >= 60 ? '基本成型'
      : r.maturity >= 40 ? '还比较单薄' : '刚起步';

    const bars = r.dims.map(d =>
      `<div class="sc-dim">
         <span class="sc-k">${d.key}</span>
         <span class="sc-track"><i style="width:${d.v}%"></i></span>
         <span class="sc-v">${esc(d.hint)}</span>
       </div>`).join('');

    const tips = r.tips.slice(0, 3).map(t => `<li><b>${t.k}</b>${esc(t.t)}</li>`).join('');

    /* 先记一笔再画：结构没变时 pushScore 只更新时间，不会多一个点 */
    const hist = Store.pushScore({
      at: Date.now(), score: r.score, maturity: r.maturity, prop: r.prop,
      depth: r.maxDepth + 1, cross: r.cross, leaves: r.leaves, nodes: r.total,
    });

    /* 分层：首屏只给「结论 + 成熟度」，六个维度、算法说明、历史曲线全部折起来。
       想深究的人点开，只想知道「我现在该改哪儿」的人看完第一屏就能走。 */
    document.getElementById('scoreBody').innerHTML =
      `<div class="sc-top">
         <div class="sc-score"><b>${r.maturity}<i>%</i></b><span>结构成熟度</span></div>
         <div class="sc-grade"><b>${grade}</b><span>Novak 结构分 ${r.score}</span></div>
       </div>
       <p class="sc-lead">${esc(leadSentence(r))}</p>
       <div class="sc-nums">
         <span><b>${r.total}</b>节点</span><span><b>${r.prop}</b>关系</span>
         <span><b>${r.maxDepth + 1}</b>层</span><span><b>${r.cross}</b>跨分支</span>
         <span><b>${r.leaves}</b>例子</span>
       </div>

       <details class="sc-more">
         <summary>六个维度分别是什么意思</summary>
         <div class="sc-dims">${bars}</div>
         <p class="sc-note"><b>关系</b>（教材里叫「命题」）＝上下两级之间写得出的关系，也就是树枝上的每一条边；<b>跨分支</b>（教材里叫「交叉连接」）＝从一个分支连到另一个分支的关系，它最能说明你真的想通了，而不只是抄了一份提纲。这两个词在界面上只有这两种写法——维度条、上面的数字行、帮助里的说明，指的都是同一件事。<br><b>成熟度</b>是六个维度归一化后的平均，和自己的上一次比才有意义——<b>Novak 结构分</b>会随节点数自然增长，写得多不等于想清楚（例子超过 8 个后，每多一个只加 0.25 分）。</p>
       </details>

       <details class="sc-more">
         <summary>这一句结论是怎么得出来的</summary>
         <ul class="sc-tips">${tips}</ul>
       </details>

       <details class="sc-more">
         <summary>成熟度变化</summary>
         ${scoreHistoryHtml(hist)}
       </details>`;

    document.getElementById('scoreMask').classList.add('show');
    setTimeout(() => { const b = document.getElementById('scoreClose'); if (b) b.focus(); }, 30);
    announce('这张图怎么样：成熟度 ' + r.maturity + '%，' + grade);
  }

  let scoreReturnFocus = null;
  function openScoreAndRemember() {
    scoreReturnFocus = document.activeElement;
    openScore();
  }

  function closeScore() {
    document.getElementById('scoreMask').classList.remove('show');
    if (scoreReturnFocus && document.contains(scoreReturnFocus)) scoreReturnFocus.focus();
    scoreReturnFocus = null;
  }

  /* ══════════ 投影模式 ══════════ */
  function toggleProjector() {
    Store.toggleProjector();
    Renderer.render();
    Renderer.fit(true);
    toast(Store.projector ? '投影模式：字号已放大，一屏一个知识点' : '已退出投影模式');
  }

  /* ══════════ 挖空练习 ══════════ */
  function blankIds() {
    const res = Renderer.result;
    if (!res) return [];
    const ids = res.nodes.filter(r => r.depth > 0).map(r => r.id);
    if (!blankSeq.length) return ids;
    /* 按 blankSeq 排；新加的节点（不在 seq 里）接在后面，不然会永远轮不到 */
    const live = new Set(ids);
    const out = blankSeq.filter(id => live.has(id));
    const seen = new Set(out);
    ids.forEach(id => { if (!seen.has(id)) out.push(id); });
    return out;
  }

  function syncBlankBar() {
    const ids = blankIds();
    const total = ids.length;
    let done = 0;
    for (const id of ids) if (Store.revealed.has(id)) done++;
    const c = document.getElementById('bbCount');
    const b = document.getElementById('bbBar');
    if (c) c.textContent = `${done} / ${total}`;
    if (b) b.style.width = (total ? (done / total) * 100 : 0) + '%';
  }

  function setBlank(on) {
    if (editing) commitEdit();
    blankSeq = [];                       // 每次进入都从 DFS 顺序开始
    Store.toggleBlank(on);
    document.body.classList.toggle('blanking', Store.blank);
    syncBlankBar();
    if (Store.blank && Store.projector) Renderer.fit(true);
    /* 进入挖空后，焦点交给「下一个」按钮：老师接着按空格就是揭示下一个，
       而不是又激活一次顶栏的挖空按钮（那样会立刻退出挖空）。 */
    setTimeout(() => {
      const b = document.getElementById(Store.blank ? 'bbNext' : 'btnBlank');
      if (b && b.offsetParent !== null) b.focus();
    }, 30);
  }

  /* 重来：清空已揭示，并换一个顺序。
     原来只有"退出再进"这一条路，而顺序是固定的——学生第二次练等于在背位置。 */
  function restartBlank() {
    const res = Renderer.result;
    const recs = res ? res.nodes.filter(r => r.depth > 0) : [];
    /* 同层内打乱，层与层之间仍由浅到深。
       全部打乱会让第一次就跳出某个「要点 3」——学生先看到零散细节，
       骨架反而在后面，跟"先粗后细"的回忆顺序相反。 */
    const groups = new Map();
    recs.forEach(r => {
      if (!groups.has(r.depth)) groups.set(r.depth, []);
      groups.get(r.depth).push(r.id);
    });
    const seq = [];
    [...groups.keys()].sort((a, b) => a - b).forEach(d => {
      const g = groups.get(d);
      for (let i = g.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        const t = g[i]; g[i] = g[j]; g[j] = t;
      }
      seq.push.apply(seq, g);
    });
    blankSeq = seq;
    Store.clearRevealed();
    syncBlankBar();
    if (Store.projector) Renderer.fit(true);
    toast('已清空，顺序也打乱了');
    announce('已重新开始，顺序已打乱');
  }

  function nextBlank() {
    const ids = blankIds();
    const next = ids.find(id => !Store.revealed.has(id));
    if (!next) { toast('已经全部揭示完了'); return; }
    Store.reveal(next);
    syncBlankBar();
    if (Store.projector) Renderer.focusOn(next, 1, true);
  }

  function prevBlank() {
    const shown = blankIds().filter(id => Store.revealed.has(id));
    if (!shown.length) return;
    Store.unreveal(shown[shown.length - 1]);
    syncBlankBar();
  }

  function revealAllBlank() {
    Store.revealAll(blankIds());
    syncBlankBar();
  }

  function bindModes() {
    /* 放映菜单里的两项：点完就把菜单收起来，否则投影态下菜单还浮在画面上 */
    document.getElementById('btnProjector').onclick = () => { toggleProjector(); closeMenus(); };
    document.getElementById('btnBlank').onclick = () => setBlank(!Store.blank);
    document.getElementById('bbNext').onclick = nextBlank;
    document.getElementById('bbPrev').onclick = prevBlank;
    document.getElementById('bbAll').onclick = revealAllBlank;
    document.getElementById('bbAgain').onclick = restartBlank;
    document.getElementById('bbExit').onclick = () => setBlank(false);

    document.getElementById('phSwitch').onclick = () => {
      Store.setTheme('mono');
      toast('已换成「墨白」：投影下比暗色主题清楚');
    };
    document.getElementById('phClose').onclick = () => {
      projHintOff = true;
      syncProjHint();
    };
  }

  /* ══════════ 演示模式 ══════════ */
  function dfsOrder(root) {
    const out = [];
    (function w(n) {
      for (const c of n.children) { out.push(c.id); w(c); }
    })(root);
    return out;
  }

  function revealSet() {
    const set = new Set([Store.root.id]);
    for (let i = 0; i < reveal; i++) set.add(order[i]);
    return set;
  }

  function visibleRecs() {
    const set = revealSet();
    const res = Renderer.result;
    return res ? res.nodes.filter(n => set.has(n.id)) : [];
  }

  function enterPresent() {
    if (editing) commitEdit();
    presenting = true;
    document.body.classList.add('presenting');
    presentBar.classList.add('show');
    order = dfsOrder(Store.root);
    reveal = 0;
    Renderer.setReveal(revealSet());
    Renderer.render();
    Renderer.fitRecs(visibleRecs(), true);
    syncPresent();
    /* 焦点交给「下一个」按钮：空格继续演示，而不是落回刚被收起的菜单 */
    setTimeout(() => { const b = document.getElementById('pbNext'); if (b) b.focus(); }, 40);
    try { document.documentElement.requestFullscreen && document.documentElement.requestFullscreen(); } catch (e) {}
  }

  function exitPresent() {
    presenting = false;
    document.body.classList.remove('presenting');
    presentBar.classList.remove('show');
    Renderer.setReveal(null);
    Renderer.render();
    Renderer.fit();
    if (document.fullscreenElement) { try { document.exitFullscreen(); } catch (e) {} }
    const b = document.querySelector('[data-menu="show"]');
    if (b) b.focus();
  }

  function applyReveal() {
    Renderer.setReveal(revealSet());
    Renderer.render();
    Renderer.fitRecs(visibleRecs(), true);
    syncPresent();
  }

  function nextReveal() {
    if (reveal >= order.length) { toast('已经是最后一个知识点了'); return; }
    reveal++;
    applyReveal();
  }

  function prevReveal() {
    if (reveal <= 0) return;
    reveal--;
    applyReveal();
  }

  function syncPresent() {
    document.getElementById('pbCount').textContent = `${reveal} / ${order.length}`;
    document.getElementById('pbBar').style.width = (order.length ? (reveal / order.length) * 100 : 0) + '%';
  }

  function bindPresent() {
    document.getElementById('btnPresent').onclick = () => { closeMenus(); enterPresent(); };
    document.getElementById('pbNext').onclick = nextReveal;
    document.getElementById('pbPrev').onclick = prevReveal;
    document.getElementById('pbExit').onclick = exitPresent;
    document.getElementById('pbAll').onclick = () => { reveal = order.length; applyReveal(); };
    document.addEventListener('fullscreenchange', () => {
      if (!document.fullscreenElement && presenting) {
        // 用户按 Esc 退出全屏时一并退出演示
        setTimeout(() => { if (!document.fullscreenElement && presenting) exitPresent(); }, 60);
      }
    });
  }

  /* ══════════ 同步界面 ══════════ */
  function syncDock() {
    const has = !!Store.selectedId;
    dock.querySelectorAll('[data-act]').forEach(b => {
      const a = b.dataset.act;
      if (a === 'undo') b.disabled = !Store.canUndo;
      else if (a === 'redo') b.disabled = !Store.canRedo;
      else if (a === 'link') b.disabled = !has;
      else if (a === 'delete') b.disabled = !has || Store.selectedId === Store.root.id;
    });
    const lb = dock.querySelector('[data-act="link"]');
    if (lb) lb.classList.toggle('on', linkMode);
  }

  function syncUI() {
    if (document.activeElement !== docTitle) docTitle.textContent = Store.title;
    syncDock();
    syncLayoutMenu();
    syncThemeMenu();
    const lineBtn = document.getElementById('btnLine');
    if (lineBtn) {
      const elbow = Store.lineStyle === 'elbow';
      lineBtn.setAttribute('aria-pressed', elbow ? 'true' : 'false');
      lineBtn.classList.toggle('active', elbow);
      const sub = document.getElementById('lineSub');
      if (sub) sub.textContent = elbow ? '折线' : '曲线';
      const path = document.getElementById('linePrevPath');
      if (path) path.setAttribute('d', elbow ? 'M2 9h11V3h13' : 'M2 9c6 0 6-6 12-6s6 6 12 6');
      lineBtn.title = elbow ? '现在是折线，点一下换成曲线' : '现在是曲线，点一下换成折线';
    }

    const bp = document.getElementById('btnProjector');
    const bb = document.getElementById('btnBlank');
    if (bp) { bp.classList.toggle('active', !!Store.projector); bp.setAttribute('aria-pressed', Store.projector ? 'true' : 'false'); }
    if (bb) { bb.classList.toggle('active', !!Store.blank); bb.setAttribute('aria-pressed', Store.blank ? 'true' : 'false'); }
    const bar = document.getElementById('blankBar');
    if (bar) bar.classList.toggle('show', !!Store.blank);
    document.body.classList.toggle('blanking', !!Store.blank);
    syncBlankBar();
    syncProjHint();
    syncOnboard();
  }

  /* ══════════ 空文档引导 ══════════
     只在「真的是一张白纸」时出现。有内容、投影、演示、挖空、练习模式下一律不打扰。 */
  const ONBOARD_KEY = 'mapmind.onboarded';
  function syncOnboard() {
    const el = document.getElementById('onboard');
    if (!el) return;
    let seen = false;
    try { seen = localStorage.getItem(ONBOARD_KEY) === '1'; } catch (e) { /* 隐私模式下会抛，当作没看过 */ }
    const quiet = !presenting && !Store.projector && !Store.blank
      && !document.body.classList.contains('practicing');
    el.hidden = !(Store.count() <= 1 && !seen && quiet);
  }

  function bindOnboard() {
    const ok = document.getElementById('obOk');
    const tpl = document.getElementById('obTemplate');
    if (ok) ok.onclick = () => {
      try { localStorage.setItem(ONBOARD_KEY, '1'); } catch (e) { /* 存不下就算了，本次会话内仍会隐藏 */ }
      document.getElementById('onboard').hidden = true;
    };
    if (tpl) tpl.onclick = e => {
      /* 不 stopPropagation 的话，这次点击会冒泡到 document 上的「点菜单外部就关菜单」，
         刚打开的模板菜单立刻被关掉。Flow 的模板步骤踩过同一个坑。 */
      e.stopPropagation();
      document.getElementById('onboard').hidden = true;
      try { localStorage.setItem(ONBOARD_KEY, '1'); } catch (e2) {}
      const b = document.querySelector('[data-menu="template"]');
      if (b) b.click();
    };
  }

  /* ══════════ 投影 + 暗色主题提示 ══════════
     投影仪投不出真正的黑色：暗底会被环境光洗成灰，整体对比度一起塌。
     这是物理限制，代码没法绕过，只能在老师踩进去的时候提醒一次。 */
  let projHintOff = false;
  function syncProjHint() {
    const el = document.getElementById('projHint');
    if (!el) return;
    const dark = document.body.classList.contains('theme-dark');
    el.hidden = !(Store.projector && dark && !projHintOff);
  }

  function bindTop() {
    docTitle.addEventListener('input', () => {
      Store.setTitle(docTitle.textContent.replace(/\n/g, ' ').slice(0, 40));
      document.title = (Store.title || '思维导图') + ' · 知识梳理';
    });
    docTitle.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); docTitle.blur(); }
    });
    docTitle.addEventListener('blur', () => { docTitle.textContent = Store.title; });

    document.getElementById('btnLine').onclick = () => Store.toggleLineStyle();

    /* 帮助弹窗：打开时把焦点送进去，关闭时送回原来的按钮。
       只加 role="dialog" 不够——焦点留在背后，键盘用户会 Tab 到背景里。 */
    document.getElementById('helpTab1').onclick = () => helpTab(1);
    document.getElementById('helpTab2').onclick = () => helpTab(2);
    document.getElementById('btnHelp').onclick = openHelp;
    document.getElementById('helpClose').onclick = closeHelp;
    document.getElementById('helpMask').addEventListener('click', e => {
      if (e.target === e.currentTarget) closeHelp();
    });

    const scoreMask = document.getElementById('scoreMask');
    document.getElementById('btnScore').onclick = openScoreAndRemember;
    document.getElementById('scoreClose').onclick = closeScore;
    scoreMask.addEventListener('click', e => { if (e.target === scoreMask) closeScore(); });

    document.addEventListener('doc-saved', () => {
      saveState.classList.add('show');
      saveState.textContent = '已保存';
      clearTimeout(saveState._t);
      saveState._t = setTimeout(() => saveState.classList.remove('show'), 1200);
    });

    window.addEventListener('resize', () => {
      if (presenting) Renderer.fit();
    });

    /* 自动保存有 450ms 防抖。写完一个节点立刻合盖 / 关标签页，
       定时器还没烧到，内容就丢了。pagehide 里同步写 localStorage，
       IDB 事务来不及也没关系——启动时会比较时间戳，用更新的那份。 */
    window.addEventListener('pagehide', () => Store.save());
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') Store.save();
    });
  }

  /* ══════════ 启动 ══════════ */
  async function init() {
    const source = await Store.init();
    buildMenus();
    bindStage();
    bindKeyboard();
    bindTop();
    bindPresent();
    bindModes();
    bindOnboard();
    bindRel();
    bindFileDrop();
    if (typeof Pacer !== 'undefined') Pacer.init();
    if (typeof Flow !== 'undefined') {
      Flow.init({
        onTemplate: () => document.querySelector('[data-menu="template"]').click(),
        onScore: openScoreAndRemember,
        onBlank: () => setBlank(!Store.blank),
        onExport: () => Exporter.exportWorksheet(),
        onAnnounce: announce,
        onToast: toast,
      });
      document.getElementById('btnFlow').onclick = () => (Flow.active ? Flow.stop() : Flow.start());
    }
    if (typeof Practice !== 'undefined') {
      Practice.init({ onToast: toast, onAnnounce: announce });
    }

    Store.on(type => {
      if (type === 'title') {
        if (document.activeElement !== docTitle) docTitle.textContent = Store.title;
        document.title = (Store.title || '思维导图') + ' · 知识梳理';
        return;
      }
      if (typeof Flow !== 'undefined') Flow.notify(type);
      if (type === 'load') { Store.selectedLinkId = null; setLinkMode(false); }
      Renderer.render();
      if (type === 'template' || type === 'map' || type === 'load') {
        Renderer.fit(true);
      } else if (Store.projector && type === 'layout') {
        Renderer.fit(true);
      }
      syncUI();
    });

    Renderer.render();
    syncUI();
    Renderer.fit();
    Store.save();      // 保证当前文档立刻出现在「最近文档」里

    if (source === 'prev' || source === 'localStorage') {
      setTimeout(() => toast('已从备份恢复上次的内容'), 700);
    }

    // 字体加载完成后重新测量一次，避免宽度偏差
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(() => { Renderer.render(); Renderer.fit(); });
    }

    window.App = App;
  }

  const App = {
    init, toast, select, startEdit, commitEdit, addChild, addSibling, deleteNode,
    enterPresent, exitPresent,
    get isEditing() { return !!editing; },
  };
  return App;
})();

document.addEventListener('DOMContentLoaded', () => App.init());
