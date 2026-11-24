/* ==========================================================================
   op-tip.js  ——  晶胞页「操作提示」浮条
   用法：在任意功能按钮上加 data-optip="点击原子，显示其配位原子"
        （值留空 = 该模式不需要提示，条自动收起）
   表现：文字条贴在晶胞画面下部居中；右下角常驻一个「提示」开关，
        用户可自行关闭，状态记在 localStorage。
   ========================================================================== */
(function () {
    'use strict';
    if (window.__OP_TIP__) return;
    window.__OP_TIP__ = true;

    var KEY = 'xw_optip_on';
    var on = true;
    try { if (localStorage.getItem(KEY) === '0') on = false; } catch (e) { }

    var bar = null, sw = null, txtEl = null, cur = '';

    var CSS = [
        '#op-tip-bar{position:absolute;left:50%;bottom:66px;transform:translateX(-50%) translateY(6px);',
        'z-index:70;max-width:min(520px,84%);padding:6px 14px;border-radius:999px;',
        'background:rgba(10,24,42,.74);border:1px solid rgba(82,168,255,.30);',
        '-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);',
        'color:#cfe6ff;font-size:12.5px;line-height:1.5;letter-spacing:.2px;',
        'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;',
        'opacity:0;pointer-events:none;transition:opacity .2s ease,transform .2s ease;}',
        '#op-tip-bar.on{opacity:1;transform:translateX(-50%) translateY(0);}',

        '#op-tip-sw{position:absolute;right:14px;bottom:16px;z-index:70;',
        'display:flex;align-items:center;gap:6px;padding:5px 10px;border-radius:999px;',
        'background:rgba(10,24,42,.62);border:1px solid rgba(120,160,200,.26);',
        '-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px);',
        'color:#7f9db9;font-size:11px;line-height:1;cursor:pointer;-webkit-user-select:none;user-select:none;',
        'transition:color .18s ease,border-color .18s ease,background .18s ease;}',
        '#op-tip-sw:hover{border-color:rgba(120,190,255,.55);}',
        '#op-tip-sw i{display:block;width:24px;height:13px;border-radius:999px;',
        'background:rgba(150,180,210,.28);position:relative;transition:background .18s ease;}',
        '#op-tip-sw i:after{content:"";position:absolute;left:2px;top:2px;width:9px;height:9px;border-radius:50%;',
        'background:#8fa9c0;transition:left .18s ease,background .18s ease;}',
        '#op-tip-sw.on{color:#a9dcff;border-color:rgba(58,160,255,.45);}',
        '#op-tip-sw.on i{background:rgba(58,160,255,.66);}',
        '#op-tip-sw.on i:after{left:13px;background:#eaf6ff;}',

        '#app-container.light-bg #op-tip-bar{background:rgba(255,255,255,.92);',
        'border-color:rgba(40,110,180,.22);color:#1d5f96;box-shadow:0 3px 12px rgba(20,60,110,.12);}',
        '#app-container.light-bg #op-tip-sw{background:rgba(255,255,255,.88);',
        'border-color:rgba(40,110,180,.22);color:#5a86ab;}',
        '#app-container.light-bg #op-tip-sw.on{color:#1d5f96;}',

        '@media (max-width:700px){#op-tip-bar{font-size:11.5px;bottom:78px;max-width:88%;}}'
    ].join('');

    function injectStyle() {
        if (document.getElementById('op-tip-style')) return;
        var st = document.createElement('style');
        st.id = 'op-tip-style';
        st.textContent = CSS;
        document.head.appendChild(st);
    }

    function mount() {
        injectStyle();
        var host = document.getElementById('canvas-area') ||
            document.getElementById('app-container') ||
            document.body;
        try {
            if (getComputedStyle(host).position === 'static') host.style.position = 'relative';
        } catch (e) { }

        bar = document.createElement('div');
        bar.id = 'op-tip-bar';
        txtEl = document.createElement('span');
        bar.appendChild(txtEl);
        host.appendChild(bar);

        sw = document.createElement('div');
        sw.id = 'op-tip-sw';
        sw.title = '操作提示 开 / 关';
        sw.innerHTML = '<span>提示</span><i></i>';
        sw.addEventListener('click', function () {
            on = !on;
            try { localStorage.setItem(KEY, on ? '1' : '0'); } catch (e) { }
            render();
        });
        host.appendChild(sw);

        render();
    }

    function render() {
        if (!bar) return;
        var showIt = !!(on && cur);
        if (txtEl) txtEl.textContent = cur;
        bar.classList.toggle('on', showIt);
        sw.classList.toggle('on', on);
    }

    function show(text) {
        cur = text || '';
        render();
    }

    /* 事件委托：捕获阶段先跑，页面自己的处理器随后照常执行 */
    /* ★ 动画打断（2026-11-12）：点任何功能按钮 = 新动作，先让页面把正在跑的动画作废，
       页面 handler 随后执行时拿到的就是干净状态。这样「组装到一半点均摊法」能当场切过去。
       三个按钮排除：它们本身就是「推进/暂停」，连点不该被自己重置。 */
    var NO_CANCEL = { 'btn-assemble': 1, 'btn-intro': 1, 'btn-pause': 1 };
    document.addEventListener('click', function (e) {
        var btn = (e.target && e.target.closest) ? e.target.closest('button,.view-btn,.filter-btn,.anim-btn') : null;
        if (btn && !NO_CANCEL[btn.id] && typeof window.__animBusy === 'function' && window.__animBusy()) {
            try { if (typeof window.__cancelAll === 'function') window.__cancelAll(); } catch (err) { }
        }
        var t = e.target;
        while (t && t.nodeType === 1) {
            if (t.hasAttribute && t.hasAttribute('data-optip')) {
                show(t.getAttribute('data-optip'));
                return;
            }
            t = t.parentNode;
        }
    }, true);

    /* 在晶胞上点一下就说明用户已经知道怎么操作了 —— 提示自动收起。
       只认「短按且几乎没移动」：拖拽旋转视角不算点击。 */
    var downX = 0, downY = 0, downT = 0, downInCanvas = false;
    function inCanvas(e) {
        var t = e.target;
        if (!t || t.nodeType !== 1) return false;
        if (t.closest && t.closest('#op-tip-bar,#op-tip-sw')) return false;
        var host = document.getElementById('canvas-area') || document.getElementById('app-container');
        return !!host && host.contains(t);
    }
    document.addEventListener('pointerdown', function (e) {
        downInCanvas = inCanvas(e);
        if (!downInCanvas) return;
        downX = e.clientX; downY = e.clientY; downT = Date.now();
    }, true);
    document.addEventListener('pointerup', function (e) {
        if (!downInCanvas) return;
        downInCanvas = false;
        if (!inCanvas(e)) return;
        if (Date.now() - downT > 700) return;
        var dx = e.clientX - downX, dy = e.clientY - downY;
        if (dx * dx + dy * dy > 64) return;
        if (cur) show('');
    }, true);

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', mount);
    } else {
        mount();
    }

    window.OpTip = { show: show, clear: function () { show(''); }, isOn: function () { return on; } };
})();
