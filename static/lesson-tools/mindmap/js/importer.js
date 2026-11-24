/* ============================================================
   importer.js — 导入其他思维导图工具的文件
   ============================================================
   支持的格式（按实际使用频率排）：
     .xmind    XMind 8 / XMind 2020+（zip 包，内含 content.xml 或 content.json）
     .mm       FreeMind / Freeplane（XML，中文文件常是 GBK 编码）
     .opml     OPML 大纲（幕布、WorkFlowy、OmniOutliner 等都能导出）
     .km       百度脑图 KityMinder（JSON）
     .md/.txt  Markdown 标题大纲 / 缩进大纲（几乎所有工具都能导出）
     .json     本工具自己的备份格式

   两个设计原则：
   1. 只搬「结构 + 文字」，不搬样式。别人的配色、字体、图标、贴纸一律不认——
      搬过来只会得到一张四不像的图，不如用本工具的主题重画。
   2. 认不出来就明说。不做「猜一个大概」的静默降级，那会让用户以为导入成功了。
   ============================================================ */
const Importer = (() => {
  const ACCEPT = '.json,.xmind,.mm,.opml,.km,.md,.markdown,.txt';
  /* 教室规模的图上限。再多渲染会开始掉帧，也会让老师没法在 10 分钟里讲完 */
  const MAX_NODES = 2000;

  /* ────────── 通用小工具 ────────── */
  const collapse = s => String(s == null ? '' : s).replace(/\s+/g, ' ').trim();

  function countAll(n) {
    let c = 1;
    for (const k of (n.children || [])) c += countAll(k);
    return c;
  }

  /* 超量就截断，并告诉用户截了多少 */
  function capTree(root, max) {
    let budget = max - 1, dropped = 0;
    (function w(n) {
      if (!n.children) return;
      const keep = [];
      for (const c of n.children) {
        if (budget > 0) { budget--; keep.push(c); w(c); }
        else dropped += countAll(c);
      }
      n.children = keep;
    })(root);
    return dropped;
  }

  /* ────────── 解码：中文 FreeMind 文件常是 GBK ────────── */
  function decodeText(buf) {
    const head = new TextDecoder('utf-8').decode(buf.slice(0, 400));
    const m = head.match(/encoding\s*=\s*["']([\w.:-]+)["']/i);
    let enc = m ? m[1].toLowerCase() : 'utf-8';
    if (/^(gb|gbk|gb2312|gb18030)/.test(enc)) enc = 'gbk';
    try { return new TextDecoder(enc).decode(buf); }
    catch (e) { return new TextDecoder('utf-8').decode(buf); }
  }

  function parseXML(text, what) {
    const doc = new DOMParser().parseFromString(text, 'text/xml');
    if (doc.querySelector('parsererror')) throw new Error(what + ' 文件不是有效的 XML');
    return doc;
  }

  /* ────────── 最小 zip 读取器 ──────────
     只做「按中央目录找到条目 + inflate」这件事，够读 .xmind 就行。 */
  async function unzip(buf) {
    const dv = new DataView(buf);
    const u8 = new Uint8Array(buf);
    const len = buf.byteLength;

    let eocd = -1;
    const floor = Math.max(0, len - 65557);
    for (let i = len - 22; i >= floor; i--) {
      if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
    }
    if (eocd < 0) throw new Error('不是有效的 zip 包（可能不是 .xmind 文件）');

    const count = dv.getUint16(eocd + 10, true);
    let off = dv.getUint32(eocd + 16, true);
    const entries = {};
    const dec = new TextDecoder('utf-8');

    for (let i = 0; i < count; i++) {
      if (off + 46 > len || dv.getUint32(off, true) !== 0x02014b50) break;
      const method = dv.getUint16(off + 10, true);
      const csize = dv.getUint32(off + 20, true);
      const nlen = dv.getUint16(off + 28, true);
      const elen = dv.getUint16(off + 30, true);
      const clen = dv.getUint16(off + 32, true);
      const lho = dv.getUint32(off + 42, true);
      const name = dec.decode(u8.subarray(off + 46, off + 46 + nlen));

      if (lho + 30 <= len && dv.getUint32(lho, true) === 0x04034b50) {
        const lnlen = dv.getUint16(lho + 26, true);
        const lelen = dv.getUint16(lho + 28, true);
        const start = lho + 30 + lnlen + lelen;
        entries[name] = { method, data: u8.subarray(start, Math.min(len, start + csize)) };
      }
      off += 46 + nlen + elen + clen;
    }

    async function read(name) {
      const e = entries[name];
      if (!e) return null;
      if (e.method === 0) return new TextDecoder('utf-8').decode(e.data);
      if (typeof DecompressionStream === 'undefined') {
        throw new Error('这个浏览器不支持解压 zip，请换新版 Chrome / Edge');
      }
      const stream = new Blob([e.data]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
      return new TextDecoder('utf-8').decode(await new Response(stream).arrayBuffer());
    }

    return {
      names: Object.keys(entries),
      has: name => Object.prototype.hasOwnProperty.call(entries, name),
      /* 有些导出会把文件放进子目录，按后缀兜一下 */
      find: base => {
        const exact = Object.keys(entries).find(n => n === base);
        if (exact) return exact;
        return Object.keys(entries).find(n => n.endsWith('/' + base) || n.endsWith('\\' + base)) || null;
      },
      read,
    };
  }

  /* ────────── XMind ────────── */
  const STRUCT_MAP = [
    [/logic|tree/i, 'logical'],
    [/org-?chart/i, 'org'],
    [/timeline/i, 'timeline'],
    [/fishbone/i, 'fishbone'],
    [/map|balanced|clockwise|counterclockwise/i, 'mindmap'],
  ];
  function structureToLayout(cls) {
    if (!cls) return 'mindmap';
    for (const [re, key] of STRUCT_MAP) if (re.test(cls)) return key;
    return 'mindmap';
  }

  function xmindJsonTopic(t, warnings) {
    const node = { text: collapse(t.title) };
    const kids = (t.children && t.children.attached) || [];
    if (kids.length) node.children = kids.map(k => xmindJsonTopic(k, warnings));
    const detached = (t.children && t.children.detached) || [];
    if (detached.length) warnings.push('忽略了 ' + detached.length + ' 个浮动主题');
    return node;
  }

  function xmindXmlTopic(el, warnings) {
    const tEl = el.querySelector(':scope > title');
    const node = { text: collapse(tEl ? tEl.textContent : '') };
    const kids = [];
    el.querySelectorAll(':scope > children > topics').forEach(tps => {
      if (tps.getAttribute('type') === 'attached') {
        tps.querySelectorAll(':scope > topic').forEach(k => kids.push(k));
      } else if (tps.getAttribute('type') === 'detached') {
        warnings.push('忽略了浮动主题');
      }
    });
    if (kids.length) node.children = kids.map(k => xmindXmlTopic(k, warnings));
    return node;
  }

  async function parseXMind(buf) {
    const zip = await unzip(buf);
    const warnings = [];

    const jn = zip.find('content.json');
    if (jn) {
      const raw = JSON.parse(await zip.read(jn));
      const sheet = Array.isArray(raw) ? raw[0] : raw;
      if (!sheet || !sheet.rootTopic) throw new Error('这个 .xmind 里没有找到中心主题');
      const root = xmindJsonTopic(sheet.rootTopic, warnings);
      if (Array.isArray(raw) && raw.length > 1) warnings.push('只导入了第 1 张画布（共 ' + raw.length + ' 张）');
      return {
        root,
        layout: structureToLayout(sheet.structureClass || sheet.rootTopic.structureClass),
        title: collapse(sheet.title) || root.text,
        label: 'XMind',
        warnings,
      };
    }

    const xn = zip.find('content.xml');
    if (xn) {
      const doc = parseXML(await zip.read(xn), 'XMind');
      const sheet = doc.querySelector('sheet');
      if (!sheet) throw new Error('这个 .xmind 里没有找到画布');
      const top = sheet.querySelector(':scope > topic');
      if (!top) throw new Error('这个 .xmind 里没有找到中心主题');
      const root = xmindXmlTopic(top, warnings);
      const titleEl = sheet.querySelector(':scope > title');
      return {
        root,
        layout: structureToLayout(top.getAttribute('structure-class')),
        title: collapse(titleEl ? titleEl.textContent : '') || root.text,
        label: 'XMind',
        warnings,
      };
    }

    if (zip.find('word/document.xml')) throw new Error('这看起来是 Word 文档，不是思维导图');
    if (zip.find('xl/workbook.xml')) throw new Error('这看起来是 Excel 表格，不是思维导图');
    if (zip.find('ppt/presentation.xml')) throw new Error('这看起来是 PPT，不是思维导图');
    throw new Error('这个压缩包里没找到思维导图数据（既无 content.json 也无 content.xml）');
  }

  /* ────────── FreeMind / Freeplane ────────── */
  function mmText(el) {
    const t = el.getAttribute('TEXT');
    if (t != null) return collapse(t);
    const rc = el.querySelector(':scope > richcontent');
    return rc ? collapse(rc.textContent) : '';
  }

  function mmNode(el) {
    const node = { text: mmText(el) };
    const kids = [];
    el.querySelectorAll(':scope > node').forEach(k => kids.push(k));
    if (kids.length) node.children = kids.map(mmNode);
    return node;
  }

  function parseFreeMind(buf) {
    const doc = parseXML(decodeText(buf), 'FreeMind');
    const map = doc.querySelector('map');
    if (!map) throw new Error('这不是 FreeMind 文件（找不到 <map>）');
    const top = map.querySelector(':scope > node');
    if (!top) throw new Error('FreeMind 文件里没有节点');
    return {
      root: mmNode(top),
      layout: 'mindmap',
      title: mmText(top) || 'FreeMind 导图',
      label: 'FreeMind',
      warnings: [],
    };
  }

  /* ────────── OPML ────────── */
  function opmlNode(el) {
    const node = { text: collapse(el.getAttribute('text') || el.getAttribute('title') || '') };
    const kids = [];
    el.querySelectorAll(':scope > outline').forEach(k => kids.push(k));
    if (kids.length) node.children = kids.map(opmlNode);
    return node;
  }

  function parseOPML(buf) {
    const doc = parseXML(decodeText(buf), 'OPML');
    const body = doc.querySelector('body');
    if (!body) throw new Error('这不是 OPML 文件（找不到 <body>）');
    const tops = [];
    body.querySelectorAll(':scope > outline').forEach(el => tops.push(opmlNode(el)));
    if (!tops.length) throw new Error('OPML 里没有大纲内容');
    const head = doc.querySelector('head > title');
    const title = collapse(head ? head.textContent : '') || tops[0].text || '导入的大纲';
    const root = tops.length === 1 ? tops[0] : { text: title, children: tops };
    return { root, layout: 'logical', title, label: 'OPML', warnings: [] };
  }

  /* ────────── 百度脑图 KityMinder ────────── */
  function kmNode(n) {
    const d = n.data || {};
    const node = { text: collapse(d.text != null ? d.text : n.text) };
    const kids = (n.children || []).map(kmNode);
    if (kids.length) node.children = kids;
    return node;
  }

  function parseKityMinder(json) {
    const r = json.root;
    if (!r || typeof r !== 'object') throw new Error('这不是百度脑图文件（找不到 root）');
    const root = kmNode(r);
    return { root, layout: 'mindmap', title: root.text || '百度脑图', label: '百度脑图', warnings: [] };
  }

  /* ────────── Markdown / 缩进大纲 ────────── */
  const indentOf = line => {
    const m = line.match(/^[ \t]*/)[0];
    let n = 0;
    for (const ch of m) n += ch === '\t' ? 2 : 1;
    return n;
  };

  function stripMarker(line) {
    return line
      .replace(/^\s*>+\s?/, '')                    // 引用
      .replace(/^\s*#{1,6}\s+/, '')                 // 只有一个标题的文件会走进缩进分支
      .replace(/^\s*([-*+•·–]|\d+[.)])\s+/, '')     // 列表符号
      .replace(/^\s*\[[ xX]\]\s*/, '')              // 任务勾选框
      .trim();
  }

  /* 用「深度序列」建树：深度只用来表达嵌套关系，具体数值不重要 */
  function buildTree(items, fallbackTitle) {
    const tops = [];
    const stack = [];
    for (const it of items) {
      const node = { text: it.text };
      while (stack.length && stack[stack.length - 1].depth >= it.depth) stack.pop();
      if (!stack.length) tops.push(node);
      else {
        const p = stack[stack.length - 1].node;
        (p.children || (p.children = [])).push(node);
      }
      stack.push({ depth: it.depth, node });
    }
    if (!tops.length) return null;
    if (tops.length === 1) return tops[0];
    return { text: fallbackTitle || '导入的导图', children: tops };
  }

  function parseOutline(text, fallbackTitle) {
    /* 先挡掉二进制：PDF / 图片被当成文本时，会得到一行乱码，看着像导入成功了 */
    const probe = Math.min(text.length, 2000);
    let bad = 0;
    for (let i = 0; i < probe; i++) {
      const c = text.charCodeAt(i);
      if (c === 0) { bad = probe; break; }
      if (c < 9 || (c > 13 && c < 32)) bad++;
    }
    if (probe && bad / probe > 0.05) throw new Error('这个文件不是文本大纲（内容里有大量二进制字符）');

    const lines = text.replace(/\r\n?/g, '\n').split('\n');
    const isHeading = l => /^#{1,6}\s+\S/.test(l);
    const items = [];

    /* 只有一个 # 标题的 Markdown 很常见（`# 水循环` + 列表）。
       它不该把 "# 水循环" 当成一个普通节点，也不该让标题变成「文件名」。
       把这条标题当中心主题，后面的缩进整体下沉一级。 */
    const headings = lines.filter(isHeading);
    let rootTitle = '';
    let bodyLines = lines;
    if (headings.length === 1) {
      const hi = lines.findIndex(isHeading);
      if (!lines.slice(0, hi).some(l => l.trim())) {
        rootTitle = collapse(stripMarker(headings[0]));
        bodyLines = lines.slice(hi + 1);
      }
    }

    if (headings.length >= 2) {
      /* 标题式：XMind / 幕布导出的 Markdown 都是这种 */
      let hd = -1;
      for (const raw of lines) {
        const line = raw.replace(/\s+$/, '');
        if (!line.trim() || /^```/.test(line)) continue;
        const h = line.match(/^(#{1,6})\s+(.*)$/);
        if (h) {
          hd = h[1].length - 1;
          items.push({ depth: hd, text: collapse(stripMarker(h[2])) });
          continue;
        }
        const body = stripMarker(line);
        if (!body) continue;
        items.push({ depth: Math.max(0, hd) + 1 + Math.floor(indentOf(line) / 2), text: collapse(body) });
      }
    } else {
      /* 缩进式：纯文本大纲、幕布复制出来的内容 */
      const indents = [];
      for (const raw of bodyLines) {
        const line = raw.replace(/\s+$/, '');
        if (!line.trim()) continue;
        const body = stripMarker(line);
        if (!body) continue;
        const ind = indentOf(line);
        while (indents.length && indents[indents.length - 1] > ind) indents.pop();
        if (!indents.length || indents[indents.length - 1] < ind) indents.push(ind);
        items.push({ depth: indents.length - 1, text: collapse(body) });
      }
      if (rootTitle) {
        items.forEach(it => { it.depth += 1; });
        items.unshift({ depth: 0, text: rootTitle });
      }
    }

    const root = buildTree(items, fallbackTitle);
    if (!root) throw new Error('文件里没有可识别的大纲内容');
    const warnings = [];
    if (items.length && items[0].depth > 0) {
      warnings.push('原文有多个顶层条目，已合并到一个中心主题下');
    }
    return { root, layout: 'logical', title: rootTitle || root.text || fallbackTitle || '导入的导图', label: '大纲文本', warnings };
  }

  /* ────────── 入口 ────────── */
  function baseName(name) {
    return String(name || '').replace(/\.[^.]+$/, '');
  }

  async function fromFile(file) {
    const name = file.name || '';
    const ext = (name.split('.').pop() || '').toLowerCase();
    const buf = await file.arrayBuffer();
    const head = new Uint8Array(buf.slice(0, 4));

    /* 先按内容嗅探，扩展名不可靠（.txt 里可能是 markdown，也可能是 JSON） */
    const isZip = head[0] === 0x50 && head[1] === 0x4b;
    const isJson = !isZip && /^\s*[{[]/.test(new TextDecoder('utf-8').decode(buf.slice(0, 64)));

    let out;
    if (isZip) {
      out = await parseXMind(buf);
    } else if (isJson) {
      const txt = decodeText(buf);
      let json;
      try { json = JSON.parse(txt); } catch (e) { throw new Error('JSON 解析失败'); }
      if (json && json.root && json.root.data) out = parseKityMinder(json);
      else if (json && json.root) out = { root: json.root, layout: json.layout, title: json.title, label: '本工具备份', warnings: [], passthrough: true };
      else throw new Error('这个 JSON 不是思维导图数据');
    } else if (ext === 'xmind') {
      throw new Error('文件扩展名是 .xmind 但内容不是 zip，可能已损坏');
    } else {
      const txt = decodeText(buf);
      if (/<opml[\s>]/i.test(txt)) out = parseOPML(buf);
      else if (/<map[\s>]/i.test(txt)) out = parseFreeMind(buf);
      else if (/^\s*</.test(txt)) throw new Error('这种 XML 格式还不支持（目前支持 OPML 和 FreeMind）');
      else out = parseOutline(txt, baseName(name) || '导入的导图');
    }

    if (!out.root) throw new Error('没有解析出内容');
    const total = countAll(out.root);
    const dropped = capTree(out.root, MAX_NODES);
    if (dropped) out.warnings.push('节点超过 ' + MAX_NODES + ' 个，已截掉 ' + dropped + ' 个');

    /* 一个节点挂几十上百个下级，通常说明源文件是「一列清单」而不是真的一棵树。
       这种结构导入后是一根极长的竖条，值得直接告诉用户。 */
    let widest = 0, wideName = '';
    (function scan(n) {
      const k = (n.children || []).length;
      if (k > widest) { widest = k; wideName = n.text; }
      (n.children || []).forEach(scan);
    })(out.root);
    if (widest > 40) {
      out.warnings.push('「' + (wideName || '中心主题').slice(0, 12) + '」直接挂了 ' + widest + ' 个下级，导入后是一根很长的竖条');
    }

    out.nodes = total - dropped;

    out.doc = {
      root: out.root,
      links: [],
      title: out.title || out.root.text || '导入的导图',
      layout: out.layout,
      theme: undefined,          // 交给 Store 保留当前主题
      lineStyle: undefined,
      projector: false,
      blank: false,
    };
    return out;
  }

  return { fromFile, ACCEPT, MAX_NODES };
})();
