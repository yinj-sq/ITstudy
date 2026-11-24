/**
 * quiz-collector.js — 测验收集 SDK
 *
 * 磁盘注入：管理员上传资源时 inject_quiz_collector() 把本脚本引用
 * 写入 HTML 文件（配合 /static/sdk/collector-base.js）。
 * 页面加载后调用 QuizCollector.init(resourceId)
 */
(function () {
  'use strict';

  if (window.QuizCollector) return;

  var Base = window.ITStudyCollectorBase;
  if (!Base) { console.warn('[QuizCollector] collector-base.js 未加载，使用内建回退'); }

  var QuizCollector = {
    _resourceId: null,
    _submitted: false,
    _startTime: Date.now(),
    _answers: Object.create(null),
    _questions: Object.create(null),
    _scores: {},
    _lastReportAt: 0,
    _lastFingerprint: '',
    _submitRequested: false,

    _sourceFile: function () {
      var source = window.__ITSTUDY_QUIZ_SOURCE_FILE__ || '';
      if (source) return String(source).replace(/\\/g, '/').replace(/^\/+/, '');
      try {
        var m = /\/static\/uploads\/[^/]+\/(.+)$/.exec(location.pathname || '') ||
          /\/study\/lesson\/\d+\/item\/[^/]+\/content\/(.+)$/.exec(location.pathname || '');
        if (m) return decodeURIComponent(m[1]);
      } catch (e) { /* ignore */ }
      return '';
    },

    /* ── 初始化入口 ── */
    init: function (resourceId) {
      // 互斥：如果 InjectCollector 已就绪，QuizCollector 不启动
      if (window.InjectCollector && window.InjectCollector.getResourceId && window.InjectCollector.getResourceId()) {
        console.log('[QuizCollector] InjectCollector 已就绪，跳过动态注入');
        return;
      }
      // 采集块可能被注入到 <head>，此时 body 尚未解析；延迟到 DOM 就绪再启动
      if (!document.body) {
        document.addEventListener('DOMContentLoaded', function () {
          QuizCollector.init(resourceId);
        });
        return;
      }
      if (window.__quiz_active) return;
      window.__quiz_active = true;

      this._resourceId = resourceId;
      this._startTime = Date.now();

      this._bindFormChanges();
      this._bindSubmitButtons();
      this._bindChoiceButtons();
      this._bindFormSubmit();
      this._startObserver();
    },

    getResourceId: function () { return this._resourceId; },

    /* ── 自定义按钮式选项（如 KNN/K-means）──
       页面没有 input/radio，选项是动态生成的 button；使用事件委托记录，
       题目编号优先取 data-qid，其次从“问题 1/10”“第 1 题”等文字推导。 */
    _bindChoiceButtons: function () {
      var self = this;
      document.addEventListener('click', function (e) {
        var btn = e.target && e.target.closest ? e.target.closest(
          'button, [role="button"], [role="radio"], [role="checkbox"], .option, .choice, .answer-option') : null;
        if (!btn || !self._isChoiceButton(btn)) return;
        var key = self._choiceQuestionKey(btn);
        var answer = (btn.textContent || '').replace(/\s+/g, ' ').trim();
        if (key && answer) self._answers[key] = answer;
        self._captureQuestion(btn, true);
        self._submitted = false;
      }, true);
    },

    _isChoiceButton: function (btn) {
      if (Base && Base.isChoiceButton) return Base.isChoiceButton(btn);
      return /^option[-_]/i.test(btn.id || '') || btn.hasAttribute('data-option');
    },

    _choiceQuestionKey: function (btn) {
      return Base ? Base.questionKey(btn) : (btn.getAttribute('data-qid') || btn.id);
    },

    _captureQuestion: function (el, clicked) {
      if (!Base || !Base.questionSnapshot) return;
      var key = Base.questionKey(el);
      var previous = this._questions[key];
      if (previous && previous.evidence === 'explicit') return;
      this._questions[key] = Base.questionSnapshot(el, clicked, previous && previous.answer);
    },

    /* 供自定义控件/canvas 页面显式提供逐题数据，避免猜测 JS 内部状态。 */
    recordQuestion: function (question) {
      if (!question || question.id === undefined || question.id === null) return;
      var key = String(question.id);
      this._questions[key] = Object.assign({prompt: '', type: 'unknown', options: [],
        answer: null, correct_answer: null, is_correct: null}, question,
      {id: key, evidence: 'explicit'});
      if (question.answer !== undefined) this._answers[key] = question.answer;
    },

    /* 供页面作者显式上报答案（可选；第三个参数可附题干与选项）。 */
    recordAnswer: function (questionId, answer, detail) {
      if (questionId !== undefined && questionId !== null && answer !== undefined) {
        this._answers[String(questionId)] = answer;
        if (detail) this.recordQuestion(Object.assign({}, detail, {id: questionId, answer: answer}));
      }
    },

    submit: function (summary) {
      this._submitRequested = true;
      this._collectAllAnswers();
      this._submitData(summary ? {totalScore: summary.total_score, maxScore: summary.max_score} : null);
    },

    /* ── 表单变化追踪（委托事件覆盖动态渲染；排除密码/身份字段）── */
    _bindFormChanges: function () {
      var self = this;
      ['input', 'change'].forEach(function (eventName) {
        document.addEventListener(eventName, function (event) {
          var el = event.target;
          if (Base && Base.isAnswerControl(el)) {
            self._collectAnswer(el);
            self._submitted = false;
          }
        }, true);
      });
    },

    _collectAnswer: function (el) {
      if (Base && !Base.isAnswerControl(el)) return;
      var name = Base ? Base.generateAnswerId(el) : (el.name || el.id);
      if (!name) return;
      this._captureQuestion(el, false);
      if (el.type === 'radio') {
        var snapshot = this._questions[name];
        if (el.checked) this._answers[name] = el.value;
        else if (snapshot && !snapshot.answer.length) this._answers[name] = '';
      } else if (el.type === 'checkbox') {
        // 从当前整组重建，避免取消勾选后仍保留旧选项。
        var question = this._questions[name];
        this._answers[name] = question ? question.answer.slice() : (el.checked ? [el.value] : []);
      } else if (el.tagName === 'SELECT' && el.multiple) {
        this._answers[name] = Array.prototype.map.call(el.selectedOptions, function (opt) { return opt.value; });
      } else {
        this._answers[name] = el.value;
      }
    },

    /* ── 提交按钮拦截 ── */
    _bindSubmitButtons: function () {
      var self = this;
      document.addEventListener('click', function (event) {
        var btn = event.target && event.target.closest ? event.target.closest(
          'button, input[type="submit"], a.btn, a.button') : null;
        if (!btn || self._isChoiceButton(btn)) return;
        var text = (btn.textContent || btn.value || btn.title || '').toLowerCase();
        if (/提交|检查|评分|判分|交卷|确认|submit|check|grade|score|finish/.test(text)) {
          self._scheduleCapture();
        }
      }, true);
    },

    _scheduleCapture: function () {
      var self = this;
      this._submitRequested = true;
      this._collectAllAnswers();
      [800, 2000, 4000].forEach(function (delay) {
        setTimeout(function () { self._tryCapture(); }, delay);
      });
    },

    _bindFormSubmit: function () {
      var self = this;
      document.addEventListener('submit', function () { self._scheduleCapture(); }, true);
    },

    _collectAllAnswers: function () {
      var self = this;
      document.querySelectorAll('input, textarea, select').forEach(function (el) {
        if (Base && Base.isAnswerControl(el)) self._collectAnswer(el);
      });
      var seen = Object.create(null);
      document.querySelectorAll('button, [role="radio"], [role="checkbox"], .option, .choice, .answer-option').forEach(function (el) {
        if (!self._isChoiceButton(el)) return;
        var key = self._choiceQuestionKey(el);
        if (!seen[key]) { self._captureQuestion(el, false); seen[key] = true; }
      });
      // 显式适配优先于 DOM 猜测，支持 canvas 或框架内部保存的题库。
      var declared = window.ITSTUDY_QUIZ_QUESTIONS;
      if (Array.isArray(declared)) declared.forEach(function (question) { self.recordQuestion(question); });
    },

    /* ── MutationObserver（等待一轮渲染完成，避免只读到半份结果）── */
    _startObserver: function () {
      var self = this;
      var timer;
      if (!document.body) return;
      var observer = new MutationObserver(function () {
        if (self._submitRequested || (Base && Base.isQuizComplete())) {
          clearTimeout(timer);
          timer = setTimeout(function () { self._tryCapture(); }, 120);
        }
      });
      observer.observe(document.body, { childList: true, subtree: true, characterData: true,
        attributes: true, attributeFilter: ['class', 'style', 'hidden', 'data-is-correct'] });
    },

    /* ── 分数捕获 ── */
    _tryCapture: function () {
      this._collectAllAnswers();
      var scoreResult = null;
      if (Base) {
        scoreResult = Base.detectScore();
      } else {
        // 回退：简单正则
        var bodyText = (document.body && document.body.innerText) || '';
        var m = /(?:得分|成绩|总分|Score)\s*[：:]\s*(\d+\.?\d*)\s*\/\s*(\d+\.?\d*)/i.exec(bodyText);
        if (m) scoreResult = { totalScore: parseFloat(m[1]), maxScore: parseFloat(m[2]) };
      }

      // 扩展形态（v5.0.0）：纯等级/证书测验与"答对题数/总题数"式测验。
      // 页面作者可设置：window.ITSTUDY_QUIZ_GRADE / ITSTUDY_QUIZ_CORRECT /
      // ITSTUDY_QUIZ_TOTAL_QUESTIONS；未设等级时服务端按 total/max 推导。
      var hasExtended = window.ITSTUDY_QUIZ_GRADE ||
        typeof window.ITSTUDY_QUIZ_CORRECT === 'number';

      var resultVisible = Base && Array.prototype.some.call(document.querySelectorAll(
        '#test-result, #quiz-result, .quiz-result, .result-summary, #result, .result'),
      function (node) { return Base.isVisible(node); });
      var canSubmit = this._submitRequested || resultVisible || hasExtended;
      // 题干中的「总分」或选项中的「正确」不是成绩；仅在提交/结果出现后读取。
      if (!canSubmit) scoreResult = null;
      if ((canSubmit || window.__ITSTUDY_QUIZ_DRY_RUN__) &&
          (scoreResult || Object.keys(this._answers).length > 0 || hasExtended)) {
        this._submitData(scoreResult);
      }
    },

    /* ── 提交数据 ── */
    _submitData: function (scoreResult) {
      var hasAnswers = Object.keys(this._answers).length > 0;
      var hasExtended = window.ITSTUDY_QUIZ_GRADE ||
        typeof window.ITSTUDY_QUIZ_CORRECT === 'number';
      if (!hasAnswers && !scoreResult && !hasExtended) return;

      var correct = null, totalQuestions = null;
      if (typeof window.ITSTUDY_QUIZ_CORRECT === 'number') correct = window.ITSTUDY_QUIZ_CORRECT;
      if (typeof window.ITSTUDY_QUIZ_TOTAL_QUESTIONS === 'number') totalQuestions = window.ITSTUDY_QUIZ_TOTAL_QUESTIONS;
      // 页面没有显式变量时，使用结果区读到的题数（如 KNN 的 #correct-count）
      if (correct === null && scoreResult && scoreResult.correctCount !== undefined) {
        correct = scoreResult.correctCount;
      }
      if (totalQuestions === null && scoreResult && scoreResult.questionCount !== undefined) {
        totalQuestions = scoreResult.questionCount;
      }

      // 终局仍允许补齐延迟渲染的逐题反馈；载荷指纹去重，重复点击不重复提交。
      // 模拟检测模式允许页面在试答过程中多次更新结果。
      var dryRun = !!window.__ITSTUDY_QUIZ_DRY_RUN__;
      var hasScore = scoreResult !== null && scoreResult !== undefined &&
        scoreResult.totalScore !== null && scoreResult.totalScore !== undefined;
      if (!dryRun && (hasScore || window.ITSTUDY_QUIZ_GRADE || correct !== null)) {
        this._submitted = true;
      }

      var duration = Math.round((Date.now() - this._startTime) / 1000);

      var payload = {
        schema_version: 3,
        resource_id: this._resourceId,
        source_file: this._sourceFile(),
        quiz_name: document.title || '',
        answers: JSON.parse(JSON.stringify(this._answers)),
        questions: Object.keys(this._questions).map(function (key) {
          return QuizCollector._questions[key];
        }),
        total_score: scoreResult ? scoreResult.totalScore : null,
        max_score: scoreResult ? scoreResult.maxScore : null,
        grade: window.ITSTUDY_QUIZ_GRADE || null,
        correct_count: correct,
        question_count: totalQuestions,
        duration: duration
      };

      if (!dryRun) {
        var fingerprint = JSON.stringify(Object.assign({}, payload, {duration: 0}));
        if (fingerprint === this._lastFingerprint) return;
        this._lastFingerprint = fingerprint;
      }

      if (dryRun) {
        // 模拟检测：不发数据库，只回报给检测页/检测接口
        var now = Date.now();
        // 成绩一旦出现立即上报，不能被“仅答案”上报的节流窗口吞掉
        if (hasScore || now - this._lastReportAt > 500) {
          this._lastReportAt = now;
          try {
            if (window.opener && !window.opener.closed) {
              window.opener.postMessage(
                { type: 'ITSTUDY_QUIZ_DRY_RUN_RESULT', payload: payload }, '*');
            }
          } catch (e) { /* ignore */ }
          try {
            var reportUrl = window.__ITSTUDY_QUIZ_REPORT_URL__;
            var csrf = window.__ITSTUDY_QUIZ_CSRF__ || '';
            if (reportUrl) {
              fetch(reportUrl, {
                method: 'POST',
                headers: {
                  'Content-Type': 'application/json',
                  'X-CSRFToken': csrf
                },
                credentials: 'same-origin',
                body: JSON.stringify(payload)
              }).catch(function () { /* 检测页仍可通过 postMessage 接收 */ });
            }
          } catch (e2) { /* ignore */ }
        }
        return;
      }

      // iframe 场景（/study/link sandbox 打开）：opaque origin 下 fetch 带凭据
      // 会被 CORS 拒绝，统一走 postMessage 由父窗口携带 CSRF 头转发完整载荷。
      // 非 iframe 场景（极少）回退为 fetch 直提。
      if (window.parent && window.parent !== window) {
        window.parent.postMessage(
          Object.assign({ type: 'ITSTUDY_QUIZ_RESULT' }, payload),
          '*'
        );
        return;
      }

      // fetch 直接提交
      if (Base) {
        Base.submitToServer('/api/resource_quiz/submit', payload)
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (data.success && Base) {
              Base.showBadge(payload.total_score || 0, payload.max_score || 0);
            } else if (QuizCollector._lastFingerprint === fingerprint) {
              QuizCollector._lastFingerprint = '';
            }
          })
          .catch(function () {
            if (QuizCollector._lastFingerprint === fingerprint) QuizCollector._lastFingerprint = '';
          });
      }
    }
  };

  // 自动初始化（从全局变量读取 resource_id）
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      if (window.__INJECT_RESOURCE_ID__) {
        QuizCollector.init(window.__INJECT_RESOURCE_ID__);
      }
    });
  } else {
    if (window.__INJECT_RESOURCE_ID__) {
      QuizCollector.init(window.__INJECT_RESOURCE_ID__);
    }
  }

  window.QuizCollector = QuizCollector;
})();
