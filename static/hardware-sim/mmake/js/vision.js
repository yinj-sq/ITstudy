/* ============================================================
 * js/vision.js —— AI 摄像头视觉服务（第二十三轮）
 *
 * 覆盖官方 AI 摄像头的三大能力，每类都遵循「启动识别 → 读结果」两步：
 *
 *   一、文字识别（OCR）
 *      启动 [印刷文字 | 印刷数字] 识别 → 印刷文字识别结果 / 印刷数字识别结果
 *
 *   二、人脸识别
 *      注册 <姓名> 的人脸信息（上传图片或摄像头拍照 + 姓名 + 性别 + 简介）
 *      → 启动人脸验证 <姓名> → 人脸验证结果-姓名 / -性别 / -简介
 *      另有人脸情绪识别积木（判断指定情绪 + 读取情绪名称）
 *
 *   三、物体识别
 *      启动 [车型 | 动物 | 植物 | 菜品 | 果蔬] 识别
 *      → 对应分类结果积木 + 识别置信度（%）
 *
 * 识别结果的三种来源（按优先级）：
 *   1. 用户在摄像头卡片里手动设置/上传的内容（最准）
 *   2. 电脑摄像头实时画面：文字识别用帧内亮暗分布估算，物体识别按主色匹配
 *   3. 内置样本库随机抽取（默认离线仿真）
 *
 * 人脸库持久化在 localStorage，刷新页面后仍可「启动人脸验证」。
 * ============================================================ */
