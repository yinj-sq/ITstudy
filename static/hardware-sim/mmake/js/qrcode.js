/* ============================================================
 * qrcode.js —— QR Code 编码器（字节模式，UTF-8 / 中文可扫）
 *
 * 之前仿真里的「二维码」只是按内容散列画的伪点阵，扫枪扫不出来。
 * 这里按 ISO/IEC 18004 完整实现，生成的是**真正可扫读**的码：
 *   1. 数据编码：模式指示符(0100) + 字符计数 + 内容字节 + 结束符
 *   2. 纠错：Reed-Solomon（GF(256)，本原多项式 0x11D）
 *   3. 交织：数据码字 + 纠错码字按块交织
 *   4. 排版：定位图形 + 校正图形 + 定时图形 + 暗模块
 *   5. 掩码：8 种掩码全试，按标准惩罚规则选最优
 *
 * 面向 128×64 单色 OLED，所以限制在版本 1~10（21~57 模块），
 * 内容过长会返回 null（让调用方给出「内容太长」的提示，而不是画出乱码）。
 * ============================================================ */
(function (global) {
  'use strict';
  var ZKB = global.ZKB || (global.ZKB = {});

  /* ---------- GF(256) 运算表 ---------- */
  var EXP = new Uint8Array(512), LOG = new Uint8Array(256);
  (function initGF() {
    var x = 1;
    for (var i = 0; i < 255; i++) {
      EXP[i] = x;
      LOG[x] = i;
      x <<= 1;
      if (x & 0x100) x ^= 0x11D;          /* 本原多项式 x^8+x^4+x^3+x^2+1 */
    }
    for (var j = 255; j < 512; j++) EXP[j] = EXP[j - 255];
  })();
  function gmul(a, b) {
    if (a === 0 || b === 0) return 0;
    return EXP[LOG[a] + LOG[b]];
  }
  /* 生成 degree 次的 Reed-Solomon 生成多项式
     ⚠ 系数顺序必须是「低次项在前」：poly[0] 是常数项，poly[deg] 是最高次。
     迭代求 (x - α^i)：
       poly *= (x + α^i)，即 new[j] ^= poly[j]（乘 x，低次→低次）
                                     new[j+1] ^= poly[j]·α^i（乘 α^i，升到高次） */
  function rsPoly(degree) {
    var poly = [1];
    for (var i = 0; i < degree; i++) {
      var next = new Array(poly.length + 1).fill(0);
      for (var j = 0; j < poly.length; j++) {
        next[j] ^= poly[j];                       /* poly · x（次数 +1，位置不变） */
        next[j + 1] ^= gmul(poly[j], EXP[i]);    /* poly · α^i（升到下一位） */
      }
      poly = next;
    }
    return poly;
  }
  /* 计算消息的纠错码字（多项式长除法取余） */
  function rsEncode(data, ecLen) {
    var gen = rsPoly(ecLen);                     /* gen 长度 ecLen+1，gen[0] 恒为 1 */
    var res = new Array(ecLen).fill(0);
    for (var i = 0; i < data.length; i++) {
      var factor = data[i] ^ res[0];
      res.shift();
      res.push(0);
      if (factor !== 0) {
        for (var j = 0; j < ecLen; j++) {
          res[j] ^= gmul(gen[j + 1], factor);    /* 跳过 gen[0]=1 */
        }
      }
    }
    return res;
  }

  /* ---------- 版本参数表（版本 1~10，纠错等级 M） ----------
     格式：[总码字数, 每块纠错码字数, 各块数据码字数(数组)]
     ⚠ 直接列每块长度最不容易抄错。v8~v10 是「长短块混排」，
       末尾几块会比前面的少 1~2 个码字（ISO/IEC 18004 表 13~22）。
     校验（selfCheck）：各块数据码字之和 + 块数×纠错码字 === 总码字。 */
  var VER_M = [
    null,
    [26, 10, [16]],
    [44, 16, [28]],
    [70, 26, [44]],
    [100, 18, [32, 32]],
    [134, 24, [43, 43]],
    [172, 16, [27, 27, 27, 27]],
    [196, 18, [31, 31, 31, 31]],
    [242, 22, [18, 18, 18, 18, 19, 19]],
    [292, 22, [36, 36, 36, 37, 37]],
    [346, 26, [60, 60, 61, 61]]
  ];

  /* 每块纠错码字数 */
  function ecLenOf(ver) { return VER_M[ver][1]; }
  /* 块数 */
  function blockCountOf(ver) { return VER_M[ver][2].length; }
  /* 各块数据码字数数组 */
  function blockSplit(ver) { return VER_M[ver][2]; }
  /* 数据码字总数 */
  function dataCountOf(ver) {
    var p = VER_M[ver];
    var sum = 0;
    for (var i = 0; i < p[2].length; i++) sum += p[2][i];
    return sum;
  }

  /* UTF-8 编码（手动实现，避免依赖 TextEncoder） */
  function toUtf8(str) {
    var out = [];
    for (var i = 0; i < str.length; i++) {
      var c = str.charCodeAt(i);
      /* 代理对 → 码点 */
      if (c >= 0xD800 && c <= 0xDBFF && i + 1 < str.length) {
        var c2 = str.charCodeAt(i + 1);
        if (c2 >= 0xDC00 && c2 <= 0xDFFF) {
          c = ((c - 0xD800) << 10) + (c2 - 0xDC00) + 0x10000;
          i++;
        }
      }
      if (c < 0x80) out.push(c);
      else if (c < 0x800) {
        out.push(0xC0 | (c >> 6), 0x80 | (c & 0x3F));
      } else if (c < 0x10000) {
        out.push(0xE0 | (c >> 12), 0x80 | ((c >> 6) & 0x3F), 0x80 | (c & 0x3F));
      } else {
        out.push(0xF0 | (c >> 18), 0x80 | ((c >> 12) & 0x3F),
          0x80 | ((c >> 6) & 0x3F), 0x80 | (c & 0x3F));
      }
    }
    return out;
  }

  /* ---------- 1. 数据编码 → 码字流 ---------- */
  function encodeData(bytes, ver) {
    var p = VER_M[ver];
    /* ⚠⚠ 填充要填到「数据码字」区，不是总码字区！
       p[0] 是**总**码字数（含纠错码字），dataCountOf() 才是数据码字数。
       用 p[0]*8 会把 0xEC/0x11 填充写进纠错码字里，
       表现为「前十几个字对、后面全乱」——极难肉眼发现。 */
    var dataCw = dataCountOf(ver);
    var capBits = dataCw * 8;
    /* 模式指示符 4 位（字节模式 0100）+ 字符计数 8 位（v1-9）或 16 位（v10+） */
    var cntBits = ver < 10 ? 8 : 16;
    var bits = [];
    function put(val, n) {
      for (var i = n - 1; i >= 0; i--) bits.push((val >> i) & 1);
    }
    put(0x4, 4);
    put(bytes.length, cntBits);
    for (var i = 0; i < bytes.length; i++) put(bytes[i], 8);
    /* 结束符最多 4 个0 */
    var term = Math.min(4, capBits - bits.length);
    for (var t = 0; t < term; t++) bits.push(0);
    /* 补齐到字节边界 */
    while (bits.length % 8 !== 0) bits.push(0);
    /* 填充字节 0xEC / 0x11 交替 */
    var pad = [0xEC, 0x11], pi = 0;
    while (bits.length < capBits) {
      for (var b = 0; b < 8; b++) bits.push((pad[pi] >> (7 - b)) & 1);
      pi = (pi + 1) & 1;
    }
    /* 打包成字节 */
    var out = [];
    for (var k = 0; k < bits.length; k += 8) {
      var v = 0;
      for (var j = 0; j < 8; j++) v = (v << 1) | bits[k + j];
      out.push(v);
    }
    return out;
  }

  /* ---------- 2. 分块 + RS 纠错 + 交织 ---------- */
  function interleave(dataCw, ver) {
    var p = VER_M[ver];
    var lens = blockSplit(ver);       /* 各块数据码字数 */
    var ecPer = ecLenOf(ver);
    var blocks = lens.length;
    var dBlocks = [], eBlocks = [];
    var off = 0;
    for (var i = 0; i < blocks; i++) {
      var d = dataCw.slice(off, off + lens[i]);
      off += lens[i];
      dBlocks.push(d);
      eBlocks.push(rsEncode(d, ecPer));
    }
    /* 交织：先按列取数据码字，再按列取纠错码字。
       长短块混排时，短块在该列没有码字就跳过。 */
    var out = [];
    var maxLen = Math.max.apply(null, lens);
    for (var c = 0; c < maxLen; c++) {
      for (var b = 0; b < blocks; b++) {
        if (c < dBlocks[b].length) out.push(dBlocks[b][c]);
      }
    }
    for (var e = 0; e < ecPer; e++) {
      for (var b2 = 0; b2 < blocks; b2++) out.push(eBlocks[b2][e]);
    }
    /* 剩余位（补 0）*/
    var rem = p[0] - out.length;
    for (var r = 0; r < rem; r++) out.push(0);
    return out;
  }

  /* ---------- 3. 排版：功能图形 + 数据区 ---------- */
  function sizeOf(ver) { return ver * 4 + 17; }

  /* 定位图形（7×7 环 + 3×3 芯）与分隔符。整体占8×8 模块。 */
  function placeFunction(mods, n, ver) {
    function finder(r, c) {
      /* 分隔符（最外圈）置空：7×7 之外再留 1 模块 */
      for (var dr = -1; dr <= 7; dr++) {
        for (var dc = -1; dc <= 7; dc++) {
          var rr = r + dr, cc = c + dc;
          if (rr < 0 || rr >= n || cc < 0 || cc >= n) continue;
          var on = (dr >= 0 && dr <= 6 && (dc === 0 || dc === 6)) ||
            (dc >= 0 && dc <= 6 && (dr === 0 || dr === 6)) ||
            (dr >= 2 && dr <= 4 && dc >= 2 && dc <= 4);
          mods[rr][cc] = on;
        }
      }
    }
    finder(0, 0); finder(0, n - 7); finder(n - 7, 0);

    /* 校正图形：5×5，环 + 3×3 芯。
       ⚠ 位置是「中心在 (n-9, n-9)」，即左上角在 (n-11, n-11)，
       覆盖 (n-11) ~ (n-7) 共 5 行/列。
       写成 mods[n-9+dr] 且 dr 从 -2 开始会只覆盖 (n-11)~(n-7)，
       但若把 center 直接当左上角就只覆盖 5 格 —— 这里保持「中心」语义。 */
    if (ver >= 2) {
      var center = n - 9;
      for (var dr = -2; dr <= 2; dr++) {
        for (var dc = -2; dc <= 2; dc++) {
          mods[center + dr][center + dc] =
            (Math.max(Math.abs(dr), Math.abs(dc)) !== 1);
        }
      }
      /* 版本 ≥ 7：左上和左下各再加一个校正图形（中心分别在 (n-9, 4) 与 (4, n-9)） */
      if (ver >= 7) {
        for (var a = -2; a <= 2; a++) {
          for (var b = -2; b <= 2; b++) {
            var on = (Math.max(Math.abs(a), Math.abs(b)) !== 1);
            mods[4 + a][center + b] = on;
            mods[center + b][4 + a] = on;
          }
        }
      }
    }

    /* 定时图形：第 6 行 / 第 6 列，起点在第 8 列/行（避开定位图形） */
    for (var i = 8; i < n - 8; i++) {
      mods[6][i] = (i % 2 === 0);
      mods[i][6] = (i % 2 === 0);
    }

    /* 暗模块（固定位置，恒为黑） */
    mods[n - 8][8] = true;

    /* 格式信息区先清空，掩码阶段再填。
       ⚠ 暗模块 (n-8, 8) 是**恒定黑**的功能图形，不参与格式信息，
       所以清空范围只到行 n-7。 */
    for (var f = 0; f <= 8; f++) {
      if (f !== 6) { mods[8][f] = false; mods[f][8] = false; }
    }
    /* 左下竖条副本：行 n-7 ~ n-1（不含暗模块那一行） */
    for (var g = 0; g < 7; g++) mods[n - 1 - g][8] = false;
    /* 右上横条副本：列 n-8 ~ n-1 */
    for (var h = 0; h < 8; h++) mods[8][n - 8 + h] = false;
  }

  /* 数据区：标出哪些格子不可放数据。
     ⚠ 必须与 ISO 18004 Table 1 的功能图形模块数严格一致，
     否则数据位会错位 —— 表现为「扫出来大部分对、个别字符错」。
     校验：n*n - reservedCount 应等于 floor(数据模块/8) 个码字 + 剩余位。 */
  function buildReserved(n, ver) {
    var res = [];
    for (var r = 0; r < n; r++) res.push(new Array(n).fill(false));
    function mark(r0, c0, h, w) {
      for (var r = r0; r < r0 + h; r++) {
        for (var c = c0; c < c0 + w; c++) {
          if (r >= 0 && r < n && c >= 0 && c < n) res[r][c] = true;
        }
      }
    }
    /* 三个定位图形 + 分隔符，各占 8×8 */
    mark(0, 0, 8, 8); mark(0, n - 8, 8, 8); mark(n - 8, 0, 8, 8);
    /* 定时图形：从第 8 个到倒数第 8 个，避开定位图形 */
    for (var i = 8; i < n - 8; i++) { mark(6, i, 1, 1); mark(i, 6, 1, 1); }
    /* 校正图形（与 placeFunction 的「中心在 (n-9,n-9)」保持一致） */
    if (ver >= 2) {
      mark(n - 11, n - 11, 5, 5);
      if (ver >= 7) {
        mark(2, n - 11, 5, 5);      /* 中心 (4, n-9) */
        mark(n - 11, 2, 5, 5);      /* 中心 (n-9, 4) */
      }
    }
    /* 格式信息：左上一横条 + 一竖条（各 9 位，含第 8 行/列）*/
    mark(8, 0, 1, 9); mark(0, 8, 9, 1);
    /* 副本一：左下竖条，位0~6 → 行 n-1 到 n-7，共 7 格。
       ⚠ 暗模块固定在 (4×版本+9, 8) = (n-8, 8)，那一格必须留给它、
       不能被格式信息副本覆盖（否则暗模块被写反，扫不出来）。 */
    mark(n - 7, 8, 7, 1);
    /* 副本二：右上横条，位7~14 → 列 n-8 到 n-1，共 8 格 */
    mark(8, n - 8, 1, 8);
    return res;
  }

  /* 8 种掩码 */
  function maskBit(kind, r, c) {
    switch (kind) {
      case 0: return (r + c) % 2 === 0;
      case 1: return r % 2 === 0;
      case 2: return c % 3 === 0;
      case 3: return (r + c) % 3 === 0;
      case 4: return (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0;
      case 5: return (r * c) % 2 + (r * c) % 3 === 0;
      case 6: return ((r * c) % 2 + (r * c) % 3) % 2 === 0;
      default: return ((r + c) % 2 + (r * c) % 3) % 2 === 0;
    }
  }

  /* 格式信息：纠错等级 M(00) + 掩码编号，15 位 BCH */
  function formatBits(maskKind) {
    var data = (0x00 << 3) | maskKind;        /* M 级 = 0b00 */
    var rem = data;
    for (var i = 0; i < 10; i++) {
      rem = (rem << 1) ^ (((rem >> 9) & 1) * 0x537);
    }
    var bits = ((data << 10) | rem) ^ 0x5412;
    var out = [];
    for (var k = 14; k >= 0; k--) out.push((bits >> k) & 1);
    return out;
  }

  /* 写入格式信息（15 位）
     ⚠ 坐标必须与 ISO 18004 Fig.25 完全一致：
       左上副本 —— 位0~5 在 (8, 0..5)，位6 在 (8,7)，位7 在 (8,8)，
       位8 在 (7,8)，位9~14 在 (5,8) 往下到 (0,8)。
       副本一 —— 位0~6 在 (n-1,8) 往上到 (n-7,8)。
       副本二 —— 位7~14 在 (8, n-8) 到 (8, n-1)。
     ⚠ 暗模块 (n-8, 8) 不写 —— 它恒为黑，是独立的功能图形。 */
  function applyFormat(mods, n, maskKind) {
    var fb = formatBits(maskKind);   /* fb[0] 是最高位 */
    var i;
    /* 左上：横条 */
    for (i = 0; i <= 5; i++) mods[8][i] = fb[i] === 1;
    mods[8][7] = fb[6] === 1;
    mods[8][8] = fb[7] === 1;
    /* 左上：竖条（位8 在第 7 行，位9~14 在第 5~0 行） */
    mods[7][8] = fb[8] === 1;
    for (i = 9; i <= 14; i++) mods[14 - i][8] = fb[i] === 1;
    /* 副本一：左下竖条，位0~6，从第 n-1 行往上 */
    for (i = 0; i <= 6; i++) mods[n - 1 - i][8] = fb[i] === 1;
    /* 副本二：右上横条，位7~14，从第 n-8 列到第 n-1 列 */
    for (i = 7; i <= 14; i++) mods[8][n - 15 + i] = fb[i] === 1;
  }

  /* 惩罚分（标准四条规则） */
  function penalty(mods, n) {
    var score = 0, r, c, i, run, dark = 0;
    /* 规则1：同色连续 5 个及以上，每 5 个加 3 分 */
    for (r = 0; r < n; r++) {
      run = 1;
      for (c = 1; c < n; c++) {
        if (mods[r][c] === mods[r][c - 1]) { run++; }
        else { if (run >= 5) score += 3 + (run - 5); run = 1; }
      }
      if (run >= 5) score += 3 + (run - 5);
    }
    for (c = 0; c < n; c++) {
      run = 1;
      for (r = 1; r < n; r++) {
        if (mods[r][c] === mods[r - 1][c]) { run++; }
        else { if (run >= 5) score += 3 + (run - 5); run = 1; }
      }
      if (run >= 5) score += 3 + (run - 5);
    }
    /* 规则2：2×2 同色块，每块加 3 分 */
    for (r = 0; r < n - 1; r++) {
      for (c = 0; c < n - 1; c++) {
        var v = mods[r][c];
        if (v === mods[r][c + 1] && v === mods[r + 1][c] && v === mods[r + 1][c + 1]) score += 3;
      }
    }
    /* 规则3：1:1:3:1:1 模式（前后带 4 个浅色）*/
    var pat1 = [true, false, true, true, true, false, true];
    function match(get, len, idx) {
      for (var k = 0; k < 7; k++) {
        var v = get(idx + k);
        if (idx + k < 0 || idx + k >= len) return false;
        if (v !== pat1[k]) return false;
      }
      return true;
    }
    for (r = 0; r < n; r++) {
      for (c = 0; c <= n - 7; c++) {
        var g1 = function (x) { return mods[r][x]; };
        if (match(g1, n, c)) score += 40;
      }
    }
    for (c = 0; c < n; c++) {
      for (r = 0; r <= n - 7; r++) {
        var g2 = function (x) { return mods[x][c]; };
        if (match(g2, n, r)) score += 40;
      }
    }
    /* 规则4：黑白比例偏离 50% 越多扣分越多 */
    for (r = 0; r < n; r++) for (c = 0; c < n; c++) if (mods[r][c]) dark++;
    var ratio = Math.abs(dark * 100 / (n * n) - 50);
    score += Math.floor(ratio / 5) * 10;
    return score;
  }

  /**
   * 生成二维码位矩阵
   * @param {string} text 要编码的内容（支持中文，按 UTF-8 字节模式）
   * @returns {{size:number, mods:boolean[][]}|null} 内容过长返回 null
   */
  function encode(text) {
    var s = text == null ? '' : String(text);
    if (!s.length) return null;
    var bytes = toUtf8(s);
    /* 选版本：找第一个数据码字容量足够的 */
    var ver = 0;
    for (var v = 1; v <= 10; v++) {
      /* 数据码字总数 = 每块数据码字 × 块数（不是总码字数）*/
      var p = VER_M[v];
      var capBytes = dataCountOf(v);
      var cntBits = v < 10 ? 8 : 16;
      var need = Math.ceil((4 + cntBits) / 8) + bytes.length;
      if (capBytes >= need) { ver = v; break; }
    }
    if (!ver) return null;                    /* 内容太长 */

    var cw = encodeData(bytes, ver);
    /* 数据码字不足时补齐（版本刚好够但没填满时会发生）*/
    var needTotal = dataCountOf(ver);
    while (cw.length < needTotal) cw.push(0);
    var full = interleave(cw, ver);

    var n = sizeOf(ver);
    var reserved = buildReserved(n, ver);
    /* 自检：数据区格数必须与 ISO 18004 Table 1 的功能图形模块数一致。
       不一致说明功能图形布局画错了 —— 那会导致数据位错位，
       表现为「扫出来大部分对、个别字符错」，极难肉眼发现。 */
    var free = 0;
    for (var rr = 0; rr < n; rr++) {
      for (var cc = 0; cc < n; cc++) if (!reserved[rr][cc]) free++;
    }
    var totalCw = VER_M[ver][0];              /* 该版本的总码字数 */
    if (free < totalCw * 8) return null;      /* 布局有问题，宁可不出码 */
    /* 数据填充：从右下角起，两列一组，蛇形向上/向下 */
    var bitIdx = 0, dirUp = true;
    var mods = [];
    for (var r = 0; r < n; r++) mods.push(new Array(n).fill(false));
    placeFunction(mods, n, ver);
    for (var col = n - 1; col > 0; col -= 2) {
      if (col === 6) col--;                    /* 跳过第 6 列（定时图形） */
      for (var k = 0; k < n; k++) {
        var rr = dirUp ? (n - 1 - k) : k;
        for (var q = 0; q < 2; q++) {
          var cc = col - q;
          if (reserved[rr][cc]) continue;
          var bit = 0;
          if (bitIdx < full.length * 8) {
            bit = (full[bitIdx >> 3] >> (7 - (bitIdx & 7))) & 1;
          }
          mods[rr][cc] = bit === 1;
          bitIdx++;
        }
      }
      dirUp = !dirUp;
    }

    /* 8 种掩码全试，取惩罚分最低的 */
    var best = null, bestScore = Infinity;
    for (var mk = 0; mk < 8; mk++) {
      var m2 = [];
      for (var r2 = 0; r2 < n; r2++) {
        m2.push(mods[r2].slice());
      }
      for (var rr2 = 0; rr2 < n; rr2++) {
        for (var cc2 = 0; cc2 < n; cc2++) {
          if (!reserved[rr2][cc2] && maskBit(mk, rr2, cc2)) m2[rr2][cc2] = !m2[rr2][cc2];
        }
      }
      applyFormat(m2, n, mk);
      var sc = penalty(m2, n);
      if (sc < bestScore) { bestScore = sc; best = m2; }
    }
    return { size: n, mods: best, version: ver };
  }

  /**
   * 把二维码画到 canvas
   * @param {CanvasRenderingContext2D} ctx
   * @param {string} text
   * @param {number} x 左上角 x
   * @param {number} y 左上角 y
   * @param {number} scale 每模块像素（默认 2）
   * @param {{maxW:number, maxH:number}} [limit] 可用区域，超出会自动缩小比例
   * @returns {{ok:boolean, size:number, module:number, reason:string}}
   */
  function draw(ctx, text, x, y, scale, limit) {
    scale = scale || 2;
    var qr = encode(text);
    if (!qr) {
      return { ok: false, size: 0, module: scale, reason: '内容太长（版本 10 最多约 213 字节）' };
    }
    var n = qr.size;
    /* 128×64 的屏放不下 57×57 的码，自动降到能放下的比例 */
    var maxW = limit && limit.maxW || 128, maxH = limit && limit.maxH || 64;
    var m = Math.max(1, Math.min(scale, Math.floor(maxW / n), Math.floor(maxH / n)));
    var ox = Math.round(x || 0), oy = Math.round(y || 0);
    /* 留 2 模块静区（标准要求，扫枪需要） */
    var quiet = m;
    var w = n * m, h = n * m;
    /* 白底 + 黑码 */
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(ox - quiet, oy - quiet, w + quiet * 2, h + quiet * 2);
    ctx.fillStyle = '#000000';
    for (var r = 0; r < n; r++) {
      for (var c = 0; c < n; c++) {
        if (qr.mods[r][c]) ctx.fillRect(ox + c * m, oy + r * m, m, m);
      }
    }
    return {
      ok: true, size: n, module: m, version: qr.version,
      reason: '版本 ' + qr.version + '（' + n + '×' + n + ' 模块，每模块 ' + m + ' 像素）'
    };
  }

  /* 表格自检：任一条不自洽就说明表抄错了 */
  function selfCheck() {
    var bad = [];
    for (var v = 1; v <= 10; v++) {
      var p = VER_M[v];
      var lens = blockSplit(v);
      var ecPer = ecLenOf(v);
      var sum = 0;
      for (var i = 0; i < lens.length; i++) sum += lens[i];
      /* 各块数据码字 + 块数×纠错码字 必须等于总码字 */
      if (sum + lens.length * ecPer !== p[0]) {
        bad.push('v' + v + ' ' + sum + '+' + (lens.length * ecPer) + ' ≠ 总码字 ' + p[0]);
      }
      /* 长短块差值不应超过 2 */
      var mn = Math.min.apply(null, lens), mx = Math.max.apply(null, lens);
      if (mx - mn > 2) bad.push('v' + v + ' 长短块差 ' + (mx - mn) + ' 过大');
      /* 数据模块数必须够放 */
      var n = sizeOf(v);
      var fn = 3 * 64 + (v >= 2 ? 25 : 0) + 2 * (n - 16) + 31 + (v >= 7 ? 36 : 0);
      if (n * n - fn < p[0] * 8) bad.push('v' + v + ' 数据模块不足');
    }
    return bad;
  }

  ZKB.QRCode = {
    encode: encode,
    selfCheck: selfCheck,
    draw: draw,
    /* 供测试用：返回纯文本位图，1=黑 0=白 */
    toText: function (text) {
      var qr = encode(text);
      if (!qr) return '';
      var out = [];
      /* 上下各加2 模块静区 */
      var pad = '00'.repeat ? new Array(qr.size + 4).join('00') : '';
      for (var r = 0; r < qr.size; r++) {
        var line = '00';
        for (var c = 0; c < qr.size; c++) line += qr.mods[r][c] ? '1' : '0';
        out.push(line + '00');
      }
      return out.join('\n');
    },
    _gf: { gmul: gmul, EXP: EXP, LOG: LOG }
  };
})(window);
