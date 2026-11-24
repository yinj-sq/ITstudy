/* ============================================================
 * gen-sim.js —— 积木 → 仿真 JavaScript（async/await 调度模型）
 * 生成的代码在 AsyncFunction 中执行，S 为仿真运行时对象。
 * ============================================================ */
(function (global) {
  'use strict';
  var ZKB = global.ZKB;
  var JS = Blockly.JavaScript;
  var F = JS.forBlock;
  var ATOM = JS.ORDER_ATOMIC;
  var NONE = JS.ORDER_NONE;

  function v(block, name, fallback) {
    return JS.valueToCode(block, name, NONE) || (fallback === undefined ? 'null' : fallback);
  }

  /* ---------- 循环 / 等待：异步不卡死 ---------- */
  F['controls_forever'] = function (block) {
    var branch = JS.statementToCode(block, 'SUBSTACK') || '';
    return 'while (S.running()) {\n' + branch + '  await S.tick();\n}\n';
  };
  F['zk_wait_sec'] = function (b) {
    return 'await S.sleep((' + v(b, 'SEC', '1') + ') * 1000);\n';
  };
  F['zk_wait_ms'] = function (b) {
    return 'await S.sleep(' + v(b, 'MS', '100') + ');\n';
  };
  F['zk_print'] = function (b) {
    return 'S.log(' + v(b, 'V', '""') + ');\n';
  };

  /* ---------- OLED ---------- */
  F['zk_oled_clear'] = function () { return 'S.oled.clear();\n'; };
  F['zk_oled_fill'] = function (b) { return 'S.oled.fill(' + b.getFieldValue('V') + ');\n'; };
  /* 第四十八轮：统一的「屏幕 %1」积木（与真机生成保持一致） */
  F['zk_oled_screen'] = function (b) {
    var v = b.getFieldValue('V');
    if (v === 'clear' || v === 'black') return 'S.oled.fill(0);\n';
    return 'S.oled.fill(1);\n';
  };
  F['zk_oled_show'] = function () { return 'S.oled.show();\n'; };
  F['zk_oled_invert'] = function (b) { return 'S.oled.invert(' + b.getFieldValue('V') + ');\n'; };
  F['zk_oled_pixel'] = function (b) {
    return 'S.oled.pixel(' + v(b, 'X') + ', ' + v(b, 'Y') + ', ' + b.getFieldValue('V') + ');\n';
  };
  F['zk_oled_line'] = function (b) {
    return 'S.oled.line(' + ['X1', 'Y1', 'X2', 'Y2'].map(function (k) { return v(b, k); }).join(', ') + ');\n';
  };
  F['zk_oled_rect'] = function (b) {
    var fill = b.getFieldValue('FILL') === 'fill_rect' ? 'true' : 'false';
    return 'S.oled.rect(' + v(b, 'X') + ', ' + v(b, 'Y') + ', ' + v(b, 'W') + ', ' + v(b, 'H') + ', ' + fill + ');\n';
  };
  F['zk_oled_circle'] = function (b) {
    var fill = b.getFieldValue('FILL') === 'fill_circle' ? 'true' : 'false';
    return 'S.oled.circle(' + v(b, 'X') + ', ' + v(b, 'Y') + ', ' + v(b, 'R') + ', ' + fill + ');\n';
  };
  F['zk_oled_text_color'] = function (b) {
    return 'S.oled.setTextColor(' + JSON.stringify(b.getFieldValue('C') || 'white') + ');\n';
  };
  F['zk_oled_text_color_do'] = function (b) {
    var tb = b.getInputTargetBlock('T');
    var chinese = tb && tb.type === 'text' && /[\u4e00-\u9fa5]/.test(tb.getFieldValue('TEXT') || '');
    return 'S.oled.text(' + v(b, 'T', '""') + ', ' + v(b, 'X', '0') + ', ' + v(b, 'Y', '0') +
      ', ' + !!chinese + ', ' + JSON.stringify(b.getFieldValue('C') || 'white') + ');\n';
  };
  F['zk_oled_text'] = function (b) {
    var tb = b.getInputTargetBlock('T');
    var chinese = tb && tb.type === 'text' && /[\u4e00-\u9fa5]/.test(tb.getFieldValue('TEXT') || '');
    return 'S.oled.text(' + v(b, 'T', '""') + ', ' + v(b, 'X', '0') + ', ' + v(b, 'Y', '0') + ', ' + !!chinese + ');\n';
  };

  /* ---------- 第二十九轮：八年级新增硬件的仿真实现 ----------
     仿真里没有真实 I2C/UART 器件，用「可调虚拟读数」代替：
     传感器数值由 S.sensor 提供，RFID 刷卡 / GPS 搜星在虚拟面板上有按钮。 */
  var HAS_CN = function (tb) {
    return !!(tb && tb.type === 'text' && /[一-龥]/.test(tb.getFieldValue('TEXT') || ''));
  };
  F['zk_magnetic_init'] = function () {
    return 'S.log("磁场传感器已初始化（仿真）");\n';
  };
  F['zk_magnetic_calibrate'] = function () {
    return 'S.sensor.calibrate("magnetic"); S.log("磁场校准中，请转动板子…");\n';
  };
  F['zk_magnetic_peeling'] = function () {
    return 'S.sensor.peel("magnetic"); S.log("磁场已去皮");\n';
  };
  F['zk_magnetic_heading'] = function () {
    return ['S.sensor.get("magnetic.heading")', NONE];
  };

  F['zk_gps_init'] = function () {
    return 'S.sensor.gpsInit(); S.log("卫星定位已初始化，正在搜星…");\n';
  };
  F['zk_gps_parse'] = function () {
    return 'S.sensor.gpsParse();\n';
  };
  F['zk_gps_data'] = function (b) {
    return ['S.sensor.get("gps.' + (b.getFieldValue('K') || 'lon') + '")', NONE];
  };
  F['zk_gps_ready'] = function () {
    return ['S.sensor.get("gps.ready") >= 1', NONE];
  };

  F['zk_qrcode'] = function (b) {
    return 'S.oled.qrcode(' + v(b, 'STR', '"24992"') + ', ' +
      v(b, 'X', '0') + ', ' + v(b, 'Y', '0') + ');\n';
  };

  /* 刷卡是语句积木（与官方 newrfid_scan 一致） */
  F['zk_rfid_scan'] = function () {
    return 'S.rfid.scan();\n';
  };
  F['zk_rfid_id'] = function () {
    return ["S.rfid.last", NONE];
  };

  F['zk_speech2_init'] = function () {
    return 'S.asr2.arm(); S.log("离线语音识别已初始化");\n';
  };
  F['zk_speech2_result'] = function () {
    return ['S.asr2.result', NONE];
  };

  /* 5 行定位显示：官方把 128x64 分成 5 行、每行 12px */
  F['zk_oled_line5'] = function (b) {
    return 'S.oled.line5(' + v(b, 'T', '""') + ', ' + v(b, 'LINE', '1') + ', ' +
      HAS_CN(b.getInputTargetBlock('T')) + ');\n';
  };

  F['zk_str2num'] = function (b) {
    var fn = b.getFieldValue('TYPE') === 'float' ? 'parseFloat' : 'parseInt';
    return [fn + '(' + v(b, 'S', '""') + ')', NONE];
  };

  /* 第四十六轮：把变量限制在最低值与最高值之间
   * 第一个口是变量（field_variable），语义同内置 math_constrain：
   * Math.min(Math.max(值, 最低), 最高)。 */
  F['zk_constrain'] = function (b) {
    var f = b.getField('VAR');
    var model = f && (f.variable || f.variable_);
    var varName = b.getFieldValue('VAR');
    var name = model ? model.name : varName;
    /* 仿真端变量存在 S.vars 里，用字符串键访问 */
    var low = v(b, 'LOW', '0');
    var high = v(b, 'HIGH', 'Infinity');
    return ['Math.min(Math.max(S.varGet(' + JSON.stringify(name) + '), ' + low + '), ' + high + ')', NONE];
  };

  /* 第四十九轮：区间映射（与 gen-python 的 hunan_map_value 完全同式） */
  F['zk_map_value'] = function (b) {
    var x = v(b, 'X', '0'), a = v(b, 'A', '0'), bb = v(b, 'B', '4095'),
      c = v(b, 'C', '0'), d = v(b, 'D', '9');
    return ['((' + bb + ') === (' + a + ') ? (' + c + ') : Math.round(' +
      '((' + x + ') - (' + a + ')) * ((' + d + ') - (' + c + ')) / ((' + bb + ') - (' + a + ')) + (' + c + ')))', NONE];
  };

  /* 第四十九轮：播放掌控板内置乐曲（仿真端走素材库同名曲目，没有就静默） */
  F['zk_music_melody'] = function (b) {
    return 'S.music.playMelody(' + JSON.stringify(b.getFieldValue('NAME') || 'BIRTHDAY') + ', ' +
      JSON.stringify(b.getFieldValue('MODE') || 'once') + ');\n';
  };

  /* ---------- OLED 扩展图形（对应 mpython oled/UI API） ---------- */
  F['zk_oled_roundrect'] = function (b) {
    return 'S.oled.roundrect(' + v(b, 'X', '0') + ', ' + v(b, 'Y', '0') + ', ' + v(b, 'W', '10') + ', ' +
      v(b, 'H', '10') + ', ' + v(b, 'R', '2') + ', ' + b.getFieldValue('V') + ');\n';
  };
  F['zk_oled_hline'] = function (b) {
    return 'S.oled.hline(' + v(b, 'X', '0') + ', ' + v(b, 'Y', '0') + ', ' + v(b, 'W', '10') + ', ' + b.getFieldValue('V') + ');\n';
  };
  F['zk_oled_vline'] = function (b) {
    return 'S.oled.vline(' + v(b, 'X', '0') + ', ' + v(b, 'Y', '0') + ', ' + v(b, 'L', '10') + ', ' + b.getFieldValue('V') + ');\n';
  };
  F['zk_oled_triangle'] = function (b) {
    return 'S.oled.triangle(' + ['X0', 'Y0', 'X1', 'Y1', 'X2', 'Y2'].map(function (k) { return v(b, k, '0'); }).join(', ') +
      ', ' + b.getFieldValue('V') + ');\n';
  };
  F['zk_oled_progress'] = function (b) {
    return 'S.oled.progress(' + v(b, 'X', '0') + ', ' + v(b, 'Y', '0') + ', ' + v(b, 'W', '40') + ', ' +
      v(b, 'H', '8') + ', ' + v(b, 'P', '50') + ');\n';
  };
  F['zk_oled_stripbar'] = function (b) {
    return 'S.oled.stripbar(' + v(b, 'X', '0') + ', ' + v(b, 'Y', '0') + ', ' + v(b, 'W', '40') + ', ' +
      v(b, 'H', '8') + ', ' + v(b, 'P', '50') + ', ' + b.getFieldValue('DIR') + ', ' + b.getFieldValue('FR') + ');\n';
  };

  /* ---------- 屏幕图片 / 表情 ---------- */
  F['zk_oled_image'] = function (b) {
    var id = b.getFieldValue('IMG');
    if (!id || id === 'none') return 'S.log("请先在右侧「屏幕图片」面板上传或选择图片");\n';
    return 'S.oled.showImage(' + JSON.stringify(id) + ');\n';
  };
  F['zk_oled_face'] = function (b) {
    return 'S.oled.showFace(' + JSON.stringify(b.getFieldValue('FACE') || 'happy') + ');\n';
  };

  /* ---------- RGB ---------- */
  function rgbArr(b) {
    return '[' + v(b, 'R', '255') + ', ' + v(b, 'G', '0') + ', ' + v(b, 'B', '0') + ']';
  }
  F['zk_rgb_one'] = function (b) {
    var n = b.getFieldValue('N');
    var m = /^#?([0-9a-f]{6})$/i.exec(b.getFieldValue('COLOR') || '000000');
    var x = parseInt(m ? m[1] : '000000', 16);
    var arr = [(x >> 16) & 255, (x >> 8) & 255, x & 255];
    return "S.rgb.set('" + n + "', [" + arr.join(',') + "]);\n";
  };
  F['zk_rgb_rgb'] = function (b) {
    return "S.rgb.set('" + b.getFieldValue('N') + "', " + rgbArr(b) + ');\n';
  };
  F['zk_rgb_clear'] = function () { return 'S.rgb.clear();\n'; };
  /* 第四十五轮：刷新彩灯（官方 rgb.write()） */
  F['zk_rgb_write'] = function () { return 'S.rgb.write();\n'; };
  F['zk_rgb_brightness'] = function (b) {
    return 'S.rgb.brightness(' + v(b, 'V', '30') + ');\n';
  };

  /* ---------- 按键 / 触摸 ---------- */
  F['zk_is_btn'] = function (b) { return ['S.btn("' + b.getFieldValue('BTN') + '")', ATOM]; };
  F['zk_is_touch'] = function (b) { return ['S.touch("' + b.getFieldValue('PAD') + '")', ATOM]; };

  /* ---------- 板载传感器 ---------- */
  F['zk_light'] = function () { return ['S.light()', ATOM]; };
  F['zk_sound'] = function () { return ['S.sound()', ATOM]; };
  F['zk_accel'] = function (b) { return ['S.accel("' + b.getFieldValue('AXIS') + '")', ATOM]; };
  F['zk_tilt'] = function (b) { return ['S.tilt("' + b.getFieldValue('K') + '")', ATOM]; };

  /* ---------- 蜂鸣器 ---------- */
  F['zk_note'] = function (b) {
    return "await S.note('" + b.getFieldValue('NOTE') + "', " + b.getFieldValue('BEAT') + ');\n';
  };
  F['zk_tone'] = function (b) {
    return 'await S.tone(' + v(b, 'F', '440') + ', ' + v(b, 'D', '0.5') + ');\n';
  };
  F['zk_music_stop'] = function () { return 'S.stopMusic();\n'; };

  /* ---------- 引脚 ---------- */
  F['zk_pin_dout'] = function (b) {
    return 'S.pinOut(' + b.getFieldValue('PIN') + ', ' + b.getFieldValue('V') + ');\n';
  };
  F['zk_pin_pwm'] = function (b) {
    return 'S.pwm(' + b.getFieldValue('PIN') + ', ' + v(b, 'V', '0') + ');\n';
  };
  F['zk_pin_din'] = function (b) { return ['S.pinDin(' + b.getFieldValue('PIN') + ')', ATOM]; };
  F['zk_pin_ain'] = function (b) { return ['S.pinAin(' + b.getFieldValue('PIN') + ')', ATOM]; };

  /* ---------- 拓展设备（多实例：INST 字段为设备序号，默认 1） ---------- */
  function inst(b) { return Number(b.getFieldValue('INST')) || 1; }
  F['zk_dht_measure'] = function (b) { return 'S.dhtMeasure(' + inst(b) + ');\n'; };
  F['zk_dht_val'] = function (b) { return ['S.dht(' + inst(b) + ', "' + b.getFieldValue('K') + '")', ATOM]; };
  F['zk_ultra'] = function (b) { return ['S.distance(' + inst(b) + ')', ATOM]; };
  /* 第四十五轮：初始化超声波（官方 mxml 用） */
  F['zk_ultra_init'] = function (b) { return 'S.ultraInit(' + inst(b) + ');\n'; };
  F['zk_servo'] = function (b) { return 'S.servo(' + inst(b) + ', ' + v(b, 'A', '90') + ');\n'; };
  F['zk_ir'] = function (b) { return ['S.ir(' + inst(b) + ')', ATOM]; };

  F['zk_heat'] = function (b) { return 'S.heater(' + inst(b) + ', ' + b.getFieldValue('V') + ');\n'; };
  F['zk_heat_power'] = function (b) { return 'S.heaterPower(' + inst(b) + ', ' + v(b, 'V', '50') + ');\n'; };
  F['zk_pump'] = function (b) { return 'S.pump(' + inst(b) + ', ' + b.getFieldValue('V') + ');\n'; };
  F['zk_pump_power'] = function (b) { return 'S.pumpPower(' + inst(b) + ', ' + v(b, 'V', '80') + ');\n'; };
  F['zk_motor'] = function (b) {
    return "S.motor(" + inst(b) + ", '" + b.getFieldValue('DIR') + "', " + v(b, 'S', '60') + ');\n';
  };
  F['zk_car'] = function (b) {
    return "S.car(" + inst(b) + ", '" + b.getFieldValue('DIR') + "', " + v(b, 'S', '60') + ');\n';
  };
  F['zk_car_wheels'] = function (b) {
    return 'S.wheels(' + inst(b) + ', ' + v(b, 'L', '0') + ', ' + v(b, 'R', '0') + ');\n';
  };
  F['zk_car_dist'] = function (b) { return ['S.carDist(' + inst(b) + ')', ATOM]; };

  F['zk_color_rgb'] = function (b) {
    var k = { r: 0, g: 1, b: 2, c: 3 }[b.getFieldValue('K')];
    return ['S.colorChannel(' + inst(b) + ', ' + k + ')', ATOM];
  };
  F['zk_color_seen'] = function (b) {
    return ['S.colorSeen(' + inst(b) + ', "' + b.getFieldValue('COLOR') + '")', ATOM];
  };
  F['zk_camera_result'] = function (b) { return ['S.cameraResult(' + inst(b) + ')', ATOM]; };
  F['zk_camera_seen'] = function (b) {
    return ['S.cameraSeen(' + inst(b) + ', "' + b.getFieldValue('OBJ') + '")', ATOM];
  };

  /* —— AI 摄像头三大识别能力（第二十三轮，第三十五轮接真实讯飞 AI）—— */
  /* 第三十五轮：三个「启动识别」积木都改成 await，
     因为真实识别要走网络（抓帧 → 讯飞接口），必须等结果出来再往下跑。 */
  /* 文字识别 */
  F['zk_vision_ocr_start'] = function (b) {
    return 'await S.visionOcrStart(' + inst(b) + ', "' + (b.getFieldValue('MODE') || 'text') + '");\n';
  };
  F['zk_vision_ocr_text'] = function (b) { return ['S.visionOcrText(' + inst(b) + ')', ATOM]; };
  F['zk_vision_ocr_number'] = function (b) { return ['S.visionOcrNumber(' + inst(b) + ')', ATOM]; };
  /* 人脸识别 */
  F['zk_vision_face_register'] = function (b) {
    return 'S.visionFaceRegister(' + inst(b) + ', ' + v(b, 'NAME', '"（未命名）"') +
      ', "' + (b.getFieldValue('GENDER') || 'male') + '", ' + v(b, 'BIO', '""') + ');\n';
  };
  F['zk_vision_face_verify'] = function (b) {
    return 'await S.visionFaceVerify(' + inst(b) + ', ' + v(b, 'NAME', '""') + ');\n';
  };
  F['zk_vision_face_name'] = function (b) { return ['S.visionFaceName(' + inst(b) + ')', ATOM]; };
  F['zk_vision_face_gender'] = function (b) { return ['S.visionFaceGender(' + inst(b) + ')', ATOM]; };
  F['zk_vision_face_bio'] = function (b) { return ['S.visionFaceBio(' + inst(b) + ')', ATOM]; };
  F['zk_vision_face_emotion'] = function (b) {
    return ['S.visionFaceEmotion(' + inst(b) + ', "' + (b.getFieldValue('EM') || 'happy') + '")', ATOM];
  };
  F['zk_vision_face_emotion_text'] = function (b) {
    return ['S.visionFaceEmotionText(' + inst(b) + ')', ATOM];
  };
  /* 物体识别 */
  F['zk_vision_obj_start'] = function (b) {
    return 'await S.visionObjStart(' + inst(b) + ', "' + (b.getFieldValue('CAT') || 'car') + '");\n';
  };
  F['zk_vision_obj_car'] = function (b) { return ['S.visionObjResult(' + inst(b) + ', "car")', ATOM]; };
  F['zk_vision_obj_animal'] = function (b) { return ['S.visionObjResult(' + inst(b) + ', "animal")', ATOM]; };
  F['zk_vision_obj_plant'] = function (b) { return ['S.visionObjResult(' + inst(b) + ', "plant")', ATOM]; };
  F['zk_vision_obj_dish'] = function (b) { return ['S.visionObjResult(' + inst(b) + ', "dish")', ATOM]; };
  F['zk_vision_obj_fruit'] = function (b) { return ['S.visionObjResult(' + inst(b) + ', "fruit")', ATOM]; };
  F['zk_vision_confidence'] = function (b) { return ['S.visionConfidence(' + inst(b) + ')', ATOM]; };
  /* 第三十五轮：场景识别 / 手写文字 / 拍照速算 / 人脸数量与属性 */
  F['zk_vision_scene_start'] = function (b) {
    return 'await S.visionSceneStart(' + inst(b) + ');\n';
  };
  F['zk_vision_scene_result'] = function (b) { return ['S.visionSceneResult(' + inst(b) + ')', ATOM]; };
  F['zk_vision_handwrite_start'] = function (b) {
    return 'await S.visionHandwriteStart(' + inst(b) + ');\n';
  };
  F['zk_vision_handwrite_text'] = function (b) { return ['S.visionHandwriteText(' + inst(b) + ')', ATOM]; };
  F['zk_vision_calc_start'] = function (b) {
    return 'await S.visionCalcStart(' + inst(b) + ');\n';
  };
  F['zk_vision_calc_text'] = function (b) { return ['S.visionCalcText(' + inst(b) + ')', ATOM]; };
  F['zk_vision_calc_answer'] = function (b) { return ['S.visionCalcAnswer(' + inst(b) + ')', ATOM]; };
  F['zk_vision_calc_correct'] = function (b) { return ['S.visionCalcCorrect(' + inst(b) + ')', ATOM]; };
  F['zk_vision_face_count'] = function (b) { return ['S.visionFaceCount(' + inst(b) + ')', ATOM]; };
  F['zk_vision_face_attr'] = function (b) {
    return ['S.visionFaceAttr(' + inst(b) + ', "' + (b.getFieldValue('A') || 'gender') + '")', ATOM];
  };
  /* 第三十五轮：K210 板上预置模型（虚拟仿真用离线模拟，
     真机上走串口指令，见 gen-python.js 的 _kpu_* 函数）*/
  F['zk_k210_kpu_load'] = function (b) {
    return 'S.kpuLoad("' + (b.getFieldValue('MODEL') || 'face') + '");\n';
  };
  F['zk_k210_face_detect'] = function (b) { return 'S.kpuDetect("face");\n'; };
  F['zk_k210_face_num'] = function (b) { return ['S.kpuFaceNum()', ATOM]; };
  F['zk_k210_face_x'] = function (b) { return ['S.kpuFaceField(' + v(b, 'N', '1') + ', 1)', ATOM]; };
  F['zk_k210_face_y'] = function (b) { return ['S.kpuFaceField(' + v(b, 'N', '1') + ', 2)', ATOM]; };
  F['zk_k210_face_w'] = function (b) { return ['S.kpuFaceField(' + v(b, 'N', '1') + ', 3)', ATOM]; };
  F['zk_k210_face_h'] = function (b) { return ['S.kpuFaceField(' + v(b, 'N', '1') + ', 4)', ATOM]; };
  F['zk_k210_face_value'] = function (b) { return ['S.kpuFaceField(' + v(b, 'N', '1') + ', 5)', ATOM]; };
  F['zk_k210_obj_detect'] = function (b) {
    return 'S.kpuDetect("' + (b.getFieldValue('MODEL') || 'class20') + '");\n';
  };
  F['zk_k210_obj_label'] = function (b) {
    return ['S.kpuObjLabel(' + (Number(b.getFieldValue('IDX')) || 0) + ')', ATOM];
  };
  F['zk_k210_obj_count'] = function (b) { return ['S.kpuObjCount()', ATOM]; };
  F['zk_k210_obj_value'] = function (b) { return ['S.kpuObjValue(' + v(b, 'N', '1') + ')', ATOM]; };
  F['zk_k210_digit'] = function (b) { return ['S.kpuDigit()', ATOM]; };

  F['zk_mic'] = function (b) { return ['S.mic(' + inst(b) + ')', ATOM]; };
  F['zk_ambient'] = function (b) { return ['S.ambient(' + inst(b) + ')', ATOM]; };

  /* —— 新增设备仿真 —— */
  F['zk_soil'] = function (b) { return ['S.soil(' + inst(b) + ')', ATOM]; };
  F['zk_soil_pct'] = function (b) { return ['S.soilPct(' + inst(b) + ')', ATOM]; };
  F['zk_pm25'] = function (b) { return ['S.pm25(' + inst(b) + ')', ATOM]; };
  F['zk_pm25_level'] = function (b) { return ['S.pm25Level(' + inst(b) + ')', ATOM]; };
  F['zk_pressure'] = function (b) { return ['S.pressure(' + inst(b) + ')', ATOM]; };
  F['zk_altitude'] = function (b) { return ['S.altitude(' + inst(b) + ')', ATOM]; };
  F['zk_ext_btn'] = function (b) { return ['S.extBtn(' + inst(b) + ')', ATOM]; };
  F['zk_fan'] = function (b) { return 'S.fan(' + inst(b) + ', ' + b.getFieldValue('V') + ');\n'; };
  F['zk_fan_power'] = function (b) { return 'S.fanPower(' + inst(b) + ', ' + v(b, 'V', '60') + ');\n'; };

  /* ---------- 舞台元素控制（仅仿真） ---------- */
  F['zk_stage_move'] = function (b) {
    return 'S.stage.moveTo(' + el(b) + ', ' + v(b, 'X', '100') + ', ' + v(b, 'Y', '100') + ');\n';
  };
  F['zk_stage_layer'] = function (b) {
    return 'S.stage.layer(' + el(b) + ', "' + b.getFieldValue('OP') + '");\n';
  };
  F['zk_stage_scale'] = function (b) {
    return 'S.stage.scale(' + el(b) + ', ' + v(b, 'PCT', '100') + ');\n';
  };
  F['zk_stage_rotate'] = function (b) {
    return 'S.stage.rotate(' + el(b) + ', ' + (Number(b.getFieldValue('DIR')) || 90) + ');\n';
  };

  /* ---------- 第三十轮：运动模块（仅仿真，真机无对应硬件） ----------
     方向 0°正上 / 90°正右 / 180°正下 / 270°正左；坐标以舞台中心为原点。 */
  function el(b) { return JSON.stringify(b.getFieldValue('EL') || ''); }
  F['zk_mv_steps'] = function (b) {
    return 'S.stage.moveSteps(' + el(b) + ', ' + v(b, 'N', '10') + ');\n';
  };
  /* 第三十五轮：zk_mv_forward / zk_mv_back 已删除 */
  F['zk_mv_goto'] = function (b) {
    return 'S.stage.gotoXY(' + el(b) + ', ' + v(b, 'X', '0') + ', ' + v(b, 'Y', '0') + ');\n';
  };
  F['zk_mv_changex'] = function (b) {
    return 'S.stage.changeXY(' + el(b) + ', "x", ' + v(b, 'N', '10') + ');\n';
  };
  F['zk_mv_changey'] = function (b) {
    return 'S.stage.changeXY(' + el(b) + ', "y", ' + v(b, 'N', '10') + ');\n';
  };
  F['zk_mv_setx'] = function (b) {
    return 'S.stage.setXYAbs(' + el(b) + ', "x", ' + v(b, 'N', '0') + ');\n';
  };
  F['zk_mv_sety'] = function (b) {
    return 'S.stage.setXYAbs(' + el(b) + ', "y", ' + v(b, 'N', '0') + ');\n';
  };
  F['zk_mv_x'] = function (b) { return ['S.stage.getXY(' + el(b) + ', "x")', NONE]; };
  F['zk_mv_y'] = function (b) { return ['S.stage.getXY(' + el(b) + ', "y")', NONE]; };
  F['zk_mv_dir'] = function (b) { return ['S.stage.getDir(' + el(b) + ')', NONE]; };
  F['zk_mv_turnright'] = function (b) {
    return 'S.stage.turnBy(' + el(b) + ', ' + v(b, 'D', '15') + ');\n';
  };
  F['zk_mv_turnleft'] = function (b) {
    return 'S.stage.turnBy(' + el(b) + ', -(' + v(b, 'D', '15') + '));\n';
  };
  F['zk_mv_pointdir'] = function (b) {
    return 'S.stage.setRot(' + el(b) + ', ' + v(b, 'D', '90') + ');\n';
  };
  /* 第三十六轮：zk_mv_setdir 已删除，方向统一由 zk_mv_pointdir 负责 */
  F['zk_mv_pointto'] = function (b) {
    return 'S.stage.pointTowards(' + el(b) + ', ' + JSON.stringify(b.getFieldValue('TO') || '') + ');\n';
  };
  F['zk_mv_glide'] = function (b) {
    return 'await S.stage.glide(' + el(b) + ', ' + v(b, 'X', '0') + ', ' + v(b, 'Y', '0') +
      ', (' + v(b, 'SEC', '1') + ') * 1000);\n';
  };
  F['zk_mv_bounce'] = function (b) {
    return 'S.stage.ifOnEdgeBounce(' + el(b) + ');\n';
  };
  F['zk_mv_random'] = function (b) { return 'S.stage.gotoRandom(' + el(b) + ');\n'; };

  /* ---------- 第三十轮：外观模块 ---------- */
  F['zk_look_show'] = function (b) { return 'S.stage.setVisible(' + el(b) + ', true);\n'; };
  F['zk_look_hide'] = function (b) { return 'S.stage.setVisible(' + el(b) + ', false);\n'; };
  F['zk_look_visible'] = function (b) {
    return ['S.stage.isVisible(' + el(b) + ')', NONE];
  };
  F['zk_look_size'] = function (b) { return ['S.stage.getSize(' + el(b) + ')', NONE]; };
  F['zk_look_setsize'] = function (b) {
    return 'S.stage.setScale(' + el(b) + ', ' + v(b, 'N', '100') + ');\n';
  };
  F['zk_look_chsize'] = function (b) {
    return 'S.stage.changeScale(' + el(b) + ', ' + v(b, 'N', '10') + ');\n';
  };
  F['zk_look_opacity'] = function (b) {
    return 'S.stage.setOpacity(' + el(b) + ', ' + v(b, 'N', '100') + ');\n';
  };
  F['zk_look_ghost'] = function (b) {
    return 'S.stage.setGhost(' + el(b) + ', ' + v(b, 'N', '0') + ');\n';
  };
  F['zk_look_colorfx'] = function (b) {
    return 'S.stage.colorFx(' + el(b) + ', "' + (b.getFieldValue('FX') || 'hue') + '", ' +
      v(b, 'N', '25') + ');\n';
  };
  F['zk_look_cleareffects'] = function (b) {
    return 'S.stage.clearEffects(' + el(b) + ');\n';
  };
  /* ---- 元素层级（第三十二轮，第三十五轮四块融合为一块下拉） ---- */
  F['zk_look_layerop'] = function (b) {
    return 'S.stage.layer(' + el(b) + ', "' + (b.getFieldValue('OP') || 'front') + '");\n';
  };
  F['zk_look_layern'] = function (b) {
    return 'S.stage.layerTo(' + el(b) + ', ' + v(b, 'N', '1') + ');\n';
  };
  F['zk_look_layer'] = function (b) { return ['S.stage.layerOf(' + el(b) + ')', ATOM]; };
  F['zk_look_layercount'] = function () { return ['S.stage.layerTotal()', ATOM]; };
  /* 第三十五轮：zk_mv_face（数字框 + 方向盘）已删除 */
  /* ---------- 音乐播放（内置曲目 / 上传音频） ---------- */
  F['zk_music_play'] = function (b) {
    return 'S.music.play(' + JSON.stringify(b.getFieldValue('NAME') || '') + ', ' +
      JSON.stringify(b.getFieldValue('MODE') || 'once') + ');\n';
  };

  /* ============================================================
   * 第三十六轮：拓展设备积木补全（定义见 js/device-blocks.js）
   * ============================================================ */

  /* ---- RGB 灯模块 ---- */
  F['zk_rgb_get'] = function (b) {
    return ['S.rgb.get(' + JSON.stringify(b.getFieldValue('N') || '0') + ', "' +
      (b.getFieldValue('C') || 'r') + '")', ATOM];
  };
  F['zk_rgb_get_brightness'] = function () { return ['S.rgb.getBrightness()', ATOM]; };
  F['zk_rgb_fill'] = function (b) {
    var m = /^#?([0-9a-f]{6})$/i.exec(b.getFieldValue('COLOR') || '000000');
    var x = parseInt(m ? m[1] : '000000', 16);
    var arr = [(x >> 16) & 255, (x >> 8) & 255, x & 255];
    return 'S.rgb.fill([' + arr.join(',') + ']);\n';
  };
  F['zk_rgb_fill_rgb'] = function (b) {
    return 'S.rgb.fill(' + rgbArr(b) + ');\n';
  };
  F['zk_rgb_off_one'] = function (b) {
    return 'S.rgb.set(' + JSON.stringify(b.getFieldValue('N') || '0') + ', [0, 0, 0]);\n';
  };

  /* ---- 按键模块 ---- */
  F['zk_ext_btn_pressed'] = function (b) { return ['S.extBtn(' + inst(b) + ')', ATOM]; };
  F['zk_ext_btn_count'] = function (b) { return ['S.extBtnCount(' + inst(b) + ')', ATOM]; };
  F['zk_ext_btn_reset'] = function (b) { return 'S.extBtnReset(' + inst(b) + ');\n'; };

  /* ---- 光线传感器 ---- */
  F['zk_light_raw'] = function (b) { return ['S.lightRaw(' + inst(b) + ')', ATOM]; };
  F['zk_light_pct'] = function (b) { return ['S.lightPct(' + inst(b) + ')', ATOM]; };
  F['zk_light_bright'] = function (b) { return ['S.lightBright(' + inst(b) + ')', ATOM]; };

  /* ---- 直流电机 / 马达 ---- */
  F['zk_motor_stop'] = function () { return 'S.motorStop();\n'; };
  F['zk_motor_get_speed'] = function (b) {
    return ['S.motorGetSpeed(' + JSON.stringify(b.getFieldValue('M') || 'MOTOR_1') + ')', ATOM];
  };
  F['zk_motor_set'] = function (b) {
    return 'S.motorSet(' + JSON.stringify(b.getFieldValue('M') || 'MOTOR_1') + ', ' +
      v(b, 'S', '60') + ');\n';
  };

  /* ---- 气压传感器 ---- */
  F['zk_pressure_pa'] = function (b) { return ['S.pressurePa(' + inst(b) + ')', ATOM]; };
  F['zk_temp'] = function (b) { return ['S.temp(' + inst(b) + ')', ATOM]; };
  F['zk_pressure_hpa'] = function (b) { return ['S.pressure(' + inst(b) + ')', ATOM]; };

  /* ---- 舵机 ---- */
  F['zk_servo_get'] = function (b) { return ['S.servoGet(' + inst(b) + ')', ATOM]; };
  F['zk_servo_off'] = function (b) { return 'S.servoOff(' + inst(b) + ');\n'; };

  /* ---- 超声波 ---- */
  F['zk_ultra_cm'] = function (b) { return ['S.distance(' + inst(b) + ')', ATOM]; };
  F['zk_ultra_mm'] = function (b) { return ['S.distanceMm(' + inst(b) + ')', ATOM]; };
  F['zk_ultra_near'] = function (b) {
    return ['S.distance(' + inst(b) + ') < ' + v(b, 'CM', '30'), ATOM];
  };

  /* ---- 人体红外 ---- */
  F['zk_pir'] = function (b) { return ['S.pir(' + inst(b) + ')', ATOM]; };
  F['zk_pir_count'] = function (b) { return ['S.pirCount(' + inst(b) + ')', ATOM]; };
  F['zk_pir_reset'] = function (b) { return 'S.pirReset(' + inst(b) + ');\n'; };

  /* ---- 温湿度 ---- */
  F['zk_dht_temp'] = function (b) { return ['S.dht(' + inst(b) + ', "t")', ATOM]; };
  F['zk_dht_hum'] = function (b) { return ['S.dht(' + inst(b) + ', "h")', ATOM]; };
  F['zk_dht_dew'] = function (b) { return ['S.dhtDew(' + inst(b) + ')', ATOM]; };
  F['zk_dht_ok'] = function (b) { return ['S.dhtOk(' + inst(b) + ')', ATOM]; };

  /* ---- 土壤湿度 ---- */
  F['zk_soil_wet'] = function (b) { return ['S.soilWet(' + inst(b) + ')', ATOM]; };
  F['zk_soil_raw'] = function (b) { return ['S.soil(' + inst(b) + ')', ATOM]; };

  /* ---- LED 灯带 ---- */
  F['zk_strip_count'] = function () { return ['S.ext.strip.count()', ATOM]; };
  F['zk_strip_get'] = function (b) {
    return ['S.ext.strip.get(' + v(b, 'I', '1') + ', "' + (b.getFieldValue('C') || 'r') + '")', ATOM];
  };
  F['zk_strip_all_off'] = function (b) {
    return 'S.ext.strip.off(' + inst(b) + ', 0);\n';
  };
  F['zk_strip_rainbow_stop'] = function (b) {
    return 'S.ext.strip.rainbowStop(' + inst(b) + ');\n';
  };

  /* ---- 水泵 ---- */
  F['zk_pump_on'] = function (b) {
    return 'S.pump(' + inst(b) + ', ' + (b.getFieldValue('V') === '1' ? 1 : 0) + ');\n';
  };
  F['zk_pump_get_power'] = function (b) { return ['S.pumpPowerGet(' + inst(b) + ')', ATOM]; };
  F['zk_pump_flow'] = function (b) { return ['S.pumpFlow(' + inst(b) + ')', ATOM]; };

  /* ---- PM2.5 ---- */
  F['zk_pm25_value'] = function (b) { return ['S.pm25(' + inst(b) + ')', ATOM]; };
  F['zk_pm25_good'] = function (b) { return ['S.pm25(' + inst(b) + ') < 35', ATOM]; };
  F['zk_pm25_harm'] = function (b) { return ['S.pm25(' + inst(b) + ') > 115', ATOM]; };

  /* ---- MP3 模块 ---- */
  F['zk_mp3_play'] = function (b) {
    return 'S.mp3.play(' + JSON.stringify(b.getFieldValue('NAME') || '') + ');\n';
  };
  F['zk_mp3_stop'] = function (b) { return 'S.mp3.stop();\n'; };
  F['zk_mp3_volume'] = function (b) {
    return 'S.mp3.volume(' + v(b, 'V', '15') + ');\n';
  };
  F['zk_mp3_playing'] = function () { return ['S.mp3.playing()', ATOM]; };
  F['zk_mp3_folder'] = function (b) {
    return 'S.mp3.playFolder(' + v(b, 'F', '1') + ', ' + v(b, 'N', '1') + ');\n';
  };

  /* ---- 十六、补充官方 API 能力（虚拟仿真用近似值） ---- */
  F['zk_ds18_temp'] = function () { return ['S.ds18Temp()', ATOM]; };
  F['zk_ds18_ok'] = function () { return ['S.ds18Ok()', ATOM]; };
  F['zk_adc_read'] = function (b) {
    return ['S.adcRead(' + (Number(b.getFieldValue('PIN')) || 2) + ')', ATOM];
  };
  F['zk_touchpad_read'] = function (b) {
    return ['S.touch("' + (b.getFieldValue('PAD') || 'P') + '")', ATOM];
  };
  F['zk_music_pitch'] = function (b) {
    return 'S.music.pitch(' + v(b, 'P', '0') + ');\n';
  };
  F['zk_music_reset'] = function () { return 'S.music.reset();\n'; };

  /* ---- 拓展板 M 口灯 ---- */
  F['zk_parrot_led_bright'] = function (b) {
    return 'S.parrot.led(' + JSON.stringify(b.getFieldValue('M') || 'MOTOR_1') + ', ' +
      v(b, 'B', '50') + ');\n';
  };

  /* ⚠️ Boolean 输出块必须返回 [code, ATOM] tuple，
     否则接在条件判断里会抛「Expecting tuple from value block」 */
  F['zk_front_has'] = function (b) {
    return ['S.stage.frontHas(' + v(b, 'CM', '30') + ', ' +
      JSON.stringify(b.getFieldValue('KIND') || 'ANY') + ')', ATOM];
  };
  F['zk_el_walk'] = function (b) {
    return 'await S.stage.walkTo(' + JSON.stringify(b.getFieldValue('EL') || '') + ', ' +
      v(b, 'Y', '430') + ');\n';
  };
  F['zk_el_walk_done'] = function (b) {
    return ['S.stage.walkDone(' + JSON.stringify(b.getFieldValue('EL') || '') + ')', ATOM];
  };

  /* ---------- 送餐机器人 ---------- */
  F['zk_robot_go'] = function (b) {
    return b.getFieldValue('ACT') === 'stop' ? 'S.robot.stop();\n' : 'S.robot.go();\n';
  };
  F['zk_robot_speed'] = function (b) { return 'S.robot.speed(' + v(b, 'V', '60') + ');\n'; };
  F['zk_robot_ground'] = function () { return ['S.robot.ground()', ATOM]; };
  F['zk_robot_dist'] = function () { return ['S.robot.dist()', ATOM]; };
  F['zk_robot_cam'] = function () { return ['S.robot.cam()', ATOM]; };
  F['zk_robot_asr'] = function () { return ['S.robot.asr()', ATOM]; };

  /* ---------- 巡线小车（第十四轮） ---------- */
  F['zk_trace_motor'] = function (b) {
    return "S.trace.motor('" + b.getFieldValue('DIR') + "', " + v(b, 'S', '60') + ');\n';
  };
  F['zk_trace_auto'] = function (b) {
    return 'S.trace.auto(' + (b.getFieldValue('ACT') === 'on' ? 'true' : 'false') + ');\n';
  };
  F['zk_trace_line'] = function () { return ['S.trace.line()', ATOM]; };
  F['zk_trace_dist'] = function () { return ['S.trace.dist()', ATOM]; };

  /* ---------- 变量 / 列表（镜像到 S 供舞台监视器显示） ---------- */
  function varInfo(b) {
    var f = b.getField('VAR');
    /* 【第四十一轮修正】Blockly 10 的 FieldVariable 把变量模型存在
       f.variable 上（不是旧版的 f.variable_），读错属性会拿到 undefined，
       于是变量名退化成内部 id（id_v1），监视器上显示成一串乱码。 */
    var model = f && (f.variable || f.variable_);
    var varName = b.getFieldValue('VAR');   // 触发 nameDB 注册（标准模式）
    var name = model ? model.name : varName;
    var type = model ? model.type : '';
    var codeName = JS.nameDB_ ? JS.nameDB_.getName(varName, Blockly.Names.NameType.VARIABLE) : ('v_' + varName);
    return { name: name, type: type, codeName: codeName };
  }
  F['variables_set'] = function (b) {
    var info = varInfo(b);
    var val = v(b, 'VALUE', info.type === 'LIST' ? '[]' : '0');
    return info.codeName + ' = ' + val + '; S.varSet(' + JSON.stringify(info.name) + ', ' +
      info.codeName + ', ' + JSON.stringify(info.type || 'scalar') + ');\n';
  };
  F['variables_get'] = function (b) {
    var info = varInfo(b);
    return [info.codeName, ATOM];
  };
  F['math_change'] = function (b) {
    var info = varInfo(b);
    var d = v(b, 'DELTA', '1');
    return info.codeName + ' = (Number(' + info.codeName + ')||0) + ' + d + '; S.varSet(' +
      JSON.stringify(info.name) + ', ' + info.codeName + ', "scalar");\n';
  };
  F['text_append'] = function (b) {
    var info = varInfo(b);
    var t = v(b, 'TEXT', '""');
    return info.codeName + ' = String(' + info.codeName + ' == null ? "" : ' + info.codeName +
      ') + ' + t + '; S.varSet(' + JSON.stringify(info.name) + ', ' + info.codeName + ', "scalar");\n';
  };
  F['zk_var_show'] = function (b) { return 'S.showVar(' + JSON.stringify(varInfo(b).name) + ');\n'; };
  F['zk_var_hide'] = function (b) { return 'S.hideVar(' + JSON.stringify(varInfo(b).name) + ');\n'; };
  F['zk_list_show'] = function (b) { return 'S.showList(' + JSON.stringify(varInfo(b).name) + ');\n'; };
  F['zk_list_hide'] = function (b) { return 'S.hideList(' + JSON.stringify(varInfo(b).name) + ');\n'; };
  F['zk_list_clear'] = function (b) { return 'S.listClear(' + v(b, 'LIST', '[]') + ');\n'; };
  F['zk_list_contains'] = function (b) {
    return ['S.listContains(' + v(b, 'LIST', '[]') + ', ' + v(b, 'ITEM', '""') + ')', ATOM];
  };

  /* ---------- 通讯网络 ---------- */
  F['zk_wifi_connect'] = function (b) {
    return 'await S.wifiConnect(' + v(b, 'SSID', '""') + ', ' + v(b, 'PWD', '""') + ');\n';
  };
  F['zk_wifi_ok'] = function () { return ['S.wifiOk()', ATOM]; };
  F['zk_radio_group'] = function (b) { return 'S.radioGroup(' + v(b, 'G', '7') + ');\n'; };
  F['zk_radio_send'] = function (b) { return 'await S.radioSend(' + v(b, 'MSG', '""') + ');\n'; };
  F['zk_radio_msg'] = function () { return ['S.radioMsg()', ATOM]; };
  /* 第四十五轮：语句版广播消息（官方 mxml 用） */
  F['zk_radio_msg_do'] = function (b) {
    return 'S.print("广播内容:", S.radioMsg());\n';
  };
  F['zk_ntp_sync'] = function () { return 'await S.ntpSync();\n'; };
  F['zk_time_now'] = function (b) { return ['S.timeNow("' + b.getFieldValue('K') + '")', ATOM]; };
  F['zk_mqtt_connect'] = function (b) {
    return 'await S.mqttConnect(' + v(b, 'HOST', '""') + ', ' + v(b, 'PORT', '1883') + ');\n';
  };
  F['zk_mqtt_pub'] = function (b) {
    return 'await S.mqttPub(' + v(b, 'TOPIC', '""') + ', ' + v(b, 'MSG', '""') + ');\n';
  };
  F['zk_mqtt_msg'] = function () { return ['S.mqttMsg()', ATOM]; };
  /* 第四十五轮：语句版 MQTT 消息（官方 mxml 用） */
  F['zk_mqtt_msg_do'] = function (b) {
    return 'S.print("MQTT 消息:", S.mqttMsg());\n';
  };
  F['zk_asr_text'] = function () { return ['S.asrText()', ATOM]; };

  /* ---------- 第二十四轮：AI 语音转文字 + 语音合成 ---------- */
  F['zk_speech_recognize'] = function (b) {
    var c = b.getFieldValue('CMD') || '';
    return 'await S.speechRecognize("' + c.replace(/"/g, '') + '");\n';
  };
  F['zk_speech_text'] = function () { return ['S.speechText()', ATOM]; };
  F['zk_speech_conf'] = function () { return ['S.speechConf()', ATOM]; };
  F['zk_speech_is'] = function (b) {
    return ['S.speechIs("' + String(b.getFieldValue('CMD') || '').replace(/"/g, '') + '")', ATOM];
  };
  F['zk_speech_speak'] = function (b) {
    return 'await S.speechSpeak(' + v(b, 'TEXT', '""') + ', ' +
      (b.getFieldValue('RATE') || '1') + ', ' +
      (b.getFieldValue('PITCH') || '1') + ', ' +
      (b.getFieldValue('VOL') || '1') + ');\n';
  };
  F['zk_speech_stop'] = function () { return 'S.speechStop();\n'; };
  F['zk_speech_speaking'] = function () { return ['S.speechSpeaking()', ATOM]; };
  F['zk_speech_done'] = function () { return ['S.speechDone()', ATOM]; };
  F['zk_weather'] = function (b) {
    return ['S.weather(' + v(b, 'CITY', '"北京"') + ', "' + b.getFieldValue('K') + '")', ATOM];
  };

  /* ---------- 自制积木（手动顶层编译，普通链中不输出） ---------- */
  F['zk_my_def'] = function () { return ''; };
  F['zk_my_call'] = function (b) {
    var spec = b.spec_ || { items: [] };
    var args = ZKB.MyBlocks.argsOf(spec);
    var parts = args.map(function (it, i) {
      return v(b, 'ARG' + i, it.type === 'bool' ? 'false' : '0');
    });
    return "await S.call('" + (b.defId_ || '') + "', [" + parts.join(', ') + ']);\n';
  };

  /* ---------- 事件帽子（手动编译，此处占位避免误入普通链） ---------- */
  ['zk_when_start', 'zk_when_btn', 'zk_when_touch', 'zk_when_shake', 'zk_when_ir',
    'zk_when_radio', 'zk_when_mqtt'].forEach(function (t) {
    F[t] = function () { return ''; };
  });

  /* 自制积木定义 → S.def(id, 异步函数)；形参可回写到连接的同名变量 */
  function myDefSim(block) {
    var spec = block.spec_ || { items: [], name: '我的积木' };
    var args = ZKB.MyBlocks.argsOf(spec);
    var prelude = args.map(function (it, i) {
      var inp = block.getInput('ARG' + i);
      var conn = inp && inp.connection.targetConnection;
      if (conn && conn.sourceBlock_ && conn.sourceBlock_.type === 'variables_get') {
        var f = conn.sourceBlock_.getField('VAR');
        /* 【第四十一轮修正】模型在 f.variable 上，旧代码读的是 f.variable_ */
        var vm = f && (f.variable || f.variable_);
        if (vm) {
          return '  S.varSet(' + JSON.stringify(vm.name) + ', a' + i + ', ' +
            JSON.stringify(vm.type || 'scalar') + ');';
        }
      }
      return '';
    }).filter(Boolean).join('\n');
    var body = prelude + (prelude ? '\n' : '') +
      (block.getNextBlock() ? JS.blockToCode(block.getNextBlock()) : '');
    return "S.def('" + block.id + "', async function (" +
      args.map(function (_, i) { return 'a' + i; }).join(', ') + ') {\n' + body + '});';
  }

  /* ============================================================
   * mPython 扩展 API：音乐 / 集合 / 文件 / 串口 / 扩展板 / NeoPixel
   * ============================================================ */
  F['zk_music_tempo'] = function (b) {
    return 'S.music.tempo(' + v(b, 'BPM', '120') + ');\n';
  };
  F['zk_music_get_tempo'] = function () { return 'S.music.tempo()'; };

  function splitItems(b) {
    var raw = b.getFieldValue('ITEMS') || '';
    return raw.split(/[,，]/).map(function (s) { return s.trim(); })
      .filter(Boolean).map(function (s) {
        return /^-?\d+(\.\d+)?$/.test(s) ? s : JSON.stringify(s);
      });
  }
  F['zk_set_create'] = function (b) { return 'new Set([' + splitItems(b).join(', ') + '])'; };
  F['zk_set_add'] = function (b) {
    return 'S.data.setAdd(' + v(b, 'SET') + ', ' + v(b, 'V', 'null') + ');\n';
  };
  F['zk_tuple_create'] = function (b) {
    var its = splitItems(b);
    return '(' + its.join(', ') + (its.length === 1 ? ',)' : ')');
  };
  F['zk_file_write'] = function (b) {
    return 'S.file.write(' + JSON.stringify(b.getFieldValue('PATH') || '/sd/test.txt') + ', ' +
      v(b, 'TXT', '""') + ');\n';
  };
  F['zk_file_read'] = function (b) {
    return 'S.file.read(' + JSON.stringify(b.getFieldValue('PATH') || '/sd/test.txt') + ')';
  };
  F['zk_uart_write'] = function (b) {
    return 'S.uart.write(' + (b.getFieldValue('UART') || 1) + ', ' + v(b, 'TXT', '""') + ');\n';
  };
  F['zk_uart_read'] = function (b) { return 'S.uart.read(' + (b.getFieldValue('UART') || 1) + ')'; };
  F['zk_parrot_speed'] = function (b) {
    return 'S.parrot.setSpeed(' + b.getFieldValue('MOTOR') + ', ' + v(b, 'SPD', '0') + ');\n';
  };
  /* 第四十五轮：停止扩展板电机（官方 mxml 用） */
  F['zk_parrot_stop'] = function () {
    return 'S.parrot.setSpeed("MOTOR_1", 0);\nS.parrot.setSpeed("MOTOR_2", 0);\n';
  };
  F['zk_parrot_get'] = function (b) { return 'S.parrot.getSpeed(' + b.getFieldValue('MOTOR') + ')'; };
  F['zk_parrot_led'] = function (b) {
    var m = b.getFieldValue('MOTOR');
    if (b.getFieldValue('ACT') === 'on') return 'S.parrot.led(' + m + ', ' + v(b, 'BR', '50') + ');\n';
    return 'S.parrot.ledOff(' + m + ');\n';
  };
  F['zk_neopixel_fill'] = function (b) {
    return 'S.neopixel.fill([' + v(b, 'R', '0') + ', ' + v(b, 'G', '0') + ', ' + v(b, 'B', '0') + ']);\n';
  };
  /* 第四十五轮修正：值积木要返回 [代码, 类型] 元组，
     原来返回裸字符串，Blockly 会抛
     "Expecting tuple from value block: zk_time_tick" */
  F['zk_time_tick'] = function () { return ['S.elapsed()', ATOM]; };

  /* ============================================================
   * DFRobot 新增硬件 → 仿真 JS（多实例：首参数为设备序号）
   * ============================================================ */
  F['zk_tracker_read'] = function (b) {
    return ['S.ext.tracker.read(' + inst(b) + ', ' +
      JSON.stringify(b.getFieldValue('CH') || 'C') + ')', ATOM];
  };
  F['zk_tracker_state'] = function (b) {
    return ['S.ext.tracker.state(' + inst(b) + ')', ATOM];
  };
  F['zk_power_read'] = function (b) {
    return 'S.ext.power.read(' + inst(b) + ', ' + JSON.stringify(b.getFieldValue('K') || 'v') + ')';
  };
  F['zk_gravity_read'] = function (b) {
    return 'S.ext.gravity.read(' + inst(b) + ', ' + JSON.stringify(b.getFieldValue('K') || 'l') + ')';
  };
  F['zk_angle_read'] = function (b) { return 'S.ext.angle.read(' + inst(b) + ')'; };
  F['zk_ir_send'] = function (b) {
    return 'S.ext.ir.send(' + inst(b) + ', ' + v(b, 'CODE', '0') + ');\n';
  };
  F['zk_ir_receive'] = function (b) { return 'S.ext.ir.receive(' + inst(b) + ')'; };
  F['zk_relay'] = function (b) {
    return 'S.ext.relay.set(' + inst(b) + ', ' + b.getFieldValue('ACT') + ');\n';
  };
  F['zk_led_brightness'] = function (b) {
    return 'S.ext.led.brightness(' + inst(b) + ', ' + v(b, 'V', '0') + ');\n';
  };
  /* 第三十五轮：LED 开关 / 亮度 / 状态 */
  F['zk_led_on'] = function (b) {
    return 'S.ext.led.on(' + inst(b) + ', "' + (b.getFieldValue('PORT') || 'led') + '");\n';
  };
  F['zk_led_off'] = function (b) {
    return 'S.ext.led.off(' + inst(b) + ', "' + (b.getFieldValue('PORT') || 'led') + '");\n';
  };
  F['zk_led_bright_set'] = function (b) {
    return 'S.ext.led.setBright(' + inst(b) + ', "' + (b.getFieldValue('PORT') || 'led') + '", ' +
      v(b, 'V', '50') + ');\n';
  };
  F['zk_led_is_on'] = function (b) {
    return ['S.ext.led.isOn(' + inst(b) + ', "' + (b.getFieldValue('PORT') || 'led') + '")', ATOM];
  };
  F['zk_led_get_bright'] = function (b) {
    return ['S.ext.led.getBright(' + inst(b) + ', "' + (b.getFieldValue('PORT') || 'led') + '")', ATOM];
  };
  F['zk_rgb_strip'] = function (b) {
    return 'S.ext.strip.set(' + inst(b) + ', ' + v(b, 'I', '1') + ', [' + v(b, 'R', '0') + ', ' +
      v(b, 'G', '0') + ', ' + v(b, 'B', '0') + ']);\n';
  };
  F['zk_rgb_strip_all'] = function (b) {
    return 'S.ext.strip.fill(' + inst(b) + ', [' + v(b, 'R', '0') + ', ' + v(b, 'G', '0') + ', ' + v(b, 'B', '0') + ']);\n';
  };
  F['zk_rgb_strip_off'] = function (b) {
    return 'S.ext.strip.off(' + inst(b) + ', ' + v(b, 'I', '0') + ');\n';
  };
  F['zk_rgb_strip_rainbow'] = function (b) {
    return 'S.ext.strip.chase(' + inst(b) + ', ' + v(b, 'START', '1') + ', ' + v(b, 'N', '6') + ', ' +
      v(b, 'MS', '120') + ');\n';
  };
  F['zk_remote_key'] = function (b) {
    return 'S.ext.remote.press(' + inst(b) + ', ' + JSON.stringify(b.getFieldValue('DIR') || 'up') + ');\n';
  };
  F['zk_remote_dir'] = function (b) { return 'S.ext.remote.dir(' + inst(b) + ')'; };
  F['zk_buzzer'] = function (b) {
    return 'S.ext.buzzer.set(' + b.getFieldValue('ACT') + ');\n';
  };

  /* ============================================================
   * 编译入口
   * ============================================================ */
  ZKB.genSim = function (workspace) {
    JS.init(workspace);

    var parts = [];
    var chainCode = function (block) { return block ? JS.blockToCode(block) : ''; };

    /* 变量初始化：局部变量与 S 镜像共享引用（列表必须先赋 []，否则列表积木操作 undefined 报错）；
       新建变量默认在舞台显示（Scratch 行为），可用"隐藏变量/隐藏列表"积木关闭 */
    var initParts = [];
    workspace.getAllVariables().forEach(function (vm) {
      var cn = JS.nameDB_ ? JS.nameDB_.getName(vm.name, Blockly.Names.NameType.VARIABLE)
                         : ('v_' + vm.name);
      if (vm.type === 'LIST') {
        initParts.push(
          'S.varSet(' + JSON.stringify(vm.name) + ', [], "LIST");\n' +
          cn + ' = S.varGet(' + JSON.stringify(vm.name) + ');\n' +
          'S.showList(' + JSON.stringify(vm.name) + ');');
      } else {
        initParts.push(
          'S.varSet(' + JSON.stringify(vm.name) + ', 0, "scalar");\n' +
          cn + ' = 0;\n' +
          'S.showVar(' + JSON.stringify(vm.name) + ');');
      }
    });

    /* 自制积木定义先注册 */
    var defParts = ZKB.MyBlocks.allDefs(workspace).map(myDefSim).filter(Boolean);

    workspace.getTopBlocks(true).forEach(function (top) {
      var t = top.type, code = '';
      if (t === 'zk_when_start') {
        code = 'S.task(async function () {\n' + chainCode(top.getNextBlock()) + '});';
      } else if (t === 'zk_when_btn') {
        code = 'S.on("button' + top.getFieldValue('BTN') + '", async function () {\n' +
          chainCode(top.getNextBlock()) + '});';
      } else if (t === 'zk_when_touch') {
        code = 'S.on("touch' + top.getFieldValue('PAD') + '", async function () {\n' +
          chainCode(top.getNextBlock()) + '});';
      } else if (t === 'zk_when_shake') {
        code = 'S.on("shake", async function () {\n' + chainCode(top.getNextBlock()) + '});';
      } else if (t === 'zk_when_ir') {
        code = 'S.on("ir", async function () {\n' + chainCode(top.getNextBlock()) + '});';
      } else if (t === 'zk_when_radio') {
        code = 'S.on("radio", async function () {\n' + chainCode(top.getNextBlock()) + '});';
      } else if (t === 'zk_when_mqtt') {
        code = 'S.onMqtt(' + v(top, 'TOPIC', '""') + ', async function () {\n' +
          chainCode(top.getNextBlock()) + '});';
      } else if (t === 'zk_my_def') {
        /* 已在 defParts 中处理 */
      } else if (top.outputConnection && !top.previousConnection && !top.nextConnection) {
        /* 第三十六轮：顶层「纯值积木」（只拖到画布、没接进任何输入口）。
           直接走 Blockly 的 blockToCode 会产出 `_dht_dew(),99` 这种
           带类型编号后缀的孤立表达式，拷到真机上直接语法报错。
           这里改用我们自己的 forBlock，取出干净的表达式。 */
        var f = F[t];
        if (typeof f === 'function') {
          /* 【第四十一轮修正】Blockly 内置的生成器签名是 (block, generator)，
             只传 block 会让 generator 为 undefined，列表类积木
             （lists_length 等）直接抛错、整个代码生成中断。
             我们的自定义生成器只用第一个参数，多传一个无副作用。 */
          var r = f(top, JS);
          if (Array.isArray(r)) r = r[0];
          code = (r == null ? '' : String(r));
        }
      } else {
        code = JS.blockToCode(top);
      }
      if (code) parts.push(code);
    });

    var raw = 'S.reset();\n' + initParts.join('\n') + '\n' +
      (defParts.length ? defParts.join('\n') + '\n' : '') +
      parts.join('\n') + '\nS.afterStarted();\n';
    return JS.finish(raw);
  };

})(window);
