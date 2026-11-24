/* ============================================================
 * toolbox.js —— 积木工具箱（动态生成：通用分类常驻，设备分类按需加载）
 * 变量 / 列表 / 自制积木 使用动态飞出分类（回调在 app.js 注册）：
 *   custom="ZKB_VARIABLE" / "ZKB_LIST" / "ZKB_PROC"
 * ============================================================ */
(function (global) {
  'use strict';
  var ZKB = global.ZKB || (global.ZKB = {});
  var C = ZKB.COLORS;

  function cat(name, colour, blocksXml, extra) {
    return '<category name="' + name + '" colour="' + colour + '" ' + (extra || '') + '>' + blocksXml + '</category>';
  }

  /* ============================================================
   * 预置数值默认值的积木（影子块写在工具箱 XML 里）
   *
   * Blockly 原生做法：把 <shadow> 作为 <value> 子节点写进积木 XML，
   * 拖出来就自带可编辑的数字（点一下即可改 0~255）。
   *
   * ⚠ 不能在 init() 里用 connection.setShadowDom() 预置：
   *   那样影子块没有真正的父积木，Blockly 的行内渲染器取不到
   *   field.getSvgRoot()，在无头环境（jsdom）里会直接抛异常。
   * ============================================================ */
  var SHADOW_XML = {
    zk_rgb_strip: [['I', '1'], ['R', '255'], ['G', '0'], ['B', '0']],
    zk_rgb_strip_all: [['R', '255'], ['G', '0'], ['B', '0']],
    zk_rgb_strip_off: [['I', '1']],
    zk_rgb_strip_rainbow: [['START', '1'], ['N', '8'], ['MS', '100']],
    /* 第三十五轮：层级积木的数字输入也改由工具箱带出
       （积木 init() 里不能用 setShadowDom，会让 Zelos 渲染崩溃） */
    zk_look_layern: [['N', '1']],
    /* 第三十六轮：运动模块「面向 N 度方向」的角度输入同样改由工具箱带出 */
    zk_mv_pointdir: [['D', '90']],
    /* 第三十六轮：拓展设备新积木的数值输入 */
    zk_motor_set: [['S', '60']],
    zk_ultra_near: [['CM', '30']],
    zk_strip_get: [['I', '1']],
    zk_mp3_volume: [['V', '15']],
    zk_mp3_folder: [['F', '1'], ['N', '1']],
    zk_parrot_led_bright: [['B', '50']],
    /* 第三十六轮：补充官方 API 能力的数值输入 */
    zk_music_pitch: [['P', '0']],
    /* 第三十七轮：LED 模块的亮度输入。
       zk_led_brightness / zk_led_bright_set 的 V 口是 input_value，
       但工具箱没带影子块，拖出来是个空口，学生没法直接填 0~100 的亮度，
       必须先去别处拖一块数字积木进来才能用。
       这里给它们带上 math_number 影子块，拖出即可点数字直接改。 */
    zk_led_brightness: [['V', '60']],
    zk_led_bright_set: [['V', '60']],
    /* 第三十六轮：逻辑「大小判断」积木的两侧。
       原来 Blockly 内置的 logic_compare 从工具箱拖出来时 A / B 是两个空口，
       学生必须先去别处找一块数字积木拖进去才能填数，
       课堂上经常卡在这里。给它带上 math_number 影子块，
       拖出来就能直接点数字改。 */
    logic_compare: [['A', '0'], ['B', '0']],
    /* 第四十五轮：把「拖出来是空口、必须再拖一块数字积木进去才能填」
       的积木一次性补齐 —— 学生拖出来就能直接点数字改。
       （影子块写在工具箱 XML 里，拖出来自带可编辑的默认值） */

    /* 控制模块：「重复执行 N 次」的次数
       controls_repeat_ext 的次数口是 input_value（空口），要带影子块；
       controls_repeat 用的是 field_number，本身就能直接点数字改，不用管。 */
    controls_repeat_ext: [['TIMES', '10']],

    /* 屏幕显示模块：绘图类积木的坐标 / 尺寸
       （口名以各积木定义里的 name 为准：
         横线用 W 表示长度、竖线用 L 表示长度、
         三角形用 X0/Y0/X1/Y1/X2/Y2、进度条用 P 表示进度、
         柱状条用 W 表示宽度） */
    zk_oled_text: [['T', '你好 掌控板', 'text'], ['X', '0'], ['Y', '0']],
    zk_oled_line: [['X1', '0'], ['Y1', '0'], ['X2', '60'], ['Y2', '30']],
    zk_oled_rect: [['X', '0'], ['Y', '0'], ['W', '40'], ['H', '20']],
    zk_oled_circle: [['X', '64'], ['Y', '32'], ['R', '16']],
    zk_oled_roundrect: [['X', '0'], ['Y', '0'], ['W', '40'], ['H', '20'], ['R', '4']],
    zk_oled_hline: [['X', '0'], ['Y', '32'], ['W', '60']],
    zk_oled_vline: [['X', '64'], ['Y', '0'], ['L', '32']],
    zk_oled_triangle: [['X0', '0'], ['Y0', '0'], ['X1', '30'], ['Y1', '0'], ['X2', '15'], ['Y2', '25']],
    zk_oled_progress: [['X', '0'], ['Y', '0'], ['W', '60'], ['H', '6'], ['P', '50']],
    zk_oled_stripbar: [['X', '0'], ['Y', '0'], ['W', '40'], ['H', '8'], ['P', '50']],
    zk_oled_pixel: [['X', '0'], ['Y', '0']],
    zk_oled_text_color_do: [['T', '你好', 'text'], ['X', '0'], ['Y', '0']],

    /* 掌控板模块：朗读内容 */
    zk_speech_speak: [['TEXT', '你好，我是掌控板', 'text']],
    /* 第四十六轮：逻辑模块的两个数值口积木。
       math_random_int 的口是 FROM / TO，
       math_constrain 的口是 VALUE / LOW / HIGH，
       全是 Blockly 内置积木，默认拖出来是三个空口，
       学生必须先去别处拖数字积木才能用。
       这里带上 math_number 影子块，拖出即可点数字直接改。 */
    math_random_int: [['FROM', '1'], ['TO', '10']],
    math_constrain: [['VALUE', '50'], ['LOW', '0'], ['HIGH', '100']],

    /* 第四十六轮：zk_constrain（把变量限制在最低值与最高值之间）
       第一个口是变量下拉（field_variable），不需要影子块；
       后两个口是数字口，带影子块让拖出来就能直接点数字改。 */
    zk_constrain: [['LOW', '0'], ['HIGH', '100']],

    /* 第四十六轮：拓展板（parrot）电机速度 / 灯亮度。
       它们的数值口是 input_value，工具箱没带影子块，
       拖出来是空口，学生没法直接填速度 / 亮度。 */
    zk_parrot_speed: [['SPD', '50']],
    zk_parrot_led: [['BR', '50']],

    /* 其它板载可输入数值的积木 */
    zk_tone: [['F', '440'], ['D', '0.5']],
    zk_music_tempo: [['BPM', '120']],
    zk_music_pitch: [['P', '0']]
  };
  function b(type) {
    var sh = SHADOW_XML[type];
    if (!sh) return '<block type="' + type + '"></block>';
    var inner = sh.map(function (p) {
      /* p = [口名, 默认值, 影子块类型(可选)] */
      var st = p[2] || 'math_number';
      var fld = st === 'math_number' ? '<field name="NUM">' + p[1] + '</field>'
        : (st === 'text' ? '<field name="TEXT">' + p[1] + '</field>'
          : '<field name="BOOL">' + p[1] + '</field>');
      return '<value name="' + p[0] + '"><shadow type="' + st + '">' +
        fld + '</shadow></value>';
    }).join('');
    return '<block type="' + type + '">' + inner + '</block>';
  }

  /* ============================================================
 * 分类结构（顺序即左侧显示顺序）：
 *   1. 控制     —— 事件 / 循环 / 等待 / 打印
 *   2. 逻辑     —— 条件 / 比较 / 运算 + 数学运算
 *   3. 屏幕显示 —— OLED 绘图 + 屏幕图片/表情
 *   4. 变量     —— 变量 + 列表（动态飞出）
 *   5. 掌控板   —— 板载资源 + 引脚IO + 扩展板(电机/灯/NeoPixel) + 已添加的传感/执行设备
 *   6. 高级     —— 文本 / 数据集合 / 文件串口 / 自制积木（默认折叠，点击展开）
 * ============================================================ */

  /* 通用分类（常驻） */
  function commonCategories() {
    return '' +
      /* ---- 1. 控制 ---- */
      cat('控制', C.control,
        b('zk_when_start') + b('zk_when_btn') + b('zk_when_touch') + b('zk_when_shake') +
        b('zk_wait_sec') + b('zk_wait_ms') +
        b('controls_repeat_ext') + b('controls_forever') +
        b('controls_whileUntil') + b('controls_for') +
        b('controls_flow_statements') + b('zk_print') +
        b('zk_time_tick')) +

      /* ---- 1-5. 运动（第三十轮，对齐 Scratch motion） ----
         方向 0°正上 / 90°正右 / 180°正下 / 270°正左，坐标以舞台中心为原点 */
      cat('运动', C.stage_motion,
        /* 位移（第三十五轮：前进 / 后退两块已删除，用「移动步数」+「方向设为」组合） */
        b('zk_mv_steps') +
        b('zk_mv_goto') + b('zk_mv_random') + b('zk_mv_glide') +
        /* 坐标读写 */
        b('zk_mv_changex') + b('zk_mv_changey') +
        b('zk_mv_setx') + b('zk_mv_sety') +
        b('zk_mv_x') + b('zk_mv_y') +
        /* 转向（第三十五轮：带方向盘的 zk_mv_face 已删除） */
        b('zk_mv_turnright') + b('zk_mv_turnleft') +
        b('zk_mv_pointdir') + b('zk_mv_pointto') + b('zk_mv_dir') +
        b('zk_mv_bounce')) +

      /* ---- 1-6. 外观（第三十轮，对齐 Scratch looks） ---- */
      cat('外观', C.stage_looks,
        b('zk_look_show') + b('zk_look_hide') + b('zk_look_visible') +
        b('zk_look_setsize') + b('zk_look_chsize') + b('zk_look_size') +
        b('zk_look_opacity') + b('zk_look_ghost') +
        b('zk_look_colorfx') + b('zk_look_cleareffects') +
        /* 叠放层级（第三十二轮从控制模块迁来，第三十五轮四块融合为一块下拉） */
        b('zk_look_layerop') + b('zk_look_layern') +
        b('zk_look_layer') + b('zk_look_layercount')) +

      /* ---- 2. 逻辑（含数学运算） ---- */
      cat('逻辑', C.logic,
        /* 第四十四轮：在「如果（）执行（）」下面加一块
           「如果（）执行（）否则（）」，
           用 Blockly 内置的 controls_ifelse（自带 else 分支）。
           原来只有 controls_if，学生想写「否则」还得拖 mutator 加分支，
           门槛太高。 */
        b('controls_if') + b('controls_ifelse') +
        b('logic_compare') + b('logic_operation') +
        b('logic_negate') + b('logic_boolean') + b('logic_null') + b('logic_ternary') +
        b('math_number') + b('math_arithmetic') + b('math_random_int') +
        /* 第四十六轮：「把（）限制在最低（）到最高（）之间」改用自建的
           zk_constrain —— 第一个口是**变量下拉**（不是数字口），
           后面两个口才可以直接输入数字。
           内置的 math_constrain 三个口全是数字口，改不了结构，
           它的定义仍保留（兼容老工程与官方 mxml 的 hunan_map）。 */
        b('zk_constrain') +
        /* 第四十九轮：区间映射（教材六年级「按量自动投喂器 / 声光贺卡」用） */
        b('zk_map_value') +
        b('math_modulo') + b('math_round') +
        b('math_number_property') + b('math_trig') + b('math_constant')) +

      /* ---- 3. 屏幕显示（含图片与表情） ---- */
      cat('屏幕显示', C.oled,
        /* 第四十八轮：把「清空屏幕」和「全屏 点亮/熄灭」合成一块
           「屏幕 %1」，下拉里有 清空 / 全亮 / 黑底 / 白底 四个选项。
           旧的两块积木定义仍在 blocks-defs 里（兼容老工程与官方 mxml），
           只是不再显示在工具箱。 */
        b('zk_oled_screen') +
        b('zk_oled_text') +
        b('zk_oled_pixel') + b('zk_oled_line') + b('zk_oled_rect') +
        b('zk_oled_circle') + b('zk_oled_invert') + b('zk_oled_show') +
        b('zk_oled_text_color') + b('zk_oled_text_color_do') +
        b('zk_oled_roundrect') + b('zk_oled_hline') + b('zk_oled_vline') +
        b('zk_oled_triangle') + b('zk_oled_progress') + b('zk_oled_stripbar') +
        /* 图片 / 表情（原「屏幕图片」分类，已合并） */
        b('zk_oled_image') + b('zk_oled_face')) +

      /* ---- 4. 变量（含列表，动态飞出） ---- */
      '<category name="变量" colour="' + C.variable + '" custom="ZKB_VARIABLE"></category>' +

      /* ---- 5. 掌控板（板载资源 + 引脚IO + 音乐 + 已添加设备） ---- */
      cat('掌控板', C.rgb,
        /* 第四十四轮：彩灯积木去重。
           原来有 6 块，实际只有 3 种能力：
             设置彩灯①为色  /  所有彩灯设为色      ← 重复
             彩灯①红绿蓝    /  所有彩灯设为红绿蓝  ← 重复
             关闭彩灯①      /  关闭全部彩灯        ← 重复
           现在统一成 3 块，靠下拉框里的「全部」选项区分单颗 / 全部：
             zk_rgb_one   彩灯[0号/1号/2号/全部] 设为 颜色
             zk_rgb_rgb   彩灯[0号/1号/2号/全部] 红R 绿G 蓝B
             zk_rgb_off_one  关闭彩灯[0号/1号/2号/全部]
           代码生成器本来就支持 'ALL'（走 rgb.fill / S.rgb.fill），
           所以不用改生成逻辑。旧积木定义保留在 blocks-defs / device-blocks
           里以兼容老工程，只是不再出现在工具箱。 */
        b('zk_rgb_one') + b('zk_rgb_rgb') + b('zk_rgb_off_one') +
        b('zk_rgb_brightness') +
        /* 第三十六轮：读取灯珠颜色 / 亮度 */
        b('zk_rgb_get') + b('zk_rgb_get_brightness') +
        b('zk_is_btn') + b('zk_is_touch') +
        b('zk_light') + b('zk_sound') + b('zk_accel') + b('zk_tilt') +
        /* 音乐：发声 / 音调 / 速度 / 内置与上传曲目播放
           第四十四轮：音调与「重置音乐播放状态」原本排在分类最末尾，
           离其它音乐积木很远，这里归拢到一起。 */
        b('zk_note') + b('zk_tone') + b('zk_music_stop') +
        b('zk_music_tempo') + b('zk_music_get_tempo') +
        b('zk_music_pitch') + b('zk_music_reset') + b('zk_music_play') +
        /* 第四十九轮：掌控板内置乐曲（music.BIRTHDAY 等，教材六年级示例用的） */
        b('zk_music_melody') +
        /* 第二十四轮：AI 语音转文字 + AI 语音合成（板载能力，无需拓展设备） */
        b('zk_speech_recognize') + b('zk_speech_text') +
        b('zk_speech_conf') + b('zk_speech_is') +
        b('zk_speech_speak') + b('zk_speech_stop') +
        b('zk_speech_speaking') + b('zk_speech_done') +
        /* 引脚：数字输入输出 / 模拟（PWM）输出 / 模拟输入 */
        b('zk_pin_dout') + b('zk_pin_pwm') + b('zk_pin_din') + b('zk_pin_ain') +
        /* 第三十六轮：通用 ADC 读取
           第四十四轮：去掉了 zk_touchpad_read（「触摸板 P 是否被触摸」）。
           它和上面的 zk_is_touch（「触摸 P 被触摸？」）生成的代码完全一样
           （都是 touchVar(PAD).is_pressed()），是同一块积木的两种说法。
           保留更简洁的 zk_is_touch；
           积木定义仍留在 device-blocks.js 里以兼容老工程。 */
        b('zk_adc_read')
        /* 第二十六轮：已去掉「扩展板电机 / 扩展板灯 / NeoPixel」积木
           （积木定义仍保留在 blocks-defs 里以兼容旧工程，只是不再显示；
           第三十六轮按「完善电机/马达积木」需求，把扩展板 parrot 官方积木
           放到了「直流电机」设备分类里） */) +
      /* ---- 6. 高级（文本 / 数据集合 / 文件串口 / 自制积木）----
         子分类始终存在于工具箱 XML 中（Blockly 不支持运行时动态插入分类），
         由 app.js 通过 zk-adv-child 标记 + CSS 控制显示/隐藏，
         这样展开/折叠都是纯样式切换，稳定可靠。 */
      '<category name="高级" colour="' + C.advanced + '" custom="ZKB_ADVANCED"></category>' +
      advancedChildren();
  }

  /* 高级分组展开后显示的子分类 */
  function advancedChildren() {
    return '' +
      '<category name="文本" colour="' + C.text + '" custom="ZKB_TEXT" zk-adv-child="1"></category>' +
      '<category name="数据集合" colour="' + C.data + '" custom="ZKB_DATA" zk-adv-child="1"></category>' +
      '<category name="文件串口" colour="' + C.file + '" custom="ZKB_FILE" zk-adv-child="1"></category>' +
      '<category name="自制积木" colour="' + C.procedure + '" custom="ZKB_PROC" zk-adv-child="1"></category>';
  }

  /* 设备分类（按 id 取对应颜色与积木） */
  var DEVICE_CAT = {
    dht: { name: '温湿度', colour: C.dht, types: ['zk_dht_measure', 'zk_dht_val',
      'zk_dht_temp', 'zk_dht_hum', 'zk_dht_dew', 'zk_dht_ok',
      /* 第三十六轮：DS18B20 单总线温度传感器 */
      'zk_ds18_temp', 'zk_ds18_ok'] },
    ultrasonic: { name: '超声波', colour: C.ultra, types: ['zk_ultra', 'zk_ultra_cm',
      'zk_ultra_mm', 'zk_ultra_near'] },
    servo: { name: '舵机', colour: C.servo, types: ['zk_servo', 'zk_servo_get', 'zk_servo_off'] },
    ir: { name: '红外', colour: C.ir, types: ['zk_ir', 'zk_when_ir'] },
    /* 第三十六轮：人体红外传感器（PIR） */
    pir: { name: '人体红外', colour: C.ir, types: ['zk_pir', 'zk_pir_count', 'zk_pir_reset'] },
    heater: { name: '加热元件', colour: C.heater, types: ['zk_heat', 'zk_heat_power'] },
    /* 第二十二轮：探测/行人相关积木一并归入「小车」分类，
       「控制」里只保留位置/层级/大小/方向四个舞台元素通用积木 */
    /* 第二十二轮：只保留「探测前方元素」；
       「让元素从上往下走 / 元素走到终点了吗」已移出（改用控制模块的
       「把元素移动到 x,y」调整 Y 坐标实现上下移动）。
       注意：blocks-defs / gen-sim 仍保留这两个块的定义，
       以便旧工程里的积木能正常打开（只是不再显示在积木区）。 */
    car: {
      name: '小车', colour: C.car,
      types: ['zk_car', 'zk_car_wheels', 'zk_car_dist', 'zk_front_has']
    },
    /* 巡线小车（第十四轮）：电机 + 循迹器 + 超声波，仅在拓展库添加后显示 */
    traceCar: { name: '巡线小车', colour: C.car, types: ['zk_trace_motor', 'zk_trace_auto', 'zk_trace_line', 'zk_trace_dist'] },
    /* 机器人（巡线/送餐）：仅在拓展库添加「机器人」模型后显示 */
    robot: { name: '机器人', colour: C.robot, types: ['zk_robot_go', 'zk_robot_speed', 'zk_robot_ground', 'zk_robot_dist', 'zk_robot_cam', 'zk_robot_asr'] },
    motor: { name: '直流电机', colour: C.motor, types: ['zk_motor', 'zk_motor_stop',
      'zk_motor_get_speed', 'zk_motor_set',
      /* 第三十六轮：恢复拓展板 parrot 官方 API 积木
         （第二十六轮曾移除，本轮按「完善电机/马达积木」的需求加回）
         第四十六轮：拓展板「灯」相关的两块移到了 LED 模块分类，
         这里只留电机相关的（转速 / 读取 / 停止）。 */
      'zk_parrot_speed', 'zk_parrot_get', 'zk_parrot_stop'] },
    pump: { name: '水泵', colour: C.pump, types: ['zk_pump', 'zk_pump_power',
      'zk_pump_on', 'zk_pump_get_power', 'zk_pump_flow'] },
    color: { name: '颜色识别', colour: C.color, types: ['zk_color_rgb', 'zk_color_seen'] },
    camera: {
      name: 'AI 摄像头', colour: C.camera, types: ['zk_camera_result', 'zk_camera_seen'],
      /* 第二十三轮：AI 视觉三大能力（文字 / 人脸 / 物体），
         仅在已添加「AI 摄像头」设备时出现 */
      children: [
        { name: '文字识别', colour: '#37474f', types: [
          'zk_vision_ocr_start', 'zk_vision_ocr_text', 'zk_vision_ocr_number'
        ] },
        { name: '人脸识别', colour: '#5d4037', types: [
          'zk_vision_face_register', 'zk_vision_face_verify',
          'zk_vision_face_name', 'zk_vision_face_gender', 'zk_vision_face_bio',
          'zk_vision_face_emotion', 'zk_vision_face_emotion_text'
        ] },
        { name: '物体识别', colour: '#33691e', types: [
          'zk_vision_obj_start', 'zk_vision_obj_car', 'zk_vision_obj_animal',
          'zk_vision_obj_plant', 'zk_vision_obj_dish', 'zk_vision_obj_fruit',
          'zk_vision_confidence'
        ] },
        /* 第三十五轮：场景 / 手写 / 速算 / 人脸属性 */
        { name: '场景与手写', colour: '#00695c', types: [
          'zk_vision_scene_start', 'zk_vision_scene_result',
          'zk_vision_handwrite_start', 'zk_vision_handwrite_text',
          'zk_vision_calc_start', 'zk_vision_calc_text',
          'zk_vision_calc_answer', 'zk_vision_calc_correct',
          'zk_vision_face_count', 'zk_vision_face_attr'
        ] },
        /* 第三十五轮：K210 板上预置模型（本地推理，不依赖网络） */
        { name: '板上模型', colour: '#4527a0', types: [
          'zk_k210_kpu_load', 'zk_k210_face_detect', 'zk_k210_face_num',
          'zk_k210_face_x', 'zk_k210_face_y', 'zk_k210_face_w', 'zk_k210_face_h',
          'zk_k210_face_value', 'zk_k210_obj_detect', 'zk_k210_obj_label',
          'zk_k210_obj_count', 'zk_k210_obj_value', 'zk_k210_digit'
        ] }
      ]
    },
    mic: { name: '麦克风', colour: C.mic, types: ['zk_mic'] },
    lightExt: { name: '光线传感器', colour: C.light, types: ['zk_ambient',
      'zk_light_raw', 'zk_light_pct', 'zk_light_bright'] },
    soil: { name: '土壤湿度', colour: C.soil, types: ['zk_soil', 'zk_soil_pct',
      'zk_soil_wet', 'zk_soil_raw'] },
    pm25: { name: 'PM2.5', colour: C.pm25, types: ['zk_pm25', 'zk_pm25_level',
      'zk_pm25_value', 'zk_pm25_good', 'zk_pm25_harm'] },
    baro: { name: '气压传感器', colour: C.baro, types: ['zk_pressure', 'zk_altitude',
      'zk_pressure_pa', 'zk_temp', 'zk_pressure_hpa'] },
    button: { name: '按键模块', colour: C.extbtn, types: ['zk_ext_btn', 'zk_ext_btn_pressed',
      'zk_ext_btn_count', 'zk_ext_btn_reset'] },
    fan: { name: '风扇', colour: C.fan, types: ['zk_fan', 'zk_fan_power'] },
    /* —— DFRobot 新增硬件 —— */
    tracker: { name: '巡线传感器', colour: C.dht, types: ['zk_tracker_read', 'zk_tracker_state'] },
    powerMeter: { name: '数字功率计', colour: C.dht, types: ['zk_power_read'] },
    gravity: { name: 'AS7341 颜色', colour: C.color, types: ['zk_gravity_read'] },
    angle: { name: '角度传感器', colour: C.analog, types: ['zk_angle_read'] },
    irTx: { name: '红外发射', colour: C.ir, types: ['zk_ir_send'] },
    irRx: { name: '红外接收', colour: C.ir, types: ['zk_ir_receive'] },
    relay: { name: '数字继电器', colour: C.heater, types: ['zk_relay'] },
    ledModule: {
      name: 'LED 模块', colour: C.heater,
      types: ['zk_led_brightness', 'zk_led_on', 'zk_led_off',
        'zk_led_bright_set', 'zk_led_is_on', 'zk_led_get_bright',
        /* 第四十六轮：把拓展板「灯」积木（原在直流电机分类）挪到这里。
           拓展板电机口当灯用（parrot.led_on / led_off）本质是 LED 控制，
           放在 LED 模块分类里学生更好找。 */
        'zk_parrot_led', 'zk_parrot_led_bright']
    },
    rgbStrip: { name: 'RGB 灯带', colour: C.rgb, types: ['zk_rgb_strip', 'zk_rgb_strip_all',
      'zk_rgb_strip_off', 'zk_rgb_strip_rainbow', 'zk_strip_count', 'zk_strip_get',
      'zk_strip_all_off', 'zk_strip_rainbow_stop'] },
    /* 第三十六轮：MP3 模块（DFRobot UART 音乐模块） */
    mp3: { name: 'MP3 模块', colour: C.music, types: ['zk_mp3_play', 'zk_mp3_stop',
      'zk_mp3_volume', 'zk_mp3_playing', 'zk_mp3_folder'] },
    remote: { name: '红外遥控器', colour: C.ir, types: ['zk_remote_key', 'zk_remote_dir', 'zk_buzzer'] },
    /* —— 通讯网络 —— */
    radio: { name: '无线广播', colour: C.net, types: ['zk_radio_group', 'zk_radio_send', 'zk_when_radio', 'zk_radio_msg'] },
    wifi: { name: 'WiFi', colour: C.net, types: ['zk_wifi_connect', 'zk_wifi_ok'] },
    ntp: { name: 'NTP 网络时间', colour: C.net, types: ['zk_ntp_sync', 'zk_time_now'] },
    mqtt: { name: 'MQTT', colour: C.net, types: ['zk_mqtt_connect', 'zk_mqtt_pub', 'zk_when_mqtt', 'zk_mqtt_msg'] },
    asr: { name: 'WiFi语音识别', colour: C.net, types: ['zk_asr_text'] },
    weather: { name: '天气', colour: C.net, types: ['zk_weather'] },
    /* —— 第二十九轮：八年级新增硬件 —— */
    magnetic: {
      name: '磁场传感器', colour: C.onboard,
      types: ['zk_magnetic_init', 'zk_magnetic_calibrate', 'zk_magnetic_peeling', 'zk_magnetic_heading']
    },
    gps: {
      name: '卫星定位', colour: C.net,
      types: ['zk_gps_init', 'zk_gps_parse', 'zk_gps_data', 'zk_gps_ready']
    },
    qrcode: { name: '二维码', colour: C.oled, types: ['zk_qrcode'] },
    rfid: { name: 'RFID 射频卡', colour: C.color, types: ['zk_rfid_scan', 'zk_rfid_id'] },
    speech2: { name: '离线语音识别', colour: C.mic, types: ['zk_speech2_init', 'zk_speech2_result'] }
  };

  function deviceCategory(id) {
    var base = (ZKB.baseOf ? ZKB.baseOf(id) : id);
    var info = DEVICE_CAT[base];
    if (!info) return '';
    /* 第十四轮：每类设备只允许添加 1 个，分类名与积木均不再带序号 */
    var blocks = info.types.map(b).join('');
    /* 第二十三轮：有子分类的设备（如 AI 摄像头）展开为飞出层 */
    if (info.children && info.children.length) {
      var kids = info.children.map(function (c) {
        return cat(c.name, c.colour, c.types.map(b).join(''));
      }).join('');
      return cat(info.name, info.colour, kids);
    }
    return cat(info.name, info.colour, blocks);
  }

  /* 分类名 → 主色 映射：作为取色兜底，保证任何环境下都能取到分类色。
   与各分类实际使用的 colour 保持同源（见下方 buildToolboxXml 的 colour 值）。 */
  ZKB.CAT_PALETTE = (function () {
    var m = {};
    /* 通用分类（当前结构） */
    ['控制', '逻辑', '屏幕显示', '变量', '掌控板', '高级',
      '运动', '外观',
      '文本', '数据集合', '文件串口', '自制积木'].forEach(function (n) {
        m[n] = null;   /* 运行时由 buildToolboxXml 的 colour 填充 */
      });
    /* 设备分类 */
    Object.keys(DEVICE_CAT).forEach(function (id) {
      m[DEVICE_CAT[id].name] = DEVICE_CAT[id].colour;
      /* 子分类（如 AI 摄像头的文字/ 人脸 / 物体识别）也登记 */
      var kids = DEVICE_CAT[id].children;
      if (kids && kids.length) kids.forEach(function (c) { m[c.name] = c.colour; });
    });
    return m;
  })();

  /* 高级分组展开后需要插入的子分类 XML */
  ZKB.buildAdvancedXml = function () {
    return advancedChildren();
  };

  /**
   * 根据已添加的设备列表生成完整工具箱 XML
   * @param {string[]} devices 已添加的设备 id 列表
   */
  ZKB.buildToolboxXml = function (devices) {
    var body = commonCategories();
    (devices || []).forEach(function (id) {
      body += deviceCategory(id);
    });
    /* 同步填充分类调色板（供取色兜底） */
    var re = /<category name="([^"]+)" colour="([^"]+)"/g, m2;
    while ((m2 = re.exec(body)) !== null) ZKB.CAT_PALETTE[m2[1]] = m2[2];
    /* 高级子分类也登记调色板 */
    var reA = /<category name="([^"]+)" colour="([^"]+)"/g, m3;
    var adv = advancedChildren();
    while ((m3 = reA.exec(adv)) !== null) ZKB.CAT_PALETTE[m3[1]] = m3[2];
    return '<xml id="zkToolbox" style="display:none">' + body + '</xml>';
  };

  // 默认工具箱（无拓展设备）
  ZKB.TOOLBOX_XML = ZKB.buildToolboxXml([]);

  /* ============================================================
   * 分类配色同步
   * Blockly 默认给分类行的左侧图标上色（.blocklyTreeIcon 的行内
   * background-color），但行背景仍是用 CSS 渐变画的灰白色，
   * 导致「色条」与「文字下方填充色」两套颜色各走各的。
   * 这里统一以图标色为唯一数据源：读取每行图标色 → 派生出行背景
   * 与飞出层背景，并随工具箱重建 / 选中切换自动重刷。
   * ============================================================ */

  /* ---- 颜色工具：hex → rgb / rgb → hex / 混合 / 亮度判断 ---- */
  function parseHex(c) {
    if (!c) return null;
    c = String(c).trim();
    var m3 = /^#?([0-9a-f])([0-9a-f])([0-9a-f])$/i.exec(c);
    if (m3) return [parseInt(m3[1] + m3[1], 16), parseInt(m3[2] + m3[2], 16), parseInt(m3[3] + m3[3], 16)];
    var m6 = /^#?([0-9a-f]{6})$/i.exec(c);
    if (m6) {
      var n = parseInt(m6[1], 16);
      return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    }
    var m8 = /^#?([0-9a-f]{8})$/i.exec(c);
    if (m8) {
      var n8 = parseInt(m8[1].slice(0, 6), 16);
      return [(n8 >> 16) & 255, (n8 >> 8) & 255, n8 & 255];
    }
    return null;
  }
  function toHex(rgb) {
    return '#' + rgb.map(function (v) {
      var s = Math.max(0, Math.min(255, Math.round(v))).toString(16);
      return s.length < 2 ? '0' + s : s;
    }).join('');
  }
  /* 与白色按比例混合：t=0 纯原色，t=1 纯白 */
  function tint(rgb, t) {
    return toHex([rgb[0] + (255 - rgb[0]) * t, rgb[1] + (255 - rgb[1]) * t, rgb[2] + (255 - rgb[2]) * t]);
  }
  /* 感知亮度（用于决定叠加文字/描边的深浅） */
  function luma(rgb) { return (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255; }

  /**
   * 把「图标色 → 行背景 → 飞出层背景」统一起来。
   * 幂等，可重复调用；工具箱重建后需再次调用。
   *
   * 注意：Blockly 10 并不会把 colour 写到 .blocklyTreeIcon 的
   * background-color 上，而是把颜色编码进分类项 div 的
   * border-left-color（行内样式，形如 border-left: 8px solid rgb(...)）。
   * 因此这里按优先级依次尝试多种来源，保证一定能取到主色：
   *   1) 行内 border-left-color / borderColor
   *   2) 图标的 background-color
   *   3) 分类 XML 中声明的 colour（兜底）
   */
  function pickCategoryColour(row, icon) {
    if (icon) {
      var bg = icon.style.backgroundColor || icon.style.background;
      var rgb = parseHex(bg);
      if (rgb) return rgb;
    }
    /* Blockly 把分类色写在 border-left-color 上 */
    if (row.style) {
      var bl = row.style.borderLeftColor || row.style.borderColor ||
        (/border-left:[^;]*?solid\s+([^;]+)/i.exec(row.getAttribute('style') || '') || [])[1];
      var r2 = parseHex(bl);
      if (r2) return r2;
    }
    /* 兜底：从分类名反查调色板 */
    var lb = row.querySelector('.blocklyTreeLabel');
    var nm = lb ? (lb.textContent || '').trim() : '';
    if (nm && ZKB.CAT_PALETTE && ZKB.CAT_PALETTE[nm]) return parseHex(ZKB.CAT_PALETTE[nm]);
    return null;
  }

  function applyCategoryColours() {
    var toolbox = document.querySelector('.blocklyToolboxDiv');
    if (!toolbox) return;
    var rows = toolbox.querySelectorAll('.blocklyTreeRow');
    var activeRgb = null;

    rows.forEach(function (row) {
      var icon = row.querySelector('.blocklyTreeIcon');
      var rgb = pickCategoryColour(row, icon);
      /* 图标未着色（自定义分类未设 colour）时跳过，保留默认样式 */
      if (!rgb) return;

      /* 行内 CSS 变量：色条保持原色，文字下方填充用同色浅底 */
      row.style.setProperty('--zk-cat', toHex(rgb));
      row.style.setProperty('--zk-cat-soft', tint(rgb, 0.86));
      row.style.setProperty('--zk-cat-soft2', tint(rgb, 0.72));

      row.setAttribute('data-cat-colour', toHex(rgb));
      if (row.classList.contains('blocklyTreeSelected')) activeRgb = rgb;
    });

    /* 飞出层：背景用当前分类色的极浅底，标题栏用浅一档 */
    if (activeRgb) {
      var fly = document.querySelector('.blocklyFlyout');
      if (fly) {
        fly.style.setProperty('--zk-fly-bg', tint(activeRgb, 0.95));
        fly.style.setProperty('--zk-fly-title', tint(activeRgb, 0.78));
      }
      document.body.setAttribute('data-active-cat', toHex(activeRgb));
    }
  }

  /* 选中项切换时重刷飞出层配色（Blockly 在 selectCategory 后触发） */
  var lastSelName = '';
  function watchSelection() {
    var toolbox = document.querySelector('.blocklyToolboxDiv');
    if (!toolbox) return;
    var sel = toolbox.querySelector('.blocklyTreeSelected .blocklyTreeLabel');
    var name = sel ? sel.textContent.trim() : '';
    if (name !== lastSelName) {
      lastSelName = name;
      applyCategoryColours();
    }
  }
  /* 供 app.js 在重建工具箱后调用：延迟若干帧直到 Blockly 完成 DOM 构建 */
  ZKB.syncCategoryColours = function () {
    applyCategoryColours();
    [60, 200, 600].forEach(function (d) { setTimeout(function () { applyCategoryColours(); watchSelection(); }, d); });
  };

})(window);
