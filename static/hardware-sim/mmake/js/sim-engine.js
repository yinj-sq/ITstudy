/* ============================================================
 * sim-engine.js —— 仿真运行时 S：调度 + 虚拟硬件 API
 * ============================================================ */
(function (global) {
  'use strict';
  var ZKB = global.ZKB;
  var st = null;        // 状态（init 时取）
  var running = false;
  var tasks = 0;
  var startedAt = Date.now();   // 本轮运行起点（elapsed 用）

  /* 日志（app.js 提供 ZKB.log） */
  function log(v, cls, group) { (ZKB.log || console.log)(v, cls || 'log-sim', group); }

  /* 音符频率 */
  var NOTE_FREQ = {
    C4: 262, D4: 294, E4: 330, F4: 349, G4: 392, A4: 440, B4: 494,
    C5: 523, D5: 587, E5: 659, F5: 698, G5: 784, A5: 880, B5: 988, C6: 1047
  };

  /* ---------------- OLED 虚拟屏幕 ----------------
     画布挂在 3D 掌控板的 TFT 屏上（#b3-oled），
     若不存在则退回旧 2D 看板的 #oled-canvas。
     物理分辨率 256×128，ctx.scale(2,2) 后按 128×64 逻辑坐标绘制。 */
  /* 屏幕内容版本号：每次绘制 +1，供舞台小助手按版本缓存镜像（避免每帧 toDataURL） */
  function oledBump(live) {
    if (!ZKB.state) return;
    ZKB.state.oledVer = (ZKB.state.oledVer || 0) + 1;
    if (live != null) ZKB.state.oledLive = !!live;
  }
  var oled = {
    cv: null, ctx: null, inverted: false,
    init: function () {
      /* 若已初始化且画布仍在，直接复用（避免重复 scale） */
      if (this.cv && this.ctx && document.body.contains(this.cv)) return true;
      this.cv = (ZKB.Board3D && ZKB.Board3D.oledCanvas && ZKB.Board3D.oledCanvas()) ||
        document.getElementById('oled-canvas');
      if (!this.cv) return false;
      this.cv.width = 256; this.cv.height = 128;
      this.ctx = this.cv.getContext('2d');
      if (!this.ctx) return false;
      this.ctx.setTransform ? this.ctx.setTransform(2, 0, 0, 2, 0, 0) : this.ctx.scale(2, 2);
      this.ctx.imageSmoothingEnabled = false;
      this.clear();
      return true;
    },
    px: function () { return this.ctx; },
    clear: function () {
      if (!this.ctx) { this.init(); if (!this.ctx) return; }
      var c = this.ctx;
      c.fillStyle = '#000'; c.fillRect(0, 0, 128, 64);
      oledBump(false);
    },
    fill: function (v) {
      var c = this.ctx; if (!c) return;
      c.fillStyle = v ? '#fff' : '#000'; c.fillRect(0, 0, 128, 64);
      oledBump(!!v);
    },
    pixel: function (x, y, v) {
      var c = this.ctx; if (!c) return;
      c.fillStyle = v ? '#fff' : '#000'; c.fillRect(x | 0, y | 0, 1, 1);
      oledBump(true);
    },
    line: function (x1, y1, x2, y2) {
      var c = this.ctx; if (!c) return;
      c.strokeStyle = '#fff'; c.lineWidth = 1;
      c.beginPath(); c.moveTo(x1, y1); c.lineTo(x2, y2); c.stroke();
      oledBump(true);
    },
    rect: function (x, y, w, h, fill) {
      var c = this.ctx; if (!c) return;
      if (fill) { c.fillStyle = '#fff'; c.fillRect(x, y, w, h); }
      else { c.strokeStyle = '#fff'; c.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1); }
      oledBump(true);
    },
    circle: function (x, y, r, fill) {
      var c = this.ctx; if (!c) return;
      c.beginPath(); c.arc(x, y, r, 0, Math.PI * 2);
      if (fill) { c.fillStyle = '#fff'; c.fill(); } else { c.strokeStyle = '#fff'; c.stroke(); }
      oledBump(true);
    },
    /* 显示文字：以「文字左上角」为坐标起点（textAlign=left, textBaseline=top）
       color 可选，默认白色，支持 8 种屏幕颜色名。 */
    COLORS: {
      'white': '#ffffff', 'black': '#000000', 'red': '#ff5555', 'green': '#55ff55',
      'blue': '#5555ff', 'yellow': '#ffff55', 'cyan': '#55ffff', 'magenta': '#ff55ff'
    },
    textColor: '#ffffff',
    text: function (s, x, y, chinese, color) {
      if (!this.init()) return;
      var c = this.ctx;
      var col = color || this.textColor || '#ffffff';
      if (this.COLORS[col]) col = this.COLORS[col];
      c.fillStyle = col;
      c.font = (chinese ? '10px ' : '9px ') + '"Microsoft YaHei",monospace';
      /* 明确以左上角为基准 */
      c.textAlign = 'left';
      c.textBaseline = 'top';
      c.fillText(String(s), Math.round(x || 0), Math.round(y || 0));
      oledBump(true);
      /* 记录最近绘制的文字（小助手屏幕下方同步显示） */
      if (ZKB.state) ZKB.state.oledLastText = String(s).slice(0, 24);
    },
    /* 设置文字颜色 */
    setTextColor: function (name) {
      this.textColor = (this.COLORS && this.COLORS[name]) ? name : 'white';
      return this.textColor;
    },
    /* ---------- 第二十九轮：5 行定位显示 + 二维码 ----------
       官方 DispChar_5lines 把 128x64 分成 5 行、每行 12 像素高，
       这里照搬这个划分：y = (line-1) * 12，先擦该行再写，避免残留。 */
    line5: function (s, line, chinese) {
      if (!this.init()) return;
      var n = Math.max(1, Math.min(5, parseInt(line, 10) || 1));
      var y = (n - 1) * 12;
      var c = this.ctx;
      /* 擦掉这一行（黑底），官方是先 fill 再显示文字 */
      c.fillStyle = '#000000';
      c.fillRect(0, y, 128, 12);
      this.text(s, 0, y, chinese);
    },
    /* ============================================================
     * 二维码（第三十三轮换成真码）
     * 之前是按内容散列画的伪点阵，扫枪扫不出来。
     * 现在交给 js/qrcode.js 的完整 QR 编码器（字节模式 + Reed-Solomon
     * + 掩码择优），生成的是真正可扫读的码，中文也支持。
     * 128×64 的屏放不下大码，会自动按整数比例缩小并保证静区。
     * ============================================================ */
    qrcode: function (str, x, y) {
      if (!this.init()) return null;
      var s = String(str == null ? '' : str);
      var r = ZKB.QRCode ? ZKB.QRCode.draw(this.ctx, s, x || 0, y || 0, 2,
        { maxW: 128, maxH: 64 }) : null;
      if (!r || !r.ok) {
        /* 内容太长：给出可见提示，而不是画一坨乱码 */
        this.text('QR内容太长', 0, 0, true);
        this.show();
        if (ZKB.log) ZKB.log('二维码内容过长：' + (r && r.reason || '编码失败'), 'log-warn');
        return r;
      }
      oledBump(true);
      if (ZKB.state) ZKB.state.oledLastText = '[二维码] ' + s.slice(0, 16);
      if (ZKB.log) {
        ZKB.log('已生成二维码「' + s.slice(0, 24) + '」：' + r.reason, 'log-sim');
      }
      return r;
    },
    invert: function (v) { if (this.cv) this.cv.style.filter = v ? 'invert(1)' : ''; this.inverted = !!v; },
    show: function () {
      /* 虚拟屏即时刷新；同步到 3D 掌控板的 TFT 彩屏 */
      if (ZKB.Board3D) ZKB.Board3D.syncOLED();
    },
    /**
     * 显示 1bit 位图（128×64）—— 供「屏幕显示图片 / 内置表情」使用。
     * bits 为 Uint8Array(W*H)，0/1，1=点亮；ox/oy 为偏移。
     * 像素化观感：每点绘制 1×1 逻辑像素，画布已 2× 放大 + 关闭平滑。
     */
    bitmap: function (bits, ox, oy) {
      var c = this.ctx; if (!c) return;
      ox = ox || 0; oy = oy || 0;
      c.fillStyle = '#000'; c.fillRect(0, 0, 128, 64);
      if (!bits) return;
      c.fillStyle = '#fff';
      var bw = Math.min(128 - ox, ZKB.OledImage ? ZKB.OledImage.W : 128);
      var bh = Math.min(64 - oy, ZKB.OledImage ? ZKB.OledImage.H : 64);
      for (var y = 0; y < bh; y++) {
        var row = y * 128;
        /* 逐行扫描合并连续点亮像素，减少 fillRect 次数 */
        var x = 0;
        while (x < bw) {
          if (bits[row + x]) {
            var x0 = x;
            while (x < bw && bits[row + x]) x++;
            c.fillRect(ox + x0, oy + y, x - x0, 1);
          } else x++;
        }
      }
      /* 同步舞台表情（表情图时） */
      if (ZKB.Store) { /* 状态已由 OledImage.show 维护 */ }
      /* 同步 3D 板 TFT 彩屏 */
      if (ZKB.Board3D) ZKB.Board3D.syncOLED();
      oledBump(true);
    },
    /* 显示图片库中的位图（zk_oled_image） */
    showImage: function (id) {
      if (ZKB.OledImage) { ZKB.OledImage.show(id); }
      else { log('图片库未初始化', 'log-err'); }
    },
    /* 显示内置表情（zk_oled_face） */
    showFace: function (k) {
      if (!ZKB.OledImage) return;
      var rec = ZKB.OledImage.get('face_' + k);
      if (rec) ZKB.OledImage.show('face_' + k);
      else log('表情未找到：' + k, 'log-err');
    },
    /* 圆角矩形 */
    roundrect: function (x, y, w, h, r, v) {
      var c = this.ctx; if (!c) return;
      c.fillStyle = v ? '#fff' : '#000';
      if (v) { roundRectPath(c, x, y, w, h, r); c.fill(); return; }
      c.strokeStyle = '#fff'; c.lineWidth = 1;
      roundRectPath(c, x + 0.5, y + 0.5, w - 1, h - 1, r); c.stroke();
    },
    hline: function (x, y, w, v) {
      var c = this.ctx; if (!c) return;
      c.fillStyle = v ? '#fff' : '#000'; c.fillRect(x | 0, y | 0, w | 0, 1);
    },
    vline: function (x, y, l, v) {
      var c = this.ctx; if (!c) return;
      c.fillStyle = v ? '#fff' : '#000'; c.fillRect(x | 0, y | 0, 1, l | 0);
    },
    triangle: function (x0, y0, x1, y1, x2, y2, v) {
      var c = this.ctx; if (!c) return;
      c.beginPath(); c.moveTo(x0, y0); c.lineTo(x1, y1); c.lineTo(x2, y2); c.closePath();
      if (v) { c.fillStyle = '#fff'; c.fill(); }
      else { c.strokeStyle = '#fff'; c.lineWidth = 1; c.stroke(); }
    },
    /* UI.ProgressBar：外框 + 内部填充比例 */
    progress: function (x, y, w, h, p) {
      var c = this.ctx; if (!c) return;
      p = Math.max(0, Math.min(100, Number(p) || 0));
      c.fillStyle = '#fff'; c.fillRect(x, y, w, h);
      c.fillStyle = '#000'; c.fillRect(x + 1, y + 1, w - 2, h - 2);
      var iw = Math.round((w - 4) * p / 100);
      c.fillStyle = '#fff'; c.fillRect(x + 2, y + 2, iw, h - 4);
    },
    /* UI.stripBar：dir=1 水平，dir=0 垂直；frame=1 带外框 */
    stripbar: function (x, y, w, h, p, dir, frame) {
      var c = this.ctx; if (!c) return;
      p = Math.max(0, Math.min(100, Number(p) || 0));
      if (Number(frame)) {
        c.strokeStyle = '#fff'; c.lineWidth = 1;
        c.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);
      }
      c.fillStyle = '#fff';
      if (Number(dir) === 1) {
        c.fillRect(x + 1, y + 1, Math.round((w - 2) * p / 100), h - 2);
      } else {
        var ih = Math.round((h - 2) * p / 100);
        c.fillRect(x + 1, y + h - 1 - ih, w - 2, ih);
      }
    }
  };

  /* 圆角矩形路径 */
  function roundRectPath(c, x, y, w, h, r) {
    r = Math.max(0, Math.min(r, Math.min(w, h) / 2));
    c.beginPath();
    c.moveTo(x + r, y);
    c.arcTo(x + w, y, x + w, y + h, r);
    c.arcTo(x + w, y + h, x, y + h, r);
    c.arcTo(x, y + h, x, y, r);
    c.arcTo(x, y, x + w, y, r);
    c.closePath();
  }

  /* ---------------- 声音（WebAudio） ---------------- */
  var audio = {
    ctx: null, osc: null, gain: null,
    ensure: function () {
      if (!this.ctx) {
        var AC = window.AudioContext || window.webkitAudioContext;
        if (AC) this.ctx = new AC();
      }
      if (this.ctx && this.ctx.state === 'suspended') this.ctx.resume();
    },
    tone: function (freq) {
      this.ensure();
      if (!this.ctx) return;
      this.stop();
      this.osc = this.ctx.createOscillator();
      this.gain = this.ctx.createGain();
      this.osc.type = 'square';
      this.osc.frequency.value = freq;
      this.gain.gain.value = 0.06;
      this.osc.connect(this.gain); this.gain.connect(this.ctx.destination);
      this.osc.start();
    },
    stop: function () {
      if (this.osc) { try { this.osc.stop(); } catch (e) {} this.osc = null; }
    }
  };

  /* ---------------- 执行器界面刷新 ---------------- */
  /* 多实例（第十三轮）：base + 序号 → 实例键；实例状态缺失时从基础原型克隆 */
  function devKey(base, inst) {
    inst = Number(inst) || 1;
    return inst > 1 ? base + '__' + inst : base;
  }
  function devOf(base, inst) {
    var k = devKey(base, inst);
    if (!st.devices[k] && st.devices[base]) {
      st.devices[k] = JSON.parse(JSON.stringify(st.devices[base]));
    }
    return st.devices[k] || st.devices[base] || {};
  }
  /* 第三十五轮：K210 预置模型的仿真状态（存在设备状态里，随运行重置） */
  function kpuState() {
    if (!st.devices._kpu) {
      st.devices._kpu = { model: '', faces: [], objs: [], digit: -1 };
    }
    return st.devices._kpu;
  }
  function servoUI(angle, key) {
    key = key || 'servo';
    angle = Math.max(0, Math.min(180, Math.round(angle)));
    if (!st.devices[key]) st.devices[key] = { angle: 90 };
    st.devices[key].angle = angle;
    var card = document.getElementById('card-' + key);
    if (card) {
      var g = card.querySelector('.servo-horn');
      if (g) g.style.transform = 'rotate(' + (angle - 90) + 'deg)';
      var el = card.querySelector('#v-servo');
      if (el) el.textContent = angle;
    }
  }
  function heaterUI(key) {
    key = key || 'heater';
    var d = st.devices[key] || { on: false, power: 0 }, card = document.getElementById('card-' + key);
    if (!card) return;
    var face = card.querySelectorAll('.card-icon svg circle');
    var p = d.on ? d.power / 100 : 0;
    if (face[1]) face[1].setAttribute('fill', 'rgb(' + (240 - p * 40) + ',' + (116 + p * 130) + ',' + (95 + p * 100) + ')');
    card.querySelector('.card-icon svg').style.filter = p > 0 ? 'drop-shadow(0 0 ' + (4 + p * 10) + 'px rgba(255,90,20,' + p + '))' : '';
    card.classList.toggle('running', d.on);
  }
  function pumpUI(key) {
    key = key || 'pump';
    var d = st.devices[key] || { on: false }, card = document.getElementById('card-' + key);
    if (!card) return;
    card.classList.toggle('running', d.on);
    var drop = card.querySelector('.card-icon svg path:last-child');
    if (drop) { drop.setAttribute('fill', d.on ? '#4d9dff' : '#2f5d80'); }
  }
  function motorUI(key) {
    key = key || 'motor';
    var d = st.devices[key] || { vel: 0 }, card = document.getElementById('card-' + key);
    if (!card) return;
    var blade = card.querySelector('.motor-spin');
    card.classList.toggle('running', d.vel !== 0);
    if (blade) {
      if (d.vel === 0) { blade.classList.remove('spin'); }
      else {
        blade.classList.add('spin');
        blade.style.setProperty('--spin-dur', Math.max(0.08, 0.9 - Math.abs(d.vel) / 100 * 0.8) + 's');
        blade.style.animationDirection = d.vel > 0 ? 'normal' : 'reverse';
      }
    }
  }
  function carUI(key) {
    key = key || 'car';
    var c = st.devices[key] || { l: 0, r: 0 }, card = document.getElementById('card-' + key);
    if (!card) return;
    card.classList.toggle('running', c.l !== 0 || c.r !== 0);
    var l = card.querySelector('#v-car-l'), r = card.querySelector('#v-car-r');
    if (l) l.textContent = c.l; if (r) r.textContent = c.r;
  }
  /* 巡线小车卡片刷新（电机 / 巡线开关 / 循线状态 / 前方距离） */
  function traceUI(d) {
    d = d || st.devices.traceCar;
    if (!d) return;
    var card = document.getElementById('card-traceCar');
    if (!card) return;
    var set = function (id, txt) { var e = card.querySelector(id); if (e) e.textContent = txt; };
    set('#v-tc-l', d.l || 0); set('#v-tc-r', d.r || 0);
    set('#v-tc-line', d.line || '离线');
    set('#v-tc-dist', d.dist == null ? '--' : d.dist);
    var au = card.querySelector('#tc-auto');
    if (au) au.textContent = '自动巡线：' + (d.auto ? '开' : '关');
    card.classList.toggle('running', !!(d.l || d.r));
  }
  function fanUI(key) {
    key = key || 'fan';
    var d = st.devices[key] || { on: false, power: 0 }, card = document.getElementById('card-' + key);
    if (!card) return;
    var blade = card.querySelector('.fan-spin');
    card.classList.toggle('running', d.on);
    if (blade) {
      if (!d.on) { blade.classList.remove('spin'); }
      else {
        blade.classList.add('spin');
        blade.style.setProperty('--spin-dur', Math.max(0.12, 1.2 - d.power / 100 * 1.05) + 's');
      }
    }
  }

  /* ---------------- 运行时 S ---------------- */
  var S = null;
  var LOOP_PACE = 100;   // 循环每次迭代的最小时长（ms），防止刷屏与空转
  var lastBeat = 0;

  /* ============================================================
   * 天气服务（ZKB.Weather）—— 第二十二轮扩展
   *   联网：Open-Meteo 免费接口（无需密钥、支持跨域）
   *        · 实况：温度 / 相对湿度 / 天气代码 / 风速·风向
   *        · 预报：当日最高 / 最低温
   *   城市地理编码：Open-Meteo geocoding 接口，输入城市名 → 经纬度
   *        （支持手动添加任意城市；失败时回落到内置城市表 / 全国默认坐标）
   *   离线/失败：按「城市 + 当前月份」的气候常识模拟全套六项数据
   *   结果缓存 30 分钟，供天气积木与拓展库卡片共用
   * ============================================================ */
  var WEATHER_CITIES = [
    { name: '北京', lat: 39.904, lon: 116.407 },
    { name: '上海', lat: 31.230, lon: 121.474 },
    { name: '广州', lat: 23.129, lon: 113.264 },
    { name: '深圳', lat: 22.543, lon: 114.058 },
    { name: '杭州', lat: 30.274, lon: 120.155 },
    { name: '长沙', lat: 28.228, lon: 112.939 }
  ];
  /* 各城市 1~12 月的常年气候（高/低气温 ℃、典型天气）——离线模拟用 */
  var WEATHER_MONTHS = {
    '北京': [[2, -8, '晴'], [5, -5, '晴'], [11, 2, '多云'], [19, 6, '多云'], [26, 14, '晴'],
    [30, 19, '雷阵雨'], [31, 23, '雷阵雨'], [30, 22, '阵雨'], [26, 15, '晴'], [19, 7, '晴'],
    [10, -1, '多云'], [4, -6, '晴']],
    '上海': [[8, 2, '阴'], [10, 3, '阴'], [15, 7, '多云'], [21, 12, '多云'], [26, 18, '晴'],
    [29, 23, '雷阵雨'], [33, 26, '晴'], [33, 26, '晴'], [29, 23, '雷阵雨'], [24, 17, '多云'],
    [18, 11, '阴'], [11, 5, '阴']],
    '广州': [[19, 10, '阴'], [20, 12, '阴'], [22, 15, '阴'], [26, 19, '阵雨'], [30, 23, '雷阵雨'],
    [32, 26, '雷阵雨'], [33, 27, '晴'], [33, 27, '晴'], [32, 25, '雷阵雨'], [30, 22, '晴'],
    [25, 17, '阴'], [21, 12, '晴']],
    '深圳': [[20, 12, '晴'], [20, 13, '阴'], [22, 16, '阴'], [26, 20, '阵雨'], [30, 24, '雷阵雨'],
    [32, 26, '雷阵雨'], [33, 27, '晴'], [33, 27, '晴'], [32, 26, '雷阵雨'], [30, 23, '晴'],
    [26, 19, '晴'], [22, 15, '晴']],
    '杭州': [[8, 3, '阴'], [10, 4, '阴'], [15, 8, '多云'], [21, 13, '多云'], [26, 18, '多云'],
    [29, 23, '雷阵雨'], [35, 26, '晴'], [34, 26, '晴'], [30, 22, '雷阵雨'], [24, 16, '多云'],
    [17, 10, '阴'], [11, 5, '阴']],
    '长沙': [[9, 3, '阴'], [11, 5, '阴'], [16, 9, '多云'], [22, 14, '多云'], [27, 19, '阵雨'],
    [30, 23, '雷阵雨'], [34, 26, '晴'], [33, 26, '晴'], [30, 23, '晴'], [24, 17, '多云'],
    [18, 11, '阴'], [12, 6, '阴']]
  };
  /* WMO 天气代码 → 中文（Open-Meteo current.weather_code） */
  var WMO_TEXT = {
    0: '晴', 1: '晴', 2: '多云', 3: '阴', 45: '雾', 48: '雾',
    51: '小雨', 53: '小雨', 55: '中雨', 56: '冻雨', 57: '冻雨',
    61: '小雨', 63: '中雨', 65: '大雨', 66: '冻雨', 67: '冻雨',
    71: '小雪', 73: '中雪', 75: '大雪', 77: '米雪',
    80: '阵雨', 81: '阵雨', 82: '强阵雨', 85: '阵雪', 86: '阵雪',
    95: '雷阵雨', 96: '雷阵雨', 99: '雷阵雨'
  };
  var weatherCache = {};   /* city -> {data, at} */

  /* 用户手动添加的城市（name -> {name, lat, lon}），存localStorage 长期保留 */
  var CITY_LS_KEY = 'zkb_weather_cities_v1';
  var userCities = (function () {
    var list = [];
    try {
      var raw = ZKB.Store && ZKB.Store.getLocal ? ZKB.Store.getLocal(CITY_LS_KEY) : null;
      if (raw && raw.length) list = raw;
    } catch (e) { /* 忽略：隐私模式等*/ }
    return list;
  })();
  function saveUserCities() {
    try { if (ZKB.Store && ZKB.Store.setLocal) ZKB.Store.setLocal(CITY_LS_KEY, userCities); } catch (e) { }
  }

  /* 城市解析：优先用户添加 → 内置表；都没有则按名留待地理编码 */
  function weatherCity(name) {
    var n = String(name == null ? '' : name).trim();
    if (!n) return WEATHER_CITIES[0];
    for (var i = 0; i < userCities.length; i++) {
      if (userCities[i].name === n) return userCities[i];
    }
    for (var j = 0; j < WEATHER_CITIES.length; j++) {
      if (WEATHER_CITIES[j].name === n) return WEATHER_CITIES[j];
    }
    return null;
  }
  /* 城市是否已有坐标（内置或用户添加） */
  function hasCoords(city) {
    return !!weatherCity(city);
  }
  /* 已收录城市名列表（内置 + 用户添加），供积木下拉、卡片城市区使用 */
  function allCityNames() {
    var out = [];
    WEATHER_CITIES.forEach(function (c) { out.push(c.name); });
    userCities.forEach(function (c) { if (out.indexOf(c.name) < 0) out.push(c.name); });
    return out;
  }

  /* ---- 地理编码：城市名 → 经纬度（Open-Meteo geocoding，中文名支持） ---- */
  var geoCache = {};
  function geocodeCity(name) {
    var n = String(name || '').trim();
    if (!n) return Promise.resolve(null);
    var known = weatherCity(n);
    if (known) return Promise.resolve({ name: known.name, lat: known.lat, lon: known.lon });
    if (geoCache[n]) return Promise.resolve(geoCache[n]);
    if (typeof fetch !== 'function' || (typeof navigator !== 'undefined' && navigator.onLine === false)) {
      return Promise.resolve(null);
    }
    var url = 'https://geocoding-api.open-meteo.com/v1/search?count=1&language=zh&format=json&name=' +
      encodeURIComponent(n);
    /* 返回 Promise。注意：超时回调与 resolve 必须共享同一闭包，
     所以 finish 要定义在 Promise 构造器内部——若把 setTimeout 提到外面，
     它的回调里resolve 不在作用域内，Promise 将永不 settle（表现为
     「正在查询坐标…」一直卡住）。*/
    return new Promise(function (resolvePromise) {
      var settled = false, timer = null;
      function finish(v) {
        if (settled) return;
        settled = true;
        if (timer) clearTimeout(timer);
        geoCache[n] = v;
        resolvePromise(v);
      }
      /* 6 秒兜底：网络不通 / 跨域被拦时也返回 null，让调用方走离线分支 */
      timer = setTimeout(function () { finish(null); }, 6000);
      try {
        fetch(url).then(function (r) { return r.ok ? r.json() : null; }).then(function (j) {
          var hit = j && j.results && j.results[0];
          if (!hit) return finish(null);
          finish({
            name: hit.name || n,
            lat: hit.latitude, lon: hit.longitude,
            admin: hit.admin1 || hit.country || ''
          });
        }).catch(function () { finish(null); });
      } catch (e) { finish(null); }
    });
  }
  /* 手动添加城市：地理编码成功（或已知城市）后收录，返回 {ok, city, msg} */
  function addCity(name) {
    var n = String(name || '').trim();
    if (!n) return Promise.resolve({ ok: false, msg: '请输入城市名' });
    var dup = allCityNames().filter(function (x) { return x === n; });
    if (dup.length) return Promise.resolve({ ok: false, city: { name: n }, msg: '「' + n + '」已在列表中' });
    return geocodeCity(n).then(function (c) {
      if (!c || typeof c.lat !== 'number' || typeof c.lon !== 'number') {
        return { ok: false, msg: '未找到城市「' + n + '」，请检查名称（如：成都 / 昆明 / 乌鲁木齐）' };
      }
      var rec = { name: c.name || n, lat: c.lat, lon: c.lon };
      userCities.push(rec);
      saveUserCities();
      return { ok: true, city: rec, msg: '已添加城市「' + rec.name + '」' };
    });
  }
  /* 移除用户添加的城市（内置城市不可移除） */
  function removeCity(name) {
    var n = String(name || '');
    var hit = userCities.filter(function (c) { return c.name === n; })[0];
    if (!hit) return { ok: false, msg: '内置城市不可移除' };
    userCities = userCities.filter(function (c) { return c.name !== n; });
    saveUserCities();
    delete weatherCache[n];
    return { ok: true, msg: '已移除城市「' + n + '」' };
  }

  /* 蒲福风级：风速 km/h → 0~12 级 */
  function beaufort(kmh) {
    var v = Number(kmh) || 0;
    var lv = 0;
    var LIMITS = [1, 6, 12, 20, 29, 39, 50, 62, 75, 89, 103, 118];
    /* 注意：这里必须逐级累加，不能用 some/forEach 的短路写法 */
    for (var i = 0; i < LIMITS.length; i++) {
      if (v >= LIMITS[i]) lv++;
      else break;
    }
    return Math.min(12, lv);
  }
  /* 风向角度（气象来向）→ 中文方位 */
  var DIRS16 = ['北', '北东北', '东北', '东东北', '东', '东东南', '东南', '南东南',
    '南', '南西南', '西南', '西西南', '西', '西西北', '西北', '北西北'];
  function windDirText(deg) {
    var d = ((Number(deg) || 0) % 360 + 360) % 360;
    return DIRS16[Math.round(d / 22.5) % 16] + '风';
  }

  /* 按月份离线模拟（带±3℃ 随机浮动，贴合真实体感），输出完整六项 */
  function simulateWeather(city, month) {
    var known = weatherCity(city);
    var c = known || { name: String(city || '北京') };
    var m = Math.max(1, Math.min(12, month || new Date().getMonth() + 1));
    var row = (WEATHER_MONTHS[c.name] || WEATHER_MONTHS['北京'])[m - 1];
    var jitter = function (v) { return Math.round(v + (Math.random() - 0.5) * 6); };
    var kinds = ['晴', '多云', '阴', '阵雨', '雷阵雨'];
    /* 月份越冷，风通常越大；给出稳定的风向与风力（离线也要能查得到） */
    var windDirDeg = [0, 45, 90, 135, 180, 225, 270, 315][
      Math.floor(Math.random() * 8)];
    var windKmh = Math.round((c.lat || 30) > 35 ? 12 + Math.random() * 14 : 6 + Math.random() * 12);
    return {
      city: c.name, text: row[2],
      high: jitter(row[0]), low: jitter(row[1]),
      humidity: Math.max(25, Math.min(95, Math.round(55 + (row[0] - 18) * 1.6 + (Math.random() - 0.5) * 20))),
      wind: windDirText(windDirDeg),
      windDirDeg: windDirDeg,
      windKmh: windKmh,
      windLevel: beaufort(windKmh),
      month: m, kinds: kinds, source: 'sim'
    };
  }
  /* 联网查询（Open-Meteo，6 秒超时）；失败返回 null
     实况 + 当日预报，字段覆盖天气现象 / 最高温 / 最低温 / 湿度 / 风向 / 风力 */
  function fetchWeather(city) {
    return new Promise(function (resolve) {
      var known = weatherCity(city);
      if (typeof fetch !== 'function' || (typeof navigator !== 'undefined' && navigator.onLine === false)) {
        return resolve(null);
      }
      var c = known || { name: String(city || '北京'), lat: 39.904, lon: 116.407 };
      var url = 'https://api.open-meteo.com/v1/forecast?latitude=' + c.lat + '&longitude=' + c.lon +
        '&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,wind_direction_10m' +
        '&daily=temperature_2m_max,temperature_2m_min&forecast_days=1&timezone=Asia%2FShanghai';
      var done = false;
      var timer = setTimeout(function () { if (!done) { done = true; resolve(null); } }, 6000);
      try {
        fetch(url).then(function (r) { return r.ok ? r.json() : null; }).then(function (j) {
          if (done) return;
          done = true; clearTimeout(timer);
          if (!j || !j.current) return resolve(null);
          var d = j.daily || {};
          var cur = j.current;
          var kmh = cur.wind_speed_10m || 0;
          resolve({
            city: c.name,
            text: WMO_TEXT[cur.weather_code] || '多云',
            high: Math.round((d.temperature_2m_max && d.temperature_2m_max[0]) || cur.temperature_2m),
            low: Math.round((d.temperature_2m_min && d.temperature_2m_min[0]) || cur.temperature_2m),
            humidity: Math.round(cur.relative_humidity_2m || 55),
            wind: windDirText(cur.wind_direction_10m),
            windDirDeg: Math.round(cur.wind_direction_10m || 0),
            windKmh: Math.round(kmh * 10) / 10,
            windLevel: beaufort(kmh),
            source: 'net'
          });
        }).catch(function () {
          if (done) return;
          done = true; clearTimeout(timer); resolve(null);
        });
      } catch (e) {
        clearTimeout(timer); resolve(null);
      }
    });
  }
  /* 统一入口：先取缓存（30 分钟内），否则联网；失败回退月份模拟
     支持未收录的城市：先地理编码拿到经纬度，联网失败则按北京气候模拟 */
  function queryWeather(city, always) {
    var raw = String(city == null ? '' : city).trim() || '北京';
    var known = weatherCity(raw);
    /* 已知城市走同步路径 */
    function run(name) {
      var hit = weatherCache[name];
      if (!always && hit && Date.now() - hit.at < 30 * 60 * 1000) {
        return Promise.resolve(hit.data);
      }
      return fetchWeather(name).then(function (d) {
        if (d) { weatherCache[name] = { data: d, at: Date.now() }; return d; }
        var sim = simulateWeather(name);
        weatherCache[name] = { data: sim, at: Date.now() };
        return sim;
      });
    }
    if (known) return run(known.name);
    /* 未收录城市：先地理编码，再查询 */
    return geocodeCity(raw).then(function (c) {
      return run(c ? c.name : raw);
    });
  }
  /* 同步取（天气积木用）：有缓存用缓存，否则先模拟并后台刷新 */
  function weatherNow(city) {
    var known = weatherCity(city);
    var c = known ? known.name : (String(city || '').trim() || '北京');
    var hit = weatherCache[c];
    if (hit && Date.now() - hit.at < 30 * 60 * 1000) return hit.data;
    /* 若当前网络在线则先尝试（不阻塞积木），本次先用模拟值 */
    queryWeather(c);
    var sim = simulateWeather(c);
    weatherCache[c] = { data: sim, at: Date.now() };
    return sim;
  }
  ZKB.Weather = {
    cities: allCityNames,               /* 函数：返回全部已收录城市名（内置+用户添加） */
    builtin: WEATHER_CITIES.map(function (c) { return c.name; }),
    userCities: function () { return userCities.slice(); },
    city: weatherCity,
    hasCoords: hasCoords,
    geocode: geocodeCity,
    addCity: addCity,
    removeCity: removeCity,
    beaufort: beaufort,
    windDir: windDirText,
    simulate: simulateWeather,
    fetch: fetchWeather,
    query: queryWeather,
    now: weatherNow,
    cache: weatherCache
  };

  /* 把 EL 字段值解析为元素 uid：支持 uid / 元素键（如 car）/ 元素名称 */
  function resolveEl(v) {
    if (!v || !ZKB.Stage || !ZKB.Stage.getItems) return '';
    var list = ZKB.Stage.getItems();
    var i;
    for (i = 0; i < list.length; i++) if (list[i].uid === v) return v;
    for (i = 0; i < list.length; i++) if (list[i].k === v) return list[i].uid;
    for (i = 0; i < list.length; i++) {
      if (ZKB.Stage.nameOf && ZKB.Stage.nameOf(list[i].uid) === v) return list[i].uid;
    }
    return '';
  }

  function buildRuntime() {
    var d = function () { return st.devices; };

    S = {
      running: function () { return running; },
      tick: function () {
        return new Promise(function (res) {
          var wait = Math.max(0, LOOP_PACE - (Date.now() - lastBeat));
          setTimeout(function () { lastBeat = Date.now(); res(); }, wait);
        });
      },
      sleep: function (ms) {
        return new Promise(function (res) {
          var t0 = Date.now();
          (function wait() {
            if (!running || Date.now() - t0 >= ms) { lastBeat = Date.now(); return res(); }
            setTimeout(wait, Math.min(20, ms - (Date.now() - t0)));
          })();
        });
      },
      task: function (fn) {
        tasks++;
        Promise.resolve().then(fn).catch(function (e) { log('运行错误：' + e.message, 'log-err'); })
          .then(function () { tasks = Math.max(0, tasks - 1); });
      },
      on: function (evt, fn) { ZKB.bus.on(evt, function () { if (running) Promise.resolve().then(fn).catch(function (e) { log('事件执行错误：' + e.message, 'log-err'); }); }); },
      reset: function () {
        oled.init();
        st.rgb.dots = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
        ZKB.SimBoard.refreshRGB();
        audio.stop();
        /* 复位网络连接状态（新一轮仿真从断网开始） */
        st.net.wifi = { connected: false, ssid: '' };
        st.net.radio.lastMsg = '';
        st.net.ntp.synced = false;
        st.net.mqtt = { connected: false, host: '', lastTopic: '', lastMsg: '' };
        /* 第二十九轮：复位八年级新增硬件的仿真状态 */
        if (S.rfid) { S.rfid.last = ''; }
        if (S.asr2) { S.asr2.result = ''; S.asr2.armed = false; }
        if (S.sensor) {
          S.sensor.set('magnetic.heading', 0);
          S.sensor.set('gps.ready', 0);
          S.sensor.set('gps.num', 0);
          S.sensor.set('gps.utc', '');
        }
        /* 复位巡线小车（电机停转、恢复自动巡线） */
        if (st.devices.traceCar) {
          st.devices.traceCar.l = 0;
          st.devices.traceCar.r = 0;
          st.devices.traceCar.auto = true;
          st.devices.traceCar.done = false;
        }
      },
      afterStarted: function () { log('仿真开始', 'log-sim'); },

      log: function (v) {
        var s = v === null || v === undefined ? '' : String(v);
        log(s, 'log-sim', 'sim');   // 连续相同输出折叠为一行（×N）
        if (ZKB.Stage) ZKB.Stage.say(s);
      },

      /* 程序已运行秒数 */
      elapsed: function () { return (Date.now() - startedAt) / 1000; },

      /* ---- 音乐（节拍） ---- */
      music: {
        _bpm: 120,
        tempo: function (v) {
          if (v === undefined) return this._bpm;
          this._bpm = Math.max(20, Math.min(400, Number(v) || 120));
          log('音乐速度 = ' + this._bpm + ' BPM', 'log-sim');
        },
        /* 播放音乐库曲目（内置乐曲 / 上传的音频） */
        play: function (id, mode) {
          if (!ZKB.MusicLib) { log('音乐库未加载', 'log-err'); return false; }
          var ok = ZKB.MusicLib.play(id, mode || 'once');
          var tr = ZKB.MusicLib.get(id);
          if (tr) {
            var MODE_CN = {
              once: '播放一次', loop: '无限循环',
              bgOnce: '在后台播放一次', bgLoop: '在后台无限循环'
            };
            log('▶ 播放音乐《' + tr.name + '》（' + (MODE_CN[mode || 'once'] || mode) + '）', 'log-sim');
          }
          return ok;
        },
        stop: function () {
          if (ZKB.MusicLib) ZKB.MusicLib.stop();
          log('⏹ 音乐已停止', 'log-sim');
        }
      },

      /* ---- 集合操作 ---- */
      data: {
        setAdd: function (set, val) {
          if (set && typeof set.add === 'function') { set.add(val); return; }
          log('「加入集合」左侧需接创建集合积木', 'log-err');
        }
      },

      /* ---- 虚拟文件系统（保存在内存，刷新后由 Store 恢复可选） ---- */
      file: {
        _fs: {},
        write: function (path, txt) {
          this._fs[path] = String(txt === undefined || txt === null ? '' : txt);
          log('已写入文件 ' + path + '（' + this._fs[path].length + ' 字节）', 'log-ok');
        },
        read: function (path) {
          return this._fs[path] === undefined ? '' : this._fs[path];
        },
        dump: function () { return this._fs; }
      },

      /* ---- 串口（虚拟：与控制台互通） ---- */
      uart: {
        _buf: {},
        write: function (id, txt) {
          this._buf[id] = this._buf[id] || '';
          this._buf[id] += String(txt === undefined || txt === null ? '' : txt);
          log('[UART' + id + ' TX] ' + txt, 'log-sim');
        },
        read: function (id) {
          var s = this._buf[id] || '';
          this._buf[id] = '';
          return s || null;
        }
      },

      /* ---- 扩展板 parrot：电机 + 灯 ---- */
      parrot: {
        _speed: { MOTOR_1: 0, MOTOR_2: 0 },
        _led: { MOTOR_1: 0, MOTOR_2: 0 },
        setSpeed: function (m, v) {
          v = Math.max(-100, Math.min(100, Number(v) || 0));
          this._speed[m] = v;
          log('扩展板电机 ' + m + ' 速度 ' + v, 'log-sim');
        },
        getSpeed: function (m) { return this._speed[m] || 0; },
        led: function (m, br) {
          this._led[m] = Math.max(0, Math.min(100, Number(br) || 0));
          log('扩展板灯 ' + m + ' 亮度 ' + this._led[m], 'log-sim');
        },
        ledOff: function (m) { this._led[m] = 0; log('扩展板灯 ' + m + ' 关闭', 'log-sim'); }
      },

      /* ---- NeoPixel ---- */
      neopixel: {
        _rgb: [0, 0, 0],
        fill: function (rgb) {
          this._rgb = [clamp255(rgb[0]), clamp255(rgb[1]), clamp255(rgb[2])];
          log('NeoPixel 全部设为 (' + this._rgb.join(',') + ')', 'log-sim');
        }
      },

      /* ============================================================
       * DFRobot 新增硬件（未连接时给出提示，连接后才工作）
       * ============================================================ */
      ext: (function () {
        /* 用闭包持有根对象，避免 this 指向混乱。
           多实例（第十三轮）：第一个参数 inst 为设备序号（1~4），
           内部换算为实例键（base 或 base__N）后校验连接与读写状态。 */
        function ok(instKey) {
          if (ZKB.SimBoard && ZKB.SimBoard.isConnected && !ZKB.SimBoard.isConnected(instKey)) {
            var meta = (ZKB.deviceMeta && ZKB.deviceMeta(instKey)) || {};
            var nm = (ZKB.deviceName && ZKB.deviceName(instKey)) || meta.name || instKey;
            log('「' + nm + '」未连接，请先在「硬件连接」中把它连到扩展板接口', 'log-err');
            return false;
          }
          return true;
        }
        var api = {
          ok: ok,
          tracker: {
            read: function (inst, ch) {
              if (!ok(devKey('tracker', inst))) return 0;
              return devOf('tracker', inst).ch[ch] || 0;
            },
            /* 巡线偏离：中间压线则居中，否则偏向未检测到的一侧 */
            state: function (inst) {
              if (!ok(devKey('tracker', inst))) return 0;
              var c = devOf('tracker', inst).ch;
              if (c.C) return 0;
              if (c.L1 || c.L2) return -1;
              if (c.R1 || c.R2) return 1;
              return 0;
            }
          },
          power: {
            read: function (inst, k) {
              if (!ok(devKey('powerMeter', inst))) return 0;
              var p = devOf('powerMeter', inst);
              return k === 'v' ? p.v : (k === 'a' ? p.a : p.w);
            }
          },
          gravity: {
            read: function (inst, k) {
              if (!ok(devKey('gravity', inst))) return 0;
              var g = devOf('gravity', inst);
              return k === 'l' ? g.l : g[k];
            }
          },
          angle: {
            read: function (inst) {
              if (!ok(devKey('angle', inst))) return 0;
              return devOf('angle', inst).deg;
            }
          },
          ir: {
            send: function (inst, code) {
              if (!ok(devKey('irTx', inst))) return;
              devOf('irTx', inst).last = code;
              /* 红外发射后，接收端（若已连接）即可读到 */
              if (ZKB.SimBoard.isConnected && ZKB.SimBoard.isConnected('irRx')) {
                devOf('irRx', 1).code = String(code);
              }
              log('红外发射 ' + code, 'log-sim');
            },
            receive: function (inst) {
              if (!ok(devKey('irRx', inst))) return '';
              return devOf('irRx', inst).code;
            }
          },
          relay: {
            set: function (inst, on) {
              if (!ok(devKey('relay', inst))) return;
              devOf('relay', inst).on = !!on;
              log('继电器 ' + (on ? '打开（通路）' : '关闭（断路）'), 'log-sim');
            }
          },
          led: {
            /* 第三十五轮：M 口灯状态（拓展板电机口当灯用，
               见 mPythonSoftware-docs 的 expandBoard 文档）。
               ext 是独立闭包，拿不到 parrot 对象，这里自持一份状态。*/
            _mlamp: { M1: 0, M2: 0 },
            brightness: function (inst, v) {
              if (!ok(devKey('ledModule', inst))) return;
              devOf('ledModule', inst).bright = Math.max(0, Math.min(100, Number(v) || 0));
              log('LED 亮度 ' + devOf('ledModule', inst).bright + '%', 'log-sim');
            },
            /* PORT 为 'led'（LED 模块接 IO 口）或 'M1' / 'M2'（拓展板 M 口灯）*/
            _port: function (inst, port) {
              var p = port || 'led';
              if (p === 'M1' || p === 'M2') {
                return { bright: this._mlamp[p] || 0, motor: true };
              }
              if (!ok(devKey('ledModule', inst))) return null;
              return devOf('ledModule', inst);
            },
            on: function (inst, port) {
              var d = this._port(inst, port);
              if (!d) return;
              if (d.motor) {
                this._mlamp[port] = d.bright > 0 ? d.bright : 50;
                log('扩展板灯 ' + port + ' 打开（亮度 ' + this._mlamp[port] + '）', 'log-sim');
              } else {
                d.bright = d.bright > 0 ? d.bright : 50;
                d.on = true;
                log('LED 打开（亮度 ' + d.bright + '%）', 'log-sim');
              }
            },
            off: function (inst, port) {
              var d = this._port(inst, port);
              if (!d) return;
              if (d.motor) {
                this._mlamp[port] = 0;
                log('扩展板灯 ' + port + ' 关闭', 'log-sim');
              } else {
                d.bright = 0;
                d.on = false;
                log('LED 关闭', 'log-sim');
              }
            },
            setBright: function (inst, port, v) {
              var d = this._port(inst, port);
              if (!d) return;
              var b = Math.max(0, Math.min(100, Number(v) || 0));
              if (d.motor) {
                this._mlamp[port] = b;
                log('扩展板灯 ' + port + ' 亮度 ' + b, 'log-sim');
              } else {
                d.bright = b;
                d.on = b > 0;
                log('LED 亮度 ' + b + '%', 'log-sim');
              }
            },
            isOn: function (inst, port) {
              var d = this._port(inst, port);
              if (!d) return false;
              return d.motor ? ((this._mlamp[port] || 0) > 0) : (d.bright > 0);
            },
            getBright: function (inst, port) {
              var d = this._port(inst, port);
              if (!d) return 0;
              return d.motor ? (this._mlamp[port] || 0) : (d.bright || 0);
            }
          },
          strip: {
            N: 16,
            _inst: 1,
            _dev: function () { return devOf('rgbStrip', this._inst); },
            _init: function (inst) {
              this._inst = inst || 1;
              var dd = this._dev();
              if (!dd.leds) {
                dd.leds = [];
                for (var i = 0; i < 16; i++) {
                  dd.leds.push({ on: 0, r: 0, g: 0, b: 0 });
                }
              }
              return dd.leds;
            },
            /* 整条同色 */
            fill: function (inst, rgb) {
              if (!ok(devKey('rgbStrip', inst))) return;
              var s = devOf('rgbStrip', inst);
              s.r = clamp255(rgb[0]); s.g = clamp255(rgb[1]); s.b = clamp255(rgb[2]);
              var leds = this._init(inst);
              leds.forEach(function (l) { l.on = 1; l.r = s.r; l.g = s.g; l.b = s.b; });
              log('灯带 16 颗全部设为 (' + s.r + ',' + s.g + ',' + s.b + ')', 'log-sim');
            },
            /* 单颗 */
            set: function (inst, i, rgb) {
              if (!ok(devKey('rgbStrip', inst))) return;
              var leds = this._init(inst);
              var k = Math.max(1, Math.min(leds.length, Math.round(i) || 1)) - 1;
              var L = leds[k];
              L.on = 1; L.r = clamp255(rgb[0]); L.g = clamp255(rgb[1]); L.b = clamp255(rgb[2]);
              /* 同步整体色，便于不支持逐颗的场合 */
              var s = devOf('rgbStrip', inst);
              s.r = L.r; s.g = L.g; s.b = L.b;
              log('灯带第 ' + (k + 1) + ' 颗 → (' + L.r + ',' + L.g + ',' + L.b + ')', 'log-sim');
            },
            /* 熄灭：i 为 0 或不填 → 全部熄灭 */
            off: function (inst, i) {
              if (!ok(devKey('rgbStrip', inst))) return;
              var leds = this._init(inst);
              var n = Math.round(i) || 0;
              if (n <= 0) {
                leds.forEach(function (l) { l.on = 0; });
                var dd = devOf('rgbStrip', inst);
                dd.r = 0; dd.g = 0; dd.b = 0;
                log('灯带全部熄灭', 'log-sim');
              } else {
                var k = Math.max(1, Math.min(leds.length, n)) - 1;
                leds[k].on = 0;
                log('灯带第 ' + (k + 1) + ' 颗熄灭', 'log-sim');
              }
            },
            /* 跑马灯：从 start 起依次点亮 n 颗 */
            chase: function (inst, start, n, ms) {
              if (!ok(devKey('rgbStrip', inst))) return;
              var leds = this._init(inst);
              var s0 = Math.max(1, Math.min(leds.length, Math.round(start) || 1)) - 1;
              var cnt = Math.max(1, Math.min(leds.length - s0, Math.round(n) || 1));
              var delay = Math.max(20, Math.round(ms) || 120);
              log('灯带跑马灯：第 ' + (s0 + 1) + '~' + (s0 + cnt) + ' 颗，间隔 ' + delay + 'ms', 'log-sim');
              var step = 0;
              var timer = setInterval(function () {
                if (step >= cnt) { clearInterval(timer); return; }
                var k = s0 + step;
                var hue = (step / cnt) * 360;
                var c = hsv2rgb(hue, 1, 1);
                leds[k].on = 1; leds[k].r = c[0]; leds[k].g = c[1]; leds[k].b = c[2];
                step++;
              }, delay);
              /* 登记以便 stop() 时清理 */
              this._timers = this._timers || [];
              this._timers.push(timer);
            },
            /* 第三十六轮：灯带总颗数 / 读某颗的颜色分量 / 停止跑马灯 */
            count: function () { return this.N; },
            get: function (i, c) {
              var leds = this._init(this._inst);
              var k = Math.max(1, Math.min(leds.length, Math.round(i) || 1)) - 1;
              var L = leds[k];
              var idx = c === 'g' ? 1 : (c === 'b' ? 2 : 0);
              return L ? (L.on ? (L[['r', 'g', 'b'][idx]]) : 0) : 0;
            },
            rainbowStop: function (inst) {
              if (!ok(devKey('rgbStrip', inst))) return;
              /* 清掉所有跑马灯定时器 */
              this._timers = this._timers || [];
              while (this._timers.length) {
                clearInterval(this._timers.pop());
              }
              log('灯带跑马灯已停止', 'log-sim');
            }
          },
          /* 红外遥控器：方向键控制 */
          remote: {
            press: function (inst, dir) {
              if (!ok(devKey('remote', inst))) return;
              devOf('remote', inst).dir = dir;
              /* 方向键控制小车电机（最直观的联动） */
              var car = st.devices.car;
              if (car) {
                var spd = 55;
                if (dir === 'up') { car.l = spd; car.r = spd; }
                else if (dir === 'down') { car.l = -spd; car.r = -spd; }
                else if (dir === 'left') { car.l = -spd; car.r = spd; }
                else if (dir === 'right') { car.l = spd; car.r = -spd; }
              }
              var DIR_CN = { up: '上', down: '下', left: '左', right: '右', ok: '确定', back: '返回' };
              log('遥控器按下「' + (DIR_CN[dir] || dir) + '」', 'log-sim');
            },
            dir: function (inst) {
              if (!ok(devKey('remote', inst))) return '';
              return devOf('remote', inst).dir || '';
            }
          },
          buzzer: {
            set: function (on) {
              st.devices.buzzer.on = !!on;
              log('蜂鸣器 ' + (on ? '响' : '不响'), 'log-sim');
            }
          }
        };
        return api;
      })(),

      oled: oled,
      /* ---------- 第二十九轮：八年级新增硬件的仿真运行时 ----------
         磁场 / 卫星定位在真实硬件上是 I2C、UART 器件，仿真里没有，
         这里用「面板可调读数 + 合理默认值」模拟，并保证：
           · 不会抛异常（未添加设备时返回默认值）
           · 数值在合理区间内随机游走，看起来像真传感器 */
      sensor: {
        _v: {
          'magnetic.heading': 0, 'magnetic.raw': 500,
          'gps.lon': 116.397, 'gps.lat': 39.908, 'gps.lonEW': 'E',
          'gps.latNS': 'N', 'gps.alt': 43, 'gps.num': 0,
          'gps.utc': '2026-01-01 00:00:00', 'gps.speed': 0, 'gps.ready': 0
        },
        get: function (key) {
          if (!(key in this._v)) return '';
          var v = this._v[key];
          return v == null ? '' : v;
        },
        set: function (key, v) { this._v[key] = v; },
        /* 校准：模拟转动板子，让方位角缓慢归零 */
        calibrate: function (which) {
          if (which !== 'magnetic') return;
          this._v['magnetic.heading'] = 0;
          log('磁场传感器校准完成，请转动板子 8 字', 'log-sim');
        },
        /* 去皮：记录当前值为基准，之后读数是相对偏移 */
        peel: function (which) {
          if (which !== 'magnetic') return;
          this._peel = this._v['magnetic.heading'];
        },
        gpsInit: function () {
          this._v['gps.ready'] = 0;
          this._v['gps.num'] = 0;
          /* 数据来源标记：'模拟' / '真实'，供 zk_gps_data 的「src」选项读*/
          this._v['gps.src'] = '模拟';
          log('卫星定位模块已启动，正在搜星…', 'log-sim');
        },
        /* 第三十三轮：接入电脑真实定位。
           navigator.geolocation 是浏览器标准 API，拿到的是电脑/手机的实际位置。
           注意：必须走 HTTPS 或 localhost，file:// 下会被浏览器拒绝。
           成功后写入 gps.real.*，gpsParse 优先使用真实数据；拿不到就回落到模拟值。 */
        gpsUseReal: function () {
          var self = this;
          if (!global.navigator || !navigator.geolocation) {
            log('当前浏览器不支持定位（navigator.geolocation 不可用），继续用模拟数据', 'log-warn');
            return Promise.resolve(false);
          }
          return new Promise(function (resolve) {
            navigator.geolocation.getCurrentPosition(function (pos) {
              var c = pos.coords || {};
              self._v['gps.real.lon'] = Number(c.longitude);
              self._v['gps.real.lat'] = Number(c.latitude);
              self._v['gps.real.alt'] = c.altitude == null ? null : Number(c.altitude);
              /* 浏览器给不出「卫星颗数」，用精度半径换算一个可信的估值：
                 accuracy 越小越准，对应可见卫星越多（经验映射 5~20 颗）。 */
              var acc = Number(c.accuracy) || 50;
              self._v['gps.real.num'] = Math.max(4,
                Math.min(20, Math.round(20 - acc / 10)));
              self._v['gps.real.acc'] = Math.round(acc);
              self._v['gps.real.ok'] = 1;
              self._v['gps.real.at'] = new Date().toISOString();
              self._v['gps.src'] = '真实';
              log('已获取电脑真实定位：经度 ' + c.longitude.toFixed(6) +
                '　纬度 ' + c.latitude.toFixed(6) +
                (c.altitude != null ? ('　海拔 ' + Math.round(c.altitude) + ' m') : '') +
                '　精度 ±' + Math.round(acc) + ' m', 'log-ok');
              if (typeof syncGpsView === 'function') syncGpsView();
              resolve(true);
            }, function (err) {
              /* 常见原因：用户拒绝授权 / 非安全上下文 / 设备无定位硬件 */
              var why = err && err.code === 1 ? '用户拒绝了定位授权'
                : (err && err.code === 3 ? '定位超时'
                  : '定位不可用（' + ((err && err.message) || '未知原因') + '）');
              self._v['gps.real.ok'] = 0;
              log('获取电脑定位失败：' + why +
                '。请用 http://localhost 打开页面并允许定位权限；已回落到模拟数据。', 'log-warn');
              resolve(false);
            }, {
              /* 高精度、10 秒超时、允许缓存 30 秒 */
              enableHighAccuracy: true, timeout: 10000, maximumAge: 30000
            });
          });
        },
        gpsIsReal: function () { return this._v['gps.real.ok'] >= 1 ? 1 : 0; },
        gpsClearReal: function () {
          this._v['gps.real.ok'] = 0;
          this._v['gps.src'] = '模拟';
          if (typeof syncGpsView === 'function') syncGpsView();
        },
        /* 解析一帧：有真实数据就用真实的，否则用模拟值 */
        gpsParse: function () {
          var real = this._v['gps.real.ok'] >= 1;
          if (!real && this._v['gps.ready'] < 1) {
            /* 仿真里点面板上的「搜星」按钮才会置位 */
            this._v['gps.num'] = 0;
            this._v['gps.utc'] = '';
            return;
          }
          if (real) {
            this._v['gps.lon'] = Number(this._v['gps.real.lon']).toFixed(6);
            this._v['gps.lat'] = Number(this._v['gps.real.lat']).toFixed(6);
            this._v['gps.alt'] = this._v['gps.real.alt'] == null
              ? '—' : Math.round(Number(this._v['gps.real.alt']));
            this._v['gps.num'] = this._v['gps.real.num'];
            /* 经纬度方向：东经/北纬为正 */
            this._v['gps.lonEW'] = this._v['gps.real.lon'] >= 0 ? 'E' : 'W';
            this._v['gps.latNS'] = this._v['gps.real.lat'] >= 0 ? 'N' : 'S';
            this._v['gps.utc'] = new Date().toISOString().slice(0, 19).replace('T', ' ');
          } else {
            var n = this._v['gps.num'] || 8;
            this._v['gps.utc'] = '2026-01-01 12:0' + (Math.floor(Math.random() * 6)) + ':00';
            this._v['gps.lon'] = (116.397 + (Math.random() - 0.5) * 0.002).toFixed(6);
            this._v['gps.lat'] = (39.908 + (Math.random() - 0.5) * 0.002).toFixed(6);
            this._v['gps.alt'] = 40 + Math.floor(Math.random() * 8);
            this._v['gps.num'] = n;
          }
          /* 解析完回填面板视图，让 GPS 卡片的经纬度跟着变 */
          if (typeof syncGpsView === 'function') syncGpsView();
        }
      },
      /* RFID 刷卡：仿真里由虚拟面板上的「刷卡」按钮触发 */
      rfid: {
        last: '',
        scan: function () {
          /* 没刷卡时返回空串，刷卡后返回卡号并保持 */
          return this.last;
        }
      },
      /* 离线语音识别：由虚拟面板上的指令按钮触发 */
      asr2: {
        result: '',
        armed: false,
        arm: function () { this.armed = true; },
        trigger: function (text) {
          this.result = text || '';
          log('离线语音识别：' + this.result, 'log-sim');
        }
      },
      rgb: {
        set: function (n, rgb) {
          var c = [clamp255(rgb[0]), clamp255(rgb[1]), clamp255(rgb[2])];
          if (n === 'ALL') for (var i = 0; i < 3; i++) st.rgb.dots[i] = c.slice();
          else st.rgb.dots[parseInt(n, 10)] = c;
          ZKB.SimBoard.refreshRGB();
        },
        clear: function () {
          for (var i = 0; i < 3; i++) st.rgb.dots[i] = [0, 0, 0];
          ZKB.SimBoard.refreshRGB();
        },
        /* 第四十五轮：刷新彩灯（官方 rgb.write()）。
           仿真里 set/fill 已经直接生效，这里做成空操作占位，
           保证官方示例反解出来的程序也能直接跑。 */
        write: function () { ZKB.SimBoard.refreshRGB(); },
        brightness: function (v) { st.rgb.brightness = Math.max(0, Math.min(1, v / 100)); ZKB.SimBoard.refreshRGB(); },
        /* 第三十六轮：读某颗灯珠的颜色分量 / 填充全部 / 读亮度 */
        get: function (n, c) {
          var i = (n === 'ALL') ? 0 : parseInt(n, 10);
          var d = (st.rgb.dots && st.rgb.dots[i]) || [0, 0, 0];
          var k = c === 'g' ? 1 : (c === 'b' ? 2 : 0);
          return d[k] || 0;
        },
        fill: function (rgb) {
          var c = [clamp255(rgb[0]), clamp255(rgb[1]), clamp255(rgb[2])];
          for (var i = 0; i < 3; i++) st.rgb.dots[i] = c.slice();
          ZKB.SimBoard.refreshRGB();
        },
        getBrightness: function () { return Math.round((st.rgb.brightness || 0) * 100); }
      },

      btn: function (k) { return !!st.btn[k]; },
      touch: function (k) { return !!st.touch[k]; },
      light: function () { return Math.round(st.light); },
      sound: function () {
        return Math.max(0, Math.round(st.sound + (Math.random() - 0.5) * 60 + st.soundBurst * 3400));
      },
      accel: function (axis) {
        var n = st.accel[axis] + (Math.random() - 0.5) * 0.03;
        return Math.round(n * 100) / 100;
      },
      tilt: function (k) {
        var a = st.accel;
        var roll = Math.asin(Math.max(-1, Math.min(1, -a.y))) * 180 / Math.PI;
        var pitch = Math.atan2(a.x, a.z) * 180 / Math.PI;
        return Math.round(k === 'p' ? pitch : roll);
      },

      note: function (name, beats) {
        audio.tone(NOTE_FREQ[name] || 440);
        return this.sleep(beats * 0.5 * 1000);
      },
      tone: function (freq, sec) {
        audio.tone(freq);
        return this.sleep(sec * 1000);
      },
      stopMusic: function () { audio.stop(); },

      pinOut: function (p, v) { st.pins['pin_' + p] = v; },
      pwm: function (p, v) { st.pins['pin_' + p] = v; },
      pinDin: function () { return 1; },
      pinAin: function () { return Math.round(500 + Math.random() * 60); },

      dhtMeasure: function (inst) { devOf('dht', inst); },
      dht: function (inst, k) { var dd = devOf('dht', inst); return k === 't' ? dd.t : dd.h; },
      distance: function (inst) { return devOf('ultrasonic', inst).cm; },
      servo: function (inst, a) { servoUI(a, devKey('servo', inst)); },
      ir: function (inst) { return devOf('ir', inst).obs; },

      /* ============================================================
       * 第三十六轮：拓展设备积木补全的运行时方法
       * ============================================================ */

      /* ---- 按钮 ---- */
      extBtnCount: function (inst) { return devOf('button', inst).count || 0; },
      extBtnReset: function (inst) { devOf('button', inst).count = 0; },

      /* ---- 光线传感器 ---- */
      lightRaw: function (inst) {
        return Math.max(0, Math.min(4095,
          Math.round(devOf('lightExt', inst).v + (Math.random() - 0.5) * 20)));
      },
      lightPct: function (inst) {
        return Math.round(Math.max(0, Math.min(4095,
          devOf('lightExt', inst).v + (Math.random() - 0.5) * 20)) / 4095 * 100);
      },
      lightBright: function (inst) {
        return Math.max(0, Math.min(4095,
          devOf('lightExt', inst).v + (Math.random() - 0.5) * 20)) > 2048;
      },

      /* ---- 直流电机 / 马达（M1 / M2） ---- */
      motorStop: function () {
        st.devices.motor = st.devices.motor || { vel: 0 };
        st.devices.motor.vel = 0;
        if (st.devices.motor2) st.devices.motor2.vel = 0;
        motorUI(devKey('motor', 1));
      },
      motorGetSpeed: function (m) {
        var dd = (m === 'MOTOR_2') ? (st.devices.motor2 || (st.devices.motor2 = { vel: 0 }))
          : (st.devices.motor || (st.devices.motor = { vel: 0 }));
        return dd.vel || 0;
      },
      /* ---- 十六、补充官方 API 能力（虚拟仿真近似值） ---- */
      ds18Temp: function () {
        /* 与 DHT 的温度保持一致，便于对比两种温度传感器 */
        var dd = devOf('dht', 1);
        return Math.round((dd.t + (Math.random() - 0.5) * 0.3) * 10) / 10;
      },
      ds18Ok: function () { return true; },
      adcRead: function (pin) {
        /* 按引脚给一个稳定的模拟量，便于课堂上演示 */
        var base = { 1: 1800, 2: 900, 3: 120, 4: 2400, 10: 2000, 13: 3000, 14: 1500 }[pin];
        if (base == null) base = 1000;
        return Math.max(0, Math.min(4095, Math.round(base + (Math.random() - 0.5) * 30)));
      },
      motorSet: function (m, spd) {
        spd = Math.max(-100, Math.min(100, Number(spd) || 0));
        var dd = (m === 'MOTOR_2') ? (st.devices.motor2 || (st.devices.motor2 = { vel: 0 }))
          : (st.devices.motor || (st.devices.motor = { vel: 0 }));
        dd.vel = spd;
        motorUI(devKey('motor', m === 'MOTOR_2' ? 2 : 1));
      },

      /* ---- 气压传感器 ---- */
      pressurePa: function (inst) {
        return Math.round(devOf('baro', inst).p * 100 + (Math.random() - 0.5) * 200);
      },
      temp: function (inst) {
        var dd = devOf('baro', inst);
        if (dd.t == null) dd.t = 26;
        return Math.round(dd.t + (Math.random() - 0.5) * 0.4);
      },

      /* ---- 舵机 ---- */
      servoGet: function (inst) { return devOf('servo', inst).angle || 90; },
      servoOff: function (inst) { devOf('servo', inst).angle = devOf('servo', inst).angle || 90; },

      /* ---- 超声波 ---- */
      distanceMm: function (inst) { return devOf('ultrasonic', inst).cm * 10; },

      /* ---- 人体红外 ---- */
      pir: function (inst) { return !!devOf('pir', inst).on; },
      pirCount: function (inst) { return devOf('pir', inst).count || 0; },
      pirReset: function (inst) { devOf('pir', inst).count = 0; },

      /* ---- 温湿度 ---- */
      dhtDew: function (inst) {
        var dd = devOf('dht', inst);
        /* Magnus 公式的简化版：露点 ≈ t - (100 - h) / 5 */
        return Math.round((dd.t - (100 - dd.h) / 5) * 10) / 10;
      },
      dhtOk: function (inst) {
        var dd = devOf('dht', inst);
        return dd.t >= -40 && dd.t <= 80 && dd.h >= 0 && dd.h <= 100;
      },

      /* ---- 土壤湿度 ---- */
      soilWet: function (inst) {
        return devOf('soil', inst).v / 4095 > 0.5;
      },

      /* ---- 水泵 ---- */
      pumpPowerGet: function (inst) { return devOf('pump', inst).power || 0; },
      pumpFlow: function (inst) { return !!devOf('pump', inst).on; },

      /* ---- MP3 模块 ---- */
      mp3: {
        play: function (name) {
          var dd = st.devices.mp3 || (st.devices.mp3 = { playing: false, name: '', volume: 15 });
          dd.playing = true;
          dd.name = name || '';
          log('MP3 播放：' + (name || '（未指定）'), 'log-sim');
        },
        stop: function () {
          var dd = st.devices.mp3 || (st.devices.mp3 = { playing: false, name: '', volume: 15 });
          dd.playing = false;
          log('MP3 停止播放', 'log-sim');
        },
        volume: function (v) {
          var dd = st.devices.mp3 || (st.devices.mp3 = { playing: false, name: '', volume: 15 });
          dd.volume = Math.max(0, Math.min(30, Number(v) || 0));
          log('MP3 音量 ' + dd.volume, 'log-sim');
        },
        playing: function () {
          var dd = st.devices.mp3 || (st.devices.mp3 = { playing: false, name: '', volume: 15 });
          return !!dd.playing;
        },
        playFolder: function (f, n) {
          var dd = st.devices.mp3 || (st.devices.mp3 = { playing: false, name: '', volume: 15 });
          dd.playing = true;
          dd.name = '文件夹' + f + ' 第' + n + '首';
          log('MP3 播放 ' + dd.name, 'log-sim');
        }
      },

      heater: function (inst, v) { var dd = devOf('heater', inst); dd.on = !!v; dd.power = v ? 100 : 0; heaterUI(devKey('heater', inst)); },
      heaterPower: function (inst, p) { var dd = devOf('heater', inst); p = Math.max(0, Math.min(100, p)); dd.power = p; dd.on = p > 0; heaterUI(devKey('heater', inst)); },
      pump: function (inst, v) { var dd = devOf('pump', inst); dd.on = !!v; dd.power = v ? 100 : 0; pumpUI(devKey('pump', inst)); },
      pumpPower: function (inst, p) { var dd = devOf('pump', inst); p = Math.max(0, Math.min(100, p)); dd.power = p; dd.on = p > 0; pumpUI(devKey('pump', inst)); },
      motor: function (inst, dir, speed) {
        speed = Math.max(0, Math.min(100, speed));
        devOf('motor', inst).vel = dir === 'f' ? speed : dir === 'b' ? -speed : 0;
        motorUI(devKey('motor', inst));
      },
      car: function (inst, dir, speed) {
        speed = Math.max(0, Math.min(100, speed));
        var m = { f: [speed, speed], b: [-speed, -speed], l: [-speed, speed], r: [speed, -speed], s: [0, 0] };
        var dd = devOf('car', inst);
        dd.l = m[dir][0]; dd.r = m[dir][1];
        carUI(devKey('car', inst));
      },
      wheels: function (inst, l, r) {
        var dd = devOf('car', inst);
        dd.l = Math.max(-100, Math.min(100, l));
        dd.r = Math.max(-100, Math.min(100, r));
        carUI(devKey('car', inst));
      },
      /* 小车自带超声波：车头前方最近障碍物距离（cm），由舞台/仿真面板实时写入 */
      carDist: function (inst) {
        var dd = devOf('car', inst);
        return dd._dist === undefined || dd._dist === null ? 200 : dd._dist;
      },
      colorChannel: function (inst, i) {
        var c = devOf('color', inst);
        return [c.r, c.g, c.b, c.c][i];
      },
      colorSeen: function (inst, name) { return devOf('color', inst).name === name; },
      cameraResult: function (inst) { return devOf('camera', inst).label; },
      cameraSeen: function (inst, obj) { return devOf('camera', inst).target === obj; },

      /* —— AI 视觉（第二十三轮，逻辑见 vision.js）——
         inst 由gen-sim 的 inst(b) 传入，可为空（表示默认实例）。*/
      visionOcrStart: function (inst, mode) {
        return ZKB.Vision.ocrStart(inst, mode);
      },
      visionOcrText: function (inst) { return ZKB.Vision.ocrText(inst); },
      visionOcrNumber: function (inst) { return ZKB.Vision.ocrNumber(inst); },
      visionFaceRegister: function (inst, name, gender, bio) {
        /* 图片在卡片里录入（人脸库按姓名保存），这里只登记文字信息 */
        var rec = ZKB.Vision.findFace(String(name || '').trim());
        var r = ZKB.Vision.registerFace(name, gender || (rec && rec.gender) || 'male',
          bio || (rec && rec.bio) || '');
        return r.ok ? r.face.name : '';
      },
      visionFaceVerify: function (inst, name) {
        /* 第三十五轮：真实人脸比对要等讯飞返回，故返回 Promise，
           生成代码里用 await 等它（离线模拟时立即 resolve）。 */
        var r = ZKB.Vision.verify(inst, name);
        if (r && typeof r.then === 'function') {
          return r.then(function (x) { return (x && x.name) || ''; });
        }
        return (r && r.name) || '';
      },
      visionFaceName: function (inst) { return ZKB.Vision.name(inst); },
      visionFaceGender: function (inst) { return ZKB.Vision.gender(inst); },
      visionFaceBio: function (inst) { return ZKB.Vision.bio(inst); },
      visionFaceEmotion: function (inst, em) { return ZKB.Vision.emotionIs(inst, em); },
      visionFaceEmotionText: function (inst) { return ZKB.Vision.emotionText(inst); },
      visionObjStart: function (inst, cat) { return ZKB.Vision.objStart(inst, cat); },
      visionObjResult: function (inst, cat) { return ZKB.Vision.objResult(inst, cat); },
      visionConfidence: function (inst) { return ZKB.Vision.confidence(inst); },
      /* —— 第三十五轮：场景识别 / 手写文字 / 拍照速算 / 人脸属性 —— */
      visionSceneStart: function (inst) { return ZKB.Vision.sceneStart(inst); },
      visionSceneResult: function (inst) { return ZKB.Vision.sceneResult(inst); },
      visionHandwriteStart: function (inst) { return ZKB.Vision.handwriteStart(inst); },
      visionHandwriteText: function (inst) { return ZKB.Vision.handwriteText(inst); },
      visionCalcStart: function (inst) { return ZKB.Vision.calcStart(inst); },
      visionCalcText: function (inst) { return ZKB.Vision.calcText(inst); },
      visionCalcAnswer: function (inst) { return ZKB.Vision.calcAnswer(inst); },
      visionCalcCorrect: function (inst) { return ZKB.Vision.calcCorrect(inst); },
      visionFaceCount: function (inst) { return ZKB.Vision.faceCount(inst); },
      visionFaceAttr: function (inst, attr) { return ZKB.Vision.faceAttr(inst, attr); },
      /* —— 第三十五轮：K210 板上预置模型（虚拟仿真离线模拟）——
         真机上这些积木走串口指令（gen-python.js 的 _kpu_*），
         仿真里用样本模拟，结果结构保持一致：
           faces: [[classid, x, y, w, h, value], ...]
           objs:  [[classid, value], ...] */
      kpuLoad: function (model) {
        var st = kpuState();
        st.model = model;
        st.faces = [];
        st.objs = [];
        st.digit = -1;
        return model;
      },
      kpuDetect: function (model) {
        var st = kpuState();
        st.model = model || st.model || 'face';
        st.faces = [];
        st.objs = [];
        st.digit = -1;
        /* 人脸追踪：随机 0~2 张脸 */
        if (st.model === 'face') {
          var n = Math.random() < 0.55 ? 0 : (Math.random() < 0.7 ? 1 : 2);
          for (var i = 0; i < n; i++) {
            st.faces.push([
              0,
              Math.round(Math.random() * 240),
              Math.round(Math.random() * 160),
              40 + Math.round(Math.random() * 60),
              40 + Math.round(Math.random() * 60),
              Math.round((0.6 + Math.random() * 0.38) * 1000) / 1000
            ]);
          }
        } else if (st.model === 'digit') {
          st.digit = Math.floor(Math.random() * 10);
        } else {
          /* 20 类：随机 1~3 个目标 */
          var m = 1 + Math.floor(Math.random() * 3);
          for (var j = 0; j < m; j++) {
            st.objs.push([
              Math.floor(Math.random() * 20),
              Math.round((0.55 + Math.random() * 0.43) * 1000) / 1000
            ]);
          }
        }
        log('K210 模型「' + st.model + '」识别 → ' +
          (st.faces.length ? st.faces.length + ' 张人脸'
            : (st.objs.length ? st.objs.length + ' 个目标'
              : (st.digit >= 0 ? '数字 ' + st.digit : '未检出目标'))), 'log-sim');
        return st.faces.length || st.objs.length || (st.digit >= 0 ? 1 : 0);
      },
      kpuFaceNum: function () { return kpuState().faces.length; },
      kpuFaceField: function (n, i) {
        var f = kpuState().faces;
        if (n < 1 || n > f.length) return 0;
        return f[n - 1][i] || 0;
      },
      kpuObjCount: function () { return kpuState().objs.length; },
      kpuObjLabel: function (idx) {
        var o = kpuState().objs;
        var names = ['人', '自行车', '汽车', '摩托车', '飞机', '公交车', '火车', '卡车', '船',
          '红灯', '黄灯', '绿灯', '蓝灯', '斑马线', '猫', '狗', '鸟', '马', '蝴蝶', '向日葵'];
        if (idx < 0 || idx >= o.length) return '';
        var cid = o[idx][0];
        return names[cid] || '';
      },
      kpuObjValue: function (n) {
        var o = kpuState().objs;
        if (n < 1 || n > o.length) return 0;
        return o[n - 1][1] || 0;
      },
      kpuDigit: function () { return kpuState().digit; },
      mic: function (inst) {
        var m = devOf('mic', inst);
        return Math.round(m.v * 0.6 + Math.random() * 60 + m.burst * 3300);
      },
      ambient: function (inst) { return Math.round(devOf('lightExt', inst).v + (Math.random() - 0.5) * 20); },

      /* —— 新增设备 —— */
      soil: function (inst) { return Math.round(devOf('soil', inst).v + (Math.random() - 0.5) * 20); },
      soilPct: function (inst) { return Math.round(devOf('soil', inst).v / 4095 * 100); },
      pm25: function (inst) { return Math.round(devOf('pm25', inst).v + (Math.random() - 0.5) * 3); },
      pm25Level: function (inst) {
        var v = devOf('pm25', inst).v;
        if (v <= 35) return '优';
        if (v <= 75) return '良';
        if (v <= 115) return '轻度污染';
        if (v <= 150) return '中度污染';
        return '重度污染';
      },
      pressure: function (inst) { return Math.round(devOf('baro', inst).p + (Math.random() - 0.5) * 2); },
      altitude: function (inst) { return Math.round(44330 * (1 - Math.pow(devOf('baro', inst).p / 1013.25, 0.1903)) * 10) / 10; },
      extBtn: function (inst) { return !!devOf('button', inst).on; },
      fan: function (inst, v) { var dd = devOf('fan', inst); dd.on = !!v; dd.power = v ? 100 : 0; fanUI(devKey('fan', inst)); },
      fanPower: function (inst, p) { var dd = devOf('fan', inst); p = Math.max(0, Math.min(100, p)); dd.power = p; dd.on = p > 0; fanUI(devKey('fan', inst)); },

      /* ============================================================
       * 舞台元素控制（第十三轮）：移动到 / 层级 / 大小
       * 仅作用于舞台模式的非背景元素，真实硬件无对应功能（Python 导出为注释）
       * ============================================================ */
      stage: {
        moveTo: function (uid, x, y) {
          uid = resolveEl(uid);
          if (!uid) { log('请先在舞台上添加元素（或在积木里填写元素名称）', 'log-err'); return; }
          if (ZKB.Stage && ZKB.Stage.moveItem) {
            var it = ZKB.Stage.moveItem(uid, x, y);
            if (it) log('元素「' + (ZKB.Stage.nameOf(uid) || uid) + '」移动到 (' +
              Math.round(x) + ', ' + Math.round(y) + ')', 'log-sim');
            else log('元素不存在或已被移除', 'log-err');
          }
        },
        layer: function (uid, op) {
          uid = resolveEl(uid);
          if (!uid) { log('请先在舞台上添加元素（或在积木里填写元素名称）', 'log-err'); return; }
          if (ZKB.Stage && ZKB.Stage.setLayer) {
            var CN = { up: '上移一层', down: '下移一层', front: '置于顶层', back: '置于底层' };
            if (ZKB.Stage.setLayer(uid, op)) {
              log('元素「' + (ZKB.Stage.nameOf(uid) || uid) + '」' + (CN[op] || op), 'log-sim');
            } else log('元素不存在或已被移除', 'log-err');
          }
        },
        /* 第三十轮：运动 / 外观模块的运行时薄封装
           真正的计算都在 js/stage.js（与舞台交互共用一套逻辑），
           这里只做「元素名 → uid」解析与日志，失败时给明确提示。 */
        _el: function (v) {
          var uid = resolveEl(v);
          if (!uid) log('找不到元素「' + v + '」，请先在舞台上添加该元素，或用积木下拉重新选择', 'log-err');
          return uid;
        },
        moveSteps: function (e, n) {
          var uid = this._el(e); if (!uid) return;
          ZKB.Stage.moveSteps(uid, Number(n) || 0);
          log('元素移动 ' + Math.round(Number(n) || 0) + ' 步 → (' +
            ZKB.Stage.getXY(uid, 'x') + ', ' + ZKB.Stage.getXY(uid, 'y') + ')', 'log-sim');
        },
        gotoXY: function (e, x, y) {
          var uid = this._el(e); if (!uid) return;
          ZKB.Stage.gotoXY(uid, Number(x) || 0, Number(y) || 0);
          log('元素移到 (' + Math.round(Number(x) || 0) + ', ' + Math.round(Number(y) || 0) + ')', 'log-sim');
        },
        changeXY: function (e, axis, d) {
          var uid = this._el(e); if (!uid) return;
          ZKB.Stage.changeXY(uid, axis, Number(d) || 0);
          log('元素 ' + axis + ' 增加 ' + Math.round(Number(d) || 0), 'log-sim');
        },
        setXYAbs: function (e, axis, v) {
          var uid = this._el(e); if (!uid) return;
          ZKB.Stage.setXYAbs(uid, axis, Number(v) || 0);
          log('元素 ' + axis + ' 设为 ' + Math.round(Number(v) || 0), 'log-sim');
        },
        getXY: function (e, axis) {
          var uid = resolveEl(e);
          return uid ? ZKB.Stage.getXY(uid, axis) : 0;
        },
        getDir: function (e) {
          var uid = resolveEl(e);
          return uid ? ZKB.Stage.getDir(uid) : 90;
        },
        turnBy: function (e, d) {
          var uid = this._el(e); if (!uid) return;
          ZKB.Stage.turnBy(uid, Number(d) || 0);
          log('元素转向 ' + ZKB.Stage.getDir(uid) + '°', 'log-sim');
        },
        setRot: function (e, d) {
          var uid = this._el(e); if (!uid) return;
          ZKB.Stage.setItemRot(uid, Number(d) || 0);
          log('元素面向 ' + ZKB.Stage.getDir(uid) + '°', 'log-sim');
        },
        pointTowards: function (e, to) {
          var uid = this._el(e); if (!uid) return;
          var t = resolveEl(to);
          if (!t) { log('找不到要面向的元素「' + to + '」', 'log-err'); return; }
          if (ZKB.Stage.pointTowards(uid, t)) {
            log('元素面向「' + (ZKB.Stage.nameOf(t) || to) + '」：' + ZKB.Stage.getDir(uid) + '°', 'log-sim');
          }
        },
        ifOnEdgeBounce: function (e) {
          var uid = this._el(e); if (!uid) return;
          if (ZKB.Stage.ifOnEdgeBounce(uid)) {
            log('碰到边缘，方向反弹为 ' + ZKB.Stage.getDir(uid) + '°', 'log-sim');
          }
        },
        gotoRandom: function (e) {
          var uid = this._el(e); if (!uid) return;
          var sz = ZKB.Stage.getSize();
          var x = Math.round((Math.random() - 0.5) * (sz.w - 80));
          var y = Math.round((Math.random() - 0.5) * (sz.h - 80));
          ZKB.Stage.gotoXY(uid, x, y);
          log('元素移到随机位置 (' + x + ', ' + y + ')', 'log-sim');
        },
        /* 滑行：返回一个 Promise，保证 await 能等到终点 */
        glide: function (e, x, y, ms) {
          var uid = this._el(e); if (!uid) return Promise.resolve(false);
          return new Promise(function (res) {
            ZKB.Stage.glideXY(uid, Number(x) || 0, Number(y) || 0,
              Number(ms) || 300, function () {
                log('元素滑行到 (' + Math.round(Number(x) || 0) + ', ' + Math.round(Number(y) || 0) + ')', 'log-sim');
                res(true);
              });
          });
        },
        /* ---------- 外观 ---------- */
        setVisible: function (e, on) {
          var uid = this._el(e); if (!uid) return;
          ZKB.Stage.setVisible(uid, on);
          log('元素' + (on ? '显示' : '隐藏'), 'log-sim');
        },
        isVisible: function (e) {
          var uid = resolveEl(e);
          return uid ? ZKB.Stage.isVisible(uid) : false;
        },
        getSize: function (e) {
          var uid = resolveEl(e);
          return uid ? ZKB.Stage.getItemSize(uid) : 100;
        },
        setScale: function (e, pct) {
          var uid = this._el(e); if (!uid) return;
          ZKB.Stage.setItemScale(uid, Number(pct) || 100);
          log('元素大小设为 ' + ZKB.Stage.getItemSize(uid) + '%', 'log-sim');
        },
        changeScale: function (e, d) {
          var uid = this._el(e); if (!uid) return;
          ZKB.Stage.setItemScale(uid, ZKB.Stage.getItemSize(uid) + (Number(d) || 0));
          log('元素大小变为 ' + ZKB.Stage.getItemSize(uid) + '%', 'log-sim');
        },
        setOpacity: function (e, pct) {
          var uid = this._el(e); if (!uid) return;
          ZKB.Stage.setOpacity(uid, Number(pct) || 0);
          log('元素不透明度 ' + Math.round(Number(pct) || 0) + '%', 'log-sim');
        },
        setGhost: function (e, pct) {
          var uid = this._el(e); if (!uid) return;
          ZKB.Stage.setGhost(uid, Number(pct) || 0);
          log('元素虚像 ' + Math.round(Number(pct) || 0) + '%', 'log-sim');
        },
        colorFx: function (e, kind, val) {
          var uid = this._el(e); if (!uid) return;
          ZKB.Stage.setColorEffect(uid, kind, Number(val) || 0);
          var CN = { hue: '色相', sat: '饱和度', bright: '亮度' };
          log('元素' + (CN[kind] || kind) + '特效 ' + Math.round(Number(val) || 0), 'log-sim');
        },
        clearEffects: function (e) {
          var uid = this._el(e); if (!uid) return;
          ZKB.Stage.clearEffects(uid);
          log('已清除元素的所有图形特效', 'log-sim');
        },

        /* 小车前方 N cm 内有指定元素吗（第二十一轮：示例④行人让行 / 超车） */
        frontHas: function (cm, kind) {
          var car = ZKB.Stage.getItems().filter(function (i) { return i.k === 'car'; })[0];
          if (!car) { log('舞台没有小车，请先添加「模拟小车」元素', 'log-err'); return false; }
          var kinds = (ZKB.KIND_TO_KINDS && ZKB.KIND_TO_KINDS[kind] !== undefined)
            ? ZKB.KIND_TO_KINDS[kind] : null;
          var hit = ZKB.Stage.frontScan(car, kinds, Number(cm) || 30);
          var cname = hit ? hit.name : '';
          log('超声波：' + (hit ? ('前方 ' + hit.dist + 'cm 处有' + cname): (kind === 'pedestrian' ? '附近没有行人' :
            kind === 'vehicle' ? '附近没有车辆' : '前方通畅')) + '（阈值 ' + (Number(cm) || 30) + 'cm）', 'log-sim');
          return !!hit;
        },
        /* 让元素从上往下走到 y（行人过斑马线）：等待走到后返回 */
        walkTo: function (el, ty) {
          var uid = resolveEl(el);
          if (!uid) { log('请先在舞台上添加行人等元素', 'log-err'); return Promise.resolve(false); }
          var target = Number(ty);
          if (isNaN(target)) target = 430;
          if (!ZKB.Stage.walkTo(uid, target, 110)) {
            log('该元素不能行走（仅行人 / 车辆等可移动元素）', 'log-err');
            return Promise.resolve(false);
          }
          var name = (ZKB.Stage.nameOf(uid) || '元素');
          log('让' + name + '从上方向下走到 y=' + Math.round(target) + '（过斑马线）', 'log-sim');
          var st2 = this;
          return this.sleep(60).then(function waitLoop() {
            var ws = ZKB.Stage.walkState(uid);
            if (!ws || ws.done) {
              log(name + ' 已通过，车子可以继续行驶', 'log-sim');
              return true;
            }
            return st2.sleep(60).then(waitLoop);
          });
        },
        /* 元素是否已走到终点 */
        walkDone: function (el) {
          var uid = resolveEl(el);
          if (!uid) return true;
          var ws = ZKB.Stage.walkState(uid);
          return !ws || !!ws.done;
        },
        /* 方向：上=0° 右=90° 下=180° 左=270°（默认右侧） */
        rotate: function (uid, deg) {
          uid = resolveEl(uid);
          if (!uid) { log('请先在舞台上添加元素（或在积木里填写元素名称）', 'log-err'); return; }
          var d = Number(deg);
          if (isNaN(d)) d = 90;
          d = ((Math.round(d) % 360) + 360) % 360;
          if (ZKB.Stage.setItemRot) {
            if (ZKB.Stage.setItemRot(uid, d)) {
              log('元素「' + (ZKB.Stage.nameOf(uid) || uid) + '」方向 = ' + d + '°', 'log-sim');
            } else log('元素不存在或已被移除', 'log-err');
          }
        },
        scale: function (uid, pct) {
          uid = resolveEl(uid);
          if (!uid) { log('请先在舞台上添加元素（或在积木里填写元素名称）', 'log-err'); return; }
          if (ZKB.Stage && ZKB.Stage.setItemScale) {
            if (ZKB.Stage.setItemScale(uid, pct)) {
              log('元素「' + (ZKB.Stage.nameOf(uid) || uid) + '」大小设为 ' +
                Math.round(pct) + '%', 'log-sim');
            } else log('元素不存在或已被移除', 'log-err');
          }
        },
        /* 第三十二轮：移到第 N 层 */
        layerTo: function (uid, n) {
          uid = resolveEl(uid);
          if (!uid) { log('请先在舞台上添加元素（或在积木里填写元素名称）', 'log-err'); return; }
          if (ZKB.Stage && ZKB.Stage.setLayerIndex) {
            if (ZKB.Stage.setLayerIndex(uid, n)) {
              log('元素「' + (ZKB.Stage.nameOf(uid) || uid) + '」移到第 ' +
                ZKB.Stage.getLayerIndex(uid) + ' 层（共 ' +
                ZKB.Stage.getLayerCount() + ' 层）', 'log-sim');
            } else log('元素不存在或已被移除', 'log-err');
          }
        },
        /* 第三十二轮：读层级 */
        layerOf: function (uid) {
          uid = resolveEl(uid);
          if (!uid) return 0;
          return ZKB.Stage && ZKB.Stage.getLayerIndex
            ? ZKB.Stage.getLayerIndex(uid) : 0;
        },
        layerTotal: function () {
          return ZKB.Stage && ZKB.Stage.getLayerCount ? ZKB.Stage.getLayerCount() : 0;
        }
      },

      /* ============================================================
       * 机器人（拓展库「机器人」模型；舞台「巡线机器人 / 机器人送餐」情景）
       * 巡线 / 地面颜色 / 超声波测距 / 语音识别 / AI 摄像头
       * ============================================================ */
      robot: {
        _st: function () {
          return (ZKB.Stage && ZKB.Stage.robotState) ? ZKB.Stage.robotState() : null;
        },
        go: function () {
          var rs = this._st();
          if (!rs) { log('请先在舞台模式添加「机器人」元素（素材库 → 机器人）', 'log-err'); return; }
          if (ZKB.Stage.robotCmd) ZKB.Stage.robotCmd('go');
          log('机器人出发：沿黑色轨迹巡线', 'log-sim');
        },
        stop: function () {
          var rs = this._st();
          if (!rs) { log('请先在舞台模式添加「机器人」元素', 'log-err'); return; }
          if (ZKB.Stage.robotCmd) ZKB.Stage.robotCmd('stop');
          log('机器人停止', 'log-sim');
        },
        speed: function (v) {
          var rs = this._st();
          if (!rs) { log('请先在舞台模式添加「机器人」元素', 'log-err'); return; }
          if (ZKB.Stage.robotCmd) ZKB.Stage.robotCmd('speed', v);
          log('机器人速度 = ' + Math.round(v), 'log-sim');
        },
        /* 地面颜色：绿色（起点）/ 黑色（轨迹）/ 红色（终点）/ 白色（地面） */
        ground: function () {
          var rs = this._st();
          return rs ? rs.ground : '白色';
        },
        /* 机器人搭载的超声波：前方最近障碍物距离（cm） */
        dist: function () {
          var rs = this._st();
          return rs ? rs.dist : 200;
        },
        /* 机器人搭载的 AI 摄像头：识别前方物体名称 */
        cam: function () {
          var rs = this._st();
          return rs ? (rs.target || '无') : '无';
        },
        /* 机器人搭载的语音识别：最近识别到的指令文字 */
        asr: function () { return st.net.asr.text; }
      },

      /* ============================================================
       * 巡线小车（第十四轮；拓展库「巡线小车」模块）
       *   电机（前进/后退/转向）+ 循迹器 5 路探针 + 超声波
       *   数据写入 st.devices.traceCar，舞台上的「巡线小车」元素按此运动
       * ============================================================ */
      trace: {
        _d: function () {
          if (!st.devices.traceCar) {
            st.devices.traceCar = { l: 0, r: 0, auto: true, line: '离线', dist: 200, target: '' };
          }
          return st.devices.traceCar;
        },
        motor: function (dir, spd) {
          var d = this._d();
          spd = Math.max(0, Math.min(100, Math.round(Number(spd) || 0)));
          /* 使用电机即退出自动巡线，回到手动模式 */
          d.auto = false;
          if (dir === 'f') { d.l = spd; d.r = spd; }
          else if (dir === 'b') { d.l = -spd; d.r = -spd; }
          else if (dir === 'l') { d.l = -spd; d.r = spd; }
          else if (dir === 'r') { d.l = spd; d.r = -spd; }
          else { d.l = 0; d.r = 0; }
          var CN = { f: '前进', b: '后退', l: '左转', r: '右转', s: '停止' };
          log('巡线小车电机 ' + (CN[dir] || dir) + '（速度 ' + spd + '）', 'log-sim');
          traceUI(d);
        },
        auto: function (on) {
          var d = this._d();
          d.auto = !!on;
          d.l = d.r = 0;
          log(on ? '巡线小车：开启自动巡线' : '巡线小车：关闭自动巡线', 'log-sim');
          if (on && !(ZKB.Stage && ZKB.Stage.traceTrack)) {
            log('未在舞台上找到「赛道黑线」元素，小车将原地待命', 'log-err');
          }
          traceUI(d);
        },
        /* 循迹器读数：居中 / 偏左 / 偏右 / 离线 */
        line: function () { return this._d().line || '离线'; },
        /* 超声波：车头前方最近障碍物距离（cm） */
        dist: function () { var d = this._d(); return d.dist == null ? 200 : d.dist; }
      },

      /* ============================================================
       * 变量 / 列表 镜像 + 舞台监视器
       * ============================================================ */
      vars: {},          // 显示名 → 当前值（列表为同一数组引用）
      varTypes: {},     // 显示名 → 'scalar' | 'LIST'
      showVars: {},     // 显示名 → true
      showLists: {},
      varSet: function (name, val, type) {
        this.vars[name] = val;
        if (type) this.varTypes[name] = type;
      },
      varGet: function (name) { return this.vars[name]; },
      showVar: function (name) { this.showVars[name] = true; },
      hideVar: function (name) { delete this.showVars[name]; },
      showList: function (name) { this.showLists[name] = true; this.varTypes[name] = 'LIST'; },
      hideList: function (name) { delete this.showLists[name]; },
      listClear: function (arr) { if (arr && typeof arr.length !== 'undefined') arr.length = 0; },
      listContains: function (arr, item) {
        if (!arr || typeof arr.length === 'undefined') return false;
        for (var i = 0; i < arr.length; i++) { if (String(arr[i]) === String(item)) return true; }
        return false;
      },

      /* ============================================================
       * 自制积木
       * ============================================================ */
      defs: {},
      def: function (id, fn) { this.defs[id] = fn; },
      call: function (id, args) {
        var fn = this.defs[id];
        if (!fn) { log('调用了不存在的自制积木（' + id + '）', 'log-err'); return; }
        return fn.apply(null, args || []);
      },

      /* ============================================================
       * 通讯网络（纯仿真：延时 + 状态 + 自发自收回环）
       * ============================================================ */
      mqttSubs: {},
      wifiConnect: function (ssid, pwd) {
        log('正在连接 WiFi：' + ssid + ' …', 'log-sim');
        var self = this;
        return this.sleep(900).then(function () {
          st.net.wifi.connected = true;
          st.net.wifi.ssid = String(ssid);
          log('WiFi 已连接 ✓', 'log-sim');
          if (ZKB.Stage) ZKB.Stage.netEvent('wifi', true);
        });
      },
      wifiOk: function () { return !!st.net.wifi.connected; },

      radioGroup: function (g) {
        st.net.radio.group = Math.round(g);
        log('无线广播频道设为 ' + st.net.radio.group, 'log-sim');
      },
      radioSend: function (msg) {
        log('无线广播发送：' + msg, 'log-sim');
        var self = this;
        /* 仿真自发自收：500ms 后自己收到该消息（便于单块板验证程序） */
        setTimeout(function () {
          if (!running) return;
          st.net.radio.lastMsg = String(msg);
          ZKB.bus.emit('radio');
          if (ZKB.Stage) ZKB.Stage.netEvent('radio');
        }, 500);
        return this.tick();
      },
      radioMsg: function () { return st.net.radio.lastMsg || ''; },

      ntpSync: function () {
        log('NTP 网络对时中…', 'log-sim');
        return this.sleep(700).then(function () {
          st.net.ntp.synced = true;
          log('NTP 对时成功 ✓', 'log-sim');
        });
      },
      timeNow: function (k) {
        var d = new Date();
        var week = '星期' + '日一二三四五六'[d.getDay()];
        var pad = function (x) { return (x < 10 ? '0' : '') + x; };
        var table = {
          all: d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
            ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds()),
          year: String(d.getFullYear()), mon: String(d.getMonth() + 1), day: String(d.getDate()),
          hour: String(d.getHours()), min: String(d.getMinutes()), sec: String(d.getSeconds()),
          week: week
        };
        return table[k] || table.all;
      },

      mqttConnect: function (host, port) {
        log('正在连接 MQTT 服务器 ' + host + ':' + port + ' …', 'log-sim');
        return this.sleep(800).then(function () {
          st.net.mqtt.connected = true;
          st.net.mqtt.host = String(host);
          log('MQTT 已连接 ✓', 'log-sim');
          if (ZKB.Stage) ZKB.Stage.netEvent('mqtt', true);
        });
      },
      onMqtt: function (topic, fn) {
        var key = String(topic);
        (this.mqttSubs[key] || (this.mqttSubs[key] = [])).push(fn);
        log('已订阅 MQTT 主题：' + key, 'log-sim');
      },
      mqttPub: function (topic, msg) {
        log('MQTT 发布 [' + topic + '] ' + msg, 'log-sim');
        var self = this;
        /* 仿真回环：发布到自己订阅的主题 */
        setTimeout(function () {
          if (!running) return;
          self._deliverMqtt(String(topic), String(msg));
        }, 300);
        return this.tick();
      },
      _deliverMqtt: function (topic, msg) {
        st.net.mqtt.lastTopic = topic;
        st.net.mqtt.lastMsg = msg;
        if (ZKB.Stage) ZKB.Stage.netEvent('mqtt');
        var fns = this.mqttSubs[topic] || [];
        fns.forEach(function (fn) {
          Promise.resolve().then(fn).catch(function (e) { log('MQTT 事件错误：' + e.message, 'log-err'); });
        });
      },
      mqttMsg: function () { return st.net.mqtt.lastMsg || ''; },

      asrText: function () { return st.net.asr.text || ''; },

      /* ---- 第二十四轮：AI 语音转文字 + 语音合成 ---- */
      /* 语音转文字：启动一次聆听（麦克风音量参与置信度计算） */
      speechRecognize: function (cmd) {
        var mic = st.devices.mic ? (st.devices.mic.v || 0)
          : (st.devices.micExt ? (st.devices.micExt.v || 0) : null);
        return ZKB.Speech.asrStart(cmd || '', mic == null ? null : mic);
      },
      speechText: function () { return ZKB.Speech.asrText(); },
      speechConf: function () { return ZKB.Speech.asrConf(); },
      speechIs: function (cmd) { return ZKB.Speech.asrIs(cmd); },
      /* 语音合成：返回 Promise（await 后可等朗读结束） */
      speechSpeak: function (text, rate, pitch, vol) {
        return ZKB.Speech.speak(text == null ? '' : String(text), rate, pitch, vol);
      },
      speechStop: function () { ZKB.Speech.stop(); return ''; },
      speechSpeaking: function () { return ZKB.Speech.speaking(); },
      speechDone: function () { return ZKB.Speech.done(); },
      speechWait: function () {
        return ZKB.Speech.waitDone(15000).then(function (ok) {
          return ok ? 1 : 0;
        });
      },

      weather: function (city, k) {
        /* 未收录城市也能查询：weatherNow 内部会先地理编码、必要时模拟 */
        var known = weatherCity(city);
        city = known ? known.name : (String(city == null ? '' : city).trim() || '北京');
        st.net.weatherCity = city;
        /* 联网优先（30 分钟内缓存），否则按月份模拟 */
        var data = weatherNow(city);
        var jitter = Math.round((Math.random() - 0.5) * 2);
        var high = String(data.high + jitter);
        var low = String(data.low + jitter);
        var table = {
          text: data.text,
          high: high,
          low: low,
          humidity: String(data.humidity),
          wind: data.wind,
          windLevel: String(data.windLevel)
        };
        /* 供舞台天气情境与设备卡片显示（含完整六项） */
        st.net.weatherResult = {
          city: data.city || city, text: data.text, high: high, low: low,
          humidity: String(data.humidity), wind: data.wind,
          windLevel: String(data.windLevel), windKmh: data.windKmh,
          source: data.source
        };
        log('天气查询：' + city + ' → ' + data.text + ' ' + low + '~' + high + '℃　湿度 ' +
          data.humidity + '%　' + data.wind + ' ' + data.windLevel + '级（' +
          (data.source === 'net' ? '联网数据' : '离线模拟') + '）', 'log-sim');
        return table[k] || data.text;
      }
    };

    return S;
  }

  /* 仿真天气数据 */
  /* 说明：天气数据已由 ZKB.Weather（联网 + 按月模拟）接管 */

  /* 色相 → RGB（跑马灯用） */
  function hsv2rgb(h, s, v) {
    h = ((h % 360) + 360) % 360 / 60;
    var i = Math.floor(h), f = h - i;
    var p = v * (1 - s), q = v * (1 - s * f), t = v * (1 - s * (1 - f));
    var r, g, b;
    switch (i % 6) {
      case 0: r = v; g = t; b = p; break;
      case 1: r = q; g = v; b = p; break;
      case 2: r = p; g = v; b = t; break;
      case 3: r = p; g = q; b = v; break;
      case 4: r = t; g = p; b = v; break;
      default: r = v; g = p; b = q;
    }
    return [Math.round(r * 255), Math.round(g * 255), Math.round(b * 255)];
  }

  function clamp255(n) {
    n = parseInt(n, 10) || 0;
    return Math.max(0, Math.min(255, n));
  }

  /* 积木类型 → 设备 id（自动补齐设备） */
  var BLOCK_DEVICE = {
    zk_dht_measure: 'dht', zk_dht_val: 'dht',
    zk_ultra: 'ultrasonic', zk_servo: 'servo',
    zk_ir: 'ir', zk_when_ir: 'ir',
    zk_heat: 'heater', zk_heat_power: 'heater',
    zk_car: 'car', zk_car_wheels: 'car',
    zk_motor: 'motor', zk_pump: 'pump', zk_pump_power: 'pump',
    /* 第十四轮：机器人模型 / 巡线小车 */
    zk_robot_go: 'robot', zk_robot_speed: 'robot', zk_robot_ground: 'robot',
    zk_robot_dist: 'robot', zk_robot_cam: 'robot', zk_robot_asr: 'robot',
    zk_trace_motor: 'traceCar', zk_trace_auto: 'traceCar',
    zk_trace_line: 'traceCar', zk_trace_dist: 'traceCar',
    zk_color_rgb: 'color', zk_color_seen: 'color',
    zk_camera_result: 'camera', zk_camera_seen: 'camera',
    zk_mic: 'mic', zk_ambient: 'lightExt',
    zk_soil: 'soil', zk_soil_pct: 'soil',
    zk_pm25: 'pm25', zk_pm25_level: 'pm25',
    zk_pressure: 'baro', zk_altitude: 'baro',
    zk_ext_btn: 'button',
    zk_fan: 'fan', zk_fan_power: 'fan',
    /* 通讯网络 */
    zk_wifi_connect: 'wifi', zk_wifi_ok: 'wifi',
    zk_radio_group: 'radio', zk_radio_send: 'radio',
    zk_when_radio: 'radio', zk_radio_msg: 'radio',
    zk_ntp_sync: 'ntp', zk_time_now: 'ntp',
    zk_mqtt_connect: 'mqtt', zk_mqtt_pub: 'mqtt',
    zk_when_mqtt: 'mqtt', zk_mqtt_msg: 'mqtt',
    zk_asr_text: 'asr',
    zk_weather: 'weather',
    /* AI 视觉（第二十三轮）——运行这些积木会自动补齐 AI 摄像头设备 */
    zk_vision_ocr_start: 'camera', zk_vision_ocr_text: 'camera', zk_vision_ocr_number: 'camera',
    zk_vision_face_register: 'camera', zk_vision_face_verify: 'camera',
    zk_vision_face_name: 'camera', zk_vision_face_gender: 'camera',
    zk_vision_face_bio: 'camera', zk_vision_face_emotion: 'camera',
    zk_vision_face_emotion_text: 'camera',
    zk_vision_obj_start: 'camera', zk_vision_obj_car: 'camera',
    zk_vision_obj_animal: 'camera', zk_vision_obj_plant: 'camera',
    zk_vision_obj_dish: 'camera', zk_vision_obj_fruit: 'camera',
    zk_vision_confidence: 'camera'
  };

  function ensureDevices(workspace) {
    var need = {};
    workspace.getAllBlocks(false).forEach(function (b) {
      var id = BLOCK_DEVICE[b.type];
      if (id) need[id] = true;
    });
    var cur = ZKB.SimBoard.getDevices();
    var merged = cur.slice();
    Object.keys(need).forEach(function (id) { if (merged.indexOf(id) < 0) merged.push(id); });
    if (merged.length !== cur.length) ZKB.SimBoard.setDevices(merged);
  }

  /* ---------------- 启动 / 停止 ---------------- */
  function run(workspace) {
    st = ZKB.state;
    ensureDevices(workspace);
    ZKB.bus.clear();
    running = true;
    startedAt = Date.now();
    lastBeat = 0;
    buildRuntime();
    // 复位执行器
    st.devices.car.l = st.devices.car.r = 0; st.devices.motor.vel = 0;
    st.devices.car.x = 40; st.devices.car.y = 50; st.devices.car.deg = 90;
    st.devices.car._sx = 60; st.devices.car._sy = 250; st.devices.car._sdeg = 0;
    st.devices.heater.on = false; st.devices.heater.power = 0;
    st.devices.pump.on = false; st.devices.pump.power = 0;
    ZKB.SimBoard.rerenderCards();

    /* ---------- 第二十九轮：八年级新增硬件 —— 面板交互桥接到运行时 ----------
       sim-board 只知道设备面板，不知道 S 对象，所以面板通过事件总线
       把「用户拖了滑块 / 点了刷卡」传进来，这里落到 S 上。 */
    ZKB.bus.on('sim-set', function (d) {
      if (!S || !S.sensor) return;
      S.sensor.set(d.key, d.val);
      if (String(d.key).indexOf('gps.') === 0) syncGpsView();
    });
    /* 第三十三轮：请求获取电脑真实定位。
       sim-board 拿不到 S 引用，走bus；用回调把结果传回去给面板刷新。 */
    ZKB.bus.on('sim-gps-real', function (d) {
      if (!S || !S.sensor) { if (d && d.cb) d.cb(false, '仿真未启动'); return; }
      S.sensor.gpsUseReal().then(function (ok) {
        if (!ok) S.sensor.gpsClearReal();
        syncGpsView();
        if (d && d.cb) d.cb(ok, S.sensor.gpsIsReal() ? '已获取真实定位' : '定位失败，已用模拟数据');
      });
    });
    /* 面板点「丢失信号」时清掉真实定位缓存 */
    ZKB.bus.on('sim-gps-clear', function () {
      if (!S || !S.sensor) return;
      S.sensor.gpsClearReal();
    });
    ZKB.bus.on('sim-sensor', function (d) {
      if (!S || !S.sensor) return;
      if (d.act === 'calibrate') S.sensor.calibrate(d.which);
      else if (d.act === 'peel') S.sensor.peel(d.which);
    });
    ZKB.bus.on('sim-rfid', function (d) {
      if (!S || !S.rfid) return;
      S.rfid.last = d.id || '';
    });
    ZKB.bus.on('sim-asr2', function (d) {
      if (!S || !S.asr2) return;
      S.asr2.trigger(d.text);
    });

    var code = ZKB.genSim(workspace);
    try {
      var AsyncFunction = Object.getPrototypeOf(async function () { }).constructor;
      var fn = new AsyncFunction('S', code);
      Promise.resolve(fn(S)).catch(function (e) {
        log('程序错误：' + e.message + '（行：' + (e.lineNumber || '?') + '）', 'log-err');
        if (running) { running = false; if (onHalt) onHalt(); }
      });
    } catch (e) {
      log('代码生成失败：' + e.message, 'log-err');
      console.error(e, code);
    }
  }

  /* 把 GPS 读数同步到 sim-board 的面板视图（面板通过 ZKB.state.gpsView 读取） */
  function syncGpsView() {
    if (!ZKB.state || !S || !S.sensor) return;
    ZKB.state.gpsView = {
      ready: S.sensor.get('gps.ready') >= 1 || S.sensor.get('gps.real.ok') >= 1,
      /* 第三十三轮：带上「是否真实定位」标记，面板据此显示来源 */
      real: S.sensor.get('gps.real.ok') >= 1,
      acc: S.sensor.get('gps.real.acc'),
      lon: S.sensor.get('gps.lon'),
      lat: S.sensor.get('gps.lat'),
      lonEW: S.sensor.get('gps.lonEW'),
      latNS: S.sensor.get('gps.latNS'),
      alt: S.sensor.get('gps.alt'),
      num: S.sensor.get('gps.num'),
      utc: S.sensor.get('gps.utc')
    };
  }

  function stop() {
    if (!running) return;
    running = false;
    audio.stop();
    // 停车 / 停转
    if (st) {
      st.devices.car.l = st.devices.car.r = 0;
      st.devices.motor.vel = 0;
    }
    /* 清空虚拟屏（停止后不再显示上一帧画面） */
    try { oled.init(); oled.clear(); } catch (e) { }
    /* 恢复 RGB 灯珠为初始状态 */
    if (st && st.rgb) {
      st.rgb.dots = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
      st.rgb.brightness = 0.3;
    }
    if (ZKB.SimBoard) ZKB.SimBoard.refreshRGB();
    document.querySelectorAll('.dev-card').forEach(function (c) { c.classList.remove('running'); });
    var blade = document.querySelector('#card-motor .motor-spin');
    if (blade) blade.classList.remove('spin');
    log('仿真已停止', 'log-sim');
  }

  var onHalt = null;

  ZKB.SimEngine = {
    run: run,
    stop: stop,
    isRunning: function () { return running; },
    setOnHalt: function (fn) { onHalt = fn; },
    /* 设备卡片：模拟 MQTT 服务器下发消息 */
    injectMqtt: function (topic, msg) {
      if (S && running) S._deliverMqtt(String(topic), String(msg));
    },
    /* 舞台监视器数据 */
    getMonitors: function () {
      if (!S) return { vars: {}, lists: {}, values: {} };
      return { vars: S.showVars, lists: S.showLists, values: S.vars };
    },
    /* 虚拟硬件 API 对象（未运行时为 null）
       供调试与自动化测试直接调用 oled / rgb / music 等虚拟外设。 */
    runtime: function () { return S || null; },
    /* 直接操作虚拟屏位图（不启动程序也可预览） */
    oled: {
      bitmap: function (bits, ox, oy) { oled.init(); return oled.bitmap(bits, ox, oy); },
      clear: function () { oled.init(); return oled.clear(); },
      text: function (s, x, y, cn, color) { oled.init(); return oled.text(s, x, y, cn, color); },
      setTextColor: function (name) { oled.init(); return oled.setTextColor(name); },
      rect: function (x, y, w, h, f) { oled.init(); return oled.rect(x, y, w, h, f); },
      circle: function (x, y, r, f) { oled.init(); return oled.circle(x, y, r, f); },
      fill: function (v) { oled.init(); return oled.fill(v); },
      line: function (a, b, c, d) { oled.init(); return oled.line(a, b, c, d); },
      pixel: function (x, y, v) { oled.init(); return oled.pixel(x, y, v); },
      roundrect: function (x, y, w, h, r, v) { oled.init(); return oled.roundrect(x, y, w, h, r, v); },
      hline: function (x, y, w, v) { oled.init(); return oled.hline(x, y, w, v); },
      vline: function (x, y, l, v) { oled.init(); return oled.vline(x, y, l, v); },
      triangle: function (a, b, c, d, e, f, g) { oled.init(); return oled.triangle(a, b, c, d, e, f, g); },
      progress: function (x, y, w, h, p) { oled.init(); return oled.progress(x, y, w, h, p); },
      stripbar: function (x, y, w, h, p, d, f) { oled.init(); return oled.stripbar(x, y, w, h, p, d, f); },
      show: function () { return oled.show(); },
      invert: function (v) { oled.init(); return oled.invert(v); },
      showImage: function (id) { if (ZKB.OledImage) ZKB.OledImage.show(id); },
      showFace: function (k) { if (ZKB.OledImage && ZKB.OledImage.get('face_' + k)) ZKB.OledImage.show('face_' + k); },
      /* 第二十九轮：5 行显示 / 二维码 */
      line5: function (s, line, cn) { oled.init(); return oled.line5(s, line, cn); },
      qrcode: function (str, x, y) { oled.init(); return oled.qrcode(str, x, y); }
    }
  };

})(window);
