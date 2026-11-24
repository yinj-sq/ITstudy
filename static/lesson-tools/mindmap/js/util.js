/* ============================================================
   util.js — 文本测量、换行、通用小工具
   ============================================================ */
const U = (() => {
  const FONT_STACK = '"PingFang SC","Hiragino Sans GB","Microsoft YaHei",system-ui,-apple-system,"Segoe UI",sans-serif';
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');

  const fontStr = (size, weight) => `${weight} ${size}px ${FONT_STACK}`;

  function measure(text, font) {
    ctx.font = font;
    return ctx.measureText(text).width;
  }

  const CJK = /[\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef\u3000-\u303f\u2010-\u201f]/;
  const NO_LEAD = /[，。、；：？！）】》”’%]/; // 不能出现在行首

  function tokenize(str) {
    const out = [];
    let buf = '';
    for (const ch of str) {
      if (ch === ' ') { if (buf) { out.push(buf); buf = ''; } out.push(' '); continue; }
      if (CJK.test(ch)) { if (buf) { out.push(buf); buf = ''; } out.push(ch); continue; }
      buf += ch;
    }
    if (buf) out.push(buf);
    return out;
  }

  /** 按宽度换行，返回行数组 */
  function wrap(text, maxWidth, font) {
    const paras = String(text == null ? '' : text).split('\n');
    const lines = [];
    for (const p of paras) {
      if (p === '') { lines.push(''); continue; }
      const tokens = tokenize(p);
      let cur = '';
      for (let t of tokens) {
        // 超长单词按字符硬拆
        if (cur === '' && measure(t, font) > maxWidth && t.length > 1) {
          let piece = '';
          for (const ch of t) {
            if (measure(piece + ch, font) > maxWidth && piece) {
              lines.push(piece); piece = ch;
            } else piece += ch;
          }
          cur = piece;
          continue;
        }
        if (cur === '') { cur = t === ' ' ? '' : t; continue; }
        if (measure(cur + t, font) <= maxWidth) cur += t;
        else {
          // 行首禁则：把标点拉到上一行
          if (NO_LEAD.test(t) && cur.length > 1) { lines.push(cur + t); cur = ''; }
          else { lines.push(cur); cur = t === ' ' ? '' : t; }
        }
      }
      if (cur !== '') lines.push(cur);
      else if (lines.length === 0 || paras.length === 1) { /* 空行已处理 */ }
    }
    return lines.length ? lines : [''];
  }

  let seed = 0;
  const uid = () => 'n' + (Date.now().toString(36).slice(-5)) + (seed++).toString(36) + Math.random().toString(36).slice(2, 5);

  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const lerp = (a, b, t) => a + (b - a) * t;

  function el(tag, cls, html) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }

  function download(blob, name) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
  }

  function roundRect(ctx2, x, y, w, h, r) {
    const rr = Math.min(r, w / 2, h / 2);
    ctx2.beginPath();
    ctx2.moveTo(x + rr, y);
    ctx2.arcTo(x + w, y, x + w, y + h, rr);
    ctx2.arcTo(x + w, y + h, x, y + h, rr);
    ctx2.arcTo(x, y + h, x, y, rr);
    ctx2.arcTo(x, y, x + w, y, rr);
    ctx2.closePath();
  }

  return { FONT_STACK, fontStr, measure, wrap, uid, clamp, lerp, el, download, roundRect };
})();
