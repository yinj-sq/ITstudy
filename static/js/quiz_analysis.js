/* 资源页逐题分析：同一页最新提交、单色条形图与可访问数据表。 */
(function () {
  'use strict';
  function escapeText(value) {
    var node = document.createElement('span');
    node.textContent = value == null ? '' : String(value);
    return node.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function values(value) { return Array.isArray(value) ? value : (value == null ? [] : [value]); }
  function answerText(question, answer) {
    return values(answer).map(function (value) {
      var option = (question.options || []).filter(function (entry) { return entry.value === String(value); })[0];
      return option ? option.label : String(value);
    }).join('；') || '未作答';
  }
  function questionLabel(question, index) {
    var label = question.prompt || question.id;
    return /^(?:第\s*\d+\s*题|\d+\s*[.、．)）]|(?:问题|Question)\s*\d+)/i.test(label)
      ? label : (index + 1) + '. ' + label;
  }
  function detailHtml(questions) {
    return (questions || []).map(function (question, index) {
      var verdict = question.is_correct === true ? '✓ 答对' :
        (question.is_correct === false ? '✗ 答错' : '— 未判定');
      var selected = values(question.answer).map(String);
      var html = '<section class="border rounded p-3 mb-3 quiz-question-detail"><h6>' +
        escapeText(questionLabel(question, index)) + '</h6>';
      if (question.options && question.options.length) {
        html += '<ul class="mb-2">' + question.options.map(function (option) {
          return '<li>' + escapeText(option.label) +
            (selected.indexOf(option.value) >= 0 ? ' <strong>（已选）</strong>' : '') + '</li>';
        }).join('') + '</ul>';
      }
      html += '<div><strong>学生作答：</strong>' + escapeText(answerText(question, question.answer)) + '</div>';
      html += '<div><strong>标准答案：</strong>' + escapeText(
        question.correct_answer == null ? '未采集到' : answerText(question, question.correct_answer)) + '</div>';
      return html + '<div><strong>判定：</strong>' + escapeText(verdict) + '</div></section>';
    }).join('');
  }
  window.QuizAnalysis = {detailHtml: detailHtml};

  document.addEventListener('DOMContentLoaded', function () {
    var root = document.getElementById('quizAnalysis');
    if (!root) return;
    var fileSelect = document.getElementById('quizAnalysisFile');
    var questionSelect = document.getElementById('quizAnalysisQuestion');
    var summary = document.getElementById('quizAnalysisSummary');
    var table = document.getElementById('quizQuestionTableBody');
    var optionTable = document.getElementById('quizOptionTableBody');
    var texture = document.getElementById('quizAnalysisTexture');
    var charts = {};
    var questions = [];
    var requestNumber = 0;
    var dark = window.matchMedia('(prefers-color-scheme: dark)');
    var forced = window.matchMedia('(forced-colors: active)');
    var printing = false;

    function token(name) { return getComputedStyle(root).getPropertyValue(name).trim(); }
    function fill(canvas) {
      var color = token('--qa-series');
      if (!texture.checked && !forced.matches && !printing) return color;
      var tile = document.createElement('canvas');
      tile.width = tile.height = 8;
      var ctx = tile.getContext('2d');
      ctx.fillStyle = color;
      ctx.fillRect(0, 0, 8, 8);
      ctx.strokeStyle = token('--qa-texture');
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(0, 8); ctx.lineTo(8, 0); ctx.stroke();
      return canvas.getContext('2d').createPattern(tile, 'repeat');
    }
    function draw(id, labels, data, title, maximum, tooltip) {
      if (charts[id]) { charts[id].destroy(); delete charts[id]; }
      var canvas = document.getElementById(id);
      if (!window.Chart) return; // 数据表仍可读取，不因图表库加载失败而丢失结果。
      canvas.parentElement.style.height = Math.max(180, labels.length * 30 + 60) + 'px';
      charts[id] = new Chart(canvas, {
        type: 'bar',
        data: {labels: labels, datasets: [{label: title, data: data,
          backgroundColor: fill(canvas), maxBarThickness: 20,
          borderRadius: 4, borderSkipped: 'start'}]},
        options: {
          indexAxis: 'y', responsive: true, maintainAspectRatio: false,
          devicePixelRatio: 1, animation: false,
          interaction: {mode: 'index', intersect: false},
          plugins: {legend: {display: false}, tooltip: {callbacks: {
            title: function (items) { return labels[items[0].dataIndex]; },
            label: function (item) { return tooltip(item.dataIndex); }
          }}},
          scales: {
            x: {beginAtZero: true, max: maximum, grid: {color: token('--qa-grid')},
              ticks: {color: token('--qa-muted'), precision: 0}},
            y: {grid: {display: false}, ticks: {color: token('--qa-text'), autoSkip: false,
              callback: function (value) {
                var label = this.getLabelForValue(value);
                return label.length > 24 ? label.slice(0, 24) + '…' : label;
              }}}
          }
        }
      });
    }
    function drawOptions() {
      var question = questions.filter(function (entry) { return entry.key === questionSelect.value; })[0];
      var note = document.getElementById('quizOptionNote');
      optionTable.textContent = '';
      if (!question) {
        note.textContent = '暂无逐题数据';
        draw('quizOptionChart', [], [], '选项选择人数', undefined, function () { return ''; });
        return;
      }
      var options = question.options || [];
      note.textContent = question.answer_key_conflict ? '检测到不同标准答案，已停止计算该题正确率，请检查资源版本。' :
        (options.length ? '按人数计数；多选题每人可选多项，选择比例之和可能超过 100%。' :
          '此题没有可识别的选项；以下列出最常见的 20 种作答，历史记录无法还原未采集的题干和选项。');
      var rows = options.length ? options : (question.answer_distribution || []).map(function (entry) {
        return {label: entry.answer, selected_count: entry.count,
          selection_rate: Math.round(entry.count / question.response_count * 1000) / 10};
      });
      rows.forEach(function (option) {
        var row = document.createElement('tr');
        row.innerHTML = '<td class="qa-stem">' + escapeText(option.label) + '</td>' +
          '<td class="qa-count">' + option.selected_count + '</td>' +
          '<td class="qa-count">' + option.selection_rate + '%</td>';
        optionTable.appendChild(row);
      });
      draw('quizOptionChart', rows.map(function (option) { return option.label; }),
        rows.map(function (option) { return option.selected_count; }),
        options.length ? '选项选择人数' : '相同作答人数', undefined,
        function (index) { return rows[index].selected_count + ' 人（' + rows[index].selection_rate + '%）'; });
    }
    function drawAccuracy() {
      draw('quizAccuracyChart', questions.map(function (question, index) {
        return questionLabel(question, index);
      }), questions.map(function (question) { return question.correct_rate; }), '逐题正确率（%）', 100,
      function (index) {
        var question = questions[index];
        return question.correct_rate == null ? '未判定，不计入正确率' :
          question.correct_rate + '% · 答对 ' + question.correct_count + '/' + question.judged_count +
          ' 人 · 未判定 ' + question.unknown_count + ' 人';
      });
    }
    function render(data) {
      var previousQuestion = questionSelect.value;
      questions = data.questions || [];
      fileSelect.textContent = '';
      (data.pages || []).forEach(function (page) {
        var option = new Option((page.source_file || '旧版未标记来源页') + '（' + page.student_count + ' 人）', page.source_file);
        fileSelect.add(option);
      });
      fileSelect.value = data.source_file || '';
      summary.textContent = data.student_count + ' 位学生 · ' + questions.length + ' 道题/题目版本' +
        (data.legacy_records ? ' · ' + data.legacy_records + ' 条旧记录未包含完整逐题信息' : '');
      if (!questions.length) summary.textContent += '。暂无逐题数据，请使用新版采集器完成一次答题。';
      summary.classList.remove('text-danger');
      table.textContent = '';
      questionSelect.textContent = '';
      questions.forEach(function (question, index) {
        var label = questionLabel(question, index);
        questionSelect.add(new Option(label, question.key));
        var row = document.createElement('tr');
        row.innerHTML = '<td class="qa-stem"><button type="button" class="btn btn-link p-0 qa-question-link">' +
          escapeText(label) + '</button></td>' +
          [question.answered_count, question.unanswered_count, question.correct_count,
            question.incorrect_count, question.unknown_count,
            question.correct_rate == null ? '未判定' : question.correct_rate + '%'].map(function (value) {
            return '<td class="qa-count">' + escapeText(value) + '</td>';
          }).join('');
        row.querySelector('button').addEventListener('click', function () {
          questionSelect.value = question.key; drawOptions(); questionSelect.focus();
        });
        table.appendChild(row);
      });
      if (questions.some(function (question) { return question.key === previousQuestion; })) questionSelect.value = previousQuestion;
      drawAccuracy(); drawOptions();
    }
    function load(source) {
      var number = ++requestNumber;
      summary.textContent = '正在汇总逐题数据…';
      var url = root.dataset.url;
      if (source !== undefined) url += '?source_file=' + encodeURIComponent(source);
      fetch(url, {credentials: 'same-origin'}).then(function (response) {
        if (!response.ok) throw new Error('统计加载失败（HTTP ' + response.status + '）');
        return response.json();
      }).then(function (body) {
        if (number !== requestNumber) return;
        if (!body.success) throw new Error(body.msg || '统计加载失败');
        render(body.data);
      }).catch(function (error) {
        if (number !== requestNumber) return;
        summary.textContent = error.message + '，请点击“刷新统计”重试。';
        summary.classList.add('text-danger');
      });
    }
    fileSelect.addEventListener('change', function () { load(fileSelect.value); });
    questionSelect.addEventListener('change', drawOptions);
    document.getElementById('quizAnalysisReload').addEventListener('click', function () { load(fileSelect.value); });
    function redraw() { drawAccuracy(); drawOptions(); }
    texture.addEventListener('change', redraw);
    dark.addEventListener('change', redraw);
    forced.addEventListener('change', redraw);
    new MutationObserver(redraw).observe(document.documentElement, {
      attributes: true, attributeFilter: ['data-theme', 'data-bs-theme']
    });
    window.addEventListener('beforeprint', function () { printing = true; redraw(); });
    window.addEventListener('afterprint', function () { printing = false; redraw(); });
    load();
  });
})();
