/* ════════════════════════════════════════════════════════════
 * 课堂页工具集（lesson_tools.js）
 *   黑板 / 画笔 / 倒计时 / 点名器 / 流程拓扑图画板 / 思维导图 / 文档抽屉 / toast
 *   依赖：window.LESSON_PAGE、window.CSRF_TOKEN（study_lesson.html 注入）
 *   加载顺序：先本文件，后 study_lesson.js（其会调用 LessonTools.*）
 * ════════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  var PAGE = window.LESSON_PAGE || {};

  /* ── 通用 ── */
  function $(id) { return document.getElementById(id); }
  function show(el) { if (el) el.classList.remove('hidden'); }
  function hide(el) { if (el) el.classList.add('hidden'); }

  var toastTimer = null;
  function toast(msg, ms) {
    var t = $('toolToast');
    if (!t) return;
    t.textContent = msg;
    show(t);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { hide(t); }, ms || 2200);
  }

  /* HTML 转义（课堂页所有 innerHTML 插值统一走这里，防条目标题注入） */
  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  window.lessonEscapeHtml = escapeHtml;

  function apiFetch(url, opts) {
    opts = opts || {};
    opts.credentials = 'same-origin';
    opts.headers = Object.assign({ 'X-CSRFToken': window.CSRF_TOKEN || '' }, opts.headers || {});
    return fetch(url, opts).then(function (r) { return r.json(); });
  }

  /* ════════════════════════════════════════════
   * 黑板（护眼墨绿板面 + 粉笔色笔迹）
   * ════════════════════════════════════════════ */
  var Blackboard = {
    canvas: null, ctx: null, drawing: false,
    color: '#FFFDE7', width: 6, erasing: false, last: null,
    pages: [''], pageIndex: 0, _pageToken: 0,

    init: function () {
      this.canvas = $('blackboardCanvas');
      if (!this.canvas) return;
      this.ctx = this.canvas.getContext('2d');
      var self = this;
      this.canvas.addEventListener('pointerdown', function (e) { self.down(e); });
      this.canvas.addEventListener('pointermove', function (e) { self.move(e); });
      ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(function (name) {
        self.canvas.addEventListener(name, function () { self.endStroke(); });
      });
      // 指针在画布外抬起时也要结束笔画
      window.addEventListener('pointerup', function () { self.endStroke(); });
      window.addEventListener('resize', function () { if (self.visible()) self.resize(); });

      document.querySelectorAll('.bb-chalk').forEach(function (dot) {
        dot.addEventListener('click', function () {
          document.querySelectorAll('.bb-chalk').forEach(function (d) { d.classList.remove('active'); });
          dot.classList.add('active');
          self.color = dot.dataset.color;
          self.erasing = false;
          $('bbEraser').classList.remove('active');
        });
      });
      document.querySelectorAll('.bb-btn[data-width]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          document.querySelectorAll('.bb-btn[data-width]').forEach(function (b) { b.classList.remove('active'); });
          btn.classList.add('active');
          self.width = parseFloat(btn.dataset.width);
          self.erasing = false;
          $('bbEraser').classList.remove('active');
        });
      });
      $('bbEraser').addEventListener('click', function () {
        self.erasing = !self.erasing;
        this.classList.toggle('active', self.erasing);
      });
      $('bbClear').addEventListener('click', function () { self.clear(); });
      $('bbClose').addEventListener('click', function () { Blackboard.close(); });
      $('bbNew').addEventListener('click', function () { self.newPage(); });
      $('bbPrev').addEventListener('click', function () { self.prevPage(); });
      $('bbNext').addEventListener('click', function () { self.nextPage(); });
      $('bbDrawer').addEventListener('click', function () {
        document.body.classList.toggle('bb-toolbar-hidden');
      });
      // 黑板打开时左右方向键翻页，便于回顾板书
      document.addEventListener('keydown', function (e) {
        if (!self.visible()) return;
        if (e.key === 'ArrowLeft') { e.preventDefault(); self.prevPage(); }
        else if (e.key === 'ArrowRight') { e.preventDefault(); self.nextPage(); }
      });
      // 默认选白粉笔/粗笔
      var first = document.querySelector('.bb-chalk');
      var thick = document.querySelector('.bb-btn[data-width="6"]');
      if (first) first.classList.add('active');
      if (thick) thick.classList.add('active');
      this.updatePageUi();
    },
    visible: function () { return !$('blackboard').classList.contains('hidden'); },
    open: function () {
      show($('blackboard'));
      this.resize();
      this.updatePageUi();
    },
    close: function () {
      this.saveCurrentPage();
      hide($('blackboard'));
    },
    resize: function () {
      var c = this.canvas, dpr = window.devicePixelRatio || 1;
      if (!c) return;
      this.saveCurrentPage();
      c.width = Math.max(1, Math.round(c.clientWidth * dpr));
      c.height = Math.max(1, Math.round(c.clientHeight * dpr));
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      this.ctx.lineCap = 'round';
      this.ctx.lineJoin = 'round';
      this.renderPage();
    },
    saveCurrentPage: function () {
      var c = this.canvas;
      if (!c || !c.width || !c.height) return;
      try { this.pages[this.pageIndex] = c.toDataURL('image/png'); } catch (e) { /* ignore */ }
    },
    clearCanvas: function () {
      if (this.ctx && this.canvas) {
        this.ctx.clearRect(0, 0, this.canvas.clientWidth, this.canvas.clientHeight);
      }
    },
    renderPage: function () {
      var self = this, c = this.canvas;
      if (!c) return;
      var token = ++this._pageToken;
      this.clearCanvas();
      var data = this.pages[this.pageIndex];
      if (!data) { this.updatePageUi(); return; }
      var img = new Image();
      img.onload = function () {
        if (token !== self._pageToken) return;
        self.clearCanvas();
        self.ctx.drawImage(img, 0, 0, c.clientWidth, c.clientHeight);
      };
      img.src = data;
      this.updatePageUi();
    },
    updatePageUi: function () {
      var info = $('bbPageInfo');
      if (info) info.textContent = (this.pageIndex + 1) + ' / ' + this.pages.length;
      var prev = $('bbPrev'), next = $('bbNext');
      if (prev) prev.disabled = this.pageIndex <= 0;
      if (next) next.disabled = this.pageIndex >= this.pages.length - 1;
    },
    goPage: function (idx) {
      if (idx < 0 || idx >= this.pages.length || idx === this.pageIndex) return;
      this.saveCurrentPage();
      this.pageIndex = idx;
      this.renderPage();
    },
    prevPage: function () { this.goPage(this.pageIndex - 1); },
    nextPage: function () { this.goPage(this.pageIndex + 1); },
    newPage: function () {
      this.saveCurrentPage();
      // 使上一页尚未完成的异步图片加载失效，避免旧图覆盖新页
      this._pageToken++;
      var idx = this.pageIndex + 1;
      this.pages.splice(idx, 0, '');
      this.pageIndex = idx;
      this.clearCanvas();
      this.updatePageUi();
      toast('已新建第 ' + (idx + 1) + ' 页');
    },
    clear: function () {
      this._pageToken++;
      this.clearCanvas();
      this.pages[this.pageIndex] = '';
      this.updatePageUi();
    },
    pos: function (e) {
      var r = this.canvas.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    },
    applyStroke: function () {
      var ctx = this.ctx;
      ctx.globalCompositeOperation = this.erasing ? 'destination-out' : 'source-over';
      ctx.strokeStyle = this.color;
      ctx.fillStyle = this.color;
      ctx.lineWidth = this.erasing ? 26 : this.width;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
    },
    dot: function (p) {
      var ctx = this.ctx;
      this.applyStroke();
      ctx.beginPath();
      ctx.arc(p.x, p.y, Math.max(2, (this.erasing ? 26 : this.width) / 2), 0, Math.PI * 2);
      ctx.fill();
    },
    down: function (e) {
      if (e.pointerType === 'mouse' && e.button !== 0) return;
      e.preventDefault();
      this.drawing = true;
      try { this.canvas.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ }
      this.last = this.pos(e);
      // 单击/轻点也落笔：此前只靠 move 连线，点按常常没有痕迹
      this.dot(this.last);
    },
    move: function (e) {
      if (!this.drawing || !this.last) return;
      e.preventDefault();
      var points = [];
      if (typeof e.getCoalescedEvents === 'function') {
        try { points = e.getCoalescedEvents() || []; } catch (err) { points = []; }
      }
      if (!points.length) points = [e];
      var ctx = this.ctx;
      this.applyStroke();
      for (var i = 0; i < points.length; i++) {
        var p = this.pos(points[i]);
        ctx.beginPath();
        ctx.moveTo(this.last.x, this.last.y);
        ctx.lineTo(p.x, p.y);
        ctx.stroke();
        this.last = p;
      }
    },
    endStroke: function () {
      this.drawing = false;
      this.last = null;
    }
  };

  /* ════════════════════════════════════════════
   * 画笔（舞台透明标注层）
   * ════════════════════════════════════════════ */
  var DrawPen = {
    canvas: null, ctx: null, active: false, drawing: false,
    color: '#FF5252', width: 3, erasing: false, last: null,

    init: function () {
      this.canvas = $('drawCanvas');
      if (!this.canvas) return;
      this.ctx = this.canvas.getContext('2d');
      var self = this;
      this.canvas.addEventListener('pointerdown', function (e) { self.down(e); });
      this.canvas.addEventListener('pointermove', function (e) { self.move(e); });
      window.addEventListener('pointerup', function () { self.drawing = false; self.last = null; });
      window.addEventListener('resize', function () { if (self.active) self.resize(true); });

      // 画笔 mini 工具条
      var bar = document.createElement('div');
      bar.className = 'bb-toolbar';
      bar.style.cssText = 'bottom:auto;top:12px;right:12px;left:auto;transform:none;display:none;';
      bar.id = 'penBar';
      ['#FF5252', '#FFE082', '#69F0AE', '#FFFFFF'].forEach(function (col, i) {
        var dot = document.createElement('span');
        dot.className = 'bb-chalk' + (i === 0 ? ' active' : '');
        dot.style.background = col;
        dot.addEventListener('click', function () {
          bar.querySelectorAll('.bb-chalk').forEach(function (d) { d.classList.remove('active'); });
          dot.classList.add('active');
          self.color = col; self.erasing = false;
          eraserBtn.classList.remove('active');
        });
        bar.appendChild(dot);
      });
      var sep = document.createElement('span'); sep.className = 'bb-sep'; bar.appendChild(sep);
      var eraserBtn = document.createElement('button');
      eraserBtn.className = 'bb-btn'; eraserBtn.title = '橡皮';
      eraserBtn.innerHTML = '<i class="bi bi-eraser-fill"></i>';
      eraserBtn.addEventListener('click', function () {
        self.erasing = !self.erasing;
        eraserBtn.classList.toggle('active', self.erasing);
      });
      bar.appendChild(eraserBtn);
      var clearBtn = document.createElement('button');
      clearBtn.className = 'bb-btn'; clearBtn.title = '清除标注';
      clearBtn.innerHTML = '<i class="bi bi-trash"></i>';
      clearBtn.addEventListener('click', function () { self.clear(); });
      bar.appendChild(clearBtn);
      document.getElementById('lessonStage').appendChild(bar);
    },
    resize: function (keep) {
      var c = this.canvas, dpr = window.devicePixelRatio || 1;
      var snap = null;
      if (keep && c.width > 0) { try { snap = c.toDataURL(); } catch (e) { /* ignore */ } }
      c.width = c.clientWidth * dpr;
      c.height = c.clientHeight * dpr;
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      this.ctx.lineCap = 'round';
      this.ctx.lineJoin = 'round';
      if (snap) {
        var self = this, img = new Image();
        img.onload = function () { self.ctx.drawImage(img, 0, 0, c.clientWidth, c.clientHeight); };
        img.src = snap;
      }
    },
    toggle: function () {
      this.active = !this.active;
      $('toolDraw').classList.toggle('active', this.active);
      if (this.active) {
        show(this.canvas);       // 先显示再取 clientWidth（隐藏时为 0）
        this.resize(false);
        $('penBar').style.display = 'flex';
        toast('画笔已开启：可在画面上标注，再点一次退出');
      } else {
        hide(this.canvas);
        $('penBar').style.display = 'none';
      }
    },
    clear: function () { this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height); },
    pos: function (e) {
      var r = this.canvas.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    },
    down: function (e) {
      this.drawing = true;
      this.last = this.pos(e);
      this.move(e);
    },
    move: function (e) {
      if (!this.drawing) return;
      var p = this.pos(e), ctx = this.ctx;
      ctx.globalCompositeOperation = this.erasing ? 'destination-out' : 'source-over';
      ctx.strokeStyle = this.color;
      ctx.lineWidth = this.erasing ? 22 : this.width;
      ctx.beginPath();
      ctx.moveTo(this.last.x, this.last.y);
      ctx.lineTo(p.x, p.y);
      ctx.stroke();
      this.last = p;
    }
  };

  /* ════════════════════════════════════════════
   * 倒计时 / 秒表
   * ════════════════════════════════════════════ */
  var Timer = {
    mode: 'countdown', totalSec: 300, remainSec: 300,
    running: false, startAt: 0, accum: 0, tickHandle: null,

    init: function () {
      var self = this;
      document.querySelectorAll('.tm-presets button').forEach(function (b) {
        b.addEventListener('click', function () {
          self.stop();
          self.mode = 'countdown';
          self.totalSec = parseInt(b.dataset.min, 10) * 60;
          self.remainSec = self.totalSec;
          self.syncModeUi();
          self.render();
        });
      });
      $('timerStart').addEventListener('click', function () { self.start(); });
      $('timerPause').addEventListener('click', function () { self.pause(); });
      $('timerReset').addEventListener('click', function () { self.reset(); });
      $('timerStopwatch').addEventListener('click', function () {
        self.stop();
        if (self.mode === 'stopwatch') {
          // 再点一次切回倒计时；保留上次选择的时长
          self.mode = 'countdown';
          self.accum = 0;
          self.remainSec = self.totalSec;
          self.syncModeUi();
          self.render();
          toast('已切换回倒计时模式');
          return;
        }
        self.mode = 'stopwatch';
        self.accum = 0;
        self.syncModeUi();
        self.render();
        toast('秒表模式：点击开始正计时');
      });
      // 首次打开 modal 时 lazy resize 无必要，直接默认 5 分钟
      this.syncModeUi();
      this.render();
    },
    fmt: function (s) {
      s = Math.max(0, Math.round(s));
      var m = Math.floor(s / 60), sec = s % 60;
      if (m >= 60) {
        var h = Math.floor(m / 60);
        return h + ':' + String(m % 60).padStart(2, '0') + ':' + String(sec).padStart(2, '0');
      }
      return String(m).padStart(2, '0') + ':' + String(sec).padStart(2, '0');
    },
    fmtStopwatch: function (s) {
      s = Math.max(0, s);
      var m = Math.floor(s / 60), sec = Math.floor(s % 60);
      var tenth = Math.floor((s - Math.floor(s)) * 10);
      if (m >= 60) {
        var h = Math.floor(m / 60);
        return h + ':' + String(m % 60).padStart(2, '0') + ':' +
          String(sec).padStart(2, '0') + '.' + tenth;
      }
      return String(m).padStart(2, '0') + ':' + String(sec).padStart(2, '0') + '.' + tenth;
    },
    syncModeUi: function () {
      var isStopwatch = this.mode === 'stopwatch';
      var box = document.querySelector('#timerModal .timer-box');
      if (box) box.classList.toggle('stopwatch', isStopwatch);
      var btn = $('timerStopwatch');
      if (btn) {
        btn.classList.toggle('active', isStopwatch);
        btn.textContent = isStopwatch ? '倒计时模式' : '秒表模式';
        btn.setAttribute('aria-pressed', isStopwatch ? 'true' : 'false');
      }
      var label = $('timerModeLabel');
      if (label) {
        label.textContent = isStopwatch ? '秒表' : '倒计时';
        label.classList.toggle('stopwatch', isStopwatch);
      }
      var total = this.totalSec;
      document.querySelectorAll('.tm-presets button').forEach(function (b) {
        b.classList.toggle('active', !isStopwatch &&
          parseInt(b.dataset.min, 10) * 60 === total);
      });
    },
    elapsed: function () {
      return this.running ? this.accum + (Date.now() - this.startAt) / 1000 : this.accum;
    },
    render: function () {
      var el = $('timerDisplay');
      el.classList.remove('warn', 'over');
      if (this.mode === 'countdown') {
        var r = this.totalSec - this.elapsed();
        if (r <= 0) {
          if (!this._overSignaled) { this._overSignaled = true; this.beep(); }
          el.textContent = '+' + this.fmt(-r);
          el.classList.add('over');
        } else {
          this._overSignaled = false;
          el.textContent = this.fmt(r);
          if (r <= 30) el.classList.add('warn');
        }
      } else {
        el.textContent = this.fmtStopwatch(this.elapsed());
      }
    },
    tick: function () { this.render(); },
    start: function () {
      if (this.running) return;
      if (this.mode === 'countdown' && this.totalSec - this.elapsed() <= 0) {
        // 已超时则重新开始
        this.accum = 0;
      }
      this.running = true;
      this.startAt = Date.now();
      var self = this;
      // 秒表用 100ms 刷新，十分之一秒位才看得出在走
      var period = this.mode === 'stopwatch' ? 100 : 250;
      this.tickHandle = setInterval(function () { self.tick(); }, period);
      this.render();
    },
    pause: function () {
      if (!this.running) return;
      this.accum = this.elapsed();
      this.running = false;
      clearInterval(this.tickHandle);
      this.render();
    },
    reset: function () {
      this.stop();
      if (this.mode === 'countdown') this.accum = 0;
      else this.accum = 0;
      this.render();
    },
    stop: function () {
      this.running = false;
      clearInterval(this.tickHandle);
      this.accum = 0;
      if (this.mode === 'countdown') { this.remainSec = this.totalSec; }
    },
    beep: function () {
      try {
        var ac = new (window.AudioContext || window.webkitAudioContext)();
        var osc = ac.createOscillator(), gain = ac.createGain();
        osc.connect(gain); gain.connect(ac.destination);
        osc.frequency.value = 880; gain.gain.value = 0.25;
        osc.start();
        setTimeout(function () { osc.stop(); ac.close(); }, 600);
      } catch (e) { /* 音频不可用忽略 */ }
    }
  };

  /* ════════════════════════════════════════════
   * 点名器
   * ════════════════════════════════════════════ */
  var Rollcall = {
    students: [], drawn: {}, rolling: false, handle: null,

    init: function () {
      var self = this;
      $('rollcallStart').addEventListener('click', function () {
        if (self.rolling) self.stopRoll();
        else self.startRoll();
      });
      $('rollcallReset').addEventListener('click', function () {
        self.drawn = {};
        self.renderList();
        $('rollcallDisplay').textContent = '准备就绪';
        $('rollcallDisplay').classList.remove('hit');
      });
    },
    load: function () {
      var self = this;
      return apiFetch('/study/lesson/' + PAGE.resourceId + '/online').then(function (d) {
        if (d && d.success) {
          self.students = d.students || [];
          if (window.LESSON_STUDENTS) window.LESSON_STUDENTS = self.students;
        } else {
          self.students = [];
        }
        self.renderList();
      }).catch(function () {
        self.students = window.LESSON_STUDENTS || [];
        self.renderList();
      });
    },
    pool: function () {
      var self = this;
      var noRepeat = $('rollcallNoRepeat').checked;
      return this.students.filter(function (s) {
        return !noRepeat || !self.drawn[s.id];
      });
    },
    startRoll: function () {
      var pool = this.pool();
      if (!this.students.length) {
        toast('暂无学生名单（需在管理端设置当前班级）');
        return;
      }
      if (!pool.length) {
        toast('全部学生已被点名，请重置记录');
        return;
      }
      this.rolling = true;
      var btn = $('rollcallStart');
      btn.innerHTML = '<i class="bi bi-hand-index-thumb"></i> 停止';
      var disp = $('rollcallDisplay');
      disp.classList.remove('hit');
      var self = this;
      this.handle = setInterval(function () {
        var s = pool[Math.floor(Math.random() * pool.length)];
        disp.textContent = s.name + '（' + (s.student_number || '') + '）';
      }, 60);
    },
    stopRoll: function () {
      clearInterval(this.handle);
      this.rolling = false;
      var btn = $('rollcallStart');
      btn.innerHTML = '<i class="bi bi-shuffle"></i> 开始点名';
      var pool = this.pool();
      if (!pool.length) return;
      var s = pool[Math.floor(Math.random() * pool.length)];
      var disp = $('rollcallDisplay');
      disp.textContent = s.name + '（' + (s.student_number || '') + '）';
      disp.classList.add('hit');
      this.drawn[s.id] = true;
      this.renderList();
    },
    renderList: function () {
      var box = $('rollcallList');
      box.innerHTML = '';
      if (!this.students.length) {
        box.innerHTML = '<div class="doc-empty">未获取到学生名单</div>';
        return;
      }
      this.students.forEach(function (s) {
        var chip = document.createElement('span');
        chip.className = 'rc-chip' + (Rollcall.drawn[s.id] ? ' drawn' : '');
        chip.textContent = s.name;
        box.appendChild(chip);
      });
    },
    open: function () {
      this.load();
    }
  };

  /* ════════════════════════════════════════════
   * 流程拓扑图画板 / 思维导图（独立应用 iframe 宿主）
   *   - 懒加载 static/lesson-tools 下的完整应用
   *   - postMessage 桥接：导出当前文档 / 打开课件文档
   *   - 教师保存到课件目录；学生只读打开
   * ════════════════════════════════════════════ */
  var LessonAppTools = {
    TOOLS: {
      flow: {
        modal: 'flowModal', frame: 'flowFrame', openList: 'flowOpenList',
        saveBtn: 'flowSaveBtn', label: '流程拓扑图', prefix: 'flow-'
      },
      mindmap: {
        modal: 'mindmapModal', frame: 'mindmapFrame', openList: 'mindmapOpenList',
        saveBtn: 'mindmapSaveBtn', label: '思维导图', prefix: 'mindmap-'
      }
    },
    state: {},
    _pendingExport: null,
    _pendingSaveTool: null,

    init: function () {
      var self = this;
      window.addEventListener('message', function (e) {
        if (e.origin !== window.location.origin) return;
        var d = e.data || {};
        if (d.source !== 'itstudy-lesson-tool') return;
        self.onMessage(d, e.source);
      });
      Object.keys(this.TOOLS).forEach(function (key) {
        var cfg = self.TOOLS[key];
        self.state[key] = { ready: false, pendingImport: null, pendingExport: false };
        var saveBtn = $(cfg.saveBtn);
        if (saveBtn) saveBtn.addEventListener('click', function () { self.requestSave(key); });
        var sel = $(cfg.openList);
        if (sel) sel.addEventListener('change', function () {
          var name = sel.value;
          sel.value = '';
          if (name) self.openDoc(key, name);
        });
        var frame = $(cfg.frame);
        if (frame) {
          // ready 消息之外的兜底：应用加载完成 1.5s 后仍无消息也放开按钮，
          // 避免静态资源被缓存/脚本异常时整个工具不可用
          frame.addEventListener('load', function () {
            setTimeout(function () {
              if (!self.state[key].ready) self.setReady(key);
            }, 1500);
          });
        }
      });

      var nameInput = $('toolNameInput');
      if (nameInput) {
        nameInput.addEventListener('keydown', function (e) {
          if (e.key === 'Enter') { e.preventDefault(); self.confirmSave(); }
          else if (e.key === 'Escape') { e.preventDefault(); self.closeNameDialog(); }
        });
      }
      if ($('toolNameOk')) $('toolNameOk').addEventListener('click', function () { self.confirmSave(); });
      if ($('toolNameCancel')) $('toolNameCancel').addEventListener('click', function () { self.closeNameDialog(); });
      if ($('toolNameClose')) $('toolNameClose').addEventListener('click', function () { self.closeNameDialog(); });
    },

    open: function (key) {
      var cfg = this.TOOLS[key];
      var st = this.state[key];
      if (!cfg || !st) return;
      var frame = $(cfg.frame);
      if (frame && !frame.getAttribute('src')) {
        var src = frame.getAttribute('data-src') || '';
        var sep = src.indexOf('?') >= 0 ? '&' : '?';
        frame.setAttribute('src', src + sep + 'embed=1');
      }
      show($(cfg.modal));
      this.refreshList(key);
    },

    setReady: function (key) {
      var cfg = this.TOOLS[key];
      var st = this.state[key];
      if (!cfg || !st) return;
      st.ready = true;
      var saveBtn = $(cfg.saveBtn);
      if (saveBtn) saveBtn.disabled = false;
      var sel = $(cfg.openList);
      if (sel) sel.disabled = false;
      if (st.pendingExport) {
        st.pendingExport = false;
        this.post(key, 'export-request', {});
      }
      if (st.pendingImport) {
        var data = st.pendingImport;
        st.pendingImport = null;
        this.post(key, 'import', { data: data });
      }
    },

    post: function (key, action, payload) {
      var cfg = this.TOOLS[key];
      var frame = cfg && $(cfg.frame);
      if (!frame || !frame.contentWindow) return;
      frame.contentWindow.postMessage({
        source: 'itstudy-lesson-host', tool: key, action: action, payload: payload || {}
      }, window.location.origin);
    },

    onMessage: function (d, source) {
      var key = d.tool;
      var cfg = this.TOOLS[key];
      if (!cfg || source !== $(cfg.frame).contentWindow) return;
      var st = this.state[key];
      if (!st) return;
      if (d.action === 'ready') { this.setReady(key); return; }
      if (d.action === 'export-result') {
        this._pendingExport = { tool: key, data: d.payload && d.payload.data };
        this.openNameDialog(key);
        return;
      }
      if (d.action === 'error') {
        toast((d.payload && d.payload.msg) || '操作失败', 4000);
        return;
      }
      if (d.action === 'imported') {
        toast('已从课件打开', 2600);
      }
    },

    requestSave: function (key) {
      var st = this.state[key];
      var cfg = this.TOOLS[key];
      if (!st || !cfg) return;
      if (!PAGE.isTeacher) { toast('只有教师可以保存到课件目录'); return; }
      if (!st.ready) {
        st.pendingExport = true;
        toast('图板正在加载，稍后会弹出保存窗口', 2500);
        return;
      }
      toast('正在读取当前' + cfg.label + '…', 1600);
      this.post(key, 'export-request', {});
    },

    defaultName: function (key) {
      var base = (PAGE.resourceTitle || '课堂') + '-' + this.TOOLS[key].label;
      return base.replace(/[^A-Za-z0-9_\-一-龥]/g, '_').slice(0, 50);
    },

    openNameDialog: function (key) {
      var pending = this._pendingExport;
      if (!pending || pending.tool !== key) return;
      this._pendingSaveTool = key;
      var input = $('toolNameInput');
      var title = $('toolNameTitle');
      if (title) title.textContent = '保存' + this.TOOLS[key].label + '到课件';
      if (input) { input.value = this.defaultName(key); }
      show($('toolNameModal'));
      if (input) { input.focus(); input.select(); }
    },

    closeNameDialog: function () {
      hide($('toolNameModal'));
      this._pendingExport = null;
      this._pendingSaveTool = null;
    },

    confirmSave: function () {
      var key = this._pendingSaveTool;
      var pending = this._pendingExport;
      var input = $('toolNameInput');
      if (!key || !pending) { this.closeNameDialog(); return; }
      var name = (input && input.value || '').trim();
      if (!name) { toast('名称不能为空'); return; }
      var self = this;
      var okBtn = $('toolNameOk');
      if (okBtn) okBtn.disabled = true;
      apiFetch('/study/lesson/' + PAGE.resourceId + '/tool-docs/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tool: key, name: name, data: pending.data })
      }).then(function (d) {
        if (d && d.success) {
          toast(d.msg || '已保存到课件目录', 2600);
          self.closeNameDialog();
          self.refreshList(key);
        } else {
          toast((d && (d.msg || d.message)) || '保存失败', 3500);
        }
      }).catch(function () { toast('保存失败', 3500); })
        .finally(function () { if (okBtn) okBtn.disabled = false; });
    },

    refreshList: function (key) {
      var cfg = this.TOOLS[key];
      var sel = $(cfg.openList);
      if (!sel) return;
      var self = this;
      apiFetch('/study/lesson/' + PAGE.resourceId + '/tool-docs/list?tool=' + encodeURIComponent(key))
        .then(function (d) {
          if (!d || !d.success) return;
          var current = sel.value;
          sel.innerHTML = '<option value="">从课件打开…</option>';
          (d.files || []).forEach(function (name) {
            var opt = document.createElement('option');
            opt.value = name;
            opt.textContent = name.replace(new RegExp('^' + cfg.prefix), '').replace(/\.json$/, '');
            sel.appendChild(opt);
          });
          if (!(d.files || []).length) {
            var empty = document.createElement('option');
            empty.value = '';
            empty.textContent = '暂无已保存' + cfg.label;
            empty.disabled = true;
            sel.appendChild(empty);
          }
          sel.value = current && Array.prototype.some.call(sel.options, function (o) { return o.value === current; }) ? current : '';
          sel.disabled = !self.state[key].ready;
        }).catch(function () {});
    },

    openDoc: function (key, name) {
      var self = this;
      var st = this.state[key];
      if (!st) return;
      if (!st.ready) {
        toast('图板正在加载，请稍后再试', 2500);
        return;
      }
      apiFetch('/study/lesson/' + PAGE.resourceId + '/tool-docs/get?tool=' + encodeURIComponent(key) +
        '&name=' + encodeURIComponent(name))
        .then(function (d) {
          if (d && d.success) {
            self.post(key, 'import', { data: d.data });
          } else {
            toast((d && (d.msg || d.message)) || '打开失败', 3000);
          }
        }).catch(function () { toast('打开失败', 3000); });
    }
  };

  /* ════════════════════════════════════════════
   * 电子文档抽屉（分类展示，树内 kind=doc 条目，服务端已按角色过滤）
   * ════════════════════════════════════════════ */
  var Docs = {
    DOC_GROUPS: [
      { key: 'activity_sheet', label: '活动单', icon: 'bi-clipboard-check' },
      { key: 'guide', label: '导学案', icon: 'bi-journal-text' },
      { key: 'design', label: '教学设计', icon: 'bi-file-earmark-ruled' },
      { key: 'handout', label: '教材分析', icon: 'bi-journal-richtext' },
      { key: 'exercise', label: '习题', icon: 'bi-pencil-square' },
      { key: 'answer', label: '参考答案', icon: 'bi-check2-square' },
      { key: 'material', label: '素材', icon: 'bi-collection' },
      { key: 'other', label: '其他', icon: 'bi-file-earmark' }
    ],

    init: function () {
      var self = this;
      $('docsClose').addEventListener('click', function () { self.toggle(false); });
      $('btnDocs').addEventListener('click', function () { self.toggle(); });
    },
    collect: function () {
      var groups = {};
      this.DOC_GROUPS.forEach(function (g) { groups[g.key] = []; });
      function walk(nodes) {
        (nodes || []).forEach(function (n) {
          (n.items || []).forEach(function (it) {
            if (it.kind === 'doc') {
              var cat = it.doc_category || 'guide';
              (groups[cat] || groups.other).push(it);
            }
          });
          walk(n.children);
        });
      }
      walk(PAGE.tree);
      return groups;
    },
    render: function () {
      var body = $('docsBody');
      body.innerHTML = '';
      var groups = this.collect();
      var total = 0;
      var self = this;
      this.DOC_GROUPS.forEach(function (g) {
        var list = groups[g.key] || [];
        var head = document.createElement('div');
        head.className = 'doc-group-title';
        head.innerHTML = '<i class="bi ' + g.icon + '"></i> ' + g.label + '（' + list.length + '）';
        body.appendChild(head);
        if (!list.length) {
          var empty = document.createElement('div');
          empty.className = 'doc-empty';
          empty.textContent = '暂无文档';
          body.appendChild(empty);
        }
        list.forEach(function (it) {
          total++;
          var item = document.createElement('div');
          item.className = 'doc-item';
          item.innerHTML = '<i class="bi bi-file-earmark"></i><span>' + escapeHtml(it.title) + '</span>';
          item.addEventListener('click', function () {
            self.toggle(false);
            if (window.Lesson && window.Lesson.openItem) window.Lesson.openItem(it.id);
          });
          body.appendChild(item);
        });
      });
      if (!total) {
        var tip = document.createElement('div');
        tip.className = 'doc-empty';
        tip.textContent = '当前课程未配置电子文档';
        body.appendChild(tip);
      }
    },
    toggle: function (force) {
      var drawer = $('docsDrawer');
      var willShow = (typeof force === 'boolean') ? force : drawer.classList.contains('hidden');
      if (willShow) { this.render(); show(drawer); }
      else hide(drawer);
    }
  };

  /* ════════════════════════════════════════════
   * 对外注册
   * ════════════════════════════════════════════ */
  window.LessonTools = {
    toast: toast,
    apiFetch: apiFetch,
    blackboard: Blackboard,
    drawPen: DrawPen,
    timer: Timer,
    rollcall: Rollcall,
    mindmap: LessonAppTools,
    flow: LessonAppTools,
    docs: Docs,
    open: function (tool) {
      switch (tool) {
        case 'blackboard': return Blackboard.open();
        case 'docs': return Docs.toggle();
        case 'flow': return LessonAppTools.open('flow');
        case 'mindmap': return LessonAppTools.open('mindmap');
        case 'rollcall': show($('rollcallModal')); return Rollcall.open();
        case 'timer': Timer.syncModeUi(); Timer.render(); show($('timerModal')); return;
        case 'draw': return DrawPen.toggle();
      }
    }
  };

  function initAll() {
    Blackboard.init();
    DrawPen.init();
    Timer.init();
    Rollcall.init();
    LessonAppTools.init();
    Docs.init();
    // 弹窗关闭统一收口（X 按钮 / 遮罩点击 / ESC 三路同口径）：
    // 停点名器滚动（避免 interval 空转更新隐藏 DOM）；倒计时运行中关闭
    // 则暂停（此前关闭弹窗后 250ms interval 继续空转，弹窗关闭时到点
    // 蜂鸣仍会响）
    function closeModal(id) {
      if (id === 'toolNameModal') { LessonAppTools.closeNameDialog(); return; }
      var m = $(id);
      if (!m) return;
      hide(m);
      if (id === 'rollcallModal' && Rollcall.rolling) {
        Rollcall.stopRoll();
      }
      if (id === 'timerModal' && Timer.running) {
        Timer.pause();
        toast(Timer.mode === 'stopwatch' ? '计时已暂停' : '倒计时已暂停');
      }
    }
    document.querySelectorAll('[data-close]').forEach(function (b) {
      b.addEventListener('click', function () { closeModal(b.dataset.close); });
    });
    document.querySelectorAll('.tool-modal').forEach(function (m) {
      m.addEventListener('click', function (e) {
        if (e.target === m) closeModal(m.id);
      });
    });
    // ESC 关闭最上层可见弹窗（此前弹窗无键盘关闭路径）
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      var modals = document.querySelectorAll('.tool-modal:not(.hidden)');
      if (!modals.length) return;
      closeModal(modals[modals.length - 1].id);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAll);
  } else {
    initAll();
  }
})();
