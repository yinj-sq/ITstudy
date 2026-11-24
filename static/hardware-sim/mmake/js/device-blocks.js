/* ============================================================
 * js/device-blocks.js —— 拓展设备积木补全（第三十六轮）
 *
 * 背景：对照「积木规范」目录里的官方资料
 *   · mPythonSoftware-docs-master/source/blocks/*.rst
 *     （rgb / light / button / NeoPixel / expandBoard / oled / music …）
 *   · mpython-master（固件与 API 源码）
 *   · mpython-esp32s3-doc-latest（掌控板 3.0 文档）
 *   · MicroPython 官方文档
 * 逐个设备补齐「读取 / 设置 / 状态 / 动作」四类积木，
 * 让课堂上常见的操作不必绕道写 .py。
 *
 * 每个积木都同步三处：
 *   1) 本文件：定义
 *   2) js/gen-sim.js：虚拟仿真代码
 *   3) js/gen-python.js：真机 .py 代码
 *
 * ⚠ 约定：数值输入口的预填值写在 js/toolbox.js 的 SHADOW_XML 里，
 *   不要在 init() 里用 connection.setShadowDom()（会让 Zelos 渲染崩溃）。
 * ============================================================ */
(function (global) {
  'use strict';
  var ZKB = global.ZKB = global.ZKB || {};
  var Blockly = global.Blockly;
  if (!Blockly || !Blockly.Blocks) return;

  var C = ZKB.COLORS || {};

  /* 设备实例下拉：部分设备只允许 1 个实例，不加下拉 */
  function def(type, json, extra) {
    if (Blockly.Blocks[type]) return;   /* 已有定义不覆盖 */
    Blockly.Blocks[type] = {
      init: function () {
        this.jsonInit(json);
        if (extra) extra.call(this);
      }
    };
  }

  /* ============================================================
   * 一、RGB 灯模块（板载 WS2812 三灯珠）
   * 官方 API：rgb[n] = (r,g,b)、rgb.write()、rgb.fill((r,g,b))
   * ============================================================ */

  /* 读取某颗灯珠当前颜色（返回 R 分量，便于做「灯是什么颜色」的判断） */
  def('zk_rgb_get', {
    message0: '彩灯 %1 的 %2 分量',
    args0: [
      { type: 'field_dropdown', name: 'N', options: ZKB.RGB_OPTIONS },
      { type: 'field_dropdown', name: 'C', options: [
        ['红', 'r'], ['绿', 'g'], ['蓝', 'b']
      ] }
    ],
    output: 'Number', colour: C.rgb,
    tooltip: '读出某颗灯珠当前的颜色分量（0~255）'
  });

  /* 读取彩灯亮度 */
  def('zk_rgb_get_brightness', {
    message0: '彩灯亮度（0~100）',
    args0: [], output: 'Number', colour: C.rgb,
    tooltip: '读回当前设置的彩灯亮度百分比'
  });

  /* 全部灯珠填充同一个颜色 */
  def('zk_rgb_fill', {
    message0: '所有彩灯设为 %1',
    args0: [{ type: 'field_colour', name: 'COLOR', colour: '#ff0000' }],
    previousStatement: null, nextStatement: null, colour: C.rgb, inputsInline: true,
    tooltip: '一次把 3 颗灯珠全部设成同一种颜色（官方 rgb.fill）'
  });

  /* 用 R/G/B 数值填满全部灯珠 */
  def('zk_rgb_fill_rgb', {
    message0: '所有彩灯设为 红%1 绿%2 蓝%3',
    args0: [
      { type: 'input_value', name: 'R', check: 'Number' },
      { type: 'input_value', name: 'G', check: 'Number' },
      { type: 'input_value', name: 'B', check: 'Number' }
    ],
    previousStatement: null, nextStatement: null, colour: C.rgb, inputsInline: true,
    tooltip: '按 0~255 的三通道数值填充全部灯珠'
  });

  /* 熄灭单颗灯珠 */
  def('zk_rgb_off_one', {
    message0: '关闭彩灯 %1',
    args0: [{ type: 'field_dropdown', name: 'N', options: ZKB.RGB_OPTIONS }],
    previousStatement: null, nextStatement: null, colour: C.rgb,
    tooltip: '只关掉指定的那一颗灯珠'
  });

  /* ============================================================
   * 二、按键模块（外接轻触按键）
   * ============================================================ */
  def('zk_ext_btn_pressed', {
    message0: '按键被按下？',
    args0: [], output: 'Boolean', colour: C.extbtn,
    tooltip: '读按键当前是否被按住（松开为否）'
  });
  def('zk_ext_btn_count', {
    message0: '按键被按下的次数',
    args0: [], output: 'Number', colour: C.extbtn,
    tooltip: '从程序开始到现在累计按了多少次'
  });
  def('zk_ext_btn_reset', {
    message0: '清零按键计数',
    args0: [], previousStatement: null, nextStatement: null, colour: C.extbtn,
    tooltip: '把按键计数清零，便于分阶段统计'
  });

  /* ============================================================
   * 三、光线传感器
   * 官方 API：light.read() 返回 0~4095
   * ============================================================ */
  def('zk_light_raw', {
    message0: '光线传感器原始值（0~4095）',
    args0: [], output: 'Number', colour: C.light,
    tooltip: 'ADC 原始读数，越大越亮'
  });
  def('zk_light_pct', {
    message0: '光照强度百分比（0~100%）',
    args0: [], output: 'Number', colour: C.light,
    tooltip: '把 0~4095 换算成百分比，便于和阈值比较'
  });
  def('zk_light_bright', {
    message0: '光线是否充足？',
    args0: [], output: 'Boolean', colour: C.light,
    tooltip: '超过中等亮度（约 2048）时为真'
  });

  /* ============================================================
   * 四、直流电机 / 马达（拓展板 M1 / M2）
   * 官方 API：parrot.set_speed(MOTOR_1, speed)、parrot.get_speed()
   * ============================================================ */
  def('zk_motor_stop', {
    message0: '停止所有电机',
    args0: [], previousStatement: null, nextStatement: null, colour: C.motor,
    tooltip: '把 M1 / M2 两个电机都停转'
  });
  def('zk_motor_get_speed', {
    message0: '%1 当前速度（-100~100）',
    args0: [{ type: 'field_dropdown', name: 'M', options: [
      ['M1 电机', 'MOTOR_1'], ['M2 电机', 'MOTOR_2']
    ] }],
    output: 'Number', colour: C.motor,
    tooltip: '读回某个电机的当前速度（正为正转、负为反转）'
  });
  def('zk_motor_set', {
    message0: '%1 速度设为 %2 （-100~100）',
    args0: [
      { type: 'field_dropdown', name: 'M', options: [
        ['M1 电机', 'MOTOR_1'], ['M2 电机', 'MOTOR_2']
      ] },
      { type: 'input_value', name: 'S', check: 'Number' }
    ],
    previousStatement: null, nextStatement: null, colour: C.motor, inputsInline: true,
    tooltip: '直接设定速度：正数正转、负数反转、0 停止'
  });

  /* ============================================================
   * 五、气压传感器（BMP280 / SPL06_001）
   * 官方模块：bme280 / spl06_001
   * ============================================================ */
  def('zk_pressure_pa', {
    message0: '大气压强（Pa）',
    args0: [], output: 'Number', colour: C.baro,
    tooltip: '原始压强单位（帕）'
  });
  def('zk_temp', {
    message0: '温度（℃）',
    args0: [], output: 'Number', colour: C.baro,
    tooltip: '气压传感器自带的温度读数'
  });
  def('zk_pressure_hpa', {
    message0: '大气压强（hPa）',
    args0: [], output: 'Number', colour: C.baro,
    tooltip: '百帕，1 hPa = 100 Pa，是天气预报里常用的单位'
  });

  /* ============================================================
   * 六、舵机
   * ============================================================ */
  def('zk_servo_get', {
    message0: '舵机当前角度（度）',
    args0: [], output: 'Number', colour: C.servo,
    tooltip: '读回舵机现在停在哪一度'
  });
  def('zk_servo_off', {
    message0: '舵机断电',
    args0: [], previousStatement: null, nextStatement: null, colour: C.servo,
    tooltip: '停止输出脉冲，舵机保持当前位置不再受力'
  });

  /* ============================================================
   * 七、超声波传感器（HC-SR04）
   * ============================================================ */
  def('zk_ultra_cm', {
    message0: '超声波距离（厘米）',
    args0: [], output: 'Number', colour: C.ultra,
    tooltip: '测量到障碍物的距离'
  });
  def('zk_ultra_mm', {
    message0: '超声波距离（毫米）',
    args0: [], output: 'Number', colour: C.ultra,
    tooltip: '同一个测量值的毫米单位'
  });
  def('zk_ultra_near', {
    message0: '前方 %1 厘米内有障碍物？',
    args0: [{ type: 'input_value', name: 'CM', check: 'Number' }],
    output: 'Boolean', colour: C.ultra,
    tooltip: '距离小于设定值时为真（避障、判断是否靠近常用）'
  });

  /* ============================================================
   * 八、人体红外传感器（PIR / 红外人体感应）
   * ============================================================ */
  def('zk_pir', {
    message0: '检测到人体？',
    args0: [], output: 'Boolean', colour: C.ir,
    tooltip: '人体红外感应到有人时为真（需先在「拓展」里添加红外人体传感器）'
  });
  def('zk_pir_count', {
    message0: '检测到人体的次数',
    args0: [], output: 'Number', colour: C.ir,
    tooltip: '累计感应到人的次数'
  });
  def('zk_pir_reset', {
    message0: '清零人体计数',
    args0: [], previousStatement: null, nextStatement: null, colour: C.ir,
    tooltip: '把人体感应计数清零'
  });

  /* ============================================================
   * 九、温湿度传感器（DHT11 / DHT22）
   * ============================================================ */
  def('zk_dht_temp', {
    message0: '温度（℃）',
    args0: [], output: 'Number', colour: C.dht,
    tooltip: '直接读温度（等价于「温湿度传感器的 温度」）'
  });
  def('zk_dht_hum', {
    message0: '湿度（%）',
    args0: [], output: 'Number', colour: C.dht,
    tooltip: '直接读湿度（等价于「温湿度传感器的 湿度」）'
  });
  def('zk_dht_dew', {
    message0: '露点（℃）',
    args0: [], output: 'Number', colour: C.dht,
    tooltip: '由温度与湿度算出的露点，用于判断是否结露'
  });
  def('zk_dht_ok', {
    message0: '温湿度读取成功？',
    args0: [], output: 'Boolean', colour: C.dht,
    tooltip: 'DHT 传感器偶尔会读失败，可先用它判断数据是否有效'
  });

  /* ============================================================
   * 十、土壤湿度传感器
   * ============================================================ */
  def('zk_soil_wet', {
    message0: '土壤是否湿润？',
    args0: [], output: 'Boolean', colour: C.soil,
    tooltip: '含水量高于中等值（约 50%）时为真'
  });
  def('zk_soil_raw', {
    message0: '土壤湿度原始值（0~4095）',
    args0: [], output: 'Number', colour: C.soil,
    tooltip: 'ADC 原始读数'
  });

  /* ============================================================
   * 十一、LED 灯带（RGB 灯带，16 颗）
   * ============================================================ */
  def('zk_strip_count', {
    message0: '灯带总颗数',
    args0: [], output: 'Number', colour: C.rgb,
    tooltip: '灯带有多少颗灯珠（16 颗）'
  });
  def('zk_strip_get', {
    message0: '灯带第 %1 颗的 %2 分量',
    args0: [
      { type: 'input_value', name: 'I', check: 'Number' },
      { type: 'field_dropdown', name: 'C', options: [
        ['红', 'r'], ['绿', 'g'], ['蓝', 'b']
      ] }
    ],
    output: 'Number', colour: C.rgb,
    tooltip: '读出某颗灯珠当前的颜色分量'
  });
  def('zk_strip_all_off', {
    message0: '灯带全部熄灭',
    args0: [], previousStatement: null, nextStatement: null, colour: C.rgb,
    tooltip: '一次关掉全部 16 颗灯珠'
  });
  def('zk_strip_rainbow_stop', {
    message0: '停止灯带跑马灯',
    args0: [], previousStatement: null, nextStatement: null, colour: C.rgb,
    tooltip: '停止正在播放的跑马灯效果'
  });

  /* ============================================================
   * 十二、水泵
   * ============================================================ */
  def('zk_pump_on', {
    message0: '水泵 %1',
    args0: [{ type: 'field_dropdown', name: 'V', options: [['打开', '1'], ['关闭', '0']] }],
    previousStatement: null, nextStatement: null, colour: C.pump,
    tooltip: '启动或停止水泵'
  });
  def('zk_pump_get_power', {
    message0: '水泵功率（0~100）',
    args0: [], output: 'Number', colour: C.pump,
    tooltip: '读回水泵当前的功率百分比'
  });
  def('zk_pump_flow', {
    message0: '水泵是否在流水？',
    args0: [], output: 'Boolean', colour: C.pump,
    tooltip: '水泵打开时为真'
  });

  /* ============================================================
   * 十三、PM2.5 传感器
   * ============================================================ */
  def('zk_pm25_value', {
    message0: 'PM2.5 浓度（μg/m³）',
    args0: [], output: 'Number', colour: C.pm25,
    tooltip: 'PM2.5 的实时浓度'
  });
  def('zk_pm25_good', {
    message0: '空气质量是否良好？',
    args0: [], output: 'Boolean', colour: C.pm25,
    tooltip: '浓度低于 35 μg/m³（优）时为真'
  });
  def('zk_pm25_harm', {
    message0: '空气质量是否超标？',
    args0: [], output: 'Boolean', colour: C.pm25,
    tooltip: '浓度高于 115 μg/m³（重度污染）时为真，可用来报警'
  });

  /* ============================================================
   * 十四、MP3 模块（DFRobot UART 音乐模块）
   * 复用已有的音乐库（ZKB.MusicLib）上传 / 内置曲目。
   * ============================================================ */
  def('zk_mp3_play', {
    message0: 'MP3 播放 %1',
    args0: [{ type: 'field_dropdown', name: 'NAME', options: function () {
      try { return ZKB.MusicLib ? ZKB.MusicLib.options() : [['（暂无曲目）', '']]; }
      catch (e) { return [['（暂无曲目）', '']]; }
    } }],
    previousStatement: null, nextStatement: null, colour: C.music, inputsInline: true,
    tooltip: '让 MP3 模块播放选中的曲目（曲目在「音乐素材」面板上传）'
  });
  def('zk_mp3_stop', {
    message0: 'MP3 停止播放',
    args0: [], previousStatement: null, nextStatement: null, colour: C.music,
    tooltip: '停止 MP3 播放'
  });
  def('zk_mp3_volume', {
    message0: 'MP3 音量设为 %1 （0~30）',
    args0: [{ type: 'input_value', name: 'V', check: 'Number' }],
    previousStatement: null, nextStatement: null, colour: C.music, inputsInline: true,
    tooltip: 'DFRobot MP3 模块的音量范围是 0~30'
  });
  def('zk_mp3_playing', {
    message0: 'MP3 正在播放？',
    args0: [], output: 'Boolean', colour: C.music,
    tooltip: '正在播放时为真'
  });
  def('zk_mp3_folder', {
    message0: 'MP3 播放文件夹 %1 中第 %2 首',
    args0: [
      { type: 'input_value', name: 'F', check: 'Number' },
      { type: 'input_value', name: 'N', check: 'Number' }
    ],
    previousStatement: null, nextStatement: null, colour: C.music, inputsInline: true,
    tooltip: '按「文件夹编号 / 曲目序号」播放 SD 卡里的 MP3'
  });

  /* ============================================================
   * 十五、拓展板通用（parrot 电机口 + 灯）
   * 官方 API：parrot.set_speed / get_speed / led_on / led_off
   * ============================================================ */
  def('zk_parrot_led_bright', {
    message0: '%1 口灯亮度设为 %2 （0~100）',
    args0: [
      { type: 'field_dropdown', name: 'M', options: [
        ['M1 口', 'MOTOR_1'], ['M2 口', 'MOTOR_2']
      ] },
      { type: 'input_value', name: 'B', check: 'Number' }
    ],
    previousStatement: null, nextStatement: null, colour: C.motor, inputsInline: true,
    tooltip: '拓展板电机口当灯用时的亮度（官方 parrot.led_on 的 brightness 参数）'
  });

  /* ============================================================
   * 十六、补充：掌控板 3.0 / MicroPython 官方 API 里还差的能力
   * 依据「积木规范」：
   *   · mpython-esp32s3-doc-latest（掌控板 3.0 文档）
   *     ds18x20.DS18X20（DS18B20 单总线温度传感器）
   *     ADC.ADC（通用模拟量读取）
   *     TouchPad.TouchPad（触摸板）
   *     music.pitch / music.reset
   *   · MicroPython 官方文档的常用类
   * ============================================================ */

  /* ---- DS18B20 单总线温度传感器 ---- */
  def('zk_ds18_temp', {
    message0: 'DS18B20 温度（℃）',
    args0: [], output: 'Number', colour: C.dht,
    tooltip: '单总线数字温度传感器（DS18B20）的读数，精度 0.5℃'
  });
  def('zk_ds18_ok', {
    message0: 'DS18B20 读取成功？',
    args0: [], output: 'Boolean', colour: C.dht,
    tooltip: '传感器未接好时读取会失败，可先用它判断'
  });

  /* ---- 通用 ADC 模拟量读取 ---- */
  def('zk_adc_read', {
    message0: 'ADC 读取引脚 %1（0~4095）',
    args0: [{ type: 'field_dropdown', name: 'PIN', options: [
      ['P1', '1'], ['P2', '2'], ['P3', '3'], ['P4', '4'],
      ['P10', '10'], ['P13', '13'], ['P14', '14']
    ] }],
    output: 'Number', colour: C.pin,
    tooltip: '用 ADC 类直接读模拟量（MicroPython 官方 ADC.ADC 用法）'
  });

  /* ---- 触摸板 ---- */
  def('zk_touchpad_read', {
    message0: '触摸板 %1 是否被触摸',
    args0: [{ type: 'field_dropdown', name: 'PAD', options: ZKB.TOUCH_OPTIONS }],
    output: 'Boolean', colour: C.key,
    tooltip: '读取触摸板对应焊盘的触摸状态（官方 TouchPad 用法）'
  });

  /* ---- 音乐音调（官方 music.pitch）---- */
  def('zk_music_pitch', {
    message0: '音乐音调设为 %1',
    args0: [{ type: 'input_value', name: 'P', check: 'Number' }],
    previousStatement: null, nextStatement: null, colour: C.music, inputsInline: true,
    tooltip: '设置乐曲的音调偏移（官方 music.pitch）'
  });
  def('zk_music_reset', {
    message0: '重置音乐播放状态',
    args0: [], previousStatement: null, nextStatement: null, colour: C.music,
    tooltip: '停止并复位音乐模块（官方 music.reset）'
  });


  /* 记录本轮新增的积木，供 toolbox / gen-sim / gen-python 对齐 */
  ZKB.DEVICE_BLOCKS_R36 = [
    'zk_rgb_get', 'zk_rgb_get_brightness', 'zk_rgb_fill', 'zk_rgb_fill_rgb', 'zk_rgb_off_one',
    'zk_ext_btn_pressed', 'zk_ext_btn_count', 'zk_ext_btn_reset',
    'zk_light_raw', 'zk_light_pct', 'zk_light_bright',
    'zk_motor_stop', 'zk_motor_get_speed', 'zk_motor_set',
    'zk_pressure_pa', 'zk_temp', 'zk_pressure_hpa',
    'zk_servo_get', 'zk_servo_off',
    'zk_ultra_cm', 'zk_ultra_mm', 'zk_ultra_near',
    'zk_pir', 'zk_pir_count', 'zk_pir_reset',
    'zk_dht_temp', 'zk_dht_hum', 'zk_dht_dew', 'zk_dht_ok',
    'zk_soil_wet', 'zk_soil_raw',
    'zk_strip_count', 'zk_strip_get', 'zk_strip_all_off', 'zk_strip_rainbow_stop',
    'zk_pump_on', 'zk_pump_get_power', 'zk_pump_flow',
    'zk_pm25_value', 'zk_pm25_good', 'zk_pm25_harm',
    'zk_mp3_play', 'zk_mp3_stop', 'zk_mp3_volume', 'zk_mp3_playing', 'zk_mp3_folder',
    'zk_parrot_led_bright',
    /* 十六、补充官方 API 能力 */
    'zk_ds18_temp', 'zk_ds18_ok', 'zk_adc_read', 'zk_touchpad_read',
    'zk_music_pitch', 'zk_music_reset'
  ];
})(window);
