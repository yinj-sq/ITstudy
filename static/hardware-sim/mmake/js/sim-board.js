/* ============================================================
 * sim-board.js —— 虚拟仿真：掌控板 + 拓展设备卡片 + 交互状态
 * ============================================================ */
(function (global) {
  'use strict';
  var ZKB = global.ZKB || (global.ZKB = {});

  /* ---------------- 事件总线 ---------------- */
  var bus = {
    handlers: {},
    on: function (evt, fn) { (this.handlers[evt] || (this.handlers[evt] = [])).push(fn); },
    emit: function (evt, arg) {
      (this.handlers[evt] || []).forEach(function (fn) { try { fn(arg); } catch (e) { console.error(e); } });
    },
    clear: function () { this.handlers = {}; }
  };

  /* ---------------- 仿真状态 ---------------- */
  var state = {
    btn: { A: false, B: false },
    touch: { P: false, Y: false, T: false, H: false, O: false, N: false },
    light: 500, sound: 120, soundBurst: 0,
    randomMode: { sound: false, light: false },
    accel: { x: 0, y: 0, z: 1 },
    pins: {},
    rgb: { brightness: 0.8, dots: [[255, 0, 0], [255, 0, 0], [255, 0, 0]] },
    /* 通讯网络仿真状态（物联网情境） */
    net: {
      wifi: { connected: false, ssid: '' },
      radio: { group: 7, lastMsg: '' },
      ntp: { synced: false },
      mqtt: { connected: false, host: '', lastTopic: '', lastMsg: '' },
      asr: { text: '开灯' },
      weatherCity: '北京'
    },
    devices: {
      dht: { t: 26, h: 55 },
      ultrasonic: { cm: 30 },
      ir: { obs: false },
      servo: { angle: 90 },
      heater: { on: false, power: 0 },
      car: { x: 40, y: 50, deg: 90, l: 0, r: 0, obstacles: [], stageObs: [],
             _sx: 60, _sy: 250, _sdeg: 0 },
      motor: { vel: 0 },
      pump: { on: false, power: 0 },
      color: { name: 'red', r: 255, g: 30, b: 30, c: 315 },
      camera: { target: 'face', label: '人脸' },
      mic: { v: 100, burst: 0 },
      /* 巡线小车（第十四轮）：电机 + 循迹器 + 超声波 */
      traceCar: { l: 0, r: 0, auto: true, line: '离线', dist: 200, target: '' },
      lightExt: { v: 900 },
      soil: { v: 2000 },
      pm25: { v: 35 },
      baro: { p: 1013 },
      button: { on: false },
      fan: { on: false, power: 0 },
      /* —— DFRobot 新增硬件 —— */
      tracker: { ch: { L2: 0, L1: 0, C: 1, R1: 0, R2: 0 } },  // 1=检测到黑线
      powerMeter: { v: 5.0, a: 0.12, w: 0.6 },
      gravity: { r: 120, g: 200, b: 240, l: 560 },
      angle: { deg: 45 },
      irTx: { last: 0 },
      irRx: { code: '' },
      relay: { on: false },
      ledModule: { bright: 60 },
      rgbStrip: { r: 0, g: 0, b: 0, leds: null },
      buzzer: { on: false },
      remote: { code: '', dir: '' },
      /* 第三十六轮：新增人体红外与 MP3 模块的默认状态 */
      pir: { on: false, count: 0 },
      mp3: { playing: false, name: '', volume: 15 }
    },
    /* 硬件连接关系（由 wirelib 写入；未连接的硬件不参与工作） */
    connected: {},
    added: []
  };

  /* UI 刷新钩子（由本模块实现，引擎调用） */
  var ui = {};

  /* ============================================================
   * 第五十轮：设备卡片的「实时绘制函数」
   *   painters[设备实例 id] = function () { 读 state.devices[id] → 改 DOM }
   * 卡片重建时清空重登记；visualLoop 里周期性调用，
   * 于是「程序改了设备状态」和「学生在卡片上拖动」都能立刻反映到画面。
   * ============================================================ */
  var painters = {};

  /* ============================================================
   * 掌控板 SVG（外层 HTML 定位 + SVG 元件 + OLED canvas 叠加）
   * ============================================================ */
  function boardHTML() {
    return '' +
      '<div class="zk-board" style="position:relative;width:380px;height:236px;user-select:none">' +
      '<svg viewBox="0 0 420 260" width="380" height="236" style="position:absolute;inset:0">' +
      // PCB
      '<rect x="6" y="6" width="408" height="248" rx="20" fill="#2b2f36" stroke="#171a1e" stroke-width="2"/>' +
      // USB-C
      '<rect x="188" y="0" width="44" height="14" rx="4" fill="#9aa3ad"/><rect x="196" y="3" width="28" height="7" rx="2" fill="#5b6775"/>' +
      // A / B 按键
      '<g class="board-pressable" data-act="btn" data-key="A"><circle cx="78" cy="42" r="17" fill="#b98f33"/><circle cx="78" cy="42" r="7" fill="#23272d"/></g>' +
      '<text x="78" y="80" text-anchor="middle" fill="#c9d1d9" font-size="20" font-weight="bold">A</text>' +
      '<g class="board-pressable" data-act="btn" data-key="B"><circle cx="342" cy="42" r="17" fill="#b98f33"/><circle cx="342" cy="42" r="7" fill="#23272d"/></g>' +
      '<text x="342" y="80" text-anchor="middle" fill="#c9d1d9" font-size="20" font-weight="bold">B</text>' +
      // RGB 灯珠
      '<circle id="rgb-0" cx="190" cy="30" r="5" fill="#0d1013" stroke="#2c333a" stroke-width="1"/>' +
      '<circle id="rgb-1" cx="212" cy="30" r="5" fill="#0d1013" stroke="#2c333a" stroke-width="1"/>' +
      '<circle id="rgb-2" cx="234" cy="30" r="5" fill="#0d1013" stroke="#2c333a" stroke-width="1"/>' +
      // 麦克风（点击打开声音调节面板）
      '<g class="board-pressable" data-act="sensor" data-k="sound" title="点击调节麦克风数值 / 随机仿真">' +
      '<circle cx="32" cy="128" r="11" fill="#23272d" stroke="#4a525c" stroke-width="2"/>' +
      '<g stroke="#8a93a0" stroke-width="1.6"><line x1="28" y1="125" x2="28" y2="131"/><line x1="32" y1="123" x2="32" y2="133"/><line x1="36" y1="125" x2="36" y2="131"/></g></g>' +
      '<g class="board-pressable" data-act="sensor" data-k="sound">' +
      '<circle cx="388" cy="128" r="11" fill="#23272d" stroke="#4a525c" stroke-width="2"/>' +
      '<g stroke="#8a93a0" stroke-width="1.6"><line x1="384" y1="125" x2="384" y2="131"/><line x1="388" y1="123" x2="388" y2="133"/><line x1="392" y1="125" x2="392" y2="131"/></g></g>' +
      // 光线传感器（点击打开光照调节面板）
      '<g class="board-pressable" data-act="sensor" data-k="light" title="点击调节光线数值 / 随机仿真">' +
      '<circle cx="210" cy="196" r="9" fill="#15181c" stroke="#3a414c"/><circle cx="210" cy="196" r="3.4" fill="#6b5e22"/></g>' +
      // 触摸焊盘 P Y T H O N
      touchPadHTML() +
      // 丝印
      '<text x="210" y="178" text-anchor="middle" fill="#8a93a0" font-size="13" letter-spacing="2">掌 控 板</text>' +
      '</svg>' +
      // OLED（HTML canvas 叠加，坐标按 viewBox 比例）
      '<canvas id="oled-canvas" width="128" height="64" style="position:absolute;left:27.6%;top:33%;width:44.8%;height:38.5%;background:#05070a;border-radius:3px"></canvas>' +
      '<button id="btn-shake" style="position:absolute;right:2px;top:88px;height:26px;padding:0 10px;border:1px solid #4a525c;border-radius:13px;background:#3a414c;color:#e8ebef;font-size:12px;cursor:pointer">摇晃</button>' +
      '</div>';
  }

  /* ============================================================
   * 第二十五轮：掌控板语音小窗口
   * 点击屏幕下方右侧的「语音小圆点」弹出，内容为语音转文字 +
   * 文字转语音两块，与 ZKB.Speech 共用同一份状态，积木跑出来的
   * 结果也会同步显示在这里。
   * ============================================================ */
  function voicePanelHTML() {
    return '' +
      '<div class="zk-voice" id="voice-panel" hidden>' +
      '<div class="zk-voice-hd"><span class="zk-voice-ic">🎤🔊</span>' +
      '<b>AI 语音</b>' +
      '<button class="zk-voice-x" id="voice-close" title="关闭">×</button></div>' +
      /* ---- 语音转文字 ---- */
      '<div class="zk-voice-sec">' +
      '<div class="zk-voice-t">🎤 语音转文字</div>' +
      '<div class="zk-voice-row">' +
      '<select id="vp-asr-cmd" class="zk-voice-sel" title="留空＝随机听一句"></select>' +
      '<button id="vp-asr-run" class="zk-voice-btn primary">开始聆听</button>' +
      '</div>' +
      '<div class="zk-voice-out">听到：<b id="vp-asr-text">—</b>' +
      '<span class="zk-voice-conf">置信度 <b id="vp-asr-conf">—</b></span></div>' +
      '</div>' +
      /* ---- 文字转语音 ---- */
      '<div class="zk-voice-sec">' +
      '<div class="zk-voice-t">🔊 文字转语音</div>' +
      '<div class="zk-voice-row">' +
      '<input type="text" id="vp-tts-text" class="zk-voice-inp" value="你好，我是掌控板" maxlength="60">' +
      '<select id="vp-tts-rate" class="zk-voice-sel">' +
      '<option value="0.7">慢</option><option value="1" selected>正常</option>' +
      '<option value="1.4">快</option><option value="1.8">很快</option></select>' +
      '</div>' +
      '<div class="zk-voice-row">' +
      '<button id="vp-tts-play" class="zk-voice-btn primary">▶ 朗读</button>' +
      '<button id="vp-tts-stop" class="zk-voice-btn">■ 停止</button>' +
      '</div>' +
      '<div class="zk-voice-out">状态：<b id="vp-tts-st">空闲</b></div>' +
      '</div>' +
      '<div class="zk-voice-tip">提示：积木「启动语音转文字 / 朗读」的结果也会显示在这里</div>' +
      '</div>';
  }

  function openVoicePanel() {
    var panel = document.getElementById('voice-panel');
    if (!panel) return;
    panel.hidden = false;
    paintVoiceDot(true);
    placeVoicePanel();
    bindVoicePanel();
  }
  /* 把小窗贴到掌控板左侧。
     注意：3D 场景容器宽度就等于板宽（约 450px），绝对定位在场景内左侧放不下，
     所以这里用 fixed 定位 + 板子实测视口坐标，小窗挂到 body 上浮在板子左侧。
     板子带 rotateX 透视，必须用 getBoundingClientRect 实测而不是读样式值。 */
  function placeVoicePanel() {
    var panel = document.getElementById('voice-panel');
    var board = document.getElementById('b3-board-wrap');
    if (!panel || !board) return;
    var bb = board.getBoundingClientRect();
    var pw = panel.offsetWidth || 252;
    var ph = panel.offsetHeight || 240;
    var gap = 12;
    var left = bb.left - pw - gap;
    /* 左侧空间不足时改浮到右侧；再不行就压住板子左侧内缘，保证一定可见 */
    if (left < 8) {
      var right = bb.right + gap;
      left = (right + pw <= window.innerWidth) ? right : Math.max(8, bb.left + gap);
    }
    /* 垂直居中对齐板子（小圆点就在板子屏幕下方，视觉上更连贯） */
    var top = bb.top + bb.height / 2 - ph / 2;
    top = Math.max(8, Math.min(top, window.innerHeight - ph - 8));
    panel.style.left = Math.round(left) + 'px';
    panel.style.top = Math.round(top) + 'px';
  }
  function closeVoicePanel() {
    var panel = document.getElementById('voice-panel');
    if (panel) panel.hidden = true;
    paintVoiceDot(false);
  }
  /* 正反两面的语音小圆点一起高亮 */
  function paintVoiceDot(on) {
    var dots = document.querySelectorAll('.b3-voice-dot');
    for (var i = 0; i < dots.length; i++) dots[i].classList.toggle('on', !!on);
  }
  function toggleVoicePanel() {
    var panel = document.getElementById('voice-panel');
    if (!panel) return;
    if (panel.hidden) openVoicePanel(); else closeVoicePanel();
  }

  function touchPadHTML() {
    var pads = [
      { k: 'P', x: 62 }, { k: 'Y', x: 112 }, { k: 'T', x: 162 },
      { k: 'H', x: 210 }, { k: 'O', x: 258 }, { k: 'N', x: 308 }
    ];
    return pads.map(function (p) {
      return '<g class="board-pressable" data-act="touch" data-key="' + p.k + '">' +
        '<rect x="' + (p.x - 16) + '" y="212" width="32" height="30" rx="6" fill="#b98f33"/>' +
        '<rect x="' + (p.x - 8) + '" y="220" width="16" height="14" rx="3" fill="#2b2f36"/>' +
        '<text x="' + p.x + '" y="252" text-anchor="middle" fill="#c9d1d9" font-size="13" font-weight="bold">' + p.k + '</text></g>';
    }).join('');
  }

  /* ============================================================
   * 设备卡片
   * ============================================================ */

  /* 宽卡片设备（第十八轮）：
   * 这几类设备的控件天然偏宽——小车模型要放下地图+4 个操作按钮、
   * RGB 灯带要完整排开16 颗灯、巡线小车有 5 个电机按钮、
   * 红外遥控器是方向键盘 + 说明文字。挤在单列（控件区仅 131px）
   * 会大量折行、比例失调，故让其跨两列显示为「大卡片」，
   * 图标相应放大；其余设备一律用常规单列尺寸，保持整齐一致。*/
  /* 第五十二轮：把「带仿真画面的执行器」也升为宽卡片。
   *
   * 实测单列宽度只有 220px（控件区约 131px），而这几类卡片要同时放
   * 「可视化画面 + 读数 + 滑杆 + 若干快捷按钮」：
   *   LED 模块 239px、角度传感器 216px、人体红外 197px、功率计 185px、
   *   AS7341 173px、风扇 166px、巡线探针 165px、继电器 153px
   * 而同一行旁边的传感器卡片只有 147px —— 一行里高低相差近 100px，
   * 下面拖出一大片空白，非常参差。
   * 让它们跨两列（451px）后：控件能横排、高度回落到 130 左右，
   * 而且独占一行，不会再和单列卡片拼行。
   */
  var WIDE_DEVICES = {
    car: 1, rgbStrip: 1, traceCar: 1, remote: 1, weather: 1, camera: 1,
    ledModule: 1, relay: 1, pir: 1, fan: 1, angle: 1,
    tracker: 1, powerMeter: 1, gravity: 1
  };
  /* 这些卡片的控件区自带「设备仿真画面」（灯珠 / 雷达 / 表盘 / 探针…），
     已经能说明这是什么设备，不必再并排一个 64/88px 的静态图标。
     留着反而会挤掉控件宽度，还出现「卡片里有两个灯珠」的重复感。 */
  var SIM_VISUAL = {
    ledModule: 1, relay: 1, pir: 1, fan: 1, motor: 1,
    servo: 1, angle: 1, tracker: 1
    /* powerMeter / gravity 没有图形化画面（只有读数、滑杆和色块），
       隐藏图标反而让卡片失去主视觉，所以它们保留静态图标。 */
  };
  function isWide(id) {
    return !!WIDE_DEVICES[ZKB.baseOf(id)];
  }
  function hasSim(id) {
    return !!SIM_VISUAL[ZKB.baseOf(id)];
  }

  function cardHTML(id) {
    var meta = ZKB.deviceMeta(id);
    var pinTag = meta.pins.length ? meta.pins.join(' / ') : '底座';
    var wide = isWide(id);
    /* 宽卡片图标放大 88px（尺寸由 CSS 的 .dev-card.wide 规则控制，与两格宽度匹配） */
    var ico = wide ? 88 : 64;
    /* 第三十四轮：卡片上标出「已连接 / 未连接」，
       让学生一眼看出哪些硬件还没接线（没连线就不能运行程序） */
    var connTag = connTagHTML(id);
    /* 第五十二轮：有自带仿真画面的卡片加 has-sim，CSS 里会隐藏并列的静态图标 */
    var sim = hasSim(id);
    var cls = 'dev-card' + (wide ? ' wide' : '') + (sim ? ' has-sim' : '');
    var html = '<div class="' + cls + '" id="card-' + id + '" data-dev="' + id + '">' +
      '<div class="card-del" data-del="' + id + '" title="移除">×</div>' +
      '<div class="card-head">' + ZKB.deviceIcon(id, 22) + '<span>' + ZKB.deviceName(id) + '</span>' +
      connTag +
      '<span class="pin-tag">' + pinTag + '</span></div>' +
      '<div class="card-body">' +
      (sim ? '' : '<div class="card-icon">' + ZKB.deviceIcon(id, ico) + '</div>') +
      '<div class="ctrl">' + cardCtrl(id) + '</div></div></div>';
    return html;
  }

  /* 连接状态标签：需接线的设备显示「已连接 P13」/「未连接」，
     板载 / 无线设备不显示 */
  function connTagHTML(id) {
    if (!ZKB.WireLib || !ZKB.WireLib.requiresConnection) return '';
    if (!ZKB.WireLib.requiresConnection(id)) return '';
    var port = ZKB.SimBoard && ZKB.SimBoard.portOf ? ZKB.SimBoard.portOf(id) : null;
    if (port) {
      return '<span class="conn-tag ok" title="已连接到扩展板接口 ' + port + '">已连接 ' + port + '</span>';
    }
    return '<span class="conn-tag warn" title="还没连线，请到「硬件连接」中完成连线">未连接</span>';
  }

  function cardCtrl(id) {
    var base = ZKB.baseOf(id);
    switch (base) {
      /* 红外遥控器：可点击方向键控制小车 */
      case 'remote':
        return '<div class="val">当前按键 <b id="v-remote-dir">无</b></div>' +
          '<div class="pad-wrap">' +
          '<div class="dpad">' +
          '<button class="dp dp-up" data-dir="up" title="向上">▲</button>' +
          '<button class="dp dp-left" data-dir="left" title="向左">◀</button>' +
          '<button class="dp dp-mid" data-dir="ok" title="确定">OK</button>' +
          '<button class="dp dp-right" data-dir="right" title="向右">▶</button>' +
          '<button class="dp dp-down" data-dir="down" title="向下">▼</button>' +
          '</div>' +
          '<div class="pad-info">点击方向键即可控制小车电机<br>（也可编写程序响应按键）</div>' +
          '</div>';
      /* RGB 灯带：逐颗点亮预览 */
      case 'rgbStrip':
        return '<div class="val">灯带 16 颗　亮灯 <b id="v-strip-n">0</b> 颗</div>' +
          '<div class="strip-wrap"><div class="strip" id="card-strip"></div></div>' +
          '<div class="chip-row">' +
          '<span class="chip-btn" data-strip="r">红</span>' +
          '<span class="chip-btn" data-strip="g">绿</span>' +
          '<span class="chip-btn" data-strip="b">蓝</span>' +
          '<span class="chip-btn" data-strip="off">全灭</span>' +
          '<span class="chip-btn" data-strip="all">全亮</span>' +
          '</div>';
      case 'expboard':
        return '<div class="val">拓展板已连接：P0~P28 扩展接口可用</div>' +
          '<div class="chip-row"><span class="chip-btn">VCC</span><span class="chip-btn">GND</span>' +
          '<span class="chip-btn">4PIN×N</span></div>';
      case 'dht':
        return '<div class="val">温度 <b id="v-dht-t">26</b> ℃　湿度 <b id="v-dht-h">55</b> %</div>' +
          slider('dht-t', '温度', -10, 50, 26) + slider('dht-h', '湿度', 0, 100, 55);
      case 'ultrasonic':
        return '<div class="val">距离 <b id="v-ultra">30</b> cm</div>' +
          slider('ultra', '障碍物距离', 2, 200, 30);
      case 'servo':
        return '<div class="servo-wrap"><svg viewBox="0 0 60 52" width="60" height="52">' +
          '<rect x="6" y="20" width="48" height="26" rx="4" fill="#2f6fb2"/>' +
          '<rect x="2" y="26" width="5" height="9" rx="2" fill="#245a92"/>' +
          '<rect x="53" y="26" width="5" height="9" rx="2" fill="#245a92"/>' +
          '<circle cx="30" cy="20" r="8" fill="#245a92"/>' +
          '<g class="servo-horn" style="transform-box:view-box;transform-origin:30px 20px">' +
          '<rect x="27" y="-6" width="6" height="26" rx="3" fill="#e8edf2"/>' +
          '<circle cx="30" cy="-1" r="1.8" fill="#9aa6b0"/>' +
          '<circle cx="30" cy="8" r="1.8" fill="#9aa6b0"/>' +
          '</g>' +
          '<circle cx="30" cy="20" r="3.2" fill="#c9d4de"/>' +
          '</svg></div>' +
          '<div class="val">角度 <b id="v-servo">90</b>°</div>' +
          '<div class="chip-row"><span class="chip-btn" data-servo="0">0°</span><span class="chip-btn" data-servo="90">90°</span>' +
          '<span class="chip-btn" data-servo="180">180°</span></div>';
      case 'ir':
        return '<div class="val">状态：<b id="v-ir">无障碍物</b></div>' +
          '<div class="chip-row"><span class="chip-btn" id="ir-toggle">放置 / 移开障碍物</span></div>';
      case 'heater':
        return '<div class="val">功率 <b id="v-heater">0</b>%</div>' + slider('heater', '加热功率', 0, 100, 0);
      case 'car':
        return '<canvas id="car-map" width="150" height="92" style="width:100%;max-width:150px;aspect-ratio:150/92;border:1px solid #dfe4ea;border-radius:6px;background:#f3faf5;cursor:crosshair" title="点击地图放置障碍物，右键障碍物移除"></canvas>' +
          '<div class="val">左轮 <b id="v-car-l">0</b>　右轮 <b id="v-car-r">0</b></div>' +
          '<div class="chip-row"><span class="chip-btn" id="car-clear-obs">清除障碍物</span>' +
          '<span class="chip-btn" id="car-reset-pos">复位小车</span></div>' +
          '<div class="val" style="font-size:10px;color:#9aa3af">左键放障碍物 / 右键移除 / 前方障碍 <b id="v-car-dist">--</b> cm</div>';
      case 'motor':
        return '<div class="rotor-wrap"><svg viewBox="0 0 66 46" width="66" height="46">' +
          '<rect x="4" y="14" width="30" height="24" rx="5" fill="#5a6672"/>' +
          '<rect x="4" y="14" width="7" height="24" rx="3" fill="#48525c"/>' +
          '<rect x="34" y="23" width="10" height="5" fill="#9aa6b0"/>' +
          '<g transform="translate(50,25)">' +
          '<g class="spin motor-spin">' +
          [0, 90, 180, 270].map(function (a) {
            return '<path d="M0,0 Q9,-7 15,-2 Q9,4 0,0Z" fill="#8ecae6" transform="rotate(' + a + ')"/>';
          }).join('') +
          '</g><circle r="3.4" fill="#4a5560"/></g>' +
          '</svg></div>' +
          '<div class="val">转速 <b id="v-motor">0</b></div>' +
          '<div class="chip-row"><span class="chip-btn" data-motor="60">正转</span><span class="chip-btn" data-motor="-60">反转</span>' +
          '<span class="chip-btn" data-motor="0">停止</span></div>';
      case 'pump':
        return '<div class="val">状态 <b id="v-pump">关闭</b>　功率 <b id="v-pump-p">0</b>%</div>' +
          slider('pump', '水泵功率', 0, 100, 0);
      case 'color':
        return '<div class="val">识别：<b id="v-color">红色</b></div>' +
          '<div class="chip-row">' +
          [['red', '红'], ['green', '绿'], ['blue', '蓝'], ['yellow', '黄'], ['purple', '紫'], ['white', '白'], ['black', '黑']]
            .map(function (p) { return '<span class="chip-btn" data-color="' + p[0] + '">' + p[1] + '</span>'; }).join('') +
          '</div>';
      case 'camera':
        /* 第二十四轮布局：左上角图标 + 右侧取景框 → 下方摄像头按钮 → 再下三大识别面板 */
        return '<div class="cam-wrap">' +
          /* ---- 第一层：左上角图标 + 右侧摄像头画面 ---- */
          '<div class="cam-top">' +
          '<div class="cam-logo" id="cam-logo" title="AI 摄像头">' + ZKB.deviceIcon(id, 56) + '</div>' +
          '<div class="cam-viewbox" id="cam-view" title="点击切换识别目标">' +
          '<div class="cam-screen" id="cam-fallback">' +
          '<span id="cam-label">人脸</span></div></div>' +
          '</div>' +
          /* ---- 第二层：摄像头按钮（状态提示并入按钮区，保持 .cam-wrap 只有三段） ---- */
          '<div class="cam-btns">' +
          '<span class="chip-btn primary" id="cam-shot">📸 拍照识别</span>' +
          '<span class="chip-btn" id="cam-real">📷 调用电脑摄像头</span>' +
          '<span class="chip-btn" id="cam-upload">🖼️ 上传图片</span>' +
          '<span class="chip-btn" id="cam-clear">✕ 清除画面</span>' +
          '<span class="cam-src" id="cam-real-st">未调用摄像头时使用模拟识别；也可上传图片模拟</span>' +
          '</div>' +
          /* ---- 第三层：文字识别 / 人脸识别 / 物体识别 ---- */
          '<div class="cam-panels">' +
          /* 文字识别 */
          '<div class="cam-panel" data-cam="ocr">' +
          '<div class="cam-sub">🔤 文字识别</div>' +
          '<div class="chip-row">' +
          '<span class="chip-btn" data-vmode="text">印刷文字</span>' +
          '<span class="chip-btn" data-vmode="number">印刷数字</span></div>' +
          '<div class="val">结果：<b id="v-vis-ocr">—</b></div>' +
          '</div>' +
          /* 人脸识别 */
          '<div class="cam-panel" data-cam="face">' +
          '<div class="cam-sub">😊 人脸识别</div>' +
          '<div class="chip-row"><span class="chip-btn" id="face-add">＋ 录入人脸</span>' +
          '<span class="chip-btn" id="face-verify">🔍 人脸验证</span></div>' +
          '<div class="face-list" id="face-list"></div>' +
          '<div class="val">姓名 <b id="v-face-name">—</b>　性别 <b id="v-face-gender">—</b></div>' +
          '<div class="val">简介 <b id="v-face-bio">—</b></div>' +
          '<div class="val">情绪 <b id="v-face-emo">—</b></div>' +
          '</div>' +
          /* 物体识别 */
          '<div class="cam-panel" data-cam="obj">' +
          '<div class="cam-sub">📦 物体识别</div>' +
          '<div class="chip-row">' +
          '<span class="chip-btn" data-vcat="car">车型</span>' +
          '<span class="chip-btn" data-vcat="animal">动物</span>' +
          '<span class="chip-btn" data-vcat="plant">植物</span>' +
          '<span class="chip-btn" data-vcat="dish">菜品</span>' +
          '<span class="chip-btn" data-vcat="fruit">果蔬</span></div>' +
          '<div class="val">结果：<b id="v-vis-obj">—</b></div>' +
          '<div class="val">置信度：<b id="v-vis-conf">—</b>%</div>' +
          '</div>' +
          '</div></div>';
      case 'mic':
        return '<div class="val">音量 <b id="v-mic">100</b></div>' +
          '<div class="chip-row"><span class="chip-btn" id="mic-burst">制造声音</span></div>' +
          slider('mic', '环境音量', 0, 4095, 100) +
          '<div class="chip-row"><span class="chip-btn" id="mic-real">🎙️ 调用电脑麦克风</span></div>' +
          '<div class="val" id="mic-real-st" style="font-size:10px;color:#9aa3af">未调用时使用「制造声音」按钮模拟</div>';
      case 'robot':
        return '<div class="val">巡线机器人（超声波 + AI 摄像头 + 语音）</div>' +
          '<div class="val" style="font-size:10px;color:#9aa3af">已同步舞台「机器人」元素<br>' +
          '用「机器人」分类积木控制巡线 / 测距 / 识别</div>' +
          '<div class="chip-row"><span class="chip-btn" id="robot-go-stage">舞台出发 / 停止</span></div>';
      case 'traceCar':
        return '<div class="val">电机 左 <b id="v-tc-l">0</b>　右 <b id="v-tc-r">0</b></div>' +
          '<div class="chip-row">' +
          '<span class="chip-btn" data-tc="f">前进</span><span class="chip-btn" data-tc="b">后退</span>' +
          '<span class="chip-btn" data-tc="l">左转</span><span class="chip-btn" data-tc="r">右转</span>' +
          '<span class="chip-btn" data-tc="s">停止</span></div>' +
          '<div class="chip-row"><span class="chip-btn" id="tc-auto">自动巡线：开</span></div>' +
          '<div class="val">循线 <b id="v-tc-line">离线</b>　前方 <b id="v-tc-dist">--</b> cm</div>' +
          '<div class="val" style="font-size:10px;color:#9aa3af">自动巡线需在舞台上布置「赛道黑线」元素</div>';
      case 'lightExt':
        return '<div class="val">光照 <b id="v-light-ext">900</b></div>' + slider('light-ext', '光照强度', 0, 4095, 900);
      case 'soil':
        return '<div class="val">湿度 <b id="v-soil">2000</b></div>' + slider('soil', '土壤湿度', 0, 4095, 2000);
      case 'pm25':
        return '<div class="val">浓度 <b id="v-pm25">35</b> μg/m³</div>' + slider('pm25', 'PM2.5', 0, 250, 35);
      case 'baro':
        return '<div class="val">气压 <b id="v-baro">1013</b> hPa</div>' + slider('baro', '大气压', 950, 1050, 1013);
      case 'button':
        return '<div class="val">状态：<b id="v-btn">未按下</b></div>' +
          '<div class="chip-row"><span class="chip-btn" id="btn-press">按下 / 松开</span></div>';
      case 'fan':
        /* 第五十二轮：画面与读数并排（宽卡片里不再是「一个大圆 + 左下角两行字」） */
        return '<div class="ctrl-row">' +
          '<div class="fan-wrap"><svg viewBox="0 0 64 64" width="76" height="76">' +
          '<circle cx="32" cy="32" r="29" fill="none" stroke="#8794a3" stroke-width="2"/>' +
          '<circle cx="32" cy="32" r="20" fill="none" stroke="#a6b2c0" stroke-width="1.4"/>' +
          '<g transform="translate(32,32)"><g class="spin fan-spin">' +
          [0, 120, 240].map(function (a) {
            return '<path d="M0,0 C0,-15 9,-21 13,-13 C16,-7 6,-2 0,0Z" fill="#5fb3d4" ' +
              'transform="rotate(' + a + ')"/>';
          }).join('') +
          '</g><circle r="4.6" fill="#3a414c"/></g>' +
          '</svg></div>' +
          '<div class="ctrl-col">' +
          '<div class="val">功率 <b id="v-fan">0</b>%</div>' +
          slider('fan', '风扇功率', 0, 100, 0) +
          '</div></div>';

      /* —— 通讯网络 —— */
      case 'wifi':
        return '<div class="val">状态：<b id="v-wifi">未连接</b></div>' +
          '<div class="val" id="v-wifi-ssid" style="font-size:10px;color:#9aa3af">运行「连接 WiFi」积木后自动联网</div>' +
          '<div class="chip-row"><span class="chip-btn" id="wifi-toggle">模拟联网 / 断网</span></div>';
      case 'radio':
        return '<div class="val">频道 <b id="v-radio-g">7</b>　最后收到 <b id="v-radio-msg">—</b></div>' +
          '<input type="text" id="radio-in" value="你好" style="width:90px;font-size:11px;padding:2px 4px">' +
          '<div class="chip-row"><span class="chip-btn" id="radio-test">模拟收到广播</span></div>';
      case 'ntp':
        return '<div class="val">对时：<b id="v-ntp">未同步</b></div>' +
          '<div class="val" id="v-ntp-time" style="font-size:13px">— —</div>' +
          '<div class="chip-row"><span class="chip-btn" id="ntp-test">模拟对时成功</span></div>';
      case 'mqtt':
        return '<div class="val">状态：<b id="v-mqtt">未连接</b></div>' +
          '<div style="font-size:10px;color:#9aa3af">主题 <input type="text" id="mqtt-topic" value="/classroom/light" style="width:130px;font-size:11px;padding:2px 4px"></div>' +
          '<div style="font-size:10px;color:#9aa3af;margin-top:3px">消息 <input type="text" id="mqtt-msg" value="on" style="width:130px;font-size:11px;padding:2px 4px"></div>' +
          '<div class="chip-row"><span class="chip-btn" id="mqtt-inject">模拟服务器下发消息</span></div>';
      case 'asr':
        return '<div class="val">识别到：<b id="v-asr">开灯</b></div>' +
          '<div class="chip-row">' +
          [['开灯', 0], ['关灯', 1], ['开风扇', 2], ['关风扇', 3], ['播放音乐', 4], ['停止', 5]]
            .map(function (p) { return '<span class="chip-btn" data-asr="' + p[0] + '">' + p[0] + '</span>'; }).join('') +
          '</div>';
      case 'weather':
        return '<div class="wx-top">' +
          '<div class="wx-city-line">' +
          '<b id="v-weather-city">北京</b>' +
          '<span class="wx-src" id="v-weather-src">未查询</span>' +
          '<span class="chip-btn" id="wx-refresh" title="重新联网查询">↻ 刷新</span>' +
          '</div>' +
          /* 六项数据区（与天气积木的六个取值一一对应） */
          '<div class="wx-grid" id="wx-grid">' +
          [['text', '天气现象', '—'], ['high', '最高温', '—'], ['low', '最低温', '—'],
          ['humidity', '湿度', '—'], ['wind', '风向', '—'], ['windLevel', '风力', '—']]
            .map(function (p) {
              return '<div class="wx-cell" data-wx="' + p[0] + '">' +
                '<span class="wx-k">' + p[1] + '</span>' +
                '<span class="wx-v" id="wx-' + p[0] + '">' + p[2] + '</span></div>';
            }).join('') +
          '</div>' +
          '<div class="val" id="v-weather-now">点击城市查询真实天气；无网络时按月份模拟</div>' +
          '</div>' +
          /* 城市库：内置 + 手动添加 */
          '<div class="wx-citybox">' +
          '<div class="wx-sub">城市库（点击查询）</div>' +
          '<div class="wx-cities" id="wx-cities"></div>' +
          '<div class="wx-add">' +
          '<input type="text" id="wx-new" placeholder="输入城市名，如：成都" maxlength="12">' +
          '<span class="chip-btn primary" id="wx-add-btn">＋ 添加城市</span>' +
          '<span class="wx-hint" id="wx-msg">点击 × 可移除手动添加的城市</span>' +
          '</div>' +
          '<div class="val" style="font-size:10px;color:#9aa3af">' +
          '数据已同步到积木「城市 □ 的天气 □」，六个选项对应上方六项</div>' +
          '</div>';
      /* ---------- 第二十九轮：八年级新增硬件 ---------- */
      case 'magnetic':
        return '<div class="val">方位角 <b id="v-mag">0</b> °（0=正北 90=正东）</div>' +
          slider('mag', '磁场方位角', 0, 359, 0) +
          '<div class="chip-row">' +
          '<span class="chip-btn" data-magdir="0">正北</span>' +
          '<span class="chip-btn" data-magdir="90">正东</span>' +
          '<span class="chip-btn" data-magdir="180">正南</span>' +
          '<span class="chip-btn" data-magdir="270">正西</span>' +
          '<span class="chip-btn" id="mag-cal">校准</span>' +
          '<span class="chip-btn" id="mag-peel">去皮</span>' +
          '</div>' +
          '<div class="val" style="font-size:10px;color:#9aa3af">提示：先点「校准」，再转动板子测方位角</div>';
      case 'gps':
        return '<div class="val">状态：<b id="v-gps">未定位</b>　卫星 <b id="v-gps-n">0</b> 颗</div>' +
          '<div class="val" id="v-gps-loc" style="font-size:11px">经度 —　纬度 —　海拔 —</div>' +
          '<div class="val" id="v-gps-time" style="font-size:10px;color:#9aa3af">UTC —</div>' +
          '<div class="chip-row">' +
          '<span class="chip-btn" id="gps-search">模拟搜星（8 颗）</span>' +
          '<span class="chip-btn" id="gps-lost">丢失信号</span>' +
          '</div>' +
          /* 第三十三轮：调用电脑真实定位 */
          '<div class="chip-row">' +
          '<span class="chip-btn primary" id="gps-real" title="调用浏览器 Geolocation API，取电脑/手机的实际位置">' +
          '📍 用电脑定位（真实数据）</span>' +
          '</div>' +
          '<div class="val" id="gps-real-info" style="font-size:10px;color:#9aa3af"></div>' +
          '<div class="val" style="font-size:10px;color:#9aa3af">' +
          '真实模块要 outdoors 才能搜到星，室内基本无信号。<br>' +
          '「用电脑定位」需用 http://localhost 打开页面并允许定位权限。</div>';
      case 'rfid':
        return '<div class="val">已读卡号：<b id="v-rfid">—</b></div>' +
          '<div class="chip-row" id="rfid-cards">' +
          [['1380013800', '卡A'], ['1380013801', '卡B'], ['1380013802', '卡C']]
            .map(function (p) { return '<span class="chip-btn" data-rfid="' + p[0] + '">' + p[1] + '</span>'; }).join('') +
          '</div>' +
          '<div class="val" style="font-size:10px;color:#9aa3af">点击卡片即模拟刷卡；「扫描」积木会读出卡号</div>';
      case 'speech2':
        return '<div class="val">识别到：<b id="v-asr2">—</b></div>' +
          '<div class="chip-row">' +
          [['开灯', 0], ['关灯', 1], ['开风扇', 2], ['关风扇', 3], ['停止', 4]]
            .map(function (p) { return '<span class="chip-btn" data-asr2="' + p[0] + '">' + p[0] + '</span>'; }).join('') +
          '</div>' +
          '<div class="val" style="font-size:10px;color:#9aa3af">离线识别模块不联网，只能识别这几条固定指令</div>';
      case 'qrcode':
        return '<div class="val">二维码内容：<b id="v-qr">—</b></div>' +
          '<div class="val" style="font-size:10px;color:#9aa3af">' +
          '积木「屏幕生成二维码」会把内容画到OLED 上，扫码枪可真读</div>';

      /* ============================================================
       * 第五十轮：补齐原来只有图标、没有任何可视化的执行器 / 传感器
       *
       * 之前 ledModule / relay / pir / mp3 / tracker / powerMeter /
       * gravity / angle / irTx / irRx 在 cardCtrl 里都落到 default，
       * 卡片上只剩一个图标 —— 程序把 LED 调到 100% 也完全看不出来，
       * 舞台那边虽然会亮，但学生分不清「是程序生效了还是本来就这样」。
       * 这里给每块都补上「看得见的输出」，并在 visualLoop 里实时同步。
       * ============================================================ */

      /* LED 模块：灯珠 + 光晕 + 亮度滑杆 + 快捷档位 */
      case 'ledModule':
        return '<div class="ctrl-row"><div class="led-sim">' +
          '<svg viewBox="0 0 120 78" width="100%" height="78" preserveAspectRatio="xMidYMid meet">' +
          '<ellipse id="led-glow" cx="60" cy="46" rx="26" ry="26" fill="#ffd24a" opacity="0"/>' +
          '<rect x="14" y="34" width="92" height="26" rx="5" fill="#2b3038" ' +
          'stroke="#454f5a" stroke-width="1.4"/>' +
          '<circle id="led-base" cx="60" cy="47" r="10.6" fill="#0b0e11" ' +
          'stroke="#5a5040" stroke-width="1.4"/>' +
          '<circle id="led-lens" cx="60" cy="47" r="8.2" fill="#3a3126"/>' +
          '<circle id="led-hot" cx="60" cy="47" r="3.4" fill="#fff" opacity="0"/>' +
          '</svg></div>' +
          /* 第五十二轮：画面与读数左右并排（ctrl-row 窄的时候自动折成上下），
             原来六行竖排把卡片顶到 240px 高，比同区的宽卡片高出 90px */
          '<div class="ctrl-col">' +
          '<div class="val">亮度 <b id="v-led">60</b>%　<b id="v-led-on">点亮</b></div>' +
          slider('led', '亮度', 0, 100, 60) +
          '</div></div>' +
          '<div class="chip-row">' +
          '<span class="chip-btn" data-led="0">关灯</span>' +
          '<span class="chip-btn" data-led="50">50%</span>' +
          '<span class="chip-btn" data-led="100">全亮</span>' +
          '</div>' +
          '<div class="val tip">运行后灯珠实时变化，舞台台灯同步变亮</div>';

      /* 数字继电器：触点状态 + 指示灯 */
      case 'relay':
        return '<div class="val">触点 <b id="v-relay">断开</b></div>' +
          '<div class="relay-box">' +
          '<span class="relay-led" id="relay-led"></span>' +
          '<span class="relay-txt" id="relay-txt">常开触点断开</span></div>' +
          '<div class="chip-row">' +
          '<span class="chip-btn" data-relay="1">吸合</span>' +
          '<span class="chip-btn" data-relay="0">断开</span></div>' +
          '<div class="val" style="font-size:10px;color:#9aa3af">' +
          '程序打开继电器时，舞台上的「电器」同步通电</div>';

      /* 人体红外：有人 / 无人 + 触发次数 */
      case 'pir':
        return '<div class="val">状态：<b id="v-pir">无人</b>　触发 <b id="v-pir-n">0</b> 次</div>' +
          /* 第五十二轮：雷达条里补上文字，否则宽卡片中间只有一个小圆点，空得很 */
          '<div class="pir-radar" id="pir-radar"><span class="pir-dot"></span>' +
          '<span class="pir-txt" id="pir-txt">感应范围内无人</span></div>' +
          '<div class="chip-row">' +
          '<span class="chip-btn" id="pir-toggle">有人经过 / 无人</span>' +
          '<span class="chip-btn" id="pir-reset">计数清零</span></div>' +
          '<div class="val" style="font-size:10px;color:#9aa3af">' +
          'PIR 只能判断「有人 / 无人」，测不出距离</div>';

      /* MP3 模块：音量 + 曲目 + 播放状态 */
      case 'mp3':
        return '<div class="val">音量 <b id="v-mp3-vol">15</b>　<b id="v-mp3-st">停止</b></div>' +
          '<div class="val">曲目 <b id="v-mp3-name">—</b></div>' +
          slider('mp3', '音量', 0, 30, 15) +
          '<div class="chip-row">' +
          '<span class="chip-btn" data-mp3="play">▶ 播放 001</span>' +
          '<span class="chip-btn" data-mp3="stop">■ 停止</span></div>';

      /* 五路巡线传感器：5 个探针的压线状态 */
      case 'tracker':
        return '<div class="val">压线 <b id="v-trk-n">1</b> / 5 路</div>' +
          '<div class="trk-row" id="trk-row">' +
          ['L2', 'L1', 'C', 'R1', 'R2'].map(function (k) {
            return '<span class="trk-dot" data-trk="' + k + '" title="' + k + '">' + k + '</span>';
          }).join('') + '</div>' +
          '<div class="chip-row">' +
          '<span class="chip-btn" id="trk-center">回到中线</span></div>' +
          '<div class="val" style="font-size:10px;color:#9aa3af">' +
          '深色 = 该路压在黑线上。小车在赛道上行驶时实时变化</div>';

      /* 数字功率计：电压 / 电流 / 功率 */
      case 'powerMeter':
        return '<div class="val">电压 <b id="v-pw-v">5.00</b> V　电流 <b id="v-pw-a">0.12</b> A</div>' +
          '<div class="val">功率 <b id="v-pw-w">0.60</b> W</div>' +
          slider('pw', '负载电流(mA)', 0, 500, 120) +
          '<div class="val" style="font-size:10px;color:#9aa3af">拖动改变电流，功率 = 电压 × 电流</div>';

      /* AS7341 颜色传感器：RGB 分量 + 亮度 */
      case 'gravity':
        return '<div class="val">R <b id="v-gr-r">120</b>　G <b id="v-gr-g">200</b>　B <b id="v-gr-b">240</b></div>' +
          '<div class="val">环境亮度 <b id="v-gr-l">560</b></div>' +
          '<div class="chip-row" id="gr-swatches"></div>' +
          '<div class="val" style="font-size:10px;color:#9aa3af">点色块切换被测物体的颜色</div>';

      /* 角度传感器：角度 + 快捷档位 */
      case 'angle':
        /* 第五十二轮：表盘与读数并排；四个快捷角度挪到滑杆下面一行，整体降了约 50px */
        return '<div class="ctrl-row">' +
          '<div class="ang-dial"><span class="ang-needle" id="ang-needle"></span></div>' +
          '<div class="ctrl-col">' +
          '<div class="val">角度 <b id="v-ang">45</b>°</div>' +
          slider('ang', '旋转角度', 0, 300, 45) +
          '</div></div>' +
          '<div class="chip-row">' +
          [0, 90, 180, 300].map(function (a) {
            return '<span class="chip-btn" data-ang="' + a + '">' + a + '°</span>';
          }).join('') + '</div>';

      /* 红外发射：最近发出的码值 */
      case 'irTx':
        return '<div class="val">最近发出：<b id="v-irtx">—</b></div>' +
          '<div class="chip-row">' +
          ['0x0C', '0x18', '0x5E'].map(function (c) {
            return '<span class="chip-btn" data-irtx="' + c + '">' + c + '</span>';
          }).join('') + '</div>' +
          '<div class="val" style="font-size:10px;color:#9aa3af">' +
          '同时添加「红外接收模块」才能收到自己发的码</div>';

      /* 红外接收：最近收到的码值 */
      case 'irRx':
        return '<div class="val">最近收到：<b id="v-irrx">—</b></div>' +
          '<div class="chip-row">' +
          '<span class="chip-btn" id="irrx-inject">模拟收到 0x0C</span></div>' +
          '<div class="val" style="font-size:10px;color:#9aa3af">' +
          '也可以点「红外遥控器」卡片的方向键</div>';
      default: return '';
    }
  }
  function slider(id, label, min, max, val) {
    return '<label style="font-size:10px;color:#9aa3af">' + label +
      '<input type="range" id="sl-' + id + '" min="' + min + '" max="' + max + '" value="' + val + '"></label>';
  }

  /* ---------------- 颜色卡片预设 ---------------- */
  var COLOR_PRESETS = {
    red: { r: 255, g: 30, b: 30, c: 315, label: '红色' },
    green: { r: 30, g: 230, b: 60, c: 320, label: '绿色' },
    blue: { r: 40, g: 70, b: 255, c: 330, label: '蓝色' },
    yellow: { r: 250, g: 220, b: 40, c: 470, label: '黄色' },
    purple: { r: 190, g: 40, b: 220, c: 300, label: '紫色' },
    white: { r: 250, g: 250, b: 250, c: 760, label: '白色' },
    black: { r: 15, g: 15, b: 18, c: 25, label: '黑色' }
  };
  var CAM_TARGETS = [['face', '人脸'], ['person', '行人'], ['object', '物体'], ['color', '颜色'], ['qrcode', '二维码']];

  /* ---------- AI 摄像头辅助 ---------- */
  function camEsc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  /* 人脸录入对话框：支持「上传人脸图片」与「摄像头拍照」两种取材方式，
     再填姓名 / 性别 / 简介，确认后回调 onSave(name, gender, bio, imgDataUrl)。*/
  function openFaceDialog(onSave) {
    var old = document.getElementById('face-dlg');
    if (old) old.parentNode.removeChild(old);
    var wrap = document.createElement('div');
    wrap.id = 'face-dlg';
    wrap.className = 'face-dlg';
    wrap.innerHTML =
      '<div class="face-dlg-box">' +
      '<div class="face-dlg-title">录入人脸信息</div>' +
      '<div class="face-dlg-shot" id="fd-prev"><span>还没有人脸照片<br>请上传图片或用摄像头拍照</span></div>' +
      '<div class="chip-row">' +
      '<label class="chip-btn primary">📁 上传人脸图片<input type="file" id="fd-file" accept="image/*" hidden></label>' +
      '<span class="chip-btn" id="fd-shoot">📷 摄像头拍照</span>' +
      '<span class="chip-btn" id="fd-clear">清除</span>' +
      '</div>' +
      '<div class="fd-row"><label>姓名</label><input type="text" id="fd-name" placeholder="如：张小明" maxlength="12"></div>' +
      '<div class="fd-row"><label>性别</label>' +
      '<select id="fd-gender"><option value="male">男</option><option value="female">女</option></select></div>' +
      '<div class="fd-row"><label>简介</label><input type="text" id="fd-bio" placeholder="如：三年级二班班长" maxlength="30"></div>' +
      '<div class="chip-row" style="justify-content:flex-end;margin-top:8px">' +
      '<span class="chip-btn" id="fd-cancel">取消</span>' +
      '<span class="chip-btn primary" id="fd-ok">保存人脸</span>' +
      '</div></div>';
    document.body.appendChild(wrap);
    var img = '';
    var prev = wrap.querySelector('#fd-prev');
    function setImg(src) {
      img = src || '';
      prev.innerHTML = img
        ? '<img src="' + img + '" alt="人脸">'
        : '<span>还没有人脸照片<br>请上传图片或用摄像头拍照</span>';
    }
    wrap.addEventListener('click', function (e) { if (e.target === wrap) close(); });
    function close() { if (wrap.parentNode) wrap.parentNode.removeChild(wrap); }
    wrap.querySelector('#fd-file').addEventListener('change', function (e) {
      var f = e.target.files && e.target.files[0];
      if (!f) return;
      var rd = new FileReader();
      rd.onload = function () { setImg(String(rd.result)); };
      rd.readAsDataURL(f);
    });
    wrap.querySelector('#fd-shoot').addEventListener('click', function () {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        ZKB.toast && ZKB.toast('当前环境不支持调用摄像头，可改用「上传人脸图片」');
        return;
      }
      navigator.mediaDevices.getUserMedia({ video: true }).then(function (st) {
        var v = document.createElement('video');
        v.autoplay = true; v.muted = true; v.setAttribute('playsinline', '');
        v.srcObject = st;
        v.style.cssText = 'width:100%;height:100%;object-fit:cover;border-radius:6px';
        prev.innerHTML = ''; prev.appendChild(v);
        var shoot = wrap.querySelector('#fd-shoot');
        shoot.textContent = '✔ 拍下这张';
        shoot.onclick = function () {
          var cv = document.createElement('canvas');
          cv.width = 96; cv.height = 72;
          cv.getContext('2d').drawImage(v, 0, 0, 96, 72);
          var keep = cv.toDataURL('image/jpeg', 0.6);
          st.getTracks().forEach(function (t) { t.stop(); });
          setImg(keep);
          shoot.textContent = '📷 重拍';
          shoot.onclick = null;
          shoot.onclick = function () { close(); openFaceDialog(onSave); };
        };
      }).catch(function () {
        ZKB.toast && ZKB.toast('无法调用摄像头，可改用「上传人脸图片」');
      });
    });
    wrap.querySelector('#fd-clear').addEventListener('click', function () { setImg(''); });
    wrap.querySelector('#fd-cancel').addEventListener('click', close);
    wrap.querySelector('#fd-ok').addEventListener('click', function () {
      var nm = wrap.querySelector('#fd-name').value.trim();
      if (!nm) { ZKB.toast && ZKB.toast('请填写姓名'); return; }
      onSave(nm, wrap.querySelector('#fd-gender').value,
        wrap.querySelector('#fd-bio').value.trim(), img);
      close();
    });
  }

  /* ============================================================
   * 真实硬件调用（第十三轮）
   *   AI 摄像头 → 申请调用电脑摄像头，采集画面做主色识别
   *   板载麦克风 → 申请调用电脑麦克风，以真实音量作为读数
   *   调用失败 / 不支持时回退为虚拟模拟数据
   * ============================================================ */
  var CAM_COLOR_NAMES = [
    ['红色', 230, 50, 50], ['橙色', 240, 150, 40], ['黄色', 235, 215, 60],
    ['绿色', 60, 175, 80], ['青色', 60, 195, 195], ['蓝色', 60, 110, 225],
    ['紫色', 150, 80, 195], ['白色', 232, 232, 232], ['黑色', 38, 38, 42]
  ];
  function nearestColorName(r, g, b) {
    var best = '物体', bd = Infinity;
    CAM_COLOR_NAMES.forEach(function (c) {
      var d = (c[1] - r) * (c[1] - r) + (c[2] - g) * (c[2] - g) + (c[3] - b) * (c[3] - b);
      if (d < bd) { bd = d; best = c[0]; }
    });
    return best;
  }

  /* ---- AI 摄像头画面装载辅助 ----
     三种取景来源（电脑摄像头 / 上传图片 / 模拟）都归到setView，
     保证识别逻辑只读DV.realBrightness / DV.realHue，不必关心画面从哪来。*/

  /* 在取景框里放一个<img>（上传图片用） */
  function setViewImg(card, src, label) {
    var view = card.querySelector('#cam-view');
    if (!view) return;
    view.querySelectorAll('img,video').forEach(function (n) { n.parentNode.removeChild(n); });
    var fb = card.querySelector('#cam-fallback');
    if (fb) fb.style.display = 'none';
    var im = document.createElement('img');
    im.src = src;
    im.alt = label || '画面';
    view.appendChild(im);
  }

  /* 从一张已加载的图片抽取平均色/亮度，写入 DV 并回显主色 */
  function analyzeImg(DV, img) {
    try {
      var cv = document.createElement('canvas');
      cv.width = 32; cv.height = 18;
      var cx = cv.getContext('2d');
      cx.drawImage(img, 0, 0, 32, 18);
      var dd = cx.getImageData(0, 0, 32, 18).data;
      var r = 0, g = 0, b = 0, n = 0;
      for (var i = 0; i < dd.length; i += 4) { r += dd[i]; g += dd[i + 1]; b += dd[i + 2]; n++; }
      r = Math.round(r / n); g = Math.round(g / n); b = Math.round(b / n);
      DV.realHue = [r, g, b];
      DV.realBrightness = Math.round(0.299 * r + 0.587 * g + 0.114 * b);
      DV.real = true;
      DV.srcKind = 'upload';
      DV.target = 'color';
      DV.label = nearestColorName(r, g, b);
      return true;
    } catch (e) { return false; }
  }

  /* ---- AI 摄像头：调用电脑摄像头 ---- */
  function startRealCamera(id, card) {
    var DV = state.devices[id];
    if (!DV) return;
    if (DV._realStream) { stopRealCamera(id, card); return; }
    var stEl = card && card.querySelector('#cam-real-st');
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      if (stEl) stEl.textContent = '不支持调用摄像头，可改用「上传图片」模拟';
      ZKB.toast && ZKB.toast('当前环境不支持调用电脑摄像头，可用「上传图片」模拟');
      return;
    }
    navigator.mediaDevices.getUserMedia({ video: true }).then(function (stream) {
      DV._realStream = stream;
      var view = card.querySelector('#cam-view');
      var fb = card.querySelector('#cam-fallback');
      if (fb) fb.style.display = 'none';
      var v = document.createElement('video');
      v.autoplay = true; v.muted = true;
      v.setAttribute('playsinline', '');
      v.srcObject = stream;
      if (view) view.appendChild(v);
      DV._realVideo = v;
      DV.srcKind = 'cam';
      if (stEl) stEl.textContent = '📷 已调用电脑摄像头：识别画面主色与亮度';
      var btn = card.querySelector('#cam-real');
      if (btn) btn.textContent = '🔴 停用摄像头';
      /* 每 0.6s 抽帧计算平均色 → 识别为主色名称 */
      var cv = document.createElement('canvas');
      cv.width = 32; cv.height = 18;
      var cx2 = cv.getContext('2d');
      DV._realTimer = setInterval(function () {
        try {
          cx2.drawImage(v, 0, 0, 32, 18);
          var dd = cx2.getImageData(0, 0, 32, 18).data;
          var r = 0, g = 0, b = 0, n = 0;
          for (var i = 0; i < dd.length; i += 4) { r += dd[i]; g += dd[i + 1]; b += dd[i + 2]; n++; }
          r = Math.round(r / n); g = Math.round(g / n); b = Math.round(b / n);
          DV.target = 'color';
          DV.label = nearestColorName(r, g, b);
          /* 记录平均亮度，供 AI 视觉的文字识别 / 情绪识别使用 */
          DV.realBrightness = Math.round(0.299 * r + 0.587 * g + 0.114 * b);
          DV.real = true;
        } catch (e) { /* 忽略抽帧失败 */ }
      }, 600);
      ZKB.toast && ZKB.toast('已调用电脑摄像头，实时采集画面');
    }).catch(function () {
      if (stEl) stEl.textContent = '摄像头不可用，可用「上传图片」模拟';
      ZKB.toast && ZKB.toast('无法调用电脑摄像头（未授权或不存在），可用「上传图片」模拟');
    });
  }

  /* ---- AI 摄像头：上传图片模拟摄像头 ----
     上传后从图片里取平均色与平均亮度，等效于「摄像头拍到了一张这样的画面」，
     文字识别的置信度、人脸情绪、物体主色匹配都会跟着这张图走。*/
  function uploadCameraImage(id, card, file) {
    var DV = state.devices[id];
    if (!DV || !file) return;
    if (!/^image\//.test(file.type || '')) {
      ZKB.toast && ZKB.toast('请选择图片文件（jpg / png / bmp…）');
      return;
    }
    var rd = new FileReader();
    rd.onload = function () {
      var src = String(rd.result || '');
      if (!src) return;
      /* 先放图，再等解码完成抽帧（img.onload 才能拿到像素，file:// 下 canvas 才不脏）*/
      var im = new Image();
      im.onload = function () {
        setViewImg(card, src, '上传的画面');
        if (!analyzeImg(DV, im)) {
          ZKB.toast && ZKB.toast('这张图片无法读取像素，已按模拟识别处理');
        }
        var stEl = card.querySelector('#cam-real-st');
        var info = '🖼️ 已上传图片（' + (file.name || '未命名') + '）：' +
          (DV.label || '主色未知') +
          '，亮度 ' + (DV.realBrightness == null ? '—' : DV.realBrightness);
        if (stEl) stEl.textContent = info;
        ZKB.log && ZKB.log('AI 摄像头·上传图片模拟：' + info, 'log-sim');
        ZKB.toast && ZKB.toast('已用上传的图片模拟摄像头画面');
        /* 画面已就绪，顺手跑一次当前选中的识别，让卡片立刻有结果 */
        var shot = card.querySelector('#cam-shot');
        if (shot) shot.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      };
      im.onerror = function () { ZKB.toast && ZKB.toast('图片解码失败，请换一张试试'); };
      im.src = src;
    };
    rd.readAsDataURL(file);
  }

  /* 清除画面，回到纯模拟识别 */
  function clearCameraView(id, card) {
    var DV = state.devices[id];
    if (DV) {
      DV.real = false;
      DV.realHue = null;
      DV.realBrightness = null;
      DV.srcKind = 'sim';
      if (DV._vision) DV._vision = null;
    }
    if (card) {
      var view = card.querySelector('#cam-view');
      if (view) view.querySelectorAll('img,video').forEach(function (n) { n.parentNode.removeChild(n); });
      var fb = card.querySelector('#cam-fallback');
      if (fb) fb.style.display = '';
      var stEl = card.querySelector('#cam-real-st');
      if (stEl) stEl.textContent = '未调用摄像头时使用模拟识别；也可上传图片模拟';
    }
  }
  function stopRealCamera(id, card) {
    var DV = state.devices[id];
    if (!DV) return;
    if (DV._realTimer) { clearInterval(DV._realTimer); DV._realTimer = null; }
    if (DV._realStream) {
      DV._realStream.getTracks().forEach(function (t) { t.stop(); });
      DV._realStream = null;
    }
    if (DV._realVideo && DV._realVideo.parentNode) {
      DV._realVideo.parentNode.removeChild(DV._realVideo);
    }
    DV._realVideo = null;
    DV.real = false;
    /* 若当前画面来自上传图片，一并清掉，回到纯模拟 */
    if (DV.srcKind === 'upload') {
      DV.srcKind = 'sim';
      DV.realHue = null;
      DV.realBrightness = null;
    }
    if (card) {
      var fb = card.querySelector('#cam-fallback');
      if (fb) fb.style.display = '';
      var stEl = card.querySelector('#cam-real-st');
      if (stEl) stEl.textContent = '未调用摄像头时使用模拟识别；也可上传图片模拟';
      var btn = card.querySelector('#cam-real');
      if (btn) btn.textContent = '📷 调用电脑摄像头';
    }
  }

  /* ---- 板载麦克风：调用电脑麦克风（真实音量优先） ---- */
  var realMic = { on: false, stream: null, ctx: null, timer: null };
  function toggleRealMic() {
    var stEl = document.getElementById('sp-mic-real-st');
    var btn = document.getElementById('sp-mic-real');
    if (realMic.on) { stopRealMic(); return; }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      if (stEl) stEl.textContent = '当前：模拟数据（不支持调用麦克风）';
      ZKB.toast && ZKB.toast('当前环境不支持调用电脑麦克风，以虚拟仿真数据为准');
      return;
    }
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      var AC = window.AudioContext || window.webkitAudioContext;
      var ctx = new AC();
      var src = ctx.createMediaStreamSource(stream);
      var an = ctx.createAnalyser();
      an.fftSize = 512;
      src.connect(an);
      var buf = new Uint8Array(an.fftSize);
      realMic.on = true;
      realMic.stream = stream;
      realMic.ctx = ctx;
      state.micRealOn = true;
      state.randomMode.sound = false;   // 真实麦克风优先，关闭随机仿真
      realMic.timer = setInterval(function () {
        an.getByteTimeDomainData(buf);
        var sum = 0;
        for (var i = 0; i < buf.length; i++) {
          var d = (buf[i] - 128) / 128;
          sum += d * d;
        }
        var rms = Math.sqrt(sum / buf.length);            // 0..1
        var v = Math.round(Math.min(1, rms * 3.2) * 4095); // 映射到 0..4095
        state.sound = v;
        bus.emit('sensor_sound', v);
        var panel = document.getElementById('sensor-panel');
        if (panel && !panel.classList.contains('hidden')) syncPanelUI();
      }, 100);
      if (stEl) stEl.textContent = '当前：电脑麦克风（实际音量）';
      if (btn) btn.textContent = '🔴 停用电脑麦克风';
      ZKB.toast && ZKB.toast('已调用电脑麦克风，以实际音量为准');
    }).catch(function () {
      if (stEl) stEl.textContent = '当前：模拟数据（麦克风不可用）';
      ZKB.toast && ZKB.toast('无法调用电脑麦克风，以虚拟仿真中的模拟数据为准');
    });
  }
  function stopRealMic() {
    if (realMic.timer) { clearInterval(realMic.timer); realMic.timer = null; }
    if (realMic.stream) {
      realMic.stream.getTracks().forEach(function (t) { t.stop(); });
      realMic.stream = null;
    }
    if (realMic.ctx && realMic.ctx.close) { realMic.ctx.close(); }
    realMic.ctx = null;
    realMic.on = false;
    state.micRealOn = false;
    var stEl = document.getElementById('sp-mic-real-st');
    var btn = document.getElementById('sp-mic-real');
    if (stEl) stEl.textContent = '当前：模拟数据';
    if (btn) btn.textContent = '🎙️ 使用电脑麦克风';
  }

  /* ---- 拓展库「麦克风」设备：调用电脑麦克风收录声音（第十四轮） ----
     真实音量优先写入该设备的读数（zk_mic 积木读取），
     并同步卡片显示；不支持 / 未授权时回退为「制造声音」按钮 + 滑杆模拟。 */
  var extMic = { on: false, stream: null, ctx: null, timer: null, devId: null };
  function toggleExtMic(id, card) {
    var DV = state.devices[id];
    if (!DV) return;
    if (extMic.on) { stopExtMic(card); return; }
    var stEl = card && card.querySelector('#mic-real-st');
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      if (stEl) stEl.textContent = '不支持调用麦克风，使用「制造声音」模拟';
      ZKB.toast && ZKB.toast('当前环境不支持调用电脑麦克风，可使用「制造声音」按钮模拟声音大小');
      return;
    }
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      var AC = window.AudioContext || window.webkitAudioContext;
      var ctx = new AC();
      var src = ctx.createMediaStreamSource(stream);
      var an = ctx.createAnalyser();
      an.fftSize = 512;
      src.connect(an);
      var buf = new Uint8Array(an.fftSize);
      extMic.on = true;
      extMic.stream = stream;
      extMic.ctx = ctx;
      extMic.devId = id;
      extMic.timer = setInterval(function () {
        an.getByteTimeDomainData(buf);
        var sum = 0;
        for (var i = 0; i < buf.length; i++) {
          var d = (buf[i] - 128) / 128;
          sum += d * d;
        }
        var rms = Math.sqrt(sum / buf.length);             // 0..1
        var v = Math.round(Math.min(1, rms * 3.2) * 4095); // 映射到 0..4095
        DV.v = v;                                          // zk_mic 积木读取此值
        /* 同步卡片显示（虚拟仿真中正确显示实时音量） */
        var out = card && card.querySelector('#v-mic');
        if (out) out.textContent = v;
        var sl = card && card.querySelector('#sl-mic');
        if (sl) sl.value = v;
        bus.emit('sensor_mic', v);
      }, 100);
      if (stEl) stEl.textContent = '当前：电脑麦克风（实际音量）';
      var btn = card && card.querySelector('#mic-real');
      if (btn) btn.textContent = '🔴 停用电脑麦克风';
      ZKB.toast && ZKB.toast('已调用电脑麦克风，麦克风读数以实际音量为准');
    }).catch(function () {
      if (stEl) stEl.textContent = '麦克风不可用，使用「制造声音」模拟';
      ZKB.toast && ZKB.toast('无法调用电脑麦克风（未授权或不存在），可使用「制造声音」按钮模拟声音大小');
    });
  }
  function stopExtMic(card) {
    if (extMic.timer) { clearInterval(extMic.timer); extMic.timer = null; }
    if (extMic.stream) {
      extMic.stream.getTracks().forEach(function (t) { t.stop(); });
      extMic.stream = null;
    }
    if (extMic.ctx && extMic.ctx.close) { extMic.ctx.close(); }
    extMic.ctx = null;
    extMic.on = false;
    extMic.devId = null;
    if (card) {
      var stEl = card.querySelector('#mic-real-st');
      if (stEl) stEl.textContent = '未调用时使用「制造声音」按钮模拟';
      var btn = card.querySelector('#mic-real');
      if (btn) btn.textContent = '🎙️ 调用电脑麦克风';
    }
  }

  /* ============================================================
   * 初始化
   * ============================================================ */
  function init() {
    document.getElementById('sim-board-wrap').innerHTML = boardHTML();
    bindBoardEvents();
    bindSensorPanel();
    renderDeviceGrid();
    requestAnimationFrame(visualLoop);
  }

  /* ---------------- 板载麦克风 / 光线 调节浮层 ---------------- */
  /* ---- 第二十四轮：板载传感器面板里的「AI 语音」实操区 ----
     语音转文字：选指令（留空＝随机听一句）→ 开始聆听 → 回显文字与置信度
     文字转语音：输入文字 + 语速 → 朗读 / 停止 → 回显朗读状态
     这块 UI 与 ZKB.Speech 共用同一份状态，积木跑出来的结果也会显示在这里。*/
  function bindVoicePanel() {
    if (!ZKB.Speech) return;
    var SP = ZKB.Speech;
    /* 第二十五轮：语音 UI 有两处（传感器面板 #sp- 前缀、掌控板语音小窗 #vp- 前缀），
       这里按前缀同时绑定一套逻辑，两者共用 ZKB.Speech 的同一份状态。*/
    ['sp', 'vp'].forEach(function (p) {
      var cmdSel = document.getElementById(p + '-asr-cmd');
      var asrText = document.getElementById(p + '-asr-text');
      var asrConf = document.getElementById(p + '-asr-conf');
      var asrRun = document.getElementById(p + '-asr-run');
      var ttsText = document.getElementById(p + '-tts-text');
      var ttsRate = document.getElementById(p + '-tts-rate');
      var ttsPlay = document.getElementById(p + '-tts-play');
      var ttsStop = document.getElementById(p + '-tts-stop');
      var ttsSt = document.getElementById(p + '-tts-st');
      if (!cmdSel && !ttsPlay) return;   /* 该前缀不在当前页，跳过 */

      /* 下拉：随机 + 课堂常用指令（只填一次，避免重复 open 时叠加 option） */
      if (cmdSel && !cmdSel.options.length) {
        var html = '<option value="">（随机听一句）</option>';
        SP.ASR_COMMANDS.forEach(function (c) { html += '<option value="' + c + '">' + c + '</option>'; });
        cmdSel.innerHTML = html;
      }

      function paint() {
        if (asrText) asrText.textContent = SP.asrText() || '—';
        if (asrConf) asrConf.textContent = SP.asrConf() + '%';
        if (ttsSt) {
          ttsSt.textContent = SP.speaking() ? '朗读中…'
            : (SP.lastText() ? '已念完：' + SP.lastText() : '空闲');
        }
      }
      /* 记到元素上，避免同一个容器被重复绑定（重复 openSensorPanel 场景）*/
      var markKey = 'zkVoiceBound';
      if (cmdSel && cmdSel[markKey]) return;
      if (cmdSel) cmdSel[markKey] = true;
      else if (ttsPlay) ttsPlay[markKey] = true;

      if (asrRun) asrRun.addEventListener('click', function () {
        /* 用板载麦克风当前音量驱动置信度：声音小就识别不准 */
        SP.asrStart(cmdSel ? cmdSel.value : '', state.sound);
        paint();
        ZKB.toast && ZKB.toast('🎤 听到：' + SP.asrText() + '（' + SP.asrConf() + '%）');
      });
      if (ttsPlay) ttsPlay.addEventListener('click', function () {
        var txt = ttsText ? ttsText.value : '';
        if (!txt.trim()) { ZKB.toast && ZKB.toast('请先输入要朗读的文字'); return; }
        SP.speak(txt, Number(ttsRate ? ttsRate.value : 1), 1, 1);
        paint();
        /* 朗读结束后刷新一次状态（Web Speech 的 onend 会稍晚触发） */
        setTimeout(paint, 300);
        setTimeout(paint, 1200);
        SP.waitDone(12000).then(paint);
      });
      if (ttsStop) ttsStop.addEventListener('click', function () {
        SP.stop();
        paint();
      });

      /* 积木运行时通过 zk-speech 事件同步 UI */
      try {
        window.addEventListener('zk-speech', paint);
      } catch (e) { }
      paint();
    });
  }

  function openSensorPanel(focusKey) {
    var panel = document.getElementById('sensor-panel');
    if (!panel) return;
    panel.classList.remove('hidden');
    syncPanelUI();
    if (focusKey) {
      var sl = document.getElementById('sp-' + focusKey);
      if (sl) sl.focus();
    }
  }
  function syncPanelUI() {
    ['sound', 'light'].forEach(function (k) {
      var v = Math.round(state[k]);
      var sl = document.getElementById('sp-' + k);
      var num = document.getElementById('sp-' + k + '-num');
      var dice = document.querySelector('.sp-dice[data-k="' + k + '"]');
      if (sl) sl.value = v;
      if (num) num.value = v;
      if (dice) dice.classList.toggle('active', !!state.randomMode[k]);
    });
  }
  function setSensor(k, v) {
    state[k] = Math.max(0, Math.min(4095, Math.round(v)));
    state.randomMode[k] = false;   // 手动调节后关闭随机模式
    syncPanelUI();
    /* 派发传感器变化事件：运行中的程序可据此重绘（屏幕/灯光等） */
    bus.emit('sensor_' + k, state[k]);
  }
  function bindSensorPanel() {
    var panel = document.getElementById('sensor-panel');
    if (!panel) return;
    document.getElementById('sp-close').addEventListener('click', function () {
      panel.classList.add('hidden');
    });
    bindVoicePanel(panel);
    /* 真实麦克风：申请调用电脑麦克风，以实际音量为准；
       无法调用时保持虚拟模拟数据（滑杆 / 🎲 随机） */
    var rm = document.getElementById('sp-mic-real');
    if (rm) rm.addEventListener('click', toggleRealMic);
    ['sound', 'light'].forEach(function (k) {
      var sl = document.getElementById('sp-' + k);
      var num = document.getElementById('sp-' + k + '-num');
      var dice = document.querySelector('.sp-dice[data-k="' + k + '"]');
      sl.addEventListener('input', function () { setSensor(k, sl.value); });
      num.addEventListener('change', function () { setSensor(k, num.value); });
      dice.addEventListener('click', function () {
        state.randomMode[k] = !state.randomMode[k];
        ZKB.toast && ZKB.toast((k === 'sound' ? '麦克风' : '光线') +
          (state.randomMode[k] ? '随机仿真已开启 🎲' : '随机仿真已关闭'));
        syncPanelUI();
      });
    });
  }

  /* ============================================================
   * 板载交互（供 2D 卡片视图与 3D 模型共用）
   * ============================================================ */
  function pressBtn(k, down) {
    if (!(k in state.btn)) return;
    state.btn[k] = !!down;
    if (down) bus.emit('button' + k);
  }
  function pressTouch(p, down) {
    if (!(p in state.touch)) return;
    state.touch[p] = !!down;
    if (down) bus.emit('touch' + p);
  }
  /* 摇晃：mode 决定三轴加速度特征（由 board3d 的下拉框传入）
     updown 上下 → Y 轴大、Z 轴抬升
     leftright 左右 → X 轴大、Z 轴抬升
     fwbw 前后 → Z 轴瞬间反向（冲击）
     rotate 旋转 → X/Y 呈圆周（Z 轴旋转）
     random 随机 → 三轴随机

     第三十九轮：新增可选参数 p —— board3d 生成的视觉参数。
     传入时按 p 的方向与幅度换算加速度，保证「看到的动作」与
     「读到的加速度」严格一致（尤其随机模式：每次方向都不同）。 */
  var SHAKE_AXIS = {
    updown: function () {
      return {
        x: Math.round((Math.random() - .5) * 12) / 100,
        y: (Math.random() > .5 ? 1 : -1) * (1.6 + Math.random() * .8),
        z: 1.1
      };
    },
    leftright: function () {
      return {
        x: (Math.random() > .5 ? 1 : -1) * (1.6 + Math.random() * .8),
        y: Math.round((Math.random() - .5) * 12) / 100,
        z: 1.1
      };
    },
    fwbw: function () {
      /* 前后：Z 轴由 +1 猛冲 -1（相当于撞击） */
      return { x: 0, y: 0, z: -(1.8 + Math.random() * .6) };
    },
    rotate: function () {
      var a = Math.random() * Math.PI * 2;
      var r = 1.2 + Math.random() * 1.2;
      return {
        x: Math.round(Math.cos(a) * r * 100) / 100,
        y: Math.round(Math.sin(a) * r * 100) / 100,
        z: 1
      };
    },
    random: function () {
      return {
        x: Math.round((Math.random() - .5) * 3 * 100) / 100,
        y: Math.round((Math.random() - .5) * 3 * 100) / 100,
        z: Math.round((.2 + Math.random() * 1.8) * 100) / 100
      };
    }
  };

  /* 按视觉参数换算加速度（dx/dy/dz/rz → x/y/z） */
  function accelFromParams(p) {
    if (!p) return null;
    var mag = 1.6 + Math.random() * 0.8;
    /* dz 前后推拉 → Z 轴冲击；rz 旋转 → X/Y 圆周；dx/dy 平移 → 对应轴 */
    var ax = p.dx ? p.dx * mag : 0;
    var ay = p.dy ? p.dy * mag : 0;
    var az = p.dz ? p.dz * (1.8 + Math.random() * 0.6) : 1.1;
    if (p.rz) {
      var a = Math.random() * Math.PI * 2;
      var r = 1.2 + Math.random() * 1.2;
      ax = Math.round(Math.cos(a) * r * 100) / 100;
      ay = Math.round(Math.sin(a) * r * 100) / 100;
      az = 1;
    }
    return {
      x: Math.round(ax * 100) / 100,
      y: Math.round(ay * 100) / 100,
      z: Math.round(az * 100) / 100
    };
  }

  function doShake(mode, params) {
    var fn = SHAKE_AXIS[mode] || SHAKE_AXIS.updown;
    /* 第三十九轮：随机模式用 board3d 传来的视觉参数换算加速度，
       保证「看到的动作方向」与「读到的加速度」严格一致
       （随机模式每次方向都不同，数据必须跟着变）。
       其余固定模式沿用各自稳定的算法，读数更可预期。 */
    var acc = (mode === 'random' && params) ? accelFromParams(params) : null;
    state.accel = acc || fn();
    /* 视觉晃动反馈（2D 视图）—— 第三十九轮：同样按方向变量化 */
    var board = document.querySelector('#sim-board-wrap .zk-board');
    if (board) {
      board.classList.remove('shaking');
      void board.offsetWidth;
      board.classList.add('shaking');
      if (params) {
        board.style.setProperty('--shake-dx', (params.dx * 5) + 'px');
        board.style.setProperty('--shake-dy', (params.dy * 4) + 'px');
        board.style.setProperty('--shake-dz', String(params.dz || 0));
        board.style.setProperty('--shake-rz', (params.rz * 2) + 'deg');
      }
    }
    /* 立即派发"当摇晃掌控板时"事件 */
    bus.emit('shake');
    /* 0.6 秒后加速度回归静置状态 */
    setTimeout(function () { state.accel = { x: 0, y: 0, z: 1 }; }, 600);
  }

  function bindBoardEvents() {
    var wrap = document.getElementById('sim-board-wrap');
    if (!wrap) return;
    /* 按键 /触摸：按下触发事件
       注意（第二十五轮）：虚拟仿真主视图用的是3D 板（board3d.js 的 .b3-pressable），
       它的按键/触摸/传感器/语音点击都走 board3d 自己的委托。
       这里必须排除 .b3-pressable，否则同一次点击会被两个委托各处理一次
       （语音小圆点会出现「开关两次＝没反应」）。*/
    wrap.addEventListener('mousedown', function (e) {
      var el = e.target.closest ? e.target.closest('[data-act]') : null;
      if (!el || el.classList.contains('b3-pressable')) return;
      var act = el.getAttribute('data-act');
      if (act === 'btn') pressBtn(el.getAttribute('data-key'), true);
      else if (act === 'touch') pressTouch(el.getAttribute('data-key'), true);
      else if (act === 'sensor') openSensorPanel(el.getAttribute('data-k'));
      else if (act === 'voice') toggleVoicePanel();
    });
    /* 语音小窗口的关闭按钮（3D 板里的同一按钮在 board3d 中也有一份绑定，
       stopPropagation 已避免重复，这里只兜底非 3D 场景）*/
    wrap.addEventListener('click', function (e) {
      if (e.target && e.target.id === 'voice-close') closeVoicePanel();
    });
    document.addEventListener('mouseup', function () {
      state.btn.A = state.btn.B = false;
      ['P', 'Y', 'T', 'H', 'O', 'N'].forEach(function (p) { state.touch[p] = false; });
    });
    var btnShake = document.getElementById('btn-shake');
    /* 第三十九轮：2D 看板的「摇晃」按钮也走统一逻辑，
       用当前选中的摇晃方式生成参数（与 3D 板一致）。
       3D 板的 doShake() 内部会回调 SimBoard.shake()，
       所以这里只调它一次，避免重复触发「当摇晃掌控板时」事件。 */
    if (btnShake) btnShake.addEventListener('click', function () {
      var B3 = ZKB.Board3D;
      if (B3 && B3.doShake) { B3.doShake(); return; }
      doShake();
    });
  }

  /* ---------------- 设备添加/移除（第十四轮：每类设备仅可添加 1 个，名称不带序号） ---------------- */
  var MAX_INST = 1;
  /* 某基础 id 的全部实例 id 列表（按序号升序） */
  function instancesOf(base) {
    base = ZKB.baseOf(base);
    return state.added.filter(function (x) { return ZKB.baseOf(x) === base; })
      .sort(function (a, b2) { return ZKB.instNo(a) - ZKB.instNo(b2); });
  }
  function addDevice(id) {
    var base = ZKB.baseOf(id);
    var insts = instancesOf(base);
    if (insts.length) {
      if (!ZKB.multipliable(base)) { ZKB.toast && ZKB.toast('该设备已经添加'); return; }
      if (insts.length >= MAX_INST) {
        ZKB.toast && ZKB.toast('「' + ZKB.deviceMeta(base).name + '」最多添加 ' + MAX_INST + ' 个');
        return;
      }
    }
    /* 找 1~4 中未被占用的最小序号（移除中间实例后可补位） */
    var n = 1;
    while (n <= MAX_INST && state.added.indexOf(ZKB.instId(base, n)) >= 0) n++;
    var newId = ZKB.instId(base, n);
    state.added.push(newId);
    /* 实例 2~4 克隆独立状态（与 1 号互不影响） */
    if (newId !== base && state.devices[base] && !state.devices[newId]) {
      state.devices[newId] = JSON.parse(JSON.stringify(state.devices[base]));
    }
    renderDeviceGrid();
    ZKB.toast && ZKB.toast('已添加：' + ZKB.deviceName(newId));
    ZKB.onDevicesChanged && ZKB.onDevicesChanged(state.added.slice());
  }
  function removeDevice(id) {
    state.added = state.added.filter(function (x) { return x !== id; });
    /* 移除摄像头设备时停止真实画面采集 */
    if (ZKB.baseOf(id) === 'camera') stopRealCamera(id, null);
    /* 移除麦克风设备时停止真实声音采集 */
    if (ZKB.baseOf(id) === 'mic' && extMic.on) stopExtMic(null);
    /* 清理该实例的独立状态与连接关系 */
    if (id !== ZKB.baseOf(id)) delete state.devices[id];
    if (state.connected && state.connected[id]) delete state.connected[id];
    /* 第四十轮：同步断开「硬件连接」界面里该设备的连线。
       否则设备已经删了，界面上却还挂着线、接口还显示绿色「已占用」。 */
    if (ZKB.WireLib && ZKB.WireLib.removeDeviceConns) {
      var n = ZKB.WireLib.removeDeviceConns(id);
      if (n > 0) ZKB.toast('已断开 ' + n + ' 条连接，接口恢复初始状态');
    }
    renderDeviceGrid();
    ZKB.onDevicesChanged && ZKB.onDevicesChanged(state.added.slice());
  }
  function hasDevice(id) {
    if (state.added.indexOf(id) >= 0) return true;
    /* 基础 id 查询：任一实例存在即视为已添加 */
    return instancesOf(id).length > 0;
  }

    /* ---------------- 灯带卡片渲染（d 为该实例状态） ---------------- */
  function renderStripCard(card, d) {
    var wrap = card.querySelector('#card-strip');
    if (!wrap) return;
    d = d || state.devices.rgbStrip;
    var N = 16;
    if (!d.leds || d.leds.length !== N) {
      d.leds = [];
      for (var i = 0; i < N; i++) d.leds.push({ on: 0, r: d.r || 0, g: d.g || 0, b: d.b || 0 });
    }
    var on = 0;
    var html = '';
    for (var k = 0; k < N; k++) {
      var L = d.leds[k];
      var col = L.on ? 'rgb(' + L.r + ',' + L.g + ',' + L.b + ')' : '#2c3036';
      if (L.on) on++;
      html += '<i class="sl-led' + (L.on ? ' on' : '') + '" style="background:' + col + '"></i>';
    }
    wrap.innerHTML = html;
    var n = card.querySelector('#v-strip-n');
    if (n) n.textContent = on;
  }

  /* ---------------- 巡线小车卡片（第十四轮） ---------------- */
  function traceCarState() {
    if (!state.devices.traceCar) {
      state.devices.traceCar = { l: 0, r: 0, auto: true, line: '离线', dist: 200, target: '' };
    }
    return state.devices.traceCar;
  }
  function refreshTraceCard() {
    var d = traceCarState();
    var card = document.getElementById('card-traceCar');
    if (!card) return;
    var set = function (sel, txt) { var e = card.querySelector(sel); if (e) e.textContent = txt; };
    set('#v-tc-l', d.l || 0); set('#v-tc-r', d.r || 0);
    set('#v-tc-line', d.line || '离线');
    set('#v-tc-dist', d.dist == null ? '--' : d.dist);
    set('#tc-auto', '自动巡线：' + (d.auto ? '开' : '关'));
    card.classList.toggle('running', !!(d.l || d.r));
  }

  function renderDeviceGrid() {
    var host = document.getElementById('sim-devices');
    if (!state.added.length) {
      painters = {};
      host.innerHTML = '<div class="empty-hint">点击左下角「＋ 拓展」添加传感器、执行器等设备</div>';
      return;
    }
    /* 卡片整批重建 → 旧的绘制函数全部作废（DOM 已不存在） */
    painters = {};
    host.innerHTML = state.added.map(cardHTML).join('');
    state.added.forEach(bindCardEvents);
  }

  /* ---------------- 卡片内控件（实例感知：DV 为该实例的独立状态） ---------------- */
  function bindCardEvents(id) {
    var card = document.getElementById('card-' + id);
    if (!card) return;
    var base = ZKB.baseOf(id);
    /* 该实例的独立状态（实例 2~4 已在 addDevice 时克隆；兜底再克隆一次） */
    if (!state.devices[id] && state.devices[base]) {
      state.devices[id] = JSON.parse(JSON.stringify(state.devices[base]));
    }
    var DV = state.devices[id] || state.devices[base] || {};
    var del = card.querySelector('.card-del');
    if (del) del.addEventListener('click', function () { removeDevice(id); });

    /* ---- 红外遥控器：方向键 ---- */
    if (base === 'remote') {
      card.querySelectorAll('.dp').forEach(function (b) {
        b.addEventListener('click', function () {
          var dir = b.getAttribute('data-dir');
          var out = card.querySelector('#v-remote-dir');
          var CN = { up: '上', down: '下', left: '左', right: '右', ok: '确定' };
          if (out) out.textContent = CN[dir] || dir;
          /* 联动小车电机（与程序运行时的行为一致） */
          var car = state.devices.car;
          if (car) {
            if (dir === 'up') { car.l = 55; car.r = 55; }
            else if (dir === 'down') { car.l = -55; car.r = -55; }
            else if (dir === 'left') { car.l = -55; car.r = 55; }
            else if (dir === 'right') { car.l = 55; car.r = -55; }
          }
          DV.dir = dir;
          bus.emit('remote_' + dir);
          if (ZKB.log) ZKB.log('遥控器按下「' + (CN[dir] || dir) + '」', 'log-sim');
        });
      });
    }

    /* ---- RGB 灯带：预览与快捷按钮 ---- */
    if (base === 'rgbStrip') {
      renderStripCard(card, DV);
      card.querySelectorAll('[data-strip]').forEach(function (b) {
        b.addEventListener('click', function () {
          var act = b.getAttribute('data-strip');
          var d = DV;
          if (!d.leds) { d.leds = []; for (var i = 0; i < 16; i++) d.leds.push({ on: 0, r: 0, g: 0, b: 0 }); }
          var col = act === 'r' ? [255, 0, 0] : act === 'g' ? [0, 255, 0] :
            act === 'b' ? [0, 0, 255] : act === 'all' ? [255, 200, 60] : [0, 0, 0];
          d.leds.forEach(function (L) {
            if (act === 'off') { L.on = 0; L.r = L.g = L.b = 0; }
            else { L.on = 1; L.r = col[0]; L.g = col[1]; L.b = col[2]; }
          });
          d.r = col[0]; d.g = col[1]; d.b = col[2];
          renderStripCard(card, DV);
          bus.emit('strip');
        });
      });
    }

    var bindSl = function (slId, fn) {
      var sl = card.querySelector('#' + slId);
      if (sl) sl.addEventListener('input', function () { fn(parseFloat(sl.value)); });
    };
    if (base === 'dht') {
      bindSl('sl-dht-t', function (x) { DV.t = x; card.querySelector('#v-dht-t').textContent = x; });
      bindSl('sl-dht-h', function (x) { DV.h = x; card.querySelector('#v-dht-h').textContent = x; });
    }
    if (base === 'ultrasonic') {
      bindSl('sl-ultra', function (x) { DV.cm = x; card.querySelector('#v-ultra').textContent = x; });
    }
    if (base === 'servo') {
      card.querySelectorAll('[data-servo]').forEach(function (b) {
        b.addEventListener('click', function () {
          var a = parseInt(b.getAttribute('data-servo'), 10);
          DV.angle = a;
          var out = card.querySelector('#v-servo');
          if (out) out.textContent = a;
          var horn = card.querySelector('.servo-horn');
          if (horn) horn.style.transform = 'rotate(' + (a - 90) + 'deg)';
        });
      });
    }
    if (base === 'ir') {
      card.querySelector('#ir-toggle').addEventListener('click', function () {
        DV.obs = !DV.obs;
        card.querySelector('#v-ir').textContent = DV.obs ? '有障碍物' : '无障碍物';
        card.classList.toggle('running', DV.obs);
        if (DV.obs) bus.emit('ir');
      });
    }
    if (base === 'heater') {
      bindSl('sl-heater', function (x) {
        DV.power = x; DV.on = x > 0;
        card.querySelector('#v-heater').textContent = x;
      });
    }
    if (base === 'pump') {
      bindSl('sl-pump', function (x) {
        DV.power = x; DV.on = x > 0;
        card.querySelector('#v-pump').textContent = x > 0 ? '打开' : '关闭';
        card.querySelector('#v-pump-p').textContent = x;
      });
    }
    if (base === 'motor') {
      card.querySelectorAll('[data-motor]').forEach(function (b) {
        b.addEventListener('click', function () {
          var vv = parseInt(b.getAttribute('data-motor'), 10);
          DV.vel = vv;
          card.querySelector('#v-motor').textContent = vv;
          card.classList.toggle('running', vv !== 0);
          var blade = card.querySelector('.motor-spin');
          if (blade) {
            if (vv === 0) blade.classList.remove('spin');
            else {
              blade.classList.add('spin');
              blade.style.setProperty('--spin-dur', Math.max(0.08, 0.9 - Math.abs(vv) / 100 * 0.8) + 's');
              blade.style.animationDirection = vv > 0 ? 'normal' : 'reverse';
            }
          }
        });
      });
    }
    if (base === 'color') {
      card.querySelectorAll('[data-color]').forEach(function (b) {
        b.addEventListener('click', function () {
          var name = b.getAttribute('data-color'), pre = COLOR_PRESETS[name];
          Object.assign(DV, { name: name }, pre);
          card.querySelector('#v-color').textContent = pre.label;
          card.querySelectorAll('.chip-btn').forEach(function (c) { c.classList.remove('on'); });
          b.classList.add('on');
        });
      });
    }
    if (base === 'camera') {
      var lb = card.querySelector('#cam-label');
      if (lb) lb.textContent = DV.label || '人脸';
      var viewEl = card.querySelector('#cam-view');
      if (viewEl) viewEl.addEventListener('click', function (e) {
        /* 点击的是画面本身才切换目标；点到画面里的 img/video 不切换 */
        if (e.target.tagName === 'IMG' || e.target.tagName === 'VIDEO') return;
        var cur = DV.target;
        var idx = CAM_TARGETS.findIndex(function (p) { return p[0] === cur; });
        if (idx < 0) idx = 0;
        var next = CAM_TARGETS[(idx + 1) % CAM_TARGETS.length];
        DV.target = next[0];
        DV.label = next[1];
        var l2 = card.querySelector('#cam-label');
        if (l2) l2.textContent = next[1];
      });
      /* 调用电脑摄像头（真实画面采集，主色识别；失败回退模拟） */
      var realBtn = card.querySelector('#cam-real');
      if (realBtn) realBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        startRealCamera(id, card);
      });
      /* 上传图片模拟摄像头（无摄像头设备时的替代方案） */
      var upBtn = card.querySelector('#cam-upload');
      if (upBtn) upBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        var inp = document.createElement('input');
        inp.type = 'file';
        inp.accept = 'image/*';
        inp.style.display = 'none';
        document.body.appendChild(inp);
        inp.addEventListener('change', function () {
          var f = inp.files && inp.files[0];
          uploadCameraImage(id, card, f);
          inp.parentNode && inp.parentNode.removeChild(inp);
        });
        inp.click();
      });
      /* 清除画面、拍照、三大识别的绑定统一放在本段末尾（需要 paint* 函数已就绪） */

      /* ===== 第二十三轮：AI 摄像头三大识别面板 ===== */
      var V = ZKB.Vision;
      /* 该卡片对应的摄像头实例序号（camera → 1，camera2 → 2 …） */
      var instNo = Number(String(id).replace(/^camera/, '')) || 1;
      var paintOcr = function () {
        var el = card.querySelector('#v-vis-ocr');
        if (!el) return;
        var m = V._vis(instNo);
        el.textContent = !m.ocrMode ? '—'
          : (m.ocrMode === 'number'
            ? (m.ocrNumber == null ? '未识别到数字' : m.ocrNumber)
            : (m.ocrText || '未识别到文字'));
      };
      var paintObj = function () {
        var el = card.querySelector('#v-vis-obj');
        var cf = card.querySelector('#v-vis-conf');
        var m = V._vis(instNo);
        if (el) el.textContent = m.objCat
          ? (V.CAT_EMOJI[m.objCat] || '') + ' ' + (m.objLabel || '未识别') : '—';
        if (cf) cf.textContent = m.objCat ? Math.round(m.confidence || 0) : '—';
      };
      var paintFace = function () {
        var m = V._vis(instNo);
        var n = card.querySelector('#v-face-name');
        var g = card.querySelector('#v-face-gender');
        var b = card.querySelector('#v-face-bio');
        var e2 = card.querySelector('#v-face-emo');
        if (n) n.textContent = m.verifyName || '—';
        if (g) g.textContent = m.verifyGender || '—';
        if (b) b.textContent = m.verifyBio || '—';
        if (e2) e2.textContent = m.emotion ? (V.EMOTION_CN[m.emotion] || m.emotion) : '—';
      };
      var paintFaces = function () {
        var box = card.querySelector('#face-list');
        if (!box) return;
        var list = V.faceList();
        if (!list.length) { box.innerHTML = '<span class="face-empty">尚未录入人脸</span>'; return; }
        box.innerHTML = list.map(function (f) {
          return '<span class="face-chip" data-face-name="' + camEsc(f.name) + '">' +
            (f.img ? '<img src="' + f.img + '" alt="">' : '👤') +
            camEsc(f.name) + '<i class="face-del" data-face-del="' + camEsc(f.name) + '">×</i></span>';
        }).join('');
        box.querySelectorAll('.face-del').forEach(function (x) {
          x.addEventListener('click', function (e) {
            e.stopPropagation();
            V.removeFace(x.getAttribute('data-face-del'));
            paintFaces();
            ZKB.refreshFaceBlocks && ZKB.refreshFaceBlocks();
            paintFace();
          });
        });
      };
      /* 拍照：按当前活动面板执行对应识别。
         亮度优先取电脑摄像头的实时平均亮度（未调用时按中间亮度模拟）。 */
      var bri01 = function () {
        if (DV.real && DV.realBrightness != null) return DV.realBrightness / 255;
        return 0.55;
      };
      var activeMode = { kind: 'face', ocr: 'text', cat: 'car' };
      var setActive = function (kind, el, groupSel) {
        activeMode.kind = kind;
        card.querySelectorAll(groupSel).forEach(function (c) { c.classList.remove('on'); });
        if (el) el.classList.add('on');
      };
      var shot = function () {
        if (activeMode.kind === 'ocr') {
          V.ocrStart(instNo, activeMode.ocr);
          paintOcr();
        } else if (activeMode.kind === 'obj') {
          V.objStart(instNo, activeMode.cat);
          paintObj();
        } else {
          /* 人脸验证：优先用 face-chip 上选中的姓名，未选则取人脸库第一位 */
          var picked = card.querySelector('.face-chip.on');
          var nm = (picked && picked.getAttribute('data-face-name')) ||
            (V.faceList()[0] ? V.faceList()[0].name : '');
          V.verify(instNo, nm, bri01());
          paintFace();
        }
      };
      var shotBtn = card.querySelector('#cam-shot');
      if (shotBtn) shotBtn.addEventListener('click', function (e) { e.stopPropagation(); shot(); });

      card.querySelectorAll('[data-vmode]').forEach(function (b) {
        b.addEventListener('click', function (e) {
          e.stopPropagation();
          activeMode.ocr = b.getAttribute('data-vmode');
          setActive('ocr', b, '[data-vmode]');
        });
      });
      card.querySelectorAll('[data-vcat]').forEach(function (b) {
        b.addEventListener('click', function (e) {
          e.stopPropagation();
          activeMode.cat = b.getAttribute('data-vcat');
          setActive('obj', b, '[data-vcat]');
        });
      });
      /* 点击人脸 chip 选中要验证的人 */
      card.addEventListener('click', function (e) {
        var chip = e.target.closest && e.target.closest('.face-chip');
        if (!chip || e.target.classList.contains('face-del')) return;
        card.querySelectorAll('.face-chip').forEach(function (c) { c.classList.remove('on'); });
        chip.classList.add('on');
        activeMode.kind = 'face';
      });
      var vbtn = card.querySelector('#face-verify');
      if (vbtn) vbtn.addEventListener('click', function (e) {
        e.stopPropagation();
        setActive('face', vbtn, '#face-verify');
        shot();
      });
      var addBtn = card.querySelector('#face-add');
      if (addBtn) addBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        openFaceDialog(function (nm, gd, bio, img) {
          V.registerFace(nm, gd, bio, img);
          paintFaces();
          ZKB.refreshFaceBlocks && ZKB.refreshFaceBlocks();
          paintFace();
        });
      });
      /* 统一重绘入口：清除画面后要把三个结果位一起复位 */
      var paintAll = function () { paintFaces(); paintOcr(); paintObj(); paintFace(); };
      paintAll();
      /* 人脸库被外部改动（如别处调用 Vision.registerFace）时，
         卡片上的名单与结果位需要同步刷新 */
      ZKB.SimBoard._camPainters[id] = function () { paintFaces(); paintFace(); };
      /* 「清除画面」按钮定义在 paintAll 之前，需延后绑定 */
      var clrBtn2 = card.querySelector('#cam-clear');
      if (clrBtn2) clrBtn2.addEventListener('click', function (e) {
        e.stopPropagation();
        clearCameraView(id, card);
        paintAll();
      });
    }
    if (base === 'mic') {
      card.querySelector('#mic-burst').addEventListener('mousedown', function () { DV.burst = 1; });
      bindSl('sl-mic', function (x) { DV.v = x; card.querySelector('#v-mic').textContent = x; });
      /* 调用电脑麦克风收录声音（真实音量优先；失败回退模拟） */
      var micRealBtn = card.querySelector('#mic-real');
      if (micRealBtn) micRealBtn.addEventListener('click', function () { toggleExtMic(id, card); });
    }
    if (base === 'robot') {
      var rg = card.querySelector('#robot-go-stage');
      if (rg) rg.addEventListener('click', function () {
        if (ZKB.Stage && ZKB.Stage.robotCmd) {
          var rs = ZKB.Stage.robotState && ZKB.Stage.robotState();
          var ok = ZKB.Stage.robotCmd(rs && rs.running ? 'stop' : 'go');
          if (!ok) ZKB.toast && ZKB.toast('请先在舞台模式添加「机器人」元素（素材库 → 机器人）');
        }
      });
    }
    if (base === 'traceCar') {
      /* 电机按钮：手动驱动（自动巡线关闭） */
      card.querySelectorAll('[data-tc]').forEach(function (b) {
        b.addEventListener('click', function () {
          var dir = b.getAttribute('data-tc');
          var d = traceCarState();
          d.auto = false;
          if (dir === 'f') { d.l = 60; d.r = 60; }
          else if (dir === 'b') { d.l = -60; d.r = -60; }
          else if (dir === 'l') { d.l = -60; d.r = 60; }
          else if (dir === 'r') { d.l = 60; d.r = -60; }
          else { d.l = 0; d.r = 0; }
          refreshTraceCard();
        });
      });
      /* 自动巡线开关：沿舞台「赛道黑线」行驶 */
      var tcAuto = card.querySelector('#tc-auto');
      if (tcAuto) tcAuto.addEventListener('click', function () {
        var d = traceCarState();
        d.auto = !d.auto;
        d.l = d.r = 0;
        refreshTraceCard();
        ZKB.toast && ZKB.toast(d.auto ? '巡线小车：自动巡线开启' : '巡线小车：自动巡线关闭');
      });
      refreshTraceCard();
    }
    if (base === 'lightExt') {
      bindSl('sl-light-ext', function (x) { DV.v = x; card.querySelector('#v-light-ext').textContent = x; });
    }
    if (base === 'soil') {
      bindSl('sl-soil', function (x) { DV.v = x; card.querySelector('#v-soil').textContent = x; });
    }
    if (base === 'pm25') {
      bindSl('sl-pm25', function (x) { DV.v = x; card.querySelector('#v-pm25').textContent = x; });
    }
    if (base === 'baro') {
      bindSl('sl-baro', function (x) { DV.p = x; card.querySelector('#v-baro').textContent = x; });
    }
    if (base === 'button') {
      var btnPress = card.querySelector('#btn-press');
      if (btnPress) btnPress.addEventListener('click', function () {
        DV.on = !DV.on;
        card.querySelector('#v-btn').textContent = DV.on ? '按下' : '未按下';
        card.classList.toggle('running', DV.on);
      });
    }
    if (base === 'fan') {
      bindSl('sl-fan', function (x) {
        DV.power = x; DV.on = x > 0;
        card.querySelector('#v-fan').textContent = x;
        card.classList.toggle('running', x > 0);
        var blade = card.querySelector('.fan-spin');
        if (blade) {
          if (x > 0) { blade.classList.add('spin'); blade.style.setProperty('--spin-dur', Math.max(0.12, 1.2 - x / 100 * 1.05) + 's'); }
          else { blade.classList.remove('spin'); }
        }
      });
    }

    /* ============================================================
     * 第五十轮：新增可视化设备的交互 + 实时绘制函数
     *
     * 每个 paint() 只做「读 DV → 改 DOM」，既能被本地交互调用，
     * 也会被 visualLoop 里的 syncLiveCards() 周期性调用，
     * 于是「程序改了状态」和「学生在卡片上操作」两条路都会立刻反映到画面。
     * ============================================================ */
    if (base === 'ledModule') {
      var paintLed = function () {
        var b = Math.max(0, Math.min(100, Number(DV.bright) || 0));
        var k = b / 100;
        var lens = card.querySelector('#led-lens');
        var glow = card.querySelector('#led-glow');
        var hot = card.querySelector('#led-hot');
        var pct = card.querySelector('#led-pct');
        var vl = card.querySelector('#v-led');
        var von = card.querySelector('#v-led-on');
        var sl = card.querySelector('#sl-led');
        if (lens) {
          lens.setAttribute('fill', k > 0.01
            ? 'rgb(' + Math.round(140 + 115 * k) + ',' +
            Math.round(120 + 105 * k) + ',' + Math.round(70 + 60 * k) + ')'
            : '#3a3126');
        }
        if (glow) glow.setAttribute('opacity', (k * 0.55).toFixed(3));
        if (hot) hot.setAttribute('opacity', (k * 0.92).toFixed(3));
        if (pct) pct.textContent = Math.round(b) + '%';
        if (vl) vl.textContent = Math.round(b);
        if (von) von.textContent = b > 0 ? '点亮' : '熄灭';
        /* 滑杆不要抢用户正在拖的那个 */
        if (sl && document.activeElement !== sl) sl.value = Math.round(b);
        card.classList.toggle('running', b > 0);
      };
      painters[id] = paintLed;
      paintLed();
      var ledSl = card.querySelector('#sl-led');
      if (ledSl) ledSl.addEventListener('input', function () {
        DV.bright = parseFloat(ledSl.value) || 0;
        DV.on = DV.bright > 0;
        paintLed();
      });
      card.querySelectorAll('[data-led]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          DV.bright = parseFloat(btn.getAttribute('data-led')) || 0;
          DV.on = DV.bright > 0;
          paintLed();
        });
      });
    }

    if (base === 'relay') {
      var paintRelay = function () {
        var on = !!DV.on;
        var led = card.querySelector('#relay-led');
        var txt = card.querySelector('#relay-txt');
        var v = card.querySelector('#v-relay');
        if (led) led.classList.toggle('on', on);
        if (txt) txt.textContent = on ? '常开触点吸合（通电）' : '常开触点断开';
        if (v) v.textContent = on ? '吸合' : '断开';
        card.classList.toggle('running', on);
      };
      painters[id] = paintRelay;
      paintRelay();
      card.querySelectorAll('[data-relay]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          /* DV 就是 state.devices.relay 本体（实例 1 没有后缀），
             直接改就等于改了引擎读到的那份状态 */
          DV.on = btn.getAttribute('data-relay') === '1';
          paintRelay();
        });
      });
    }

    if (base === 'pir') {
      var paintPir = function () {
        var on = !!DV.on;
        var v = card.querySelector('#v-pir');
        var n = card.querySelector('#v-pir-n');
        var radar = card.querySelector('#pir-radar');
        var txt = card.querySelector('#pir-txt');
        if (v) v.textContent = on ? '检测到有人' : '无人';
        if (n) n.textContent = DV.count || 0;
        if (radar) radar.classList.toggle('on', on);
        if (txt) txt.textContent = on ? '检测到人体红外变化' : '感应范围内无人';
        card.classList.toggle('running', on);
      };
      painters[id] = paintPir;
      paintPir();
      var pirT = card.querySelector('#pir-toggle');
      if (pirT) pirT.addEventListener('click', function () {
        DV.on = !DV.on;
        if (DV.on) DV.count = (DV.count || 0) + 1;
        paintPir();
        if (DV.on) bus.emit('ir');
      });
      var pirR = card.querySelector('#pir-reset');
      if (pirR) pirR.addEventListener('click', function () {
        DV.count = 0;
        paintPir();
      });
    }

    if (base === 'mp3') {
      var paintMp3 = function () {
        var st = card.querySelector('#v-mp3-st');
        var nm = card.querySelector('#v-mp3-name');
        var vol = card.querySelector('#v-mp3-vol');
        var sl = card.querySelector('#sl-mp3');
        if (st) st.textContent = DV.playing ? '播放中' : '停止';
        if (nm) nm.textContent = DV.name || '—';
        if (vol) vol.textContent = DV.volume == null ? 15 : DV.volume;
        if (sl && document.activeElement !== sl) sl.value = DV.volume == null ? 15 : DV.volume;
        card.classList.toggle('running', !!DV.playing);
      };
      painters[id] = paintMp3;
      paintMp3();
      var mp3Sl = card.querySelector('#sl-mp3');
      if (mp3Sl) mp3Sl.addEventListener('input', function () {
        DV.volume = parseFloat(mp3Sl.value) || 0;
        paintMp3();
      });
      card.querySelectorAll('[data-mp3]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          if (btn.getAttribute('data-mp3') === 'play') {
            DV.playing = true; DV.name = DV.name || '001';
          } else { DV.playing = false; }
          paintMp3();
        });
      });
    }

    if (base === 'tracker') {
      var paintTrk = function () {
        var ch = DV.ch || {};
        var n = 0;
        card.querySelectorAll('[data-trk]').forEach(function (d) {
          var k2 = d.getAttribute('data-trk');
          var on = !!ch[k2];
          if (on) n++;
          d.classList.toggle('on', on);
        });
        var cnt = card.querySelector('#v-trk-n');
        if (cnt) cnt.textContent = n;
      };
      painters[id] = paintTrk;
      paintTrk();
      var trkC = card.querySelector('#trk-center');
      if (trkC) trkC.addEventListener('click', function () {
        DV.ch = { L2: 0, L1: 0, C: 1, R1: 0, R2: 0 };
        paintTrk();
      });
      card.querySelectorAll('[data-trk]').forEach(function (d) {
        d.addEventListener('click', function () {
          var k2 = d.getAttribute('data-trk');
          DV.ch = DV.ch || {};
          DV.ch[k2] = DV.ch[k2] ? 0 : 1;
          paintTrk();
        });
      });
    }

    if (base === 'powerMeter') {
      var paintPw = function () {
        var vv = DV.v == null ? 5 : DV.v;
        var aa = DV.a == null ? 0.12 : DV.a;
        var set = function (sid, txt) { var e = card.querySelector(sid); if (e) e.textContent = txt; };
        set('#v-pw-v', vv.toFixed(2));
        set('#v-pw-a', aa.toFixed(2));
        set('#v-pw-w', (vv * aa).toFixed(2));
        var sl = card.querySelector('#sl-pw');
        if (sl && document.activeElement !== sl) sl.value = Math.round(aa * 1000);
      };
      painters[id] = paintPw;
      paintPw();
      var pwSl = card.querySelector('#sl-pw');
      if (pwSl) pwSl.addEventListener('input', function () {
        DV.a = (parseFloat(pwSl.value) || 0) / 1000;
        DV.w = (DV.v || 5) * DV.a;
        paintPw();
      });
    }

    if (base === 'gravity') {
      var GR_COLORS = [
        ['红', 220, 60, 50], ['绿', 60, 190, 90], ['蓝', 60, 110, 230],
        ['黄', 230, 200, 60], ['白', 240, 240, 240],
      ];
      var paintGr = function () {
        var set = function (sid, txt) { var e = card.querySelector(sid); if (e) e.textContent = txt; };
        set('#v-gr-r', DV.r == null ? 0 : Math.round(DV.r));
        set('#v-gr-g', DV.g == null ? 0 : Math.round(DV.g));
        set('#v-gr-b', DV.b == null ? 0 : Math.round(DV.b));
        set('#v-gr-l', DV.l == null ? 0 : Math.round(DV.l));
      };
      painters[id] = paintGr;
      paintGr();
      var sw = card.querySelector('#gr-swatches');
      if (sw) {
        sw.innerHTML = GR_COLORS.map(function (c, i) {
          return '<span class="chip-btn" data-gr="' + i + '" style="border-left:4px solid rgb(' +
            c[1] + ',' + c[2] + ',' + c[3] + ')">' + c[0] + '</span>';
        }).join('');
        sw.querySelectorAll('[data-gr]').forEach(function (b) {
          b.addEventListener('click', function () {
            var c = GR_COLORS[parseInt(b.getAttribute('data-gr'), 10)] || GR_COLORS[0];
            DV.r = c[1]; DV.g = c[2]; DV.b = c[3];
            DV.l = Math.round(0.299 * c[1] + 0.587 * c[2] + 0.114 * c[3]) * 3;
            paintGr();
          });
        });
      }
    }

    if (base === 'angle') {
      var paintAng = function () {
        var deg = DV.deg == null ? 45 : DV.deg;
        var v = card.querySelector('#v-ang');
        var nd = card.querySelector('#ang-needle');
        var sl = card.querySelector('#sl-ang');
        if (v) v.textContent = Math.round(deg);
        if (nd) nd.style.transform = 'rotate(' + deg + 'deg)';
        if (sl && document.activeElement !== sl) sl.value = Math.round(deg);
      };
      painters[id] = paintAng;
      paintAng();
      var angSl = card.querySelector('#sl-ang');
      if (angSl) angSl.addEventListener('input', function () {
        DV.deg = parseFloat(angSl.value) || 0;
        paintAng();
      });
      card.querySelectorAll('[data-ang]').forEach(function (b) {
        b.addEventListener('click', function () {
          DV.deg = parseFloat(b.getAttribute('data-ang')) || 0;
          paintAng();
        });
      });
    }

    if (base === 'irTx') {
      var paintIrTx = function () {
        var e = card.querySelector('#v-irtx');
        if (e) e.textContent = DV.last ? '0x' + Number(DV.last).toString(16).toUpperCase() : '—';
      };
      painters[id] = paintIrTx;
      paintIrTx();
      card.querySelectorAll('[data-irtx]').forEach(function (b) {
        b.addEventListener('click', function () {
          DV.last = parseInt(b.getAttribute('data-irtx'), 16);
          paintIrTx();
        });
      });
    }

    if (base === 'irRx') {
      var paintIrRx = function () {
        var e = card.querySelector('#v-irrx');
        if (e) e.textContent = DV.code ? '0x' + Number(DV.code).toString(16).toUpperCase() : '—';
      };
      painters[id] = paintIrRx;
      paintIrRx();
      var inj = card.querySelector('#irrx-inject');
      if (inj) inj.addEventListener('click', function () {
        DV.code = 0x0C;
        paintIrRx();
        bus.emit('ir');
      });
    }

    /* 风扇 / 直流电机 / 舵机 / 加热 / 水泵：程序驱动时也要看得见变化 */
    if (base === 'fan') {
      var paintFan = function () {
        var p = Math.max(0, Math.min(100, Number(DV.power) || 0));
        var v = card.querySelector('#v-fan');
        if (v) v.textContent = Math.round(p);
        var blade = card.querySelector('.fan-spin');
        if (blade) {
          if (p > 0) {
            blade.classList.add('spin');
            blade.style.setProperty('--spin-dur', Math.max(0.12, 1.2 - p / 100 * 1.05) + 's');
          } else { blade.classList.remove('spin'); }
        }
        var sl = card.querySelector('#sl-fan');
        if (sl && document.activeElement !== sl) sl.value = Math.round(p);
        card.classList.toggle('running', p > 0);
      };
      painters[id] = paintFan;
    }

    if (base === 'motor') {
      var paintMotor = function () {
        var vv = Number(DV.vel) || 0;
        var v = card.querySelector('#v-motor');
        if (v) v.textContent = vv;
        var blade = card.querySelector('.motor-spin');
        if (blade) {
          if (vv === 0) blade.classList.remove('spin');
          else {
            blade.classList.add('spin');
            blade.style.setProperty('--spin-dur', Math.max(0.08, 0.9 - Math.abs(vv) / 100 * 0.8) + 's');
            blade.style.animationDirection = vv > 0 ? 'normal' : 'reverse';
          }
        }
        card.classList.toggle('running', vv !== 0);
      };
      painters[id] = paintMotor;
      paintMotor();
    }

    if (base === 'servo') {
      var paintServo = function () {
        var a = DV.angle == null ? 90 : DV.angle;
        var v = card.querySelector('#v-servo');
        if (v) v.textContent = Math.round(a);
        var horn = card.querySelector('.servo-horn');
        if (horn) horn.style.transform = 'rotate(' + (a - 90) + 'deg)';
      };
      paintServo();
      painters[id] = function () {
        var a = DV.angle == null ? 90 : DV.angle;
        var horn = card.querySelector('.servo-horn');
        if (horn) horn.style.transform = 'rotate(' + (a - 90) + 'deg)';
        paintServo();
      };
    }

    if (base === 'pump') {
      painters[id] = function () {
        var p = Math.max(0, Math.min(100, Number(DV.power) || 0));
        var v = card.querySelector('#v-pump');
        var vp = card.querySelector('#v-pump-p');
        var sl = card.querySelector('#sl-pump');
        if (v) v.textContent = p > 0 ? '打开' : '关闭';
        if (vp) vp.textContent = Math.round(p);
        if (sl && document.activeElement !== sl) sl.value = Math.round(p);
        card.classList.toggle('running', p > 0);
      };
    }

    if (base === 'heater') {
      painters[id] = function () {
        var p = Math.max(0, Math.min(100, Number(DV.power) || 0));
        var v = card.querySelector('#v-heater');
        var sl = card.querySelector('#sl-heater');
        if (v) v.textContent = Math.round(p);
        if (sl && document.activeElement !== sl) sl.value = Math.round(p);
        card.classList.toggle('running', p > 0);
      };
    }

    /* —— 小车：点击地图放置障碍物，右键移除 —— */
    if (base === 'car') {
      bindCarMap(card, DV);
    }

    /* —— 通讯网络卡片 —— */
    if (base === 'wifi') {
      card.querySelector('#wifi-toggle').addEventListener('click', function () {
        var n = state.net.wifi;
        n.connected = !n.connected;
        n.ssid = n.connected ? '教室WiFi' : '';
      });
    }
    if (base === 'radio') {
      card.querySelector('#radio-test').addEventListener('click', function () {
        var msg = card.querySelector('#radio-in').value || '你好';
        state.net.radio.lastMsg = msg;
        bus.emit('radio');
      });
    }
    if (base === 'ntp') {
      card.querySelector('#ntp-test').addEventListener('click', function () {
        state.net.ntp.synced = true;
      });
    }
    if (base === 'mqtt') {
      card.querySelector('#mqtt-inject').addEventListener('click', function () {
        var topic = card.querySelector('#mqtt-topic').value || '';
        var msg = card.querySelector('#mqtt-msg').value || '';
        state.net.mqtt.connected = true;
        if (ZKB.SimEngine.injectMqtt) ZKB.SimEngine.injectMqtt(topic, msg);
      });
    }
    if (base === 'asr') {
      card.querySelectorAll('[data-asr]').forEach(function (b) {
        b.addEventListener('click', function () {
          state.net.asr.text = b.getAttribute('data-asr');
          card.querySelector('#v-asr').textContent = state.net.asr.text;
        });
      });
    }
    if (base === 'weather') bindWeather(card);
    /* ---------- 第二十九轮：八年级新增硬件的交互 ---------- */
    if (base === 'magnetic') {
      var slMag = card.querySelector('#sl-mag');
      var vMag = card.querySelector('#v-mag');
      if (slMag) {
        slMag.addEventListener('input', function () {
          var deg = parseInt(slMag.value, 10);
          vMag.textContent = deg;
          simSet('magnetic.heading', deg);
        });
      }
      card.querySelectorAll('[data-magdir]').forEach(function (b) {
        b.addEventListener('click', function () {
          var deg = parseInt(b.getAttribute('data-magdir'), 10);
          if (slMag) slMag.value = deg;
          vMag.textContent = deg;
          simSet('magnetic.heading', deg);
        });
      });
      var magCal = card.querySelector('#mag-cal');
      if (magCal) magCal.addEventListener('click', function () {
        simSensorCalibrate('magnetic');
        if (slMag) { slMag.value = 0; }
        vMag.textContent = 0;
      });
      var magPeel = card.querySelector('#mag-peel');
      if (magPeel) magPeel.addEventListener('click', function () { simSensorPeel('magnetic'); });
    }
    if (base === 'gps') {
      var gpsSearch = card.querySelector('#gps-search');
      if (gpsSearch) gpsSearch.addEventListener('click', function () {
        /* 仿真里点一下就当作搜到 8 颗星 */
        simSet('gps.ready', 1);
        simSet('gps.num', 8);
        var n = card.querySelector('#v-gps-n');
        if (n) n.textContent = '8';
        var s = card.querySelector('#v-gps');
        if (s) { s.textContent = '已定位'; s.style.color = '#3ddc84'; }
        refreshGps(card);
      });
      var gpsLost = card.querySelector('#gps-lost');
      if (gpsLost) gpsEventLost(card);
      /* 第三十三轮：用电脑的真实定位 */
      var gpsReal = card.querySelector('#gps-real');
      if (gpsReal) gpsReal.addEventListener('click', function () {
        var info = card.querySelector('#gps-real-info');
        gpsReal.textContent = '正在获取…';
        gpsReal.style.opacity = '.6';
        gpsRealUseReal(card, info, function () {
          gpsReal.textContent = '📍 用电脑定位（真实数据）';
          gpsReal.style.opacity = '';
        });
      });
    }
    if (base === 'rfid') {
      card.querySelectorAll('[data-rfid]').forEach(function (b) {
        b.addEventListener('click', function () {
          var id = b.getAttribute('data-rfid');
          simRfidScan(id);
          var v = card.querySelector('#v-rfid');
          if (v) v.textContent = id;
        });
      });
    }
    if (base === 'speech2') {
      card.querySelectorAll('[data-asr2]').forEach(function (b) {
        b.addEventListener('click', function () {
          var t = b.getAttribute('data-asr2');
          simAsr2(t);
          var v = card.querySelector('#v-asr2');
          if (v) v.textContent = t;
        });
      });
    }
  }

  /* ---------- 仿真运行时桥接小工具 ----------
     这几个新设备的状态存在 sim-engine 的 S 对象里（S.sensor / S.rfid / S.asr2），
     但 sim-board拿不到 S 引用，所以走 ZKB.Sim 的事件总线通知引擎。 */
  function simSet(key, val) {
    ZKB.bus && ZKB.bus.emit('sim-set', { key: key, val: val });
  }
  function simSensorCalibrate(which) {
    ZKB.bus && ZKB.bus.emit('sim-sensor', { act: 'calibrate', which: which });
  }
  function simSensorPeel(which) {
    ZKB.bus && ZKB.bus.emit('sim-sensor', { act: 'peel', which: which });
  }
  function simRfidScan(id) {
    ZKB.bus && ZKB.bus.emit('sim-rfid', { id: id });
  }
  function simAsr2(text) {
    ZKB.bus && ZKB.bus.emit('sim-asr2', { text: text });
  }
  function gpsEventLost(card) {
    simSet('gps.ready', 0);
    simSet('gps.num', 0);
    simSet('gps.utc', '');
    /* 第三十三轮：「丢失信号」同时清掉真实定位缓存，
       否则点过「用电脑定位」后再点这个，真实数据还会继续被gpsParse 采用。 */
    ZKB.bus && ZKB.bus.emit('sim-gps-clear', null);
    var n = card.querySelector('#v-gps-n');
    if (n) n.textContent = '0';
    var s = card.querySelector('#v-gps');
    if (s) { s.textContent = '未定位'; s.style.color = ''; }
    var info = card.querySelector('#gps-real-info');
    if (info) { info.textContent = ''; info.style.color = ''; }
    refreshGps(card);
  }
  /* GPS 面板的经纬度 / UTC 文本（由引擎在每次 tick 后回填） */
  function refreshGps(card) {
    var d = ZKB.state && ZKB.state.gpsView;
    if (!d) return;
    var loc = card.querySelector('#v-gps-loc');
    if (loc) {
      loc.textContent = (d.ready ? '经度 ' + d.lon + '　纬度 ' + d.lat +
        '　海拔 ' + d.alt + ' ' + (d.altUnit || '') : '经度 —　纬度 —　海拔 —');
    }
    var tm = card.querySelector('#v-gps-time');
    if (tm) tm.textContent = 'UTC ' + (d.utc || '—');
    /* 第三十三轮：显示数据来源（真实定位 / 模拟）*/
    var s = card.querySelector('#v-gps');
    if (s && d.ready) {
      s.textContent = d.real ? '已定位（真实）' : '已定位（模拟）';
      s.style.color = d.real ? '#3ddc84' : '#ffb020';
    }
    var info = card.querySelector('#gps-real-info');
    if (info && d.real) {
      info.innerHTML = '✓ 正在使用电脑真实定位' +
        (d.acc ? '（精度 ±' + d.acc + ' m）' : '');
      info.style.color = '#3ddc84';
    }
  }

  /* ============================================================
   * 第三十三轮：调用电脑真实定位
   *
   * sim-board 拿不到 sim-engine 的 S 引用，走事件总线请引擎执行；
   * navigator.geolocation 只在安全上下文（https / localhost）可用，
   * file:// 直接打开会被浏览器拒绝 —— 这里提前判断并给出可操作的提示。
   * ============================================================ */
  function gpsRealUseReal(card, info, done) {
    if (!global.navigator || !navigator.geolocation) {
      if (info) {
        info.innerHTML = '✗ 当前浏览器不支持定位，请用 Chrome / Edge';
        info.style.color = '#f87171';
      }
      if (done) done();
      return;
    }
    if (location.protocol === 'file:') {
      if (info) {
        info.innerHTML = '✗ 定位需要安全上下文。请用<b>本地服务器</b>打开本页面' +
          '（如 <code>http://localhost</code>），直接双击 HTML 文件无法定位。';
        info.style.color = '#f87171';
      }
      if (done) done();
      return;
    }
    if (info) { info.textContent = '正在向浏览器申请定位权限…'; info.style.color = '#9aa3af'; }
    ZKB.bus && ZKB.bus.emit('sim-gps-real', {
      cb: function (ok, msg) {
        if (ok) {
          simSet('gps.ready', 1);   /* 让 gpsParse 能出数 */
          var n = card.querySelector('#v-gps-n');
          var d = ZKB.state && ZKB.state.gpsView;
          if (n && d) n.textContent = d.num;
          refreshGps(card);
          if (info) {
            info.innerHTML = '✓ ' + msg + (d && d.acc ? '，精度 ±' + d.acc + ' m' : '');
            info.style.color = '#3ddc84';
          }
        } else {
          if (info) {
            info.innerHTML = '✗ ' + msg + '。请点「模拟搜星」继续演示。';
            info.style.color = '#f87171';
          }
        }
        if (done) done();
      }
    });
    /* 引擎未启动时 bus 可能没监听，给个兜底提示 */
    setTimeout(function () {
      if (info && /正在向浏览器申请/.test(info.textContent)) {
        info.innerHTML = '✗ 仿真引擎未启动，请先点「运行」。';
        info.style.color = '#f87171';
        if (done) done();
      }
    }, 1200);
  }

  /* ============================================================
   * 天气卡片（第二十二轮）
   *   · 城市库：内置 6 城 + 手动添加任意城市（Open-Meteo 地理编码）
   *   · 六项数据：天气现象 / 最高温 / 最低温 / 湿度 / 风向 / 风力(级)
   *   · 查询结果写入 state.net.weatherResult，供天气积木与舞台共享
   * ============================================================ */
  function renderCityList(card) {
    var box = card.querySelector('#wx-cities');
    if (!box || !ZKB.Weather) return;
    var names = ZKB.Weather.cities();
    var user = ZKB.Weather.userCities().map(function (c) { return c.name; });
    var cur = state.net.weatherCity;
    box.innerHTML = names.map(function (n) {
      var mine = user.indexOf(n) >= 0;
      return '<span class="wx-city' + (n === cur ? ' on' : '') + (mine ? ' mine' : '') +
        '" data-city="' + n + '" title="' + (mine ? '手动添加的城市（可移除）' : '内置城市') + '">' +
        n + (mine ? '<i class="wx-x" data-rm="' + n + '" title="移除">×</i>' : '') + '</span>';
    }).join('');
  }
  /* 把六项数据写进卡片 + 全局（供积木 / 舞台使用） */
  function applyWeather(card, d) {
    if (!d) return;
    var map = {
      text: d.text,
      high: (d.high != null ? d.high : '—') + '℃',
      low: (d.low != null ? d.low : '—') + '℃',
      humidity: (d.humidity != null ? d.humidity : '—') + '%',
      wind: d.wind || '—',
      windLevel: (d.windLevel != null ? d.windLevel : '—') + ' 级'
    };
    Object.keys(map).forEach(function (k) {
      var el = card.querySelector('#wx-' + k);
      if (el) el.textContent = map[k];
    });
    var cityEl = card.querySelector('#v-weather-city');
    if (cityEl && d.city) cityEl.textContent = d.city;
    var srcEl = card.querySelector('#v-weather-src');
    if (srcEl) {
      srcEl.textContent = d.source === 'net' ? '联网数据' :
        (d.source === 'sim' ? '离线模拟' : '未查询');
      srcEl.className = 'wx-src ' + (d.source === 'net' ? 'net' : 'sim');
    }
    var out = card.querySelector('#v-weather-now');
    if (out) {
      /* 摘要：城市 + 天气现象 + 温度区间 + 数据来源 + 同步提示 */
      var srcTxt = d.source === 'net' ? '联网数据' : (d.source === 'sim' ? '离线模拟' : '未查询');
      var detail = d.source === 'net'
        ? (d.windKmh != null ? '　风速 ' + d.windKmh + 'km/h' : '')
        : (d.month ? '　按 ' + d.month + ' 月气候模拟' : '　无网络，按月份气候模拟');
      out.textContent = (d.city || '') + '　' + (d.text || '') + '　' +
        (d.low != null ? d.low : '—') + '~' + (d.high != null ? d.high : '—') + '℃　' +
        srcTxt + detail + '　已同步到积木「城市 □ 的天气 □」';
    }
    /* 同步全局：天气积木、舞台情境、监视器共用 */
    state.net.weatherCity = d.city || state.net.weatherCity;
    state.net.weatherResult = {
      city: d.city, text: d.text,
      high: String(d.high), low: String(d.low),
      humidity: String(d.humidity), wind: d.wind,
      windLevel: String(d.windLevel), windKmh: d.windKmh,
      source: d.source
    };
    renderCityList(card);
  }
  function queryCity(card, city) {
    state.net.weatherCity = city;
    renderCityList(card);
    var srcEl = card.querySelector('#v-weather-src');
    if (srcEl) { srcEl.textContent = '查询中…'; srcEl.className = 'wx-src'; }
    if (!ZKB.Weather) return;
    ZKB.Weather.query(city, true).then(function (d) { applyWeather(card, d); });
  }
  function bindWeather(card) {
    var msgEl = card.querySelector('#wx-msg');
    var say = function (t, bad) {
      if (!msgEl) return;
      msgEl.textContent = t;
      msgEl.className = 'wx-hint' + (bad ? ' bad' : '');
    };
    renderCityList(card);
    /* 城市库：点击查询（× 优先为移除） */
    card.querySelector('#wx-cities').addEventListener('click', function (e) {
      var rm = e.target.closest ? e.target.closest('[data-rm]') : null;
      if (rm) {
        e.stopPropagation();
        var rn = rm.getAttribute('data-rm');
        var r = ZKB.Weather.removeCity(rn);
        say(r.msg, !r.ok);
        renderCityList(card);
        return;
      }
      var btn = e.target.closest ? e.target.closest('[data-city]') : null;
      if (btn) queryCity(card, btn.getAttribute('data-city'));
    });
    /* 手动添加城市 */
    var input = card.querySelector('#wx-new');
    var doAdd = function () {
      var v = (input.value || '').trim();
      if (!v) { say('请先输入城市名', true); return; }
      say('正在查询「' + v + '」坐标…');
      ZKB.Weather.addCity(v).then(function (r) {
        say(r.msg, !r.ok);
        if (!r.ok) return;
        if (input) input.value = '';
        renderCityList(card);
        queryCity(card, r.city.name);
      });
    };
    var addBtn = card.querySelector('#wx-add-btn');
    if (addBtn) addBtn.addEventListener('click', doAdd);
    if (input) {
      input.addEventListener('keydown', function (e) { if (e.key === 'Enter') doAdd(); });
    }
    /* 刷新当前城市 */
    var rf = card.querySelector('#wx-refresh');
    if (rf) rf.addEventListener('click', function () {
      queryCity(card, state.net.weatherCity || '北京');
    });
    /* 若程序已跑过天气积木，把结果回填到卡片 */
    var wr = state.net.weatherResult;
    if (wr && wr.city) {
      applyWeather(card, Object.assign({}, wr, {
        high: parseFloat(wr.high), low: parseFloat(wr.low),
        humidity: parseFloat(wr.humidity), windLevel: parseFloat(wr.windLevel)
      }));
    } else {
      /* 首次打开卡片即自动查询当前城市，避免六项数据空着「—」 */
      queryCity(card, state.net.weatherCity || '北京');
    }
  }

  /* ============================================================
   * 视觉循环（板载传感自发变化 + 执行器动画 + 小车运动学）
   * ============================================================ */
  var lastT = 0, netUITick = 0, liveTick = 0;

  /* 第五十轮：调一遍所有已登记的卡片绘制函数 */
  function syncLiveCards() {
    var ids = Object.keys(painters);
    for (var i = 0; i < ids.length; i++) {
      try { painters[ids[i]](); } catch (e) { /* 单张卡片出错不影响其它 */ }
    }
  }
  function visualLoop(ts) {
    var dt = Math.min(0.05, (ts - lastT) / 1000 || 0);
    lastT = ts;
    // 板载声音冲击衰减
    if (state.soundBurst > 0) state.soundBurst = Math.max(0, state.soundBurst - dt * 2.2);
    var mic = state.devices.mic;
    if (mic.burst > 0) mic.burst = Math.max(0, mic.burst - dt * 2.2);

    /* 🎲 随机仿真模式：仅被点击 🎲 的传感器自动波动，其余保持静止 */
    var panel = document.getElementById('sensor-panel');
    var panelOpen = panel && !panel.classList.contains('hidden');
    if (state.randomMode.sound) {
      state.sound += (Math.random() - 0.5) * 1400 * dt * 3;
      state.sound = Math.max(0, Math.min(4095, state.sound));
    }
    if (state.randomMode.light) {
      state.light += (Math.random() - 0.5) * 1200 * dt * 3;
      state.light = Math.max(0, Math.min(4095, state.light));
    }
    // 面板打开时同步滑块数值（仅随机模式下需要刷新）
    if (panelOpen && (state.randomMode.sound || state.randomMode.light)) {
      syncPanelUI();
    }

    if (state.added.indexOf('car') >= 0) tickCar(dt);
    drawCar();

    /* 网络卡片状态刷新（约 5 次/秒） */
    netUITick += dt;
    if (netUITick > 0.2) {
      netUITick = 0;
      refreshNetUI();
      /* 巡线小车卡片：电机 / 循线 / 测距 状态 */
      if (state.added.indexOf('traceCar') >= 0) refreshTraceCard();
    }

    /* 第五十轮：执行器类卡片的实时绘制（约 7 次/秒）
       程序里改了 LED 亮度 / 继电器 / 风扇 / 舵机…，卡片画面立刻跟着变 */
    liveTick += dt;
    if (liveTick > 0.15) {
      liveTick = 0;
      syncLiveCards();
    }

    /* 拓展「麦克风」：模拟（制造声音/滑杆）或真实音量
       → 同步到卡片显示、板载麦克风读数（掌控板）与传感器面板 */
    if (state.added.indexOf('mic') >= 0) {
      var m2 = state.devices.mic;
      var shown = extMic.on
        ? Math.round(m2.v)
        : Math.max(0, Math.min(4095, Math.round(m2.v * 0.6 + m2.burst * 3300)));
      var mv = document.getElementById('v-mic');
      if (mv) mv.textContent = shown;
      if (!state.micRealOn && !state.randomMode.sound) {
        state.sound = shown;
        bus.emit('sensor_sound', shown);
        if (panelOpen) syncPanelUI();
      }
    }

    requestAnimationFrame(visualLoop);
  }

  function refreshNetUI() {
    var n = state.net;
    var set = function (id, txt) { var el = document.getElementById(id); if (el) el.textContent = txt; };
    set('v-wifi', n.wifi.connected ? '已连接 ' + n.wifi.ssid : '未连接');
    set('v-radio-g', n.radio.group);
    set('v-radio-msg', n.radio.lastMsg || '—');
    set('v-ntp', n.ntp.synced ? '已同步（东八区）' : '未同步');
    if (n.ntp.synced) {
      var d = new Date();
      var pad = function (x) { return (x < 10 ? '0' : '') + x; };
      set('v-ntp-time', d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
        ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds()));
    }
    set('v-mqtt', n.mqtt.connected ? '已连接 ' + n.mqtt.host : '未连接');
    /* 天气：程序运行「天气」积木后同步回填六项数据（含数据来源） */
    var wr = state.net.weatherResult;
    var wcard = document.getElementById('card-weather');
    if (wr && wcard) {
      applyWeather(wcard, {
        city: wr.city, text: wr.text,
        high: parseFloat(wr.high), low: parseFloat(wr.low),
        humidity: parseFloat(wr.humidity),
        wind: wr.wind, windLevel: parseFloat(wr.windLevel),
        windKmh: wr.windKmh, source: wr.source
      });
    }
  }

  /* ---------------- 小车障碍物互动 ---------------- */
  var OBS_R = 8;   // 障碍物碰撞/拾取半径（地图像素）

  function bindCarMap(card, carState) {
    var cv = card.querySelector('#car-map');
    var c = carState || state.devices.car;
    if (!cv) return;

    function pt(e) {
      var r = cv.getBoundingClientRect();
      return {
        x: (e.clientX - r.left) * (cv.width / r.width),
        y: (e.clientY - r.top) * (cv.height / r.height)
      };
    }
    function nearObs(p) {
      for (var i = 0; i < c.obstacles.length; i++) {
        var dx = c.obstacles[i].x - p.x, dy = c.obstacles[i].y - p.y;
        if (dx * dx + dy * dy < (OBS_R + 3) * (OBS_R + 3)) return i;
      }
      return -1;
    }
    cv.addEventListener('click', function (e) {
      var p = pt(e), idx = nearObs(p);
      if (idx >= 0) {
        c.obstacles.splice(idx, 1);               // 点中已有障碍物 → 移除
      } else {
        var dxc = p.x - c.x, dyc = p.y - c.y;
        if (dxc * dxc + dyc * dyc < 14 * 14) return;  // 离车太近不放置
        if (c.obstacles.length >= 14) c.obstacles.shift();
        c.obstacles.push({ x: Math.round(p.x), y: Math.round(p.y) });
      }
    });
    cv.addEventListener('contextmenu', function (e) {
      e.preventDefault();
      var idx = nearObs(pt(e));
      if (idx >= 0) c.obstacles.splice(idx, 1);
    });
    card.querySelector('#car-clear-obs').addEventListener('click', function () {
      c.obstacles.length = 0;
    });
    card.querySelector('#car-reset-pos').addEventListener('click', function () {
      c.x = 40; c.y = 50; c.deg = 90;
    });
  }

  /* 车头前方最近障碍物距离（像素），无遮挡返回 null */
  function frontObstaclePx(c) {
    var best = null;
    var rad = c.deg * Math.PI / 180;
    var fx = Math.cos(rad), fy = Math.sin(rad);
    c.obstacles.forEach(function (o) {
      var dx = o.x - c.x, dy = o.y - c.y;
      var along = dx * fx + dy * fy;
      if (along < 2) return;                       // 只看车头前方
      var perp = Math.abs(dx * (-fy) + dy * fx);  // 侧向偏移
      if (perp > 9) return;                        // 偏出车身宽度
      var d = along - OBS_R;
      if (d < 0) d = 0;
      if (best === null || d < best) best = d;
    });
    return best;
  }

  function tickCar(dt) {
    var c = state.devices.car;
    var speed = 26; // 像素/秒 @ 100
    var left = c.l / 100, right = c.r / 100;
    if (Math.abs(left - right) < 0.08) {
      var v = (left + right) / 2;
      var nx = c.x + Math.cos(c.deg * Math.PI / 180) * v * speed * dt;
      var ny = c.y + Math.sin(c.deg * Math.PI / 180) * v * speed * dt;
      /* 碰撞检测：下一个位置撞上障碍物则原地停止 */
      var blocked = false;
      for (var i = 0; i < c.obstacles.length; i++) {
        var dx = c.obstacles[i].x - nx, dy = c.obstacles[i].y - ny;
        if (dx * dx + dy * dy < (OBS_R + 5) * (OBS_R + 5)) { blocked = true; break; }
      }
      if (!blocked) { c.x = nx; c.y = ny; }
    } else {
      c.deg += (right - left) * 130 * dt;
    }
    c.deg = (c.deg + 360) % 360;
    if (c.x < 4) c.x = 4; if (c.x > 146) c.x = 146;
    if (c.y < 4) c.y = 4; if (c.y > 88) c.y = 88;

    /* 前方障碍距离同步到超声波读数（地图 1 像素 ≈ 1 cm）与卡片显示；
       仅在虚拟仿真视图激活时写入，避免与舞台模式的路障测距争抢 */
    var distEl = document.getElementById('v-car-dist');
    var fp = frontObstaclePx(c);
    var simView = document.getElementById('sim-view');
    var simActive = simView && simView.classList.contains('active');
    var stageView = document.getElementById('stage-view');
    var stageActive = stageView && stageView.classList.contains('active');
    /* 小车自带超声波读数（zk_car_dist 积木读取）：
       虚拟仿真用小地图障碍物；舞台模式由stage.js 按舞台元素测距（行人/路树…），
       此处仅在虚拟仿真视图下写值，避免覆盖舞台测出的距离。 */
    if (!stageActive) c._dist = fp === null ? 200 : Math.max(1, Math.round(fp));
    if (simActive && state.added.indexOf('ultrasonic') >= 0) {
      state.devices.ultrasonic.cm = fp === null ? 50 : Math.max(1, Math.round(fp));
      var ul = document.getElementById('v-ultra');
      if (ul) ul.textContent = state.devices.ultrasonic.cm;
      var sl = document.getElementById('sl-ultra');
      if (sl) sl.value = state.devices.ultrasonic.cm;
    }
    if (distEl && simActive) {
      distEl.textContent = c._dist == null ? '--'
        : (c._target ? (c._target + ' ' + c._dist) : c._dist);
    }
  }
  function drawCar() {
    var cv = document.getElementById('car-map');
    if (!cv) return;
    var ctx = cv.getContext('2d'), c = state.devices.car;
    ctx.clearRect(0, 0, 150, 92);
    ctx.fillStyle = '#e9f5ee';
    for (var gx = 15; gx < 150; gx += 15) { ctx.fillRect(gx, 0, 1, 92); }
    for (var gy = 15; gy < 92; gy += 15) { ctx.fillRect(0, gy, 150, 1); }
    /* 障碍物：红色警示方块 */
    c.obstacles.forEach(function (o) {
      ctx.fillStyle = 'rgba(211,59,59,.18)';
      ctx.beginPath(); ctx.arc(o.x, o.y, OBS_R + 3, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = '#d33b3b';
      roundRectPath(ctx, o.x - 6, o.y - 6, 12, 12, 3);
      ctx.fill();
      ctx.fillStyle = '#fff'; ctx.font = 'bold 10px Microsoft YaHei';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText('!', o.x, o.y + 0.5);
      ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
    });
    ctx.save(); ctx.translate(c.x, c.y); ctx.rotate(c.deg * Math.PI / 180);
    ctx.fillStyle = '#3d7ea6';
    ctx.beginPath(); ctx.moveTo(8, 0); ctx.lineTo(-6, -5); ctx.lineTo(-6, 5); ctx.closePath(); ctx.fill();
    ctx.restore();
  }
  function roundRectPath(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  /* ---------------- 对外接口 ---------------- */
  ZKB.bus = bus;
  ZKB.state = state;
  ZKB.ui = ui;
  ZKB.SimBoard = {
    init: init,
    /* AI 摄像头卡片的重绘回调表：{设备 id: fn}。
       人脸库变化时由 Vision.notifyFaceChange() 触发。*/
    _camPainters: {},
    /* 供 Vision 调用：人脸库变化后刷新所有摄像头卡片 */
    refreshFaceCards: function () {
      Object.keys(ZKB.SimBoard._camPainters).forEach(function (k) {
        try { ZKB.SimBoard._camPainters[k](); } catch (e) { }
      });
      ZKB.refreshFaceBlocks && ZKB.refreshFaceBlocks();
    },
    addDevice: addDevice,
    removeDevice: removeDevice,
    hasDevice: hasDevice,
    /* 多实例：某基础 id 的全部实例 id（按序号升序） */
    instancesOf: instancesOf,
    /* 显示名（直流电机1 / 直流电机2 …） */
    deviceName: function (id) { return ZKB.deviceName(id); },
    /* 板载交互（2D / 3D 共用） */
    pressBtn: pressBtn,
    pressTouch: pressTouch,
    shake: doShake,
    openSensorPanel: openSensorPanel,
    voicePanelHTML: voicePanelHTML,
    openVoicePanel: openVoicePanel,
    placeVoicePanel: placeVoicePanel,
    closeVoicePanel: closeVoicePanel,
    toggleVoicePanel: toggleVoicePanel,
    getDevices: function () { return state.added.slice(); },
    /* 连接关系：{devId: port}。未连接的硬件不参与仿真工作。 */
    connected: {},
    setConnected: function (map) {
      state.connected = map || {};
      /* 连接变化时刷新设备卡片（显示「未连接」提示） */
      renderDeviceGrid();
      /* 舞台联动元素随之增删（仅已连接的硬件会在舞台出现） */
      if (ZKB.Stage && ZKB.Stage.syncDevices) ZKB.Stage.syncDevices();
    },
    isConnected: function (id) {
      return !!(state.connected && state.connected[id]);
    },
    portOf: function (id) {
      return state.connected && state.connected[id] ? state.connected[id] : null;
    },
    setDevices: function (list) {
      state.added = [];
      (list || []).forEach(function (id) { if (ZKB.deviceMeta(id)) state.added.push(id); });
      renderDeviceGrid();
      /* 同步 3D 视图 */
      if (ZKB.Board3D) ZKB.Board3D.renderDevices();
      /* 第五十轮：同步舞台上的联动元素。
         原来只有「拓展库添加设备」（走 onDevicesChanged）才会同步，
         而「新建工程 / 打开工程 / 切换情景」都只调 setDevices ——
         于是新建工程后舞台上的旧设备元素会赖着不走。 */
      if (ZKB.Stage && ZKB.Stage.syncDevices) ZKB.Stage.syncDevices();
    },
    refreshRGB: function () {
      var bl = Math.max(0, Math.min(1, state.rgb.brightness));
      for (var i = 0; i < 3; i++) {
        var dot = document.getElementById('rgb-' + i);
        if (!dot) continue;
        var c = state.rgb.dots[i];
        /* 灯珠本体 = 颜色 × 亮度（默认亮度 80%） */
        var sum = (c[0] * bl | 0) + (c[1] * bl | 0) + (c[2] * bl | 0);
        if (sum > 12) {
          dot.setAttribute('fill', 'rgb(' + (c[0] * bl | 0) + ',' + (c[1] * bl | 0) + ',' + (c[2] * bl | 0) + ')');
          dot.setAttribute('stroke', 'rgba(255,255,255,.7)');
          dot.setAttribute('stroke-width', (1 + bl * 1.6).toFixed(1));
        } else {
          dot.setAttribute('fill', '#0d1013');
          dot.setAttribute('stroke', '#2c333a');
          dot.setAttribute('stroke-width', '1');
        }
      }
      if (ZKB.Board3D) ZKB.Board3D.syncRGB();
    },
    rerenderCards: function () {
      renderDeviceGrid();
      if (ZKB.Board3D) ZKB.Board3D.renderDevices();
    }
  };

})(window);
