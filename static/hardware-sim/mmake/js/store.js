/* ============================================================
 * store.js —— 浏览器本地持久化
 * 分层策略：
 *   小数据（舞台布局、界面偏好）→ localStorage，同步读写，秒开
 *   大数据（积木工程、上传图片）→ IndexedDB，可存二进制/BLOB
 * 两者都不依赖服务器：只要不清理浏览器缓存 / 不使用无痕模式，
 * 关闭浏览器后重新打开仍能恢复全部数据。
 * ============================================================ */
(function (global) {
  'use strict';
  var ZKB = global.ZKB || (global.ZKB = {});

  /* ITstudy 集成：按登录账号隔离本地数据（iframe URL 的 uid 参数）。
     独立打开（无 uid）时保持原键，兼容原有 .mxml/本地数据。 */
  var UID = (function () {
    try {
      var v = new URLSearchParams(global.location.search).get('uid') || '';
      return /^[A-Za-z0-9_-]{1,40}$/.test(v) ? v : '';
    } catch (e) { return ''; }
  })();
  var PREFIX = UID ? 'u_' + UID + '__' : '';
  function skey(k) { return PREFIX + k; }

  /* ---------------- localStorage 封装 ---------------- */
  var mem = {};   // localStorage 不可用时的内存兜底（隐私模式）
  var lsOK = (function () {
    try {
      var k = '__zk_test__';
      localStorage.setItem(k, '1');
      localStorage.removeItem(k);
      return true;
    } catch (e) { return false; }
  })();

  function setLocal(key, val) {
    key = skey(key);
    var s;
    try { s = JSON.stringify(val); } catch (e) { return false; }
    if (!lsOK) { mem[key] = s; return true; }
    try { localStorage.setItem(key, s); return true; }
    catch (e) {
      /* 超出配额：清理旧的自动保存快照后重试一次 */
      try {
        ['zkb_autosave_v1', 'zkb_autosave_prev_v1'].forEach(function (k) { localStorage.removeItem(skey(k)); });
        localStorage.setItem(key, s);
        return true;
      } catch (e2) { mem[key] = s; return false; }
    }
  }
  function getLocal(key) {
    key = skey(key);
    var s = lsOK ? localStorage.getItem(key) : mem[key];
    if (s === null || s === undefined) return null;
    try { return JSON.parse(s); } catch (e) { return null; }
  }
  function delLocal(key) {
    key = skey(key);
    if (lsOK) { try { localStorage.removeItem(key); } catch (e) {} }
    delete mem[key];
  }

  /* ---------------- IndexedDB 封装 ---------------- */
  var DB_NAME = 'zkb_store' + (UID ? '_' + UID : '');
  var DB_VER = 1;
  var STORE_PROJ = 'projects';
  var STORE_IMG = 'images';
  var STORE_KV = 'kv';
  var _db = null, _dbFail = false;

  function openDB() {
    return new Promise(function (resolve) {
      if (_db) return resolve(_db);
      if (_dbFail || !global.indexedDB) return resolve(null);
      var req;
      try { req = indexedDB.open(DB_NAME, DB_VER); }
      catch (e) { _dbFail = true; return resolve(null); }
      req.onupgradeneeded = function (e) {
        var db = e.target.result;
        if (!db.objectStoreNames.contains(STORE_PROJ)) db.createObjectStore(STORE_PROJ, { keyPath: 'id' });
        if (!db.objectStoreNames.contains(STORE_IMG)) db.createObjectStore(STORE_IMG, { keyPath: 'id' });
        if (!db.objectStoreNames.contains(STORE_KV)) db.createObjectStore(STORE_KV);
      };
      req.onsuccess = function () { _db = req.result; resolve(_db); };
      req.onerror = function () { _dbFail = true; resolve(null); };
    });
  }

  function tx(store, mode, fn) {
    return openDB().then(function (db) {
      if (!db) return null;
      return new Promise(function (resolve) {
        var t, os;
        try {
          t = db.transaction(store, mode);
          os = t.objectStore(store);
        } catch (e) { return resolve(null); }
        var out;
        try { out = fn(os); } catch (e) { return resolve(null); }
        t.oncomplete = function () { resolve(out && out.result !== undefined ? out.result : out); };
        t.onerror = function () { resolve(null); };
        t.onabort = function () { resolve(null); };
      });
    });
  }

  /* ---------------- 对外 API ---------------- */
  var Store = {
    /* 初始化：探测可用性 */
    init: function () {
      /* 记录能力，供 UI 展示 */
      var caps = { local: lsOK, idb: !!(global.indexedDB && !_dbFail) };
      setLocal('zkb_caps', caps);
      return openDB().then(function (db) {
        caps.idb = !!db;
        setLocal('zkb_caps', caps);
        return caps;
      });
    },
    caps: function () { return getLocal('zkb_caps') || { local: lsOK, idb: !!global.indexedDB }; },

    setLocal: setLocal,
    getLocal: getLocal,
    delLocal: delLocal,

    /* —— 工程 —— */
    saveProject: function (data) {
      var rec = {
        id: 'current', data: data,
        savedAt: Date.now()
      };
      return tx(STORE_PROJ, 'readwrite', function (os) { os.put(rec); })
        .then(function () { return true; });
    },
    loadProject: function () {
      return tx(STORE_PROJ, 'readonly', function (os) { return os.get('current'); })
        .then(function (r) { return r ? r.data : null; });
    },
    clearProject: function () {
      return tx(STORE_PROJ, 'readwrite', function (os) { os.delete('current'); });
    },

    /* —— 图片（已像素化的 1bit 位图 + 预览图） —— */
    saveImage: function (rec) {
      return tx(STORE_IMG, 'readwrite', function (os) { os.put(rec); });
    },
    loadImage: function (id) {
      return tx(STORE_IMG, 'readonly', function (os) { return os.get(id); });
    },
    listImages: function () {
      return tx(STORE_IMG, 'readonly', function (os) { return os.getAll(); });
    },
    deleteImage: function (id) {
      return tx(STORE_IMG, 'readwrite', function (os) { os.delete(id); });
    },

    /* —— 通用键值 —— */
    setKV: function (k, v) { return tx(STORE_KV, 'readwrite', function (os) { os.put(v, k); }); },
    getKV: function (k) {
      return tx(STORE_KV, 'readonly', function (os) { return os.get(k); });
    },

    /* —— 存储用量估算 —— */
    usage: function () {
      if (navigator.storage && navigator.storage.estimate) {
        return navigator.storage.estimate().then(function (e) {
          return { used: e.usage || 0, quota: e.quota || 0 };
        });
      }
      return Promise.resolve({ used: 0, quota: 0 });
    },

    /* 清空全部本地数据（设置面板用） */
    clearAll: function () {
      [STORE_PROJ, STORE_IMG, STORE_KV].forEach(function (s) {
        tx(s, 'readwrite', function (os) { os.clear(); });
      });
      ['zkb_autosave_v1', 'zkb_autosave_prev_v1', 'zkb_stage_scene_v1', 'zkb_prefs_v1', 'zkb_caps']
        .forEach(delLocal);
    }
  };

  ZKB.Store = Store;

})(window);