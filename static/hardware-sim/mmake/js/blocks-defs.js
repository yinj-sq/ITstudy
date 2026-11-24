/* ============================================================
 * blocks-defs.js  —— 掌控图形化编程：全部自定义积木定义
 * 依赖：Blockly 10.x UMD（blockly_compressed.js + blocks_compressed.js）
 * ============================================================ */
(function (global) {
  'use strict';

  var ZKB = global.ZKB || (global.ZKB = {});

  /* ---------- 通用选项 ---------- */
  /* 引脚选项：第二十六轮按参考图拆分，定义见「八、引脚输入输出」小节
     （ZKB.PIN_DIGITAL_OPTIONS / PIN_ANALOG_IN_OPTIONS / PIN_ANALOG_OUT_OPTIONS），
     这里保留 PIN_OPTIONS 指向数字引脚作为兼容别名。 */
  /* 扩展板实际引出的 10 个 IO 口（顺序与扩展板一致） */
  ZKB.EXP_IO_PINS = ['P0', 'P1', 'P2', 'P8', 'P9', 'P12', 'P13', 'P14', 'P15', 'P16'];
  /* 掌控板不支持的引脚 */
  ZKB.UNUSABLE_PINS = { P12: 1 };
  ZKB.BTN_OPTIONS = [['A 键', 'A'], ['B 键', 'B']];
  ZKB.TOUCH_OPTIONS = [['P', 'P'], ['Y', 'Y'], ['T', 'T'], ['H', 'H'], ['O', 'O'], ['N', 'N']];
  ZKB.RGB_OPTIONS = [['0 号', '0'], ['1 号', '1'], ['2 号', '2'], ['全部', 'ALL']];
  /* 内置表情（与 oled-image.js 的 FACES 键对应） */
  ZKB.FACE_OPTIONS = [
    ['喜（开心大笑）', 'happy'], ['怒（生气）', 'angry'], ['哀（难过）', 'sad'], ['乐（微笑）', 'calm'],
    ['惊（惊讶）', 'wow'], ['思（思考）', 'think'], ['爱（爱心眼）', 'love'], ['睡（睡觉）', 'sleep'],
    ['哭（流泪）', 'cry'], ['星（星星眼）', 'star']
  ];
  /* 「屏幕显示图片」下拉项：从图片库动态读取，带占位项保证首次可用
   *
   * 第三十六轮：只列「用户上传的图片」。
   * 原来内置表情也以「表情·喜」这种名字注册进了图片库，
   * 于是「屏幕显示图片」的下拉里既有表情又有用户图片，
   * 和独立的「屏幕显示表情」积木功能重复，学生会困惑该用哪个。
   * 现在按 kind 过滤：kind==='face' 的是内置表情（归表情积木管），
   * 其余才是用户上传的图片。 */
  function imgOptions() {
    var opts = [];
    if (global.ZKB && ZKB.OledImage && ZKB.OledImage.list) {
      try {
        ZKB.OledImage.list().forEach(function (r) {
          if (!r || !r.id || !r.name) return;
          /* 跳过内置表情 */
          if (r.kind === 'face' || r.face) return;
          opts.push([r.name, r.id]);
        });
      } catch (e) {}
    }
    /* 第三十九轮：素材库入口在**左下角**（「素材」按钮），
       不是右侧面板 —— 提示语要说对地方，否则学生找不到上传入口。 */
    if (!opts.length) opts = [['（请先在左侧素材中上传图片）', 'none']];
    return opts;
  }
  ZKB.imgOptions = imgOptions;
  /* 图片库变化后，刷新工作区中所有 zk_oled_image 积木的下拉选项 */
  ZKB.refreshImageBlocks = function () {
    if (!global.Blockly || !Blockly.getMainWorkspace) return;
    try {
      Blockly.getMainWorkspace().getAllBlocks(false).forEach(function (b) {
        if (b.type !== 'zk_oled_image') return;
        var f = b.getField('IMG');
        if (!f) return;
        var cur = f.getValue();
        var opts = imgOptions();
        var curOk = opts.some(function (o) { return o[1] === cur; });
        f.setOptions(!curOk ? opts : [['（当前图片不存在）', cur]].concat(opts));
      });
    } catch (e) {}
  };
  ZKB.NOTES = [
    ['C4 (do)', 'C4'], ['D4 (re)', 'D4'], ['E4 (mi)', 'E4'], ['F4 (fa)', 'F4'],
    ['G4 (sol)', 'G4'], ['A4 (la)', 'A4'], ['B4 (si)', 'B4'],
    ['C5 (高音do)', 'C5'], ['D5', 'D5'], ['E5', 'E5'], ['F5', 'F5'],
    ['G5', 'G5'], ['A5', 'A5'], ['B5', 'B5'], ['C6', 'C6']
  ];

  /* 人脸库变化后，刷新工作区中所有 zk_vision_face_verify 积木的姓名下拉 */
  ZKB.refreshFaceBlocks = function () {
    if (!global.Blockly || !Blockly.getMainWorkspace) return;
    var names = [];
    try {
      /* 人脸库存放在 ZKB.Vision 里（localStorage key: zkb_faces_v1） */
      var list = ZKB.Vision ? ZKB.Vision.faceList() : [];
      names = list.map(function (f) { return f.name; });
    } catch (e) { names = []; }
    if (!names.length) names = ['（尚未录入人脸）'];
    try {
      Blockly.getMainWorkspace().getAllBlocks(false).forEach(function (b) {
        if (b.type !== 'zk_vision_face_verify') return;
        var f = b.getField('NAME');
        if (!f) return;
        var cur = f.getValue();
        var opts = names.map(function (n) { return [n, n]; });
        /* 当前选中项已从人脸库移除时，保留它并标注（而不是静默跳到别的名字） */
        if (cur && !names.some(function (n) { return n === cur; })) {
          opts = [[cur + '（已删除）', cur]].concat(opts);
        }
        f.setOptions(opts);
      });
    } catch (e) { }
  };

  /* ---------- 颜色 ---------- */
  var C = {
    /* 第三十五轮：控制模块重新配色。
       原来「事件」#f2a73b 与「控制」#e8871e 太接近，学生分不清；
       且 Blockly 内置循环积木（重复执行 / 条件重复）是默认绿色，
       与本站暖色体系割裂。现在统一成「琥珀 → 赭石」的暖色梯度：
         事件   #f0a92c  亮琥珀（最醒目，积木顶帽）
         控制   #e0741c  赭橙（等待 / 打印 / 循环）
         循环   #c85f16  深赭（Blockly 内置循环积木，稍深以示层级） */
    event: '#f0a92c', control: '#e0741c', logic: '#3f88e8', math: '#3fae5a',
    text: '#4a5fc1', variable: '#e06a2b', procedure: '#ff6680',
    oled: '#0f9d8e', rgb: '#d63384', key: '#7c5cd6', onboard: '#1e88e5',
    sound: '#57606a', pin: '#c2632c', dht: '#12a8b8', ultra: '#3955b5',
    servo: '#d9a800', ir: '#d33b3b', heater: '#e0552c', car: '#3d7ea6',
    motor: '#cf7a16', pump: '#2f9e8e', color: '#9048c4', camera: '#37474f',
    mic: '#8e5bbf', light: '#d9a800',
    soil: '#8a6f3a', pm25: '#5b6775', baro: '#3a6ea5', extbtn: '#c2632c', fan: '#5aa8cc',
    net: '#7c5cd6',
    /* mPython API 兼容类目 */
    music: '#b4590e', data: '#2a7a4b', file: '#5a6b7a', expboard: '#c2410c',
    /* 高级分组（文本 / 数据集合 / 文件串口 / 自制积木）：灰蓝，避开外观紫 */
    advanced: '#54607a',
    /* DFRobot 新增硬件 */
    analog: '#0f8f8a',
    /* 机器人（巡线 / 送餐） */
    robot: '#7048e8',
    /* 第三十轮：舞台运动 / 外观（与板载蓝 #1e88e5、板载灯粉 #d63384 拉开差距） */
    stage_motion: '#1565c0', stage_looks: '#7b1fa2',
    /* 第三十五轮：循环积木（Blockly 内置循环块的统一色） */
    control_loop: '#c85f16',
    /* 第四十七轮：数学类自定义积木（zk_constrain / zk_str2num）的颜色。
       Blockly 内置的数学积木（math_number / math_arithmetic /
       math_random_int / math_constrain …）用的是主题默认的
       紫蓝色 #5b67a5；而自定义积木若用站点色 C.logic(#3f88e8)
       就会在同一个「逻辑」分类里出现两种蓝，学生分不清哪些是
       配套的一组。这里直接对齐 Blockly 默认数学色，
       让自建积木和它替代的内置积木看起来是一套。 */
    math_block: '#5b67a5'
  };
  ZKB.COLORS = C;

  /* ---------- 注册辅助 ---------- */
  /* 设备实例（第十四轮）：传感器 / 执行器每类仅可添加 1 个，
     积木不再追加「几号设备」INST 下拉；INST_DEV 置空即不追加。
     （gen-sim 的 inst(b) 在字段不存在时默认按 1 号实例生成代码。） */
  var INST_DEV = {};
  ZKB.hasInstField = function (type) { return !!INST_DEV[type]; };
  function def(type, json, extra) {
    var instBase = INST_DEV[type];
    if (instBase) {
      var n = (json.args0 || []).length;
      json.message0 += ' %' + (n + 1);
      (json.args0 = json.args0 || []).push({
        type: 'field_dropdown', name: 'INST',
        options: function () { return [['1 号', '1']]; }
      });
    }
    Blockly.Blocks[type] = {
      init: function () {
        this.jsonInit(json);
        if (extra) extra.call(this);
      }
    };
  }
  var HAT = '"shape": "hat"'; // 仅用于备注，Blockly hat 通过 inputsInline 风格+ setNextStatement

  /* ============================================================
   * 一、事件积木
   * ============================================================ */
  def('zk_when_start', {
    message0: '当 掌控板 启动时',
    args0: [],
    nextStatement: null, colour: C.event,
    tooltip: '程序从上电开始执行',
    hat: 'cap'
  });

  def('zk_when_btn', {
    message0: '当按键 %1 被按下',
    args0: [{ type: 'field_dropdown', name: 'BTN', options: ZKB.BTN_OPTIONS }],
    nextStatement: null, colour: C.event, tooltip: '按下 A/B 键时执行下面的积木', hat: 'cap'
  });

  def('zk_when_touch', {
    message0: '当触摸引脚 %1 被触摸',
    args0: [{ type: 'field_dropdown', name: 'PAD', options: ZKB.TOUCH_OPTIONS }],
    nextStatement: null, colour: C.event, tooltip: '手指触摸掌控板边缘的 P/Y/T/H/O/N 金色焊盘', hat: 'cap'
  });

  def('zk_when_shake', {
    message0: '当摇晃掌控板时',
    args0: [],
    nextStatement: null, colour: C.event, tooltip: '摇晃掌控板（仿真中点击板上的“摇晃”按钮）', hat: 'cap'
  });

  def('zk_when_ir', {
    message0: '当红外传感器检测到障碍物时',
    args0: [],
    nextStatement: null, colour: C.event, tooltip: '需要先在“拓展”中添加红外传感器', hat: 'cap'
  });

  /* ============================================================
   * 二、控制：等待 / 输出
   * ============================================================ */
  def('zk_wait_sec', {
    message0: '等待 %1 秒',
    args0: [{ type: 'input_value', name: 'SEC', check: 'Number' }],
    previousStatement: null, nextStatement: null, colour: C.control,
    inputsInline: true, tooltip: '暂停指定秒数，可为小数'
  }, function () { this.getInput('SEC').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">1</field></shadow>')); });

  def('zk_wait_ms', {
    message0: '等待 %1 毫秒',
    args0: [{ type: 'input_value', name: 'MS', check: 'Number' }],
    previousStatement: null, nextStatement: null, colour: C.control,
    inputsInline: true, tooltip: '1000 毫秒 = 1 秒'
  }, function () { this.getInput('MS').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">500</field></shadow>')); });

  def('zk_print', {
    message0: '串口输出 %1',
    args0: [{ type: 'input_value', name: 'V' }],
    previousStatement: null, nextStatement: null, colour: C.control,
    inputsInline: true, tooltip: '把数据显示在控制台 / 串口终端'
  }, function () { this.getInput('V').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="text"><field name="TEXT">你好</field></shadow>')); });

  // 永久循环（Blockly 10 标准库不含此积木，自行定义）
  def('controls_forever', {
    message0: '一直重复',
    args0: [],
    message1: '%1',
    args1: [{ type: 'input_statement', name: 'SUBSTACK' }],
    previousStatement: null, nextStatement: null, colour: C.control_loop,
    tooltip: '永远循环执行（仿真运行时可点击“停止”结束）'
  });

  /* 第三十五轮：统一 Blockly 内置循环积木的配色。
     Blockly 自带的「重复执行 N 次」「当条件成立时重复」「计数循环」
     默认是绿色，与本站暖色控制体系割裂。这里只改颜色，
     不动其逻辑与 XML 结构（老工程照样能打开）。 */
  ['controls_repeat_ext', 'controls_repeat', 'controls_whileUntil',
    'controls_for', 'controls_forEach'].forEach(function (t) {
    var blk = Blockly.Blocks[t];
    if (!blk) return;
    var oldInit = blk.init;
    blk.init = function () {
      oldInit.apply(this, arguments);
      this.setColour(C.control_loop);
    };
  });

  /* ============================================================
   * 第四十轮 + 第四十一轮：变量积木与列表积木的下拉互不混用
   *
   * 第四十轮的做法：给内置变量积木的 VAR 字段固定加
   * variableTypes:['','String']（空串 / String = 普通变量），
   * 这样「把…设为」「将…增加」「…（变量）」的下拉里不会冒出列表。
   *
   * 第四十一轮修的坑：variables_get 不只是「读取变量」积木，
   * 它还是**所有列表积木的影子块**
   * （lists_length / lists_getIndex / lists_setIndex / zk_list_clear …），
   * 影子块的 XML 上带着 variabletype="LIST"。
   *
   * Blockly 的反序列化顺序是：
   *   FieldVariable.fromXml → getOrCreateVariablePackage(按 XML 声明的类型
   *   找到/建好变量) → setValue → doClassValidation_ → typeIsAllowed(类型)
   * 白名单一刀切地把 LIST 挡在外面 → 字段回落到默认变量名「项目」，
   * initModel 还会顺手在工作区里凭空造出一个普通变量「项目」。
   *
   * 现在的做法：白名单以 **XML 声明的类型**为准。
   *   · XML 声明了 variabletype（列表影子块）→ 只接受该类型
   *   · XML 没声明 → 沿用积木自身定义的白名单（普通变量）
   * 于是列表积木能正确显示列表名，变量积木的下拉里也不会混进列表。
   * ============================================================ */
  ['variables_set', 'math_change', 'variables_get'].forEach(function (t) {
    var blk = Blockly.Blocks[t];
    if (!blk) return;
    var oldInit = blk.init;
    blk.init = function () {
      oldInit.apply(this, arguments);
      var f = this.getField('VAR');
      if (f) {
        f.variableTypes = ['', 'String'];
        f.defaultType = '';
        /* 已有工程里若选中了列表，改成普通变量（取第一个普通变量） */
        try {
          var m = f.getVariable();
          if (m && m.type === 'LIST') {
            var plain = this.workspace.getVariablesOfType('') ||
              this.workspace.getVariablesOfType('String');
            if (plain && plain.length) f.setValue(plain[0].getId());
          }
        } catch (e) { /* 老工程可能没有变量，忽略 */ }
      }
    };
  });

  /* 让 field_variable 的白名单跟随 XML 上声明的变量类型
   *
   * FieldVariable.fromXml 会先按 XML 的 variabletype 找到/建好变量，
   * 紧接着 setValue 又要过一遍 typeIsAllowed 白名单。
   * 白名单若与 XML 声明冲突，变量就绑不上，字段回落成默认名「项目」。
   * 这里在反序列化时按声明的类型收紧白名单，保证两边一致。
   */
  (function () {
    var FV = global.Blockly && global.Blockly.FieldVariable;
    if (!FV || FV.__zkTypeAware) return;
    var origFromXml = FV.prototype.fromXml;
    FV.prototype.fromXml = function (dom) {
      var vt = dom.getAttribute('variabletype') || dom.getAttribute('variableType') || '';
      if (vt) {
        this.variableTypes = [vt];
        this.defaultType = vt;
      }
      return origFromXml.call(this, dom);
    };
    FV.__zkTypeAware = true;
  })();

  /* 第四十三轮：loadState 也要按变量类型收紧白名单
   *
   * 【为什么 fromXml 修了还不够】
   * Blockly 把积木从工具箱拖到工作区时，走的是**另一条**反序列化路径：
   *   blocks.append → loadFields → FieldVariable.loadState(state)
   * loadState 收到的 state 是 JS 对象 {id, name, type}，
   * 不是 XML，于是上面那个 fromXml 的补丁**根本不会被触发**。
   *
   * 实际发生的事：
   *   1. loadState → getOrCreateVariablePackage(按 state.type='LIST' 找到列表)
   *      → setValue(id) → doClassValidation_ → typeIsAllowed('LIST')
   *   2. 但 variables_get 的白名单被固定成 ['','String']（第四十轮加的，
   *      为了让「把…设为」这类积木的下拉里不冒出列表）
   *   3. LIST 不在白名单里 → 校验失败 → 字段值不生效
   *   4. 随后 initModel() 兜底 → 绑到普通变量
   *      → 积木上显示「计分」/「项目」，而不是列表名
   *
   * 也就是说：手工反序列化（load 工程）是对的，
   * 但**拖拽落地是错的**——正是学生最常用的操作路径。
   *
   * 【怎么改】
   * loadState 里同样按 state.type 收紧白名单，
   * 与 fromXml 的处理保持一致，两条路径行为统一。 */
  (function () {
    var FV = global.Blockly && global.Blockly.FieldVariable;
    if (!FV || FV.__zkStateAware) return;
    var origLoadState = FV.prototype.loadState;
    FV.prototype.loadState = function (state) {
      /* state = {id, name, type}，type 是变量的真实类型（'LIST' / ''） */
      var vt = state && state.type;
      if (vt) {
        this.variableTypes = [vt];
        this.defaultType = vt;
      }
      return origLoadState.call(this, state);
    };
    FV.__zkStateAware = true;
  })();

  /* 第四十一轮：新建变量字段时优先复用已有变量，别再凭空造「项目」
   *
   * 【坑在哪】FieldVariable.initModel 的原始逻辑是：
   *   字段还没绑定变量 → 用 defaultVariableName 调 getOrCreateVariablePackage，
   *   在工作区里**新建**一个同名变量。
   * 内置 variables_get / variables_set / math_change 的 defaultVariableName
   * 就是 Blockly 的 Msg.VARIABLES_DEFAULT_NAME —— 中文版是「项目」。
   * 于是任何一次「字段还没绑上变量就被 initModel」的场合，
   * 工作区里都会冒出一个叫「项目」的普通变量，
   * 列表积木的下拉里也会多出它。
   *
   * 【怎么改】改成：先在白名单允许的类型里找**已经存在**的变量，
   * 找到就直接绑上（doValueUpdate_ 是 Blockly 自己的绑定路径，不做额外校验）；
   * 一个都没有时才退回原始逻辑建默认名变量。
   *
   * 效果：
   *   · 新拖出的 variables_get 直接显示已有的「计分」，而不是「项目」
   *   · zk_list_show / zk_list_hide 直接显示已有的列表名，而不是造一个「列表」
   *   · zk_var_show / zk_var_hide 直接显示已有的变量名，而不是造一个「我的变量」
   */
  (function () {
    var FV = global.Blockly && global.Blockly.FieldVariable;
    if (!FV || FV.__zkReuseExisting) return;
    var origInitModel = FV.prototype.initModel;
    FV.prototype.initModel = function () {
      /* 已经绑好了 → 什么都不用做 */
      if (this.variable) return origInitModel.call(this);

      var src = this.getSourceBlock();
      if (!src) return origInitModel.call(this);

      var ws = src.workspace;
      if (!ws || !ws.getVariablesOfType) return origInitModel.call(this);

      /* 白名单允许的类型里，找第一个已经存在的变量 */
      var types;
      try { types = this.getVariableTypes() || []; } catch (e) { types = []; }
      for (var i = 0; i < types.length; i++) {
        var arr = ws.getVariablesOfType(types[i]);
        if (arr && arr.length) {
          this.doValueUpdate_(arr[0].getId());
          return;
        }
      }
      /* 一个都没有 → 交给原始逻辑（建默认名变量） */
      return origInitModel.call(this);
    };
    FV.__zkReuseExisting = true;
  })();

  /* ============================================================
   * 三、OLED 屏幕显示
   *
   * 第四十四轮：原来「清空屏幕」与「整屏（点亮/熄灭）」两个积木
   * 摆在一起，学生分不清区别（清空 ≈ 整屏熄灭，其实重复了一半）。
   * 现在把两者分工讲清楚：
   *   · 清空屏幕        —— 清成黑屏（等同「整屏 熄灭」，但语义更明确）
   *   · 整屏 点亮/熄灭  —— 一次铺满全屏，常用「点亮」做背景底色
   * 文案上把「整屏」改成更口语的「全屏」，并给两者补上提示。
   * ============================================================ */
  /* ============================================================
   * 第四十八轮：屏幕底色统一成一个积木
   *
   * 【原来的问题】
   *   「清空屏幕（变黑）」和「全屏 点亮/熄灭」摆在一起，
   *   学生分不清区别（清空 ≈ 全屏熄灭，其实重复了一半）。
   *
   * 【现在的做法】
   *   合成一块「屏幕 %1」，下拉里给四个明确的选择：
   *     清空 —— 清成黑屏（等同 fill(0)，但语义是"擦干净"）
   *     全亮 —— 全部像素点亮（当白底用）
   *     黑底 —— 铺一层黑底（等同 fill(0)，当背景色用）
   *     白底 —— 铺一层白底（等同 fill(1)，当背景色用）
   *
   *   这样「擦干净」和「铺底色」两种意图分开表达，
   *   又不用两块积木。
   *
   * 【兼容】旧积木 zk_oled_clear / zk_oled_fill 的定义保留，
   *   老工程打开不会变成"未知积木"；官方 mxml 的
   *   hunan_mpython_display_Clear / _fill 仍映射到旧积木。
   * ============================================================ */
  def('zk_oled_screen', {
    message0: '屏幕 %1',
    args0: [{
      type: 'field_dropdown', name: 'V',
      /* 四个选项的值各不相同：
       *   clear = 擦干净（黑屏）
       *   all   = 全亮（全部像素点亮）
       *   black = 黑底（当背景色用）
       *   white = 白底（当背景色用）
       * 全亮 与 白底 的效果一样，但语义不同：
       *   「全亮」是测试屏幕 / 当底色，
       *   「白底」明确表示"我要铺一层白底再写黑字"。
       * 值不同才能在导出 mxml 时还原学生当时选的是哪一项。 */
      options: [['清空', 'clear'], ['全亮', 'all'], ['黑底', 'black'], ['白底', 'white']]
    }],
    previousStatement: null, nextStatement: null, colour: C.oled,
    tooltip: '一次设置整块 128×64 屏幕的底色\n' +
      '「清空」= 擦干净（黑屏），可再往上写内容\n' +
      '「全亮 / 白底」= 全部点亮，当白色背景用\n' +
      '「黑底」= 全部熄灭，当黑色背景用'
  });

  def('zk_oled_clear', {
    message0: '清空屏幕（变黑）',
    args0: [], previousStatement: null, nextStatement: null, colour: C.oled,
    tooltip: '把 128×64 OLED 屏幕全部熄灭（清成黑屏）\n' +
      '（新做法：用「屏幕 清空」这一块，功能一样）'
  });

  def('zk_oled_fill', {
    message0: '全屏 %1',
    args0: [{ type: 'field_dropdown', name: 'V', options: [['点亮', '1'], ['熄灭', '0']] }],
    previousStatement: null, nextStatement: null, colour: C.oled,
    tooltip: '一次把整块屏幕填成同一个状态\n' +
      '（新做法：用「屏幕 全亮 / 黑底」这一块，功能一样）'
  });

  def('zk_oled_text', {
    message0: '屏幕显示 %1  x:%2 y:%3',
    args0: [
      { type: 'input_value', name: 'T' },
      { type: 'input_value', name: 'X', check: 'Number' },
      { type: 'input_value', name: 'Y', check: 'Number' }
    ],
    previousStatement: null, nextStatement: null, colour: C.oled,
    inputsInline: true, tooltip: '在指定坐标显示文本（中文英文均可），显示后需要“刷新屏幕”'
  }, function () {
    this.getInput('T').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="text"><field name="TEXT">你好 掌控板</field></shadow>'));
    this.getInput('X').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">0</field></shadow>'));
    this.getInput('Y').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">0</field></shadow>'));
  });

  def('zk_oled_pixel', {
    message0: '画点 x:%1 y:%2 %3',
    args0: [
      { type: 'input_value', name: 'X', check: 'Number' },
      { type: 'input_value', name: 'Y', check: 'Number' },
      { type: 'field_dropdown', name: 'V', options: [['亮', '1'], ['灭', '0']] }
    ],
    previousStatement: null, nextStatement: null, colour: C.oled, inputsInline: true
  }, function () {
    this.getInput('X').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">10</field></shadow>'));
    this.getInput('Y').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">10</field></shadow>'));
  });

  def('zk_oled_line', {
    message0: '画线段 (%1 , %2) → (%3 , %4)',
    args0: ['X1', 'Y1', 'X2', 'Y2'].map(function (n, i) {
      return { type: 'input_value', name: n, check: 'Number' };
    }),
    previousStatement: null, nextStatement: null, colour: C.oled, inputsInline: true
  });

  def('zk_oled_rect', {
    message0: '画矩形 x:%1 y:%2 宽:%3 高:%4 %5',
    args0: [
      { type: 'input_value', name: 'X', check: 'Number' },
      { type: 'input_value', name: 'Y', check: 'Number' },
      { type: 'input_value', name: 'W', check: 'Number' },
      { type: 'input_value', name: 'H', check: 'Number' },
      { type: 'field_dropdown', name: 'FILL', options: [['空心', 'rect'], ['实心', 'fill_rect']] }
    ],
    previousStatement: null, nextStatement: null, colour: C.oled, inputsInline: true
  });

  def('zk_oled_circle', {
    message0: '画圆 圆心(%1 , %2) 半径:%3 %4',
    args0: [
      { type: 'input_value', name: 'X', check: 'Number' },
      { type: 'input_value', name: 'Y', check: 'Number' },
      { type: 'input_value', name: 'R', check: 'Number' },
      { type: 'field_dropdown', name: 'FILL', options: [['空心', 'circle'], ['实心', 'fill_circle']] }
    ],
    previousStatement: null, nextStatement: null, colour: C.oled, inputsInline: true
  });

  def('zk_oled_invert', {
    message0: '屏幕反色 %1',
    args0: [{ type: 'field_dropdown', name: 'V', options: [['正常显示', '0'], ['反色显示', '1']] }],
    previousStatement: null, nextStatement: null, colour: C.oled
  });

  /* 屏幕文字颜色（单色屏 8 色） */
  def('zk_oled_text_color', {
    message0: '屏幕文字颜色 %1',
    args0: [{
      type: 'field_dropdown', name: 'C', options: [
        ['白色', 'white'], ['黑色', 'black'], ['红色', 'red'], ['绿色', 'green'],
        ['蓝色', 'blue'], ['黄色', 'yellow'], ['青色', 'cyan'], ['品红', 'magenta']
      ]
    }],
    previousStatement: null, nextStatement: null, colour: C.oled,
    tooltip: '设置后续「屏幕显示文字」使用的颜色'
  });

  def('zk_oled_text_color_do', {
    message0: '显示文字 %1 于 x:%2 y:%3 颜色 %4',
    args0: [
      { type: 'input_value', name: 'T' },
      { type: 'input_value', name: 'X', check: 'Number' },
      { type: 'input_value', name: 'Y', check: 'Number' },
      {
        type: 'field_dropdown', name: 'C', options: [
          ['白色', 'white'], ['黑色', 'black'], ['红色', 'red'], ['绿色', 'green'],
          ['蓝色', 'blue'], ['黄色', 'yellow'], ['青色', 'cyan'], ['品红', 'magenta']
        ]
      }
    ],
    previousStatement: null, nextStatement: null, colour: C.oled,
    inputsInline: true, tooltip: '带颜色地显示文字（坐标以文字左上角为起点）'
  });

  def('zk_oled_show', {
    message0: '刷新屏幕显示',
    args0: [], previousStatement: null, nextStatement: null, colour: C.oled,
    tooltip: '把缓冲区内容送到屏幕显示'
  });

  /* —— 屏幕显示图片 / 表情（依据 oled.Bitmap + framebuf） ——
     第三十六轮：图片积木只管用户上传的图片，表情交给「屏幕显示表情」积木，
     两者不再重复。 */
  def('zk_oled_image', {
    message0: '屏幕显示图片 %1',
    args0: [{ type: 'field_dropdown', name: 'IMG', options: function () { return imgOptions(); } }],
    previousStatement: null, nextStatement: null, colour: C.oled,
    tooltip: '把选择的图片（已像素化为 128×64 单色位图）显示到掌控板屏幕。' +
      '图片在左下角「素材」里上传；内置表情请用「屏幕显示表情」积木'
  }, function () {
    /* 下拉项在图片库变化后刷新 */
    this.refreshImg_ = true;
  });

  def('zk_oled_face', {
    message0: '屏幕显示表情 %1',
    args0: [{ type: 'field_dropdown', name: 'FACE', options: ZKB.FACE_OPTIONS }],
    previousStatement: null, nextStatement: null, colour: C.oled,
    tooltip: '内置表情位图（喜/怒/哀/乐…），虚拟仿真与舞台小助手表情同步变化。' +
      '要显示自己上传的图片请用「屏幕显示图片」积木'
  });

  def('zk_oled_roundrect', {
    message0: '画圆角矩形 x:%1 y:%2 宽:%3 高:%4 圆角:%5 %6',
    args0: [
      { type: 'input_value', name: 'X', check: 'Number' },
      { type: 'input_value', name: 'Y', check: 'Number' },
      { type: 'input_value', name: 'W', check: 'Number' },
      { type: 'input_value', name: 'H', check: 'Number' },
      { type: 'input_value', name: 'R', check: 'Number' },
      { type: 'field_dropdown', name: 'V', options: [['点亮', '1'], ['熄灭', '0']] }
    ],
    previousStatement: null, nextStatement: null, colour: C.oled, inputsInline: true
  });

  def('zk_oled_hline', {
    message0: '画横线 x:%1 y:%2 长度:%3 %4',
    args0: [
      { type: 'input_value', name: 'X', check: 'Number' },
      { type: 'input_value', name: 'Y', check: 'Number' },
      { type: 'input_value', name: 'W', check: 'Number' },
      { type: 'field_dropdown', name: 'V', options: [['点亮', '1'], ['熄灭', '0']] }
    ],
    previousStatement: null, nextStatement: null, colour: C.oled, inputsInline: true
  });

  def('zk_oled_vline', {
    message0: '画竖线 x:%1 y:%2 长度:%3 %4',
    args0: [
      { type: 'input_value', name: 'X', check: 'Number' },
      { type: 'input_value', name: 'Y', check: 'Number' },
      { type: 'input_value', name: 'L', check: 'Number' },
      { type: 'field_dropdown', name: 'V', options: [['点亮', '1'], ['熄灭', '0']] }
    ],
    previousStatement: null, nextStatement: null, colour: C.oled, inputsInline: true
  });

  def('zk_oled_triangle', {
    message0: '画三角形 (%1,%2)(%3,%4)(%5,%6) %7',
    args0: ['X0', 'Y0', 'X1', 'Y1', 'X2', 'Y2'].map(function (n) {
      return { type: 'input_value', name: n, check: 'Number' };
    }).concat([{ type: 'field_dropdown', name: 'V', options: [['点亮', '1'], ['熄灭', '0']] }]),
    previousStatement: null, nextStatement: null, colour: C.oled, inputsInline: true,
    tooltip: '依据 oled.fill_triangle 绘制实心三角形'
  });

  def('zk_oled_progress', {
    message0: '画进度条 x:%1 y:%2 宽:%3 高:%4 进度:%5 %',
    args0: [
      { type: 'input_value', name: 'X', check: 'Number' },
      { type: 'input_value', name: 'Y', check: 'Number' },
      { type: 'input_value', name: 'W', check: 'Number' },
      { type: 'input_value', name: 'H', check: 'Number' },
      { type: 'input_value', name: 'P', check: 'Number' }
    ],
    previousStatement: null, nextStatement: null, colour: C.oled, inputsInline: true,
    tooltip: 'UI.ProgressBar 进度条，progress 为 0~100'
  });

  def('zk_oled_stripbar', {
    message0: '画柱状条 x:%1 y:%2 宽:%3 高:%4 进度:%5% 方向:%6 外框:%7',
    args0: [
      { type: 'input_value', name: 'X', check: 'Number' },
      { type: 'input_value', name: 'Y', check: 'Number' },
      { type: 'input_value', name: 'W', check: 'Number' },
      { type: 'input_value', name: 'H', check: 'Number' },
      { type: 'input_value', name: 'P', check: 'Number' },
      { type: 'field_dropdown', name: 'DIR', options: [['水平', '1'], ['垂直', '0']] },
      { type: 'field_dropdown', name: 'FR', options: [['显示外框', '1'], ['不显示外框', '0']] }
    ],
    previousStatement: null, nextStatement: null, colour: C.oled, inputsInline: true,
    tooltip: 'UI.stripBar 柱状条：dir=1 水平，dir=0 垂直；frame=1 显示外框'
  });

  /* ============================================================
   * 四、RGB 彩灯
   * ============================================================ */
  def('zk_rgb_one', {
    message0: '设置彩灯 %1 为 %2',
    args0: [
      { type: 'field_dropdown', name: 'N', options: ZKB.RGB_OPTIONS },
      { type: 'field_colour', name: 'COLOR', colour: '#ff0000' }
    ],
    previousStatement: null, nextStatement: null, colour: C.rgb, inputsInline: true,
    tooltip: '掌控板正面有 3 颗 RGB 灯珠（编号 0、1、2）'
  });

  def('zk_rgb_rgb', {
    message0: '彩灯 %1 红 %2 绿 %3 蓝 %4',
    args0: [
      { type: 'field_dropdown', name: 'N', options: ZKB.RGB_OPTIONS },
      { type: 'input_value', name: 'R', check: 'Number' },
      { type: 'input_value', name: 'G', check: 'Number' },
      { type: 'input_value', name: 'B', check: 'Number' }
    ],
    previousStatement: null, nextStatement: null, colour: C.rgb, inputsInline: true
  }, function () {
    [['R', '255'], ['G', '0'], ['B', '0']].forEach(function (p) {
      this.getInput(p[0]).connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">' + p[1] + '</field></shadow>'));
    }, this);
  });

  def('zk_rgb_clear', {
    message0: '关闭全部彩灯',
    args0: [], previousStatement: null, nextStatement: null, colour: C.rgb
  });

  def('zk_rgb_brightness', {
    message0: '设置彩灯亮度 %1 （0~100）',
    args0: [{ type: 'input_value', name: 'V', check: 'Number' }],
    previousStatement: null, nextStatement: null, colour: C.rgb, inputsInline: true,
    tooltip: '默认亮度 80%；亮度会同时影响灯珠颜色深浅与光晕强弱'
  }, function () { this.getInput('V').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">80</field></shadow>')); });

  /* 第四十五轮：刷新彩灯（rgb.write()）
   * 官方示例里每次改完颜色都要跟一句 rgb.write() 才生效
   * （WS2812 需要这句把数据锁存到灯带），
   * 六年级示例的 py 反解也需要它，所以单独做一个积木。 */
  def('zk_rgb_write', {
    message0: '刷新彩灯',
    args0: [], previousStatement: null, nextStatement: null, colour: C.rgb,
    tooltip: '把刚才设置的颜色真正刷到彩灯上（官方写法 rgb.write()）'
  });

  /* ============================================================
   * 五、按键 / 触摸（值积木）
   * ============================================================ */
  def('zk_is_btn', {
    message0: '按键 %1 被按下？',
    args0: [{ type: 'field_dropdown', name: 'BTN', options: ZKB.BTN_OPTIONS }],
    output: 'Boolean', colour: C.key, tooltip: '按住时为“真”'
  });
  def('zk_is_touch', {
    message0: '触摸 %1 被触摸？',
    args0: [{ type: 'field_dropdown', name: 'PAD', options: ZKB.TOUCH_OPTIONS }],
    output: 'Boolean', colour: C.key
  });

  /* ============================================================
   * 六、板载传感器
   * ============================================================ */
  def('zk_light', {
    message0: '板载光线强度（0~4095）',
    args0: [], output: 'Number', colour: C.onboard, tooltip: '板载光敏传感器，越亮数值越大'
  });
  def('zk_sound', {
    message0: '板载声音强度（0~4095）',
    args0: [], output: 'Number', colour: C.onboard, tooltip: '板载麦克风采集的音量'
  });
  def('zk_accel', {
    message0: '加速度 %1',
    args0: [{ type: 'field_dropdown', name: 'AXIS', options: [['X 轴', 'x'], ['Y 轴', 'y'], ['Z 轴', 'z']] }],
    output: 'Number', colour: C.onboard
  });
  def('zk_tilt', {
    message0: '倾斜角 %1 （度）',
    args0: [{ type: 'field_dropdown', name: 'K', options: [['俯仰 Pitch', 'p'], ['横滚 Roll', 'r']] }],
    output: 'Number', colour: C.onboard
  });

  /* ============================================================
   * 七、蜂鸣器 / 音乐
   * ============================================================ */
  def('zk_note', {
    message0: '播放音符 %1 节拍 %2',
    args0: [
      { type: 'field_dropdown', name: 'NOTE', options: ZKB.NOTES },
      { type: 'field_dropdown', name: 'BEAT', options: [['半拍', '0.5'], ['1 拍', '1'], ['2 拍', '2'], ['4 拍', '4']] }
    ],
    previousStatement: null, nextStatement: null, colour: C.sound, inputsInline: true
  });
  def('zk_tone', {
    message0: '播放频率 %1 Hz 持续 %2 秒',
    args0: [
      { type: 'input_value', name: 'F', check: 'Number' },
      { type: 'input_value', name: 'D', check: 'Number' }
    ],
    previousStatement: null, nextStatement: null, colour: C.sound, inputsInline: true
  }, function () {
    this.getInput('F').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">440</field></shadow>'));
    this.getInput('D').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">0.5</field></shadow>'));
  });
  def('zk_music_stop', {
    message0: '停止蜂鸣器',
    args0: [], previousStatement: null, nextStatement: null, colour: C.sound
  });

  /* ============================================================
   * 八、引脚输入输出
   * 第二十六轮按参考图拆分引脚：
   *   · 数字引脚 = P0~P2、P8~P16（不含 P3~P7 / P17~P27，这些不直出）
   *   · 模拟引脚 = 读取只支持 ADC 的 P0 / P1 / P2 / P8 / P9；
   *     输出（PWM）支持 P0、P1、P5~P9、P11、P13~P16 等可作 PWM 的脚。
   * ============================================================ */
  /* 数字引脚（可数字输入 / 数字输出） */
  ZKB.PIN_DIGITAL_OPTIONS = [
    ['P0', '0'], ['P1', '1'], ['P2', '2'],
    ['P8', '8'], ['P9', '9'], ['P10', '10'], ['P11', '11'],
    ['P13', '13'], ['P14', '14'], ['P15', '15'], ['P16', '16']
  ];
  /* 模拟输入（ADC 读取）——掌控板仅 P0 / P1 / P2 / P8 / P9 支持模拟输入 */
  ZKB.PIN_ANALOG_IN_OPTIONS = [
    ['P0', '0'], ['P1', '1'], ['P2', '2'], ['P8', '8'], ['P9', '9']
  ];
  /* 模拟输出（PWM）——可作 PWM 输出的引脚 */
  ZKB.PIN_ANALOG_OUT_OPTIONS = [
    ['P0', '0'], ['P1', '1'], ['P2', '2'], ['P5', '5'], ['P6', '6'],
    ['P7', '7'], ['P8', '8'], ['P9', '9'], ['P10', '10'], ['P11', '11'],
    ['P13', '13'], ['P14', '14'], ['P15', '15'], ['P16', '16']
  ];
  /* 兼容旧字段名（其它模块 / 历史工程可能仍在用） */
  ZKB.PIN_OPTIONS = ZKB.PIN_DIGITAL_OPTIONS;

  /* ============================================================
   * 八、引脚输入输出（旧定义已被上面的新选项表替代）
   * ============================================================ */
  def('zk_pin_dout', {
    message0: '设置数字引脚 %1 输出 %2',
    args0: [
      { type: 'field_dropdown', name: 'PIN', options: ZKB.PIN_DIGITAL_OPTIONS },
      { type: 'field_dropdown', name: 'V', options: [['低电平', '0'], ['高电平', '1']] }
    ],
    previousStatement: null, nextStatement: null, colour: C.pin, inputsInline: true,
    tooltip: '设置数字引脚输出高/低电平'
  });
  def('zk_pin_pwm', {
    message0: '设置模拟引脚 %1 输出(PWM) %2',
    args0: [
      { type: 'field_dropdown', name: 'PIN', options: ZKB.PIN_ANALOG_OUT_OPTIONS },
      { type: 'input_value', name: 'V', check: 'Number' }
    ],
    previousStatement: null, nextStatement: null, colour: C.pin, inputsInline: true,
    tooltip: '设置模拟引脚输出 PWM（0~1023）'
  }, function () { this.getInput('V').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">512</field></shadow>')); });
  def('zk_pin_din', {
    message0: '读取数字引脚 %1',
    args0: [{ type: 'field_dropdown', name: 'PIN', options: ZKB.PIN_DIGITAL_OPTIONS }],
    output: 'Number', colour: C.pin, outputShape: Blockly.OUTPUT_SHAPE_HEXAGON,
    tooltip: '读取数字引脚的电平（高电平 1 / 低电平 0）'
  });
  def('zk_pin_ain', {
    message0: '读取模拟引脚 %1',
    args0: [{ type: 'field_dropdown', name: 'PIN', options: ZKB.PIN_ANALOG_IN_OPTIONS }],
    output: 'Number', colour: C.pin, outputShape: Blockly.OUTPUT_SHAPE_HEXAGON,
    tooltip: '读取模拟引脚的 ADC 值（0~1023）'
  });

  /* ============================================================
   * 九、拓展设备积木（每个类型默认一个实例）
   * ============================================================ */
  // 温湿度传感器
  def('zk_dht_measure', {
    message0: '温湿度传感器：测量一次',
    args0: [], previousStatement: null, nextStatement: null, colour: C.dht
  });
  def('zk_dht_val', {
    message0: '温湿度传感器的 %1',
    args0: [{ type: 'field_dropdown', name: 'K', options: [['温度（℃）', 't'], ['湿度（%）', 'h']] }],
    output: 'Number', colour: C.dht
  });

  // 超声波
  def('zk_ultra', {
    message0: '超声波传感器测得距离（厘米）',
    args0: [], output: 'Number', colour: C.ultra
  });

  /* 第四十五轮：初始化超声波（语句型）
   * 官方 mxml 里有 hunan_mpython_bluebit_ultrasonic_init，
   * 是一个无参数的语句块（放在 next 里）。 */
  def('zk_ultra_init', {
    message0: '初始化超声波传感器',
    args0: [], previousStatement: null, nextStatement: null, colour: C.ultra,
    tooltip: '使用超声波前先初始化一次（官方 bluebit 超声波的用法）'
  });

  // 舵机
  def('zk_servo', {
    message0: '舵机转到 %1 度',
    args0: [{ type: 'input_value', name: 'A', check: 'Number' }],
    previousStatement: null, nextStatement: null, colour: C.servo, inputsInline: true
  }, function () { this.getInput('A').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">90</field></shadow>')); });

  // 红外传感器
  def('zk_ir', {
    message0: '红外传感器检测到障碍物？',
    args0: [], output: 'Boolean', colour: C.ir
  });

  // 加热元件
  def('zk_heat', {
    message0: '加热元件 %1',
    args0: [{ type: 'field_dropdown', name: 'V', options: [['打开', '1'], ['关闭', '0']] }],
    previousStatement: null, nextStatement: null, colour: C.heater
  });
  def('zk_heat_power', {
    message0: '加热元件功率设为 %1 %',
    args0: [{ type: 'input_value', name: 'V', check: 'Number' }],
    previousStatement: null, nextStatement: null, colour: C.heater, inputsInline: true
  }, function () { this.getInput('V').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">50</field></shadow>')); });

  // 小车
  def('zk_car', {
    message0: '小车 %1 速度 %2',
    args0: [
      { type: 'field_dropdown', name: 'DIR', options: [['前进', 'f'], ['后退', 'b'], ['原地左转', 'l'], ['原地右转', 'r'], ['停止', 's']] },
      { type: 'input_value', name: 'S', check: 'Number' }
    ],
    previousStatement: null, nextStatement: null, colour: C.car, inputsInline: true
  }, function () { this.getInput('S').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">60</field></shadow>')); });
  def('zk_car_wheels', {
    message0: '小车左右轮速  左 %1 右 %2 （-100~100）',
    args0: [
      { type: 'input_value', name: 'L', check: 'Number' },
      { type: 'input_value', name: 'R', check: 'Number' }
    ],
    previousStatement: null, nextStatement: null, colour: C.car, inputsInline: true
  });

  // 直流电机
  def('zk_motor', {
    message0: '直流电机 %1 速度 %2 （0~100）',
    args0: [
      { type: 'field_dropdown', name: 'DIR', options: [['正转', 'f'], ['反转', 'b'], ['停止', 's']] },
      { type: 'input_value', name: 'S', check: 'Number' }
    ],
    previousStatement: null, nextStatement: null, colour: C.motor, inputsInline: true
  }, function () { this.getInput('S').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">60</field></shadow>')); });

  // 水泵
  def('zk_pump', {
    message0: '水泵 %1',
    args0: [{ type: 'field_dropdown', name: 'V', options: [['打开', '1'], ['关闭', '0']] }],
    previousStatement: null, nextStatement: null, colour: C.pump
  });
  def('zk_pump_power', {
    message0: '水泵功率设为 %1 % （0~100）',
    args0: [{ type: 'input_value', name: 'V', check: 'Number' }],
    previousStatement: null, nextStatement: null, colour: C.pump, inputsInline: true
  }, function () { this.getInput('V').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">80</field></shadow>')); });

  // 颜色传感器
  def('zk_color_rgb', {
    message0: '颜色传感器 %1 通道值',
    args0: [{ type: 'field_dropdown', name: 'K', options: [['红 R', 'r'], ['绿 G', 'g'], ['蓝 B', 'b'], ['亮度', 'c']] }],
    output: 'Number', colour: C.color
  });
  def('zk_color_seen', {
    message0: '颜色传感器看到 %1 ？',
    args0: [{ type: 'field_dropdown', name: 'COLOR', options: [
      ['红色', 'red'], ['绿色', 'green'], ['蓝色', 'blue'], ['黄色', 'yellow'],
      ['紫色', 'purple'], ['白色', 'white'], ['黑色', 'black']
    ] }],
    output: 'Boolean', colour: C.color
  });

  // AI 摄像头
  def('zk_camera_result', {
    message0: '摄像头识别到的内容（文字）',
    args0: [], output: 'String', colour: C.camera,
    tooltip: '仿真中可在摄像头画面上点击切换识别目标'
  });
  def('zk_camera_seen', {
    message0: '摄像头是否看到 %1 ？',
    args0: [{ type: 'field_dropdown', name: 'OBJ', options: [
      ['人脸', 'face'], ['行人', 'person'], ['物体', 'object'],
      ['颜色', 'color'], ['二维码', 'qrcode']
    ] }],
    output: 'Boolean', colour: C.camera
  });

  /* ---------- AI 摄像头：文字识别（第二十三轮） ----------
     对应官方 AI 摄像头的「印刷文字 / 印刷数字」识别：
     先启动识别（自动拍照取帧），再用结果积木读取。*/
  def('zk_vision_ocr_start', {
    message0: '启动 %1 识别',
    args0: [{ type: 'field_dropdown', name: 'MODE', options: [
      ['印刷文字', 'text'], ['印刷数字', 'number']
    ] }],
    nextStatement: null, colour: C.camera, hat: 'cap',
    tooltip: '调用摄像头拍照，识别画面中的印刷文字或数字；识别结果存到摄像头里'
  });
  def('zk_vision_ocr_text', {
    message0: '印刷文字识别结果',
    args0: [], output: 'String', colour: C.camera,
    tooltip: '读取上一次「启动 印刷文字 识别」的结果'
  });
  def('zk_vision_ocr_number', {
    message0: '印刷数字识别结果',
    args0: [], output: 'Number', colour: C.camera,
    tooltip: '读取上一次「启动 印刷数字 识别」的结果（取文字里的数字部分）'
  });

  /* ---------- AI 摄像头：人脸识别 ----------
     先「注册 人脸信息」（姓名 / 性别 / 简介 + 一张人脸图），
     再「启动人脸验证」，最后用结果积木读取姓名、性别、简介。*/
  def('zk_vision_face_register', {
    message0: '注册 %1 的人脸信息 性别 %2 简介 %3',
    args0: [
      { type: 'input_value', name: 'NAME' },
      { type: 'field_dropdown', name: 'GENDER', options: [['男', 'male'], ['女', 'female']] },
      { type: 'input_value', name: 'BIO' }
    ],
    inputsInline: false, colour: C.camera, hat: 'cap',
    tooltip: '把人脸与姓名关联：先在摄像头卡片里上传或拍一张人脸照片，再把姓名与简介接上来'
  });
  def('zk_vision_face_verify', {
    message0: '启动人脸验证 %1',
    /* Blockly 不允许空 options 数组，故用函数形式：每次新建积木时读取当前人脸库。
       人脸库后续变化由 ZKB.refreshFaceBlocks() 就地刷新。 */
    args0: [{
      type: 'field_dropdown', name: 'NAME',
      options: function () {
        var list = [];
        try { list = ZKB.Vision ? ZKB.Vision.faceList() : []; } catch (e) { list = []; }
        if (!list.length) return [['（尚未录入人脸）', '']];
        return list.map(function (f) { return [f.name, f.name]; });
      }
    }],
    nextStatement: null, colour: C.camera, hat: 'cap',
    tooltip: '调用摄像头拍照，与已登记的人脸比对；下拉里是在摄像头卡片中录入的人脸'
  });
  def('zk_vision_face_name', {
    message0: '人脸验证结果-姓名',
    args0: [], output: 'String', colour: C.camera,
    tooltip: '验证通过返回姓名，未通过返回「未识别」'
  });
  def('zk_vision_face_gender', {
    message0: '人脸验证结果-性别',
    args0: [], output: 'String', colour: C.camera,
    tooltip: '返回「男」或「女」'
  });
  def('zk_vision_face_bio', {
    message0: '人脸验证结果-简介',
    args0: [], output: 'String', colour: C.camera,
    tooltip: '返回登记时填写的简介'
  });
  def('zk_vision_face_emotion', {
    message0: '人脸情绪识别结果 %1',
    args0: [{ type: 'field_dropdown', name: 'EM', options: [
      ['高兴', 'happy'], ['平静', 'calm'], ['惊讶', 'surprise'],
      ['生气', 'angry'], ['难过', 'sad']
    ] }],
    output: 'Boolean', colour: C.camera,
    tooltip: '判断当前人脸表情是不是指定情绪'
  });
  def('zk_vision_face_emotion_text', {
    message0: '人脸情绪',
    args0: [], output: 'String', colour: C.camera,
    tooltip: '返回当前识别到的情绪名称'
  });

  /* ---------- AI 摄像头：物体识别 ----------
     官方支持车型 / 动物 / 植物 / 菜品 / 果蔬五类，
     每类一个启动积木 + 一个结果积木，另有统一的置信度积木。*/
  def('zk_vision_obj_start', {
    message0: '启动 %1 识别',
    args0: [{ type: 'field_dropdown', name: 'CAT', options: [
      ['车型', 'car'], ['动物', 'animal'], ['植物', 'plant'],
      ['菜品', 'dish'], ['果蔬', 'fruit']
    ] }],
    nextStatement: null, colour: C.camera, hat: 'cap',
    tooltip: '调用摄像头拍照识别物体；结果与置信度同步到摄像头卡片'
  });
  def('zk_vision_obj_car', {
    message0: '车型识别结果',
    args0: [], output: 'String', colour: C.camera,
    tooltip: '如：轿车 / SUV / 卡车 / 摩托车'
  });
  def('zk_vision_obj_animal', {
    message0: '动物识别结果',
    args0: [], output: 'String', colour: C.camera
  });
  def('zk_vision_obj_plant', {
    message0: '植物识别结果',
    args0: [], output: 'String', colour: C.camera
  });
  def('zk_vision_obj_dish', {
    message0: '菜品识别结果',
    args0: [], output: 'String', colour: C.camera
  });
  def('zk_vision_obj_fruit', {
    message0: '果蔬识别结果',
    args0: [], output: 'String', colour: C.camera
  });
  def('zk_vision_confidence', {
    message0: '识别置信度（%）',
    args0: [], output: 'Number', colour: C.camera,
    tooltip: '0~100，数值越大越可信'
  });

  /* ---------- AI 摄像头：场景识别（第三十五轮） ----------
     讯飞场景识别接口可判断室内/室外、自然/城市等场景标签。*/
  def('zk_vision_scene_start', {
    message0: '启动场景识别',
    args0: [], nextStatement: null, colour: C.camera, hat: 'cap',
    tooltip: '调用摄像头拍照，判断画面场景（室内/室外、自然/城市等）'
  });
  def('zk_vision_scene_result', {
    message0: '场景识别结果',
    args0: [], output: 'String', colour: C.camera,
    tooltip: '读取上一次「启动场景识别」的结果'
  });

  /* ---------- AI 摄像头：手写文字识别（第三十五轮） ---------- */
  def('zk_vision_handwrite_start', {
    message0: '启动手写文字识别',
    args0: [], nextStatement: null, colour: C.camera, hat: 'cap',
    tooltip: '调用摄像头拍照，识别画面中的手写文字'
  });
  def('zk_vision_handwrite_text', {
    message0: '手写文字识别结果',
    args0: [], output: 'String', colour: C.camera,
    tooltip: '读取上一次「启动手写文字识别」的结果'
  });

  /* ---------- AI 摄像头：拍照速算（第三十五轮） ---------- */
  def('zk_vision_calc_start', {
    message0: '启动拍照速算识别',
    args0: [], nextStatement: null, colour: C.camera, hat: 'cap',
    tooltip: '调用摄像头拍照，识别画面中的算式并算出答案'
  });
  def('zk_vision_calc_text', {
    message0: '速算识别-算式',
    args0: [], output: 'String', colour: C.camera,
    tooltip: '读取识别到的算式文本，如「12+8=」'
  });
  def('zk_vision_calc_answer', {
    message0: '速算识别-答案',
    args0: [], output: 'Number', colour: C.camera,
    tooltip: '读取速算算式的计算结果'
  });
  def('zk_vision_calc_correct', {
    message0: '速算识别-是否正确',
    args0: [], output: 'Boolean', colour: C.camera,
    tooltip: '讯飞速算接口判分：正确为真，错误为假'
  });

  /* ---------- AI 摄像头：人脸数量与属性（第三十五轮） ---------- */
  def('zk_vision_face_count', {
    message0: '画面中的人脸数量',
    args0: [], output: 'Number', colour: C.camera,
    tooltip: '统计画面里检测到几张人脸'
  });
  def('zk_vision_face_attr', {
    message0: '人脸属性 %1',
    args0: [{ type: 'field_dropdown', name: 'A', options: [
      ['性别', 'gender'], ['年龄', 'age'], ['表情', 'emotion'], ['颜值', 'score']
    ] }],
    output: 'String', colour: C.camera,
    tooltip: '读取当前画面中第一张人脸的属性'
  });

  /* ---------- AI 摄像头：K210 本地模型（第三十五轮） ----------
     参考 mPythonSoftware-docs 的 k210 模块文档：
     AI 摄像头 / 1956 / 人工智能交互实验箱的 flash 里预置了三个模型：
       人脸追踪 (yolo2)   0x300000
       手写数字 (分类器)  0x600000
       20 类 (yolo2)      0x640000
     这些是板上跑的自带模型，不依赖网络，是真机上最可靠的识别方式。*/

  /* 20 类模型的类别标签（与官方 20class 示例一致） */
  var K210_CLASSES = [
    ['人', 0], ['自行车', 1], ['汽车', 2], ['摩托车', 3], ['飞机', 4], ['公交车', 5],
    ['火车', 6], ['卡车', 7], ['船', 8], ['红灯', 9], ['黄灯', 10], ['绿灯', 11],
    ['蓝灯', 12], ['斑马线', 13], ['猫', 14], ['狗', 15], ['鸟', 16], ['马', 17],
    ['蝴蝶', 18], ['向日葵', 19]
  ];

  def('zk_k210_kpu_load', {
    message0: '加载 K210 模型 %1',
    args0: [{ type: 'field_dropdown', name: 'MODEL', options: [
      ['人脸追踪 (yolo2)', 'face'], ['手写数字 (分类器)', 'digit'], ['20 类 (yolo2)', 'class20']
    ] }],
    nextStatement: null, colour: C.camera, hat: 'cap',
    tooltip: '从 flash 里加载预置模型：人脸追踪 0x300000 / 手写数字 0x600000 / 20 类 0x640000'
  });

  def('zk_k210_face_detect', {
    message0: '启动人脸追踪',
    args0: [], nextStatement: null, colour: C.camera, hat: 'cap',
    tooltip: '用 yolo2 模型检测画面中的人脸，返回人脸数量与位置'
  });
  def('zk_k210_face_num', {
    message0: '检测到的人脸数量',
    args0: [], output: 'Number', colour: C.camera,
    tooltip: '当前画面中检测到的人脸个数'
  });
  def('zk_k210_face_x', {
    message0: '第 %1 张人脸的 x 坐标',
    args0: [{ type: 'input_value', name: 'N', check: 'Number' }],
    output: 'Number', colour: C.camera,
    tooltip: '人脸检测框左上角的横坐标（相对画面宽度）'
  });
  def('zk_k210_face_y', {
    message0: '第 %1 张人脸的 y 坐标',
    args0: [{ type: 'input_value', name: 'N', check: 'Number' }],
    output: 'Number', colour: C.camera,
    tooltip: '人脸检测框左上角的纵坐标（相对画面高度）'
  });
  def('zk_k210_face_w', {
    message0: '第 %1 张人脸的宽度',
    args0: [{ type: 'input_value', name: 'N', check: 'Number' }],
    output: 'Number', colour: C.camera,
    tooltip: '人脸检测框的宽度'
  });
  def('zk_k210_face_h', {
    message0: '第 %1 张人脸的高度',
    args0: [{ type: 'input_value', name: 'N', check: 'Number' }],
    output: 'Number', colour: C.camera,
    tooltip: '人脸检测框的高度'
  });
  def('zk_k210_face_value', {
    message0: '第 %1 张人脸的置信度',
    args0: [{ type: 'input_value', name: 'N', check: 'Number' }],
    output: 'Number', colour: C.camera,
    tooltip: '检测到该人脸的概率（0~1）'
  });

  def('zk_k210_obj_detect', {
    message0: '启动 %1 识别',
    args0: [{ type: 'field_dropdown', name: 'MODEL', options: [
      ['20 类物体', 'class20'], ['手写数字', 'digit']
    ] }],
    nextStatement: null, colour: C.camera, hat: 'cap',
    tooltip: '用板上预置模型识别物体：20 类 yolo2 或手写数字分类器'
  });
  def('zk_k210_obj_label', {
    message0: '识别到的 %1',
    args0: [{ type: 'field_dropdown', name: 'IDX', options: function () {
      return K210_CLASSES.map(function (c) { return [c[0], String(c[1])]; });
    } }],
    output: 'String', colour: C.camera,
    tooltip: '读取第 N 个识别结果对应的类别名称'
  });
  def('zk_k210_obj_count', {
    message0: '识别到的物体数量',
    args0: [], output: 'Number', colour: C.camera,
    tooltip: '当前画面中检测到的目标个数'
  });
  def('zk_k210_obj_value', {
    message0: '第 %1 个识别结果的置信度',
    args0: [{ type: 'input_value', name: 'N', check: 'Number' }],
    output: 'Number', colour: C.camera,
    tooltip: '检测到该目标的概率（0~1）'
  });

  def('zk_k210_digit', {
    message0: '手写数字识别结果',
    args0: [], output: 'Number', colour: C.camera,
    tooltip: '用分类器模型识别画面中的手写数字（0~9）'
  });

  // 外置麦克风
  def('zk_mic', {
    message0: '麦克风声音强度（0~4095）',
    args0: [], output: 'Number', colour: C.mic
  });

  // 外置光线传感器
  def('zk_ambient', {
    message0: '光线传感器光照强度（0~4095）',
    args0: [], output: 'Number', colour: C.light
  });

  // 土壤湿度传感器
  def('zk_soil', {
    message0: '土壤湿度（0~4095）',
    args0: [], output: 'Number', colour: C.soil,
    tooltip: '数值越大，土壤越湿润'
  });
  def('zk_soil_pct', {
    message0: '土壤湿度百分比（0~100%）',
    args0: [], output: 'Number', colour: C.soil
  });

  // PM2.5 传感器
  def('zk_pm25', {
    message0: 'PM2.5 浓度（μg/m³）',
    args0: [], output: 'Number', colour: C.pm25
  });
  def('zk_pm25_level', {
    message0: '空气质量等级',
    args0: [], output: 'String', colour: C.pm25,
    tooltip: '返回：优 / 良 / 轻度污染 / 中度污染 / 重度污染'
  });

  // 气压传感器
  def('zk_pressure', {
    message0: '大气压强（hPa）',
    args0: [], output: 'Number', colour: C.baro
  });
  def('zk_altitude', {
    message0: '海拔高度（米）',
    args0: [], output: 'Number', colour: C.baro
  });

  // 外接按键模块
  def('zk_ext_btn', {
    message0: '外接按键被按下？',
    args0: [], output: 'Boolean', colour: C.extbtn,
    tooltip: '需要先在“拓展”中添加按键模块'
  });

  // 风扇
  def('zk_fan', {
    message0: '风扇 %1',
    args0: [{ type: 'field_dropdown', name: 'V', options: [['打开', '1'], ['关闭', '0']] }],
    previousStatement: null, nextStatement: null, colour: C.fan
  });
  def('zk_fan_power', {
    message0: '风扇功率设为 %1 % （0~100）',
    args0: [{ type: 'input_value', name: 'V', check: 'Number' }],
    previousStatement: null, nextStatement: null, colour: C.fan, inputsInline: true
  }, function () { this.getInput('V').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">60</field></shadow>')); });

  /* ============================================================
   * 十、变量 / 列表 舞台监视器
   *
   * 第四十轮：变量与列表严格分开。
   * field_variable 默认会列出**所有**类型的变量（普通变量 + 列表），
   * 于是「显示变量」的下拉里会冒出「我的列表」，
   * 学生分不清哪个是变量哪个是列表。
   * 这里给变量类积木加 variableTypes: ['']（空字符串 = 普通变量），
   * 列表类积木保持 variableTypes: ['LIST']，两边互不干扰。
   * ============================================================ */
  def('zk_var_show', {
    message0: '显示变量 %1',
    args0: [{ type: 'field_variable', name: 'VAR', variable: '我的变量', variableTypes: [''], defaultType: '' }],
    previousStatement: null, nextStatement: null, colour: C.variable, inputsInline: true,
    tooltip: '在舞台上实时显示变量的值'
  });
  def('zk_var_hide', {
    message0: '隐藏变量 %1',
    args0: [{ type: 'field_variable', name: 'VAR', variable: '我的变量', variableTypes: [''], defaultType: '' }],
    previousStatement: null, nextStatement: null, colour: C.variable, inputsInline: true
  });
  def('zk_list_show', {
    message0: '显示列表 %1',
    args0: [{ type: 'field_variable', name: 'VAR', variable: '列表', variableTypes: ['LIST'], defaultType: 'LIST' }],
    previousStatement: null, nextStatement: null, colour: C.variable, inputsInline: true,
    tooltip: '在舞台上实时显示列表的全部项目'
  });
  def('zk_list_hide', {
    message0: '隐藏列表 %1',
    args0: [{ type: 'field_variable', name: 'VAR', variable: '列表', variableTypes: ['LIST'], defaultType: 'LIST' }],
    previousStatement: null, nextStatement: null, colour: C.variable, inputsInline: true
  });
  def('zk_list_clear', {
    message0: '删除 %1 的全部项目',
    args0: [{ type: 'input_value', name: 'LIST', check: 'Array' }],
    previousStatement: null, nextStatement: null, colour: C.variable, inputsInline: true
  }, function () {
    this.getInput('LIST').connection.setShadowDom(listShadowDom(this));
  });
  def('zk_list_contains', {
    message0: '%1 包含 %2 ？',
    args0: [
      { type: 'input_value', name: 'LIST', check: 'Array' },
      { type: 'input_value', name: 'ITEM' }
    ],
    output: 'Boolean', colour: C.variable, inputsInline: true
  }, function () {
    this.getInput('LIST').connection.setShadowDom(listShadowDom(this));
    this.getInput('ITEM').connection.setShadowDom(Blockly.utils.xml.textToDom(
      '<shadow type="text"><field name="TEXT">东西</field></shadow>'));
  });

  /* 列表积木输入口的默认影子
   *
   * 【为什么不能用固定写法】原来写的是
   *   <shadow type="variables_get">
   *     <field name="VAR" variableTypes="LIST" defaultType="LIST">列表</field>
   *   </shadow>
   * 但 Blockly 反序列化字段时只认 variabletype 属性，
   * variableTypes / defaultType 会被忽略 → 这个影子块反序列化时
   * 按「普通变量」处理，白白在工作区里造出一个叫「列表」的普通变量。
   *
   * 正确做法：指向工作区里真实存在的列表（连 id 一起带上），
   * 这样影子块显示的就是列表名；一个列表都没有时干脆不放影子，
   * 免得凭空造变量。
   *
   * 【第四十二轮】列表不再固定取 lists[0]，
   * 而是优先用「当前列表」（ZKB.getCurrentListId()）。
   * 否则学生新建了「新队伍」，
   * 拖出来的列表积木却还挂在旧列表「队伍名单」上，看着像没生效。 */
  function listShadowDom(block) {
    var ws = block.workspace;
    var lists = ws && ws.getVariablesOfType ? ws.getVariablesOfType('LIST') : [];
    if (!lists || !lists.length) return null;
    var v = pickCurrentList(lists);
    return Blockly.utils.xml.textToDom(
      '<shadow type="variables_get"><field name="VAR" id="' + v.getId() +
      '" variabletype="LIST">' + escapeAttr(v.name) + '</field></shadow>');
  }

  /* 从列表数组里挑出「当前列表」
   *
   * 优先级：当前选中 id → 第一个列表。
   * ZKB.getCurrentListId 由 app.js 提供（新建列表后会记录 id），
   * 这里做了兜底，避免 app.js 尚未加载时抛错。 */
  function pickCurrentList(lists) {
    if (!lists || !lists.length) return null;
    var curId = (global.ZKB && ZKB.getCurrentListId) ? ZKB.getCurrentListId() : '';
    if (curId) {
      for (var i = 0; i < lists.length; i++) {
        if (lists[i].getId() === curId) return lists[i];
      }
    }
    return lists[0];
  }

  /* ============================================================
   * 十一、通讯网络（物联网）
   * ============================================================ */
  // WiFi
  def('zk_wifi_connect', {
    message0: '连接 WiFi 名称 %1 密码 %2',
    args0: [
      { type: 'input_value', name: 'SSID' },
      { type: 'input_value', name: 'PWD' }
    ],
    previousStatement: null, nextStatement: null, colour: C.net, inputsInline: true,
    tooltip: '连接无线路由器，物联网项目的第一步'
  }, function () {
    this.getInput('SSID').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="text"><field name="TEXT">教室WiFi</field></shadow>'));
    this.getInput('PWD').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="text"><field name="TEXT">12345678</field></shadow>'));
  });
  def('zk_wifi_ok', {
    message0: 'WiFi 已连接？',
    args0: [], output: 'Boolean', colour: C.net
  });

  // 无线广播
  def('zk_radio_group', {
    message0: '无线广播频道设为 %1',
    args0: [{ type: 'input_value', name: 'G', check: 'Number' }],
    previousStatement: null, nextStatement: null, colour: C.net, inputsInline: true,
    tooltip: '频道相同（0~83）的掌控板之间可以互相收发消息'
  }, function () {
    this.getInput('G').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">7</field></shadow>'));
  });
  def('zk_radio_send', {
    message0: '无线广播发送 %1',
    args0: [{ type: 'input_value', name: 'MSG' }],
    previousStatement: null, nextStatement: null, colour: C.net, inputsInline: true
  }, function () {
    this.getInput('MSG').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="text"><field name="TEXT">你好</field></shadow>'));
  });
  def('zk_when_radio', {
    message0: '当收到无线广播时',
    args0: [], nextStatement: null, colour: C.net, hat: 'cap',
    tooltip: '收到同频道掌控板发来的消息时执行'
  });
  def('zk_radio_msg', {
    message0: '收到的广播内容',
    args0: [], output: 'String', colour: C.net
  });

  // NTP 网络时间
  def('zk_ntp_sync', {
    message0: 'NTP 网络对时',
    args0: [], previousStatement: null, nextStatement: null, colour: C.net,
    tooltip: '连接 WiFi 后通过网络校准掌控板的时间'
  });
  def('zk_time_now', {
    message0: '当前时间 %1',
    args0: [{
      type: 'field_dropdown', name: 'K', options: [
        ['完整日期时间', 'all'], ['年', 'year'], ['月', 'mon'], ['日', 'day'],
        ['时', 'hour'], ['分', 'min'], ['秒', 'sec'], ['星期', 'week']
      ]
    }],
    output: 'String', colour: C.net
  });

  // MQTT
  def('zk_mqtt_connect', {
    message0: '连接 MQTT 服务器 %1 端口 %2',
    args0: [
      { type: 'input_value', name: 'HOST' },
      { type: 'input_value', name: 'PORT', check: 'Number' }
    ],
    previousStatement: null, nextStatement: null, colour: C.net, inputsInline: true
  }, function () {
    this.getInput('HOST').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="text"><field name="TEXT">mqtt.example.cn</field></shadow>'));
    this.getInput('PORT').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">1883</field></shadow>'));
  });
  def('zk_mqtt_pub', {
    message0: 'MQTT 发布 主题 %1 内容 %2',
    args0: [
      { type: 'input_value', name: 'TOPIC' },
      { type: 'input_value', name: 'MSG' }
    ],
    previousStatement: null, nextStatement: null, colour: C.net, inputsInline: true
  }, function () {
    this.getInput('TOPIC').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="text"><field name="TEXT">/classroom/light</field></shadow>'));
    this.getInput('MSG').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="text"><field name="TEXT">on</field></shadow>'));
  });
  def('zk_when_mqtt', {
    message0: '当 MQTT 主题 %1 收到消息时',
    args0: [{ type: 'input_value', name: 'TOPIC' }],
    nextStatement: null, colour: C.net, hat: 'cap', inputsInline: true
  }, function () {
    this.getInput('TOPIC').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="text"><field name="TEXT">/classroom/light</field></shadow>'));
  });
  def('zk_mqtt_msg', {
    message0: 'MQTT 收到的消息内容',
    args0: [], output: 'String', colour: C.net
  });

  /* ============================================================
   * 第四十五轮：官方 mxml 的「语句版」广播 / MQTT 消息
   *
   * 【为什么要专门加这两个】
   * 官方 mPython 里，「当收到无线广播时」「当 MQTT 收到消息时」
   * 这两个事件积木下面挂的是一个**语句型**的消息块
   * （官方叫「收到的广播内容」，是带 next 的语句块）。
   * 而本项目的 zk_radio_msg / zk_mqtt_msg 是**值积木**
   * （output: String，要放进 value 口里）。
   *
   * 角色对不上，导入官方 mxml 时就会报
   *   "Next statement does not exist"
   * 整条程序链断掉。
   *
   * 这里补两个语句版积木，专门给官方 mxml 导入用：
   *   zk_radio_msg_do —— 「收到广播内容（作为语句）」
   *   zk_mqtt_msg_do  —— 「MQTT 消息内容（作为语句）」
   * 它们把消息内容打印到控制台，作用与官方的语句块一致。
   * ============================================================ */
  def('zk_radio_msg_do', {
    message0: '收到广播内容 %1',
    args0: [{ type: 'input_value', name: 'MSG' }],
    previousStatement: null, nextStatement: null, colour: C.net, inputsInline: true,
    tooltip: '收到无线广播时，把广播内容显示出来（官方 mxml 的语句型消息块）'
  }, function () {
    this.getInput('MSG').connection.setShadowDom(Blockly.utils.xml.textToDom(
      '<shadow type="text"><field name="TEXT">on</field></shadow>'));
  });
  def('zk_mqtt_msg_do', {
    message0: 'MQTT 消息内容 %1',
    args0: [{ type: 'input_value', name: 'MSG' }],
    previousStatement: null, nextStatement: null, colour: C.net, inputsInline: true,
    tooltip: '收到 MQTT 消息时，把消息内容显示出来（官方 mxml 的语句型消息块）'
  }, function () {
    this.getInput('MSG').connection.setShadowDom(Blockly.utils.xml.textToDom(
      '<shadow type="text"><field name="TEXT">on</field></shadow>'));
  });

  // WiFi 语音识别（旧积木，保留兼容）
  def('zk_asr_text', {
    message0: '语音识别到的文字',
    args0: [], output: 'String', colour: C.net,
    tooltip: '识别用户说出的指令（仿真中可在设备卡片上切换识别结果）'
  });

  /* ============================================================
   * 第二十四轮：AI 语音转文字 + AI 语音合成（掌控板板载能力）
   *   语音转文字：启动语音转文字 → 语音转文字结果 / 置信度 / 是否命中指令
   *   语音合成：朗读文字 → 停止朗读 / 正在朗读 / 朗读完毕 / 播报的文字
   * ============================================================ */

  /* ---------- AI 语音转文字 ---------- */
  def('zk_speech_recognize', {
    message0: '启动语音转文字 %1',
    args0: [{
      type: 'field_dropdown', name: 'CMD',
      options: [['（随机听一句）', ''],
      ['开灯', '开灯'], ['关灯', '关灯'], ['开风扇', '开风扇'], ['关风扇', '关风扇'],
      ['播放音乐', '播放音乐'], ['停止', '停止'], ['今天天气怎么样', '今天天气怎么样'],
      ['开始上课', '开始上课'], ['下课了', '下课了'], ['几点了', '几点了']]
    }],
    nextStatement: null, colour: C.onboard, hat: 'cap',
    tooltip: '调用麦克风听取一句话并转成文字；下拉里选定了指令就等于「对着它说」，'
      + '不选则从课堂常用指令里随机听一句。置信度受麦克风音量影响'
  });
  def('zk_speech_text', {
    message0: '语音转文字结果',
    args0: [], output: 'String', colour: C.onboard,
    tooltip: '读取上一次「启动语音转文字」听到的内容'
  });
  def('zk_speech_conf', {
    message0: '语音识别置信度（%）',
    args0: [], output: 'Number', colour: C.onboard,
    tooltip: '0~100。声音太小或太嘈杂都会让置信度下降'
  });
  def('zk_speech_is', {
    message0: '听到的指令是 %1 吗',
    args0: [{
      type: 'field_dropdown', name: 'CMD',
      options: [['开灯', '开灯'], ['关灯', '关灯'], ['开风扇', '开风扇'], ['关风扇', '关风扇'],
      ['播放音乐', '播放音乐'], ['停止', '停止'], ['开始上课', '开始上课'], ['下课了', '下课了']]
    }],
    output: 'Boolean', colour: C.onboard,
    tooltip: '判断听到的内容里是否包含指定指令，是则返回真'
  });

  /* ---------- AI 语音合成（文字转语音） ---------- */
  def('zk_speech_speak', {
    message0: '朗读 %1 语速 %2 音调 %3 音量 %4',
    args0: [
      { type: 'input_value', name: 'TEXT' },
      {
        type: 'field_dropdown', name: 'RATE', options: [
          ['正常', '1'], ['慢', '0.7'], ['快', '1.4'], ['很快', '1.8']
        ]
      },
      {
        type: 'field_dropdown', name: 'PITCH', options: [
          ['正常', '1'], ['低沉', '0.7'], ['偏高', '1.4']
        ]
      },
      {
        type: 'field_dropdown', name: 'VOL', options: [
          ['响', '1'], ['中', '0.7'], ['轻', '0.4']
        ]
      }
    ],
    inputsInline: false, nextStatement: null, colour: C.onboard, hat: 'cap',
    tooltip: '把文字读出来（电脑上用系统发音，可调语速/音调/音量）'
  });
  def('zk_speech_stop', {
    message0: '停止朗读',
    args0: [], previousStatement: null, colour: C.onboard,
    tooltip: '打断正在进行的朗读'
  });
  def('zk_speech_speaking', {
    message0: '正在朗读吗',
    args0: [], output: 'Boolean', colour: C.onboard
  });
  def('zk_speech_done', {
    message0: '朗读完毕',
    args0: [], output: 'Boolean', colour: C.onboard,
    tooltip: '本次朗读是否已经念完'
  });

  // 天气
  def('zk_weather', {
    message0: '城市 %1 的天气 %2',
    args0: [
      { type: 'input_value', name: 'CITY' },
      {
        type: 'field_dropdown', name: 'K', options: [
          ['天气现象', 'text'], ['最高温度(℃)', 'high'], ['最低温度(℃)', 'low'],
          ['湿度(%)', 'humidity'], ['风向', 'wind'], ['风力(级)', 'windLevel']
        ]
      }
    ],
    output: 'String', colour: C.net, inputsInline: true
  }, function () {
    this.getInput('CITY').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="text"><field name="TEXT">北京</field></shadow>'));
  });

  /* ============================================================
   * 十二、自制积木（自定义函数：支持数字/文本参数、布尔参数、文本标签）
   * ============================================================ */
  var PROC_COLOUR = C.procedure;

  function defaultSpec() {
    return { name: '我的积木', items: [], noRefresh: false };
  }

  /* 根据 spec 重建积木外观（名字 + 参数输入框 + 文本标签，全部内联一行）
     定义块与调用块用前缀符号区分（★ 定义 / ▸ 调用）。
     注：不使用 appendField(SVG) —— Blockly 的字段标签依赖文本测量，
     SVG 字段在部分环境下会导致渲染异常；用字符前缀更稳妥。 */
  function rebuildFromSpec(block, spec, withShadow) {
    block.setColour(PROC_COLOUR);
    while (block.inputList.length) block.removeInput(block.inputList[0].name);
    var dummy = block.appendDummyInput('HEAD')
      .appendField(withShadow ? '▸ ' : '★ ', 'ICON')
      .appendField(spec.name || '我的积木', 'NAME');
    (spec.items || []).forEach(function (it, i) {
      /* k==='label' 为文本标签；其余（arg）生成输入框。兼容历史的 k:'text' 写法 */
      if (it.k === 'label' || it.k === 'text') {
        dummy.appendField(it.text || it.t || '');
      } else {
        var input = block.appendValueInput('ARG' + i);
        input.setCheck(it.type === 'bool' ? 'Boolean' : null);
        if (withShadow) {
          input.connection.setShadowDom(Blockly.utils.xml.textToDom(
            it.type === 'bool'
              ? '<shadow type="logic_boolean"><field name="BOOL">TRUE</field></shadow>'
              : '<shadow type="math_number"><field name="NUM">0</field></shadow>'));
        }
        dummy = block.appendDummyInput('TAIL' + i);
      }
    });
    block.setInputsInline(true);
    block.spec_ = spec;
  }

  Blockly.Blocks['zk_my_def'] = {
    init: function () {
      this.hat = 'cap';
      this.setNextStatement(true);
      rebuildFromSpec(this, defaultSpec(), false);
    },
    mutationToDom: function () {
      var el = Blockly.utils.xml.createElement('mutation');
      el.setAttribute('spec', JSON.stringify(this.spec_ || defaultSpec()));
      return el;
    },
    domToMutation: function (el) {
      try { this.spec_ = JSON.parse(el.getAttribute('spec') || '{}'); }
      catch (e) { this.spec_ = defaultSpec(); }
      if (!this.spec_.items) this.spec_.items = [];
      rebuildFromSpec(this, this.spec_, false);
    },
    customContextMenu: function (options) {
      var self = this;
      options.unshift({
        text: '编辑自制积木…',
        enabled: true,
        callback: function () { if (ZKB.MyBlocks && ZKB.MyBlocks.openEdit) ZKB.MyBlocks.openEdit(self); }
      });
    }
  };

  Blockly.Blocks['zk_my_call'] = {
    init: function () {
      this.defId_ = null;
      this.setPreviousStatement(true);
      this.setNextStatement(true);
      rebuildFromSpec(this, defaultSpec(), true);
    },
    mutationToDom: function () {
      var el = Blockly.utils.xml.createElement('mutation');
      el.setAttribute('defid', this.defId_ || '');
      el.setAttribute('spec', JSON.stringify(this.spec_ || defaultSpec()));
      return el;
    },
    domToMutation: function (el) {
      this.defId_ = el.getAttribute('defid') || '';
      try { this.spec_ = JSON.parse(el.getAttribute('spec') || '{}'); }
      catch (e) { this.spec_ = defaultSpec(); }
      if (!this.spec_.items) this.spec_.items = [];
      rebuildFromSpec(this, this.spec_, true);
    }
  };

  /* 自制积木管理器：创建 / 编辑 / 同步调用块 */
  ZKB.MyBlocks = {
    allDefs: function (workspace) {
      return workspace.getTopBlocks(true).filter(function (b) { return b.type === 'zk_my_def'; });
    },
    /* 生成稳定的 Python/JS 函数名 */
    fnName: function (defId) {
      var s = '_mb_' + String(defId || '').replace(/[^a-zA-Z0-9]/g, '').slice(-10);
      return s === '_mb_' ? '_mb_x' : s;
    },
    argsOf: function (spec) {
      return (spec.items || []).filter(function (it) { return it.k === 'arg'; });
    },
    /* 新建定义块，返回该块（用 marker 精确定位，避免误取到其它顶层块） */
    createDef: function (workspace, spec) {
      var MARK = 'ZK_MYDEF_' + Date.now().toString(36);
      var xml = '<xml xmlns="https://developers.google.com/blockly/xml">' +
        '<block type="zk_my_def" id="' + MARK + '" x="60" y="' +
        (60 + this.allDefs(workspace).length * 140) + '">' +
        '<mutation spec="' + escapeAttr(JSON.stringify(spec)) + '"></mutation></block></xml>';
      var dom = Blockly.utils.xml.textToDom(xml);
      Blockly.Xml.domToWorkspace(dom, workspace);
      /* Blockly 会用随机 id 覆盖手写 id，故按位置 + 类型找回刚创建的块 */
      var defs = this.allDefs(workspace);
      var created = defs.filter(function (b) { return b.spec_ && b.spec_.name === spec.name; }).pop();
      return created || defs[defs.length - 1] || null;
    },
    /* 编辑定义块并同步全部调用块（尽量保留已连接参数） */
    updateDef: function (defBlock, spec) {
      var oldArgs = this.argsOf(defBlock.spec_ || {});
      var saved = {};
      var self = this;
      oldArgs.forEach(function (it, i) {
        var conn = defBlock.getInput('ARG' + i) && defBlock.getInput('ARG' + i).connection.targetConnection;
        if (conn) {
          var savedBlock = conn.sourceBlock_;
          saved[it.name] = savedBlock;
        }
      });
      defBlock.spec_ = spec;
      rebuildFromSpec(defBlock, spec, false);
      this.argsOf(spec).forEach(function (it, i) {
        if (saved[it.name]) {
          var input = defBlock.getInput('ARG' + i);
          if (input) try { input.connection.connect(saved[it.name].outputConnection); } catch (e) {}
        }
      });
      this.syncCalls(defBlock.workspace, defBlock.id, spec);
    },
    syncCalls: function (workspace, defId, spec) {
      var args = this.argsOf(spec);
      workspace.getAllBlocks(false).forEach(function (b) {
        if (b.type !== 'zk_my_call' || b.defId_ !== defId) return;
        var oldSpec = b.spec_ || defaultSpec();
        var saved = {};
        this.argsOf(oldSpec).forEach(function (it, i) {
          var input = b.getInput('ARG' + i);
          var conn = input && input.connection.targetConnection;
          if (conn) saved[it.name] = conn.sourceBlock_;
        });
        b.spec_ = spec;
        rebuildFromSpec(b, spec, true);
        args.forEach(function (it, i) {
          if (saved[it.name]) {
            var input = b.getInput('ARG' + i);
            if (input) try { input.connection.connect(saved[it.name].outputConnection); } catch (e) {}
          }
        });
      }, this);
    }
  };
  function escapeAttr(s) {
    return s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  /* ---------- 自定义积木类型清单（供设备依赖检查/示例使用） ---------- */
  ZKB.DEVICE_BLOCK_TYPES = {
    dht: ['zk_dht_measure', 'zk_dht_val'],
    ultrasonic: ['zk_ultra'],
    servo: ['zk_servo'],
    ir: ['zk_ir', 'zk_when_ir'],
    heater: ['zk_heat', 'zk_heat_power'],
    car: ['zk_car', 'zk_car_wheels'],
    motor: ['zk_motor'],
    pump: ['zk_pump', 'zk_pump_power'],
    color: ['zk_color_rgb', 'zk_color_seen'],
    camera: ['zk_camera_result', 'zk_camera_seen', 'zk_camera_seen',
    /* 第二十三轮：AI 视觉三大能力 */
    'zk_vision_ocr_start', 'zk_vision_ocr_text', 'zk_vision_ocr_number',
    'zk_vision_face_register', 'zk_vision_face_verify', 'zk_vision_face_name',
    'zk_vision_face_gender', 'zk_vision_face_bio', 'zk_vision_face_emotion',
    'zk_vision_face_emotion_text',
    'zk_vision_obj_start', 'zk_vision_obj_car', 'zk_vision_obj_animal',
    'zk_vision_obj_plant', 'zk_vision_obj_dish', 'zk_vision_obj_fruit',
    'zk_vision_confidence',
    /* 第三十五轮：场景 / 手写 / 速算 / 人脸属性 + K210 板上模型 */
    'zk_vision_scene_start', 'zk_vision_scene_result',
    'zk_vision_handwrite_start', 'zk_vision_handwrite_text',
    'zk_vision_calc_start', 'zk_vision_calc_text',
    'zk_vision_calc_answer', 'zk_vision_calc_correct',
    'zk_vision_face_count', 'zk_vision_face_attr',
    'zk_k210_kpu_load', 'zk_k210_face_detect', 'zk_k210_face_num',
    'zk_k210_face_x', 'zk_k210_face_y', 'zk_k210_face_w', 'zk_k210_face_h',
    'zk_k210_face_value', 'zk_k210_obj_detect', 'zk_k210_obj_label',
    'zk_k210_obj_count', 'zk_k210_obj_value', 'zk_k210_digit'],
    mic: ['zk_mic'],
    lightExt: ['zk_ambient'],
    soil: ['zk_soil', 'zk_soil_pct'],
    pm25: ['zk_pm25', 'zk_pm25_level'],
    baro: ['zk_pressure', 'zk_altitude'],
    button: ['zk_ext_btn'],
    fan: ['zk_fan', 'zk_fan_power'],
    radio: ['zk_radio_group', 'zk_radio_send', 'zk_when_radio', 'zk_radio_msg'],
    wifi: ['zk_wifi_connect', 'zk_wifi_ok'],
    ntp: ['zk_ntp_sync', 'zk_time_now'],
    mqtt: ['zk_mqtt_connect', 'zk_mqtt_pub', 'zk_when_mqtt', 'zk_mqtt_msg'],
    asr: ['zk_asr_text'],
    weather: ['zk_weather'],
    expboard: []
  };

  /* ============================================================
   * 六、mPython 官方图形化 API 兼容积木
   * 依据参考资料 mPythonSoftware-docs-master/source/blocks/*.rst
   * ============================================================ */

  /* ---- 音乐 ---- */
  def('zk_music_tempo', {
    message0: '设置音乐速度 %1 （BPM）',
    args0: [{ type: 'input_value', name: 'BPM', check: 'Number' }],
    previousStatement: null, nextStatement: null, colour: C.music,
    tooltip: 'music.set_tempo(bpm)：设置节拍速度（每分钟节拍数，默认 120）'
  }, function () {
    this.getInput('BPM').connection.setShadowDom(
      Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">120</field></shadow>'));
  });

  def('zk_music_get_tempo', {
    message0: '获取音乐速度', args0: [],
    output: null, colour: C.music, outputShape: Blockly.OUTPUT_SHAPE_ROUND,
    tooltip: 'music.tempo()：获取当前节拍速度（BPM）'
  });

  /* ---------- 音乐播放（内置曲目 + 上传音频） ---------- */
  /* 曲目下拉动态读取音乐库（ZKB.MusicLib.list()），素材库新增/删除后自动反映 */
  function musicOptions() {
    try {
      if (global.ZKB && ZKB.MusicLib && ZKB.MusicLib.list) {
        var arr = ZKB.MusicLib.list();
        if (arr.length) return arr.map(function (t) { return [t.name, t.id]; });
      }
    } catch (e) {}
    return [['（请先在素材库添加音乐）', '']];
  }
  /* 重复方式：播放一次 / 无限循环 / 在后台播放一次 / 在后台无限循环 */
  var MUSIC_REPEAT_OPTS = [
    ['播放一次', 'once'],
    ['无限循环', 'loop'],
    ['在后台播放一次', 'bgOnce'],
    ['在后台无限循环', 'bgLoop']
  ];
  def('zk_music_play', {
    message0: '播放音乐 %1 %2',
    args0: [
      { type: 'field_dropdown', name: 'NAME', options: musicOptions },
      { type: 'field_dropdown', name: 'MODE', options: MUSIC_REPEAT_OPTS }
    ],
    previousStatement: null, nextStatement: null, colour: C.music, inputsInline: true,
    tooltip: '播放音乐库中的曲目（内置乐曲或上传的音频文件）\n' +
      '重复方式：播放一次 / 无限循环 / 在后台播放一次（在后台无限循环）\n' +
      '「在后台」表示不影响程序继续往下执行'
  });

  /* 第四十九轮：播放掌控板**内置**乐曲
   * 与上面的 zk_music_play（素材库里的音乐文件）是两回事：
   * 这里是 music 模块自带的旋律（music.BIRTHDAY / music.DADADADUM …），
   * 教材六年级示例（声光贺卡 / 时间提醒器 / 电子围栏）用的都是它。
   * 之前没有这块积木，导入教材示例时 music.play(...) 只能降级成打印，
   * 真机上一点声音都没有。 */
  var ZK_MELODIES = [
    ['生日快乐', 'BIRTHDAY'], ['噔噔噔噔', 'DADADADUM'], ['娱乐者', 'ENTERTAINER'],
    ['欢乐颂', 'ODE'], ['前奏曲', 'PRELUDE'], ['尼安猫', 'NYAN'], ['电话铃声', 'RINGTONE'],
    ['放克', 'FUNK'], ['布鲁斯', 'BLUES'], ['婚礼进行曲', 'WEDDING'], ['葬礼进行曲', 'FUNERAL'],
    ['笑点', 'PUNCHLINE'], ['坏蛋出场', 'BADDY'], ['追逐', 'CHASE'], ['叮咚', 'BA_DING'],
    ['哇哇哇哇', 'WAWAWAWAA'], ['上升音', 'JUMP_UP'], ['下降音', 'JUMP_DOWN'],
    ['能量上升', 'POWER_UP'], ['能量下降', 'POWER_DOWN']
  ];
  var ZK_MELODY_MODE = [
    ['播完再继续（一次）', 'once'],
    ['播完再继续（循环）', 'loopWait'],
    ['边播边继续（一次）', 'bgOnce'],
    ['边播边继续（循环）', 'bgLoop']
  ];
  def('zk_music_melody', {
    message0: '播放内置旋律 %1 %2',
    args0: [
      { type: 'field_dropdown', name: 'NAME', options: ZK_MELODIES },
      { type: 'field_dropdown', name: 'MODE', options: ZK_MELODY_MODE }
    ],
    previousStatement: null, nextStatement: null, colour: C.music, inputsInline: true,
    tooltip: '播放掌控板内置乐曲（music 模块自带，不需要素材库）\n' +
      '「播完再继续」= wait=True，程序等这首放完才往下走\n' +
      '「边播边继续」= wait=False，音乐在后台响，程序同时往下走'
  });

  /* ---- 集合 / 元组 ---- */
  def('zk_set_create', {
    message0: '创建集合 %1',
    args0: [{ type: 'field_input', name: 'ITEMS', text: '1,2,3' }],
    output: null, colour: C.data, outputShape: Blockly.OUTPUT_SHAPE_ROUND,
    tooltip: 'set([元素…])，按逗号分隔'
  });
  def('zk_set_add', {
    message0: '集合 %1 加入元素 %2', output: null, colour: C.data,
    args0: [
      { type: 'field_variable', name: 'SET', variable: '集合' },
      { type: 'input_value', name: 'V' }
    ], inputsInline: true, tooltip: 'set.add(x)'
  });
  def('zk_tuple_create', {
    message0: '创建元组 (%1)',
    args0: [{ type: 'field_input', name: 'ITEMS', text: '1,2' }],
    output: null, colour: C.data, outputShape: Blockly.OUTPUT_SHAPE_ROUND
  });

  /* ---- 文件（mpython file 模块） ---- */
  def('zk_file_write', {
    message0: '写文件 %1 内容 %2',
    args0: [
      { type: 'field_input', name: 'PATH', text: '/sd/test.txt' },
      { type: 'input_value', name: 'TXT' }
    ],
    previousStatement: null, nextStatement: null, colour: C.file, inputsInline: true,
    tooltip: 'mpython 内置 file 模块：打开文件写入并关闭'
  });
  def('zk_file_read', {
    message0: '读取文件 %1', args0: [{ type: 'field_input', name: 'PATH', text: '/sd/test.txt' }],
    output: null, colour: C.file, outputShape: Blockly.OUTPUT_SHAPE_ROUND,
    tooltip: '读取文件全部内容返回字符串'
  });

  /* ---- 串口（UART） ---- */
  def('zk_uart_write', {
    message0: '串口 %1 发送 %2',
    args0: [
      { type: 'field_number', name: 'UART', value: 1 },
      { type: 'input_value', name: 'TXT' }
    ],
    previousStatement: null, nextStatement: null, colour: C.file, inputsInline: true,
    tooltip: 'UART(uart_id).write(data)'
  });
  def('zk_uart_read', {
    message0: '串口 %1 接收',
    args0: [{ type: 'field_number', name: 'UART', value: 1 }],
    output: null, colour: C.file, outputShape: Blockly.OUTPUT_SHAPE_ROUND,
    tooltip: 'UART(uart_id).read()，无数据返回 None'
  });

  /* ---- 扩展板（parrot: 电机 / 灯） ---- */
  def('zk_parrot_speed', {
    message0: '扩展板电机 %1 速度 %2',
    args0: [
      { type: 'field_dropdown', name: 'MOTOR', options: [['M1', 'MOTOR_1'], ['M2', 'MOTOR_2']] },
      { type: 'input_value', name: 'SPD', check: 'Number' }
    ],
    previousStatement: null, nextStatement: null, colour: C.expboard, inputsInline: true,
    tooltip: 'parrot.set_speed(motor_no, speed)，范围 -100~100，负值反转'
  });
  /* 第四十五轮：停止扩展板电机（语句型）
   * 官方 mxml 里的 hunan_ledon_m1m2_off_mPython 是无参数的语句块。 */
  def('zk_parrot_stop', {
    message0: '停止扩展板电机',
    args0: [], previousStatement: null, nextStatement: null, colour: C.expboard,
    tooltip: '让 M1 / M2 两个扩展板电机都停下来（官方 ledon 电机停机）'
  });
  def('zk_parrot_get', {
    message0: '扩展板电机 %1 当前速度',
    args0: [{ type: 'field_dropdown', name: 'MOTOR', options: [['M1', 'MOTOR_1'], ['M2', 'MOTOR_2']] }],
    output: null, colour: C.expboard, outputShape: Blockly.OUTPUT_SHAPE_ROUND,
    tooltip: 'parrot.get_speed(motor_no)'
  });
  def('zk_parrot_led', {
    message0: '扩展板灯 %1 %2 亮度 %3',
    args0: [
      { type: 'field_dropdown', name: 'MOTOR', options: [['M1', 'MOTOR_1'], ['M2', 'MOTOR_2']] },
      { type: 'field_dropdown', name: 'ACT', options: [['打开', 'on'], ['关闭', 'off']] },
      { type: 'input_value', name: 'BR', check: 'Number' }
    ],
    previousStatement: null, nextStatement: null, colour: C.expboard, inputsInline: true,
    tooltip: 'parrot.led_on(no, brightness) / led_off(no)，亮度 0~100'
  });

  /* ---- NeoPixel ---- */
  def('zk_neopixel_fill', {
    message0: 'NeoPixel 全部设为 R:%1 G:%2 B:%3',
    args0: [
      { type: 'input_value', name: 'R', check: 'Number' },
      { type: 'input_value', name: 'G', check: 'Number' },
      { type: 'input_value', name: 'B', check: 'Number' }
    ],
    previousStatement: null, nextStatement: null, colour: C.expboard, inputsInline: true,
    tooltip: 'NeoPixel.fill((r,g,b))'
  });

  /* ---- 环境（GPIO / 定时器） ---- */
  def('zk_time_tick', {
    message0: '获取运行时间(秒)', args0: [],
    output: null, colour: C.control, outputShape: Blockly.OUTPUT_SHAPE_ROUND,
    tooltip: 'time.time() 减去启动时刻，得到程序运行秒数'
  });

  /* ============================================================
   * 舞台元素控制（第十三轮）：位置 / 层级 / 大小
   * 作用于舞台模式中的非背景元素（仅仿真，Python 导出为注释）
   * ============================================================ */
  /* 舞台可编辑元素下拉：非背景元素（马路/斑马线等地面元素不可调）。
     每次打开下拉都实时读取舞台当前元素（自动识别新增/删除），
     同名元素自动编号（机器人 / 机器人2 …），便于区分。 */
  function stageElOptions() {
    var opts = [];
    try {
      if (global.ZKB && ZKB.Stage && ZKB.Stage.getEditable) {
        var seen = {};
        ZKB.Stage.getEditable().forEach(function (it) {
          var nm = it.name || it.k;
          seen[nm] = (seen[nm] || 0) + 1;
          if (seen[nm] > 1) nm = nm + seen[nm];
          opts.push([nm, it.uid]);
        });
      }
    } catch (e) {}
    if (!opts.length) opts = [['（舞台暂无元素）', '']];
    return opts;
  }
  ZKB.stageElOptions = stageElOptions;
  ZKB.elKindOptions = elKindOptions;
  ZKB.KIND_TO_KINDS = KIND_TO_KINDS;

  /* 让 EL 下拉接受「元素 uid / 元素键（如 car）/ 元素名称」三种写法：
     示例工程里无法预知 uid（元素 uid 是运行时生成的），
     所以允许直接写元素键，运行时再解析成对应元素。 */
  function allowElText(block) {
    var f = block.getField('EL');
    if (f && f.setValidator) f.setValidator(function (v) { return v; });
  }

  /* ---- 面向方向：数字框 + 方向盘双向同步 ----
     第三十二轮从控制模块迁到这里（zk_stage_rotate 已删除）。
     数字框可手动输入 0~360 精确角度，方向盘下拉快速选四个正方向，两者双向同步。*/
  var DIR_DIAL_OPTS = [
    ['方向盘 → 90°（向右）', '90'],
    ['方向盘 ↑ 0°（向上）', '0'],
    ['方向盘 ↓ 180°（向下）', '180'],
    ['方向盘 ← 270°（向左）', '270'],
    ['方向盘 任意角度', 'CUSTOM']
  ];
  var dirToDial = function (v) {
    v = ((Math.round(Number(v) || 0) % 360) + 360) % 360;
    return (v === 90 || v === 0 || v === 180 || v === 270) ? String(v) : 'CUSTOM';
  };
  /* 方向盘 ↔ 数字 双向同步：
     直接包裹两个字段的 setValue（不依赖工作区 change 事件，
     无头工作区 / 事件关闭时也能同步），并用 __zkDirLock 防递归。 */
  function syncDirFields(block) {
    if (block.__zkDirSync) return;
    var num = block.getField('DIR'), dial = block.getField('DIAL');
    if (!num || !dial) return;
    block.__zkDirSync = true;
    var numSet = num.setValue.bind(num);
    var dialSet = dial.setValue.bind(dial);
    num.setValue = function (v) {
      var r = numSet(v);
      if (block.__zkDirLock) return r;
      block.__zkDirLock = true;
      try {
        var want = dirToDial(num.getValue());
        if (dial.getValue() !== want) dialSet(want);
      } finally { block.__zkDirLock = false; }
      return r;
    };
    dial.setValue = function (v) {
      var r = dialSet(v);
      if (block.__zkDirLock) return r;
      block.__zkDirLock = true;
      try {
        if (v && v !== 'CUSTOM') numSet(String(Number(v)));
      } finally { block.__zkDirLock = false; }
      return r;
    };
  }

  /* ============================================================
   * 控制模块：舞台元素控制（**已停用**）
   *
   * 第三十二轮：按用户要求从工具箱「控制」分类移除这4 块，
   * 元素移动/ 层级 / 大小 / 方向统一改由「运动」「外观」两个模块承担
   * （中心原点、层级更细，语义与 Scratch 一致）。
   *
   * ⚠ 但**保留积木定义**：用户此前保存的 .mxml 工程里可能还有这4 块，
   * 若连定义一起删掉，打开时会变成「未知积木」方块，工程直接报废。
   * 所以这里只停用、不删除 —— 反序列化仍能正常载入并生成代码。
   * ============================================================ */
  var DEPRECATED_NOTE = '【已停用】该积木已移出工具箱，请改用「运动」「外观」模块里的同类积木。';
  def('zk_stage_move', {
    message0: '把元素 %1 移动到 x:%2 y:%3',
    args0: [
      { type: 'field_dropdown', name: 'EL', options: stageElOptions },
      { type: 'input_value', name: 'X', check: 'Number' },
      { type: 'input_value', name: 'Y', check: 'Number' }
    ],
    previousStatement: null, nextStatement: null, colour: 160,
    inputsInline: true,
    tooltip: DEPRECATED_NOTE + '请改用「运动」分类的「把元素 移到 x,y」。'
  }, function () {
    allowElText(this);
    this.getInput('X').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">100</field></shadow>'));
    this.getInput('Y').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">100</field></shadow>'));
  });

  def('zk_stage_layer', {
    message0: '把元素 %1 %2',
    args0: [
      { type: 'field_dropdown', name: 'EL', options: stageElOptions },
      {
        type: 'field_dropdown', name: 'OP', options: [
          ['上移一层', 'up'], ['下移一层', 'down'],
          ['置于顶层', 'front'], ['置于底层', 'back']
        ]
      }
    ],
    previousStatement: null, nextStatement: null, colour: 160,
    inputsInline: true,
    tooltip: DEPRECATED_NOTE + '请改用「外观」分类的层级积木（更细，可移到第 N 层）。'
  }, function () { allowElText(this); });

  def('zk_stage_scale', {
    message0: '把元素 %1 大小设为 %2 %',
    args0: [
      { type: 'field_dropdown', name: 'EL', options: stageElOptions },
      { type: 'input_value', name: 'PCT', check: 'Number' }
    ],
    previousStatement: null, nextStatement: null, colour: 160,
    inputsInline: true,
    tooltip: DEPRECATED_NOTE + '请改用「外观」分类的「把元素 大小设为 %」。'
  }, function () {
    allowElText(this);
    this.getInput('PCT').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">100</field></shadow>'));
  });

  def('zk_stage_rotate', {
    message0: '把元素 %1 面向 %2 度方向 %3',
    args0: [
      { type: 'field_dropdown', name: 'EL', options: stageElOptions },
      { type: 'field_number', name: 'DIR', value: 90, min: 0, max: 360, precision: 1 },
      { type: 'field_dropdown', name: 'DIAL', options: DIR_DIAL_OPTS }
    ],
    previousStatement: null, nextStatement: null, colour: 160,
    inputsInline: true,
    tooltip: DEPRECATED_NOTE + '请改用「运动」分类的「把元素 面向 % 度方向」。'
  }, function () {
    allowElText(this);
    this.getField('DIR').setValue(Math.round(Number(this.getFieldValue('DIR')) || 90));
    this.getField('DIAL').setValue(dirToDial(this.getFieldValue('DIR')));
    syncDirFields(this);
  });

  /* ============================================================
   * 第三十轮：运动模块（对齐 Scratch motion）
   *
   * 方向约定与全站一致：**0° 正上、90° 正右、180° 正下、270° 正左**。
   * 坐标约定对齐 Scratch：**以舞台中心为原点**，x 向右为正、y 向下为正。
   * ============================================================ */
  /* ⚠ 必须用函数返回新对象：Blockly 在 init() 时会往参数对象上写内部字段，
     多个积木共用同一个字面量会互相污染，导致后注册的积木
     报 Invalid block definition。 */
  function MOTION_EL() { return { type: 'field_dropdown', name: 'EL', options: stageElOptions }; }

  /* 运动：值积木（读取用） */
  def('zk_mv_x', {
    message0: '元素 %1 的 x 坐标',
    args0: [MOTION_EL()], output: 'Number', colour: C.stage_motion,
    tooltip: '读取引用的 x 坐标。舞台中心为 0，向右为正（Scratch 惯例）'
  }, function () { allowElText(this); });

  def('zk_mv_y', {
    message0: '元素 %1 的 y 坐标',
    args0: [MOTION_EL()], output: 'Number', colour: C.stage_motion,
    tooltip: '读取引用的 y 坐标。舞台中心为 0，向下为正（Scratch 惯例）'
  }, function () { allowElText(this); });

  def('zk_mv_dir', {
    message0: '元素 %1 的方向',
    args0: [MOTION_EL()], output: 'Number', colour: C.stage_motion,
    tooltip: '读取引用的方向角：0° 正上、90° 正右、180° 正下、270° 正左'
  }, function () { allowElText(this); });

  /* 第三十五轮曾新增「把元素的方向设为 N 度」（zk_mv_setdir），
     第三十六轮按需求删除：方向调整统一由
     「把元素面向 N 度方向」（zk_mv_pointdir）承担，功能完全一致。 */

  /* 运动：语句积木 */
  function mvStep(type, msg, tip, defVal) {
    def(type, {
      message0: msg,
      args0: [MOTION_EL(), { type: 'input_value', name: 'N', check: 'Number' }],
      previousStatement: null, nextStatement: null, colour: C.stage_motion, inputsInline: true,
      tooltip: tip
    }, function () {
      allowElText(this);
      this.getInput('N').connection.setShadowDom(
        Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">' + defVal + '</field></shadow>'));
    });
  }
  mvStep('zk_mv_steps', '把元素 %1 移动 %2 步', '沿当前方向前进指定步数（10 步约等于舞台上的一小格）', 10);
  /* 第三十五轮：删除「把元素前进 N 步」「把元素后退 N 步」——
     用「把元素移动 N 步」+「把元素的方向设为 N 度」组合即可，
     积木区更精简，学生也更容易理解「移动」与「方向」的关系。 */

  def('zk_mv_goto', {
    message0: '把元素 %1 移到 x:%2 y:%3',
    args0: [MOTION_EL(),
      { type: 'input_value', name: 'X', check: 'Number' },
      { type: 'input_value', name: 'Y', check: 'Number' }],
    previousStatement: null, nextStatement: null, colour: C.stage_motion, inputsInline: true,
    tooltip: '直接移到指定坐标（舞台中心为原点）。会瞬间到达，不带滑行'
  }, function () {
    allowElText(this);
    this.getInput('X').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">0</field></shadow>'));
    this.getInput('Y').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">0</field></shadow>'));
  });

  function mvTurn(type, msg, tip, defVal) {
    def(type, {
      message0: msg,
      args0: [MOTION_EL(), { type: 'input_value', name: 'D', check: 'Number' }],
      previousStatement: null, nextStatement: null, colour: C.stage_motion, inputsInline: true,
      tooltip: tip
    }, function () {
      allowElText(this);
      this.getInput('D').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">' + defVal + '</field></shadow>'));
    });
  }
  mvTurn('zk_mv_turnright', '把元素 %1 右转 %2 度', '顺时针转向（Scratch 约定：右转角度为正）', 15);
  mvTurn('zk_mv_turnleft', '把元素 %1 左转 %2 度', '逆时针转向，角度为正数', 15);

  def('zk_mv_pointdir', {
    message0: '把元素 %1 面向 %2 度方向',
    args0: [MOTION_EL(), { type: 'input_value', name: 'D', check: 'Number' }],
    previousStatement: null, nextStatement: null, colour: C.stage_motion, inputsInline: true,
    tooltip: '直接设定朝向：0° 正上、90° 正右、180° 正下、270° 正左。' +
      '配合「把元素移动 N 步」可实现前进 / 后退 / 绕圈'
  }, function () { allowElText(this); });

  def('zk_mv_pointto', {
    message0: '把元素 %1 面向元素 %2',
    args0: [MOTION_EL(), { type: 'field_dropdown', name: 'TO', options: stageElOptions }],
    previousStatement: null, nextStatement: null, colour: C.stage_motion, inputsInline: true,
    tooltip: '让一个元素转向另一个元素（自动计算夹角）'
  }, function () { allowElText(this); });

  /* 第三十五轮：删除「把元素 面向 N 度方向（带方向盘）」——
     改用「把元素 面向 N 度方向」（zk_mv_pointdir，纯数字输入）
     与「把元素的方向设为 N 度」（zk_mv_setdir）两块完成同样的事。 */

  def('zk_mv_changex', {
    message0: '把元素 %1 的 x 增加 %2',
    args0: [MOTION_EL(), { type: 'input_value', name: 'N', check: 'Number' }],
    previousStatement: null, nextStatement: null, colour: C.stage_motion, inputsInline: true,
    tooltip: '在水平方向移动，正数向右、负数向左'
  }, function () {
    allowElText(this);
    this.getInput('N').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">10</field></shadow>'));
  });
  def('zk_mv_changey', {
    message0: '把元素 %1 的 y 增加 %2',
    args0: [MOTION_EL(), { type: 'input_value', name: 'N', check: 'Number' }],
    previousStatement: null, nextStatement: null, colour: C.stage_motion, inputsInline: true,
    tooltip: '在垂直方向移动，正数向下、负数向上'
  }, function () {
    allowElText(this);
    this.getInput('N').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">10</field></shadow>'));
  });
  def('zk_mv_setx', {
    message0: '把元素 %1 的 x 设为 %2',
    args0: [MOTION_EL(), { type: 'input_value', name: 'N', check: 'Number' }],
    previousStatement: null, nextStatement: null, colour: C.stage_motion, inputsInline: true,
    tooltip: '直接设定水平坐标（舞台中心为 0）'
  }, function () {
    allowElText(this);
    this.getInput('N').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">0</field></shadow>'));
  });
  def('zk_mv_sety', {
    message0: '把元素 %1 的 y 设为 %2',
    args0: [MOTION_EL(), { type: 'input_value', name: 'N', check: 'Number' }],
    previousStatement: null, nextStatement: null, colour: C.stage_motion, inputsInline: true,
    tooltip: '直接设定垂直坐标（舞台中心为 0）'
  }, function () {
    allowElText(this);
    this.getInput('N').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">0</field></shadow>'));
  });

  def('zk_mv_glide', {
    message0: '把元素 %1 在 %2 秒内滑行到 x:%3 y:%4',
    args0: [MOTION_EL(),
      { type: 'input_value', name: 'SEC', check: 'Number' },
      { type: 'input_value', name: 'X', check: 'Number' },
      { type: 'input_value', name: 'Y', check: 'Number' }],
    previousStatement: null, nextStatement: null, colour: C.stage_motion, inputsInline: true,
    tooltip: '在指定时间内平滑移动到目标坐标，时间越短滑得越快'
  }, function () {
    allowElText(this);
    this.getInput('SEC').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">1</field></shadow>'));
    this.getInput('X').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">0</field></shadow>'));
    this.getInput('Y').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">0</field></shadow>'));
  });

  def('zk_mv_bounce', {
    message0: '如果元素 %1 碰到边缘就反弹',
    args0: [MOTION_EL()],
    previousStatement: null, nextStatement: null, colour: C.stage_motion, inputsInline: true,
    tooltip: '元素贴到舞台边缘时自动转向弹回来（对齐 Scratch「碰到边缘就反弹」）'
  }, function () { allowElText(this); });

  def('zk_mv_random', {
    message0: '把元素 %1 移到随机位置',
    args0: [MOTION_EL()],
    previousStatement: null, nextStatement: null, colour: C.stage_motion, inputsInline: true,
    tooltip: '在舞台范围内随机取一个位置'
  }, function () { allowElText(this); });

  /* ============================================================
   * 第三十轮：外观模块（对齐 Scratch looks）
   *   显示隐藏 / 大小 / 透明度 / 虚像 / 颜色特效 / 图形特效 / 层级
   * ============================================================ */
    function LOOK_EL() { return { type: 'field_dropdown', name: 'EL', options: stageElOptions }; }

  def('zk_look_show', {
    message0: '显示元素 %1',
    args0: [LOOK_EL()],
    previousStatement: null, nextStatement: null, colour: C.stage_looks, inputsInline: true,
    tooltip: '把隐藏起来的元素重新显示出来'
  }, function () { allowElText(this); });

  def('zk_look_hide', {
    message0: '隐藏元素 %1',
    args0: [LOOK_EL()],
    previousStatement: null, nextStatement: null, colour: C.stage_looks, inputsInline: true,
    tooltip: '把元素藏起来（舞台上看不到，但仍在舞台上，逻辑继续运行）'
  }, function () { allowElText(this); });

  def('zk_look_visible', {
    message0: '元素 %1 是否显示？',
    args0: [LOOK_EL()], output: 'Boolean', colour: C.stage_looks,
    tooltip: '判断元素当前是否可见'
  }, function () { allowElText(this); });

  def('zk_look_size', {
    message0: '元素 %1 的大小',
    args0: [LOOK_EL()], output: 'Number', colour: C.stage_looks,
    tooltip: '读取引用的大小百分比（100% 为原始大小）'
  }, function () { allowElText(this); });

  def('zk_look_chsize', {
    message0: '把元素 %1 的大小增加 %2',
    args0: [LOOK_EL(), { type: 'input_value', name: 'N', check: 'Number' }],
    previousStatement: null, nextStatement: null, colour: C.stage_looks, inputsInline: true,
    tooltip: '在当前大小基础上增减（正数放大、负数缩小）'
  }, function () {
    allowElText(this);
    this.getInput('N').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">10</field></shadow>'));
  });

  def('zk_look_setsize', {
    message0: '把元素 %1 的大小设为 %2 %',
    args0: [LOOK_EL(), { type: 'input_value', name: 'N', check: 'Number' }],
    previousStatement: null, nextStatement: null, colour: C.stage_looks, inputsInline: true,
    tooltip: '直接设定大小（30% ~ 300%）'
  }, function () {
    allowElText(this);
    this.getInput('N').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">100</field></shadow>'));
  });

  def('zk_look_opacity', {
    message0: '把元素 %1 的不透明度设为 %2 %',
    args0: [LOOK_EL(), { type: 'input_value', name: 'N', check: 'Number' }],
    previousStatement: null, nextStatement: null, colour: C.stage_looks, inputsInline: true,
    tooltip: '100% 为完全不透明，0% 为完全透明（半透明用 50）'
  }, function () {
    allowElText(this);
    this.getInput('N').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">100</field></shadow>'));
  });

  def('zk_look_ghost', {
    message0: '把元素 %1 的虚像设为 %2 %',
    args0: [LOOK_EL(), { type: 'input_value', name: 'N', check: 'Number' }],
    previousStatement: null, nextStatement: null, colour: C.stage_looks, inputsInline: true,
    tooltip: 'Scratch 的「虚像」效果：0% 为实体，100% 为完全透明（像影子一样淡）'
  }, function () {
    allowElText(this);
    this.getInput('N').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">0</field></shadow>'));
  });

  /* 颜色特效：色相 / 饱和度 / 亮度 */
  def('zk_look_colorfx', {
    message0: '把元素 %1 的 %2 增加 %3',
    args0: [LOOK_EL(),
      {
        type: 'field_dropdown', name: 'FX', options: [
          ['色相', 'hue'], ['饱和度', 'sat'], ['亮度', 'bright']
        ]
      },
      { type: 'input_value', name: 'N', check: 'Number' }],
    previousStatement: null, nextStatement: null, colour: C.stage_looks, inputsInline: true,
    tooltip: '改变元素颜色。色相是 0~200 度的色环偏移（像调滤镜），饱和度与亮度可正可负'
  }, function () {
    allowElText(this);
    this.getInput('N').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">25</field></shadow>'));
  });

  def('zk_look_cleareffects', {
    message0: '清除元素 %1 的所有图形特效',
    args0: [LOOK_EL()],
    previousStatement: null, nextStatement: null, colour: C.stage_looks, inputsInline: true,
    tooltip: '一次性还原透明度、虚像与所有颜色特效'
  }, function () { allowElText(this); });

  /* ---- 元素层级（第三十二轮，第三十五轮融合为一块） ----
     层号从 1 开始，1 是最底层。
     第三十五轮：原先「置于顶层 / 置于底层 / 上移一层 / 下移一层」四块积木
     融合成一块「把元素 [层级操作]」，用下拉选择操作方式，
     积木区更简洁，学生也不用在四块里挑。 */
  def('zk_look_layerop', {
    message0: '把元素 %1 %2',
    args0: [
      LOOK_EL(),
      {
        type: 'field_dropdown', name: 'OP', options: [
          ['置于顶层', 'front'],
          ['置于底层', 'back'],
          ['上移一层', 'up'],
          ['下移一层', 'down']
        ]
      }
    ],
    previousStatement: null, nextStatement: null, colour: C.stage_looks, inputsInline: true,
    tooltip: '调整元素在舞台上的叠放次序：置于顶层 / 置于底层 / 上移一层 / 下移一层'
  }, function () { allowElText(this); });

  def('zk_look_layern', {
    message0: '把元素 %1 移到第 %2 层',
    args0: [LOOK_EL(), { type: 'input_value', name: 'N', check: 'Number' }],
    previousStatement: null, nextStatement: null, colour: C.stage_looks, inputsInline: true,
    tooltip: '第 1 层是最底层。层号超出范围时自动钳到最底/最顶层'
  }, function () { allowElText(this); });

  def('zk_look_layer', {
    message0: '元素 %1 的层数',
    args0: [LOOK_EL()], output: 'Number', colour: C.stage_looks,
    tooltip: '读出当前叠放次序：1 是最底层'
  }, function () { allowElText(this); });

  def('zk_look_layercount', {
    message0: '舞台上的元素总层数',
    args0: [], output: 'Number', colour: C.stage_looks,
    tooltip: '舞台上共有多少个元素（每个元素占一层）'
  });

  /* ============================================================
   * 元素积木（第二十一轮）：自动识别舞台中存在的元素
   *  —— 下拉内容来自舞台实时元素列表（Stage.getEditable）
   * ============================================================ */
  /* 元素分类下拉：行人 / 车辆 / 任意障碍物 */
  function elKindOptions() {
    return [
      ['行人', 'pedestrian'], ['车辆', 'vehicle'], ['任意障碍物', 'ANY']
    ];
  }
  var KIND_TO_KINDS = {
    pedestrian: ['pedestrian'], vehicle: ['vehicle'], ANY: null
  };
  /* 小车前方 N 厘米内有指定元素吗（返回条件） */
  def('zk_front_has', {
    message0: '小车前方 %1 cm 内有 %2 吗',
    args0: [
      { type: 'input_value', name: 'CM' },
      { type: 'field_dropdown', name: 'KIND', options: elKindOptions }
    ],
    output: 'Boolean', colour: C.control, outputShape: Blockly.OUTPUT_SHAPE_HEXAGON,
    tooltip: '用小车的超声波探测前方是否有行人 / 车辆 / 任意障碍物'
  }, function () {
    this.getInput('CM').connection.setShadowDom(
      Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">30</field></shadow>'));
  });
  /* 让元素从上往下走到 y 坐标（行人过斑马线） */
  def('zk_el_walk', {
    message0: '让 %1 从上往下走到 y = %2',
    args0: [
      { type: 'field_dropdown', name: 'EL', options: stageElOptions },
      { type: 'input_value', name: 'Y' }
    ],
    previousStatement: null, nextStatement: null, colour: C.control,
    inputsInline: true,
    tooltip: '让行人 / 车辆等元素沿竖直方向向下移动到指定 y 坐标（走到后程序继续）'
  }, function () {
    allowElText(this);
    this.getInput('Y').connection.setShadowDom(
      Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">430</field></shadow>'));
  });
  /* 元素行走是否结束（等待行人通过） */
  def('zk_el_walk_done', {
    message0: '%1 走到终点了吗',
    args0: [{ type: 'field_dropdown', name: 'EL', options: stageElOptions }],
    output: 'Boolean', colour: C.control, outputShape: Blockly.OUTPUT_SHAPE_HEXAGON,
    tooltip: '行人 / 车辆是否已经走到指定位置'
  }, function () { allowElText(this); });

  /* ============================================================
   * 机器人（拓展库「机器人」模型；舞台「巡线机器人 / 机器人送餐」情景）
   * 巡线 + 地面颜色识别 + 超声波 + 语音识别 + AI 摄像头
   * 仅在拓展库添加「机器人」后，积木区才显示「机器人」分类。
   * ============================================================ */
  def('zk_robot_go', {
    message0: '机器人 %1',
    args0: [{
      type: 'field_dropdown', name: 'ACT', options: [
        ['出发（巡线）', 'go'], ['停止', 'stop']
      ]
    }],
    previousStatement: null, nextStatement: null, colour: C.robot,
    inputsInline: true,
    tooltip: '机器人从绿色起点出发，沿黑色轨迹巡线，到达红色终点自动停止'
  });

  def('zk_robot_speed', {
    message0: '机器人 速度 %1',
    args0: [{ type: 'input_value', name: 'V', check: 'Number' }],
    previousStatement: null, nextStatement: null, colour: C.robot,
    inputsInline: true, tooltip: '巡线速度 0~100'
  }, function () {
    this.getInput('V').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">60</field></shadow>'));
  });

  def('zk_robot_ground', {
    message0: '机器人地面颜色', args0: [],
    output: null, colour: C.robot, outputShape: Blockly.OUTPUT_SHAPE_ROUND,
    tooltip: '机器人颜色传感器读到地面：绿色（起点）/ 黑色（轨迹）/ 红色（终点）/ 白色（地面）'
  });

  def('zk_robot_dist', {
    message0: '机器人前方距离 (cm)', args0: [],
    output: null, colour: C.robot, outputShape: Blockly.OUTPUT_SHAPE_ROUND,
    tooltip: '机器人搭载的超声波传感器：到前方最近障碍物的距离'
  });

  def('zk_robot_cam', {
    message0: '机器人摄像头识别', args0: [],
    output: null, colour: C.robot, outputShape: Blockly.OUTPUT_SHAPE_ROUND,
    tooltip: '机器人搭载的 AI 摄像头：识别前方物体（行人/路树等）'
  });

  def('zk_robot_asr', {
    message0: '机器人语音识别', args0: [],
    output: null, colour: C.robot, outputShape: Blockly.OUTPUT_SHAPE_ROUND,
    tooltip: '机器人搭载的语音识别：最近听到的指令文字（在 WiFi语音识别 卡片上模拟说话）'
  });

  def('zk_car_dist', {
    message0: '小车前方距离 (cm)', args0: [],
    output: null, colour: C.car, outputShape: Blockly.OUTPUT_SHAPE_ROUND,
    tooltip: '小车自带的超声波传感器：到车头前方最近障碍物的距离'
  });

  /* ============================================================
   * 巡线小车（第十四轮；拓展库「巡线小车」模块）
   *   小车电机（前进/后退/转向）+ 循迹器 5 路探针 + 超声波
   *   舞台上的「巡线小车」元素由虚拟仿真中的设备数据驱动
   * ============================================================ */
  def('zk_trace_motor', {
    message0: '巡线小车 电机 %1 速度 %2',
    args0: [
      {
        type: 'field_dropdown', name: 'DIR', options: [
          ['前进', 'f'], ['后退', 'b'], ['左转', 'l'], ['右转', 'r'], ['停止', 's']
        ]
      },
      { type: 'input_value', name: 'S', check: 'Number' }
    ],
    previousStatement: null, nextStatement: null, colour: C.car,
    inputsInline: true,
    tooltip: '直接驱动巡线小车电机（使用电机时自动关闭「自动巡线」）'
  }, function () {
    this.getInput('S').connection.setShadowDom(Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">60</field></shadow>'));
  });

  def('zk_trace_auto', {
    message0: '巡线小车 自动巡线 %1',
    args0: [{
      type: 'field_dropdown', name: 'ACT', options: [['开启', 'on'], ['关闭', 'off']]
    }],
    previousStatement: null, nextStatement: null, colour: C.car,
    inputsInline: true,
    tooltip: '沿舞台上的「赛道黑线」自动巡线（需先布置赛道黑线元素）'
  });

  def('zk_trace_line', {
    message0: '巡线小车 循线状态', args0: [],
    output: null, colour: C.car, outputShape: Blockly.OUTPUT_SHAPE_ROUND,
    tooltip: '循迹器 5 路探针读到的黑线位置：居中 / 偏左 / 偏右 / 离线'
  });

  def('zk_trace_dist', {
    message0: '巡线小车 前方距离 (cm)', args0: [],
    output: null, colour: C.car, outputShape: Blockly.OUTPUT_SHAPE_ROUND,
    tooltip: '巡线小车搭载的超声波：到车头前方最近障碍物的距离'
  });

/* ============================================================
   * 十三、DFRobot 新增硬件对应的积木
   * 依据 DFRobot 官方资料：SEN0241 巡线、SEN0291 功率计、
   *   SEN0364 AS7341、DFR0095/0094 红外收发、DFR0017 继电器等
   * ============================================================ */

  def('zk_tracker_read', {
    message0: '巡线传感器 %1',
    args0: [{
      type: 'field_dropdown', name: 'CH', options: [
        ['左外', 'L2'], ['左中', 'L1'], ['中间', 'C'], ['右中', 'R1'], ['右外', 'R2']
      ]
    }],
    output: null, colour: C.dht, outputShape: Blockly.OUTPUT_SHAPE_ROUND,
    tooltip: 'SEN0241 巡线传感器：返回 true=检测到黑线'
  });

  def('zk_tracker_state', {
    message0: '巡线偏离',
    args0: [],
    output: null, colour: C.dht, outputShape: Blockly.OUTPUT_SHAPE_ROUND,
    tooltip: '返回 -1 左偏、0 居中、1 右偏（用于自动循迹）'
  });

  def('zk_power_read', {
    message0: '功率计 %1',
    args0: [{
      type: 'field_dropdown', name: 'K', options: [
        ['电压(V)', 'v'], ['电流(A)', 'a'], ['功率(W)', 'w']
      ]
    }],
    output: null, colour: C.dht, outputShape: Blockly.OUTPUT_SHAPE_ROUND,
    tooltip: 'SEN0291 I2C 数字功率计：实时读数'
  });

  def('zk_gravity_read', {
    message0: 'AS7341 %1',
    args0: [{
      type: 'field_dropdown', name: 'K', options: [
        ['红光', 'r'], ['绿光', 'g'], ['蓝光', 'b'], ['总亮度', 'l']
      ]
    }],
    output: null, colour: C.dht, outputShape: Blockly.OUTPUT_SHAPE_ROUND,
    tooltip: 'SEN0364 AS7341 可见光传感器：读取光谱分量'
  });

  def('zk_angle_read', {
    message0: '角度传感器角度', args0: [],
    output: null, colour: C.dht, outputShape: Blockly.OUTPUT_SHAPE_ROUND,
    tooltip: '模拟角度电位器：0~180 度'
  });

  def('zk_ir_send', {
    message0: '红外发射 %1',
    args0: [{ type: 'input_value', name: 'CODE' }],
    previousStatement: null, nextStatement: null, colour: C.ir, inputsInline: true,
    tooltip: 'DFR0095 红外发射模块：发送红外指令码'
  });

  def('zk_ir_receive', {
    message0: '红外接收到的指令码', args0: [],
    output: null, colour: C.ir, outputShape: Blockly.OUTPUT_SHAPE_ROUND,
    tooltip: 'DFR0094 红外接收模块：读取收到的指令码'
  });

  def('zk_relay', {
    message0: '继电器 %1',
    args0: [{ type: 'field_dropdown', name: 'ACT', options: [['打开', '1'], ['关闭', '0']] }],
    previousStatement: null, nextStatement: null, colour: C.heater,
    tooltip: 'DFR0017 数字继电器模块：控制大功率设备通断'
  });

  def('zk_led_brightness', {
    message0: 'LED 亮度 %1',
    args0: [{ type: 'input_value', name: 'V', check: 'Number' }],
    previousStatement: null, nextStatement: null, colour: C.heater,
    tooltip: 'LED 模块亮度 0~100（PWM 调光）'
  });

  /* 第三十五轮：LED 模块补充积木。
     参考 mPythonSoftware-docs 的 expandBoard 文档：拓展板的 M1 / M2 电机口
     除了能驱动电机，还能当灯用（parrot.led_on / led_off），
     所以 LED 模块既可以接 IO 口做 PWM 调光，也可以接 M 口做开关灯。 */
  def('zk_led_on', {
    message0: '打开 %1',
    args0: [{ type: 'field_dropdown', name: 'PORT', options: [
      ['LED 模块', 'led'], ['M1 口灯', 'M1'], ['M2 口灯', 'M2']
    ] }],
    previousStatement: null, nextStatement: null, colour: C.heater,
    tooltip: '点亮 LED；M1 / M2 口接的灯可以用拓展板的 led_on 控制'
  });
  def('zk_led_off', {
    message0: '关闭 %1',
    args0: [{ type: 'field_dropdown', name: 'PORT', options: [
      ['LED 模块', 'led'], ['M1 口灯', 'M1'], ['M2 口灯', 'M2']
    ] }],
    previousStatement: null, nextStatement: null, colour: C.heater,
    tooltip: '熄灭 LED；M1 / M2 口接的灯可以用拓展板的 led_off 控制'
  });
  def('zk_led_bright_set', {
    message0: '把 %1 的亮度设为 %2',
    args0: [
      { type: 'field_dropdown', name: 'PORT', options: [
        ['LED 模块', 'led'], ['M1 口灯', 'M1'], ['M2 口灯', 'M2']
      ] },
      { type: 'input_value', name: 'V', check: 'Number' }
    ],
    previousStatement: null, nextStatement: null, colour: C.heater, inputsInline: true,
    tooltip: '设置亮度 0~100（拓展板 M 口灯的亮度范围同样是 0~100）'
  });
  def('zk_led_is_on', {
    message0: '%1 是否亮着',
    args0: [{ type: 'field_dropdown', name: 'PORT', options: [
      ['LED 模块', 'led'], ['M1 口灯', 'M1'], ['M2 口灯', 'M2']
    ] }],
    output: 'Boolean', colour: C.heater,
    tooltip: '判断这盏灯当前是否点亮'
  });
  def('zk_led_get_bright', {
    message0: '%1 的亮度',
    args0: [{ type: 'field_dropdown', name: 'PORT', options: [
      ['LED 模块', 'led'], ['M1 口灯', 'M1'], ['M2 口灯', 'M2']
    ] }],
    output: 'Number', colour: C.heater,
    tooltip: '读取当前亮度（0~100）'
  });

  /* ============================================================
   * RGB 灯带积木（数值输入可编辑 0~255）
   *
   * 默认值以 <shadow> 写在工具箱 XML 里（见 toolbox.js 的 SHADOW_XML），
   * 这样拖出来就自带可点击编辑的数字框。
   * ⚠ 这里不能再用 connection.setShadowDom()：那样影子块没有真正的父积木，
   *   Blockly 行内渲染器会取不到 field.getSvgRoot() 而抛异常。
   * ============================================================ */
  def('zk_rgb_strip', {
    message0: '灯带第 %1 颗 颜色 R:%2 G:%3 B:%4',
    args0: [
      { type: 'input_value', name: 'I', check: 'Number' },
      { type: 'input_value', name: 'R', check: 'Number' },
      { type: 'input_value', name: 'G', check: 'Number' },
      { type: 'input_value', name: 'B', check: 'Number' }
    ],
    previousStatement: null, nextStatement: null, colour: C.rgb, inputsInline: true,
    tooltip: 'RGB 灯带（共 16 颗）：指定第 I 颗（1~16）点亮为指定颜色，R/G/B 取值 0~255'
  });

  def('zk_rgb_strip_all', {
    message0: '灯带全部 颜色 R:%1 G:%2 B:%3',
    args0: [
      { type: 'input_value', name: 'R', check: 'Number' },
      { type: 'input_value', name: 'G', check: 'Number' },
      { type: 'input_value', name: 'B', check: 'Number' }
    ],
    previousStatement: null, nextStatement: null, colour: C.rgb, inputsInline: true,
    tooltip: 'RGB 灯带：16 颗全部点亮为同一颜色，R/G/B 取值 0~255'
  });

  def('zk_rgb_strip_off', {
    message0: '灯带第 %1 颗 熄灭',
    args0: [{ type: 'input_value', name: 'I', check: 'Number' }],
    previousStatement: null, nextStatement: null, colour: C.rgb,
    tooltip: 'RGB 灯带：熄灭指定灯珠（填 0 表示全部熄灭）'
  });

  def('zk_rgb_strip_rainbow', {
    message0: '灯带跑马灯（起始第 %1 颗，共 %2 颗，速度 %3 毫秒）',
    args0: [
      { type: 'input_value', name: 'START', check: 'Number' },
      { type: 'input_value', name: 'N', check: 'Number' },
      { type: 'input_value', name: 'MS', check: 'Number' }
    ],
    previousStatement: null, nextStatement: null, colour: C.rgb, inputsInline: true,
    tooltip: '灯带依次点亮指定数量的灯珠，形成流动效果'
  });

  /* 红外遥控器：方向键控制硬件 */
  def('zk_remote_key', {
    message0: '遥控器按下 %1',
    args0: [{
      type: 'field_dropdown', name: 'DIR', options: [
        ['上键', 'up'], ['下键', 'down'], ['左键', 'left'], ['右键', 'right'],
        ['确定键', 'ok'], ['返回键', 'back']
      ]
    }],
    previousStatement: null, nextStatement: null, colour: C.ir, inputsInline: true,
    tooltip: '迷你红外遥控器：点击虚拟遥控器上的方向键即可触发'
  });

  def('zk_remote_dir', {
    message0: '遥控器 %1',
    args0: [{
      type: 'field_dropdown', name: 'DIR', options: [
        ['向上', 'up'], ['向下', 'down'], ['向左', 'left'], ['向右', 'right']
      ]
    }],
    output: null, colour: C.ir, outputShape: Blockly.OUTPUT_SHAPE_ROUND,
    tooltip: '读取遥控器当前按下的方向'
  });

  def('zk_buzzer', {
    message0: '蜂鸣器 %1',
    args0: [{ type: 'field_dropdown', name: 'ACT', options: [['响', '1'], ['不响', '0']] }],
    previousStatement: null, nextStatement: null, colour: C.sound,
    tooltip: '扩展板板载蜂鸣器（注意：会占用 P0 口）'
  });

  /* ============================================================
   * 第二十九轮：八年级教材新增硬件对应的积木
   *
   * 依据 参考资料/mPython图形化mxml示例程序/八年级 的 31 个官方示例，
   * 官方积木名为 hunan_magnetic_* / hunan_mpython_bluebit_ATGM336H_* /
   * hunan_mpython_qr_code / hunan_mpython_bluebit_newrfid_* /
   * hunan_mpython_bluebit_ledong_speech_recognition_*，
   * 导入时由 project.js 的 TYPE_ALIAS 映射过来，导出时反向还原。
   * ============================================================ */

  /* ---------- 磁场传感器（板载 MMC5603NJ，I2C 0x30） ---------- */
  def('zk_magnetic_init', {
    message0: '初始化磁场传感器',
    args0: [], previousStatement: null, nextStatement: null, colour: C.onboard,
    tooltip: 'magnetic = Magnetic()：板载磁力计上电即自动初始化，' +
      '一般不需要手动调用；这里对应官方 hunan_mpython_magnetic_init'
  });

  def('zk_magnetic_calibrate', {
    message0: '磁场传感器校准',
    args0: [], previousStatement: null, nextStatement: null, colour: C.onboard,
    tooltip: 'magnetic.calibrate()：校准磁力计。使用前请把板子拿在手上' +
      '转圈（呈「8」字形反复转动），校准后才能准确读方位角'
  });

  def('zk_magnetic_peeling', {
    message0: '磁场传感器去皮',
    args0: [], previousStatement: null, nextStatement: null, colour: C.onboard,
    tooltip: 'magnetic.peeling()：记录当前磁场为基准并扣除（类似电子秤去皮），' +
      '用于测量相对磁场强度'
  });

  def('zk_magnetic_heading', {
    message0: '磁场方位角（0~359 度）',
    args0: [], output: 'Number', colour: C.onboard,
    tooltip: 'magnetic.get_heading()：返回磁北方向的夹角，0 度是正北，90 度是正东。' +
      '必须先校准'
  });

  /* ---------- 卫星定位 ATGM336H（UART） ---------- */
  def('zk_gps_init', {
    message0: '初始化卫星定位 串口 %1 发送脚P%2 接收脚 P%3',
    args0: [
      { type: 'field_dropdown', name: 'COM', options: [['1', '1'], ['2', '2'], ['3', '3']] },
      { type: 'field_dropdown', name: 'TX', options: [['15', '15'], ['16', '16'], ['13', '13']] },
      { type: 'field_dropdown', name: 'RX', options: [['16', '16'], ['15', '15'], ['14', '14']] }
    ],
    previousStatement: null, nextStatement: null, colour: C.net, inputsInline: true,
    tooltip: 'ATGM336H(北斗) 模块初始化，接上后大约 1~2 秒才能搜到卫星。' +
      '接线：模块 TX → 掌控板接收脚，模块 RX → 掌控板发送脚'
  });

  def('zk_gps_parse', {
    message0: '解析卫星数据',
    args0: [], previousStatement: null, nextStatement: null, colour: C.net,
    tooltip: 'GNSS.GNSS_Parese()：从串口缓存里解析出一帧定位数据。' +
      '建议每隔 500 毫秒调用一次'
  });

  def('zk_gps_data', {
    message0: '卫星定位数据 %1',
    args0: [{
      type: 'field_dropdown', name: 'K', options: [
        ['经度', 'lon'], ['纬度', 'lat'],
        ['东经西经', 'lonEW'], ['北纬南纬', 'latNS'],
        ['海拔（米）', 'alt'], ['卫星数', 'num'],
        ['定位有效性', 'valid'], ['UTC 时间', 'utc'], ['速度', 'speed'],
        /* 第三十三轮：让学生看出当前是真实定位还是模拟数据 */
        ['数据来源（真实/模拟）', 'src']
      ]
    }],
    output: null, colour: C.net, outputShape: Blockly.OUTPUT_SHAPE_ROUND,
    tooltip: '读取解析后的定位数据。卫星数≥4 且定位有效才准。\n' +
      '仿真面板点「📍用电脑定位」可取电脑的真实位置；\n' +
      '没点时用模拟数据（卫星数恒为 8，坐标在北京一带）'
  });

  def('zk_gps_ready', {
    message0: '卫星已定位？',
    args0: [], output: 'Boolean', colour: C.net,
    tooltip: '是否已经成功定位到卫星（数据有效）'
  });

  /* ---------- 二维码（板载 OLED 点阵生成） ---------- */
  def('zk_qrcode', {
    message0: '屏幕生成二维码 内容 %1 x:%2 y:%3',
    args0: [
      { type: 'input_value', name: 'STR' },
      { type: 'input_value', name: 'X', check: 'Number' },
      { type: 'input_value', name: 'Y', check: 'Number' }
    ],
    previousStatement: null, nextStatement: null, colour: C.oled, inputsInline: true,
    tooltip: '在OLED 屏幕上生成二维码，内容建议不超过 20 个字符，' +
      '超出部分会显示不全'
  }, function () {
    this.getInput('STR').connection.setShadowDom(
      Blockly.utils.xml.textToDom('<shadow type="text"><field name="TEXT">24992</field></shadow>'));
    this.getInput('X').connection.setShadowDom(
      Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">0</field></shadow>'));
    this.getInput('Y').connection.setShadowDom(
      Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">0</field></shadow>'));
  });

  /* ---------- RFID 射频卡（I2C） ----------
     官方 hunan_mpython_bluebit_newrfid_scan 是**语句积木**：
     扫码 + 判断放在同一块里（结构是 IF0 / DO0）。
     这里拆成两块，与本项目其它传感器保持一致的风格：
       zk_rfid_scan —— 语句积木，读卡（相当于官方积木本体）
       zk_rfid_id   —— 值积木，取最近一次读到的卡号 */
  def('zk_rfid_scan', {
    message0: '扫描 RFID 卡',
    args0: [], previousStatement: null, nextStatement: null, colour: C.color,
    inputsInline: true,
    tooltip: 'rfid.scanning()：读取射频卡序列号，结果存入卡号。' +
      '仿真中点击卡片面板上的卡A/卡B/卡C即可模拟刷卡'
  });

  def('zk_rfid_id', {
    message0: 'RFID 卡号',
    args0: [], output: 'String', colour: C.color,
    tooltip: '读取最近一次刷到的射频卡编号'
  });

  /* ---------- 离线语音识别模块（UART） ---------- */
  def('zk_speech2_init', {
    message0: '初始化离线语音识别 串口 %1 发送脚 P%2 接收脚 P%3',
    args0: [
      { type: 'field_dropdown', name: 'COM', options: [['1', '1'], ['2', '2']] },
      { type: 'field_dropdown', name: 'TX', options: [['16', '16'], ['13', '13']] },
      { type: 'field_dropdown', name: 'RX', options: [['15', '15'], ['14', '14']] }
    ],
    previousStatement: null, nextStatement: null, colour: C.mic, inputsInline: true,
    tooltip: '离线语音识别模块初始化。与云端AI 语音识别的区别是：' +
      '不联网、速度快，代价是只能识别固定的几条指令'
  });

  def('zk_speech2_result', {
    message0: '离线语音识别结果（文字）',
    args0: [], output: 'String', colour: C.mic,
    tooltip: '语音识别模块返回的文字结果，未识别时为空串'
  });

  /* ---------- 5行显示（官方 DispChar_5lines 的等价积木） ---------- */
  def('zk_oled_line5', {
    message0: '第 %1 行显示 %2',
    args0: [
      { type: 'input_value', name: 'LINE', check: 'Number' },
      { type: 'input_value', name: 'T' }
    ],
    previousStatement: null, nextStatement: null, colour: C.oled, inputsInline: true,
    tooltip: '在OLED 的第1~5 行中的某一行显示文字（八年级教材常用写法）。' +
      '行号填 1 表示最上面一行'
  }, function () {
    this.getInput('LINE').connection.setShadowDom(
      Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">1</field></shadow>'));
    this.getInput('T').connection.setShadowDom(
      Blockly.utils.xml.textToDom('<shadow type="text"><field name="TEXT">你好</field></shadow>'));
  });

  /* ---------- 字符串转数字（官方 string_to_number 的等价积木） ---------- */
  def('zk_str2num', {
    message0: '把 %1 转成 %2',
    args0: [
      { type: 'input_value', name: 'S' },
      { type: 'field_dropdown', name: 'TYPE', options: [['整数', 'int'], ['小数', 'float']] }
    ],
    output: 'Number', colour: C.math_block,
    tooltip: '把读到的文本（如传感器数值 "123"）转成数字才能参与计算与比较'
  }, function () {
    this.getInput('S').connection.setShadowDom(
      Blockly.utils.xml.textToDom('<shadow type="text"><field name="TEXT">1</field></shadow>'));
  });

  /* ============================================================
   * 第四十六轮：把变量限制在范围内的积木
   *
   * 【为什么要自己定义一个】Blockly 内置的 math_constrain
   * 三个口全是 input_value（VALUE / LOW / HIGH），
   * 第一个口拖出来是空口或数字，学生没法直接选「要限制哪个变量」。
   * 而实际教学里最常见的用法是：
   *   「把 温度 限制在 最低 0 到最高 100 之间」
   * ——第一个参数是一个**变量**，后两个是数字。
   *
   * 内置积木的口结构改不了（改了会破坏老工程与官方 mxml 兼容），
   * 所以另建一个 zk_constrain，第一个口用 field_variable。
   *
   * 【默认没有数字】field_variable 显示的是变量名而不是数字，
   * 符合用户「第一个（）使用变量（默认没有数字）」的要求。
   * ============================================================ */
  def('zk_constrain', {
    message0: '把 %1 限制在最低 %2 到最高 %3 之间',
    args0: [
      /* 第一个口：变量下拉（不是数字口） */
      { type: 'field_variable', name: 'VAR', variable: '我的变量', variableTypes: [''], defaultType: '' },
      /* 后两个口：可输入数字 */
      { type: 'input_value', name: 'LOW', check: 'Number' },
      { type: 'input_value', name: 'HIGH', check: 'Number' }
    ],
    output: 'Number', colour: C.math_block, inputsInline: true,
    tooltip: '把某个变量的值限制在指定的最低值与最高值之间，超出的部分会被截断'
  });

  /* 第四十九轮：教材（湘科版六年级）示例里大量出现「区间映射」
     hunan_map_value(x, in_min, in_max, out_min, out_max)
     例如把超声波距离 2~33cm 映射成音调 131~998Hz。
     之前没有对应积木，导入教材示例时这一句会被降级成文本。 */
  def('zk_map_value', {
    message0: '把 %1 从 [ %2 , %3 ] 映射到 [ %4 , %5 ]',
    args0: [
      { type: 'input_value', name: 'X', check: 'Number' },
      { type: 'input_value', name: 'A', check: 'Number' },
      { type: 'input_value', name: 'B', check: 'Number' },
      { type: 'input_value', name: 'C', check: 'Number' },
      { type: 'input_value', name: 'D', check: 'Number' }
    ],
    output: 'Number', colour: C.math_block, inputsInline: true,
    tooltip: '线性映射：把 X 从 [A, B] 区间按比例换算到 [C, D] 区间\n' +
      '例：把光线值 0~4095 映射成亮度 0~9'
  }, function () {
    var self = this;
    ['X', 'A', 'B', 'C', 'D'].forEach(function (k, i) {
      var n = ['0', '0', '4095', '0', '9'][i];
      self.getInput(k).connection.setShadowDom(
        Blockly.utils.xml.textToDom('<shadow type="math_number"><field name="NUM">' + n + '</field></shadow>'));
    });
  });

})(window);
