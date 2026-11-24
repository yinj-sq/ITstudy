/* ============================================================
 * wirelib.js —— 硬件连接：3D 掌控板 + 掌控IO扩展板 + 拖拽连线
 *
 * 参考 DFRobot MBT0014 掌控IO扩展板资料：
 *   IO口(3Pin)   : P0 P1 P2 P8 P9 P12 P13 P14 P15 P16（掌控板不支持 P12）
 *   I2C 接口 ×3  : 3.3V / 5V（各含 GND / SCL / SDA）
 *   引脚金手指   : 0 1 2 3V GND
 *   触摸金手指×6 : P Y T H O N
 *   电机驱动 ×2  : M1+ M1- M2+ M2-（不占额外引脚）
 *   供电         : microUSB 电源口 / PH2.0 电池口 / 电源开关 / 电源指示灯
 *   蜂鸣器      ×1 带开关（掌控模式下需关闭，占用 P0）
 *   尺寸         : 80mm × 47mm
 *
 * 连接规则：把硬件拖到扩展板（或掌控板）的对应接口上，
 *           连上之后该硬件才会参与虚拟仿真的工作。
 * ============================================================ */
(function (global) {
  'use strict';
  var ZKB = global.ZKB || (global.ZKB = {});
  var $ = function (id) { return document.getElementById(id); };

  /* ============================================================
   * 接口定义（严格对照参考图 / MBT0014 技术规格）
   *
   * 布局（对照参考图）：
   *   左侧    ：IO 口 10 个 3Pin（P0 P1 P2 P8 P9 P12 P13 P14 P15 P16）
   *             三列排针 GND 灰 / 3V3 红 / P 绿，P12 掌控板不支持（标 ×）
   *   中间靠左：I2C 口 3 个 4Pin（两个 3.3V + 一个 5V，SDA SCL GND VCC）
   *   中间    ：掌控板插槽 + 金手指 GND 3V 2 1 0，掌控板默认插在上面
   *   右下角  ：M 口两组绿色端子（M1+ M1- M2+ M2-）
   *   其余    ：蜂鸣器（P0，带开关）、USB 电源、电池口、电源开关、
   *             触摸金手指 P/Y/T/H/O/N（底部）
   * ============================================================ */
  var EXP_W = 400, EXP_H = 235;

  /* ---- 1. IO 口：仅 10 个，三列 3Pin 排在扩展板最左侧 ---- */
  var IO_NAMES = ['P0', 'P1', 'P2', 'P8', 'P9',
    'P12', 'P13', 'P14', 'P15', 'P16'];
  var IO_PINS = IO_NAMES.map(function (n, i) {
    return {
      pin: n, group: 'io', pins: 3, label: n,
      /* 按参考图：10 个 IO 口竖排在扩展板左侧（三列排针的中间列中心） */
      x: 22, y: 26 + i * 20.5,
      /* P12 掌控板不支持，标记为不可用 */
      unusable: (n === 'P12')
    };
  });
  /* 掌控板实际不支持的引脚（程序中不可选） */
  var UNUSABLE_PINS = { P12: 1 };

  /* ---- 2. I2C 口：3 个 4Pin，排在扩展板中间靠左 ---- */
  var I2C_PINS = [
    { pin: 'I2C_3V3_A', group: 'i2c', pins: 4, volt: '3V3', x: 122, y: 103, label: '3V3' },
    { pin: 'I2C_3V3_B', group: 'i2c', pins: 4, volt: '3V3', x: 122, y: 131, label: '3V3' },
    { pin: 'I2C_5V', group: 'i2c', pins: 4, volt: '5V', x: 122, y: 159, label: '5V' }
  ];

  /* ---- 3. M 口：两组 2Pin 绿色端子，排在扩展板右下角 ---- */
  var MOTOR_PINS = [
    { pin: 'M1+', group: 'motor', pins: 2, pair: 'M1', x: 370, y: 146, label: 'M1+' },
    { pin: 'M1-', group: 'motor', pins: 2, pair: 'M1', x: 370, y: 170, label: 'M1-' },
    { pin: 'M2+', group: 'motor', pins: 2, pair: 'M2', x: 370, y: 194, label: 'M2+' },
    { pin: 'M2-', group: 'motor', pins: 2, pair: 'M2', x: 370, y: 218, label: 'M2-' }
  ];

  /* ---- 4. 金手指：GND 3V 2 1 0（扩展板中间插槽，掌控板默认插在这里） ---- */
  var GOLD_PINS = [
    { pin: 'GND', group: 'gold', pins: 1, board: 'G', x: 156, y: 30, label: 'GND' },
    { pin: '3V', group: 'gold', pins: 1, board: 'V', x: 178, y: 30, label: '3V' },
    { pin: '2', group: 'gold', pins: 1, board: '2', x: 200, y: 30, label: '2' },
    { pin: '1', group: 'gold', pins: 1, board: '1', x: 222, y: 30, label: '1' },
    { pin: '0', group: 'gold', pins: 1, board: '0', x: 244, y: 30, label: '0' }
  ];

  /* 金手指 ↔ 掌控板 对应关系（用于自动连线提示） */
  var GOLD_TO_BOARD = { GND: 'G', '3V': 'V', '2': '2', '1': '1', '0': '0' };

  /* 硬件引脚数（决定可连哪类接口） */
  var DEVICE_PINS = {
    dht: 3, ultrasonic: 3, servo: 3, ir: 3, heater: 2, car: 2, motor: 2, pump: 3,
    color: 4, camera: 4, mic: 3, lightExt: 3, soil: 3, pm25: 5, baro: 4,
    button: 3, fan: 3, tracker: 5, gravity: 4, powerMeter: 4, angle: 3,
    irTx: 3, irRx: 3, ledModule: 3, relay: 4, rgbStrip: 3, remote: 3,
    robot: 2,   /* 机器人：2Pin 电机驱动，接 M 口其中一组（M1± 或 M2±） */
    traceCar: 2,  /* 巡线小车：电机驱动 2Pin + 传感器（循迹器/超声波），电机接 M 口一组 */
    /* 第二十六轮：WiFi / 天气 / 网络时间 / MQTT 为 2Pin 网络模块，
       候选接口 P13 / P14 / P15 任选一个（写在 DEVICE_PORT 里） */
    wifi: 2, weather: 2, ntp: 2, mqtt: 2,
    /* 第二十九轮：八年级新增硬件
       magnetic / qrcode 为板载器件（磁力机在 I2C 上，二维码纯软件），给 4Pin 表示走 I2C 口；
       gps / speech2 是 UART 模块，2Pin 接 IO 口；rfid 是 I2C 设备，4Pin。 */
    magnetic: 4, qrcode: 4, gps: 2, speech2: 2, rfid: 4
  };

  /* M 口成对（第十三轮）：M1+/M1- 为一组、M2+/M2- 为一组。
     2pin 设备（电机类）必须同时连接同组的两个接口，
     连接记录统一存为组名（'M1' / 'M2'），占用该组两个物理端口。 */
  var M_PAIR = { 'M1+': 'M1', 'M1-': 'M1', 'M2+': 'M2', 'M2-': 'M2' };
  var M_PAIR_PORTS = { M1: ['M1+', 'M1-'], M2: ['M2+', 'M2-'] };
  function pairOf(port) { return M_PAIR[port] || null; }
  /* 一条连接记录实际占用的物理端口（M 组连接占两个） */
  function connPorts(c) { return M_PAIR_PORTS[c.port] || [c.port]; }
  /* 某物理端口是否已被占用（exceptDev：拉线重连时排除设备自身） */
  function portOccupied(pin, exceptDev) {
    return conns.some(function (c) {
      return c.devId !== exceptDev && connPorts(c).indexOf(pin) >= 0;
    });
  }

  /* ============================================================
   * 硬件 → 接口族
   *
   * 拓展板只有四类接口，不同的硬件能接的口也不同：
   *   io    任意 IO 口（GND / 3V3 / P，3Pin）—— 大多数传感器与执行器
   *   i2c   三个 I2C 口（4Pin）—— I2C 类传感器
   *   motor M 口（2Pin 电机驱动）—— 电机 / 加热 / 机器人
   *   net   网络 / 串口模块固定走 P13 / P14 / P15
   *
   * 「推荐接口」只用于菜单排序与提示，不再限制可连范围：
   * 现在任何引脚数匹配的拓展板接口都可以接（见 compatiblePorts）。
   * ============================================================ */
  var DEVICE_IFACE = {
    /* IO 口族（3Pin：GND / 3V3 / P） */
    dht: 'io', ultrasonic: 'io', servo: 'io', ir: 'io', pump: 'io',
    mic: 'io', lightExt: 'io', soil: 'io', pm25: 'io', button: 'io',
    fan: 'io', tracker: 'io', angle: 'io', irTx: 'io', irRx: 'io',
    ledModule: 'io', rgbStrip: 'io', remote: 'io',
    gps: 'net', speech2: 'net',
    /* I2C 口族（4Pin） */
    color: 'i2c', camera: 'i2c', powerMeter: 'i2c', gravity: 'i2c',
    baro: 'i2c', magnetic: 'i2c', qrcode: 'i2c', rfid: 'i2c', relay: 'i2c',
    /* M 口族（2Pin 电机驱动） */
    heater: 'motor', car: 'motor', motor: 'motor', robot: 'motor', traceCar: 'motor',
    /* 网络 / 串口模块（固定 P13 / P14 / P15） */
    wifi: 'net', weather: 'net', ntp: 'net', mqtt: 'net'
  };
  /* 板载器件（无需接线即可工作）：二维码、磁力计、板载无线等 */
  var NO_WIRE = { qrcode: 1, magnetic: 1, radio: 1, asr: 1, expboard: 1 };

  /* 硬件 → 推荐接口（仅用于菜单排序与「推荐」提示） */
  var DEVICE_PORT = {
    dht: ['P1', 'P2', 'P0'], ultrasonic: ['P9', 'P8'], servo: ['P0'], ir: ['P14'],
    heater: ['M1', 'M2'], car: ['M1', 'M2'], motor: ['M1', 'M2'], pump: ['P15'],
    robot: ['M1', 'M2'], traceCar: ['M1', 'M2'],
    color: ['I2C_5V', 'I2C_3V3_A'], camera: ['I2C_3V3_A'], mic: ['P0'], lightExt: ['P16'],
    soil: ['P2'], pm25: ['P13'], baro: ['I2C_5V'], button: ['P8'], fan: ['P16'],
    /* DFRobot 新增硬件 */
    tracker: ['P13', 'P14'], powerMeter: ['I2C_5V', 'I2C_3V3_A'], angle: ['P2'],
    irTx: ['P16'], irRx: ['P15'], ledModule: ['P13'], relay: ['I2C_3V3_A', 'P0'],
    gravity: ['I2C_5V', 'I2C_3V3_A'], rgbStrip: ['P13'], remote: ['P15'],
    /* 第二十六轮：WiFi / 天气（及配套的网络时间、MQTT）支持 P13 / P14 / P15 任意一个 */
    wifi: ['P13', 'P14', 'P15'], weather: ['P13', 'P14', 'P15'],
    ntp: ['P13', 'P14', 'P15'], mqtt: ['P13', 'P14', 'P15'],
    /* 第二十九轮：八年级新增硬件 */
    magnetic: ['I2C_5V', 'I2C_3V3_A'], qrcode: ['I2C_5V', 'I2C_3V3_A'],
    gps: ['P13', 'P15'], speech2: ['P13', 'P15'], rfid: ['I2C_5V', 'I2C_3V3_A']
  };
  /* 过滤掉扩展板上不存在的接口（防止推荐到P3/P4/P5 等） */
  (function () {
    var valid = {};
    allPorts().forEach(function (p) { if (!UNUSABLE_PINS[p.pin]) valid[p.pin] = 1; });
    /* 4Pin 设备统一可选三个 I2C 接口（3.3V A / 3.3V B / 5V），顺序固定 */
    var I2C_ALL = I2C_PINS.map(function (p) { return p.pin; });
    Object.keys(DEVICE_PORT).forEach(function (k) {
      DEVICE_PORT[k] = DEVICE_PORT[k].filter(function (pn) {
        /* M 口用组名（M1 / M2），不在物理端口表里，单独放行 */
        return valid[pn] || M_PAIR_PORTS[pn];
      });
      if (!DEVICE_PORT[k].length) DEVICE_PORT[k] = compatiblePorts(k).map(function (p) {
        return p.pin;
      });
    });
  })();

  var PORT_KIND = {};
  IO_PINS.forEach(function (p) { PORT_KIND[p.pin] = 'digital'; });
  /* PWM 复用引脚（与掌控板一致） */
  ['P9', 'P13', 'P14', 'P15', 'P16'].forEach(function (n) { PORT_KIND[n] = 'pwm'; });
  I2C_PINS.forEach(function (p) { PORT_KIND[p.pin] = 'i2c'; });
  MOTOR_PINS.forEach(function (p) { PORT_KIND[p.pin] = 'motor'; });
  GOLD_PINS.forEach(function (p) { PORT_KIND[p.pin] = 'gold'; });
  /* M 组名也按电机口着色 */
  PORT_KIND.M1 = 'motor'; PORT_KIND.M2 = 'motor';

  var KIND_COLOR = {
    pwm: '#e0552c', digital: '#5a6672', i2c: '#7c5cd6', motor: '#2a7a4b', gold: '#c9a23c'
  };
  var GROUP_NAME = { io: 'IO 口（3Pin）', i2c: 'I2C 口（4Pin）', motor: 'M 口（2Pin）', gold: '金手指' };
  function colorOfPort(p) { return KIND_COLOR[PORT_KIND[p] || 'digital']; }
  function groupOfPort(p) {
    var all = IO_PINS.concat(I2C_PINS, MOTOR_PINS, GOLD_PINS);
    var hit = all.filter(function (x) { return x.pin === p; })[0];
    return hit ? hit.group : 'io';
  }
  function allPorts() { return IO_PINS.concat(I2C_PINS, MOTOR_PINS, GOLD_PINS); }
  /* 按分组返回接口（用于接口分组显示与筛选） */
  function portGroups() {
    return {
      io: IO_PINS, i2c: I2C_PINS, motor: MOTOR_PINS, gold: GOLD_PINS
    };
  }
  /* 某硬件的引脚数（多实例 id 取其基础 id 的引脚数） */
  function pinsOf(devId) {
    var base = (ZKB.baseOf ? ZKB.baseOf(devId) : devId);
    return DEVICE_PINS[base] || 3;
  }

  /* ============================================================
   * 接口族（第三十四轮：各拓展设备支持更多接口）
   *
   * 拓展板只有四类接口，不同硬件能接的口也不同：
   *   io    任意 IO 口（GND / 3V3 / P，3Pin）—— 大多数传感器与执行器
   *   i2c   三个 I2C 口（4Pin）—— I2C 类传感器
   *   motor M 口（2Pin 电机驱动）—— 电机 / 加热 / 机器人
   *   net   网络 / 串口模块，固定走 P13 / P14 / P15
   *
   * 两套清单，各司其职：
   *   portsForDevice   —— 推荐接口（拉线时高亮的少数几个，教学不乱）
   *   compatiblePorts  —— 同族全部接口（右键菜单里可任选，第三十四轮新增）
   * ============================================================ */
  function ifaceOf(devId) {
    var base = (ZKB.baseOf ? ZKB.baseOf(devId) : devId);
    /* 不在表内 = 板载 / 无线设备（无线广播、WiFi 语音识别等），无需接线 */
    if (NO_WIRE[base]) return null;
    return DEVICE_IFACE[base] || null;
  }
  /* 该设备同族的全部接口（物理口对象数组） */
  function compatiblePorts(devId) {
    var kind = ifaceOf(devId);
    if (!kind) return [];
    var g = allPorts().filter(function (p) { return !UNUSABLE_PINS[p.pin]; });
    if (kind === 'i2c') return g.filter(function (p) { return p.group === 'i2c'; });
    if (kind === 'motor') return g.filter(function (p) { return p.group === 'motor'; });
    if (kind === 'net') {
      return g.filter(function (p) {
        return p.pin === 'P13' || p.pin === 'P14' || p.pin === 'P15';
      });
    }
    return g.filter(function (p) { return p.group === 'io'; });
  }
  /* 某硬件可用的接口（拉线高亮用）
     规则：
       i2c / motor / net 三族接口总数很少，直接全给；
       io 族接口多，只高亮 DEVICE_PORT 里推荐的少数几个（教学不乱），
       其余同族接口仍可在右键菜单里手动选择。 */
  function portsForDevice(devId) {
    var base = (ZKB.baseOf ? ZKB.baseOf(devId) : devId);
    var g = allPorts().filter(function (p) { return !UNUSABLE_PINS[p.pin]; });
    var kind = ifaceOf(devId);
    /* I2C 口一共三个（3.3V A / 3.3V B / 5V），全部可用 */
    if (kind === 'i2c') return g.filter(function (p) { return p.group === 'i2c'; });
    /* M 口按组呈现：M1 / M2 */
    if (kind === 'motor') return g.filter(function (p) { return p.group === 'motor'; });
    /* 网络 / 串口模块固定走 P13 / P14 / P15 */
    if (kind === 'net') {
      return g.filter(function (p) {
        return p.pin === 'P13' || p.pin === 'P14' || p.pin === 'P15';
      });
    }
    /* IO 族：优先按 DEVICE_PORT 推荐的接口返回（第二十六轮起为各设备指定） */
    var spec = DEVICE_PORT[base];
    if (spec && spec.length) {
      var hit = spec.map(function (pin) {
        return g.filter(function (p) { return p.pin === pin; })[0];
      }).filter(Boolean);
      if (hit.length) return hit;
    }
    return g.filter(function (p) { return p.group === 'io'; });
  }
  /* 右键菜单里的接口清单：同族全部接口 + 是否推荐 + 分组名 */
  function menuPortsFor(devId) {
    var base = (ZKB.baseOf ? ZKB.baseOf(devId) : devId);
    var kind = ifaceOf(devId);
    var rec = DEVICE_PORT[base] || [];
    var out = [];
    if (!kind) return out;               /* 板载 / 无线设备无需接线 */
    if (kind === 'motor') {
      /* M 口按组（M1 / M2）呈现：点一个即同时占用 M1+ / M1- */
      ['M1', 'M2'].forEach(function (g) {
        out.push({ key: g, group: 'motor', rec: rec.indexOf(g) >= 0 });
      });
    } else {
      compatiblePorts(devId).forEach(function (p) {
        out.push({ key: p.pin, group: p.group, rec: rec.indexOf(p.pin) >= 0 });
      });
    }
    return out;
  }
  /* 接口匹配校验：接口族不符则给出中文提示
     （同族接口一律可接 —— 第三十四轮起每个设备支持更多接口） */
  function matchError(devId, port) {
    if (UNUSABLE_PINS[port]) return '掌控板不支持 ' + port + ' 口，请选择其它接口';
    var kind = ifaceOf(devId);
    var nm = ((ZKB.deviceMeta && ZKB.deviceMeta(devId)) || {}).name || devId;
    if (!kind) return '「' + nm + '」是板载 / 无线设备，不需要接线';
    /* 同族接口可直接匹配 */
    var ok = compatiblePorts(devId).some(function (p) {
      return p.pin === port || (M_PAIR_PORTS[port] && p.pin === port);
    });
    if (ok) return null;
    var grp = groupOfPort(port);
    /* M 口用组名（M1 / M2），也按电机口族判定 */
    if (M_PAIR_PORTS[port]) grp = 'motor';
    var need = grp === 'i2c' ? 4 : (grp === 'motor' ? 2 : 3);
    return '接口不匹配：' + port + ' 是 ' + need + 'Pin，「' + nm + '」需要 ' +
      (kind === 'i2c' ? '4Pin I2C 口' : kind === 'motor' ? '2Pin M 口' :
        kind === 'net' ? 'P13 / P14 / P15 口' : '3Pin IO 口');
  }

  /* ============================================================
   * 扩展板 SVG —— 严格对照参考图重绘（viewBox 400×235）
   *
   *   左侧    ：IO 接口 10 个 3Pin（三列排针：GND 灰 / 3V3 红 / P 绿）
   *   中间    ：掌控板插槽 + 金手指 GND 3V 2 1 0（掌控板插在上面）
   *   中间靠左：I2C 接口 3 个 4Pin（3V3 / 3V3 / 5V）
   *   右下角  ：M 接口两组绿色端子（M1± / M2±）
   *   其余    ：蜂鸣器（P0 带开关）、USB 电源、电池口、电源开关、
   *             触摸金手指 P/Y/T/H/O/N（底部）
   * ============================================================ */
  function expBoardSVG() {
    var s = '';

    /* ---- PCB ---- */
    s += '<rect x="0" y="0" width="400" height="235" rx="7" fill="#0b0d0f"/>';
    s += '<rect x="2" y="2" width="396" height="231" rx="6" fill="#101214"/>';

    /* ---- 最左侧：IO 接口 10 个 3Pin（三列排针） ----
       与参考图一致：GND 灰 / 3V3 红 / P 绿 三条竖排针，每行一个 IO 口 */
    /* 列标题 */
    s += '<text x="12" y="10" font-size="5" fill="#8a9099" text-anchor="middle">GND</text>';
    s += '<text x="22" y="10" font-size="5" fill="#ef9a9a" text-anchor="middle">3V3</text>';
    s += '<text x="32" y="10" font-size="5" fill="#a5d6a7" text-anchor="middle">P</text>';
    IO_PINS.forEach(function (p) {
      var y = (p.y - 7).toFixed(1);
      /* 三列排针：GND 灰 / 3V3 红 / P 绿（每列带针孔） */
      s += '<rect x="8" y="' + y + '" width="8" height="14" fill="#43484f"/>' +
        '<circle cx="12" cy="' + p.y + '" r="1.6" fill="#101214"/>';
      s += '<rect x="18" y="' + y + '" width="8" height="14" fill="#c62828"/>' +
        '<circle cx="22" cy="' + p.y + '" r="1.6" fill="#101214"/>';
      s += '<rect x="28" y="' + y + '" width="8" height="14" fill="#2e7d32"/>' +
        '<circle cx="32" cy="' + p.y + '" r="1.6" fill="#101214"/>';
      /* P12 占位但不可用：排针灰显 */
      if (p.unusable) {
        s += '<rect x="8" y="' + y + '" width="28" height="14" fill="#101214" opacity=".45"/>';
      }
    });
    /* 分组标注（接口名称由接口圆点层逐行标注，避免重复） */
    s += '<text x="24" y="229" font-size="5.5" fill="#8a9099" text-anchor="middle" ' +
      'font-weight="bold">IO 接口（3Pin）</text>';

    /* ---- 中间：掌控板插槽底座 + 金手指 GND 3V 2 1 0 ---- */
    /* 插槽底座（掌控板压在上方，只露出下沿一条） */
    s += '<rect x="60" y="20" width="280" height="26" rx="3" fill="#08090b"/>';
    for (var i0 = 0; i0 < 30; i0++) {
      s += '<rect x="' + (64 + i0 * 9.2) + '" y="38" width="4" height="5" fill="#25282c"/>';
    }
    /* 金手指触点（金色圆孔 + 名称；掌控板压在其上，下沿略露出） */
    GOLD_PINS.forEach(function (p) {
      s += '<circle cx="' + p.x + '" cy="' + p.y + '" r="6.5" fill="#c9a23c"/>';
      s += '<circle cx="' + p.x + '" cy="' + p.y + '" r="3.4" fill="#5a4a1a"/>';
      s += '<text x="' + p.x + '" y="' + (p.y - 9) + '" font-size="5.5" fill="#c9a23c" ' +
        'text-anchor="middle" font-weight="bold" font-family="monospace">' + p.label + '</text>';
    });
    s += '<text x="200" y="56" font-size="6" fill="#7a818a" text-anchor="middle">' +
      '掌控板金手指（G / V / 2 / 1 / 0）</text>';

    /* ---- 品牌 ---- */
    s += '<text x="200" y="70" font-size="8.5" font-weight="700" fill="#c9a23c" ' +
      'text-anchor="middle" letter-spacing=".5">DFROBOT 掌控扩展板</text>';
    s += '<text x="200" y="79" font-size="5" fill="#6a7078" text-anchor="middle">' +
      'MBT0014 · 80mm × 47mm</text>';

    /* ---- 中间靠左：I2C 接口 3 个（横排 4Pin） ---- */
    s += '<text x="122" y="86" font-size="7" fill="#8a9099" text-anchor="middle" ' +
      'font-weight="bold">I2C 接口（4Pin）</text>';
    I2C_PINS.forEach(function (p) {
      var x = p.x - 22, y = p.y - 9;
      s += '<rect x="' + x + '" y="' + y + '" width="44" height="18" rx="2" fill="#1a1c1f"/>';
      /* 4 个触点（横排 4Pin，与参考图一致） */
      for (var k = 0; k < 4; k++) {
        s += '<rect x="' + (x + 4 + k * 11) + '" y="' + (y + 3) + '" width="7" height="12" ' +
          'fill="#2a2d31"/>' +
          '<circle cx="' + (x + 7.5 + k * 11) + '" cy="' + (y + 9) + '" r="1.7" fill="#6a7078"/>';
      }
      /* 丝印：SDA SCL GND + 电压（与参考图一致标在排针下方） */
      s += '<text x="' + p.x + '" y="' + (y + 26) + '" font-size="4.8" fill="#8a9099" ' +
        'text-anchor="middle">SDA SCL GND <tspan fill="' +
        (p.volt === '5V' ? '#ef9a9a' : '#c9a23c') + '">' + p.volt + '</tspan></text>';
    });

    /* ---- 蜂鸣器（占 P0，带开关；参考图位于中部偏右下） ---- */
    s += '<rect x="217" y="86" width="26" height="10" rx="2" fill="#2a2d31"/>';
    s += '<rect x="220" y="88.5" width="9" height="5" rx="1" fill="#c9a23c"/>';
    s += '<circle cx="230" cy="110" r="11" fill="#1a1c1f"/>';
    s += speakerMark(230, 110);
    s += '<text x="230" y="128" font-size="5" fill="#8a9099" text-anchor="middle">蜂鸣器 P0</text>';
    s += '<text x="248" y="128" font-size="5.5" fill="#c94a4a" text-anchor="middle">×</text>';

    /* ---- 底部：触摸金手指 P Y T H O N ---- */
    ['P', 'Y', 'T', 'H', 'O', 'N'].forEach(function (t, i) {
      var x = 118 + i * 30;
      s += '<rect x="' + x + '" y="206" width="26" height="24" rx="3" fill="#c9a23c"/>';
      s += '<circle cx="' + (x + 13) + '" cy="212" r="5" fill="#f5f7f9"/>';
      s += '<text x="' + (x + 13) + '" y="226" font-size="11" font-weight="bold" ' +
        'text-anchor="middle" fill="#1b1e23" font-family="monospace">' + t + '</text>';
    });

    /* ---- 右上：USB 电源 + 电池口 + 电源开关 ---- */
    s += '<rect x="330" y="6" width="30" height="14" rx="2" fill="#8a9099"/>';
    s += '<rect x="335" y="9" width="20" height="8" rx="1" fill="#3a4046"/>';
    s += '<text x="345" y="28" font-size="5" fill="#8a9099" text-anchor="middle">5V-5V USB</text>';
    /* 电池口 */
    s += '<rect x="332" y="34" width="26" height="20" fill="#2a2d31"/>';
    for (var b = 0; b < 3; b++) {
      s += '<rect x="334" y="' + (37 + b * 6) + '" width="22" height="3.6" fill="#c9a23c"/>';
    }
    s += '<text x="345" y="62" font-size="5" fill="#8a9099" text-anchor="middle">3.5V-5V 电池</text>';
    /* 电源开关 OFF / ON */
    s += '<rect x="334" y="68" width="24" height="44" rx="3" fill="#2a2d31"/>';
    s += '<text x="346" y="79" font-size="5.5" fill="#c9d1d9" text-anchor="middle">OFF</text>';
    s += '<rect x="337" y="83" width="18" height="11" rx="2" fill="#4a5058"/>';
    s += '<text x="346" y="106" font-size="5.5" fill="#c9d1d9" text-anchor="middle">ON</text>';
    s += '<text x="346" y="118" font-size="5" fill="#8a9099" text-anchor="middle">电源开关</text>';

    /* ---- 右下角：M 接口两组（绿色端子台） ---- */
    s += '<rect x="340" y="122" width="56" height="108" rx="3" fill="#2e7d32"/>';
    s += '<text x="368" y="132" font-size="5.5" fill="#c8e6c9" text-anchor="middle" ' +
      'font-weight="bold">M 接口</text>';
    MOTOR_PINS.forEach(function (p) {
      /* 绿色螺钉端子：外壳 + 银色螺钉 */
      s += '<circle cx="' + p.x + '" cy="' + p.y + '" r="8" fill="#4caf50"/>';
      s += '<circle cx="' + p.x + '" cy="' + p.y + '" r="3.4" fill="#e8ebef"/>';
      s += '<path d="M' + (p.x - 2.4) + ',' + p.y + ' h4.8 M' + p.x + ',' + (p.y - 2.4) +
        ' v4.8" stroke="#9aa3ad" stroke-width="1"/>';
      /* 白色丝印名称（端子左侧） */
      s += '<text x="356" y="' + (p.y + 2) + '" font-size="6" fill="#e8ebef" ' +
        'text-anchor="end" font-weight="bold" font-family="monospace">' + p.label + '</text>';
    });
    return s;
  }

  /* 喇叭图标（蜂鸣器） */
  function speakerMark(x, y) {
    return '<g transform="translate(' + x + ',' + y + ')" fill="none" stroke="#c9d1d9" ' +
      'stroke-width="1.3" stroke-linecap="round">' +
      '<path d="M-6,-3 h3 l4,-3.5 v13 l-4,-3.5 h-3 Z"/>' +
      '<path d="M4,-4 q2.5,4 0,8"/></g>';
  }

  /* ============================================================
   * 小掌控板模型（插在扩展板中间插槽上，260×130）
   * 按参考图重绘：A/B 金色圆按键、顶部指示灯与 RGB 三灯、
   * 大屏 OLED（掌控板丝印）、下方圆形白键、底部金手指 G V 2 1 0
   * ============================================================ */
  function boardSVG() {
    var s = '';
    /* ---- PCB（260×130，下沿为金手指） ---- */
    s += '<rect x="0" y="0" width="260" height="130" rx="10" fill="#191d21"/>';
    s += '<rect x="3" y="3" width="254" height="124" rx="8" fill="#20242a"/>';
    /* A 键（左）：字母在按键左侧，金色圆环 + 白芯（与参考图一致） */
    s += '<text x="20" y="28" text-anchor="middle" fill="#f0f3f6" font-size="14" ' +
      'font-weight="bold">A</text>';
    s += '<circle cx="46" cy="24" r="13" fill="#c9a23c"/>';
    for (var a = 0; a < 8; a++) {
      var an = a * Math.PI / 4;
      s += '<circle cx="' + (46 + Math.cos(an) * 10).toFixed(1) + '" cy="' +
        (24 + Math.sin(an) * 10).toFixed(1) + '" r="1.3" fill="#5a4a1a"/>';
    }
    s += '<circle cx="46" cy="24" r="7.5" fill="#f5f7f9"/>' +
      '<circle cx="46" cy="24" r="2.2" fill="#c9d1d9"/>';
    /* B 键（右）：字母在按键右侧 */
    s += '<text x="240" y="28" text-anchor="middle" fill="#f0f3f6" font-size="14" ' +
      'font-weight="bold">B</text>';
    s += '<circle cx="214" cy="24" r="13" fill="#c9a23c"/>';
    for (var b2 = 0; b2 < 8; b2++) {
      var an2 = b2 * Math.PI / 4;
      s += '<circle cx="' + (214 + Math.cos(an2) * 10).toFixed(1) + '" cy="' +
        (24 + Math.sin(an2) * 10).toFixed(1) + '" r="1.3" fill="#5a4a1a"/>';
    }
    s += '<circle cx="214" cy="24" r="7.5" fill="#f5f7f9"/>' +
      '<circle cx="214" cy="24" r="2.2" fill="#c9d1d9"/>';
    /* 顶部中间：两列指示灯小点 */
    [104, 156].forEach(function (x) {
      for (var d = 0; d < 3; d++) {
        s += '<rect x="' + x + '" y="' + (12 + d * 8) + '" width="3" height="4" rx="1" fill="#7d868f"/>';
      }
    });
    /* RGB 三灯（金色灯座 + 灯珠，位于两列指示灯下方） */
    for (var i = 0; i < 3; i++) {
      s += '<rect x="' + (113 + i * 13) + '" y="38" width="10" height="9" rx="2" fill="#e8c24a"/>';
      s += '<circle cx="' + (118 + i * 13) + '" cy="42.5" r="3" fill="#15181c"/>';
    }
    /* OLED 大屏（掌控板丝印，与参考图一致） */
    s += '<rect x="45" y="54" width="170" height="52" rx="4" fill="#0d1014" ' +
      'stroke="#3a414c" stroke-width="1"/>';
    s += '<rect x="50" y="58" width="160" height="44" rx="2" fill="#0b1410"/>';
    s += '<text x="130" y="86" font-size="11" text-anchor="middle" fill="#2f6b52">掌控板</text>';
    /* 麦克风（左）/ 光线传感器（右） */
    s += '<circle cx="20" cy="80" r="7" fill="none" stroke="#7d8794" stroke-width="1.4"/>';
    s += '<circle cx="240" cy="80" r="6" fill="none" stroke="#7d8794" stroke-width="1.4"/>';
    /* 屏幕下方圆形白键（参考图中的圆形复位/功能键） */
    s += '<circle cx="130" cy="114" r="5.5" fill="#f5f7f9" stroke="#9aa3ad" stroke-width="1"/>';
    /* 底部金手指 G V 2 1 0（正好压在扩展板金手指上） */
    ['G', 'V', '2', '1', '0'].forEach(function (t, i) {
      var x = 77 + i * 22;
      s += '<rect x="' + x + '" y="122" width="18" height="8" rx="1.5" fill="#c9a23c"/>';
      s += '<text x="' + (x + 9) + '" y="128" font-size="6.5" font-weight="bold" ' +
        'text-anchor="middle" fill="#1b1e23" font-family="monospace">' + t + '</text>';
    });
    return s;
  }

  /* ============================================================
   * 硬件 3D 缩略（用 CSS 类拼装，与拓展库风格一致）
   * ============================================================ */
  function hwThumb(id) {
    var M = ZKB.devMeta3D && ZKB.devMeta3D[id];
    if (M && M.thumb) return M.thumb();
    return '<div class="hw-fallback">' + (ZKB.deviceMeta ? (ZKB.deviceMeta(id) || {}).name || id : id) + '</div>';
  }

  /* ============================================================
   * 弹窗主体
   * ============================================================ */
  var dlg = null;
  /* 连接关系：{devId, port, x, y} —— x/y 为硬件在弹窗中的停放坐标 */
  var conns = [];
  var dragging = null;

  function open() {
    if (!dlg) build();
    if (!dlg) return;
    dlg.classList.remove('hidden');
    render();
  }
  function close() { dlg && dlg.classList.add('hidden'); }

  function build() {
    dlg = $('wire-lib-mask');
    if (!dlg) return;
    $('wl-close').addEventListener('click', close);
    dlg.addEventListener('click', function (e) { if (e.target === dlg) close(); });
    var fb = $('wl-full');
    if (fb) fb.addEventListener('click', toggleFullscreen);
    document.addEventListener('fullscreenchange', function () {
      /* 第三十五轮：全屏切换后右键菜单要挪到新的宿主里，
         否则浏览器全屏时菜单（挂在 body 上）会看不见 */
      rehostPartMenu();
      if (!document.fullscreenElement && wlFull) { wlFull = false; toggleFullscreenOff(); }
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && wlFull) { toggleFullscreen(); }
    });
    $('wl-clear').addEventListener('click', function () {
      if (!confirm('清空全部硬件连接线？\n（掌控板与金手指的默认连接会保留）')) return;
      clearConnections();
    });
    /* 第三十四轮：一键连接（把所有已添加硬件接到推荐接口上） */
    var autoBtn = $('wl-auto');
    if (autoBtn) autoBtn.addEventListener('click', function () { autoConnectAll(); });
    $('wl-help-toggle').addEventListener('click', function () {
      var h = $('wl-help');
      h.classList.toggle('hidden');
    });
    /* 第三十二轮：串口诊断（配合 CP210x 驱动指引）。
       驱动没装时 navigator.serial 拿不到设备，或者枚举出来但 open() 失败。 */
    var drvBtn = $('wl-driver-btn');
    if (drvBtn) drvBtn.addEventListener('click', diagnoseSerial);
    /* 第三十八轮：右下角放大 / 缩小 / 复位按钮 */
    bindZoomButtons();
    /* 恢复上次选择的界面缩放 */
    zoom = loadZoom();
    applyZoom();
  }

  /* ============================================================
   * 串口诊断：帮用户判断「驱动装了没」
   * Web Serial 只在 Chrome/Edge 且安全上下文（https 或 localhost）下可用。
   * ============================================================ */
  function diagnoseSerial() {
    var box = $('wl-driver-info');
    if (!box) return;
    box.className = 'wl-driver-info';
    box.textContent = '正在检测…';
    if (!navigator.serial) {
      box.classList.add('bad');
      box.innerHTML = '当前浏览器不支持 Web Serial，请用 <b>Chrome / Edge</b> 打开本页面' +
        '（且地址须是 http://localhost 或 https）。';
      return;
    }
    navigator.serial.getPorts().then(function (ports) {
      if (!ports.length) {
        box.classList.add('warn');
        box.innerHTML = '已支持串口，但<b>没有检测到已授权的设备</b>。' +
          '请先安装 CP210x 驱动，再用数据线连上掌控板，点工具条的「上传到掌控板」授权一次。';
        return;
      }
      var lines = ports.map(function (p, i) {
        var info = p.getInfo ? p.getInfo() : {};
        return (i + 1) + '. ' + (info.usbVendorId != null ?
          ('VID ' + info.usbVendorId.toString(16) + ' / PID ' +
            (info.usbProductId || 0).toString(16)) : '未知型号');
      });
      box.classList.add('ok');
      box.innerHTML = '✓ 检测到 ' + ports.length + ' 个串口设备：<br>' + lines.join('<br>') +
        '<br><span style="color:#8a939e">VID 10C4 / PID EA60 就是 CP210x，驱动正常。</span>';
    }).catch(function (e) {
      box.classList.add('bad');
      box.textContent = '检测失败：' + (e && e.message ? e.message : e);
    });
  }
  function toggleFullscreenOff() {
    var box = $('wire-lib');
    if (box) box.classList.remove('fullscreen');
    document.body.classList.remove('zk-wire-full');
    var btn = $('wl-full');
    if (btn) { btn.textContent = '⛶ 全屏'; btn.classList.remove('on'); }
    setTimeout(function () { render(); }, 60);
  }

  /* ============================================================
   * 读连接关系；默认补上「金手指 ↔ 掌控板」的五根连线
   * （GND/3V/2/1/0 通过中间金手指连接，默认已连接，用户可断开）
   * ============================================================ */
  function loadConns() {
    var raw = ZKB.Store && ZKB.Store.getLocal('zkb_connections_v1');
    conns = Array.isArray(raw) ? raw.slice() : [];
    /* 旧版单口 M 连接迁移为组连接（M1+ / M1- → M1 组） */
    var migrated = false;
    conns = conns.map(function (c) {
      if (M_PAIR[c.port]) { migrated = true; return { devId: c.devId, port: M_PAIR[c.port] }; }
      return c;
    });
    if (migrated) {
      /* 同设备去重（可能迁移出两条同设备记录） */
      var seen = {};
      conns = conns.filter(function (c) {
        if (seen[c.devId]) return false;
        seen[c.devId] = 1; return true;
      });
    }
    /* 补齐默认金手指连线（幂等：已存在则不重复添加） */
    var changed = false;
    GOLD_PINS.forEach(function (p) {
      var key = 'board_' + p.pin;
      if (!conns.some(function (c) { return c.devId === key; })) {
        conns.push({ devId: key, port: p.pin, board: true });
        changed = true;
      }
    });
    if (changed && ZKB.Store) ZKB.Store.setLocal('zkb_connections_v1', conns);
  }

  function saveConns() {
    if (ZKB.Store) ZKB.Store.setLocal('zkb_connections_v1', conns);
    /* 只把真实硬件（board_ 前缀的是金手指连线）同步到 SimBoard */
    var map = {};
    conns.forEach(function (c) {
      if (c.board) return;
      map[c.devId] = c.port;
    });
    if (ZKB.SimBoard && ZKB.SimBoard.setConnected) ZKB.SimBoard.setConnected(map);
    if (ZKB.Stage && ZKB.Stage.syncDevices) ZKB.Stage.syncDevices();
  }

  /* 清空连接：断开全部「硬件 ↔ 接口」的连接线，
     保留掌控板与金手指的默认连接；同步持久化到 localStorage */
  function clearConnections() {
    var before = conns.filter(function (c) { return !c.board; }).length;
    conns = conns.filter(function (c) { return c.board; });
    cleanupWiring();
    saveConns();
    render();
    ZKB.toast(before > 0 ? ('已清空 ' + before + ' 条硬件连接') : '当前没有硬件连接');
  }

  /* ============================================================
   * 第四十轮：移除某个设备的全部连接
   *
   * 场景：用户在虚拟仿真里删除拓展设备后，硬件连接界面里
   * 还留着这个设备的连线与占用状态 —— 设备都没了，线还挂着，
   * 接口也一直显示绿色「已占用」，与实际状态不符。
   * 这里在删除设备时同步把它的连接清掉并重绘。
   * ============================================================ */
  function removeDeviceConns(devId) {
    if (!devId) return 0;
    var before = conns.filter(function (c) { return c.devId === devId; }).length;
    if (!before) return 0;
    conns = conns.filter(function (c) { return c.devId !== devId; });
    /* 该设备的摆位记录也一并清掉，避免下次添加时位置错乱 */
    var lay = loadLayout();
    if (lay[devId]) { delete lay[devId]; saveLayout(lay); }
    cleanupWiring();
    saveConns();
    render();
    return before;
  }

  /* ============================================================
   * 一键连接：把所有已添加但未连线的硬件接到推荐接口上
   * （接口被占用时顺延到同组的下一个可用接口）
   * ============================================================ */
  function autoConnectAll() {
    loadConns();
    var added = (ZKB.SimBoard && ZKB.SimBoard.getDevices) ? ZKB.SimBoard.getDevices() : [];
    var n = 0;
    added.forEach(function (id) {
      if (conns.some(function (c) { return c.devId === id; })) return;
      if (!ifaceOf(id)) return;              /* 板载 / 无线设备无需连线 */
      var list = menuPortsFor(id);
      for (var i = 0; i < list.length; i++) {
        var key = list[i].key;
        var busy = M_PAIR_PORTS[key]
          ? M_PAIR_PORTS[key].some(function (q) { return portOccupied(q, id); })
          : portOccupied(key, id);
        if (busy) continue;
        conns = conns.filter(function (c) { return c.devId !== id; });
        conns.push({ devId: id, port: key });
        n++;
        break;
      }
    });
    if (n) { saveConns(); render(); }
    ZKB.toast(n ? ('已自动连接 ' + n + ' 个硬件') : '所有硬件都已连接');
    return n;
  }

  /* ============================================================
   * 渲染：扩展板 + 硬件停放区 + 连线
   * ============================================================ */
  function render() {
    loadConns();
    var svg = $('wl-svg');
    if (!svg) { console.warn('硬件连接：未找到扩展板画布'); return; }

    var added = ZKB.SimBoard ? ZKB.SimBoard.getDevices() : [];
    /* 图层顺序（由下至上）：
       1. wl-board-g  扩展板
       2. wl-b1-g     掌控板（插在中间金手指上）
       3. wl-links    连线（在最上层，仅次于设备模型）
       4. wl-ports    接口圆点（需可点击，置于连线之上）
       设备模型由 #wl-dock 承载，CSS 中 z-index 高于扩展板 */
    svg.innerHTML =
      '<g id="wl-board-g">' + expBoardSVG() + '</g>' +
      '<g id="wl-b1-g" transform="translate(' + BOARD_TX + ',' + BOARD_TY + ')">' +
      boardSVG() + '</g>' +
      '<g id="wl-links"></g><g id="wl-ports"></g>';

    /* 硬件直接以 3D 模型摆到右侧工作区，位置可自由拖动 */
    var stage = $('wl-stage');
    var sw = (stage && stage.clientWidth) || 660;
    var layout = ensureLayout(added, sw);

    var dockEl = $('wl-dock');
    dockEl.innerHTML = added.map(function (id, i) {
      var pos = layout[id] || { x: 40 + i * 92, y: 40, k: 1 };
      var c = conns.filter(function (x) { return x.devId === id; })[0] || null;
      var M = (ZKB.devMeta3D && ZKB.devMeta3D[id]) || null;
      var nm = ((ZKB.deviceMeta && ZKB.deviceMeta(id)) || {}).name || id;
      return '<div class="wl-part' + (c ? ' docked' : ' free') + '" data-dev="' + id + '" ' +
        (c ? 'data-port="' + c.port + '" ' : '') +
        'style="left:' + Math.round(pos.x) + 'px;top:' + Math.round(pos.y) + 'px">' +
        /* 左右两个连线控点：点击设备后出现，点击控点拖出连接线 */
        '<i class="wl-anchor l" data-side="l" title="点击拖出连接线"></i>' +
        '<i class="wl-anchor r" data-side="r" title="点击拖出连接线"></i>' +
        '<div class="wl-part-in" style="transform:scale(' + (pos.k || 1) + ')">' +
        hwThumb(id) + '</div>' +
        '<div class="wl-part-n">' + esc(nm) + '</div>' +
        (c ? '<div class="wl-port-tag" style="background:' + colorOfPort(c.port) + '">' + c.port + '</div>'
          : '<div class="wl-port-tag none">未连接</div>') +
        '</div>';
    }).join('');

    drawPorts();
    drawLinks();
    updateStat();
    /* 第三十八轮：重绘后缩放层的可用尺寸可能变了（弹窗开合 / 全屏切换），
       重新按当前尺寸套一次缩放，保证平移量与内容居中。 */
    applyZoom();
  }

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  /* ============================================================
   * 硬件摆位持久化：{devId: {x, y, k}}
   * ============================================================ */
  var LAY_KEY = 'zkb_hw_layout_v1';
  function loadLayout() {
    var o = ZKB.Store && ZKB.Store.getLocal(LAY_KEY);
    return (o && typeof o === 'object') ? o : {};
  }
  function saveLayout(o) {
    if (ZKB.Store) ZKB.Store.setLocal(LAY_KEY, o);
  }
  /* 新增硬件自动在扩展板右侧网格排布（保持较近距离） */
  function ensureLayout(added, sw) {
    var o = loadLayout();
    var changed = false;
    /* 扩展板居中且上方有掌控板，硬件分列左右两侧，避免遮挡板面 */
    var sideW = Math.max(150, (sw - Math.min(sw * 0.64, 560)) / 2 - 46);
    added.forEach(function (id, i) {
      if (!o[id]) {
        var left = i % 2 === 0;
        var idx = Math.floor(i / 2);
        o[id] = {
          x: left ? Math.max(8, sideW * 0.08) : Math.max(8, sw - sideW * 0.08 - 78),
          y: 40 + idx * 104,
          k: 1
        };
        changed = true;
      }
    });
    Object.keys(o).forEach(function (k) {
      if (added.indexOf(k) < 0) { delete o[k]; changed = true; }
    });
    if (changed) saveLayout(o);
    return o;
  }

  /* ============================================================
   * 第三十八轮：整体缩放硬件工作区
   *
   * 放大 / 缩小按钮缩放的是**整个硬件工作区**（扩展板 + 掌控板 +
   * 所有设备模型 + 连线），实现方式是对 #wl-zoom-wrap 施加
   * CSS transform: scale()。
   *
   * 缩放系数独立于各设备自己的缩放（右键菜单里的「尺寸」滑块）：
   * 界面缩放管整体观感，单设备尺寸管个别设备大小，两者叠加生效。
   *
   * ⚠ 坐标系有两套，别混淆：
   *   · 屏幕坐标 —— getBoundingClientRect() 的值，已含缩放。
   *     连线绘制、接口命中检测都用这套，天然正确。
   *   · 布局坐标 —— 缩放层内的 left/top，未含缩放。
   *     设备拖动写入 left/top 时必须用这套，故要除以 zoom。
   * ============================================================ */
  var ZOOM_STEP = 0.15;
  var ZOOM_MIN = 0.4, ZOOM_MAX = 2.5;
  var ZOOM_KEY = 'zkb_hw_zoom_v1';
  var zoom = 1;

  function loadZoom() {
    var z = ZKB.Store && ZKB.Store.getLocal(ZOOM_KEY);
    z = Number(z);
    if (!isFinite(z) || z <= 0) z = 1;
    return Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, z));
  }
  function saveZoom(z) {
    if (ZKB.Store) ZKB.Store.setLocal(ZOOM_KEY, z);
  }

  /* 缩放层的平移量：让缩放后内容的中心仍停在舞台中心。
     wrap 的定位尺寸是未缩放的（offsetWidth），缩放只影响渲染。 */
  function zoomOffset() {
    var wrap = $('wl-zoom-wrap');
    var W = wrap ? wrap.offsetWidth : 0;
    var H = wrap ? wrap.offsetHeight : 0;
    return { tx: W / 2 * (1 - zoom), ty: H / 2 * (1 - zoom), W: W, H: H };
  }

  /* 屏幕坐标（相对舞台内容区）→ 缩放层内的布局坐标 */
  function screenToLayout(sx, sy) {
    var o = zoomOffset();
    return { x: (sx - o.tx) / zoom, y: (sy - o.ty) / zoom };
  }

  /* 把缩放系数应用到缩放层 */
  function applyZoom() {
    var wrap = $('wl-zoom-wrap');
    if (!wrap) return;
    var o = zoomOffset();
    /* 平移放在 transform 里（而不是 left/top）：
       wrap 是 position:absolute + inset:0，改 left/top 会把元素拉伸。
       transform: translate() scale() 的顺序保证平移量不被缩放。 */
    wrap.style.transform = 'translate(' + Math.round(o.tx) + 'px,' +
      Math.round(o.ty) + 'px) scale(' + zoom + ')';
    updateZoomLabel();
    /* 缩放后设备锚点位置变了，连线要重画 */
    drawLinks();
  }

  function setZoom(z, silent) {
    zoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, Math.round(z * 100) / 100));
    saveZoom(zoom);
    applyZoom();
    if (!silent) {
      var msg = '界面缩放 ' + Math.round(zoom * 100) + '%';
      if (zoom <= ZOOM_MIN + 0.01) msg += '（已到最小）';
      if (zoom >= ZOOM_MAX - 0.01) msg += '（已到最大）';
      if (ZKB.toast) ZKB.toast(msg);
    }
    return zoom;
  }

  function updateZoomLabel() {
    var el = $('wl-zoom-val');
    if (el) el.textContent = Math.round(zoom * 100) + '%';
  }

  function bindZoomButtons() {
    var out = $('wl-zoom-out');
    var inb = $('wl-zoom-in');
    var rst = $('wl-zoom-reset');
    if (out) out.addEventListener('click', function () { setZoom(zoom - ZOOM_STEP); });
    if (inb) inb.addEventListener('click', function () { setZoom(zoom + ZOOM_STEP); });
    if (rst) rst.addEventListener('click', function () { setZoom(1); });
  }

  /* ============================================================
   * 端口在弹窗画布中的像素坐标。
     viewBox 为 400 宽，采用 preserveAspectRatio 默认的等比缩放，
     以容器宽度换算比例即可；SVG 无 CSS 变形时高度同样按比例。 */
  function boardScale() {
    var box = $('wl-board-box');
    if (!box) return 1;
    var br = box.getBoundingClientRect();
    return (br.width || EXP_W) / EXP_W;
  }

  /* viewBox 上移了EXP_VB_Y，故画布内 y 需要减去该偏移 */
  function vbY(y) { return y - EXP_VB_Y; }

  /* 扩展板画布（.wl-board-box）在舞台中的左上角偏移。
     扩展板是居中定位的，接口坐标必须加上这个偏移才是舞台坐标，
     否则连线端点会与接口圆点错位。 */
  function boardOrigin() {
    var box = $('wl-board-box'), stage = $('wl-stage');
    if (!box || !stage) return { x: 0, y: 0 };
    var br = box.getBoundingClientRect(), sr = stage.getBoundingClientRect();
    return { x: br.left - sr.left, y: br.top - sr.top };
  }

  /* 接口在「舞台坐标系」中的位置（供命中检测使用） */
  function portPos(port) {
    var p = allPorts().filter(function (x) { return x.pin === port; })[0];
    if (!p) return null;
    var scale = boardScale();
    var o = boardOrigin();
    return { x: o.x + p.x * scale, y: o.y + vbY(p.y) * scale, raw: p };
  }

  /* 舞台像素坐标 → SVG viewBox 坐标。
     连线画在 #wl-svg 内部，必须使用 viewBox 坐标，否则端点会被
     缩放 + viewBox 上移量带偏（表现为"连线没出现"/位置错乱）。 */
  function stageToVb(sx, sy) {
    var scale = boardScale(), o = boardOrigin();
    return { x: (sx - o.x) / scale, y: (sy - o.y) / scale + EXP_VB_Y };
  }

  /* 接口原始定义（viewBox 坐标） */
  function portDef(port) {
    return allPorts().filter(function (x) { return x.pin === port; })[0] || null;
  }

  /* 设备左/右控点在「舞台坐标系」中的位置 */
  function anchorPosStage(node, side) {
    var stage = $('wl-stage');
    if (!stage || !node) return { x: 0, y: 0 };
    var hr = stage.getBoundingClientRect();
    var nr = node.getBoundingClientRect();
    return {
      x: nr.left - hr.left + (side === 'l' ? 0 : nr.width),
      y: nr.top - hr.top + nr.height / 2
    };
  }

  /* 接口圆点：空闲半透明 + 名称标签；被占用时高亮为绿色并显示连接对象 */
  /* 只切换现有接口节点的 class，不重建 DOM。
     用于「拉线时高亮可连接接口」—— 鼠标每移动一帧都会调用，
     若重建 innerHTML 会销毁节点（既浪费，外部持有的引用也会失效）。 */
  function highlightPorts(devId) {
    var stage = $('wl-stage');
    if (!stage) return;
    var allow = null;
    if (devId) {
      allow = {};
      portsForDevice(devId).forEach(function (p) {
        if (!UNUSABLE_PINS[p.pin] && !portOccupied(p.pin, devId)) allow[p.pin] = 1;
      });
    }
    stage.querySelectorAll('.wl-port').forEach(function (node) {
      var pn = node.getAttribute('data-port');
      var dead = !!UNUSABLE_PINS[pn];
      var ok = !!(allow && allow[pn]);
      node.classList.toggle('wire-ok', !!(devId && ok));
      node.classList.toggle('wl-port-dim', !!((devId && !ok) || dead));
    });
  }

  function drawPorts(filterDev) {
    var g = $('wl-ports');
    if (!g) return;
    /* 第三十九轮：区分两种「已连接」
       · used     —— 被拓展硬件占用（绿色大圆点）
       · goldUsed —— 金手指常驻连接（掌控板默认插在扩展板中间，金色圆点）
       两者分开统计，是为了让「设备断开后接口恢复初始状态」看得清楚：
       绿色消失 = 设备已拔掉；金色一直在 = 掌控板本就插在那里。 */
    var used = {}, goldUsed = {};
    conns.forEach(function (c) {
      connPorts(c).forEach(function (p) {
        if (c.board) goldUsed[p] = (goldUsed[p] || 0) + 1;
        else used[p] = (used[p] || 0) + 1;
      });
    });
    /* 若正在拖拽某个硬件，只高亮它「引脚数匹配」的接口 */
    var allow = null;
    if (filterDev) {
      allow = {};
      portsForDevice(filterDev).forEach(function (p) { allow[p.pin] = 1; });
    }
    g.innerHTML = allPorts().map(function (p) {
      var occupied = used[p.pin];
      var gold = goldUsed[p.pin];
      /* 掌控板不支持的引脚（P12）：灰显且不可连接 */
      var dead = !!UNUSABLE_PINS[p.pin];
      var col = occupied ? '#4ade80' : (gold ? '#e8c24a' : (dead ? '#4a5058' : colorOfPort(p.pin)));
      var dim = ((allow && !allow[p.pin]) || dead) ? ' wl-port-dim' : '';
      var label = occupied ? p.pin : (p.group === 'i2c' ? p.volt : p.label);
      /* 标签位置：IO 口在排针右侧（与参考图一致），I2C 在接口上方，
         M 口名称已由扩展板丝印绘制（绿色端子旁白字），这里不再重复 */
      var lx = p.x, ly = p.y - 13, anchor = 'middle';
      if (p.group === 'io') { lx = p.x + 20; ly = p.y + 3; anchor = 'start'; }
      var showLabel = p.group !== 'motor';
      /* 半径：被硬件占用 > 金手指常驻 > 空闲 */
      var rr = occupied ? 8 : (gold ? 7 : 5);
      var rr2 = occupied ? 12 : (gold ? 11 : 9);
      var op = occupied ? '.95' : (gold ? '.9' : (allow ? '.85' : '.6'));
      return '<g class="wl-port' + (occupied ? ' used' : '') + (gold ? ' gold-used' : '') + dim +
        '" data-port="' + p.pin + '">' +
        /* 透明热区：扩大可点击范围，方便课堂拖线 */
        '<circle cx="' + p.x + '" cy="' + p.y + '" r="13" fill="transparent"/>' +
        '<circle cx="' + p.x + '" cy="' + p.y + '" r="' + rr + '" fill="' + col +
        '" opacity="' + op + '" stroke="#0d0f12" stroke-width="1.2"/>' +
        '<circle cx="' + p.x + '" cy="' + p.y + '" r="' + rr2 + '" fill="none" ' +
        'stroke="' + col + '" stroke-width="1" opacity=".35"/>' +
        (showLabel ?
          '<text x="' + lx + '" y="' + ly + '" font-size="6" fill="' +
          (occupied ? '#4ade80' : (gold ? '#e8c24a' : (dead ? '#5a6068' : '#9aa3ad'))) +
          '" text-anchor="' + anchor + '">' + label + '</text>' : '') +
        (dead ? '<text x="' + (lx + 20) + '" y="' + ly + '" font-size="5" fill="#c94a4a" ' +
          'text-anchor="start">×</text>' : '') +
        '</g>';
    }).join('');
  }

  /* 连线绘制：硬件 ↔ 接口 的曲线；金手指 ↔ 掌控板 的短线。
     注意：全部使用 SVG viewBox 坐标（stageToVb 转换），
     否则连线会被缩放与 viewBox 上移量带偏而不可见。 */
  function drawLinks() {
    var g = $('wl-links');
    if (!g) return;
    var parts = [];

    conns.forEach(function (c) {
      var col = colorOfPort(c.port);

      /* 金手指连线：扩展板金手指 ↔ 掌控板金手指（短竖线，viewBox 坐标） */
      if (c.board) {
        var raw0 = portDef(c.port);
        var bp = raw0 && boardGoldPos(c.port);
        if (raw0 && bp) {
          parts.push('<path d="M' + raw0.x + ',' + raw0.y + ' L' + bp.x + ',' + bp.y +
            '" fill="none" stroke="' + col + '" stroke-width="3.5" stroke-linecap="round" ' +
            'opacity=".85"/>' +
            '<circle cx="' + raw0.x + '" cy="' + raw0.y + '" r="4" fill="' + col + '"/>' +
            '<circle cx="' + bp.x + '" cy="' + bp.y + '" r="3.4" fill="' + col + '"/>');
        }
        return;
      }

      var node = document.querySelector('.wl-part[data-dev="' + c.devId + '"]');
      if (!node) return;
      /* 从离接口较近的一侧控点出线 */
      var al = stageToVb(anchorPosStage(node, 'l').x, anchorPosStage(node, 'l').y);
      var ar = stageToVb(anchorPosStage(node, 'r').x, anchorPosStage(node, 'r').y);
      /* M 组连接 → 同组两个物理端口各画一条线；普通连接 → 一条 */
      var targets = connPorts(c);
      var segs = '';
      targets.forEach(function (tp) {
        var raw = portDef(tp);
        if (!raw) return;
        var a = Math.abs(al.x - raw.x) <= Math.abs(ar.x - raw.x) ? al : ar;
        var sx = a.x, sy = a.y, ex = raw.x, ey = raw.y;
        var mx = (sx + ex) / 2;
        var d = 'M' + sx + ',' + sy + ' C' + sx + ',' + (sy + 30) + ' ' +
          mx + ',' + (ey - 30) + ' ' + ex + ',' + ey;
        segs += '<path d="' + d + '" fill="none" stroke="#000" stroke-width="16" ' +
          'opacity="0" stroke-linecap="round"/>' +
          '<path class="wl-link-vis" d="' + d + '" fill="none" stroke="' + col +
          '" stroke-width="3" stroke-linecap="round" opacity=".9"/>' +
          '<circle cx="' + sx + '" cy="' + sy + '" r="3.6" fill="' + col + '"/>' +
          '<circle cx="' + ex + '" cy="' + ey + '" r="4.5" fill="' + col +
          '" stroke="#0d0f12" stroke-width="1.2"/>';
      });
      if (!segs) return;
      /* 包一层 .wl-link：右键连线即可断开。
         内含 16px 全透明热区路径，让细线也好点中 */
      parts.push('<g class="wl-link" data-dev="' + c.devId + '">' + segs + '</g>');
    });

    /* 正在拉线：从设备控点拉出一条跟随鼠标的虚线（层级最上，仅次于设备） */
    if (wiring && wiring.devId) {
      var node2 = document.querySelector('.wl-part[data-dev="' + wiring.devId + '"]');
      if (node2) {
        var ap = anchorPosStage(node2, wiring.side || 'r');
        var s = stageToVb(ap.x, ap.y);
        var m = stageToVb(wiring.mx, wiring.my);
        var col2 = colorOfPort((DEVICE_PORT[ZKB.baseOf ? ZKB.baseOf(wiring.devId) : wiring.devId] || ['P0'])[0]);
        parts.push('<path d="M' + s.x + ',' + s.y + ' Q' + s.x + ',' + ((s.y + m.y) / 2) +
          ' ' + ((s.x + m.x) / 2) + ',' + m.y + '" fill="none" stroke="' + col2 +
          '" stroke-width="3.2" stroke-dasharray="8 5" stroke-linecap="round" opacity=".95"/>' +
          '<circle cx="' + s.x + '" cy="' + s.y + '" r="4.5" fill="' + col2 + '"/>' +
          '<circle cx="' + m.x + '" cy="' + m.y + '" r="5.5" fill="' + col2 +
          '" opacity=".75"/>');
      }
    }
    g.innerHTML = parts.join('');
  }

  /* 掌控板上某个金手指在 viewBox 中的坐标 */
  function boardGoldPos(port) {
    var b1 = document.getElementById('wl-b1-g');
    if (!b1) return null;
    var info = BOARD_GOLD[port];
    if (!info) return null;
    var m = /translate\(([-\d.]+),\s*([-\d.]+)\)/.exec(b1.getAttribute('transform') || '');
    var tx = m ? parseFloat(m[1]) : BOARD_TX;
    var ty = m ? parseFloat(m[2]) : BOARD_TY;
    return { x: tx + info.x, y: ty + info.y };
  }

  /* 小掌控板上金手指（boardSVG 内）的中心坐标。
     与扩展板 GOLD_PINS 对应：GND=G / 3V=V / 2 / 1 / 0 */
  var BOARD_GOLD = {
    GND: { x: 86, y: 126 }, '3V': { x: 108, y: 126 }, '2': { x: 130, y: 126 },
    '1': { x: 152, y: 126 }, '0': { x: 174, y: 126 }
  };

  /* 掌控板在扩展板画布上的偏移：让板的 5 个金手指正好压在扩展板金手指上
     （扩展板 GOLD_PINS 首个 x=156，板内首个 x=86 → tx=70；
       扩展板金手指 y=30，板内金手指 y=126 → ty=-96） */
  var BOARD_TX = 70, BOARD_TY = -96;
  /* 扩展板画布上移让出空间展示掌控板（viewBox: 0 -112 400 347） */
  var EXP_VB_Y = -112, EXP_VB_H = 347;

  function updateStat() {
    var s = $('wl-stat');
    if (!s) return;
    var added = ZKB.SimBoard ? ZKB.SimBoard.getDevices() : [];
    var n = conns.length;
    s.innerHTML = '已添加硬件 <b>' + added.length + '</b> 个 · 已连接 <b>' + n + '</b> 个' +
      (n < added.length ? ' <span style="color:#e0483e">（未连接的硬件不会工作）</span>' : '');
  }

  /* ============================================================
  /* ============================================================
   * 交互：左键拖动移动硬件 · 拖到接口连线 · 右键菜单
   * ============================================================ */
  var dragging = null;
  var wiring = null;      /* 正在拉线：{devId, side, mx, my} —— 从设备控点出线 */
  var anchorDrag = false; /* 按住控点拖线中（松开时在接口上即完成连接） */
  var suppressNextClick = false;  /* 刚拖动过：本次 click 不当作"选中" */
  var bound = false;

  function bindDrag() {
    if (bound) return;
    bound = true;
    initPortPinMap();
    var stage = $('wl-stage');
    if (!stage) return;

    /* ============================================================
     * 连线交互（方向：设备 → 扩展板接口）
     *   1) 点击设备 → 选中，设备两侧出现两个控点；点击空白 → 控点消失
     *   2) 点击（或按住）控点 → 拖出一条跟随鼠标的连接线
     *   3) 点击扩展板接口（或在接口上松开）→ 完成连接；点击空白 → 取消
     *   4) 右键连接线 → 直接断开（去掉连接线）；
     *      右键设备 → 拉线中取消连线，否则打开更多选项
     * ============================================================ */
    /* 选中设备：显示两侧控点 */
    function selectPart(node) {
      stage.querySelectorAll('.wl-part').forEach(function (x) { x.classList.remove('sel'); });
      if (node) node.classList.add('sel');
    }

    /* 控点按下：开始拉线（捕获阶段 + stopPropagation，避免触发设备拖动） */
    stage.addEventListener('mousedown', function (e) {
      if (e.button === 2) return;
      var an = e.target.closest ? e.target.closest('.wl-anchor') : null;
      if (!an) return;
      var node = an.closest('.wl-part');
      if (!node) return;
      e.preventDefault();
      e.stopPropagation();
      anchorDrag = true;
      selectPart(node);
      startWiringFrom(node.getAttribute('data-dev'), an.getAttribute('data-side'));
    }, true);

    /* 控点拖出后在接口上松开 → 完成连接（命中检测用舞台像素坐标） */
    document.addEventListener('mouseup', function (e) {
      if (!wiring || !anchorDrag) return;
      anchorDrag = false;
      var el = null;
      try { el = document.elementFromPoint(e.clientX, e.clientY); } catch (err) { }
      var pg = el && el.closest ? el.closest('.wl-port') : null;
      if (pg) tryConnect(wiring.devId, pg.getAttribute('data-port'));
      /* 未落在接口上：保持拉线状态，可再点击接口完成（点空白取消） */
    });

    stage.addEventListener('mousedown', function (e) {
      if (e.button === 2) return;
      var pg = e.target.closest ? e.target.closest('.wl-port') : null;
      if (pg) return;   /* 接口的点击在 click 阶段处理 */
      var node = e.target.closest ? e.target.closest('.wl-part') : null;
      if (node) return; /* 设备的点击在 click 阶段处理（避免与拖动冲突） */
      /* 点空白 → 取消拉线 + 取消选中（控点消失） */
      if (wiring) cleanupWiring();
      selectPart(null);
    });

    /* ---- 点击：接口完成连接 / 控点出线 / 设备选中 ---- */
    stage.addEventListener('click', function (e) {
      /* 已在拉线中：本次点击若落在接口上 → 完成连接 */
      if (wiring) {
        var pg = e.target.closest ? e.target.closest('.wl-port') : null;
        if (pg) { tryConnect(wiring.devId, pg.getAttribute('data-port')); return; }
        /* 落在另一个控点上 → 从该控点重新出线 */
        var an = e.target.closest ? e.target.closest('.wl-anchor') : null;
        if (an) {
          var nn = an.closest('.wl-part');
          if (nn) {
            selectPart(nn);
            startWiringFrom(nn.getAttribute('data-dev'), an.getAttribute('data-side'));
          }
          return;
        }
        /* 落在设备上 → 仅切换选中（保持拉线） */
        var nd = e.target.closest ? e.target.closest('.wl-part') : null;
        if (nd) { selectPart(nd); return; }
        /* 其它位置 → 取消 */
        cleanupWiring();
        return;
      }

      /* 未在拉线：点击控点 → 开始拉线；点击设备 → 选中控点出现 */
      if (suppressNextClick) { suppressNextClick = false; return; }
      var an2 = e.target.closest ? e.target.closest('.wl-anchor') : null;
      if (an2) {
        var n2 = an2.closest('.wl-part');
        if (n2) {
          selectPart(n2);
          startWiringFrom(n2.getAttribute('data-dev'), an2.getAttribute('data-side'));
        }
        return;
      }
      /* 点击已占用接口 → 断开（由后面的监听器处理）
         第三十九轮：金手指（gold-used）也是常驻连接，同样可点断开 */
      var usedPort = e.target.closest ? e.target.closest('.wl-port.used, .wl-port.gold-used') : null;
      if (usedPort) return;
      var node = e.target.closest ? e.target.closest('.wl-part') : null;
      if (node) selectPart(node);
    });

    /* ---- 拉线过程中移动鼠标：线跟随 + 高亮可用接口 ---- */
    stage.addEventListener('mousemove', function (e) {
      if (!wiring) return;
      var host = stage.getBoundingClientRect();
      wiring.mx = e.clientX - host.left;
      wiring.my = e.clientY - host.top;
      /* 就地切换 class 高亮可连接接口（不重建 DOM） */
      highlightPorts(wiring.devId);
      drawLinks();
    });

    /* ---- 右键：右键连接线断开 / 取消拉线 / 设备更多选项 ---- */
    stage.addEventListener('contextmenu', function (e) {
      /* 右键连接线 → 直接断开（去掉连接线） */
      var lk = e.target.closest ? e.target.closest('.wl-link') : null;
      if (lk) {
        e.preventDefault();
        var ldev = lk.getAttribute('data-dev');
        var lconn = conns.filter(function (c) { return c.devId === ldev; })[0];
        if (lconn) {
          conns = conns.filter(function (c) { return c.devId !== ldev; });
          saveConns();
          render();
          ZKB.toast('已断开「' +
            (((ZKB.deviceMeta && ZKB.deviceMeta(ldev)) || {}).name || ldev) +
            '」与 ' + lconn.port + ' 的连接');
        }
        return;
      }
      var node = e.target.closest ? e.target.closest('.wl-part') : null;
      if (!node) return;
      e.preventDefault();
      var id = node.getAttribute('data-dev');
      var nm = ((ZKB.deviceMeta && ZKB.deviceMeta(id)) || {}).name || id;
      /* 正在从该设备拉线 → 右键取消当前连线 */
      if (wiring && wiring.devId === id) {
        cleanupWiring();
        ZKB.toast('已取消「' + nm + '」的连线');
        return;
      }
      /* 右键设备 → 打开更多选项（尺寸/恢复位置/移除） */
      showPartMenu(id, e.clientX, e.clientY);
    });

    /* ---- 左键：选中 / 拖动 ---- */
    stage.addEventListener('mousedown', function (e) {
      if (e.button === 2) return;
      var node = e.target.closest ? e.target.closest('.wl-part') : null;
      if (!node) return;
      var id = node.getAttribute('data-dev');
      if (!id) return;
      var host = stage.getBoundingClientRect();
      var lay = loadLayout();
      var pos = lay[id] || { x: 20, y: 20, k: 1 };
      /* 第三十八轮：记录「布局坐标」下的鼠标偏移。
         屏幕坐标要除以 zoom 才是布局坐标，否则放大后拖动会错位。 */
      var lp = screenToLayout(e.clientX - host.left, e.clientY - host.top);
      dragging = {
        id: id, node: node,
        ox: lp.x - pos.x,
        oy: lp.y - pos.y,
        moved: false, hover: null
      };
      node.classList.add('dragging');
      /* 选中高亮 */
      stage.querySelectorAll('.wl-part').forEach(function (x) { x.classList.remove('sel'); });
      node.classList.add('sel');
      e.preventDefault();
    });

    /* ---- 触屏 ---- */
    stage.addEventListener('touchstart', function (e) {
      var node = e.target.closest ? e.target.closest('.wl-part') : null;
      if (!node) return;
      var t = e.touches[0];
      var host = stage.getBoundingClientRect();
      var lay = loadLayout();
      var pos = lay[node.getAttribute('data-dev')] || { x: 20, y: 20, k: 1 };
      /* 第三十八轮：与鼠标拖动一致，偏移量取布局坐标 */
      var lp = screenToLayout(t.clientX - host.left, t.clientY - host.top);
      dragging = {
        id: node.getAttribute('data-dev'), node: node,
        ox: lp.x - pos.x, oy: lp.y - pos.y,
        moved: false, hover: null
      };
      node.classList.add('dragging');
      e.preventDefault();
    }, { passive: false });

    /* ---- 移动 ---- */
    var move = function (e) {
      if (!dragging) return;
      dragging.moved = true;
      var host = stage.getBoundingClientRect();
      /* 第三十八轮：屏幕坐标 → 布局坐标（除以缩放系数），
         因为设备的 left/top 是缩放层内的布局坐标。 */
      var lp = screenToLayout(e.clientX - host.left, e.clientY - host.top);
      var x = lp.x - dragging.ox;
      var y = lp.y - dragging.oy;
      /* 边界限制用布局尺寸（缩放层的 offsetWidth），不是屏幕尺寸 */
      var lw = $('wl-zoom-wrap');
      var maxX = (lw ? lw.offsetWidth : host.width) - 70;
      var maxY = (lw ? lw.offsetHeight : host.height) - 70;
      dragging.node.style.left = Math.max(0, Math.min(maxX, x)) + 'px';
      dragging.node.style.top = Math.max(0, Math.min(maxY, y)) + 'px';

      /* 命中最近接口（只在引脚数匹配的接口中找）。
         这里用屏幕坐标比较：portPos 返回的也是屏幕坐标（已含缩放）。 */
      var best = null, bestD = 54;
      var all = portsForDevice(dragging.id);
      for (var i = 0; i < all.length; i++) {
        if (UNUSABLE_PINS[all[i].pin]) continue;
        var pp = portPos(all[i].pin);
        if (!pp) continue;
        var dx = (e.clientX - host.left) - pp.x;
        var dy = (e.clientY - host.top) - pp.y;
        var d = Math.sqrt(dx * dx + dy * dy);
        if (d < bestD) { bestD = d; best = all[i].pin; }
      }
      /* 第八轮：拖动仅高亮最近接口作为位置参考，不自动连线 */
      dragging.hover = best;
      stage.querySelectorAll('.wl-port').forEach(function (g) {
        g.classList.toggle('hover', g.getAttribute('data-port') === best);
      });
    };
    document.addEventListener('mousemove', move);
    document.addEventListener('touchmove', function (e) {
      if (!dragging) return;
      move(e.touches[0]); e.preventDefault();
    }, { passive: false });

    /* ---- 松开：落位 + 判定连线 ---- */
    var up = function () {
      if (!dragging) return;
      var d = dragging;
      dragging = null;
      d.node.classList.remove('dragging');
      stage.querySelectorAll('.wl-port.hover').forEach(function (g) { g.classList.remove('hover'); });
      drawPorts();   /* 恢复全部接口显示 */

      var lay = loadLayout();
      var pos = lay[d.id] || { k: 1 };
      pos.x = parseFloat(d.node.style.left) || 0;
      pos.y = parseFloat(d.node.style.top) || 0;
      lay[d.id] = pos;
      saveLayout(lay);

      /* 第八轮：连线改为「点击设备 → 点击接口」，拖动只负责移动位置，不再自动连线。
         仅在确实移动过时才抑制随后的 click（否则正常点击设备也会被吞掉）。 */
      if (d.moved) suppressNextClick = true;
      drawLinks();
      render();
    };
    document.addEventListener('mouseup', up);
    document.addEventListener('touchend', up);

    /* ---- 点击接口：断开该硬件 ---- */
    stage.addEventListener('click', function (e) {
      /* 第三十九轮：金手指（gold-used）也能点断开 */
      var pg = e.target.closest ? e.target.closest('.wl-port.used, .wl-port.gold-used') : null;
      if (!pg) return;
      var port = pg.getAttribute('data-port');
      var hit = conns.filter(function (c) { return c.port === port; })[0];
      if (!hit) return;
      /* 金手指是「掌控板 ↔ 扩展板」的常驻连接，提示语要区分 */
      var what = hit.board
        ? '掌控板与扩展板的「' + port + '」金手指连接'
        : ((ZKB.deviceMeta && ZKB.deviceMeta(hit.devId)) || {}).name + ' 与 ' + port + ' 的连接';
      if (confirm('断开 ' + what + '？')) {
        conns = conns.filter(function (c) { return c !== hit; });
        saveConns();
        render();
        /* 第三十九轮：断开后明确告诉学生接口已恢复初始状态 */
        ZKB.toast('已断开，' + port + ' 接口恢复初始状态');
      }
    });
  }

  function cleanupWiring() {
    wiring = null;
    anchorDrag = false;
    var stage = $('wl-stage');
    if (stage) {
      stage.querySelectorAll('.wl-port.wiring').forEach(function (g) { g.classList.remove('wiring'); });
      stage.querySelectorAll('.wl-part.wire-src')
        .forEach(function (p) { p.classList.remove('wire-src'); });
      stage.querySelectorAll('.wl-port.wire-ok')
        .forEach(function (g) { g.classList.remove('wire-ok'); });
    }
    /* 恢复全部接口显示（清掉拉线高亮） */
    highlightPorts(null);
    drawLinks();
  }

  /* 完成连接：校验接口族（P12 不可用 / 接口族匹配 / M 口成对）后写入连接关系 */
  function tryConnect(devId, port) {
    /* 掌控板不支持的引脚（P12） */
    if (UNUSABLE_PINS[port]) {
      ZKB.toast('掌控板不支持 ' + port + ' 口，请选择其它接口');
      cleanupWiring();
      return;
    }
    /* 接口族必须匹配（第三十四轮：同族接口全部可连，不再按推荐列表限制） */
    var err = matchError(devId, port);
    if (err) {
      ZKB.toast(err);
      cleanupWiring();
      return;
    }
    var nm = ((ZKB.deviceMeta && ZKB.deviceMeta(devId)) || {}).name || devId;
    /* M 口成对：点 M± 任一接口即连接同组两个接口 */
    var pair = pairOf(port);
    if (pair) {
      var busy = M_PAIR_PORTS[pair].some(function (p) { return portOccupied(p, devId); });
      if (busy) {
        ZKB.toast(pair + ' 组已被占用，请选择另一组 M 口');
        cleanupWiring();
        return;
      }
      conns = conns.filter(function (c) { return c.devId !== devId; });
      conns.push({ devId: devId, port: pair });
      saveConns();
      ZKB.toast(nm + ' 已连接到 ' + pair + ' 组（' + M_PAIR_PORTS[pair].join(' / ') + '）');
      cleanupWiring();
      render();
      return;
    }
    conns = conns.filter(function (c) { return c.devId !== devId; });
    conns.push({ devId: devId, port: port });
    saveConns();
    ZKB.toast(nm + ' 已连接到 ' + port);
    cleanupWiring();
    render();
  }

  /* 从某个设备的控点开始拉线：记录设备 id 与控点侧，并在设备上做高亮标记 */
  function startWiringFrom(devId, side) {
    if (!devId) return;
    var stage = $('wl-stage');
    if (!stage) return;
    stage.querySelectorAll('.wl-part.wire-src')
      .forEach(function (p) { p.classList.remove('wire-src'); });
    var node = stage.querySelector('.wl-part[data-dev="' + devId + '"]');
    if (node) node.classList.add('wire-src');
    /* 线尾初始落在控点上 */
    var host = stage.getBoundingClientRect();
    var cx = host.width / 2, cy = host.height / 2;
    if (node) {
      var ap = anchorPosStage(node, side || 'r');
      cx = ap.x; cy = ap.y;
    }
    wiring = { devId: devId, side: side || 'r', mx: cx, my: cy };
    /* 只高亮引脚数匹配的接口 */
    highlightPorts(devId);
    drawLinks();
  }

  /* 端口类型 → 所需引脚数（用于校验与高亮） */
  var DEVICE_PINS_BY_PORT = {};
  function initPortPinMap() {
    allPorts().forEach(function (p) {
      DEVICE_PINS_BY_PORT[p.pin] = p.group === 'i2c' ? 4 : (p.group === 'motor' ? 2 : 3);
    });
  }

  /* ============================================================
   * 硬件右键菜单：删除 / 调整尺寸 / 选择接口（更多接口）/ 断开
   *
   * 第三十四轮：接口按「组」分区展示 —— IO 口 / I2C 口 / M 口，
   * 同组的接口全部可点（不再只列推荐的那几个），
   * 推荐接口用 ★ 标记。
   * ============================================================ */
  var PORT_GROUP_TITLE = {
    io: 'IO 口（3Pin）', i2c: 'I2C 口（4Pin）', motor: 'M 口（2Pin 电机驱动）'
  };
  function showPartMenu(id, x, y) {
    var m = ensurePartMenu();
    var conn = conns.filter(function (c) { return c.devId === id; })[0] || null;
    var lay = loadLayout();
    var pos = lay[id] || { k: 1 };
    var nm = ((ZKB.deviceMeta && ZKB.deviceMeta(id)) || {}).name || id;
    var list = menuPortsFor(id);
    /* 按接口组分区（保持 allPorts 顺序，推荐项加 ★） */
    var groups = [];
    list.forEach(function (p) {
      var g = groups.filter(function (x) { return x.key === p.group; })[0];
      if (!g) { g = { key: p.group, items: [] }; groups.push(g); }
      g.items.push(p);
    });
    var portsHTML = groups.map(function (g) {
      return '<div class="pm-sub pm-grp">' + esc(PORT_GROUP_TITLE[g.key] || g.key) + '</div>' +
        '<div class="pm-ports">' + g.items.map(function (p) {
          /* 已被其它硬件占用的接口置灰（M 组两个物理口都占用才算占用） */
          var busy = M_PAIR_PORTS[p.key]
            ? M_PAIR_PORTS[p.key].some(function (q) { return portOccupied(q, id); })
            : portOccupied(p.key, id);
          var cls = (conn && conn.port === p.key ? ' cur' : '') + (busy ? ' busy' : '');
          return '<button data-port="' + p.key + '" class="' + cls.trim() + '"' +
            (busy ? ' title="该接口已被其它硬件占用"' : '') + '>' +
            p.key + (p.rec ? ' ★' : '') + (busy ? ' ·占用' : '') + '</button>';
        }).join('') + '</div>';
    }).join('');

    m.innerHTML =
      '<div class="pm-title">' + esc(nm) + '</div>' +
      '<div class="pm-row"><span>尺寸</span>' +
      '<input type="range" data-act="k" min="50" max="220" value="' + Math.round((pos.k || 1) * 100) + '">' +
      '<b data-out="k">' + Math.round((pos.k || 1) * 100) + '%</b></div>' +
      '<div class="pm-sep"></div>' +
      '<div class="pm-sub">连线到接口<em class="pm-hint">（★ 为推荐接口，同组接口均可选）</em></div>' +
      portsHTML +
      (conn ? '<button data-act="disconnect" class="pm-warn">断开连接（' + conn.port + '）</button>' : '') +
      '<div class="pm-sep"></div>' +
      '<button data-act="reset">恢复默认位置</button>' +
      '<button data-act="remove" class="pm-danger">从拓展库移除该硬件</button>';

    m.classList.remove('hidden');
    var r = m.getBoundingClientRect();
    m.style.left = Math.max(4, Math.min(x, window.innerWidth - r.width - 8)) + 'px';
    m.style.top = Math.max(4, Math.min(y, window.innerHeight - r.height - 8)) + 'px';

    m.querySelectorAll('[data-act="k"]').forEach(function (inp) {
      inp.addEventListener('input', function () {
        m.querySelector('[data-out="k"]').textContent = inp.value + '%';
        var l = loadLayout();
        var p = l[id] || {};
        p.k = Number(inp.value) / 100;
        l[id] = p; saveLayout(l);
        var node = document.querySelector('.wl-part[data-dev="' + id + '"] .wl-part-in');
        if (node) node.style.transform = 'scale(' + p.k + ')';
      });
    });
    m.querySelectorAll('[data-port]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var port = btn.getAttribute('data-port');
        /* 已被其它硬件占用：提示并忽略 */
        var taken = M_PAIR_PORTS[port]
          ? M_PAIR_PORTS[port].some(function (p) { return portOccupied(p, id); })
          : portOccupied(port, id);
        if (taken) { ZKB.toast('接口 ' + port + ' 已被其它硬件占用，请选择其它接口'); return; }
        /* M 组按钮直接走成对连接逻辑（占用同组两个物理端口） */
        if (M_PAIR_PORTS[port]) {
          conns = conns.filter(function (c) { return c.devId !== id; });
          conns.push({ devId: id, port: port });
          saveConns();
          ZKB.toast(nm + ' 已连接到 ' + port + ' 组（' + M_PAIR_PORTS[port].join(' / ') + '）');
        } else {
          conns = conns.filter(function (c) { return c.devId !== id; });
          conns.push({ devId: id, port: port });
          saveConns();
          ZKB.toast(nm + ' 已连接到 ' + port);
        }
        hidePartMenu(); render();
      });
    });
    m.querySelectorAll('[data-act="disconnect"]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        conns = conns.filter(function (c) { return c.devId !== id; });
        saveConns(); hidePartMenu(); render();
        /* 第三十九轮：明确提示接口已恢复初始状态 */
        ZKB.toast(nm + ' 已断开，其占用接口恢复初始状态');
      });
    });
    m.querySelectorAll('[data-act="reset"]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var l = loadLayout();
        if (l[id]) { l[id].k = 1; l[id].x = 40; l[id].y = 40; saveLayout(l); }
        hidePartMenu(); render();
      });
    });
    m.querySelectorAll('[data-act="remove"]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (!confirm('从拓展库移除「' + nm + '」？')) return;
        /* 第四十轮：removeDevice() 内部已通过 removeDeviceConns()
           同步断开该设备的连线并重绘，这里不再重复处理。 */
        if (ZKB.SimBoard) ZKB.SimBoard.removeDevice(id);
        hidePartMenu();
        render();
      });
    });
  }
  /* 硬件连接区的右键菜单宿主
   *
   * 第三十五轮：全屏时右键菜单不显示的修复。
   * 原因：进入浏览器全屏后，浏览器只渲染 fullscreenElement 的子树，
   * 而菜单原先挂在 document.body 上 → 全屏里根本看不见。
   * 解决：菜单宿主随全屏状态切换，全屏时挂进全屏元素内部。 */
  function partMenuHost() {
    var fs = document.fullscreenElement;
    var st = $('wl-stage');
    /* 只有硬件连接区自己进入全屏才把菜单塞进去 */
    if (fs && (fs.id === 'wire-lib' || (st && fs.contains && fs.contains(st)))) return fs;
    return document.body;
  }
  function ensurePartMenu() {
    var m = $('wl-part-menu');
    if (!m) {
      m = document.createElement('div');
      m.id = 'wl-part-menu';
      m.className = 'wl-part-menu hidden';
      /* 点击外部关闭 */
      document.addEventListener('mousedown', function (e) {
        if (!m.contains(e.target)) m.classList.add('hidden');
      });
    }
    /* 宿主可能随全屏状态变化，这里保证它待在正确的父节点上 */
    var host = partMenuHost();
    if (m.parentNode !== host) host.appendChild(m);
    return m;
  }
  /* 全屏状态变化时把菜单挪到正确的宿主里 */
  function rehostPartMenu() {
    var m = $('wl-part-menu');
    if (!m) return;
    var host = partMenuHost();
    if (m.parentNode !== host) host.appendChild(m);
  }
  function hidePartMenu() {
    var m = $('wl-part-menu');
    if (m) m.classList.add('hidden');
  }

  /* ============================================================
   * 硬件连接区全屏（便于编辑与浏览）
   * ============================================================ */
  var wlFull = false;
  function toggleFullscreen() {
    wlFull = !wlFull;
    var box = $('wire-lib');
    if (box) box.classList.toggle('fullscreen', wlFull);
    document.body.classList.toggle('zk-wire-full', wlFull);
    var btn = $('wl-full');
    if (btn) {
      btn.textContent = wlFull ? '⛶ 退出全屏' : '⛶ 全屏';
      btn.classList.toggle('on', wlFull);
    }
    /* 视口变化后重算接口坐标与连线 */
    setTimeout(function () { render(); }, 60);
    if (wlFull && box && box.requestFullscreen) {
      try { box.requestFullscreen().catch(function () { }); } catch (e) { }
    } else if (!wlFull && document.fullscreenElement) {
      try { document.exitFullscreen().catch(function () { }); } catch (e) { }
    }
    /* 第三十五轮：全屏切换后右键菜单要挪到新的宿主里 */
    setTimeout(rehostPartMenu, 60);
    return wlFull;
  }
  function isFullscreen() { return wlFull; }

  /* ============================================================
   * 供其它模块调用
   * ============================================================ */
  ZKB.WireLib = {
    open: open, close: close, render: render, bindDrag: bindDrag,
    toggleFullscreen: toggleFullscreen,
    isFullscreen: isFullscreen,
    clearConnections: clearConnections,
    /* 第四十轮：删除设备时同步断开它的连接 */
    removeDeviceConns: removeDeviceConns,
    autoConnectAll: autoConnectAll,
    EXP_W: EXP_W, EXP_H: EXP_H,
    ports: function () { return allPorts(); },
    portGroups: portGroups,
    portsForDevice: portsForDevice,
    /* 同族全部接口（右键菜单可选的完整清单） */
    compatiblePorts: compatiblePorts,
    /* 右键菜单接口清单（含推荐标记与分组名） */
    menuPortsFor: menuPortsFor,
    /* 设备所属接口族：io / i2c / motor / net；板载设备为 null */
    ifaceOf: ifaceOf,
    groupOfPort: groupOfPort,
    groupName: function (g) { return GROUP_NAME[g] || g; },
    goldToBoard: GOLD_TO_BOARD,
    /* 掌控板不支持的引脚（当前仅 P12） */
    unusablePins: function () { var o = []; Object.keys(UNUSABLE_PINS).forEach(function (k) { o.push(k); }); return o; },
    devicePins: function (id) { return pinsOf(id); },
    /* 端口所需引脚数（校验用） */
    portNeed: function (port) {
      if (!DEVICE_PINS_BY_PORT[port]) initPortPinMap();
      return DEVICE_PINS_BY_PORT[port] || 3;
    },
    /* 校验硬件与接口是否匹配（不匹配返回错误文案） */
    checkMatch: function (devId, port) {
      return matchError(devId, port);
    },
    /* 该硬件是否需要接线（拓展库里没有接口的板载 / 无线设备不需要） */
    requiresConnection: function (devId) {
      return !!ifaceOf(devId);
    },
    /* 已添加但尚未完成硬件连接的设备（返回显示名列表） */
    unconnectedDevices: function () {
      var devs = (ZKB.SimBoard && ZKB.SimBoard.getDevices) ? ZKB.SimBoard.getDevices() : [];
      var out = [];
      devs.forEach(function (id) {
        if (!ZKB.WireLib.requiresConnection(id)) return;
        if (conns.some(function (c) { return c.devId === id; })) return;
        out.push(((ZKB.deviceMeta && ZKB.deviceMeta(id)) || {}).name || id);
      });
      return out;
    },
    /* 清理拉线状态 */
    cancelWiring: cleanupWiring,
    portOf: function (devId) {
      var base = (ZKB.baseOf ? ZKB.baseOf(devId) : devId);
      var rec = DEVICE_PORT[base] || [];
      return rec[0] || 'P13';
    },
    conns: function () { return conns.slice(); },
    isConnected: function (devId) {
      return conns.some(function (c) { return c.devId === devId; });
    },
    PORT_COLOR: KIND_COLOR
  };

})(window);