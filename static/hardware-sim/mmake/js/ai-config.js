/* ============================================================
 * ai-config.js —— 科大讯飞凭据设置界面
 *
 * 第二十六轮：让用户改 APPID / APIKey / APISecret，
 * 存在 localStorage，可一键恢复内置默认值。
 *
 * 三组凭据对应关系（讯飞按「应用 × 能力」分配密钥）：
 *   语音组 speech —— 语音识别、语音合成、人脸检测、人脸比对
 *   文字组 text   —— 印刷文字、手写文字、拍照速算
 *   图像组 image  —— 物体识别、场景识别
 * ============================================================ */
(function (global) {
  'use strict';
  var ZKB = global.ZKB || (global.ZKB = {});

  /* 分组说明里的能力清单要和 CAPABILITIES 保持一致：
     拍照速算识别用 Digest 协议、需要 apiSecret，所以归在 speech 组，
     不在文字识别组里。 */
  var GROUPS = [
    { key: 'speech', cn: '语音与人脸', hint: '语音转文字、文字转语音、人脸检测与属性、人脸比对、拍照速算识别' },
    { key: 'text', cn: '文字识别', hint: '印刷文字识别、手写文字识别' },
    { key: 'image', cn: '物体与场景', hint: '物体识别、场景识别' }
  ];

  var els = {};

  function $(id) { return document.getElementById(id); }

  /* 该分组下包含哪些能力（从 ZKB.Xfyun.CAPABILITIES 反查，避免两处维护） */
  function capsOf(groupKey) {
    var X = ZKB.Xfyun;
    if (!X || !X.CAPABILITIES) return [];
    return X.CAPABILITIES.filter(function (c) { return c.group === groupKey; });
  }

  /* 渲染三组凭据输入框 */
  function buildGroups() {
    var box = els.groups;
    if (!box) return;
    box.innerHTML = '';
    GROUPS.forEach(function (g) {
      var wrap = document.createElement('div');
      wrap.className = 'cfg-group';

      var title = document.createElement('div');
      title.className = 'cfg-group-title';
      title.textContent = g.cn;
      wrap.appendChild(title);

      var hint = document.createElement('div');
      hint.className = 'cfg-group-hint';
      var caps = capsOf(g.key);
      hint.textContent = caps.length
        ? g.hint + '（' + caps.map(function (c) { return c.cn; }).join('、') + '）'
        : g.hint;
      wrap.appendChild(hint);

      /* APIKey */
      var kRow = document.createElement('label');
      kRow.className = 'cfg-row';
      kRow.innerHTML = '<span>APIKey</span>';
      var kIn = document.createElement('input');
      kIn.type = 'text';
      kIn.spellcheck = false;
      kIn.id = 'cfg-key-' + g.key;
      kIn.placeholder = '32 位接口密钥';
      kRow.appendChild(kIn);
      wrap.appendChild(kRow);

      /* APISecret */
      var sRow = document.createElement('label');
      sRow.className = 'cfg-row';
      sRow.innerHTML = '<span>APISecret</span>';
      var sIn = document.createElement('input');
      sIn.type = 'text';
      sIn.spellcheck = false;
      sIn.id = 'cfg-secret-' + g.key;
      sIn.placeholder = '32 位接口密钥';
      sRow.appendChild(sIn);
      wrap.appendChild(sRow);

      /* 该组的协议说明 */
      var protos = {};
      caps.forEach(function (c) { protos[c.auth] = 1; });
      var pRow = document.createElement('div');
      pRow.className = 'cfg-proto';
      pRow.textContent = '鉴权方式：' + Object.keys(protos).join(' + ');
      wrap.appendChild(pRow);

      box.appendChild(wrap);
    });
  }

  /* 把当前凭据填进输入框 */
  function fillForm() {
    var X = ZKB.Xfyun;
    if (!X) return;
    var c = X.creds();
    if (els.appid) els.appid.value = c.appId || '';
    GROUPS.forEach(function (g) {
      var ki = $('cfg-key-' + g.key);
      var si = $('cfg-secret-' + g.key);
      if (ki) ki.value = (c[g.key] && c[g.key].apiKey) || '';
      if (si) si.value = (c[g.key] && c[g.key].apiSecret) || '';
    });
    paintState();
  }

  /* 顶部状态提示：当前用的是默认还是自定义 */
  function paintState() {
    var X = ZKB.Xfyun;
    if (!X || !els.state) return;
    var custom = X.isCustom();
    var secure = !!(global.crypto && global.crypto.subtle);

    var html = custom
      ? '<b class="ok">当前使用你自己的讯飞凭据</b>（保存在浏览器本地）'
      : '<b class="warn">当前使用内置默认凭据</b>。内置密钥可能已过期或被调用方限制'
        + '（讯飞返回 401 apikey not found 即属此类）。若识别类积木报错，'
        + '请到讯飞开放平台控制台创建应用、开通对应能力，把 APPID / APIKey / APISecret 填到这里。';

    if (!secure) {
      html += '<br><span class="warn">⚠ 当前环境不支持 Web Crypto，签名会失败。'
        + '请用本地服务器打开（如 python -m http.server 8000），不要直接双击 HTML 文件。</span>';
    } else {
      html += '<br><span class="ok">✓ 签名环境正常</span>'
        + '<br><span class="warn">⚠ 讯飞图像类接口官方标注「不支持跨域」。'
        + '语音合成/语音识别走 WebSocket 不受此限制；'
        + '人脸、文字、物体、场景识别请在浏览器允许跨域或经由本地代理调用，'
        + '并确认讯飞控制台的「IP 白名单」已包含本机外网 IP。</span>';
    }

    /* 附上内置三组凭据的实测结论（2026-10-08 Chromium 直连逐能力验证得到），
       省得用户自己再排查一遍 */
    html += '<br><span class="cfg-note" style="display:block;margin-top:6px">'
      + '内置三组凭据实测结论：<b>speech 组完全可用</b>——人脸检测、语音合成、语音识别、'
      + '<b>拍照速算识别均已实测成功</b>；<b>text 组（印刷/手写文字）鉴权签名已通过</b>，'
      + '但讯飞这两个接口在浏览器里被跨域拦截，需本地代理或在掌控板真机上跑；'
      + '<b>image 组（物体/场景）同样受跨域限制，未能验证</b>。'
      + '</span>';
    els.state.innerHTML = html;
  }

  function open() {
    if (!els.mask) return;
    buildGroups();
    fillForm();
    els.mask.classList.remove('hidden');
    if (ZKB.log) {
      ZKB.log('打开 AI 设置（科大讯飞凭据）', 'log-sim');
    }
  }

  function close() {
    if (els.mask) els.mask.classList.add('hidden');
  }

  function save() {
    var X = ZKB.Xfyun;
    if (!X) return;
    var next = { appId: (els.appid && els.appid.value.trim()) || '' };
    GROUPS.forEach(function (g) {
      var ki = $('cfg-key-' + g.key);
      var si = $('cfg-secret-' + g.key);
      next[g.key] = {
        apiKey: ki ? ki.value.trim() : '',
        apiSecret: si ? si.value.trim() : ''
      };
    });

    /* APPID 为空直接拦下——讯飞所有接口都要它 */
    if (!next.appId) {
      if (ZKB.toast) ZKB.toast('请填写 APPID');
      if (els.appid) els.appid.focus();
      return;
    }
    /* 至少要有一组 APIKey，否则所有能力都会 401 */
    var anyKey = GROUPS.some(function (g) { return !!next[g.key].apiKey; });
    if (!anyKey) {
      if (ZKB.toast) ZKB.toast('至少填写一组 APIKey');
      return;
    }

    X.setCreds(next);
    fillForm();
    if (ZKB.toast) ZKB.toast('AI 凭据已保存');
    if (ZKB.log) {
      ZKB.log('已保存讯飞凭据（APPID ' + next.appId + '）', 'log-ok');
    }
    /* 不自动关闭，让用户看到状态更新 */
  }

  function reset() {
    var X = ZKB.Xfyun;
    if (!X) return;
    X.resetCreds();
    fillForm();
    if (ZKB.toast) ZKB.toast('已恢复内置默认凭据');
    if (ZKB.log) ZKB.log('已恢复讯飞默认凭据', 'log-ok');
  }

  function bind() {
    els.mask = $('ai-cfg-mask');
    if (!els.mask) return;
    els.groups = $('cfg-groups');
    els.appid = $('cfg-appid');
    els.state = $('cfg-state');

    var btn = $('btn-ai-cfg');
    if (btn) btn.addEventListener('click', open);
    var c1 = $('ai-cfg-close');
    var c2 = $('cfg-cancel');
    if (c1) c1.addEventListener('click', close);
    if (c2) c2.addEventListener('click', close);
    var cs = $('cfg-save');
    if (cs) cs.addEventListener('click', save);
    var cr = $('cfg-reset');
    if (cr) cr.addEventListener('click', reset);

    /* 点遮罩空白处关闭 */
    els.mask.addEventListener('click', function (e) {
      if (e.target === els.mask) close();
    });
    /* ESC 关闭 */
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !els.mask.classList.contains('hidden')) close();
    });
  }

  ZKB.AiConfig = {
    bind: bind,
    open: open,
    close: close,
    save: save,
    reset: reset,
    fillForm: fillForm,
    GROUPS: GROUPS
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bind);
  } else {
    bind();
  }
})(window);
