/* ============================================================
 * matlib.js —— 素材库：图片 / 表情 / 元素素材 / 情景
 * 入口：左侧「拓展库」右侧的「素材」按钮
 * 能力：
 *   1. 上传图片 → 像素化为 128×64 单色位图 → 预览 / 显示到掌控板屏幕
 *   2. 内置表情（喜怒哀乐等），一键显示
 *   3. 上传元素素材（PNG/JPG/SVG…，超尺寸自动缩小）→ 放入舞台可拖动
 *   4. 情景：查看内置情景元素、新建情景、保存当前舞台为情景
 * 所有素材持久化到 IndexedDB（ZKB.Store），清理浏览器缓存前一直可用。
 * ============================================================ */
(function (global) {
  'use strict';
  var ZKB = global.ZKB || (global.ZKB = {});
  var $ = function (id) { return document.getElementById(id); };

  var IMG_MAX = 3 * 1024 * 1024;    // 图片素材 3MB
  var ELE_MAX = 2 * 1024 * 1024;    // 元素素材 2MB
  var ELE_MAX_DIM = 400;            // 元素素材最大边长，超出自动缩小
  var IMG_ALLOW = ['image/png', 'image/jpeg', 'image/gif', 'image/bmp', 'image/webp'];
  var ELE_ALLOW = IMG_ALLOW.concat(['image/svg+xml']);

  var open = false;
  var tab = 'image';

  /* ============================================================
   * 打开 / 关闭
   * ============================================================ */
  function show() {
    if (!ZKB.OledImage) return;
    ZKB.OledImage.restore();
    renderAll();
    var m = $('mat-lib-mask');
    if (m) m.classList.remove('hidden');
    open = true;
  }
  function hide() {
    var m = $('mat-lib-mask');
    if (m) m.classList.add('hidden');
    open = false;
  }

  function switchTab(name) {
    tab = name;
    document.querySelectorAll('.mat-tab').forEach(function (t) {
      t.classList.toggle('active', t.getAttribute('data-mt') === name);
    });
    document.querySelectorAll('.mat-pane').forEach(function (p) {
      p.classList.toggle('active', p.getAttribute('data-mp') === name);
    });
    if (name === 'element') renderElements();
    if (name === 'scene') renderScenes();
  }

  function renderAll() {
    renderImages();
    renderFaces();
    renderElements();
    renderMusic();
    renderScenes();
  }

  /* ============================================================
   * 1.5 音乐素材（第二十六轮）：内置曲目试听 + 上传音频管理
   * ============================================================ */
  function fmtSize(n) {
    if (!n) return '';
    return n > 1048576 ? (n / 1048576).toFixed(2) + 'MB'
      : Math.max(1, Math.round(n / 1024)) + 'KB';
  }

  function renderMusic() {
    if (!ZKB.MusicLib) return;
    var cur = ZKB.MusicLib.current();

    /* --- 内置曲目 --- */
    var bb = $('mat-mus-builtin');
    if (bb) {
      var bs = ZKB.MusicLib.builtin();
      bb.innerHTML = bs.map(function (t) {
        var on = cur === t.id;
        return '<div class="mat-cell music' + (on ? ' on' : '') +
          '" data-mus="' + t.id + '" title="点击试听">' +
          /* 第四十四轮：卡片里加播放 / 暂停按钮，
             不用点整张卡也能控制，方便对照多首音乐。 */
          '<button class="mus-btn" data-mus-play="' + t.id + '" title="' +
          (on ? '暂停' : '播放') + '">' + (on ? '⏸' : '▶') + '</button>' +
          '<div class="mus-ico">♪</div>' +
          '<div class="mus-name">' + escapeHtml(t.name) + '</div>' +
          '<div class="mus-sub">内置 · ' + t.base + ' BPM · ' + t.seq.length + ' 个音符</div>' +
          '</div>';
      }).join('');
      bindMusicEvents(bb);
    }

    /* --- 上传的音乐 --- */
    var box = $('mat-mus-list');
    if (box) {
      var ups = ZKB.MusicLib.list().filter(function (t) { return t.kind === 'upload'; });
      box.innerHTML = ups.length ? ups.map(function (t) {
        var on = cur === t.id;
        return '<div class="mat-cell music' + (on ? ' on' : '') +
          '" data-mus="' + t.id + '" title="点击试听">' +
          '<button class="mus-btn" data-mus-play="' + t.id + '" title="' +
          (on ? '暂停' : '播放') + '">' + (on ? '⏸' : '▶') + '</button>' +
          '<div class="mus-ico">🎵</div>' +
          '<div class="mus-name">' + escapeHtml(t.name) + '</div>' +
          '<div class="mus-sub">上传 · ' + fmtSize(t.size) + '</div>' +
          '<div class="mat-del" data-mus-del="' + t.id + '" title="删除">×</div>' +
          '</div>';
      }).join('') : '<div class="empty-hint">还没有上传音乐，点上方「📤 上传音乐」添加</div>';

      bindMusicEvents(box);

      box.querySelectorAll('[data-mus-del]').forEach(function (b) {
        b.addEventListener('click', function (e) {
          e.stopPropagation();
          var id = b.getAttribute('data-mus-del');
          if (!confirm('确定删除这首上传的音乐吗？')) return;
          if (ZKB.MusicLib.current() === id) ZKB.MusicLib.stop();
          ZKB.MusicLib.remove(id);
          renderMusic();
          ZKB.toast('已删除');
        });
      });
    }
  }

  /* 第四十四轮：音乐卡片的播放 / 暂停 / 切换事件
     规则：
       · 点播放按钮 → 正在播这首就暂停，否则播这首
       · 点卡片其它地方 → 同样切换（保持原来的整卡点击试听）
       · 切到别的曲子时，上一首会自动停（MusicLib.play 内部先 stop） */
  function bindMusicEvents(box) {
    box.querySelectorAll('[data-mus-play]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        var id = btn.getAttribute('data-mus-play');
        if (ZKB.MusicLib.current() === id) {
          ZKB.MusicLib.pause();
          renderMusic();
          return;
        }
        ZKB.MusicLib.play(id, 'once');
        renderMusic();
        ZKB.toast('试听《' + ZKB.MusicLib.get(id).name + '》');
      });
    });

    box.querySelectorAll('[data-mus]').forEach(function (c) {
      c.addEventListener('click', function (e) {
        if (e.target.getAttribute('data-mus-del')) return;
        if (e.target.getAttribute('data-mus-play')) return;
        var id = c.getAttribute('data-mus');
        if (ZKB.MusicLib.current() === id) {
          ZKB.MusicLib.pause();
          renderMusic();
          return;
        }
        /* 切歌：MusicLib.play 内部会先 stop 掉上一首 */
        ZKB.MusicLib.play(id, 'once');
        renderMusic();
        ZKB.toast('试听《' + ZKB.MusicLib.get(id).name + '》');
      });
    });
  }

  /* 上传音乐（大小 / 格式限制由 MusicLib.add 统一校验） */
  function onUploadMusic(file) {
    var tip = $('mat-mus-tip');
    if (tip) tip.innerHTML = '正在处理「' + escapeHtml(file.name) + '」…';
    ZKB.MusicLib.add(file, function (err, item) {
      if (err) {
        if (tip) tip.innerHTML = '<span style="color:#e0483e">✕ ' + escapeHtml(err.message) + '</span>';
        ZKB.toast(err.message);
        return;
      }
      if (tip) tip.innerHTML = '✓ 已添加《' + escapeHtml(item.name) + '》（' +
        fmtSize(item.size) + '），可用积木「播放音乐」播放';
      renderMusic();
      ZKB.toast('音乐已添加：' + item.name);
    });
  }

  /* ============================================================
   * 1. 图片素材
   * ============================================================ */
  function bitsThumbURL(bits) {
    try { return ZKB.OledImage.bitsToDataURL(bits); } catch (e) { return ''; }
  }

  function renderImages() {
    var box = $('mat-img-list');
    if (!box) return;
    var items = ZKB.OledImage.list().filter(function (r) { return r.kind === 'upload'; });
    if (!items.length) {
      box.innerHTML = '<div class="empty-hint">还没有上传图片，点击上方「上传图片」开始</div>';
      return;
    }
    box.innerHTML = items.map(function (r) {
      return '<div class="mat-cell" data-id="' + r.id + '" title="点击显示到掌控板屏幕">' +
        '<div class="mat-del" data-del="' + r.id + '" title="删除">×</div>' +
        '<img src="' + bitsThumbURL(r.bits) + '" alt="">' +
        '<span>' + escapeHtml(r.name) + '</span></div>';
    }).join('');

    box.querySelectorAll('.mat-cell').forEach(function (c) {
      c.addEventListener('click', function (e) {
        if (e.target.getAttribute('data-del')) return;
        var id = c.getAttribute('data-id');
        box.querySelectorAll('.mat-cell').forEach(function (x) { x.classList.remove('on'); });
        c.classList.add('on');
        showPreview(id);
        ZKB.OledImage.show(id);
        if (ZKB.refreshImageBlocks) ZKB.refreshImageBlocks();
      });
    });
    box.querySelectorAll('[data-del]').forEach(function (b) {
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        var id = b.getAttribute('data-del');
        if (!confirm('确定删除这张图片素材吗？')) return;
        ZKB.OledImage.remove(id);
        renderImages();
        if (ZKB.refreshImageBlocks) ZKB.refreshImageBlocks();
      });
    });
  }

  function showPreview(id) {
    var box = $('mat-preview');
    var rec = id ? ZKB.OledImage.get(id) : null;
    if (!box) return;
    if (!rec) { box.innerHTML = '<span class="empty-hint">选择一张图片后在此预览</span>'; return; }
    box.innerHTML = '<img src="' + bitsThumbURL(rec.bits) + '" alt="" ' +
      'style="width:100%;image-rendering:pixelated;background:#0b1410;border-radius:6px">';
  }

  /* 上传图片 → 像素化 */
  function onUploadImage(file) {
    var tip = $('mat-img-tip');
    if (tip) tip.textContent = '正在处理「' + file.name + '」…';
    ZKB.OledImage.fileToBitmap(file, {}, function (err, res) {
      if (err) {
        if (tip) tip.innerHTML = '<span style="color:#e0483e">✕ ' + escapeHtml(err.message) + '</span>';
        ZKB.toast(err.message);
        return;
      }
      var id = 'img_' + Date.now().toString(36);
      ZKB.OledImage.register({
        id: id, name: res.name.replace(/\.[^.]+$/, ''), kind: 'upload',
        bits: fitToScreen(res.bits, res.w, res.h),
        w: ZKB.OledImage.W, h: ZKB.OledImage.H, threshold: res.threshold
      });
      if (tip) tip.innerHTML = '✓ 已像素化为 ' + res.w + '×' + res.h + ' → 128×64（阈值 ' +
        res.threshold + '），已存入浏览器缓存';
      renderImages();
      showPreview(id);
      ZKB.OledImage.show(id);
      if (ZKB.refreshImageBlocks) ZKB.refreshImageBlocks();
      ZKB.toast('图片已添加并显示到屏幕');
    });
  }

  /* ============================================================
   * 2. 表情
   * ============================================================ */
  function renderFaces() {
    var box = $('mat-face-list');
    if (!box) return;
    var FACES = ZKB.OledImage.FACES;
    box.innerHTML = Object.keys(FACES).map(function (k) {
      var rec = ZKB.OledImage.get('face_' + k);
      return '<div class="mat-cell face" data-face="' + k + '" title="点击显示到掌控板屏幕">' +
        '<img src="' + (rec ? bitsThumbURL(rec.bits) : '') + '" alt="">' +
        '<span>' + FACES[k].name + '</span></div>';
    }).join('');
    box.querySelectorAll('.mat-cell').forEach(function (c) {
      c.addEventListener('click', function () {
        box.querySelectorAll('.mat-cell').forEach(function (x) { x.classList.remove('on'); });
        c.classList.add('on');
        var k = c.getAttribute('data-face');
        ZKB.OledImage.show('face_' + k);
        if (ZKB.Stage) ZKB.Stage.setMood(k);
        ZKB.toast('已显示表情「' + FACES[k].name + '」');
      });
    });
  }

  /* ============================================================
   * 3. 元素素材
   * ============================================================ */
  function eleStore() {
    return ZKB.Store.getLocal('zkb_elements_v1') || [];
  }
  function setEleStore(list) { ZKB.Store.setLocal('zkb_elements_v1', list); }

  function renderElements() {
    var box = $('mat-ele-list');
    if (!box) return;
    var list = eleStore();
    if (!list.length) {
      box.innerHTML = '<div class="empty-hint">还没有上传元素素材，可上传 PNG / JPG / SVG 素材</div>';
    } else {
      box.innerHTML = list.map(function (e) {
        return '<div class="mat-cell" data-ele="' + e.id + '" title="点击添加到舞台（可拖动）">' +
          '<div class="mat-del" data-del="' + e.id + '" title="删除">×</div>' +
          '<img src="' + e.url + '" alt="">' +
          '<span>' + escapeHtml(e.name) + '</span></div>';
      }).join('');
      box.querySelectorAll('.mat-cell').forEach(function (c) {
        c.addEventListener('click', function (e) {
          if (e.target.getAttribute('data-del')) return;
          var id = c.getAttribute('data-ele');
          var rec = eleStore().filter(function (x) { return x.id === id; })[0];
          if (rec && ZKB.Stage) {
            ZKB.Stage.addCustom(rec, 360 + Math.round(Math.random() * 100), 300);
            ZKB.toast('已添加元素「' + rec.name + '」，可拖动调整位置');
          }
        });
      });
      box.querySelectorAll('[data-del]').forEach(function (b) {
        b.addEventListener('click', function (e) {
          e.stopPropagation();
          var id = b.getAttribute('data-del');
          if (!confirm('确定删除该元素素材吗？')) return;
          setEleStore(eleStore().filter(function (x) { return x.id !== id; }));
          renderElements();
        });
      });
    }

    /* 内置元素 */
    var bb = $('mat-ele-builtin');
    if (!bb || !ZKB.SceneLib) return;
    var cats = ZKB.SceneLib.cats();
    bb.innerHTML = cats.map(function (c) {
      return '<div class="mat-ele-group"><div class="mat-ele-gt">' + c + '</div><div class="mat-grid flat">' +
        ZKB.SceneLib.byCat(c).map(function (k) {
          var d = ZKB.SceneLib.LIB[k];
          return '<div class="mat-cell small" data-kind="' + k + '" title="点击添加到舞台">' +
            '<div class="mini-svg">' + (d.thumb ? d.thumb() : '') + '</div>' +
            '<span>' + d.name + '</span></div>';
        }).join('') + '</div></div>';
    }).join('');
    bb.querySelectorAll('[data-kind]').forEach(function (c) {
      c.addEventListener('click', function () {
        var k = c.getAttribute('data-kind');
        if (ZKB.Stage) {
          ZKB.Stage.add(k, 340 + Math.round(Math.random() * 120), 290 + Math.round(Math.random() * 70));
        }
      });
    });
  }

  /* 上传元素素材：格式校验 + 自动缩小 */
  function onUploadElement(file) {
    var tip = $('mat-ele-tip');
    var okType = ELE_ALLOW.indexOf(file.type) >= 0 ||
      /\.(png|jpe?g|gif|bmp|webp|svg)$/i.test(file.name);
    if (!okType) {
      msg(tip, '✕ 不支持的格式：' + (file.type || '未知') + '。仅支持 PNG/JPG/GIF/BMP/WebP/SVG', true);
      return;
    }
    if (file.size > ELE_MAX) {
      msg(tip, '✕ 素材过大（' + (file.size / 1024 / 1024).toFixed(1) +
        'MB），上限 2MB。请先压缩后再上传', true);
      return;
    }
    var fr = new FileReader();
    fr.onerror = function () { msg(tip, '✕ 文件读取失败', true); };
    fr.onload = function () {
      var url = String(fr.result);
      var done = function (w, h) {
        var rec = {
          id: 'ele_' + Date.now().toString(36),
          name: file.name.replace(/\.[^.]+$/, ''),
          url: url, w: w, h: h
        };
        var list = eleStore();
        list.push(rec);
        setEleStore(list);
        msg(tip, '✓ 已添加元素素材「' + rec.name + '」（' + w + '×' + h + '）', false);
        renderElements();
        ZKB.toast('元素素材已添加');
      };
      /* SVG 直接用，无需缩放 */
      if (/svg/i.test(file.type) || /\.svg$/i.test(file.name)) {
        done(0, 0);
        return;
      }
      /* 位图：读取尺寸，超限自动缩小后重新导出 */
      var img = new Image();
      img.onerror = function () { msg(tip, '✕ 图片解码失败，请换一张', true); };
      img.onload = function () {
        var w = img.naturalWidth || img.width, h = img.naturalHeight || img.height;
        var maxSide = Math.max(w, h);
        if (maxSide <= ELE_MAX_DIM) { done(w, h); return; }
        var sc = ELE_MAX_DIM / maxSide;
        var dw = Math.max(1, Math.round(w * sc)), dh = Math.max(1, Math.round(h * sc));
        var cv = document.createElement('canvas');
        cv.width = dw; cv.height = dh;
        var c = cv.getContext('2d');
        c.imageSmoothingQuality = 'high';
        c.drawImage(img, 0, 0, dw, dh);
        msg(tip, '✓ 已自动缩小：' + w + '×' + h + ' → ' + dw + '×' + dh, false);
        done(dw, dh);
      };
      img.src = url;
    };
    fr.readAsDataURL(file);
  }

  function msg(el, text, isErr) {
    if (!el) return;
    el.innerHTML = isErr ? '<span style="color:#e0483e">' + escapeHtml(text) + '</span>'
      : '<span style="color:#2fa84f">' + escapeHtml(text) + '</span>';
  }

  /* ============================================================
   * 4. 情景
   * ============================================================ */
  function myScenes() {
    return ZKB.Store.getLocal('zkb_scenes_v1') || [];
  }
  function setMyScenes(l) { ZKB.Store.setLocal('zkb_scenes_v1', l); }

  function renderScenes() {
    var box = $('mat-scene-list');
    if (box) {
      var list = myScenes();
      box.innerHTML = list.length ? list.map(function (s) {
        return '<div class="mat-cell scene" data-scene="' + s.id + '" title="点击布置到舞台">' +
          '<div class="mat-del" data-del="' + s.id + '" title="删除">×</div>' +
          '<div class="mat-scene-thumb">' + sceneThumb(s) + '</div>' +
          '<span>' + escapeHtml(s.name) + '</span></div>';
      }).join('') : '<div class="empty-hint">还没有自定义情景，点击「保存当前舞台为情景」创建</div>';

      box.querySelectorAll('[data-scene]').forEach(function (c) {
        c.addEventListener('click', function (e) {
          if (e.target.getAttribute('data-del')) return;
          var id = c.getAttribute('data-scene');
          var sc = myScenes().filter(function (x) { return x.id === id; })[0];
          if (sc && ZKB.Stage) { ZKB.Stage.applyCustomScene(sc); ZKB.toast('已布置情景「' + sc.name + '」'); }
        });
      });
      box.querySelectorAll('[data-del]').forEach(function (b) {
        b.addEventListener('click', function (e) {
          e.stopPropagation();
          var id = b.getAttribute('data-del');
          if (!confirm('确定删除该情景吗？')) return;
          setMyScenes(myScenes().filter(function (x) { return x.id !== id; }));
          renderScenes();
        });
      });
    }

    /* 内置情景 */
    var bb = $('mat-scene-builtin');
    if (!bb || !ZKB.SceneLib) return;
    var keys = Object.keys(ZKB.SceneLib.SCENES);
    bb.innerHTML = keys.map(function (k) {
      var s = ZKB.SceneLib.SCENES[k];
      return '<div class="mat-cell scene" data-bsc="' + k + '" title="点击查看元素">' +
        '<div class="mat-scene-thumb">' + sceneThumb({ items: s.items }) + '</div>' +
        '<span>' + s.name + '</span></div>';
    }).join('');
    bb.querySelectorAll('[data-bsc]').forEach(function (c) {
      c.addEventListener('click', function () {
        var k = c.getAttribute('data-bsc');
        var s = ZKB.SceneLib.SCENES[k];
        /* 显示元素清单 */
        var d = $('mat-scene-detail');
        if (d) {
          var rows = s.items.map(function (it) {
            var def = ZKB.SceneLib.LIB[it.k];
            return '<div class="msd-row"><b>' + (def ? def.name : it.k) + '</b>' +
              '<span>' + it.k + '</span><span>x:' + it.x + ' y:' + it.y + '</span></div>';
          }).join('');
          d.innerHTML = '<div class="msd-head">情景「' + s.name + '」共 ' + s.items.length + ' 个元素' +
            '<button class="mini-btn" id="msd-apply">布置到舞台</button></div>' + rows;
          var ap = $('msd-apply');
          if (ap) ap.addEventListener('click', function () {
            ZKB.Stage.applyScene(k);
            ZKB.toast('已布置情景「' + s.name + '」');
          });
        }
      });
    });
  }

  /* 情景缩略：用元素图标平铺 */
  function sceneThumb(sc) {
    if (!sc || !sc.items || !ZKB.SceneLib) return '<span class="empty-hint">空</span>';
    var html = sc.items.slice(0, 9).map(function (it) {
      var def = ZKB.SceneLib.LIB[it.k];
      if (!def) return '';
      return '<span class="mst-i">' + (def.thumb ? def.thumb() : '') + '</span>';
    }).join('');
    return '<div class="mst-grid">' + html + '</div>';
  }

  /* 新建情景对话框 */
  function openSceneDialog(currentItems) {
    var mask = $('scene-dialog-mask');
    var nameEl = $('sd-name');
    var box = $('sd-eles');
    if (!mask || !box || !ZKB.SceneLib) return;
    $('sd-title').textContent = '新建情景';
    $('sd-tip').textContent = '给情景起个名字，并勾选要包含的元素（可多选）';
    nameEl.value = '';
    var sel = {};
    box.innerHTML = ZKB.SceneLib.cats().map(function (c) {
      return '<div class="sd-cat"><div class="sd-cat-t">' + c + '</div>' +
        ZKB.SceneLib.byCat(c).map(function (k) {
          var d = ZKB.SceneLib.LIB[k];
          return '<label class="sd-item"><input type="checkbox" data-k="' + k + '">' +
            '<span class="mini-svg">' + (d.thumb ? d.thumb() : '') + '</span>' + d.name + '</label>';
        }).join('') + '</div>';
    }).join('');

    $('sd-ok').onclick = function () {
      var nm = (nameEl.value || '').trim() || '我的情景';
      var keys = [];
      box.querySelectorAll('input:checked').forEach(function (i) { keys.push(i.getAttribute('data-k')); });
      if (!keys.length) { ZKB.toast('请至少勾选一个元素'); return; }
      /* 按网格自动排布（并排间隔，避免重叠） */
      var items = keys.map(function (k, i) {
        var def = ZKB.SceneLib.LIB[k];
        return {
          k: k,
          x: 180 + (i % 4) * 160,
          y: 250 + Math.floor(i / 4) * 120
        };
      });
      var list = myScenes();
      list.push({
        id: 'sc_' + Date.now().toString(36),
        name: nm, items: items, savedAt: Date.now()
      });
      setMyScenes(list);
      mask.classList.add('hidden');
      renderScenes();
      ZKB.toast('情景「' + nm + '」已创建');
    };
    $('sd-cancel').onclick = function () { mask.classList.add('hidden'); };
    mask.classList.remove('hidden');
    nameEl.focus();
  }

  /* 保存当前舞台为情景 */
  function saveCurrentScene() {
    if (!ZKB.Stage) return;
    var items = ZKB.Stage.getItems().map(function (i) {
      return { k: i.k, x: i.x, y: i.y, rot: i.rot || 0, scale: i.scale || 1, custom: i.custom || null };
    });
    if (!items.length) { ZKB.toast('舞台是空的，先添加一些元素'); return; }
    var nm = prompt('给这个情景起个名字：', '我的情景' + (myScenes().length + 1));
    if (nm === null) return;
    nm = (nm || '').trim() || '我的情景';
    var list = myScenes();
    list.push({ id: 'sc_' + Date.now().toString(36), name: nm, items: items, savedAt: Date.now() });
    setMyScenes(list);
    renderScenes();
    ZKB.toast('已保存情景「' + nm + '」');
  }

  /* ============================================================
   * 工具
   * ============================================================ */
  function fitToScreen(bits, sw, sh) {
    var W = ZKB.OledImage.W, H = ZKB.OledImage.H;
    var out = new Uint8Array(W * H);
    var sc = Math.min(W / sw, H / sh, 1);
    var dw = Math.max(1, Math.round(sw * sc)), dh = Math.max(1, Math.round(sh * sc));
    var ox = Math.floor((W - dw) / 2), oy = Math.floor((H - dh) / 2);
    for (var y = 0; y < dh; y++) {
      var sy = Math.min(sh - 1, Math.floor(y / sc));
      for (var x = 0; x < dw; x++) {
        var sx = Math.min(sw - 1, Math.floor(x / sc));
        if (bits[sy * sw + sx]) out[(oy + y) * W + (ox + x)] = 1;
      }
    }
    return out;
  }
  function escapeHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  /* ============================================================
   * 初始化
   * ============================================================ */
  function init() {
    var btn = $('btn-mat-lib');
    if (btn) btn.addEventListener('click', show);
    var cl = $('mat-close');
    if (cl) cl.addEventListener('click', hide);
    var mask = $('mat-lib-mask');
    if (mask) mask.addEventListener('click', function (e) { if (e.target === mask) hide(); });

    document.querySelectorAll('.mat-tab').forEach(function (t) {
      t.addEventListener('click', function () { switchTab(t.getAttribute('data-mt')); });
    });

    var f = $('mat-file');
    if (f) f.addEventListener('change', function () {
      var file = this.files && this.files[0];
      if (file) onUploadImage(file);
      this.value = '';
    });
    var ef = $('mat-ele-file');
    if (ef) ef.addEventListener('change', function () {
      var file = this.files && this.files[0];
      if (file) onUploadElement(file);
      this.value = '';
    });

    var mf = $('mat-mus-file');
    if (mf) mf.addEventListener('change', function () {
      var file = this.files && this.files[0];
      if (file) onUploadMusic(file);
      this.value = '';
    });

    var nb = $('mat-scene-new');
    if (nb) nb.addEventListener('click', function () { openSceneDialog(); });
    var sb = $('mat-scene-save');
    if (sb) sb.addEventListener('click', saveCurrentScene);

    /* 启动时恢复内置表情与缓存图片 */
    if (ZKB.OledImage) ZKB.OledImage.restore();
  }

  ZKB.MatLib = { init: init, show: show, hide: hide };

})(window);