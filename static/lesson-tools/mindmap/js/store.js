/* ============================================================
   store.js — 数据模型 / 命令式撤销 / IndexedDB 多文档持久化
   ============================================================ */
const Store = (() => {
  const LS_KEY = 'mapmind.doc.v2';   // 旧版 localStorage 键（用于迁移与兜底）
  const DB_NAME = 'mapmind';
  const SCHEMA = 3;
  const MAX_HISTORY = 120;

  const S = {
    docId: 'current',
    root: null,
    links: [],            // 关系边 [{id, from, to, label}]
    title: '思维导图',
    layout: 'logical',
    theme: 'paper',
    lineStyle: 'curve',
    projector: false,     // 投影模式
    blank: false,         // 挖空练习
    revealed: new Set(),  // 挖空已揭示的节点
    selectedId: null,
    selectedLinkId: null,
    _subs: [],
    _saveTimer: null,
    _transient: false,    // 练习链接载入的别人文档：只换内存，绝不落盘
  };

  const H = { past: [], future: [] };

  /* ══════════ IndexedDB ══════════ */
  const IDB = (() => {
    let dbp = null;
    function open() {
      if (dbp) return dbp;
      dbp = new Promise(resolve => {
        let req;
        try { req = indexedDB.open(DB_NAME, 1); }
        catch (e) { resolve(null); return; }
        req.onupgradeneeded = () => {
          const db = req.result;
          if (!db.objectStoreNames.contains('docs')) db.createObjectStore('docs', { keyPath: 'id' });
        };
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => resolve(null);
        req.onblocked = () => resolve(null);
      });
      return dbp;
    }
    async function get(id) {
      const db = await open();
      if (!db) return null;
      return new Promise(res => {
        try {
          const rq = db.transaction('docs', 'readonly').objectStore('docs').get(id);
          rq.onsuccess = () => res(rq.result || null);
          rq.onerror = () => res(null);
        } catch (e) { res(null); }
      });
    }
    async function all() {
      const db = await open();
      if (!db) return [];
      return new Promise(res => {
        try {
          const rq = db.transaction('docs', 'readonly').objectStore('docs').getAll();
          rq.onsuccess = () => res(rq.result || []);
          rq.onerror = () => res([]);
        } catch (e) { res([]); }
      });
    }
    async function put(obj) {
      const db = await open();
      if (!db) return false;
      return new Promise(res => {
        try {
          const tx = db.transaction('docs', 'readwrite');
          tx.objectStore('docs').put(obj);
          tx.oncomplete = () => res(true);
          tx.onerror = () => res(false);
          tx.onabort = () => res(false);
        } catch (e) { res(false); }
      });
    }
    async function del(id) {
      const db = await open();
      if (!db) return false;
      return new Promise(res => {
        try {
          const tx = db.transaction('docs', 'readwrite');
          tx.objectStore('docs').delete(id);
          tx.oncomplete = () => res(true);
          tx.onerror = () => res(false);
        } catch (e) { res(false); }
      });
    }
    return { get, all, put, del };
  })();

  /* ══════════ 基础 ══════════ */
  function normalize(node) {
    node.id = node.id || U.uid();
    node.text = node.text == null ? '' : String(node.text);
    node.collapsed = !!node.collapsed;
    node.children = (node.children || []).map(normalize);
    return node;
  }

  function walk(fn, node = S.root, depth = 0, parent = null) {
    if (!node) return;
    fn(node, depth, parent);
    for (const c of node.children) walk(fn, c, depth + 1, node);
  }

  function find(id, node = S.root) {
    if (!node) return null;
    if (node.id === id) return node;
    for (const c of node.children) {
      const r = find(id, c);
      if (r) return r;
    }
    return null;
  }

  function parentOf(id) {
    let res = null;
    walk((n, d, p) => { if (n.id === id) res = p; });
    return res;
  }

  function isDescendant(ancestorId, id) {
    const a = find(ancestorId);
    if (!a) return false;
    let hit = false;
    walk(n => { if (n.id === id) hit = true; }, a);
    return hit;
  }

  function count(node = S.root) {
    let n = 1;
    for (const c of node.children) n += count(c);
    return n;
  }

  /* ══════════ 订阅 ══════════ */
  function on(fn) { S._subs.push(fn); }
  function emit(type) { S._subs.forEach(fn => fn(type)); }

  /* ══════════ 命令式历史 ══════════ */
  function record(entry) {
    H.past.push(entry);
    if (H.past.length > MAX_HISTORY) H.past.shift();
    H.future.length = 0;
  }

  function undo() {
    const e = H.past.pop();
    if (!e) return false;
    e.undo();
    H.future.push(e);
    emit('undo'); scheduleSave();
    return true;
  }

  function redo() {
    const e = H.future.pop();
    if (!e) return false;
    e.redo();
    H.past.push(e);
    emit('redo'); scheduleSave();
    return true;
  }

  function clearHistory() { H.past.length = 0; H.future.length = 0; }

  /* ══════════ 结构操作 ══════════ */
  function addChild(parentId) {
    const p = find(parentId) || S.root;
    const node = normalize({ text: '' });
    const idx = p.children.length;
    const prevSel = S.selectedId;
    const prevCollapsed = p.collapsed;
    const apply = () => { p.children.splice(idx, 0, node); p.collapsed = false; S.selectedId = node.id; };
    const revert = () => {
      const i = p.children.indexOf(node);
      if (i >= 0) p.children.splice(i, 1);
      p.collapsed = prevCollapsed;
      S.selectedId = prevSel;
    };
    apply();
    record({ undo: revert, redo: apply });
    emit('add'); scheduleSave();
    return node;
  }

  function addSibling(id) {
    const node = find(id);
    if (!node || node === S.root) return addChild(id);
    const p = parentOf(id);
    const nn = normalize({ text: '' });
    const idx = p.children.indexOf(node) + 1;
    const prevSel = S.selectedId;
    const apply = () => { p.children.splice(idx, 0, nn); S.selectedId = nn.id; };
    const revert = () => {
      const i = p.children.indexOf(nn);
      if (i >= 0) p.children.splice(i, 1);
      S.selectedId = prevSel;
    };
    apply();
    record({ undo: revert, redo: apply });
    emit('add'); scheduleSave();
    return nn;
  }

  function remove(id) {
    const node = find(id);
    if (!node || node === S.root) return false;
    const p = parentOf(id);
    const idx = p.children.indexOf(node);
    const prevSel = S.selectedId;
    const dropped = S.links.filter(l => l.from === id || l.to === id);

    const apply = () => {
      const i = p.children.indexOf(node);
      if (i >= 0) p.children.splice(i, 1);
      S.links = S.links.filter(l => l.from !== id && l.to !== id);
      S.selectedId = p.id;
    };
    const revert = () => {
      p.children.splice(idx, 0, node);
      dropped.forEach(l => { if (!S.links.includes(l)) S.links.push(l); });
      S.selectedId = prevSel;
    };
    apply();
    record({ undo: revert, redo: apply });
    emit('remove'); scheduleSave();
    return true;
  }

  function setText(id, text) {
    const node = find(id);
    if (!node || node.text === text) return;
    const from = node.text;
    const apply = () => { node.text = text; };
    const revert = () => { node.text = from; };
    apply();
    record({ undo: revert, redo: apply });
    emit('text'); scheduleSave();
  }

  function toggleCollapse(id) {
    const node = find(id);
    if (!node || !node.children.length) return;
    const from = node.collapsed;
    const apply = () => { node.collapsed = !from; };
    const revert = () => { node.collapsed = from; };
    apply();
    record({ undo: revert, redo: apply });
    emit('collapse'); scheduleSave();
  }

  function setCollapsedAll(collapsed) {
    const prev = [];
    walk(n => { if (n.children.length) prev.push([n, n.collapsed]); });
    const apply = () => { walk((n, d) => { if (d > 0 && n.children.length) n.collapsed = collapsed; }); };
    const revert = () => prev.forEach(([n, v]) => { n.collapsed = v; });
    apply();
    record({ undo: revert, redo: apply });
    emit('collapse'); scheduleSave();
  }

  function moveTo(id, targetId) {
    if (id === targetId) return false;
    const node = find(id), target = find(targetId);
    if (!node || !target || node === S.root) return false;
    const fromP = parentOf(id);
    if (target === fromP) return false;
    if (isDescendant(id, targetId)) return false;
    const fromIdx = fromP.children.indexOf(node);
    const toIdx = target.children.length;
    const prevSel = S.selectedId;
    const apply = () => {
      const i = fromP.children.indexOf(node);
      if (i >= 0) fromP.children.splice(i, 1);
      target.children.splice(toIdx, 0, node);
      target.collapsed = false;
      S.selectedId = node.id;
    };
    const revert = () => {
      const i = target.children.indexOf(node);
      if (i >= 0) target.children.splice(i, 1);
      fromP.children.splice(fromIdx, 0, node);
      S.selectedId = prevSel;
    };
    apply();
    record({ undo: revert, redo: apply });
    emit('move'); scheduleSave();
    return true;
  }

  /* ══════════ 关系边（concept map 语义） ══════════ */
  function linkExists(from, to) {
    return S.links.some(l => (l.from === from && l.to === to) || (l.from === to && l.to === from));
  }

  function addLink(from, to, label) {
    if (!from || !to || from === to) return null;
    if (!find(from) || !find(to)) return null;
    if (linkExists(from, to)) return null;
    const link = { id: U.uid(), from, to, label: (label || '关联').slice(0, 8) };
    const apply = () => { if (!S.links.includes(link)) S.links.push(link); };
    const revert = () => { S.links = S.links.filter(l => l !== link); };
    apply();
    record({ undo: revert, redo: apply });
    emit('links'); scheduleSave();
    return link;
  }

  function removeLink(id) {
    const link = S.links.find(l => l.id === id);
    if (!link) return false;
    const idx = S.links.indexOf(link);
    const apply = () => { S.links = S.links.filter(l => l !== link); };
    const revert = () => { S.links.splice(idx, 0, link); };
    apply();
    record({ undo: revert, redo: apply });
    emit('links'); scheduleSave();
    return true;
  }

  function setLinkLabel(id, label) {
    const link = S.links.find(l => l.id === id);
    if (!link || !label) return;
    const from = link.label;
    const apply = () => { link.label = label.slice(0, 8); };
    const revert = () => { link.label = from; };
    apply();
    record({ undo: revert, redo: apply });
    emit('links'); scheduleSave();
  }

  /* ══════════ 视图状态 ══════════ */
  function setLayout(k) {
    if (S.layout === k) return;
    const from = S.layout;
    const apply = () => { S.layout = k; };
    const revert = () => { S.layout = from; };
    apply(); record({ undo: revert, redo: apply });
    emit('layout'); scheduleSave();
  }

  function setTheme(k) {
    if (S.theme === k) return;
    const from = S.theme;
    const apply = () => { S.theme = k; };
    const revert = () => { S.theme = from; };
    apply(); record({ undo: revert, redo: apply });
    emit('theme'); scheduleSave();
  }

  function toggleLineStyle() {
    const from = S.lineStyle;
    const to = from === 'curve' ? 'elbow' : 'curve';
    const apply = () => { S.lineStyle = to; };
    const revert = () => { S.lineStyle = from; };
    apply(); record({ undo: revert, redo: apply });
    emit('style'); scheduleSave();
  }

  function setTitle(t) { S.title = t; emit('title'); scheduleSave(); }

  function toggleProjector() {
    S.projector = !S.projector;
    emit('projector'); scheduleSave();
  }

  function toggleBlank(force) {
    S.blank = typeof force === 'boolean' ? force : !S.blank;
    S.revealed.clear();
    emit('blank'); scheduleSave();
  }

  function reveal(id) {
    if (!S.blank || S.revealed.has(id)) return false;
    S.revealed.add(id);
    emit('reveal');
    return true;
  }

  function revealAll(ids) {
    ids.forEach(id => S.revealed.add(id));
    emit('reveal');
  }

  function unreveal(id) {
    if (S.revealed.delete(id)) emit('reveal');
  }

  /* 原地清空（挖空"重来"用）。toggleBlank 也会清，但那是退出再进，
     中间会有一次遮罩消失又出现的跳变。 */
  function clearRevealed() {
    if (!S.revealed.size) return;
    S.revealed.clear();
    emit('reveal');
  }

  /* ══════════ 文档 ══════════ */
  function normalizeLinks(list) {
    if (!Array.isArray(list)) return [];
    const ids = new Set();
    walk(n => ids.add(n.id));
    return list
      .filter(l => l && ids.has(l.from) && ids.has(l.to) && l.from !== l.to)
      .map(l => ({ id: l.id || U.uid(), from: l.from, to: l.to, label: String(l.label || '关联') }));
  }

  function exportDoc() {
    return {
      root: JSON.parse(JSON.stringify(S.root)),
      links: JSON.parse(JSON.stringify(S.links)),
      title: S.title, layout: S.layout, theme: S.theme,
      lineStyle: S.lineStyle, projector: S.projector, blank: S.blank,
    };
  }

  function applyDoc(d) {
    S.root = normalize(JSON.parse(JSON.stringify(d.root)));
    S.links = normalizeLinks(JSON.parse(JSON.stringify(d.links || [])));
    S.title = d.title || '思维导图';
    S.layout = LAYOUTS.some(l => l.key === d.layout) ? d.layout : 'logical';
    S.theme = THEMES[d.theme] ? d.theme : 'paper';
    S.lineStyle = d.lineStyle === 'elbow' ? 'elbow' : 'curve';
    S.projector = !!d.projector;
    /* 挖空是课堂现场状态，不是文档内容。曾经把 blank:true 写进文档：
       老师讲完挖空直接合盖，第二天打开这张图，所有分支仍是遮住的。 */
    S.blank = false;
    S.revealed.clear();
    S.selectedId = S.root.id;
  }

  function loadTemplate(key) {
    const tpl = TEMPLATES[key] || TEMPLATES.summary;
    const prev = exportDoc();
    const next = {
      root: JSON.parse(JSON.stringify(tpl.tree)), links: [], title: tpl.name,
      layout: S.layout, theme: S.theme, lineStyle: S.lineStyle,
      projector: S.projector, blank: false,
    };
    const apply = () => applyDoc(next);
    const revert = () => applyDoc(prev);
    apply(); record({ undo: revert, redo: apply });
    emit('template'); scheduleSave();
  }

  /* 套用思维图型：同时切换结构与节点提示语 */
  function loadMap(key) {
    const m = THINKING_MAPS[key];
    if (!m) return false;
    const prev = exportDoc();
    const next = {
      root: JSON.parse(JSON.stringify(m.tree)), links: [], title: m.name,
      layout: m.layout, theme: S.theme, lineStyle: S.lineStyle,
      projector: S.projector, blank: false,
    };
    const apply = () => applyDoc(next);
    const revert = () => applyDoc(prev);
    apply(); record({ undo: revert, redo: apply });
    emit('map'); scheduleSave();
    return true;
  }

  /* opts.transient：只换内存里的内容，不落盘。
     练习链接是别人发来的，不该覆盖学生自己存着的文档。
     opts.noHistory：用于退出练习时换回学生自己的文档，不留下能撤销回练习图的入口。 */
  function setDoc(doc, opts) {
    if (!validDoc(doc)) return false;
    const transient = !!(opts && opts.transient);
    const prev = exportDoc();
    const next = {
      root: doc.root, links: doc.links || [], title: doc.title || '思维导图',
      layout: doc.layout, theme: doc.theme, lineStyle: doc.lineStyle,
      projector: doc.projector, blank: doc.blank,
    };
    const apply = () => applyDoc(next);
    const revert = () => applyDoc(prev);
    apply();
    S._transient = transient;
    if (!(opts && opts.noHistory)) record({ undo: revert, redo: apply });
    emit('load');
    if (!transient) scheduleSave();
    return true;
  }

  function toJSON() {
    return {
      app: 'mindmap', version: SCHEMA, id: S.docId,
      title: S.title, layout: S.layout, theme: S.theme, lineStyle: S.lineStyle,
      projector: S.projector, blank: false,
      root: JSON.parse(JSON.stringify(S.root)),
      links: JSON.parse(JSON.stringify(S.links)),
      savedAt: new Date().toISOString(),
    };
  }

  /* ══════════ 多文档 ══════════ */
  function docMeta(rec) {
    return {
      id: rec.id,
      title: rec.title || '未命名',
      updatedAt: rec.updatedAt || 0,
      count: (function cnt(n) { return n ? 1 + (n.children || []).reduce((a, c) => a + cnt(c), 0) : 0; })(rec.root),
      active: rec.id === S.docId,
    };
  }

  async function listDocs() {
    const recs = (await IDB.all()).filter(r => r && r.id !== 'prev' && validDoc(r));
    return recs.map(docMeta).sort((a, b) => b.updatedAt - a.updatedAt);
  }

  async function openDoc(id) {
    if (id === S.docId) return false;
    S._transient = false;
    save();                                  // 切换前先把当前文档落盘
    const rec = await IDB.get(id);
    if (!rec || !validDoc(rec)) return false;
    S.docId = id;
    applyDoc(migrate(rec));
    clearHistory();
    emit('load'); scheduleSave();
    return true;
  }

  async function newDoc(key = 'blank', opts) {
    /* 删除当前文档后新建空白页时，不能先 save()——那会把刚删掉的文档写回去。 */
    if (!(opts && opts.replace)) {
      S._transient = false;
      save();
    }
    const tpl = TEMPLATES[key] || TEMPLATES.blank;
    S.docId = 'd' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    applyDoc({
      root: JSON.parse(JSON.stringify(tpl.tree)), links: [],
      title: tpl.name === '空白画布' ? '思维导图' : tpl.name,
      layout: S.layout, theme: S.theme, lineStyle: S.lineStyle,
      projector: false, blank: false,
    });
    S._transient = false;
    clearHistory();
    emit('load'); save();
    return true;
  }

  async function duplicateDoc() {
    S._transient = false;
    save();
    const title = S.title + ' 副本';
    S.docId = 'd' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    S.title = title;
    clearHistory();
    emit('load'); save();
    return true;
  }

  async function deleteDoc(id) {
    const deletingCurrent = id === S.docId;
    const rest = deletingCurrent ? (await listDocs()).filter(d => d.id !== id) : [];
    await IDB.del(id);
    /* localStorage 兜底副本如果正是这份，也要一起清掉，
       否则下次启动会在「IDB 没有有效文档」时把它当备份恢复。 */
    try {
      const raw = localStorage.getItem(LS_KEY);
      if (raw) {
        const d = JSON.parse(raw);
        if ((d.id || 'current') === id) localStorage.removeItem(LS_KEY);
      }
    } catch (e) { /* ignore */ }
    clearScores(id);
    /* prev 是「上次启动时的完整副本」。如果它正是被删的这份，
       不清掉的话，将来主存档损坏时会把它当备份恢复回来。 */
    try {
      const prev = await IDB.get('prev');
      if (prev && (prev.docId || 'current') === id) await IDB.del('prev');
    } catch (e) { /* ignore */ }
    if (!deletingCurrent) return true;

    /* 不能走 openDoc()/newDoc()：它们开头都会 save() 当前文档，
       等于把刚删除的这份又写回 IndexedDB（删了又复活）。 */
    if (rest.length) {
      const rec = await IDB.get(rest[0].id);
      if (rec && validDoc(rec)) {
        S.docId = rest[0].id;
        applyDoc(migrate(rec));
        clearHistory();
        S._transient = false;
        emit('load'); save();
        return true;
      }
    }
    await newDoc('blank', { replace: true });
    return true;
  }

  /* ══════════ 校验与迁移 ══════════ */
  function validDoc(d) {
    if (!d || typeof d !== 'object' || !d.root || typeof d.root !== 'object') return false;
    let ok = true, n = 0;
    (function scan(x, depth) {
      if (!ok) return;
      if (depth > 40 || n++ > 6000) { ok = false; return; }
      if (!x || typeof x !== 'object') { ok = false; return; }
      if (x.text != null && typeof x.text !== 'string') { ok = false; return; }
      /* children 缺省按空数组处理，手写/精简过的 JSON 也能导入 */
      if (x.children != null && !Array.isArray(x.children)) { ok = false; return; }
      (x.children || []).forEach(c => scan(c, depth + 1));
    })(d.root, 0);
    return ok;
  }

  function migrate(d) {
    let v = Number(d.version) || 1;
    if (v < 3) {
      d.projector = !!d.projector;
      d.blank = !!d.blank;
      v = 3;
    }
    if (!Array.isArray(d.links)) d.links = [];
    d.version = SCHEMA;
    return d;
  }

  /* ══════════ 持久化 ══════════ */
  function scheduleSave() {
    if (S._transient) return;
    clearTimeout(S._saveTimer);
    S._saveTimer = setTimeout(save, 450);
  }

  let chain = Promise.resolve();
  function save() {
    if (S._transient) return;
    let doc;
    try { doc = toJSON(); } catch (e) { return; }
    try { localStorage.setItem(LS_KEY, JSON.stringify(doc)); } catch (e) { /* 兜底失败忽略 */ }
    const rec = Object.assign({}, doc, { id: S.docId, updatedAt: Date.now() });
    chain = chain
      .then(() => IDB.put(rec))
      .then(() => document.dispatchEvent(new CustomEvent('doc-saved')))
      .catch(() => {});
  }

  /* ══════════ 结构分历史 ══════════
     单独存 localStorage，不进文档。理由：
     分数是「这次看的时候算出来的」，属于观测记录，不属于文档内容；
     混进文档会让撤销、导出、多文档复制都多背一份无关数据。 */
  const SCORE_KEY = 'mapmind.scores.v1';

  function readScoreBook() {
    try {
      const raw = localStorage.getItem(SCORE_KEY);
      const obj = raw ? JSON.parse(raw) : null;
      return (obj && typeof obj === 'object') ? obj : {};
    } catch (e) { return {}; }
  }

  function scoreFingerprint(r) {
    /* 结构没变就不该多一个点，否则曲线全是水平重复段 */
    return [r.nodes, r.prop, r.depth, r.cross, r.leaves].join('/');
  }

  function pushScore(rec) {
    const book = readScoreBook();
    const id = S.docId || 'current';
    const list = Array.isArray(book[id]) ? book[id] : [];
    const fp = scoreFingerprint(rec);
    const last = list[list.length - 1];
    if (last && last.fp === fp) {
      last.at = rec.at;                  // 结构没变，只更新时间
    } else {
      list.push(Object.assign({ fp }, rec));
    }
    book[id] = list.slice(-120);
    try { localStorage.setItem(SCORE_KEY, JSON.stringify(book)); } catch (e) { /* 配额满就放弃，不影响主流程 */ }
    return book[id];
  }

  function listScores(docId) {
    const book = readScoreBook();
    const list = book[docId || S.docId || 'current'];
    return Array.isArray(list) ? list.slice() : [];
  }

  function clearScores(docId) {
    const book = readScoreBook();
    delete book[docId || S.docId || 'current'];
    try { localStorage.setItem(SCORE_KEY, JSON.stringify(book)); } catch (e) { /* ignore */ }
  }

  /* ══════════ 初始化 ══════════ */
  async function init() {
    let doc = null, source = '';

    /* localStorage 里那份是「最后一次保存」的同步副本。它可能比 IndexedDB 新：
       页面关闭时 IDB 事务来不及完成，但 localStorage.setItem 是同步的。
       所以不能只在 IDB 全坏时才看它，还要比时间戳。 */
    let lsDoc = null;
    try {
      const raw = localStorage.getItem(LS_KEY);
      if (raw) {
        const d = JSON.parse(raw);
        if (validDoc(d)) lsDoc = d;
      }
    } catch (e) { /* 忽略 */ }

    const recs = (await IDB.all()).filter(r => r && r.id !== 'prev');
    const valid = recs.filter(validDoc).sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
    const broken = recs.length - valid.length;

    if (valid.length) {
      doc = valid[0];
      S.docId = doc.id;
      source = 'current';
    } else {
      // 主存档损坏时回滚
      const prev = await IDB.get('prev');
      if (prev && prev.doc && validDoc(prev.doc)) {
        doc = prev.doc;
        S.docId = prev.docId || 'current';
        source = 'prev';
      }
    }

    if (!doc && lsDoc) {
      doc = lsDoc;
      S.docId = lsDoc.id || 'current';
      source = 'localStorage';
    } else if (doc && lsDoc) {
      // localStorage 永远保存「最后一次 save 的那份」。它更新就说明关闭前还有一版没写进 IDB，
      // 不管 id 是否相同，都该以它为准（切换文档后立刻关闭也属于这种情况）。
      const lsTime = Date.parse(lsDoc.savedAt) || 0;
      const idbTime = doc.updatedAt || Date.parse(doc.savedAt) || 0;
      if (lsTime > idbTime + 500) {
        doc = lsDoc;
        S.docId = lsDoc.id || S.docId;
        source = 'localStorage';
      }
    }

    if (doc) {
      doc = migrate(doc);
      applyDoc(doc);
      if (source === 'current') {
        try {
          await IDB.put({ id: 'prev', docId: S.docId, doc: JSON.parse(JSON.stringify(doc)) });
        } catch (e) {}
      } else if (source === 'localStorage') {
        // 从更新的同步副本恢复后，把它写回主存档，下一轮就不会再走兜底
        try {
          await IDB.put(Object.assign({}, JSON.parse(JSON.stringify(doc)), {
            id: S.docId, updatedAt: Date.now(),
          }));
        } catch (e) {}
      }
    } else {
      const tpl = TEMPLATES.summary;
      S.root = normalize(JSON.parse(JSON.stringify(tpl.tree)));
      S.links = [];
      S.title = '思维导图';
      S.docId = 'current';
      S.selectedId = S.root.id;
    }
    /* 浏览器在磁盘紧张时可能清掉 IndexedDB。申请持久化存储能显著降低被清的概率；
       被拒绝也不影响使用。 */
    try {
      if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});
    } catch (e) { /* ignore */ }
    if (broken > 0) return source + ':broken';
    return source || 'template';
  }

  Object.assign(S, {
    init, walk, find, parentOf, isDescendant, count, on, emit,
    undo, redo, addChild, addSibling, remove, setText,
    toggleCollapse, setCollapsedAll, moveTo,
    addLink, removeLink, setLinkLabel, linkExists,
    setLayout, setTheme, toggleLineStyle, setTitle,
    toggleProjector, toggleBlank, reveal, revealAll, unreveal, clearRevealed,
    loadTemplate, loadMap, setDoc, toJSON, save, scheduleSave, exportDoc,
    listDocs, openDoc, newDoc, duplicateDoc, deleteDoc,
    pushScore, listScores, clearScores,
  });
  /* 注意：这三个不能写进上面那个对象字面量。
     Object.assign 会「读取」getter 的当前值再赋值，于是拿到的是 0 / false 的快照，
     撤销按钮会永久灰着。必须用 defineProperties 保留 getter 本身。 */
  Object.defineProperties(S, {
    canUndo: { get: () => H.past.length > 0, enumerable: true },
    canRedo: { get: () => H.future.length > 0, enumerable: true },
    historySize: { get: () => H.past.length, enumerable: true },
  });
  return S;
})();
