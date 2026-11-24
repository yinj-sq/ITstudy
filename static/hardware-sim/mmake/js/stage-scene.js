/* ============================================================
 * stage-scene.js —— 舞台矢量场景元素库
 * 所有元素均为纯 SVG（矢量），任意缩放不失真；每个元素定义
 *   view  : 默认尺寸（舞台逻辑坐标 800×560）
 *   build : 返回 SVG 标记字符串，可读取自身状态生成动态外观
 *   tick  : 可选，每帧回调，用于动画（风扇转动、水滴、蒸汽…）
 * 元素可被用户在舞台上直接拖动，位置保存在 ZKB.state.scene。
 * ============================================================ */
(function (global) {
  'use strict';
  var ZKB = global.ZKB || (global.ZKB = {});

  /* ---------- 常用 SVG 片段 ---------- */
  function shadow(cx, cy, rx, ry, o) {
    return '<ellipse cx="' + cx + '" cy="' + cy + '" rx="' + rx + '" ry="' + ry +
      '" fill="rgba(30,50,80,' + (o || 0.16) + ')"/>';
  }
  /* 线性渐变定义（一次性放入 <defs>） */
  var GRAD_DEFS = [
    ['gPot', '#c98a52', '#8d5a2b'],
    ['gPotSoil', '#6b4a2f', '#4a3220'],
    ['gKettle', '#eef2f6', '#a8b3bd'],
    ['gKettleHot', '#ffb26b', '#e0552c'],
    ['gLampShade', '#ffe9a8', '#f0a93c'],
    ['gLampOn', '#fff6cf', '#ffd24a'],
    ['gSwitch', '#fdfdfd', '#cfd6dd'],
    ['gPotPlant', '#7fc96b', '#3f8f4f'],
    ['gBulb', '#fff8d6', '#ffd84a'],
    ['gBulbOff', '#e8ecf0', '#b9c2cb'],
    ['gHeater', '#ff9d5c', '#e0431f'],
    ['gHeaterOff', '#b9c2cb', '#8a939e'],
    ['gScreen', '#123a2e', '#0a2019']
  ].map(function (d) {
    return '<linearGradient id="' + d[0] + '" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0" stop-color="' + d[1] + '"/><stop offset="1" stop-color="' + d[2] + '"/>' +
      '</linearGradient>';
  }).join('');

  function rr(x, y, w, h, r, fill, extra) {
    return '<rect x="' + x + '" y="' + y + '" width="' + w + '" height="' + h + '" rx="' + r +
      '" fill="' + fill + '"' + (extra || '') + '/>';
  }

  /* ============================================================
   * 元素库
   * st: 设备/场景状态；t: 累计秒数
   * ============================================================ */
  var LIB = {

    /* ---------------- 花盆（土壤湿度联动） ---------------- */
    pot: {
      name: '花盆', w: 92, h: 104, cat: '生活物品', dynamic: true,
      build: function (st) {
        var soil = st && st.devices.soil;
        var wet = soil ? (soil.v > 600 ? 2 : soil.v > 300 ? 1 : 0) : 1;
        var tilt = wet === 0 ? 9 : wet === 1 ? 4 : 0;   // 缺水叶片下垂
        var leafC = wet === 0 ? '#c9a227' : wet === 1 ? '#8fbf5a' : '#4fae52';
        var s = shadow(46, 100, 34, 8);
        // 叶片
        s += '<g transform="translate(46,52)">';
        for (var i = 0; i < 6; i++) {
          var a = -150 + i * 60;
          s += '<path d="M0,0 Q6,-26 2,-44 Q-4,-26 0,0Z" fill="' + leafC +
            '" transform="rotate(' + (a + 180) + ') rotate(' + tilt + ',0,-44)" opacity="' + (0.75 + i * 0.04) + '"/>';
        }
        s += '<circle cx="0" cy="-6" r="5" fill="#6b4a2f"/></g>';
        // 盆体
        s += '<path d="M14,56 L78,56 L70,98 Q46,102 22,98 Z" fill="url(#gPot)" stroke="#7a4a22" stroke-width="1.5"/>';
        s += rr(14, 50, 64, 12, 3, 'url(#gPotSoil)');        // 土壤
        // 土壤湿度色点
        var dot = wet === 2 ? '#3fa9e0' : wet === 1 ? '#7fc4e8' : '#c98a52';
        s += '<circle cx="46" cy="56" r="4" fill="' + dot + '"/>';
        if (wet === 2) s += '<circle cx="40" cy="55" r="2" fill="#bfe6ff" opacity=".8"/>';
        s += rr(12, 92, 68, 8, 3, '#8d5a2b');
        return s;
      },
      label: function (st) {
        var soil = st && st.devices.soil;
        if (!soil) return '花盆';
        return '湿度 ' + soil.v;
      }
    },

    /* ---------------- 台灯（光线 / 开关联动） ---------------- */
    lamp: {
      name: '台灯', w: 104, h: 130, cat: '生活物品', dynamic: true,
      build: function (st) {
        var on = lampOn(st);
        var gl = lampGlow(st);                /* 呼吸光晕强度 */
        var t = (st && st._animT) || 0;
        var s = shadow(52, 124, 30, 7);
        if (on) {
          /* 灯光亮起动画：外层大光晕 + 内层光晕随时间呼吸 */
          s += '<ellipse cx="52" cy="34" rx="' + (56 + gl * 10).toFixed(1) + '" ry="' +
            (48 + gl * 8).toFixed(1) + '" fill="rgba(255,214,90,' + (0.16 * gl).toFixed(3) + ')"/>';
          s += '<ellipse cx="52" cy="30" rx="' + (44 + gl * 8).toFixed(1) + '" ry="' +
            (38 + gl * 6).toFixed(1) + '" fill="rgba(255,226,140,' + (0.26 * gl).toFixed(3) + ')"/>';
        }
        // 底座
        s += '<ellipse cx="52" cy="122" rx="30" ry="8" fill="#3f4a56"/>';
        s += rr(46, 60, 6, 62, 3, '#5a6672');
        // 灯罩
        s += '<path d="M22,58 L82,58 L70,26 L34,26 Z" fill="url(#' + (on ? 'gLampOn' : 'gLampShade') + ')" stroke="#a9761c" stroke-width="1.5"/>';
        s += rr(30, 54, 48, 8, 3, on ? '#ffe07a' : '#d9c08a');
        // 灯珠（点亮时高亮 + 呼吸光晕）
        s += '<circle cx="56" cy="56" r="' + (on ? 9 : 6) + '" fill="' + (on ? '#fffbe8' : '#cfc6ae') + '"/>';
        if (on) {
          var pulse = 0.82 + 0.18 * Math.sin(t * 2.6);
          s += '<circle cx="56" cy="56" r="' + (14 * pulse).toFixed(1) + '" fill="#ffe9a0" opacity="' +
            (0.38 * gl).toFixed(3) + '"/>';
          s += '<circle cx="56" cy="56" r="' + (22 * pulse).toFixed(1) + '" fill="#fff3c4" opacity="' +
            (0.16 * gl).toFixed(3) + '"/>';
        }
        // 开关
        s += rr(38, 92, 22, 12, 6, '#2b3138');
        s += '<circle cx="' + (on ? 52 : 46) + '" cy="98" r="4" fill="' + (on ? '#ffd24a' : '#8a939e') + '"/>';
        return s;
      },
      label: function (st) { return lampOn(st) ? '台灯·开' : '台灯·关'; }
    },

    /* ---------------- 热水壶（温度联动 + 蒸汽） ---------------- */
    kettle: {
      name: '热水壶', w: 96, h: 116, cat: '生活物品', dynamic: true,
      build: function (st) {
        var dht = st && st.devices.dht;
        var temp = dht ? dht.t : 25;
        var hot = temp >= 60;
        var warm = temp >= 40;
        var s = shadow(46, 112, 28, 7);
        // 壶身
        s += '<path d="M20,44 Q20,34 32,32 L66,32 Q80,34 80,48 L80,92 Q80,102 68,102 L30,102 Q20,102 20,92 Z" fill="url(#' +
          (hot ? 'gKettleHot' : 'gKettle') + ')" stroke="#8b959f" stroke-width="1.5"/>';
        // 壶嘴
        s += '<path d="M78,52 L92,44 L92,54 L78,60 Z" fill="url(#gKettle)" stroke="#8b959f" stroke-width="1.2"/>';
        // 把手
        s += '<path d="M24,44 Q10,58 26,72" fill="none" stroke="#6b7680" stroke-width="5" stroke-linecap="round"/>';
        // 底座
        s += rr(22, 100, 56, 10, 4, '#4d5560');
        // 盖 + 温控灯
        s += rr(34, 24, 34, 10, 4, '#b9c2cb');
        s += '<circle cx="51" cy="29" r="3.5" fill="' + (hot ? '#ff4d4d' : warm ? '#ffb020' : '#7fd8a0') + '"/>' +
          (hot ? '<circle cx="51" cy="29" r="7" fill="#ff6b6b" opacity=".35"/>' : '');
        // 温度标签
        s += '<text x="50" y="80" font-size="15" font-weight="700" text-anchor="middle" fill="' +
          (hot ? '#7a1c0c' : '#3c4650') + '">' + Math.round(temp) + '°C</text>';
        return s;
      },
      tick: function (g, st, t) {
        var dht = st && st.devices.dht;
        var temp = dht ? dht.t : 25;
        var layer = g.querySelector('.steam');
        if (temp < 55) { if (layer) layer.remove(); return; }
        if (!layer) {
          layer = document.createElementNS('http://www.w3.org/2000/svg', 'g');
          layer.setAttribute('class', 'steam');
          g.appendChild(layer);
        }
        var html = '';
        for (var i = 0; i < 3; i++) {
          var ph = (t * 0.7 + i * 0.33) % 1;
          var y = 22 - ph * 26;
          var op = Math.max(0, 1 - ph) * 0.75;
          html += '<path d="M44,' + y + ' q5,-7 0,-13 q-5,-6 0,-12" fill="none" stroke="#ffffff" ' +
            'stroke-width="2.4" stroke-linecap="round" opacity="' + op.toFixed(2) + '"/>';
        }
        layer.innerHTML = html;
      },
      label: function (st) {
        var dht = st && st.devices.dht;
        return '热水壶 ' + Math.round(dht ? dht.t : 25) + '°C';
      }
    },

    /* ---------------- 墙壁开关（可点击，联动灯/风扇） ---------------- */
    switch: {
      name: '开关', w: 62, h: 84, cat: '生活物品', dynamic: true,
      build: function (st) {
        var on = lampOn(st);
        var s = rr(6, 6, 50, 72, 8, 'url(#gSwitch)', ' stroke="#b9c2cb" stroke-width="1.5"');
        s += rr(12, 12, 38, 34, 5, '#f2f4f6', ' stroke="#dde2e7"');
        // 拨杆
        s += '<g class="lever" transform="translate(31,29) rotate(' + (on ? -22 : 22) + ')">' +
          rr(-5, -14, 10, 28, 5, on ? '#ffd24a' : '#c3cbd3') + '</g>';
        s += '<circle cx="31" cy="60" r="4" fill="' + (on ? '#ffb020' : '#c3cbd3') + '"/>';
        s += '<text x="31" y="72" font-size="8" text-anchor="middle" fill="#8a939e">' + (on ? 'ON' : 'OFF') + '</text>';
        return s;
      },
      label: function (st) { return lampOn(st) ? '开关·开' : '开关·关'; },
      clickable: true
    },

    /* ---------------- 加湿器 / 水泵（沿用设备状态） ---------------- */
    humidifier: {
      name: '加湿器', w: 76, h: 112, cat: '生活物品', dynamic: true,
      build: function (st) {
        var on = pumpOn(st);
        var s = shadow(38, 108, 24, 6);
        s += '<path d="M18,34 Q18,24 30,24 L46,24 Q58,24 58,34 L58,96 Q58,104 48,104 L28,104 Q18,104 18,96 Z" ' +
          'fill="' + (on ? '#bfe6f5' : '#e6eaee') + '" stroke="#9aa6b0" stroke-width="1.5"/>';
        s += rr(24, 40, 28, 44, 5, '#ffffff', ' opacity=".55"');
        s += rr(30, 14, 16, 12, 3, '#b9c2cb');
        if (on) {
          s += '<circle cx="38" cy="10" r="3.5" fill="#7fd8f0" opacity=".8"/>';
        }
        s += '<circle cx="38" cy="88" r="6" fill="' + (on ? '#4fc3f7' : '#cfd6dd') + '"/>';
        return s;
      },
      tick: function (g, st, t) {
        var on = pumpOn(st);
        var layer = g.querySelector('.mist');
        if (!on) { if (layer) layer.remove(); return; }
        if (!layer) {
          layer = document.createElementNS('http://www.w3.org/2000/svg', 'g');
          layer.setAttribute('class', 'mist');
          g.appendChild(layer);
        }
        var html = '';
        for (var i = 0; i < 4; i++) {
          var ph = (t * 0.55 + i * 0.25) % 1;
          var y = 12 - ph * 20;
          html += '<circle cx="' + (28 + i * 7) + '" cy="' + y.toFixed(1) + '" r="' + (2 + ph * 3).toFixed(1) +
            '" fill="#bfe6f5" opacity="' + Math.max(0, 0.75 - ph * 0.75).toFixed(2) + '"/>';
        }
        layer.innerHTML = html;
      },
      label: function (st) { return pumpOn(st) ? '加湿器·开' : '加湿器·关'; }
    },

    /* ---------------- 电风扇（沿用风扇设备） ---------------- */
    fan: {
      name: '电风扇', w: 96, h: 126, cat: '生活物品', dynamic: true,
      build: function (st) {
        var f = st && st.devices.fan;
        var on = f && f.on;
        var spd = f ? Math.max(1, f.power) : 1;
        var s = shadow(48, 122, 26, 6);
        s += rr(42, 66, 10, 52, 4, '#8a939e');
        s += '<ellipse cx="47" cy="120" rx="24" ry="7" fill="#5a6672"/>';
        // 网罩
        s += '<circle cx="47" cy="46" r="34" fill="none" stroke="#9aa6b0" stroke-width="2.5"/>';
        s += '<circle cx="47" cy="46" r="30" fill="none" stroke="#c3cbd3" stroke-width="1.5"/>';
        // 扇叶（旋转组由 tick 更新 transform）
        s += '<g class="blades" transform="translate(47,46)">' +
          '<g class="spin">' + [0, 120, 240].map(function (a) {
            return '<path d="M0,0 Q13,-9 22,-3 Q13,5 0,0Z" fill="#8ecae6" transform="rotate(' + a + ')"/>';
          }).join('') + '</g>';
        s += '<circle cx="47" cy="46" r="6" fill="#4a5560"/>';
        return s;
      },
      tick: function (g, st, t) {
        var f = st && st.devices.fan;
        var spin = g.querySelector('.spin');
        if (!spin) return;
        var on = f && f.on;
        if (on) {
          spin.setAttribute('transform', 'rotate(' + ((t * (f.power || 1) * 8) % 360) + ')');
          spin.style.opacity = '1';
        } else {
          spin.style.opacity = '.45';
        }
      },
      label: function (st) {
        var f = st && st.devices.fan;
        return f && f.on ? '风扇·' + f.power + '%' : '风扇·关';
      }
    },

    /* ---------------- 加热杯 / 暖手宝（加热元件） ---------------- */
    heater: {
      name: '加热座', w: 92, h: 76, cat: '生活物品', dynamic: true,
      build: function (st) {
        var h = st && st.devices.heater;
        var on = h && h.on;
        var p = on ? (h.power || 50) / 100 : 0;
        var s = shadow(46, 72, 28, 6);
        s += '<path d="M14,44 Q14,36 24,36 L68,36 Q78,36 78,44 L78,62 Q78,70 68,70 L24,70 Q14,70 14,62 Z" fill="url(#' +
          (on ? 'gHeater' : 'gHeaterOff') + ')" stroke="#8b959f" stroke-width="1.4"/>';
        // 加热盘
        s += '<ellipse cx="46" cy="38" rx="28" ry="8" fill="' + (on ? '#ff8a3d' : '#aeb7c0') + '"/>';
        if (on) {
          s += '<ellipse cx="46" cy="38" rx="28" ry="8" fill="none" stroke="#ffd24a" stroke-width="2.5" opacity="' + (0.4 + p * 0.6) + '"/>';
        }
        // 旋钮 + 指示灯
        s += '<circle cx="70" cy="56" r="5" fill="#5a6672"/>';
        s += '<circle cx="22" cy="56" r="3.5" fill="' + (on ? '#ff4d4d' : '#aeb7c0') + '"/>';
        if (on) s += '<text x="46" y="59" font-size="11" font-weight="700" text-anchor="middle" fill="#fff">' + h.power + '%</text>';
        return s;
      },
      label: function (st) {
        var h = st && st.devices.heater;
        return h && h.on ? '加热·' + h.power + '%' : '加热·关';
      }
    },

    /* ---------------- 桌面（摆放基底） ---------------- */
    desk: {
      name: '桌面', w: 260, h: 90, cat: '场景',
      build: function () {
        var s = rr(0, 12, 260, 18, 4, '#c98a52', ' stroke="#a06f3c" stroke-width="1.5"');
        s += rr(8, 30, 12, 56, 3, '#a06f3c');
        s += rr(240, 30, 12, 56, 3, '#a06f3c');
        s += rr(14, 16, 232, 6, 2, '#e0c49a', ' opacity=".5"');
        return s;
      },
      label: function () { return '桌面'; }
    },

    /* ---------------- 窗（光线情景） ---------------- */
    window: {
      name: '窗户', w: 120, h: 130, cat: '场景', dynamic: true,
      build: function (st) {
        var light = st ? Math.min(1, (st.light || 0) / 4095) : 0.6;
        var sky = light > 0.5 ? '#bfe6ff' : '#5c7a99';
        var s = rr(0, 0, 120, 130, 6, '#e8e2d6', ' stroke="#b0a898" stroke-width="2"');
        s += rr(8, 8, 104, 114, 3, sky);
        if (light > 0.5) {
          s += '<circle cx="88" cy="34" r="12" fill="#ffe27a" opacity=".9"/>';
        }
        s += '<path d="M60,8 L60,122 M8,65 L112,65" stroke="#e8e2d6" stroke-width="5"/>';
        if (light > 0.35) {
          s += '<path d="M112,50 L160,10 L160,120 L112,96 Z" fill="#fff6cf" opacity="' + (light * 0.3).toFixed(2) + '"/>';
        }
        return s;
      },
      label: function (st) {
        var light = st ? Math.round(st.light || 0) : 0;
        return '窗户 光线' + light;
      }
    },

    /* ---------------- 绿植 ---------------- */
    plant: {
      name: '绿植', w: 78, h: 110, cat: '生活物品',
      build: function () {
        var s = shadow(39, 106, 22, 6);
        s += '<path d="M18,66 L60,66 L55,102 Q39,105 23,102 Z" fill="url(#gPot)" stroke="#7a4a22" stroke-width="1.4"/>';
        s += rr(18, 60, 42, 10, 3, 'url(#gPotSoil)');
        s += '<g transform="translate(39,60)">';
        for (var i = 0; i < 7; i++) {
          s += '<ellipse cx="0" cy="-18" rx="6" ry="20" fill="url(#gPotPlant)" transform="rotate(' +
            (-60 + i * 20) + ')" opacity=".9"/>';
        }
        s += '</g>';
        return s;
      },
      label: function () { return '绿植'; }
    },

    /* ---------------- 书本（一组 3 本） ---------------- */
    books: {
      name: '书本', w: 86, h: 40, cat: '生活物品',
      build: function () {
        var cols = ['#e0552c', '#3f88e8', '#3fae5a'];
        var s = '';
        for (var i = 0; i < 3; i++) {
          s += rr(i * 26, 12 - i * 2, 24, 28, 2, cols[i], ' opacity=".92"') +
            rr(i * 26 + 3, 16 - i * 2, 18, 3, 1, '#ffffff', ' opacity=".55"');
        }
        return s;
      },
      label: function () { return '书本'; }
    },

    /* ---------------- 闹钟 ---------------- */
    clock: {
      name: '闹钟', w: 74, h: 78, cat: '生活物品', dynamic: true,
      build: function (st) {
        var ntp = st && st.net && st.net.ntp && st.net.ntp.synced;
        var d = new Date();
        var hh = d.getHours(), mm = d.getMinutes();
        var ah = ((hh % 12) + mm / 60) * 30, am = mm * 6;
        var s = shadow(37, 74, 22, 5);
        s += '<circle cx="37" cy="38" r="30" fill="#eef2f6" stroke="#8b959f" stroke-width="2"/>';
        s += '<circle cx="37" cy="38" r="24" fill="#fff"/>';
        s += '<line x1="37" y1="38" x2="' + (37 + Math.cos((ah - 90) * Math.PI / 180) * 13).toFixed(1) +
          '" y2="' + (38 + Math.sin((ah - 90) * Math.PI / 180) * 13).toFixed(1) + '" stroke="#2b3138" stroke-width="2.6" stroke-linecap="round"/>';
        s += '<line x1="37" y1="38" x2="' + (37 + Math.cos((am - 90) * Math.PI / 180) * 18).toFixed(1) +
          '" y2="' + (38 + Math.sin((am - 90) * Math.PI / 180) * 18).toFixed(1) + '" stroke="#2b3138" stroke-width="1.8" stroke-linecap="round"/>';
        s += '<circle cx="37" cy="38" r="2.4" fill="#e0552c"/>';
        s += '<path d="M18,12 L26,20 M56,12 L48,20" stroke="#8b959f" stroke-width="3" stroke-linecap="round"/>';
        s += '<text x="37" y="70" font-size="8" text-anchor="middle" fill="' + (ntp ? '#3fae5a' : '#9aa6b0') + '">' +
          (ntp ? '已对时' : '未对时') + '</text>';
        return s;
      },
      label: function () { return '闹钟'; }
    }
  };

  /* ---------- 状态辅助 ---------- */
  /* lampOn 见下方「光照联动」小节（第十六轮重写） */
  /* ============================================================
   * 光照联动（第十六轮）
   *   lightLevel：优先读拓展「光线传感器」读数，没有则用板载光线
   *   lampOn：光线 < 400（或LED 模块亮 / 掌控板 RGB 彩灯亮）→ 台灯点亮
   *   lampGlow：台灯开启时的呼吸光晕强度（0~1），用于动画
   * ============================================================ */
  function lightLevel(st) {
    if (!st) return 2000;
    var dev = st.devices || {};
    if (dev.lightExt && dev.lightExt.v != null) return dev.lightExt.v;   /* 拓展光线传感器 */
    if (dev.dht && dev.dht.light != null) return dev.dht.light;
    return st.light != null ? st.light : 2000;                          /* 板载光线 */
  }
  /* 掌控板 RGB 彩灯亮度（0~100），示例⑤用 RGB 积木亮灯 */
  function rgbLitLevel(st) {
    if (ZKB.rgbLitLevel) {
      try { return ZKB.rgbLitLevel() || 0; } catch (e) { /* 忽略 */ }
    }
    var rgb = st && st.rgb;
    if (!rgb || !rgb.dots) return 0;
    var m = 0;
    rgb.dots.forEach(function (c) { m = Math.max(m, c[0], c[1], c[2]); });
    return Math.round(m * Math.max(0.25, rgb.brightness));
  }
  function lampOn(st) {
    if (st && st.sceneFlags && st.sceneFlags.lamp !== undefined) return !!st.sceneFlags.lamp;
    if (st) {
      if (lightLevel(st) < 400) return true;                             /* 光线不足自动亮灯 */
      if (rgbLitLevel(st) > 2) return true;                              /* 掌控板彩灯亮着 */
    }
    var f = st && st.devices.fan;
    return !!(f && f.on);   // 兜底：默认跟随风扇开关（也可由开关积木/点击控制）
  }
  /* 台灯光晕强度（开灯时带呼吸动画） */
  function lampGlow(st) {
    if (!lampOn(st)) return 0;
    var t = (st && st._animT) || 0;
    return 0.72 + 0.28 * Math.sin(t * 2.6);
  }

  function pumpOn(st) { var p = st && st.devices.pump; return !!(p && p.on); }

  /* ============================================================
   * 预置情景：一键布置常见教学场景
   * ============================================================ */
  var SCENES = {
    study: {
      name: '书房学习桌',
      items: [
        { k: 'desk', x: 250, y: 400 }, { k: 'lamp', x: 268, y: 292 },
        { k: 'books', x: 372, y: 372 }, { k: 'pot', x: 460, y: 318 },
        { k: 'clock', x: 178, y: 340 }, { k: 'plant', x: 540, y: 322 },
        { k: 'window', x: 60, y: 70 }
      ]
    },
    living: {
      name: '客厅生活角',
      items: [
        { k: 'desk', x: 250, y: 400 }, { k: 'switch', x: 150, y: 250 },
        { k: 'fan', x: 200, y: 290 }, { k: 'humidifier', x: 330, y: 300 },
        { k: 'sofa', x: 460, y: 330 }, { k: 'window', x: 60, y: 70 }
      ]
    },
    kitchen: {
      name: '厨房安全',
      items: [
        { k: 'counter', x: 240, y: 400 }, { k: 'kettle', x: 270, y: 296 },
        { k: 'heater', x: 380, y: 336 }, { k: 'plant', x: 470, y: 322 },
        { k: 'window', x: 60, y: 70 }
      ]
    },
    garden: {
      name: '阳台花园',
      items: [
        { k: 'desk', x: 250, y: 400 }, { k: 'pot', x: 280, y: 318 },
        { k: 'pot', x: 390, y: 322 }, { k: 'plant', x: 480, y: 318 },
        { k: 'window', x: 60, y: 70 }, { k: 'humidifier', x: 180, y: 300 }
      ]
    }
  };

  /* 补充两个元素定义（sofa / counter），保持与库风格一致 */
  LIB.sofa = {
    name: '沙发', w: 150, h: 96, cat: '生活物品',
    build: function () {
      var s = shadow(75, 92, 62, 8);
      s += rr(0, 26, 150, 46, 10, '#5f7f9c', ' stroke="#4a667f" stroke-width="1.5"');
      s += rr(8, 4, 134, 34, 10, '#6d8fac');
      s += rr(8, 40, 60, 26, 6, '#7fa0ba');
      s += rr(82, 40, 60, 26, 6, '#7fa0ba');
      s += rr(0, 62, 16, 30, 6, '#4a667f');
      s += rr(134, 62, 16, 30, 6, '#4a667f');
      return s;
    },
    label: function () { return '沙发'; }
  };
  LIB.counter = {
    name: '厨房台面', w: 240, h: 92, cat: '场景',
    build: function () {
      var s = rr(0, 10, 240, 16, 4, '#d7dde3', ' stroke="#b6bfc7" stroke-width="1.5"');
      s += rr(6, 26, 10, 62, 3, '#c2cbd3');
      s += rr(224, 26, 10, 62, 3, '#c2cbd3');
      s += rr(16, 14, 208, 5, 2, '#eef2f6', ' opacity=".6"');
      return s;
    },
    label: function () { return '台面'; }
  };

  /* ============================================================
   * 交通情景元素
   * ============================================================ */

  /* 红绿灯：三灯竖排，当前灯由 sceneFlags.light 决定（'r'|'y'|'g'） */
  LIB.trafficLight = {
    name: '红绿灯', w: 64, h: 168, cat: '交通', dynamic: true, state: 'r',
    build: function (st) {
      var mode = (st && st.sceneFlags && st.sceneFlags.light) || 'r';
      var s = shadow(32, 164, 18, 5);
      /* 灯杆 */
      s += rr(28, 20, 8, 144, 3, '#5a6672');
      s += rr(20, 160, 24, 8, 3, '#3f4a56');
      /* 灯箱 */
      s += rr(8, 6, 48, 96, 8, '#23272d', ' stroke="#12151a" stroke-width="2"');
      var lights = [['r', 26, '#ff4d4d'], ['y', 48, '#ffd24a'], ['g', 70, '#4ade80']];
      lights.forEach(function (L) {
        var on = mode === L[0];
        /* 未点亮的灯也画出来（暗色） */
        s += '<circle cx="32" cy="' + L[1] + '" r="14" fill="' + (on ? L[2] : '#2c3238') + '"/>';
        if (on) {
          s += '<circle cx="32" cy="' + L[1] + '" r="19" fill="' + L[2] + '" opacity=".28"/>';
          s += '<circle cx="32" cy="' + L[1] + '" r="14" fill="none" stroke="#fff" stroke-width="1.4" opacity=".55"/>';
        }
      });
      /* 行人小图标 */
      s += '<g opacity=".9"><circle cx="32" cy="122" r="5" fill="' +
        (mode === 'r' ? '#ffd24a' : '#6b7680') + '"/>' +
        '<path d="M32,128 v14 M32,134 l-7,-4 M32,134 l7,-4 M32,142 l-6,10 M32,142 l6,10" stroke="' +
        (mode === 'r' ? '#ffd24a' : '#6b7680') + '" stroke-width="3" stroke-linecap="round" fill="none"/></g>';
      return s;
    },
    label: function (st) {
      var m = (st && st.sceneFlags && st.sceneFlags.light) || 'r';
      return '红绿灯·' + ({ r: '红灯', y: '黄灯', g: '绿灯' })[m];
    },
    clickable: true
  };

  /* 斑马线 */
  LIB.crosswalk = {
    name: '斑马线', w: 220, h: 76, cat: '交通',
    build: function () {
      var s = rr(0, 8, 220, 60, 4, '#5f6b78');
      for (var i = 0; i < 7; i++) {
        s += '<rect x="' + (8 + i * 30) + '" y="12" width="18" height="52" rx="2" fill="#f4f6f8" opacity=".9"/>';
      }
      return s;
    },
    label: function () { return '斑马线'; }
  };

  /* 横向斑马线（第二十一轮）：条纹垂直于马路，供行人上下通过 */
  LIB.crosswalkV = {
    name: '斑马线(横)', w: 84, h: 230, cat: '交通',
    build: function () {
      var s = rr(4, 0, 76, 230, 4, '#5f6b78');
      for (var i = 0; i < 8; i++) {
        s += '<rect x="12" y="' + (8 + i * 28) + '" width="60" height="16" rx="2" fill="#f4f6f8" opacity=".92"/>';
      }
      /* 上下人行横道线 */
      s += '<rect x="6" y="0" width="4" height="230" fill="#e8ecf0" opacity=".5"/>';
      s += '<rect x="74" y="0" width="4" height="230" fill="#e8ecf0" opacity=".5"/>';
      return s;
    },
    label: function () { return '斑马线'; }
  };

  /* 道路（带车道虚线） */
  LIB.road = {
    name: '马路', w: 640, h: 150, cat: '交通',
    build: function () {
      var s = rr(0, 0, 640, 150, 4, '#4a5560');
      s += '<rect x="0" y="6" width="640" height="4" rx="2" fill="#e8ecf0" opacity=".5"/>';
      s += '<rect x="0" y="140" width="640" height="4" rx="2" fill="#e8ecf0" opacity=".5"/>';
      /* 中央双黄线 */
      s += '<rect x="0" y="71" width="640" height="3" fill="#f0b429"/>';
      s += '<rect x="0" y="77" width="640" height="3" fill="#f0b429"/>';
      /* 车道虚线 */
      for (var i = 0; i < 12; i++) {
        s += '<rect x="' + (14 + i * 54) + '" y="73.5" width="28" height="4" rx="2" fill="#e8ecf0" opacity=".75"/>';
      }
      return s;
    },
    label: function () { return '马路'; }
  };

  /* 停止线 */
  LIB.stopLine = {
    name: '停止线', w: 180, h: 26, cat: '交通',
    build: function () {
      return rr(0, 4, 180, 18, 3, '#f4f6f8', ' opacity=".92"');
    },
    label: function () { return '停止线'; }
  };

  /* 限速牌 */
  LIB.speedLimit = {
    name: '限速牌', w: 58, h: 82, cat: '交通',
    build: function () {
      var s = shadow(29, 78, 14, 4);
      s += rr(26, 30, 6, 48, 3, '#8a939e');
      s += '<circle cx="29" cy="26" r="24" fill="#f4f6f8" stroke="#e0483e" stroke-width="6"/>';
      s += '<text x="29" y="35" font-size="20" font-weight="700" text-anchor="middle" fill="#1f2429">30</text>';
      return s;
    },
    label: function () { return '限速30'; }
  };

  /* 行人（过马路） */
  LIB.pedestrian = {
    name: '行人', w: 48, h: 96, cat: '交通',
    build: function (st) {
      /* 走路动画相位由 tick 更新，这里画基础形态 */
      var c = '#ff8a3d';
      var s = shadow(24, 92, 12, 4);
      s += '<circle cx="24" cy="16" r="9" fill="#ffd9b3"/>';
      s += '<path d="M24,26 v26" stroke="' + c + '" stroke-width="9" stroke-linecap="round"/>';
      s += '<path d="M14,34 l10,4 l10,-4" stroke="' + c + '" stroke-width="7" stroke-linecap="round" fill="none"/>';
      s += '<path d="M24,52 l-9,22 M24,52 l9,22" stroke="#4a5560" stroke-width="8" stroke-linecap="round"/>';
      s += '<rect x="19" y="28" width="10" height="14" rx="2" fill="#fff" opacity=".25"/>';
      return s;
    },
    tick: function (g, st, t) {
      /* 上下轻微起伏，模拟行走 */
      var inner = g.querySelector('.stage-item-body');
      if (!inner) return;
      var bob = Math.sin(t * 5) * 1.6;
      inner.setAttribute('transform', 'translate(0,' + (-bob).toFixed(2) + ')');
    },
    label: function () { return '行人'; }
  };

  /* 车辆（第二十一轮：路口被超 / 被让行的前车，可从上方开过） */
  LIB.vehicle = {
    name: '车辆', w: 62, h: 34, cat: '交通',
    build: function () {
      var s = shadow(31, 30, 22, 5);
      /* 车身（车头朝右） */
      s += '<rect x="2" y="8" width="58" height="20" rx="6" fill="#c8443c"/>';
      s += '<path d="M14,8 q6,-7 18,-7 q12,0 18,7z" fill="#e05a52"/>';
      s += '<rect x="20" y="3" width="12" height="6" rx="2" fill="#cfe4f2"/>';
      s += '<rect x="35" y="3" width="12" height="6" rx="2" fill="#cfe4f2"/>';
      s += '<rect x="54" y="11" width="6" height="5" rx="1.5" fill="#fff3b0"/>';
      /* 车轮 */
      s += '<circle cx="15" cy="28" r="6" fill="#1d2024"/><circle cx="15" cy="28" r="2.4" fill="#8a929b"/>';
      s += '<circle cx="47" cy="28" r="6" fill="#1d2024"/><circle cx="47" cy="28" r="2.4" fill="#8a929b"/>';
      return s;
    },
    tick: function (g, st, t) {
      /* 被探测时轻微闪动 */
      var inner = g.querySelector('.stage-item-body');
      if (!inner) return;
      var on = st && st.sceneFlags && st.sceneFlags.honk;
      inner.setAttribute('opacity', on ? (0.75 + 0.25 * Math.abs(Math.sin(t * 6))).toFixed(2) : '1');
    },
    label: function () { return '车辆'; }
  };

  /* 停车标志 */
  LIB.stopSign = {
    name: '停车牌', w: 56, h: 80, cat: '交通',
    build: function () {
      var s = shadow(28, 76, 13, 4);
      s += rr(25, 30, 6, 46, 3, '#8a939e');
      s += '<path d="M28,4 L52,26 L28,48 L4,26 Z" fill="#e0483e" stroke="#a32e26" stroke-width="2"/>';
      s += '<text x="28" y="32" font-size="17" font-weight="700" text-anchor="middle" fill="#fff">停</text>';
      return s;
    },
    label: function () { return '停车牌'; }
  };

  /* 树（路边绿化） */
  LIB.streetTree = {
    name: '路树', w: 84, h: 116, cat: '交通',
    build: function () {
      var s = shadow(42, 112, 20, 5);
      s += rr(37, 52, 10, 60, 3, '#8a6f4a');
      s += '<circle cx="42" cy="38" r="26" fill="#4f9e52"/>';
      s += '<circle cx="26" cy="48" r="18" fill="#5fae60"/>';
      s += '<circle cx="58" cy="48" r="18" fill="#5fae60"/>';
      s += '<circle cx="42" cy="30" r="17" fill="#68bd68" opacity=".85"/>';
      return s;
    },
    label: function () { return '路树'; }
  };

  /* 交通情景注册到 SCENES */
  SCENES.traffic = {
    name: '交通路口',
    /* items 在文件末尾统一补齐小车 / 车辆 / 横向斑马线后赋值 */
    items: [],
    /* 该情景建议联动的小车/超声波等设备 */
    devices: ['car', 'ultrasonic']
  };

  SCENES.parking = {
    name: '停车位',
    items: [
      { k: 'road', x: 70, y: 320 }, { k: 'stopSign', x: 110, y: 296 },
      { k: 'streetTree', x: 560, y: 190 }, { k: 'speedLimit', x: 640, y: 296 },
      { k: 'crosswalk', x: 380, y: 318 }
    ],
    devices: ['car', 'ultrasonic']
  };

  /* ============================================================
   * 元素缩略图（素材库用）：用元素自身的 build() 渲染成小图标
   * ============================================================ */
  /* 生成缩略图。
     要点：不要额外加 scale/translate —— viewBox 已按元素真实宽高比设置，
     再叠加变换会与 preserveAspectRatio 重复缩放，导致宽扁元素（马路、赛道黑线、
     停止线等）严重偏移甚至溢出。只需给出合适的 viewBox 让它自适应居中即可。
     pad 为留白，避免描边/阴影被裁掉。 */
  function makeThumb(k) {
    return function () {
      var def = LIB[k];
      if (!def) return '';
      var inner = '';
      try { inner = def.build(null) || ''; } catch (e) { inner = ''; }
      var w = Math.max(def.w, 1), h = Math.max(def.h, 1);
      /* 留白取短边的 6%，最小 2、最大 14，兼顾描边与紧凑度 */
      var pad = Math.max(2, Math.min(14, Math.min(w, h) * 0.06));
      return '<svg viewBox="' + (-pad).toFixed(1) + ' ' + (-pad).toFixed(1) + ' ' +
        (w + pad * 2).toFixed(1) + ' ' + (h + pad * 2).toFixed(1) + '" ' +
        'width="100%" height="100%" preserveAspectRatio="xMidYMid meet" ' +
        'style="display:block;overflow:visible">' + inner + '</svg>';
    };
  }
  /* 为每个元素生成 thumb（惰性，渲染时若无则跳过） */
  function ensureThumbs() {
    Object.keys(LIB).forEach(function (k) {
      if (!LIB[k].thumb) LIB[k].thumb = makeThumb(k);
    });
  }

  /* ============================================================
   * DFRobot 新增硬件对应的舞台元素
   * ============================================================ */

  /* 赛道黑线（循迹小车 / 巡线小车用） */
  LIB.trackLine = {
    name: '赛道黑线', w: 560, h: 40, cat: '交通',
    build: function () {
      var s = '';
      for (var i = 0; i < 14; i++) {
        s += '<rect x="' + (i * 42) + '" y="14" width="30" height="12" rx="2" fill="#2b2f36"/>';
      }
      s += '<rect x="0" y="18" width="560" height="4" fill="#3a414c" opacity=".5"/>';
      return s;
    },
    label: function () { return '赛道'; }
  };

  /* 循迹器（5 路探针）：第十四轮保留，随巡线传感器设备数据点亮 */
  LIB.trackerPad = {
    name: '循迹器', w: 66, h: 26, cat: '交通', dynamic: true,
    build: function (st) {
      var trk = st && st.devices && st.devices.tracker;
      var ch = trk && trk.ch;
      var s = '<rect x="0" y="4" width="66" height="18" rx="3" fill="#1f242a"/>';
      ['L2', 'L1', 'C', 'R1', 'R2'].forEach(function (n, i) {
        var on = ch ? ch[n] : (n === 'C' ? 1 : 0);
        s += '<rect x="' + (4 + i * 12) + '" y="8" width="9" height="10" rx="1.5" fill="' +
          (on ? '#4ade80' : '#2b3038') + '"/>';
      });
      return s;
    },
    label: function (st) {
      var trk = st && st.devices && st.devices.tracker;
      if (!trk || !trk.ch) return '循迹器';
      var c = trk.ch;
      return '循迹 ' + (c.C ? '居中' : (c.L1 || c.L2 ? '偏左' : (c.R1 || c.R2 ? '偏右' : '离线')));
    },
    dynamic: true
  };

  /* 继电器控制的家用电器 */
  LIB.appliance = {
    name: '家用电器', w: 110, h: 120, cat: '生活物品', dynamic: true,
    build: function (st) {
      var r = st && st.devices.relay;
      var on = r && r.on;
      var s = shadow(55, 116, 40, 7);
      s += '<rect x="14" y="30" width="82" height="80" rx="8" fill="' +
        (on ? '#f4f6f8' : '#d8dde2') + '" stroke="#a8b2bd" stroke-width="1.6"/>';
      s += '<rect x="24" y="42" width="62" height="26" rx="4" fill="#2b3138"/>';
      s += '<text x="55" y="60" font-size="13" font-weight="700" text-anchor="middle" fill="' +
        (on ? '#7dff9a' : '#5a636e') + '">' + (on ? 'ON' : 'OFF') + '</text>';
      s += '<circle cx="34" cy="84" r="5" fill="' + (on ? '#4ade80' : '#3a414c') + '"/>';
      if (on) s += '<circle cx="34" cy="84" rx="9" fill="#4ade80" opacity=".3"/>';
      s += '<rect x="42" y="108" width="10" height="8" fill="#8a939e"/>' +
        '<rect x="58" y="108" width="10" height="8" fill="#8a939e"/>';
      return s;
    },
    label: function (st) {
      var r = st && st.devices.relay;
      return r && r.on ? '电器·通电' : '电器·断电';
    },
    dynamic: true
  };

  /* RGB 灯带 */
  /* RGB 灯带：加长到 16 颗灯珠，可按程序逐颗点亮 */
  LIB.rgbStrip = {
    name: 'RGB 灯带', w: 460, h: 46, cat: '生活物品', dynamic: true,
    build: function (st) {
      var d = (st && st.devices.rgbStrip) || { r: 0, g: 0, b: 0 };
      /* leds 为每颗灯的 {on, r, g, b}；未设置时整条同色 */
      var leds = d.leds && d.leds.length ? d.leds : null;
      var N = 16, gap = 27, x0 = 8;
      var html = '<rect x="0" y="8" width="' + (N * gap + 16) + '" height="26" rx="6" fill="#1a1d21"/>' +
        '<rect x="4" y="12" width="' + (N * gap + 8) + '" height="18" rx="4" fill="#25292e"/>';
      for (var i = 0; i < N; i++) {
        var col;
        if (leds) {
          var L = leds[i] || { on: 0, r: 0, g: 0, b: 0 };
          col = L.on ? 'rgb(' + L.r + ',' + L.g + ',' + L.b + ')' : '#2c3036';
        } else {
          col = (d.r + d.g + d.b > 0) ? 'rgb(' + d.r + ',' + d.g + ',' + d.b + ')' : '#2c3036';
        }
        var lx = x0 + i * gap;
        html += '<rect x="' + lx + '" y="14" width="20" height="14" rx="3.5" fill="' + col + '"/>';
        /* 点亮的灯带光晕 */
        if (col.indexOf('rgb') === 0) {
          html += '<rect x="' + (lx - 3) + '" y="11" width="26" height="20" rx="6" fill="' + col +
            '" opacity=".22"/>';
        }
      }
      /* 两端接头 */
      html += '<rect x="0" y="16" width="8" height="10" rx="2" fill="#3fae5a"/>' +
        '<rect x="' + (N * gap + 16) + '" y="16" width="8" height="10" rx="2" fill="#c94a4a"/>';
      return html;
    },
    label: function (st) {
      var dev = (st && st.devices) || {};
      var d = dev.rgbStrip;
      if (!d) return '灯带（未连接）';
      if (d.leds && d.leds.length) {
        var on = d.leds.filter(function (l) { return l.on; }).length;
        return '灯带 ' + on + '/' + d.leds.length + ' 颗亮';
      }
      return '灯带 ' + (d.r || 0) + ',' + (d.g || 0) + ',' + (d.b || 0);
    },
    dynamic: true
  };

  /* 数字功率计 */
  LIB.powerMeterBox = {
    name: '功率计', w: 104, h: 78, cat: '生活物品', dynamic: true,
    build: function (st) {
      var p = st && st.devices.powerMeter;
      var v = p ? p.v : 0, a = p ? p.a : 0, w = p ? p.w : 0;
      var s = shadow(52, 74, 36, 6);
      s += '<rect x="4" y="6" width="96" height="64" rx="7" fill="#1b3a52"/>';
      s += '<rect x="12" y="14" width="80" height="30" rx="3" fill="#0b3d1f"/>';
      s += '<text x="52" y="28" font-size="11" text-anchor="middle" fill="#8cff9e" font-family="monospace">' +
        v.toFixed(1) + 'V</text>';
      s += '<text x="52" y="40" font-size="9" text-anchor="middle" fill="#6fe89a" font-family="monospace">' +
        a.toFixed(2) + 'A / ' + w.toFixed(2) + 'W</text>';
      s += '<rect x="12" y="50" width="80" height="10" rx="5" fill="#0a2e18"/>';
      s += '<rect x="14" y="52" width="' + Math.round(Math.min(1, v / 5) * 76) + '" height="6" rx="3" fill="#3fe07a"/>';
      return s;
    },
    label: function (st) {
      var p = st && st.devices.powerMeter;
      return p ? p.v.toFixed(1) + 'V ' + p.w.toFixed(2) + 'W' : '功率计';
    },
    dynamic: true
  };

  /* ============================================================
   * 校园场景元素
   * ============================================================ */

  /* 教学楼（多层，带窗户与旗杆） */
  LIB.schoolBuilding = {
    name: '教学楼', w: 260, h: 210, cat: '校园',
    build: function (st) {
      /* 亮灯数量跟随环境光线 */
      var lv = st ? Math.min(1, (st.light || 0) / 4095) : 0.6;
      var night = lv < 0.3;
      var s = shadow(130, 206, 120, 8);
      /* 主体 */
      s += '<rect x="10" y="40" width="240" height="166" rx="4" fill="#e6ddd0" stroke="#c4b8a6" stroke-width="2"/>';
      /* 屋顶 */
      s += '<path d="M4,42 L130,6 L256,42 Z" fill="#b8543f"/>';
      /* 窗户 */
      for (var r = 0; r < 3; r++) {
        for (var c = 0; c < 6; c++) {
          var lit = night && ((r * 6 + c) % 3 !== 0);
          s += '<rect x="' + (26 + c * 36) + '" y="' + (56 + r * 44) + '" width="24" height="28" rx="2" ' +
            'fill="' + (lit ? '#ffd76a' : '#8fa8bd') + '"' + (lit ? ' opacity=".95"' : '') + '/>';
          if (lit) s += '<rect x="' + (26 + c * 36) + '" y="' + (56 + r * 44) + '" width="24" height="28" rx="2" fill="none" stroke="#fff8d0" stroke-width="1.2" opacity=".6"/>';
        }
      }
      /* 门 */
      s += '<rect x="104" y="166" width="52" height="40" rx="3" fill="#7d5a3c"/>';
      s += '<circle cx="148" cy="188" r="2.6" fill="#e8c66a"/>';
      /* 校牌 */
      s += '<rect x="92" y="46" width="76" height="18" rx="3" fill="#b8543f"/>';
      s += '<text x="130" y="59" font-size="11" font-weight="700" text-anchor="middle" fill="#fff">教学楼</text>';
      return s;
    },
    label: function (st) {
      var lv = st ? Math.min(1, (st.light || 0) / 4095) : 0.6;
      return lv < 0.3 ? '教学楼·灯亮' : '教学楼';
    },
    dynamic: true
  };

  /* 旗杆 + 国旗 */
  LIB.flagpole = {
    name: '旗杆', w: 76, h: 200, cat: '校园',
    build: function (st) {
      var t = (Date.now ? 0 : 0);
      var s = shadow(38, 196, 16, 4);
      /* 基座 */
      s += '<path d="M18,176 L58,176 L54,196 L22,196 Z" fill="#c9c2b4" stroke="#a9a294" stroke-width="1.2"/>';
      /* 杆 */
      s += '<rect x="35" y="20" width="6" height="158" rx="3" fill="#c0c6cc"/>';
      s += '<rect x="35" y="20" width="2.4" height="158" fill="#e2e7eb"/>';
      /* 顶球 */
      s += '<circle cx="38" cy="17" r="6" fill="#f0b429" stroke="#c9901a" stroke-width="1.2"/>';
      /* 国旗（红色 + 星） */
      s += '<path class="flag-cloth" d="M41,28 q16,5 31,0 v26 q-15,5 -31,0 Z" fill="#de2910" stroke="#b81e0c" stroke-width="1"/>';
      s += '<path d="M48,36 l2.2,4.6 5,.7 -3.6,3.5 .9,5 -4.5,-2.4 -4.5,2.4 .9,-5 -3.6,-3.5 5,-.7 Z" fill="#ffde00" transform="scale(.72) translate(19,17)"/>';
      return s;
    },
    tick: function (g, st, t) {
      var f = g.querySelector('.flag-cloth');
      if (!f) return;
      /* 轻微飘动 */
      var w = Math.sin(t * 2.2) * 1.6;
      f.setAttribute('transform', 'translate(' + w.toFixed(2) + ',0)');
    },
    label: function () { return '旗杆'; }
  };

  /* 操场跑道 */
  LIB.playground = {
    name: '操场', w: 320, h: 200, cat: '校园',
    build: function () {
      var s = '<ellipse cx="160" cy="100" rx="156" ry="94" fill="#7ab86a"/>';
      /* 红色跑道 */
      s += '<ellipse cx="160" cy="100" rx="140" ry="80" fill="none" stroke="#cf6b52" stroke-width="14"/>';
      s += '<ellipse cx="160" cy="100" rx="122" ry="66" fill="none" stroke="#cf6b52" stroke-width="3" opacity=".8"/>';
      /* 内场草坪 + 足球门 */
      s += '<ellipse cx="160" cy="100" rx="112" ry="58" fill="#8cc97a"/>';
      s += '<rect x="96" y="76" width="16" height="48" fill="none" stroke="#fff" stroke-width="2.4"/>';
      s += '<rect x="208" y="76" width="16" height="48" fill="none" stroke="#fff" stroke-width="2.4"/>';
      s += '<rect x="112" y="92" width="96" height="16" fill="none" stroke="#fff" stroke-width="2"/>';
      return s;
    },
    label: function () { return '操场'; }
  };

  /* 篮球架 */
  LIB.basketballHoop = {
    name: '篮球架', w: 120, h: 170, cat: '校园',
    build: function () {
      var s = shadow(60, 166, 34, 6);
      /* 立柱 */
      s += '<rect x="52" y="60" width="12" height="104" rx="4" fill="#8a939e"/>';
      /* 底座 */
      s += '<path d="M34,156 L82,156 L88,168 L28,168 Z" fill="#6b7680"/>';
      /* 篮板 */
      s += '<rect x="58" y="10" width="54" height="42" rx="3" fill="#f0f4f8" stroke="#c4ccd4" stroke-width="1.5" opacity=".9"/>';
      s += '<rect x="74" y="22" width="24" height="18" rx="2" fill="none" stroke="#e0552c" stroke-width="2.4"/>';
      /* 篮圈 + 网 */
      s += '<ellipse cx="86" cy="44" rx="15" ry="5" fill="none" stroke="#e0552c" stroke-width="3"/>';
      s += '<path d="M72,46 l4,16 M86,48 l0,16 M100,46 l-4,16" stroke="#fff" stroke-width="1.6" opacity=".85" fill="none"/>';
      return s;
    },
    label: function () { return '篮球架'; }
  };

  /* 校园路灯 */
  LIB.streetLamp = {
    name: '校园灯', w: 66, h: 190, cat: '校园',
    build: function (st) {
      var lv = st ? Math.min(1, (st.light || 0) / 4095) : 0.6;
      var on = lv < 0.35;
      var s = shadow(33, 186, 16, 4);
      s += '<rect x="29" y="16" width="8" height="168" rx="3" fill="#7d868f"/>';
      s += '<ellipse cx="33" cy="184" rx="20" ry="6" fill="#5f686f"/>';
      /* 灯臂 */
      s += '<path d="M33,24 q0,-10 12,-10" fill="none" stroke="#7d868f" stroke-width="7" stroke-linecap="round"/>';
      /* 灯头 */
      s += '<path d="M32,8 h30 l-5,14 h-20 Z" fill="#98a2ab"/>';
      s += '<circle cx="47" cy="22" r="9" fill="' + (on ? '#ffe9a0' : '#c8d0d8') + '"/>';
      if (on) s += '<path d="M47,22 L47,186 L130,186 L130,22 Z" fill="#ffe9a0" opacity=".08"/>';
      return s;
    },
    label: function (st) {
      var lv = st ? Math.min(1, (st.light || 0) / 4095) : 0.6;
      return lv < 0.35 ? '校园灯·亮' : '校园灯';
    },
    dynamic: true
  };

  /* 花坛 */
  LIB.flowerBed = {
    name: '花坛', w: 140, h: 88, cat: '校园',
    build: function () {
      var s = '<ellipse cx="70" cy="78" rx="64" ry="8" fill="rgba(30,50,80,.14)"/>';
      s += '<ellipse cx="70" cy="56" rx="66" ry="30" fill="#c7b299"/>';
      s += '<ellipse cx="70" cy="52" rx="58" ry="24" fill="#8a6f4a"/>';
      /* 花朵 */
      var cols = ['#e8607a', '#f0b429', '#c86ad0', '#fff'];
      for (var i = 0; i < 7; i++) {
        var fx = 26 + i * 14, fy = 46 + (i % 3) * 6;
        var c = cols[i % cols.length];
        s += '<circle cx="' + fx + '" cy="' + fy + '" r="5" fill="' + c + '"/>' +
          '<circle cx="' + fx + '" cy="' + fy + '" r="2" fill="#ffe9a0"/>';
        s += '<path d="M' + fx + ',' + (fy + 5) + ' v6" stroke="#4f8f4a" stroke-width="1.6"/>';
      }
      /* 绿草 */
      s += '<path d="M14,58 q4,-10 8,0 M100,56 q4,-11 8,0 M60,62 q4,-9 8,0" stroke="#5fae55" stroke-width="2" fill="none" stroke-linecap="round"/>';
      return s;
    },
    label: function () { return '花坛'; }
  };

  /* 校门 */
  LIB.schoolGate = {
    name: '校门', w: 300, h: 170, cat: '校园',
    build: function () {
      var s = shadow(150, 166, 130, 8);
      /* 门柱 */
      s += '<rect x="16" y="52" width="30" height="110" rx="4" fill="#c2b39c" stroke="#a4977f" stroke-width="1.5"/>';
      s += '<rect x="254" y="52" width="30" height="110" rx="4" fill="#c2b39c" stroke="#a4977f" stroke-width="1.5"/>';
      /* 门楣 */
      s += '<rect x="10" y="30" width="280" height="26" rx="5" fill="#b8543f"/>';
      s += '<text x="150" y="49" font-size="15" font-weight="700" text-anchor="middle" fill="#ffe9a0">实验小学</text>';
      /* 栅栏门 */
      for (var i = 0; i < 12; i++) {
        s += '<rect x="' + (52 + i * 16) + '" y="64" width="5" height="98" rx="2" fill="#9aa3ad"/>';
      }
      s += '<rect x="46" y="58" width="200" height="7" rx="3" fill="#b3bcc6"/>';
      s += '<rect x="46" y="110" width="200" height="7" rx="3" fill="#b3bcc6"/>';
      return s;
    },
    label: function () { return '校门'; }
  };

  /* 板报栏 */
  LIB.bulletinBoard = {
    name: '板报栏', w: 130, h: 120, cat: '校园',
    build: function () {
      var s = shadow(65, 116, 50, 6);
      s += '<rect x="10" y="72" width="8" height="42" rx="3" fill="#8a939e"/>';
      s += '<rect x="112" y="72" width="8" height="42" rx="3" fill="#8a939e"/>';
      s += '<rect x="4" y="8" width="122" height="72" rx="5" fill="#2f6ea8" stroke="#255a8c" stroke-width="2"/>';
      /* 内框 + 画报 */
      s += '<rect x="14" y="18" width="102" height="52" rx="3" fill="#fdfbf5"/>';
      s += '<rect x="20" y="24" width="42" height="38" rx="2" fill="#7ab86a"/>';
      s += '<circle cx="34" cy="36" r="6" fill="#ffe27a"/>';
      s += '<rect x="68" y="24" width="42" height="6" rx="3" fill="#c4ccd4"/>';
      s += '<rect x="68" y="36" width="34" height="5" rx="2.5" fill="#d8dee4"/>';
      s += '<rect x="68" y="47" width="38" height="5" rx="2.5" fill="#d8dee4"/>';
      return s;
    },
    label: function () { return '板报栏'; }
  };

  /* 长椅 */
  LIB.bench = {
    name: '长椅', w: 140, h: 78, cat: '校园',
    build: function () {
      var s = shadow(70, 74, 56, 6);
      /* 椅腿 */
      s += '<rect x="18" y="50" width="8" height="24" rx="3" fill="#6b7680"/>';
      s += '<rect x="114" y="50" width="8" height="24" rx="3" fill="#6b7680"/>';
      /* 座面 */
      s += '<rect x="8" y="40" width="124" height="14" rx="4" fill="#c08a4a" stroke="#9a6c34" stroke-width="1.2"/>';
      /* 靠背 */
      s += '<rect x="12" y="16" width="116" height="12" rx="4" fill="#c08a4a" stroke="#9a6c34" stroke-width="1.2"/>';
      s += '<rect x="16" y="28" width="8" height="14" fill="#8a939e"/>';
      s += '<rect x="116" y="28" width="8" height="14" fill="#8a939e"/>';
      return s;
    },
    label: function () { return '长椅'; }
  };

  /* 垃圾桶 */
  LIB.trashBin = {
    name: '垃圾桶', w: 62, h: 92, cat: '校园',
    build: function () {
      var s = shadow(31, 88, 20, 5);
      s += '<path d="M14,30 L48,30 L43,86 Q31,90 19,86 Z" fill="#4f8f4a" stroke="#3d7039" stroke-width="1.4"/>';
      s += '<rect x="11" y="22" width="40" height="10" rx="4" fill="#5fae55" stroke="#3d7039" stroke-width="1.2"/>';
      s += '<rect x="24" y="6" width="14" height="16" rx="3" fill="#3d7039"/>';
      /* 回收标识 */
      s += '<circle cx="31" cy="56" r="9" fill="#eef4ee" opacity=".9"/>';
      s += '<path d="M27,56 l3,3 l6,-6" stroke="#4f8f4a" stroke-width="2.2" fill="none" stroke-linecap="round"/>';
      return s;
    },
    label: function () { return '垃圾桶'; }
  };

  /* 智能家居情景（演示新增硬件：继电器 / 灯带 / 功率计 / 灯光） */
  SCENES.smarthome = {
    name: '智能家居',
    items: [
      { k: 'counter', x: 250, y: 400 },
      { k: 'appliance', x: 270, y: 292 },
      { k: 'rgbStrip', x: 330, y: 330 },
      { k: 'powerMeterBox', x: 450, y: 330 },
      { k: 'lamp', x: 520, y: 286 },
      { k: 'pot', x: 200, y: 320 },
      { k: 'switch', x: 150, y: 250 },
      { k: 'deskLamp', x: 620, y: 300 }
    ],
    devices: ['relay', 'rgbStrip', 'powerMeter', 'ledModule', 'dht']
  };

  /* 循迹小车情景（第十四轮保留：赛道 + 循迹器 + 小车） */
  SCENES.tracing = {
    name: '循迹小车',
    items: [
      { k: 'road', x: 90, y: 260 },
      { k: 'trackLine', x: 110, y: 320 },
      { k: 'car', x: 200, y: 336 },
      { k: 'trackerPad', x: 158, y: 336 },
      { k: 'trafficLight', x: 680, y: 130 },
      { k: 'stopSign', x: 620, y: 250 }
    ],
    devices: ['tracker', 'car', 'motor', 'ultrasonic']
  };

  /* ============================================================
   * 硬件联动元素：虚拟仿真添加硬件后，舞台上出现对应元素
   * ============================================================ */

  /* 温湿度传感器（DHT11） */
  LIB.dhtSensor = {
    name: '温湿度传感器', w: 74, h: 92, cat: '生活物品', dynamic: true,
    build: function (st) {
      var dev = (st && st.devices) || {};
      var d = dev.dht || {};
      var t = (d.t != null ? d.t : 26);
      var h = (d.h != null ? d.h : 55);
      var s = shadow(37, 88, 24, 5);
      s += '<rect x="16" y="8" width="42" height="52" rx="4" fill="#3f4a58"/>';
      /* 格栅 */
      for (var r = 0; r < 4; r++) {
        for (var c = 0; c < 5; c++) {
          s += '<rect x="' + (19 + c * 7) + '" y="' + (11 + r * 5) + '" width="5" height="3" ' +
            'fill="#2b323b"/>';
        }
      }
      s += '<rect x="22" y="62" width="30" height="22" rx="3" fill="#0b1410"/>' +
        '<text x="37" y="70" font-size="7" text-anchor="middle" fill="#7dff9a" font-family="monospace">' +
        Math.round(t) + '°</text>' +
        '<text x="37" y="80" font-size="7" text-anchor="middle" fill="#7dff9a" font-family="monospace">' +
        Math.round(h) + '%</text>';
      s += '<rect x="26" y="86" width="5" height="4" fill="#c9a23c"/>' +
        '<rect x="34" y="86" width="5" height="4" fill="#c9a23c"/>' +
        '<rect x="42" y="86" width="5" height="4" fill="#c9a23c"/>';
      return s;
    },
    label: function (st) {
      var dev = (st && st.devices) || {};
      var d = dev.dht;
      if (!d) return '温湿度';
      var t = (d.t != null ? d.t : 26);
      var h = (d.h != null ? d.h : 55);
      return '温' + Math.round(t) + '° 湿' + Math.round(h) + '%';
    },
    dynamic: true
  };

  /* 超声波传感器（HC-SR04）：舞台模式下向正前方发射测距波束，
     实时显示到最近障碍物元素（行人/路树…）的距离 */
  LIB.ultraSensor = {
    name: '超声波传感器', w: 86, h: 58, cat: '生活物品', dynamic: true,
    build: function (st) {
      var u = (st && st.devices.ultrasonic) || { cm: 30 };
      var s = shadow(43, 54, 30, 4);
      s += '<rect x="4" y="14" width="78" height="30" rx="3" fill="#2f3740"/>';
      s += '<circle cx="20" cy="16" r="11" fill="#0d1014" stroke="#6b7480" stroke-width="2"/>' +
        '<circle cx="20" cy="16" r="5" fill="#1a1f25"/>';
      s += '<circle cx="66" cy="16" r="11" fill="#0d1014" stroke="#6b7480" stroke-width="2"/>' +
        '<circle cx="66" cy="16" r="5" fill="#1a1f25"/>';
      /* 超声波波纹：距离越近波纹越密 */
      var n = Math.max(1, Math.min(4, Math.round(40 / Math.max(4, u.cm))));
      for (var i = 0; i < n; i++) {
        var op = 0.55 - i * 0.12;
        s += '<path d="M78,12 q' + (5 + i * 4) + ',11 0,22" fill="none" ' +
          'stroke="#7ec8e3" stroke-width="1.6" opacity="' + op.toFixed(2) + '"/>';
      }
      /* 测距波束（舞台测距激活时）：命中→实线+红点；未命中→淡虚线到最大量程 */
      if (u._stage) {
        var len = Math.max(8, Math.min(400, (u.cm || 0) * 2));
        if (u._hit) {
          var near = u.cm < 30;
          var bc = near ? '#ff5d5d' : '#4ade80';
          s += '<line x1="82" y1="16" x2="' + (82 + len) + '" y2="16" stroke="' + bc +
            '" stroke-width="2.4" opacity=".8" stroke-linecap="round"/>';
          s += '<circle cx="' + (82 + len) + '" cy="16" r="4.5" fill="' + bc + '"/>' +
            '<circle cx="' + (82 + len) + '" cy="16" r="8" fill="' + bc + '" opacity=".28"/>';
        } else {
          s += '<line x1="82" y1="16" x2="' + (82 + len) + '" y2="16" stroke="#7ec8e3" ' +
            'stroke-width="2" opacity=".3" stroke-dasharray="7 6" stroke-linecap="round"/>';
        }
      }
      s += '<rect x="14" y="44" width="5" height="8" fill="#c9a23c"/>' +
        '<rect x="26" y="44" width="5" height="8" fill="#c9a23c"/>' +
        '<rect x="38" y="44" width="5" height="8" fill="#c9a23c"/>' +
        '<rect x="50" y="44" width="5" height="8" fill="#c9a23c"/>';
      return s;
    },
    label: function (st) {
      var u = st && st.devices.ultrasonic;
      if (!u) return '超声波';
      if (u._stage && u._hit && u._target) {
        return '距' + u._target + ' ' + Math.round(u.cm) + 'cm';
      }
      if (u._stage && !u._hit) return '前方无障碍';
      return '距离 ' + Math.round(u.cm) + ' cm';
    },
    dynamic: true
  };

  /* 红外避障传感器 */
  LIB.irObstacle = {
    name: '红外避障', w: 68, h: 54, cat: '生活物品', dynamic: true,
    build: function (st) {
      var ir = (st && st.devices.ir) || { obs: false };
      var hit = ir.obs;
      var s = shadow(34, 50, 24, 4);
      s += '<rect x="6" y="12" width="56" height="30" rx="3" fill="#23282e"/>';
      s += '<circle cx="20" cy="20" r="8" fill="#0d1014" stroke="#7d8794" stroke-width="1.6"/>' +
        '<circle cx="48" cy="20" r="8" fill="#0d1014" stroke="#7d8794" stroke-width="1.6"/>';
      /* 发射端发光 */
      s += '<circle cx="20" cy="20" r="3.4" fill="' + (hit ? '#ff4040' : '#5a2a2a') + '"/>';
      /* 接收端：检测到障碍时点亮 */
      s += '<circle cx="48" cy="20" r="3.4" fill="' + (hit ? '#4ade80' : '#2a3a2a') + '"/>';
      if (hit) {
        s += '<path d="M54,14 q8,6 0,12" fill="none" stroke="#4ade80" stroke-width="1.6" opacity=".7"/>';
      }
      s += '<rect x="16" y="42" width="5" height="7" fill="#c9a23c"/>' +
        '<rect x="28" y="42" width="5" height="7" fill="#c9a23c"/>' +
        '<rect x="40" y="42" width="5" height="7" fill="#c9a23c"/>';
      return s;
    },
    label: function (st) {
      var ir = st && st.devices.ir;
      return ir ? (ir.obs ? '检测到障碍' : '无障碍') : '红外避障';
    },
    dynamic: true
  };

  /* 水泵 */
  LIB.pump = {
    name: '水泵', w: 92, h: 78, cat: '生活物品', dynamic: true,
    build: function (st) {
      var p = (st && st.devices.pump) || { on: false };
      var s = shadow(46, 74, 30, 5);
      s += '<rect x="12" y="20" width="68" height="42" rx="6" fill="#2f9e8e"/>';
      s += '<circle cx="34" cy="41" r="14" fill="#1a7a6e"/>' +
        '<circle cx="34" cy="41" r="7" fill="#0f5a52"/>';
      /* 进出水口 */
      s += '<rect x="76" y="28" width="12" height="10" rx="2" fill="#0f3540"/>' +
        '<rect x="76" y="46" width="12" height="10" rx="2" fill="#0f3540"/>';
      /* 出水水流 */
      if (p.on) {
        s += '<rect x="80" y="30" width="6" height="26" fill="#4fc3f7" opacity=".55"/>';
        s += '<circle cx="86" cy="62" r="4" fill="#4fc3f7" opacity=".75"/>';
        s += '<circle cx="86" cy="72" r="2.6" fill="#4fc3f7" opacity=".55"/>';
      }
      s += '<circle cx="20" cy="32" r="3.4" fill="' + (p.on ? '#ff5d5d' : '#3a2f2f') + '"/>';
      s += '<rect x="22" y="62" width="5" height="7" fill="#c9a23c"/>' +
        '<rect x="34" y="62" width="5" height="7" fill="#c9a23c"/>';
      return s;
    },
    label: function (st) {
      var p = st && st.devices.pump;
      return p ? (p.on ? '水泵·开 ' + Math.round(p.power) + '%' : '水泵·关') : '水泵';
    },
    dynamic: true
  };

  /* 墙壁开关（按键模块） */
  LIB.wallSwitch = {
    name: '墙壁开关', w: 62, h: 84, cat: '生活物品', dynamic: true,
    build: function (st) {
      var b = (st && st.devices.button) || { on: false };
      var on = b.on;
      var s = shadow(31, 80, 20, 4);
      s += '<rect x="8" y="6" width="46" height="70" rx="6" fill="#f0f2f5" stroke="#c4ccd4" stroke-width="1.4"/>';
      s += '<rect x="16" y="14" width="30" height="28" rx="4" fill="' +
        (on ? '#e8c24a' : '#dfe4ea') + '" stroke="#b6bfc7"/>';
      s += '<rect x="16" y="48" width="30" height="20" rx="4" fill="' +
        (on ? '#2f9e8e' : '#dfe4ea') + '" stroke="#b6bfc7"/>';
      s += '<circle cx="31" cy="28" r="5" fill="' + (on ? '#8a6f22' : '#b6bfc7') + '"/>';
      return s;
    },
    label: function (st) {
      var b = st && st.devices.button;
      return b ? (b.on ? '开关·开' : '开关·关') : '开关';
    },
    dynamic: true
  };

  /* 台灯（对应 ledModule 硬件） */
  LIB.deskLamp = {
    name: 'LED 台灯', w: 110, h: 140, cat: '生活物品', dynamic: true,
    build: function (st) {
      var lm = (st && st.devices.ledModule) || { bright: 0 };
      var k = Math.max(0, Math.min(100, lm.bright)) / 100;
      var s = shadow(55, 136, 34, 5);
      /* 底座 */
      s += '<ellipse cx="55" cy="130" rx="34" ry="7" fill="#4a525c"/>';
      /* 灯杆 */
      s += '<path d="M55,128 L55,74" stroke="#6b7680" stroke-width="6" stroke-linecap="round"/>';
      s += '<path d="M55,76 q0,-26 26,-30" fill="none" stroke="#6b7680" stroke-width="5" stroke-linecap="round"/>';
      /* 灯罩 */
      s += '<path d="M68,34 h32 l8,18 h-48 Z" fill="#5a636e"/>';
      s += '<ellipse cx="84" cy="52" rx="24" ry="6" fill="#3f464f"/>';
      /* 光锥与灯泡 */
      if (k > 0.02) {
        s += '<path d="M60,54 L26,128 h116 L108,54 Z" fill="#ffe9a0" opacity="' + (k * 0.24).toFixed(2) + '"/>';
        s += '<circle cx="84" cy="54" r="11" fill="rgb(255,' + (240 - k * 60 | 0) + ',' +
          (170 - k * 120 | 0) + ')" opacity="' + (0.35 + k * 0.65).toFixed(2) + '"/>';
        s += '<circle cx="84" cy="54" r="20" fill="#ffe9a0" opacity="' + (k * 0.2).toFixed(2) + '"/>';
      } else {
        s += '<ellipse cx="84" cy="54" rx="24" ry="6" fill="#c8d0d8"/>';
      }
      return s;
    },
    label: function (st) {
      var lm = st && st.devices.ledModule;
      return lm ? ('LED 亮度 ' + Math.round(lm.bright) + '%') : 'LED 台灯';
    },
    dynamic: true
  };

  /* ============================================================
   * 更多拓展库硬件元素（与虚拟仿真设备数据实时同步）
   * ============================================================ */

  /* 舵机（SG90）：摆臂角度随 servo.angle 转动 */
  LIB.servoArm = {
    name: '舵机', w: 92, h: 84, cat: '智能硬件', dynamic: true,
    build: function (st) {
      var sv = (st && st.devices.servo) || { angle: 90 };
      var ang = Math.max(0, Math.min(180, sv.angle != null ? sv.angle : 90));
      var s = shadow(46, 80, 30, 4);
      /* 摆臂（90°=竖直向上，0°=向左，180°=向右） */
      s += '<g transform="rotate(' + (ang - 90) + ' 46 34)">' +
        '<rect x="41" y="2" width="10" height="36" rx="4" fill="#e8edf2"/>' +
        '<circle cx="46" cy="8" r="2.4" fill="#9aa6b0"/>' +
        '<circle cx="46" cy="18" r="2.4" fill="#9aa6b0"/></g>';
      /* 机身 */
      s += '<rect x="22" y="34" width="48" height="34" rx="5" fill="#2f6fb2"/>';
      s += '<rect x="16" y="40" width="6" height="10" rx="2" fill="#245a92"/>' +
        '<rect x="70" y="40" width="6" height="10" rx="2" fill="#245a92"/>';
      s += '<circle cx="46" cy="34" r="8" fill="#245a92"/><circle cx="46" cy="34" r="3.4" fill="#c9d4de"/>';
      s += '<text x="46" y="62" font-size="9" text-anchor="middle" fill="#fff" font-family="monospace">' +
        Math.round(ang) + '°</text>';
      s += '<rect x="30" y="68" width="5" height="7" fill="#c9a23c"/>' +
        '<rect x="44" y="68" width="5" height="7" fill="#c9a23c"/>' +
        '<rect x="58" y="68" width="5" height="7" fill="#c9a23c"/>';
      return s;
    },
    label: function (st) {
      var sv = st && st.devices.servo;
      return sv ? ('舵机·' + Math.round(sv.angle) + '°') : '舵机';
    },
    dynamic: true
  };

  /* 直流电机：扇叶转速/转向随 motor.vel */
  LIB.dcMotor = {
    name: '直流电机', w: 96, h: 78, cat: '智能硬件', dynamic: true,
    build: function (st) {
      var m = (st && st.devices.motor) || { vel: 0 };
      var s = shadow(48, 74, 30, 4);
      /* 扇叶（tick 旋转） */
      s += '<g transform="translate(72,30)"><g class="spin">' +
        [0, 90, 180, 270].map(function (a) {
          return '<path d="M0,0 Q10,-8 18,-2 Q10,4 0,0Z" fill="#8ecae6" transform="rotate(' + a + ')"/>';
        }).join('') + '</g><circle r="4" fill="#4a5560"/></g>';
      /* 电机身 + 转轴 */
      s += '<rect x="12" y="16" width="44" height="30" rx="8" fill="#5a6672"/>';
      s += '<rect x="12" y="16" width="10" height="30" rx="4" fill="#48525c"/>';
      s += '<rect x="54" y="26" width="12" height="5" fill="#9aa6b0"/>';
      s += '<circle cx="20" cy="52" r="3.4" fill="' + (m.vel ? '#4ade80' : '#3a4148') + '"/>';
      s += '<rect x="26" y="52" width="5" height="7" fill="#c9a23c"/>' +
        '<rect x="38" y="52" width="5" height="7" fill="#c9a23c"/>';
      return s;
    },
    tick: function (g, st, t) {
      var m = st && st.devices.motor;
      var spin = g.querySelector('.spin');
      if (!spin || !m) return;
      if (m.vel) spin.setAttribute('transform', 'rotate(' + ((t * m.vel * 6) % 360) + ')');
      spin.style.opacity = m.vel ? '1' : '.45';
    },
    label: function (st) {
      var m = st && st.devices.motor;
      if (!m || !m.vel) return '电机·停止';
      return m.vel > 0 ? ('电机·正转' + m.vel) : ('电机·反转' + Math.abs(m.vel));
    },
    dynamic: true
  };

  /* 颜色传感器（TCS34725）：感应窗显示识别到的颜色 */
  var COLOR_CN = {
    red: '红色', green: '绿色', blue: '蓝色', yellow: '黄色', purple: '紫色',
    cyan: '青色', white: '白色', black: '黑色', orange: '橙色'
  };
  LIB.colorSensor = {
    name: '颜色传感器', w: 82, h: 78, cat: '智能硬件', dynamic: true,
    build: function (st) {
      var c = (st && st.devices.color) || { r: 255, g: 30, b: 30, name: 'red' };
      var col = 'rgb(' + (c.r | 0) + ',' + (c.g | 0) + ',' + (c.b | 0) + ')';
      var s = shadow(41, 74, 26, 4);
      s += '<rect x="10" y="10" width="62" height="46" rx="5" fill="#2b3138"/>';
      s += '<circle cx="41" cy="30" r="14" fill="#0d1014" stroke="#6b7480" stroke-width="2"/>';
      s += '<circle cx="41" cy="30" r="9" fill="' + col + '"/>';
      s += '<circle cx="41" cy="30" r="16" fill="none" stroke="' + col + '" stroke-width="1.4" opacity=".45"/>';
      s += '<circle cx="20" cy="20" r="3" fill="#fff" opacity=".85"/>';
      s += '<rect x="22" y="58" width="5" height="7" fill="#c9a23c"/>' +
        '<rect x="34" y="58" width="5" height="7" fill="#c9a23c"/>' +
        '<rect x="46" y="58" width="5" height="7" fill="#c9a23c"/>' +
        '<rect x="58" y="58" width="5" height="7" fill="#c9a23c"/>';
      return s;
    },
    label: function (st) {
      var c = st && st.devices.color;
      return c ? ('颜色·' + (COLOR_CN[c.name] || c.name)) : '颜色传感器';
    },
    dynamic: true
  };

  /* AS7341 可见光颜色传感器（gravity） */
  LIB.as7341Sensor = {
    name: 'AS7341 颜色', w: 84, h: 78, cat: '智能硬件', dynamic: true,
    build: function (st) {
      var g = (st && st.devices.gravity) || { r: 120, g: 200, b: 240, l: 560 };
      var k = Math.max(0.3, Math.min(1, (g.l || 500) / 800));
      var col = 'rgb(' + Math.min(255, g.r * k | 0) + ',' + Math.min(255, g.g * k | 0) + ',' +
        Math.min(255, g.b * k | 0) + ')';
      var s = shadow(42, 74, 27, 4);
      s += '<rect x="11" y="10" width="62" height="46" rx="5" fill="#22303c"/>';
      /* 多通道感应阵列 */
      for (var i = 0; i < 3; i++) {
        s += '<rect x="' + (20 + i * 15) + '" y="18" width="11" height="11" rx="2" fill="#0d1014" ' +
          'stroke="#54616e" stroke-width="1.2"/>';
      }
      s += '<rect x="20" y="34" width="41" height="12" rx="3" fill="' + col + '"/>';
      s += '<rect x="22" y="58" width="5" height="7" fill="#c9a23c"/>' +
        '<rect x="34" y="58" width="5" height="7" fill="#c9a23c"/>' +
        '<rect x="46" y="58" width="5" height="7" fill="#c9a23c"/>' +
        '<rect x="58" y="58" width="5" height="7" fill="#c9a23c"/>';
      return s;
    },
    label: function (st) {
      var g = st && st.devices.gravity;
      return g ? ('光感·' + Math.round(g.l)) : 'AS7341';
    },
    dynamic: true
  };

  /* AI 摄像头：显示当前识别目标 */
  LIB.aiCamera = {
    name: 'AI 摄像头', w: 98, h: 86, cat: '智能硬件', dynamic: true,
    build: function (st) {
      var cam = (st && st.devices.camera) || { label: '人脸' };
      var s = shadow(49, 82, 30, 4);
      s += '<rect x="44" y="58" width="10" height="16" fill="#4a5560"/>' +
        '<ellipse cx="49" cy="76" rx="20" ry="5" fill="#5a6672"/>';
      s += '<rect x="16" y="10" width="66" height="50" rx="8" fill="#243447" stroke="#d83a30" stroke-width="2"/>';
      s += '<circle cx="36" cy="35" r="13" fill="#0d1014" stroke="#7f93a8" stroke-width="2"/>' +
        '<circle cx="36" cy="35" r="6" fill="#1a2f45"/>' +
        '<circle cx="33" cy="32" r="2" fill="#7fb2e0"/>';
      s += '<rect x="54" y="24" width="24" height="22" rx="3" fill="#101820"/>' +
        '<text x="66" y="38" font-size="8" text-anchor="middle" fill="#ffd08a">' +
        (cam.label || '人脸') + '</text>';
      return s;
    },
    label: function (st) {
      var cam = st && st.devices.camera;
      return cam ? ('识别：' + (cam.label || '人脸')) : 'AI 摄像头';
    },
    dynamic: true
  };

  /* 麦克风：音量柱随 mic.v 起伏 */
  LIB.micSensor = {
    name: '麦克风', w: 74, h: 100, cat: '智能硬件', dynamic: true,
    build: function (st) {
      var m = (st && st.devices.mic) || { v: 100 };
      var k = Math.max(0, Math.min(1, (m.v || 0) / 4095));
      var s = shadow(37, 96, 22, 4);
      s += '<circle cx="30" cy="24" r="16" fill="#2b3138"/>';
      for (var r = 0; r < 3; r++) {
        s += '<circle cx="30" cy="24" r="' + (11 - r * 3.4) + '" fill="none" stroke="#4a5560" stroke-width="1.4"/>';
      }
      s += '<rect x="26" y="40" width="8" height="24" rx="3" fill="#4a5560"/>';
      for (var i = 0; i < 5; i++) {
        var on = k * 5 > i;
        s += '<rect x="' + (52 + i * 4.6) + '" y="' + (34 - i * 4) + '" width="3.4" height="' + (6 + i * 4) +
          '" fill="' + (on ? (i >= 3 ? '#ff5d5d' : '#4ade80') : '#3a4148') + '"/>';
      }
      s += '<rect x="20" y="66" width="5" height="7" fill="#c9a23c"/>' +
        '<rect x="32" y="66" width="5" height="7" fill="#c9a23c"/>';
      return s;
    },
    label: function (st) {
      var m = st && st.devices.mic;
      return m ? ('音量 ' + Math.round(m.v)) : '麦克风';
    },
    dynamic: true
  };

  /* 光线传感器：光晕随 lightExt.v 强弱 */
  LIB.lightSensor = {
    name: '光线传感器', w: 82, h: 82, cat: '智能硬件', dynamic: true,
    build: function (st) {
      var l = (st && st.devices.lightExt) || { v: 900 };
      var k = Math.max(0, Math.min(1, (l.v || 0) / 4095));
      var s = shadow(41, 78, 26, 4);
      s += '<rect x="12" y="14" width="58" height="46" rx="5" fill="#2b3138"/>';
      s += '<circle cx="41" cy="34" r="14" fill="#e8d9a0"/>';
      s += '<path d="M33,34 q4,-8 8,0 q4,8 8,0" fill="none" stroke="#8a6f22" stroke-width="2.2"/>';
      s += '<path d="M33,28 q4,-8 8,0 q4,8 8,0 M33,40 q4,-8 8,0 q4,8 8,0" fill="none" ' +
        'stroke="#8a6f22" stroke-width="2.2" opacity=".7"/>';
      if (k > 0.05) {
        s += '<circle cx="41" cy="34" r="19" fill="#ffe9a0" opacity="' + (k * 0.5).toFixed(2) + '"/>';
      }
      s += '<rect x="26" y="62" width="5" height="7" fill="#c9a23c"/>' +
        '<rect x="38" y="62" width="5" height="7" fill="#c9a23c"/>' +
        '<rect x="50" y="62" width="5" height="7" fill="#c9a23c"/>';
      return s;
    },
    label: function (st) {
      var l = st && st.devices.lightExt;
      return l ? ('光照 ' + Math.round(l.v)) : '光线传感器';
    },
    dynamic: true
  };

  /* 角度传感器：旋钮指针随 angle.deg 转动 */
  LIB.angleSensor = {
    name: '角度传感器', w: 82, h: 82, cat: '智能硬件', dynamic: true,
    build: function (st) {
      var a = (st && st.devices.angle) || { deg: 45 };
      var deg = Math.max(0, Math.min(300, a.deg != null ? a.deg : 45));
      var rot = -135 + deg / 300 * 270;
      var s = shadow(41, 78, 26, 4);
      s += '<rect x="12" y="12" width="58" height="52" rx="5" fill="#2b3138"/>';
      s += '<path d="M24,52 A20,20 0 0 1 58,52" fill="none" stroke="#4a5560" stroke-width="2"/>';
      s += '<circle cx="41" cy="40" r="15" fill="#dfe4ea" stroke="#9aa6b0" stroke-width="2"/>';
      s += '<g transform="rotate(' + rot + ' 41 40)">' +
        '<rect x="39.4" y="27" width="3.2" height="10" rx="1.6" fill="#d83a30"/></g>';
      s += '<circle cx="41" cy="40" r="4" fill="#9aa6b0"/>';
      s += '<rect x="26" y="66" width="5" height="7" fill="#c9a23c"/>' +
        '<rect x="38" y="66" width="5" height="7" fill="#c9a23c"/>' +
        '<rect x="50" y="66" width="5" height="7" fill="#c9a23c"/>';
      return s;
    },
    label: function (st) {
      var a = st && st.devices.angle;
      return a ? ('角度 ' + Math.round(a.deg) + '°') : '角度传感器';
    },
    dynamic: true
  };

  /* PM2.5 传感器：读数与颗粒数随 pm25.v，超限变色 */
  LIB.pm25Sensor = {
    name: 'PM2.5 传感器', w: 86, h: 84, cat: '智能硬件', dynamic: true,
    build: function (st) {
      var p = (st && st.devices.pm25) || { v: 35 };
      var v = p.v || 0;
      var lv = v <= 35 ? '#4ade80' : (v <= 75 ? '#ffd24a' : '#ff5d5d');
      var s = shadow(43, 80, 28, 4);
      s += '<rect x="12" y="10" width="62" height="56" rx="6" fill="#3a4552"/>';
      for (var i = 0; i < 4; i++) {
        s += '<rect x="18" y="' + (16 + i * 6) + '" width="20" height="3" rx="1.5" fill="#232a33"/>';
      }
      s += '<rect x="42" y="16" width="26" height="20" rx="3" fill="#0b1410"/>' +
        '<text x="55" y="29" font-size="9" text-anchor="middle" fill="' + lv +
        '" font-family="monospace">' + Math.round(v) + '</text>';
      var n = Math.min(6, Math.round(v / 40));
      for (var d = 0; d < n; d++) {
        s += '<circle cx="' + (46 + d * 4.4) + '" cy="44" r="1.8" fill="' + lv + '" opacity=".8"/>';
      }
      s += '<rect x="26" y="68" width="5" height="7" fill="#c9a23c"/>' +
        '<rect x="38" y="68" width="5" height="7" fill="#c9a23c"/>';
      return s;
    },
    label: function (st) {
      var p = st && st.devices.pm25;
      return p ? ('PM2.5 ' + Math.round(p.v)) : 'PM2.5';
    },
    dynamic: true
  };

  /* 气压传感器：表盘指针随 baro.p 摆动 */
  LIB.baroSensor = {
    name: '气压传感器', w: 82, h: 80, cat: '智能硬件', dynamic: true,
    build: function (st) {
      var b = (st && st.devices.baro) || { p: 1013 };
      var k = Math.max(0, Math.min(1, ((b.p || 1013) - 950) / 100));
      var rot = -120 + k * 240;
      var s = shadow(41, 76, 26, 4);
      s += '<rect x="14" y="12" width="54" height="50" rx="5" fill="#2b3138"/>';
      s += '<circle cx="41" cy="38" r="17" fill="#f0f2f5"/>';
      s += '<path d="M28,48 A16,16 0 0 1 54,48" fill="none" stroke="#9aa6b0" stroke-width="2"/>';
      s += '<g transform="rotate(' + rot + ' 41 38)">' +
        '<line x1="41" y1="38" x2="41" y2="26" stroke="#d83a30" stroke-width="2.4" stroke-linecap="round"/></g>';
      s += '<circle cx="41" cy="38" r="3" fill="#4a5560"/>';
      s += '<rect x="26" y="64" width="5" height="7" fill="#c9a23c"/>' +
        '<rect x="38" y="64" width="5" height="7" fill="#c9a23c"/>' +
        '<rect x="50" y="64" width="5" height="7" fill="#c9a23c"/>';
      return s;
    },
    label: function (st) {
      var b = st && st.devices.baro;
      return b ? ('气压 ' + Math.round(b.p) + 'hPa') : '气压传感器';
    },
    dynamic: true
  };

  /* 红外发射模块：发射瞬间闪烁红光与波纹 */
  LIB.irTxModule = {
    name: '红外发射模块', w: 78, h: 66, cat: '智能硬件', dynamic: true,
    build: function (st) {
      var t = (st && st.devices.irTx) || { last: 0 };
      var firing = !!(t.last && (Date.now() - t.last < 600));
      var s = shadow(39, 62, 24, 4);
      s += '<rect x="10" y="16" width="58" height="34" rx="4" fill="#2b3138"/>';
      s += '<circle cx="26" cy="30" r="9" fill="#1a1f25" stroke="#6b7480" stroke-width="1.6"/>';
      s += '<circle cx="26" cy="30" r="4" fill="' + (firing ? '#ff4040' : '#4a2a2a') + '"/>';
      if (firing) {
        for (var i = 0; i < 3; i++) {
          s += '<path d="M' + (38 + i * 8) + ',22 q5,8 0,16" fill="none" stroke="#ff8a80" ' +
            'stroke-width="1.8" opacity="' + (0.8 - i * 0.22).toFixed(2) + '"/>';
        }
      }
      s += '<circle cx="60" cy="24" r="2.6" fill="' + (firing ? '#4ade80' : '#2a3a2a') + '"/>';
      s += '<rect x="20" y="52" width="5" height="7" fill="#c9a23c"/>' +
        '<rect x="32" y="52" width="5" height="7" fill="#c9a23c"/>' +
        '<rect x="44" y="52" width="5" height="7" fill="#c9a23c"/>';
      return s;
    },
    label: function (st) {
      var t = st && st.devices.irTx;
      var firing = t && t.last && (Date.now() - t.last < 600);
      return firing ? '红外·发射中' : '红外发射';
    },
    dynamic: true
  };

  /* 红外遥控器：高亮最近按下的方向键 */
  LIB.irRemote = {
    name: '红外遥控器', w: 66, h: 116, cat: '智能硬件', dynamic: true,
    build: function (st) {
      var r = (st && st.devices.remote) || { dir: '' };
      var d = r.dir || '';
      function btn(x, y, w, ch, key) {
        var on = d === key;
        return '<rect x="' + x + '" y="' + y + '" width="' + w + '" height="15" rx="4" fill="' +
          (on ? '#e8c24a' : '#3a4148') + '"/>' +
          '<text x="' + (x + w / 2) + '" y="' + (y + 11) + '" font-size="8.5" text-anchor="middle" fill="' +
          (on ? '#1b1e23' : '#c9d1d9') + '">' + ch + '</text>';
      }
      var s = shadow(33, 112, 20, 4);
      s += '<rect x="12" y="4" width="42" height="102" rx="9" fill="#23282e" stroke="#454f5a" stroke-width="1.4"/>';
      s += '<circle cx="33" cy="11" r="4" fill="' + (d ? '#ff5d5d' : '#3a2f2f') + '"/>';
      s += btn(19, 20, 28, '▲', 'up');
      s += btn(14, 39, 18, '◀', 'left') + btn(34, 39, 18, '▶', 'right');
      s += btn(19, 58, 28, '▼', 'down');
      s += btn(19, 80, 28, 'OK', 'ok');
      return s;
    },
    label: function (st) {
      var r = st && st.devices.remote;
      var CN = { up: '上', down: '下', left: '左', right: '右', ok: '确定' };
      return (r && r.dir) ? ('遥控·' + (CN[r.dir] || r.dir)) : '遥控器';
    },
    dynamic: true
  };

  /* ============================================================
   * 巡线机器人情景（第十四轮：原「循迹小车」改为「巡线机器人」）
   *   机器人：识别地面颜色（绿=起点 / 黑=轨迹 / 红=终点 / 白=地面），
   *   沿黑色轨迹巡线，从绿色点出发，到红色点自动停止。
   *   搭载超声波测距 / AI 摄像头 / 语音识别（积木见 zk_robot_*）。
   *   path：巡线折线（元素相对坐标），stage.js 的 tickRobot 按它移动机器人。
   * ============================================================ */
  LIB.deliverTrack = {
    name: '巡线轨迹', w: 520, h: 200, cat: '机器人',
    path: [[20, 160], [200, 160], [260, 100], [340, 100], [420, 30], [500, 30]],
    build: function () {
      var d = 'M20,160 L200,160 L260,100 L340,100 L420,30 L500,30';
      var s = '<path d="' + d + '" fill="none" stroke="#3a3f46" stroke-width="30" ' +
        'stroke-linejoin="round" stroke-linecap="round"/>';
      s += '<path d="' + d + '" fill="none" stroke="#14161a" stroke-width="24" ' +
        'stroke-linejoin="round" stroke-linecap="round"/>';
      /* 中心虚线（道路感） */
      s += '<path d="' + d + '" fill="none" stroke="#e8ecf2" stroke-width="2" ' +
        'stroke-dasharray="10 8" stroke-linejoin="round" opacity=".5"/>';
      return s;
    },
    label: function () { return '巡线轨迹'; }
  };

  LIB.greenStart = {
    name: '起点（绿）', w: 46, h: 46, cat: '机器人',
    build: function () {
      return '<circle cx="23" cy="23" r="21" fill="#2e9e54" stroke="#1c6b38" stroke-width="2.5"/>' +
        '<circle cx="23" cy="23" r="14" fill="#43c46f"/>' +
        '<text x="23" y="28" font-size="13" font-weight="bold" text-anchor="middle" fill="#fff">起</text>';
    },
    label: function () { return '起点'; }
  };

  LIB.redEnd = {
    name: '终点（红）', w: 46, h: 46, cat: '机器人',
    build: function () {
      return '<circle cx="23" cy="23" r="21" fill="#c9403c" stroke="#8e2622" stroke-width="2.5"/>' +
        '<circle cx="23" cy="23" r="14" fill="#e5574f"/>' +
        '<text x="23" y="28" font-size="13" font-weight="bold" text-anchor="middle" fill="#fff">终</text>';
    },
    label: function () { return '终点'; }
  };

  /* 机器人：机身 + 摄像头眼 + 地面颜色传感器（巡线探头）+ 状态屏 + 轮子 */
  LIB.deliverBot = {
    name: '机器人', w: 64, h: 64, cat: '机器人', dynamic: true,
    build: function (st) {
      var rb = st && st.devices && st.devices.deliverRobot;
      var gnd = rb ? rb.ground : '白色';
      var GND_COL = { 绿色: '#43c46f', 黑色: '#26292e', 红色: '#e5574f', 白色: '#e8ecf2' };
      var s = shadow(32, 60, 24, 4);
      /* 超声波波束（命中时实线 + 端点；未命中淡虚线） */
      if (rb && rb.running !== undefined) {
        var beamLen = Math.min(120, (rb.dist || 200) * 2);
        var hit = rb.dist < 200;
        s += '<line x1="62" y1="32" x2="' + (62 + beamLen) + '" y2="32" ' +
          'stroke="' + (hit ? (rb.dist < 30 ? '#e5484d' : '#4a90d9') : '#9ab6d3') + '" ' +
          'stroke-width="' + (hit ? 2.4 : 1.6) + '"' + (hit ? '' : ' stroke-dasharray="5 5"') +
          ' opacity=".8"/>';
        if (hit) s += '<circle cx="' + (62 + beamLen) + '" cy="32" r="3.4" fill="' +
          (rb.dist < 30 ? '#e5484d' : '#4a90d9') + '"/>';
      }
      /* 天线 */
      s += '<path d="M32,2 v6" stroke="#8a93a0" stroke-width="2.4" stroke-linecap="round"/>' +
        '<circle cx="32" cy="3" r="2.6" fill="#e0552c"/>';
      /* 机身 */
      s += '<rect x="8" y="8" width="48" height="44" rx="9" fill="#f2f5f9" stroke="#b9c2ce" stroke-width="1.6"/>';
      /* AI 摄像头眼（前脸 +x 方向） */
      s += '<rect x="40" y="16" width="14" height="12" rx="3" fill="#1d2530"/>';
      s += '<circle cx="47" cy="22" r="3.6" fill="#4a90d9"/>' +
        '<circle cx="47" cy="22" r="1.5" fill="#bfe0ff"/>';
      /* 状态屏：显示地面颜色 */
      s += '<rect x="12" y="16" width="22" height="14" rx="2.5" fill="#14181e"/>';
      s += '<rect x="14" y="18" width="18" height="10" rx="1.5" fill="' +
        (GND_COL[gnd] || '#e8ecf2') + '"/>';
      /* 麦克风孔 */
      s += '<circle cx="18" cy="38" r="1.4" fill="#8a93a0"/><circle cx="24" cy="38" r="1.4" fill="#8a93a0"/>' +
        '<circle cx="30" cy="38" r="1.4" fill="#8a93a0"/>';
      /* 地面颜色传感器（底部巡线探头） */
      s += '<rect x="26" y="52" width="12" height="6" rx="2" fill="#3a4048"/>';
      s += '<circle cx="32" cy="58" r="3.4" fill="' + (GND_COL[gnd] || '#e8ecf2') +
        '" stroke="#3a4048" stroke-width="1.2"/>';
      /* 轮子 */
      s += '<circle cx="18" cy="56" r="7" fill="#26292e"/><circle cx="18" cy="56" r="3" fill="#5a6470"/>';
      s += '<circle cx="46" cy="56" r="7" fill="#26292e"/><circle cx="46" cy="56" r="3" fill="#5a6470"/>';
      return s;
    },
    label: function (st) {
      var rb = st && st.devices && st.devices.deliverRobot;
      if (!rb) return '机器人';
      if (rb.arrived) return '已到达 ✔';
      var t = rb.running ? '巡线中·' + (rb.ground || '') : '待机·' + (rb.ground || '');
      if (rb.target) t += '·前方' + rb.target + rb.dist + 'cm';
      return t;
    },
    dynamic: true
  };

  /* 机器人送餐情景：绿点出发 → 黑色轨迹巡线 → 红点停止（机器人送餐应用） */
  SCENES.delivery = {
    name: '机器人送餐',
    items: [
      { k: 'deliverTrack', x: 140, y: 140 },
      { k: 'greenStart', x: 137, y: 277 },
      { k: 'redEnd', x: 617, y: 147 },
      { k: 'deliverBot', x: 128, y: 265 },
      { k: 'streetTree', x: 300, y: 330 },
      { k: 'pedestrian', x: 430, y: 190 },
      { k: 'bench', x: 540, y: 320 },
      { k: 'streetLamp', x: 660, y: 260 }
    ],
    devices: ['robot']
  };

  /* 校园情景 */
  SCENES.campus = {
    name: '校园',
    items: [
      { k: 'schoolBuilding', x: 90, y: 130 },
      { k: 'schoolGate', x: 420, y: 300 },
      { k: 'playground', x: 430, y: 190 },
      { k: 'flagpole', x: 330, y: 250 },
      { k: 'streetLamp', x: 300, y: 250 },
      { k: 'streetLamp', x: 730, y: 250 },
      { k: 'basketballHoop', x: 700, y: 150 },
      { k: 'flowerBed', x: 150, y: 350 },
      { k: 'bench', x: 330, y: 360 },
      { k: 'trashBin', x: 520, y: 360 },
      { k: 'bulletinBoard', x: 60, y: 300 },
      { k: 'plant', x: 250, y: 340 },
      { k: 'streetTree', x: 620, y: 300 },
      { k: 'streetTree', x: 100, y: 230 }
    ],
    devices: ['dht', 'lightExt', 'fan']
  };

  /* 交通情景补上小车（加入 motor / car 设备联动）
     第二十一轮：横向斑马线（crosswalkV）横放马路中间供行人上下通过，
     行人在斑马线上方待过马路，前方停一辆车（vehicle）供「确认安全后超车」演示。 */
  SCENES.traffic.items = [
    { k: 'road', x: 60, y: 296 },
    { k: 'crosswalkV', x: 316, y: 210 },
    { k: 'trafficLight', x: 636, y: 176 }, { k: 'stopLine', x: 120, y: 300 },
    { k: 'speedLimit', x: 600, y: 296 }, { k: 'pedestrian', x: 330, y: 218 },
    { k: 'streetTree', x: 96, y: 176 }, { k: 'stopSign', x: 616, y: 300 },
    { k: 'vehicle', x: 300, y: 300 },
    { k: 'car', x: 120, y: 330 }
  ];

  /* ============================================================
   * 小车（交通/校园场景共用；由 stage.js 的 tickCar 驱动运动学）
   * ============================================================ */
  LIB.car = {
    name: '模拟小车', w: 64, h: 56, cat: '交通', dynamic: true,
    build: function (st) {
      /* 第二十一轮：车头前方探测距离提示线（dynamic 元素每帧重绘，
         必须在这里画，否则会被每帧重建覆盖掉） */
      var c = st && st.devices && st.devices.car;
      var d = c && c._dist != null ? c._dist : 0;
      var nm = (c && c._target) || '';
      var s = carBodySvg(0, 0, false, 0);
      var dpx = Math.max(10, Math.min(150, d * 2));
      var col = dpx < 60 ? '#ff5252' : dpx < 120 ? '#ffa733' : '#4ad07a';
      var g = '<g opacity=".92">' +
        '<line x1="54" y1="34" x2="' + (54 + dpx) + '" y2="34" stroke="' + col +
        '" stroke-width="2" stroke-dasharray="5 4"/>' +
        '<circle cx="54" cy="34" r="2.6" fill="' + col + '"/>' +
        '<circle cx="' + (54 + dpx) + '" cy="34" r="3.4" fill="none" stroke="' + col +
        '" stroke-width="1.8"/>';
      for (var gx = 50; gx <= 150; gx += 50) {
        g += '<line x1="' + (54 + gx) + '" y1="30" x2="' + (54 + gx) +
          '" y2="38" stroke="' + col + '" stroke-width="1" opacity=".45"/>';
      }
      g += '<text x="' + (58 + dpx) + '" y="26" font-size="10" fill="' + col +
        '" font-weight="700">' + (d > 0 ? (nm ? nm + ' ' + d : d + 'cm') : '前方通畅') +
        '</text></g>';
      return s + g;
    },
    tick: function (g, st, t) {
      /* 运动学由 stage.js 的 tickCar 更新，这里仅补充缩略渲染 */
    },
    label: function (st) {
      var c = st && st.devices && st.devices.car;
      if (!c) return '模拟小车';
      var spd = Math.round(Math.abs((c.l || 0) + (c.r || 0)) / 2);
      var txt = spd < 1 ? '小车·停止' : '小车·' + spd + '%';
      /* 附带车头超声波测距（到行人 / 路树等障碍物） */
      if (c._dist != null && c._dist < 200) txt += '·距' + (c._target || '障碍物') + c._dist + 'cm';
      return txt;
    },
    dynamic: true
  };
  /* 小车车身 SVG（与 stage.js 的 carBody 保持一致的观感，供缩略图使用） */
  function carBodySvg(x, y, blocked, vLin) {
    var s = '<ellipse cx="' + (x + 30) + '" cy="' + (y + 34) + '" rx="26" ry="13" fill="rgba(30,50,80,.18)"/>';
    s += '<rect x="' + (x + 14) + '" y="' + (y + 22) + '" width="11" height="5" rx="2" fill="#22262c"/>';
    s += '<rect x="' + (x + 40) + '" y="' + (y + 22) + '" width="11" height="5" rx="2" fill="#22262c"/>';
    s += '<rect x="' + (x + 14) + '" y="' + (y + 32) + '" width="11" height="5" rx="2" fill="#22262c"/>';
    s += '<rect x="' + (x + 40) + '" y="' + (y + 32) + '" width="11" height="5" rx="2" fill="#22262c"/>';
    s += '<rect x="' + (x + 10) + '" y="' + (y + 24) + '" width="42" height="20" rx="6" fill="#3d7ea6"/>';
    s += '<rect x="' + (x + 34) + '" y="' + (y + 26.5) + '" width="10" height="15" rx="2" fill="#bfe3f2"/>';
    s += '<rect x="' + (x + 18) + '" y="' + (y + 26.5) + '" width="9" height="15" rx="2" fill="#9fc3d6"/>';
    if (blocked) {
      s += '<circle cx="' + (x + 53) + '" cy="' + (y + 28) + '" r="3" fill="#ff4040"/>';
      s += '<circle cx="' + (x + 53) + '" cy="' + (y + 40) + '" r="3" fill="#ff4040"/>';
    } else if (Math.abs(vLin) > 1) {
      s += '<circle cx="' + (x + 53) + '" cy="' + (y + 28) + '" r="2.6" fill="#fff096"/>';
      s += '<circle cx="' + (x + 53) + '" cy="' + (y + 40) + '" r="2.6" fill="#fff096"/>';
    }
    return s;
  }

  /* ============================================================
   * 巡线小车（第十四轮）
   *   车体 + 两台电机 + 循迹器 5 路探针 + 超声波
   *   运动由 stage.js 的 tickTraceCar 驱动（数据来自拓展库「巡线小车」设备）
   * ============================================================ */
  var TC_ON = { 居中: [0, 0, 1, 0, 0], 偏左: [1, 1, 0, 0, 0], 偏右: [0, 0, 0, 1, 1], 离线: [0, 0, 0, 0, 0] };
  LIB.traceCar = {
    name: '巡线小车', w: 104, h: 66, cat: '交通', dynamic: true,
    build: function (st) {
      var dev = (st && st.devices) || {};
      var tc = dev.traceCar || {};
      var line = tc.line || '离线';
      var on = TC_ON[line] || TC_ON['离线'];
      var dist = (tc.dist == null) ? 200 : tc.dist;
      var moving = !!(tc.l || tc.r) || !!tc.auto;
      var s = shadow(52, 60, 40, 6);
      /* 电机（车头两侧，转动条纹随速度变化） */
      [[16, 8], [16, 44]].forEach(function (p) {
        s += '<rect x="' + p[0] + '" y="' + p[1] + '" width="15" height="14" rx="3" fill="#cf7a16" ' +
          'stroke="#8a4c0c" stroke-width="1"/>';
        s += '<circle cx="' + (p[0] + 7.5) + '" cy="' + (p[1] + 7) + '" r="4.6" fill="#e0834d"/>';
        s += '<circle cx="' + (p[0] + 7.5) + '" cy="' + (p[1] + 7) + '" r="1.8" fill="#7a3d17"/>';
        if (moving) {
          s += '<g class="spin" style="transform-box:view-box;transform-origin:' +
            (p[0] + 7.5) + 'px ' + (p[1] + 7) + 'px;--spin-dur:.7s">' +
            '<rect x="' + (p[0] + 6.4) + '" y="' + (p[1] + 1.6) + '" width="2.2" height="10.8" rx="1" fill="#7a3d17"/>' +
            '</g>';
        }
      });
      /* 车体 */
      s += rr(8, 12, 88, 40, 9, '#2f7fb5', ' stroke="#20608c" stroke-width="1.6"');
      s += rr(20, 18, 34, 14, 4, '#63b0dd');
      /* 超声波头（车头 +x 方向） */
      s += '<circle cx="88" cy="32" r="10" fill="#0d1014" stroke="#6b7480" stroke-width="2"/>';
      s += '<circle cx="88" cy="32" r="4.6" fill="#1a1f25"/>';
      var waves = Math.max(1, Math.min(4, Math.round(40 / Math.max(6, dist))));
      for (var i = 0; i < waves; i++) {
        s += '<path d="M98,' + (32 - 6 - i * 4) + ' q' + (4 + i * 3) + ',' + (6 + i * 4) + ' 0,' +
          (12 + i * 8) + '" fill="none" stroke="#7ec8e3" stroke-width="1.6" opacity="' +
          (0.6 - i * 0.12).toFixed(2) + '"/>';
      }
      /* 循迹器探针条（车头前方 5 路） */
      s += rr(10, 52, 52, 11, 3, '#1f242a');
      for (var k = 0; k < 5; k++) {
        s += '<rect x="' + (14 + k * 10) + '" y="55" width="7" height="5" rx="1.5" fill="' +
          (on[k] ? '#4ade80' : '#2b3038') + '"/>';
      }
      /* 轮子 */
      s += '<circle cx="24" cy="56" r="8" fill="#22262c"/><circle cx="24" cy="56" r="3.4" fill="#8a93a0"/>';
      s += '<circle cx="80" cy="56" r="8" fill="#22262c"/><circle cx="80" cy="56" r="3.4" fill="#8a93a0"/>';
      return s;
    },
    label: function (st) {
      var tc = (st && st.devices && st.devices.traceCar) || {};
      var line = tc.line || '离线';
      if (!tc.auto) {
        return '巡线小车·' + ((tc.l || tc.r) ? '手动' : '停止');
      }
      return '巡线小车·' + (line === '离线' ? '待命' : '巡线' + line);
    },
    dynamic: true
  };

  /* 巡线小车情景：赛道黑线 + 巡线小车（设备联动生成小车 / 循迹器 / 超声波） */
  SCENES.tracecar = {
    name: '巡线小车',
    items: [
      { k: 'road', x: 70, y: 300 },
      { k: 'trackLine', x: 100, y: 330 },
      { k: 'streetTree', x: 120, y: 180 },
      { k: 'stopSign', x: 660, y: 250 },
      { k: 'trafficLight', x: 690, y: 130 }
    ],
    devices: ['traceCar', 'tracker', 'ultrasonic']
  };

  /* ============================================================
   * 第二十九轮：八年级教材新增元素
   * 对应八年级示例：智能停车场 / 智能货架 / 山体滑坡监测 /
   *   跌倒远程求助 / 共享单车 / 点餐服务 / 磁场与卫星定位
   * ============================================================ */

  /* 停车位（智能停车场：车位占用状态由 sceneFlags.parkTaken 决定） */
  LIB.parkingSpot = {
    name: '停车位', w: 118, h: 96, cat: '交通', dynamic: true,
    build: function (st) {
      var taken = st && st.sceneFlags && st.sceneFlags.parkTaken;
      var s = '<rect x="4" y="4" width="110" height="88" rx="4" fill="none" ' +
        'stroke="' + (taken ? '#e0553b' : '#4ade80') + '" stroke-width="3" stroke-dasharray="7 5"/>';
      /* 车位编号 */
      s += '<text x="59" y="34" font-size="15" font-weight="700" text-anchor="middle" fill="' +
        (taken ? '#e0553b' : '#8aa0b4') + '">' + (st && st.sceneFlags && st.sceneFlags.parkNo || 'A1') + '</text>';
      /* 已占用时画一辆车 */
      if (taken) {
        s += rr(24, 46, 70, 30, 7, '#3d7ea6');
        s += '<path d="M34,46 q8,-13 25,-13 q17,0 25,13z" fill="#63b0dd"/>';
        s += '<circle cx="42" cy="78" r="7" fill="#22262c"/><circle cx="76" cy="78" r="7" fill="#22262c"/>';
      }
      return s;
    },
    label: function (st) {
      var t = st && st.sceneFlags && st.sceneFlags.parkTaken;
      var no = (st && st.sceneFlags && st.sceneFlags.parkNo) || 'A1';
      return '车位' + no + (t ? '·已占' : '·空闲');
    },
    clickable: true
  };

  /* 货架（智能货架：三层，商品可被"取走"） */
  LIB.shelf = {
    name: '智能货架', w: 156, h: 178, cat: '校园',
    build: function (st) {
      var left = st && st.sceneFlags && st.sceneFlags.shelfLeft;
      if (left == null) left = 3;
      var s = shadow(78, 174, 62, 6);
      /* 货架主体 */
      s += rr(6, 6, 144, 166, 4, '#8a6f4a', ' stroke="#6b5436" stroke-width="1.6"');
      /* 三层隔板 */
      [6, 60, 114].forEach(function (y) {
        s += rr(12, y + 44, 132, 5, 2, '#a8895c');
      });
      /* 商品：每层摆若干个，左侧按剩余数量减少 */
      var goods = ['#e0553b', '#3d7ea6', '#f0b429', '#2f9e8e', '#9048c4', '#d63384'];
      var n = Math.max(0, Math.min(6, left));
      for (var i = 0; i < 6; i++) {
        var row = Math.floor(i / 2), col = i % 2;
        if (i >= n) continue;
        var gx = 26 + col * 62, gy = 12 + row * 54;
        s += rr(gx, gy, 44, 34, 4, goods[i]);
        s += rr(gx + 6, gy + 5, 32, 8, 2, '#ffffff', ' opacity=".28"');
      }
      /* 剩余数量标签 */
      s += '<text x="78" y="164" font-size="13" font-weight="700" text-anchor="middle" fill="#fff">剩余 ' + n + ' 件</text>';
      return s;
    },
    label: function (st) {
      var n = (st && st.sceneFlags && st.sceneFlags.shelfLeft);
      return '货架·剩' + (n == null ? 3 : n) + '件';
    },
    clickable: true
  };

  /* 山体与滑坡面（山体滑坡自动监测） */
  LIB.hillside = {
    name: '山坡', w: 260, h: 200, cat: '场景', dynamic: true,
    build: function (st) {
      var risk = st && st.sceneFlags && st.sceneFlags.slideRisk;
      /* risk 0~100：>60 时画红色警戒线与裂缝 */
      var s = rr(0, 120, 260, 80, 4, '#7d8a5a', ' opacity=".55"');
      s += '<path d="M0,124 L60,44 L120,96 L180,30 L260,124 Z" fill="#6b7a4a"/>';
      s += '<path d="M40,72 L60,44 L84,66 Z" fill="#84915c"/>';
      s += '<path d="M160,56 L180,30 L206,58 Z" fill="#84915c"/>';
      /* 裂缝：风险越高越明显 */
      if (risk > 30) {
        var op = Math.min(0.9, (risk - 30) / 70);
        s += '<path d="M96,60 l-8,22 l10,16 l-6,26" stroke="#3a2a18" stroke-width="' +
          (1 + risk / 40).toFixed(1) + '" fill="none" opacity="' + op.toFixed(2) + '"/>';
      }
      if (risk > 60) {
        s += '<path d="M4,30 L256,30" stroke="#e0483e" stroke-width="3" stroke-dasharray="10 6"/>';
        s += '<text x="130" y="24" font-size="14" font-weight="700" text-anchor="middle" fill="#e0483e">警戒线</text>';
      }
      return s;
    },
    label: function (st) {
      var r = (st && st.sceneFlags && st.sceneFlags.slideRisk) || 0;
      return '山坡·风险' + Math.round(r) + '%';
    },
    clickable: true
  };

  /* 人形图标（跌倒远程求助）：st.sceneFlags.fallen 时画成倒地姿势 */
  LIB.person = {
    name: '学生', w: 56, h: 92, cat: '校园', dynamic: true,
    build: function (st) {
      var fallen = st && st.sceneFlags && st.sceneFlags.fallen;
      var s = shadow(28, 88, 16, 4);
      if (!fallen) {
        s += '<circle cx="28" cy="18" r="10" fill="#ffd9b3"/>';
        s += '<path d="M28,28 v26" stroke="#3d7ea6" stroke-width="10" stroke-linecap="round"/>';
        s += '<path d="M16,36 l12,5 l12,-5" stroke="#3d7ea6" stroke-width="7" stroke-linecap="round" fill="none"/>';
        s += '<path d="M28,54 l-9,22 M28,54 l9,22" stroke="#2b3038" stroke-width="8" stroke-linecap="round"/>';
      } else {
        /* 倒地：横躺，头在左 */
        s += '<circle cx="14" cy="70" r="9" fill="#ffd9b3"/>';
        s += '<path d="M24,70 h34" stroke="#3d7ea6" stroke-width="11" stroke-linecap="round"/>';
        s += '<path d="M34,64 l4,-14 M52,64 l4,-14" stroke="#3d7ea6" stroke-width="7" stroke-linecap="round" fill="none"/>';
        s += '<path d="M58,74 l12,10" stroke="#2b3038" stroke-width="8" stroke-linecap="round"/>';
        /* 求救标记 */
        s += '<circle cx="14" cy="48" r="9" fill="#e0553b"/>';
        s += '<text x="14" y="53" font-size="13" font-weight="700" text-anchor="middle" fill="#fff">!</text>';
      }
      return s;
    },
    label: function (st) {
      return (st && st.sceneFlags && st.sceneFlags.fallen) ? '学生·跌倒' : '学生·正常';
    },
    clickable: true
  };

  /* 共享单车（八年级「共享单车/方向」主题） */
  LIB.bike = {
    name: '共享单车', w: 104, h: 62, cat: '交通',
    build: function () {
      var s = shadow(52, 58, 34, 5);
      s += '<circle cx="24" cy="42" r="15" fill="none" stroke="#3a414c" stroke-width="3.4"/>';
      s += '<circle cx="80" cy="42" r="15" fill="none" stroke="#3a414c" stroke-width="3.4"/>';
      s += '<path d="M24,42 L42,42 L56,20 L44,20" stroke="#2f9e8e" stroke-width="3.6" fill="none" stroke-linecap="round"/>';
      s += '<path d="M42,42 L60,42 L56,20" stroke="#2f9e8e" stroke-width="3.6" fill="none"/>';
      s += '<path d="M52,18 L66,18" stroke="#2b3038" stroke-width="4" stroke-linecap="round"/>';
      s += '<rect x="46" y="28" width="14" height="7" rx="2" fill="#f0b429"/>';
      return s;
    },
    label: function () { return '共享单车'; }
  };

  /* 餐桌（点餐服务：厨师端↔学生端） */
  LIB.diningTable = {
    name: '餐桌', w: 168, h: 104, cat: '校园',
    build: function (st) {
      var served = st && st.sceneFlags && st.sceneFlags.served;
      var s = shadow(84, 100, 58, 6);
      s += rr(6, 22, 156, 12, 4, '#a8895c');
      [20, 78, 134].forEach(function (x) {
        s += rr(x, 34, 8, 62, 3, '#8a6f4a');
      });
      /* 盘子：上菜后显示食物 */
      [40, 84, 128].forEach(function (x, i) {
        s += '<ellipse cx="' + x + '" cy="24" rx="16" ry="6" fill="#f4f6f8" stroke="#c9d2da" stroke-width="1.4"/>';
        if (served) {
          s += '<circle cx="' + x + '" cy="22" r="7" fill="#e8834a"/>';
          s += '<circle cx="' + (x + 7) + '" cy="21" r="5" fill="#7fc96b"/>';
        }
      });
      if (served) {
        s += '<text x="84" y="76" font-size="13" font-weight="700" text-anchor="middle" fill="#2f9e8e">已上菜</text>';
      }
      return s;
    },
    label: function (st) {
      return (st && st.sceneFlags && st.sceneFlags.served) ? '餐桌·已上菜' : '餐桌·等待';
    },
    clickable: true
  };

  /* 指南针（磁场传感器） */
  LIB.compass = {
    name: '指南针', w: 96, h: 96, cat: '智能硬件', dynamic: true,
    build: function (st) {
      /* sceneFlags.magHeading 0~359，红色指针指向该方位 */
      var hdg = (st && st.sceneFlags && st.sceneFlags.magHeading) || 0;
      var s = '<circle cx="48" cy="48" r="44" fill="#1e3a5f" stroke="#2f5a8f" stroke-width="2"/>';
      s += '<circle cx="48" cy="48" r="33" fill="#f4f6f8"/>';
      /* 刻度 */
      for (var i = 0; i < 8; i++) {
        var a = i * Math.PI / 4;
        var r1 = 28, r2 = 33;
        s += '<line x1="' + (48 + Math.sin(a) * r1).toFixed(1) + '" y1="' + (48 - Math.cos(a) * r1).toFixed(1) +
          '" x2="' + (48 + Math.sin(a) * r2).toFixed(1) + '" y2="' + (48 - Math.cos(a) * r2).toFixed(1) +
          '" stroke="#b9c2ce" stroke-width="1.4"/>';
      }
      s += '<text x="48" y="16" font-size="10" font-weight="bold" text-anchor="middle" fill="#1e3a5f">N</text>';
      s += '<text x="48" y="86" font-size="10" text-anchor="middle" fill="#7c8a99">S</text>';
      /* 指针 */
      var rad = (hdg - 90) * Math.PI / 180;
      var px = 48 + Math.cos(rad) * 24, py = 48 + Math.sin(rad) * 24;
      s += '<line x1="48" y1="48" x2="' + px.toFixed(1) + '" y2="' + py.toFixed(1) +
        '" stroke="#e0483e" stroke-width="3.4" stroke-linecap="round"/>';
      s += '<circle cx="48" cy="48" r="4" fill="#1e3a5f"/>';
      return s;
    },
    label: function (st) {
      return '指南针·' + Math.round((st && st.sceneFlags && st.sceneFlags.magHeading) || 0) + '°';
    }
  };

  /* 卫星（GPS 定位） */
  LIB.satellite = {
    name: '卫星', w: 84, h: 84, cat: '智能硬件', dynamic: true,
    build: function (st) {
      var ready = st && st.sceneFlags && st.sceneFlags.gpsReady;
      var s = '<g transform="translate(42,34)">';
      s += '<rect x="-11" y="-9" width="22" height="18" rx="3" fill="#c3cad3"/>';
      s += '<rect x="-12" y="-6" width="8" height="12" fill="' + (ready ? '#4d9dff' : '#8a93a0') + '"/>';
      s += '<rect x="4" y="-6" width="8" height="12" fill="' + (ready ? '#4d9dff' : '#8a93a0') + '"/>';
      s += '<path d="M-6,9 L-14,20 M6,9 L14,20" stroke="#8a93a0" stroke-width="2"/></g>';
      if (ready) {
        /* 信号波 */
        s += '<g fill="none" stroke="#4ade80" stroke-width="2" stroke-linecap="round" opacity=".85">' +
          '<path d="M30 44 a14 14 0 0 1 24 0"/><path d="M24 38 a22 22 0 0 1 36 0"/></g>';
        s += '<circle cx="42" cy="60" r="5" fill="#2f9e8e"/>';
      } else {
        s += '<text x="42" y="70" font-size="10" text-anchor="middle" fill="#8a93a0">搜星中…</text>';
      }
      return s;
    },
    label: function (st) {
      return (st && st.sceneFlags && st.sceneFlags.gpsReady) ? '卫星·已定位' : '卫星·搜星中';
    }
  };

  /* ============================================================
   * 六年级新增元素（对应 参考资料/示例py格式/六年级 的 27 个示例）
   * ============================================================ */

  /* 护眼台灯（可调色温护眼灯 / 护眼灯自动调节亮度） */
  LIB.eyeLamp = {
    name: '护眼台灯', w: 96, h: 122, cat: '家居',
    build: function () {
      var s = shadow(48, 118, 40, 5);
      /* 底座 */
      s += '<ellipse cx="48" cy="116" rx="32" ry="7" fill="#3a414c"/>';
      s += '<rect x="44" y="64" width="8" height="52" fill="#5b6674"/>';
      /* 灯罩 */
      s += '<path d="M22,64 L74,64 L66,28 L30,28 Z" fill="#ffd76b" stroke="#f0b429" stroke-width="2.4"/>';
      s += '<rect x="28" y="24" width="40" height="7" rx="3" fill="#f0b429"/>';
      /* 灯光锥 */
      s += '<path d="M32,66 L64,66 L78,116 L18,116 Z" fill="#ffe9a8" opacity=".28"/>';
      s += '<circle cx="48" cy="46" r="7" fill="#fff6d0" opacity=".85"/>';
      return s;
    },
    label: function () { return '护眼台灯'; }
  };

  /* 书桌（时间提醒器 / 坐姿监控器 / 学习场景） */
  LIB.studyDesk = {
    name: '书桌', w: 138, h: 92, cat: '家居',
    build: function () {
      var s = shadow(69, 86, 56, 6);
      /* 桌面 */
      s += '<rect x="8" y="26" width="122" height="9" rx="2" fill="#c98f52"/>';
      s += '<rect x="8" y="35" width="122" height="4" fill="#a06f3c"/>';
      /* 桌腿 */
      s += '<rect x="18" y="39" width="7" height="47" fill="#8a5f34"/>';
      s += '<rect x="113" y="39" width="7" height="47" fill="#8a5f34"/>';
      /* 桌上的书 */
      s += '<rect x="30" y="17" width="26" height="9" rx="1.5" fill="#e8871e"/>';
      s += '<rect x="33" y="13" width="21" height="5" rx="1.5" fill="#f6a94a"/>';
      return s;
    },
    label: function () { return '书桌'; }
  };

  /* 洗衣机（模拟洗衣机控制过程） */
  LIB.washer = {
    name: '洗衣机', w: 112, h: 126, cat: '家电',
    build: function () {
      var s = shadow(56, 120, 48, 6);
      s += '<rect x="14" y="8" width="84" height="110" rx="6" fill="#e8eef5" stroke="#b9c4d2" stroke-width="2.4"/>';
      /* 控制面板 */
      s += '<rect x="20" y="14" width="72" height="18" rx="3" fill="#5b6674"/>';
      s += '<circle cx="34" cy="23" r="5.5" fill="#3dcf8e"/>';
      s += '<rect x="46" y="19" width="38" height="8" rx="2" fill="#cfd8e3"/>';
      /* 桶门 */
      s += '<circle cx="56" cy="70" r="30" fill="#dbe4ee" stroke="#b9c4d2" stroke-width="2.6"/>';
      s += '<circle cx="56" cy="70" r="21" fill="#9fb4cc"/>';
      s += '<path d="M40,64 a18,18 0 0 1 32,0" stroke="#eef4fa" stroke-width="3" fill="none" opacity=".7"/>';
      return s;
    },
    label: function () { return '洗衣机'; }
  };

  /* 垃圾桶（垃圾桶示例：满了要提醒） */
  LIB.trashCan = {
    name: '垃圾桶', w: 78, h: 100, cat: '家居',
    build: function () {
      var s = shadow(39, 94, 34, 5);
      s += '<path d="M16,26 L62,26 L56,92 L22,92 Z" fill="#6f7a88" stroke="#4d5663" stroke-width="2.2"/>';
      s += '<rect x="12" y="18" width="54" height="10" rx="4" fill="#8794a3"/>';
      s += '<rect x="30" y="14" width="18" height="6" rx="3" fill="#a6b2c0"/>';
      /* 满载提示条 */
      s += '<rect x="24" y="40" width="30" height="26" rx="3" fill="#3a414c"/>';
      s += '<rect x="26" y="58" width="26" height="6" rx="2" fill="#e8871e"/>';
      return s;
    },
    label: function () { return '垃圾桶'; }
  };

  /* 投喂器（定时自动投喂器 / 按量自动投喂器） */
  LIB.feeder = {
    name: '自动投喂器', w: 96, h: 132, cat: '家居',
    build: function () {
      var s = shadow(48, 126, 40, 5);
      /* 料桶 */
      s += '<path d="M26,14 L70,14 L66,66 L30,66 Z" fill="#c8d3e0" stroke="#98a5b5" stroke-width="2.4"/>';
      /* 存量刻度 */
      s += '<rect x="32" y="24" width="10" height="34" rx="2" fill="#f0b429"/>';
      s += '<path d="M46,24 L62,24 M46,36 L62,36 M46,48 L62,48" stroke="#98a5b5" stroke-width="2"/>';
      /* 出料口 */
      s += '<rect x="38" y="66" width="20" height="12" rx="3" fill="#8794a3"/>';
      /* 盛食盆 */
      s += '<path d="M22,92 L74,92 L66,116 L30,116 Z" fill="#e8871e" stroke="#b9641a" stroke-width="2.2"/>';
      s += '<ellipse cx="48" cy="92" rx="26" ry="6" fill="#f6a94a"/>';
      return s;
    },
    label: function () { return '自动投喂器'; }
  };

  /* 电子围栏（电子围栏系统：围栏 + 警示灯） */
  LIB.fencePost = {
    name: '电子围栏', w: 82, h: 118, cat: '安防',
    build: function () {
      var s = shadow(41, 112, 32, 5);
      s += '<rect x="36" y="26" width="8" height="84" fill="#5b6674"/>';
      s += '<rect x="20" y="18" width="42" height="12" rx="4" fill="#8794a3"/>';
      /* 警示灯 */
      s += '<circle cx="41" cy="14" r="7" fill="#e05a4e"/>';
      s += '<circle cx="41" cy="14" r="3" fill="#ffd0cc"/>';
      /* 红外感应弧 */
      s += '<path d="M41,40 a26,26 0 0 1 0,44" stroke="#ffb3ac" stroke-width="2.6" fill="none" stroke-dasharray="4 4"/>';
      s += '<path d="M41,40 a14,14 0 0 1 0,44" stroke="#ff8a80" stroke-width="2" fill="none" stroke-dasharray="3 3"/>';
      return s;
    },
    label: function () { return '电子围栏'; }
  };

  /* 节能风扇（节能风扇） */
  /* 节能风扇
     第五十轮：改为 dynamic —— 扇叶转速跟随「风扇」设备的功率，
     这样程序里调 `风扇功率 60%` 舞台上立刻能看见转起来。 */
  LIB.energyFan = {
    name: '节能风扇', w: 104, h: 126, cat: '家电', dynamic: true,
    build: function (st) {
      var fan = (st && st.devices && st.devices.fan) || { power: 0 };
      var s = shadow(52, 120, 40, 5);
      /* 网罩 */
      s += '<circle cx="52" cy="46" r="34" fill="none" stroke="#8794a3" stroke-width="3"/>';
      s += '<circle cx="52" cy="46" r="24" fill="none" stroke="#a6b2c0" stroke-width="2"/>';
      s += '<circle cx="52" cy="46" r="12" fill="none" stroke="#a6b2c0" stroke-width="2"/>';
      /* 扇叶（可旋转的一组） */
      s += '<g class="fan-blades" data-pow="' + (fan.power || 0) + '">';
      s += '<path d="M52,46 C52,26 62,20 66,28 C69,35 60,44 52,46Z" fill="#5fb3d4"/>';
      s += '<path d="M52,46 C70,48 74,60 66,64 C59,67 53,57 52,46Z" fill="#5fb3d4"/>';
      s += '<path d="M52,46 C50,64 38,68 34,60 C31,53 41,47 52,46Z" fill="#5fb3d4"/>';
      s += '</g>';
      s += '<circle cx="52" cy="46" r="6" fill="#3a414c"/>';
      /* 立柱与底座 */
      s += '<rect x="48" y="80" width="8" height="34" fill="#5b6674"/>';
      s += '<ellipse cx="52" cy="116" rx="26" ry="6" fill="#3a414c"/>';
      /* 运行指示灯 */
      s += '<circle cx="52" cy="98" r="3.2" fill="' +
        ((fan.power || 0) > 0 ? '#4ade80' : '#3a414c') + '"/>';
      return s;
    },
    tick: function (g, st, t) {
      var fan = st && st.devices && st.devices.fan;
      var blades = g.querySelector('.fan-blades');
      if (!blades) return;
      var p = Math.max(0, Math.min(100, (fan && fan.power) || 0));
      if (p > 0) blades.setAttribute('transform', 'rotate(' + ((t * p * 6) % 360) + ' 52 46)');
    },
    label: function (st) {
      var fan = st && st.devices && st.devices.fan;
      return fan && fan.power > 0 ? ('风扇·' + Math.round(fan.power) + '%') : '节能风扇';
    }
  };

  /* 人体红外（PIR）
     第五十轮新增：原来「人体红外」设备在舞台上没有对应元素。 */
  LIB.pirSensor = {
    name: '人体红外', w: 84, h: 96, cat: '智能硬件', dynamic: true,
    build: function (st) {
      var pir = (st && st.devices && st.devices.pir) || { on: false };
      var s = shadow(42, 90, 28, 4);
      /* 白色半球罩 */
      s += '<path d="M12,58 a30 30 0 0 1 60 0 Z" fill="' + (pir.on ? '#fff6e8' : '#eef1f4') + '" ' +
        'stroke="#c8d0d8" stroke-width="2"/>';
      /* 菲涅尔纹 */
      s += '<circle cx="42" cy="42" r="12" fill="none" stroke="#cfd6dd" stroke-width="1.6"/>';
      s += '<circle cx="42" cy="42" r="20" fill="none" stroke="#cfd6dd" stroke-width="1.2"/>';
      /* 底座 */
      s += '<rect x="8" y="58" width="68" height="12" rx="4" fill="#5b6674"/>';
      /* 检测到人时的红色指示灯 + 波纹 */
      s += '<circle cx="42" cy="64" r="3.4" fill="' + (pir.on ? '#ff5d5d' : '#3a414c') + '"/>';
      if (pir.on) {
        s += '<circle cx="42" cy="46" r="26" fill="#ff8a5c" opacity=".16"/>';
      }
      return s;
    },
    label: function (st) {
      var pir = st && st.devices && st.devices.pir;
      return pir && pir.on ? '人体红外·有人' : '人体红外·无人';
    }
  };

  /* MP3 模块（UART 音乐模块）
     第五十轮新增：原来「MP3 模块」在舞台上没有对应元素。 */
  LIB.mp3Box = {
    name: 'MP3 模块', w: 96, h: 76, cat: '智能硬件', dynamic: true,
    build: function (st) {
      var m = (st && st.devices && st.devices.mp3) || { playing: false, name: '' };
      var s = shadow(48, 72, 32, 4);
      s += '<rect x="8" y="16" width="80" height="48" rx="5" fill="#1f3a5c" stroke="#2b4f78" stroke-width="1.6"/>';
      /* 喇叭 */
      s += '<circle cx="30" cy="40" r="15" fill="#0a0d10"/>';
      s += '<circle cx="30" cy="40" r="7" fill="#5a6672"/>';
      /* 播放指示条 */
      s += '<rect x="52" y="26" width="28" height="4" rx="2" fill="' +
        (m.playing ? '#4ade80' : '#3f88e8') + '"/>';
      s += '<rect x="52" y="36" width="22" height="4" rx="2" fill="#3f88e8" opacity=".7"/>';
      s += '<rect x="52" y="46" width="14" height="4" rx="2" fill="#3f88e8" opacity=".45"/>';
      /* 状态灯 */
      s += '<circle cx="80" cy="20" r="2.8" fill="' + (m.playing ? '#4ade80' : '#3a414c') + '"/>';
      return s;
    },
    label: function (st) {
      var m = st && st.devices && st.devices.mp3;
      if (!m || !m.playing) return 'MP3 模块';
      return 'MP3·' + (m.name || '播放中');
    }
  };

  /* 孵蛋箱（自动孵蛋箱） */
  LIB.incubator = {
    name: '孵蛋箱', w: 116, h: 112, cat: '家电',
    build: function () {
      var s = shadow(58, 106, 48, 6);
      /* 箱体 */
      s += '<rect x="12" y="20" width="92" height="84" rx="8" fill="#e8eef5" stroke="#b9c4d2" stroke-width="2.4"/>';
      /* 观察窗 */
      s += '<rect x="24" y="32" width="68" height="44" rx="5" fill="#9fd8e8" stroke="#7ab8cc" stroke-width="2.4"/>';
      /* 蛋 */
      s += '<ellipse cx="40" cy="66" rx="7" ry="9" fill="#fff8ec" stroke="#e2d6c0" stroke-width="1.4"/>';
      s += '<ellipse cx="58" cy="68" rx="7" ry="9" fill="#fff8ec" stroke="#e2d6c0" stroke-width="1.4"/>';
      s += '<ellipse cx="76" cy="66" rx="7" ry="9" fill="#fff8ec" stroke="#e2d6c0" stroke-width="1.4"/>';
      /* 温控面板 */
      s += '<rect x="28" y="82" width="60" height="14" rx="3" fill="#5b6674"/>';
      s += '<text x="58" y="93" font-size="10" fill="#3dcf8e" text-anchor="middle" font-family="monospace">38.0C</text>';
      /* 加热指示 */
      s += '<circle cx="98" cy="34" r="5" fill="#e05a4e"/>';
      return s;
    },
    label: function () { return '孵蛋箱'; }
  };

  /* 贺卡（声光贺卡：打开会亮灯+响音乐） */
  LIB.greetCard = {
    name: '声光贺卡', w: 108, h: 86, cat: '家居',
    build: function () {
      var s = shadow(54, 80, 46, 5);
      /* 卡面 */
      s += '<rect x="14" y="20" width="80" height="54" rx="5" fill="#ffd7e0" stroke="#e8a8bc" stroke-width="2.4"/>';
      /* 打开的左半 */
      s += '<path d="M54,20 L14,20 L14,74 L54,74 Z" fill="#ffe9ef" stroke="#e8a8bc" stroke-width="2"/>';
      /* 心形 */
      s += '<path d="M54,60 C42,50 46,40 54,46 C62,40 66,50 54,60Z" fill="#e05a7a"/>';
      /* 音符 */
      s += '<path d="M72,36 L72,52" stroke="#7c5cd6" stroke-width="2.6"/>';
      s += '<circle cx="69" cy="53" r="3.4" fill="#7c5cd6"/>';
      /* 彩灯 */
      s += '<circle cx="26" cy="12" r="4" fill="#f0b429"/>';
      s += '<circle cx="36" cy="10" r="4" fill="#e05a7a"/>';
      s += '<circle cx="46" cy="12" r="4" fill="#3dcf8e"/>';
      return s;
    },
    label: function () { return '声光贺卡'; }
  };

  /* 坐姿检测人像（坐姿监控器 / 户外活动监控器） */
  LIB.posturePerson = {
    name: '坐姿检测', w: 84, h: 132, cat: '人物',
    build: function () {
      var s = shadow(42, 126, 34, 5);
      /* 头 */
      s += '<circle cx="42" cy="24" r="14" fill="#ffd9b8" stroke="#d9b48f" stroke-width="2"/>';
      /* 躯干（驼背时前倾） */
      s += '<path d="M42,40 L56,50 L56,92 L28,92 L28,50 Z" fill="#5fb3d4" stroke="#3d8ca8" stroke-width="2.2"/>';
      /* 腿 */
      s += '<rect x="30" y="92" width="9" height="30" rx="3" fill="#4a5563"/>';
      s += '<rect x="45" y="92" width="9" height="30" rx="3" fill="#4a5563"/>';
      /* 报警弧线（检测到不良坐姿时亮） */
      s += '<path d="M64,30 a18,18 0 0 1 0,32" stroke="#ffb3ac" stroke-width="2.4" fill="none"/>';
      s += '<circle cx="70" cy="46" r="7" fill="#e05a4e"/>';
      s += '<text x="70" y="50" font-size="9" fill="#fff" text-anchor="middle" font-family="sans-serif">!</text>';
      return s;
    },
    label: function () { return '坐姿检测'; }
  };

  /* ============================================================
   * 八年级新增情景
   * ============================================================ */

  /* 智能停车场（对应「智能停车场_发送端 / 接收端」） */
  SCENES.parking2 = {
    name: '智能停车场',
    items: [
      { k: 'road', x: 60, y: 330 },
      { k: 'parkingSpot', x: 120, y: 190 },
      { k: 'parkingSpot', x: 268, y: 190 },
      { k: 'parkingSpot', x: 416, y: 190 },
      { k: 'streetLamp', x: 660, y: 180 },
      { k: 'streetTree', x: 720, y: 300 },
      { k: 'stopSign', x: 96, y: 300 }
    ],
    devices: ['ultrasonic', 'camera', 'ledModule']
  };

  /* 智能货架自动售货（对应「智能货架自动售货」） */
  SCENES.vending = {
    name: '智能货架',
    items: [
      { k: 'shelf', x: 180, y: 200 },
      { k: 'counter', x: 500, y: 380 },
      { k: 'trashBin', x: 640, y: 360 },
      { k: 'plant', x: 380, y: 320 },
      { k: 'streetLamp', x: 660, y: 160 }
    ],
    devices: ['rfid', 'ledModule', 'servo']
  };

  /* 山体滑坡自动监测（对应「山体滑坡自动监测_发送端 / 接收端」） */
  SCENES.landslide = {
    name: '山体滑坡监测',
    items: [
      { k: 'hillside', x: 300, y: 230 },
      { k: 'streetTree', x: 130, y: 300 },
      { k: 'streetTree', x: 200, y: 340 },
      { k: 'counter', x: 640, y: 380 },
      { k: 'streetLamp', x: 700, y: 170 }
    ],
    devices: ['dht', 'soil', 'mqtt', 'ledModule']
  };

  /* 跌倒自动远程求助（对应「跌倒自动远程求助」系列） */
  SCENES.fallhelp = {
    name: '跌倒远程求助',
    items: [
      { k: 'desk', x: 220, y: 380 },
      { k: 'person', x: 420, y: 300 },
      { k: 'person', x: 560, y: 306 },
      { k: 'bench', x: 660, y: 380 },
      { k: 'plant', x: 120, y: 330 },
      { k: 'schoolBuilding', x: 90, y: 120 }
    ],
    devices: ['mqtt', 'ledModule', 'servo']
  };

  /* 共享单车（对应「从主题接收消息：共享单车/方向」） */
  SCENES.bikeshare = {
    name: '共享单车',
    items: [
      { k: 'road', x: 60, y: 320 },
      { k: 'bike', x: 200, y: 280 },
      { k: 'bike', x: 380, y: 300 },
      { k: 'bike', x: 560, y: 276 },
      { k: 'stopSign', x: 700, y: 250 },
      { k: 'streetTree', x: 130, y: 190 }
    ],
    devices: ['car', 'mqtt', 'ledModule']
  };

  /* 点餐服务（对应「厨师端 / 学生端」） */
  SCENES.ordering = {
    name: '点餐服务',
    items: [
      { k: 'diningTable', x: 220, y: 300 },
      { k: 'diningTable', x: 500, y: 300 },
      { k: 'counter', x: 360, y: 130 },
      { k: 'kettle', x: 250, y: 90 },
      { k: 'person', x: 160, y: 380 },
      { k: 'person', x: 560, y: 384 }
    ],
    devices: ['mqtt', 'ledModule', 'servo']
  };

  /* 磁场与卫星定位实验（对应「体验磁场传感器 / 卫星定位功能」） */
  SCENES.navig = {
    name: '磁场与定位',
    items: [
      { k: 'compass', x: 250, y: 250 },
      { k: 'satellite', x: 560, y: 130 },
      { k: 'desk', x: 180, y: 400 },
      { k: 'window', x: 90, y: 80 },
      { k: 'plant', x: 640, y: 330 },
      { k: 'streetTree', x: 720, y: 280 }
    ],
    devices: ['magnetic', 'gps']
  };

  /* ============================================================
   * 六年级新增情景（对应 参考资料/示例py格式/六年级 的 27 个示例）
   * ============================================================ */

  /* 护眼台灯（可调色温护眼灯 / 护眼灯自动调节亮度） */
  SCENES.eyecare = {
    name: '护眼灯调节',
    items: [
      { k: 'studyDesk', x: 300, y: 340 },
      { k: 'eyeLamp', x: 250, y: 280 },
      { k: 'lightSensor', x: 420, y: 300 },
      { k: 'wallSwitch', x: 470, y: 220 },
      { k: 'plant', x: 660, y: 300 }
    ],
    devices: ['lightExt', 'rgbStrip']
  };

  /* 书房学习桌（示例⑤「光线感应台灯」用；scene key 必须是 study） */
  /* 第五十四轮：这里原本带 `devices: ['lightExt']`。
     它是「无本地缓存时的默认情景」，于是**刚打开网站就凭空多出一个光线传感器**，
     设备区一上来就不是空的，学生还没动手就先有一台设备、还要手工去连线。
     改成不带设备：默认打开是干净的空工程；需要光线传感器的示例/教材活动
     自己声明 devices（示例⑤、护眼灯活动等），applyScene 不会再额外补。
     舞台上那个 lightSensor 图案保留 —— 它只是书房场景的装饰元素。 */
  SCENES.study = {
    name: '书房学习桌',
    items: [
      { k: 'desk', x: 300, y: 340 },
      { k: 'lamp', x: 210, y: 280 },
      { k: 'books', x: 330, y: 300 },
      { k: 'pot', x: 400, y: 290 },
      { k: 'wallSwitch', x: 480, y: 230 },
      { k: 'window', x: 110, y: 100 },
      { k: 'lightSensor', x: 350, y: 250 }
    ],
    devices: []
  };

  /* 坐姿监控（时间提醒器 / 坐姿监控器示例） */
  SCENES.posture = {
    name: '坐姿监控',
    items: [
      { k: 'studyDesk', x: 320, y: 330 },
      { k: 'posturePerson', x: 320, y: 210 },
      { k: 'deskLamp', x: 210, y: 290 },
      { k: 'ultraSensor', x: 430, y: 250 },
      { k: 'wallSwitch', x: 500, y: 190 }
    ],
    devices: ['ultrasonic', 'rgbStrip']
  };

  /* 洗衣机（模拟洗衣机控制过程） */
  SCENES.washer = {
    name: '洗衣机模拟',
    items: [
      { k: 'washer', x: 260, y: 300 },
      { k: 'trashCan', x: 520, y: 320 },
      { k: 'window', x: 90, y: 90 },
      { k: 'plant', x: 660, y: 300 }
    ],
    devices: ['ledModule']
  };

  /* 智能喂养（定时自动投喂器 / 按量自动投喂器） */
  SCENES.feeder = {
    name: '自动投喂',
    items: [
      { k: 'feeder', x: 300, y: 290 },
      { k: 'trashCan', x: 520, y: 330 },
      { k: 'ultraSensor', x: 420, y: 300 },
      { k: 'servoArm', x: 380, y: 230 },
      { k: 'plant', x: 660, y: 300 }
    ],
    devices: ['servo', 'ultrasonic']
  };

  /* 电子围栏（电子围栏系统） */
  SCENES.fence = {
    name: '电子围栏',
    items: [
      { k: 'fencePost', x: 150, y: 260 },
      { k: 'fencePost', x: 640, y: 260 },
      { k: 'streetTree', x: 400, y: 180 },
      { k: 'road', x: 60, y: 380 },
      { k: 'crosswalk', x: 400, y: 380 },
      { k: 'pedestrian', x: 320, y: 330 }
    ],
    devices: ['ir', 'ledModule']
  };

  /* 节能风扇（节能风扇 / 声光控灯） */
  SCENES.energy = {
    name: '节能风扇',
    items: [
      { k: 'energyFan', x: 320, y: 280 },
      { k: 'studyDesk', x: 560, y: 340 },
      { k: 'lightSensor', x: 200, y: 220 },
      { k: 'micSensor', x: 240, y: 320 },
      { k: 'window', x: 100, y: 90 }
    ],
    devices: ['fan', 'lightExt', 'mic']
  };

  /* 智能孵化（自动孵蛋箱） */
  SCENES.incubate = {
    name: '自动孵蛋箱',
    items: [
      { k: 'incubator', x: 300, y: 300 },
      { k: 'dhtSensor', x: 440, y: 270 },
      { k: 'heater', x: 180, y: 300 },
      { k: 'wallSwitch', x: 500, y: 200 }
    ],
    devices: ['dht', 'relay']
  };

  /* 声光贺卡（声光贺卡） */
  SCENES.greetcard = {
    name: '声光贺卡',
    items: [
      { k: 'greetCard', x: 300, y: 300 },
      { k: 'studyDesk', x: 480, y: 350 },
      { k: 'dcMotor', x: 200, y: 320 },
      { k: 'rgbStrip', x: 620, y: 200 },
      { k: 'plant', x: 680, y: 330 }
    ],
    devices: ['motor', 'rgbStrip', 'ledModule']
  };

  ZKB.SceneLib = {
    LIB: LIB, SCENES: SCENES, GRAD_DEFS: GRAD_DEFS,
    keys: function () { return Object.keys(LIB); },
    byCat: function (cat) {
      return Object.keys(LIB).filter(function (k) { return LIB[k].cat === cat; });
    },
    cats: function () {
      ensureThumbs();
      var s = {};
      Object.keys(LIB).forEach(function (k) { s[LIB[k].cat] = 1; });
      /* 分类展示顺序：生活物品 → 智能硬件 → 交通 → 校园 → 机器人 → 场景 */
      var ORDER = ['生活物品', '智能硬件', '交通', '校园', '机器人', '场景'];
      return Object.keys(s).sort(function (a, b) {
        var ia = ORDER.indexOf(a), ib = ORDER.indexOf(b);
        return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
      });
    },
    thumbOf: function (k) { ensureThumbs(); return LIB[k] && LIB[k].thumb ? LIB[k].thumb() : ''; },
    ensureThumbs: ensureThumbs
  };

})(window);