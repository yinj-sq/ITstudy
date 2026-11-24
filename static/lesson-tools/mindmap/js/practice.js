/* ============================================================
   practice.js — 学生自测模式
   ============================================================
   老师点顶栏「自测」，或者打开 index.html?practice=1，界面换成学生端：
   一张遮住的图 + 一条答题条。学生先自己回忆、写下答案，再对答案，
   然后自评「答对了 / 没答上」，全部答完出结果。

   两个设计决定：

   1. 自评而不是自动判分。中文表述千变万化，「细胞核」和「细胞核结构」
      算不算对，机器判不了。相似度只用来给一句提示（「很接近」），
      不做判分依据——判分权交给学生，这也正是元认知训练要的东西。

   2. 不是另开一个页面，而是同一份 HTML 换一套外壳。老师的文档、主题、
      结构原样带过来，学生不用重新导入，老师也不用重新准备。
   ============================================================ */
const Practice = (() => {
  let active = false;
  let seq = [];                 // 题目顺序（节点 id）
  let cur = 0;                  // 当前第几题
  let phase = 'ask';            // 'ask' 待作答 | 'revealed' 已看答案待自评
  let results = new Map();      // id -> { ok, input }
  let idx = new Map();          // id -> { text, depth, parentText }
  /* 由 app.js 注入，避免本模块依赖 app.js 的局部函数 */
  let onToast = () => {};
  let onAnnounce = () => {};
  let stash = null;             // 打开别人的练习链接前，先把学生自己那份存起来

  const $ = id => document.getElementById(id);
  const esc = s => String(s == null ? '' : s)
    .replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  /* ── 相似度：只做提示，不做判分 ── */
  function norm(s) {
    return String(s == null ? '' : s)
      .toLowerCase()
      .replace(/[\s\u3000]/g, '')
      .replace(/[，。、；：！？,.;:!?"'“”‘’()（）\[\]【】《》<>·…—-]/g, '');
  }

  function similarity(a, b) {
    const x = norm(a), y = norm(b);
    if (!x || !y) return 0;
    if (x === y) return 1;
    const short = x.length <= y.length ? x : y;
    const long = x.length <= y.length ? y : x;
    if (long.indexOf(short) >= 0) {
      return 0.7 + 0.3 * (short.length / long.length);
    }
    /* 一两个字的答案（「水」「细胞」）没有 bigram，退回字符交集 */
    if (long.length <= 2) {
      const set = new Set(long.split(''));
      let hit = 0;
      new Set(short.split('')).forEach(c => { if (set.has(c)) hit++; });
      return (hit / set.size) * 0.6;
    }
    const grams = s => {
      const m = new Map();
      for (let i = 0; i < s.length - 1; i++) {
        const g = s.slice(i, i + 2);
        m.set(g, (m.get(g) || 0) + 1);
      }
      return m;
    };
    const gx = grams(x), gy = grams(y);
    let inter = 0, tot = 0;
    gx.forEach((n, g) => { tot += n; if (gy.has(g)) inter += Math.min(n, gy.get(g)); });
    gy.forEach(n => { tot += n; });
    return tot ? (2 * inter) / tot : 0;
  }

  function simTip(input, answer, sim) {
    if (!norm(input)) return '没写也没关系，先看答案';
    if (sim >= 0.85) return '几乎一样';
    if (sim >= 0.6) return '很接近';
    if (sim >= 0.35) return '有点接近，再想想差别在哪';
    return '和答案差别比较大';
  }

  /* ── 题目顺序 ── */
  function buildIndex() {
    idx = new Map();
    /* 兄弟信息要单独收集：Store.walk 只给 parent 对象，给不出「我是第几个」。
       这三个字段是题面的线索——回忆时线索越接近当初编码时的情境越好提取，
       但只给位置和数量，不给兄弟节点的文字（那是别的题的答案）。 */
    const kids = new Map();
    Store.walk((n, d, p) => {
      idx.set(n.id, {
        text: (n.text || '').trim(),
        depth: d,
        parentText: p ? (p.text || '').trim() : '',
        sibIdx: 0,
        sibCount: 1,
      });
      if (p) {
        if (!kids.has(p.id)) kids.set(p.id, []);
        kids.get(p.id).push(n.id);
      }
    });
    kids.forEach(list => list.forEach((id, i) => {
      const e = idx.get(id);
      if (e) { e.sibIdx = i + 1; e.sibCount = list.length; }
    }));
  }

  function makeSeq(ids) {
    if (ids && ids.length) return ids.slice();
    const all = [];
    Store.walk((n, d) => { if (d > 0) all.push({ id: n.id, d }); });
    /* 同层打乱、层间保序：先骨架后细节，但每一层的顺序每次不同，
       避免第二次练的时候记住的是「第几个是哪个」而不是内容。 */
    const groups = new Map();
    all.forEach(r => {
      if (!groups.has(r.d)) groups.set(r.d, []);
      groups.get(r.d).push(r.id);
    });
    const out = [];
    [...groups.keys()].sort((a, b) => a - b).forEach(d => {
      const g = groups.get(d);
      for (let i = g.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        const t = g[i]; g[i] = g[j]; g[j] = t;
      }
      out.push.apply(out, g);
    });
    return out;
  }

  /* ── 高亮当前题 ── */
  function paintCur() {
    document.querySelectorAll('#nodes .node.cur-q').forEach(e => e.classList.remove('cur-q'));
    const id = seq[cur];
    if (!id) return;
    const el = document.querySelector('#nodes .node[data-id="' + id + '"]');
    if (el) el.classList.add('cur-q');
  }

  /* 把镜头框到「这一格 + 它的父节点 + 直接下级」。
     父节点一定要在画面里：整张图被遮住时，学生唯一能推理的线索就是它挂在谁下面。 */
  function frameCur(animate) {
    const id = seq[cur];
    if (!id) return;
    const ids = [id];
    const p = Store.parentOf(id);
    if (p) ids.push(p.id);
    const node = Store.find(id);
    if (node && !node.collapsed) (node.children || []).forEach(c => ids.push(c.id));
    const narrow = window.innerWidth < 620;
    Renderer.frameIds(ids, {
      animate: !!animate,
      bottom: narrow ? 150 : 120,     // 让开底部答题条
      padX: narrow ? 20 : 56,
      padY: 40,
      min: narrow ? 0.62 : 0.5,
      max: 1.15,
    });
  }

  /* ── 渲染一题 ── */
  function paint() {
    if (cur >= seq.length) { finish(); return; }
    const id = seq[cur];
    const info = idx.get(id) || {};
    $('pqIdx').textContent = '第 ' + (cur + 1) + ' / ' + seq.length + ' 题';
    /* 三条线索，按强弱排：挂在谁下面 > 同层第几个 > 第几层。
       窄屏会被截断，所以最有用的一条放最前。 */
    const cues = [];
    if (info.parentText) cues.push('挂在「' + info.parentText + '」下面');
    if (info.sibCount > 1) cues.push('同层第 ' + info.sibIdx + ' / ' + info.sibCount + ' 个');
    if (info.depth) cues.push('第 ' + info.depth + ' 层');
    $('pqCtx').textContent = cues.join(' · ');
    const inp = $('pqInput');
    inp.value = '';
    inp.disabled = false;
    $('pqCheck').hidden = false;
    $('pqAns').hidden = true;
    $('phProg').textContent = cur + ' / ' + seq.length;
    phase = 'ask';
    paintCur();
    frameCur(true);
  }

  /* ── 对答案 ── */
  function check() {
    if (!active || phase !== 'ask' || cur >= seq.length) return;
    const id = seq[cur];
    const answer = (idx.get(id) || {}).text || '';
    const input = $('pqInput').value;
    Store.reveal(id);                      // 会触发 render，节点显示出来
    $('pqAnsText').textContent = answer || '（这一格是空的）';
    $('pqSim').textContent = simTip(input, answer, similarity(input, answer));
    $('pqAns').hidden = false;
    $('pqInput').disabled = true;
    $('pqCheck').hidden = true;
    phase = 'revealed';
    paintCur();                            // render 重建了节点元素，类要补回去
    setTimeout(() => { const b = $('pqOk'); if (b) b.focus(); }, 30);
  }

  /* ── 自评 ── */
  function judge(ok) {
    if (!active || phase !== 'revealed') return;
    results.set(seq[cur], { ok: !!ok, input: $('pqInput').value });
    cur++;
    if (cur >= seq.length) { finish(); return; }
    paint();
    setTimeout(() => { const i = $('pqInput'); if (i) i.focus(); }, 30);
  }

  /* ── 结果 ── */
  function finish() {
    const total = seq.length;
    let right = 0;
    const wrong = [];
    seq.forEach(id => {
      const r = results.get(id);
      if (r && r.ok) right++;
      else wrong.push(id);
    });
    const rate = total ? Math.round((right / total) * 100) : 0;

    $('practiceBar').hidden = true;
    $('phProg').textContent = right + ' / ' + total;
    $('prNum').textContent = right + ' / ' + total;
    $('prRate').textContent = '正确率 ' + rate + '%';
    $('prWrong').innerHTML = wrong.length
      ? '<p>没答上的 ' + wrong.length + ' 个，可以单独再练一遍：</p>' +
        wrong.map(id => '<i>' + esc((idx.get(id) || {}).text || '空节点') + '</i>').join('')
      : '<p>全对了。合上屏幕，试着把这张图口述一遍——能讲出来才算真的记住。</p>';
    $('prWrongOnly').hidden = !wrong.length;
    $('practiceResult').classList.add('show');
    setTimeout(() => { const b = $('prAgain'); if (b) b.focus(); }, 60);
    onAnnounce('自测完成，答对 ' + right + ' 个，共 ' + total + ' 个');
  }

  /* 编码：JSON → UTF-8 → deflate-raw → base64url，前面加一位版本标记
     （1 = 压过，0 = 没压，留给不支持 CompressionStream 的浏览器）。

     载荷是压过的紧凑格式，不是 toJSON 原样：节点只留「文字 + 子节点」，
     关系边用「0.2.1」这种路径指代端点。节点 id 是随机串，一个节点要吃掉
     三四十个字符，全带上链接会长一倍多，而微信里发链接是会被截断的。 */
  const b64u = {
    enc(bytes) {
      let s = '';
      for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
      return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    },
    dec(str) {
      const s = str.replace(/-/g, '+').replace(/_/g, '/');
      const bin = atob(s + '='.repeat((4 - (s.length % 4)) % 4));
      const out = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
      return out;
    },
  };

  async function pipe(bytes, fmt, mode) {
    const Ctor = mode === 'zip' ? window.CompressionStream : window.DecompressionStream;
    if (typeof Ctor === 'undefined') return null;
    try {
      const cs = new Ctor(fmt);
      const w = cs.writable.getWriter();
      w.write(bytes);
      w.close();
      return new Uint8Array(await new Response(cs.readable).arrayBuffer());
    } catch (e) { return null; }
  }

  function packNode(n) {
    return [n.text || '', (n.children || []).map(packNode)];
  }

  function unpackNode(a, p, out) {
    const node = { id: 'pn' + out.n++, text: a[0] || '', children: [] };
    out.paths.set(p, node.id);
    (a[1] || []).forEach((c, i) => node.children.push(unpackNode(c, p ? p + '.' + i : String(i), out)));
    return node;
  }

  async function encodeDoc() {
    const d = Store.toJSON();
    /* 投影、挖空是老师的现场状态，不跟着链接走；
       collapsed 也丢掉——练习时缩着的分支等于没出题 */
    const paths = new Map();
    (function walkP(n, p) {
      paths.set(n.id, p);
      (n.children || []).forEach((c, i) => walkP(c, p ? p + '.' + i : String(i)));
    })(d.root, '');
    const payload = {
      v: 2, t: d.title, l: d.layout, th: d.theme, ls: d.lineStyle,
      r: packNode(d.root),
      k: (d.links || []).map(l => {
        const a = paths.get(l.from), b = paths.get(l.to);
        return (a == null || b == null) ? null : [a, b, l.label || ''];
      }).filter(Boolean),
    };
    const bytes = new TextEncoder().encode(JSON.stringify(payload));
    const z = await pipe(bytes, 'deflate-raw', 'zip');
    return z ? '1' + b64u.enc(z) : '0' + b64u.enc(bytes);
  }

  async function decodeDoc(code) {
    let bytes = b64u.dec(code.slice(1));
    if (code[0] === '1') {
      const out = await pipe(bytes, 'deflate-raw', 'unzip');
      if (!out) throw new Error('inflate failed');
      bytes = out;
    }
    const o = JSON.parse(new TextDecoder().decode(bytes));
    if (!o || !o.root && !o.r) throw new Error('bad payload');

    /* 老格式（v1，节点带 id）：原样用 */
    if (o.root) {
      return {
        root: o.root, links: o.links || [], title: o.title || '练习',
        layout: o.layout, theme: o.theme, lineStyle: o.lineStyle,
        projector: false, blank: false,
      };
    }

    const out = { n: 0, paths: new Map() };
    const root = unpackNode(o.r, '', out);
    const links = (o.k || []).map(t => {
      const from = out.paths.get(t[0]), to = out.paths.get(t[1]);
      if (!from || !to) return null;
      return { id: 'pl' + out.n++, from, to, label: t[2] || '关联' };
    }).filter(Boolean);
    return {
      root, links, title: o.t || '练习', layout: o.l, theme: o.th, lineStyle: o.ls,
      projector: false, blank: false,
    };
  }

  async function buildLink() {
    const code = await encodeDoc();
    return location.origin + location.pathname + '?p=' + code;
  }

  /* 复制到剪贴板。file:// 下 navigator.clipboard 常常直接不存在，
     所以必须有 execCommand 这条退路，不能只写一句 catch 就算完。 */
  function legacyCopy(text) {
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.cssText = 'position:fixed;top:-1000px;left:0;opacity:0';
      document.body.appendChild(ta);
      ta.select();
      ta.setSelectionRange(0, text.length);
      const ok = document.execCommand('copy');
      document.body.removeChild(ta);
      return ok;
    } catch (e) { return false; }
  }

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(() => true, () => legacyCopy(text));
    }
    return Promise.resolve(legacyCopy(text));
  }

  /* 链接是相对当前地址生成的：
       file:// 指向老师这台电脑上的文件，127.0.0.1/localhost 指向老师本机。
     这两种地址发给学生都打不开。本机地址仍然允许复制（老师可能要在同一台机器上预览），
     但必须把「学生打不开」说在前面，不能只说复制成功。 */
  function shareWarning() {
    if (location.protocol === 'file:') {
      return '现在双击打开的链接只指向你这台电脑，学生打不开。把整个文件夹发给学生，或用局域网地址打开后再复制。';
    }
    const h = (location.hostname || '').toLowerCase();
    if (h === 'localhost' || h === '127.0.0.1' || h === '::1' || h === '[::1]') {
      return '已复制，但这是本机地址，学生打不开；要发给学生请换成局域网地址或服务器地址。';
    }
    return '';
  }

  /* 链接里带不了几千个节点，超了就明说，别给一个打不开的短链 */
  async function copyLink() {
    const warning = shareWarning();
    if (location.protocol === 'file:') { onToast(warning); return; }
    let url;
    try {
      url = await buildLink();
    } catch (e) {
      onToast('生成链接失败');
      return;
    }
    if (url.length > 60000) {
      onToast('这张图太大，链接装不下。拆成两张图，或改用导出图片 / 打印学案。');
      return;
    }
    if (await copyText(url)) {
      onToast(warning || '自测链接已复制，发给学生就能直接做');
    } else {
      window.prompt('复制这个链接发给学生：', url);
    }
  }

  /* ── 开关 ── */
  function start(ids) {
    buildIndex();
    seq = makeSeq(ids);
    if (!seq.length) {
      onToast('这张图还没有分支，先加点内容再练');
      return;
    }
    cur = 0;
    results = new Map();
    phase = 'ask';
    active = true;
    document.body.classList.add('practicing');
    Store.toggleBlank(true);
    $('practiceHead').hidden = false;
    $('practiceBar').hidden = false;
    $('practiceResult').classList.remove('show');
    $('phTitle').textContent = Store.title || '自测';
    Renderer.render();
    Renderer.fit(false);        // 先摆一个全景，paint() 里再框到第一题
    paint();
    setTimeout(() => { const i = $('pqInput'); if (i) i.focus(); }, 80);
    onAnnounce('开始自测，共 ' + seq.length + ' 题');
  }

  function stop() {
    if (!active) return;
    active = false;
    document.body.classList.remove('practicing');
    $('practiceHead').hidden = true;
    $('practiceBar').hidden = true;
    $('practiceResult').classList.remove('show');
    Store.toggleBlank(false);
    /* 从别人的链接进来的，退出时换回学生自己那份文档，
       免得他一抬头发现自己的图不见了。
       noHistory：退出后留在撤销栈里的不该是「练习图」，否则 Ctrl+Z 会把别人的图又撤回来。 */
    if (stash) {
      Store.setDoc(stash, { noHistory: true });
      stash = null;
    }
    Renderer.render();
    Renderer.fit(true);
    /* 从链接进来的，退出时把参数抹掉，免得刷新又进练习 */
    if (/[?&](practice=1|p=)/.test(location.search)) {
      try { history.replaceState(null, '', location.pathname); } catch (e) { /* file:// 下可能不让改，忽略 */ }
    }
  }

  function retryWrong() {
    const wrong = seq.filter(id => {
      const r = results.get(id);
      return !r || !r.ok;
    });
    $('practiceResult').classList.remove('show');
    $('practiceBar').hidden = false;
    start(wrong);
  }

  function bind() {
    const on = (id, fn) => { const el = $(id); if (el) el.onclick = fn; };

    on('btnPractice', () => start());
    on('phExit', stop);
    on('pqCheck', check);
    on('pqOk', () => judge(true));
    on('pqNo', () => judge(false));
    on('prAgain', () => {
      $('practiceResult').classList.remove('show');
      $('practiceBar').hidden = false;
      start();
    });
    on('prWrongOnly', retryWrong);
    on('prExit', stop);

    const inp = $('pqInput');
    if (inp) {
      /* 中文输入法组词时按 Enter 是「选词」，不是「提交」。
         编辑器里早就处理了，答题框漏了——学生会把拼音当成答案交上去。 */
      let composing = false;
      inp.addEventListener('compositionstart', () => { composing = true; });
      inp.addEventListener('compositionend', () => { composing = false; });
      inp.addEventListener('keydown', e => {
        if (composing || e.isComposing || e.keyCode === 229) return;
        if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); check(); }
      });
    }

    /* 答案区的两个按钮也吃 Enter/空格，键盘流不中断 */
    ['pqOk', 'pqNo'].forEach(id => {
      const b = $(id);
      if (!b) return;
      b.addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          e.stopPropagation();
          judge(id === 'pqOk');
        }
      });
    });

    /* 练习模式下全局快捷键让位：空格是「对答案」，不是「揭示下一个」 */
    document.addEventListener('keydown', e => {
      if (!active) return;
      if (e.target && /INPUT|TEXTAREA/.test(e.target.tagName)) return;
      if (e.key === 'Escape') { e.preventDefault(); stop(); }
    }, true);
  }

  function init(opts) {
    if (opts) {
      if (typeof opts.onToast === 'function') onToast = opts.onToast;
      if (typeof opts.onAnnounce === 'function') onAnnounce = opts.onAnnounce;
    }
    bind();

    /* 学生打开的练习链接：图就装在 URL 里 */
    const hit = location.search.match(/[?&]p=([A-Za-z0-9_-]+)/);
    if (hit) {
      decodeDoc(hit[1]).then(doc => {
        stash = Store.toJSON();
        if (Store.setDoc(doc, { transient: true })) {
          setTimeout(() => start(), 150);
        } else {
          onToast('这个自测链接里的图不完整');
        }
      }).catch(() => onToast('这个自测链接打不开，可能复制的时候被截断了'));
      return;
    }

    /* 老师在自己机器上直接进练习：index.html?practice=1 */
    if (/[?&]practice=1/.test(location.search)) {
      setTimeout(() => start(), 120);
    }
  }

  return { init, start, stop, similarity, copyLink, buildLink };
})();
