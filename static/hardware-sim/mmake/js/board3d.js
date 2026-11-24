/* ============================================================
 * board3d.js —— 虚拟仿真：掌控板 3D 模型 + 拓展硬件 3D 模型库
 *
 * 实现方式：CSS 3D transform（perspective + rotateX/rotateY），
 * 元件全部由 SVG 构成 —— 矢量、可缩放不失真、无需 WebGL。
 * 板子可翻转查看正面 / 背面（元件标注与官方资料图一致）。
 *
 * 拓展硬件的 3D 模型见下方 MODELS 表；硬件的连接与连线
 * 移至「硬件连接」弹窗（wirelib.js）承载。
 * ============================================================ */
(function (global) {
  'use strict';
  var ZKB = global.ZKB || (global.ZKB = {});
  var SVGNS = 'http://www.w3.org/2000/svg';

  var host = null, wireSvg = null, devLayer = null;
  var flip = false;            // false=正面, true=背面
  var flipped = false;         // 是否已翻转

  /* ============================================================
   * 拓展硬件 3D 模型库（依据 DFRobot 资料）
 * 每个模型返回一个 {label, kind, size, thumb}：
 *   thumb —— 用于「硬件连接」弹窗与拓展库的缩略渲染
 *   kind  —— 接口类型（决定连线颜色）
 * 采用纯 CSS 立体造型 + 阴影，矢量缩放不失真。
 * ============================================================ */

  /* 通用外壳：黑色 PCB + 金手指排针 */
  function pcb(w, h, opt) {
    opt = opt || {};
    return '<div class="m3d pcb' + (opt.round ? ' round' : '') + '" style="width:' + w + 'px;height:' + h + 'px' +
      (opt.bg ? ';background:' + opt.bg : '') + '">' +
      (opt.inner || '') +
      (opt.pins === false ? '' :
        '<div class="m3d-pins' + (opt.pinsUp ? ' up' : '') + '">' +
        '<i></i><i></i><i></i>' + (opt.pins4 ? '<i></i>' : '') + '</div>') +
      '</div>';
  }
  function led(cls) { return '<span class="m3d-led ' + (cls || '') + '"></span>'; }
  function hdr(n, cls) {
    var s = '<div class="m3d-hdr ' + (cls || '') + '">';
    for (var i = 0; i < n; i++) s += '<i></i>';
    return s + '</div>';
  }

  var MODELS = {
    /* ---- 传感器 ---- */
    dht: {
      label: '温湿度', kind: 'digital', size: 84,
      thumb: function () {
        return pcb(62, 52, {
          bg: '#3f4a58',
          inner: '<div class="m3d-grid"></div><div class="m3d-dht-face">' +
            '<span class="m3d-dht-lcd">25°C<br>55%</span></div>' + led('on'),
          pins: 3
        });
      }
    },
    ultrasonic: {
      label: '超声波', kind: 'digital', size: 92,
      thumb: function () {
        return pcb(64, 46, {
          bg: '#2f3740', pins: 4,
          inner: '<div class="m3d-us-l"></div><div class="m3d-us-r"></div>' +
            '<div class="m3d-us-wave"></div>'
        });
      }
    },
    servo: {
      label: '9g 舵机', kind: 'pwm', size: 82,
      thumb: function () {
        return pcb(60, 50, {
          bg: '#8a939e', pins: 3,
          inner: '<div class="m3d-servo-body"></div><div class="m3d-servo-horn"></div>'
        });
      }
    },
    ir: {
      label: '红外接收', kind: 'digital', size: 76,
      thumb: function () {
        return pcb(56, 40, {
          bg: '#23282e', pins: 3,
          inner: '<div class="m3d-ir-eye"></div><div class="m3d-ir-eye"></div>' + led()
        });
      }
    },
    irTx: {
      label: '红外发射', kind: 'digital', size: 62,
      thumb: function () {
        return pcb(44, 34, {
          bg: '#1f242a', pins: 3,
          inner: '<div class="m3d-led ir"></div><div class="m3d-ir-eye"></div>'
        });
      }
    },
    irRx: {
      label: '红外接收头', kind: 'digital', size: 62,
      thumb: function () {
        return pcb(44, 34, {
          bg: '#2b3038', pins: 3,
          inner: '<div class="m3d-ir-dom"></div>'
        });
      }
    },
    lightExt: {
      label: '光线传感器', kind: 'analog', size: 72,
      thumb: function () {
        return pcb(52, 44, {
          bg: '#8a939e', pins: 3,
          inner: '<div class="m3d-photo"></div><div class="m3d-lcd-mini"></div>'
        });
      }
    },
    soil: {
      label: '土壤湿度', kind: 'analog', size: 86,
      thumb: function () {
        return pcb(46, 62, {
          bg: '#3a414c', pins: 3,
          inner: '<div class="m3d-soil-fork"></div><div class="m3d-soil-dirt"></div>'
        });
      }
    },
    tracker: {
      label: '巡线&光感', kind: 'digital', size: 96,
      thumb: function () {
        return pcb(72, 48, {
          bg: '#1f242a', pins: 5,
          inner: '<div class="m3d-trk-line"></div><div class="m3d-trk-line"></div>' +
            '<div class="m3d-trk-led"></div><div class="m3d-photo sm"></div>'
        });
      }
    },
    color: {
      label: '颜色传感器', kind: 'i2c', size: 82,
      thumb: function () {
        return pcb(58, 46, {
          bg: '#2b3038', pins: 4,
          inner: '<div class="m3d-color-lens"></div><div class="m3d-led"></div>'
        });
      }
    },
    gravity: {
      label: 'AS7341 颜色', kind: 'i2c', size: 78,
      thumb: function () {
        return pcb(54, 42, {
          bg: '#3d2f5c', pins: 4,
          inner: '<div class="m3d-color-lens"></div><div class="m3d-lcd-mini"></div>'
        });
      }
    },
    angle: {
      label: '角度传感器', kind: 'analog', size: 76,
      thumb: function () {
        return pcb(52, 52, {
          bg: '#2f3740', round: true, pins: 3,
          inner: '<div class="m3d-angle-dial"><i></i></div>'
        });
      }
    },
    powerMeter: {
      label: '数字功率计', kind: 'i2c', size: 88,
      thumb: function () {
        return pcb(64, 50, {
          bg: '#1b3a52', pins: 4,
          inner: '<div class="m3d-meter-lcd">2.4V<br>0.3A</div>' +
            '<div class="m3d-meter-bar"><i></i></div>'
        });
      }
    },
    pm25: {
      label: 'PM2.5', kind: 'digital', size: 96,
      thumb: function () {
        return pcb(70, 52, {
          bg: '#3a414c', pins: 5,
          inner: '<div class="m3d-slot"></div><div class="m3d-fan-mini"></div>' + led()
        });
      }
    },
    baro: {
      label: '气压传感器', kind: 'i2c', size: 68,
      thumb: function () {
        return pcb(46, 40, {
          bg: '#3a6ea5', pins: 4,
          inner: '<div class="m3d-chip"></div>'
        });
      }
    },
    camera: {
      label: 'AI 摄像头', kind: 'i2c', size: 92,
      thumb: function () {
        return pcb(62, 48, {
          bg: '#20252b', pins: 4,
          inner: '<div class="m3d-cam"><i></i></div><div class="m3d-cam-led"></div>'
        });
      }
    },
    mic: {
      label: '麦克风', kind: 'analog', size: 62,
      thumb: function () {
        return pcb(46, 46, {
          bg: '#37474f', round: true, pins: 3,
          inner: '<div class="m3d-grille"></div>'
        });
      }
    },

    /* ---- 执行器 / 模块 ---- */
    ledModule: {
      label: 'LED 模块', kind: 'digital', size: 74,
      thumb: function () {
        return pcb(52, 44, {
          bg: '#2b3038', pins: 3,
          inner: '<div class="m3d-bulb"></div><div class="m3d-lcd-mini"></div>'
        });
      }
    },
    rgbStrip: {
      label: 'RGB 灯带', kind: 'digital', size: 92,
      thumb: function () {
        return pcb(66, 36, {
          bg: '#1a1d21', pins: 3,
          inner: '<div class="m3d-strip"><i></i><i></i><i></i><i></i><i></i></div>'
        });
      }
    },
    relay: {
      label: '继电器模块', kind: 'digital', size: 88,
      thumb: function () {
        return pcb(66, 54, {
          bg: '#1f3a5c', pins: 4,
          inner: '<div class="m3d-relay"></div>' +
            '<div class="m3d-terminal"><i></i><i></i><i></i></div>' + led('on')
        });
      }
    },
    fan: {
      label: '风扇模块', kind: 'pwm', size: 94,
      thumb: function () {
        return pcb(60, 60, {
          bg: '#5aa8cc', round: true, pins: 3,
          inner: '<div class="m3d-fan-blades"><i></i></div><div class="m3d-fan-hub"></div>'
        });
      }
    },
    heater: {
      label: '加热元件', kind: 'pwm', size: 80,
      thumb: function () {
        return pcb(54, 54, {
          bg: '#e0552c', round: true, pins: false,
          inner: '<div class="m3d-coil"></div>'
        });
      }
    },
    pump: {
      label: '水泵', kind: 'pwm', size: 84,
      thumb: function () {
        return pcb(56, 50, {
          bg: '#2f9e8e', pins: 3,
          inner: '<div class="m3d-pump-in"></div><div class="m3d-drip"></div>'
        });
      }
    },
    motor: {
      label: '减速电机', kind: 'pwm', size: 86,
      thumb: function () {
        return '<div class="m3d pcb" style="width:60px;height:52px;background:#cf7a16;border-radius:8px">' +
          '<div class="m3d-motor"></div>' + hdr(2, 'side') + '</div>';
      }
    },
    car: {
      label: '小车', kind: 'digital', size: 118,
      thumb: function () {
        return '<div class="m3d pcb" style="width:76px;height:44px;background:#3d7ea6;border-radius:6px">' +
          '<div class="m3d-car-win"></div><div class="m3d-wheel"></div><div class="m3d-wheel"></div>' +
          '<div class="m3d-wheel"></div><div class="m3d-wheel"></div></div>';
      }
    },
    robot: {
      label: '机器人', kind: 'motor', size: 110,
      thumb: function () {
        return '<div class="m3d pcb" style="width:64px;height:58px;background:#f2f5f9;' +
          'border:2px solid #b9c2ce;border-radius:12px;position:relative">' +
          /* AI 摄像头双眼 */
          '<div style="position:absolute;left:12px;top:12px;width:12px;height:12px;' +
          'border-radius:50%;background:#1d2530;box-shadow:22px 0 0 #1d2530"></div>' +
          '<div style="position:absolute;left:15px;top:15px;width:6px;height:6px;' +
          'border-radius:50%;background:#4a90d9;box-shadow:22px 0 0 #4a90d9"></div>' +
          /* 地面颜色传感器（巡线探头） */
          '<div style="position:absolute;left:24px;top:32px;width:16px;height:7px;' +
          'border-radius:3px;background:#3a4048"></div>' +
          '<div style="position:absolute;left:29px;top:33px;width:6px;height:5px;' +
          'border-radius:2px;background:#43c46f"></div>' +
          /* 轮子 */
          '<div class="m3d-wheel" style="left:6px;bottom:-7px"></div>' +
          '<div class="m3d-wheel" style="right:6px;bottom:-7px;left:auto"></div></div>';
      }
    },
    button: {
      label: '按钮模块', kind: 'digital', size: 74,
      thumb: function () {
        return pcb(52, 46, {
          bg: '#2f9e8e', pins: 3,
          inner: '<div class="m3d-bigbtn"></div>'
        });
      }
    },
    /* 第三十六轮：人体红外与 MP3 模块的 3D 缩略图 */
    pir: {
      label: '人体红外', kind: 'digital', size: 74,
      thumb: function () {
        return pcb(52, 46, {
          bg: '#2b3038', pins: 3,
          inner: '<div class="m3d-lcd-mini"></div>'
        });
      }
    },
    mp3: {
      label: 'MP3 模块', kind: 'digital', size: 84,
      thumb: function () {
        return pcb(60, 44, {
          bg: '#1f3a5c', pins: 4,
          inner: '<div class="m3d-strip"><i></i><i></i><i></i><i></i></div>'
        });
      }
    },
    remote: {
      label: '红外遥控器', kind: 'digital', size: 92,
      thumb: function () {
        return pcb(58, 54, {
          bg: '#2b3038', pins: 3,
          inner: '<div class="m3d-remote"><i></i><i></i><i></i><i></i></div>'
        });
      }
    },
  };

  /* ============================================================
   * 第三十二轮：补齐剩余 18 个拓展硬件的 3D 模型
   * 设备库有 40 项，MODELS 原来只有 22 个，缺的这批在
   * 「硬件连接」里只能显示一个灰底占位框，看不出设备长什么样。
   * 造型依据 DFRobot 各模块资料页的实物图，全部用 SVG + CSS 拼装。
   * ============================================================ */
  function board(w, h, inner) {
    return '<div class="m3d m3d-board-flat" style="width:' + w + 'px;height:' + h + 'px">' +
      inner + '</div>';
  }

  MODELS.traceCar = {
    label: '巡线小车', kind: 'pwm', size: 116,
    thumb: function () {
      return board(100, 66,
        /* 底部双驱轮 + 前面两个万向轮 */
        '<div class="m3d-wheel" style="left:10px;top:14px"></div>' +
        '<div class="m3d-wheel" style="left:64px;top:14px"></div>' +
        '<div class="m3d-motor" style="left:12px;top:40px"></div>' +
        '<div class="m3d-motor" style="left:70px;top:40px"></div>' +
        /* 车体 */
        '<div class="m3d-pcb" style="position:absolute;left:8px;top:6px;width:84px;height:22px;' +
        'border-radius:4px;background:#1f6fb2;box-shadow:0 2px 0 rgba(0,0,0,.35)"></div>' +
        /* 底部两路巡线传感器 */
        '<div class="m3d-trk-line" style="left:26px"></div>' +
        '<div class="m3d-trk-line" style="left:46px"></div>' +
        '<div class="m3d-trk-led" style="left:36px"></div>');
    }
  };

  MODELS.radio = {
    label: '无线广播', kind: 'digital', size: 70,
    thumb: function () {
      return board(58, 44,
        '<svg width="30" height="24" viewBox="0 0 30 24" style="position:absolute;left:14px;top:8px">' +
        '<path d="M15,22 a13,13 0 0 1 0,-20 a13,13 0 0 1 0,20z" fill="none" stroke="#7fb3d5" stroke-width="2"/>' +
        '<path d="M15,22 a8,8 0 0 1 0,-13 a8,8 0 0 1 0,13z" fill="none" stroke="#7fb3d5" stroke-width="2"/>' +
        '<circle cx="15" cy="15" r="2.4" fill="#7fb3d5"/></svg>');
    }
  };
  MODELS.wifi = {
    label: 'WiFi', kind: 'digital', size: 74,
    thumb: function () {
      return board(60, 46,
        '<svg width="34" height="24" viewBox="0 0 34 24" style="position:absolute;left:13px;top:6px">' +
        '<path d="M2,18 a24,24 0 0 1 30,0" fill="none" stroke="#3dcf8e" stroke-width="2.4"/>' +
        '<path d="M8,20 a15,15 0 0 1 18,0" fill="none" stroke="#3dcf8e" stroke-width="2.4"/>' +
        '<circle cx="17" cy="21" r="2.6" fill="#3dcf8e"/></svg>');
    }
  };
  MODELS.ntp = {
    label: '网络授时', kind: 'digital', size: 70,
    thumb: function () {
      return board(56, 42,
        '<div class="m3d-lcd-mini">08:30</div>' +
        '<svg width="16" height="16" viewBox="0 0 16 16" style="position:absolute;right:6px;top:5px">' +
        '<circle cx="8" cy="8" r="6.4" fill="none" stroke="#7fb3d5" stroke-width="1.6"/>' +
        '<path d="M8,4.4 V8 L10.6,9.8" stroke="#7fb3d5" stroke-width="1.6" fill="none" stroke-linecap="round"/></svg>');
    }
  };
  MODELS.mqtt = {
    label: 'MQTT 物联网', kind: 'digital', size: 84,
    thumb: function () {
      return board(68, 52,
        '<svg width="44" height="22" viewBox="0 0 44 22" style="position:absolute;left:12px;top:8px">' +
        '<path d="M4,18 a15,15 0 0 1 36,0" fill="none" stroke="#7c5cd6" stroke-width="2.2"/>' +
        '<path d="M13,19 a8,8 0 0 1 18,0" fill="none" stroke="#7c5cd6" stroke-width="2.2"/>' +
        '<circle cx="22" cy="19" r="2.6" fill="#7c5cd6"/>' +
        '<rect x="17" y="2" width="10" height="7" rx="1.5" fill="#7c5cd6" opacity=".7"/></svg>');
    }
  };
  MODELS.asr = {
    label: 'WiFi语音识别', kind: 'digital', size: 78,
    thumb: function () {
      return board(62, 48,
        '<div class="m3d-grille" style="left:8px;top:8px;width:24px;height:32px"></div>' +
        '<svg width="22" height="26" viewBox="0 0 22 26" style="position:absolute;right:10px;top:10px">' +
        '<rect x="8" y="3" width="6" height="12" rx="3" fill="#5fb3d4"/>' +
        '<path d="M4,12 a7,7 0 0 0 14,0" fill="none" stroke="#5fb3d4" stroke-width="2"/>' +
        '<path d="M11,19 L11,23 L7,23" stroke="#5fb3d4" stroke-width="2" fill="none" stroke-linecap="round"/></svg>');
    }
  };
  MODELS.weather = {
    label: '天气', kind: 'digital', size: 84,
    thumb: function () {
      return board(68, 52,
        '<svg width="40" height="34" viewBox="0 0 40 34" style="position:absolute;left:14px;top:8px">' +
        '<circle cx="13" cy="13" r="6" fill="#ffd76b"/>' +
        '<path d="M15,29 a6.5,6.5 0 0 1 1,-13 a8.5,8.5 0 0 1 16,3 a6,6 0 0 1 -2,10z" ' +
        'fill="#e8eef5" stroke="#7c8ea3" stroke-width="1.8"/></svg>');
    }
  };
  MODELS.magnetic = {
    label: '磁场传感器', kind: 'i2c', size: 68,
    thumb: function () {
      return pcb(46, 44, {
        bg: '#37474f', pins: 4,
        inner: '<svg width="30" height="26" viewBox="0 0 30 26" style="position:absolute;left:8px;top:9px">' +
          '<path d="M15,24 a9,9 0 0 1 0,-22" fill="none" stroke="#e05a4e" stroke-width="2.4" stroke-linecap="round"/>' +
          '<path d="M15,24 a9,9 0 0 0 0,-22" fill="none" stroke="#5fb3d4" stroke-width="2.4" stroke-linecap="round"/>' +
          '<text x="15" y="6" font-size="8" fill="#cfd8e3" text-anchor="middle" font-family="sans-serif">N</text>' +
          '</svg>'
      });
    }
  };
  MODELS.gps = {
    label: '卫星定位', kind: 'digital', size: 88,
    thumb: function () {
      return board(70, 52,
        '<svg width="34" height="28" viewBox="0 0 34 28" style="position:absolute;left:18px;top:4px">' +
        '<path d="M17,26 L11,10 A9,9 0 0 1 23,10 Z" fill="#5fb3d4" stroke="#3d8ca8" stroke-width="1.8"/>' +
        '<circle cx="17" cy="13" r="4" fill="#e8eef5"/></svg>' +
        '<div class="m3d-hdr m3d-4pin"></div>');
    }
  };
  MODELS.qrcode = {
    label: '二维码', kind: 'digital', size: 70,
    thumb: function () {
      return board(56, 48,
        '<svg width="36" height="36" viewBox="0 0 36 36" style="position:absolute;left:10px;top:6px">' +
        '<rect width="36" height="36" fill="#fff"/>' +
        '<g fill="#1b2028">' +
        '<rect x="3" y="3" width="9" height="9"/><rect x="24" y="3" width="9" height="9"/>' +
        '<rect x="3" y="24" width="9" height="9"/>' +
        '<rect x="15" y="4" width="3" height="3"/><rect x="15" y="10" width="3" height="3"/>' +
        '<rect x="4" y="15" width="3" height="3"/><rect x="10" y="15" width="3" height="3"/>' +
        '<rect x="16" y="15" width="3" height="3"/><rect x="22" y="16" width="3" height="3"/>' +
        '<rect x="29" y="16" width="3" height="3"/><rect x="15" y="21" width="3" height="3"/>' +
        '<rect x="21" y="22" width="3" height="3"/><rect x="27" y="24" width="3" height="3"/>' +
        '<rect x="15" y="29" width="3" height="3"/><rect x="22" y="30" width="3" height="3"/>' +
        '</g></svg>');
    }
  };
  MODELS.rfid = {
    label: 'RFID 射频卡', kind: 'i2c', size: 76,
    thumb: function () {
      return board(60, 46,
        '<div class="m3d-coil"></div>' +
        '<svg width="22" height="26" viewBox="0 0 22 26" style="position:absolute;left:32px;top:10px">' +
        '<rect x="2" y="5" width="18" height="16" rx="2.5" fill="#f6f7f9" stroke="#c2c8d0" stroke-width="1.6"/>' +
        '<rect x="5" y="8" width="6" height="6" rx="1" fill="#8aa0b8"/>' +
        '<rect x="13" y="8" width="4" height="10" rx="1" fill="#c2c8d0"/></svg>');
    }
  };
  MODELS.speech2 = {
    label: '离线语音识别', kind: 'digital', size: 82,
    thumb: function () {
      return board(66, 48,
        '<div class="m3d-grille" style="left:8px;top:10px;width:22px;height:28px"></div>' +
        '<div class="m3d-chip" style="left:34px;top:12px"></div>' +
        '<div class="m3d-led on" style="left:52px;top:14px"></div>' +
        '<div class="m3d-hdr m3d-4pin"></div>');
    }
  };

  function deviceModel(id) {
    var m = MODELS[id];
    if (!m) return null;
    return m;
  }
  /* 供拓展库 / 素材库使用 */
  ZKB.devMeta3D = MODELS;

  /* ============================================================
   * 掌控板正反面 SVG（严格对照 DFRobot 资料图绘制）
   * 正面：A 字母在按键左侧、B 字母在按键右侧；屏幕与麦克风整体上移
   * 背面：按资料图重绘，无长横线、无 PYTHON 金手指
   * ============================================================ */
  /* ============================================================
   * RGB 指示灯：金色外框 + 灯珠 + 光晕
   * 结构：金色外框（金属座）→ 黑色灯座 → 外层光晕 → 柔光环 → 灯珠本体
   * 三层同圆心，syncRGB 只改 fill / opacity，光晕即自动生效。
   * ============================================================ */
  var RGB_CY = 45;
  /* 第三十七轮：三颗灯珠拉开间距（原来 23 单位，视觉上挤成一团） */
  var RGB_CX = [158, 191, 224];
  function rgbLamp(id, cx) {
    /* 绘制顺序（后画的在上层）：
         1. 金色外框（灯珠的金属座，第三十七轮新增）
         2. 黑色灯座（最下）
         3. 大光晕   ← 必须压在灯座之上，否则被黑色遮罩盖住看不见
         4. 柔光环
         5. 灯珠本体 + 高光
       这样亮灯时光晕是"浮"在黑色灯座上方的，模拟灯光溢出的效果。 */
    return '<g class="b3-rgb-lamp" data-lamp="' + id + '">' +
      /* 1) 金色外框（灯珠金属座） */
      '<circle cx="' + cx + '" cy="' + RGB_CY + '" r="9.6" fill="#e8c24a"/>' +
      '<circle cx="' + cx + '" cy="' + RGB_CY + '" r="9.6" fill="none" ' +
      'stroke="#a8862a" stroke-width="1"/>' +
      /* 2) 灯座（黑底，最下层） */
      '<circle cx="' + cx + '" cy="' + RGB_CY + '" r="7.4" fill="#0b0e11" ' +
      'stroke="#39414b" stroke-width="1"/>' +
      /* 3) 最外层光晕（大而淡，营造发光溢出；位于灯座之上） */
      '<circle class="b3-rgb-glow" id="' + id + '-glow" cx="' + cx + '" cy="' + RGB_CY +
      '" r="13" fill="#0e1114" opacity="0"/>' +
      /* 4) 中层柔光 */
      '<circle class="b3-rgb-halo" id="' + id + '-halo" cx="' + cx + '" cy="' + RGB_CY +
      '" r="7" fill="#0e1114" opacity="0"/>' +
      /* 5) 灯珠本体（最上层，最亮） */
      '<circle class="b3-rgb-core" id="' + id + '" cx="' + cx + '" cy="' + RGB_CY +
      '" r="5.6" fill="#15181c"/>' +
      /* 6) 白炽亮点（亮灯时灯芯发白，模拟 LED 刺眼的高光，最上层） */
      '<circle class="b3-rgb-hot" id="' + id + '-hot" cx="' + cx + '" cy="' + RGB_CY +
      '" r="3" fill="#ffffff" opacity="0"/>' +
      /* 高光点（让灯珠看起来是球体而非平贴色块） */
      '<circle cx="' + (cx - 2) + '" cy="' + (RGB_CY - 2) + '" r="1.8" fill="#fff" opacity=".28"/>' +
      '</g>';
  }

  function faceFront() {
    return '' +
      /* ---- PCB ---- */
      '<rect x="0" y="0" width="420" height="260" rx="16" fill="#1b1e22"/>' +
      '<rect x="3" y="3" width="414" height="254" rx="14" fill="#22262b"/>' +
      /* TYPE-C（上边缘中偏左） */
      '<rect x="168" y="0" width="44" height="11" rx="3" fill="#9aa3ad"/>' +
      '<rect x="175" y="2.5" width="30" height="7" rx="2" fill="#454f5a"/>' +
      /* ---- A 键：字母在键的左侧 ---- */
      '<text x="42" y="40" text-anchor="middle" fill="#f0f3f6" font-size="22" font-weight="bold">A</text>' +
      '<g class="b3-pressable" data-act="btn" data-key="A" title="按键 A">' +
      '<circle cx="82" cy="32" r="24" fill="transparent"/>' +
      /* 大金圈 + 中心白孔 + 周围小孔（资料图为金色圆盘） */
      '<circle cx="82" cy="32" r="19" fill="#e8c24a"/>' +
      '<circle cx="82" cy="32" r="14" fill="#f5f7f9"/>' +
      '<circle cx="82" cy="32" r="14" fill="none" stroke="#c9a83c" stroke-width="1.5"/>' +
      ringHoles(82, 32, 17, 16, 10) +
      '<circle cx="82" cy="32" r="15.5" fill="none" stroke="#a8862a" stroke-width="1" opacity=".7"/>' +
      '</g>' +
      /* ---- B 键：字母在键的右侧 ---- */
      '<g class="b3-pressable" data-act="btn" data-key="B" title="按键 B">' +
      '<circle cx="338" cy="32" r="24" fill="transparent"/>' +
      '<circle cx="338" cy="32" r="19" fill="#e8c24a"/>' +
      '<circle cx="338" cy="32" r="14" fill="#f5f7f9"/>' +
      '<circle cx="338" cy="32" r="14" fill="none" stroke="#c9a83c" stroke-width="1.5"/>' +
      ringHoles(338, 32, 17, 16, 10) +
      '<circle cx="338" cy="32" r="15.5" fill="none" stroke="#a8862a" stroke-width="1" opacity=".7"/>' +
      '</g>' +
      '<text x="378" y="40" text-anchor="middle" fill="#f0f3f6" font-size="22" font-weight="bold">B</text>' +
      /* ---- 中间：两个指示灯柱 + RGB 三灯 ---- */
      '<rect x="176" y="6" width="4" height="10" rx="2" fill="#7d868f"/>' +
      '<rect x="176" y="22" width="4" height="10" rx="2" fill="#7d868f"/>' +
      '<rect x="228" y="6" width="4" height="10" rx="2" fill="#7d868f"/>' +
      '<rect x="228" y="22" width="4" height="10" rx="2" fill="#7d868f"/>' +
      /* RGB 三灯：加大灯珠 + 金色外框 + 外圈光晕（第三十七轮：间距拉开到 33） */
      rgbLamp('b3-rgb-0', RGB_CX[0]) +
      rgbLamp('b3-rgb-1', RGB_CX[1]) +
      rgbLamp('b3-rgb-2', RGB_CX[2]) +
      /* ---- 麦克风（左）与光线传感器（右）：位于屏幕两侧，整体上移 ---- */
      '<g class="b3-pressable" data-act="sensor" data-k="sound" title="麦克风（点击调节声音）">' +
      /* 透明热区：把可点击范围扩大到 46×46，便于点中 */
      '<rect x="10" y="72" width="48" height="48" rx="10" fill="transparent"/>' +
      '<circle cx="34" cy="96" r="13" fill="none" stroke="#d8dde2" stroke-width="2"/>' +
      '<circle cx="34" cy="96" r="4" fill="none" stroke="#d8dde2" stroke-width="1.6"/>' +
      '<path d="M28,100 q6,7 12,0" fill="none" stroke="#d8dde2" stroke-width="1.6"/>' +
      '<path d="M24,96 v2 a10,10 0 0 0 20,0 v-2" fill="none" stroke="#d8dde2" stroke-width="1.6"/>' +
      '<circle cx="34" cy="126" r="12" fill="none" stroke="#d8dde2" stroke-width="2.4"/>' +
      '</g>' +
      '<g class="b3-pressable" data-act="sensor" data-k="light" title="光线传感器（点击调节光线）">' +
      /* 透明热区：把可点击范围扩大到 56×56 */
      '<rect x="360" y="88" width="54" height="56" rx="12" fill="transparent"/>' +
      '<circle cx="386" cy="112" r="7" fill="none" stroke="#d8dde2" stroke-width="1.6"/>' +
      '<circle cx="386" cy="112" r="2.4" fill="none" stroke="#d8dde2" stroke-width="1.2"/>' +
      '<path d="M386,100 v-6 M386,124 v6 M374,112 h-6 M398,112 h6" stroke="#d8dde2" stroke-width="1.4"/>' +
      '<rect x="373" y="130" width="26" height="9" rx="2" fill="#e2603c"/>' +
      '<rect x="373" y="132" width="13" height="5" fill="#f5f7f9"/>' +
      '</g>' +
      /* ---- TFT 屏幕（白色外框 + 黑色屏面），上移 ---- */
      '<rect x="66" y="66" width="288" height="128" rx="4" fill="#f4f6f8"/>' +
      '<rect x="76" y="76" width="268" height="108" rx="3" fill="#05070a"/>' +
      /* 品牌 + 二维码 + 编号（屏幕下方白框内） */
      '<text x="86" y="182" fill="#2b3138" font-size="15" font-weight="bold">掌控板</text>' +
      '<g opacity=".55"><rect x="164" y="170" width="15" height="15" fill="none" stroke="#2b3138" stroke-width="1.1"/>' +
      '<rect x="166.5" y="172.5" width="3.4" height="3.4" fill="#2b3138"/>' +
      '<rect x="173" y="172.5" width="3.4" height="3.4" fill="#2b3138"/>' +
      '<rect x="166.5" y="179" width="3.4" height="3.4" fill="#2b3138"/>' +
      '<rect x="173" y="179" width="3.4" height="3.4" fill="#2b3138"/></g>' +
      '<text x="186" y="178" fill="#2b3138" font-size="11" font-family="monospace">01234</text>' +
      '<text x="186" y="189" fill="#2b3138" font-size="11" font-family="monospace">56789</text>' +
      /* ---- 圆形金色焊盘（屏幕下方居中）→ 第二十五轮改为「语音小圆点」----
         点击弹出语音小窗口：语音转文字 + 文字转语音 */
      voiceDot(210, 210, '#f5f7f9', '#2b3138') +
      /* ---- 触摸焊盘 P Y T H O N ---- */
      touchPads() +
      /* 无线 / 蓝牙图标（右侧丝印） */
      btIcon(392, 214);
  }

  /* 金圈周围的焊点（资料图中的小圆孔） */
  function ringHoles(cx, cy, r, n, holeR) {
    var s = '';
    for (var i = 0; i < n; i++) {
      var a = (i / n) * Math.PI * 2;
      s += '<circle cx="' + (cx + Math.cos(a) * r).toFixed(1) +
        '" cy="' + (cy + Math.sin(a) * r).toFixed(1) + '" r="' + holeR +
        '" fill="#a8862a" opacity=".85"/>';
    }
    return s;
  }

  /* 蓝牙图标（丝印） */
  function btIcon(x, y) {
    return '<g transform="translate(' + x + ',' + y + ')" opacity=".85" ' +
      'stroke="#c9d1d9" stroke-width="1.5" fill="none">' +
      '<path d="M0,-7 L5,-3 L0,1 M0,7 L5,3 L0,-1 M0,-7 v14"/></g>';
  }

  /* 触摸焊盘：P Y T H O N（金色方块 + 黑色小圆点） */
  /* ============================================================
   * 第二十五轮：语音小圆点
   * 原来这里是一个纯装饰的金色圆形焊盘（屏幕下方居中），
   * 现在把它改成可点击的语音入口：点击弹出语音小窗口
   *（语音转文字 + 文字转语音）。正面带 id（用于高亮），
   * 背面同样可点但不重复 id。
   * ============================================================ */
  function voiceDot(cx, cy, innerFill, ink) {
    return '<g class="b3-pressable b3-voice-dot" data-act="voice" id="board-voice-dot"' +
      ' title="语音（点击打开语音转文字 / 文字转语音）">' +
      /* 透明热区：把可点击范围扩大到 44×44，便于点中 */
      '<rect x="' + (cx - 22) + '" y="' + (cy - 22) + '" width="44" height="44" rx="10" fill="transparent"/>' +
      '<circle cx="' + cx + '" cy="' + cy + '" r="11" fill="#e8c24a"/>' +
      '<circle cx="' + cx + '" cy="' + cy + '" r="7.5" fill="' + innerFill + '"/>' +
      /* 麦克风剪影 */
      '<g fill="none" stroke="' + ink + '" stroke-width="1.3" stroke-linecap="round">' +
      '<path d="M' + (cx - 3) + ',' + (cy - 2.4) + 'v1.8a3,3 0 0 0 6,0v-1.8"/>' +
      '<path d="M' + (cx - 4.4) + ',' + (cy - 0.4) + 'a4.4,4.4 0 0 0 8.8,0"/>' +
      '<line x1="' + cx + '" y1="' + (cy + 4) + '" x2="' + cx + '" y2="' + (cy + 5.6) + '"/></g>' +
      '</g>';
  }

  function touchPads() {
    var letters = ['P', 'Y', 'T', 'H', 'O', 'N'];
    return letters.map(function (t, i) {
      var x = 24 + i * 66;
      return '<g class="b3-pressable" data-act="touch" data-key="' + t + '" title="触摸 ' + t + '">' +
        '<rect x="' + x + '" y="228" width="56" height="30" rx="3" fill="#e8c24a"/>' +
        '<circle cx="' + (x + 10) + '" cy="236" r="3.2" fill="#1b1e22"/>' +
        '<text x="' + (x + 30) + '" y="252" text-anchor="middle" fill="#1b1e22" ' +
        'font-size="17" font-weight="bold" font-family="monospace">' + t + '</text></g>';
    }).join('');
  }

  /* ============================================================
   * 背面：按资料图重绘（PCB 元件 + 底部 0/1/2/V/G 排针）
   * 不含长横线、不含 PYTHON 金手指
   * ============================================================ */
  function faceBack() {
    var s = '';
    /* PCB */
    s += '<rect x="0" y="0" width="420" height="260" rx="16" fill="#141619"/>';
    s += '<rect x="3" y="3" width="414" height="254" rx="14" fill="#1a1d21"/>';
    /* 顶部两处黑色接口（电池座 / 排线座） */
    s += '<rect x="14" y="4" width="40" height="18" rx="2" fill="#0d0f11"/>';
    s += '<rect x="366" y="4" width="40" height="18" rx="2" fill="#0d0f11"/>';
    /* TYPE-C（中上） */
    s += '<rect x="176" y="0" width="68" height="20" rx="4" fill="#b6bec6"/>';
    s += '<rect x="186" y="4" width="48" height="13" rx="2" fill="#8a939c"/>';
    s += '<rect x="196" y="7" width="28" height="7" rx="1.5" fill="#5c656e"/>';

    /* 左侧 VCC / GND 丝印与黄色测试点 */
    s += '<text x="16" y="60" fill="#c9d1d9" font-size="9" font-weight="bold">VCC</text>';
    s += '<text x="16" y="188" fill="#c9d1d9" font-size="9" font-weight="bold">GND</text>';
    s += '<rect x="12" y="68" width="14" height="30" rx="3" fill="#e8c24a"/>';
    s += '<rect x="12" y="150" width="14" height="30" rx="3" fill="#e8c24a"/>';

    /* RESET 按键 */
    s += '<rect x="34" y="66" width="34" height="24" rx="3" fill="#e8e8ea" stroke="#9aa3ad"/>';
    s += '<text x="51" y="82" text-anchor="middle" fill="#2b3138" font-size="8" font-weight="bold">RESET</text>';

    /* 喇叭 */
    s += '<rect x="34" y="104" width="30" height="30" rx="3" fill="#4a525c"/>';
    s += speaker(49, 119);

    /* 蜂鸣器（左侧小圆 + 丝印） */
    s += '<circle cx="96" cy="62" r="8" fill="none" stroke="#c9d1d9" stroke-width="1.4"/>';
    s += speaker(96, 62, 1);
    s += '<text x="112" y="60" fill="#8a939e" font-size="6">蜂鸣器</text>';
    s += '<text x="112" y="70" fill="#8a939e" font-size="6">0d</text>';

    /* 麦克风（右上丝印） */
    s += speaker(392, 62, 1);
    s += '<text x="376" y="78" text-anchor="middle" fill="#8a939e" font-size="6">MIC</text>';

    /* 顶部两枚金色圆焊盘（对应正面的 A/B 键背面） */
    s += '<circle cx="82" cy="32" r="16" fill="#e8c24a"/>';
    s += '<circle cx="82" cy="32" r="11" fill="#1a1d21"/>';
    s += ringHoles(82, 32, 14, 14, 1.6);
    s += '<circle cx="338" cy="32" r="16" fill="#e8c24a"/>';
    s += '<circle cx="338" cy="32" r="11" fill="#1a1d21"/>';
    s += ringHoles(338, 32, 14, 14, 1.6);

    /* 各类贴片元件（用小方块矩阵模拟丝印特征） */
    s += smd(126, 18, 26, 12) + smd(160, 18, 18, 12) + smd(240, 18, 18, 12) + smd(268, 18, 26, 12);
    s += smd(112, 46, 16, 10) + smd(136, 46, 12, 10) + smd(120, 72, 20, 12) + smd(152, 72, 14, 10);
    s += smd(112, 100, 14, 14) + smd(134, 100, 14, 14) + smd(160, 100, 20, 12);
    s += smd(78, 120, 30, 12) + smd(78, 142, 22, 12) + smd(112, 142, 16, 10);
    s += smd(196, 84, 34, 22) + smd(240, 84, 26, 18) + smd(276, 84, 18, 18);
    s += smd(196, 118, 22, 16) + smd(226, 118, 16, 16) + smd(252, 116, 14, 14);
    s += smd(196, 146, 28, 12) + smd(232, 146, 18, 12) + smd(258, 144, 16, 16);
    s += smd(300, 120, 20, 20) + smd(300, 150, 16, 16) + smd(330, 130, 22, 14);
    s += smd(78, 168, 24, 12) + smd(112, 168, 14, 12) + smd(136, 166, 12, 14);
    s += smd(300, 168, 26, 12) + smd(334, 166, 18, 14);

    /* 主芯片（带丝印） */
    s += '<rect x="196" y="112" width="0" height="0" fill="none"/>';
    s += '<text x="196" y="188" fill="#8a939e" font-size="6">Z</text>' +
      '<text x="176" y="198" fill="#8a939e" font-size="6">X</text>' +
      '<text x="216" y="198" fill="#8a939e" font-size="6">Y</text>';
    s += '<circle cx="210" cy="182" r="10" fill="none" stroke="#c9d1d9" stroke-width="1.2"/>';
    s += '<path d="M210,172 v20 M200,182 h20" stroke="#c9d1d9" stroke-width="1"/>';

    /* 品牌丝印 + 版本 */
    s += '<text x="30" y="205" fill="#e8ebef" font-size="16" font-weight="bold">掌控板</text>';
    s += '<rect x="96" y="194" width="34" height="14" rx="3" fill="#2b3138" stroke="#5a636e"/>';
    s += '<text x="113" y="205" text-anchor="middle" fill="#c9d1d9" font-size="9" font-weight="bold">2.0.1</text>';
    /* 圆形金色焊盘 → 语音小圆点（与正面同心，背面同样可点；去掉 id 避免与正面重复） */
    s += voiceDot(210, 210, '#1a1d21', '#c9d1d9')
      .replace(' id="board-voice-dot"', '')
      .replace('class="b3-pressable b3-voice-dot"', 'class="b3-pressable b3-voice-dot b3-face-back-voice"');
    /* 圆形认证图标（丝印） */
    s += '<circle cx="272" cy="202" r="10" fill="none" stroke="#c9d1d9" stroke-width="1.3"/>';
    s += '<path d="M268,206 l4,-8 l4,8" fill="none" stroke="#c9d1d9" stroke-width="1.3"/>';

    /* 底部引脚排针 0 / 1 / 2 / V / G（金色长条 + 编号） */
    s += pinStrip();
    return s;
  }

  /* 贴片元件（矩形焊盘） */
  function smd(x, y, w, h) {
    return '<rect x="' + x + '" y="' + y + '" width="' + w + '" height="' + h +
      '" rx="1.5" fill="#2e343b" stroke="#4a525c" stroke-width="1"/>';
  }

  /* 喇叭图标 */
  function speaker(x, y, sc) {
    var k = sc || 1;
    return '<g transform="translate(' + x + ',' + y + ') scale(' + k + ')" ' +
      'fill="none" stroke="#c9d1d9" stroke-width="1.6" stroke-linecap="round">' +
      '<path d="M-7,-3 h4 l5,-4 v14 l-5,-4 h-4 Z"/>' +
      '<path d="M6,-4 q3,4 0,8"/><path d="M9,-7 q5,7 0,14"/></g>';
  }

  /* 底部引脚排针 0 / 1 / 2 / V / G（资料图：金色长条 + 编号 + 圆形焊孔） */
  function pinStrip() {
    var labels = ['0', '1', '2', 'V', 'G'];
    var out = '';
    labels.forEach(function (t, i) {
      var x = 16 + i * 78;
      out += '<rect x="' + x + '" y="224" width="70" height="34" rx="3" fill="#e8c24a"/>';
      /* 每段上的多排小孔 */
      for (var r = 0; r < 3; r++) {
        for (var c = 0; c < 7; c++) {
          out += '<circle cx="' + (x + 7 + c * 9) + '" cy="' + (229 + r * 8) +
            '" r="1.7" fill="#1a1d21"/>';
        }
      }
      out += '<text x="' + (x + 52) + '" y="254" text-anchor="middle" fill="#1a1d21" ' +
        'font-size="15" font-weight="bold" font-family="monospace">' + t + '</text>';
    });
    return out;
  }
  /* ============================================================
   * 2D 模式的引脚标注层
   *
   * 依据官方资料「mPython掌控板_pin_define.jpg」的元件布局：
   *   正面左上 = 按键 A，左上偏中 = EXT / GND / OLED / 麦克风，
   *   右上 = 按键 B 与声音传感器，中间 = RGB LED，
   *   底部金手指 = P Y T H O N 触摸焊盘。
   * 用绝对定位的标签覆盖在板面上（只在 2D 模式显示）。
   * ============================================================ */
  function pinLabelsHTML() {
    /* 全部放在板面内部的空白处（左侧麦克风区、右侧光线区、
       RGB 灯与屏幕之间的空隙、底部焊盘右侧），
       避免溢出到面板外被裁剪。 */
    var items = [
      { t: '按键 A', x: 1.5, y: 5.5, w: 11, a: 'r' },
      { t: 'RGB LED', x: 30, y: 19, w: 18, a: 'c' },
      { t: '按键 B', x: 76, y: 5.5, w: 11, a: 'l' },
      { t: '麦克风', x: 1.5, y: 33, w: 10, a: 'r' },
      { t: '光线传感器', x: 70, y: 38, w: 20, a: 'l' },
      { t: '语音小圆点', x: 44, y: 79, w: 16, a: 'c' }
    ];
    return items.map(function (it) {
      return '<span class="b3-pin-label' + (it.a === 'r' ? ' r' : (it.a === 'l' ? ' l' : ' c')) +
        '" style="left:' + it.x + '%;top:' + it.y + '%;width:' + it.w + '%">' +
        '<i></i>' + it.t + '</span>';
    }).join('');
  }

  /* ============================================================
   * 构建 3D / 2D 场景
   *
   * 第三十七轮：新增 2D / 3D 切换。
   *   3D —— 立体视角（透视 + 可拖拽旋转 + 翻转看背面）
   *   2D —— 平面正视图（无透视，附引脚标注层，便于对照官方引脚定义图）
   *
   * 两套视图共用同一份 SVG（faceFront / faceBack）与同一块 OLED 画布，
   * 因此切换时不需要重建画布，屏幕内容也不会丢。
   * ============================================================ */
  function build() {
    host = document.getElementById('sim-board-wrap');
    if (!host) { console.warn('未找到 #sim-board-wrap，跳过 3D 板构建'); return; }
    /* 高度加高：留出「PYTHON」金手指字母的显示空间（虚拟仿真主视图） */
    host.innerHTML =
      '<div class="b3-scene" id="b3-scene">' +
      /* 板子（3D，可翻转）——板下不再显示硬件区，改由「硬件连接」弹窗承载 */
      '<div class="b3-board-wrap" id="b3-board-wrap">' +
      '<div class="b3-board" id="b3-board">' +
      '<div class="b3-face b3-front" id="b3-front">' +
      '<svg viewBox="0 0 420 260" class="b3-svg">' + faceFront() + '</svg>' +
      '<canvas id="b3-oled" width="128" height="64" class="b3-oled"></canvas>' +
      '</div>' +
      '<div class="b3-face b3-back" id="b3-back">' +
      '<svg viewBox="0 0 420 260" class="b3-svg">' + faceBack() + '</svg>' +
      '</div>' +
      '<div class="b3-edge"></div>' +
      '</div>' +
      /* 2D 模式专用：引脚标注层（对照官方「引脚定义」图）。
         放在 .b3-board 之外 —— .b3-face 有圆角裁剪，标签放里面会被切掉 */
      '<div class="b3-pins" id="b3-pins">' + pinLabelsHTML() + '</div>' +
      '</div>' +
      /* 控制条 */
      '<div class="b3-tools">' +
      '<span class="b3-viewswitch" title="切换 2D 平面图 / 3D 立体图">' +
      '<button class="b3-vs-btn active" id="b3-v-3d" data-view="3d">3D</button>' +
      '<button class="b3-vs-btn" id="b3-v-2d" data-view="2d">2D</button>' +
      '</span>' +
      '<button class="b3-btn" id="b3-flip" title="翻转查看正反面">🔄 翻转</button>' +
      '<button class="b3-btn" id="b3-shake" title="模拟摇晃掌控板">📳 摇晃</button>' +
      '<select id="b3-shake-mode" class="b3-select" title="选择摇晃方式">' +
      SHAKE_MODES.map(function (m) {
        return '<option value="' + m.id + '">' + m.name + '</option>';
      }).join('') +
      '</select>' +
      /* 第四十二轮：右侧的「正面 / 背面」和「上下摇晃（Y 轴）」提示已隐藏。
         翻转状态与摇晃方式都能从按钮本身看出来，
         这些文字占了位置，把控制条挤成两行。
         元素保留（display:none），JS 仍会更新它们，需要时可恢复显示。 */
      '<span class="b3-hint b3-hint-off" id="b3-side">正面</span>' +
      '<span class="b3-hint b3-hint-off" id="b3-shake-hint"></span>' +
      '</div>' +
      '</div>' +
      /* 语音小窗口（第二十五轮：点屏幕下方的语音小圆点弹出）。
         必须挂在 .b3-scene 之外——场景有 perspective，fixed 子元素会继承 3D 变换
         上下文导致 fixed 坐标被扭曲。配色靠 .b3-scene 之外单独覆盖。 */
      (ZKB.SimBoard && ZKB.SimBoard.voicePanelHTML ? ZKB.SimBoard.voicePanelHTML() : '');

    wireSvg = null;
    devLayer = null;
    loadShakeMode();
    bindBoardEvents();
    setShakeMode(shakeMode);
    /* 恢复上次选择的 2D / 3D 视图 */
    var savedView = ZKB.Store && ZKB.Store.getLocal(VIEW_KEY);
    setView(savedView === '2d' ? '2d' : '3d');
  }

  /* ============================================================
   * 交互
   * ============================================================ */
  function bindBoardEvents() {
    var flipBtn = document.getElementById('b3-flip');
    if (flipBtn) flipBtn.addEventListener('click', function () {
      flipped = !flipped;
      var b = document.getElementById('b3-board');
      if (b) b.classList.toggle('flipped', flipped);
      var side = document.getElementById('b3-side');
      if (side) side.textContent = flipped ? '背面' : '正面';
      /* 第四十二轮：右侧的「正面 / 背面」提示已隐藏，
         改把当前朝向写进按钮的 title 与文字里，信息不丢。 */
      if (flipBtn) {
        flipBtn.textContent = flipped ? '🔄 翻回正面' : '🔄 翻转';
        flipBtn.title = flipped ? '当前看的是背面，点一下翻回正面' : '翻转查看正反面';
      }
      /* 翻转后重画接口高亮（位置随视角变化） */
      setTimeout(function () {
        if (ZKB.WireLib) ZKB.WireLib.render();
        /* 翻转动画结束后重新贴语音小窗 */
        if (ZKB.SimBoard && ZKB.SimBoard.placeVoicePanel) ZKB.SimBoard.placeVoicePanel();
      }, 420);
    });

    var shakeBtn = document.getElementById('b3-shake');
    if (shakeBtn) shakeBtn.addEventListener('click', doShake);

    /* ============================================================
     * 第三十七轮：2D / 3D 视图切换
     * ============================================================ */
    ['b3-v-3d', 'b3-v-2d'].forEach(function (id) {
      var btn = document.getElementById(id);
      if (!btn) return;
      btn.addEventListener('click', function () {
        setView(btn.getAttribute('data-view'));
      });
    });

    /* 3D 模式：按住板子可拖拽旋转视角 */
    bindDragRotate();

    /* 摇晃方式选择 */
    var shakeSel = document.getElementById('b3-shake-mode');
    if (shakeSel) {
      shakeSel.addEventListener('change', function () {
        setShakeMode(this.value);
        ZKB.toast('摇晃方式：' + currentShake().name);
      });
    }

    /* 按键 / 触摸 / 传感器点击（复用 sim-board 的事件委托） */
    var board = document.getElementById('b3-board');
    if (board) {
      board.addEventListener('mousedown', function (e) {
        var t = e.target.closest ? e.target.closest('.b3-pressable') : null;
        if (!t) return;
        var act = t.getAttribute('data-act');
        if (act === 'btn') {
          var k = t.getAttribute('data-key');
          if (ZKB.SimBoard) ZKB.SimBoard.pressBtn(k, true);
        } else if (act === 'touch') {
          var p = t.getAttribute('data-key');
          if (ZKB.SimBoard) ZKB.SimBoard.pressTouch(p, true);
        } else if (act === 'sensor') {
          if (ZKB.SimBoard) ZKB.SimBoard.openSensorPanel(t.getAttribute('data-k'));
        } else if (act === 'voice') {
          /* 第二十五轮：点语音小圆点 → 切换语音小窗口 */
          if (ZKB.SimBoard) ZKB.SimBoard.toggleVoicePanel();
        }
        e.preventDefault();
      });
      /* 语音小窗口的关闭按钮 */
      var vclose = document.getElementById('voice-close');
      if (vclose) {
        vclose.addEventListener('click', function (e) {
          e.stopPropagation();
          if (ZKB.SimBoard) ZKB.SimBoard.closeVoicePanel();
        });
      }
    }
    document.addEventListener('mouseup', function () {
      ['A', 'B'].forEach(function (k) { if (ZKB.SimBoard) ZKB.SimBoard.pressBtn(k, false); });
      ['P', 'Y', 'T', 'H', 'O', 'N'].forEach(function (k) {
        if (ZKB.SimBoard) ZKB.SimBoard.pressTouch(k, false);
      });
    });

    window.addEventListener('resize', function () {
      if (ZKB.WireLib) ZKB.WireLib.render();
      /* 窗口尺寸变化后重新贴一次语音小窗（它按板子实测位置定位） */
      if (ZKB.SimBoard && ZKB.SimBoard.placeVoicePanel) ZKB.SimBoard.placeVoicePanel();
    });
  }

  /* ============================================================
   * 第三十七轮：2D / 3D 视图切换
   *
   * 3D —— .b3-scene 无 flat 类，保留 perspective + rotateX(12deg)，
   *      板面可以按住拖拽改变视角，也可以翻转看背面。
   * 2D —— 加 .flat 类：去掉透视与倾斜，正面平铺展示，
   *      并显示引脚标注层（对照官方「引脚定义」图）。
   * 两套视图共用同一块 OLED 画布与同一套事件绑定，切换不丢状态。
   * ============================================================ */
  var view = '3d';
  var VIEW_KEY = 'zkb_view_mode_v1';

  function setView(v) {
    view = (v === '2d') ? '2d' : '3d';
    var scene = document.getElementById('b3-scene');
    if (scene) scene.classList.toggle('flat', view === '2d');
    /* 2D 模式下隐藏翻转（背面与平面正视图无意义） */
    var flipBtn = document.getElementById('b3-flip');
    if (flipBtn) flipBtn.style.display = (view === '2d') ? 'none' : '';
    /* 按钮高亮 */
    ['b3-v-3d', 'b3-v-2d'].forEach(function (id) {
      var b = document.getElementById(id);
      if (!b) return;
      b.classList.toggle('active', b.getAttribute('data-view') === view);
    });
    /* 2D 下如果板子是背面状态，先翻回正面 */
    if (view === '2d' && flipped) {
      flipped = false;
      var bd = document.getElementById('b3-board');
      if (bd) bd.classList.remove('flipped');
      var side = document.getElementById('b3-side');
      if (side) side.textContent = '正面';
    }
    /* 记住选择 */
    if (ZKB.Store) ZKB.Store.setLocal(VIEW_KEY, view);
    /* 视角复位 + 重贴语音小窗 */
    applyRotation();
    setTimeout(function () {
      if (ZKB.SimBoard && ZKB.SimBoard.placeVoicePanel) ZKB.SimBoard.placeVoicePanel();
    }, 60);
    return view;
  }

  /* 当前视角（3D 时的旋转角） */
  var rotX = 12, rotY = 0;
  function applyRotation() {
    var wrap = document.getElementById('b3-board-wrap');
    if (!wrap) return;
    if (view === '2d') {
      wrap.style.transform = 'none';
    } else {
      wrap.style.transform = 'rotateX(' + rotX + 'deg) rotateY(' + rotY + 'deg)';
    }
  }

  /* 3D 模式：按住板面拖拽改变视角 */
  function bindDragRotate() {
    var wrap = document.getElementById('b3-board-wrap');
    if (!wrap) return;
    var dragging = false, sx = 0, sy = 0, baseX = 12, baseY = 0, moved = false;
    wrap.addEventListener('mousedown', function (e) {
      if (view === '2d') return;
      /* 点在可交互元件上时不启动拖拽（否则按键按下会同时转视角） */
      if (e.target.closest && e.target.closest('.b3-pressable')) return;
      dragging = true; moved = false;
      sx = e.clientX; sy = e.clientY;
      baseX = rotX; baseY = rotY;
      wrap.style.cursor = 'grabbing';
    });
    document.addEventListener('mousemove', function (e) {
      if (!dragging) return;
      var dx = e.clientX - sx, dy = e.clientY - sy;
      if (!moved && Math.abs(dx) + Math.abs(dy) < 4) return;
      moved = true;
      rotY = baseY + dx * 0.6;
      rotX = Math.max(-60, Math.min(60, baseX - dy * 0.5));
      applyRotation();
      e.preventDefault();
    });
    document.addEventListener('mouseup', function () {
      if (!dragging) return;
      dragging = false;
      wrap.style.cursor = '';
      /* 拖拽结束后重新贴语音小窗 + 重画连线 */
      if (moved) {
        if (ZKB.WireLib) ZKB.WireLib.render();
        if (ZKB.SimBoard && ZKB.SimBoard.placeVoicePanel) ZKB.SimBoard.placeVoicePanel();
      }
    });
    wrap.style.cursor = 'grab';
  }

  /* ============================================================
   * 摇晃动画
   * ============================================================ */

  /* 摇晃动画 */
  /* ============================================================
   * 摇晃方式：可手动选择方向，加速度读数随之变化
   * mode: updown 上下 | leftright 左右 | fwbw 前后 | rotate 旋转 | random 随机
   *
   * 第三十九轮：每个方向都补齐了**视觉**与**加速度**两套参数：
   *   dx / dy  —— 屏幕平移（左右 / 上下）
   *   dz      —— 前后推拉（沿 Z 轴，透视下表现为板子推近 / 拉远）
   *   rz      —— 绕 Z 轴旋转（原地转圈）
   * 之前「前后摇晃」的 dx/dy/rz 全为 0 → 3D 板完全不动，只有数据在变。
   * ============================================================ */
  var SHAKE_MODES = [
    { id: 'updown', name: '上下摇晃', dx: 0, dy: 1, dz: 0, rz: 0, label: 'Y 轴' },
    { id: 'leftright', name: '左右摇晃', dx: 1, dy: 0, dz: 0, rz: 0, label: 'X 轴' },
    { id: 'fwbw', name: '前后摇晃', dx: 0, dy: 0, dz: 1, rz: 0, label: 'Z 轴推拉' },
    { id: 'rotate', name: '旋转晃动', dx: 0, dy: 0, dz: 0, rz: 1, label: 'Z 轴旋转' },
    { id: 'random', name: '随机摇晃', dx: 0, dy: 0, dz: 0, rz: 0, label: '每次方向随机' }
  ];
  var SHAKE_KEY = 'zkb_shake_mode_v1';
  var shakeMode = 'updown';

  function currentShake() {
    return SHAKE_MODES.filter(function (m) { return m.id === shakeMode; })[0] || SHAKE_MODES[0];
  }
  function setShakeMode(id) {
    var m = SHAKE_MODES.filter(function (x) { return x.id === id; })[0];
    if (!m) return null;
    shakeMode = id;
    if (ZKB.Store) ZKB.Store.setLocal(SHAKE_KEY, id);
    /* 同步下拉框 */
    var sel = document.getElementById('b3-shake-mode');
    if (sel) sel.value = id;
    var lbl = document.getElementById('b3-shake-hint');
    if (lbl) lbl.textContent = m.name + '（' + m.label + '）';
    /* 第四十二轮：右侧的摇晃方式提示已隐藏，
       改把方式写进「摇晃」按钮的 title，信息不丢。 */
    var btn = document.getElementById('b3-shake');
    if (btn) btn.title = '模拟摇晃掌控板（当前：' + m.name + '）';
    return m;
  }
  function loadShakeMode() {
    var id = ZKB.Store && ZKB.Store.getLocal(SHAKE_KEY);
    shakeMode = id || 'updown';
  }

  /* ============================================================
   * 第三十九轮：摇晃的「视觉参数」与「加速度参数」由同一份数据生成，
   * 保证两者永远一致（前后摇晃 → 板子前后推拉 + Z 轴冲击；
   * 随机摇晃 → 每次随机挑一个方向，视觉与数据同步变化）。
   * ============================================================ */
  var SHAKE_DIRS = ['updown', 'leftright', 'fwbw', 'rotate'];

  /* 生成一次摇晃的完整参数 */
  function shakeParams(modeId) {
    var m = SHAKE_MODES.filter(function (x) { return x.id === modeId; })[0] || SHAKE_MODES[0];
    var p = { dx: m.dx, dy: m.dy, dz: m.dz, rz: m.rz, dir: m.id };
    if (m.id === 'random') {
      /* 随机挑一个方向，并把各轴的幅度与正负都随机化 */
      var dir = SHAKE_DIRS[Math.floor(Math.random() * SHAKE_DIRS.length)];
      var base = SHAKE_MODES.filter(function (x) { return x.id === dir; })[0];
      p.dir = dir;
      p.dx = base.dx; p.dy = base.dy; p.dz = base.dz; p.rz = base.rz;
      /* 幅度随机 0.6~1.4 倍 */
      var amp = 0.6 + Math.random() * 0.8;
      p.dx *= amp; p.dy *= amp; p.dz *= amp; p.rz *= amp;
      /* 平移类方向随机正负（左右 / 上下 / 前后各往一边） */
      if (p.dx) p.dx *= Math.random() > 0.5 ? 1 : -1;
      if (p.dy) p.dy *= Math.random() > 0.5 ? 1 : -1;
      if (p.dz) p.dz *= Math.random() > 0.5 ? 1 : -1;
    }
    return p;
  }

  /* 摇晃：视觉动画 + 加速度数据同时按所选方式变化 */
  function doShake() {
    var b = document.getElementById('b3-board');
    var m = currentShake();
    var p = shakeParams(m.id);
    if (b) {
      b.classList.remove('shaking');
      void b.offsetWidth;
      b.classList.add('shaking');
      /* 用内联 CSS 变量覆盖默认的晃动幅度：
         dx/dy 屏幕平移、dz 前后推拉、rz 绕 Z 轴旋转 */
      b.style.animation = '';
      b.style.setProperty('--shake-dx', (p.dx * 10) + 'px');
      b.style.setProperty('--shake-dy', (p.dy * 8) + 'px');
      b.style.setProperty('--shake-dz', (p.dz * 26) + 'px');
      b.style.setProperty('--shake-rz', (p.rz * 8) + 'deg');
    }
    /* 把同一份参数传给加速度计算，保证视觉与读数一致 */
    if (ZKB.SimBoard) ZKB.SimBoard.shake(m.id, p);
    var dirName = SHAKE_MODES.filter(function (x) { return x.id === p.dir; })[0];
    var hint = document.getElementById('b3-shake-hint');
    if (hint && dirName) hint.textContent = dirName.name + '（' + dirName.label + '）';
    setTimeout(function () {
      if (b) {
        b.classList.remove('shaking');
        b.style.animation = '';
        /* 第三十九轮：显式复位 transform，确保摇晃后
           板子精确回到初始位置（不残留任何位移 / 旋转） */
        b.style.transform = '';
      }
      /* 复位提示文字为当前选中的方式 */
      var lbl = document.getElementById('b3-shake-hint');
      if (lbl) lbl.textContent = m.name + '（' + m.label + '）';
    }, 800);
  }

  /* ============================================================
   * OLED 同步：把虚拟屏位图画到 3D 板的 TFT 彩屏上
   *
   * 数据源：sim-engine 的虚拟屏画布。3D 板替换了原 2D 看板后，
   * 该画布可能已不存在或尺寸不同，故此处做多来源兜底：
   *   1) 优先取 #b3-oled（3D 板自带画布，sim-engine 直接绘制到这里）
   *   2) 其次取 #oled-canvas（旧 2D 看板遗留）
   * ============================================================ */
  function syncOLED() {
    var dst = document.getElementById('b3-oled');
    if (!dst) return;
    /* 若 3D 板画布即为目标（sim-engine 直接绘制），无需再复制 */
    var src = document.getElementById('oled-canvas');
    if (!src || src === dst) return;
    try {
      var c = dst.getContext('2d');
      if (!c) return;
      c.imageSmoothingEnabled = false;
      c.drawImage(src, 0, 0, dst.width, dst.height);
    } catch (e) { /* 忽略 */ }
  }

  /* 供 sim-engine 使用的虚拟屏画布（在 3D 板内） */
  function oledCanvas() {
    return document.getElementById('b3-oled');
  }

  /* RGB 灯珠同步 */
  function syncRGB() {
    var st = ZKB.state;
    if (!st) return;
    for (var i = 0; i < 3; i++) {
      var id = 'b3-rgb-' + i;
      var dot = document.getElementById(id);
      if (!dot) continue;
      var c = st.rgb.dots[i], br = st.rgb.brightness;
      /* 灯珠本体 = 颜色 × 亮度（亮度积木默认值 80%，所以颜色接近原色） */
      var bl = Math.max(0, Math.min(1, br));
      var r = (c[0] * bl) | 0, g = (c[1] * bl) | 0, b2 = (c[2] * bl) | 0;
      var sum = r + g + b2;
      var lit = sum > 12;
      var col = lit ? 'rgb(' + r + ',' + g + ',' + b2 + ')' : '#0d1013';   /* 未亮：更暗 */

      /* 灯珠本体（最上层）：描边高光让灯珠更"实" */
      dot.setAttribute('fill', col);
      dot.setAttribute('stroke', lit ? 'rgba(255,255,255,.7)' : '#2c333a');

      /* 光晕：亮度控制强弱，尺寸保持小巧（半径 20~26 / 11~14） */
      var kk = lit ? Math.min(1, 0.55 + bl * 0.45) : 0;

      var halo = document.getElementById(id + '-halo');
      if (halo) {
        halo.setAttribute('fill', col);
        halo.setAttribute('opacity', (kk * 0.95).toFixed(3));
        halo.setAttribute('r', (11 + bl * 3).toFixed(1));
      }
      var glow = document.getElementById(id + '-glow');
      if (glow) {
        glow.setAttribute('fill', col);
        glow.setAttribute('opacity', (kk * 0.62).toFixed(3));
        glow.setAttribute('r', (7 + bl * 2).toFixed(1));
      }
      /* 白炽灯芯：0/1/2 号灯珠常亮（未设色时也能看到中心白点，
         设色后叠加在彩色灯珠上，让灯光看起来更亮更刺眼 */
      var hot = document.getElementById(id + '-hot');
      if (hot) hot.setAttribute('opacity', (0.35 + kk * 0.55).toFixed(3));
    }
  }

  /* 掌控板彩灯亮度（0~100）：供舞台台灯联动等外部模块判断「灯是否亮着」 */
  function rgbLitLevel() {
    var s2 = ZKB.state;
    if (!s2 || !s2.rgb || !s2.rgb.dots) return 0;
    var bl = Math.max(0, Math.min(1, s2.rgb.brightness));
    var m = 0;
    for (var i = 0; i < 3; i++) {
      var c2 = s2.rgb.dots[i] || [0, 0, 0];
      m = Math.max(m, c2[0], c2[1], c2[2]);
    }
    return Math.min(100, Math.round(m * bl * 1.2));
  }
  ZKB.rgbLitLevel = rgbLitLevel;

  /* ============================================================
   * 对外接口
   * ============================================================ */
  ZKB.Board3D = {
    build: build,
    /* 硬件模型已移至「硬件连接」弹窗（wirelib.js），此处保留空实现以兼容调用 */
    renderDevices: function () { },
    syncOLED: syncOLED,
    /* 供 sim-engine 获取虚拟屏画布 */
    oledCanvas: oledCanvas,
    syncRGB: syncRGB,
    doShake: doShake,
    modelOf: deviceModel,
    /* 摇晃方式 */
    shakeModes: SHAKE_MODES,
    shakeMode: currentShake,
    setShakeMode: setShakeMode,
    /* 第三十九轮：生成摇晃参数（2D 看板的「摇晃」按钮也复用，
       保证两个视图的方向与加速度一致） */
    shakeParams: shakeParams,
    /* 第三十七轮：2D / 3D 视图切换 */
    setView: setView,
    getView: function () { return view; },
    flip: function () {
      var b = document.getElementById('b3-flip');
      if (b) b.click();
    }
  };

})(window);