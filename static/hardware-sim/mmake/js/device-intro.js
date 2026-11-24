/* ============================================================
 * device-intro.js —— 拓展库设备详细介绍 + 「视频介绍」
 *
 * 第五十轮新增。
 *   ① 悬停「拓展库」里的设备卡片 → 弹出详细说明
 *      （是什么 / 怎么接线 / 课堂里能做什么 / 容易踩的坑）
 *   ② 卡片右上角出现 ▶ 按钮 → 打开「视频介绍」
 *
 * 关于「视频」：整个项目是单文件离线运行的，不能外链网络视频，
 * 所以这里做了一个**内嵌的分镜动画播放器**——
 * 4 幕分镜自动轮播（登场 → 接线 → 工作原理 → 课堂用法），
 * 带字幕、进度点、暂停/播放，效果等同一段几十秒的设备介绍短片，
 * 而且不依赖任何外部资源、断网也能看。
 * ============================================================ */
(function (global) {
  'use strict';
  var ZKB = global.ZKB || (global.ZKB = {});

  /* ============================================================
   * 一、设备文案
   *   what —— 这是什么
   *   how  —— 怎么接线 / 怎么用
   *   use  —— 课堂上能做什么
   *   tip  —— 容易踩的坑
   *   demo —— 视频第 3 幕用哪种动画（见 demoSvg）
   * ============================================================ */
  var INTRO = {
    /* ---------- 传感器 ---------- */
    dht: {
      demo: 'sense',
      what: 'DHT11 数字温湿度传感器，能同时测出空气温度和相对湿度。它内部已经把模拟量转成了数字信号，所以读数稳定、不容易飘。',
      how: '三根线：VCC 接 3V3、GND 接 GND、DATA 接 P1。数据脚是单总线协议，一根线既传数据也供给时序。',
      use: '做「温度提醒器」「自动孵蛋箱」「智能温室」——判断温度超过阈值就开风扇或报警。',
      tip: '两次读数之间至少要隔 1 秒，循环里记得加「等待 1 秒」；刚上电第一次读到的常常是 0，可以先空读一次。'
    },
    ultrasonic: {
      demo: 'distance',
      what: 'HC-SR04 超声波测距模块：一头发射 40kHz 超声波，一头接收回波，用「发出到收到」的时间差算出距离。',
      how: '四根线：VCC、GND、Trig 接 P14、Echo 接 P13。Trig 发一个 10μs 高电平触发，Echo 的高电平宽度就是回波时间。',
      use: '做「倒车雷达」「自动避障小车」「坐姿监控器」——人离屏幕太近就提醒。',
      tip: '量程大约 2~400cm，2cm 以内和软布料（毛衣、窗帘）经常测不到，程序里要处理「读数为 0 或超大」的情况。'
    },
    ir: {
      demo: 'switch',
      what: '红外反射式避障传感器：发射红外光，靠反射光强弱判断前方有没有障碍物。',
      how: '三根线：VCC、GND、OUT 接 P21。检测到障碍物时 OUT 一般输出低电平。',
      use: '做「防撞小车」「自动门」「传送带计数」——比超声波便宜、响应快，但只能判断「有 / 没有」，测不出距离。',
      tip: '黑色物体吸光，可能检测不到；阳光直射会干扰。阈值用电位器调，调到指示灯刚好亮灭的临界点最灵敏。'
    },
    color: {
      demo: 'rgb',
      what: 'TCS34725 颜色传感器：通过 I2C 读取红、绿、蓝三个通道的光强，换算出被测物体的颜色。',
      how: '四根线（I2C）：VCC、GND、SDA、SCL。掌控板 I2C 口是固定的，接 I2C_3V3 或 I2C_5V 都行。',
      use: '做「颜色分拣机」「会认颜色的灯」——把识别到的颜色显示在屏幕上，或让彩灯变成同样的颜色。',
      tip: '测量距离要近（1~3cm），环境光会影响结果；测之前先用白纸做一次白平衡会更准。'
    },
    camera: {
      demo: 'screen',
      what: 'AI 摄像头（K210 等模块）：板载神经网络加速，能直接做人脸识别、物体识别、文字识别，不用联网。',
      how: '串口连接：TX 接 P13、RX 接 P14，VCC/GND 供电。识别结果通过串口以固定格式发给掌控板。',
      use: '做「人脸签到」「垃圾分类助手」「车牌识别」——把识别结果当条件，去控制灯、舵机或屏幕。',
      tip: '识别率受光线和角度影响很大；每次识别要几十到几百毫秒，循环里别放太紧，加一点等待更稳。'
    },
    mic: {
      demo: 'sound',
      what: '模拟量声音传感器（麦克风模块）：把声音大小转成 0~4095 的模拟电压，只能测「响不响」，不能还原声音内容。',
      how: '三根线：VCC、GND、AO 接 P3（模拟输入口）。注意接 AO 而不是 DO（DO 只有「超过阈值」的开关量）。',
      use: '做「声控灯」「噪音监测仪」「拍手计数器」——声音超过阈值就触发动作。',
      tip: '读的是瞬时音量，说话时数值会剧烈跳动，通常要连续采样几次取平均或取最大值再判断。'
    },
    lightExt: {
      demo: 'sense',
      what: '模拟量光线传感器（光敏电阻模块）：把光照强度转成 0~4095 的模拟值，越亮数值越大。',
      how: '三根线：VCC、GND、AO 接 P2（模拟输入口）。',
      use: '做「光控灯」「护眼台灯」「自动窗帘」——天黑自动开灯、太亮自动调暗。',
      tip: '不同传感器数值范围差别很大，不要照抄别人的阈值；先打印几次读数看看自己这个模块的实际范围。'
    },
    tracker: {
      demo: 'distance',
      what: '五路巡线传感器（SEN0241）：并排 5 组红外对管，每组独立输出「是否压在黑线上」。',
      how: 'VCC、GND，另有 5 个信号脚分别接 5 个数字口（P13、P14 等）。',
      use: '做「循迹小车」——中间探头压线说明走正了，左侧压线说明偏右了要往左修。',
      tip: '探头离地 1~2cm 效果最好；黑线要够黑、地面要够白，环境光太强时先在暗一点的地方调阈值。'
    },
    gravity: {
      demo: 'rgb',
      what: 'AS7341 可见光颜色传感器（SEN0364）：11 个光谱通道，比普通 RGB 传感器更能分辨相近的颜色。',
      how: 'I2C 四线：VCC、GND、SDA、SCL，接掌控板 I2C 口。',
      use: '做「精确颜色分拣」「灯光色温检测」——需要分辨相近颜色（比如深蓝和浅蓝）时用它。',
      tip: '读数受光源影响，测同一个物体时尽量保持光源和距离一致；需要较长的积分时间，别读太快。'
    },
    powerMeter: {
      demo: 'sense',
      what: '数字功率计（SEN0291）：I2C 接口，能测出电压、电流，并算出实时功率。',
      how: 'I2C 四线接掌控板；被测电路串在模块的输入端子上。',
      use: '做「节能监测」「电器功耗对比实验」——测一节课里风扇、台灯各耗多少电。',
      tip: '注意模块的额定量程，不要测超过量程的电路；测量时电流方向要对，接反会读成负数。'
    },
    angle: {
      demo: 'move',
      what: '角度传感器（旋转电位器）：转轴的角度被转换成模拟电压，读数范围 0~300°左右。',
      how: '三根线：VCC、GND、AO 接 P2（模拟输入口）。',
      use: '做「旋钮调光灯」「机械臂关节角度」「音量旋钮」——把转动角度当成一个连续的输入量。',
      tip: '机械上通常转不到 360°，两端会有死区，做映射时先把实际范围量一遍。'
    },
    irRx: {
      demo: 'distance',
      what: '红外接收模块（DFR0094）：接收红外遥控器发的 38kHz 编码信号，解出按键码值。',
      how: '三根线：VCC、GND、OUT 接 P15（数字输入口）。',
      use: '做「遥控小车」「红外遥控灯」——按下遥控器不同键，程序里比较码值执行不同动作。',
      tip: '不同遥控器的码值完全不同，必须先用「读取红外码」把自家遥控器的键值一个个记下来。'
    },
    soil: {
      demo: 'sense',
      what: '土壤湿度传感器：两片电极插入土里，靠土壤导电性反映含水量，输出模拟值。',
      how: '三根线：VCC、GND、AO 接 P10（模拟输入口）。',
      use: '做「自动浇水」「植物养护提醒」——土太干就开水泵。',
      tip: '长期通电会电解腐蚀电极，建议只在测量时供电；砂土和黏土的读数差别很大，要按自己班的土重新定阈值。'
    },
    pm25: {
      demo: 'sense',
      what: 'PM2.5 粉尘传感器：激光散射原理，数出空气中悬浮颗粒的浓度（μg/m³）。',
      how: '一般四线：VCC、GND、TX/RX 接 P22、P23（串口）。',
      use: '做「教室空气质量看板」「雾霾提醒灯」——浓度超标亮红灯。',
      tip: '上电后需要几十秒预热，读数才会稳定；风扇进气口别堵住。'
    },
    baro: {
      demo: 'sense',
      what: '气压传感器（BMP280 等）：测量大气压强，单位 hPa，也能顺带算海拔。',
      how: 'I2C 四线：VCC、GND、SDA、SCL。',
      use: '做「天气预报瓶」「海拔计」「气压变化记录」——气压骤降往往意味着要变天。',
      tip: '气压随海拔变化明显，同一层楼不同高度也会有差别；做实验时把传感器固定在一个位置。'
    },
    button: {
      demo: 'switch',
      what: '外接轻触按键模块：按下时输出一个电平变化，用来做外部触发。',
      how: '三根线：VCC、GND、OUT 接 P15（数字输入口）。',
      use: '做「外部确认键」「门铃」「计数器」——掌控板自带的 A/B 键不够用时加它。',
      tip: '机械按键会抖动，读一次可能误判，程序里加 20~50ms 的等待再读第二次更可靠。'
    },
    pir: {
      demo: 'switch',
      what: '人体红外传感器（PIR）：靠检测人体发出的红外线变化来判断「有人经过」，只能给出「有 / 无」。',
      how: '三根线：VCC、GND、OUT 接 P15（数字输入口）。',
      use: '做「人来灯亮」「走廊节能灯」「入侵报警」——比摄像头简单，也不涉及隐私。',
      tip: '上电后要 30 秒左右初始化；人不动时也可能判为「无人」，因为它测的是「移动」。'
    },
    magnetic: {
      demo: 'sense',
      what: '板载磁力计 MMC5603NJ（I2C 0x30）：测三轴磁场，可以算出板子朝向的方位角。',
      how: '板载，无需接线。首次使用建议先做一次「校准」，否则方位角会偏。',
      use: '做「电子指南针」「转向检测」——需要「板子朝哪个方向」时用它。',
      tip: '附近有磁铁、音箱、电机都会干扰；校准要在远离金属的桌面上做。'
    },
    gps: {
      demo: 'net',
      what: '卫星定位模块（ATGM336H，北斗/GPS 双模）：通过串口输出经纬度、海拔、时间。',
      how: '四线：VCC、GND、TX 接 P13、RX 接 P15（串口）。天线要朝上、尽量放室外。',
      use: '做「定位打卡」「轨迹记录」「精准授时」。',
      tip: '室内几乎收不到星，必须到室外空旷处；冷启动可能要 1~3 分钟才有定位。'
    },

    /* ---------- 执行器 ---------- */
    servo: {
      demo: 'move',
      what: 'SG90 舵机：给一个角度（0~180°），内部电路自己闭环转到那个位置并保持住。',
      how: '三根线：棕色 GND、红色 VCC、橙色信号接 P0（PWM 输出）。',
      use: '做「机械臂」「自动门」「投喂器翻盖」「云台」——需要「转到指定角度并停住」的场合。',
      tip: '舵机启动电流大，多个舵机同时动容易把板子拉复位，建议外接电源；别强行用手掰，会扫齿。'
    },
    heater: {
      demo: 'switch',
      what: '加热元件（加热片 / 加热丝）：通电就发热，功率越大升温越快。',
      how: '通过 PWM 口（P9）控制，一般要加一个三极管或 MOS 管做开关，不能直接用 IO 驱动。',
      use: '做「恒温箱」「自动孵蛋箱」——温度低于阈值就加热。',
      tip: '一定要「测—判—控」闭环，别一直全功率加热；加热片很烫，做外壳时要留散热和防烫。'
    },
    car: {
      demo: 'move',
      what: '小车模型（四驱 / 两驱底盘）：两个（或四个）直流电机，通过左右轮差速实现前进、后退、转向。',
      how: '左右电机各占两个 IO（P8、P16、P19、P20），用 PWM 调速、用两个 IO 的高低电平换向。',
      use: '做「避障小车」「遥控小车」「巡线小车」——小学阶段最综合的项目载体。',
      tip: '左右轮速不一致会跑偏，可以在程序里做一点补偿；电池电压下降后速度会变慢，这不是程序 bug。'
    },
    motor: {
      demo: 'spin',
      what: '直流电机（带驱动）：给电压就转，电压越高转得越快；交换正负极就反转。',
      how: '接电机驱动板的 M1/M2 口，驱动板再用 P6、P7 两个 PWM 口控制转速与方向。',
      use: '做「风扇」「传送带」「搅拌器」「升降机构」。',
      tip: 'IO 口不能直接带电机（电流不够还会烧板子），必须经过驱动；电机两端并联一个电容能减少干扰。'
    },
    pump: {
      demo: 'switch',
      what: '微型水泵：通电抽水，可以开关控制，也可以用 PWM 调流量。',
      how: '经驱动接 P11（PWM 输出），水泵单独供电更稳。',
      use: '做「自动浇水」「自动喂水器」「水位控制」。',
      tip: '水泵不能空转太久（会烧），程序里最好加一个「水位检测」；管子里有空气时先排气。'
    },
    ledModule: {
      demo: 'light',
      what: '单色 LED 模块：一个高亮 LED 加限流电阻，亮度可以用 PWM 连续调节，也可以只做「开 / 关」。',
      how: '三根线：VCC、GND、信号接 P13。信号脚给 PWM 就能调亮度，给高低电平就是开关。',
      use: '做「光控灯」「呼吸灯」「状态指示灯」「护眼台灯」——最基础也最常用的输出设备。',
      tip: '亮度 0 不等于断电，只是占空比为 0；PWM 频率太低时肉眼会看到闪烁，掌控板默认频率已经够高。'
    },
    rgbStrip: {
      demo: 'rgb',
      what: 'RGB 灯带：每颗灯珠内部都有红绿蓝三个芯片，可以单独调色，整条灯带能做出流水、彩虹等效果。',
      how: '三根线：VCC、GND、DIN 接 P13。数据是单向串行的，灯带的「输入」端必须接板子。',
      use: '做「氛围灯」「彩虹流水灯」「音乐律动灯」——颜色直观，学生最有成就感。',
      tip: '灯带颗数多时耗电大，要单独供电并共地；颜色顺序有 RGB 和 GRB 两种，颜色不对就换一下顺序。'
    },
    relay: {
      demo: 'switch',
      what: '数字继电器模块：用小电流的 IO 去控制大电流的通断，相当于一个「电控开关」。',
      how: 'VCC、GND、IN 接 P8。IN 给高电平（或低电平，看模块）时触点吸合。',
      use: '做「智能插座」「远程开关灯」「控制小风扇 / 小台灯」——把弱点控制延伸到 220V 电器。',
      tip: '⚠ 接 220V 有触电危险，小学课堂只用电池供电的低压负载演示；注意模块是高电平触发还是低电平触发。'
    },
    irTx: {
      demo: 'distance',
      what: '红外发射模块（DFR0095）：把按键码调制成 38kHz 红外信号发射出去。',
      how: '三根线：VCC、GND、信号接 P16（数字输出）。',
      use: '做「自制遥控器」「两块板互相通信（红外对射）」。',
      tip: '必须和接收端的编码方式一致才能被识别；有效距离一般几米，且需要大致对准。'
    },
    fan: {
      demo: 'spin',
      what: 'PWM 调速风扇：给不同的占空比就得到不同的转速，可以用来降温或做风感实验。',
      how: 'VCC、GND、PWM 信号接 P16。',
      use: '做「温控风扇」「节能风扇」「风力实验」——温度超过阈值就自动加大风速。',
      tip: '风扇启动需要克服静摩擦，占空比太低可能转不起来（会嗡嗡响但不转），一般从 30% 起步。'
    },
    robot: {
      demo: 'move',
      what: '机器人模型：把电机、循迹器、超声波、摄像头组合在一起的综合载体。',
      how: '电机接 M1/M2，循迹器与超声波按各自说明接线；在「拓展库」添加后舞台会出现机器人元素。',
      use: '做「巡线 + 避障 + 识别」的综合任务，是六年级「模拟自动驾驶」单元的主角。',
      tip: '先把每个模块单独调通，再组合；组合后最容易出问题的是供电和 IO 冲突。'
    },
    traceCar: {
      demo: 'move',
      what: '巡线小车：两路电机 + 五路循迹器 + 超声波，专门为「自动驾驶」主题准备的小车。',
      how: '电机接 M1/M2，循迹器 5 个信号脚接数字口，超声波 Trig/Echo 接 P14/P13。',
      use: '做「自动巡线」「红灯停车」「斑马线让行」——舞台上有对应赛道情景可直接演示。',
      tip: '自动巡线依赖赛道的黑线，舞台上要先布置「赛道黑线」元素；速度太快会冲出弯道。'
    },

    /* ---------- 通讯网络 ---------- */
    radio: {
      demo: 'net',
      what: '无线广播：掌控板自带的 2.4G 无线，可以按「频道」群发短消息，不需要路由器。',
      how: '板载，无需接线。两块板要设成同一个频道号才能互相收到。',
      use: '做「两块板互相点亮」「分组抢答器」「无线遥控」。',
      tip: '广播是「一对多」，同频道所有板子都会收到；消息内容建议带一个编号，方便区分发送方。'
    },
    wifi: {
      demo: 'net',
      what: 'WiFi 联网：连接教室或家里的无线网络，之后才能用 NTP 对时、MQTT、天气等云服务。',
      how: '板载。用「连接 WiFi」积木填 SSID 和密码，连上后返回「已连接」。',
      use: '做「物联网灯」「天气站」「数据上传」——所有联网项目的第一步。',
      tip: '掌控板一般只支持 2.4G，不支持 5G；学校网络常需要网页认证，这种网络连不上。'
    },
    ntp: {
      demo: 'net',
      what: 'NTP 网络对时：从互联网时间服务器取回准确时间，让板子知道自己「现在几点」。',
      how: '板载，前提是已经连上 WiFi。',
      use: '做「下课提醒器」「定时投喂」「作息打卡」——需要真实时间的场合。',
      tip: '时区要设成东八区（+8），否则会差 8 小时；对时一次就够，不用每轮循环都同步。'
    },
    mqtt: {
      demo: 'net',
      what: 'MQTT 物联网消息协议：通过「主题（topic）」发布和订阅消息，适合设备之间远程通信。',
      how: '板载，需要 WiFi + MQTT 服务器地址（如 SIoT）。',
      use: '做「远程开关灯」「多机联动」「教室环境数据上云」。',
      tip: '主题名要两端完全一致（包括斜杠）；消息是字符串，数字要转成字符串再发。'
    },
    asr: {
      demo: 'net',
      what: 'WiFi 语音识别：把录音上传到云端，返回识别出的文字，可以当指令用。',
      how: '板载麦克风 + WiFi。需要联网，识别有 1 秒左右的延迟。',
      use: '做「语音开灯」「语音问答机器人」。',
      tip: '环境噪音会明显降低识别率；指令词要短、要区分度高（「开灯」「关灯」比「把灯打开一下」好）。'
    },
    weather: {
      demo: 'net',
      what: '天气服务：联网查询指定城市的实时天气与预报。',
      how: '板载，需要 WiFi。',
      use: '做「教室天气看板」「下雨提醒」「穿衣建议」。',
      tip: '接口有调用频率限制，别放在死循环里每秒查一次；城市名要写对。'
    },
    qrcode: {
      demo: 'screen',
      what: '二维码：在 OLED 上画出二维码，手机扫一下就能跳到指定网址或看到一段文字。',
      how: '板载，无需接线，只占用屏幕。',
      use: '做「扫码看作品」「电子名片」「课堂签到入口」。',
      tip: 'OLED 只有 128×64，二维码内容越长格子越密、越难扫；尽量控制在 40 个字符以内。'
    },
    remote: {
      demo: 'distance',
      what: '红外遥控器：一块按键面板，每按一个键就发一串 38kHz 调制的红外编码。它自己不带接收能力。',
      how: '不需要接线，但必须配一个「红外接收模块」才能被掌控板读到；接收端接 P15。',
      use: '做「遥控小车」「遥控灯」「课堂抢答」——比键盘更贴近真实家电的交互方式。',
      tip: '同一款遥控器的键值固定，可以写进变量表当常量用；电池没电时距离会明显变短且时好时坏。'
    },
    mp3: {
      demo: 'sound',
      what: 'MP3 语音模块（DFRobot UART 版）：把音频文件存在 TF 卡里，用串口指令控制播放、暂停、音量和选曲。',
      how: '串口四线：VCC、GND、TX 接 P13、RX 接 P14。TF 卡里的音频要按 0001.mp3、0002.mp3 这样命名。',
      use: '做「语音提示器」「会说话的垃圾桶」「校园广播」——比蜂鸣器音质好得多，能播放人声。',
      tip: '音频格式要用模块支持的（一般是 MP3、44.1kHz）；音量别一上来就拉满，容易破音。'
    },
    rfid: {
      demo: 'distance',
      what: 'RFID 读卡模块：读出身卡 / 钥匙扣里的卡号（UID），用来做身份识别。',
      how: '一般 I2C 或串口，按模块说明接 4 根线。',
      use: '做「刷卡开门」「考勤签到」「图书借阅」。',
      tip: '卡号是全球唯一的，可以直接当「学号」用；读卡距离只有几厘米，要贴近。'
    },
    speech2: {
      demo: 'sound',
      what: '离线语音识别模块：不联网，只认预先训练好的几条固定指令。',
      how: '串口四线：VCC、GND、TX、RX。',
      use: '做「不联网的语音控制」——网络不稳的教室也能演示。',
      tip: '只能识别烧录进模块的那几条词，识别率和说话距离、口音关系很大。'
    }
  };

  /* ============================================================
   * 二、「视频」第 3 幕的动画
   *   每种 demo 一段 320×180 的 SVG，靠 CSS 动画循环播放。
   *   全部是纯 CSS 关键帧，没有任何外部资源。
   * ============================================================ */
  var NS = 'http://www.w3.org/2000/svg';
  function demoSvg(kind) {
    var head = '<svg viewBox="0 0 320 180" class="dv-svg">';
    switch (kind) {
      case 'light':
        return head +
          '<circle class="dv-glow" cx="160" cy="90" r="52" fill="#ffd24a" opacity=".22"/>' +
          '<circle cx="160" cy="90" r="34" fill="#e8c24a" stroke="#a8862a" stroke-width="2"/>' +
          '<circle class="dv-bulb" cx="160" cy="90" r="22" fill="#fff3b0"/>' +
          '<g class="dv-rays" stroke="#ffd24a" stroke-width="4" stroke-linecap="round">' +
          '<path d="M160 26 v-12"/><path d="M160 154 v12"/>' +
          '<path d="M96 90 h-12"/><path d="M224 90 h12"/>' +
          '<path d="M115 45 l-9-9"/><path d="M205 135 l9 9"/>' +
          '<path d="M205 45 l9-9"/><path d="M115 135 l-9 9"/></g>' +
          '</svg>';
      case 'rgb':
        return head +
          '<rect x="52" y="40" width="216" height="100" rx="10" fill="#1a1d21"/>' +
          ['#ff4d4d', '#ffd24a', '#4ade80', '#4d9dff', '#c86ad0'].map(function (c, i) {
            return '<rect class="dv-led" style="animation-delay:' + (i * .18) + 's" ' +
              'x="' + (68 + i * 40) + '" y="70" width="28" height="40" rx="6" fill="' + c + '"/>';
          }).join('') +
          '</svg>';
      case 'spin':
        return head +
          '<circle cx="160" cy="90" r="66" fill="none" stroke="#a6b2c0" stroke-width="3"/>' +
          '<g class="dv-spin" style="transform-origin:160px 90px">' +
          [0, 120, 240].map(function (a) {
            return '<path d="M160,90 C160,52 186,38 196,56 C202,70 180,82 160,90Z" ' +
              'fill="#5fb3d4" transform="rotate(' + a + ' 160 90)"/>';
          }).join('') + '</g>' +
          '<circle cx="160" cy="90" r="12" fill="#3a414c"/>' +
          '</svg>';
      case 'move':
        return head +
          '<rect x="90" y="86" width="140" height="10" rx="5" fill="#dfe4ea"/>' +
          '<g class="dv-arm" style="transform-origin:160px 91px">' +
          '<rect x="156" y="34" width="8" height="58" rx="4" fill="#e8edf2"/>' +
          '<circle cx="160" cy="40" r="6" fill="#9aa6b0"/></g>' +
          '<circle cx="160" cy="91" r="9" fill="#5a636e"/>' +
          '<text class="dv-tick" x="160" y="140" text-anchor="middle" font-size="16" ' +
          'font-family="monospace" fill="#8a939e">0°</text>' +
          '</svg>';
      case 'distance':
        return head +
          '<rect x="52" y="70" width="46" height="40" rx="6" fill="#1f3a5c"/>' +
          '<circle cx="75" cy="90" r="11" fill="#0a0d10"/>' +
          '<circle cx="75" cy="90" r="5" fill="#5a6672"/>' +
          '<g class="dv-wave" stroke="#4d9dff" stroke-width="3" fill="none">' +
          '<path d="M100 78 q18 12 0 24" opacity=".9"/>' +
          '<path d="M114 70 q28 20 0 40" opacity=".7"/>' +
          '<path d="M128 62 q38 28 0 56" opacity=".5"/></g>' +
          '<rect x="214" y="52" width="40" height="76" rx="6" fill="#c9d1d9"/>' +
          '<text class="dv-num" x="160" y="156" text-anchor="middle" font-size="17" ' +
          'font-family="monospace" fill="#3a6ea5">30 cm</text>' +
          '</svg>';
      case 'switch':
        return head +
          '<rect x="72" y="56" width="176" height="72" rx="10" fill="#1f3a5c"/>' +
          '<circle class="dv-swled" cx="110" cy="76" r="8" fill="#3a414c"/>' +
          '<path class="dv-lever" style="transform-origin:160px 110px" ' +
          'd="M160,110 L196,84" stroke="#e8c24a" stroke-width="7" stroke-linecap="round"/>' +
          '<circle cx="160" cy="110" r="7" fill="#c9d1d9"/>' +
          '<text class="dv-tick" x="230" y="116" text-anchor="middle" font-size="14" ' +
          'font-family="monospace" fill="#7fd4c8">OFF</text>' +
          '</svg>';
      case 'sound':
        return head +
          '<rect x="120" y="52" width="80" height="76" rx="8" fill="#1f3a5c"/>' +
          '<circle cx="160" cy="90" r="24" fill="#0a0d10"/>' +
          '<circle cx="160" cy="90" r="10" fill="#5a6672"/>' +
          '<g class="dv-wave" stroke="#ffd24a" stroke-width="3" fill="none">' +
          '<path d="M206 74 q16 16 0 32" opacity=".9"/>' +
          '<path d="M222 62 q26 26 0 56" opacity=".7"/>' +
          '<path d="M238 50 q36 38 0 80" opacity=".5"/></g>' +
          '</svg>';
      case 'net':
        return head +
          '<circle cx="70" cy="90" r="26" fill="#1f3a5c"/>' +
          '<text x="70" y="96" text-anchor="middle" font-size="12" fill="#7fd4c8" ' +
          'font-family="monospace">ZK</text>' +
          '<circle cx="250" cy="90" r="26" fill="#2b4f78"/>' +
          '<text x="250" y="96" text-anchor="middle" font-size="11" fill="#9fd8e8" ' +
          'font-family="monospace">NET</text>' +
          '<path d="M100 90 h120" stroke="#9aa3af" stroke-width="2" stroke-dasharray="6 6"/>' +
          '<circle class="dv-pkt" cx="100" cy="90" r="7" fill="#4ade80"/>' +
          '<text class="dv-tick" x="160" y="152" text-anchor="middle" font-size="13" ' +
          'font-family="monospace" fill="#8a939e">发送中…</text>' +
          '</svg>';
      case 'screen':
        return head +
          '<rect x="86" y="44" width="148" height="92" rx="8" fill="#0b1410" ' +
          'stroke="#2a3a30" stroke-width="2"/>' +
          [0, 1, 2].map(function (i) {
            return '<rect class="dv-line" style="animation-delay:' + (i * .45) + 's" ' +
              'x="100" y="' + (62 + i * 22) + '" width="' + (110 - i * 22) + '" height="8" rx="4" ' +
              'fill="#7fe3c4"/>';
          }).join('') +
          '<text class="dv-tick" x="160" y="158" text-anchor="middle" font-size="13" ' +
          'font-family="monospace" fill="#8a939e">128 × 64</text>' +
          '</svg>';
      default: /* sense */
        return head +
          '<rect x="60" y="44" width="200" height="92" rx="8" fill="#f5f7fa" ' +
          'stroke="#dfe4ea" stroke-width="2"/>' +
          '<polyline class="dv-ecg" points="72,110 96,110 106,72 118,124 130,96 142,110 172,110 ' +
          '182,70 194,126 206,98 218,110 248,110" fill="none" stroke="#3f88e8" ' +
          'stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>' +
          '<text class="dv-num" x="160" y="158" text-anchor="middle" font-size="17" ' +
          'font-family="monospace" fill="#3a6ea5">26.0</text>' +
          '</svg>';
    }
  }

  /* ============================================================
   * 三、悬停详情浮层
   * ============================================================ */
  var tip = null;
  function ensureTip() {
    if (tip) return tip;
    tip = document.createElement('div');
    tip.id = 'ext-tip';
    tip.className = 'ext-tip hidden';
    document.body.appendChild(tip);
    return tip;
  }

  function introOf(id) {
    var base = ZKB.baseOf ? ZKB.baseOf(id) : id;
    return INTRO[base] || null;
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  /* 在卡片右侧/左侧弹出详情（自动避让窗口边界） */
  function showTip(id, cardEl) {
    var d = ZKB.deviceMeta(id);
    var it = introOf(id);
    if (!d || !it) return;
    var t = ensureTip();
    var catCN = { main: '主控', sensor: '传感器', actuator: '执行器', network: '通讯网络', other: '其他' };
    var h = '';
    h += '<div class="et-head">' + ZKB.deviceIcon(id, 34) +
      '<div><div class="et-name">' + esc(d.name) + '</div>' +
      '<div class="et-meta">' + (catCN[d.cat] || '设备') +
      ' · 接口 ' + (d.pins && d.pins.length ? esc(d.pins.join(' / ')) : '板载') + '</div></div></div>';
    h += '<div class="et-sec"><b>这是什么</b><p>' + esc(it.what) + '</p></div>';
    h += '<div class="et-sec"><b>怎么接线 / 怎么用</b><p>' + esc(it.how) + '</p></div>';
    h += '<div class="et-sec"><b>课堂上能做什么</b><p>' + esc(it.use) + '</p></div>';
    h += '<div class="et-sec et-tip"><b>容易踩的坑</b><p>' + esc(it.tip) + '</p></div>';
    h += '<div class="et-foot">点卡片可添加设备 · 点右上角 ▶ 看视频介绍</div>';
    t.innerHTML = h;
    t.classList.remove('hidden');

    /* 定位：默认放卡片右侧；若超出「拓展库面板」的右边界（而不是整个窗口），
       就翻到卡片左侧 —— 避免浮层飘到弹窗外面去。 */
    var r = cardEl.getBoundingClientRect();
    var panel = cardEl.closest ? cardEl.closest('#ext-lib') : null;
    var limit = panel ? panel.getBoundingClientRect().right : window.innerWidth;
    var tw = 330, th = t.offsetHeight || 320;
    var gap = 14;
    var x = r.right + gap;
    if (x + tw > limit - 8) x = r.left - tw - gap;
    if (x < 12) x = 12;
    if (x + tw > window.innerWidth - 12) x = window.innerWidth - tw - 12;
    var y = Math.min(Math.max(12, r.top - 8), Math.max(12, window.innerHeight - th - 12));
    t.style.left = Math.round(x) + 'px';
    t.style.top = Math.round(y) + 'px';
  }

  function hideTip() {
    if (tip) tip.classList.add('hidden');
  }

  /* ============================================================
   * 四、「视频介绍」播放器
   *   4 幕分镜自动轮播 + 字幕 + 进度点 + 暂停/播放
   * ============================================================ */
  var vstate = {
    mask: null, id: '', scene: 0, timer: 0, playing: true,
    scenes: [], capEl: null, stageEl: null, dotsEl: null
  };
  var SCENE_MS = 2800;

  function ensurePlayer() {
    if (vstate.mask) return vstate.mask;
    var m = document.createElement('div');
    m.id = 'dv-mask';
    m.className = 'hidden';
    m.innerHTML =
      '<div id="dv-box" role="dialog" aria-label="设备视频介绍">' +
      '<div class="dv-head">' +
      '<div class="dv-title"><span id="dv-name">设备</span>' +
      '<span class="dv-badge">视频介绍</span></div>' +
      '<button class="dv-x" id="dv-close" title="关闭">×</button>' +
      '</div>' +
      '<div class="dv-stage" id="dv-stage"></div>' +
      '<div class="dv-cap" id="dv-cap"></div>' +
      '<div class="dv-bar">' +
      '<button class="dv-play" id="dv-play" title="暂停 / 播放">⏸</button>' +
      '<div class="dv-dots" id="dv-dots"></div>' +
      '<span class="dv-hint">共 4 幕 · 自动轮播</span>' +
      '</div></div>';
    document.body.appendChild(m);

    m.addEventListener('click', function (e) {
      if (e.target === m) closeVideo();
    });
    m.querySelector('#dv-close').addEventListener('click', closeVideo);
    m.querySelector('#dv-play').addEventListener('click', function () {
      vstate.playing = !vstate.playing;
      this.textContent = vstate.playing ? '⏸' : '▶';
      if (vstate.playing) scheduleNext(); else clearTimeout(vstate.timer);
    });
    vstate.mask = m;
    vstate.stageEl = m.querySelector('#dv-stage');
    vstate.capEl = m.querySelector('#dv-cap');
    vstate.dotsEl = m.querySelector('#dv-dots');
    return m;
  }

  /* 组装 4 幕 */
  function buildScenes(id) {
    var d = ZKB.deviceMeta(id);
    var it = introOf(id);
    if (!d || !it) return [];
    var icon = ZKB.deviceIcon(id, 120);
    var catCN = { main: '主控', sensor: '传感器', actuator: '执行器', network: '通讯网络', other: '其他' };
    return [
      {
        cap: '① ' + d.name + '：' + it.what,
        html: '<div class="dv-hero"><div class="dv-hero-icon">' + icon + '</div>' +
          '<div class="dv-hero-name">' + esc(d.name) + '</div>' +
          '<div class="dv-hero-cat">' + (catCN[d.cat] || '设备') + '</div></div>'
      },
      {
        cap: '② 接线：' + it.how,
        html: '<div class="dv-wire">' +
          '<div class="dv-wire-board"><span>掌控板</span></div>' +
          '<div class="dv-wire-line"><i></i></div>' +
          '<div class="dv-wire-dev">' + ZKB.deviceIcon(id, 64) +
          '<span>' + esc((d.pins && d.pins.join(' / ')) || '板载') + '</span></div>' +
          '</div>'
      },
      {
        cap: '③ 工作原理：' + (it.what.split('。')[0] || '') + '。',
        html: '<div class="dv-demo">' + demoSvg(it.demo) + '</div>'
      },
      {
        cap: '④ 课堂用法：' + it.use + '　⚠ ' + it.tip,
        html: '<div class="dv-use">' +
          '<div class="dv-use-t">课堂用法</div>' +
          '<p>' + esc(it.use) + '</p>' +
          '<div class="dv-use-t warn">容易踩的坑</div>' +
          '<p>' + esc(it.tip) + '</p></div>'
      }
    ];
  }

  function paintScene() {
    var sc = vstate.scenes[vstate.scene];
    if (!sc) return;
    vstate.stageEl.innerHTML = sc.html;
    vstate.capEl.textContent = sc.cap;
    /* 进度点 */
    var dots = vstate.dotsEl.children;
    for (var i = 0; i < dots.length; i++) {
      dots[i].classList.toggle('on', i === vstate.scene);
    }
    /* 重放入场动画 */
    vstate.stageEl.classList.remove('dv-in');
    void vstate.stageEl.offsetWidth;
    vstate.stageEl.classList.add('dv-in');
  }

  function scheduleNext() {
    clearTimeout(vstate.timer);
    if (!vstate.playing) return;
    vstate.timer = setTimeout(function () {
      vstate.scene = (vstate.scene + 1) % vstate.scenes.length;
      paintScene();
      scheduleNext();
    }, SCENE_MS);
  }

  function openVideo(id) {
    var m = ensurePlayer();
    var scenes = buildScenes(id);
    if (!scenes.length) {
      if (ZKB.toast) ZKB.toast('该设备暂无详细介绍');
      return;
    }
    hideTip();
    vstate.id = id;
    vstate.scenes = scenes;
    vstate.scene = 0;
    vstate.playing = true;
    m.querySelector('#dv-play').textContent = '⏸';
    m.querySelector('#dv-name').textContent = ZKB.deviceMeta(id).name;
    vstate.dotsEl.innerHTML = scenes.map(function () { return '<i></i>'; }).join('');
    m.classList.remove('hidden');
    paintScene();
    scheduleNext();
  }

  function closeVideo() {
    clearTimeout(vstate.timer);
    if (vstate.mask) vstate.mask.classList.add('hidden');
  }

  ZKB.DeviceIntro = {
    of: introOf,
    show: showTip,
    hide: hideTip,
    openVideo: openVideo,
    closeVideo: closeVideo,
    /* 供测试使用 */
    _intro: INTRO,
    _demoSvg: demoSvg
  };

  /* 滚轮 / 窗口变化时收起浮层，避免浮层「飘」在原位 */
  window.addEventListener('scroll', hideTip, true);
  window.addEventListener('resize', hideTip);
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { closeVideo(); hideTip(); }
  });

})(window);
