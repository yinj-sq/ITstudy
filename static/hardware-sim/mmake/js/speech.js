/* ============================================================
 * speech.js —— AI 语音能力（语音转文字 + 文字转语音）
 *
 * 两个方向的能力，都能在虚拟仿真里真的跑起来：
 *
 * 1. AI 语音转文字（ASR, Automatic Speech Recognition）
 *    - 课堂常用指令库（开灯 / 关灯 / 播放音乐 …）+ 自定义句子
 *    - 支持「连续聆听」模式：识别到指令后自动重新开始，方便做人机对话
 *    - 置信度随「麦克风音量」起伏：声音太小声识别不准（贴近真实体感）
 *
 * 2. AI 语音合成（TTS, Text To Speech）
 *    - 优先调用浏览器内置的 SpeechSynthesis（真正发声，可在系统里静音调节）
 *    - 不支持时降级为「模拟朗读」：按字数估算时长并驱动界面上的声波动画
 *    - 支持语速 / 音调 / 音量三个下拉，对应 Web Speech API 的 rate/pitch/volume
 *
 * 状态挂在 ZKB.state.speech 上，仿真运行时（S）与积木生成器共用同一份数据。
 * ============================================================ */
(function (global) {
  'use strict';
  var ZKB = global.ZKB;

  /* ---------------- 课堂常用指令库 ---------------- */
  /* 与「WiFi 语音识别」拓展设备的预设保持一致（旧工程兼容） */
  var ASR_PRESET = ['开灯', '关灯', '开风扇', '关风扇', '播放音乐', '停止'];
  /* 语音转文字的更完整指令池（供下拉选择与随机识别使用） */
  var ASR_COMMANDS = [
    '开灯', '关灯', '打开电灯', '关闭电灯', '开风扇', '关风扇',
    '播放音乐', '停止音乐', '下一首', '上一首',
    '打开窗帘', '关上窗帘', '开始上课', '下课了',
    '今天天气怎么样', '几点了', '你叫什么名字',
    '前进', '后退', '左转', '右转', '停下',
    '打开电视', '关闭电视', '打开空调', '把灯调亮一点'
  ];

  var TTS_VOICES_HINT = ['zh-CN', 'zh_CN', 'zh-Hans', 'cmn-Hans-CN'];

  function state() {
    if (!ZKB.state) ZKB.state = {};
    if (!ZKB.state.speech) {
      ZKB.state.speech = {
        /* ASR */
        asrText: '开灯',
        asrConf: 96,
        asrSource: 'sim',        /* sim | cam | typed */
        asrListening: false,
        asrHistory: [],
        /* TTS */
        ttsText: '',
        ttsSpeaking: false,
        ttsDone: false,
        ttsCount: 0,
        ttsSource: 'none'        /* none | web | sim */
      };
    }
    return ZKB.state.speech;
  }

  /* ============================================================
   * 一、AI 语音转文字（ASR）
   * ============================================================ */

  function rand(arr) { return arr[Math.floor(Math.random() * arr.length)]; }

  /* 按音量估算置信度：太小声识别不准（0~0.2 几乎听不清） */
  function confByVolume(vol) {
    var v = vol == null ? 0.6 : Math.max(0, Math.min(1, vol / 4095));
    if (v < 0.12) return 20 + Math.round(v * 100);        /* 20~32 */
    if (v < 0.3) return 45 + Math.round((v - 0.12) * 160); /* 45~74 */
    return 78 + Math.round(Math.min(1, v) * 21);          /* 78~99 */
  }

  /* 启动一次语音转文字。
     vol：麦克风音量（0~4095），null 时按随机音量估算。
     cmd：指定要识别的内容（积木下拉），null 时从指令库随机抽。*/
  function asrStart(cmd, vol) {
    var st = state();
    var text = cmd ? String(cmd) : rand(ASR_COMMANDS);
    /* 用户显式选了指令时视为「说得很清楚」，置信度偏高 */
    var conf = cmd ? Math.min(99, 92 + Math.round(Math.random() * 7))
      : confByVolume(vol == null ? 400 + Math.random() * 3000 : vol);
    st.asrText = text;
    st.asrConf = conf;
    st.asrSource = (ZKB.state.net && ZKB.state.net.asr && ZKB.state.net.asr.real)
      ? 'cam' : 'sim';
    st.asrDone = true;
    st.asrHistory.unshift({ text: text, conf: conf, t: Date.now() });
    if (st.asrHistory.length > 12) st.asrHistory.pop();
    /* 同步到 WiFi 语音识别设备卡片（旧积木 zk_asr_text 也能读到） */
    if (ZKB.state.net && ZKB.state.net.asr) ZKB.state.net.asr.text = text;
    ZKB.log && ZKB.log('🎤 语音转文字 → ' + text + '（置信度 ' + conf + '%）', 'log-sim');
    notify();      /* 广播：让传感器面板与掌控板语音小窗口同步显示 */
    return text;
  }

  function asrText() { return state().asrText || ''; }
  function asrConf() { return state().asrConf || 0; }
  function asrIs(cmd) {
    var t = state().asrText || '';
    return String(cmd || '').length > 0 && t.indexOf(String(cmd)) >= 0;
  }
  /* 置信度是否达标（下拉：不限 / 较高 / 很高） */
  function asrConfLevel(level) {
    var c = asrConf();
    if (level === 'high') return c >= 80;
    if (level === 'veryhigh') return c >= 92;
    return true;
  }
  function asrListening(on) {
    var st = state();
    st.asrListening = on === undefined ? !st.asrListening : !!on;
    return st.asrListening;
  }
  function asrHistory() { return state().asrHistory.slice(); }

  /* ============================================================
   * 二、AI 语音合成（TTS）
   * ============================================================ */

  var synth = null;
  function getSynth() {
    if (synth !== null) return synth;
    try {
      synth = global.speechSynthesis && typeof global.SpeechSynthesisUtterance === 'function'
        ? global.speechSynthesis : false;
    } catch (e) { synth = false; }
    return synth;
  }

  /* 挑一个中文发音人（拿不到就用系统默认） */
  function pickVoice() {
    var s = getSynth();
    if (!s) return null;
    var list = [];
    try { list = s.getVoices() || []; } catch (e) { return null; }
    if (!list.length) return null;
    for (var i = 0; i < list.length; i++) {
      var lang = String(list[i].lang || '').replace('_', '-');
      if (TTS_VOICES_HINT.indexOf(lang) >= 0 || TTS_VOICES_HINT.indexOf(list[i].lang) >= 0) {
        return list[i];
      }
    }
    return null;
  }

  /* 模拟朗读时长：中文按每字 0.18s 估算，最短 0.4s */
  function simDuration(text, rate) {
    var n = String(text || '').replace(/\s/g, '').length || 1;
    var r = rate == null ? 1 : Math.max(0.5, Math.min(2, rate));
    return Math.max(400, Math.round(n * 180 / r));
  }

  var simTimer = null;

  /* 把文字读出来。rate/pitch/volume 与Web Speech API 同义（0.5~2 / 0~2 / 0~1）。
     返回 Promise：resolve(true) 表示朗读请求已成功发起（不是等念完）。*/
  function speak(text, rate, pitch, volume) {
    var st = state();
    var txt = String(text == null ? '' : text);
    stop();     /* 打断上一句，避免连点时叠音 */
    if (!txt) {
      st.ttsSpeaking = false;
      st.ttsDone = true;
      return Promise.resolve(false);
    }
    var r = rate == null ? 1 : Math.max(0.5, Math.min(2, rate));
    var p = pitch == null ? 1 : Math.max(0, Math.min(2, pitch));
    var v = volume == null ? 1 : Math.max(0, Math.min(1, volume));

    st.ttsText = txt;
    st.ttsSpeaking = true;
    st.ttsDone = false;
    st.ttsCount = (st.ttsCount || 0) + 1;

    var s = getSynth();
    /* 优先真发声 */
    if (s && typeof global.SpeechSynthesisUtterance === 'function') {
      try {
        var u = new global.SpeechSynthesisUtterance(txt);
        u.rate = r; u.pitch = p; u.volume = v;
        u.lang = 'zh-CN';
        var vc = pickVoice();
        if (vc) u.voice = vc;
        u.onend = function () { finish(true); };
        u.onerror = function () { finish(false); };
        s.speak(u);
        st.ttsSource = 'web';
        ZKB.log && ZKB.log('🔊 语音合成（浏览器发音）：' + txt, 'log-sim');
        return Promise.resolve(true);
      } catch (e) { /* 落到模拟朗读 */ }
    }
    /* 降级：模拟朗读（驱动声波动画与「正在朗读」状态） */
    st.ttsSource = 'sim';
    var dur = simDuration(txt, r);
    ZKB.log && ZKB.log('🔊 语音合成（模拟朗读 ' + (dur / 1000).toFixed(1) + 's）：' + txt, 'log-sim');
    if (simTimer) clearTimeout(simTimer);
    simTimer = setTimeout(function () { finish(true); }, dur);
    return Promise.resolve(true);
  }

  function finish(ok) {
    var st = state();
    st.ttsSpeaking = false;
    st.ttsDone = !!ok;
    if (simTimer) { clearTimeout(simTimer); simTimer = null; }
    notify();
  }

  function stop() {
    var st = state();
    if (simTimer) { clearTimeout(simTimer); simTimer = null; }
    var s = getSynth();
    if (s) { try { s.cancel(); } catch (e) { } }
    st.ttsSpeaking = false;
    st.ttsDone = true;
    notify();
  }

  function speaking() { return !!state().ttsSpeaking; }
  function done() { return !!state().ttsDone; }
  function lastText() { return state().ttsText || ''; }

  /* 等待朗读完毕（供「播放完毕」积木轮询用；超时兜底避免死循环） */
  function waitDone(timeoutMs) {
    var st = state();
    var limit = timeoutMs || 15000;
    var t0 = Date.now();
    return new Promise(function (resolve) {
      (function poll() {
        if (!st.ttsSpeaking) return resolve(true);
        if (Date.now() - t0 > limit) return resolve(false);
        setTimeout(poll, 80);
      })();
    });
  }

  /* ============================================================
   * 界面联动：语音合成时在控制台画声波、结束时停止
   * ============================================================ */
  function notify() {
    try {
      if (ZKB.log) { /* 日志已在 speak/stop 里打，这里只负责状态广播 */ }
      if (typeof global.dispatchEvent === 'function' && global.CustomEvent) {
        global.dispatchEvent(new global.CustomEvent('zk-speech', {
          detail: { speaking: speaking(), text: lastText() }
        }));
      }
    } catch (e) { }
  }

  ZKB.Speech = {
    ASR_PRESET: ASR_PRESET,
    ASR_COMMANDS: ASR_COMMANDS,
    /* ASR */
    asrStart: asrStart,
    asrText: asrText,
    asrConf: asrConf,
    asrIs: asrIs,
    asrConfLevel: asrConfLevel,
    asrListening: asrListening,
    asrHistory: asrHistory,
    confByVolume: confByVolume,
    /* TTS */
    speak: speak,
    stop: stop,
    speaking: speaking,
    done: done,
    lastText: lastText,
    waitDone: waitDone,
    simDuration: simDuration,
    hasWebVoice: function () { return !!getSynth(); },
    _state: state
  };

})(window);