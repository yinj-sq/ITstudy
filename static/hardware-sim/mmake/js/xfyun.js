/* ============================================================
 * xfyun.js —— 科大讯飞开放平台 WebAPI 封装
 *
 * 第二十六轮：AI 技能积木接入科大讯飞真实接口。
 *
 * 覆盖能力：
 *   语音识别 IAT（WebSocket 流式）   语音合成 TTS（WebSocket）
 *   人脸检测与属性 / 人脸比对          印刷文字识别
 *   手写文字识别                       拍照速算识别
 *   物体识别 / 场景识别
 *
 * 鉴权：讯飞统一用 HMAC-SHA256 签名
 *   signature_origin = "host: $host\ndate: $date\n$request-line"
 *   signature        = base64(hmac_sha256(signature_origin, apiSecret))
 *   authorization    = base64('api_key="…", algorithm="hmac-sha256",
 *                              headers="host date request-line",
 *                              signature="…"')
 *   date 必须是 RFC1123 的 UTC/GMT 时间（服务端校验 300 秒时钟偏移）
 *
 * 凭据：内置三套默认值（用户可在界面上改成自己的），
 *       改动后存 localStorage，刷新不丢。
 * ============================================================ */
(function (global) {
  'use strict';
  var ZKB = global.ZKB || (global.ZKB = {});

  var LS_KEY = 'zkb_xfyun_creds_v1';

  /* ============================================================
   * 一、内置默认凭据
   *
   * 讯飞按「应用 × 接口能力」分配不同 APIKey，所以分成三套：
   *   speech  —— 语音听写 IAT、语音合成 TTS、人脸检测/比对
   *   text    —— 印刷文字、手写文字、拍照速算
   *   image   —— 物体识别、场景识别
   * ============================================================ */
  var DEFAULT_CREDS = {
    /* 公开发布版：内置凭据已移除。
       请在「⚙ AI 设置」里填自己的讯飞 appId / apiKey / apiSecret，
       保存后写在浏览器 localStorage 里，不会随文件泄露。 */
    appId: '',
    speech: { apiKey: '', apiSecret: '' },
    text: { apiKey: '', apiSecret: '' },
    image: { apiKey: '', apiSecret: '' }
  };

  function clone(o) { return JSON.parse(JSON.stringify(o)); }

  /* 读用户自定义凭据，与默认值合并 */
  function creds() {
    var base = clone(DEFAULT_CREDS);
    var saved = null;
    try { saved = ZKB.Store && ZKB.Store.getLocal(LS_KEY); }
    catch (e) { saved = null; }
    if (saved && typeof saved === 'object') {
      if (saved.appId) base.appId = saved.appId;
      ['speech', 'text', 'image'].forEach(function (k) {
        if (saved[k] && saved[k].apiKey) {
          base[k].apiKey = saved[k].apiKey;
          base[k].apiSecret = saved[k].apiSecret || base[k].apiSecret;
        }
      });
      if (saved.custom != null) base.custom = !!saved.custom;
    }
    if (base.custom == null) base.custom = false;
    return base;
  }

  /* 覆盖保存（只存用户改动过的字段） */
  function setCreds(next) {
    var cur = creds();
    var out = { appId: next.appId || cur.appId };
    ['speech', 'text', 'image'].forEach(function (k) {
      out[k] = {
        apiKey: (next[k] && next[k].apiKey) || cur[k].apiKey,
        apiSecret: (next[k] && next[k].apiSecret) || cur[k].apiSecret
      };
    });
    out.custom = true;
    if (ZKB.Store && ZKB.Store.setLocal) ZKB.Store.setLocal(LS_KEY, out);
    else { try { localStorage.setItem(LS_KEY, JSON.stringify(out)); } catch (e) { } }
    return creds();
  }

  /* 恢复内置默认值 */
  function resetCreds() {
    try { localStorage.removeItem(LS_KEY); } catch (e) { }
    if (ZKB.Store && ZKB.Store.delLocal) ZKB.Store.delLocal(LS_KEY);
    return creds();
  }

  function isCustom() { return creds().custom === true; }

  /* ============================================================
   * 二、签名工具
   * ============================================================ */

  /* base64（btoa 只吃 latin1，这里做 UTF-8 安全处理） */
  function b64(str) {
    var bytes = new TextEncoder().encode(String(str));
    var bin = '';
    for (var i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin);
  }
  function b64FromBytes(u8) {
    var bin = '';
    for (var i = 0; i < u8.length; i++) bin += String.fromCharCode(u8[i]);
    return btoa(bin);
  }
  /* base64 → Uint8Array（解码音频用） */
  function unb64(s) {
    var bin = atob(String(s || ''));
    var u8 = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    return u8;
  }

  /* RFC1123 GMT 时间，例如 'Thu, 17 Sep 2026 01:38:38 GMT' */
  function rfc1123() {
    return new Date().toUTCString();
  }

  /* HMAC-SHA256（浏览器 Web Crypto；file:// 下不可用时返回 null） */
  function hmacSha256(origin, secret) {
    if (!global.crypto || !global.crypto.subtle) return Promise.resolve(null);
    /* 第五十一轮：API Secret 为空时，浏览器的 importKey 会抛
       DataError: Zero-length key is not supported —— 报错完全看不懂。
       公开发布版不再内置凭据，用户没填就会走到这里，
       换成一句能照着做的提示。 */
    if (!secret) {
      return Promise.reject(new Error(
        '未配置讯飞凭据：请点右上角「⚙ AI 设置」，填入自己的 APPID / APIKey / APISecret'));
    }
    var enc = new TextEncoder();
    return global.crypto.subtle.importKey(
      'raw', enc.encode(String(secret)),
      { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']
    ).then(function (key) {
      return global.crypto.subtle.sign('HMAC', key, enc.encode(String(origin)));
    }).then(function (buf) {
      return b64FromBytes(new Uint8Array(buf));
    });
  }

  /* 生成 authorization 参数值（HMAC-URL 风格：签名放 URL 查询串） */
  function authorization(apiKey, apiSecret, date, requestLine) {
    var origin = 'host: ' + X.host + '\ndate: ' + date + '\n' + requestLine;
    return hmacSha256(origin, apiSecret).then(function (sig) {
      if (!sig) return null;
      var auth = 'api_key="' + apiKey + '", algorithm="hmac-sha256", ' +
        'headers="host date request-line", signature="' + sig + '"';
      return b64(auth);
    });
  }

  /* ============================================================
   * 二之二、纯 JS MD5
   *
   * 讯飞「旧版 WebAPI」（物体识别 / 场景识别 / 手写文字）
   * 用的是 MD5(APIKey + X-CurTime + X-Param)，
   * 而 Web Crypto 的 subtle.digest 不支持 MD5，只能自己实现。
   * ============================================================ */
  var MD5_K = [
    0xd76aa478, 0xe8c7b756, 0x242070db, 0xc1bdceee, 0xf57c0faf, 0x4787c62a,
    0xa8304613, 0xfd469501, 0x698098d8, 0x8b44f7af, 0xffff5bb1, 0x895cd7be,
    0x6b901122, 0xfd987193, 0xa679438e, 0x49b40821, 0xf61e2562, 0xc040b340,
    0x265e5a51, 0xe9b6c7aa, 0xd62f105d, 0x02441453, 0xd8a1e681, 0xe7d3fbc8,
    0x21e1cde6, 0xc33707d6, 0xf4d50d87, 0x455a14ed, 0xa9e3e905, 0xfcefa3f8,
    0x676f02d9, 0x8d2a4c8a, 0xfffa3942, 0x8771f681, 0x6d9d6122, 0xfde5380c,
    0xa4beea44, 0x4bdecfa9, 0xf6bb4b60, 0xbebfbc70, 0x289b7ec6, 0xeaa127fa,
    0xd4ef3085, 0x04881d05, 0xd9d4d039, 0xe6db99e5, 0x1fa27cf8, 0xc4ac5665,
    0xf4292244, 0x432aff97, 0xab9423a7, 0xfc93a039, 0x655b59c3, 0x8f0ccc92,
    0xffeff47d, 0x85845dd1, 0x6fa87e4f, 0xfe2ce6e0, 0xa3014314, 0x4e0811a1,
    0xf7537e82, 0xbd3af235, 0x2ad7d2bb, 0xeb86d391
  ];
  var MD5_S = [
    7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22,
    5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20,
    4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23,
    6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21
  ];

  function md5(str) {
    /* UTF-8 编码 */
    var bytes = new TextEncoder().encode(String(str));
    var len = bytes.length;
    var bitLen = len * 8;
    /* 补位：末尾加 0x80，再补到 56 mod 64，最后 8 字节写长度（小端） */
    var withPad = len + 1;
    while (withPad % 64 !== 56) withPad++;
    var total = withPad + 8;
    var buf = new Uint8Array(total);
    buf.set(bytes, 0);
    buf[len] = 0x80;
    var dv = new DataView(buf.buffer);
    /* 位长度写进最后 8 字节（低 32 位放低位，高 32 位放高位） */
    dv.setUint32(total - 8, bitLen >>> 0, true);
    dv.setUint32(total - 4, Math.floor(bitLen / 4294967296), true);

    var a0 = 0x67452301, b0 = 0xefcdab89, c0 = 0x98badcfe, d0 = 0x10325476;
    var M = new Int32Array(16);

    for (var off = 0; off < total; off += 64) {
      for (var i = 0; i < 16; i++) M[i] = dv.getInt32(off + i * 4, true);
      var A = a0, B = b0, C = c0, D = d0;
      for (var j = 0; j < 64; j++) {
        var F, g;
        if (j < 16) { F = (B & C) | (~B & D); g = j; }
        else if (j < 32) { F = (D & B) | (~D & C); g = (5 * j + 1) % 16; }
        else if (j < 48) { F = B ^ C ^ D; g = (3 * j + 5) % 16; }
        else { F = C ^ (B | ~D); g = (7 * j) % 16; }
        F = (F + A + MD5_K[j] + M[g]) | 0;
        A = D; D = C; C = B;
        B = (B + ((F << MD5_S[j]) | (F >>> (32 - MD5_S[j])))) | 0;
      }
    a0 = (a0 + A) | 0; b0 = (b0 + B) | 0;
    c0 = (c0 + C) | 0; d0 = (d0 + D) | 0;
    }
    /* 输出 32 位小写 hex。
       MD5 的字节序是小端：先输出每个 32 位字的低字节，再高字节，
       例如 a0=0x67452301 要输出成 "01234567" 而不是 "67452301"。 */
    function hex(n) {
      var s = '';
      for (var i = 0; i < 4; i++) {
        var b = (n >>> (i * 8)) & 0xff;
        s += (b < 16 ? '0' : '') + b.toString(16);
      }
      return s;
    }
    return hex(a0) + hex(b0) + hex(c0) + hex(d0);
  }

  /* ============================================================
   * 三、接口地址
   *
   * ⚠ 关键：讯飞这 7 个图像能力并不是同一套协议，实测文档核实后
   *   分成三套，每套的签名方式、请求体结构、结果结构都不一样。
   *
   * 【A】hmacUrl —— HMAC-SHA256，签名放 URL 查询串
   *     authorization / date / host 三个参数
   *     体：{ header:{app_id,status:3}, parameter:{[svc]:{…}},
   *          payload:{[svc]_data_1:{encoding,image,status:3}} }
   *     覆盖：人脸检测与属性分析、人脸比对
   *
   * 【B】hmacDigest —— HMAC-SHA256 + Digest 头，签名放请求头
   *     headers="host date request-line digest"，digest=SHA-256=base64(sha256(body))
   *     体：{ common:{app_id}, business:{…}, data:{image} }
   *     覆盖：拍照速算识别（⚠ 用 speech 组凭据，因为它需要 apiSecret）
   *
   * 【C】md5Header —— 旧版 WebAPI，MD5(apiKey+curTime+param) 放请求头
   *     X-Appid / X-CurTime / X-Param(base64 json) / X-CheckSum
   *     体：表单 image=base64(URL 编码) 或 图片二进制流
   *     覆盖：印刷文字识别、手写文字识别、物体识别、场景识别
   * ============================================================ */
  var X = { host: '' };

  function callMeta(kind) {
    var c = creds();
    if (kind === 'speech') return { appId: c.appId, key: c.speech.apiKey, secret: c.speech.apiSecret };
    if (kind === 'text') return { appId: c.appId, key: c.text.apiKey, secret: c.text.apiSecret };
    return { appId: c.appId, key: c.image.apiKey, secret: c.image.apiSecret };
  }

  /* WebSocket 接口（语音） */
  var WS_API = {
    iat: { host: 'iat-api.xfyun.cn', path: '/v2/iat' },
    tts: { host: 'tts-api.xfyun.cn', path: '/v2/tts' }
  };

  /* HTTP 接口（图像/文字/OCR）—— path 里的 serviceId 就是 URL 那段 */
  var HTTP_API = {
    /* 人脸比对：serviceId 与人脸检测共用 s67c9c78c，用 service_kind 区分。
       parameter 块名是 face_compare_result，payload 用 input1/input2 两段图 */
    faceCompare: {
      host: 'api.xf-yun.com', path: '/v1/private/s67c9c78c',
      serviceId: 's67c9c78c', auth: 'hmacUrl', kind: 'speech',
      twoImage: true, serviceKind: 'face_compare',
      resultBlock: 'face_compare_result',
      payloadKey: 'input1'
    },
    /* 人脸检测与属性分析：
       parameter 块名是 face_detect_result（不是 result），
       payload 键是 input1（不是 serviceId_data_1）——
       这两点写错会被讯飞以 10163 parameter schema validate error 拒掉 */
    faceDetect: {
      host: 'api.xf-yun.com', path: '/v1/private/s67c9c78c',
      serviceId: 's67c9c78c', auth: 'hmacUrl', kind: 'speech',
      serviceKind: 'face_detect',
      resultBlock: 'face_detect_result',
      payloadKey: 'input1',
      /* detect_points=0 只框出人脸；detect_property=1 才返回性别/表情等属性 */
      extra: { detect_points: '0', detect_property: '1' }
    },
    /* 印刷文字识别：官方地址是 webapi.xfyun.cn/v1/service/v1/ocr/general，
       用 MD5 请求头（X-Appid/X-CurTime/X-Param/X-CheckSum）+ 表单 image，
       不是私有 hmacUrl 接口 s00b65163。
       ⚠ language 可选值只有 'en' 和 'cn|en'（不是 'mix0'），
         填错会报 10107。 */
    printedText: {
      host: 'webapi.xfyun.cn', path: '/v1/service/v1/ocr/general',
      auth: 'md5Header', kind: 'text', form: true,
      param: { language: 'cn|en', location: 'true' }
    },
    /* 拍照速算识别：rest-api.xfyun.cn/v2/itr，Digest 签名
       ⚠ 它需要 apiSecret，所以必须走 speech 组凭据（text 组没给 secret） */
    photoCalculate: {
      host: 'rest-api.xfyun.cn', path: '/v2/itr',
      auth: 'hmacDigest', kind: 'speech',
      /* business 固定这两个字段，aue 只支持 raw */
      business: { ent: 'math-arith', aue: 'raw' }
    },
    /* 手写文字识别：webapi.xfyun.cn/v1/service/v1/ocr/handwriting，MD5 请求头
       language 同样只有 'en' / 'cn|en' */
    handwriting: {
      host: 'webapi.xfyun.cn', path: '/v1/service/v1/ocr/handwriting',
      auth: 'md5Header', kind: 'text', form: true,
      param: { language: 'cn|en', location: 'true' }
    },
    /* 物体识别：tupapi 旧接口，MD5 请求头 + 二进制流 */
    objectRecg: {
      host: 'tupapi.xfyun.cn', path: '/v1/currency',
      auth: 'md5Header', kind: 'image', binary: true
    },
    /* 场景识别：tupapi 旧接口，MD5 请求头 + 二进制流 */
    sceneRecg: {
      host: 'tupapi.xfyun.cn', path: '/v1/scene',
      auth: 'md5Header', kind: 'image', binary: true
    }
  };

  function requestLineOf(method, path) {
    return method + ' ' + path + ' HTTP/1.1';
  }

  /* 【A】组装带 HMAC-URL 签名的完整 URL */
  function signedUrl(api, method, kind) {
    var m = callMeta(kind || api.kind || 'text');
    var date = rfc1123();
    X.host = api.host;
    return authorization(m.key, m.secret, date, requestLineOf(method, api.path))
      .then(function (auth) {
        if (!auth) return null;
        return 'https://' + api.host + api.path +
          '?authorization=' + encodeURIComponent(auth) +
          '&date=' + encodeURIComponent(date) +
          '&host=' + api.host;
      });
  }

  /* 【B】组装 Digest + Authorization 请求头 */
  function digestHeaders(api, apiKey, apiSecret, bodyStr) {
    var date = rfc1123();
    /* Digest: SHA-256=base64(sha256(body)) */
    var digest;
    if (!global.crypto || !global.crypto.subtle) return Promise.resolve(null);
    return global.crypto.subtle.digest('SHA-256', new TextEncoder().encode(bodyStr))
      .then(function (buf) { digest = 'SHA-256=' + b64FromBytes(new Uint8Array(buf)); })
      .then(function () {
        var origin = 'host: ' + api.host + '\ndate: ' + date + '\n' +
          requestLineOf('POST', api.path) + '\ndigest: ' + digest;
        return hmacSha256(origin, apiSecret);
      })
      .then(function (sig) {
        if (!sig) return null;
        return {
          date: date,
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json,version=1.0',
            /* ⚠⚠ 浏览器里绝对不要发 'Date' 头——它是浏览器保护的 forbidden header，
               脚本设了也会被静默丢弃。Date 参与签名，一旦丢失，
               服务端算出的 signature 必然对不上，返回
               401 HMAC signature does not match。
               讯飞支持用 'x-date' 代替（其错误码说明里就有 "a valid date or
               x-date header is required"），x-date 是普通自定义头，浏览器放行。
               这也是这个接口能在纯前端跑通的关键。 */
            'x-date': date,
            'Digest': digest,
            'Authorization': 'api_key="' + apiKey + '", algorithm="hmac-sha256", ' +
              'headers="host date request-line digest", signature="' + sig + '"'
          }
        };
      });
  }

  /* 【C】组装 MD5 请求头 */
  function md5Headers(api, apiKey, business) {
    var curTime = String(Math.floor(Date.now() / 1000));
    var paramStr = b64(JSON.stringify(business));
    return Promise.resolve({
      curTime: curTime,
      headers: {
        'X-Appid': callMeta(api.kind || 'text').appId,
        'X-CurTime': curTime,
        'X-Param': paramStr,
        'X-CheckSum': md5(apiKey + curTime + paramStr),
        'Content-Type': 'application/x-www-form-urlencoded; charset=utf-8'
      }
    });
  }

  /* ============================================================
   * 四、语音合成 TTS（WebSocket）
   *
   * 请求帧：
   *   { common:{app_id}, business:{aue,auf,vcn,speed,volume,pitch,tte},
   *     data:{ status:2, text: base64(文本) } }
   * 响应帧 data.audio 为 base64，status===2 表示结束，需拼接所有分片。
   * ============================================================ */
  var TTS_VOICES = [
    ['小燕（女声，标准）', 'xiaoyan'],
    ['小宇（男声，标准）', 'xiaoyu'],
    ['晓晓（女声）', 'xiaoxiao'],
    ['晓双（男声）', 'xiaoshuang'],
    ['小枫（男声）', 'xiaofeng'],
    ['小美（女声）', 'xiaomei'],
    ['小语（女声）', 'xiaoyu_']
  ];

  function speak(text, opt) {
    opt = opt || {};
    var txt = String(text == null ? '' : text);
    if (!txt) return Promise.resolve({ ok: false, msg: '要朗读的文字为空' });
    if (txt.length > 2000) txt = txt.slice(0, 2000);

    var api = WS_API.tts;
    return signedUrl(api, 'GET', 'speech').then(function (url) {
      if (!url) return { ok: false, msg: '签名失败：当前环境不支持 Web Crypto（请用 localhost 或 HTTPS 打开）' };
      var m = callMeta('speech');
      return new Promise(function (resolve) {
        var ws;
        try { ws = new WebSocket(url); }
        catch (e) { resolve({ ok: false, msg: '无法建立连接：' + e.message }); return; }

        var chunks = [];
        var settled = false;
        var timer = setTimeout(function () {
          if (settled) return;
          settled = true;
          try { ws.close(); } catch (e) { }
          if (chunks.length) {
            resolve({ ok: true, audio: joinBytes(chunks), fmt: opt.fmt || 'mp3', url: api.path });
          } else {
            resolve({ ok: false, msg: '语音合成超时（20 秒）' });
          }
        }, 20000);

        ws.onopen = function () {
          ws.send(JSON.stringify({
            common: { app_id: m.appId },
            business: (function () {
              var aue = opt.aue || 'lame';
              var bs = {
                aue: aue,
                auf: opt.auf || 'audio/L16;rate=16000',
                vcn: opt.voice || 'xiaoyan',
                /* 讯飞这三位是 0~100，50 为默认 */
                speed: Math.round(50 * (opt.rate == null ? 1 : opt.rate)),
                volume: Math.round(50 * (opt.volume == null ? 1 : opt.volume)),
                pitch: Math.round(50 * (opt.pitch == null ? 1 : opt.pitch)),
                tte: 'UTF8'
              };
              /* ⚠ aue=lame（mp3）时讯飞强制要求传 sfl=1，
                 少了这个参数服务端会不返回音频（表现为一直收不到帧直到超时）。
                 raw（pcm）/ opus 不需要 sfl。 */
              if (aue === 'lame') bs.sfl = 1;
              return bs;
            })(),
            data: { status: 2, text: b64(txt) }
          }));
        };
        ws.onmessage = function (ev) {
          var r = null;
          try { r = JSON.parse(ev.data); } catch (e) { return; }
          if (r.code !== 0) {
            clearTimeout(timer);
            if (!settled) { settled = true; try { ws.close(); } catch (e) { } }
            resolve({ ok: false, msg: '讯飞返回错误 ' + r.code + '：' + (r.message || '') });
            return;
          }
          if (r.data && r.data.audio) chunks.push(unb64(r.data.audio));
          if (r.data && r.data.status === 2) {
            clearTimeout(timer);
            if (!settled) { settled = true; try { ws.close(); } catch (e) { } }
            if (!chunks.length) {
              resolve({ ok: false, msg: '讯飞未返回音频数据' });
            } else {
              resolve({ ok: true, audio: joinBytes(chunks), fmt: 'mp3', url: api.path });
            }
          }
        };
        ws.onerror = function () {
          clearTimeout(timer);
          if (!settled) { settled = true; resolve({ ok: false, msg: '语音合成连接失败（请检查网络或凭据）' }); }
        };
        ws.onclose = function () {
          clearTimeout(timer);
          if (!settled) {
            settled = true;
            resolve(chunks.length
              ? { ok: true, audio: joinBytes(chunks), fmt: 'mp3', url: api.path }
              : { ok: false, msg: '语音合成连接被关闭' });
          }
        };
      });
    });
  }

  /* 把多个 Uint8Array 拼成一个 */
  function joinBytes(list) {
    var n = list.reduce(function (s, a) { return s + a.length; }, 0);
    var out = new Uint8Array(n);
    var o = 0;
    list.forEach(function (a) { out.set(a, o); o += a.length; });
    return out;
  }

  /* ============================================================
   * 五、语音识别 IAT（WebSocket 流式）
   *
   * 发送两帧：
   *   第1帧 data.status=0，带 business（语言/领域/方言/音频参数）
   *   第2帧 data.status=2，带 base64(audioBytes)
   * 接收帧 data.status: 0 中间结果 / 1 最后一段 / 2 结束。
   * 文本在 data.result.sn 索引处，结果串格式为 "[0]文本[1]…"。
   * ============================================================ */
  function listen(opt) {
    opt = opt || {};
    var api = WS_API.iat;
    var audio = opt.audio || null;

    /* 未给音频时优先取麦克风实时采集 */
    return ensureAudio(audio).then(function (ab) {
      if (!ab) return { ok: false, msg: '没有可用的音频数据（麦克风未授权？）' };
      return signedUrl(api, 'GET', 'speech').then(function (url) {
        if (!url) return { ok: false, msg: '签名失败：当前环境不支持 Web Crypto' };
        var m = callMeta('speech');
        return new Promise(function (resolve) {
          var ws;
          try { ws = new WebSocket(url); }
          catch (e) { resolve({ ok: false, msg: '无法建立连接：' + e.message }); return; }

          var segs = {};
          var finalText = '';
          var settled = false;
          var timer = setTimeout(function () {
            if (settled) return;
            settled = true;
            try { ws.close(); } catch (e) { }
            resolve(finalText
              ? { ok: true, text: finalText, conf: 90 }
              : { ok: false, msg: '语音识别超时（20 秒）' });
          }, 20000);

          function done(ok, extra) {
            clearTimeout(timer);
            if (settled) return;
            settled = true;
            try { ws.close(); } catch (e) { }
            if (ok) {
              resolve({ ok: true, text: finalText, conf: extra && extra.conf || 90, raw: extra && extra.raw });
            } else {
              resolve({ ok: false, msg: (extra && extra.msg) || '语音识别失败' });
            }
          }

          ws.onopen = function () {
            ws.send(JSON.stringify({
              common: { app_id: m.appId },
              business: {
                language: opt.language || 'zh_cn',
                domain: opt.domain || 'iat',
                accent: opt.accent || 'mandarin',
                dwa: 'wpgs'      /* 开动态修正，断句更准 */
              },
              data: {
                status: 0,
                format: 'audio/L16;rate=16000',
                encoding: 'raw'
                /* ⚠ 不要再加 sample_rate —— 讯飞 IAT 的 schema 里没有这个字段，
                   多了会返回 10163 param validate error: '$.data.sample_rate' unknown field。
                   采样率已经写在 format 里（audio/L16;rate=16000）。 */
              }
            }));
            /* 第二帧：音频数据 */
            var bytes = new Uint8Array(ab);
            var CHUNK = 1280;                       /* 每次 1280 字节，官方建议 */
            var pos = 0;
            function pump() {
              if (settled || pos >= bytes.length) {
                if (!settled && pos >= bytes.length) {
                  /* 音频发完，发结束标识 */
                  try { ws.send(JSON.stringify({ data: { status: 2 } })); } catch (e) { }
                  /* 音频本来就没数据时立刻收尾，避免死等 */
                  if (bytes.length === 0) done(true, { conf: 0 });
                }
                return;
              }
              var slice = bytes.subarray(pos, pos + CHUNK);
              pos += CHUNK;
              try {
                ws.send(JSON.stringify({
                  data: { status: 1, format: 'audio/L16;rate=16000',
                          encoding: 'raw',
                          audio: b64FromBytes(slice) }
                }));
              } catch (e) { done(false, { msg: '发送音频失败：' + e.message }); return; }
              setTimeout(pump, 40);
            }
            pump();
          };

          ws.onmessage = function (ev) {
            var r = null;
            try { r = JSON.parse(ev.data); } catch (e) { return; }
            if (r.code !== 0) { done(false, { msg: '讯飞返回错误 ' + r.code + '：' + (r.message || '') }); return; }
            var d = r.data || {};
            if (d.result && typeof d.result.sn === 'number') {
              segs[d.result.sn] = d.result.ls || '';
            }
            if (d.result && d.result.pgs === 'apd') return;  /* apd 后续片段丢弃 */
            /* 合并：sn 从小到大拼接，[n] 是分隔标记 */
            var keys = Object.keys(segs).map(Number).sort(function (a, b) { return a - b; });
            finalText = keys.map(function (k) { return segs[k]; }).join('').trim();
            if (d.status === 2) {
              done(finalText.length > 0, {
                conf: 90,
                raw: r,
                msg: finalText.length ? '' : '没听清，请再说一次'
              });
            }
          };
          ws.onerror = function () { done(false, { msg: '语音识别连接失败（请检查网络或凭据）' }); };
          ws.onclose = function () { done(finalText.length > 0, { msg: '语音识别连接被关闭' }); };
        });
      });
    });
  }

  /* 取音频：优先用传入，否则录一段麦克风 */
  function ensureAudio(audio) {
    if (audio) return Promise.resolve(audio);
    var md = navigator.mediaDevices;
    if (!md || !md.getUserMedia) return Promise.resolve(null);
    return md.getUserMedia({ audio: true }).then(function (stream) {
      return recordAudio(stream, opt_ms(4000)).then(function (buf) {
        stream.getTracks().forEach(function (t) { t.stop(); });
        return buf;
      });
    }).catch(function () { return null; });
  }
  /* 录音时长（可被 opt 覆盖） */
  var _ms = 4000;
  function opt_ms(v) { _ms = v; return _ms; }
  function setRecordMs(v) { _ms = Math.max(500, Math.min(15000, v | 0)); }
  function getRecordMs() { return _ms; }

  /* 用 ScriptProcessor（兼容性最好，无需 AudioWorklet）录 PCM */
  function recordAudio(stream, ms) {
    return new Promise(function (resolve) {
      var AC = global.AudioContext || global.webkitAudioContext;
      if (!AC) { resolve(null); return; }
      var ctx = new AC();
      var src = ctx.createMediaStreamSource(stream);
      var proc = ctx.createScriptProcessor(4096, 1, 1);
      var chunks = [], total = 0, stopped = false;
      var target = 16000 * 2 * (ms / 1000);   /* 16k 16bit 单声道 */
      proc.onaudioprocess = function (e) {
        if (stopped) return;
        var input = e.inputBuffer.getChannelData(0);
        var buf = new ArrayBuffer(input.length * 2);
        var dv = new DataView(buf);
        for (var i = 0; i < input.length; i++) {
          var s = Math.max(-1, Math.min(1, input[i]));
          dv.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
        }
        chunks.push(new Uint8Array(buf));
        total += buf.byteLength;
        if (total >= target) finish();
      };
      function finish() {
        if (stopped) return;
        stopped = true;
        try { src.disconnect(); proc.disconnect(); ctx.close(); } catch (e) { }
        resolve(joinBytes(chunks).buffer);
      }
      src.connect(proc);
      proc.connect(ctx.destination);
      setTimeout(finish, ms + 400);
    });
  }

  /* ============================================================
   * 六、图像 / 文字类（HTTP POST，按 auth 字段分发三种协议）
   * ============================================================ */

  function tooBig(imageBase64) {
    return String(imageBase64).length > 4 * 1024 * 1024;
  }
  function noImage(imageBase64) {
    return !imageBase64 ? { ok: false, msg: '没有图片数据' }
      : tooBig(imageBase64) ? { ok: false, msg: '图片太大（base64 超过 4MB），请先缩小尺寸' }
        : null;
  }

  /* 把讯飞的各种返回形态归一为 { ok, result }，result 是业务 JSON */
  function normalizeJson(j, api) {
    if (!j) return { ok: false, msg: '返回内容不是 JSON' };
    /* 【A】header.code */
    if (j.header) {
      if (j.header.code !== 0 && j.header.code != null) {
        return {
          ok: false, code: j.header.code,
          msg: '讯飞错误 ' + j.header.code + '：' + (j.header.message || ''),
          raw: j
        };
      }
      /* payload 里放结果的是 xxx_result 块，块名因接口而异：
         人脸检测 face_detect_result / 人脸比对 face_compare_result / OCR result */
      var pay = j.payload || {};
      var want = api && api.resultBlock;
      var blk = (want && pay[want] && pay[want].text)
        ? pay[want]
        : (pay.result && pay.result.text ? pay.result : null);
      if (!blk) {
        /* 兜底：找出任意带 text 的块 */
        Object.keys(pay).forEach(function (k) {
          if (!blk && pay[k] && pay[k].text) blk = pay[k];
        });
      }
      if (!blk) return { ok: false, msg: '返回里没有结果字段', raw: j };
      var inner = null;
      try { inner = JSON.parse(new TextDecoder().decode(unb64(blk.text))); } catch (e) { }
      if (!inner) {
        try { inner = JSON.parse(decodeURIComponent(escape(atob(blk.text)))); } catch (e2) { }
      }
      if (!inner) return { ok: false, msg: '结果 base64 解码失败', raw: j };
      if (inner.ret != null && inner.ret != 0) {
        return { ok: false, code: inner.ret, msg: '识别失败 ret=' + inner.ret, raw: inner };
      }
      return { ok: true, result: inner, raw: j };
    }
    /* 【B】直接就是业务 JSON（速算）
       速算返回 { code, message, sid, data:{ ITRResult:{…} } }，
       要把 data 剥出来当 result，否则下面每CalcLine 得自己再剥一层。 */
    if (j.code != null && String(j.code) !== '0') {
      return { ok: false, msg: '讯飞错误 ' + j.code + '：' + (j.message || ''), code: j.code };
    }
    return { ok: true, result: j.data != null ? j.data : j, raw: j };
  }

  /* 【C】旧版返回：{ code:"0", data:{...}|[...], desc, sid } */
  function normalizeLegacy(j) {
    if (!j) return { ok: false, msg: '返回内容不是 JSON' };
    if (String(j.code) !== '0') {
      return { ok: false, msg: '讯飞错误 ' + j.code + '：' + (j.desc || j.message || ''), code: j.code };
    }
    return { ok: true, result: j.data != null ? j.data : j, raw: j };
  }

  function fetchJson(url, init) {
    return fetch(url, init).then(function (r) {
      return r.text().then(function (t) {
        var j = null;
        try { j = JSON.parse(t); } catch (e) { }
        if (!j) {
          return { ok: false, msg: 'HTTP ' + r.status + '：' + String(t).slice(0, 140) };
        }
        if (!r.ok) {
          return { ok: false, msg: 'HTTP ' + r.status + '：' + (j.message || j.desc || String(t).slice(0, 100)) };
        }
        return { __json: j };
      });
    }).catch(function (e) {
      return { ok: false, msg: '请求异常：' + e.message + corsHint() };
    });
  }

  function corsHint() {
    /* 实测结论（2026-10-08 Chromium 直连，绕系统代理）：
       - rest-api.xfyun.cn（拍照速算，Digest 协议）→ **有 CORS 头，浏览器可直连**，实测 200
       - api.xf-yun.com（人脸，HMAC-URL 签名放查询串）→ 简单请求可直连，实测 200
       - webapi.xfyun.cn / tupapi.xfyun.cn（MD5 请求头那几个）→ 服务端不下发
         Access-Control-Allow-Origin，且自定义头会触发预检 OPTIONS，
         连 mode:'no-cors' 都 Failed to fetch。属协议层限制，前端无法绕过，
         只能经本地代理或改用讯飞 SDK。 */
    var p = location.protocol;
    var tail = '该接口在浏览器里会被跨域拦截（讯飞服务端不下发 CORS 头），'
      + '需要经本地代理调用，或在掌控板真机上跑（真机走 mPython SDK，不受跨域限制）。';
    return p === 'file:' ? '（' + tail + '另外请用本地服务器打开，不要直接双击 HTML 文件。）' : '（' + tail + '）';
  }

  /* ---- 协议 A：HMAC-URL + header/parameter/payload ----
     三处容易写错的地方都由接口表的字段驱动，不再硬编码：
       parameter 里的结果块名   → api.resultBlock（人脸是 face_detect_result）
       payload 里的图片键名     → api.payloadKey（人脸是 input1，OCR 是 xxx_data_1）
       该接口额外的业务参数     → api.extra（如 detect_property=1）
     写错任一项，讯飞都会返回 10163 parameter schema validate error。 */
  function postHmacUrl(apiName, imageBase64, param, secondImage) {
    var api = HTTP_API[apiName];
    var m = callMeta(api.kind);
    var blockName = api.resultBlock || 'result';

    var parameter = {};
    parameter[api.serviceId] = {
      service_kind: api.serviceKind,
      /* 结果块：声明要什么格式的返回 */
      /* 块名必须与 resultBlock 一致，不能一律叫 result */
    };
    parameter[api.serviceId][blockName] = {
      encoding: 'utf8', compress: 'raw', format: 'json'
    };
    /* 接口自带的业务参数（如人脸的 detect_property） */
    Object.keys(api.extra || {}).forEach(function (k) {
      parameter[api.serviceId][k] = api.extra[k];
    });
    /* 调用方临时传入的参数 */
    Object.keys(param || {}).forEach(function (k) {
      parameter[api.serviceId][k] = param[k];
    });

    var payload = {};
    var key1 = api.payloadKey || (api.serviceId + '_data_1');
    payload[key1] = { encoding: 'jpg', image: String(imageBase64), status: 3 };
    /* 人脸比对需要第二张图（底库图） */
    if (api.twoImage) {
      payload.input2 = { encoding: 'jpg', image: String(secondImage || ''), status: 3 };
    }

    var body = {
      header: { app_id: m.appId, status: 3 },
      parameter: parameter,
      payload: payload
    };

    return signedUrl(api, 'POST', api.kind).then(function (url) {
      if (!url) return { ok: false, msg: '签名失败：当前环境不支持 Web Crypto（请用 localhost 或 HTTPS 打开）' };
      return fetchJson(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json;charset=UTF-8' },
        body: JSON.stringify(body)
      }).then(function (r) {
        if (r.__json) return normalizeJson(r.__json, api);
        return r;
      });
    });
  }

  /* ---- 协议 B：HMAC-Digest + common/business/data ---- */
  function postHmacDigest(apiName, imageBase64, business) {
    var api = HTTP_API[apiName];
    var m = callMeta(api.kind);
    var biz = Object.assign({}, api.business || {}, business || {});
    var body = {
      common: { app_id: m.appId },
      business: biz,
      data: { image: String(imageBase64) }
    };
    var bodyStr = JSON.stringify(body);
    return digestHeaders(api, m.key, m.secret, bodyStr).then(function (dh) {
      if (!dh) return { ok: false, msg: '签名失败：当前环境不支持 Web Crypto（请用 localhost 或 HTTPS 打开）' };
      return fetchJson('https://' + api.host + api.path, {
        method: 'POST', headers: dh.headers, body: bodyStr
      }).then(function (r) {
        if (r.__json) return normalizeJson(r.__json);
        return r;
      });
    });
  }

  /* ---- 协议 C：MD5 请求头 + 表单/二进制 ---- */
  function postMd5Header(apiName, imageBase64, business) {
    var api = HTTP_API[apiName];
    var m = callMeta(api.kind);
    /* X-Param 的业务参数：接口表里的 param 是默认值，调用方可覆盖 */
    var biz = Object.assign({}, api.param || {}, business || {});
    /* 物体/场景识别那类旧接口需要 image_name/image_url 兜底字段 */
    if (!api.param) biz = Object.assign({ image_name: 'img.jpg', image_url: '' }, biz);
    return md5Headers(api, m.key, biz).then(function (mh) {
      var init;
      if (api.binary) {
        /* base64 → 二进制字节流 */
        init = {
          method: 'POST',
          headers: (function () {
            var h = {};
            Object.keys(mh.headers).forEach(function (k) { h[k] = mh.headers[k]; });
            h['Content-Type'] = 'application/octet-stream';
            return h;
          })(),
          body: unb64(imageBase64)
        };
      } else {
        /* 表单：image=base64 后 urlencode */
        init = {
          method: 'POST',
          headers: mh.headers,
          body: 'image=' + encodeURIComponent(String(imageBase64))
        };
      }
      return fetchJson('https://' + api.host + api.path, init).then(function (r) {
        if (r.__json) return normalizeLegacy(r.__json);
        return r;
      });
    });
  }

  /* 统一入口：按 api.auth 分发 */
  function postImage(apiName, imageBase64, param, secondImage) {
    var api = HTTP_API[apiName];
    if (!api) return Promise.resolve({ ok: false, msg: '未知的讯飞接口：' + apiName });
    var bad = noImage(imageBase64);
    if (bad) return Promise.resolve(bad);
    if (api.auth === 'hmacDigest') return postHmacDigest(apiName, imageBase64, param);
    if (api.auth === 'md5Header') return postMd5Header(apiName, imageBase64, param);
    return postHmacUrl(apiName, imageBase64, param, secondImage);
  }

  /* ---- 各能力的薄封装 ---- */

  /* 印刷文字识别：webapi.xfyun.cn 旧接口，MD5 请求头 + 表单 image。
     language 只能是 'en' 或 'cn|en'（传 'mix0' 会报 10107） */
  function printedText(imageBase64) {
    return postImage('printedText', imageBase64, null);
  }

  /* 手写文字识别：webapi.xfyun.cn 旧接口 */
  function handwriting(imageBase64) {
    return postImage('handwriting', imageBase64, null);
  }

  /* 拍照速算识别：business.ent 固定 math-arith、aue 只支持 raw，
     这两个字段由接口表 photoCalculate.business 提供 */
  function photoCalculate(imageBase64) {
    return postImage('photoCalculate', imageBase64, null);
  }

  /* 人脸检测与属性分析（返回年龄/性别/表情/颜值） */
  function faceDetect(imageBase64) {
    return postImage('faceDetect', imageBase64, null);
  }

  /* 人脸比对：imageBase64=待测人脸，compareImageBase64=底库人脸 */
  function faceCompare(imageBase64, compareImageBase64) {
    var bad = noImage(compareImageBase64);
    if (bad) return Promise.resolve({ ok: false, msg: '还需要第二张人脸照片（底库图）' });
    return postImage('faceCompare', imageBase64, null, compareImageBase64);
  }

  /* 物体识别 */
  function objectRecg(imageBase64) {
    return postImage('objectRecg', imageBase64, null);
  }

  /* 场景识别 */
  function sceneRecg(imageBase64) {
    return postImage('sceneRecg', imageBase64, null);
  }

  /* ============================================================
   * 七、结果解析工具（把讯飞结果压成积木好用的字符串/数字）
   *
   * 各接口真实返回结构（已按官方文档 + 实测核实）：
   *   印刷文字  { pages:[{ lines:[{ words:[{word}] }] }] }
   *   手写文字  { wordsResult:[{ words:[{content}] }] }
   *   拍照速算  { linesResult:[{ words:[{content}],
   *                          imp_line_info:{total_score} }] }
   *   人脸检测  { ret, face_num:N, face_1:{ x,y,w,h, score,
   *                        property:{gender,expression,glass,mask,beard,hair} } }
   *             ⚠ 注意：人脸检测不含年龄与颜值，那是三个独立接口
   *               （tuputech-age / face_score / sex / expression）
   *   人脸比对  { ret, score }
   *   物体/场景 { fileList:[{ label, rate, labels, rates }] }（旧版 data.fileList）
   * ============================================================ */

  function eachLine(obj, push) {
    var keys = ['pages', 'linesResult', 'wordsResult', 'block', 'blocks'];
    for (var i = 0; i < keys.length; i++) {
      var arr = obj && obj[keys[i]];
      if (!Array.isArray(arr) || !arr.length) continue;
      arr.forEach(function (unit) {
        var lines = Array.isArray(unit.lines) && unit.lines.length ? unit.lines : [unit];
        lines.forEach(function (ln) { push(ln, unit); });
      });
      return true;
    }
    return false;
  }

  /* 速算识别的结果结构与 OCR 不同：
       data.ITRResult.recog_result[].line_word_result[] 里
       word_content 是个数组（每行公式一个元素）
     单独抽出来，避免塞进 OCR 那套 words/word 逻辑里。 */
  function eachCalcLine(result, push) {
    var root = result;
    if (root && root.ITRResult) root = root.ITRResult;
    if (root && root.data && root.data.ITRResult) root = root.data.ITRResult;
    var rgs = root && root.recog_result;
    if (!Array.isArray(rgs) || !rgs.length) return false;
    var scores = [];
    var ml = root.multi_line_info;
    if (ml && Array.isArray(ml.imp_line_info)) scores = ml.imp_line_info;
    var idx = 0, found = false;
    rgs.forEach(function (rg) {
      var lwr = Array.isArray(rg.line_word_result) ? rg.line_word_result : [];
      lwr.forEach(function (l) {
        var wc = l.word_content;
        var text = Array.isArray(wc) ? wc.join(' ') : (wc == null ? '' : String(wc));
        var info = scores[idx] || null;
        idx++;
        if (text || info) found = true;
        push({ text: text, imp_line_info: info }, l);
      });
    });
    return found;
  }

  /* OCR 类：把文字拼成文本，一行一段 */
  function ocrText(result) {
    if (!result) return '';
    if (typeof result === 'string') return result;
    var lines = [];

    /* 先试速算结构（data.ITRResult…），命中就直接用公式文本 */
    var calcHit = eachCalcLine(result, function (ln) {
      if (ln.text) lines.push(ln.text);
    });
    if (calcHit && lines.length) return lines.join('\n').trim();

    var hit = eachLine(result, function (ln) {
      /* 印刷文字用 word 字段，其余用 content；同一行内的字先横向拼起来 */
      var s = '';
      if (Array.isArray(ln.words)) {
        ln.words.forEach(function (w) {
          var t = w.word != null ? w.word : w.content;
          if (t) s += String(t);
        });
      } else if (ln.content) {
        s = String(ln.content);
      }
      if (s) lines.push(s);
    });
    if (hit && lines.length) return lines.join('\n').trim();
    /* 兜底：直接的字符串字段 */
    if (result.expression) {
      return result.expression + (result.answer != null ? ' = ' + result.answer : '');
    }
    if (result.content) return String(result.content);
    return lines.join('\n').trim();
  }

  /* 速算答案：从文本里抓「= 后的数字」，抓不到就抓任意数字 */
  function calcAnswer(result) {
    var t = ocrText(result);
    var m = /=\s*(-?\d+(?:\.\d+)?)/.exec(t) || /(-?\d+(?:\.\d+)?)/.exec(t);
    return m ? parseFloat(m[1]) : 0;
  }

  /* 速算判分：讯飞用 imp_line_info.total_score，1 对 0 错。
     多行时取「全部正确」——任一行错则整体错。
     官方结构是 data.ITRResult.{recog_result, multi_line_info}，
     eachCalcLine 已把两侧按顺序配对好了。 */
  function calcCorrect(result) {
    var seen = false, allRight = true;
    eachCalcLine(result, function (ln) {
      var info = ln.imp_line_info;
      if (info && info.total_score != null) {
        seen = true;
        var s = Number(info.total_score);
        if (!(s === 1 || s > 0.5)) allRight = false;
      }
    });
    if (seen) return allRight;
    /* 兼容旧结构（linesResult[].imp_line_info） */
    eachLine(result, function (ln, unit) {
      var info = ln.imp_line_info || (unit && unit.imp_line_info);
      if (info && info.total_score != null) {
        seen = true;
        var s = Number(info.total_score);
        if (!(s === 1 || s > 0.5)) allRight = false;
      }
    });
    return seen ? allRight : null;
  }

  /* 速算异常码：attr_exception 非 0 时结果不可信
     0x0 正常；0x7011 空白图（文档明确列出） */
  function calcException(result) {
    var root = result;
    if (root && root.data && root.data.ITRResult) root = root.data.ITRResult;
    if (root && root.ITRResult) root = root.ITRResult;
    var v = root && root.attr_exception;
    return v == null ? 0 : Number(v);
  }

  /* 取第 n 张人脸（face_num + face_1 / face_2 …） */
  function faceAt(result, n) {
    if (!result) return null;
    var i = n || 1;
    if (result['face_' + i]) return result['face_' + i];
    /* 兼容有的版本直接给 face_result 数组 */
    if (Array.isArray(result.face_result)) return result.face_result[i - 1] || null;
    if (Array.isArray(result.faceResult)) return result.faceResult[i - 1] || null;
    return null;
  }

  /* 人脸数量：优先信 face_num */
  function faceCount(result) {
    if (!result) return 0;
    if (typeof result.face_num === 'number') return result.face_num;
    if (Array.isArray(result.face_result)) return result.face_result.length;
    if (Array.isArray(result.faceResult)) return result.faceResult.length;
    if (result.face_1) return 1;
    return 0;
  }

  /* 人脸属性 → 「女 高兴 戴眼镜」
     官方取值：gender 0=男 1=女；expression 0惊讶 1害怕 2厌恶 3高兴 4悲伤 5生气 6正常；
               glass 0不戴 1戴；mask 0没戴 1戴；beard 0无 1有；hair 0光头 1短发 2长发 */
  function faceAttr(result, n) {
    var fr = faceAt(result, n);
    if (!fr) return '';
    var p = fr.property || fr;
    function v(x) {
      if (x == null) return null;
      return (typeof x === 'object' && x.value != null) ? x.value : x;
    }
    var GENDER = { 0: '男', 1: '女' };
    var EXPR = { 0: '惊讶', 1: '害怕', 2: '厌恶', 3: '高兴', 4: '悲伤', 5: '生气', 6: '正常' };
    var HAIR = { 0: '光头', 1: '短发', 2: '长发' };
    var out = [];

    var g = v(p.gender);
    if (g != null && GENDER[String(g)]) out.push(GENDER[String(g)]);

    var e = v(p.expression);
    if (e != null && EXPR[String(e)]) out.push(EXPR[String(e)]);

    if (v(p.glass) === 1 || v(p.glass) === '1') out.push('戴眼镜');
    if (v(p.mask) === 1 || v(p.mask) === '1') out.push('戴口罩');
    if (v(p.beard) === 1 || v(p.beard) === '1') out.push('有胡须');

    /* 年龄与颜值来自独立接口，若调用方合并进来则一并显示 */
    var age = v(p.age);
    if (age != null) out.push(Math.round(Number(age)) + '岁');
    var beauty = v(p.beauty != null ? p.beauty : p.Beauty);
    if (beauty != null) {
      var bn = Number(beauty);
      out.push('颜值' + Math.round(bn <= 1 ? bn * 100 : bn));
    }

    /* 人脸框置信度也带出来，方便判断识别是否可靠 */
    var score = v(fr.score);
    if (score != null && out.length) {
      out.push('可信' + Math.round(Number(score) * 100) + '%');
    }
    return out.join(' ');
  }

  /* 人脸框位置（返回第 n 张的 {x,y,w,h}），用于在画面上画框 */
  function faceBox(result, n) {
    var fr = faceAt(result, n);
    if (!fr || fr.x == null) return null;
    return {
      x: Number(fr.x) || 0, y: Number(fr.y) || 0,
      w: Number(fr.w) || 0, h: Number(fr.h) || 0,
      score: Number(fr.score) || 0
    };
  }

  /* 人脸比对得分（0~1，>0.67 判为同一人） */
  function faceScore(result) {
    if (!result) return 0;
    var s = result.score != null ? result.score
      : (result.faceScore != null ? result.faceScore : 0);
    return Math.round((Number(s) || 0) * 100) / 100;
  }

  /* 物体 / 场景识别 → [{name, score}] 按分数降序 */
  function recgTags(result) {
    var list = null;
    if (!result) return [];
    /* 旧接口：data.fileList */
    if (Array.isArray(result.fileList)) list = result.fileList;
    else if (Array.isArray(result)) list = result;
    else if (Array.isArray(result.result)) list = result.result;
    else if (Array.isArray(result.object_result)) list = result.object_result;
    else if (Array.isArray(result.scene_result)) list = result.scene_result;
    if (!list) return [];
    return list.map(function (r) {
      return {
        label: r.label,
        name: (r.name || sceneLabel(r.label) || '未知'),
        score: Math.round((Number(r.rate != null ? r.rate
          : (r.score != null ? r.score : r.confidence)) || 0) * 1000) / 1000
      };
    }).sort(function (a, b) { return b.score - a.score; });
  }

  /* 场景 label → 中文（讯飞官方场景表，label=-1 为图片错误） */
  var SCENE_LABELS = {
    0: '卧室', 1: '教室', 2: '餐厅(公共)', 3: '草地', 4: '沙漠', 5: '办公室',
    6: '酒吧', 7: '室内运动场', 8: '商场', 9: '山峰', 10: '湖/池塘/海洋',
    11: '森林', 12: '街道', 13: '室外运动场', 14: '海滩', 15: '泳池',
    16: '游乐场', 17: '没有场景', 18: '其他场景', 19: '车内/船上/飞机上',
    20: '礼堂', 21: '广场', 22: '纯人物图', 23: '播音室', 24: '房屋/建筑',
    25: '医院', 26: '网吧/游戏厅', 27: '雕塑/石碑', 28: '宿舍', 29: '化妆室/理发店',
    30: '健身房', 31: '机场', 32: '火车站', 33: '汽车站', 34: '市场/集市',
    35: '图书馆/书店', 36: '公路', 37: '古建筑', 38: '厨房', 39: '餐厅(家里)',
    40: '洗手间', 41: '浴室', 42: '停车场'
  };
  function sceneLabel(label) {
    if (label == null) return '';
    if (SCENE_LABELS[label]) return SCENE_LABELS[label];
    return label === -1 ? '图片错误' : '';
  }

  /* 能力清单：给设置界面展示「哪个能力用哪套凭据、走哪种协议」 */
  var CAPABILITIES = [
    { key: 'faceDetect', cn: '人脸检测与属性', group: 'speech', auth: 'HMAC-URL', need2: false },
    { key: 'faceCompare', cn: '人脸比对', group: 'speech', auth: 'HMAC-URL', need2: true },
    /* ⚠ 印刷文字/手写文字是 webapi.xfyun.cn 的 MD5 请求头接口；
       ⚠ 拍照速算用 Digest 协议，需要 apiSecret，所以归到 speech 组 */
    { key: 'printedText', cn: '印刷文字识别', group: 'text', auth: 'MD5 请求头', need2: false },
    { key: 'handwriting', cn: '手写文字识别', group: 'text', auth: 'MD5 请求头', need2: false },
    { key: 'photoCalculate', cn: '拍照速算识别', group: 'speech', auth: 'HMAC-Digest', need2: false },
    { key: 'objectRecg', cn: '物体识别', group: 'image', auth: 'MD5 请求头', need2: false },
    { key: 'sceneRecg', cn: '场景识别', group: 'image', auth: 'MD5 请求头', need2: false }
  ];

  ZKB.Xfyun = {
    DEFAULT_CREDS: DEFAULT_CREDS,
    TTS_VOICES: TTS_VOICES,
    WS_API: WS_API,
    HTTP_API: HTTP_API,
    CAPABILITIES: CAPABILITIES,
    SCENE_LABELS: SCENE_LABELS,
    LS_KEY: LS_KEY,

    creds: creds,
    setCreds: setCreds,
    resetCreds: resetCreds,
    isCustom: isCustom,
    rfc1123: rfc1123,

    speak: speak,
    listen: listen,
    setRecordMs: setRecordMs,
    getRecordMs: getRecordMs,

    printedText: printedText,
    handwriting: handwriting,
    photoCalculate: photoCalculate,
    faceDetect: faceDetect,
    faceCompare: faceCompare,
    objectRecg: objectRecg,
    sceneRecg: sceneRecg,

    ocrText: ocrText,
    calcAnswer: calcAnswer,
    calcCorrect: calcCorrect,
    calcException: calcException,
    eachCalcLine: eachCalcLine,
    faceAttr: faceAttr,
    faceCount: faceCount,
    faceScore: faceScore,
    recgTags: recgTags,
    sceneLabel: sceneLabel,

    /* 供测试与调试 */
    _b64: b64,
    _unb64: unb64,
    _md5: md5,
    _authorization: authorization,
    _signedUrl: signedUrl,
    _digestHeaders: digestHeaders,
    _md5Headers: md5Headers,
    _postImage: postImage,
    _normalizeJson: normalizeJson,
    _normalizeLegacy: normalizeLegacy
  };
})(window);