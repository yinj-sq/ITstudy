/* ============================================================
   pacer.js — 课堂节奏计时器 + 元认知提示卡
   ============================================================ */
const Pacer = (() => {
  const rootEl = document.getElementById('pacer');
  const toggle = document.getElementById('pcToggle');
  const body = document.getElementById('pcBody');
  const sel = document.getElementById('pcPreset');
  const phaseEl = document.getElementById('pcPhase');
  const timeEl = document.getElementById('pcTime');
  const barEl = document.getElementById('pcBar');
  const promptEl = document.getElementById('pcPrompt');
  const playBtn = document.getElementById('pcPlay');

  let presetKey = 'closing10';
  let idx = 0;
  let left = 0;
  let deadline = 0;
  let running = false;
  let tick = null;
  let promptIdx = -1;
  let promptOverride = null;
  let cardReturn = null;

  const phases = () => PACER_PRESETS[presetKey].phases;
  const cur = () => phases()[Math.min(idx, phases().length - 1)];

  function esc(s) {
    return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  function fmt(ms) {
    const s = Math.max(0, Math.ceil(ms / 1000));
    return String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0');
  }

  function paint() {
    const p = cur();
    phaseEl.textContent = (idx + 1) + '/' + phases().length + ' ' + p.name;
    timeEl.textContent = fmt(left);
    const total = p.sec * 1000;
    barEl.style.width = (total ? Math.max(0, Math.min(1, left / total)) * 100 : 0) + '%';
    timeEl.classList.toggle('over', left <= 0);
    rootEl.classList.toggle('running', running);
    rootEl.classList.toggle('warn', running && left <= 30000);
    playBtn.textContent = running ? '暂停' : (left > 0 && left < p.sec * 1000 ? '继续' : '开始');
  }

  function paintPrompt() {
    if (promptOverride) {
      promptEl.innerHTML = '<b>' + esc(promptOverride.stage) + '</b>' + esc(promptOverride.text);
    } else {
      promptEl.textContent = cur().prompt || '';
    }
  }

  function loadPhase(keepRunning) {
    stopTick();                 // 必须先停掉旧计时，否则新阶段会沿用旧 deadline
    promptOverride = null;
    left = cur().sec * 1000;
    paint();
    paintPrompt();
    if (keepRunning) start();
  }

  function stopTick() {
    clearInterval(tick);
    tick = null;
    running = false;
  }

  function start() {
    if (running) return;
    if (left <= 0) left = cur().sec * 1000;
    deadline = Date.now() + left;
    running = true;
    clearInterval(tick);
    tick = setInterval(onTick, 200);
    paint();
  }

  function pause() {
    if (!running) return;
    left = Math.max(0, deadline - Date.now());
    stopTick();
    paint();
  }

  function onTick() {
    left = Math.max(0, deadline - Date.now());
    if (left <= 0) { finish(); return; }
    paint();
  }

  function finish() {
    stopTick();
    left = 0;
    paint();
    if (idx < phases().length - 1) {
      App.toast('「' + cur().name + '」时间到，进入下一段');
      idx++;
      loadPhase(true);           // 课堂节奏：自动进入下一段
    } else {
      App.toast('「' + PACER_PRESETS[presetKey].name + '」走完了');
      playBtn.textContent = '重新开始';
    }
  }

  function next() {
    if (idx < phases().length - 1) {
      idx++;
      loadPhase(running);
    } else {
      App.toast('已经是最后一段了');
    }
  }

  function reset() {
    stopTick();
    idx = 0;
    left = phases()[0].sec * 1000;
    promptOverride = null;
    paint();
    paintPrompt();
  }

  function shuffle() {
    promptIdx = (promptIdx + 1) % PROMPTS.length;
    promptOverride = PROMPTS[promptIdx];
    paintPrompt();
  }

  /* 把当前提示放大成一张卡，投影给全班看 */
  const card = document.getElementById('promptCard');
  const cardStage = document.getElementById('pcardStage');
  const cardText = document.getElementById('pcardText');

  function currentPrompt() {
    if (promptOverride) return promptOverride;
    return { stage: '本段提示', text: cur().prompt || '' };
  }

  function showCard() {
    const p = currentPrompt();
    if (!p.text) return;
    cardStage.textContent = p.stage;
    cardText.textContent = p.text;
    cardReturn = document.activeElement;
    card.hidden = false;
    /* 必须把焦点移进 dialog，否则读屏软件只会念「对话框」不念内容；
       用了 focus 就不要再挂 aria-live，否则会念两遍 */
    requestAnimationFrame(() => { card.classList.add('show'); card.focus(); });
  }

  function hideCard() {
    if (card.hidden) return;
    card.classList.remove('show');
    setTimeout(() => { card.hidden = true; }, 180);
    if (cardReturn && cardReturn.focus) cardReturn.focus();
    cardReturn = null;
  }

  function setPreset(key) {
    if (!PACER_PRESETS[key]) return;
    presetKey = key;
    sel.value = key;
    reset();
  }

  function setOpen(on) {
    body.hidden = !on;
    toggle.setAttribute('aria-expanded', on ? 'true' : 'false');
    rootEl.classList.toggle('open', on);
  }

  function init() {
    sel.innerHTML = Object.entries(PACER_PRESETS)
      .map(([k, p]) => `<option value="${k}">${esc(p.name)}</option>`).join('');
    sel.value = presetKey;

    toggle.onclick = () => setOpen(body.hidden);
    sel.onchange = () => setPreset(sel.value);
    playBtn.onclick = () => (running ? pause() : start());
    document.getElementById('pcNext').onclick = next;
    document.getElementById('pcReset').onclick = reset;
    document.getElementById('pcShuffle').onclick = shuffle;

    /* 点提示语 → 放大成全屏提示卡 */
    promptEl.onclick = showCard;
    promptEl.title = '点击放大给全班看';
    card.onclick = hideCard;
    document.addEventListener('keydown', e => {
      if (!card.hidden && e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        hideCard();
      }
    }, true);

    reset();
  }

  return { init, start, pause, reset, setOpen, get isRunning() { return running; } };
})();
