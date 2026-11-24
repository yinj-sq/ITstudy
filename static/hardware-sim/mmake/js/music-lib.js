/* ============================================================
 * music-lib.js —— 音乐库（内置曲目 + 上传音频）
 * ------------------------------------------------------------
 * · 内置若干常见简短曲目（一闪一闪亮晶晶、小星星、生日歌、
 *   两只老虎、欢乐颂、幸福拍手歌等），以「音符 + 时值」序列
 *   描述，播放时用 Web Audio 实时合成（方波音色，接近蜂鸣器），
 *   无需外部音频文件，离线可用。
 * · 支持上传音频文件（MP3 / WAV / OGG / M4A），用 HTMLAudio
 *   播放；上传文件以 dataURL 存到 localStorage。
 * · 上传限制：单文件 ≤ 3MB，格式白名单，超出则拒绝并提示。
 * · 对外接口：ZKB.MusicLib = { list, get, add, remove, play, stop,
 *   isPlaying, current, MAX_BYTES, ALLOW, builtin }
 * ============================================================ */
(function (global) {
  var ZKB = global.ZKB = global.ZKB || {};

  /* ---------------- 上传限制 ---------------- */
  var MAX_BYTES = 3 * 1024 * 1024;                 // 单文件 ≤ 3MB
  var ALLOW = ['audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/x-wav',
    'audio/wave', 'audio/ogg', 'audio/aac', 'audio/mp4', 'audio/x-m4a'];
  var ALLOW_EXT = /\.(mp3|wav|ogg|m4a|aac)$/i;
  var STORE_KEY = 'zkb_music_lib_v1';

  /* ---------------- 音符频率表 ---------------- */
  var NOTE = {
    C4: 261.63, D4: 293.66, E4: 329.63, F4: 349.23, G4: 392.00, A4: 440.00, B4: 493.88,
    C5: 523.25, D5: 587.33, E5: 659.25, F5: 698.46, G5: 783.99, A5: 880.00, B5: 987.77,
    C6: 1046.50, D6: 1174.66, E6: 1318.51, G3: 196.00, A3: 220.00, B3: 246.94,
    F3: 174.61, E3: 164.81, D3: 146.83, C3: 130.81
  };
  /* 简谱字符 → 频率（含低音点 / 高音点） */
  var SOLFEGE = {
    '1': NOTE.C4, '2': NOTE.D4, '3': NOTE.E4, '4': NOTE.F4, '5': NOTE.G4,
    '6': NOTE.A4, '7': NOTE.B4, '1+': NOTE.C5, '2+': NOTE.D5, '3+': NOTE.E5,
    '4+': NOTE.F5, '5+': NOTE.G5, '6+': NOTE.A5, '7+': NOTE.B5,
    '0': 0   // 休止
  };

  /* ---------------- 内置曲目 ----------------
     seq: [音, 时值(拍)]，时值单位为「拍」，1 拍 = tempo/60 秒
     base: 基准速度 bpm */
  var BUILTIN = [
    {
      id: 'twinkle', name: '一闪一闪亮晶晶', base: 112,
      seq: [['1', 1], ['1', 1], ['5', 1], ['5', 1], ['6', 1], ['6', 1], ['5', 2],
      ['4', 1], ['4', 1], ['3', 1], ['3', 1], ['2', 1], ['2', 1], ['1', 2],
      ['5', 1], ['5', 1], ['4', 1], ['4', 1], ['3', 1], ['3', 1], ['2', 2],
      ['5', 1], ['5', 1], ['4', 1], ['4', 1], ['3', 1], ['3', 1], ['2', 2],
      ['1', 1], ['1', 1], ['5', 1], ['5', 1], ['6', 1], ['6', 1], ['5', 2],
      ['4', 1], ['4', 1], ['3', 1], ['3', 1], ['2', 1], ['2', 1], ['1', 2]]
    },
    {
      id: 'star', name: '小星星', base: 100,
      seq: [['1', 1], ['1', 1], ['5', 1], ['5', 1], ['6', 1], ['6', 1], ['5', 2],
      ['4', 1], ['4', 1], ['3', 1], ['3', 1], ['2', 1], ['2', 1], ['1', 2],
      ['5', 1], ['5', 1], ['4', 1], ['4', 1], ['3', 1], ['3', 1], ['2', 2],
      ['1', 1], ['1', 1], ['5', 1], ['5', 1], ['6', 1], ['6', 1], ['5', 2],
      ['4', 1], ['4', 1], ['3', 1], ['3', 1], ['2', 1], ['2', 1], ['1', 2]]
    },
    {
      id: 'birthday', name: '生日快乐', base: 120,
      seq: [['5', 0.75], ['5', 0.25], ['5', 0.75], ['5', 0.25], ['5', 0.75], ['3', 0.5],
      ['1', 0.75], ['1', 0.25], ['1', 0.75], ['7', 0.25], ['7', 0.75], ['6', 0.5],
      ['5', 0.75], ['5', 0.25], ['5', 0.75], ['3', 0.25], ['3', 0.75], ['2', 0.5],
      ['1', 0.75], ['1', 0.25], ['1', 0.75], ['5', 0.25], ['5', 0.75], ['3', 0.5],
      ['1', 1], ['3', 1], ['5', 1], ['4', 2]]
    },
    {
      id: 'twotigers', name: '两只老虎', base: 116,
      seq: [['1', 1], ['2', 1], ['3', 1], ['1', 1], ['1', 1], ['2', 1], ['3', 1], ['1', 1],
      ['3', 1], ['4', 1], ['5', 2], ['3', 1], ['4', 1], ['5', 2],
      ['5-', 0.75], ['6-', 0.25], ['5-', 0.75], ['4-', 0.25], ['3-', 1], ['1', 1],
      ['1', 1], ['2', 1], ['3', 1], ['1', 1], ['1', 1], ['2', 1], ['3', 1], ['1', 1],
      ['3', 1], ['4', 1], ['5', 2], ['3', 1], ['4', 1], ['5', 2]]
    },
    {
      id: 'ode', name: '欢乐颂', base: 108,
      seq: [['3', 1], ['4', 1], ['5', 1], ['3', 1], ['3', 1], ['4', 1], ['5', 2],
      ['3', 1], ['4', 1], ['5', 1], ['3', 1], ['5-', 1], ['4-', 1], ['3', 1],
      ['2', 1], ['1', 1], ['2', 1], ['3', 1], ['3', 1], ['2', 1], ['2', 2],
      ['3', 1], ['4', 1], ['5', 1], ['3', 1], ['3', 1], ['4', 1], ['5', 2],
      ['5', 1], ['4', 1], ['3', 1], ['4', 1], ['3', 2]]
    },
    {
      id: 'clap', name: '幸福拍手歌', base: 120,
      seq: [['5', 1], ['5', 1], ['3', 1], ['1', 1], ['2', 1], ['2', 1], ['1', 2],
      ['5', 1], ['5', 1], ['3', 1], ['1', 1], ['2', 1], ['2', 1], ['1', 2],
      ['5', 1], ['5', 1], ['5-', 1], ['3', 1], ['1', 1], ['1', 1], ['2', 2], ['3', 2],
      ['5', 1], ['5', 1], ['5-', 1], ['3', 1], ['1', 1], ['1', 1], ['2', 2], ['3', 2],
      ['1', 1], ['2', 1], ['3', 1], ['4', 1], ['3', 1], ['2', 1], ['1', 2]]
    },
    {
      id: 'scale', name: '音阶练习 C大调', base: 120,
      seq: [['1', 1], ['2', 1], ['3', 1], ['4', 1], ['5', 1], ['6', 1], ['7', 1],
      ['1+', 2], ['7', 1], ['6', 1], ['5', 1], ['4', 1], ['3', 1], ['2', 1],
      ['1', 2]]
    },
    {
      id: 'mary', name: '玛丽有只小羊羔', base: 108,
      seq: [['3', 1], ['2', 1], ['1', 2], ['2', 1], ['1', 2],
      ['3', 1], ['2', 1], ['1', 2], ['2', 1], ['1', 2],
      ['5', 1], ['3', 1], ['2', 1], ['1', 2]]
    }
  ];
  /* 低音点「-」的频率表（3- / 4- / 5- / 6- 等） */
  var LOW = { '1-': NOTE.C3, '2-': NOTE.D3, '3-': NOTE.E3, '4-': NOTE.F3, '5-': NOTE.G3, '6-': NOTE.A3, '7-': NOTE.B3 };

  /* ---------------- 存储 ---------------- */
  function loadUploads() {
    try {
      var raw = ZKB.Store && ZKB.Store.getLocal ? ZKB.Store.getLocal(STORE_KEY) : null;
      if (typeof raw === 'string') raw = JSON.parse(raw || '[]');
      return Array.isArray(raw) ? raw : [];
    } catch (e) { return []; }
  }
  function saveUploads(list) {
    try {
      if (ZKB.Store && ZKB.Store.setLocal) ZKB.Store.setLocal(STORE_KEY, JSON.stringify(list));
    } catch (e) {
      ZKB.toast && ZKB.toast('音乐保存失败：浏览器存储空间不足，请删除一些上传的音乐');
    }
  }

  /* ---------------- 音频上下文 ---------------- */
  var actx = null;
  function ctx() {
    if (actx) return actx;
    try {
      var AC = global.AudioContext || global.webkitAudioContext;
      if (!AC) return null;
      actx = new AC();
    } catch (e) { actx = null; }
    return actx;
  }
  function resume() {
    var c = ctx();
    if (c && c.state === 'suspended' && c.resume) c.resume();
    return c;
  }

  /* ---------------- 播放状态 ---------------- */
  var state = {
    curId: '',     // 正在播放的曲目 id
    mode: '',      // once | loop | bgOnce | bgLoop
    stopped: true,
    bgm: null,     // 上传音频的 <audio> 实例
    oscs: []       // 第四十四轮：记录内置曲目正在发声的 oscillator
  };

  function freqOf(name) {
    if (!name) return 0;
    if (name === '0') return 0;                   // 休止
    if (LOW[name] != null) return LOW[name];
    if (SOLFEGE[name] != null) return SOLFEGE[name];
    return NOTE[name] || 0;
  }

  /* 用方波合成一段内置曲目 */
  function playBuiltin(tr, bpm, loop, onEnd) {
    var c = resume();
    if (!c) { ZKB.toast && ZKB.toast('当前浏览器不支持音频播放'); return false; }
    var spb = 60 / Math.max(30, bpm || tr.base || 120);   // 每拍秒数
    var t0 = c.currentTime + 0.06;
    var t = t0;
    var gain = c.createGain();
    gain.gain.value = 0.16;
    gain.connect(c.destination);
    /* 第四十四轮：把这一段用到的 oscillator 记下来。
       原来 stop() 只清了定时器，已经启动的 oscillator 仍在发声，
       切到下一首时两首会叠着响。 */
    var mine = [];
    tr.seq.forEach(function (pair) {
      var f = freqOf(pair[0]);
      var dur = Math.max(0.06, pair[1] * spb);
      if (f > 0) {
        var o = c.createOscillator();
        o.type = 'square';
        o.frequency.value = f;
        o.connect(gain);
        o.start(t);
        o.stop(t + dur * 0.92);
        mine.push(o);
      }
      t += dur;
    });
    state.oscs = mine;
    var total = t - t0;
    state.timer = global.setTimeout(function () {
      if (loop) { playBuiltin(tr, bpm, true, onEnd); return; }
      state.stopped = true;
      state.curId = '';
      state.oscs = [];
      if (onEnd) onEnd();
    }, total * 1000 + 80);
    return true;
  }

  /* 播放上传的音频 */
  function playUpload(tr, loop, bg, onEnd) {
    var a = state.bgm;
    if (!a) {
      a = state.bgm = new global.Audio();
      a.preload = 'auto';
    }
    a.src = tr.url;
    a.loop = !!loop;
    a.volume = 1;
    state.curId = tr.id;
    state.mode = bg ? 'bgLoop' : (loop ? 'loop' : 'once');
    state.stopped = false;
    a.onended = function () {
      /* 第四十四轮：换歌时旧音频的 ended 事件也会触发，
         如果不核对曲目 id，就会把「已切走的那首」重新播起来。
         这里只在还是当前这首时才继续。 */
      if (state.curId !== tr.id) return;
      if (!loop && onEnd) onEnd();
      if (loop) { try { a.currentTime = 0; a.play(); } catch (e) { } }
    };
    try {
      var p = a.play();
      if (p && p.then) p.then(function () {}).catch(function () {
        ZKB.toast && ZKB.toast('音频播放被浏览器拦截，请再点击一次播放按钮');
      });
    } catch (e) {
      ZKB.toast && ZKB.toast('音频播放失败：' + e.message);
      return false;
    }
    return true;
  }

  /* ---------------- 对外接口 ---------------- */
  function builtin() { return BUILTIN.slice(); }

  function list() {
    var up = loadUploads();
    return BUILTIN.map(function (t) {
      return { id: t.id, name: t.name, kind: 'builtin', bpm: t.base, notes: t.seq.length };
    }).concat(up.map(function (t) {
      return {
        id: t.id, name: t.name, kind: 'upload', bpm: 0,
        size: t.size, mime: t.mime, url: t.url
      };
    }));
  }

  function get(id) {
    var i;
    for (i = 0; i < BUILTIN.length; i++) if (BUILTIN[i].id === id) return BUILTIN[i];
    var up = loadUploads();
    for (i = 0; i < up.length; i++) if (up[i].id === id) return up[i];
    return null;
  }

  function isBuiltin(id) {
    for (var i = 0; i < BUILTIN.length; i++) if (BUILTIN[i].id === id) return true;
    return false;
  }

  /**
   * 播放音乐
   * @param {string} id 曲目 id
   * @param {string} mode once | loop | bgOnce | bgLoop
   */
  function play(id, mode) {
    mode = mode || 'once';
    stop();
    var tr = get(id);
    if (!tr) { ZKB.toast && ZKB.toast('未找到该曲目：' + id); return false; }
    var loop = (mode === 'loop' || mode === 'bgLoop');
    var bg = (mode === 'bgOnce' || mode === 'bgLoop');
    state.curId = id;
    state.mode = mode;
    state.stopped = false;
    if (isBuiltin(id)) {
      return playBuiltin(tr, tr.base, loop, function () { state.curId = ''; });
    }
    return playUpload(tr, loop, bg, function () { state.curId = ''; });
  }

  function stop() {
    if (state.timer) { global.clearTimeout(state.timer); state.timer = null; }
    /* 第四十四轮：真正停掉内置曲目正在发声的 oscillator。
       原来只清了定时器，已经 start() 的振荡器还在响，
       切到下一首时两首叠着播。 */
    if (state.oscs && state.oscs.length) {
      state.oscs.forEach(function (o) {
        try { o.stop(); } catch (e) { /* 已经停了 */ }
        try { o.disconnect(); } catch (e) { }
      });
      state.oscs = [];
    }
    if (state.bgm) {
      /* 切换曲目时先 pause，避免上一首还在放 */
      try { state.bgm.pause(); } catch (e) { }
      try { state.bgm.currentTime = 0; } catch (e) { }
    }
    state.stopped = true;
    state.curId = '';
  }

  /* 第四十四轮：暂停 / 继续（给素材库的播放/暂停按钮用） */
  function pause() {
    if (state.bgm) {
      try { state.bgm.pause(); } catch (e) { }
    }
    /* 内置曲目是实时合成的，暂停 = 停止（从头再来用 play） */
    if (!state.bgm) {
      if (state.timer) { global.clearTimeout(state.timer); state.timer = null; }
      if (state.oscs && state.oscs.length) {
        state.oscs.forEach(function (o) {
          try { o.stop(); } catch (e) { }
          try { o.disconnect(); } catch (e) { }
        });
        state.oscs = [];
      }
    }
    state.stopped = true;
    state.curId = '';
  }

  function isPlaying() { return !state.stopped; }
  function current() { return state.curId; }

  /**
   * 上传音频
   * @param {File} file
   * @param {function(Error, Object)} cb
   */
  function add(file, cb) {
    cb = cb || function () {};
    function done(err, res) { cb(err, res); }
    if (!file) return done(new Error('未选择文件'));
    /* 大小限制 */
    if (file.size > MAX_BYTES) {
      return done(new Error('文件过大：' + (file.size / 1048576).toFixed(2) +
        'MB，超过 3MB 上限'));
    }
    /* 格式限制：优先看 MIME，再看扩展名（部分系统 file.type 为空） */
    var extOk = ALLOW_EXT.test(file.name || '');
    var mimeOk = file.type ? (ALLOW.indexOf(file.type.toLowerCase()) >= 0) : false;
    if (!mimeOk && !extOk) {
      return done(new Error('格式不支持：仅支持 MP3 / WAV / OGG / M4A 音频'));
    }
    var reader = new global.FileReader();
    reader.onload = function () {
      try {
        var url = String(reader.result || '');
        var up = loadUploads();
        var id = 'mus_' + Date.now().toString(36);
        var item = {
          id: id,
          name: (file.name || '未命名').replace(/\.[^.]+$/, ''),
          mime: file.type || (extOk ? 'audio/mpeg' : ''),
          size: file.size,
          url: url
        };
        up.push(item);
        saveUploads(up);
        done(null, item);
      } catch (e) {
        done(new Error('保存失败：' + (e.message || e)));
      }
    };
    reader.onerror = function () { done(new Error('文件读取失败')); };
    try { reader.readAsDataURL(file); } catch (e) { done(new Error('文件读取失败')); }
  }

  function remove(id) {
    var up = loadUploads();
    var n = up.length;
    up = up.filter(function (t) { return t.id !== id; });
    if (up.length !== n) { saveUploads(up); return true; }
    return false;
  }

  /** 积木下拉选项：[['曲目名', id], …] */
  function options() {
    return list().map(function (t) { return [t.name, t.id]; });
  }

  ZKB.MusicLib = {
    list: list, get: get, add: add, remove: remove,
    play: play, stop: stop, pause: pause, isPlaying: isPlaying, current: current,
    options: options, isBuiltin: isBuiltin, builtin: builtin,
    freqOf: freqOf,
    MAX_BYTES: MAX_BYTES, ALLOW: ALLOW, STORE_KEY: STORE_KEY,
    NOTE: NOTE
  };

})(window);
