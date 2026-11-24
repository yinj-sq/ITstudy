/* ============================================================
 * js/vision-ai.js —— AI 摄像头「真实视觉」桥接（第三十五轮）
 *
 * 目标：虚拟仿真界面里若能正常调用电脑摄像头，就把真实画面交给
 *       科大讯飞的 AI 模型（文字识别 / 人脸检测 / 人脸比对 /
 *       物体识别 / 场景识别），让积木拿到真答案而不是随机样本。
 *
 * 链路：
 *   摄像头卡片里的 <video>（已在 startRealCamera 中拿到）
 *     → drawImage 到 canvas → JPEG dataURL
 *     → 去掉 "data:image/jpeg;base64," 前缀（讯飞只要裸 base64）
 *     → ZKB.Xfyun.* 对应接口
 *     → 结果写回 ZKB.Vision 的视觉状态，供积木读取
 *
 * 降级策略（保证离线课堂也能用）：
 *   1. 没有摄像头 / 未授权  → 回落到 vision.js 的离线模拟识别
 *   2. 讯飞接口不可用 / 报错 → 同样回落，并把原因写进日志
 *
 * 讯飞凭据：沿用参考资料里的公共测试账号（见 科大讯飞AI技能API接口文档.txt），
 *           用户可在「AI 设置」里换成自己的 APPID / APIKey。
 * ============================================================ */
