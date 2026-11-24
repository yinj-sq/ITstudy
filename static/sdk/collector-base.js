/**
 * collector-base.js — 测验收集器公共基类
 *
 * 提供 quiz-collector（磁盘/运行时注入采集）的共用能力：
 * - 分数检测（正则 + DOM 选择器回退）
 * - 完成状态检测
 * - 徽章显示
 * - 答案 ID 生成
 * - fetch 提交封装
 *
 * 依赖：无。纯原生 JS。
 */
(function () {
  'use strict';

  if (window.ITStudyCollectorBase) return;

  function getCookie(name) {
    var parts = document.cookie ? document.cookie.split(';') : [];
    for (var i = 0; i < parts.length; i++) {
      var part = parts[i].trim();
      if (part.indexOf(name + '=') === 0) {
        return decodeURIComponent(part.substring(name.length + 1));
      }
    }
    return '';
  }

  var Base = {
    /* ── 分数检测正则（中英文，10+ 种模式）── */
    SCORE_PATTERNS: [
      /得分\s*[：:]\s*(\d+\.?\d*)\s*\/\s*(\d+\.?\d*)/,
      /成绩\s*[：:]\s*(\d+\.?\d*)\s*\/\s*(\d+\.?\d*)/,
      /总分\s*[：:]\s*(\d+\.?\d*)\s*\/\s*(\d+\.?\d*)/,
      /总得分\s*[：:]\s*(\d+\.?\d*)\s*\/\s*(\d+\.?\d*)/,
      /合计\s*[：:]\s*(\d+\.?\d*)\s*\/\s*(\d+\.?\d*)/,
      /总计\s*[：:]\s*(\d+\.?\d*)\s*\/\s*(\d+\.?\d*)/,
      /Score\s*[：:]\s*(\d+\.?\d*)\s*\/\s*(\d+\.?\d*)/i,
      /Total\s*[：:]\s*(\d+\.?\d*)\s*\/\s*(\d+\.?\d*)/i,
      /答对\s*(\d+\.?\d*)\s*题\s*\/\s*共\s*(\d+\.?\d*)\s*题/,
      /正确\s*(\d+\.?\d*)\s*[\/／]\s*(\d+\.?\d*)/,
      /正确率\s*[：:]\s*(\d+\.?\d*)\s*%/,
      /得分\s*[：:]\s*(\d+\.?\d*)\s*分/,
      /成绩\s*[：:]\s*(\d+\.?\d*)\s*分/,
      /分数\s*[：:]\s*(\d+\.?\d*)\s*分/,
    ],

    /* ── 完成检测关键词 ── */
    COMPLETE_KEYWORDS: [
      '提交成功', '成绩', '得分', '总分', '考试完成',
      '测验完成', '测试完成', '答题结束', '分数', '测试结果',
      '正确率', '正确数', '答对', 'result', 'score', 'submitted', 'completed',
      'congratulations', 'correct', 'incorrect'
    ],

    /* 元素是否真实可见（隐藏证书/模板占位不得参与成绩检测） */
    isVisible: function (el) {
      if (!el) return false;
      try {
        var style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' ||
            style.opacity === '0') return false;
        var rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      } catch (e) {
        return false;
      }
    },

    _numberFrom: function (el) {
      if (!this.isVisible(el)) return null;
      var raw = (el.textContent || '').replace(/,/g, '');
      var m = /(-?\d+(?:\.\d+)?)/.exec(raw);
      return m ? parseFloat(m[1]) : null;
    },

    /* ── 通用结果区检测：correct-count / total-questions / accuracy ──
       适用于“按钮答题 + 自定义结果卡片”的 HTML 测验（如 KNN/K-means），
       不依赖页面作者额外埋点。
    */
    detectResultStats: function () {
      var resultRoots = ['#test-result', '#quiz-result', '.quiz-result',
        '.result-summary', '#result', '.result'];
      var rootVisible = false;
      var roots = resultRoots.map(function (sel) {
        var el = document.querySelector(sel);
        if (el && this.isVisible(el)) rootVisible = true;
        return el;
      }, this);
      if (!rootVisible) return null;

      var correctEl = document.getElementById('correct-count');
      var totalEl = document.getElementById('total-questions');
      var accuracyEl = document.getElementById('accuracy');
      var correct = this._numberFrom(correctEl);
      var total = this._numberFrom(totalEl);
      var accuracy = this._numberFrom(accuracyEl);
      var totalScore = null;
      if (accuracy !== null) {
        totalScore = accuracy;
      } else if (correct !== null && total !== null && total > 0) {
        totalScore = Math.round(correct / total * 1000) / 10;
      }
      if (totalScore === null) return null;
      return {
        totalScore: totalScore,
        maxScore: 100,
        correctCount: correct,
        questionCount: total,
        source: 'dom-result'
      };
    },

    /* ── 分数检测 ── */
    detectScore: function () {
      // 先读可见结果区，避免隐藏证书里的“得分：100分”占位文本被误采
      var stats = this.detectResultStats();
      if (stats) return stats;

      var text = (document.body && document.body.innerText) || '';
      for (var i = 0; i < this.SCORE_PATTERNS.length; i++) {
        var m = this.SCORE_PATTERNS[i].exec(text);
        if (m) {
          var score = parseFloat(m[1]);
          var max = m[2] ? parseFloat(m[2]) : null;
          if (!isNaN(score) && score >= 0) {
            return { totalScore: score, maxScore: max };
          }
        }
      }

      // CSS 选择器回退（仅可见元素）
      var selEl = document.querySelector('[data-score], .score, #score, .result-score, .total-score');
      if (selEl && this.isVisible(selEl)) {
        var selText = selEl.textContent || '';
        var m2 = /(\d+\.?\d*)\s*\/\s*(\d+\.?\d*)/.exec(selText);
        if (m2) return { totalScore: parseFloat(m2[1]), maxScore: parseFloat(m2[2]) };
        var m3 = /(\d+\.?\d*)/.exec(selText);
        if (m3) return { totalScore: parseFloat(m3[1]), maxScore: null };
      }

      return null;
    },

    /* ── 完成状态检测 ── */
    isQuizComplete: function () {
      if (this.detectResultStats()) return true;
      var bodyText = (document.body && document.body.innerText) || '';
      for (var i = 0; i < this.COMPLETE_KEYWORDS.length; i++) {
        if (bodyText.toLowerCase().indexOf(this.COMPLETE_KEYWORDS[i].toLowerCase()) !== -1) {
          return true;
        }
      }
      return false;
    },

    /* ── 徽章显示 ── */
    showBadge: function (score, max, text, color) {
      // 移除已有徽章
      var existing = document.getElementById('__itstudy_badge__');
      if (existing) existing.remove();

      text = text || '成绩已提交';
      color = color || '#22c55e';
      var display = max ? score + ' / ' + max : String(score);

      var badge = document.createElement('div');
      badge.id = '__itstudy_badge__';
      badge.style.cssText =
        'position:fixed;bottom:24px;right:24px;z-index:99999;' +
        'background:' + color + ';color:#fff;padding:10px 18px;border-radius:12px;' +
        'font-size:14px;font-family:sans-serif;box-shadow:0 4px 16px rgba(0,0,0,0.2);' +
        'pointer-events:none;transition:opacity 0.4s ease;opacity:1;';
      badge.textContent = '✓ ' + text + '  ' + display;
      document.body.appendChild(badge);

      // 5s 后自动消失
      setTimeout(function () {
        badge.style.opacity = '0';
        setTimeout(function () { if (badge.parentNode) badge.parentNode.removeChild(badge); }, 400);
      }, 5000);
    },

    /* ── 逐题快照：保留题干、完整选项与实际选择，不只保存 value/on ── */
    questionScope: function (el) {
      var root = el.closest('[data-qid], [data-question-id], [data-question], fieldset, ' +
        '.question, .quiz-question, .question-item, .quiz-item') ||
        el.closest('#quiz-container, .quiz-container, .quiz, [id*="quiz"]');
      if (root) return root;
      root = el.parentElement || document.body;
      if (/^(radio|checkbox)$/.test(el.type) && el.name) {
        var group = Array.prototype.filter.call(document.querySelectorAll('input'), function (input) {
          return input.type === el.type && input.name === el.name && input.form === el.form;
        });
        while (root.parentElement && !group.every(function (input) { return root.contains(input); })) root = root.parentElement;
      }
      return root;
    },

    cleanText: function (value) {
      return String(value == null ? '' : value).replace(/\s+/g, ' ').trim();
    },

    isAnswerControl: function (el) {
      if (!el || !el.matches('input, select, textarea') ||
          el.closest('[data-itstudy-ignore], #__itstudy_badge__')) return false;
      if (el.tagName === 'INPUT' && !/^(radio|checkbox|text|number)$/i.test(el.type)) return false;
      return !/^(csrf.*|password|username|name|student[_-]?(name|number|id)|phone|email|readonly_code)$/i.test(el.name || el.id || '');
    },

    isChoiceButton: function (el) {
      if (!el || el.matches('input, select, textarea') || el.querySelector('input, select, textarea')) return false;
      var text = this.cleanText(el.textContent);
      if (/^(提交|检查|评分|判分|交卷|确认|下一题|上一题|重新|返回|submit|check|next|back|retry)/i.test(text)) return false;
      return /^option[-_]/i.test(el.id || '') ||
        el.matches('[data-answer], [data-option], [data-choice], [role="radio"], [role="checkbox"], .option, .choice, .answer-option') ||
        (!!el.closest('[data-qid], [data-question], .question, .quiz-question') && /^[A-Z][.、．)）\s]/.test(text));
    },

    questionPrompt: function (root, el) {
      var prompt = root.getAttribute('data-prompt') || root.getAttribute('data-question-text');
      if (prompt) return this.cleanText(prompt).slice(0, 4000);
      var title = root.querySelector('[data-prompt], .question-text, .question-title, .prompt, .stem') ||
        root.querySelector('legend, h1, h2, h3, h4, h5, h6');
      if (title) {
        var text = this.cleanText(title.textContent);
        var paragraph = root.querySelector('p');
        if (/^(问题\s*\d+\s*\/\s*\d+|第\s*\d+\s*题|Question\s*\d+)\s*$/i.test(text) &&
            paragraph && !paragraph.closest('.option, .choice, .feedback')) text += ' ' + this.cleanText(paragraph.textContent);
        return text.slice(0, 4000);
      }
      if (el && el.labels && el.labels.length && !/^(radio|checkbox)$/.test(el.type)) {
        return this.cleanText(el.labels[0].textContent).slice(0, 4000);
      }
      var copy = root.cloneNode(true);
      copy.querySelectorAll('script, style, input, select, textarea, button, label, ' +
        '[role="radio"], [role="checkbox"], .option, .choice, .options, .choices, ' +
        '.feedback, .explanation, .question-result, .correct-answer').forEach(function (node) { node.remove(); });
      return this.cleanText(copy.textContent).slice(0, 4000);
    },

    questionKey: function (el, root) {
      root = root || this.questionScope(el);
      var explicit = el.getAttribute('data-qid') || root.getAttribute('data-qid') ||
        root.getAttribute('data-question-id') || root.getAttribute('data-question');
      if (explicit) return String(explicit);
      if (this.isAnswerControl(el) && el.name) return el.name.replace(/\[\]$/, '');
      var prompt = this.questionPrompt(root, el);
      var m = /问题\s*(\d+)\s*\/\s*\d+/.exec(prompt) ||
        /第\s*(\d+)\s*题/.exec(prompt) || /Question\s*(\d+)/i.exec(prompt);
      if (m) return 'q' + m[1];
      if (this.isAnswerControl(el) && el.id && !/^(radio|checkbox)$/.test(el.type)) return el.id;
      // 动态测验可能反复复用同一个容器：无题号时用题干生成稳定键。
      var seed = prompt || root.id || ('control_' + Array.prototype.indexOf.call(
        document.querySelectorAll('input, select, textarea, button, [role="radio"]'), el));
      var hash = 0;
      for (var i = 0; i < seed.length; i++) hash = ((hash << 5) - hash + seed.charCodeAt(i)) | 0;
      return 'q_' + (hash >>> 0).toString(36);
    },

    optionLabel: function (el) {
      if (el.labels && el.labels.length) return this.cleanText(el.labels[0].textContent);
      var label = el.closest('label');
      if (label) return this.cleanText(label.textContent);
      if (el.tagName === 'INPUT') {
        var next = el.nextSibling;
        if (next && this.cleanText(next.textContent)) return this.cleanText(next.textContent);
        return this.cleanText(el.getAttribute('aria-label') || el.value);
      }
      return this.cleanText(el.textContent || el.getAttribute('aria-label'));
    },

    questionSnapshot: function (el, clicked, previous) {
      var self = this;
      var root = this.questionScope(el);
      var native = this.isAnswerControl(el);
      var type = native ? (/^(radio|checkbox)$/.test(el.type) ?
        (el.type === 'checkbox' ? 'multiple' : 'single') :
        (el.tagName === 'SELECT' ? (el.multiple ? 'multiple' : 'single') : 'text')) :
        (root.getAttribute('data-type') === 'multiple' || el.getAttribute('role') === 'checkbox' ? 'multiple' : 'single');
      var choices = [];
      if (native && /^(radio|checkbox)$/.test(el.type)) {
        choices = Array.prototype.filter.call(root.querySelectorAll('input'), function (input) {
          return input.type === el.type && (!el.name || input.name === el.name);
        });
      } else if (native && el.tagName === 'SELECT') {
        choices = Array.prototype.filter.call(el.options, function (option) { return option.value !== ''; });
      } else if (!native) {
        choices = Array.prototype.filter.call(root.querySelectorAll(
          'button, [role="radio"], [role="checkbox"], [data-option], .option, .choice, .answer-option'),
        function (button) { return self.isChoiceButton(button); });
      }
      var rawValues = choices.map(function (choice) {
        return choice.getAttribute('data-option') || choice.getAttribute('data-choice') ||
          choice.getAttribute('data-answer') || choice.getAttribute('value') || '';
      });
      var options = choices.map(function (choice, index) {
        var label = self.optionLabel(choice);
        var value = rawValues[index];
        if (!value || rawValues.indexOf(value) !== rawValues.lastIndexOf(value)) {
          var letter = /^([A-Z])[.、．)）\s]/.exec(label);
          value = letter ? letter[1] : 'option_' + (index + 1);
        }
        return {value: value, label: label || value};
      });
      var selected = choices.reduce(function (values, choice, index) {
        if (choice.checked || choice.selected || choice.getAttribute('aria-checked') === 'true' ||
            choice.getAttribute('aria-pressed') === 'true' || choice.matches('.selected, .is-selected')) {
          values.push(options[index].value);
        }
        return values;
      }, []);
      if (!native && clicked) {
        var chosen = choices.indexOf(el);
        if (chosen >= 0) {
          var value = options[chosen].value;
          if (type === 'multiple') {
            selected = Array.isArray(previous) ? previous.slice() : selected;
            selected = selected.indexOf(value) < 0 ? selected.concat([value]) :
              selected.filter(function (entry) { return entry !== value; });
          } else selected = [value];
        }
      } else if (!native && !selected.length && Array.isArray(previous)) selected = previous.slice();
      var question = {id: this.questionKey(el, root), prompt: this.questionPrompt(root, el),
        type: type, options: options, answer: type === 'text' ? el.value : selected,
        correct_answer: null, is_correct: null, evidence: 'unknown'};
      var correct = root.getAttribute('data-correct-answer');
      if (correct === null && native) correct = el.getAttribute('data-correct-answer');
      if (correct !== null) {
        try { correct = JSON.parse(correct); } catch (e) { /* 字符串答案 */ }
        if (type !== 'text') {
          var values = Array.isArray(correct) ? correct : String(correct).split(/[,，]/);
          correct = values.map(function (value) {
            value = self.cleanText(value);
            var option = options.filter(function (entry) {
              return entry.value === value || entry.label === value ||
                (new RegExp('^' + value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '[.、．)）\\s]')).test(entry.label);
            });
            return option.length === 1 ? option[0].value : value;
          });
        }
        question.correct_answer = correct;
        question.evidence = 'data-attribute';
      } else {
        var marked = choices.reduce(function (values, choice, index) {
          if (choice.getAttribute('data-correct') === 'true' || choice.matches('.is-correct, .correct')) {
            values.push(options[index].value);
          }
          return values;
        }, []);
        if (marked.length) { question.correct_answer = marked; question.evidence = 'dom-feedback'; }
      }
      var verdict = root.getAttribute('data-is-correct');
      if (verdict === 'true' || verdict === 'false') {
        question.is_correct = verdict === 'true';
        question.evidence = 'data-attribute';
      } else {
        var feedback = root.querySelector('.feedback, .question-result, [data-feedback]');
        if (feedback && this.isVisible(feedback)) {
          var text = this.cleanText(feedback.textContent);
          if (/^(回答正确|答对了|正确[！!。]|correct\b)/i.test(text)) question.is_correct = true;
          if (/^(回答错误|答错了|错误[！!。]|incorrect\b)/i.test(text)) question.is_correct = false;
          if (question.is_correct !== null) question.evidence = 'dom-feedback';
        }
      }
      return question;
    },

    /* ── 题目 ID 生成 ── */
    generateAnswerId: function (el) {
      return this.questionKey(el);
    },

    /* ── fetch 提交封装 ── */
    submitToServer: function (url, payload) {
      var headers = { 'Content-Type': 'application/json' };
      var csrfToken = getCookie('csrf_token');
      if (csrfToken) headers['X-CSRFToken'] = csrfToken;
      return fetch(url, {
        method: 'POST',
        headers: headers,
        credentials: 'same-origin',
        body: JSON.stringify(payload)
      });
    }
  };

  window.ITStudyCollectorBase = Base;
})();
