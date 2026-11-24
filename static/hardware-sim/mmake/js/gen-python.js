/* ============================================================
 * gen-python.js —— 积木 → MicroPython（掌控板 mpython 固件 API）
 * API 参考：mPython 官方库（mpython.py / dht / servo / hcsr04）
 * ============================================================ */
(function (global) {
  'use strict';
  var ZKB = global.ZKB;
  var PY = Blockly.Python;
  var O = PY.ORDER_NONE;

  /* ============================================================
   * 统一缩进单位 = 4 空格
   *
   * Blockly 自带的 Python 生成器默认 2 空格（PY.INDENT = '  '），
   * 但 mPython 官方示例与 MicroPython 社区习惯都是 4 空格。
   * 这里直接改生成器的 INDENT 属性——所有内置生成器
   * （controls_if / controls_for / logic_compare …）都用它来缩进，
   * 改一处即可整体对齐，无需逐个覆写 forBlock。
   * 本文件自制的 indent() 默认也是 4 空格，两边一致。
   * ============================================================ */
  PY.INDENT = '    ';

  /* ---------- 取值辅助 ---------- */
  function v(block, name, fallback) {
    var code = PY.valueToCode(block, name, O) || (fallback === undefined ? '0' : fallback);
    return code;
  }
  function indent(code, unit) {
    unit = unit || '    ';
    return code.split('\n').map(function (l) { return l.length ? unit + l : l; }).join('\n');
  }
  function hexToRgb(hex) {
    var m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
    if (!m) return [0, 0, 0];
    var n = parseInt(m[1], 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }

  /* ============================================================
   * 事件帽子
   * ============================================================ */
  PY.forBlock['zk_when_start'] = function (block) {
    return '# ----- 掌控板启动 -----';
  };
  // 事件帽子在顶层编译时特殊处理（见 genPython），这里不参与普通链生成

  function touchVar(pad) { return 'touchPad_' + pad; }

  /* ============================================================
   * 控制
   * ============================================================ */
  PY.forBlock['zk_wait_sec'] = function (b) {
    return 'sleep_ms(int((' + v(b, 'SEC', '1') + ') * 1000))\n';
  };
  PY.forBlock['zk_wait_ms'] = function (b) {
    return 'sleep_ms(int(' + v(b, 'MS', '100') + '))\n';
  };
  PY.forBlock['zk_print'] = function (b) {
    return 'print(' + v(b, 'V', "''") + ')\n';
  };

  /* 永久循环（兼容无积木时） */
  PY.forBlock['controls_forever'] = function (block) {
    var branch = PY.statementToCode(block, 'SUBSTACK');
    return 'while True:\n' + (branch || '    pass\n');
  };

  /* 重复执行直到 / 当…成立时重复
   *
   * ⚠【第四十九轮修正】Blockly 内置 python 生成器写的是
   *     'while ' + (until ? 'not ' : '') + cond + ':'  —— 条件**不加括号**。
   * 而本项目里 zk_light / zk_sound / zk_ultra 这类自定义值积木
   * 返回的是**纯字符串**（没有算子优先级元组），
   * valueToCode 判定优先级未知时会给它们**单独**套一层括号，于是
   *     官方写法  while not (light.read() > 20):
   * 被生成成
   *     实际产出  while not (light.read()) > 20:
   * 这两句语义完全不同：
   *     前者 = 「光线 > 20 时退出循环」
   *     后者 = 「(非光线) 再 > 20」，在 MicroPython 里是拿 bool 比大小，
   *            几乎恒为 False → 循环一次都不执行。
   * 这里显式给**整个条件**加括号，保证语义与官方示例一致。 */
  PY.forBlock['controls_whileUntil'] = function (b) {
    var until = b.getFieldValue('MODE') === 'UNTIL';
    var cond = v(b, 'BOOL') || 'False';
    var branch = PY.statementToCode(b, 'DO') || PY.INDENT + 'pass\n';
    return 'while ' + (until ? 'not (' + cond + ')' : cond) + ':\n' + branch;
  };

  /* ============================================================
   * OLED
   * ============================================================ */
  PY.forBlock['zk_oled_clear'] = function () { return 'oled.fill(0)\n'; };
  PY.forBlock['zk_oled_fill'] = function (b) { return 'oled.fill(' + b.getFieldValue('V') + ')\n'; };
  /* 第四十八轮：统一的「屏幕 %1」积木
   *   清空 → oled.fill(0)   （擦干净：黑屏）
   *   全亮 → oled.fill(1)   （全部点亮）
   *   黑底 → oled.fill(0)   （铺黑底）
   *   白底 → oled.fill(1)   （铺白底）
   * 真机 oled 的 fill(x)：0=黑、1=白。 */
  PY.forBlock['zk_oled_screen'] = function (b) {
    var v = b.getFieldValue('V');
    if (v === 'clear' || v === 'black') return 'oled.fill(0)\n';
    return 'oled.fill(1)\n';
  };
  PY.forBlock['zk_oled_show'] = function () { return 'oled.show()\n'; };
  PY.forBlock['zk_oled_invert'] = function (b) { return 'oled.invert(' + b.getFieldValue('V') + ')\n'; };

  PY.forBlock['zk_oled_text_color'] = function (b) {
    return '_zk_text_color("' + (b.getFieldValue('C') || 'white') + '")\n';
  };
  PY.forBlock['zk_oled_text_color_do'] = function (b) {
    var expr = v(b, 'T', "''");
    var x = v(b, 'X', '0'), y = v(b, 'Y', '0');
    return '_zk_text(' + expr + ', ' + x + ', ' + y + ', "' +
      (b.getFieldValue('C') || 'white') + '")\n';
  };
  PY.forBlock['zk_oled_text'] = function (b) {
    var expr = v(b, 'T', "''");
    var x = v(b, 'X', '0'), y = v(b, 'Y', '0');
    /* 只要要显示的内容里有中文，就必须用 DispChar（mpython 固件
     * 的 DispChar 才能显示中文，text 只支持 ASCII）。
     *
     * 【第四十九轮修正】原来只看 expr（Python 源码）里有没有中文，
     * 但中文变量名会被 nameDB_ 转义成 _E4_B8_80 这种形式，
     * 中文早就没了 → 判断失效 → 用了 oled.text，
     * 真机上显示成乱码。
     * 现在改成看**积木里真正要显示的内容**：
     *   文本积木 → 取它的 TEXT 字段原文
     *   文本拼接 → 看各个拼接项里有没有中文 */
    var raw = '';
    try {
      var tf = b.getField('T');
      var tv = tf ? tf.getValue() : '';
      if (tv) {
        raw = String(tv);
      } else {
        /* 文本拼接（text_join）：把每个 ADD 项的文本取出来 */
        var inp = b.getInput('T');
        var tb = inp && inp.connection ? inp.connection.targetBlock() : null;
        if (tb) {
          raw = JSON.stringify(tb).replace(/\\u[0-9a-fA-F]{4}/g, function (m) {
            return String.fromCharCode(parseInt(m.slice(2), 16));
          });
        }
      }
    } catch (e) { }
    /* 【第四十九轮修正】官方六年级示例清一色用 oled.DispChar
     * （护眼灯 / 声光贺卡 / 坐姿监控器 … 里全是 DispChar），
     * 从没出现过 oled.text。DispChar 对 ASCII 同样有效，
     * 这里统一用 DispChar，保证学生照教材做出来的工程
     * 生成的代码和教材一模一样，真机上也一致。
     * （raw 仍算出来，留给调试与将来按字体细分用） */
    void raw;
    return 'oled.DispChar(str(' + expr + '), ' + x + ', ' + y + ')\n';
  };
  PY.forBlock['zk_oled_pixel'] = function (b) {
    return 'oled.pixel(' + v(b, 'X') + ', ' + v(b, 'Y') + ', ' + b.getFieldValue('V') + ')\n';
  };
  PY.forBlock['zk_oled_line'] = function (b) {
    return 'oled.line(' + ['X1', 'Y1', 'X2', 'Y2'].map(function (k) { return v(b, k); }).join(', ') + ', 1)\n';
  };
  PY.forBlock['zk_oled_rect'] = function (b) {
    return 'oled.' + b.getFieldValue('FILL') + '(' + v(b, 'X') + ', ' + v(b, 'Y') + ', ' +
      v(b, 'W') + ', ' + v(b, 'H') + ', 1)\n';
  };
  PY.forBlock['zk_oled_circle'] = function (b) {
    return 'oled.' + b.getFieldValue('FILL') + '(' + v(b, 'X') + ', ' + v(b, 'Y') + ', ' + v(b, 'R') + ', 1)\n';
  };

  /* ---------- OLED 扩展图形（依据 mpython 官方 API） ---------- */
  PY.forBlock['zk_oled_roundrect'] = function (b) {
    return 'oled.RoundRect(' + v(b, 'X') + ', ' + v(b, 'Y') + ', ' + v(b, 'W') + ', ' + v(b, 'H') +
      ', ' + v(b, 'R') + ', ' + b.getFieldValue('V') + ')\n';
  };
  PY.forBlock['zk_oled_hline'] = function (b) {
    return 'oled.hline(' + v(b, 'X') + ', ' + v(b, 'Y') + ', ' + v(b, 'W') + ', ' + b.getFieldValue('V') + ')\n';
  };
  PY.forBlock['zk_oled_vline'] = function (b) {
    return 'oled.vline(' + v(b, 'X') + ', ' + v(b, 'Y') + ', ' + v(b, 'L') + ', ' + b.getFieldValue('V') + ')\n';
  };
  PY.forBlock['zk_oled_triangle'] = function (b) {
    return 'oled.fill_triangle(' + ['X0', 'Y0', 'X1', 'Y1', 'X2', 'Y2'].map(function (k) { return v(b, k); }).join(', ') +
      ', ' + b.getFieldValue('V') + ')\n';
  };
  PY.forBlock['zk_oled_progress'] = function (b) {
    return 'UI.ProgressBar(' + v(b, 'X') + ', ' + v(b, 'Y') + ', ' + v(b, 'W') + ', ' + v(b, 'H') + ', ' +
      v(b, 'P', '50') + ')\n';
  };
  PY.forBlock['zk_oled_stripbar'] = function (b) {
    /* 官方 API 为 UI.stripBar（大写 B），见 mPythonSoftware-docs oled.rst */
    return 'UI.stripBar(' + v(b, 'X') + ', ' + v(b, 'Y') + ', ' + v(b, 'W') + ', ' + v(b, 'H') + ', ' +
      v(b, 'P', '50') + ', dir=' + b.getFieldValue('DIR') + ', frame=' + b.getFieldValue('FR') + ')\n';
  };

  /* ---------- 屏幕图片 / 表情 ----------
     生成的位图字节采用 framebuf.MONO_HLSB 布局（横向 128px = 16 字节 / 行），
     通过 oled.Bitmap(x, y, bitmap, w, h, c) 显示。 */
  PY.forBlock['zk_oled_face'] = function (b) {
    var face = b.getFieldValue('FACE') || 'happy';
    var reg = ZKB.PyImageRegistry && ZKB.PyImageRegistry.face(face);
    if (!reg) {
      return '# 表情 ' + face + ' 未找到，请先在「屏幕图片」面板生成\n' +
        'oled.DispChar("' + face + '", 0, 0)\noled.show()\n';
    }
    return reg.emit;
  };
  PY.forBlock['zk_oled_image'] = function (b) {
    var id = b.getFieldValue('IMG');
    if (!id || id === 'none') return '# 请先在右侧「屏幕图片」面板上传图片\n';
    var reg = ZKB.PyImageRegistry && ZKB.PyImageRegistry.get(id);
    if (!reg) return '# 图片「' + id + '」不存在，请重新选择\n';
    return reg.emit;
  };

  /* ============================================================
   * RGB
   * ============================================================ */
  PY.forBlock['zk_rgb_one'] = function (b) {
    var c = hexToRgb(b.getFieldValue('COLOR'));
    var n = b.getFieldValue('N');
    /* ⚠ 官方六年级示例（制作走马灯.py / 制作光控灯.py）在每次 rgb.write()
       之后都跟一句 time.sleep_ms(1) —— WS2812 需要这个延时来锁存数据，
       少了这一句连续刷新会丢帧、颜色显示不稳。 */
    if (n === 'ALL') return 'rgb.fill((' + c.join(', ') + '))\nrgb.write()\ntime.sleep_ms(1)\n';
    return 'rgb[' + n + '] = (' + c.join(', ') + ')\nrgb.write()\ntime.sleep_ms(1)\n';
  };
  PY.forBlock['zk_rgb_rgb'] = function (b) {
    var n = b.getFieldValue('N');
    var t = '(' + v(b, 'R', '255') + ', ' + v(b, 'G', '0') + ', ' + v(b, 'B', '0') + ')';
    if (n === 'ALL') return 'rgb.fill' + t + '\nrgb.write()\ntime.sleep_ms(1)\n';
    return 'rgb[' + n + '] = ' + t + '\nrgb.write()\ntime.sleep_ms(1)\n';
  };
  PY.forBlock['zk_rgb_clear'] = function () {
    return 'rgb.fill((0, 0, 0))\nrgb.write()\ntime.sleep_ms(1)\n';
  };
  /* 第四十五轮：刷新彩灯（官方 rgb.write()） */
  PY.forBlock['zk_rgb_write'] = function () {
    return 'rgb.write()\ntime.sleep_ms(1)\n';
  };
  PY.forBlock['zk_rgb_brightness'] = function (b) {
    return 'rgb.brightness(round((' + v(b, 'V', '30') + ') / 100, 2))\n';
  };

  /* ============================================================
   * 按键 / 触摸
   * ============================================================ */
  PY.forBlock['zk_is_btn'] = function (b) {
    return ['button_' + b.getFieldValue('BTN').toLowerCase() + '.is_pressed()', O];
  };
  PY.forBlock['zk_is_touch'] = function (b) {
    return [touchVar(b.getFieldValue('PAD')) + '.is_pressed()', O];
  };

  /* ============================================================
   * 板载传感器
   * ============================================================ */
  PY.forBlock['zk_light'] = function () { return ['light.read()', O]; };
  PY.forBlock['zk_sound'] = function () { return ['sound.read()', O]; };
  PY.forBlock['zk_accel'] = function (b) {
    return ['accelerometer.get_' + b.getFieldValue('AXIS') + '()', O];
  };
  PY.forBlock['zk_tilt'] = function (b) {
    var idx = b.getFieldValue('K') === 'r' ? '0' : '1';
    return ['accelerometer.roll_pitch_angle()[' + idx + ']', O];
  };

  /* ============================================================
   * 蜂鸣器
   * ============================================================ */
  PY.forBlock['zk_note'] = function (b) {
    return "music.play('" + b.getFieldValue('NOTE') + ':' + b.getFieldValue('BEAT') + "')\n";
  };
  PY.forBlock['zk_tone'] = function (b) {
    return 'music.pitch(int(' + v(b, 'F', '440') + '), int((' + v(b, 'D', '0.5') + ') * 1000))\n';
  };
  PY.forBlock['zk_music_stop'] = function () { return 'music.stop()\n'; };

  /* ============================================================
   * 引脚
   * ============================================================ */
  PY.forBlock['zk_pin_dout'] = function (b) {
    return 'pin_' + b.getFieldValue('PIN') + '.write_digital(' + b.getFieldValue('V') + ')\n';
  };
  PY.forBlock['zk_pin_pwm'] = function (b) {
    return 'pin_' + b.getFieldValue('PIN') + '.write_analog(int(' + v(b, 'V', '0') + '))\n';
  };
  PY.forBlock['zk_pin_din'] = function (b) { return ['pin_' + b.getFieldValue('PIN') + '.read_digital()', O]; };
  PY.forBlock['zk_pin_ain'] = function (b) { return ['pin_' + b.getFieldValue('PIN') + '.read_analog()', O]; };

  /* ============================================================
   * 拓展设备
   * ============================================================ */
  PY.forBlock['zk_dht_measure'] = function () { return 'dht_sensor.measure()\n'; };
  PY.forBlock['zk_dht_val'] = function (b) {
    return ['dht_sensor.' + (b.getFieldValue('K') === 't' ? 'temperature()' : 'humidity()'), O];
  };
  /* 第三十二轮：官方六年级示例统一写 ultrasonic.distance()（bluebit 版返回 cm），
     原来写 distance_cm() 是 HCSR04 的方法名，改用官方写法。 */
  PY.forBlock['zk_ultra'] = function () { return ['ultrasonic.distance()', O]; };
  /* 第四十五轮：初始化超声波（官方 mxml 用） */
  PY.forBlock['zk_ultra_init'] = function () { return 'ultrasonic = Ultrasonic()\n'; };
  PY.forBlock['zk_servo'] = function (b) { return 'servo_1.write_angle(int(' + v(b, 'A', '90') + '))\n'; };
  PY.forBlock['zk_ir'] = function () { return ['(_ir_sensor.read_digital() == 0)', O]; };

  PY.forBlock['zk_heat'] = function (b) { return '_heater.write_analog(' + (b.getFieldValue('V') === '1' ? '1023' : '0') + ')\n'; };
  PY.forBlock['zk_heat_power'] = function (b) {
    return '_heater.write_analog(int((' + v(b, 'V', '50') + ') / 100 * 1023))\n';
  };
  PY.forBlock['zk_pump'] = function (b) { return '_pump.write_analog(' + (b.getFieldValue('V') === '1' ? '1023' : '0') + ')\n'; };
  PY.forBlock['zk_pump_power'] = function (b) {
    return '_pump.write_analog(int((' + v(b, 'V', '80') + ') / 100 * 1023))\n';
  };
  PY.forBlock['zk_motor'] = function (b) {
    var d = b.getFieldValue('DIR'), s = v(b, 'S', '60');
    var vel = d === 'f' ? s : d === 'b' ? '-(' + s + ')' : '0';
    return '_motor_drive(' + vel + ')\n';
  };
  PY.forBlock['zk_car'] = function (b) {
    var d = b.getFieldValue('DIR'), s = v(b, 'S', '60');
    var map = { f: [s, s], b: ['-( ' + s + ')', '-(' + s + ')'], l: ['-(' + s + ')', s], r: [s, '-(' + s + ')'], s: ['0', '0'] };
    return '_car_drive(' + map[d][0] + ', ' + map[d][1] + ')\n';
  };
  PY.forBlock['zk_car_wheels'] = function (b) {
    return '_car_drive(' + v(b, 'L', '0') + ', ' + v(b, 'R', '0') + ')\n';
  };

  PY.forBlock['zk_color_rgb'] = function (b) {
    var k = { r: '0', g: '1', b: '2', c: '3' }[b.getFieldValue('K')];
    return ['_color_value()[' + k + ']', O];
  };
  PY.forBlock['zk_color_seen'] = function (b) {
    return ["_color_seen('" + b.getFieldValue('COLOR') + "')", O];
  };
  PY.forBlock['zk_camera_result'] = function () { return ['_camera_result()', O]; };
  PY.forBlock['zk_camera_seen'] = function (b) {
    return ["_camera_seen('" + b.getFieldValue('OBJ') + "')", O];
  };

  /* —— AI 摄像头三大识别能力（第二十三轮）—— */
  var OCR_MODE_CN = { text: 'text', number: 'number' };
  var OBJ_CAT_CN = { car: 'car', animal: 'animal', plant: 'plant', dish: 'dish', fruit: 'fruit' };
  var EMO_CN = { happy: 'happy', calm: 'calm', surprise: 'surprise', angry: 'angry', sad: 'sad' };

  /* 文字识别 */
  PY.forBlock['zk_vision_ocr_start'] = function (b) {
    return "_vision_ocr_start('" + (OCR_MODE_CN[b.getFieldValue('MODE')] || 'text') + "')\n";
  };
  PY.forBlock['zk_vision_ocr_text'] = function () { return ['_vision_ocr_text()', O]; };
  PY.forBlock['zk_vision_ocr_number'] = function () { return ['_vision_ocr_number()', O]; };

  /* 人脸识别 */
  PY.forBlock['zk_vision_face_register'] = function (b) {
    return '_vision_face_register(' + v(b, 'NAME', '"（未命名）"') + ', "' +
      (b.getFieldValue('GENDER') === 'female' ? 'female' : 'male') + '", ' +
      v(b, 'BIO', '""') + ')\n';
  };
  PY.forBlock['zk_vision_face_verify'] = function (b) {
    var n = b.getFieldValue('NAME');
    return '_vision_face_verify("' + String(n || '').replace(/"/g, '') + '")\n';
  };
  PY.forBlock['zk_vision_face_name'] = function () { return ['_vision_face_name()', O]; };
  PY.forBlock['zk_vision_face_gender'] = function () { return ['_vision_face_gender()', O]; };
  PY.forBlock['zk_vision_face_bio'] = function () { return ['_vision_face_bio()', O]; };
  PY.forBlock['zk_vision_face_emotion'] = function (b) {
    return ['_vision_face_is("' + (EMO_CN[b.getFieldValue('EM')] || 'happy') + '")', O];
  };
  PY.forBlock['zk_vision_face_emotion_text'] = function () { return ['_vision_emotion_text()', O]; };

  /* 物体识别 */
  PY.forBlock['zk_vision_obj_start'] = function (b) {
    return "_vision_obj_start('" + (OBJ_CAT_CN[b.getFieldValue('CAT')] || 'car') + "')\n";
  };
  PY.forBlock['zk_vision_obj_car'] = function () { return ['_vision_obj_result("car")', O]; };
  PY.forBlock['zk_vision_obj_animal'] = function () { return ['_vision_obj_result("animal")', O]; };
  PY.forBlock['zk_vision_obj_plant'] = function () { return ['_vision_obj_result("plant")', O]; };
  PY.forBlock['zk_vision_obj_dish'] = function () { return ['_vision_obj_result("dish")', O]; };
  PY.forBlock['zk_vision_obj_fruit'] = function () { return ['_vision_obj_result("fruit")', O]; };
  PY.forBlock['zk_vision_confidence'] = function () { return ['_vision_confidence()', O]; };
  /* 第三十五轮：K210 板上预置模型积木（真机走串口指令） */
  PY.forBlock['zk_k210_kpu_load'] = function (b) {
    var M = { face: 'face', digit: 'digit', class20: 'class20' };
    return '_kpu_load("' + (M[b.getFieldValue('MODEL')] || 'face') + '")\n';
  };
  PY.forBlock['zk_k210_face_detect'] = function () { return '_kpu_detect("face")\n'; };
  PY.forBlock['zk_k210_face_num'] = function () { return ['_kpu_face_num()', O]; };
  PY.forBlock['zk_k210_face_x'] = function (b) {
    return ['_kpu_face_field(' + v(b, 'N', '1') + ', 1)', O];
  };
  PY.forBlock['zk_k210_face_y'] = function (b) {
    return ['_kpu_face_field(' + v(b, 'N', '1') + ', 2)', O];
  };
  PY.forBlock['zk_k210_face_w'] = function (b) {
    return ['_kpu_face_field(' + v(b, 'N', '1') + ', 3)', O];
  };
  PY.forBlock['zk_k210_face_h'] = function (b) {
    return ['_kpu_face_field(' + v(b, 'N', '1') + ', 4)', O];
  };
  PY.forBlock['zk_k210_face_value'] = function (b) {
    return ['_kpu_face_field(' + v(b, 'N', '1') + ', 5)', O];
  };
  PY.forBlock['zk_k210_obj_detect'] = function (b) {
    return '_kpu_detect("' + (b.getFieldValue('MODEL') || 'class20') + '")\n';
  };
  PY.forBlock['zk_k210_obj_label'] = function (b) {
    return ['_kpu_obj_label(' + (Number(b.getFieldValue('IDX')) || 0) + ')', O];
  };
  PY.forBlock['zk_k210_obj_count'] = function () { return ['_kpu_obj_count()', O]; };
  PY.forBlock['zk_k210_obj_value'] = function (b) {
    return ['_kpu_obj_value(' + v(b, 'N', '1') + ')', O];
  };
  PY.forBlock['zk_k210_digit'] = function () { return ['_kpu_digit()', O]; };
  PY.forBlock['zk_mic'] = function () { return ['_mic_ext.read_analog()', O]; };
  PY.forBlock['zk_ambient'] = function () { return ['_light_ext.read_analog()', O]; };

  /* —— 新增设备 —— */
  PY.forBlock['zk_soil'] = function () { return ['_soil.read_analog()', O]; };
  PY.forBlock['zk_soil_pct'] = function () {
    return ['int(_soil.read_analog() / 4095 * 100)', O];
  };
  PY.forBlock['zk_pm25'] = function () { return ['_pm25_concentration()', O]; };
  PY.forBlock['zk_pm25_level'] = function () { return ['_pm25_level()', O]; };
  PY.forBlock['zk_pressure'] = function () { return ['_baro.pressure()', O]; };
  PY.forBlock['zk_altitude'] = function () { return ['_baro.altitude()', O]; };
  PY.forBlock['zk_ext_btn'] = function () { return ['(_ext_btn.read_digital() == 1)', O]; };
  PY.forBlock['zk_fan'] = function (b) {
    return '_fan.write_analog(' + (b.getFieldValue('V') === '1' ? '1023' : '0') + ')\n';
  };
  PY.forBlock['zk_fan_power'] = function (b) {
    return '_fan.write_analog(int((' + v(b, 'V', '60') + ') / 100 * 1023))\n';
  };

  /* ============================================================
   * 变量 / 列表 监视器（真实硬件无对应外设，保留说明注释；舞台仿真中实时显示）
   * ============================================================ */
  function fieldVarName(b) {
    var f = b.getField('VAR');
    /* 【第四十一轮修正】Blockly 10 的模型在 f.variable 上（旧版是 f.variable_） */
    var model = f && (f.variable || f.variable_);
    if (model) return model.name;
    return b.getFieldValue('VAR') || '变量';
  }
  PY.forBlock['zk_var_show'] = function (b) {
    return '# [舞台监视器] 显示变量「' + fieldVarName(b) + '」\n';
  };
  PY.forBlock['zk_var_hide'] = function (b) {
    return '# [舞台监视器] 隐藏变量「' + fieldVarName(b) + '」\n';
  };
  PY.forBlock['zk_list_show'] = function (b) {
    return '# [舞台监视器] 显示列表「' + fieldVarName(b) + '」\n';
  };
  PY.forBlock['zk_list_hide'] = function (b) {
    return '# [舞台监视器] 隐藏列表「' + fieldVarName(b) + '」\n';
  };
  PY.forBlock['zk_list_clear'] = function (b) {
    return v(b, 'LIST', '[]') + '.clear()\n';
  };
  PY.forBlock['zk_list_contains'] = function (b) {
    return ['(' + v(b, 'ITEM', "''") + ' in ' + v(b, 'LIST', '[]') + ')', O];
  };

  /* ============================================================
   * 通讯网络（物联网）
   * ============================================================ */
  // WiFi
  PY.forBlock['zk_wifi_connect'] = function (b) {
    return 'mywifi.connectWiFi(str(' + v(b, 'SSID', "''") + '), str(' + v(b, 'PWD', "''") + '))\n';
  };
  PY.forBlock['zk_wifi_ok'] = function () {
    return ['bool(mywifi.sta.isconnected())', O];
  };
  // 无线广播
  PY.forBlock['zk_radio_group'] = function (b) {
    return 'radio.config(channel=int(' + v(b, 'G', '7') + '))\n';
  };
  PY.forBlock['zk_radio_send'] = function (b) {
    return 'radio.send(str(' + v(b, 'MSG', "''") + '))\n';
  };
  PY.forBlock['zk_radio_msg'] = function () { return ['_radio_msg', O]; };
  /* 第四十五轮：语句版广播消息（官方 mxml 用），把消息打印到控制台 */
  PY.forBlock['zk_radio_msg_do'] = function (b) {
    return 'print("广播内容:", _radio_msg)\n';
  };
  // NTP
  PY.forBlock['zk_ntp_sync'] = function () {
    return 'ntptime.host = "ntp.aliyun.com"\nntptime.settime()\n';
  };
  PY.forBlock['zk_time_now'] = function (b) {
    return ["_now('" + b.getFieldValue('K') + "')", O];
  };
  // MQTT
  PY.forBlock['zk_mqtt_connect'] = function (b) {
    return '_mqtt = MQTTClient("mpython", str(' + v(b, 'HOST', "''") + '), port=int(' +
      v(b, 'PORT', '1883') + '))\n_mqtt.set_callback(_mqtt_cb)\n_mqtt.connect()\n';
  };
  PY.forBlock['zk_mqtt_pub'] = function (b) {
    return '_mqtt.publish(str(' + v(b, 'TOPIC', "''") + ').encode(), str(' + v(b, 'MSG', "''") + ').encode())\n';
  };
  PY.forBlock['zk_mqtt_msg'] = function () { return ['_mqtt_msg', O]; };
  /* 第四十五轮：语句版 MQTT 消息（官方 mxml 用） */
  PY.forBlock['zk_mqtt_msg_do'] = function (b) {
    return 'print("MQTT 消息:", _mqtt_msg)\n';
  };
  // WiFi 语音识别（旧积木）
  PY.forBlock['zk_asr_text'] = function () { return ['_asr_text()', O]; };

  /* —— 第二十四轮：AI 语音转文字 + 语音合成 —— */
  PY.forBlock['zk_speech_recognize'] = function (b) {
    var c = String(b.getFieldValue('CMD') || '').replace(/'/g, '');
    return c
      ? "_speech_recognize('" + c + "')\n"
      : '_speech_recognize("")\n';
  };
  PY.forBlock['zk_speech_text'] = function () { return ['_speech_text()', O]; };
  PY.forBlock['zk_speech_conf'] = function () { return ['_speech_conf()', O]; };
  PY.forBlock['zk_speech_is'] = function (b) {
    return ["_speech_text().find('" + String(b.getFieldValue('CMD') || '').replace(/'/g, '') + "') >= 0", O];
  };
  PY.forBlock['zk_speech_speak'] = function (b) {
    return '_speech_speak(str(' + v(b, 'TEXT', '"你好"') + '), ' +
      Number(b.getFieldValue('RATE') || 1) + ', ' +
      Number(b.getFieldValue('PITCH') || 1) + ', ' +
      Number(b.getFieldValue('VOL') || 1) + ')\n';
  };
  PY.forBlock['zk_speech_stop'] = function () { return '_speech_stop()\n'; };
  PY.forBlock['zk_speech_speaking'] = function () { return ['_speech_speaking()', O]; };
  PY.forBlock['zk_speech_done'] = function () { return ['_speech_done()', O]; };
  // 天气
  PY.forBlock['zk_weather'] = function (b) {
    return ["_weather(str(" + v(b, 'CITY', "'北京'") + "), '" + b.getFieldValue('K') + "')", O];
  };

  /* ============================================================
   * 第二十九轮：八年级新增硬件 → MicroPython
   *
   * API 依据（参考资料/mpython-master 固件源码）：
   *   Magnetic (mpython.py:643)  magnetic.calibrate() / peeling() / get_heading()
   *   ATGM336H_5N.py            GNSS(uart_num, pin_tx, pin_rx).GNSS_Parese()
   *   educore rfid (I2C)         rfid(sda, scl).scanning()
   *   magnetic 为板载器件，I2C 地址 48(0x30)，上电自动实例化
   * ============================================================ */
  PY.forBlock['zk_magnetic_init'] = function () {
    /* 板载磁力机上电即已实例化，这里只做一次显式 import 保证可读性 */
    return '# 磁场传感器（板载 I2C 0x30）已就绪\n';
  };
  PY.forBlock['zk_magnetic_calibrate'] = function () {
    return 'magnetic.calibrate()\n';
  };
  PY.forBlock['zk_magnetic_peeling'] = function () {
    return 'magnetic.peeling()\n';
  };
  PY.forBlock['zk_magnetic_heading'] = function () {
    return ['magnetic.get_heading()', O];
  };

  /* ATGM336H：UART 号 + 收发脚 → 官方示例用 1 / P16 / P15 */
  PY.forBlock['zk_gps_init'] = function (b) {
    var com = b.getFieldValue('COM') || '1';
    var tx = b.getFieldValue('TX') || '16';
    var rx = b.getFieldValue('RX') || '15';
    /* 固件里类名是 BDS（不是 ATGM336H），构造参数 uart_num / pin_tx / pin_rx */
    return 'GNSS = BDS(uart_num=' + com + ', pin_tx=Pin(Pin.P' + tx +
      '), pin_rx=Pin(Pin.P' + rx + '))\n';
  };
  PY.forBlock['zk_gps_parse'] = function () {
    return 'GNSS.GNSS_Parese()\n';
  };
  PY.forBlock['zk_gps_data'] = function (b) {
    return ['_gps_field(GNSS, \'' + (b.getFieldValue('K') || 'lon') + '\')', O];
  };
  PY.forBlock['zk_gps_ready'] = function () {
    return ['_gps_valid(GNSS)', O];
  };

  PY.forBlock['zk_qrcode'] = function (b) {
    return 'oled.qr_code(str(' + v(b, 'STR', "'24992'") + '), ' +
      v(b, 'X', '0') + ', ' + v(b, 'Y', '0') + ')\n';
  };

  /* 刷卡是语句积木（与官方 newrfid_scan 一致），卡号用 zk_rfid_id 取 */
  PY.forBlock['zk_rfid_scan'] = function () {
    return '_rfid_scan()\n';
  };
  PY.forBlock['zk_rfid_id'] = function () {
    return ['_rfid_last', O];
  };

  PY.forBlock['zk_speech2_init'] = function (b) {
    var com = b.getFieldValue('COM') || '1';
    var tx = b.getFieldValue('TX') || '16';
    var rx = b.getFieldValue('RX') || '15';
    return '_asr2_init(uart_num=' + com + ', pin_tx=Pin.P' + tx + ', pin_rx=Pin.P' + rx + ')\n';
  };
  PY.forBlock['zk_speech2_result'] = function () {
    return ['_asr2_result()', O];
  };

  /* 5 行显示：官方 DispChar_5lines 用 UI.print 直接定位行号，
     这里换成 mpython 的 oled.rect + oled.text 组合，效果一致 */
  PY.forBlock['zk_oled_line5'] = function (b) {
    var line = v(b, 'LINE', '1');
    var txt = v(b, 'T', "''");
    return '_line5(str(' + txt + '), int(' + line + '))\n';
  };

  PY.forBlock['zk_str2num'] = function (b) {
    var fn = b.getFieldValue('TYPE') === 'float' ? 'float' : 'int';
    return [fn + '(str(' + v(b, 'S', "''") + '))', O];
  };

  /* 第四十六轮：把变量限制在最低值与最高值之间
   * 第一个口是变量（field_variable），取变量名参与运算；
   * 语义与 Blockly 内置 math_constrain 一致：min(max(值, 最低), 最高)。 */
  PY.forBlock['zk_constrain'] = function (b) {
    var nm = fieldVarName(b);
    /* 走 nameDB 拿到合法的 python 变量名（中文名会被转成拼音/下划线） */
    var code = PY.getVariableName ? PY.getVariableName(b.getFieldValue('VAR')) : nm;
    if (!code) code = nm;
    var low = v(b, 'LOW', '0');
    var high = v(b, 'HIGH', 'float(\'inf\')');
    return ['min(max(' + code + ', ' + low + '), ' + high + ')', O];
  };
  /* 第四十九轮：区间映射
   * 用头文件里注入的 hunan_map_value()（与官方六年级示例同名），
   * 不另起名字，方便学生拿生成的代码和教材对照。 */
  PY.forBlock['zk_map_value'] = function (b) {
    return ['hunan_map_value(' + v(b, 'X', '0') + ', ' + v(b, 'A', '0') + ', ' +
      v(b, 'B', '4095') + ', ' + v(b, 'C', '0') + ', ' + v(b, 'D', '9') + ')', O];
  };

  /* ============================================================
   * 自制积木（自定义函数）
   * ============================================================ */
  PY.forBlock['zk_my_call'] = function (block) {
    var spec = block.spec_ || { items: [] };
    var args = ZKB.MyBlocks.argsOf(spec);
    var parts = args.map(function (it, i) {
      return v(block, 'ARG' + i, it.type === 'bool' ? 'False' : "''");
    });
    return ZKB.MyBlocks.fnName(block.defId_) + '(' + parts.join(', ') + ')\n';
  };

  /* 自制积木定义 → def 函数（参数名固定 a0/a1…，形参值写入同名变量便于积木引用） */
  function myDefCode(block) {
    var spec = block.spec_ || { items: [], name: '我的积木' };
    var args = ZKB.MyBlocks.argsOf(spec);
    var fn = ZKB.MyBlocks.fnName(block.id);
    var head = 'def ' + fn + '(' + args.map(function (_, i) { return 'a' + i; }).join(', ') + '):';
    var maps = args.map(function (it, i) {
      var inp = block.getInput('ARG' + i);
      var conn = inp && inp.connection.targetConnection;
      var varName = null;
      if (conn && conn.sourceBlock_ && conn.sourceBlock_.type === 'variables_get') {
        var f = conn.sourceBlock_.getField('VAR');
        /* 【第四十一轮修正】模型在 f.variable 上，旧代码读的是 f.variable_ */
        var vm = f && (f.variable || f.variable_);
        if (vm) varName = vm.name;
      }
      if (varName !== null) return "    globals()[" + JSON.stringify(varName) + "] = a" + i;
      return null;
    }).filter(Boolean);
    var chain = block.getNextBlock() ? PY.blockToCode(block.getNextBlock()) : '';
    var body = maps.join('\n') + (maps.length ? '\n' : '') + (chain || '');
    body = indent(body) || '    pass';
    if (spec.noRefresh) body = '    # 运行时不刷新屏幕\n' + body;
    return '# 自制积木：' + (spec.name || '我的积木') + '\n' + head + '\n' + body;
  }

  /* ============================================================
   * 前置代码（import + 设备初始化 + 辅助函数）
   * ============================================================ */
  // 引脚映射：均选用 mpython 固件支持对应模式、且不与板载资源冲突的引脚
  // （触摸复用 P27/P14/P12/P13/P15/P4，OLED/蜂鸣器等板载资源也已避开）
  var DEVICE_PINS = {
    dht: 1, servo: 0, ir: 21, heater: 9, pump: 11,
    car: [8, 16, 19, 20], motor: [6, 7],
    ultra: { trig: 14, echo: 13 }, mic: 3, lightExt: 2,
    soil: 10, pm25: { rx: 22, tx: 23 }, baro: 0, extbtn: 15, fan: 16,
    /* 第二十九轮：RFID（I2C SDA/SCL）与离线语音识别（UART）默认引脚 */
    rfid: { sda: 20, scl: 19 }, speech2: { tx: 16, rx: 15 },
    /* 第三十六轮：人体红外与 MP3 模块默认引脚 */
    pir: 15
  };

  function buildPreamble(ws, flags) {
    var L = [];
    L.push('# ==========================================');
    L.push('#  由「掌控图形化编程」自动生成的 MicroPython 代码');
    L.push('#  硬件：掌控板（mpython 固件）+ 拓展设备');
    L.push('# ==========================================');
    L.push('from mpython import *');

    if (flags.music) L.push('import music');
    /* 第四十九轮：math.sqrt 需要 math 模块 */
    if (flags.mathLib) L.push('import math');
    if (flags.dht) L.push('from dht import DHT11');
    /* 第三十六轮：DS18B20 单总线温度传感器（掌控板 3.0 文档 ds18x20.DS18X20） */
    if (flags.ds18) L.push('from ds18x20 import DS18X20');
    /* 通用 ADC（MicroPython 官方 ADC.ADC） */
    if (flags.adc) L.push('from machine import ADC');
    if (flags.servo) L.push('from servo import Servo');
    /* 第三十二轮：官方六年级示例（超声波测距.py / 坐姿监控器.py / 红灯自动停车.py）
       统一用 `from bluebit import *`，超声波与颜色传感器都从这来。
       原来按需import hcsr04 / tcs34725，与教材写法不一致、
       且 tcs34725 并非所有固件都带。 */
    if (flags.ultra || flags.color) L.push('from bluebit import *');
    /* 官方图形化生成的映射函数就叫这个名字（六年级 坐姿监控器.py /
       按量自动投喂器.py / 电子围栏系统.py），保持同名便于和教材代码对照。 */
    L.push('');
    L.push('def hunan_map_value(x, in_min, in_max, out_min, out_max):');
    L.push('    # 把 x 从 [in_min, in_max] 线性映射到 [out_min, out_max]');
    L.push('    if in_min == in_max:');
    L.push('        return out_min');
    L.push('    mapped = (x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min');
    L.push('    return int(mapped)');
    if (flags.shake) L.push('from machine import Timer');
    if (flags.camera || flags.vision) L.push('from machine import UART');
    /* 第二十九轮：八年级新增硬件需要的模块 */
    if (flags.gps) L.push('from machine import UART');
    if (flags.rfid) L.push('from machine import I2C');

    /* 通用引脚（引脚 IO 积木） */
    Object.keys(flags.pins).sort(function (a, b) { return a - b; }).forEach(function (p) {
      var mode = flags.pins[p];
      L.push('pin_' + p + ' = MPythonPin(' + p + ', PinMode.' + mode + ')');
    });

    /* 设备初始化 */
    if (flags.dht) L.push('dht_sensor = DHT11(Pin(Pin.P' + DEVICE_PINS.dht + '))');
    if (flags.servo) L.push('servo_1 = Servo(' + DEVICE_PINS.servo + ')');
    if (flags.ir) L.push('_ir_sensor = MPythonPin(' + DEVICE_PINS.ir + ', PinMode.IN)');
    if (flags.ultra) {
      /* 第三十二轮：对齐官方六年级示例（超声波测距.py / 坐姿监控器.py）
         官方写法是 `from bluebit import *` + `ultrasonic = Ultrasonic()`
         + `ultrasonic.distance()`（返回 cm）。
         原来用的 HCSR04(trigger_pin=..., echo_pin=...) 是 micropython 通用写法，
         但掌控板固件实测更稳的是官方 bluebit 版，且与教材一致。 */
      L.push('ultrasonic = Ultrasonic()');
    }
    if (flags.heater) L.push('_heater = MPythonPin(' + DEVICE_PINS.heater + ', PinMode.PWM)');
    if (flags.pump) L.push('_pump = MPythonPin(' + DEVICE_PINS.pump + ', PinMode.PWM)');
    if (flags.mic) L.push('_mic_ext = MPythonPin(' + DEVICE_PINS.mic + ', PinMode.ANALOG)');
    if (flags.lightExt) L.push('_light_ext = MPythonPin(' + DEVICE_PINS.lightExt + ', PinMode.ANALOG)');
    if (flags.soil) L.push('_soil = MPythonPin(' + DEVICE_PINS.soil + ', PinMode.ANALOG)');
    if (flags.extbtn) L.push('_ext_btn = MPythonPin(' + DEVICE_PINS.extbtn + ', PinMode.IN)');
    if (flags.pir) L.push('_pir = MPythonPin(' + DEVICE_PINS.pir + ', PinMode.IN)');
    if (flags.fan) L.push('_fan = MPythonPin(' + DEVICE_PINS.fan + ', PinMode.PWM)');
    if (flags.pm25) {
      L.push('# PM2.5 传感器（串口，如 PMS5003；引脚按实际接线修改）');
      L.push('from machine import UART');
      L.push('_pm25_uart = UART(2, baudrate=9600, tx=Pin(Pin.P' + DEVICE_PINS.pm25.tx + '), rx=Pin(Pin.P' + DEVICE_PINS.pm25.rx + '))');
      L.push('def _pm25_concentration():');
      L.push('    buf = _pm25_uart.read(32)');
      L.push('    if buf and len(buf) >= 14 and buf[0] == 0x42 and buf[1] == 0x4d:');
      L.push('        return buf[10] * 256 + buf[11]');
      L.push('    return 0');
      L.push('def _pm25_level():');
      L.push('    v = _pm25_concentration()');
      L.push('    if v <= 35: return "优"');
      L.push('    if v <= 75: return "良"');
      L.push('    if v <= 115: return "轻度污染"');
      L.push('    if v <= 150: return "中度污染"');
      L.push('    return "重度污染"');
    }
    if (flags.baro) {
      L.push('# 气压传感器（I2C，如 BMP280；请按实际模块调整库名）');
      L.push('from bmp280 import BMP280');
      L.push('_baro = BMP280(i2c)');
    }

    if (flags.motor) {
      L.push('_motor_a = MPythonPin(' + DEVICE_PINS.motor[0] + ', PinMode.PWM)');
      L.push('_motor_b = MPythonPin(' + DEVICE_PINS.motor[1] + ', PinMode.PWM)');
      L.push('def _motor_drive(v):');
      L.push('    v = max(-100, min(100, int(v)))');
      L.push('    _motor_a.write_analog(int(v / 100 * 1023) if v > 0 else 0)');
      L.push('    _motor_b.write_analog(int(-v / 100 * 1023) if v < 0 else 0)');
    }
    if (flags.car) {
      var p = DEVICE_PINS.car;
      L.push('# 小车电机引脚（请按实际接线修改）');
      L.push('_car_lf = MPythonPin(' + p[0] + ', PinMode.PWM)');
      L.push('_car_lb = MPythonPin(' + p[1] + ', PinMode.PWM)');
      L.push('_car_rf = MPythonPin(' + p[2] + ', PinMode.PWM)');
      L.push('_car_rr = MPythonPin(' + p[3] + ', PinMode.PWM)');
      L.push('def _wheel(a, b, speed):');
      L.push('    speed = max(-100, min(100, int(speed)))');
      L.push('    a.write_analog(int(speed / 100 * 1023) if speed > 0 else 0)');
      L.push('    b.write_analog(int(-speed / 100 * 1023) if speed < 0 else 0)');
      L.push('def _car_drive(l, r):');
      L.push('    _wheel(_car_lf, _car_lb, l)');
      L.push('    _wheel(_car_rf, _car_rr, r)');
    }
    if (flags.color) {
      /* 第三十二轮：对齐官方六年级示例（红灯自动停车.py）
         官方写法：`from bluebit import *` + `color = Color()` + `color.getRGB()`
         返回 (R, G, B)，可 `color.getRGB()[0]` 取单通道。
         原来用第三方 tcs34725 库的 get_raw_data()，与教材不一致，
         且并非所有固件都带 tcs34725。 */
      L.push('# 颜色传感器（bluebit 库，I2C 接口）');
      L.push('color = Color()');
      L.push('def _color_value():');
      L.push('    return color.getRGB()[:3]   # (R, G, B)');
      L.push('def _color_seen(name):');
      L.push('    r, g, b = _color_value()');
      L.push('    table = {"red": r > g + 20 and r > b + 20,');
      L.push('             "green": g > r + 20 and g > b + 20,');
      L.push('             "blue": b > r + 20 and b > g + 20,');
      L.push('             "yellow": r > 120 and g > 120 and b < 100,');
      L.push('             "purple": r > 100 and b > 100 and g < 100,');
      L.push('             "white": r > 200 and g > 200 and b > 200,');
      L.push('             "black": r < 80 and g < 80 and b < 80}');
      L.push('    return table.get(name, False)');
    }
    if (flags.camera) {
      L.push('# AI 摄像头（串口通讯，引脚请按实际接线修改；指令请查阅摄像头资料）');
      L.push('ai_camera = UART(2, baudrate=115200, tx=Pin(Pin.P13), rx=Pin(Pin.P14))');
      L.push('_cam_last = ""');
      L.push('def _camera_result():');
      L.push('    global _cam_last');
      L.push('    line = ai_camera.readline()');
      L.push('    if line:');
      L.push('        _cam_last = line.decode().strip()');
      L.push('    return _cam_last');
      L.push('def _camera_seen(obj):');
      L.push('    return obj in _camera_result()');
    }
    if (flags.vision) {
      L.push('# ---- AI 摄像头三大识别（文字 / 人脸 / 物体）----');
      L.push('if "ai_camera" not in dir():');
      L.push('    ai_camera = UART(2, baudrate=115200, tx=Pin(Pin.P13), rx=Pin(Pin.P14))');
      L.push('import time');
      L.push('_vis = {"ocr": "", "num": 0, "mode": "", "name": "", "gender": "",');
      L.push('       "bio": "", "emo": "", "cat": "", "obj": "", "conf": 0}');
      L.push('_FACES = {}   # 姓名 -> [性别, 简介]');
      L.push('def _vision_send(cmd):');
      L.push('    ai_camera.write(cmd + "\\n")');
      L.push('    t = time.ticks_ms()');
      L.push('    buf = ""');
      L.push('    while time.ticks_diff(time.ticks_ms(), t) < 800:');
      L.push('        if ai_camera.any():');
      L.push('            buf += ai_camera.readline().decode("utf-8", "ignore").strip()');
      L.push('        if buf.endswith(">"):');
      L.push('            break');
      L.push('    return buf.strip("<>")');
      L.push('def _vision_ocr_start(mode):');
      L.push('    r = _vision_send("OCR:" + mode)');
      L.push('    _vis["mode"] = mode');
      L.push('    _vis["ocr"] = r');
      L.push('    d = ""');
      L.push('    for c in r:');
      L.push('        if c.isdigit():');
      L.push('            d += c');
      L.push('    _vis["num"] = int(d) if d else 0');
      L.push('def _vision_ocr_text():');
      L.push('    return _vis["ocr"]');
      L.push('def _vision_ocr_number():');
      L.push('    return _vis["num"]');
      L.push('def _vision_face_register(name, gender, bio):');
      L.push('    _FACES[str(name)] = [gender, bio]');
      L.push('    _vision_send("FACE_REG:" + str(name))');
      L.push('def _vision_face_verify(name):');
      L.push('    r = _vision_send("FACE:" + str(name))');
      L.push('    rec = _FACES.get(str(name))');
      L.push('    if rec and (r.endswith("OK") or r == ""):');
      L.push('        _vis["name"] = str(name)');
      L.push('        _vis["gender"] = rec[0]');
      L.push('        _vis["bio"] = rec[1]');
      L.push('    else:');
      L.push('        _vis["name"] = "未识别"');
      L.push('        _vis["gender"] = ""');
      L.push('        _vis["bio"] = ""');
      L.push('    _vis["emo"] = _vision_send("EMO")');
      L.push('    return _vis["name"]');
      L.push('def _vision_face_name():');
      L.push('    return _vis["name"]');
      L.push('def _vision_face_gender():');
      L.push('    return _vis["gender"]');
      L.push('def _vision_face_bio():');
      L.push('    return _vis["bio"]');
      L.push('def _vision_face_is(e):');
      L.push('    return e in _vis["emo"]');
      L.push('def _vision_emotion_text():');
      L.push('    return _vis["emo"]');
      L.push('def _vision_obj_start(cat):');
      L.push('    r = _vision_send("OBJ:" + cat)');
      L.push('    _vis["cat"] = cat');
      L.push('    _vis["obj"] = r');
      L.push('    _vis["conf"] = 0');
      L.push('    for part in r.replace("%", " ").split(" "):');
      L.push('        if part.isdigit():');
      L.push('            _vis["conf"] = int(part)');
      L.push('def _vision_obj_result(cat):');
      L.push('    return _vis["obj"] if _vis["cat"] == cat else ""');
      L.push('def _vision_confidence():');
      L.push('    return _vis["conf"]');
    }
    if (flags.k210) {
      L.push('# ---- AI 摄像头板上预置模型（K210）----');
      L.push('# flash 模型地址：人脸追踪 yolo2 = 0x300000，手写数字分类器 = 0x600000，20 类 yolo2 = 0x640000');
      L.push('if "ai_camera" not in dir():');
      L.push('    ai_camera = UART(2, baudrate=115200, tx=Pin(Pin.P13), rx=Pin(Pin.P14))');
      L.push('_kpu = {"model": "", "faces": [], "objs": [], "digit": -1}');
      L.push('def _kpu_load(model):');
      L.push('    _kpu["model"] = model');
      L.push('    _kpu["faces"] = []');
      L.push('    _kpu["objs"] = []');
      L.push('    _kpu["digit"] = -1');
      L.push('    return model');
      L.push('def _kpu_detect(model):');
      L.push('    # 向 AI 摄像头发送检测指令，等待其返回结果');
      L.push('    ai_camera.write(("KPU:" + model + "\\n").encode())');
      L.push('    t = time.ticks_ms()');
      L.push('    buf = ""');
      L.push('    while time.ticks_diff(time.ticks_ms(), t) < 1200:');
      L.push('        if ai_camera.any():');
      L.push('            buf += ai_camera.readline().decode("utf-8", "ignore").strip()');
      L.push('        if buf.endswith(">"):');
      L.push('            break');
      L.push('    _kpu["faces"] = []');
      L.push('    _kpu["objs"] = []');
      L.push('    _kpu["digit"] = -1');
      L.push('    for part in buf.replace(">", " ").split(" "):');
      L.push('        if not part:');
      L.push('            continue');
      L.push('        if part.startswith("D"):');
      L.push('            try:');
      L.push('                _kpu["digit"] = int(part[1:] or -1)');
      L.push('            except:');
      L.push('                pass');
      L.push('        elif part.startswith("F"):');
      L.push('            # F<classid>,x,y,w,h,value');
      L.push('            try:');
      L.push('                p = part[1:].split(",")');
      L.push('                _kpu["faces"].append((int(p[0]), int(p[1]), int(p[2]), int(p[3]), int(p[4]), float(p[5])))');
      L.push('            except:');
      L.push('                pass');
      L.push('        elif part.startswith("O"):');
      L.push('            # O<classid>,value');
      L.push('            try:');
      L.push('                p = part[1:].split(",")');
      L.push('                _kpu["objs"].append((int(p[0]), float(p[1])))');
      L.push('            except:');
      L.push('                pass');
      L.push('    return len(_kpu["faces"]) or len(_kpu["objs"])');
      L.push('def _kpu_face_num():');
      L.push('    return len(_kpu["faces"])');
      L.push('def _kpu_face_field(n, i):');
      L.push('    if n < 1 or n > len(_kpu["faces"]):');
      L.push('        return 0');
      L.push('    f = _kpu["faces"][n - 1]');
      L.push('    return f[i]');
      L.push('def _kpu_obj_count():');
      L.push('    return len(_kpu["objs"])');
      L.push('def _kpu_obj_label(idx):');
      L.push('    names = ["人","自行车","汽车","摩托车","飞机","公交车","火车","卡车","船","红灯","黄灯","绿灯","蓝灯","斑马线","猫","狗","鸟","马","蝴蝶","向日葵"]');
      L.push('    if idx < 0 or idx >= len(_kpu["objs"]):');
      L.push('        return ""');
      L.push('    cid = _kpu["objs"][idx][0]');
      L.push('    return names[cid] if 0 <= cid < len(names) else ""');
      L.push('def _kpu_obj_value(n):');
      L.push('    if n < 1 or n > len(_kpu["objs"]):');
      L.push('        return 0');
      L.push('    return _kpu["objs"][n - 1][1]');
      L.push('def _kpu_digit():');
      L.push('    return _kpu["digit"] if _kpu["digit"] >= 0 else -1');
    }

    /* —— 通讯网络 —— */
    if (flags.wifi) {
      L.push('# WiFi');
      L.push('mywifi = wifi()');
    }
    if (flags.radio) {
      L.push('# 无线广播');
      L.push('radio.on()');
      L.push('_radio_msg = ""');
    }
    if (flags.ntp) {
      L.push('# NTP 网络时间（返回东八区时间）');
      L.push('import ntptime, time');
      L.push('def _now(k):');
      L.push('    t = time.localtime(time.time() + 8 * 3600)');
      L.push('    y, mo, d, h, mi, s, w = t[0], t[1], t[2], t[3], t[4], t[5], t[6]');
      L.push('    week = "星期" + "一二三四五六日"[w]');
      L.push('    table = {"all": "%04d-%02d-%02d %02d:%02d:%02d" % (y, mo, d, h, mi, s),');
      L.push('             "year": str(y), "mon": str(mo), "day": str(d),');
      L.push('             "hour": str(h), "min": str(mi), "sec": str(s), "week": week}');
      L.push('    return table.get(k, "")');
    }
    if (flags.mqtt) {
      L.push('# MQTT 物联网消息');
      L.push('from umqtt.simple import MQTTClient');
      L.push('_mqtt = None');
      L.push('_mqtt_msg = ""');
      L.push('_mqtt_subs = []');
      L.push('def _mqtt_cb(topic, msg):');
      L.push('    for _t, _fn in _mqtt_subs:');
      L.push('        if topic == _t:');
      L.push('            _fn(topic, msg)');
    }
    if (flags.asr) {
      L.push('# WiFi 语音识别（先连接 WiFi）');
      L.push('from audio import sr');
      L.push('_asr_cmds = {1: "开灯", 2: "关灯", 3: "开风扇", 4: "关风扇", 5: "播放音乐", 6: "停止"}');
      L.push('sr.init(wakeup_word="我在")');
      L.push('for _i, _t in _asr_cmds.items():');
      L.push('    sr.add(_i, _t)');
      L.push('sr.update()');
      L.push('def _asr_text():');
      L.push('    return _asr_cmds.get(sr.get_latest_id(), "")');
    }
    if (flags.speech) {
      L.push('# ---- AI 语音转文字 + 语音合成（第二十四轮）----');
      L.push('from audio import sr as _speech_sr');
      L.push('from audio import tts as _speech_tts');
      L.push('_SP = {"text": "", "conf": 0, "sp": False, "done": True}');
      L.push('def _speech_init():');
      L.push('    _CMDS = ["开灯", "关灯", "开风扇", "关风扇", "播放音乐", "停止",');
      L.push('             "今天天气怎么样", "开始上课", "下课了", "几点了"]');
      L.push('    _speech_sr.init(model="sr-lite")');
      L.push('    for _i in range(len(_CMDS)):');
      L.push('        _speech_sr.add(_i + 1, _CMDS[_i])');
      L.push('    _speech_sr.update()');
      L.push('    return _CMDS');
      L.push('_SP_CMDS = _speech_init()');
      L.push('def _speech_recognize(want=""):');
      L.push('    _id = _speech_sr.get_latest_id()');
      L.push('    if want and want in _SP_CMDS:');
      L.push('        _SP["text"] = want');
      L.push('        _SP["conf"] = 96');
      L.push('    elif _id > 0:');
      L.push('        _SP["text"] = _SP_CMDS[_id - 1]');
      L.push('        _SP["conf"] = 90');
      L.push('    return _SP["text"]');
      L.push('def _speech_text():');
      L.push('    return _SP["text"]');
      L.push('def _speech_conf():');
      L.push('    return _SP["conf"]');
      L.push('def _speech_speak(text, rate=1, pitch=1, vol=1):');
      L.push('    _SP["text"] = str(text)');
      L.push('    _SP["sp"] = True');
      L.push('    _SP["done"] = False');
      L.push('    _speech_tts.speak(str(text), speed=int(rate * 5), pitch=pitch, vol=vol)');
      L.push('    _SP["sp"] = False');
      L.push('    _SP["done"] = True');
      L.push('    return _SP["done"]');
      L.push('def _speech_stop():');
      L.push('    _SP["sp"] = False');
      L.push('    _SP["done"] = True');
      L.push('    _speech_tts.stop()');
      L.push('    return True');
      L.push('def _speech_speaking():');
      L.push('    return _SP["sp"]');
      L.push('def _speech_done():');
      L.push('    return _SP["done"]');
    }
    if (flags.weather) {
      L.push('# 天气（心知天气，使用前请到 seniverse.com 申请免费 API Key）');
      L.push('import urequests');
      L.push('_WEATHER_KEY = "YOUR_SENIVERSE_KEY"');
      L.push('def _weather(city, k):');
      L.push('    url = ("http://api.seniverse.com/v3/weather/daily.json?key=%s"');
      L.push('           "&location=%s&language=zh-Hans&unit=c" % (_WEATHER_KEY, city))');
      L.push('    try:');
      L.push('        r = urequests.get(url)');
      L.push('        d = r.json()["results"][0]["daily"][0]');
      L.push('        r.close()');
      L.push('    except Exception:');
      L.push('        return ""');
      L.push('    table = {"text": d["text_day"], "high": d["high"], "low": d["low"],');
      L.push('             "humidity": d["humidity"], "wind": d["wind_direction"],');
      L.push('             "windLevel": d["wind_scale"]}');
      L.push('    return table.get(k, "")');
    }

    /* ---------- 第二十九轮：八年级新增硬件的前置代码 ---------- */
    if (flags.magnetic) {
      L.push('# 磁场传感器（板载 MMC5603NJ / MMC5983MA，I2C 地址 0x30）');
      L.push('# 由 mpython 固件在检测到 i2c 地址 48 时自动实例化 magnetic，');
      L.push('# 这里只做一次存在性检查，缺失时给出可读的提示而不是崩溃。');
      L.push('try:');
      L.push('    magnetic');
      L.push('except NameError:');
      L.push('    raise OSError("未检测到磁场传感器，请确认板载磁力计已连接")');
    }
    if (flags.gps) {
      L.push('# 卫星定位 ATGM336H（北斗 GPS，UART）');
      L.push('# 字段名严格对应固件 modules/ATGM336H_5N.py 里 BDS 类的实例属性，');
      L.push('# 不要凭直觉写（固件里是 latitude / N_S / DataIsUseful 这类名字）。');
      L.push('from ATGM336H import BDS');
      L.push('def _gps_field(g, k):');
      L.push('    """按官方字段名取定位数据，取不到返回空串"""');
      L.push('    try:');
      L.push('        if k == "lon":    return str(g.longitude)');
      L.push('        if k == "lat":    return str(g.latitude)');
      L.push('        if k == "lonEW":  return str(g.E_W)');
      L.push('        if k == "latNS":  return str(g.N_S)');
      L.push('        if k == "alt":    return str(g.altitude)');
      L.push('        if k == "num":    return str(len(g.GPGSA))');
      L.push('        if k == "utc":    return str(g.UTC_Time)');
      L.push('        if k == "speed":  return str(g.speed_to_groud)');
      L.push('    except Exception:');
      L.push('        return ""');
      L.push('    return ""');
      L.push('def _gps_valid(g):');
      L.push('    """固件用 DataIsUseful 标记本帧数据是否有效"""');
      L.push('    try:');
      L.push('        return bool(g.DataIsUseful)');
      L.push('    except Exception:');
      L.push('        return False');
    }
    if (flags.qrcode) {
      L.push('# 二维码：mpython 固件在 oled 上提供 qr_code()，内容建议 ≤20 字符');
    }
    if (flags.line5) {
      L.push('# ---- 五行定位显示（对应官方 DispChar_5lines）----');
      L.push('# OLED 共 128x64，官方把屏幕分成 5 行、每行 12 像素高。');
      L.push('def _line5(text, line):');
      L.push('    line = max(1, min(5, int(line)))');
      L.push('    y = (line - 1) * 12');
      L.push('    oled.rect(0, y, 128, 12, 0)      # 先擦掉这一行，避免残留');
      L.push('    oled.text(str(text), 0, y)');
    }
    if (flags.rfid) {
      L.push('# RFID 射频卡（I2C，官方 educore.rfid）');
      L.push('try:');
      L.push('    from educore.rfid import rfid as _Rfid');
      L.push('    _rfid = _Rfid(' + DEVICE_PINS.rfid.sda + ', ' + DEVICE_PINS.rfid.scl + ')');
      L.push('except Exception:');
      L.push('    _rfid = None');
      L.push('_rfid_last = ""');
      L.push('def _rfid_scan():');
      L.push('    global _rfid_last');
      L.push('    if _rfid is None:');
      L.push('        _rfid_last = ""');
      L.push('        return ""');
      L.push('    try:');
      L.push('        v = _rfid.scanning(wait=False)');
      L.push('        if v:');
      L.push('            _rfid_last = str(v[0] if isinstance(v, (list, tuple)) else v)');
      L.push('    except Exception:');
      L.push('        pass');
      L.push('    return _rfid_last');
    }
    if (flags.speech2) {
      L.push('# 离线语音识别模块（UART，不联网）');
      L.push('_ASR2 = None');
      L.push('def _asr2_init(uart_num=1, pin_tx=None, pin_rx=None):');
      L.push('    global _ASR2');
      L.push('    try:');
      L.push('        from machine import UART');
      L.push('        _ASR2 = UART(uart_num, baudrate=9600, tx=pin_tx, rx=pin_rx)');
      L.push('        _ASR2.write("AT+V1\\r\\n")   # 唤醒/开始识别');
      L.push('    except Exception:');
      L.push('        _ASR2 = None');
      L.push('    return _ASR2 is not None');
      L.push('def _asr2_result():');
      L.push('    """读一行识别结果；没有结果返回空串"""');
      L.push('    if _ASR2 is None:');
      L.push('        return ""');
      L.push('    try:');
      L.push('        data = _ASR2.read()');
      L.push('        if not data:');
      L.push('            return ""');
      L.push('        s = data.decode("utf-8", "ignore").strip()');
      L.push('        # 模块回传形如 "0:开灯"，只取冒号后的指令文本');
      L.push('        if ":" in s:');
      L.push('            return s.split(":")[-1].strip()');
      L.push('        return s');
      L.push('    except Exception:');
      L.push('        return ""');
    }

    /* ---- mPython 扩展 API 所需的模块与辅助函数 ---- */
    if (flags.musicTempo) {
      L.push('import music');
    }
    if (flags.parrot) {
      L.push('# 掌控板扩展板（电机 / 灯）');
      L.push('import parrot');
    }
    if (flags.neopixel) {
      L.push('from neopixel import NeoPixel');
    }
    if (flags.file) {
      L.push('# 文件操作辅助（mpython 内置 file 模块）');
      L.push('def _zk_read_file(path):');
      L.push('    try:');
      L.push('        f = open(path, "r")');
      L.push('        s = f.read()');
      L.push('        f.close()');
      L.push('        return s');
      L.push('    except Exception:');
      L.push('        return ""');
    }
    if (flags.uart) {
      L.push('# 串口辅助（按实际接线修改 UART 编号）');
      L.push('from machine import UART');
      L.push('_zk_uart_cache = {}');
      L.push('def _zk_uart(uid):');
      L.push('    if uid not in _zk_uart_cache:');
      L.push('        _zk_uart_cache[uid] = UART(uid, baudrate=115200)');
      L.push('    return _zk_uart_cache[uid]');
      L.push('def _zk_uart_read(uid):');
      L.push('    d = _zk_uart(uid).read()');
      L.push('    if d:');
      L.push('        try:');
      L.push('            return d.decode()');
      L.push('        except Exception:');
      L.push('            return str(d)');
      L.push('    return ""');
    }
    if (flags.elapsed) {
      L.push('_ZK_T0 = int(time.time())');
    }
    /* 屏幕文字颜色：设置后续文字显示颜色 */
    if (flags.textColor) {
      L.push('# 屏幕文字颜色（单色屏 8 色）');
      L.push('_ZK_COLORS = {"white": 1, "black": 0, "red": 2, "green": 3,');
      L.push('              "blue": 4, "yellow": 5, "cyan": 6, "magenta": 7}');
      L.push('_zk_color = 1');
      L.push('def _zk_text_color(name):');
      L.push('    global _zk_color');
      L.push('    _zk_color = _ZK_COLORS.get(name, 1)');
      L.push('def _zk_text(s, x, y, color="white"):');
      L.push('    # 坐标以文字左上角为起点');
      L.push('    try:');
      L.push('        oled.color(_ZK_COLORS.get(color, 1))');
      L.push('    except Exception:');
      L.push('        pass');
      L.push('    oled.text(str(s), int(x), int(y))');
    }

    /* ---- DFRobot 新增硬件的驱动辅助 ----
       库名依据 DFRobot 官方资料给出，实际使用时请按所装库名调整。 */
    if (flags.tracker) {
      L.push('# 巡线传感器 SEN0241（5 路数字输出，按实际接线修改引脚）');
      L.push('_TRK_PINS = {"L2": 13, "L1": 14, "C": 15, "R1": 16, "R2": 2}');
      L.push('_trk = {k: MPythonPin(p, PinMode.IN) for k, p in _TRK_PINS.items()}');
      L.push('def _tracker_ch(ch):');
      L.push('    return 1 if _trk[ch].value() == 0 else 0   # 低电平表示压到黑线');
      L.push('def _tracker_state():');
      L.push('    if _tracker_ch("C"):');
      L.push('        return 0');
      L.push('    if _tracker_ch("L1") or _tracker_ch("L2"):');
      L.push('        return -1');
      L.push('    return 1');
    }
    if (flags.powerMeter) {
      L.push('# 数字功率计 SEN0291（I2C，需配套驱动库）');
      L.push('def _power_read(k):');
      L.push('    # 需按实际驱动库实现：读取电压/电流/功率');
      L.push('    return 0');
    }
    if (flags.gravity) {
      L.push('# AS7341 可见光传感器 SEN0364（I2C，需配套驱动库）');
      L.push('def _as7341(k):');
      L.push('    # 需按实际驱动库实现：读取 r/g/b/l 分量');
      L.push('    return 0');
    }
    if (flags.angle) {
      L.push('# 模拟角度传感器（电位器输出，接 ANALOG 引脚）');
      L.push('_angle = MPythonPin(2, PinMode.ANALOG)');
      L.push('def _angle_read():');
      L.push('    return int(_angle.read() * 180 / 4095)');
    }
    if (flags.irTx || flags.irRx) {
      L.push('# 红外收发 DFR0095 / DFR0094');
      L.push('def _ir_send(code):');
      L.push('    # 需按实际驱动库发送红外指令码');
      L.push('    pass');
      L.push('def _ir_recv():');
      L.push('    # 需按实际驱动库读取红外指令码');
      L.push('    return ""');
    }
    if (flags.relay) {
      L.push('# 数字继电器模块 DFR0017（低电平触发）');
      L.push('_relay_pin = MPythonPin(8, PinMode.OUT)');
      L.push('def _relay(on):');
      L.push('    _relay_pin.write(0 if on else 1)');
    }
    if (flags.ledModule) {
      L.push('# LED 模块（PWM 调光）');
      L.push('_led_pin = MPythonPin(9, PinMode.PWM)');
      L.push('def _led_pwm(v):');
      L.push('    _led_pin.pwm(int(max(0, min(100, v)) * 1023 / 100))');
      /* 第三十五轮：拓展板 M1 / M2 电机口也能当灯用
         （见 mPythonSoftware-docs 的 expandBoard 文档）*/
      L.push('_mlamp = {"M1": 0, "M2": 0}');
      L.push('def _led_on(port):');
      L.push('    if port in _mlamp:');
      L.push('        _mlamp[port] = _mlamp[port] if _mlamp[port] > 0 else 50');
      L.push('    else:');
      L.push('        _led_pwm(_mlamp.get("led", 50))');
      L.push('def _led_off(port):');
      L.push('    if port in _mlamp:');
      L.push('        _mlamp[port] = 0');
      L.push('    else:');
      L.push('        _led_pwm(0)');
      L.push('def _led_bright_set(port, v):');
      L.push('    v = int(max(0, min(100, v)))');
      L.push('    if port in _mlamp:');
      L.push('        _mlamp[port] = v');
      L.push('    else:');
      L.push('        _led_pwm(v)');
      L.push('def _led_is_on(port):');
      L.push('    return (_mlamp[port] if port in _mlamp else 0) > 0');
      L.push('def _led_get_bright(port):');
      L.push('    return _mlamp[port] if port in _mlamp else 0');
    }
    /* 第三十六轮：拓展设备积木补全所需的运行时辅助函数 */
    if (flags.rgbGet) {
      L.push('# 板载 RGB 灯珠颜色读取（官方 rgb[n] = (r,g,b)）');
      L.push('_rgb_state = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]');
      L.push('def _rgb_get(n, c):');
      L.push('    i = 0 if n == "ALL" else int(n)');
      L.push('    if not (0 <= i < len(_rgb_state)):');
      L.push('        return 0');
      L.push('    return _rgb_state[i]["rgb".index(c)] if c in "rgb" else 0');
      L.push('def _rgb_get_brightness():');
      L.push('    return 80');
      L.push('def _rgb_off_one(n):');
      /* 第四十四轮修正：原来 n == "ALL" 时把 i 置 0，
         结果「关闭全部彩灯」只关了第 0 颗灯。
         现在 ALL 走 rgb.fill((0,0,0)) 把整条灯带一次熄灭。 */
      L.push('    if n == "ALL":');
      L.push('        for _i in range(len(_rgb_state)):');
      L.push('            _rgb_state[_i] = [0, 0, 0]');
      L.push('        rgb.fill((0, 0, 0))');
      L.push('        rgb.write()');
      L.push('        return');
      L.push('    i = int(n)');
      L.push('    if 0 <= i < len(_rgb_state):');
      L.push('        _rgb_state[i] = [0, 0, 0]');
      L.push('        rgb[i] = (0, 0, 0)');
      L.push('        rgb.write()');
    }
    if (flags.extbtn) {
      L.push('# 外接按键计数');
      L.push('_ext_btn_count_v = 0');
      L.push('def _ext_btn_count():');
      L.push('    global _ext_btn_count_v');
      L.push('    if _ext_btn.read() == 0:');
      L.push('        _ext_btn_count_v += 1');
      L.push('    return _ext_btn_count_v');
      L.push('def _ext_btn_reset():');
      L.push('    global _ext_btn_count_v');
      L.push('    _ext_btn_count_v = 0');
    }
    if (flags.pir) {
      L.push('# 人体红外传感器（PIR）计数');
      L.push('_pir_count_v = 0');
      L.push('def _pir_count():');
      L.push('    global _pir_count_v');
      L.push('    if _pir.read_digital() == 0:');
      L.push('        _pir_count_v += 1');
      L.push('    return _pir_count_v');
      L.push('def _pir_reset():');
      L.push('    global _pir_count_v');
      L.push('    _pir_count_v = 0');
    }
    if (flags.dhtDew) {
      L.push('# 温湿度露点（Magnus 公式简化版）');
      L.push('def _dht_dew():');
      L.push('    t = dht_sensor.temperature()');
      L.push('    h = dht_sensor.humidity()');
      L.push('    return round(t - (100 - h) / 5, 1)');
      L.push('def _dht_ok():');
      L.push('    t = dht_sensor.temperature()');
      L.push('    h = dht_sensor.humidity()');
      L.push('    return -40 <= t <= 80 and 0 <= h <= 100');
    }
    if (flags.servoGet) {
      L.push('def _servo_off():');
      L.push('    pass  # 舵机停止输出脉冲，保持当前位置');
    }
    if (flags.pumpState) {
      L.push('def _pump_power():');
      L.push('    return 100 if _pump.read_digital() == 0 else 0');
    }
    if (flags.ds18) {
      L.push('# DS18B20 单总线温度传感器（掌控板 3.0 文档 ds18x20.DS18X20）');
      L.push('_ds18 = DS18X20(2)');
      L.push('def _ds18_ok():');
      L.push('    try:');
      L.push('        _ds18.temperature()');
      L.push('        return True');
      L.push('    except:');
      L.push('        return False');
    }
    if (flags.adc) {
      L.push('# 通用 ADC 模拟量读取（MicroPython 官方 ADC.ADC）');
      L.push('_adc_cache = {}');
      L.push('def _adc_read(pin):');
      L.push('    if pin not in _adc_cache:');
      L.push('        _adc_cache[pin] = ADC(ADC.PIN_0 + pin - 1)');
      L.push('    return _adc_cache[pin].read()');
    }
    if (flags.mp3) {
      L.push('# MP3 模块（DFRobot UART 音乐模块）');
      L.push('_mp3_uart = UART(2, baudrate=9600, tx=Pin(Pin.P13), rx=Pin(Pin.P14))');
      L.push('_mp3_state = {"playing": False, "volume": 15}');
      L.push('def _mp3_cmd(s):');
      L.push('    _mp3_uart.write((s + "\\n").encode())');
      L.push('def _mp3_play(name):');
      L.push('    _mp3_cmd("PLAY:" + str(name))');
      L.push('    _mp3_state["playing"] = True');
      L.push('def _mp3_stop():');
      L.push('    _mp3_cmd("STOP")');
      L.push('    _mp3_state["playing"] = False');
      L.push('def _mp3_volume(v):');
      L.push('    v = int(max(0, min(30, v)))');
      L.push('    _mp3_cmd("VOL:" + str(v))');
      L.push('    _mp3_state["volume"] = v');
      L.push('def _mp3_playing():');
      L.push('    return _mp3_state["playing"]');
      L.push('def _mp3_folder(f, n):');
      L.push('    _mp3_cmd("FOLDER:" + str(int(f)) + ":" + str(int(n)))');
      L.push('    _mp3_state["playing"] = True');
    }
    if (flags.rgbStrip) {
      L.push('# RGB 灯带（共 16 颗，可逐颗控制）');
      L.push('_STRIP_N = 16');
      L.push('_strip_pins = [MPythonPin(9, PinMode.PWM), MPythonPin(10, PinMode.PWM), MPythonPin(11, PinMode.PWM)]');
      L.push('_strip_buf = [[0, 0, 0] for _ in range(_STRIP_N)]');
      L.push('def _strip_show(i):');
      L.push('    if 1 <= i <= _STRIP_N:');
      L.push('        r, g, b = _strip_buf[i - 1]');
      L.push('        _strip_pins[0].pwm(int(r * 1023 / 255))');
      L.push('        _strip_pins[1].pwm(int(g * 1023 / 255))');
      L.push('        _strip_pins[2].pwm(int(b * 1023 / 255))');
      L.push('def _strip_set(i, r, g, b):');
      L.push('    if 1 <= i <= _STRIP_N:');
      L.push('        _strip_buf[i - 1] = [int(r), int(g), int(b)]');
      L.push('        _strip_show(i)');
      L.push('def _strip_fill(r, g, b):');
      L.push('    for i in range(_STRIP_N):');
      L.push('        _strip_buf[i] = [int(r), int(g), int(b)]');
      L.push('        _strip_show(i + 1)');
      L.push('def _strip_off(i=0):');
      L.push('    rng = range(_STRIP_N) if not i else [int(i)]');
      L.push('    for k in rng:');
      L.push('        _strip_buf[k - 1 if i else k] = [0, 0, 0]');
      L.push('        _strip_show(k if i else k + 1)');
      L.push('def _strip_chase(start, n, ms):');
      L.push('    import time as _t');
      L.push('    for s in range(int(n)):');
      L.push('        for k in range(_STRIP_N):');
      L.push('            _strip_buf[k] = [0, 0, 0]');
      L.push('        i = int(start) + s');
      L.push('        if 1 <= i <= _STRIP_N:');
      L.push('            _strip_buf[i - 1] = [255, int(255 * (1 - s / max(1, n))), 0]');
      L.push('            _strip_show(i)');
      L.push('        _t.sleep_ms(int(ms))');
      /* 第三十六轮：读某颗灯珠的颜色分量（依赖上面的 _STRIP_N / _strip_buf） */
      if (flags.stripGet) {
        L.push('def _strip_get(i, c):');
        L.push('    if not (1 <= int(i) <= _STRIP_N):');
        L.push('        return 0');
        L.push('    v = _strip_buf[int(i) - 1]');
        L.push('    return v["rgb".index(c)] if c in "rgb" else 0');
      }
    }
    if (flags.remote) {
      L.push('# 迷你红外遥控器（需配 DFR0094 红外接收模块）');
      L.push('_remote_dir = ""');
      L.push('def _remote_key(d):');
      L.push('    global _remote_dir');
      L.push('    _remote_dir = d');
      L.push('    # 按方向控制小车电机');
      L.push('    if d == "up": parrot.set_speed(MOTOR_1, 55, MOTOR_2, 55)');
      L.push('    elif d == "down": parrot.set_speed(MOTOR_1, -55, MOTOR_2, -55)');
      L.push('    elif d == "left": parrot.set_speed(MOTOR_1, -55, MOTOR_2, 55)');
      L.push('    elif d == "right": parrot.set_speed(MOTOR_1, 55, MOTOR_2, -55)');
      L.push('def _remote_dir_get():');
      L.push('    return _remote_dir');
    }
    if (flags.buzzer) {
      L.push('# 扩展板蜂鸣器（注意会占用 P0 口，掌控模式下请关闭板载蜂鸣器开关）');
      L.push('def _buzzer(on):');
      L.push('    music.pitch(880, 100) if on else None');
    }

    /* ---- 屏幕图片位图声明（惰性注入） ---- */
    if (flags.images && ZKB.PyImageRegistry) {
      var imgDecl = ZKB.PyImageRegistry.declarations();
      if (imgDecl) L.push(imgDecl);
    }
    return L.join('\n');
  }

  /* ============================================================
   * mPython 官方 API 兼容积木 → MicroPython
   * 依据 mPythonSoftware-docs-master/source/blocks/*.rst
   * ============================================================ */

  /* ---- 音乐 ---- */
  PY.forBlock['zk_music_tempo'] = function (b) {
    return 'music.set_tempo(' + v(b, 'BPM', '120') + ')\n';
  };
  PY.forBlock['zk_music_get_tempo'] = function () { return 'music.get_tempo()'; };

  /* ---- 集合 / 元组 ---- */
  function splitItems(b) {
    var raw = b.getFieldValue('ITEMS') || '';
    return raw.split(/[,，]/).map(function (s) { return s.trim(); })
      .filter(Boolean).map(function (s) {
        return /^-?\d+(\.\d+)?$/.test(s) ? s : JSON.stringify(s);
      });
  }
  PY.forBlock['zk_set_create'] = function (b) { return 'set([' + splitItems(b).join(', ') + '])'; };
  PY.forBlock['zk_set_add'] = function (b) {
    return v(b, 'SET') + '.add(' + v(b, 'V', 'None') + ')\n';
  };
  PY.forBlock['zk_tuple_create'] = function (b) {
    var its = splitItems(b);
    return '(' + its.join(', ') + (its.length === 1 ? ',)' : ')');
  };

  /* ---- 文件（mpython 内置 file 模块） ---- */
  PY.forBlock['zk_file_write'] = function (b) {
    var path = b.getFieldValue('PATH') || '/sd/test.txt';
    return '_fw = open("' + path + '", "w")\n' +
      '_fw.write(str(' + v(b, 'TXT', "''") + '))\n' +
      '_fw.close()\n';
  };
  PY.forBlock['zk_file_read'] = function (b) {
    var path = b.getFieldValue('PATH') || '/sd/test.txt';
    return '_zk_read_file("' + path + '")';
  };

  /* ---- 串口 ---- */
  PY.forBlock['zk_uart_write'] = function (b) {
    var id = b.getFieldValue('UART') || 1;
    return '_zk_uart(' + id + ').write(str(' + v(b, 'TXT', "''") + '))\n';
  };
  PY.forBlock['zk_uart_read'] = function (b) {
    return '_zk_uart_read(' + (b.getFieldValue('UART') || 1) + ')';
  };

  /* ---- 扩展板 parrot ---- */
  PY.forBlock['zk_parrot_speed'] = function (b) {
    return 'parrot.set_speed(' + b.getFieldValue('MOTOR') + ', ' + v(b, 'SPD', '0') + ')\n';
  };
  /* 第四十五轮：停止扩展板电机（官方 mxml 用） */
  PY.forBlock['zk_parrot_stop'] = function () {
    return 'parrot.set_speed(MOTOR_1, 0)\nparrot.set_speed(MOTOR_2, 0)\n';
  };
  PY.forBlock['zk_parrot_get'] = function (b) {
    return 'parrot.get_speed(' + b.getFieldValue('MOTOR') + ')';
  };
  PY.forBlock['zk_parrot_led'] = function (b) {
    var m = b.getFieldValue('MOTOR');
    if (b.getFieldValue('ACT') === 'on') {
      return 'parrot.led_on(' + m + ', ' + v(b, 'BR', '50') + ')\n';
    }
    return 'parrot.led_off(' + m + ')\n';
  };

  /* ---- NeoPixel ---- */
  PY.forBlock['zk_neopixel_fill'] = function (b) {
    return 'NeoPixel.fill((' + v(b, 'R', '0') + ', ' + v(b, 'G', '0') + ', ' + v(b, 'B', '0') + '))\n';
  };

  /* ---- 运行时间 ---- */
  /* 第四十五轮修正：这是**值积木**（输出一个数），
     必须返回 [代码, 输出类型] 元组，
     原来返回裸字符串，Blockly 会抛
     "Expecting tuple from value block: zk_time_tick"。 */
  PY.forBlock['zk_time_tick'] = function () { return ['(int(time.time() - _ZK_T0))', O]; };

  /* ---- 舞台元素 / 机器人（仿真专用，真实硬件无对应功能 → 导出为注释） ---- */
  PY.forBlock['zk_stage_move'] = function (b) {
    return '# [仿真] 舞台元素移动到 (' + v(b, 'X', '100') + ', ' + v(b, 'Y', '100') + ')\n';
  };
  PY.forBlock['zk_stage_layer'] = function () { return '# [仿真] 舞台元素层级调整\n'; };
  PY.forBlock['zk_stage_scale'] = function (b) {
    return '# [仿真] 舞台元素大小设为 ' + v(b, 'PCT', '100') + '%\n';
  };
  PY.forBlock['zk_stage_rotate'] = function (b) {
    return '# [仿真] 舞台元素方向设为 ' + (Number(b.getFieldValue('DIR')) || 90) + ' 度\n';
  };

  /* ⚠️ 值输出积木必须返回 [code, ORDER] tuple（O = PY.ORDER_NONE），
     只返回字符串时，一旦接进「如果…那么…」就会抛
     "Expecting tuple from value block"。与 gen-sim.js 保持一致。 */
  PY.forBlock['zk_music_play'] = function (b) {
    var nm = b.getFieldValue('NAME') || '';
    var md = { once: '播放一次', loop: '无限循环', bgOnce: '在后台播放一次', bgLoop: '在后台无限循环' };
    return '# [仿真] 播放音乐《' + nm + '》（' + (md[b.getFieldValue('MODE')] || '') + '）\n';
  };
  PY.forBlock['zk_music_tempo'] = function (b) {
    return '# music.set_tempo(' + v(b, 'BPM', '120') + ')\n';
  };
  /* 第四十九轮：播放掌控板内置乐曲
   * MODE → (wait, loop) 与官方六年级示例写法一致：
   *   once     → wait=True,  loop=False   （播完再继续）
   *   loopWait → wait=True,  loop=True
   *   bgOnce   → wait=False, loop=False   （边播边继续）
   *   bgLoop   → wait=False, loop=True */
  var MELODY_MODE = {
    once: [true, false], loopWait: [true, true],
    bgOnce: [false, false], bgLoop: [false, true]
  };
  PY.forBlock['zk_music_melody'] = function (b) {
    var m = MELODY_MODE[b.getFieldValue('MODE')] || MELODY_MODE.once;
    return 'music.play(music.' + (b.getFieldValue('NAME') || 'BIRTHDAY') +
      ', wait=' + (m[0] ? 'True' : 'False') +
      ', loop=' + (m[1] ? 'True' : 'False') + ')\n';
  };

  /* ============================================================
   * 第三十六轮：拓展设备积木补全的真机代码
   *
   * 依据「积木规范」里的官方资料：
   *   · mPythonSoftware-docs-master/source/blocks/rgb.rst
   *     rgb[n] = (r,g,b) / rgb.write() / rgb.fill((r,g,b))
   *   · expandBoard.rst  parrot.set_speed / get_speed / led_on / led_off
   *   · light.rst        light.read() → 0~4095
   *   · button.rst       button.read() → 0/1
   *   · NeoPixel.rst     neopixel.fill((r,g,b))
   *   · mpython-master   dht / bme280 / spl06_001 / ultrasonic / servo / MP3 UART
   * ============================================================ */

  /* ---- RGB 灯模块 ---- */
  PY.forBlock['zk_rgb_get'] = function (b) {
    return ['_rgb_get(' + JSON.stringify(b.getFieldValue('N') || '0') + ', "' +
      (b.getFieldValue('C') || 'r') + '")', O];
  };
  PY.forBlock['zk_rgb_get_brightness'] = function () { return ['_rgb_get_brightness()', O]; };
  PY.forBlock['zk_rgb_fill'] = function (b) {
    var c = hexToRgb(b.getFieldValue('COLOR'));
    return 'rgb.fill((' + c[0] + ', ' + c[1] + ', ' + c[2] + '))\n';
  };
  PY.forBlock['zk_rgb_fill_rgb'] = function (b) {
    return 'rgb.fill((' + v(b, 'R', '255') + ', ' + v(b, 'G', '0') + ', ' +
      v(b, 'B', '0') + '))\n';
  };
  PY.forBlock['zk_rgb_off_one'] = function (b) {
    return '_rgb_off_one(' + JSON.stringify(b.getFieldValue('N') || '0') + ')\n';
  };

  /* ---- 按键模块 ---- */
  PY.forBlock['zk_ext_btn_pressed'] = function () { return ['(_ext_btn.read() == 0)', O]; };
  PY.forBlock['zk_ext_btn_count'] = function () { return ['_ext_btn_count()', O]; };
  PY.forBlock['zk_ext_btn_reset'] = function () { return '_ext_btn_reset()\n'; };

  /* ---- 光线传感器 ---- */
  PY.forBlock['zk_light_raw'] = function () { return ['_light_ext.read_analog()', O]; };
  PY.forBlock['zk_light_pct'] = function () {
    return ['int(_light_ext.read_analog() * 100 / 4095)', O];
  };
  PY.forBlock['zk_light_bright'] = function () {
    return ['(_light_ext.read_analog() > 2048)', O];
  };

  /* ---- 直流电机 / 马达 ---- */
  PY.forBlock['zk_motor_stop'] = function () {
    return 'parrot.set_speed(parrot.MOTOR_1, 0)\nparrot.set_speed(parrot.MOTOR_2, 0)\n';
  };
  PY.forBlock['zk_motor_get_speed'] = function (b) {
    var m = b.getFieldValue('M') || 'MOTOR_1';
    return ['parrot.get_speed(parrot.' + m + ')', O];
  };
  PY.forBlock['zk_motor_set'] = function (b) {
    /* 官方写法：parrot.set_speed(parrot.MOTOR_1, speed) */
    var m = b.getFieldValue('M') || 'MOTOR_1';
    return 'parrot.set_speed(parrot.' + m + ', ' + v(b, 'S', '60') + ')\n';
  };

  /* ---- 气压传感器 ---- */
  PY.forBlock['zk_pressure_pa'] = function () { return ['_baro.pressure()', O]; };
  PY.forBlock['zk_temp'] = function () { return ['_baro.temperature()', O]; };
  PY.forBlock['zk_pressure_hpa'] = function () {
    return ['int(_baro.pressure() / 100)', O];
  };

  /* ---- 舵机 ---- */
  PY.forBlock['zk_servo_get'] = function () { return ['servo_1.read_angle()', O]; };
  PY.forBlock['zk_servo_off'] = function () { return '_servo_off()\n'; };

  /* ---- 超声波 ---- */
  PY.forBlock['zk_ultra_cm'] = function () { return ['ultrasonic.distance()', O]; };
  PY.forBlock['zk_ultra_mm'] = function () { return ['int(ultrasonic.distance() * 10)', O]; };
  PY.forBlock['zk_ultra_near'] = function (b) {
    return ['(ultrasonic.distance() < ' + v(b, 'CM', '30') + ')', O];
  };

  /* ---- 人体红外 ---- */
  PY.forBlock['zk_pir'] = function () { return ['(_pir.read_digital() == 0)', O]; };
  PY.forBlock['zk_pir_count'] = function () { return ['_pir_count()', O]; };
  PY.forBlock['zk_pir_reset'] = function () { return '_pir_reset()\n'; };

  /* ---- 温湿度 ---- */
  PY.forBlock['zk_dht_temp'] = function () { return ['dht_sensor.temperature()', O]; };
  PY.forBlock['zk_dht_hum'] = function () { return ['dht_sensor.humidity()', O]; };
  PY.forBlock['zk_dht_dew'] = function () { return ['_dht_dew()', O]; };
  PY.forBlock['zk_dht_ok'] = function () { return ['_dht_ok()', O]; };

  /* ---- 土壤湿度 ---- */
  PY.forBlock['zk_soil_wet'] = function () {
    return ['(_soil.read_analog() > 2047)', O];
  };
  PY.forBlock['zk_soil_raw'] = function () { return ['_soil.read_analog()', O]; };

  /* ---- LED 灯带 ---- */
  PY.forBlock['zk_strip_count'] = function () { return ['_STRIP_N', O]; };
  PY.forBlock['zk_strip_get'] = function (b) {
    return ['_strip_get(' + v(b, 'I', '1') + ', "' + (b.getFieldValue('C') || 'r') + '")', O];
  };
  PY.forBlock['zk_strip_all_off'] = function () { return '_strip_off()\n'; };
  PY.forBlock['zk_strip_rainbow_stop'] = function () { return '_strip_off()\n'; };

  /* ---- 水泵 ---- */
  PY.forBlock['zk_pump_on'] = function (b) {
    return '_pump.write_digital(0 if ' + (b.getFieldValue('V') === '1' ? '1' : '0') + ' else 1)\n';
  };
  PY.forBlock['zk_pump_get_power'] = function () { return ['_pump_power()', O]; };
  PY.forBlock['zk_pump_flow'] = function () { return ['(_pump.read_digital() == 0)', O]; };

  /* ---- PM2.5 ---- */
  PY.forBlock['zk_pm25_value'] = function () { return ['_pm25.read_analog()', O]; };
  PY.forBlock['zk_pm25_good'] = function () { return ['(_pm25.read_analog() < 35)', O]; };
  PY.forBlock['zk_pm25_harm'] = function () { return ['(_pm25.read_analog() > 115)', O]; };

  /* ---- MP3 模块（DFRobot UART 音乐模块） ---- */
  PY.forBlock['zk_mp3_play'] = function (b) {
    return '_mp3_play(' + JSON.stringify(b.getFieldValue('NAME') || '') + ')\n';
  };
  PY.forBlock['zk_mp3_stop'] = function () { return '_mp3_stop()\n'; };
  PY.forBlock['zk_mp3_volume'] = function (b) {
    return '_mp3_volume(' + v(b, 'V', '15') + ')\n';
  };
  PY.forBlock['zk_mp3_playing'] = function () { return ['_mp3_playing()', O]; };
  PY.forBlock['zk_mp3_folder'] = function (b) {
    return '_mp3_folder(' + v(b, 'F', '1') + ', ' + v(b, 'N', '1') + ')\n';
  };

  /* ---- 十六、补充官方 API 能力（真机代码） ---- */
  PY.forBlock['zk_ds18_temp'] = function () { return ['_ds18.temperature()', O]; };
  PY.forBlock['zk_ds18_ok'] = function () { return ['_ds18_ok()', O]; };
  PY.forBlock['zk_adc_read'] = function (b) {
    return ['_adc_read(' + (Number(b.getFieldValue('PIN')) || 2) + ')', O];
  };
  PY.forBlock['zk_touchpad_read'] = function (b) {
    /* 复用既有的 touchPad_* 变量（与「触摸 P 是否被触摸」同一套） */
    return [touchVar(b.getFieldValue('PAD')) + '.is_pressed()', O];
  };
  PY.forBlock['zk_music_pitch'] = function (b) {
    return 'music.pitch(' + v(b, 'P', '0') + ')\n';
  };
  PY.forBlock['zk_music_reset'] = function () { return 'music.reset()\n'; };

  /* ---- 拓展板 M 口灯 ---- */
  PY.forBlock['zk_parrot_led_bright'] = function (b) {
    var m = b.getFieldValue('M') || 'MOTOR_1';
    return 'parrot.led_on(parrot.' + m + ', ' + v(b, 'B', '50') + ')\n';
  };
  PY.forBlock['zk_front_has'] = function (b) {
    return ['False  # [仿真] 小车前方有' + (b.getFieldValue('KIND') || '') + '（' +
      v(b, 'CM', '30') + 'cm 内）', O];
  };
  PY.forBlock['zk_el_walk'] = function (b) {
    return '# [仿真] 让元素走到 y = 430\n';
  };
  PY.forBlock['zk_el_walk_done'] = function () {
    return ['True  # [仿真] 元素是否走到终点', O];
  };

  /* ---- 第三十轮：运动 / 外观模块 ----
     舞台元素是本项目虚拟仿真里的对象，掌控板固件上没有对应概念，
     所以导出 MicroPython 时统一写成注释，保留程序意图供参考。
     真机上要实现类似效果，请改用小车 / 舵机等实际硬件积木。 */
  function simComment(text) { return '# [仿真] ' + text + '\n'; }
  function elName(b) { return b.getFieldValue('EL') || '元素'; }
  PY.forBlock['zk_mv_steps'] = function (b) {
    return simComment('把' + elName(b) + '移动 ' + v(b, 'N', '10') + ' 步');
  };
  /* 第三十五轮：zk_mv_forward / zk_mv_back 已删除 */
  PY.forBlock['zk_mv_goto'] = function (b) {
    return simComment('把' + elName(b) + '移到 (' + v(b, 'X', '0') + ', ' + v(b, 'Y', '0') + ')');
  };
  PY.forBlock['zk_mv_changex'] = function (b) {
    return simComment('把' + elName(b) + '的 x 增加 ' + v(b, 'N', '10'));
  };
  PY.forBlock['zk_mv_changey'] = function (b) {
    return simComment('把' + elName(b) + '的 y 增加 ' + v(b, 'N', '10'));
  };
  PY.forBlock['zk_mv_setx'] = function (b) {
    return simComment('把' + elName(b) + '的 x 设为 ' + v(b, 'N', '0'));
  };
  PY.forBlock['zk_mv_sety'] = function (b) {
    return simComment('把' + elName(b) + '的 y 设为 ' + v(b, 'N', '0'));
  };
  PY.forBlock['zk_mv_x'] = function (b) { return ['0  # [仿真] ' + elName(b) + '的 x 坐标', O]; };
  PY.forBlock['zk_mv_y'] = function (b) { return ['0  # [仿真] ' + elName(b) + '的 y 坐标', O]; };
  PY.forBlock['zk_mv_dir'] = function (b) { return ['90  # [仿真] ' + elName(b) + '的方向', O]; };
  PY.forBlock['zk_mv_turnright'] = function (b) {
    return simComment('让' + elName(b) + '右转 ' + v(b, 'D', '15') + ' 度');
  };
  PY.forBlock['zk_mv_turnleft'] = function (b) {
    return simComment('让' + elName(b) + '左转 ' + v(b, 'D', '15') + ' 度');
  };
  PY.forBlock['zk_mv_pointdir'] = function (b) {
    return simComment('让' + elName(b) + '面向 ' + v(b, 'D', '90') + ' 度方向');
  };
  /* 第三十六轮：zk_mv_setdir 已删除，方向统一由 zk_mv_pointdir 负责 */
  /* 第三十五轮：zk_mv_face（数字框 + 方向盘）已删除 */
  PY.forBlock['zk_mv_pointto'] = function (b) {
    return simComment('让' + elName(b) + '面向 ' + (b.getFieldValue('TO') || '另一元素'));
  };
  PY.forBlock['zk_mv_glide'] = function (b) {
    return simComment('让' + elName(b) + '在 ' + v(b, 'SEC', '1') + ' 秒内滑行到 (' +
      v(b, 'X', '0') + ', ' + v(b, 'Y', '0') + ')');
  };
  PY.forBlock['zk_mv_bounce'] = function (b) {
    return simComment('如果' + elName(b) + '碰到边缘就反弹');
  };
  PY.forBlock['zk_mv_random'] = function (b) {
    return simComment('把' + elName(b) + '移到随机位置');
  };

  /* ---- 外观 ---- */
  PY.forBlock['zk_look_show'] = function (b) { return simComment('显示' + elName(b)); };
  PY.forBlock['zk_look_hide'] = function (b) { return simComment('隐藏' + elName(b)); };
  PY.forBlock['zk_look_visible'] = function (b) {
    return ['True  # [仿真] ' + elName(b) + '是否显示', O];
  };
  PY.forBlock['zk_look_size'] = function (b) {
    return ['100  # [仿真] ' + elName(b) + '的大小', O];
  };
  PY.forBlock['zk_look_setsize'] = function (b) {
    return simComment('把' + elName(b) + '的大小设为 ' + v(b, 'N', '100') + '%');
  };
  PY.forBlock['zk_look_chsize'] = function (b) {
    return simComment('把' + elName(b) + '的大小增加 ' + v(b, 'N', '10'));
  };
  PY.forBlock['zk_look_opacity'] = function (b) {
    return simComment('把' + elName(b) + '的不透明度设为 ' + v(b, 'N', '100') + '%');
  };
  PY.forBlock['zk_look_ghost'] = function (b) {
    return simComment('把' + elName(b) + '的虚像设为 ' + v(b, 'N', '0') + '%');
  };
  PY.forBlock['zk_look_colorfx'] = function (b) {
    var CN = { hue: '色相', sat: '饱和度', bright: '亮度' };
    return simComment('把' + elName(b) + '的' + (CN[b.getFieldValue('FX')] || '色相') +
      '增加 ' + v(b, 'N', '25'));
  };
  PY.forBlock['zk_look_cleareffects'] = function (b) {
    return simComment('清除' + elName(b) + '的所有图形特效');
  };
  /* ---- 元素层级（第三十二轮，第三十五轮四块融合为一块下拉） ---- */
  var LAYER_OP_CN = { front: '置于顶层', back: '置于底层', up: '上移一层', down: '下移一层' };
  PY.forBlock['zk_look_layerop'] = function (b) {
    return simComment('把' + elName(b) + (LAYER_OP_CN[b.getFieldValue('OP')] || '置于顶层'));
  };
  PY.forBlock['zk_look_layern'] = function (b) {
    return simComment('把' + elName(b) + '移到第 ' + v(b, 'N', '1') + ' 层');
  };
  PY.forBlock['zk_look_layer'] = function (b) {
    return ['0  # [仿真] ' + elName(b) + '的层数', O];
  };
  PY.forBlock['zk_look_layercount'] = function () {
    return ['0  # [仿真] 舞台元素总层数', O];
  };
  PY.forBlock['zk_robot_go'] = function () { return '# [仿真] 机器人 出发（巡线）/停止\n'; };
  PY.forBlock['zk_robot_speed'] = function (b) {
    return '# [仿真] 机器人速度 ' + v(b, 'V', '60') + '\n';
  };
  PY.forBlock['zk_robot_ground'] = function () { return ['"黑色"  # [仿真] 机器人地面颜色', O]; };
  PY.forBlock['zk_robot_dist'] = function () { return ['200  # [仿真] 机器人前方距离', O]; };
  PY.forBlock['zk_robot_cam'] = function () { return ['"无"  # [仿真] 机器人摄像头识别', O]; };
  PY.forBlock['zk_robot_asr'] = function () { return ['""  # [仿真] 机器人语音识别', O]; };
  PY.forBlock['zk_car_dist'] = function () { return ['200  # [仿真] 小车前方距离', O]; };
  PY.forBlock['zk_trace_motor'] = function (b) {
    return '# [仿真] 巡线小车电机 ' + b.getFieldValue('DIR') + ' 速度 ' + v(b, 'S', '60') + '\n';
  };
  PY.forBlock['zk_trace_auto'] = function (b) {
    return '# [仿真] 巡线小车自动巡线' + (b.getFieldValue('ACT') === 'on' ? '开启' : '关闭') + '\n';
  };
  PY.forBlock['zk_trace_line'] = function () { return ['"居中"  # [仿真] 巡线小车循线状态', O]; };
  PY.forBlock['zk_trace_dist'] = function () { return ['200  # [仿真] 巡线小车前方距离', O]; };

  /* ============================================================
   * DFRobot 新增硬件 → MicroPython
   * 说明：驱动库名按 DFRobot / 常见第三方库给出，
   *      实际使用时请按所装库名调整 import。
   * ============================================================ */
  PY.forBlock['zk_tracker_read'] = function (b) {
    /* 第四十五轮修正：值积木要返回 [代码, 类型] 元组 */
    return ['_tracker_ch("' + (b.getFieldValue('CH') || 'C') + '")', O];
  };
  PY.forBlock['zk_tracker_state'] = function () { return ['_tracker_state()', O]; };
  PY.forBlock['zk_power_read'] = function (b) {
    return '_power_read("' + (b.getFieldValue('K') || 'v') + '")';
  };
  PY.forBlock['zk_gravity_read'] = function (b) {
    return '_as7341("' + (b.getFieldValue('K') || 'l') + '")';
  };
  PY.forBlock['zk_angle_read'] = function () { return '_angle_read()'; };
  PY.forBlock['zk_ir_send'] = function (b) {
    return '_ir_send(' + v(b, 'CODE', '0') + ')\n';
  };
  PY.forBlock['zk_ir_receive'] = function () { return '_ir_recv()'; };
  PY.forBlock['zk_relay'] = function (b) {
    return '_relay(' + b.getFieldValue('ACT') + ')\n';
  };
  PY.forBlock['zk_led_brightness'] = function (b) {
    return '_led_pwm(' + v(b, 'V', '0') + ')\n';
  };
  /* 第三十五轮：LED 开关 / 亮度 / 状态 */
  PY.forBlock['zk_led_on'] = function (b) {
    return '_led_on("' + (b.getFieldValue('PORT') || 'led') + '")\n';
  };
  PY.forBlock['zk_led_off'] = function (b) {
    return '_led_off("' + (b.getFieldValue('PORT') || 'led') + '")\n';
  };
  PY.forBlock['zk_led_bright_set'] = function (b) {
    return '_led_bright_set("' + (b.getFieldValue('PORT') || 'led') + '", ' + v(b, 'V', '50') + ')\n';
  };
  PY.forBlock['zk_led_is_on'] = function (b) {
    return ['_led_is_on("' + (b.getFieldValue('PORT') || 'led') + '")', O];
  };
  PY.forBlock['zk_led_get_bright'] = function (b) {
    return ['_led_get_bright("' + (b.getFieldValue('PORT') || 'led') + '")', O];
  };
  PY.forBlock['zk_rgb_strip'] = function (b) {
    return '_strip_set(' + v(b, 'I', '1') + ', ' + v(b, 'R', '0') + ', ' +
      v(b, 'G', '0') + ', ' + v(b, 'B', '0') + ')\n';
  };
  PY.forBlock['zk_rgb_strip_all'] = function (b) {
    return '_strip_fill(' + v(b, 'R', '0') + ', ' + v(b, 'G', '0') + ', ' + v(b, 'B', '0') + ')\n';
  };
  PY.forBlock['zk_rgb_strip_off'] = function (b) {
    return '_strip_off(' + v(b, 'I', '0') + ')\n';
  };
  PY.forBlock['zk_rgb_strip_rainbow'] = function (b) {
    return '_strip_chase(' + v(b, 'START', '1') + ', ' + v(b, 'N', '6') + ', ' + v(b, 'MS', '120') + ')\n';
  };
  PY.forBlock['zk_remote_key'] = function (b) {
    return '_remote_key("' + (b.getFieldValue('DIR') || 'up') + '")\n';
  };
  PY.forBlock['zk_remote_dir'] = function () { return '_remote_dir_get()'; };
  PY.forBlock['zk_buzzer'] = function (b) {
    return '_buzzer(' + b.getFieldValue('ACT') + ')\n';
  };

  /* ============================================================
   * 屏幕图片 / 表情 → MicroPython 位图代码
   * 位图以 MONO_HLSB 字节数组形式生成，通过 oled.Bitmap 显示。
   * 采用「惰性注入」：首次用到某张图时才把字节数组写进前置区。
   * ============================================================ */
  var usedImages = {};   // id -> {varName}
  var imgSeq = 0;

  ZKB.PyImageRegistry = {
    get: function (id) {
      if (!ZKB.OledImage) return null;
      var rec = ZKB.OledImage.get(id);
      if (!rec) return null;
      var py = ZKB.OledImage.pythonFor(id);
      if (!py) return null;

      /* 同一张图只生成一份字节数组，重复引用复用 */
      var varName;
      if (usedImages[id]) {
        varName = usedImages[id].varName;
      } else {
        varName = 'zk_img' + (imgSeq++);
        usedImages[id] = { varName: varName };
      }
      py.varName = varName;
      py.emit = 'oled.Bitmap(0, 0, ' + varName + ', ' + ZKB.OledImage.W + ', ' + ZKB.OledImage.H + ', 1)\noled.show()\n';
      return py;
    },
    face: function (k) { return this.get('face_' + k); },
    /* 供前置区生成器输出已用到的位图声明 */
    declarations: function () {
      var out = [];
      Object.keys(usedImages).forEach(function (id) {
        var rec = ZKB.OledImage && ZKB.OledImage.get(id);
        if (!rec) return;
        var py = ZKB.OledImage.pythonFor(id);
        if (!py) return;
        /* 变量名以注册表为准（与正文调用处同名） */
        out.push('# ---- 屏幕图片：' + String(rec.name).replace(/[#>]/g, '') + ' ----');
        out.push(usedImages[id].varName + ' = ' + py.decl);
      });
      return out.join('\n');
    },
    reset: function () { usedImages = {}; imgSeq = 0; }
  };

  /* ============================================================
   * 编译入口
   * ============================================================ */
  function eventCode(block) {
    var type = block.type;
    var chain = block.getNextBlock() ? PY.blockToCode(block.getNextBlock()) : '';
    var body = indent(chain) || '    pass';
    var uid = type + '_' + block.id.replace(/[^a-zA-Z0-9]/g, '').slice(0, 6);

    if (type === 'zk_when_btn') {
      var btn = block.getFieldValue('BTN').toLowerCase();
      return 'def _' + uid + '(_pin):\n' + body + '\n' +
        'button_' + btn + '.event_pressed = _' + uid + '\n';
    }
    if (type === 'zk_when_touch') {
      return 'def _' + uid + '(_v):\n' + body + '\n' +
        touchVar(block.getFieldValue('PAD')) + '.event_pressed = _' + uid + '\n';
    }
    if (type === 'zk_when_ir') {
      return 'def _' + uid + '(_pin):\n' + body + '\n' +
        '_ir_sensor.irq(_' + uid + ', Pin.IRQ_FALLING)\n';
    }
    if (type === 'zk_when_shake') {
      return 'def _' + uid + '():\n' + body + '\n' +
        '_shake_prev = [accelerometer.get_x(), accelerometer.get_y(), accelerometer.get_z()]\n' +
        'def _shake_cb(_t):\n' +
        '    x, y, z = accelerometer.get_x(), accelerometer.get_y(), accelerometer.get_z()\n' +
        '    if abs(x - _shake_prev[0]) + abs(y - _shake_prev[1]) + abs(z - _shake_prev[2]) > 2.5:\n' +
        '        _' + uid + '()\n' +
        '    _shake_prev[0], _shake_prev[1], _shake_prev[2] = x, y, z\n' +
        'Timer(1).init(period=120, mode=Timer.PERIODIC, callback=_shake_cb)\n';
    }
    if (type === 'zk_when_radio') {
      return 'def _' + uid + '():\n' + body + '\n' +
        '# 轮询接收同频道广播\n' +
        'while True:\n' +
        '    _rm = radio.receive()\n' +
        '    if _rm is not None:\n' +
        '        _radio_msg = str(_rm)\n' +
        '        _' + uid + '()\n' +
        '    sleep_ms(30)\n';
    }
    if (type === 'zk_when_mqtt') {
      var topic = v(block, 'TOPIC', "''");
      return 'def _' + uid + '(_topic, _msg):\n' +
        '    global _mqtt_msg\n' +
        '    _mqtt_msg = _msg.decode()\n' +
        body + '\n' +
        '_mqtt_subs.append((' + topic + '.encode(), _' + uid + '))\n' +
        'while True:\n' +
        '    try:\n' +
        '        _mqtt.check_msg()\n' +
        '    except OSError:\n' +
        '        pass\n' +
        '    sleep_ms(30)\n';
    }
    return '';
  }

  /* ============================================================
   * 主入口
   * ============================================================ */
  ZKB.genPython = function (workspace) {
    /* 初始化生成器（变量名表、函数定义收集等） */
    PY.init(workspace);
    /* 扫描全部积木，确定依赖 */
    var flags = { pins: {}, music: false, shake: false,
      dht: false, servo: false, ir: false, ultra: false, heater: false,
      pump: false, motor: false, car: false, color: false, camera: false, vision: false,
      mic: false, lightExt: false, soil: false, pm25: false, baro: false,
      extbtn: false, fan: false,
      wifi: false, radio: false, ntp: false, mqtt: false, asr: false, weather: false,
      speech: false,   /* 第二十四轮：AI 语音转文字 + 语音合成 */
      /* mPython 扩展 API */
      musicTempo: false, parrot: false, neopixel: false,
      file: false, uart: false, elapsed: false, images: false,
      /* DFRobot 新增硬件 */
      tracker: false, powerMeter: false, gravity: false, angle: false,
      irTx: false, irRx: false, relay: false, ledModule: false,
      rgbStrip: false, buzzer: false, remote: false,
      textColor: false,
      mathLib: false,  /* 第四十九轮：用到 math.sqrt 时需要 import math */
      /* 第三十六轮：拓展设备积木补全 */
      pir: false, mp3: false, ds18: false, adc: false, touchpad: false,
      rgbGet: false, dhtDew: false, servoGet: false, stripGet: false, pumpState: false };
    var pinModeMap = { zk_pin_dout: 'OUT', zk_pin_pwm: 'PWM', zk_pin_din: 'IN', zk_pin_ain: 'ANALOG' };
    var devMap = {
      zk_dht_measure: 'dht', zk_dht_val: 'dht', zk_servo: 'servo',
      zk_ir: 'ir', zk_when_ir: 'ir', zk_ultra: 'ultra',
      zk_heat: 'heater', zk_heat_power: 'heater',
      zk_pump: 'pump', zk_pump_power: 'pump',
      zk_motor: 'motor', zk_car: 'car', zk_car_wheels: 'car',
      zk_color_rgb: 'color', zk_color_seen: 'color',
      zk_camera_result: 'camera', zk_camera_seen: 'camera',
      /* AI 摄像头三大识别 → vision（独立函数库，复用 camera 的 UART） */
      zk_vision_ocr_start: 'vision', zk_vision_ocr_text: 'vision', zk_vision_ocr_number: 'vision',
      zk_vision_face_register: 'vision', zk_vision_face_verify: 'vision',
      zk_vision_face_name: 'vision', zk_vision_face_gender: 'vision', zk_vision_face_bio: 'vision',
      zk_vision_face_emotion: 'vision', zk_vision_face_emotion_text: 'vision',
      zk_vision_obj_start: 'vision', zk_vision_obj_car: 'vision', zk_vision_obj_animal: 'vision',
      zk_vision_obj_plant: 'vision', zk_vision_obj_dish: 'vision', zk_vision_obj_fruit: 'vision',
      zk_vision_confidence: 'vision',
      /* 第三十五轮：新增视觉能力（场景 / 手写 / 速算 / 人脸属性） */
      zk_vision_scene_start: 'vision', zk_vision_scene_result: 'vision',
      zk_vision_handwrite_start: 'vision', zk_vision_handwrite_text: 'vision',
      zk_vision_calc_start: 'vision', zk_vision_calc_text: 'vision',
      zk_vision_calc_answer: 'vision', zk_vision_calc_correct: 'vision',
      zk_vision_face_count: 'vision', zk_vision_face_attr: 'vision',
      /* 第三十五轮：K210 板上预置模型 */
      zk_k210_kpu_load: 'k210', zk_k210_face_detect: 'k210', zk_k210_face_num: 'k210',
      zk_k210_face_x: 'k210', zk_k210_face_y: 'k210',
      zk_k210_face_w: 'k210', zk_k210_face_h: 'k210', zk_k210_face_value: 'k210',
      zk_k210_obj_detect: 'k210', zk_k210_obj_label: 'k210',
      zk_k210_obj_count: 'k210', zk_k210_obj_value: 'k210', zk_k210_digit: 'k210',
      zk_mic: 'mic', zk_ambient: 'lightExt',
      zk_soil: 'soil', zk_soil_pct: 'soil',
      zk_pm25: 'pm25', zk_pm25_level: 'pm25',
      zk_pressure: 'baro', zk_altitude: 'baro',
      zk_ext_btn: 'extbtn',
      zk_fan: 'fan', zk_fan_power: 'fan',
      zk_note: 'music', zk_tone: 'music', zk_music_stop: 'music', zk_music_play: 'music',
      /* 第四十九轮：内置乐曲也要 import music */
      zk_music_melody: 'music',
      zk_when_shake: 'shake',
      zk_wifi_connect: 'wifi', zk_wifi_ok: 'wifi',
      zk_radio_group: 'radio', zk_radio_send: 'radio',
      zk_when_radio: 'radio', zk_radio_msg: 'radio',
      zk_ntp_sync: 'ntp', zk_time_now: 'ntp',
      zk_mqtt_connect: 'mqtt', zk_mqtt_pub: 'mqtt',
      zk_when_mqtt: 'mqtt', zk_mqtt_msg: 'mqtt',
      zk_asr_text: 'asr',
      /* 第二十四轮：AI 语音能力（独立函数库，不依赖 WiFi） */
      zk_speech_recognize: 'speech', zk_speech_text: 'speech',
      zk_speech_conf: 'speech', zk_speech_is: 'speech',
      zk_speech_speak: 'speech', zk_speech_stop: 'speech',
      zk_speech_speaking: 'speech', zk_speech_done: 'speech',
      zk_weather: 'weather',
      /* 第二十九轮：八年级新增硬件 */
      zk_magnetic_init: 'magnetic', zk_magnetic_calibrate: 'magnetic',
      zk_magnetic_peeling: 'magnetic', zk_magnetic_heading: 'magnetic',
      zk_gps_init: 'gps', zk_gps_parse: 'gps', zk_gps_data: 'gps', zk_gps_ready: 'gps',
      zk_rfid_scan: 'rfid', zk_rfid_id: 'rfid',
      zk_speech2_init: 'speech2', zk_speech2_result: 'speech2',
      zk_qrcode: 'qrcode',
      /* 第三十六轮：拓展设备积木补全 */
      zk_ext_btn_pressed: 'extbtn', zk_ext_btn_count: 'extbtn', zk_ext_btn_reset: 'extbtn',
      zk_light_raw: 'lightExt', zk_light_pct: 'lightExt', zk_light_bright: 'lightExt',
      zk_motor_stop: 'motor', zk_motor_get_speed: 'motor', zk_motor_set: 'motor',
      zk_pressure_pa: 'baro', zk_temp: 'baro', zk_pressure_hpa: 'baro',
      zk_servo_get: 'servo', zk_servo_off: 'servo',
      zk_ultra_cm: 'ultra', zk_ultra_mm: 'ultra', zk_ultra_near: 'ultra',
      zk_pir: 'pir', zk_pir_count: 'pir', zk_pir_reset: 'pir',
      zk_dht_temp: 'dht', zk_dht_hum: 'dht', zk_dht_dew: 'dht', zk_dht_ok: 'dht',
      zk_soil_wet: 'soil', zk_soil_raw: 'soil',
      zk_strip_count: 'rgbStrip', zk_strip_get: 'rgbStrip',
      zk_strip_all_off: 'rgbStrip', zk_strip_rainbow_stop: 'rgbStrip',
      zk_pump_on: 'pump', zk_pump_get_power: 'pump', zk_pump_flow: 'pump',
      zk_pm25_value: 'pm25', zk_pm25_good: 'pm25', zk_pm25_harm: 'pm25',
      zk_mp3_play: 'mp3', zk_mp3_stop: 'mp3', zk_mp3_volume: 'mp3',
      zk_mp3_playing: 'mp3', zk_mp3_folder: 'mp3',
      /* 第三十六轮：补充官方 API 能力 */
      zk_ds18_temp: 'ds18', zk_ds18_ok: 'ds18',
      zk_adc_read: 'adc', zk_touchpad_read: 'touchpad'
    };
    /* mPython 扩展 API → 标记位 */
    var extMap = {
      zk_music_tempo: 'musicTempo', zk_music_get_tempo: 'musicTempo',
      zk_music_pitch: 'musicTempo', zk_music_reset: 'musicTempo',
      zk_parrot_speed: 'parrot', zk_parrot_get: 'parrot', zk_parrot_led: 'parrot',
      zk_neopixel_fill: 'neopixel',
      zk_file_write: 'file', zk_file_read: 'file',
      zk_uart_write: 'uart', zk_uart_read: 'uart',
      zk_time_tick: 'elapsed',
      zk_oled_image: 'images', zk_oled_face: 'images',
      zk_oled_text_color: 'textColor', zk_oled_text_color_do: 'textColor',
      /* DFRobot 新增硬件 */
      zk_tracker_read: 'tracker', zk_tracker_state: 'tracker',
      zk_power_read: 'powerMeter',
      zk_gravity_read: 'gravity',
      zk_angle_read: 'angle',
      zk_ir_send: 'irTx', zk_ir_receive: 'irRx',
      zk_relay: 'relay',
      zk_led_brightness: 'ledModule',
      /* 第三十五轮：LED 开关 / 亮度 / 状态 */
      zk_led_on: 'ledModule', zk_led_off: 'ledModule', zk_led_bright_set: 'ledModule',
      zk_led_is_on: 'ledModule', zk_led_get_bright: 'ledModule',
      zk_rgb_strip: 'rgbStrip',
      zk_buzzer: 'buzzer',
      zk_rgb_strip: 'rgbStrip', zk_rgb_strip_all: 'rgbStrip',
      zk_rgb_strip_off: 'rgbStrip', zk_rgb_strip_rainbow: 'rgbStrip',
      zk_remote_key: 'remote', zk_remote_dir: 'remote',
      /* 第二十九轮：5 行定位显示（对应官方 DispChar_5lines） */
      zk_oled_line5: 'line5',
      /* 第三十六轮：电机类积木走拓展板 parrot 模块（需 import parrot） */
      zk_motor_stop: 'parrot', zk_motor_get_speed: 'parrot', zk_motor_set: 'parrot',
      /* 第三十六轮：需要额外运行时辅助函数的积木 */
      zk_rgb_get: 'rgbGet', zk_rgb_get_brightness: 'rgbGet', zk_rgb_off_one: 'rgbGet',
      zk_dht_dew: 'dhtDew', zk_dht_ok: 'dhtDew',
      zk_servo_off: 'servoGet',
      zk_strip_get: 'stripGet',
      zk_pump_get_power: 'pumpState',
      zk_parrot_led_bright: 'parrot'
    };

    workspace.getAllBlocks(false).forEach(function (b) {
      var t = b.type;
      if (pinModeMap[t]) {
        var p = b.getFieldValue('PIN');
        if (p && !flags.pins[p]) flags.pins[p] = pinModeMap[t];
      }
      if (devMap[t]) flags[devMap[t]] = true;
      if (extMap[t]) flags[extMap[t]] = true;
      /* 第四十九轮：Blockly 内置 math_single 的「开平方」生成的是
         math.sqrt(...)，MicroPython 里必须 import math，
         否则真机一跑就 NameError: name 'math' isn't defined。
         其它 OP（绝对值 / 取负 …）是内置运算符，不需要 import。 */
      if (t === 'math_single' && b.getFieldValue('OP') === 'ROOT') flags.mathLib = true;
    });

    /* 位图注册表需重置：随后先编译 body（登记用到的图片），
       再据此生成前置区声明，否则位图字节数组会漏掉。 */
    if (ZKB.PyImageRegistry) ZKB.PyImageRegistry.reset();

    /* 自制积木定义先收集（函数体可能引用其它积木，放在顶层代码之前） */
    var myDefs = ZKB.MyBlocks.allDefs(workspace).map(myDefCode).filter(Boolean);

    /* 顶层编译（帽子特殊处理） */
    var bodyParts = [];
    workspace.getTopBlocks(true).forEach(function (top) {
      var t = top.type;
      if (t === 'zk_when_start') {
        var n = top.getNextBlock();
        if (n) bodyParts.push(PY.blockToCode(n));
      } else if (t === 'zk_when_btn' || t === 'zk_when_touch' ||
                 t === 'zk_when_ir' || t === 'zk_when_shake' ||
                 t === 'zk_when_radio' || t === 'zk_when_mqtt') {
        bodyParts.push(eventCode(top));
      } else if (t === 'zk_my_def') {
        /* 已在 myDefs 中统一处理 */
      } else if (top.outputConnection && !top.previousConnection && !top.nextConnection) {
        /* 第三十六轮：顶层「纯值积木」改用我们自己的 forBlock，
           避免 Blockly 的 blockToCode 产出 `_dht_dew(),99` 这种
           带类型编号后缀的孤立表达式（拷到真机上直接语法报错）。 */
        var pf = PY.forBlock[t];
        if (typeof pf === 'function') {
          /* 第四十五轮修正：Blockly 内置生成器签名是 (block, generator)，
             只传积木会让 generator 为 undefined，
             内置的 text / colour 等生成器一调 b.quote_ 就抛
             "Cannot read properties of undefined (reading 'quote_')"。 */
          var pr = pf(top, PY);
          if (Array.isArray(pr)) pr = pr[0];
          bodyParts.push(pr == null ? '' : String(pr));
        }
      } else {
        bodyParts.push(PY.blockToCode(top));
      }
    });

    var code = buildPreamble(workspace, flags) + '\n\n' +
      (myDefs.length ? myDefs.join('\n\n') + '\n\n' : '') +
      bodyParts.filter(Boolean).join('\n');
    code = PY.finish(code); // 追加用户自定义函数等定义
    return code.replace(/\n{3,}/g, '\n\n').trim() + '\n';
  };

})(window);