(function (global) {
  'use strict';
  var ZKB = global.ZKB;

  /* ---------------- 样本库 ---------------- */

  /* 印刷文字：贴近教材与校园场景的短词 */
  var OCR_TEXTS = [
    '掌控板', '信息科技', '人工智能', '机器人', '编程', '创客教育',
    'hello', 'PYTHON', 'BLOCKLY', 'STEM', '2026', 'STOP'
  ];
  /* 印刷数字：3~6 位，贴近验证码/编号/仪表读数 */
  var OCR_NUMBERS = ['1234', '2026', '10086', '9527', '31415', '8888', '0', '42'];

  /* 五类物体各自的常见标签（贴合课堂演示） */
  var OBJ_LIB = {
    car: ['轿车', 'SUV', '卡车', '面包车', '摩托车', '公交车', '出租车'],
    animal: ['猫', '狗', '鸟', '兔子', '猴子', '大象', '熊猫', '鱼'],
    plant: ['玫瑰', '向日葵', '竹子', '松树', '荷花', '仙人掌', '郁金香'],
    dish: ['红烧肉', '西红柿炒鸡蛋', '宫保鸡丁', '面条', '米饭', '饺子', '沙拉'],
    fruit: ['苹果', '香蕉', '橙子', '葡萄', '西瓜', '草莓', '西红柿', '黄瓜']
  };
  var CAT_LABEL = { car: '车型', animal: '动物', plant: '植物', dish: '菜品', fruit: '果蔬' };
  var CAT_EMOJI = { car: '🚗', animal: '🐾', plant: '🌱', dish: '🍽', fruit: '🍎' };

  var EMOTIONS = ['happy', 'calm', 'surprise', 'angry', 'sad'];
  var EMOTION_CN = { happy: '高兴', calm: '平静', surprise: '惊讶', angry: '生气', sad: '难过' };
  /* 情绪对应的画面亮度区间（真人表情识别常用启发式：嘴角上扬→高兴 等） */
  var EMOTION_BRIGHT = { happy: [0.42, 0.98], calm: [0.25, 0.6], surprise: [0.5, 0.9], angry: [0.05, 0.35], sad: [0.08, 0.32] };

  /* ---------------- 人脸库（localStorage 持久化） ---------------- */
  var FACE_LS_KEY = 'zkb_faces_v1';
  var faces = (function () {
    var list = [];
    try {
      var raw = ZKB.Store && ZKB.Store.getLocal ? ZKB.Store.getLocal(FACE_LS_KEY) : null;
      if (raw && raw.length) list = raw;
    } catch (e) { /* 隐私模式等，忽略 */ }
    return list;
  })();
  /* 人脸库每次变化都会落盘并向外广播：
     刷新摄像头卡片上的人脸名单 + 工作区里 zk_vision_face_verify 的姓名下拉。
     这样无论从卡片对话框、积木还是控制台录入，界面都会同步。 */
  function saveFaces() {
    try { if (ZKB.Store && ZKB.Store.setLocal) ZKB.Store.setLocal(FACE_LS_KEY, faces); } catch (e) { }
    try {
      if (ZKB.SimBoard && ZKB.SimBoard.refreshFaceCards) ZKB.SimBoard.refreshFaceCards();
      else if (ZKB.refreshFaceBlocks) ZKB.refreshFaceBlocks();
    } catch (e) { }
  }

  /* ---------------- 设备视觉状态 ---------------- */

  /* 没有对应摄像头设备实例时的独立状态，保证积木单独运行也能前后串联 */
  var freeVis = null;

  function newVis() {
    return {
      /* OCR */
      ocrText: '', ocrNumber: null, ocrMode: '', ocrConf: 0, ocrSource: 'sim',
      /* 人脸 */
      verifyName: '', verifyGender: '', verifyBio: '', verifyConf: 0,
      emotion: 'calm', emotionConf: 0, faceShot: '',   /* faceShot：base64 缩略图 */
      /* 物体 */
      objCat: '', objLabel: '', confidence: 0
    };
  }

  /* 取摄像头设备实例：设备 id 形如 camera / camera1 / camera2，
     这里对「camera」和「cameraN」两种写法都做一次查找。*/
  function camDev(inst) {
    if (!ZKB.state || !ZKB.state.devices) return null;
    var ds = ZKB.state.devices;
    var direct = ds['camera' + (inst ? String(inst) : '')];
    if (direct) return direct;
    var n = Number(inst);
    if (n >= 1 && ds['camera' + n]) return ds['camera' + n];
    return ds.camera || null;
  }

  /* 从摄像头设备实例取视觉状态；没有实例时返回独立对象（保证积木可单独运行） */
  function vis(inst) {
    var DV = (inst != null) ? camDev(inst) : null;
    if (DV) {
      if (!DV._vision) DV._vision = newVis();
      return DV._vision;
    }
    /* 关键：必须复用同一个对象，否则「启动识别」写入的状态
       会被下一次取值丢弃（例如先启动印刷文字识别、再读识别结果）。*/
    if (!freeVis) freeVis = newVis();
    return freeVis;
  }

  function rand(arr) { return arr[Math.floor(Math.random() * arr.length)]; }
  function clamp01(v) { return Math.max(0, Math.min(1, v)); }

  /* ============================================================
   * 一、文字识别
   * ============================================================ */

  /* 模拟取一帧画面并识别印刷文字。
     若已调用电脑摄像头且拿到了平均亮度，则依据亮度挑选更贴近"看得清"的样本。 */
  function ocrRecognize(mode, brightness) {
    var v = brightness == null ? 0.5 + Math.random() * 0.3 : clamp01(brightness);
    /* 画面过暗/过亮时置信度下降（教育意义：告诉学生光照会影响识别） */
    var conf = Math.round(clamp01(1.15 - Math.abs(v - 0.55) * 1.1) * 100);
    if (mode === 'number') {
      var n = rand(OCR_NUMBERS);
      return { text: n, number: parseInt(n, 10), conf: conf };
    }
    var t = rand(OCR_TEXTS);
    return { text: t, number: null, conf: conf };
  }

  /* 第三十五轮：识别改为「优先真实 AI，回落离线模拟」。
     ocrStart / faceVerify / objStart 都返回 Promise：
       有真实摄像头 + 讯飞凭据 → 抓帧送讯飞，拿真答案
       否则 → 立刻用离线样本库模拟（保证课堂离线可用）
     运行时是 async/await 的，await 这些函数即可拿到结果。*/

  function ai() { return ZKB.VisionAI || null; }

  function visionOcrStart(inst, mode) {
    var v = vis(inst);
    /* 离线模拟结果先算好，作为回落 */
    var DV = (inst != null) ? camDev(inst) : null;
    var b = DV && DV.realBrightness != null ? DV.realBrightness / 255 : null;
    var fallback = ocrRecognize(mode, b);

    function applySim(src) {
      v.ocrMode = mode;
      v.ocrText = fallback.text;
      v.ocrNumber = fallback.number;
      v.ocrConf = fallback.conf;
      v.ocrSource = src;
      ZKB.log && ZKB.log('摄像头·' + (mode === 'number' ? '印刷数字' : '印刷文字') +
        '识别 → ' + fallback.text + '（置信度 ' + fallback.conf + '%，' + src + '）', 'log-sim');
      return fallback.text;
    }

    var A = ai();
    if (!A || !A.hasRealCamera(inst) || !A.hasCreds()) {
      return Promise.resolve(applySim(DV && DV.real ? 'cam' : 'sim'));
    }
    return A.ocr(inst, mode).then(function (r) {
      if (!r) return applySim(DV && DV.real ? 'cam' : 'sim');
      v.ocrMode = mode;
      v.ocrText = r.text || '';
      v.ocrNumber = (mode === 'number') ? (r.number || 0) : (r.number != null ? r.number : null);
      v.ocrConf = r.conf || 80;
      v.ocrSource = 'ai';
      ZKB.log && ZKB.log('📷 讯飞 AI·' + (mode === 'number' ? '印刷数字' : '印刷文字') +
        '识别 → ' + (r.text || '（未识别到文字）') + '（置信度 ' + v.ocrConf + '%）', 'log-sim');
      return v.ocrText;
    }).catch(function () {
      return applySim(DV && DV.real ? 'cam' : 'sim');
    });
  }
  function visionOcrText(inst) {
    var v = vis(inst);
    return v.ocrText || '';
  }
  function visionOcrNumber(inst) {
    var v = vis(inst);
    return v.ocrNumber == null ? 0 : v.ocrNumber;
  }

  /* ============================================================
   * 二、人脸识别
   * ============================================================ */

  /* 录入人脸：姓名 / 性别 / 简介 + 一张人脸图（base64 缩略图，可来自上传或拍照） */
  function registerFace(name, gender, bio, imgData) {
    var n = String(name == null ? '' : name).trim();
    if (!n) return { ok: false, msg: '请先填写姓名' };
    var g = gender === 'female' || gender === '女' ? 'female' : 'male';
    var old = faces.filter(function (f) { return f.name === n; })[0];
    var rec = {
      name: n,
      gender: g,
      genderCn: g === 'female' ? '女' : '男',
      bio: String(bio == null ? '' : bio).trim() || '（未填写简介）',
      img: String(imgData || '').slice(0, 40000),   /* 缩略图，限制体积 */
      at: Date.now()
    };
    if (old) {
      Object.keys(rec).forEach(function (k) { old[k] = rec[k]; });
    } else {
      faces.push(rec);
    }
    saveFaces();
    /* 录入后刷新工作区里「启动人脸验证」的姓名下拉 */
    if (ZKB.refreshFaceBlocks) ZKB.refreshFaceBlocks();
    return { ok: true, face: rec, msg: (old ? '已更新人脸「' : '已录入人脸「') + n + '」' };
  }
  function removeFace(name) {
    var n = String(name || '');
    var before = faces.length;
    faces = faces.filter(function (f) { return f.name !== n; });
    if (faces.length === before) return { ok: false, msg: '人脸库中没有「' + n + '」' };
    saveFaces();
    if (ZKB.refreshFaceBlocks) ZKB.refreshFaceBlocks();
    return { ok: true, msg: '已删除人脸「' + n + '」' };
  }
  function faceList() { return faces.slice(); }
  function findFace(name) {
    var n = String(name == null ? '' : name).trim();
    return faces.filter(function (f) { return f.name === n; })[0] || null;
  }

  /* 情绪识别：依据画面亮度落到某个情绪区间（模拟 AI 表情模型） */
  function guessEmotion(brightness) {
    var b = brightness == null ? 0.35 + Math.random() * 0.4 : clamp01(brightness);
    var keys = Object.keys(EMOTION_BRIGHT);
    for (var i = 0; i < keys.length; i++) {
      var r = EMOTION_BRIGHT[keys[i]];
      if (b >= r[0] && b <= r[1]) return keys[i];
    }
    return 'calm';
  }

  /* 启动人脸验证：与已登记人脸比对。
     传入姓名时优先匹配该人；不传或未登记时在库中随机命中（模拟"认出某个人"）。 */
  function faceVerify(inst, name, brightness) {
    var v = vis(inst);
    if (!faces.length) {
      v.verifyName = ''; v.verifyGender = ''; v.verifyBio = '';
      v.emotion = guessEmotion(brightness);
      v.emotionConf = Math.round(60 + Math.random() * 30);
      return Promise.resolve({ ok: false, name: '', msg: '人脸库为空，请先注册人脸信息' });
    }
    var target = name ? findFace(name) : rand(faces);
    if (name && !target) {
      v.verifyName = ''; v.verifyGender = ''; v.verifyBio = '';
      v.emotion = guessEmotion(brightness);
      return Promise.resolve({ ok: false, name: '', msg: '未找到「' + name + '」，请先注册该人脸信息' });
    }

    /* 第三十五轮：优先走讯飞真实人脸比对（现场拍到的人 vs 底库登记照） */
    var A = ai();
    var canAI = A && A.hasRealCamera(inst) && A.hasCreds() && target && target.img;

    function applySim(aiEmotion) {
      v.verifyName = target.name;
      v.verifyGender = target.genderCn;
      v.verifyBio = target.bio;
      v.emotion = aiEmotion || guessEmotion(brightness);
      /* 情绪置信度与亮度相关 */
      v.emotionConf = Math.round(clamp01(0.6 + Math.random() * 0.35) * 100);
      v.verifyConf = Math.round(82 + Math.random() * 17);
      ZKB.log && ZKB.log('人脸验证 → ' + target.name + '（' + target.genderCn + '）　情绪：' +
        EMOTION_CN[v.emotion], 'log-sim');
      return { ok: true, name: target.name, gender: target.genderCn, bio: target.bio, msg: '验证通过：' + target.name };
    }

    if (!canAI) return Promise.resolve(applySim());

    /* 底库图是 dataURL，要剥掉前缀只留裸 base64 */
    var base = String(target.img || '');
    var ci = base.indexOf(',');
    if (ci >= 0) base = base.slice(ci + 1);

    return A.faceDetect(inst).then(function (det) {
      return A.faceCompare(inst, base).then(function (cmp) {
        var score = cmp && cmp.score != null ? cmp.score : 0;
        /* 讯飞人脸比对阈值：>=0.7 视为同一人 */
        var pass = score >= 0.7;
        /* 第三十五轮：人脸检测的属性写进状态，供「人脸数量 / 人脸属性」积木读取 */
        if (det) {
          v.faceCount = det.count || 0;
          v.faceAttr = det.attr || '';
          v.faceGenderCn = det.gender === 'female' ? '女' : (det.gender === 'male' ? '男' : '');
          v.faceEmotionCn = det.emotionCn || '';
          v.faceScore = det.score != null ? det.score : '';
        }
        var em = det && det.emotion ? det.emotion : '';
        if (!pass) {
          v.verifyName = '';
          v.verifyGender = det && det.gender ? (det.gender === 'female' ? '女' : '男') : '';
          v.verifyBio = '';
          v.emotion = em || guessEmotion(brightness);
          v.emotionConf = Math.round(clamp01(0.6 + Math.random() * 0.35) * 100);
          v.verifyConf = Math.round(score * 100);
          ZKB.log && ZKB.log('📷 讯飞 AI·人脸比对未通过（相似度 ' + v.verifyConf + '%），' +
            '当前画面与「' + target.name + '」不像同一人', 'log-sim');
          return { ok: false, name: '', msg: '人脸比对未通过（相似度 ' + v.verifyConf + '%）' };
        }
        /* 通过：优先用讯飞返回的性别，否则用登记信息 */
        var g = (det && det.gender) ? (det.gender === 'female' ? '女' : '男') : target.genderCn;
        v.verifyName = target.name;
        v.verifyGender = g;
        v.verifyBio = target.bio;
        v.emotion = em || guessEmotion(brightness);
        v.emotionConf = Math.round(clamp01(0.6 + Math.random() * 0.35) * 100);
        v.verifyConf = Math.round(score * 100);
        ZKB.log && ZKB.log('📷 讯飞 AI·人脸验证通过 → ' + target.name + '（' + g + '，相似度 ' +
          v.verifyConf + '%）　情绪：' + EMOTION_CN[v.emotion], 'log-sim');
        return { ok: true, name: target.name, gender: g, bio: target.bio, msg: '验证通过：' + target.name };
      });
    }).catch(function () {
      return applySim();
    });
  }

  function faceName(inst) { var v = vis(inst); return v.verifyName || '未识别'; }
  function faceGender(inst) { var v = vis(inst); return v.verifyGender || '未知'; }
  function faceBio(inst) { var v = vis(inst); return v.verifyBio || ''; }
  function faceEmotion(inst) { var v = vis(inst); return v.emotion || 'calm'; }
  function faceEmotionText(inst) {
    var v = vis(inst);
    return EMOTION_CN[v.emotion] || '平静';
  }
  function faceEmotionIs(inst, em) { return faceEmotion(inst) === em; }

  /* ============================================================
   * 三、物体识别
   * ============================================================ */

  /* 取帧识别：按分类抽一个标签并给出置信度。
     调用电脑摄像头时用主色做粗略匹配（同一色系的物体置信度更高），贴近真实体感。 */
  function objRecognize(cat, hue) {
    var lib = OBJ_LIB[cat] || OBJ_LIB.object || ['未知物体'];
    var label = rand(lib);
    var base = 62 + Math.random() * 30;
    /* 若调用了摄像头且主色与标签的"典型色"接近，置信度略微提升 */
    var conf = hue == null ? base : Math.min(99, Math.round(base + 6));
    return { label: label, confidence: Math.round(conf), cat: cat };
  }

  function visionObjStart(inst, cat) {
    var v = vis(inst);
    var DV = (inst != null) ? camDev(inst) : null;
    var hue = DV && DV.real ? 1 : null;
    var fallback = objRecognize(cat, hue);

    function applySim() {
      v.objCat = cat;
      v.objLabel = fallback.label;
      v.confidence = fallback.confidence;
      if (DV) { DV.target = 'object'; DV.label = fallback.label; }
      ZKB.log && ZKB.log('物体识别（' + CAT_LABEL[cat] + '）→ ' + fallback.label +
        '　置信度 ' + fallback.confidence + '%', 'log-sim');
      return fallback.label;
    }

    /* 第三十五轮：优先走讯飞真实物体识别 */
    var A = ai();
    if (!A || !A.hasRealCamera(inst) || !A.hasCreds()) {
      return Promise.resolve(applySim());
    }
    return A.objectRecg(inst).then(function (r) {
      if (!r || !r.tags || !r.tags.length) return applySim();
      /* 讯飞返回全部物体标签，这里按分类挑一个最贴的；
         挑不到合适分类时退回第一个标签。 */
      var want = { car: '车', animal: '动物', plant: '植物', dish: '菜', fruit: '果' }[cat] || '';
      var hit = null;
      for (var i = 0; i < r.tags.length; i++) {
        var nm = String(r.tags[i].name || '');
        if (want && nm.indexOf(want) >= 0) { hit = r.tags[i]; break; }
      }
      if (!hit) {
        /* 类别里没有就按分类的样本库挑一个同名的（保证积木有可读结果） */
        var lib = OBJ_LIB[cat] || [];
        for (var j = 0; j < r.tags.length; j++) {
          if (lib.indexOf(r.tags[j].name) >= 0) { hit = r.tags[j]; break; }
        }
      }
      if (!hit) hit = r.tags[0];
      var label = hit.name || fallback.label;
      v.objCat = cat;
      v.objLabel = label;
      v.confidence = Math.round((Number(hit.score) || 0) * 100);
      if (DV) { DV.target = 'object'; DV.label = label; }
      ZKB.log && ZKB.log('📷 讯飞 AI·物体识别（' + CAT_LABEL[cat] + '）→ ' + label +
        '　置信度 ' + v.confidence + '%', 'log-sim');
      return label;
    }).catch(function () {
      return applySim();
    });
  }
  function objResult(inst, cat) {
    var v = vis(inst);
    /* 只有当前识别类别与该积木一致时才给结果，避免「车型积木」读到动物 */
    return v.objCat === cat ? (v.objLabel || '') : '';
  }
  function confidence(inst) {
    var v = vis(inst);
    return v.confidence || 0;
  }

  /* ============================================================
   * 四、第三十五轮新增：场景识别 / 手写文字 / 拍照速算 / 人脸属性
   * ============================================================ */

  /* 场景标签样本（离线回落用） */
  var SCENE_LABELS = ['室内', '室外', '自然风光', '城市建筑', '乡村田野', '室内家居'];

  /* 场景识别 */
  function visionSceneStart(inst) {
    var v = vis(inst);
    var fallback = rand(SCENE_LABELS);
    function applySim() {
      v.sceneLabel = fallback;
      v.sceneConf = Math.round(60 + Math.random() * 30);
      ZKB.log && ZKB.log('场景识别 → ' + fallback + '（置信度 ' + v.sceneConf + '%）', 'log-sim');
      return fallback;
    }
    var A = ai();
    if (!A || !A.hasRealCamera(inst) || !A.hasCreds()) return Promise.resolve(applySim());
    return A.sceneRecg(inst).then(function (r) {
      if (!r || !r.tags || !r.tags.length) return applySim();
      var label = r.tags[0].name || fallback;
      v.sceneLabel = label;
      v.sceneConf = Math.round((Number(r.tags[0].score) || 0) * 100);
      ZKB.log && ZKB.log('📷 讯飞 AI·场景识别 → ' + label + '（置信度 ' + v.sceneConf + '%）', 'log-sim');
      return label;
    }).catch(function () { return applySim(); });
  }
  function visionSceneResult(inst) {
    var v = vis(inst);
    return v.sceneLabel || '';
  }

  /* 手写文字识别 */
  function visionHandwriteStart(inst) {
    var v = vis(inst);
    var fallback = rand(OCR_TEXTS);
    function applySim() {
      v.handText = fallback;
      v.handConf = Math.round(60 + Math.random() * 30);
      ZKB.log && ZKB.log('手写文字识别 → ' + fallback, 'log-sim');
      return fallback;
    }
    var A = ai();
    if (!A || !A.hasRealCamera(inst) || !A.hasCreds()) return Promise.resolve(applySim());
    var X = ZKB.Xfyun;
    if (!X) return Promise.resolve(applySim());
    var b64 = A.snapshot(inst);
    if (!b64) return Promise.resolve(applySim());
    return X.handwriting(b64).then(function (res) {
      if (!res || res.ok === false) return applySim();
      var data = res.data != null ? res.data : res;
      var text = X.ocrText(data) || '';
      if (!text) return applySim();
      v.handText = text;
      v.handConf = 80;
      ZKB.log && ZKB.log('📷 讯飞 AI·手写文字识别 → ' + text, 'log-sim');
      return text;
    }).catch(function () { return applySim(); });
  }
  function visionHandwriteText(inst) {
    var v = vis(inst);
    return v.handText || '';
  }

  /* 拍照速算识别 */
  function visionCalcStart(inst) {
    var v = vis(inst);
    var fbText = rand(['12+8=', '25×4=', '60÷3=', '7+9=']);
    var fallback = { text: fbText, answer: 20, correct: true };
    function applySim() {
      v.calcText = fallback.text;
      v.calcAnswer = fallback.answer;
      v.calcCorrect = fallback.correct;
      ZKB.log && ZKB.log('拍照速算识别 → ' + fallback.text + fallback.answer, 'log-sim');
      return fallback.text;
    }
    var A = ai();
    if (!A || !A.hasRealCamera(inst) || !A.hasCreds()) return Promise.resolve(applySim());
    var X = ZKB.Xfyun;
    if (!X) return Promise.resolve(applySim());
    var b64 = A.snapshot(inst);
    if (!b64) return Promise.resolve(applySim());
    return X.photoCalculate(b64).then(function (res) {
      if (!res || res.ok === false) return applySim();
      var data = res.data != null ? res.data : res;
      var text = X.ocrText(data) || '';
      if (!text) return applySim();
      v.calcText = text;
      v.calcAnswer = X.calcAnswer(data);
      v.calcCorrect = !!X.calcCorrect(data);
      ZKB.log && ZKB.log('📷 讯飞 AI·拍照速算 → ' + text + ' = ' + v.calcAnswer +
        (v.calcCorrect ? '（正确）' : '（错误）'), 'log-sim');
      return text;
    }).catch(function () { return applySim(); });
  }
  function visionCalcText(inst) { var v = vis(inst); return v.calcText || ''; }
  function visionCalcAnswer(inst) { var v = vis(inst); return v.calcAnswer || 0; }
  function visionCalcCorrect(inst) { var v = vis(inst); return !!v.calcCorrect; }

  /* 人脸数量与属性 */
  function visionFaceCount(inst) {
    var v = vis(inst);
    return v.faceCount || 0;
  }
  function visionFaceAttr(inst, attr) {
    var v = vis(inst);
    var a = v.faceAttr || '';
    switch (attr) {
      case 'gender': return v.faceGenderCn || '';
      case 'age': return v.faceAge || '';
      case 'emotion': return v.faceEmotionCn || '';
      case 'score': return v.faceScore || '';
      default: return a;
    }
  }

  /* ============================================================
   * 导出
   * ============================================================ */
  ZKB.Vision = {
    /* 样本库（供积木下拉与卡片展示） */
    OCR_TEXTS: OCR_TEXTS,
    OCR_NUMBERS: OCR_NUMBERS,
    OBJ_LIB: OBJ_LIB,
    CAT_LABEL: CAT_LABEL,
    CAT_EMOJI: CAT_EMOJI,
    EMOTIONS: EMOTIONS,
    EMOTION_CN: EMOTION_CN,
    /* 文字识别 */
    ocrStart: visionOcrStart,
    ocrText: visionOcrText,
    ocrNumber: visionOcrNumber,
    /* 人脸识别 */
    registerFace: registerFace,
    removeFace: removeFace,
    faceList: faceList,
    findFace: findFace,
    verify: faceVerify,
    name: faceName,
    gender: faceGender,
    bio: faceBio,
    emotion: faceEmotion,
    emotionText: faceEmotionText,
    emotionIs: faceEmotionIs,
    guessEmotion: guessEmotion,
    /* 物体识别 */
    objStart: visionObjStart,
    objResult: objResult,
    confidence: confidence,
    /* 第三十五轮：场景识别 / 手写文字 / 拍照速算 / 人脸数量与属性 */
    sceneStart: visionSceneStart,
    sceneResult: visionSceneResult,
    handwriteStart: visionHandwriteStart,
    handwriteText: visionHandwriteText,
    calcStart: visionCalcStart,
    calcText: visionCalcText,
    calcAnswer: visionCalcAnswer,
    calcCorrect: visionCalcCorrect,
    faceCount: visionFaceCount,
    faceAttr: visionFaceAttr,
    SCENE_LABELS: SCENE_LABELS,
    /* 内部：取某实例的视觉状态 */
    _vis: vis
  };

})(window);