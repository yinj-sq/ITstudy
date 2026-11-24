/* ============================================================
   layout.js — 文本测量 + 五种结构布局算法
   ============================================================ */
const Layout = (() => {
  const PAD = 90;
  /* 间距（投影模式下会整体放大） */
  const G = { x: 62, y: 18, mx: 46, my: 56, sp: 38 };

  let current = null;

  /* ── 尺寸测量 ── */
  function measureAll(root) {
    const k = Store.projector ? 1.85 : 1;   // 投影模式：字号放大约 1.85 倍
    const walk = (n, depth) => {
      const base = NODE_STYLE[Math.min(depth, NODE_STYLE.length - 1)];
      const s = {
        size: Math.round(base.size * k),
        weight: base.weight,
        padX: Math.round(base.padX * (k > 1 ? 1.4 : 1)),
        padY: Math.round(base.padY * (k > 1 ? 1.4 : 1)),
        maxW: Math.round(base.maxW * k * 1.02),
        minW: Math.round(base.minW * (k > 1 ? 1.3 : 1)),
        radius: Math.round(base.radius * (k > 1 ? 1.4 : 1)),
        shadow: base.shadow && k === 1,
      };
      const font = U.fontStr(s.size, s.weight);
      const text = n.text || (depth === 0 ? '中心主题' : '');
      const lines = U.wrap(text, s.maxW - s.padX * 2, font);
      let maxLineW = 0;
      for (const l of lines) maxLineW = Math.max(maxLineW, U.measure(l, font));

      n._depth = depth;
      n._style = s;
      n._font = font;
      n._lines = lines;
      n._lh = Math.round(s.size * 1.5);

      let w = Math.ceil(maxLineW) + s.padX * 2;
      w = Math.max(s.minW, Math.min(s.maxW, w));
      if (maxLineW + s.padX * 2 > w) w = maxLineW + s.padX * 2;
      n._w = Math.ceil(w);
      n._h = Math.ceil(lines.length * n._lh + s.padY * 2);

      for (const c of n.children) walk(c, depth + 1);
    };
    walk(root, 0);
  }

  /* ── 子树尺寸缓存 ── */
  function heightFn(gap) {
    const M = new Map();
    return function H(n) {
      if (M.has(n)) return M.get(n);
      let v;
      if (!n.children.length || n.collapsed) v = n._h;
      else {
        let sum = 0;
        n.children.forEach((c, i) => { sum += H(c) + (i ? gap : 0); });
        v = Math.max(n._h, sum);
      }
      M.set(n, v);
      return v;
    };
  }

  function widthFn(gap) {
    const M = new Map();
    return function W(n) {
      if (M.has(n)) return M.get(n);
      let v;
      if (!n.children.length || n.collapsed) v = n._w;
      else {
        let sum = 0;
        n.children.forEach((c, i) => { sum += W(c) + (i ? gap : 0); });
        v = Math.max(n._w, sum);
      }
      M.set(n, v);
      return v;
    };
  }

  /* ── 水平方向摆放（dir: 1 向右 / -1 向左） ── */
  function placeDir(n, anchorX, cy, dir, H, gap) {
    n._x = dir > 0 ? anchorX : anchorX - n._w;
    n._y = cy - n._h / 2;
    n._dir = dir > 0 ? 'r' : 'l';
    if (n.collapsed || !n.children.length) return;
    let total = 0;
    n.children.forEach((c, i) => { total += H(c) + (i ? gap : 0); });
    let y = cy - total / 2;
    for (const c of n.children) {
      const ch = H(c);
      const nx = dir > 0 ? n._x + n._w + G.x : n._x - G.x;
      placeDir(c, nx, y + ch / 2, dir, H, gap);
      y += ch + gap;
    }
  }

  /* ── 1. 逻辑结构图 ── */
  function logical(root) {
    const H = heightFn(G.y);
    (function place(n, x, cy) {
      n._x = x; n._y = cy - n._h / 2; n._dir = 'r';
      if (n.collapsed || !n.children.length) return;
      let total = 0;
      n.children.forEach((c, i) => { total += H(c) + (i ? G.y : 0); });
      let y = cy - total / 2;
      for (const c of n.children) {
        const ch = H(c);
        place(c, x + n._w + G.x, y + ch / 2);
        y += ch + G.y;
      }
    })(root, 0, 0);
  }

  /* ── 2. 思维导图（左右发散） ── */
  function mindmap(root) {
    const H = heightFn(G.y);
    root._x = -root._w / 2;
    root._y = -root._h / 2;
    root._dir = 'r';

    const right = [], left = [];
    root.children.forEach((c, i) => (i % 2 === 0 ? right : left).push(c));

    const block = (list, dir) => {
      if (!list.length) return;
      let total = 0;
      list.forEach((c, i) => { total += H(c) + (i ? G.y : 0); });
      let y = -total / 2;
      for (const c of list) {
        const ch = H(c);
        const ax = dir > 0 ? root._x + root._w + G.x : root._x - G.x;
        placeDir(c, ax, y + ch / 2, dir, H, G.y);
        y += ch + G.y;
      }
    };
    block(right, 1);
    block(left, -1);
  }

  /* ── 3. 组织结构图（自上而下） ── */
  function org(root) {
    const W = widthFn(G.mx);
    (function place(n, cx, y) {
      n._x = cx - n._w / 2; n._y = y; n._dir = 'd';
      if (n.collapsed || !n.children.length) return;
      let total = 0;
      n.children.forEach((c, i) => { total += W(c) + (i ? G.mx : 0); });
      let x = cx - total / 2;
      for (const c of n.children) {
        const cw = W(c);
        place(c, x + cw / 2, y + n._h + G.my);
        x += cw + G.mx;
      }
    })(root, 0, 0);
  }

  /* ── 4. 时间轴 ── */
  function timeline(root) {
    const H = heightFn(G.y);
    const kids = root.children;
    let total = 0;
    kids.forEach((c, i) => { total += H(c) + (i ? G.sp : 0); });

    const cy = total / 2;
    root._x = 0; root._y = cy - root._h / 2; root._dir = 'r';

    const spineX = root._x + root._w + 66;
    let y = 0;
    const pts = [];
    for (const c of kids) {
      const ch = H(c);
      placeDir(c, spineX + 30, y + ch / 2, 1, H, G.y);
      c._spineY = y + ch / 2;
      c._spineX = spineX;
      pts.push(c._spineY);
      y += ch + G.sp;
    }
    root._spineX = spineX;
    root._spineYs = pts;
  }

  /* ── 5. 鱼骨图 ── */
  function fishbone(root) {
    const H = heightFn(G.y);
    const W = widthFn(G.x);
    root._x = 0; root._y = -root._h / 2; root._dir = 'r';

    // 向左堆叠（用于子因的下级）
    const placeLeft = (n, rightX, cy) => {
      n._x = rightX - n._w; n._y = cy - n._h / 2; n._dir = 'l';
      if (n.collapsed || !n.children.length) return;
      let total = 0;
      n.children.forEach((c, i) => { total += H(c) + (i ? G.y : 0); });
      let y = cy - total / 2;
      for (const c of n.children) {
        const ch = H(c);
        placeLeft(c, n._x - 26, y + ch / 2);
        y += ch + G.y;
      }
    };

    let cursor = root._x - 60;
    const bones = [];

    // 统一骨长，保证视觉整齐
    let maxSubs = 0;
    root.children.forEach(c => { if (!c.collapsed) maxSubs = Math.max(maxSubs, c.children.length); });
    const L = Math.max(146, 100 + maxSubs * 26);
    const dx = -Math.round(L * 0.5);

    root.children.forEach((c, i) => {
      const up = i % 2 === 0;
      const sign = up ? -1 : 1;
      const attachX = cursor;
      const endX = attachX + dx;
      const endY = sign * L;

      c._x = endX - c._w / 2;
      c._y = up ? endY - c._h - 8 : endY + 8;
      c._dir = 'r';
      c._subTicks = [];
      c._bone = { x1: attachX, y1: 0, x2: endX, y2: endY, up };

      const subs = c.collapsed ? [] : c.children;
      const n = subs.length;
      subs.forEach((s, j) => {
        const t = n === 1 ? 0.56 : 0.3 + (j / (n - 1)) * 0.58;
        const px = attachX + (endX - attachX) * t;
        const py = endY * t;
        s._x = px - 18 - s._w;
        s._y = py - s._h / 2;
        s._dir = 'l';
        c._subTicks.push({ x1: px, y1: py, x2: px - 18, y2: py });
        if (!s.collapsed && s.children.length) placeLeft(s, s._x - 24, py);
      });

      let maxW = c._w;
      subs.forEach(s => { maxW = Math.max(maxW, W(s)); });
      cursor = attachX - (Math.abs(dx) + maxW * 0.55 + 38);
      bones.push({ c, attachX, endX, endY, up });
    });

    root._spineStart = cursor + 40;
    root._bones = bones;
  }

  /* ── 6. 圆圈图 / 气泡图（中心 + 环形发散） ── */
  function ring(root) {
    root._x = -root._w / 2;
    root._y = -root._h / 2;
    root._dir = 'r';
    const kids = root.children;
    if (!kids.length) return;

    const H = heightFn(G.y);
    const n = kids.length;
    let maxW = 0, maxH = 0;
    kids.forEach(c => { maxW = Math.max(maxW, c._w); maxH = Math.max(maxH, c._h); });
    const R = Math.max(190, 84 + n * 30, (maxW + maxH) * 0.85);

    kids.forEach((c, i) => {
      const a = -Math.PI / 2 + (i / n) * Math.PI * 2;
      const cx = Math.cos(a) * R * 1.3;
      const cy = Math.sin(a) * R * 0.86;
      const dir = Math.cos(a) >= 0 ? 1 : -1;
      c._x = cx - c._w / 2;
      c._y = cy - c._h / 2;
      c._dir = dir > 0 ? 'r' : 'l';
      c._ring = true;

      if (c.collapsed || !c.children.length) return;
      let total = 0;
      c.children.forEach((g, j) => { total += H(g) + (j ? G.y : 0); });
      let y = cy - total / 2;
      const ax = dir > 0 ? c._x + c._w + G.x : c._x - G.x;
      c.children.forEach(g => {
        const gh = H(g);
        placeDir(g, ax, y + gh / 2, dir, H, G.y);
        y += gh + G.y;
      });
    });
  }

  /* ── 7. 双气泡图（两个中心 + 中间共同点） ── */
  function double(root) {
    const H = heightFn(G.y);
    const W = widthFn(G.x);
    const kids = root.children;

    root._x = -root._w / 2;
    root._y = 0;
    root._dir = 'r';

    if (kids.length < 2) { mindmap(root); return; }

    const A = kids[0], B = kids[1], shared = kids.slice(2);

    const placeOut = (n, line, cy, dir) => {
      n._x = dir > 0 ? line : line - n._w;
      n._y = cy - n._h / 2;
      n._dir = dir > 0 ? 'r' : 'l';
      if (n.collapsed || !n.children.length) return;
      let total = 0;
      n.children.forEach((c, i) => { total += H(c) + (i ? G.y : 0); });
      let y = cy - total / 2;
      n.children.forEach(c => {
        const ch = H(c);
        const ax = dir > 0 ? n._x + n._w + G.x : n._x - G.x;
        placeOut(c, ax, y + ch / 2, dir);
        y += ch + G.y;
      });
    };

    let midW = 0;
    shared.forEach(s => { midW = Math.max(midW, W(s)); });

    const hubCy = root._y + root._h + G.my + Math.max(H(A), H(B)) / 2;
    const gap = G.x + 40;

    placeOut(A, -midW / 2 - gap, hubCy, -1);
    placeOut(B, midW / 2 + gap, hubCy, 1);

    let total = 0;
    shared.forEach((s, i) => { total += H(s) + (i ? G.y : 0); });
    let y = hubCy - total / 2;
    shared.forEach(s => {
      const sh = H(s);
      placeOut(s, -W(s) / 2, y + sh / 2, 1);
      y += sh + G.y;
    });
  }

  /* ── 8. 复流程图（左因右果） ── */
  function multiflow(root) {
    const H = heightFn(G.y);
    root._x = -root._w / 2;
    root._y = -root._h / 2;
    root._dir = 'r';

    const causes = root.children.filter(c => c.grp !== 'effect');
    const effects = root.children.filter(c => c.grp === 'effect');

    const block = (list, dir) => {
      if (!list.length) return;
      let total = 0;
      list.forEach((c, i) => { total += H(c) + (i ? G.y : 0); });
      let y = -total / 2;
      list.forEach(c => {
        const ch = H(c);
        const ax = dir > 0 ? root._x + root._w + G.x : root._x - G.x;
        placeDir(c, ax, y + ch / 2, dir, H, G.y);
        y += ch + G.y;
      });
    };
    block(causes, -1);
    block(effects, 1);
  }

  /* ── 连线 ── */
  function buildEdges(root, key) {
    const edges = [];
    const dots = [];

    if (key === 'timeline') {
      const ys = root._spineYs || [];
      const sx = root._spineX;
      const rcy = root._y + root._h / 2;
      if (ys.length) {
        const top = Math.min(...ys, rcy), bot = Math.max(...ys, rcy);
        edges.push({ x1: sx, y1: top, x2: sx, y2: bot, kind: 'line', w: 2, from: root.id, to: root.id });
        edges.push({ x1: root._x + root._w, y1: rcy, x2: sx, y2: rcy, kind: 'line', w: 2.4, from: root.id, to: root.id });
        ys.forEach(y => {
          dots.push({ x: sx, y, r: 4 });
          const c = root.children.find(cc => cc._spineY === y);
          if (c) edges.push({ x1: sx, y1: y, x2: c._x, y2: y, kind: 'line', w: 1.8, from: root.id, to: c.id });
        });
        // 子节点内部连线
        root.children.forEach(c => {
          if (c.collapsed) return;
          c.children.forEach(g => {
            const cy = c._y + c._h / 2, gy = g._y + g._h / 2;
            edges.push({ x1: c._x + c._w, y1: cy, x2: g._x, y2: gy, kind: 'h', w: 1.6, from: c.id, to: g.id });
          });
        });
      }
      return { edges, dots };
    }

    if (key === 'fishbone') {
      if ((root._bones || []).length) {
        edges.push({
          x1: root._spineStart, y1: root._y + root._h / 2,
          x2: root._x, y2: root._y + root._h / 2, kind: 'line', w: 2.6, from: root.id, to: root.id,
        });
      }
      (root._bones || []).forEach(b => {
        edges.push({ x1: b.attachX, y1: 0, x2: b.endX, y2: b.endY, kind: 'line', w: 2, from: root.id, to: b.c.id });
        dots.push({ x: b.attachX, y: 0, r: 3.5 });
        (b.c._subTicks || []).forEach((t, i) => {
          const sub = b.c.children[i];
          edges.push({ x1: t.x1, y1: t.y1, x2: t.x2, y2: t.y2, kind: 'line', w: 1.4, from: b.c.id, to: sub ? sub.id : b.c.id });
        });
      });
      return { edges, dots };
    }

    /* 圆圈图：中心到每个子节点画放射线，其余按水平走 */
    if (key === 'ring') {
      const rr = { x: root._x, y: root._y, w: root._w, h: root._h };
      const rc = { x: rr.x + rr.w / 2, y: rr.y + rr.h / 2 };
      root.children.forEach(c => {
        const p1 = rectAnchor(rr, c._x + c._w / 2, c._y + c._h / 2);
        const p2 = rectAnchor({ x: c._x, y: c._y, w: c._w, h: c._h }, rc.x, rc.y);
        edges.push({ x1: p1.x, y1: p1.y, x2: p2.x, y2: p2.y, kind: 'line', w: 2, from: root.id, to: c.id });
      });
      const walkR = (n) => {
        if (n.collapsed) return;
        n.children.forEach(c => {
          const rightSide = c._x > n._x;
          edges.push({
            x1: rightSide ? n._x + n._w : n._x, y1: n._y + n._h / 2,
            x2: rightSide ? c._x : c._x + c._w, y2: c._y + c._h / 2,
            kind: 'h', w: 1.8, from: n.id, to: c.id,
          });
          walkR(c);
        });
      };
      root.children.forEach(walkR);
      return { edges, dots };
    }

    /* 双气泡图：标题往下连两个中心与共同点，其余按水平走 */
    if (key === 'double') {
      const rcx = root._x + root._w / 2, rcy = root._y + root._h;
      const walkD = (n) => {
        if (n.collapsed) return;
        n.children.forEach(c => {
          const rightSide = c._x > n._x;
          edges.push({
            x1: rightSide ? n._x + n._w : n._x, y1: n._y + n._h / 2,
            x2: rightSide ? c._x : c._x + c._w, y2: c._y + c._h / 2,
            kind: 'h', w: 1.8, from: n.id, to: c.id,
          });
          walkD(c);
        });
      };
      root.children.forEach(c => {
        edges.push({
          x1: rcx, y1: rcy, x2: c._x + c._w / 2, y2: c._y,
          kind: 'v', w: 2.2, from: root.id, to: c.id,
        });
        walkD(c);
      });
      return { edges, dots };
    }

    const kind = key === 'org' ? 'v' : 'h';
    const walk = (n) => {
      if (n.collapsed) return;
      for (const c of n.children) {
        if (kind === 'v') {
          edges.push({ x1: n._x + n._w / 2, y1: n._y + n._h, x2: c._x + c._w / 2, y2: c._y, kind: 'v', w: n._depth === 0 ? 2.4 : 1.8, from: n.id, to: c.id });
        } else {
          const rightSide = c._x > n._x;
          const x1 = rightSide ? n._x + n._w : n._x;
          const x2 = rightSide ? c._x : c._x + c._w;
          edges.push({ x1, y1: n._y + n._h / 2, x2, y2: c._y + c._h / 2, kind: 'h', w: n._depth === 0 ? 2.4 : 1.8, from: n.id, to: c.id });
        }
        walk(c);
      }
    };
    walk(root);
    return { edges, dots };
  }

  /* ── 关系边（concept map 语义连线） ── */
  /* 从矩形中心朝目标点射出，返回与矩形边框的交点 */
  function rectAnchor(r, tx, ty) {
    const cx = r.x + r.w / 2, cy = r.y + r.h / 2;
    const dx = tx - cx, dy = ty - cy;
    if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5) return { x: cx, y: cy };
    const sx = dx ? (r.w / 2) / Math.abs(dx) : Infinity;
    const sy = dy ? (r.h / 2) / Math.abs(dy) : Infinity;
    const s = Math.min(sx, sy);
    return { x: cx + dx * s, y: cy + dy * s };
  }

  /* 点到矩形的距离（矩形向外扩 pad，让标签文字本身也算进去） */
  function distToRect(px, py, r, padX, padY) {
    const dx = Math.max(r.x - padX - px, 0, px - (r.x + r.w + padX));
    const dy = Math.max(r.y - padY - py, 0, py - (r.y + r.h + padY));
    return Math.hypot(dx, dy);
  }

  /* 相邻两条关系边交替向两侧弯曲，避免互相压线 */
  function buildLinks(byId, links) {
    const out = [];
    if (!links || !links.length) return out;
    const rects = [...byId.values()];
    const TS = [0.5, 0.42, 0.58, 0.34, 0.66, 0.26, 0.74];
    /* 投影模式下标签字更大，避让间距同步放大 */
    const K = Store.projector ? 1.7 : 1;
    const LFS = Store.projector ? 20 : 12.5;
    const LFONT = U.fontStr(LFS, 700);
    const LH2 = LFS * 0.72;                    // 标签半高
    const OFFS = [11, 22, 34, 48, 64].map(v => Math.round(v * K));

    links.forEach((l, i) => {
      const a = byId.get(l.from), b = byId.get(l.to);
      if (!a || !b) return;                       // 端点被折叠隐藏时整条隐藏
      const halfW = (l.label ? U.measure(l.label, LFONT) : 0) / 2 + 3;
      const ac = { x: a.x + a.w / 2, y: a.y + a.h / 2 };
      const bc = { x: b.x + b.w / 2, y: b.y + b.h / 2 };
      const p1 = rectAnchor(a, bc.x, bc.y);
      const p2 = rectAnchor(b, ac.x, ac.y);
      const dx = p2.x - p1.x, dy = p2.y - p1.y;
      const dist = Math.hypot(dx, dy) || 1;
      const bend = Math.min(54, dist * 0.22) * (i % 2 ? 1 : -1);
      const c = {
        x: (p1.x + p2.x) / 2 + (-dy / dist) * bend,
        y: (p1.y + p2.y) / 2 + (dx / dist) * bend,
      };

      /* 沿曲线找一处离所有节点最远的位置放标签：先换位置，再往法线方向外推 */
      let best = null;
      for (const t of TS) {
        const mt = 1 - t;
        const bx = mt * mt * p1.x + 2 * mt * t * c.x + t * t * p2.x;
        const by = mt * mt * p1.y + 2 * mt * t * c.y + t * t * p2.y;
        const tx = 2 * mt * (c.x - p1.x) + 2 * t * (p2.x - c.x);
        const ty = 2 * mt * (c.y - p1.y) + 2 * t * (p2.y - c.y);
        const tl = Math.hypot(tx, ty) || 1;
        for (const off of OFFS) {
          const lx = bx + (-ty / tl) * off;
          const ly = by + (tx / tl) * off;
          let score = Infinity;
          for (const r of rects) {
            const d = distToRect(lx, ly, r, halfW, LH2);
            if (d < score) score = d;
          }
          if (!best || score > best.score) best = { x: lx, y: ly, score };
          if (score > 6) break;            // 已经完全离开节点，不用再往外推
        }
      }

      out.push({
        id: l.id, from: l.from, to: l.to, label: l.label || '',
        p1, c, p2, lx: best.x, ly: best.y,
        ang: Math.atan2(p2.y - c.y, p2.x - c.x),
      });
    });
    return out;
  }

  function linkPath(l) {
    return `M${l.p1.x} ${l.p1.y}Q${l.c.x} ${l.c.y} ${l.p2.x} ${l.p2.y}`;
  }

  /* ── 主入口 ── */
  function compute(root, opts) {
    const key = opts.layout || 'logical';
    const k = Store.projector ? 1.55 : 1;   // 投影模式下节点更大，间距同步放大
    G.x = 62 * k; G.y = 18 * k; G.mx = 46 * k; G.my = 56 * k; G.sp = 38 * k;
    measureAll(root);

    if (key === 'mindmap') mindmap(root);
    else if (key === 'org') org(root);
    else if (key === 'timeline') timeline(root);
    else if (key === 'fishbone') fishbone(root);
    else if (key === 'ring') ring(root);
    else if (key === 'double') double(root);
    else if (key === 'multiflow') multiflow(root);
    else logical(root);

    const { edges, dots } = buildEdges(root, key);

    // 可见节点
    const list = [];
    (function collect(n) {
      list.push(n);
      if (!n.collapsed) n.children.forEach(collect);
    })(root);

    // 关系边先按未平移坐标算，便于参与包围盒计算
    const preMap = new Map();
    list.forEach(n => preMap.set(n.id, { x: n._x, y: n._y, w: n._w, h: n._h }));
    const preLinks = buildLinks(preMap, Store.links);

    // 归一化
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    list.forEach(n => {
      minX = Math.min(minX, n._x); minY = Math.min(minY, n._y);
      maxX = Math.max(maxX, n._x + n._w); maxY = Math.max(maxY, n._y + n._h);
    });
    edges.forEach(e => {
      minX = Math.min(minX, e.x1, e.x2); maxX = Math.max(maxX, e.x1, e.x2);
      minY = Math.min(minY, e.y1, e.y2); maxY = Math.max(maxY, e.y1, e.y2);
    });
    const LW = Store.projector ? 96 : 58, LH = Store.projector ? 22 : 14;
    preLinks.forEach(l => {
      minX = Math.min(minX, l.c.x, l.lx - LW); maxX = Math.max(maxX, l.c.x, l.lx + LW);
      minY = Math.min(minY, l.c.y, l.ly - LH); maxY = Math.max(maxY, l.c.y, l.ly + LH);
    });
    if (!isFinite(minX)) { minX = minY = 0; maxX = maxY = 200; }

    const ox = PAD - minX, oy = PAD - minY;

    const nodes = list.map(n => ({
      id: n.id,
      node: n,
      x: n._x + ox,
      y: n._y + oy,
      w: n._w,
      h: n._h,
      depth: n._depth,
      dir: n._dir || 'r',
      collapsed: !!n.collapsed,
      hasChildren: n.children.length > 0,
      childCount: n.children.length,
      lines: n._lines,
      style: n._style,
      font: n._font,
      lh: n._lh,
    }));

    edges.forEach(e => { e.x1 += ox; e.x2 += ox; e.y1 += oy; e.y2 += oy; });
    dots.forEach(d => { d.x += ox; d.y += oy; });

    const links = preLinks.map(l => {
      const o = {
        id: l.id, from: l.from, to: l.to, label: l.label,
        p1: { x: l.p1.x + ox, y: l.p1.y + oy },
        c: { x: l.c.x + ox, y: l.c.y + oy },
        p2: { x: l.p2.x + ox, y: l.p2.y + oy },
        lx: l.lx + ox, ly: l.ly + oy, ang: l.ang,
      };
      o.d = linkPath(o);
      return o;
    });

    const result = {
      layout: key,
      nodes,
      edges,
      dots,
      links,
      bounds: {
        minX: 0, minY: 0,
        width: Math.ceil(maxX - minX + PAD * 2),
        height: Math.ceil(maxY - minY + PAD * 2),
      },
      byId: new Map(nodes.map(n => [n.id, n])),
      linkById: new Map(links.map(l => [l.id, l])),
    };
    current = result;
    return result;
  }

  function edgePath(e, style) {
    const { x1, y1, x2, y2, kind } = e;
    if (kind === 'line') return `M${x1} ${y1}L${x2} ${y2}`;
    const horiz = kind === 'h';
    if (style === 'elbow') {
      if (horiz) {
        const mx = (x1 + x2) / 2;
        const dy = Math.sign(y2 - y1);
        if (Math.abs(y2 - y1) < 1.2) return `M${x1} ${y1}L${x2} ${y2}`;
        const r = Math.min(12, Math.abs(y2 - y1) / 2, Math.abs(x2 - x1) / 2);
        return `M${x1} ${y1}L${mx - r} ${y1}Q${mx} ${y1} ${mx} ${y1 + dy * r}L${mx} ${y2 - dy * r}Q${mx} ${y2} ${mx + r} ${y2}L${x2} ${y2}`;
      }
      const my = (y1 + y2) / 2;
      const dx = Math.sign(x2 - x1);
      if (Math.abs(x2 - x1) < 1.2) return `M${x1} ${y1}L${x2} ${y2}`;
      const r = Math.min(12, Math.abs(x2 - x1) / 2, Math.abs(y2 - y1) / 2);
      return `M${x1} ${y1}L${x1} ${my - r}Q${x1} ${my} ${x1 + dx * r} ${my}L${x2 - dx * r} ${my}Q${x2} ${my} ${x2} ${my + r}L${x2} ${y2}`;
    }
    if (horiz) {
      const dx = (x2 - x1) * 0.5;
      return `M${x1} ${y1}C${x1 + dx} ${y1} ${x2 - dx} ${y2} ${x2} ${y2}`;
    }
    const dy = (y2 - y1) * 0.5;
    return `M${x1} ${y1}C${x1} ${y1 + dy} ${x2} ${y2 - dy} ${x2} ${y2}`;
  }

  return {
    compute, edgePath, linkPath, measureAll,
    get current() { return current; },
  };
})();