(function (global) {
  'use strict';
  var ZKB = global.ZKB;

  /* ---------------- 工具：从设备实例拿到真实视频元素 ---------------- */

  function camDev(inst) {
    if (!ZKB.state || !ZKB.state.devices) return null;
    var ds = ZKB.state.devices;
    var direct = ds['camera' + (inst ? String(inst) : '')];
    if (direct) return direct;
    var n = Number(inst);
    if (n >= 1 && ds['camera' + n]) return ds['camera' + n];
    return ds.camera || null;
  }

  /* 抓一帧，返回裸 base64（不含 dataURL 前缀）；
     没有真实摄像头时返回 null。 */
  function grabFrame(inst, maxSide) {
    var DV = camDev(inst);
    if (!DV) return null;
    var v = DV._realVideo;
    if (!v || !v.videoWidth || !v.videoHeight) return null;
    var side = maxSide || 640;
    var w = v.videoWidth, h = v.videoHeight;
    var k = Math.min(1, side / Math.max(w, h));
    var cw = Math.max(1, Math.round(w * k));
    var ch = Math.max(1, Math.round(h * k));
    try {
      var cv = document.createElement('canvas');
      cv.width = cw; cv.height = ch;
      var cx = cv.getContext('2d');
      cx.drawImage(v, 0, 0, cw, ch);
      var url = cv.toDataURL('image/jpeg', 0.85);
      var i = url.indexOf(',');
      return i >= 0 ? url.slice(i + 1) : url;
    } catch (e) {
      /* 画布被跨域内容污染时会抛错 */
      return null;
    }
  }

  /* 供外部（摄像头卡片）使用的公开取帧接口 */
  function snapshot(inst) { return grabFrame(inst, 640); }

  /* ---------------- 讯飞调用封装 ---------------- */

  function xf() { return ZKB.Xfyun; }

  /* 讯飞凭据是否就绪（图像类接口用 image 组凭据） */
  function hasCreds() {
    var X = xf();
    if (!X) return false;
    try {
      var c = X.creds();
      if (!c || !c.appId) return false;
      var im = c.image || {};
      return !!(im.apiKey || im.apiSecret);
    } catch (e) { return false; }
  }

  /* 把讯飞的 {ok,msg,data} 统一成「成功则返回 data，否则抛错」 */
  function unwrap(res, what) {
    if (!res) throw new Error(what + '：接口无返回');
    if (res.ok === false) throw new Error(what + '：' + (res.msg || '调用失败'));
    return res.data != null ? res.data : res;
  }

  /* ---------------- 各能力的真实识别 ---------------- */

  /* 印刷文字 / 印刷数字识别 */
  function ocr(inst, mode) {
    var b64 = grabFrame(inst, 1280);
    if (!b64) return Promise.resolve(null);   /* 无摄像头 → 走离线模拟 */
    var X = xf();
    if (!X) return Promise.resolve(null);
    var what = mode === 'number' ? '印刷数字识别' : '印刷文字识别';
    /* 数字识别用「拍照速算」接口取公式里的数字；纯数字场景仍走印刷文字再抽数字 */
    var p = (mode === 'number')
      ? X.printedText(b64)
      : X.printedText(b64);
    return p.then(function (res) {
      var data = unwrap(res, what);
      var text = X.ocrText(data) || '';
      var num = 0;
      var m = /-?\d+(?:\.\d+)?/.exec(text.replace(/[，,]/g, ''));
      if (m) num = parseFloat(m[0]);
      var conf = 0;
      try {
        var r = data && data.result;
        if (r && r.trash) conf = Math.round((Number(r.trash) || 0) * 100);
      } catch (e) { /* 忽略 */ }
      if (!conf) conf = 85;   /* 讯飞旧接口不返回置信度，给个保守值 */
      return { text: text, number: num, conf: conf, src: 'xfyun' };
    }).catch(function (e) {
      ZKB.log && ZKB.log('⚠ ' + what + '调用失败：' + e.message + '（已回落到模拟识别）', 'log-warn');
      return null;
    });
  }

  /* 人脸检测与属性分析（返回性别 / 表情 / 年龄 / 颜值） */
  function faceDetect(inst) {
    var b64 = grabFrame(inst, 960);
    if (!b64) return Promise.resolve(null);
    var X = xf();
    if (!X) return Promise.resolve(null);
    return X.faceDetect(b64).then(function (res) {
      var data = unwrap(res, '人脸检测');
      var attr = X.faceAttr(data, 0) || '';
      var count = X.faceCount(data) || 0;
      var em = emotionFromAttr(attr);
      return {
        count: count,
        attr: attr,
        gender: /女/.test(attr) ? 'female' : (/男/.test(attr) ? 'male' : ''),
        emotion: em,
        emotionCn: em ? EMOTION_CN[em] : '',
        /* 年龄：讯飞返回 age（years） */
        age: pickAge(data),
        score: X.faceScore(data),
        src: 'xfyun'
      };
    }).catch(function (e) {
      ZKB.log && ZKB.log('⚠ 人脸检测调用失败：' + e.message + '（已回落到模拟识别）', 'log-warn');
      return null;
    });
  }

  /* 从讯飞人脸结果里取出年龄 */
  function pickAge(data) {
    try {
      var fr = (data && (data.face_result || data.faceResult)) || [];
      var p = fr.length ? (fr[0].property || fr[0]) : (data && data.property);
      if (!p) return '';
      var age = (p.age && typeof p.age === 'object') ? p.age.value : p.age;
      if (age == null || age === '') return '';
      return String(Math.round(Number(age) || 0));
    } catch (e) { return ''; }
  }

  var EMOTION_CN = { happy: '高兴', calm: '平静', surprise: '惊讶', angry: '生气', sad: '难过' };

  /* 讯飞人脸属性文案 → 本项目的情绪枚举 */
  function emotionFromAttr(attr) {
    var s = String(attr || '');
    if (/高兴/.test(s)) return 'happy';
    if (/惊讶/.test(s)) return 'surprise';
    if (/生气/.test(s)) return 'angry';
    if (/悲伤|难过/.test(s)) return 'sad';
    if (/害怕|厌恶|正常/.test(s)) return 'calm';
    return '';
  }

  /* 人脸比对（现场拍到的人 vs 底库里的登记照） */
  function faceCompare(inst, baseImg) {
    var b64 = grabFrame(inst, 960);
    if (!b64 || !baseImg) return Promise.resolve(null);
    var X = xf();
    if (!X) return Promise.resolve(null);
    return X.faceCompare(b64, baseImg).then(function (res) {
      var data = unwrap(res, '人脸比对');
      var score = 0;
      try {
        var fr = (data && (data.face_result || data.faceResult)) || [];
        if (fr.length) score = Number(fr[0].score || fr[0].confidence || 0);
        else score = Number((data && data.score) || 0);
      } catch (e) { /* 忽略 */ }
      return { score: Math.round(score * 1000) / 1000, src: 'xfyun' };
    }).catch(function (e) {
      ZKB.log && ZKB.log('⚠ 人脸比对调用失败：' + e.message + '（已回落到模拟识别）', 'log-warn');
      return null;
    });
  }

  /* 物体识别 */
  function objectRecg(inst) {
    var b64 = grabFrame(inst, 960);
    if (!b64) return Promise.resolve(null);
    var X = xf();
    if (!X) return Promise.resolve(null);
    return X.objectRecg(b64).then(function (res) {
      var data = unwrap(res, '物体识别');
      var tags = X.recgTags(data) || [];
      return { tags: tags, src: 'xfyun' };
    }).catch(function (e) {
      ZKB.log && ZKB.log('⚠ 物体识别调用失败：' + e.message + '（已回落到模拟识别）', 'log-warn');
      return null;
    });
  }

  /* 场景识别 */
  function sceneRecg(inst) {
    var b64 = grabFrame(inst, 960);
    if (!b64) return Promise.resolve(null);
    var X = xf();
    if (!X) return Promise.resolve(null);
    return X.sceneRecg(b64).then(function (res) {
      var data = unwrap(res, '场景识别');
      var tags = X.recgTags(data) || [];
      return { tags: tags, src: 'xfyun' };
    }).catch(function (e) {
      ZKB.log && ZKB.log('⚠ 场景识别调用失败：' + e.message + '（已回落到模拟识别）', 'log-warn');
      return null;
    });
  }

  /* ---------------- 对外接口 ---------------- */

  ZKB.VisionAI = {
    /* 抓一帧（base64，无前缀） */
    snapshot: snapshot,
    /* 是否有真实摄像头可用 */
    hasRealCamera: function (inst) {
      var DV = camDev(inst);
      return !!(DV && DV._realVideo && DV._realVideo.videoWidth);
    },
    /* 讯飞凭据是否就绪 */
    hasCreds: hasCreds,
    ocr: ocr,
    faceDetect: faceDetect,
    faceCompare: faceCompare,
    objectRecg: objectRecg,
    sceneRecg: sceneRecg,
    /* 内部：设备实例查找（给 vision.js 复用） */
    _camDev: camDev
  };
})(window);
