/* ============================================================
 * examples.js —— 内置示例工程（Blockly XML）
 * ============================================================ */
(function (global) {
  'use strict';
  var ZKB = global.ZKB || (global.ZKB = {});
  var NS = 'xmlns="https://developers.google.com/blockly/xml"';

  /* ---------------- 示例 1：屏幕显示 Hello ---------------- */
  var exHello = '' +
    '<xml ' + NS + '>' +
    '<block type="zk_when_start" x="40" y="40"><next>' +
    '<block type="zk_oled_screen"><field name="V">clear</field><next>' +
    '<block type="zk_oled_text">' +
    '<value name="T"><shadow type="text"><field name="TEXT">你好，掌控板</field></shadow></value>' +
    '<value name="X"><shadow type="math_number"><field name="NUM">0</field></shadow></value>' +
    '<value name="Y"><shadow type="math_number"><field name="NUM">0</field></shadow></value>' +
    '<next><block type="zk_oled_text">' +
    '<value name="T"><shadow type="text"><field name="TEXT">Hello mPython</field></shadow></value>' +
    '<value name="X"><shadow type="math_number"><field name="NUM">0</field></shadow></value>' +
    '<value name="Y"><shadow type="math_number"><field name="NUM">20</field></shadow></value>' +
    '<next><block type="zk_oled_show"><next>' +
    '<block type="zk_rgb_one"><field name="N">0</field><field name="COLOR">#3ddc84</field><next>' +
    '<block type="zk_print"><value name="V"><shadow type="text"><field name="TEXT">你好，掌控图形化编程！</field></shadow></value>' +
    '</block></next></block></next></block></next></block></next></block></next></block>' +
    '</xml>';

  /* ---------------- 示例 2：按键控制彩灯与蜂鸣器 ---------------- */
  var exButton = '' +
    '<xml ' + NS + '>' +
    '<block type="zk_when_start" x="40" y="40"><next>' +
    '<block type="zk_rgb_brightness"><value name="V"><shadow type="math_number"><field name="NUM">60</field></shadow></value></block>' +
    '</next></block>' +
    '<block type="zk_when_btn" x="40" y="180"><field name="BTN">A</field><next>' +
    '<block type="zk_rgb_one"><field name="N">ALL</field><field name="COLOR">#ff5d5d</field><next>' +
    '<block type="zk_note"><field name="NOTE">C4</field><field name="BEAT">0.5</field><next>' +
    '<block type="zk_print"><value name="V"><shadow type="text"><field name="TEXT">A 键：亮红灯</field></shadow></value></block>' +
    '</next></block></next></block></next></block>' +
    '<block type="zk_when_btn" x="40" y="330"><field name="BTN">B</field><next>' +
    '<block type="zk_rgb_clear"><next>' +
    '<block type="zk_note"><field name="NOTE">E5</field><field name="BEAT">0.5</field></block>' +
    '</next></block></next></block>' +
    '</xml>';

  /* ---------------- 示例 3：温湿度周期显示 ---------------- */
  var exDht = '' +
    '<xml ' + NS + '>' +
    '<block type="zk_when_start" x="40" y="40"><next>' +
    '<block type="controls_forever"><statement name="SUBSTACK">' +
    '<block type="zk_dht_measure"><next>' +
    '<block type="zk_oled_screen"><field name="V">clear</field><next>' +
    '<block type="zk_oled_text">' +
    '<value name="T"><block type="text_join"><mutation items="2"></mutation>' +
    '<value name="ADD0"><shadow type="text"><field name="TEXT">温度: </field></shadow></value>' +
    '<value name="ADD1"><block type="zk_dht_val"><field name="K">t</field></block></value>' +
    '</block></value>' +
    '<value name="X"><shadow type="math_number"><field name="NUM">0</field></shadow></value>' +
    '<value name="Y"><shadow type="math_number"><field name="NUM">0</field></shadow></value>' +
    '<next><block type="zk_oled_text">' +
    '<value name="T"><block type="text_join"><mutation items="2"></mutation>' +
    '<value name="ADD0"><shadow type="text"><field name="TEXT">湿度: </field></shadow></value>' +
    '<value name="ADD1"><block type="zk_dht_val"><field name="K">h</field></block></value>' +
    '</block></value>' +
    '<value name="X"><shadow type="math_number"><field name="NUM">0</field></shadow></value>' +
    '<value name="Y"><shadow type="math_number"><field name="NUM">22</field></shadow></value>' +
    '<next><block type="zk_oled_show"><next>' +
    '<block type="zk_wait_sec"><value name="SEC"><shadow type="math_number"><field name="NUM">1</field></shadow></value></block>' +
    '</next></block></next></block></next></block></next></block></next></block>' +
    '</statement></block></next></block>' +
    '</xml>';

  /* ---------------- 示例 4：超声波避障小车（双程序并行） ----------------
     车头带探测距离提示线。行人与小车写成**两个独立的「当掌控板 启动时」程序并行运行**：
       程序 A（行人）：用运动模块的「把元素 移到 x,y」实现上下行走（中心原点）——
         启动先把行人移到起点 (-70,-62) 做位置初始化，
         再逐段把 Y 调大（40 → 172）往下走过马路，
         到对面停 4 秒，再把 Y 改回 -62 回到上方入口，循环往复。
       程序 B（小车）：位置初始化 → 循环；前方 30cm 内有障碍时判断类别——
         · 60cm 内有行人 → 停车让行，等行人通过再走；
         · 是车辆等 → 后退确认安全 → 左转 45° 超越 → 右转 45° 回原车道。
     元素下拉在 XML 里写元素键（car / pedestrian），由 loadExample 按 elKeys 自动换成 uid。
     注：本段由 tools/gen-example4.py 构造（标签成对闭合），请改生成器而非手改此处。*/
  var exCar = '' +
    '<xml xmlns="http://www.w3.org/1999/xhtml"><block type="zk_when_start"><next><block type="zk_mv_goto"><field name="EL">pedestrian</field>><value name="X"><shadow type="math_number"><field name="NUM">-7' +
    '0</field></shadow></value><value name="Y"><shadow type="math_number"><field name="NUM">-62</field></shadow></value><next><block type="zk_print"><value name="V"><shadow type="text"><field name="TEXT">行' +
    '人已初始化到起点（与小车程序并行运行）</field></shadow></value><next><block type="zk_wait_sec"><value name="SEC"><shadow type="math_number"><field name="NUM">3</field></shadow></value><next><block type="controls_forever' +
    '"><value name="SUBSTACK"><block type="zk_mv_goto"><field name="EL">pedestrian</field>><value name="X"><shadow type="math_number"><field name="NUM">-70</field></shadow></value><value name="Y"><shadow t' +
    'ype="math_number"><field name="NUM">-20</field></shadow></value><next><block type="zk_wait_sec"><value name="SEC"><shadow type="math_number"><field name="NUM">1</field></shadow></value><next><block ty' +
    'pe="zk_mv_goto"><field name="EL">pedestrian</field>><value name="X"><shadow type="math_number"><field name="NUM">-70</field></shadow></value><value name="Y"><shadow type="math_number"><field name="NUM' +
    '">40</field></shadow></value><next><block type="zk_wait_sec"><value name="SEC"><shadow type="math_number"><field name="NUM">1</field></shadow></value><next><block type="zk_mv_goto"><field name="EL">pe' +
    'destrian</field>><value name="X"><shadow type="math_number"><field name="NUM">-70</field></shadow></value><value name="Y"><shadow type="math_number"><field name="NUM">172</field></shadow></value><next' +
    '><block type="zk_wait_sec"><value name="SEC"><shadow type="math_number"><field name="NUM">4</field></shadow></value><next><block type="zk_print"><value name="V"><shadow type="text"><field name="TEXT">' +
    '行人已到达对面</field></shadow></value><next><block type="zk_mv_goto"><field name="EL">pedestrian</field>><value name="X"><shadow type="math_number"><field name="NUM">-70</field></shadow></value><value name=' +
    '"Y"><shadow type="math_number"><field name="NUM">-62</field></shadow></value><next><block type="zk_wait_sec"><value name="SEC"><shadow type="math_number"><field name="NUM">1</field></shadow></value><n' +
    'ext><block type="zk_print"><value name="V"><shadow type="text"><field name="TEXT">行人回到斑马线入口（Y 改回 -62）</field></shadow></value></block></next></block></next></block></next></block></next></block></next' +
    '></block></next></block></next></block></next></block></next></block></value></block></next></block></next></block></next></block></next></block><block type="zk_when_start"><next><block type="zk_mv_go' +
    'to"><field name="EL">car</field>><value name="X"><shadow type="math_number"><field name="NUM">-310</field></shadow></value><value name="Y"><shadow type="math_number"><field name="NUM">42</field></shad' +
    'ow></value><next><block type="zk_print"><value name="V"><shadow type="text"><field name="TEXT">避障小车启动！车头探测线已开启</field></shadow></value><next><block type="zk_print"><value name="V"><shadow type="text">' +
    '<field name="TEXT">行人优先：近了就停车让行</field></shadow></value><next><block type="zk_print"><value name="V"><shadow type="text"><field name="TEXT">遇到车辆：确认安全后左转 45° 超越</field></shadow></value><next><block typ' +
    'e="controls_forever"><value name="SUBSTACK"><block type="controls_if"><mutation else="1"></mutation><value name="IF0"><block type="zk_front_has"><field name="KIND">ANY</field>><value name="CM"><shadow' +
    ' type="math_number"><field name="NUM">30</field></shadow></value></block></value><statement name="DO0"><block type="controls_if"><mutation else="1"></mutation><value name="IF0"><block type="zk_front_h' +
    'as"><field name="KIND">pedestrian</field>><value name="CM"><shadow type="math_number"><field name="NUM">60</field></shadow></value></block></value><statement name="DO0"><block type="zk_print"><value n' +
    'ame="V"><shadow type="text"><field name="TEXT">前方有行人，停车让行</field></shadow></value><next><block type="zk_car"><field name="DIR">s</field>><value name="S"><shadow type="math_number"><field name="NUM">0<' +
    '/field></shadow></value><next><block type="zk_wait_sec"><value name="SEC"><shadow type="math_number"><field name="NUM">1.2</field></shadow></value><next><block type="zk_print"><value name="V"><shadow ' +
    'type="text"><field name="TEXT">行人已通过，继续行驶</field></shadow></value></block></next></block></next></block></next></block></statement><statement name="ELSE"><block type="zk_print"><value name="V"><shadow' +
    ' type="text"><field name="TEXT">前方有车辆，后退确认安全</field></shadow></value><next><block type="zk_car"><field name="DIR">b</field>><value name="S"><shadow type="math_number"><field name="NUM">30</field></sha' +
    'dow></value><next><block type="zk_wait_sec"><value name="SEC"><shadow type="math_number"><field name="NUM">0.5</field></shadow></value><next><block type="zk_print"><value name="V"><shadow type="text">' +
    '<field name="TEXT">安全，左转 45° 超越前车</field></shadow></value><next><block type="zk_car"><field name="DIR">l</field>><value name="S"><shadow type="math_number"><field name="NUM">45</field></shadow></value' +
    '><next><block type="zk_wait_sec"><value name="SEC"><shadow type="math_number"><field name="NUM">0.7</field></shadow></value><next><block type="zk_car"><field name="DIR">f</field>><value name="S"><shad' +
    'ow type="math_number"><field name="NUM">60</field></shadow></value><next><block type="zk_wait_sec"><value name="SEC"><shadow type="math_number"><field name="NUM">1.2</field></shadow></value><next><blo' +
    'ck type="zk_car"><field name="DIR">r</field>><value name="S"><shadow type="math_number"><field name="NUM">45</field></shadow></value><next><block type="zk_wait_sec"><value name="SEC"><shadow type="mat' +
    'h_number"><field name="NUM">0.7</field></shadow></value><next><block type="zk_car"><field name="DIR">s</field>><value name="S"><shadow type="math_number"><field name="NUM">0</field></shadow></value></' +
    'block></next></block></next></block></next></block></next></block></next></block></next></block></next></block></next></block></next></block></next></block></statement><next><block type="zk_wait_ms"><' +
    'value name="MS"><shadow type="math_number"><field name="NUM">120</field></shadow></value></block></next></block></statement><statement name="ELSE"><block type="zk_car"><field name="DIR">f</field>><val' +
    'ue name="S"><shadow type="math_number"><field name="NUM">60</field></shadow></value></block></statement><next><block type="zk_wait_ms"><value name="MS"><shadow type="math_number"><field name="NUM">100' +
    '</field></shadow></value></block></next></block></value></block></next></block></next></block></next></block></next></block></next></block></xml>';

  /* ---------------- 示例 5：光线感应台灯 ---------------- */
  var exLight = '' +
    '<xml ' + NS + '>' +
    '<block type="zk_when_start" x="40" y="40"><next>' +
    '<block type="controls_forever"><statement name="SUBSTACK">' +
    '<block type="controls_if"><mutation else="1"></mutation>' +
    '<value name="IF0"><block type="logic_compare"><field name="OP">LT</field>' +
    '<value name="A"><block type="zk_ambient"/></value>' +
    '<value name="B"><shadow type="math_number"><field name="NUM">400</field></shadow></value>' +
    '</block></value>' +
    '<statement name="DO0">' +
    '<block type="zk_rgb_one"><field name="N">ALL</field><field name="COLOR">#ffd76b</field><next>' +
    '<block type="zk_print"><value name="V"><shadow type="text"><field name="TEXT">光线不足，台灯自动打开</field></shadow></value></block>' +
    '</next></block>' +
    '</statement>' +
    '<statement name="ELSE">' +
    '<block type="zk_rgb_clear"></block>' +
    '</statement>' +
    '<next><block type="zk_wait_sec"><value name="SEC"><shadow type="math_number"><field name="NUM">0.5</field></shadow></value></block></next>' +
    '</block>' +
    '</statement></block></next></block>' +
    '</xml>';

  /* ---------------- 示例 6：无线广播控灯 ---------------- */
  var exRadio = '' +
    '<xml ' + NS + '>' +
    '<block type="zk_when_start" x="40" y="40"><next>' +
    '<block type="zk_radio_group"><value name="G"><shadow type="math_number"><field name="NUM">7</field></shadow></value><next>' +
    '<block type="zk_rgb_brightness"><value name="V"><shadow type="math_number"><field name="NUM">70</field></shadow></value><next>' +
    '<block type="zk_print"><value name="V"><shadow type="text"><field name="TEXT">无线广播已开启，频道 7</field></shadow></value></block>' +
    '</next></block></next></block></next></block>' +
    '<block type="zk_when_btn" x="40" y="210"><field name="BTN">A</field><next>' +
    '<block type="zk_radio_send"><value name="MSG"><shadow type="text"><field name="TEXT">开灯</field></shadow></value></block>' +
    '</next></block>' +
    '<block type="zk_when_btn" x="40" y="310"><field name="BTN">B</field><next>' +
    '<block type="zk_radio_send"><value name="MSG"><shadow type="text"><field name="TEXT">关灯</field></shadow></value></block>' +
    '</next></block>' +
    '<block type="zk_when_radio" x="420" y="40"><next>' +
    '<block type="controls_if"><mutation else="1"></mutation>' +
    '<value name="IF0"><block type="logic_compare"><field name="OP">EQ</field>' +
    '<value name="A"><block type="zk_radio_msg"/></value>' +
    '<value name="B"><shadow type="text"><field name="TEXT">开灯</field></shadow></value>' +
    '</block></value>' +
    '<statement name="DO0">' +
    '<block type="zk_rgb_one"><field name="N">ALL</field><field name="COLOR">#ffd76b</field><next>' +
    '<block type="zk_print"><value name="V"><shadow type="text"><field name="TEXT">收到广播：开灯</field></shadow></value></block>' +
    '</next></block></statement>' +
    '<statement name="ELSE"><block type="zk_rgb_clear"><next>' +
    '<block type="zk_print"><value name="V"><shadow type="text"><field name="TEXT">收到广播：关灯</field></shadow></value></block>' +
    '</next></block></statement>' +
    '</block></next></block>' +
    '</xml>';

  /* ---------------- 示例 7：MQTT 物联灯 ---------------- */
  var exMqtt = '' +
    '<xml ' + NS + '>' +
    '<block type="zk_when_start" x="40" y="40"><next>' +
    '<block type="zk_wifi_connect">' +
    '<value name="SSID"><shadow type="text"><field name="TEXT">教室WiFi</field></shadow></value>' +
    '<value name="PWD"><shadow type="text"><field name="TEXT">12345678</field></shadow></value>' +
    '<next><block type="zk_mqtt_connect">' +
    '<value name="HOST"><shadow type="text"><field name="TEXT">mqtt.example.cn</field></shadow></value>' +
    '<value name="PORT"><shadow type="math_number"><field name="NUM">1883</field></shadow></value>' +
    '<next><block type="zk_print"><value name="V"><shadow type="text"><field name="TEXT">MQTT 物联灯已就绪</field></shadow></value></block>' +
    '</next></block></next></block></next></block>' +
    '<block type="zk_when_mqtt" x="40" y="260">' +
    '<value name="TOPIC"><shadow type="text"><field name="TEXT">/classroom/light</field></shadow></value>' +
    '<next>' +
    '<block type="controls_if"><mutation else="1"></mutation>' +
    '<value name="IF0"><block type="logic_compare"><field name="OP">EQ</field>' +
    '<value name="A"><block type="zk_mqtt_msg"/></value>' +
    '<value name="B"><shadow type="text"><field name="TEXT">on</field></shadow></value>' +
    '</block></value>' +
    '<statement name="DO0"><block type="zk_rgb_one"><field name="N">ALL</field><field name="COLOR">#7fe0a0</field></block></statement>' +
    '<statement name="ELSE"><block type="zk_rgb_clear"></block></statement>' +
    '</block></next></block>' +
    '</xml>';

  /* ---------------- 示例 8：天气播报站（含变量监视器） ---------------- */
  var exWeather = '' +
    '<xml ' + NS + '>' +
    '<variables><variable id="wb_temp">最高温</variable></variables>' +
    '<block type="zk_when_start" x="40" y="40"><next>' +
    '<block type="zk_wifi_connect">' +
    '<value name="SSID"><shadow type="text"><field name="TEXT">教室WiFi</field></shadow></value>' +
    '<value name="PWD"><shadow type="text"><field name="TEXT">12345678</field></shadow></value>' +
    '<next><block type="zk_var_show"><field name="VAR" id="wb_temp">最高温</field><next>' +
    '<block type="controls_forever"><statement name="SUBSTACK">' +
    '<block type="zk_oled_screen"><field name="V">clear</field><next>' +
    '<block type="variables_set"><field name="VAR" id="wb_temp">最高温</field>' +
    '<value name="VALUE"><block type="zk_weather"><field name="K">high</field>' +
    '<value name="CITY"><shadow type="text"><field name="TEXT">北京</field></shadow></value>' +
    '</block></value><next>' +
    '<block type="zk_oled_text">' +
    '<value name="T"><block type="text_join"><mutation items="2"></mutation>' +
    '<value name="ADD0"><shadow type="text"><field name="TEXT">北京：</field></shadow></value>' +
    '<value name="ADD1"><block type="zk_weather"><field name="K">text</field>' +
    '<value name="CITY"><shadow type="text"><field name="TEXT">北京</field></shadow></value>' +
    '</block></value></block></value>' +
    '<value name="X"><shadow type="math_number"><field name="NUM">0</field></shadow></value>' +
    '<value name="Y"><shadow type="math_number"><field name="NUM">0</field></shadow></value>' +
    '<next><block type="zk_oled_text">' +
    '<value name="T"><block type="text_join"><mutation items="3"></mutation>' +
    '<value name="ADD0"><shadow type="text"><field name="TEXT">最高 </field></shadow></value>' +
    '<value name="ADD1"><block type="variables_get"><field name="VAR" id="wb_temp">最高温</field></block></value>' +
    '<value name="ADD2"><shadow type="text"><field name="TEXT"> ℃</field></shadow></value>' +
    '</block></value>' +
    '<value name="X"><shadow type="math_number"><field name="NUM">0</field></shadow></value>' +
    '<value name="Y"><shadow type="math_number"><field name="NUM">22</field></shadow></value>' +
    '<next><block type="zk_oled_show"><next>' +
    '<block type="zk_wait_sec"><value name="SEC"><shadow type="math_number"><field name="NUM">10</field></shadow></value></block>' +
    '</next></block></next></block></next></block></next></block></next></block>' +
    '</statement></block></next></block></next></block></next></block>' +
    '</xml>';

  /* 示例的舞台情景：载入示例时自动切换到对应情景（scene 字段） */
  ZKB.EXAMPLES = [
    {
      name: '① 你好，掌控板',
      desc: '屏幕显示文字、点亮彩灯、串口输出',
      devices: [], scene: 'study', xml: exHello
    },
    {
      name: '② 按键控制彩灯',
      desc: 'A/B 键事件、RGB、蜂鸣器（仿真中点击板上 A/B）',
      devices: [], scene: 'living', xml: exButton
    },
    {
      name: '③ 温湿度实时显示',
      desc: 'DHT11 测量、循环、屏幕显示（拓展：温湿度传感器）',
      devices: ['dht'], scene: 'campus', xml: exDht
    },
    {
      name: '④ 超声波避障小车',
      desc: '车头探测线实时测距：遇行人停车让行、行人过斑马线后继续；遇车辆确认安全后左转 45° 超越；其它障碍绕行',
      devices: ['ultrasonic', 'car'], scene: 'traffic',
      elKeys: ['car', 'pedestrian'], elKey: 'car', xml: exCar
    },
    {
      name: '⑤ 光线感应台灯',
      desc: '光线传感器 < 400 自动亮灯；载入后舞台切到「书房学习桌」，光线变暗时台灯亮起、太阳变月亮',
      devices: ['lightExt'], scene: 'study', xml: exLight
    },
    {
      name: '⑥ 无线广播控灯',
      desc: '同频道两块掌控板互相发消息，A/B 键发送、收到广播自动亮灯（拓展：无线广播）',
      devices: ['radio'], scene: 'smarthome', xml: exRadio
    },
    {
      name: '⑦ MQTT 物联灯',
      desc: '连接 WiFi 与 MQTT 服务器，服务器下发消息远程开关灯（拓展：WiFi+MQTT）',
      devices: ['wifi', 'mqtt'], scene: 'smarthome', xml: exMqtt
    },
    {
      name: '⑧ 天气播报站',
      desc: '查询城市天气（联网真实 / 离线按月模拟），屏幕显示并用变量监视器展示最高温（拓展：WiFi+天气）',
      devices: ['wifi', 'weather'], scene: 'campus', xml: exWeather
    }
  ];

})(window);
