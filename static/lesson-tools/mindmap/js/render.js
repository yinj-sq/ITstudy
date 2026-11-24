/* ============================================================
   render.js — 节点 / 连线渲染 + 视口
   ============================================================ */
const Renderer = (() => {
  const NS = 'http://www.w3.org/2000/svg';
  const stageEl = document.getElementById('stage');
  const worldEl = document.getElementById('world');
  const edgesEl = document.getElementById('edges');
  const nodesEl = document.getElementById('nodes');
  const zoomVal = document.getElementById('zoomVal');

  const els = new Map();     // id -> element
  let lastResult = null;
  let revealSet = null;      // 演示模式：可见节点 id 集合
  let view = { x: 0, y: 0, scale: 1 };

  const theme = () => THEMES[Store.theme] || THEMES.paper;
  const levelStyle = (depth) => {
    const t = theme();
    return t.levels[Math.min(depth, t.levels.length - 1)];
  };

  function applyTheme() {
    const t = theme();
    stageEl.style.backgroundColor = t.canvas;
    stageEl.style.backgroundImage = `radial-gradient(circle, ${t.dot} 1px, transparent 1px)`;
    document.documentElement.style.setProperty('--line-c', t.line);
    /* body 背景跟画布同色：顶栏是半透明玻璃，透出来的就是这一层。
       两处不一致的话，暖色面板会被掺回冷调（反之亦然）。 */
    document.documentElement.style.setProperty('--canvas-c', t.canvas);
    const h = t.canvas.replace('#', '');
    const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
    const lum = 0.299 * r + 0.587 * g + 0.114 * b;
    document.body.classList.toggle('theme-dark', lum < 140);
    /* 暖色画布（米黄纸、暖阳）时让工具栏也暖一档。判据是 r 明显高于 b：
       素纸 r-b=23、暖阳 12 命中；青竹 -1、墨白 0、深海 -10 不命中。
       阈值 8 是留给「几乎中性但偏暖一点点」的余量，太小会把青竹也抓进来。 */
    document.body.classList.toggle('theme-warm', lum >= 140 && (r - b) > 8);
  }

  /* ── 节点元素 ── */
  function makeNodeEl(rec) {
    const el = document.createElement('div');
    el.className = 'node';
    el.dataset.id = rec.id;
    el.innerHTML = '<div class="nbox"></div><span class="bmark">?</span><button class="cbtn" tabindex="-1"></button>';
    return el;
  }

  function paintNode(el, rec) {
    const ls = levelStyle(rec.depth);
    const st = rec.style;
    const proj = !!Store.projector;
    el.dataset.dir = rec.dir;
    el.style.width = rec.w + 'px';
    el.style.height = rec.h + 'px';
    el.style.transform = `translate(${rec.x}px,${rec.y}px)`;
    el.style.background = ls.bg;
    el.style.color = ls.fg;
    el.style.borderRadius = st.radius + 'px';
    /* 投影模式：去掉阴影、加实边框，远距离更干净 */
    el.style.boxShadow = proj ? 'none' : (ls.shadow && ls.shadow !== 'none' ? ls.shadow : 'none');
    el.style.fontSize = st.size + 'px';
    el.style.fontWeight = st.weight;
    el.style.fontFamily = U.FONT_STACK;
    el.style.setProperty('--padx', st.padX + 'px');
    el.style.setProperty('--pady', st.padY + 'px');
    if (proj) {
      const bd = ls.border && ls.border !== 'transparent' ? ls.border : 'rgba(0,0,0,.18)';
      el.style.outline = `2px solid ${bd}`;
      el.style.outlineOffset = '-2px';
    } else {
      el.style.outline = ls.border && ls.border !== 'transparent' ? `1.5px solid ${ls.border}` : 'none';
      el.style.outlineOffset = '-1.5px';
    }

    const box = el.querySelector('.nbox');
    const key = rec.lines.join('\u0001');
    if (box.dataset.key !== key) {
      box.dataset.key = key;
      box.innerHTML = '';
      for (const ln of rec.lines) {
        const d = document.createElement('div');
        d.className = 'nline';
        d.style.height = rec.lh + 'px';
        d.style.fontSize = st.size + 'px';
        d.textContent = ln === '' ? '\u00a0' : ln;
        box.appendChild(d);
      }
    }

    const btn = el.querySelector('.cbtn');
    if (rec.hasChildren && rec.depth > 0) {
      btn.style.display = '';
      btn.textContent = rec.collapsed ? String(rec.childCount) : '−';
      el.classList.toggle('collapsed', rec.collapsed);
    } else {
      btn.style.display = 'none';
      el.classList.remove('collapsed');
    }

    el.classList.toggle('sel', Store.selectedId === rec.id);
    el.classList.toggle('hidden-node', !!(revealSet && !revealSet.has(rec.id)));
    const isBlank = Store.blank && rec.depth > 0 &&
      !Store.revealed.has(rec.id) && el.dataset.editing !== '1';
    el.classList.toggle('blank', isBlank);

    /* 无障碍：把节点暴露成标准树结构 */
    const selId = Store.selectedId || (Store.root && Store.root.id);
    el.setAttribute('role', 'treeitem');
    el.setAttribute('aria-level', String(rec.depth + 1));
    el.setAttribute('aria-selected', Store.selectedId === rec.id ? 'true' : 'false');
    if (rec.hasChildren) el.setAttribute('aria-expanded', rec.collapsed ? 'false' : 'true');
    else el.removeAttribute('aria-expanded');
    el.tabIndex = selId === rec.id ? 0 : -1;
    /* 挖空时连读屏也不能泄露答案 */
    let label = isBlank ? '待填空' : (rec.lines.join('') || '空节点');
    if (rec.hasChildren && rec.collapsed) label += `，已折叠 ${rec.childCount} 个分支`;
    el.setAttribute('aria-label', label);
  }

  /* ── 连线 ── */
  function svgEl(tag, attrs) {
    const n = document.createElementNS(NS, tag);
    if (attrs) for (const k in attrs) n.setAttribute(k, attrs[k]);
    return n;
  }

  /* 关系边：带箭头的虚线 + 关系词标签 */
  function renderLinks(res, frag) {
    if (!res.links || !res.links.length) return;
    const t = theme();
    const accent = t.levels[0].bg;
    const canvas = t.canvas;

    const defs = svgEl('defs');
    const marker = svgEl('marker', {
      id: 'relArrow', viewBox: '0 0 10 10', refX: '9', refY: '5',
      markerWidth: '6.5', markerHeight: '6.5', orient: 'auto-start-reverse',
    });
    marker.appendChild(svgEl('path', { d: 'M0 0.8L9.6 5L0 9.2z', fill: accent }));
    defs.appendChild(marker);
    frag.appendChild(defs);

    for (const l of res.links) {
      if (revealSet && (!revealSet.has(l.from) || !revealSet.has(l.to))) continue;
      const g = svgEl('g', { class: 'rel' + (Store.selectedLinkId === l.id ? ' sel' : '') });
      g.dataset.link = l.id;
      g.appendChild(svgEl('path', { d: l.d, class: 'rel-hit' }));
      const line = svgEl('path', {
        d: l.d, class: 'rel-line', stroke: accent, 'marker-end': 'url(#relArrow)',
      });
      if (Store.projector) line.style.strokeWidth = '2.8';
      g.appendChild(line);
      if (l.label) {
        const tx = svgEl('text', {
          x: l.lx, y: l.ly, class: 'rel-label', fill: accent, stroke: canvas,
        });
        if (Store.projector) {
          tx.style.fontSize = '20px';
          tx.style.strokeWidth = '6';
        }
        tx.textContent = l.label;
        g.appendChild(tx);
      }
      frag.appendChild(g);
    }
  }

  function renderEdges(res) {
    const frag = document.createDocumentFragment();
    for (const e of res.edges) {
      const p = document.createElementNS(NS, 'path');
      p.setAttribute('d', Layout.edgePath(e, Store.lineStyle));
      p.setAttribute('stroke-width', e.w);
      if (revealSet && (!revealSet.has(e.from) || !revealSet.has(e.to))) {
        p.style.opacity = '0';
      }
      frag.appendChild(p);
    }
    for (const d of res.dots) {
      const c = document.createElementNS(NS, 'circle');
      c.setAttribute('cx', d.x); c.setAttribute('cy', d.y); c.setAttribute('r', d.r);
      c.setAttribute('fill', theme().line);
      frag.appendChild(c);
    }
    renderLinks(res, frag);
    edgesEl.replaceChildren(frag);
  }

  /* ── 主渲染 ── */
  function render() {
    applyTheme();
    const res = Layout.compute(Store.root, { layout: Store.layout });
    lastResult = res;

    const W = res.bounds.width, H = res.bounds.height;
    worldEl.style.width = W + 'px';
    worldEl.style.height = H + 'px';
    edgesEl.setAttribute('width', W);
    edgesEl.setAttribute('height', H);
    edgesEl.setAttribute('viewBox', `0 0 ${W} ${H}`);

    const seen = new Set();
    for (const rec of res.nodes) {
      seen.add(rec.id);
      let el = els.get(rec.id);
      if (!el) {
        el = makeNodeEl(rec);
        paintNode(el, rec);          // 先定位再插入，避免从左上角飞入
        els.set(rec.id, el);
        nodesEl.appendChild(el);
        el.classList.add('enter');
        setTimeout(() => el.classList.remove('enter'), 240);
      } else {
        paintNode(el, rec);
      }
    }
    for (const [id, el] of els) {
      if (!seen.has(id)) { el.remove(); els.delete(id); }
    }

    renderEdges(res);
    applyView();
    return res;
  }

  /* ── 视口 ── */
  function applyView() {
    worldEl.style.transform = `translate(${view.x}px,${view.y}px) scale(${view.scale})`;
    zoomVal.textContent = Math.round(view.scale * 100) + '%';
    stageEl.style.backgroundSize = `${24 * view.scale}px ${24 * view.scale}px`;
    stageEl.style.backgroundPosition = `${view.x}px ${view.y}px`;
  }

  function setView(x, y, scale) {
    view.x = x; view.y = y; view.scale = scale;
    applyView();
  }

  function zoomAt(cx, cy, factor) {
    const s0 = view.scale;
    const s1 = U.clamp(s0 * factor, 0.2, 2.5);
    if (s1 === s0) return;
    const rect = stageEl.getBoundingClientRect();
    const px = cx - rect.left, py = cy - rect.top;
    view.x = px - (px - view.x) * (s1 / s0);
    view.y = py - (py - view.y) * (s1 / s0);
    view.scale = s1;
    applyView();
  }

  function zoomBy(factor) {
    const r = stageEl.getBoundingClientRect();
    zoomAt(r.left + r.width / 2, r.top + r.height / 2, factor);
  }

  /* 投影模式：锁定 100%，镜头对准某个节点（一屏一个知识点） */
  let camTimer = null;
  function camAnimate() {
    worldEl.classList.add('cam');
    clearTimeout(camTimer);
    camTimer = setTimeout(() => worldEl.classList.remove('cam'), 560);
  }

  function focusOn(id, scale, animate) {
    const rec = lastResult && lastResult.byId.get(id);
    if (!rec) return;
    const r = stageEl.getBoundingClientRect();

    // 取该节点 + 它的直接下级作为取景范围，叶子节点自然居中
    let minX = rec.x, minY = rec.y, maxX = rec.x + rec.w, maxY = rec.y + rec.h;
    const node = Store.find(id);
    if (node && !node.collapsed) {
      for (const c of node.children) {
        if (revealSet && !revealSet.has(c.id)) continue;   // 演示中还没出现的节点不参与取景
        const cr = lastResult.byId.get(c.id);
        if (!cr) continue;
        minX = Math.min(minX, cr.x); minY = Math.min(minY, cr.y);
        maxX = Math.max(maxX, cr.x + cr.w); maxY = Math.max(maxY, cr.y + cr.h);
      }
    }

    if (animate) camAnimate();
    view.scale = scale;

    let vx = r.width / 2 - ((minX + maxX) / 2) * scale;
    let vy = (r.height - 70) / 2 - ((minY + maxY) / 2) * scale;

    // 包围盒过大时，至少保证当前节点本身留在视野里
    const nodeLeft = rec.x * scale + vx;
    const minLeft = r.width * 0.14;
    if (nodeLeft < minLeft) vx += minLeft - nodeLeft;

    const nodeTop = rec.y * scale + vy;
    const minTop = r.height * 0.1;
    if (nodeTop < minTop) vy += minTop - nodeTop;

    view.x = vx; view.y = vy;
    applyView();
  }

  /* 把某个节点本身放到画面指定位置（不做整体缩放） */
  /* 把一组节点框进视野。练习模式用：当前这一格 + 它的父节点 + 直接下级。
     为什么不用 fit()：fit 框的是整张图，手机上缩到 0.37，学生连「问到哪一格」
     都找不着；为什么不用 focusOn()：focusOn 只看下级，看不到它挂在谁下面，
     而「它挂在谁下面」恰恰是这类题唯一的线索。 */
  function frameIds(ids, opts) {
    const o = opts || {};
    if (!lastResult) return;
    const recs = (ids || []).map(id => lastResult.byId.get(id)).filter(Boolean);
    if (!recs.length) return;
    const r = stageEl.getBoundingClientRect();
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    recs.forEach(n => {
      minX = Math.min(minX, n.x); minY = Math.min(minY, n.y);
      maxX = Math.max(maxX, n.x + n.w); maxY = Math.max(maxY, n.y + n.h);
    });
    const bw = Math.max(40, maxX - minX), bh = Math.max(40, maxY - minY);
    const padX = o.padX == null ? 44 : o.padX;
    const padY = o.padY == null ? 44 : o.padY;
    const bottom = o.bottom || 0;
    const s = U.clamp(
      Math.min((r.width - padX * 2) / bw, (r.height - padY * 2 - bottom) / bh),
      o.min == null ? 0.4 : o.min, o.max == null ? 1.3 : o.max);
    if (o.animate) camAnimate();
    view.scale = s;
    view.x = (r.width - bw * s) / 2 - minX * s;
    view.y = (r.height - bottom - bh * s) / 2 - minY * s;
    applyView();
  }

  function centerNode(id, scale, animate, fx = 0.42, fy = 0.5) {
    const rec = lastResult && lastResult.byId.get(id);
    if (!rec) return;
    const r = stageEl.getBoundingClientRect();
    if (animate) camAnimate();
    view.scale = scale;
    view.x = r.width * fx - (rec.x + rec.w / 2) * scale;
    view.y = (r.height - 70) * fy - (rec.y + rec.h / 2) * scale;
    applyView();
  }

  function fit(animate) {
    if (!lastResult) return;
    if (Store.projector) { centerNode(Store.root.id, 1, animate); return; }
    const r = stageEl.getBoundingClientRect();
    const bw = lastResult.bounds.width, bh = lastResult.bounds.height;
    const mx = Math.min(140, r.width * 0.1), my = Math.min(150, r.height * 0.15);
    const s = U.clamp(Math.min((r.width - mx) / bw, (r.height - my) / bh), 0.2, 1.4);
    view.scale = s;
    view.x = (r.width - bw * s) / 2;
    view.y = (r.height - bh * s) / 2;
    applyView();
  }

  /* 按给定节点集合取景（思维展示逐级展开时使用） */
  function fitRecs(recs, animate) {
    if (!recs || !recs.length) return;
    if (Store.projector) {
      // 投影模式不做整体缩放，只把最新一个节点送到视野里
      focusOn(recs[recs.length - 1].id, 1, animate);
      return;
    }
    const r = stageEl.getBoundingClientRect();
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const n of recs) {
      minX = Math.min(minX, n.x); minY = Math.min(minY, n.y);
      maxX = Math.max(maxX, n.x + n.w); maxY = Math.max(maxY, n.y + n.h);
    }
    const bw = Math.max(60, maxX - minX), bh = Math.max(60, maxY - minY);
    const s = U.clamp(Math.min((r.width - 180) / bw, (r.height - 210) / bh), 0.35, 1.85);
    if (animate) camAnimate();
    view.scale = s;
    view.x = (r.width - bw * s) / 2 - minX * s;
    view.y = (r.height - 76 - bh * s) / 2 - minY * s;
    applyView();
  }

  function centerOn(id, smooth) {
    const rec = lastResult && lastResult.byId.get(id);
    if (!rec) return;
    const r = stageEl.getBoundingClientRect();
    view.x = r.width / 2 - (rec.x + rec.w / 2) * view.scale;
    view.y = r.height / 2 - (rec.y + rec.h / 2) * view.scale;
    applyView();
  }

  function ensureVisible(id) {
    const rec = lastResult && lastResult.byId.get(id);
    if (!rec) return;
    const r = stageEl.getBoundingClientRect();
    const pad = 60;
    const x1 = rec.x * view.scale + view.x;
    const y1 = rec.y * view.scale + view.y;
    const x2 = (rec.x + rec.w) * view.scale + view.x;
    const y2 = (rec.y + rec.h) * view.scale + view.y;
    let dx = 0, dy = 0;
    if (x1 < pad) dx = pad - x1;
    else if (x2 > r.width - pad) dx = r.width - pad - x2;
    if (y1 < pad + 40) dy = pad + 40 - y1;
    else if (y2 > r.height - 110) dy = r.height - 110 - y2;
    if (dx || dy) { view.x += dx; view.y += dy; applyView(); }
  }

  function setReveal(set) { revealSet = set; }
  function getView() { return { ...view }; }

  return {
    render, applyView, setView, zoomAt, zoomBy, fit, fitRecs, focusOn, centerNode, centerOn, frameIds, ensureVisible,
    setReveal, getView,
    get result() { return lastResult; },
    nodeEl: (id) => els.get(id),
    stageEl,
  };
})();

/* 视口拖拽/缩放由 app.js 绑定 */
