/* ============================================================
 * project.js —— 工程存档（mxml / zkb 兼容）
 *
 * 第二十六轮：保存格式由 .zkb 改为 .mxml，兼容 mPython 官方格式。
 *
 * mxml 格式（对齐 mPython IDE）：本质就是标准 Blockly XML，
 * 文件首行多一行标记 `<!--mPythonType:0-->`，后跟 <xml> 根节点。
 * 设备清单等本项目私有信息放在 XML 注释里，不影响 mPython 打开。
 *
 * 同时兼容打开三种输入：
 *   1) .mxml / .xml —— mPython 官方图形化工程
 *   2) .zkb —— 本项目旧版 JSON 存档
 *   3) .py —— MicroPython 源码（转为积木，见 loadFromPython）
 * ============================================================ */
(function (global) {
  'use strict';
  var ZKB = global.ZKB || (global.ZKB = {});

  /* mPython 官方在 XML 前加的标记行；0 表示图形化工程 */
  var MPYTHON_MARK = '<!--mPythonType:0-->';

  /* 本项目私有信息塞进 XML 注释，mPython 会原样忽略 */
  var META_KEY = 'zkbmeta';

  /* ============================================================
   * mPython 风格 XML 缩进序列化
   *
   * 官方 IDE 导出的 mxml 是「每层 2 空格严格递进」的：
   *
   *   <!--mPythonType:0-->
   *   <xml xmlns="https://developers.google.com/blockly/xml">
   *     <block type="hunan_mpython3_button_event" id="…" x="-862" y="-587">
   *       <field name="button">a</field>
   *       <next>
   *         <block type="hunan_mpython_display_fill" id="…">
   *
   * 而 Blockly 自带的 Xml.domToText 输出的是**没有缩进的一整行**，
   * 人读不了、diff 也难看。这里自己序列化，严格对齐官方格式：
   *   · 每层 2 空格，空行不缩进
   *   · 空元素写成显式闭合 <tag></tag>（官方就是这样，不自闭合）
   *   · 属性顺序保持原样（type/id/x/y/mutator/inline…）
   * ============================================================ */

  var XMLNS = 'https://developers.google.com/blockly/xml';

  function escText(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function escAttr(s) {
    return escText(s).replace(/"/g, '&quot;');
  }

  /* 序列化 DOM 子节点，depth 为当前缩进层数 */
  function serNode(node, depth, out) {
    var pad = new Array(depth + 1).join('  ');   /* depth 层 = depth*2 空格 */
    var i, child;

    /* 文本节点：官方字段值直接写在一行里，不额外缩进 */
    if (node.nodeType === 3 || node.nodeType === 4) {
      var t = String(node.nodeValue || '');
      if (t.trim()) out.push(pad + escText(t));
      return;
    }
    if (node.nodeType !== 1) return;

    /* 开始标签：属性按原顺序输出 */
    var tag = node.nodeName;
    var attrs = '';
    for (i = 0; i < node.attributes.length; i++) {
      attrs += ' ' + node.attributes[i].name + '="' +
        escAttr(node.attributes[i].value) + '"';
    }
    /* <xml> 是根节点，必须带默认命名空间，否则 mPython 打不开 */
    if (tag === 'xml' && !/\bxmlns\b/.test(attrs)) {
      attrs += ' xmlns="' + XMLNS + '"';
    }

    var kids = [];
    for (i = 0; i < node.childNodes.length; i++) {
      child = node.childNodes[i];
      var isElem = child.nodeType === 1;
      var hasText = isElem ? false
        : (child.nodeType === 3 && String(child.nodeValue || '').trim() !== '');
      if (isElem || hasText) kids.push(child);
    }

    /* 字段这类「有值」的元素：<field name="x">值</field> 保持一行 */
    if (!kids.length) {
      out.push(pad + '<' + tag + attrs + '></' + tag + '>');
      return;
    }
    if (kids.length === 1 && kids[0].nodeType !== 1) {
      out.push(pad + '<' + tag + attrs + '>' +
        escText(kids[0].nodeValue) + '</' + tag + '>');
      return;
    }

    out.push(pad + '<' + tag + attrs + '>');
    for (i = 0; i < kids.length; i++) serNode(kids[i], depth + 1, out);
    out.push(pad + '</' + tag + '>');
  }

  /* 文本 → 严格缩进的 XML 文本 */
  function prettyXml(text) {
    var doc = parseXml(text);
    if (!doc) return String(text || '');
    var out = [];
    serNode(doc.documentElement, 0, out);
    return out.join('\n');
  }

  /* 解析 XML 文本为 DOM（浏览器 / jsdom 均有 DOMParser） */
  function parseXml(text) {
    if (typeof DOMParser === 'undefined') return null;
    try {
      return new DOMParser().parseFromString(String(text || ''), 'text/xml');
    } catch (e) {
      try {
        return new DOMParser().parseFromString(
          '<xml xmlns="' + XMLNS + '">' + String(text || '') + '</xml>', 'text/xml');
      } catch (e2) { return null; }
    }
  }

  /* ============================================================
   * 导出
   * ============================================================ */

  /* 从工作区生成 mxml 文本（严格缩进）
     extra.mode = 'mpython' 时额外把积木类型改写成 mPython 官方类型，
     使文件能直接在 mPython IDE 里打开（双向兼容的「出去」那一半）。 */
  function toMxml(ws, devices, extra) {
    var B = global.Blockly;
    if (!B || !B.Xml) {
      throw new Error('Blockly 未加载，无法生成 mxml');
    }
    var dom = B.Xml.workspaceToDom(ws);
    var meta = {
      app: 'zkb-graphical-ide',
      version: 2,
      devices: devices || [],
      savedAt: new Date().toISOString()
    };
    if (extra) {
      Object.keys(extra).forEach(function (k) { meta[k] = extra[k]; });
    }
    /* 私有元数据放在注释里，保证 <xml> 仍是唯一根节点 */
    var metaXml = rebuildMeta(meta);

    /* Blockly 给的是无缩进单行，这里换成 mPython 官方缩进格式。
       同时把 mutation 里的 else="true" 归一成 else="1"——
       Blockly 10.4.3 读回时只认 "1"，不归一的话「导出→再打开」
       这个闭环会把所有 else 分支悄悄丢掉。 */
    var xml = remapMutations(prettyXml(B.Xml.domToText(dom)));

    /* mPython 模式：把本项目积木类型改写成官方 hunan_* 类型 */
    if (extra && extra.mode === 'mpython') {
      xml = toMpythonTypes(xml);
      var st = toMpythonTypes.lastStats;
      /* 统计信息塞进元数据，方便打开文件时提示「有多少积木 mPython 不认识」 */
      meta.unmapped = st ? st.keptTypes : [];
      metaXml = rebuildMeta(meta);
    }

    /* 缩进后首尾各留一个换行，文件结构 = 标记行 / 元信息行 / XML */
    return MPYTHON_MARK + '\n' + metaXml + '\n' + xml + '\n';
  }

  /* 重新生成元信息注释（导出 mPython 模式时补写 unmapped 后要用） */
  function rebuildMeta(meta) {
    return '<!--' + META_KEY + '=' +
      encodeURIComponent(JSON.stringify(meta)) + '-->';
  }

  /* 提取 mxml 首行标记（兼容旧文件缺失的情况） */
  function mpythonType(text) {
    var m = /<!--\s*mPythonType\s*:\s*(\d+)\s*-->/i.exec(text || '');
    return m ? parseInt(m[1], 10) : null;
  }

  /* 读取本项目私有元数据（设备清单等） */
  function readMeta(text) {
    var m = new RegExp('<!--\\s*' + META_KEY + '\\s*=\\s*(.*?)\\s*-->').exec(text || '');
    if (!m) return null;
    try { return JSON.parse(decodeURIComponent(m[1])); }
    catch (e) { return null; }
  }

  /* 纯 Blockly XML（去掉 mPython 标记与本项目注释） */
  function pureXml(text) {
    return String(text || '')
      .replace(/<!--\s*mPythonType\s*:\s*\d+\s*-->/gi, '')
      .replace(/<!--\s*zkbmeta\s*=[\s\S]*?-->/gi, '')
      .trim();
  }

  /* ============================================================
   * 载入：三种输入统一成一个工程对象
   * ============================================================ */

  /* text + fileName → { xml, devices, extra, fmt, fileName }，失败返回 null */
  function parse(text, fileName) {
    var txt = String(text || '');
    var name = String(fileName || '');

    /* ① 旧版 .zkb（JSON）
       早期版本存 {xml, devices}，更早的存 {blocks:[…]} 或 {workspace:…}，
       这里一并接受，避免旧存档直接打不开。 */
    var json = null;
    try { json = JSON.parse(txt); } catch (e) { json = null; }
    if (json && typeof json === 'object' && !Array.isArray(json)) {
      var isZkb = typeof json.xml === 'string'
        || Array.isArray(json.blocks)
        || typeof json.workspace === 'string';
      if (isZkb) {
        return {
          xml: typeof json.xml === 'string' ? json.xml
            : (typeof json.workspace === 'string' ? json.workspace : ''),
          blocks: json.blocks || null,
          devices: json.devices || [],
          extra: json,
          fmt: 'zkb', fileName: name
        };
      }
    }

    /* ② mxml / xml（Blockly XML） */
    if (/<\s*xml[\s>]/i.test(txt) || /mPythonType/i.test(txt)) {
      var meta = readMeta(txt);
      return {
        xml: pureXml(txt),
        devices: (meta && meta.devices) || [],
        extra: meta || null,
        fmt: mpythonType(txt) === null ? 'xml' : 'mxml',
        fileName: name
      };
    }

    /* ③ MicroPython 源码 */
    if (/\.py$/i.test(name) || /^\s*(from|import)\s+/m.test(txt)) {
      return {
        py: txt, devices: [], extra: null, fmt: 'py', fileName: name
      };
    }

    return null;
  }

  /* 生成下载用的文件名：掌控图形化编程-YYYYMMDD-HHmm.mxml */
  function fileName(stamp) {
    var d = new Date();
    function p(n) { return n < 10 ? '0' + n : '' + n; }
    var s = stamp || (d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) +
      '-' + p(d.getHours()) + p(d.getMinutes()));
    return '掌控图形化编程-' + s + '.mxml';
  }

  /* 载入 MicroPython 源码 → 积木。
     走「积木 → 代码 → 反推」的成本太高，这里采用更实用的策略：
     把源码作为一个只读大文本积木放进工作区，用户可阅读与再生成。
     若项目已注册了 ZKB.Py2Blocks（可选的逆转换器），优先用它还原真积木。 */
  function loadFromPython(ws, py, devices) {
    /* ① 有逆转换器就用真积木 */
    if (ZKB.Py2Blocks && typeof ZKB.Py2Blocks.parse === 'function') {
      try {
        var r = ZKB.Py2Blocks.parse(ws, py);
        if (r && r.ok) return { mode: 'blocks', count: r.count || 0 };
      } catch (e) {
        ZKB.log && ZKB.log('Python 反解失败：' + e.message, 'log-err');
      }
    }
    /* ② 退路：整段源码塞进一个代码积木，保证不丢内容 */
    if (typeof ZKB.workspaceFromPython === 'function') {
      try {
        ZKB.workspaceFromPython(ws, py);
        return { mode: 'codeblock', count: 1 };
      } catch (e) { /* 继续走兜底 */ }
    }
    return { mode: 'none', count: 0, devices: devices || [] };
  }

  /* ============================================================
   * 导入映射：把 mPython 官方积木类型映射到本项目等价积木
   *
   * mxml 是官方格式，里面会出现 mpython_* 积木。为了让官方示例
   * 也能在本 IDE 里打开，这里做一层 best-effort 映射：
   * 完全等价的直接改名；无法对应的保留原类型（会显示为未知积木，
   * 但不会导致整个工程打开失败）。
   * ============================================================ */
  /* 官方示例的板载能力 → 本项目等价积木。
     统计自 参考资料/mPython图形化示例程序 的 31 个 .mxml，
     官方积木统一带 hunan_ 前缀（AI 摄像头那套是 mpython_AIcamera_，无前缀）。 */
  var HUNAN_ALIAS = {
    /* 事件帽子 */
    'hunan_mpython_main': 'zk_when_start',
    'hunan_mpython3_button_event': 'zk_when_btn',
    'hunan_mpython3_touchpad_event': 'zk_when_touch',
    /* 事件帽子 */
    'hunan_mpython_button_pressed': 'zk_is_btn',
    /* 控制 */
    'hunan_wait_seconds': 'zk_wait_sec',
    'hunan_loop': 'controls_forever',
    'hunan_for': 'controls_for',
    'hunan_repeat_until': 'controls_whileUntil',
    'hunan_if': 'controls_if',
    'hunan_logic_compare': 'logic_compare',
    'hunan_logic_operation': 'logic_operation',
    'hunan_text_join': 'text_join',
    'hunan_math_round': 'math_round',
    'hunan_mpython_high_low': 'math_number',
    'hunan_map': 'math_constrain',
    'hunan_mpython_time_ticks': 'zk_time_tick',
    /* 屏幕 */
    'hunan_mpython_display_fill': 'zk_oled_fill',
    'hunan_mpython_display_Clear': 'zk_oled_clear',
    'hunan_mpython_display_DispChar': 'zk_oled_text',
    /* ⚠ DispChar_5lines 与 DispChar 是**两种不同**的积木：
       前者带行号输入（官方 5 行分区显示），后者是普通 x/y 定位显示。
       这里必须指向 zk_oled_line5，若误写成 zk_oled_text，
       「导出成官方 → 再导回本项目」时行号输入会丢失、
       挂在 message 里的子积木也会因为输入名对不上而被丢弃。 */
    'hunan_mpython_display_DispChar_5lines': 'zk_oled_line5',
    'hunan_mpython_display_Show': 'zk_oled_show',
    'hunan_mpython_display_ShowString': 'zk_oled_text',
    'hunan_mpython_set_brightness': 'zk_oled_text_color',
    /* 板载 RGB */
    'hunan_mpython_set_rgb_list_color': 'zk_rgb_rgb',
    'hunan_mpython_off_rgb_list': 'zk_rgb_clear',
    'hunan_mpython_set_rgb_brightness': 'zk_rgb_brightness',
    'hunan_mpython_set_rgb_list_number': 'zk_rgb_one',
    'hunan_mpython_rgb_list': 'zk_rgb_one',       /* shadow：编号选择 */
    'hunan_brightness_value_shadow': 'math_number',
    'hunan_mpython_4_lines': 'math_number',       /* shadow：行号 */
    /* 板载传感器 */
    'hunan_mpython_read_light': 'zk_light',
    'hunan_mpython_read_sound': 'zk_sound',
    'hunan_mpython_accelerometer_get': 'zk_accel',
    'hunan_mpython_time_localtime': 'zk_time_now',
    /* ---------- 八年级新增硬件（与 EXPORT_MAP 严格互逆） ---------- */
    'hunan_mpython_magnetic_init': 'zk_magnetic_init',
    'hunan_mpython_magnetic_calibrate': 'zk_magnetic_calibrate',
    'hunan_mpython_magnetic_peeling': 'zk_magnetic_peeling',
    'hunan_mpython_magnetic_get_heading': 'zk_magnetic_heading',
    'hunan_mpython_bluebit_ATGM336H_init': 'zk_gps_init',
    'hunan_mpython_bluebit_ATGM336H_Parese': 'zk_gps_parse',
    'hunan_mpython_bluebit_ATGM336H_data': 'zk_gps_data',
    'hunan_mpython_qr_code': 'zk_qrcode',
    'hunan_mpython_bluebit_newrfid_scan': 'zk_rfid_scan',
    'hunan_mpython_bluebit_newrfid_getserial': 'zk_rfid_id',
    'hunan_mpython_bluebit_ledong_speech_recognition_init': 'zk_speech2_init',
    'hunan_mpython_bluebit_ledong_speech_recognition_result': 'zk_speech2_result',
    'hunan_string_to_number': 'zk_str2num',
    /* ---------- 八年级物联网 / 引脚 / 数学 / 音乐补充 ---------- */
    'hunan_mpython3_siot_receive_from': 'zk_when_mqtt',
    'hunan_mpython_siot_message': 'zk_mqtt_msg',
    'hunan_python_conn_read_analog': 'zk_pin_ain',
    'hunan_python_conn_read_digital': 'zk_pin_din',
    'hunan_python_conn_set_digital': 'zk_pin_dout',
    'hunan_mpython_conn_pin_get_analog': 'math_number',
    'hunan_mpython_conn_pin_get_digital': 'math_number',
    'hunan_mpython_music_tone_tempo': 'zk_music_tempo',
    'hunan_mpython_music_musical_note': 'math_number',
    'hunan_mpython_bluebit_ledong_speech_recognition_any': 'zk_speech2_result',
    'hunan_math_abs': 'math_single',     /* Blockly 内置：绝对值 */
    'hunan_math_reduce': 'math_arithmetic',
    'hunan_mpython_radio_rec': 'zk_radio_msg',
    'uart_tx_pin': 'math_number',
    /* 天气与输入类：官方用输入框 / 城市下拉，本项目用统一的天气积木，
       城市下拉作为影子丢弃即可 */
    'hunan_seniverse_weather_custom_init': 'zk_weather',
    'hunan_mpython_get_seniverse_weather_info2': 'zk_weather',
    'china_city': 'text',
    'hunan_input': 'zk_print',
    'hunan_input_res': 'text',
    /* 拓展设备 */
    /* 第四十五轮：官方 bluebit_ultrasonic 是**值积木**（放在 value 口里），
       对应本项目的 zk_ultra（超声波测距）；
       bluebit_ultrasonic_init 是语句型（初始化），对应 zk_ultra_init。 */
    'hunan_mpython_bluebit_ultrasonic': 'zk_ultra',
    'hunan_mpython_bluebit_ultrasonic_init': 'zk_ultra_init',
    'hunan_mpython_bluebit_get_color': 'zk_tracker_read',
    'hunan_mpython_dh11_hum_tem': 'zk_dht_measure',
    'hunan_microbit_music_play_built_in': 'zk_music_play',
    'hunan_microbit_music_stop': 'zk_music_stop',
    'hunan_mpython_music_pitch': 'zk_music_tempo',
    /* 灯带 / 拓展板 */
    /* 官方「扩展板电机 M1/M2 正转」是语句积木，
       对应本项目的 zk_parrot_speed（扩展板电机 速度） */
    'hunan_ledon_m1m2_Forward_mPython': 'zk_parrot_speed',
    'hunan_ledon_m1m2_off_mPython': 'zk_parrot_stop',
    'hunan_LeDong_servo': 'zk_servo',
    /* 无线 */
    'hunan_mpython_radio_send': 'zk_radio_send',
    /* 第四十五轮：官方「收到的广播内容」是**语句型**（带 next），
       本项目的 zk_radio_msg 是值积木（output: String），
       角色对不上会让整条程序链断掉。
       这里映射到专门为官方 mxml 准备的语句版积木。 */
    'hunan_mpython3_radio_recv_msg': 'zk_radio_msg_do',
    'hunan_mpython_radio_channel': 'zk_radio_group',
    'hunan_mpython_radio_on_off': 'zk_radio_send',
    'hunan_mpython_init_wifi': 'zk_wifi_connect',
    'hunan_mpython_wifi_isconnected': 'zk_wifi_ok',
    'hunan_mpython_siot_publish_to': 'zk_mqtt_pub',
    /* 同理：官方 MQTT 消息也是语句型 */
    'hunan_mpython3_siot_receive_msg': 'zk_mqtt_msg_do',
    'hunan_mpython_siot_init': 'zk_mqtt_connect',
    'hunan_mpython_ntp_server': 'zk_ntp_sync',
    'hunan_mpython3_ntptime_settime': 'zk_ntp_sync',
    /* 点阵图片 */
    'hunan_mpython_display_pbm_data': 'zk_oled_image',
    'hunan_mpython_get_pbm_data': 'zk_camera_result',
    'mpython_pbm_image': 'zk_camera_result',
    /* 以下几种官方积木只作为 <shadow> 下拉默认值出现（选引脚/选电平/
       类型转换），本项目对应的输入口本来就带自己的影子积木，
       映射成 math_number 即可正常丢弃，不影响主结构。 */
    'set_analog': 'math_number',
    'uart_rx_pin': 'math_number',
    'dh11_hum_tem_pin': 'math_number',
    /* 第四十五轮修正：官方 math_convert 是**类型转换**积木
       （<field name="TYPE0">int</field> + 一个值口 INPUT0），
       原来映射到 zk_print（语句积木）→ 官方把它放在 VALUE 口里时
       「语句积木接到值口」会让渲染崩掉
       （Cannot read properties of null (reading 'setAttribute')）。
       现在映射到本项目的类型转换**值**积木 zk_str2num，口名也对应上：
         INPUT0 → S（要转换的值）、TYPE0 → TYPE（转成整数还是小数）。 */
    'math_convert': 'zk_str2num',
    /* 数字引脚读写 */
    'hunan_python_conn_read_digital': 'zk_pin_din',
    'hunan_python_conn_set_digital': 'zk_pin_dout',
    'hunan_mpython_conn_pin_get_digital': 'zk_pin_din',
    'hunan_mpython_conn_pin_set_all': 'zk_pin_dout',
    'hunan_mpython_init': 'zk_print',
    /* 物联网 */
    'hunan_mpython3_init_wifi': 'zk_wifi_connect',
    'hunan_mpython_siot_connect': 'zk_mqtt_connect',
    'hunan_mpython_siot_isconnected': 'zk_wifi_ok',
    'hunan_mpython_siot_subscribe': 'zk_mqtt_msg_do',
    /* 等待直到（等价「重复执行直到」） */
    'hunan_dengdaizhidao': 'controls_if'
  };

  /* 合并后的完整映射表：hunan_* 与 mpython_* 共用一张。
     ⚠ 目标必须是在 blocks-defs.js 里真实注册过的积木名，
     否则导入后会变成「未知积木」方块，白映射一场。 */
  var TYPE_ALIAS = Object.assign({}, HUNAN_ALIAS, {
    /* 屏幕显示 */
    'mpython_display_fill': 'zk_oled_fill',
    'mpython_display_Show': 'zk_oled_show',
    'mpython_display_ShowString': 'zk_oled_text',
    'mpython_display_DispChar': 'zk_oled_text',
    'mpython_display_Clear': 'zk_oled_clear',
    'mpython_display_Color': 'zk_oled_text_color',
    'mpython_display_Contrast': 'zk_oled_invert',
    /* 板载 RGB */
    'mpython_rgb_Color': 'zk_rgb_one',
    'mpython_rgb_Brightness': 'zk_rgb_brightness',
    'mpython_rgb_Off': 'zk_rgb_clear',
    'mpython_rgb_ColorHSV': 'zk_rgb_one',
    'mpython_rgb_Range': 'zk_rgb_strip_all',
    /* 蜂鸣器 / 音乐 */
    'mpython_music_play': 'zk_music_play',
    'mpython_music_stop': 'zk_music_stop',
    /* 板载传感器 */
    'mpython_sensor_temperature': 'zk_dht_val',
    'mpython_sensor_light': 'zk_light',
    'mpython_sensor_sound': 'zk_sound',
    'mpython_adc_read': 'zk_pin_ain',
    'mpython_gpio_mode': 'zk_pin_dout',
    'mpython_gpio_write': 'zk_pin_dout',
    'mpython_gpio_read': 'zk_pin_din',
    /* 拓展板 parrot */
    'mpython_parrot_set_buzzer': 'zk_parrot_led',
    'mpython_parrot_set_led': 'zk_parrot_led',
    'mpython_parrot_set_servo': 'zk_servo',
    'mpython_parrot_set_motor': 'zk_parrot_speed',
    /* AI 摄像头（KPU）→ 本项目统一用「摄像头 + AI 识别」这套 */
    'mpython_AIcamera_uart_init': 'zk_robot_cam',
    'mpython_AIcamera_sensor_camera_snapshot': 'zk_camera_result',
    'mpython_AIcamera_kpu_load': 'zk_camera_seen',
    'mpython_AIcamera_kpu_initialize_yolo2': 'zk_camera_seen',
    'mpython_AIcamera_kpu_run_yolo2': 'zk_vision_obj_start'
  });

  /* ============================================================
   * 导入时按映射表把官方积木类型改成本项目类型
   *
   * 只改 <block type> / <shadow type>，不动 id / field / value，
   * 这样官方工程能最大程度在本 IDE 里打开。
   * 返回新文本（没得改时原样返回）。
   * ============================================================ */
  /* 建「官方类型 → 本项目类型」的逆向表。
     EXPORT_MAP 的方向是「本项目 → 官方」，这里反着来，
     key 是**官方类型**，value 里的 f/v/s 是「官方名 → 本项目名」。
     键要同时收两种类型：
       · 官方类型（本项目就是从官方文件来的）
       · 本项目类型（本项目文件刚被导出成官方类型，再导回来）

     ⚠ 必须延迟到首次调用时再建：EXPORT_MAP 声明在remapTypes
     之后，文件加载时就构建会拿到空表。 */
  var _revNames = null;
  function revNames() {
    if (_revNames) return _revNames;
    var m = {};
    function put(officialType, kind, map) {
      if (!map) return;
      var slot = m[officialType] || (m[officialType] = { f: {}, v: {}, s: {} });
      Object.keys(map).forEach(function (zkName) {
        if (map[zkName] === null) return;
        slot[kind][map[zkName]] = zkName;   /* 官方名 → 本项目名 */
      });
    }
    Object.keys(EXPORT_MAP).forEach(function (zkType) {
      var rule = EXPORT_MAP[zkType];
      if (!rule || rule.type === zkType) return;
      ['f', 'v', 's'].forEach(function (kind) {
        put(rule.type, kind, rule[kind]);
        /* 同一规则也按本项目类型登记一份（导出→导回的闭环） */
        put(zkType, kind, rule[kind]);
      });
    });
    _revNames = m;
    return m;
  }

  function remapTypes(xmlText) {
    var txt = remapMutations(String(xmlText || ''));
    var doc = parseXml(txt);
    /* 解析失败就退回纯文本替换，至少还能改类型 */
    if (!doc) {
      return txt.replace(
        /<(block|shadow)\s+type="([^"]+)"/g,
        function (all, tag, type) {
          var to = TYPE_ALIAS[type];
          return to ? '<' + tag + ' type="' + to + '"' : all;
        });
    }

    var els = doc.getElementsByTagName('*');
    var REV = revNames();
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      var tag = el.nodeName;
      if (tag !== 'block' && tag !== 'shadow') continue;
      var t = el.getAttribute('type');
      var to = TYPE_ALIAS[t];
      /* 先用「原始官方类型」查逆向表翻输入名，再改类型。
         顺序不能反：改了类型就找不到对应的名字表了。 */
      var r = REV[t] || REV[to];
      if (r) renameChildren(el, r);
      if (to) el.setAttribute('type', to);
      /* 第四十五轮：字段值规范化 + 输入口名对齐
         （必须在改完类型之后，因为要按本项目类型来对齐口名） */
      normalizeFieldValues(el, to || t);
      alignInputNames(el, to || t);
    }
    return serDoc(doc);
  }

  /* ============================================================
   * 第四十五轮：字段值规范化
   *
   * 【为什么要做】
   * 官方 mxml 里字段值的写法与本项目不完全一致：
   *   · 按键：官方写 BTN = "a" / "b"（小写），本项目用 "A" / "B"
   *   · 按键动作：官方写 ACTION = "pressed"，本项目用 "PRESSED"
   * 值对不上时 Blockly 的下拉框会匹配不到选项，
   * 字段值变空 → 报 "Cannot read properties of null (reading 'setAttribute')"。
   *
   * 这里把常见字段的值统一成本项目认的形式。
   * ============================================================ */
  var FIELD_VALUE_FIX = {
    /* 按键：A / B */
    BTN: { a: 'A', b: 'B', A: 'A', B: 'B' },
    /* 按键动作：按下 / 松开 */
    ACTION: { pressed: 'PRESSED', released: 'RELEASED', up: 'PRESSED', down: 'RELEASED' },
    /* 触摸引脚：官方小写，本项目大写 */
    PAD: {
      p: 'P', y: 'Y', t: 'T', h: 'H', o: 'O', n: 'N',
      P: 'P', Y: 'Y', T: 'T', H: 'H', O: 'O', N: 'N'
    }
  };

  function normalizeFieldValues(el, type) {
    /* 先收集本项目这个积木真正有的字段名 */
    var known = knownFields(type);
    /* 官方字段名 → 本项目字段名 */
    var nameFix = FIELD_NAME_FIX[type] || null;

    for (var j = el.childNodes.length - 1; j >= 0; j--) {
      var c = el.childNodes[j];
      if (c.nodeType !== 1 || c.nodeName !== 'field') continue;
      var nm = c.getAttribute('name');

      /* ① 按对照表改字段名 */
      if (nameFix && (nm in nameFix)) {
        var nf = nameFix[nm];
        if (nf !== nm) { c.setAttribute('name', nf); nm = nf; }
      }

      /* ② 本项目积木上没有的字段名直接删掉。
         官方 mxml 常带本项目没有的字段（如 zk_when_btn 的 ACTION），
         Blockly 反序列化遇到不存在的字段会抛
         "Cannot read properties of null (reading 'setAttribute')"，
         整份工程都打不开。 */
      if (known && known.indexOf(nm) < 0) {
        el.removeChild(c);
        continue;
      }

      /* ③ 字段值规范化（大小写等） */
      var fix = FIELD_VALUE_FIX[nm];
      if (!fix) continue;
      var val = c.textContent;
      if (val === null || val === undefined) continue;
      var trimmed = String(val).trim();
      var to = fix[trimmed];
      if (to && to !== val) c.textContent = to;
    }
  }

  /* ============================================================
   * 第四十五轮：输入口名（value / statement）对齐
   *
   * 【踩坑】Blockly 的 applyInputTagNodes 遇到「本积木上不存在的口名」时
   *   是 `console.warn(...); break;` —— 直接跳出循环，
   *   后面所有的 value 都不处理了。
   * 于是官方 mxml 里一个多余的口（如 zk_servo 的 pwm_pin、
   *   zk_print 的 INPUT0）就会让后面真正需要的口（A / V）整个丢掉，
   *   表现为 "Cannot read properties of null (reading 'setAttribute')"。
   *
   * 【怎么改】
   *   ① 先按已知对照表把官方口名换成本项目的口名；
   *   ② 再通用地检查：本积木上真的没有这个口 → 删掉，
   *      免得它把后面的口全带崩。
   * ============================================================ */

  /* 官方口名 → 本项目口名（按积木类型区分） */
  var INPUT_NAME_FIX = {
    /* 舵机：官方 servo_angle → 本项目 A */
    zk_servo: { servo_angle: 'A', A: 'A', pwm_pin: null },
    /* 打印 / 输入框：官方 INPUT0 → 本项目 V */
    zk_print: { INPUT0: 'V', text: 'V', V: 'V' },
    /* 类型转换：官方 INPUT0 → 本项目 S（要转换的值） */
    zk_str2num: { INPUT0: 'S', S: 'S', text: 'S' }
  };

  /* 官方字段名 → 本项目字段名（按积木类型区分） */
  var FIELD_NAME_FIX = {
    /* 类型转换：官方 TYPE0（转成什么类型）→ 本项目 TYPE */
    zk_str2num: { TYPE0: 'TYPE', TYPE: 'TYPE' }
  };

  /* 把某个积木上的 value / statement 口名对齐，并删掉对不上的 */
  function alignInputNames(el, type) {
    var fix = INPUT_NAME_FIX[type] || null;

    /* 本积木真实拥有的口名（value 口 + statement 口） */
    var known = knownInputs(type);

    for (var j = el.childNodes.length - 1; j >= 0; j--) {
      var c = el.childNodes[j];
      if (c.nodeType !== 1) continue;
      if (c.nodeName !== 'value' && c.nodeName !== 'statement') continue;
      var nm = c.getAttribute('name');

      /* ① 按对照表改名 */
      if (fix && (nm in fix)) {
        var to = fix[nm];
        if (to === null) { el.removeChild(c); continue; }
        if (to !== nm) { c.setAttribute('name', to); nm = to; }
      }

      /* ② 通用兜底：本积木上没有这个口 → 删掉
         （留着会让 Blockly break 掉后面所有的口） */
      if (known && known.indexOf(nm) < 0) {
        el.removeChild(c);
      }
    }
  }

  /* 取某个积木类型实际拥有的输入口名（value 口 + statement 口） */
  var _knownInputsCache = {};
  function knownInputs(type) {
    if (type in _knownInputsCache) return _knownInputsCache[type];
    var names = null;
    try {
      var B = global.Blockly;
      var blk = B && B.Blocks && B.Blocks[type];
      if (blk) {
        /* 用一次性的 Workspace 建一个块出来看它有哪些口
           （不碰主工作区，避免与正在导入的块冲突） */
        var ws = null;
        try { if (B.Workspace) ws = new B.Workspace(); } catch (e) { ws = null; }
        if (!ws && B.getMainWorkspace) ws = B.getMainWorkspace();
        if (ws) {
          var inst = ws.newBlock(type);
          names = [];
          var inputList = inst.inputList || [];
          for (var i = 0; i < inputList.length; i++) {
            if (inputList[i].name) names.push(inputList[i].name);
          }
          inst.dispose();
          if (ws !== B.getMainWorkspace && ws.dispose) ws.dispose();
        } else {
          names = null;
        }
      }
    } catch (e) { names = null; }
    _knownInputsCache[type] = names;
    return names;
  }

  /* 取某个积木类型实际拥有的字段名 */
  var _knownFieldsCache = {};
  function knownFields(type) {
    if (type in _knownFieldsCache) return _knownFieldsCache[type];
    var names = null;
    try {
      var B = global.Blockly;
      var blk = B && B.Blocks && B.Blocks[type];
      if (blk) {
        /* 字段多数是 init() 里 appendField 动态加的，
           所以要真的建一个块出来看它有哪些字段。
           用一次性的 HeadlessWorkspace 建（不碰主工作区，避免与
           正在导入的块冲突）。 */
        var ws = null;
        try {
          if (B.Workspace && B.WorkspaceSvg) ws = new B.Workspace();
        } catch (e) { ws = null; }
        if (!ws && B.getMainWorkspace) ws = B.getMainWorkspace();
        if (ws) {
          var inst = ws.newBlock(type);
          names = [];
          var inputList = inst.inputList || [];
          for (var i = 0; i < inputList.length; i++) {
            var row = inputList[i].fieldRow || [];
            for (var j = 0; j < row.length; j++) {
              if (row[j].name) names.push(row[j].name);
            }
          }
          inst.dispose();
          if (ws !== B.getMainWorkspace && ws.dispose) ws.dispose();
        } else {
          names = null;
        }
      }
    } catch (e) { names = null; }
    _knownFieldsCache[type] = names;
    return names;
  }

  /* 把某个 block 元素直属的 field / value / statement 名按逆向表改名 */
  function renameChildren(el, rule) {
    for (var j = 0; j < el.childNodes.length; j++) {
      var c = el.childNodes[j];
      if (c.nodeType !== 1) continue;
      var kind = c.nodeName === 'field' ? 'f'
        : c.nodeName === 'value' ? 'v'
          : c.nodeName === 'statement' ? 's' : '';
      if (!kind) continue;
      var nm = c.getAttribute('name');
      var to = rule[kind] && rule[kind][nm];
      if (to) c.setAttribute('name', to);
    }
  }

  /* ------------------------------------------------------------
   * mutation 归一化：else="true" → else="1"
   *
   * 【踩过的坑】Blockly 10.4.3 的 controls_if.domToMutation 只认
   * 「属性值等于 "1"」才算有 else 分支，写 "true" 一律当没有。
   * 而 Blockly 自己导出的 XML 里偏偏是 else="true"，
   * 于是「导出 → 再打开」这个闭环会把所有 else 分支悄悄丢掉。
   *
   * mPython 官方示例统一写 else="1"（见 护眼灯自动调节亮度.mxml），
   * 所以这里把 true 归一成 1，两种来源都能正确载入。
   * 同时把 if/else if 的 elseif 计数一并归一。
   * ------------------------------------------------------------ */
  function remapMutations(xmlText) {
    return String(xmlText || '').replace(
      /<mutation\b([^>]*)>/g,
      function (all, attrs) {
        var fixed = attrs.replace(
          /\belse="(?:true|yes|True)"/, 'else="1"');
        return '<mutation' + fixed + '>';
      });
  }

  /* ============================================================
   * 导出映射（反向）：把本项目积木改写成 mPython 官方积木
   *
   * 目的：导出的 .mxml 能**直接在 mPython IDE 里打开**，
   * 与 remapTypes（导入方向）构成双向兼容。
   *
   * 每条规则的形状：
   *   '本项目类型': {
   *     type: '官方类型',
   *     f: { 本项目字段名: 官方字段名 },   // field
   *     v: { 本项目输入名: 官方输入名 },   // value
   *     s: { 本项目语句名: 官方语句名 },   // statement
   *     drop: ['本项目字段名', …]           // 官方没有、导出时丢弃
   *   }
   *
   * 只写「语义确实等价」的积木。语义不一致的（比如本项目的
   * zk_mqtt_* 对应官方的 SIoT，协议不同）宁可保留本项目类型，
   * 也不导出一个在 mPython 里能打开但跑不对的积木。
   * ============================================================ */
  var EXPORT_MAP = {
    /* ---------- 事件帽子 ---------- */
    'zk_when_start': { type: 'hunan_mpython_main' },
    'zk_when_btn': { type: 'hunan_mpython3_button_event', f: { BTN: 'button' }, drop: [] },
    'zk_when_touch': { type: 'hunan_mpython3_touchpad_event', f: { PAD: 'BUTTON' } },

    /* ---------- 控制 ---------- */
    'zk_wait_sec': { type: 'hunan_wait_seconds', v: { SEC: 'TIME' } },
    'zk_wait_ms': { type: 'zk_wait_ms' },   /* 官方无毫秒等待，保留本项目类型 */

    /* ---------- 屏幕 ---------- */
    'zk_oled_fill': { type: 'hunan_mpython_display_fill', f: { V: 'color' } },
    'zk_oled_text': { type: 'hunan_mpython_display_DispChar', v: { T: 'message', X: 'x', Y: 'y' } },
    'zk_oled_clear': { type: 'hunan_mpython_display_Clear' },

    /* ---------- RGB 彩灯 ---------- */
    'zk_rgb_one': { type: 'hunan_mpython_set_rgb_list_number', v: { N: 'num' } },
    'zk_rgb_rgb': { type: 'hunan_mpython_set_rgb_list_number', v: { N: 'num' } },
    'zk_rgb_clear': { type: 'hunan_mpython_off_rgb_list' },
    'zk_rgb_brightness': {
      type: 'hunan_mpython_set_rgb_brightness', v: { V: 'BRIGHTNESS' }
    },

    /* ---------- 按键 / 触摸 ---------- */
    'zk_is_btn': { type: 'hunan_mpython_button_pressed', f: { BTN: 'button' } },
    'zk_is_touch': { type: 'zk_is_touch' },

    /* ---------- 板载传感器 ---------- */
    'zk_light': { type: 'hunan_mpython_read_light' },
    'zk_sound': { type: 'hunan_mpython_read_sound' },
    'zk_accel': { type: 'hunan_mpython_accelerometer_get' },
    'zk_time_now': { type: 'hunan_mpython_time_localtime' },
    'zk_time_tick': { type: 'hunan_mpython_time_ticks' },

    /* ---------- 拓展设备 ---------- */
    'zk_ultra': { type: 'hunan_mpython_bluebit_ultrasonic' },
    'zk_dht_measure': { type: 'hunan_mpython_dh11_hum_tem' },
    'zk_dht_val': { type: 'hunan_mpython_dh11_hum_tem', f: { K: 'hum_tem' } },
    /* ---- 打印 / 屏幕刷新 / 布尔 ----
       第三十三轮：把这两个原来「保留本项目类型」的积木也映射到官方类型，
       让保存出的 mxml 在 mPython IDE 里不出现未知块。
       · zk_print → hunan_input（官方「输入框」积木，输入口名同样是 text，
         在 mPython 里会弹出输入框；本项目的「打印」在真机上也常配合 input 用）
       · zk_oled_show → hunan_mpython_display_DispChar
         官方没有独立的「刷新屏幕」积木 —— DispChar 的 Python 生成器
         会自动带上 oled.show()，语义等价。
       · zk_gps_ready 官方确无对应物（判断是否已定位），只能保留。 */
    'zk_print': { type: 'hunan_input', v: { V: 'text' } },
    'zk_gps_ready': { type: 'zk_gps_ready' },
    'zk_oled_show': { type: 'hunan_mpython_display_DispChar' },
    'zk_servo': { type: 'hunan_LeDong_servo', v: { A: 'servo_angle' } },
    'zk_music_stop': { type: 'hunan_microbit_music_stop' },

    /* ---------- 无线 ---------- */
    'zk_radio_group': { type: 'hunan_mpython_radio_channel', v: { G: 'channel' } },
    'zk_radio_send': { type: 'hunan_mpython_radio_send', v: { MSG: 'send' } },
    'zk_radio_msg': { type: 'hunan_mpython3_radio_recv_msg', f: { message: 'message' } },
    /* 第四十五轮：语句版广播 / MQTT 消息（官方 mxml 导入用） */
    'zk_radio_msg_do': { type: 'hunan_mpython3_radio_recv_msg', v: { MSG: 'message' } },
    'zk_mqtt_msg_do': { type: 'hunan_mpython3_siot_receive_msg', v: { MSG: 'message' } },
    'zk_wifi_connect': { type: 'hunan_mpython3_init_wifi', f: { SSID: 'ssid', PWD: 'password' } },
    'zk_wifi_ok': { type: 'hunan_mpython_wifi_isconnected' },

    /* ---------- 第九节：八年级新增硬件 ---------- */
    'zk_magnetic_init': { type: 'hunan_mpython_magnetic_init' },
    'zk_magnetic_calibrate': { type: 'hunan_mpython_magnetic_calibrate' },
    'zk_magnetic_peeling': { type: 'hunan_mpython_magnetic_peeling' },
    'zk_magnetic_heading': { type: 'hunan_mpython_magnetic_get_heading' },
    'zk_gps_init': { type: 'hunan_mpython_bluebit_ATGM336H_init', f: { COM: 'COMNUM' }, v: { TX: 'tx', RX: 'rx' } },
    'zk_gps_parse': { type: 'hunan_mpython_bluebit_ATGM336H_Parese' },
    'zk_gps_data': { type: 'hunan_mpython_bluebit_ATGM336H_data' },
    'zk_qrcode': { type: 'hunan_mpython_qr_code', v: { STR: 'str', X: 'x', Y: 'y' } },
    'zk_rfid_scan': { type: 'hunan_mpython_bluebit_newrfid_scan' },
    'zk_rfid_id': { type: 'hunan_mpython_bluebit_newrfid_getserial' },
    'zk_speech2_init': { type: 'hunan_mpython_bluebit_ledong_speech_recognition_init', f: { COM: 'COMNUM' }, v: { TX: 'tx', RX: 'rx' } },
    'zk_speech2_result': { type: 'hunan_mpython_bluebit_ledong_speech_recognition_result' },
    'zk_str2num': { type: 'hunan_string_to_number', v: { S: 'TEXT' } },
    'zk_oled_line5': { type: 'hunan_mpython_display_DispChar_5lines', v: { T: 'message', LINE: 'DispChar_5lines' } }
  };

  /* 反查：官方类型 → 本项目类型（EXPORT_MAP 的逆，用于判断能否双向） */
  var REVERSE_MAP = (function () {
    var m = {};
    Object.keys(EXPORT_MAP).forEach(function (k) {
      var t = EXPORT_MAP[k].type;
      if (t && !m[t]) m[t] = k;
    });
    return m;
  })();

  /* ------------------------------------------------------------
   * 把 XML 文本按 EXPORT_MAP 改写成官方类型
   *
   * 用 DOM 逐块处理：只改当前 block 的 type 以及它**直属**的
   * field/value/statement 名，不动下一层子积木（子积木自己是
   * 一个独立元素，会被自己的规则处理）。
   * 遇到不认识的本项目类型原样保留 —— mPython 打开时该积木
   * 显示为未知块，但整个工程仍能正常载入，不会整份文件报废。
   * ------------------------------------------------------------ */
  function toMpythonTypes(xmlText) {
    var doc = parseXml(String(xmlText || ''));
    if (!doc) return String(xmlText || '');

    /* 索引：block/shadow 元素 → 其直属 field/value/statement 子元素 */
    var blocks = doc.getElementsByTagName('*');
    var list = [];
    for (var i = 0; i < blocks.length; i++) {
      var el = blocks[i];
      if (el.nodeName !== 'block' && el.nodeName !== 'shadow') continue;
      var kids = { f: {}, v: {}, s: {} };
      for (var j = 0; j < el.childNodes.length; j++) {
        var c = el.childNodes[j];
        if (c.nodeType !== 1) continue;
        var nm = c.getAttribute('name');
        if (!nm) continue;
        if (c.nodeName === 'field') kids.f[nm] = c;
        else if (c.nodeName === 'value') kids.v[nm] = c;
        else if (c.nodeName === 'statement') kids.s[nm] = c;
      }
      list.push({ el: el, kids: kids });
    }

    var stats = { mapped: 0, kept: 0 };
    var keptTypes = {};

    list.forEach(function (it) {
      var t = it.el.getAttribute('type');
      var rule = EXPORT_MAP[t];
      if (!rule) {
        /* 本项目类型但没写导出规则 → 保留原样，让 mPython 标为未知块 */
        if (String(t).indexOf('zk_') === 0) { keptTypes[t] = 1; stats.kept++; }
        return;
      }
      if (rule.type === t) { stats.kept++; return; }   /* 规则里显式声明保留 */
      it.el.setAttribute('type', rule.type);
      stats.mapped++;
      /* field / value / statement 改名 */
      ['f', 'v', 's'].forEach(function (kind) {
        var map = rule[kind];
        if (!map) return;
        Object.keys(map).forEach(function (from) {
          var node = it.kids[kind][from];
          if (!node) return;
          if (map[from] === null) {          /* 显式丢弃 */
            node.parentNode.removeChild(node);
          } else {
            node.setAttribute('name', map[from]);
          }
        });
      });
      /* drop：列出即丢 */
      (rule.drop || []).forEach(function (nm) {
        ['f', 'v', 's'].forEach(function (kind) {
          var node = it.kids[kind][nm];
          if (node) node.parentNode.removeChild(node);
        });
      });
    });

    stats.keptTypes = Object.keys(keptTypes);
    /* 统计单独返回，不挂在字符串上（字符串挂属性在严格模式下会抛错） */
    toMpythonTypes.lastStats = stats;
    return serDoc(doc);
  }

  /* DOM → 严格缩进文本（与 prettyXml 同一个序列化器，复用 serNode） */
  function serDoc(doc) {
    var lines = [];
    serNode(doc.documentElement, 0, lines);
    return lines.join('\n');
  }

  /* 统计一个工程里有多少种本项目积木没有官方对应（导出前预警用） */
  function unmappedTypes(xmlText) {
    var doc = parseXml(String(xmlText || ''));
    var out = {};
    if (!doc) return [];
    var blocks = doc.getElementsByTagName('*');
    for (var i = 0; i < blocks.length; i++) {
      var el = blocks[i];
      if (el.nodeName !== 'block' && el.nodeName !== 'shadow') continue;
      var t = el.getAttribute('type');
      if (!t || String(t).indexOf('zk_') !== 0) continue;
      if (!EXPORT_MAP[t]) out[t] = 1;
    }
    return Object.keys(out);
  }

  /* 某个官方类型在本项目是否有对应积木（判断双向兼容完整度） */
  function isBidirectional(officialType) {
    return !!REVERSE_MAP[officialType];
  }
  function unknownTypes(xmlText) {
    var out = [];
    var re = /<block\s+type="([^"]+)"/g;
    var m;
    while ((m = re.exec(xmlText || ''))) {
      if (out.indexOf(m[1]) < 0) out.push(m[1]);
    }
    var hasBlockly = false;
    try { hasBlockly = !!(global.Blockly && global.Blockly.Blocks); }
    catch (e) { hasBlockly = false; }
    return out.filter(function (t) {
      if (TYPE_ALIAS[t]) return false;
      if (!hasBlockly) return true;
      try { return !global.Blockly.Blocks[t]; } catch (e) { return true; }
    });
  }

  ZKB.Project = {
    MPYTHON_MARK: MPYTHON_MARK,
    toMxml: toMxml,
    parse: parse,
    pureXml: pureXml,
    mpythonType: mpythonType,
    readMeta: readMeta,
    fileName: fileName,
    loadFromPython: loadFromPython,
    unknownTypes: unknownTypes,
    remapTypes: remapTypes,
    remapMutations: remapMutations,
    prettyXml: prettyXml,
    toMpythonTypes: toMpythonTypes,
    unmappedTypes: unmappedTypes,
    isBidirectional: isBidirectional,
    EXPORT_MAP: EXPORT_MAP,
    REVERSE_MAP: REVERSE_MAP,
    HUNAN_ALIAS: HUNAN_ALIAS,
    TYPE_ALIAS: TYPE_ALIAS
  };
})(window);