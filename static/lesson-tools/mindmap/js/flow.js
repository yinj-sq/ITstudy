/* ============================================================
   flow.js — 结课流水线
   ============================================================
   把结课时真正会做的五步串成一条可点击的流程条：
   新建 → 计时 → 挖空 → 评估 → 学案。

   设计上的三个决定：
   1. 不做向导弹窗。向导会挡住图，而老师在结课时一直在看图。
      改成顶栏下方一条窄条，不遮内容，随时可关。
   2. 不强制顺序。任何一步都能直接点，跳过的步骤不算「完成」。
      课堂上经常是「模板已经选好了，直接起计时」。
   3. 状态只活在一次会话里，不落盘。它不是数据，是临时脚手架。
   ============================================================ */
const Flow = (() => {
  const el = document.getElementById('flow');
  const stepsEl = document.getElementById('flowSteps');
  const titleEl = document.getElementById('flowTitle');

  const STEPS = [
    { key: 'template', label: '新建', hint: '从一张白纸开始，或按「你要做什么」选一种图' },
    { key: 'timer', label: '计时', hint: '10 分钟节奏，分 4 段走完' },
    { key: 'blank', label: '挖空', hint: '遮住文字，让学生先说出来' },
    { key: 'score', label: '评估', hint: '看这张图缺什么，而不是打几分' },
    { key: 'export', label: '学案', hint: '导出留白学案，发给学生课后填' },
  ];

  let idx = 0;
  let active = false;
  let awaiting = null;
  let hooks = {};

  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  function paint() {
    const done = idx >= STEPS.length;
    titleEl.textContent = done ? '五步走完了' : '一节课的流程';
    el.classList.toggle('done', done);
    /* 不用 aria-label：可见文字是「3挖空」这种拼接，aria-label 写「第 3 步：挖空」
       会被 WCAG 2.5.3 判为「名称不含可见文字」。让名称就等于可见文字最省事。
       对勾用 aria-hidden 的 SVG，不进入文字内容，读屏不会念「对勾选模板」。 */
    const TICK = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">' +
      '<path d="M5 12.6l4.4 4.4L19 7.4" fill="none" stroke="currentColor" ' +
      'stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    stepsEl.innerHTML = STEPS.map((s, i) => {
      const cls = i < idx ? 'done' : (i === idx && !done ? 'cur' : '');
      const mark = i < idx ? TICK : String(i + 1);
      const cur = i === idx && !done ? ' aria-current="step"' : '';
      return `<li><button type="button" class="flow-step ${cls}" data-i="${i}"${cur}
        title="${esc(s.hint)}">` +
        `<span class="fs-n">${mark}</span><span class="fs-l">${esc(s.label)}</span></button></li>`;
    }).join('');
  }

  function advance(from) {
    if (from >= idx) idx = from + 1;
    paint();
    if (idx >= STEPS.length) {
      if (hooks.onAnnounce) hooks.onAnnounce('流程走完了');
      if (hooks.onToast) hooks.onToast('五步走完了 · 都在这张图上');
    } else if (hooks.onAnnounce) {
      hooks.onAnnounce('下一步：' + STEPS[idx].label);
    }
  }

  function runStep(i) {
    const s = STEPS[i];
    if (!s) return;
    switch (s.key) {
      case 'template':
        /* 只负责把模板菜单打开；真正推进要等用户选中模板后由 notify() 触发 */
        awaiting = 'template';
        if (hooks.onTemplate) hooks.onTemplate();
        break;
      case 'timer':
        if (typeof Pacer !== 'undefined') { Pacer.setOpen(true); Pacer.start(); }
        advance(i);
        break;
      case 'blank':
        /* 走 App 的 setBlank，而不是直接改 Store：
           1) setBlank 会重置揭示顺序并把焦点交给「下一个」按钮；
           2) 直接 toggle 的话焦点留在流程按钮上，老师按空格会再次激活它、
              把刚进入的挖空又关掉。 */
        if (hooks.onBlank) hooks.onBlank();
        else if (!Store.blank) Store.toggleBlank();
        advance(i);
        break;
      case 'score':
        if (hooks.onScore) hooks.onScore();
        advance(i);
        break;
      case 'export':
        if (hooks.onExport) hooks.onExport();
        advance(i);
        break;
    }
  }

  function start() {
    active = true;
    idx = 0;
    awaiting = null;
    el.hidden = false;
    document.body.classList.add('flow-on');
    paint();
    if (hooks.onAnnounce) hooks.onAnnounce('流程已开始，第 1 步：新建');
  }

  function stop() {
    active = false;
    awaiting = null;
    el.hidden = true;
    document.body.classList.remove('flow-on');
  }

  /* 外部事件：用户套了模板 / 思维图型时，若正等这一步就推进 */
  function notify(type) {
    if (!active || !awaiting) return;
    if (type === 'template' || type === 'map' || type === 'load') {
      awaiting = null;
      advance(0);
    }
  }

  function init(h) {
    hooks = h || {};
    stepsEl.addEventListener('click', e => {
      const b = e.target.closest('.flow-step');
      if (!b) return;
      /* 必须拦住冒泡：document 上有个「点菜单外部就关闭菜单」的监听，
         而流程条不在菜单里，冒泡过去会把刚打开的模板菜单立刻关掉。 */
      e.stopPropagation();
      runStep(Number(b.dataset.i));
    });
    document.getElementById('flowClose').onclick = stop;
    paint();
  }

  return { init, start, stop, notify, get active() { return active; }, get step() { return idx; } };
})();
