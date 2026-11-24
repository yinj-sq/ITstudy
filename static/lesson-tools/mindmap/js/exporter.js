/* ============================================================
   exporter.js — 导出 PNG / JSON
   ============================================================ */
const Exporter = (() => {

  function drawArrow(ctx, x, y, ang, color) {
    const L = 7.5, W = 3.4;
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(ang);
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.lineTo(-L, -W);
    ctx.lineTo(-L, W);
    ctx.closePath();
    ctx.fillStyle = color;
    ctx.fill();
    ctx.restore();
  }

  function esc(s) {
    return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  /* 打印用配色：白底省墨；深色主题整体换成墨白，保证纸上可读 */
  function printTheme() {
    const t = THEMES[Store.theme] || THEMES.paper;
    const h = t.canvas.replace('#', '');
    const lum = 0.299 * parseInt(h.slice(0, 2), 16) +
                0.587 * parseInt(h.slice(2, 4), 16) +
                0.114 * parseInt(h.slice(4, 6), 16);
    if (lum < 140) return THEMES.mono;
    return Object.assign({}, t, { canvas: '#ffffff' });
  }

  function buildCanvas(scale = 2, opts = {}) {
    const res = Layout.current;
    if (!res) return null;
    const t = opts.print ? printTheme() : (THEMES[Store.theme] || THEMES.paper);

    const PAD = 56;
    const HEAD = (Store.title && !opts.noTitle) ? 54 : 0;
    const rawW = res.bounds.width + PAD * 2;
    const rawH = res.bounds.height + PAD * 2 + HEAD;

    /* Canvas 有硬上限：Safari 单边 16384，Chrome 单边 65535 / 总面积约 2.68 亿像素。
       超过之后 toBlob 会静默返回 null（不是报错），用户拿到一个空文件。
       先按 16000px / 6400 万像素反算缩放，宁可整体缩小，也不要导出失败。 */
    const MAX_SIDE = 16000, MAX_AREA = 64e6;
    const s = Math.max(0.08, Math.min(
      scale,
      MAX_SIDE / rawW,
      MAX_SIDE / rawH,
      Math.sqrt(MAX_AREA / (rawW * rawH)),
    ));

    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.floor(rawW * s));
    canvas.height = Math.max(1, Math.floor(rawH * s));
    canvas._fitScale = s;
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    ctx.scale(s, s);

    // 背景
    ctx.fillStyle = t.canvas;
    ctx.fillRect(0, 0, rawW, rawH);

    // 标题
    if (HEAD) {
      const lv2 = t.levels[Math.min(2, t.levels.length - 1)];
      ctx.globalAlpha = 0.55;
      ctx.fillStyle = lv2.fg;
      ctx.font = `600 16px ${U.FONT_STACK}`;
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      ctx.fillText(Store.title, PAD, PAD + 14);
      ctx.globalAlpha = 1;
    }

    ctx.translate(PAD, PAD + HEAD);

    // 连线
    ctx.strokeStyle = t.line;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    for (const e of res.edges) {
      ctx.lineWidth = e.w;
      ctx.stroke(new Path2D(Layout.edgePath(e, Store.lineStyle)));
    }

    // 圆点
    for (const d of res.dots) {
      ctx.beginPath();
      ctx.arc(d.x, d.y, d.r, 0, Math.PI * 2);
      ctx.fillStyle = t.line;
      ctx.fill();
    }

    // 关系边：虚线 + 箭头 + 关系词
    const relColor = t.levels[0].bg;
    if (res.links && res.links.length) {
      ctx.save();
      ctx.setLineDash([6, 4]);
      ctx.lineWidth = 1.6;
      ctx.strokeStyle = relColor;
      for (const l of res.links) {
        ctx.stroke(new Path2D(l.d));
        drawArrow(ctx, l.p2.x, l.p2.y, l.ang, relColor);
      }
      ctx.restore();

      ctx.font = `600 11px ${U.FONT_STACK}`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.lineWidth = 3.5;
      ctx.strokeStyle = t.canvas;
      for (const l of res.links) {
        if (!l.label) continue;
        ctx.strokeText(l.label, l.lx, l.ly);
      }
      ctx.fillStyle = relColor;
      for (const l of res.links) {
        if (!l.label) continue;
        ctx.fillText(l.label, l.lx, l.ly);
      }
    }

    // 节点
    for (const rec of res.nodes) {
      const ls = t.levels[Math.min(rec.depth, t.levels.length - 1)];
      const st = rec.style;

      U.roundRect(ctx, rec.x, rec.y, rec.w, rec.h, st.radius);
      ctx.fillStyle = ls.bg;
      ctx.fill();
      if (ls.border && ls.border !== 'transparent') {
        ctx.strokeStyle = ls.border;
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }

      ctx.fillStyle = ls.fg;
      ctx.font = rec.font;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      const baseY = rec.y + st.padY;

      // 学案版：非中心节点的文字留空，画一条待填虚线
      if (opts.blank && rec.depth > 0) {
        const cx = rec.x + rec.w / 2, cy = rec.y + rec.h / 2;
        const lw = Math.min(rec.w - st.padX * 2, 76);
        ctx.save();
        ctx.globalAlpha = 0.4;
        ctx.strokeStyle = ls.fg;
        ctx.lineWidth = 1.6;
        ctx.setLineDash([5, 5]);
        ctx.beginPath();
        ctx.moveTo(cx - lw / 2, cy);
        ctx.lineTo(cx + lw / 2, cy);
        ctx.stroke();
        ctx.restore();
        continue;
      }

      rec.lines.forEach((line, i) => {
        if (!line) return;
        ctx.fillText(line, rec.x + rec.w / 2, baseY + i * rec.lh + rec.lh / 2 + 0.5);
      });
    }

    return canvas;
  }

  function exportPNG() {
    const canvas = buildCanvas(2);
    if (!canvas) { App.toast('导出失败：没有可导出的内容'); return; }
    canvas.toBlob(blob => {
      if (!blob) { App.toast('导出失败：图太大，先拆成两张再导'); return; }
      const name = (Store.title || '思维导图').replace(/[\\/:*?"<>|]/g, '_');
      U.download(blob, `${name}.png`);
      App.toast(canvas._fitScale < 0.999 ? '图太大，已按比例缩小导出' : '图片已导出');
    }, 'image/png');
  }

  /* 学案版：所有分支文字留空，打印给学生填（固定按常规字号，不受投影模式影响） */
  function exportWorksheet() {
    const wasProj = Store.projector;
    if (wasProj) { Store.projector = false; Renderer.render(); }
    const canvas = buildCanvas(2, { blank: true, print: true });
    if (wasProj) { Store.projector = true; Renderer.render(); }
    if (!canvas) return;
    canvas.toBlob(blob => {
      if (!blob) { App.toast('学案生成失败：图太大，先拆成两张'); return; }
      const name = (Store.title || '思维导图').replace(/[\\/:*?"<>|]/g, '_');
      U.download(blob, `${name}-学案.png`);
      App.toast(canvas._fitScale < 0.999 ? '图太大，学案已缩小；建议拆图后打印' : '学案已导出，可直接打印');
    }, 'image/png');
  }

  /* 打印：mode = 'blank'（学生学案，文字留空）| 'full'（教师版） */
  function printSheet(mode) {
    const wasProj = Store.projector;
    if (wasProj) { Store.projector = false; Renderer.render(); }
    const canvas = buildCanvas(3, { blank: mode === 'blank', noTitle: true, print: true });
    if (wasProj) { Store.projector = true; Renderer.render(); }
    if (!canvas) return;

    // 按画布长宽比自动选横版或竖版，尽量占满纸张
    const portrait = canvas.height > canvas.width * 1.05;
    let st = document.getElementById('printPageCss');
    if (!st) {
      st = document.createElement('style');
      st.id = 'printPageCss';
      document.head.appendChild(st);
    }
    st.textContent =
      `@page{size:A4 ${portrait ? 'portrait' : 'landscape'};margin:10mm}` +
      /* A4 去掉 10mm 页边距后的可用高度：竖版 277mm、横版 190mm。
         页眉约 11mm、页脚约 5mm，图片上限必须留出这部分，否则会溢出到第 2 页。
         旧值 244/176 在横版下必出两页（176+16 > 190）。 */
      `#printArea .ps-img img{max-height:${portrait ? 235 : 155}mm}`;

    const url = canvas.toDataURL('image/png');
    if (!url || url.length < 100) {
      App.toast('打印图生成失败：图太大，先拆成两张');
      return;
    }
    const title = esc(Store.title || '思维导图');
    const area = document.getElementById('printArea');
    area.innerHTML =
      '<div class="ps-page">' +
        '<div class="ps-head">' +
          '<h1>' + title + '</h1>' +
          '<div class="ps-meta"><span>姓名 <i></i></span><span>班级 <i></i></span><span>日期 <i></i></span></div>' +
        '</div>' +
        '<div class="ps-img"><img src="' + url + '" alt="' + title + '"></div>' +
        '<div class="ps-foot">' + (mode === 'blank'
          ? '先自己回忆，再对照导图补全空白处。'
          : '教师版：可直接投影或作为板书参考。') + '</div>' +
      '</div>';
    App.toast(mode === 'blank' ? '已生成学案，正在打开打印…' : '正在打开打印…');
    /* data URL 图片不一定在 80ms 内解码完；大图直接 print 会印出空白。
       等图片 onload 再打开打印预览。 */
    const img = area.querySelector('.ps-img img');
    const go = () => setTimeout(() => window.print(), 40);
    if (img && !img.complete) img.addEventListener('load', go, { once: true });
    else go();
  }

  function exportJSON() {
    const data = JSON.stringify(Store.toJSON(), null, 2);
    const blob = new Blob([data], { type: 'application/json' });
    const name = (Store.title || '思维导图').replace(/[\\/:*?"<>|]/g, '_');
    U.download(blob, `${name}.json`);
    App.toast('备份文件已导出');
  }

  function importJSON(file) {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const doc = JSON.parse(reader.result);
        if (Store.setDoc(doc)) App.toast('文件已导入');
        else App.toast('文件格式不正确');
      } catch (e) {
        App.toast('文件解析失败');
      }
    };
    reader.readAsText(file);
  }

  return { buildCanvas, exportPNG, exportWorksheet, printSheet, exportJSON, importJSON };
})();
