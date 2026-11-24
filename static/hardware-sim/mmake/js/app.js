/* ============================================================
 * app.js —— 主控制器：Blockly 注入 / 模式切换 / 运行 / 保存打开 /
 *           代码预览 / 设备抽屉 / 真机上传 / 控制台
 * ============================================================ */
(function (global) {
  'use strict';
  var ZKB = global.ZKB;

  var $ = function (id) { return document.getElementById(id); };
  var ws = null;
  var mode = 'stage';
  var running = false;
  var rafCode = 0;

  document.addEventListener('DOMContentLoaded', init);

  /* ============================================================
   * 初始化
   * ============================================================ */
  function init() {
    // Blockly 自带工具箱渲染在注入容器左侧；占位的左栏隐藏，由工具箱充当左侧积木区
    $('toolbox-pane').style.display = 'none';

    injectBlockly();
    ZKB.Stage.init();
    ZKB.SimBoard.init();
    /* 3D 掌控板（虚拟仿真主视图） */
    var b3host = document.getElementById('sim-board-wrap');
    if (b3host && ZKB.Board3D) {
      ZKB.Board3D.build();
      ZKB.Board3D.renderDevices();
    }
    if (ZKB.Store) ZKB.Store.init();

    bindUI();
    refreshCode();
    bootLog();
    status('就绪');

    /* 首次同步积木区配色（色条 / 行底色同源） */
    if (ZKB.syncCategoryColours) ZKB.syncCategoryColours();
    /* 视口尺寸变化后 Blockly 会重排工具箱，需再次同步配色 */
    window.addEventListener('resize', function () {
      if (ZKB.syncCategoryColours) setTimeout(ZKB.syncCategoryColours, 120);
    });
  }

  function injectBlockly() {
    var toolboxDom = Blockly.utils.xml.textToDom(ZKB.TOOLBOX_XML);
    ws = Blockly.inject('blockly-workspace', {
      toolbox: toolboxDom,
      media: 'vendor/blockly/media/',
      grid: { spacing: 26, length: 2, colour: '#e6eaef', snap: false },
      zoom: { controls: true, wheel: true, startScale: 0.9, maxScale: 2, minScale: 0.4, scaleSpeed: 1.12 },
      trashcan: true,
      maxTrashcanContents: 200,
      move: { scrollbars: true, drag: true, wheel: true },
      sounds: false,
      renderer: 'zelos'
    });

    // 积木变化 → 实时刷新代码预览与状态栏
    ws.addChangeListener(function (e) {
      if (e.isUiEvent) return;
      if (rafCode) cancelAnimationFrame(rafCode);
      rafCode = requestAnimationFrame(refreshCode);
    });

    /* 动态分类飞出回调（修复 "Couldn't find a callback function" 报错） */
    ws.registerToolboxCategoryCallback('ZKB_VARIABLE', variableFlyout);
    ws.registerToolboxCategoryCallback('ZKB_LIST', listFlyout);
    ws.registerToolboxCategoryCallback('ZKB_PROC', procFlyout);
    /* 高级分组及其子分类 */
    ws.registerToolboxCategoryCallback('ZKB_ADVANCED', function () {
      return domChildren(flyoutDom('<label text="展开左侧「高级」分组后，可使用以下分类：文本 / 数据集合 / 文件串口 / 自制积木"></label>'));
    });
    ws.registerToolboxCategoryCallback('ZKB_TEXT', textFlyout);
    ws.registerToolboxCategoryCallback('ZKB_DATA', dataFlyout);
    ws.registerToolboxCategoryCallback('ZKB_FILE', fileFlyout);
    ws.registerButtonCallback('ZK_NEW_VAR', function () { openNameDialog('var'); });
    ws.registerButtonCallback('ZK_NEW_LIST', function () { openNameDialog('list'); });
    /* 第三十轮：变量 / 列表的重命名与删除集中到一个管理面板。
       积木下拉菜单里虽然也有这两项，但菜单里的删除会直接生效、
       不给确认；这里做成带确认的列表，误操作更安全。 */
    ws.registerButtonCallback('ZK_MANAGE_VARS', function () { openVarManager(); });
    ws.registerButtonCallback('ZK_NEW_PROC', function () { openProcMaker(null); });

    /* 高级分组：点击展开/折叠 */
    bindAdvancedGroup();

    /* 自制积木：直接在块上改名时同步调用块；删除定义时删除调用块 */
    ws.addChangeListener(function (e) {
      if (e.type === Blockly.Events.BLOCK_CHANGE && e.element === 'field' && e.name === 'NAME') {
        var blk = ws.getBlockById(e.blockId);
        if (blk && blk.type === 'zk_my_def' && blk.spec_) {
          blk.spec_.name = e.newValue || '我的积木';
          ZKB.MyBlocks.syncCalls(ws, blk.id, blk.spec_);
          refreshFlyoutLater();
        }
      }
      if (e.type === Blockly.Events.BLOCK_DELETE && e.oldXml) {
        var xml = e.oldXml;
        var defId = null;
        try {
          if (xml.getAttribute && xml.getAttribute('type') === 'zk_my_def') {
            defId = xml.getAttribute('id');
          }
        } catch (err) {}
        if (!defId) {
          var txt = Blockly.Xml.domToText(xml);
          var m = /type="zk_my_def"[^>]*\sid="([^"]+)"/.exec(txt) || /id="([^"]+)"[^>]*type="zk_my_def"/.exec(txt);
          if (m) defId = m[1];
        }
        if (defId) {
          ws.getAllBlocks(false).forEach(function (b) {
            if (b.type === 'zk_my_call' && b.defId_ === defId) b.dispose(true);
          });
          refreshFlyoutLater();
        }
      }
    });

    window.addEventListener('resize', function () { Blockly.svgResize(ws); });
  }

  var flyoutTimer = 0;
  /* 刷新飞出层：先重建工具箱（保证动态分类内容重新生成），
     若未选中任何分类则自动选中「自制积木」，让新建的积木立刻可见。 */
  function refreshFlyoutLater(selectName) {
    clearTimeout(flyoutTimer);
    flyoutTimer = setTimeout(function () {
      try {
        var tb = ws.getToolbox();
        if (!tb) return;
        /* 确保高级分组处于展开状态，否则「自制积木」被 CSS 隐藏 */
        if (selectName === '自制积木' && !advancedExpanded()) setAdvancedExpanded(true);
        tb.refreshSelection();
        /* 若当前没有选中分类，切到目标分类 */
        var sel = document.querySelector('.blocklyToolboxDiv .blocklyTreeSelected .blocklyTreeLabel');
        var cur = sel ? sel.textContent.trim() : '';
        if (selectName && cur !== selectName) {
          var rows = document.querySelectorAll('.blocklyToolboxDiv .blocklyTreeRow');
          for (var i = 0; i < rows.length; i++) {
            var lb = rows[i].querySelector('.blocklyTreeLabel');
            if (lb && lb.textContent.trim() === selectName) {
              rows[i].dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
              break;
            }
          }
        }
      } catch (e) { console.warn('刷新飞出层失败', e); }
      if (ZKB.syncCategoryColours) ZKB.syncCategoryColours();
    }, 90);
  }

  /* ============================================================
   * 第四十一轮：变量 / 列表的「当前选中项」跟踪
   *
   * 新建列表后，飞出层里的列表积木应该指向**刚建的这个列表**。
   * 原来写死 lists[0]，学生新建完列表，积木上还是老列表的名字，
   * 以为没生效。这里记住当前选中的变量 / 列表，
   * 飞出层优先用它们，删除后自动回退到第一个。
   * ============================================================ */
  var activeVarId = '';
  var activeListId = '';
  function pickById(arr, id) {
    if (!id) return null;
    for (var i = 0; i < arr.length; i++) {
      if (arr[i].getId() === id) return arr[i];
    }
    return null;
  }

  /* 第四十二轮：把「当前列表」暴露给 blocks-defs.js
   *
   * 列表积木（lists_length / zk_list_clear …）的输入口影子块
   * 是在 blocks-defs.js 里生成的，它也得指向当前列表，
   * 否则从工作区里新拖出的列表积木会挂在旧列表上。
   * 这里给出一个统一入口，两边都用同一个「当前列表」。 */
  ZKB.getCurrentListId = function () { return activeListId; };
  ZKB.getCurrentVarId = function () { return activeVarId; };

  /* ============================================================
   * 动态飞出分类：变量 / 列表 / 自制积木
   * ============================================================ */
  function escXml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function flyoutDom(innerXml) {
    return Blockly.utils.xml.textToDom('<xml xmlns="https://developers.google.com/blockly/xml">' + innerXml + '</xml>');
  }
  function domChildren(dom) { return Array.prototype.slice.call(dom.childNodes); }
  function varField(v) {
    /* LIST 类型变量必须带 variabletype，否则 variables_get 字段序列化时
       会抛 "Serialized variable type ... does not match variable field" */
    var typeAttr = v.type === 'LIST' ? ' variabletype="LIST"' : '';
    return '<field name="VAR"' + (v.getId ? ' id="' + v.getId() + '"' : '') + typeAttr + '>' +
      escXml(v.name) + '</field>';
  }
  function listGetterShadow(v) {
    return '<shadow type="variables_get">' + varField(v) + '</shadow>';
  }

  /* 第三十轮：变量 / 列表管理面板
     积木下拉菜单里虽然也有「重命名变量…」「删除变量…」，但删除会立刻生效、
     没有二次确认，课堂上误点很危险。这里做成带确认的列表。 */
  function openVarManager() {
    var box = $('vm-list');
    if (!box) return;
    var vars = ws.getAllVariables().filter(function (v) {
      return v.type === '' || v.type === 'String';
    });
    var lists = workspace_lists();
    var html = '';
    function rows(arr, kind) {
      if (!arr.length) return '';
      return arr.map(function (v) {
        return '<div class="vm-row" data-vid="' + v.getId() + '" data-kind="' + kind + '">' +
          '<span class="vm-name" title="' + escHtml(v.name) + '">' + escHtml(v.name) + '</span>' +
          '<span class="vm-tag">' + (kind === 'list' ? '列表' : '变量') + '</span>' +
          '<button class="vm-btn" data-act="rename">重命名</button>' +
          '<button class="vm-btn danger" data-act="del">删除</button>' +
          '</div>';
      }).join('');
    }
    if (vars.length) html += '<div class="vm-sec">变量</div>' + rows(vars, 'var');
    if (lists.length) html += '<div class="vm-sec">列表</div>' + rows(lists, 'list');
    if (!html) html = '<div class="vm-empty">还没有变量或列表</div>';
    box.innerHTML = html;

    box.onclick = function (e) {
      var btn = e.target.closest('.vm-btn');
      if (!btn) return;
      var row = btn.closest('.vm-row');
      if (!row) return;
      var id = row.getAttribute('data-vid');
      var model = ws.getVariableById ? ws.getVariableById(id) : null;
      if (!model) { renderVarManager(); return; }
      if (btn.getAttribute('data-act') === 'rename') {
        openRenameDialog(model);
        /* 重命名对话框关闭后刷新本面板 */
        setTimeout(renderVarManager, 300);
      } else {
        deleteVariable(model);
        renderVarManager();
      }
    };
    $('varmgr-mask').classList.remove('hidden');
  }
  function workspace_lists() {
    return ws.getVariablesOfType ? ws.getVariablesOfType('LIST') :
      ws.getAllVariables().filter(function (v) { return v.type === 'LIST'; });
  }
  function renderVarManager() {
    if ($('varmgr-mask') && !$('varmgr-mask').classList.contains('hidden')) openVarManager();
  }
  function escHtml(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  /* 【第三十轮】原先这里有个 varManageButtons()，给每个变量在flyout 里
   生成「✎ 重命名」「🗑 删除」两个按钮。5 个变量就把整屏占满，
   积木被挤到看不见的地方；而且功能与积木下拉菜单重复。已改为
   openVarManager() 统一管理，功能更全且不占空间。 */

  /* ============================================================
   * 高级分组：点击「高级」行展开/折叠子分类
   *
   * 实现说明：Blockly 不支持运行时向工具箱插入分类，因此子分类
   * （文本 / 数据集合 / 文件串口 / 自制积木）始终存在于工具箱 XML 中，
   * 通过 zk-adv-child 标记 + body 上的 zk-adv-open 类用 CSS 显隐。
   * 折叠状态持久化，工具箱重建后自动恢复。
   * ============================================================ */
  var ADV_STATE_KEY = 'zkb_adv_expanded_v1';
  var advBound = false;
  var ADV_NAMES = { '文本': 1, '数据集合': 1, '文件串口': 1, '自制积木': 1 };

  function bindAdvancedGroup() {
    if (advBound) { renderAdvancedGroup(); return; }
    advBound = true;

    var toolbox = document.querySelector('.blocklyToolboxDiv');
    if (!toolbox) return;

    /* 事件委托：点击「高级」分类行 → 切换展开 */
    toolbox.addEventListener('click', function (e) {
      var row = e.target.closest ? e.target.closest('.blocklyTreeRow') : null;
      if (!row) return;
      var label = row.querySelector('.blocklyTreeLabel');
      if (!label || label.textContent.trim() !== '高级') return;
      /* 阻止 Blockly 打开飞出层（高级本身没有积木，仅作折叠开关） */
      e.preventDefault();
      e.stopPropagation();
      setAdvancedExpanded(!advancedExpanded());
    }, true);

    renderAdvancedGroup();
  }

  function advancedExpanded() {
    /* 默认折叠：只有用户显式展开过才返回 true */
    return !!(ZKB.Store && ZKB.Store.getLocal(ADV_STATE_KEY) === true);
  }
  function setAdvancedExpanded(on) {
    if (ZKB.Store) ZKB.Store.setLocal(ADV_STATE_KEY, !!on);
    renderAdvancedGroup();
    if (ZKB.syncCategoryColours) ZKB.syncCategoryColours();
  }
  function toggleAdvancedGroup() { setAdvancedExpanded(!advancedExpanded()); }

  /* 标记高级子分类 + 更新箭头与显隐状态 */
  function renderAdvancedGroup() {
    var expanded = advancedExpanded();
    /* body 类驱动 CSS 显隐 */
    document.body.classList.toggle('zk-adv-open', expanded);

    var toolbox = document.querySelector('.blocklyToolboxDiv');
    if (!toolbox) return;

    toolbox.querySelectorAll('.blocklyToolboxCategory').forEach(function (c) {
      var lb = c.querySelector('.blocklyTreeLabel');
      if (!lb) return;
      var name = lb.textContent.trim();

      if (ADV_NAMES[name]) {
        c.classList.add('zk-adv-child');
        return;
      }
      if (name === '高级') {
        c.classList.add('zk-adv-toggle');
        var row = c.querySelector('.blocklyTreeRow');
        if (!row) return;
        c.classList.toggle('zk-adv-open', expanded);
        var arrow = row.querySelector('.zk-adv-arrow');
        if (!arrow) {
          arrow = document.createElement('span');
          arrow.className = 'zk-adv-arrow';
          var icon = row.querySelector('.blocklyTreeIcon');
          if (icon && icon.parentNode) {
            icon.parentNode.insertBefore(arrow, icon.nextSibling);
          } else {
            row.insertBefore(arrow, row.firstChild);
          }
        }
        arrow.textContent = expanded ? '▾' : '▸';
        row.title = expanded ? '点击收起高级分类' : '点击展开高级分类（文本/数据集合/文件串口/自制积木）';
      }
    });
  }

  /* ============================================================
/* ============================================================
   * 变量分类（含列表 —— 原「列表」分类已合并至此）
   *
   * 【第三十轮】改为「一套积木 + 积木上下拉切换变量」
   *
   * 原来每个变量都生成一整套积木（5 块），5 个变量就是 25 块；
   * 列表更夸张，每个列表 9 块。变量一多飞出层就被撑爆，
   * 同一个动作要拖 N 遍才能分别操作 N 个变量。
   *
   * 改成：每种积木**只出一块**，积木上的 field_variable 本身就是下拉框，
   * 拖出一块就能切换任意变量。这也是 Scratch 的做法。
   *   · variables_get / variables_set / math_change 是 Blockly 内置，
   *     本来就带 VAR 下拉，直接复用
   *   · zk_var_show / zk_var_hide / zk_list_show / zk_list_hide
   *     在 blocks-defs 里已声明 field_variable，同样自带下拉
   *   · 以 <shadow><variables_get> 作输入口的积木
   *     （lists_setIndex / lists_getIndex / zk_list_clear …），
   *     下拉藏在影子积木里，点开也能切
   * ============================================================ */
  function variableFlyout(workspace) {
    var xml = '<button text="＋ 新建一个变量" callbackKey="ZK_NEW_VAR"></button>' +
      '<button text="＋ 新建一个列表" callbackKey="ZK_NEW_LIST"></button>';

    var vars = workspace.getAllVariables().filter(function (v) {
      return v.type === '' || v.type === 'String';
    });
    var lists = workspace.getVariablesOfType ? workspace.getVariablesOfType('LIST') :
      workspace.getAllVariables().filter(function (v) { return v.type === 'LIST'; });

    /* 第四十一轮：优先用「当前选中」的变量 / 列表。
       新建列表后，列表积木要立刻指向刚建的那个列表，
       而不是永远用 lists[0]（老列表），让学生以为没生效。 */
    var f1 = pickById(vars, activeVarId) || vars[0];
    var L = pickById(lists, activeListId) || lists[0];

    /* ---------- 变量积木：每种只出一块 ---------- */
    if (f1) {
      xml += '<label text="────  变量（用积木上的下拉切换）  ────"></label>';
      xml += '<block type="variables_set">' + varField(f1) +
        '<value name="VALUE"><shadow type="math_number"><field name="NUM">0</field></shadow></value></block>';
      xml += '<block type="math_change">' + varField(f1) +
        '<value name="DELTA"><shadow type="math_number"><field name="NUM">1</field></shadow></value></block>';
      xml += '<block type="zk_var_show">' + varField(f1) + '</block>';
      xml += '<block type="zk_var_hide">' + varField(f1) + '</block>';
      xml += '<block type="variables_get">' + varField(f1) + '</block>';
    }

    /* ---------- 列表积木：同理，每种一块 ---------- */
    if (L) {
      xml += '<label text="────  列表（用积木上的下拉切换）  ────"></label>';
      xml += '<block type="lists_setIndex"><mutation mode="INSERT" where="LAST" at="false"></mutation>' +
        '<field name="MODE">INSERT</field><field name="WHERE">LAST</field>' +
        '<value name="LIST">' + listGetterShadow(L) + '</value>' +
        '<value name="TO"><shadow type="text"><field name="TEXT">东西</field></shadow></value></block>';
      xml += '<block type="lists_setIndex"><mutation mode="INSERT" where="FROM_START" at="true"></mutation>' +
        '<field name="MODE">INSERT</field><field name="WHERE">FROM_START</field>' +
        '<value name="LIST">' + listGetterShadow(L) + '</value>' +
        '<value name="AT"><shadow type="math_number"><field name="NUM">1</field></shadow></value>' +
        '<value name="TO"><shadow type="text"><field name="TEXT">东西</field></shadow></value></block>';
      xml += '<block type="lists_getIndex"><mutation mode="REMOVE" where="FROM_START"></mutation>' +
        '<field name="MODE">REMOVE</field><field name="WHERE">FROM_START</field>' +
        '<value name="VALUE">' + listGetterShadow(L) + '</value>' +
        '<value name="AT"><shadow type="math_number"><field name="NUM">1</field></shadow></value></block>';
      xml += '<block type="lists_getIndex"><mutation mode="GET" where="FROM_START"></mutation>' +
        '<field name="MODE">GET</field><field name="WHERE">FROM_START</field>' +
        '<value name="VALUE">' + listGetterShadow(L) + '</value>' +
        '<value name="AT"><shadow type="math_number"><field name="NUM">1</field></shadow></value></block>';
      xml += '<block type="zk_list_clear"><value name="LIST">' + listGetterShadow(L) + '</value></block>';
      xml += '<block type="zk_list_contains">' +
        '<value name="LIST">' + listGetterShadow(L) + '</value>' +
        '<value name="ITEM"><shadow type="text"><field name="TEXT">东西</field></shadow></value></block>';
      xml += '<block type="lists_length"><value name="VALUE">' + listGetterShadow(L) + '</value></block>';
      xml += '<block type="lists_isEmpty"><value name="VALUE">' + listGetterShadow(L) + '</value></block>';
      /* 第四十三轮修正：lists_indexOf 的列表输入口叫 VALUE，不是 LIST！
         （源码：this.appendValueInput("VALUE").setCheck("Array")）
         原来错写成 <value name="LIST">，影子块接不上去，
         「在列表中找到」积木拖出来是空的，列表名自然也显示不出来。
         它还有一个 FIND 输入口，放要找的东西。 */
      xml += '<block type="lists_indexOf"><mutation type="VALUE" mode="FIND"></mutation>' +
        '<field name="TYPE">VALUE</field><field name="MODE">FIND</field>' +
        '<value name="VALUE">' + listGetterShadow(L) + '</value>' +
        '<value name="FIND"><shadow type="text"><field name="TEXT">东西</field></shadow></value></block>';
      xml += '<block type="zk_list_show">' + varField(L) + '</block>';
      xml += '<block type="zk_list_hide">' + varField(L) + '</block>';
    }

    /* ---------- 管理区放在最后，且压缩成一行 ----------
       【为什么要压缩】原来每个变量都带「✎ 重命名」「🗑 删除」两个按钮，
       5 个变量就占满整屏，积木被挤到看不见的地方。
       而field_variable 的下拉菜单里本来就有「重命名变量...」「删除变量...」，
       这两个按钮是重复功能。改成一行文字提示 + 积木优先显示。 */
    if (vars.length || lists.length) {
      xml += '<label text="────────  重命名 / 删除：在积木的下拉菜单里选 ────────"></label>';
      xml += '<label text="现有变量：' + escXml(vars.map(function (v) { return v.name; }).join('、')) + '"></label>';
      if (lists.length) {
        xml += '<label text="现有列表：' + escXml(lists.map(function (v) { return v.name; }).join('、')) + '"></label>';
      }
      /* 兜底：下拉菜单在某些 Blockly 版本里不提供，仍给一组紧凑按钮 */
      xml += '<button text="✎ 管理变量名" callbackKey="ZK_MANAGE_VARS"></button>';
    } else {
      xml += '<label text="还没有变量，点击上方按钮新建"></label>';
      xml += '<label text="还没有列表，点击上方按钮新建"></label>';
    }
    return domChildren(flyoutDom(xml));
  }

  /* 兼容旧回调名（列表已并入变量，不再单独注册） */
  function listFlyout(workspace) { return variableFlyout(workspace); }

  /* ============================================================
   * 高级分组：文本 / 数据集合 / 文件串口 / 自制积木
   * ============================================================ */
  function textFlyout() {
    return domChildren(flyoutDom(
      b_('text') + b_('text_join') + b_('text_append') + b_('text_length') +
      b_('text_isEmpty') + b_('text_charAt') + b_('text_indexOf')));
  }
  function dataFlyout() {
    return domChildren(flyoutDom(
      b_('zk_set_create') + b_('zk_set_add') + b_('zk_tuple_create')));
  }
  function fileFlyout() {
    return domChildren(flyoutDom(
      b_('zk_file_write') + b_('zk_file_read') +
      b_('zk_uart_write') + b_('zk_uart_read')));
  }
  function b_(type) { return '<block type="' + type + '"></block>'; }


  function procFlyout(workspace) {
    var xml = '<button text="＋ 制作新的积木" callbackKey="ZK_NEW_PROC"></button>';
    var defs = ZKB.MyBlocks.allDefs(workspace);
    if (!defs.length) {
      xml += '<label text="还没有自制积木"></label>' +
        '<label text="点击上方按钮，把常用积木打包成一个新积木"></label>';
    } else {
      defs.forEach(function (d, i) {
        var nm = (d.spec_ && d.spec_.name) || '我的积木';
        xml += '<label text="' + (i + 1) + '. ' + escXml(nm) + '"></label>';
        var spec = escXml(JSON.stringify(d.spec_ || {}));
        xml += '<block type="zk_my_call">' +
          '<mutation defid="' + d.id + '" spec="' + spec + '"></mutation></block>';
      });
    }
    return domChildren(flyoutDom(xml));
  }

  /* ============================================================
   * 新建 / 重命名 变量 / 列表 弹窗
   * ============================================================ */
  var ndRenameModel = null;   // 非 null 时为重命名模式
  function openNameDialog(kind) {
    var isList = kind === 'list';
    ndRenameModel = null;
    $('nd-title').textContent = isList ? '新建列表' : '新建变量';
    $('nd-tip').textContent = isList ? '输入列表名称，新建后会出现完整的列表积木' : '输入变量名称，新建后会出现完整的变量积木';
    $('nd-input').value = isList ? '我的列表' : '我的变量';
    $('name-dialog-mask').classList.remove('hidden');
    setTimeout(function () { $('nd-input').focus(); $('nd-input').select(); }, 30);
    $('nd-input').dataset.kind = kind;
  }
  /* ============================================================
   * 弹窗叠放管理
   *
   * 变量/列表重命名弹窗（#name-dialog-mask，z-index 2000）常常是
   * 从「变量/列表管理」面板（#varmgr-mask，z-index 925）里点开��
   * 两层都是 position:fixed; inset:0 的全屏遮罩，叠加后会：
   *   1) 视觉上多一层灰暗，弹窗像"沉"下去
   *   2) 更糟的是 varmgr 在下面，重命名弹窗点空白关闭时，
   *      事件可能穿透到管理面板，弹两层
   *
   * 做法：打开子弹窗时把父面板临时隐藏（不是降z-index，
   * 因为降了父面板仍会拦截点击），关闭时恢复。
   * 用一个栈记录"我隐藏了谁"，支持嵌套。
   * ============================================================ */
  var dialogStack = [];
  function pushDialog(id) {
    var el = $(id);
    if (!el || el.classList.contains('hidden')) return;
    el.classList.add('hidden');
    dialogStack.push(id);
  }
  function popDialog(id) {
    var i = dialogStack.indexOf(id);
    /* 第三十六轮：只有「确实被 pushDialog 收起过」才恢复显示。
       原来不管在不在栈里都会 classList.remove('hidden')，
       结果新建变量 → 命名弹窗 → 确定 → closeNameDialog()
       会把本来关着的「变量管理」面板强行弹出来，
       用户每次新建变量都得再点一次「完成」才能关掉。 */
    if (i < 0) return;
    dialogStack.splice(i, 1);
    var el = $(id);
    /* 栈里还有别的父面板时才不恢复 */
    if (el && dialogStack.indexOf(id) < 0) el.classList.remove('hidden');
  }
  function closeAllDialogs() {
    dialogStack.forEach(function (x) {
      var e = $(x);
      if (e) e.classList.remove('hidden');
    });
    dialogStack = [];
  }

  /* 关闭命名弹窗的统一出口：一定要走这里，
     否则会漏掉「恢复被临时隐藏的父面板」这一步。 */
  function closeNameDialog() {
    $('name-dialog-mask').classList.add('hidden');
    ndRenameModel = null;
    /* 恢复之前被 pushDialog 收起的父面板 */
    popDialog('varmgr-mask');
  }
  function openRenameDialog(model) {
    var isList = model.type === 'LIST';
    ndRenameModel = model;
    $('nd-title').textContent = isList ? '重命名列表' : '重命名变量';
    $('nd-tip').textContent = '输入新名称，所有用到它的积木会同步更新';
    $('nd-input').value = model.name;
    /* 从管理面板点开的 → 先把面板收起来，避免两层遮罩互相遮挡 */
    pushDialog('varmgr-mask');
    $('name-dialog-mask').classList.remove('hidden');
    setTimeout(function () { $('nd-input').focus(); $('nd-input').select(); }, 30);
  }
  function confirmNameDialog() {
    var name = $('nd-input').value.trim();
    if (!name) { ZKB.toast('名称不能为空'); return; }

    /* —— 重命名模式 —— */
    if (ndRenameModel) {
      var model = ndRenameModel;
      var isList = model.type === 'LIST';
      if (name === model.name) { closeNameDialog(); return; }
      if (ws.getVariable(name, model.type || '')) {
        ZKB.toast('已经有同名的' + (isList ? '列表' : '变量') + '了'); return;
      }
      try {
        ws.renameVariableById(model.getId(), name);
      } catch (e) { ZKB.toast('重命名失败：名称冲突'); return; }
      closeNameDialog();
      ZKB.toast('已重命名为：' + name);
      refreshFlyoutLater();
      return;
    }

    /* —— 新建模式 —— */
    var kind = $('nd-input').dataset.kind;
    var newIsList = kind === 'list';
    var type = newIsList ? 'LIST' : '';
    if (ws.getVariable(name, type)) { ZKB.toast('已经有同名的' + (newIsList ? '列表' : '变量') + '了'); return; }
    var newId = Blockly.utils.idGenerator.genUid();
    ws.createVariable(name, type, newId);
    /* 第四十一轮：记住刚建的列表，
       飞出层里的列表积木立刻指向它，学生马上能看到效果 */
    if (newIsList) activeListId = newId; else activeVarId = newId;
    closeNameDialog();
    ZKB.toast('已新建' + (newIsList ? '列表' : '变量') + '：' + name);
    refreshFlyoutLater();
  }
  function deleteVariable(model) {
    var isList = model.type === 'LIST';
    if (!global.confirm('确定删除' + (isList ? '列表' : '变量') + '「' + model.name + '」吗？\n所有用到它的积木也会被移除。')) return;
    ws.deleteVariableById(model.getId());
    ZKB.toast('已删除' + (isList ? '列表' : '变量') + '：' + model.name);
    /* 第四十一轮：删掉当前选中的那个后，回退到其它列表 */
    if (isList && activeListId === model.getId()) activeListId = '';
    if (!isList && activeVarId === model.getId()) activeVarId = '';
    refreshFlyoutLater();
    renderVarManager();   /* 若管理面板正开着，同步刷新 */
  }

  /* ============================================================
   * 第四十一轮：列表的「重命名 / 删除」菜单用列表措辞
   *
   * Blockly 内置的 field_variable 下拉菜单写死了
   * 「重命名变量...」「删除变量“%1”」，删列表时也写「变量」，
   * 学生分不清删的是变量还是列表。
   * 这里在生成菜单时按字段当前绑定的变量类型换文案。
   * ============================================================ */
  (function () {
    var FV = global.Blockly && global.Blockly.FieldVariable;
    if (!FV || FV.__zkListWording) return;
    var orig = FV.dropdownCreate;
    FV.dropdownCreate = function () {
      var opts = orig.apply(this, arguments);
      var model = this.variable;
      if (!model || model.type !== 'LIST') return opts;
      var name = this.getText();
      return opts.map(function (o) {
        if (o[0] === global.Blockly.Msg.RENAME_VARIABLE) return ['重命名列表...', o[1]];
        if (o[0] === global.Blockly.Msg.DELETE_VARIABLE.replace('%1', name)) {
          return ['删除列表“' + name + '”', o[1]];
        }
        return o;
      });
    };
    FV.__zkListWording = true;
  })();

  /* 列表的删除确认框同样要说「列表」
   *
   * Blockly 的确认文案是全局消息（Msg.DELETE_VARIABLE_CONFIRMATION），
   * 这里在删除列表的瞬间临时换成列表措辞，调用结束立即还原。
   */
  (function () {
    var VM = global.Blockly && global.Blockly.VariableMap;
    if (!VM || VM.__zkListConfirm) return;
    var orig = VM.prototype.deleteVariableById;
    VM.prototype.deleteVariableById = function (id) {
      var model = this.getVariableById ? this.getVariableById(id) : null;
      if (!model || model.type !== 'LIST') return orig.call(this, id);
      var oldC = global.Blockly.Msg.DELETE_VARIABLE_CONFIRMATION;
      var oldP = global.Blockly.Msg.CANNOT_DELETE_VARIABLE_PROCEDURE;
      global.Blockly.Msg.DELETE_VARIABLE_CONFIRMATION = '要删除对列表“%2”的%1个引用吗？';
      global.Blockly.Msg.CANNOT_DELETE_VARIABLE_PROCEDURE = '不能删除列表“%1”，因为它是函数“%2”定义的一部分';
      try {
        return orig.call(this, id);
      } finally {
        global.Blockly.Msg.DELETE_VARIABLE_CONFIRMATION = oldC;
        global.Blockly.Msg.CANNOT_DELETE_VARIABLE_PROCEDURE = oldP;
      }
    };
    VM.__zkListConfirm = true;
  })();

  /* ============================================================
   * 制作新的积木（自制积木）弹窗
   * ============================================================ */
  var pdEditing = null;     // 正在编辑的定义块（null = 新建）
  var pdItems = [];         // [{k:'arg',type:'num'|'bool',name} | {k:'label',text}]

  function openProcMaker(defBlock) {
    pdEditing = defBlock || null;
    var spec = defBlock ? defBlock.spec_ : null;
    pdItems = spec ? JSON.parse(JSON.stringify(spec.items || [])) : [];
    $('pd-title').textContent = defBlock ? '编辑自制积木' : '制作新的积木';
    $('pd-name').value = spec ? spec.name : '积木名称';
    $('pd-norefresh').checked = spec ? !!spec.noRefresh : false;
    renderPdItems();
    $('proc-dialog-mask').classList.remove('hidden');
  }
  ZKB.MyBlocks.openEdit = function (defBlock) { openProcMaker(defBlock); };

  function uniqueName(base, used) {
    var n = base, i = 2;
    while (used.indexOf(n) >= 0) { n = base + i++; }
    used.push(n);
    return n;
  }
  function renderPdItems() {
    var host = $('pd-items');
    host.innerHTML = pdItems.map(function (it, i) {
      if (it.k === 'label') {
        return '<span class="pd-chip pd-label"><input type="text" data-i="' + i + '" value="' + escXml(it.text) + '" maxlength="10"></span>' +
          '<button type="button" class="pd-x" data-del="' + i + '">×</button>';
      }
      var cls = it.type === 'bool' ? 'pd-hex' : 'pd-oval';
      return '<span class="pd-chip ' + cls + '"><input type="text" data-i="' + i + '" value="' + escXml(it.name) + '" maxlength="8"></span>' +
        '<button type="button" class="pd-x" data-del="' + i + '">×</button>';
    }).join('');
  }
  function pdAdd(kind) {
    var used = pdItems.map(function (it) { return it.name || it.text; });
    if (kind === 'num') pdItems.push({ k: 'arg', type: 'num', name: uniqueName('数字', used) });
    else if (kind === 'bool') pdItems.push({ k: 'arg', type: 'bool', name: uniqueName('布尔', used) });
    else pdItems.push({ k: 'label', text: uniqueName('文字', used) });
    renderPdItems();
  }
  function confirmProc() {
    var name = $('pd-name').value.trim() || '我的积木';
    /* 收集输入框最新值 */
    document.querySelectorAll('#pd-items input[data-i]').forEach(function (inp) {
      var i = parseInt(inp.getAttribute('data-i'), 10);
      var val = inp.value.trim();
      if (pdItems[i].k === 'label') pdItems[i].text = val || '文字';
      else pdItems[i].name = val || ('参数' + (i + 1));
    });
    /* 参数名不能重复或为空 */
    var argNames = pdItems.filter(function (it) { return it.k === 'arg'; }).map(function (it) { return it.name; });
    var dup = argNames.some(function (n, i) { return argNames.indexOf(n) !== i; });
    if (dup) { ZKB.toast('输入项名称不能重复'); return; }
    var spec = { name: name, items: pdItems.slice(), noRefresh: $('pd-norefresh').checked };
    if (pdEditing) ZKB.MyBlocks.updateDef(pdEditing, spec);
    else ZKB.MyBlocks.createDef(ws, spec);
    $('proc-dialog-mask').classList.add('hidden');
    ZKB.toast(pdEditing ? '自制积木已更新' : '自制积木已创建，可在下方定义其功能');
    /* 刷新「自制积木」分类，让新积木立即出现在积木区 */
    refreshFlyoutLater('自制积木');
  }

  /* 根据当前已添加设备重建左侧工具箱 */
  function rebuildToolbox() {
    if (!ws) return;
    var xml = ZKB.buildToolboxXml(ZKB.SimBoard.getDevices());
    try {
      ws.updateToolbox(Blockly.utils.xml.textToDom(xml));
    } catch (e) {
      console.warn('工具箱重建失败', e);
    }
    /* 重建后重新同步分类配色（色条与行底色保持同源） */
    if (ZKB.syncCategoryColours) ZKB.syncCategoryColours();
    /* 重建后恢复「高级」分组的折叠状态：updateToolbox 会生成全新的
       分类 DOM（zk-adv-child 标记丢失），必须重新标记，否则原本折叠的
       子分类（文本/数据集合/文件串口/自制积木）会被显示出来 */
    renderAdvancedGroup();
    [60, 200, 600].forEach(function (d) { setTimeout(renderAdvancedGroup, d); });
  }

  /* ============================================================
   * 硬件连接弹窗
   * ============================================================ */
  function openWireLib() {
    if (!ZKB.WireLib) { ZKB.toast('硬件连接模块未加载'); return; }
    ZKB.WireLib.open();
    ZKB.WireLib.bindDrag();
    /* 打开弹窗时把已连接硬件同步到舞台 */
    if (ZKB.Stage && ZKB.Stage.syncDevices) ZKB.Stage.syncDevices();
  }
  /* 第三十四轮：载入工程 / 示例后，把「还没连线」的硬件自动接上，
     否则「未连线不能运行」的规则会让别人打开你的工程就跑不起来 */
  function autoConnectDevices() {
    if (!ZKB.WireLib || !ZKB.WireLib.autoConnectAll) return;
    setTimeout(function () { ZKB.WireLib.autoConnectAll(); }, 60);
  }

  /* ============================================================
   * 拓展库
   * ============================================================ */
  function openExtLib() {
    $('ext-lib-mask').classList.remove('hidden');
    renderExtGrid('all', '');
    $('ext-search').value = '';
  }
  function closeExtLib() {
    $('ext-lib-mask').classList.add('hidden');
    /* 第五十轮：详情浮层挂在 body 上，关弹窗时一并收起 */
    if (ZKB.DeviceIntro) ZKB.DeviceIntro.hide();
  }
  function renderExtGrid(cat, keyword) {
    var list = ZKB.DEVICE_LIST.filter(function (d) {
      if (cat !== 'all' && d.cat !== cat) return false;
      if (keyword) {
        var k = keyword.toLowerCase();
        if (d.name.toLowerCase().indexOf(k) < 0 && d.desc.toLowerCase().indexOf(k) < 0) return false;
      }
      return true;
    });
    $('ext-grid').innerHTML = list.map(function (d) {
      var added = ZKB.SimBoard.hasDevice(d.id);
      /* 第五十轮：卡片右上角加「▶ 视频介绍」徽标（悬停时显现）。
         ⚠ 它是 <span> 不是 <button>（不能嵌套 button），
         点击时在 #ext-grid 的代理里先判断，命中就只开视频、不加设备。 */
      return '<button type="button" class="ext-card' + (added ? ' added' : '') +
        '" data-add="' + d.id + '" data-dev="' + d.id + '">' +
        '<span class="ext-video" data-video="' + d.id + '" title="看视频介绍">▶ 视频介绍</span>' +
        '<div class="ext-icon">' + ZKB.deviceIcon(d.id, 56) + '</div>' +
        '<div class="ext-name">' + d.name + '</div>' +
        '<div class="ext-desc">' + d.desc + '</div>' +
        '<div class="add-tag">' + (added ? '已添加' : '＋ 添加') + '</div>' +
        '</button>';
    }).join('');
  }

  /* ============================================================
   * 日志 / 提示 / 确认框
   * ============================================================ */
  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  function nowStamp() {
    var d = new Date();
    return pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':' + pad2(d.getSeconds());
  }
  function fileStamp() {
    var d = new Date();
    return d.getFullYear() + pad2(d.getMonth() + 1) + pad2(d.getDate()) +
      '-' + pad2(d.getHours()) + pad2(d.getMinutes()) + pad2(d.getSeconds());
  }

  var lastLogLine = null, lastLogBase = '', lastLogGroup = '', lastLogCount = 0;
  ZKB.log = function (text, cls, group) {
    var box = $('console');
    // 同组且与上一条完全相同的连续输出，折叠为“（连续 ×N）”，避免循环 print 刷屏
    if (group && lastLogLine && lastLogLine.parentNode === box &&
        group === lastLogGroup && text === lastLogBase) {
      lastLogCount++;
      lastLogLine.textContent = '[' + nowStamp() + '] ' + text +
        (lastLogCount > 1 ? ' （连续 ×' + lastLogCount + '）' : '');
      box.scrollTop = box.scrollHeight;
      return;
    }
    var line = document.createElement('div');
    line.className = cls || 'log-info';
    line.textContent = '[' + nowStamp() + '] ' + text;
    box.appendChild(line);
    while (box.childNodes.length > 300) box.removeChild(box.firstChild);
    box.scrollTop = box.scrollHeight;
    lastLogLine = line;
    lastLogBase = text;
    lastLogGroup = group || '';
    lastLogCount = 1;
  };

  var toastTimer = 0;
  ZKB.toast = function (msg) {
    var el = $('toast');
    el.textContent = msg;
    el.classList.remove('hidden');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.classList.add('hidden'); }, 2200);
  };

  ZKB.confirm = function (title, bodyText) {
    return new Promise(function (resolve) {
      $('modal-title').textContent = title;
      $('modal-body').textContent = bodyText;
      $('modal-mask').classList.remove('hidden');
      $('modal-ok').onclick = function () { $('modal-mask').classList.add('hidden'); resolve(true); };
      $('modal-cancel').onclick = function () { $('modal-mask').classList.add('hidden'); resolve(false); };
    });
  };

  function status(t) { $('status-left').textContent = t; }

  function bootLog() {
    ZKB.log('欢迎使用「掌控图形化编程」个人学习版', 'log-ok');
    ZKB.log('左侧拖入积木，右侧切换「舞台 / 虚拟仿真」，点击 ▶运行 查看效果', 'log-info');
    if (!ZKB.SerialLink.isSupported()) {
      ZKB.log('当前浏览器不支持 WebSerial：真机上传请改用 Chrome / Edge；仍可下载 .py 手动烧录', 'log-info');
    }
  }

  /* ============================================================
   * 代码预览
   * ============================================================ */
  function refreshCode() {
    var pre = $('code-preview');
    try {
      pre.textContent = ZKB.genPython(ws);
    } catch (e) {
      pre.textContent = '# 代码生成出错：' + e.message;
    }
    var n = ws.getAllBlocks(false).length;
    if (!running) status(n ? '就绪 · 共 ' + n + ' 块积木' : '就绪');
  }

  /* ============================================================
   * 模式切换
   * ============================================================ */
  function setMode(m) {
    mode = m;
    document.querySelectorAll('.mode-tab').forEach(function (t) {
      t.classList.toggle('active', t.getAttribute('data-mode') === m);
    });
    $('stage-view').classList.toggle('active', m === 'stage');
    $('sim-view').classList.toggle('active', m === 'sim');
    $('mode-hint').textContent = m === 'stage'
      ? '积木程序将在舞台中演示，串口输出显示为气泡'
      : '';
  }

  /* ============================================================
   * 运行 / 停止
   * ============================================================ */
  function setRunningUI(on) {
    running = on;
    $('btn-run').disabled = on;
    $('btn-stop').disabled = !on;
  }

  /* ============================================================
   * 第三十四轮：虚拟仿真必须先完成「硬件连接」
   *
   * 教学上要让「接线 → 运行」成为固定动作：
   * 只要拓展库里添加了需要接线的硬件，而它还没连到扩展板接口，
   * 就拦住运行，先弹窗提示去做硬件连接；连好之后再次点击 ▶ 即可运行。
   * ============================================================ */
  function pendingConnections() {
    if (!ZKB.WireLib || !ZKB.WireLib.unconnectedDevices) return [];
    return ZKB.WireLib.unconnectedDevices();
  }
  function doRun() {
    if (running) return;
    /* 第三十四轮：硬件连接是运行的前置条件——
       只要有拓展设备还没连线，就先提示去「硬件连接」完成接线，
       不直接运行积木区的程序。（先于「工作区有没有积木」判断，
       因为用户刚加完设备的场景下，多半还要继续摆积木） */
    var pend = pendingConnections();
    if (pend.length) {
      ZKB.log('⚠ 还有 ' + pend.length + ' 个拓展设备没有完成硬件连接：' +
        pend.join('、') + '，请先在「硬件连接」中连线后再运行。', 'log-warn');
      ZKB.toast('请先完成硬件连接（' + pend.length + ' 个设备未连接）');
      openWireLib();
      return;
    }
    if (!ws.getTopBlocks(false).length) { ZKB.toast('工作区还没有积木'); return; }
    refreshCode();
    try {
      ZKB.SimEngine.run(ws);
      setRunningUI(true);
      status('运行中…（' + (mode === 'sim' ? '虚拟仿真' : '舞台') + '）');
      ZKB.log('▶ 开始运行程序（' + (mode === 'sim' ? '虚拟仿真模式' : '舞台模式') + '）', 'log-info');
    } catch (e) {
      ZKB.log('启动失败：' + e.message, 'log-err');
    }
  }

  function doStop() {
    if (!running) return;
    ZKB.SimEngine.stop();
    setRunningUI(false);
    status('已停止');
  }

  /* ============================================================
   * 工程：新建 / 保存 / 打开 / 示例
   * ============================================================ */
  function newProject() {
    ZKB.confirm('新建工程', '将清空当前全部积木与拓展设备，确定继续吗？').then(function (ok) {
      if (!ok) return;
      if (running) doStop();
      ws.clear();
      ZKB.SimBoard.setDevices([]);
      rebuildToolbox();
      refreshCode();
      ZKB.log('已新建空白工程', 'log-info');
      ZKB.toast('新工程已就绪');
    });
  }

  /* 第三十三轮：保存固定输出 **mPython 官方格式** 的 .mxml。
     · 类型改写成 hunan_*，可直接在 mPython IDE 里打开
     · 本项目也能打开（remapTypes 支持 hunan_* → zk_* 双向识别）
     · 输出带严格缩进（每层 2 空格），人读得懂、也便于和教材代码对照
     · 官方没有对应物的积木会原样保留，在 mPython 里显示为未知块，
       但整份工程仍能正常载入，不会报废 */
  function saveProject() {
    var xml = ZKB.Project.toMxml(ws, ZKB.SimBoard.getDevices(), {
      mode: 'mpython',
      /* 附带当前语音凭据是否自定义过，方便换设备续用 */
      xfyunCustom: !!(ZKB.Xfyun && ZKB.Xfyun.isCustom())
    });
    download(new Blob([xml], { type: 'text/xml;charset=utf-8' }),
      ZKB.Project.fileName());
    var un = ZKB.Project.unmappedTypes(ZKB.Project.pureXml(xml));
    if (un.length) {
      ZKB.log('工程已保存（.mxml，mPython 官方格式）。有 ' + un.length +
        ' 种积木 mPython 官方没有对应物，在 mPython IDE 里会显示为未知块：' +
        un.slice(0, 5).join(', ') + (un.length > 5 ? ' …' : ''), 'log-info');
      ZKB.toast('已保存（' + un.length + ' 种积木 mPython 不认识）');
    } else {
      ZKB.log('工程已保存（.mxml，mPython 官方格式，全部积木都有对应类型）', 'log-ok');
      ZKB.toast('已保存（.mxml，可直接用 mPython IDE 打开）');
    }
  }

  /* ============================================================
   * 第四十五轮：按程序内容自动补齐拓展设备
   *
   * 【为什么要做】
   * 打开一个带传感器的程序（六年级示例、官方 mxml、老师分享的工程），
   * 里面用了超声波 / 温湿度 / 舵机这些拓展设备，
   * 但「拓展库」里并没有把它们加进来，
   * 于是：设备分类不显示 → 积木找不到 → 接线无从谈起 → 跑不起来。
   *
   * 这里按积木类型反查需要哪些设备，自动补进设备列表，
   * 这样打开程序就能直接跑。
   *
   * 【积木类型 → 设备 id 的对应表】
   * 只列「这个积木离开对应设备就没意义」的传感器 / 执行器，
   * 板载资源（彩灯、蜂鸣器、按键、光线、声音）不算拓展设备。
   */
  var BLOCK_DEVICE_MAP = {
    /* 超声波 */
    zk_ultra: 'ultrasonic', zk_ultra_cm: 'ultrasonic',
    zk_ultra_mm: 'ultrasonic', zk_ultra_near: 'ultrasonic',
    /* 温湿度 / 温度 */
    zk_dht_measure: 'dht', zk_dht_val: 'dht', zk_dht_temp: 'dht',
    zk_dht_hum: 'dht', zk_dht_dew: 'dht', zk_dht_ok: 'dht',
    zk_ds18_temp: 'dht', zk_ds18_ok: 'dht',
    zk_temp: 'dht', zk_ambient: 'dht',
    /* 舵机 */
    zk_servo: 'servo', zk_servo_get: 'servo', zk_servo_off: 'servo',
    /* 人体红外 / 加热元件 */
    zk_pir: 'pir', zk_pir_count: 'pir', zk_pir_reset: 'pir',
    zk_heat: 'heater', zk_heat_power: 'heater',
    /* 颜色识别 / AI 摄像头 */
    zk_color_rgb: 'color', zk_color_seen: 'color',
    zk_camera_result: 'camera', zk_camera_seen: 'camera',
    /* 直流电机 / 水泵 / 风扇 */
    zk_motor: 'motor', zk_motor_stop: 'motor',
    zk_motor_get_speed: 'motor', zk_motor_set: 'motor',
    zk_parrot_speed: 'motor', zk_parrot_get: 'motor', zk_parrot_stop: 'motor',
    /* 第四十六轮：拓展板「灯」积木已移到 LED 模块分类，
       这里也要跟着改，否则载入程序会自动添加「直流电机」设备，
       积木却出现在没添加设备的分类里，学生看不到。 */
    zk_parrot_led: 'ledModule', zk_parrot_led_bright: 'ledModule',
    zk_pump: 'pump', zk_pump_on: 'pump',
    zk_pump_get_power: 'pump', zk_pump_flow: 'pump', zk_pump_power: 'pump',
    zk_fan: 'fan', zk_fan_power: 'fan',
    /* 小车 / 巡线小车 / 机器人 */
    zk_car: 'car', zk_car_wheels: 'car', zk_car_dist: 'car', zk_front_has: 'car',
    zk_trace_motor: 'traceCar', zk_trace_auto: 'traceCar',
    zk_trace_line: 'traceCar', zk_trace_dist: 'traceCar',
    zk_robot_go: 'robot', zk_robot_speed: 'robot', zk_robot_ground: 'robot',
    zk_robot_dist: 'robot', zk_robot_cam: 'robot', zk_robot_asr: 'robot',
    /* 红外：传感器 / 遥控器 / 发射接收 */
    zk_ir: 'ir', zk_when_ir: 'ir',
    zk_ir_send: 'irTx', zk_ir_receive: 'irRx',
    zk_remote_key: 'remote', zk_remote_dir: 'remote',
    /* MP3 / 语音模块 */
    zk_mp3_play: 'mp3', zk_mp3_stop: 'mp3', zk_mp3_volume: 'mp3',
    zk_mp3_folder: 'mp3', zk_mp3_playing: 'mp3',
    /* RGB 灯带 */
    zk_rgb_strip: 'rgbStrip', zk_rgb_strip_all: 'rgbStrip',
    zk_rgb_strip_off: 'rgbStrip', zk_rgb_strip_rainbow: 'rgbStrip',
    zk_strip_count: 'rgbStrip', zk_strip_get: 'rgbStrip',
    zk_strip_all_off: 'rgbStrip', zk_strip_rainbow_stop: 'rgbStrip',
    zk_neopixel_fill: 'rgbStrip',
    /* 巡线传感器 */
    zk_tracker_read: 'tracker', zk_tracker_state: 'tracker',
    /* 其它拓展传感器 */
    zk_soil: 'soil', zk_soil_pct: 'soil', zk_soil_raw: 'soil', zk_soil_wet: 'soil',
    zk_pm25: 'pm25', zk_pm25_good: 'pm25', zk_pm25_harm: 'pm25',
    zk_pm25_level: 'pm25', zk_pm25_value: 'pm25',
    zk_pressure: 'baro', zk_pressure_hpa: 'baro', zk_pressure_pa: 'baro',
    zk_angle_read: 'angle', zk_altitude: 'angle',
    zk_magnetic_init: 'magnetic', zk_magnetic_heading: 'magnetic',
    zk_magnetic_calibrate: 'magnetic', zk_magnetic_peeling: 'magnetic',
    zk_relay: 'relay',
    zk_led_on: 'ledModule', zk_led_off: 'ledModule',
    zk_led_brightness: 'ledModule', zk_led_bright_set: 'ledModule',
    zk_led_get_bright: 'ledModule', zk_led_is_on: 'ledModule',
    zk_light_raw: 'lightExt', zk_light_bright: 'lightExt', zk_light_pct: 'lightExt',
    zk_gravity_read: 'gravity',
    zk_power_read: 'powerMeter',
    zk_ext_btn: 'button', zk_ext_btn_pressed: 'button',
    zk_ext_btn_count: 'button', zk_ext_btn_reset: 'button',
    zk_mic: 'mic',
    zk_rfid_scan: 'rfid', zk_rfid_id: 'rfid',
    zk_qrcode: 'qrcode',
    zk_gps_init: 'gps', zk_gps_data: 'gps',
    zk_gps_parse: 'gps', zk_gps_ready: 'gps',
    zk_speech2_init: 'speech2', zk_speech2_result: 'speech2',
    zk_asr_text: 'asr',
    zk_wifi_connect: 'wifi', zk_wifi_ok: 'wifi',
    zk_ntp_sync: 'ntp',
    zk_mqtt_connect: 'mqtt', zk_mqtt_pub: 'mqtt',
    zk_mqtt_msg: 'mqtt', zk_when_mqtt: 'mqtt',
    zk_radio_send: 'radio', zk_radio_msg: 'radio',
    zk_radio_group: 'radio', zk_when_radio: 'radio',
    zk_weather: 'weather',
    zk_k210_digit: 'camera', zk_k210_face_detect: 'camera',
    zk_k210_face_h: 'camera', zk_k210_face_num: 'camera',
    zk_k210_face_value: 'camera', zk_k210_face_w: 'camera',
    zk_k210_face_x: 'camera', zk_k210_face_y: 'camera',
    zk_k210_kpu_load: 'camera',
    zk_k210_obj_count: 'camera', zk_k210_obj_detect: 'camera',
    zk_k210_obj_label: 'camera', zk_k210_obj_value: 'camera'
  };

  /* 扫描工作区，推断需要补哪些拓展设备 */
  function inferDevices() {
    var need = {};
    try {
      ws.getAllBlocks(false).forEach(function (b) {
        var dev = BLOCK_DEVICE_MAP[b.type];
        if (dev) need[dev] = 1;
      });
    } catch (e) { }
    return Object.keys(need);
  }

  /* 第四十五轮：把推断能力暴露出去，便于测试与外部调用 */
  ZKB.inferDevices = inferDevices;
  ZKB.autoAddDevices = function (extra) { return autoAddDevices(extra); };
  ZKB.BLOCK_DEVICE_MAP = BLOCK_DEVICE_MAP;

  /* 把推断出的设备补进当前设备列表，并同步接线 */
  function autoAddDevices(extra) {
    var need = inferDevices();
    /* 调用方明确指定的设备优先 */
    if (extra && extra.length) extra.forEach(function (d) { need[d] = 1; });
    if (!need.length) return [];

    var cur = ZKB.SimBoard.getDevices ? ZKB.SimBoard.getDevices() : [];
    var have = {};
    cur.forEach(function (d) { have[ZKB.baseOf ? ZKB.baseOf(d) : d] = 1; });

    var add = need.filter(function (d) { return !have[d]; });
    if (!add.length) return [];

    /* setDevices 会重建设备列表，这里用现有列表 + 新增 */
    var merged = cur.slice();
    add.forEach(function (d) { merged.push(d); });
    ZKB.SimBoard.setDevices(merged);
    /* 补上的设备也要接线，否则「未连线不能运行」 */
    if (typeof autoConnectDevices === 'function') autoConnectDevices();
    return add;
  }

  function loadProject(data, fileName) {
    if (!data) { ZKB.toast('文件格式不正确'); ZKB.log('打开失败：无法识别的文件格式', 'log-err'); return; }
    if (running) doStop();

    /* ③ MicroPython 源码 → 积木 */
    if (data.fmt === 'py') {
      try {
        ws.clear();
        var r = ZKB.Project.loadFromPython(ws, data.py, []);
        rebuildToolbox();
        refreshCode();
        ZKB.SimBoard.setDevices((r && r.devices) || []);
        /* 第四十五轮：按积木内容自动补齐拓展设备 */
        var addedPy = autoAddDevices();
        if (addedPy.length) {
          rebuildToolbox();
          autoConnectDevices();
          ZKB.log('已自动添加拓展设备：' + addedPy.join('、'), 'log-ok');
        }
        if (r && r.mode === 'blocks') {
          ZKB.log('已从 Python 源码还原 ' + r.count + ' 个积木：' + (fileName || 'py 文件'), 'log-ok');
          ZKB.toast('已还原为积木');
        } else if (r && r.mode === 'codeblock') {
          ZKB.log('Python 源码已放入代码积木（暂不支持逐句还原）：' + (fileName || 'py 文件'), 'log-ok');
          ZKB.toast('源码已放入代码积木');
        } else {
          ZKB.log('无法解析该 Python 源码：' + (fileName || 'py 文件'), 'log-err');
          ZKB.toast('无法解析该 Python 源码');
        }
      } catch (e) {
        ZKB.log('Python 载入失败：' + e.message, 'log-err');
        ZKB.toast('Python 载入失败');
      }
      return;
    }

    /* ① zkb / ② mxml（Blockly XML） */
    if (!data.xml) { ZKB.toast('文件格式不正确'); ZKB.log('打开失败：文件中没有积木数据', 'log-err'); return; }
    try {
      ws.clear();
      /* 官方 mxml 用 hunan_* / mpython_* 积木名，先按映射表改成本项目类型 */
      var xml = ZKB.Project.remapTypes(data.xml);
      var dom = Blockly.utils.xml.textToDom(xml);
      Blockly.Xml.domToWorkspace(dom, ws);
      ZKB.SimBoard.setDevices(data.devices || []);
      autoConnectDevices();
      /* 第四十五轮：按积木内容自动补齐拓展设备
         （官方 mxml 里用了超声波 / 温湿度等设备，
           但文件本身不带设备清单，这里按积木反查补上） */
      var addedMx = autoAddDevices();
      rebuildToolbox();
      refreshCode();
      if (addedMx.length) {
        ZKB.log('已自动添加拓展设备：' + addedMx.join('、'), 'log-ok');
        ZKB.toast('已自动添加 ' + addedMx.length + ' 个拓展设备');
      }

      /* 导入官方 mxml 时，若有本项目未收录的积木类型，给出明确提示 */
      var un = ZKB.Project.unknownTypes(xml);
      if (un.length) {
        ZKB.log('工程中有 ' + un.length + ' 种积木本项目未收录，已按未知积木占位：' +
          un.slice(0, 6).join(', ') + (un.length > 6 ? ' …' : ''), 'log-info');
        ZKB.toast('已打开，但有 ' + un.length + ' 种积木不认识');
      }
      var fmtName = { zkb: '.zkb', mxml: '.mxml', xml: '.xml' }[data.fmt] || '';
      ZKB.log('已打开工程：' + (fileName || '本地文件') + fmtName, 'log-ok');
      ZKB.toast('工程已载入');
    } catch (e) {
      ZKB.log('工程载入失败：' + e.message, 'log-err');
      ZKB.toast('工程载入失败');
    }
  }

  function onOpenFile(e) {
    var file = e.target.files[0];
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function () {
      var data = ZKB.Project.parse(reader.result, file.name);
      if (!data) {
        ZKB.toast('无法识别的文件格式');
        ZKB.log('打开失败：不支持的文件类型（支持 .mxml / .xml / .zkb / .py）', 'log-err');
      } else {
        loadProject(data, file.name);
      }
      e.target.value = '';
    };
    reader.readAsText(file);
  }

  function loadExample(ex) {
    if (running) doStop();
    try {
      ws.clear();
      var dom = Blockly.utils.xml.textToDom(ex.xml);
      Blockly.Xml.domToWorkspace(dom, ws);
      ZKB.SimBoard.setDevices(ex.devices || []);
      /* 第三十四轮：示例自带拓展设备 → 自动接线，
         否则「未连线不能运行」的规则会让示例跑不起来 */
      if (ex.devices && ex.devices.length) autoConnectDevices();
      rebuildToolbox();
      refreshCode();
      /* 示例可指定舞台情景：载入后自动切换（如避障小车 → 交通路口） */
      if (ex.scene && ZKB.Stage && ZKB.Stage.applyScene) {
        /* 第三十八轮：先切到舞台模式，否则情景切了但当前是虚拟仿真视图，
           学生看不到效果（右上角标签页也停在「虚拟仿真」）。 */
        setMode('stage');
        ZKB.Stage.applyScene(ex.scene, true);
        var sc = (ZKB.SceneLib && ZKB.SceneLib.SCENES[ex.scene]);
        var scName = (sc && sc.name) || ex.scene;
        /* 同步舞台工具栏的「情景」下拉框与右侧情景名 */
        if (ZKB.Stage.syncSceneSelect) ZKB.Stage.syncSceneSelect(ex.scene);
        ZKB.log('舞台已切换到情景：' + scName, 'log-ok');
        if (ZKB.toast) ZKB.toast('已切换到情景：' + scName);
      }
      /* 示例可指定初始化元素（elKey）：把「元素下拉」为空的
         元素类积木自动填成舞台上对应元素的 uid（元素 uid 运行时才生成）。
         第三十一轮：控制模块的 4 个元素积木已删除，统一改由运动 / 外观模块承担。 */
      /* 第二十一轮：elKeys 支持多个元素（示例④：小车 + 行人）；
         elKey 保持单元素兼容。逐个元素键依次填入「元素下拉」为空的积木。 */
      var elKeys = ex.elKeys || (ex.elKey ? [ex.elKey] : []);
      var EL_BLOCKS = ['zk_stage_move', 'zk_stage_layer', 'zk_stage_scale',
        'zk_stage_rotate', 'zk_mv_goto', 'zk_mv_random', 'zk_mv_glide', 'zk_mv_changex',
        'zk_mv_changey', 'zk_mv_setx', 'zk_mv_sety', 'zk_mv_x', 'zk_mv_y',
        'zk_mv_turnright', 'zk_mv_turnleft', 'zk_mv_pointdir',
        'zk_mv_pointto', 'zk_mv_dir', 'zk_mv_bounce', 'zk_mv_steps',
        'zk_look_show', 'zk_look_hide', 'zk_look_visible', 'zk_look_size',
        'zk_look_chsize', 'zk_look_setsize', 'zk_look_opacity', 'zk_look_ghost',
        'zk_look_colorfx', 'zk_look_cleareffects',
        'zk_look_layerop', 'zk_look_layern',
        'zk_el_walk', 'zk_el_walk_done'];
      if (elKeys.length && ZKB.Stage && ZKB.Stage.getItems) {
        /* 按积木里写的元素键（如果写的是键名而非 uid）优先匹配 */
        var pool = elKeys.map(function (k) {
          return ZKB.Stage.getItems().filter(function (i) { return i.k === k; })[0];
        }).filter(Boolean);
        ws.getAllBlocks(false).forEach(function (b) {
          if (EL_BLOCKS.indexOf(b.type) < 0) return;
          var f = b.getField('EL');
          if (!f) return;
          var cur = String(f.getValue() || '');
          /* 已经是有效 uid 就不动 */
          if (cur && cur.indexOf('it') === 0) return;
          /* 优先按积木里写的元素键匹配（示例 XML 里写 car / pedestrian） */
          var hit = pool.filter(function (it) { return it.k === cur; })[0];
          if (!hit) hit = pool[0];
          if (hit) f.setValue(hit.uid);
        });
      }
      ZKB.log('已载入示例：' + ex.name, 'log-ok');
      ZKB.toast('示例已载入' + (ex.scene && ZKB.SceneLib && ZKB.SceneLib.SCENES[ex.scene]
        ? '，舞台已切到「' + ZKB.SceneLib.SCENES[ex.scene].name + '」' : '') + '，点击 ▶运行 试试');
    } catch (e) {
      ZKB.log('示例载入失败：' + e.message, 'log-err');
    }
  }

  /* ============================================================
   * 第四十九轮：信息科技教材（湘科版）示例程序
   *
   * 【为什么用 py 源码而不是 Blockly XML】
   *   教材的示例程序在课件里是**图片截图**（docx/pptx 内不含代码文本），
   *   无法提取成积木。而官方六年级 py 示例程序是**可运行的源码**，
   *   用 Py2Blocks 反解成积木，既能像普通示例一样在积木区编辑，
   *   又能保证上传到真机的代码与官方示例完全一致。
   *
   * 【流程】
   *   py 源码 → Py2Blocks.parse() → 积木 → 生成 py → 上传真机
   * ============================================================ */
  function loadTextbookExample(item, groupLabel) {
    if (running) doStop();
    try {
      var pySrc = ZKB.TEXTBOOK_PY ? ZKB.TEXTBOOK_PY(item.file) : '';
      if (!pySrc) {
        ZKB.log('教材示例源码缺失：' + item.file, 'log-err');
        return false;
      }
      ws.clear();
      /* py → 积木 */
      var r = ZKB.Py2Blocks && ZKB.Py2Blocks.parse
        ? ZKB.Py2Blocks.parse(ws, pySrc)
        : { ok: false, reason: '反解器未就绪' };
      if (!r || !r.ok) {
        ZKB.log('教材示例还原失败：' + (r && r.reason || '未知原因'), 'log-err');
        ZKB.toast('这个示例暂时无法还原成积木');
        return false;
      }
      /* 教材示例需要的拓展设备 → 自动添加并接线 */
      var devs = item.devices || [];
      if (devs.length) {
        ZKB.SimBoard.setDevices(devs);
        autoConnectDevices();
      }
      rebuildToolbox();
      refreshCode();
      /* 切到合适的舞台情景 */
      if (item.scene && ZKB.Stage && ZKB.Stage.applyScene) {
        setMode('stage');
        ZKB.Stage.applyScene(item.scene, true);
        if (ZKB.Stage.syncSceneSelect) ZKB.Stage.syncSceneSelect(item.scene);
      }
      ZKB.log('已载入教材示例：' + groupLabel + ' · ' + item.act, 'log-ok');
      ZKB.toast('已载入「' + item.act + '」，可点击 ▶运行，或上传到掌控板');
      return true;
    } catch (e) {
      ZKB.log('教材示例载入失败：' + e.message, 'log-err');
      ZKB.toast('教材示例载入失败');
      return false;
    }
  }

  /* 渲染教材菜单（按单元/活动分组） */
  function renderTextbookMenu() {
    var menu = $('textbook-menu');
    if (!menu || !ZKB.TEXTBOOK_GROUPS) return;
    var html = '';
    ZKB.TEXTBOOK_GROUPS.forEach(function (grp) {
      html += '<div class="menu-head">' + grp.book + ' · ' + grp.unit + '</div>';
      grp.items.forEach(function (it, i) {
        var label = grp.book + '|' + grp.unit + '|' + it.act + '|' + i;
        html += '<button type="button" class="menu-item" data-tb="' +
          encodeURIComponent(label) + '" title="' +
          it.file + (it.devices && it.devices.length ? '（需拓展：' + it.devices.join('、') + '）' : '') + '">' +
          it.act + '</button>';
      });
    });
    html += '<div class="menu-sep"></div>' +
      '<div class="menu-item" style="color:#6b7280;cursor:default">教材示例可直接上传到掌控板</div>';
    menu.innerHTML = html;
  }

  /* ============================================================
   * 下载 / 复制
   * ============================================================ */
  function download(blob, name) {
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 200);
  }
  function downloadPy() {
    refreshCode();
    var code = ZKB.genPython(ws);
    download(new Blob([code], { type: 'text/x-python' }), 'main.py');
    ZKB.log('已导出 main.py，可用 mPython 客户端烧录到掌控板', 'log-ok');
  }
  function copyCode() {
    var text = $('code-preview').textContent;
    function ok() { ZKB.toast('代码已复制到剪贴板'); }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(ok).catch(function () { fallbackCopy(text) && ok(); });
    } else if (fallbackCopy(text)) ok();
  }
  function fallbackCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    var done = false;
    try { done = document.execCommand('copy'); } catch (e) {}
    ta.remove();
    return done;
  }

  /* ============================================================
   * UI 绑定
   * ============================================================ */
  function closeAllMenus() {
    document.querySelectorAll('.menu.open').forEach(function (m) { m.classList.remove('open'); });
  }

  /* ============================================================
   * 舞台工具栏：情景一键布置 / 元素添加 / 网格 / 清空
   * ============================================================ */
  function bindStageUI() {
    var selScene = $('stg-scene'), selAdd = $('stg-add');
    if (!selScene || !selAdd) { console.warn('舞台工具栏未找到，跳过绑定'); return; }

    /* 预置情景 */
    if (ZKB.SceneLib) {
      var scenes = ZKB.SceneLib.SCENES;
      selScene.innerHTML = Object.keys(scenes).map(function (k) {
        return '<option value="' + k + '">' + scenes[k].name + '</option>';
      }).join('');
      selScene.addEventListener('change', function () {
        ZKB.Stage.applyScene(this.value);
      });
      /* 第三十八轮：初始化时同步右侧的当前情景名 */
      if (ZKB.Stage.syncSceneSelect) ZKB.Stage.syncSceneSelect(selScene.value);

      /* 元素下拉：按分类分组 */
      var cats = ZKB.SceneLib.cats();
      selAdd.innerHTML = '<option value="">选择元素…</option>' + cats.map(function (c) {
        return '<optgroup label="' + c + '">' + ZKB.SceneLib.byCat(c).map(function (k) {
          var d = ZKB.SceneLib.LIB[k];
          return '<option value="' + k + '">' + d.name + '</option>';
        }).join('') + '</optgroup>';
      }).join('');
    }

    var btnAdd = $('stg-add-go');
    if (btnAdd) btnAdd.addEventListener('click', function () {
      var k = selAdd.value;
      if (!k) { ZKB.toast('请先选择要添加的元素'); return; }
      /* 添加到舞台中心附近 */
      ZKB.Stage.add(k, 340 + Math.round(Math.random() * 120), 300 + Math.round(Math.random() * 80));
    });

    var btnGrid = $('stg-grid');
    if (btnGrid) btnGrid.addEventListener('click', function () {
      var host = $('stage-host');
      if (!host) return;
      host.classList.toggle('show-grid');
      this.classList.toggle('on', host.classList.contains('show-grid'));
    });

    /* 显示 / 隐藏所有元素文字 */
    var btnText = $('stg-text');
    if (btnText) {
      btnText.classList.toggle('on', ZKB.Stage.textVisible());
      btnText.addEventListener('click', function () {
        var on = ZKB.Stage.toggleText();
        this.classList.toggle('on', on);
        ZKB.toast(on ? '已显示元素文字' : '已隐藏全部元素文字');
      });
    }

    /* 锁定背景元素（只有硬件联动元素可移动） */
    var btnLock = $('stg-lock');
    if (btnLock) {
      btnLock.classList.toggle('on', ZKB.Stage.isLocked());
      btnLock.addEventListener('click', function () {
        var on = ZKB.Stage.toggleLock();
        this.classList.toggle('on', on);
        ZKB.toast(on ? '已锁定背景元素（右键可解除）' : '已解除锁定');
      });
    }

    /* 全屏显示：自适应放大所有元素，便于观察与编辑 */
    var btnFull = $('stg-full');
    if (btnFull) btnFull.addEventListener('click', function () {
      var on = ZKB.Stage.toggleFullscreen();
      this.textContent = on ? '⛶ 退出全屏' : '⛶ 全屏';
      this.classList.toggle('on', on);
    });
    document.addEventListener('fullscreenchange', function () {
      if (!document.fullscreenElement) {
        var b = $('stg-full');
        if (b) { b.textContent = '⛶ 全屏'; b.classList.remove('on'); }
        document.body.classList.remove('zk-stage-full');
      }
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        var b = $('stg-full');
        if (b && document.body.classList.contains('zk-stage-full')) {
          b.textContent = '⛶ 全屏'; b.classList.remove('on');
        }
        document.body.classList.remove('zk-stage-full');
      }
    });

    /* 舞台尺寸（逻辑坐标系宽高，可手动调节） */
    var wIn = $('stg-w'), hIn = $('stg-h');
    function syncSizeInputs() {
      var s = ZKB.Stage.getSize();
      if (wIn) wIn.value = s.w;
      if (hIn) hIn.value = s.h;
    }
    syncSizeInputs();
    var btnApply = $('stg-size-apply');
    if (btnApply) btnApply.addEventListener('click', function () {
      var w = parseInt(wIn && wIn.value, 10) || 800;
      var h = parseInt(hIn && hIn.value, 10) || 560;
      var r = ZKB.Stage.setSize(w, h);
      syncSizeInputs();
      ZKB.toast('舞台尺寸已设为 ' + r.w + ' × ' + r.h);
    });
    var btnReset = $('stg-size-reset');
    if (btnReset) btnReset.addEventListener('click', function () {
      ZKB.Stage.setSize(800, 560);
      syncSizeInputs();
      ZKB.toast('已恢复默认尺寸 800 × 560');
    });
    /* 窗口尺寸变化时保持输入框同步 */
    window.addEventListener('resize', syncSizeInputs);

    var btnFit = $('stg-fit');
    if (btnFit) btnFit.addEventListener('click', function () {
      Blockly.svgResize(ws);
      ZKB.toast('已按窗口重新适配');
    });

    var btnClear = $('stg-clear');
    if (btnClear) btnClear.addEventListener('click', function () {
      if (!confirm('确定要清空舞台上的所有元素吗？（可在上方「情景」中一键恢复）')) return;
      ZKB.Stage.clear();
      ZKB.toast('舞台已清空');
    });
  }

  /* ============================================================
   * 自动保存到浏览器缓存（IndexedDB + localStorage 双保险）
   * 只要不清理浏览器缓存，关闭浏览器后仍可恢复工程。
   * ============================================================ */
  var AKEY = 'zkb_autosave_v1';
  var autosaveTimer = 0;

  function snapshot() {
    return {
      xml: Blockly.Xml.domToText(Blockly.Xml.workspaceToDom(ws)),
      devices: ZKB.SimBoard.getDevices(),
      mode: mode,
      savedAt: Date.now()
    };
  }

  function bindAutosave() {
    /* 积木变化 → 延迟保存 */
    ws.addChangeListener(function (e) {
      if (e.isUiEvent) return;
      clearTimeout(autosaveTimer);
      autosaveTimer = setTimeout(saveSnapshot, 900);
    });
    /* 关闭窗口前再存一次（同步写 localStorage 最保险） */
    window.addEventListener('beforeunload', function () {
      try { ZKB.Store.setLocal(AKEY, snapshot()); } catch (err) {}
    });
    /* 启动时尝试恢复 */
    restoreSnapshot();
  }

  function saveSnapshot() {
    if (!ws) return;
    var data = snapshot();
    try { ZKB.Store.setLocal(AKEY, data); } catch (e) {}
    if (ZKB.Store.saveProject) {
      ZKB.Store.saveProject(data).then(function () {
        $('status-left') && ($('status-left').textContent = '已自动保存到本地缓存');
      });
    }
  }

  function restoreSnapshot() {
    var data = ZKB.Store.getLocal(AKEY);
    if (!data || !data.xml) {
      ZKB.log('未发现本地缓存，将开始新工程（编辑后会自动保存）', 'log-info');
      return;
    }
    try {
      Blockly.Xml.domToWorkspace(Blockly.utils.xml.textToDom(data.xml), ws);
      ZKB.SimBoard.setDevices(data.devices || []);
      autoConnectDevices();
      rebuildToolbox();
      refreshCode();
      var when = data.savedAt ? new Date(data.savedAt).toLocaleString('zh-CN') : '';
      ZKB.log('已从浏览器缓存恢复上次工程（' + when + '）', 'log-ok');
      status('已恢复本地缓存的工程');
    } catch (e) {
      ZKB.log('本地缓存恢复失败：' + e.message, 'log-err');
    }
  }

  /* ============================================================
   * 意见反馈：点击右下角版权文字 → 确认弹窗 → 新窗口打开问卷网站
   * ============================================================ */
  var FEEDBACK_URL = 'https://txc.qq.com/products/802163';

  function bindFeedback() {
    var trigger = $('status-right');
    var mask = $('fb-mask');
    if (!trigger || !mask) return;

    function open() { mask.classList.remove('hidden'); }
    function close() { mask.classList.add('hidden'); }

    trigger.addEventListener('click', open);
    $('fb-cancel').addEventListener('click', close);
    $('fb-close').addEventListener('click', close);
    /* 点击遮罩空白处关闭 */
    mask.addEventListener('click', function (e) { if (e.target === mask) close(); });
    /* ESC 关闭 */
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !mask.classList.contains('hidden')) close();
    });

    $('fb-ok').addEventListener('click', function () {
      /* 新窗口打开，不阻塞当前页面；noopener 提升安全性 */
      var w = window.open(FEEDBACK_URL, '_blank', 'noopener,noreferrer');
      if (!w) {
        /* 弹窗被拦截时给出可手动复制的提示 */
        ZKB.toast('浏览器拦截了新窗口，请手动打开：' + FEEDBACK_URL);
      }
      close();
    });
  }

  function bindUI() {
    /* 模式页签 */
    document.querySelectorAll('.mode-tab').forEach(function (t) {
      t.addEventListener('click', function () { setMode(t.getAttribute('data-mode')); });
    });

    bindFeedback();
    bindStageUI();
    if (ZKB.MatLib) ZKB.MatLib.init();
    bindAutosave();

    /* 运行 / 停止 */
    $('btn-run').addEventListener('click', doRun);
    $('btn-stop').addEventListener('click', doStop);
    ZKB.SimEngine.setOnHalt(function () {
      setRunningUI(false);
      status('程序已结束');
    });

    /* 代码抽屉 */
    $('btn-code').addEventListener('click', function () {
      var d = $('code-drawer');
      d.classList.toggle('closed');
      if (!d.classList.contains('closed')) { refreshCode(); }
      setTimeout(function () { Blockly.svgResize(ws); }, 280);
    });
    $('btn-drawer-close').addEventListener('click', function () {
      $('code-drawer').classList.add('closed');
      setTimeout(function () { Blockly.svgResize(ws); }, 280);
    });
    $('btn-copy-code').addEventListener('click', copyCode);
    $('btn-download-code').addEventListener('click', downloadPy);

    /* 「+拓展」按钮已移除，改由左下角工具条的「拓展库」统一入口 */
    var btnWire = $('btn-wire-lib');
    if (btnWire) btnWire.addEventListener('click', openWireLib);

    /* 拓展库（左下角按钮 + 模态框） */
    $('btn-ext-lib').addEventListener('click', openExtLib);
    $('btn-ext-back').addEventListener('click', closeExtLib);
    /* 点击弹窗外的空白区域（遮罩层）直接关闭拓展库弹窗
       （素材库遮罩点击关闭已在 matlib.js 中实现） */
    var extMask = document.getElementById('ext-lib-mask');
    if (extMask) {
      extMask.addEventListener('click', function (e) {
        if (e.target === extMask) closeExtLib();   /* 点在弹窗内部不关闭 */
      });
    }
    document.querySelectorAll('.ext-tab').forEach(function (t) {
      t.addEventListener('click', function () {
        document.querySelectorAll('.ext-tab').forEach(function (x) { x.classList.remove('active'); });
        t.classList.add('active');
        renderExtGrid(t.getAttribute('data-cat'), $('ext-search').value.trim());
      });
    });
    $('ext-search').addEventListener('input', function () {
      var active = document.querySelector('.ext-tab.active').getAttribute('data-cat');
      renderExtGrid(active, this.value.trim());
    });
    /* 第五十轮：悬停设备卡片 → 弹出详细介绍浮层 */
    $('ext-grid').addEventListener('mouseover', function (e) {
      var card = e.target.closest ? e.target.closest('[data-dev]') : null;
      if (!card || !ZKB.DeviceIntro) return;
      var id = card.getAttribute('data-dev');
      if (card._tipId === id) return;   /* 同一张卡片内移动不重复渲染 */
      card._tipId = id;
      ZKB.DeviceIntro.show(id, card);
    });
    /* 只在「整块网格移出」时收起。
       ⚠ 不要用 mouseout + relatedTarget 判断——在卡片内部的子元素之间移动时
       relatedTarget 有时是 null（合成事件 / 指针离开文档），
       会把刚弹出的浮层立刻收掉。 */
    $('ext-grid').addEventListener('mouseleave', function () {
      document.querySelectorAll('.ext-card').forEach(function (c) { c._tipId = ''; });
      if (ZKB.DeviceIntro) ZKB.DeviceIntro.hide();
    });

    $('ext-grid').addEventListener('click', function (e) {
      /* 先看是不是点了「▶ 视频介绍」——那样只开视频，不加设备 */
      var vbtn = e.target.closest ? e.target.closest('[data-video]') : null;
      if (vbtn) {
        e.preventDefault();
        e.stopPropagation();
        if (ZKB.DeviceIntro) ZKB.DeviceIntro.openVideo(vbtn.getAttribute('data-video'));
        return;
      }
      var el = e.target.closest('[data-add]');
      if (!el) return;
      var id = el.getAttribute('data-add');
      if (ZKB.SimBoard.hasDevice(id)) {
        ZKB.toast('该设备已添加');
      } else {
        ZKB.SimBoard.addDevice(id);
        /* 第三十四轮：加了拓展设备就提示先做硬件连接 */
        var needWire = !ZKB.WireLib || !ZKB.WireLib.requiresConnection ||
          ZKB.WireLib.requiresConnection(id);
        ZKB.toast(needWire
          ? ('已添加：' + ZKB.deviceMeta(id).name + ' —— 请到「硬件连接」中把它连到扩展板接口')
          : ('已添加：' + ZKB.deviceMeta(id).name));
        el.classList.add('added');
        el.querySelector('.add-tag') && (el.querySelector('.add-tag').textContent = '已添加');
      }
    });

    ZKB.onDevicesChanged = function (list) {
      rebuildToolbox();
      /* 硬件联动：虚拟仿真添加/移除设备后，同步舞台上的对应元素 */
      if (ZKB.Stage && ZKB.Stage.syncDevices) ZKB.Stage.syncDevices();
      if (running) return;
      status(list.length ? '已添加拓展：' + list.map(function (id) { return ZKB.deviceMeta(id).name; }).join('、') : '就绪');
    };

    /* 工程菜单 */
    $('btn-new').addEventListener('click', newProject);
    $('btn-save').addEventListener('click', saveProject);
    $('btn-open').addEventListener('click', function () { $('file-open').click(); });
    $('file-open').addEventListener('change', onOpenFile);

    /* 示例菜单 */
    var exMenu = $('examples-menu');
    exMenu.innerHTML = ZKB.EXAMPLES.map(function (ex, i) {
      return '<button type="button" class="menu-item" data-i="' + i + '" title="' + ex.desc + '">' + ex.name + '</button>';
    }).join('') + '<div class="menu-sep"></div>' +
      '<div class="menu-item" style="color:#6b7280;cursor:default">示例会载入所需拓展设备</div>';
    $('btn-examples').addEventListener('click', function (e) {
      e.stopPropagation();
      var open = exMenu.classList.contains('open');
      closeAllMenus();
      if (!open) exMenu.classList.add('open');
    });
    exMenu.addEventListener('click', function (e) {
      var item = e.target.closest('.menu-item');
      var idx = item ? parseInt(item.getAttribute('data-i'), 10) : NaN;
      closeAllMenus();
      if (isNaN(idx)) return; // 底部提示项
      loadExample(ZKB.EXAMPLES[idx]);
    });

    /* 教材示例菜单（第四十九轮） */
    renderTextbookMenu();
    var tbMenu = $('textbook-menu');
    $('btn-textbook').addEventListener('click', function (e) {
      e.stopPropagation();
      var open = tbMenu.classList.contains('open');
      closeAllMenus();
      if (!open) tbMenu.classList.contains('open') || tbMenu.classList.add('open');
    });
    tbMenu.addEventListener('click', function (e) {
      var item = e.target.closest('.menu-item');
      var key = item ? item.getAttribute('data-tb') : null;
      closeAllMenus();
      if (!key) return; // 底部提示项
      var parts = decodeURIComponent(key).split('|');
      var book = parts[0], unit = parts[1], act = parts[2];
      var grp = (ZKB.TEXTBOOK_GROUPS || []).filter(function (g) {
        return g.book === book && g.unit === unit;
      })[0];
      if (!grp) return;
      var it = grp.items.filter(function (x) { return x.act === act; })[0];
      if (!it) return;
      loadTextbookExample(it, book + ' · ' + unit);
    });

    /* 连接设备 */
    $('btn-connect').addEventListener('click', async function () {
      if (ZKB.SerialLink.isConnected()) {
        await ZKB.SerialLink.disconnect();
      } else {
        await ZKB.SerialLink.connect();
      }
    });

    /* 上传菜单 */
    var upMenu = $('upload-menu');
    $('btn-upload').addEventListener('click', function (e) {
      e.stopPropagation();
      var open = upMenu.classList.contains('open');
      closeAllMenus();
      if (!open) upMenu.classList.add('open');
    });
    upMenu.addEventListener('click', async function (e) {
      var item = e.target.closest('.menu-item');
      if (!item) return;
      closeAllMenus();
      var act = item.getAttribute('data-act');
      if (act === 'download-py') { downloadPy(); return; }
      var code = ZKB.genPython(ws);
      if (act === 'upload-run') {
        ZKB.log('准备上传 main.py 到掌控板…', 'log-hw');
        await ZKB.SerialLink.uploadAndRun(code);
      } else if (act === 'run-repl') {
        await ZKB.SerialLink.runOnce(code);
      }
    });

    /* 点击空白关闭菜单 */
    document.addEventListener('mousedown', function (e) {
      if (!e.target.closest('.menu-wrap')) closeAllMenus();
    });

    /* 控制台清空 */
    $('btn-clear-log').addEventListener('click', function () { $('console').innerHTML = ''; });

    /* —— 新建变量 / 列表 弹窗 —— */
    $('nd-cancel').addEventListener('click', function () { closeNameDialog(); });
    /* 第三十轮：变量管理面板的关闭 / 点遮罩关闭 */
    $('vm-close').addEventListener('click', function () { $('varmgr-mask').classList.add('hidden'); });
    $('varmgr-mask').addEventListener('click', function (e) {
      if (e.target === $('varmgr-mask')) $('varmgr-mask').classList.add('hidden');
    });
    $('nd-ok').addEventListener('click', confirmNameDialog);
    $('nd-input').addEventListener('keydown', function (e) {
      if (e.key === 'Enter') confirmNameDialog();
    });
    /* Esc 关闭：绑在 document 上而不是只绑输入框 ——
       第三十二轮实测发现，若焦点不在输入框（例如用户点了面板里的
       另一行、或点了弹窗空白处），按 Esc 完全没反应，弹窗卡住关不掉。
       只在最上层弹窗打开时才响应，避免误关下层。 */
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      if (!$('name-dialog-mask').classList.contains('hidden')) { closeNameDialog(); return; }
      if (!$('varmgr-mask').classList.contains('hidden')) {
        $('varmgr-mask').classList.add('hidden');
      }
    });

    /* —— 制作新的积木 弹窗 —— */
    document.querySelectorAll('.pd-opt').forEach(function (btn) {
      btn.addEventListener('click', function () { pdAdd(btn.getAttribute('data-add')); });
    });
    $('pd-trash').addEventListener('click', function () { pdItems = []; renderPdItems(); });
    $('pd-items').addEventListener('click', function (e) {
      var x = e.target.closest('.pd-x');
      if (!x) return;
      pdItems.splice(parseInt(x.getAttribute('data-del'), 10), 1);
      renderPdItems();
    });
    function closePd() { $('proc-dialog-mask').classList.add('hidden'); }
    $('pd-cancel').addEventListener('click', closePd);
    $('pd-close').addEventListener('click', closePd);
    $('pd-ok').addEventListener('click', confirmProc);
  }

})(window);
