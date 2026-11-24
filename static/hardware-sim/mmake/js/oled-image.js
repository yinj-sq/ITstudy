/* ============================================================
 * oled-image.js —— 掌控板屏幕图片显示
 * 能力：
 *   1. 上传本地图片 → 校验（格式 / 体积 / 像素）→ 等比缩放 →
 *      灰度化 + 阈值化「像素化」→ 生成 128×64 单色位图；
 *   2. 内置表情（喜 / 怒 / 哀 / 乐 / 惊讶 / 思考 / 爱心 / 睡觉…），
 *      全部用代码绘制的位图，天然像素风；
 *   3. 虚拟仿真（掌控板小屏）与舞台模式同步显示；
 *   4. 生成 MicroPython 代码（oled.Bitmap + framebuf）。
 * ============================================================ */
(function (global) {
  'use strict';
  var ZKB = global.ZKB || (global.ZKB = {});

  var W = 128, H = 64;          // OLED 逻辑分辨率
  var MAX_BYTES = 3 * 1024 * 1024;   // 上传体积上限 3MB
  var ALLOW = ['image/png', 'image/jpeg', 'image/gif', 'image/bmp', 'image/webp'];

/* ============================================================
   * 内置表情：在 128×64 上用绘图基元直接绘制（1bit 单色像素风）
   *   统一构图：头部椭圆（64,32 rx28 ry27）、眼睛 y≈28、嘴 y≈45
   *   每个表情 = draw(bits) 函数；键名沿用旧版，旧工程照常可用
   * ============================================================ */

  /* ---- 绘图基元 ---- */
  function px(b, x, y) {
    x = Math.round(x); y = Math.round(y);
    if (x >= 0 && x < W && y >= 0 && y < H) b[y * W + x] = 1;
  }
  /* 以 (x,y) 为中心画 t×t 方点（线宽 / 圆点） */
  function dot(b, x, y, t) {
    t = t || 1;
    var o = Math.floor((t - 1) / 2);
    for (var j = 0; j < t; j++) for (var i = 0; i < t; i++) px(b, x + i - o, y + j - o);
  }
  /* 以 (x,y) 为左上角的实心矩形（w/h 为像素数，t 为像素放大倍数） */
  function fillRect(b, x, y, w, h, t) {
    t = t || 1;
    for (var j = 0; j < h * t; j++) for (var i = 0; i < w * t; i++) px(b, x * t + i, y * t + j);
  }
  function line(b, x0, y0, x1, y1, t) {
    t = t || 1;
    var dx = Math.abs(x1 - x0), dy = Math.abs(y1 - y0);
    var sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
    var err = dx - dy, guard = 0;
    for (; guard < 6000; guard++) {
      dot(b, x0, y0, t);
      if (x0 === x1 && y0 === y1) break;
      var e2 = 2 * err;
      if (e2 > -dy) { err -= dy; x0 += sx; }
      if (e2 < dx) { err += dx; y0 += sy; }
    }
  }
  function fillCircle(b, cx, cy, r) {
    for (var y = -r; y <= r; y++) {
      var w = Math.floor(Math.sqrt(Math.max(0, r * r - y * y)));
      for (var x = -w; x <= w; x++) px(b, cx + x, cy + y);
    }
  }
  function strokeCircle(b, cx, cy, r, t) {
    t = t || 1;
    var steps = Math.max(20, Math.ceil(2 * Math.PI * r));
    for (var s = 0; s < steps; s++) {
      var a = s / steps * Math.PI * 2;
      dot(b, cx + Math.cos(a) * r, cy + Math.sin(a) * r, t);
    }
  }
  /* 椭圆弧：角度 0=右, π/2=下, π=左, 3π/2=上 */
  function arc(b, cx, cy, rx, ry, a0, a1, t) {
    t = t || 1;
    var span = Math.abs(a1 - a0);
    var steps = Math.max(24, Math.ceil(span * Math.max(rx, ry) * 1.2));
    for (var s = 0; s <= steps; s++) {
      var a = a0 + (a1 - a0) * s / steps;
      dot(b, cx + Math.cos(a) * rx, cy + Math.sin(a) * ry, t);
    }
  }
  function strokeEllipse(b, cx, cy, rx, ry, t) {
    t = t || 1;
    var steps = Math.max(28, Math.ceil(2 * Math.PI * Math.max(rx, ry)));
    for (var s = 0; s < steps; s++) {
      var a = s / steps * Math.PI * 2;
      dot(b, cx + Math.cos(a) * rx, cy + Math.sin(a) * ry, t);
    }
  }
  function fillEllipse(b, cx, cy, rx, ry) {
    for (var y = -ry; y <= ry; y++) {
      var w = Math.floor(rx * Math.sqrt(Math.max(0, 1 - (y * y) / (ry * ry))));
      for (var x = -w; x <= w; x++) px(b, cx + x, cy + y);
    }
  }
  /* 多边形扫描线填充 */
  function fillPoly(b, pts) {
    var minY = 1e9, maxY = -1e9, i;
    for (i = 0; i < pts.length; i++) {
      minY = Math.min(minY, pts[i][1]); maxY = Math.max(maxY, pts[i][1]);
    }
    for (var y = Math.floor(minY); y <= Math.ceil(maxY); y++) {
      var xs = [];
      for (i = 0; i < pts.length; i++) {
        var a = pts[i], c = pts[(i + 1) % pts.length];
        if ((a[1] <= y && c[1] > y) || (c[1] <= y && a[1] > y)) {
          xs.push(a[0] + (y - a[1]) / (c[1] - a[1]) * (c[0] - a[0]));
        }
      }
      xs.sort(function (m, n) { return m - n; });
      for (i = 0; i + 1 < xs.length; i += 2) {
        for (var x = Math.round(xs[i]); x <= Math.round(xs[i + 1]); x++) px(b, x, y);
      }
    }
  }
  /* 爱心：两圆 + 下方三角 */
  function heart(b, cx, cy, s) {
    fillCircle(b, cx - s * 0.52, cy - s * 0.3, s * 0.5);
    fillCircle(b, cx + s * 0.52, cy - s * 0.3, s * 0.5);
    fillPoly(b, [[cx - s, cy - s * 0.1], [cx + s, cy - s * 0.1], [cx, cy + s]]);
  }
  /* 四角星光 */
  function sparkle(b, cx, cy, r, t) {
    t = t || 1;
    fillPoly(b, [[cx, cy - r], [cx + t, cy], [cx, cy + r], [cx - t, cy]]);
    fillPoly(b, [[cx - r, cy], [cx, cy + t], [cx + r, cy], [cx, cy - t]]);
    fillCircle(b, cx, cy, 1 + Math.floor(t / 2));
  }
  /* 泪滴：上尖下圆 */
  function tear(b, cx, cy, s) {
    fillCircle(b, cx, cy, s);
    fillPoly(b, [[cx - s * 0.85, cy - s * 0.3], [cx + s * 0.85, cy - s * 0.3], [cx, cy - s * 2.1]]);
  }
  /* 字母 Z（睡觉用） */
  function zed(b, x, y, s, t) {
    t = t || 1;
    line(b, x, y, x + s, y, t);
    line(b, x + s, y, x, y + s, t);
    line(b, x, y + s, x + s, y + s, t);
  }
  /* 张口大笑：下半圆填充 + 上沿平线 */
  function openSmile(b, cx, cy, rx, ry) {
    for (var y = 0; y <= ry; y++) {
      var w = Math.floor(rx * Math.sqrt(Math.max(0, 1 - (y * y) / (ry * ry))));
      for (var x = -w; x <= w; x++) px(b, cx + x, cy + y);
    }
    line(b, cx - rx, cy, cx + rx, cy, 2);
  }
  /* 头部轮廓（所有表情共用，保持风格统一） */
  function headBase(b) {
    strokeEllipse(b, 64, 32, 28, 27, 2);
    fillCircle(b, 64, 33, 1);          /* 鼻尖 */
  }
  function blush(b, y) {
    fillCircle(b, 44, y, 3);
    fillCircle(b, 84, y, 3);
  }
  var EX = 52, EY = 28;      /* 左眼中心 */
  var MX = 64, MY = 45;      /* 嘴中心 y */

  var FACES = {
    happy: {   /* 喜 —— 弯弯笑眼 + 张口大笑 + 腮红 */
      name: '喜',
      draw: function (b) {
        headBase(b);
        arc(b, EX, EY + 2, 7, 5, Math.PI, Math.PI * 2, 2);
        arc(b, 128 - EX, EY + 2, 7, 5, Math.PI, Math.PI * 2, 2);
        openSmile(b, MX, MY - 7, 13, 10);
        blush(b, 38);
      }
    },
    angry: {   /* 怒 —— 竖眉 + 圆眼 + 锯齿嘴 */
      name: '怒',
      draw: function (b) {
        headBase(b);
        line(b, 43, 18, 59, 25, 3);
        line(b, 85, 18, 69, 25, 3);
        fillCircle(b, EX, EY + 3, 4);
        fillCircle(b, 128 - EX, EY + 3, 4);
        line(b, 50, MY - 2, 57, MY - 8, 2);
        line(b, 57, MY - 8, 64, MY - 2, 2);
        line(b, 64, MY - 2, 71, MY - 8, 2);
        line(b, 71, MY - 8, 78, MY - 2, 2);
      }
    },
    sad: {     /* 哀 —— 八字眉 + 泪珠 + 撇嘴 */
      name: '哀',
      draw: function (b) {
        headBase(b);
        line(b, 44, 26, 58, 20, 2);
        line(b, 84, 26, 70, 20, 2);
        fillCircle(b, EX, EY + 3, 4);
        fillCircle(b, 128 - EX, EY + 3, 4);
        arc(b, MX, MY - 4, 11, 8, 0, Math.PI, 2);
        tear(b, 85, 35, 3);
      }
    },
    calm: {    /* 乐 —— 平静微笑 + 腮红 */
      name: '乐',
      draw: function (b) {
        headBase(b);
        fillCircle(b, EX, EY, 3);
        fillCircle(b, 128 - EX, EY, 3);
        arc(b, MX, MY - 4, 9, 7, Math.PI * 0.18, Math.PI * 0.82, 2);
        blush(b, 38);
      }
    },
    wow: {     /* 惊 —— 瞪大双眼 + 张口 O */
      name: '惊',
      draw: function (b) {
        headBase(b);
        arc(b, EX, EY - 9, 6, 4, Math.PI * 1.08, Math.PI * 1.92, 2);
        arc(b, 128 - EX, EY - 9, 6, 4, Math.PI * 1.08, Math.PI * 1.92, 2);
        strokeCircle(b, EX, EY + 1, 6, 2);
        strokeCircle(b, 128 - EX, EY + 1, 6, 2);
        fillCircle(b, EX, EY + 1, 2);
        fillCircle(b, 128 - EX, EY + 1, 2);
        strokeEllipse(b, MX, MY - 3, 6, 8, 2);
      }
    },
    think: {   /* 思 —— 一眼眯 + 思绪气泡 */
      name: '思',
      draw: function (b) {
        headBase(b);
        arc(b, EX, EY + 2, 6, 4, Math.PI, Math.PI * 2, 2);
        fillCircle(b, 128 - EX, EY + 1, 4);
        line(b, MX - 7, MY - 1, MX + 7, MY - 4, 2);
        fillCircle(b, 84, 22, 2);
        fillCircle(b, 91, 15, 2);
        fillCircle(b, 99, 8, 3);
      }
    },
    love: {    /* 爱 —— 爱心眼 + 大笑 + 腮红 */
      name: '爱',
      draw: function (b) {
        headBase(b);
        heart(b, EX, EY, 7);
        heart(b, 128 - EX, EY, 7);
        openSmile(b, MX, MY - 7, 12, 9);
        blush(b, 38);
      }
    },
    sleep: {   /* 睡 —— 闭眼 + 小呼噜 + Zzz */
      name: '睡',
      draw: function (b) {
        headBase(b);
        arc(b, EX, EY - 1, 6, 4, 0, Math.PI, 2);
        arc(b, 128 - EX, EY - 1, 6, 4, 0, Math.PI, 2);
        strokeEllipse(b, MX, MY - 5, 4, 4, 2);
        zed(b, 95, 26, 7, 2);
        zed(b, 104, 17, 5, 2);
        zed(b, 111, 9, 4, 1);
      }
    },
    cry: {     /* 哭 —— 泪流成河 + 皱嘴 */
      name: '哭',
      draw: function (b) {
        headBase(b);
        line(b, 44, 25, 58, 20, 2);
        line(b, 84, 25, 70, 20, 2);
        fillCircle(b, EX, EY + 3, 4);
        fillCircle(b, 128 - EX, EY + 3, 4);
        tear(b, EX, EY + 10, 3);
        tear(b, 128 - EX, EY + 10, 3);
        line(b, EX, EY + 15, EX, MY - 3, 2);
        line(b, 128 - EX, EY + 15, 128 - EX, MY - 3, 2);
        line(b, 52, MY - 4, 58, MY + 1, 2);
        line(b, 58, MY + 1, 64, MY - 4, 2);
        line(b, 64, MY - 4, 70, MY + 1, 2);
        line(b, 70, MY + 1, 76, MY - 4, 2);
      }
    },
    star: {    /* 星 —— 星星眼 + 兴奋大笑 */
      name: '星',
      draw: function (b) {
        headBase(b);
        sparkle(b, EX, EY, 7, 2);
        sparkle(b, 128 - EX, EY, 7, 2);
        openSmile(b, MX, MY - 7, 13, 10);
        blush(b, 38);
      }
    }
  };

  /* ============================================================
   * 位图工具
   *   bits: Uint8Array(W*H)，0/1，1 = 点亮
   * ============================================================ */
  function newBits() { return new Uint8Array(W * H); }

  /* 表情 → 128×64 位图
     新版表情用 draw(bits) 在 128×64 上直接绘制；
     兼容旧版rows 点阵（12×12'#'字模，放大居中）。 */
  function faceToBits(face) {
    var bmp = newBits();
    if (face && typeof face.draw === 'function') {
      face.draw(bmp);
      return bmp;
    }
    var src = (face && face.rows) || [];
    if (!src.length) return bmp;
    var n = src.length, m = src[0].length;
    var scale = Math.max(1, Math.floor(Math.min(H / n, W / m) / 1));
    /* 表情本身为 11 列有效内容，居中绘制 */
    var ox = Math.floor((W - (m - 1) * scale) / 2);
    var oy = Math.floor((H - (n - 1) * scale) / 2);
    for (var y = 0; y < n; y++) {
      for (var x = 0; x < m; x++) {
        if (src[y][x] !== '#') continue;
        for (var dy = 0; dy < scale; dy++) {
          for (var dx = 0; dx < scale; dx++) {
            var bx = ox + x * scale + dx, by = oy + y * scale + dy;
            if (bx >= 0 && bx < W && by >= 0 && by < H) bmp[by * W + bx] = 1;
          }
        }
      }
    }
    return bmp;
  }

  /* 任意位图 → 居中放入 128×64 */
  function fitBits(src, sw, sh) {
    var out = newBits();
    var s = Math.min(W / sw, H / sh);
    var dw = Math.max(1, Math.round(sw * s)), dh = Math.max(1, Math.round(sh * s));
    var ox = Math.floor((W - dw) / 2), oy = Math.floor((H - dh) / 2);
    for (var y = 0; y < dh; y++) {
      for (var x = 0; x < dw; x++) {
        var v = src[(Math.floor(y / s) * sw) + Math.floor(x / s)];
        if (v) {
          var py = oy + y, px = ox + x;
          if (px >= 0 && px < W && py >= 0 && py < H) out[py * W + px] = 1;
        }
      }
    }
    return out;
  }

/* 位图 → MONO_HLSB 字节数组（mpython framebuf 格式）
   framebuf.MONO_HLSB 布局：像素按行从左到右、每行字节数 = ceil(宽/8)，
   每字节内 MSB 在最左。即：第 y 行第 x 像素 → 字节 y*(W/8) + (x>>3)，
   该字节的位 7-(x&7)。行跨度必须是 W/8 字节，不能按总像素连续排布。 */
function bitsToBytesHLSB(bits) {
  var stride = W >> 3;          // 每行字节数：128/8 = 16
  var out = new Array(H * stride);
  for (var y = 0; y < H; y++) {
    for (var byteCol = 0; byteCol < stride; byteCol++) {
      var v = 0;
      for (var i = 0; i < 8; i++) {
        if (bits[y * W + byteCol * 8 + i]) v |= (0x80 >> i);
      }
      out[y * stride + byteCol] = v;
    }
  }
  return out;
}

  /* 位图 → PNG dataURL（用于虚拟屏与舞台预览） */
  function bitsToDataURL(bits) {
    var cv = document.createElement('canvas');
    cv.width = W; cv.height = H;
    var c = cv.getContext('2d');
    var img = c.createImageData(W, H);
    for (var i = 0; i < W * H; i++) {
      var on = bits[i];
      /* 像素化外观：每个 OLED 像素画成 2×2 方块 */
      img.data[i * 4] = on ? 255 : 12;
      img.data[i * 4 + 1] = on ? 255 : 16;
      img.data[i * 4 + 2] = on ? 255 : 20;
      img.data[i * 4 + 3] = 255;
    }
    c.putImageData(img, 0, 0);
    return cv.toDataURL('image/png');
  }

  /* ============================================================
   * 图片像素化处理
   * ============================================================ */
  function fileToBitmap(file, opts, cb) {
    opts = opts || {};
    if (!file) return cb(new Error('未选择文件'));
    if (ALLOW.indexOf(file.type) < 0 && !/\.(png|jpe?g|gif|bmp|webp)$/i.test(file.name)) {
      return cb(new Error('不支持的格式：' + (file.type || '未知') + '。仅支持 PNG / JPG / GIF / BMP / WebP'));
    }
    if (file.size > MAX_BYTES) {
      return cb(new Error('图片过大（' + (file.size / 1024 / 1024).toFixed(1) +
        'MB），上限 3MB。请先压缩后再上传'));
    }
    var fr = new FileReader();
    fr.onerror = function () { cb(new Error('文件读取失败')); };
    fr.onload = function () {
      var img = new Image();
      img.onerror = function () { cb(new Error('图片解码失败，请换一张')); };
      img.onload = function () {
        try {
          var sw = img.naturalWidth || img.width, sh = img.naturalHeight || img.height;
          if (!sw || !sh) return cb(new Error('图片尺寸无效'));
          if (sw * sh > 4000 * 4000) return cb(new Error('图片分辨率过大（' + sw + '×' + sh + '）'));

          /* 等比缩放到不超过 OLED 尺寸（可再留白） */
          var maxW = opts.maxW || W, maxH = opts.maxH || H;
          var scale = Math.min(maxW / sw, maxH / sh, 1);
          var dw = Math.max(1, Math.round(sw * scale));
          var dh = Math.max(1, Math.round(sh * scale));

          var cv = document.createElement('canvas');
          cv.width = dw; cv.height = dh;
          var c = cv.getContext('2d', { willReadFrequently: true });
          c.imageSmoothingEnabled = true;
          c.imageSmoothingQuality = 'high';
          c.drawImage(img, 0, 0, dw, dh);

          var data = c.getImageData(0, 0, dw, dh).data;
          /* 灰度 + 阈值 → 1bit 位图（保留灰度层次感：可调阈值） */
          var thr = opts.threshold === undefined ? 128 : opts.threshold;
          var bits = new Uint8Array(dw * dh);
          var sum = 0;
          for (var i = 0; i < dw * dh; i++) {
            var r = data[i * 4], g = data[i * 4 + 1], b = data[i * 4 + 2];
            var lum = 0.299 * r + 0.587 * g + 0.114 * b;
            sum += lum;
            bits[i] = lum >= thr ? 1 : 0;
          }
          /* 对比度过低（纯色图）时自适应阈值：取均值 */
          if (opts.auto !== false) {
            var mean = sum / (dw * dh);
            if (mean > 40 && mean < 215) {
              var t2 = Math.round(mean);
              for (var k = 0; k < bits.length; k++) {
                var l2 = 0.299 * data[k * 4] + 0.587 * data[k * 4 + 1] + 0.114 * data[k * 4 + 2];
                bits[k] = l2 >= t2 ? 1 : 0;
              }
              thr = t2;
            }
          }
          cb(null, { bits: bits, w: dw, h: dh, threshold: thr, name: file.name, bytes: file.size });
        } catch (err) {
          cb(new Error('处理失败：' + err.message));
        }
      };
      img.src = fr.result;
    };
    fr.readAsDataURL(file);
  }

  /* ============================================================
   * 图片库（内存 + IndexedDB 持久化）
   * ============================================================ */
  var library = {};   // id -> {id,name,bits,w,h,kind}
  var order = [];

  function register(rec) {
    if (!rec.id) return null;
    library[rec.id] = rec;
    if (order.indexOf(rec.id) < 0) order.push(rec.id);
    if (ZKB.Store && rec.bits) {
      /* 位图存为普通数组以便结构化克隆 */
      var clone = {
        id: rec.id, name: rec.name, kind: rec.kind || 'upload',
        w: rec.w, h: rec.h, threshold: rec.threshold,
        bits: Array.prototype.slice.call(rec.bits)
      };
      ZKB.Store.saveImage(clone);
    }
    return rec;
  }

  function get(id) { return library[id] || null; }
  function list() { return order.map(function (id) { return library[id]; }).filter(Boolean); }

  function remove(id) {
    delete library[id];
    order = order.filter(function (x) { return x !== id; });
    if (ZKB.Store) ZKB.Store.deleteImage(id);
  }

  /* 启动时恢复内置表情 + 上次上传的图片 */
  function restore() {
    Object.keys(FACES).forEach(function (k) {
      var f = FACES[k];
      register({ id: 'face_' + k, name: '表情·' + f.name, kind: 'face', face: k, bits: faceToBits(f), w: W, h: H });
    });
    if (ZKB.Store) {
      ZKB.Store.listImages().then(function (recs) {
        (recs || []).forEach(function (r) {
          if (!r || !r.bits) return;
          if (library[r.id]) return;
          r.bits = Uint8Array.from(r.bits);
          library[r.id] = r;
          if (order.indexOf(r.id) < 0) order.push(r.id);
        });
      });
    }
  }

  /* ============================================================
   * 显示：写入虚拟屏 + 舞台同步
   * ============================================================ */
  var currentId = null;

  function show(id) {
    var rec = get(id);
    if (!rec) return false;
    currentId = id;
    var bits = rec.bits;

    /* 1) 虚拟仿真的掌控板小屏 */
    if (ZKB.SimEngine && ZKB.SimEngine.oled) {
      try { ZKB.SimEngine.oled.bitmap(bits, 0, 0); } catch (e) {}
    }
    /* 2) 舞台上的小助手同步屏幕内容（表情或图片） */
    if (rec.kind === 'face' && ZKB.Stage && ZKB.Stage.setMood) {
      ZKB.Stage.setMood(rec.face);
    }
    /* 通知舞台刷新小助手屏幕（不额外在左上角放屏幕预览，
       舞台只保留「掌控小助手」上的那一块屏，与虚拟仿真同步） */
    if (ZKB.Stage && ZKB.Stage.refreshAssistant) {
      try { ZKB.Stage.refreshAssistant(); } catch (e) {}
    }
    if (ZKB.log) ZKB.log('屏幕显示：' + rec.name, 'log-ok');
    if (ZKB.toast) ZKB.toast('屏幕已显示「' + rec.name + '」');
    return true;
  }

  function getCurrent() { return currentId ? get(currentId) : null; }

  /* ============================================================
   * MicroPython 代码生成
   * ============================================================ */
  function pythonFor(id) {
    var rec = get(id);
    if (!rec) return null;
    var bytes = bitsToBytesHLSB(rec.bits);
    var hex = bytes.map(function (b) { return ('0' + b.toString(16)).slice(-2); }).join('');
    /* 注意：这里只产出「字节数组内容」与声明文本，变量名由 gen-python 的
       PyImageRegistry 统一分配（同一张图只生成一份，多图依次命名 zk_img0/1…）。
       因此不要在此写死变量名，否则声明与调用会不一致。 */
    return {
      hex: hex,
      decl: '[\n' + chunk(hex, 64) + ']',
      byteLen: bytes.length
    };
  }
  function chunk(s, n) {
    var out = [];
    for (var i = 0; i < s.length; i += n) {
      out.push("    '" + s.substr(i, n) + "'");
    }
    return out.join(',\n');
  }

  /* ============================================================
   * 导出接口
   * ============================================================ */
  ZKB.OledImage = {
    W: W, H: H, MAX_BYTES: MAX_BYTES, ALLOW: ALLOW,
    FACES: FACES,
    restore: restore,
    fileToBitmap: fileToBitmap,
    bitsToDataURL: bitsToDataURL,
    faceToBits: function (k) { return FACES[k] ? faceToBits(FACES[k]) : null; },
    register: register,
    get: get,
    list: list,
    remove: remove,
    show: show,
    current: getCurrent,
    pythonFor: pythonFor,
    bitsToBytesHLSB: bitsToBytesHLSB
  };

})(window);