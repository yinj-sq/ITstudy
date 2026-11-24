// Ketcher 3.18 上游只有英文界面；这里在编辑器同源 iframe 内做运行期中文映射。
// 仅翻译精确匹配的界面文案（工具栏 title、菜单、对话框、设置项），
// 不触碰画布 SVG 内的元素符号与用户输入内容。

const EXACT = {
  // 顶部与通用操作
  'Open...': '打开…',
  'Open…': '打开…',
  'Save as...': '另存为…',
  'Save As…': '另存为…',
  'Open structure': '打开结构',
  'Save Structure': '保存结构',
  'Clear Canvas': '清空画布',
  'Undo': '撤销',
  'Redo': '重做',
  'Copy': '复制',
  'Paste': '粘贴',
  'Cut': '剪切',
  'Delete': '删除',
  'Remove': '移除',
  'Cancel': '取消',
  'Save': '保存',
  'Apply': '应用',
  'Check': '检查',
  'Close': '关闭',
  'Reset': '重置',
  'Preview': '预览',
  'Save to Templates': '保存到模板',
  'File name:': '文件名：',
  'File format:': '文件格式：',
  'PASTE FROM CLIPBOARD': '从剪贴板粘贴',
  'or drag file here': '或拖拽文件到此处',
  'OPEN FROM FILE': '从文件打开',
  'Image Recognition service is not available': '图像识别服务不可用',

  // 工具栏
  'Hand Tool': '抓手工具',
  'Hand tool': '抓手工具',
  'Select Rectangle': '框选',
  'Rectangle Selection': '框选',
  'Erase': '橡皮擦',
  'Single Bond': '单键',
  'Chain': '链',
  'Stereochemistry': '立体化学',
  'Charge Plus': '正电荷',
  'Charge Minus': '负电荷',
  'S-Group': 'S-基团',
  'R-Group Label Tool': 'R-基团标签',
  'Create a monomer': '创建单体',
  'Reaction Plus Tool': '反应加号工具',
  'Arrow Open Angle Tool': '反应箭头工具',
  'Reaction Mapping Tool': '反应映射工具',
  'Shape Ellipse': '椭圆',
  'Add text': '添加文本',
  'Add Image': '添加图片',
  'Structure Library': '结构库',
  'Periodic Table': '元素周期表',
  'Any atom': '任意原子',
  'Extended Table': '扩展元素表',
  'Aromatize': '芳构化',
  'Dearomatize': '去芳构化',
  'Layout': '布局',
  'Clean Up': '清理',
  'Calculate CIP': '计算 CIP',
  'Check Structure': '检查结构',
  'Calculated Values': '计算值',
  'Add/Remove explicit hydrogens': '添加/移除显式氢',
  '3D Viewer': '3D 查看器',
  'Settings': '设置',
  'Help': '帮助',
  'About': '关于',
  'Fullscreen mode': '全屏',
  'Create Antisense Strand': '创建反义链',
  'Calculate properties': '计算属性',
  'Switch to sequence layout mode': '切换到序列布局',
  'Number of monomers in a line': '每行单体数',
  'Hide library': '隐藏库',
  'Favorites': '收藏',
  'Presets': '预设',
  'Sugars': '糖',
  'Bases': '碱基',
  'Phosphates': '磷酸',
  'Nucleotides': '核苷酸',
  'Peptides': '肽',

  // 元素与环模板
  'Hydrogen': '氢',
  'Carbon': '碳',
  'Nitrogen': '氮',
  'Oxygen': '氧',
  'Sulfur': '硫',
  'Phosphorus': '磷',
  'Fluorine': '氟',
  'Chlorine': '氯',
  'Bromine': '溴',
  'Iodine': '碘',
  'Benzene': '苯环',
  'Cyclopentadiene': '环戊二烯',
  'Cyclohexane': '环己烷',
  'Cyclopentane': '环戊烷',
  'Cyclopropane': '环丙烷',
  'Cyclobutane': '环丁烷',
  'Cycloheptane': '环庚烷',
  'Cyclooctane': '环辛烷',

  // 右键菜单
  'Edit...': '编辑…',
  'Edit…': '编辑…',
  'Single': '单键',
  'Single Up': '单键向上',
  'Single Down': '单键向下',
  'Single Up/Down': '单键上下',
  'Double': '双键',
  'Double Cis/Trans': '双键顺反',
  'Triple': '三键',
  'Dative': '配位键',
  'Query bonds': '查询键',
  'Any': '任意',
  'Aromatic': '芳香',
  'Single/Double': '单键/双键',
  'Single/Aromatic': '单键/芳香',
  'Double/Aromatic': '双键/芳香',
  'Attach S-Group...': '附加 S-基团…',
  'Highlight': '高亮',
  'No highlight': '无高亮',

  // 计算值
  'Chemical Formula:': '化学式：',
  'Molecular Weight:': '分子量：',
  'Decimal places': '小数位数',
  'Exact Mass:': '精确质量：',
  'Elemental Analysis:': '元素分析：',

  // 结构检查
  'Valence': '价态',
  'Radical': '自由基',
  'Pseudoatom': '伪原子',
  'Query': '查询',
  'Overlapping Atoms': '重叠原子',
  'Overlapping Bonds': '重叠键',
  'R-Groups': 'R-基团',
  'Chirality': '手性',
  '3D Structure': '3D 结构',
  'Chiral flag': '手性标记',
  'No errors detected': '未检测到错误',

  // 3D 查看器
  'COMPONENT EDIT MODE': '组件编辑模式',
  'Stereocenters can be changed after the strong 3D rotation':
    '强 3D 旋转后可修改立体中心',

  // 设置
  'General': '常规',
  'Reset to Select Tool': '重置为选择工具',
  'After Paste': '粘贴后',
  'Rotation Step, º': '旋转步长，º',
  'Show valence warnings': '显示价态警告',
  'Atom coloring': '原子着色',
  'Font': '字体',
  'Font size': '字号',
  'Sub font size': '下标字号',
  'Reaction component margin size': '反应组分边距',
  'Image resolution': '图像分辨率',
  'low': '低',
  'Show the Stereo flags': '显示立体标记',
  'Label display at stereogenic centers': '立体中心标签显示',
  'IUPAC style': 'IUPAC 风格',
  'Absolute Center color': '绝对中心颜色',
  'AND Centers color': 'AND 中心颜色',
  'OR Centers color': 'OR 中心颜色',
  'Color stereogenic centers': '为立体中心着色',
  'Labels Only': '仅标签',
  'Auto fade And/Or center labels': '自动淡化 AND/OR 中心标签',
  'Text of Absolute flag': '绝对标记文字',
  'Text of AND flag': 'AND 标记文字',
  'Text of OR flag': 'OR 标记文字',
  'Text of Mixed flag': '混合标记文字',
  'Ignore the chiral flag': '忽略手性标记',
  'Atoms': '原子',
  'Display carbon explicitly': '显式显示碳',
  'Display charge': '显示电荷',
  'Display valence': '显示价态',
  'Show hydrogen labels': '显示氢标签',
  'Terminal and Hetero': '末端与杂原子',
  'Bonds': '键',
  'Aromatic Bonds as circle': '芳香键显示为圆圈',
  'Bond length': '键长',
  'Bond spacing': '键间距',
  'Bond thickness': '键粗细',
  'Stereo (Wedge) bond width': '立体（楔形）键宽',
  'Hash spacing': '虚线间距',
  'Server': '服务器',
  'Smart-layout': '智能布局',
  'Ignore stereochemistry errors': '忽略立体化学错误',
  'Ignore pseudoatoms at mass': '质量计算忽略伪原子',
  'Add Rsites at mass calculation': '质量计算加入 R 位点',
  'Add Isotopes at mass calculation': '质量计算加入同位素',
  'Valence mode': '价态模式',
  'Default': '默认',
  'Display mode': '显示模式',
  'Lines': '线框',
  'Background color': '背景颜色',
  'Light': '浅色',
  'Label coloring': '标签着色',
  'Bright': '明亮',
  'Options for Debugging': '调试选项',
  'Show atom Ids': '显示原子 ID',
  'Show bonds Ids': '显示键 ID',
  'Show half bonds Ids': '显示半键 ID',
  'Show loop Ids': '显示环 ID',
  'Set ACS Settings': '设置 ACS 参数',
};

const ATTRIBUTES = ['title', 'aria-label', 'placeholder'];
const SKIP_TAGS = new Set([
  'SCRIPT', 'STYLE', 'TEXTAREA', 'INPUT', 'CODE', 'PRE', 'OPTION',
]);
const pendingRoots = new Set();
let rafId = 0;

function normalize(raw) {
  return String(raw || '').replace(/ /g, ' ');
}

function translateValue(raw) {
  const value = normalize(raw);
  const key = value.trim();
  if (!key) return null;
  if (EXACT[key]) return value.replace(key, EXACT[key]);
  const shortcut = key.match(/^(.*?)(\s+\([^()]*\))$/);
  if (shortcut && EXACT[shortcut[1]]) {
    return value.replace(key, EXACT[shortcut[1]] + shortcut[2]);
  }
  return null;
}

function translateAttributes(el) {
  if (!el || el.nodeType !== 1) return;
  ATTRIBUTES.forEach((attr) => {
    const raw = el.getAttribute(attr);
    if (!raw) return;
    const zh = translateValue(raw);
    if (zh && zh !== raw) el.setAttribute(attr, zh);
  });
}

function translateTextNode(node) {
  if (!node || node.nodeType !== 3) return;
  const parent = node.parentElement;
  if (!parent || SKIP_TAGS.has(parent.tagName)) return;
  if (parent.isContentEditable || parent.closest('svg, [contenteditable="true"]')) return;
  const raw = normalize(node.nodeValue);
  if (!raw || !raw.trim()) return;
  const key = raw.trim();
  const zh = EXACT[key];
  if (!zh) return;
  const start = raw.indexOf(key);
  node.nodeValue = raw.slice(0, start) + zh + raw.slice(start + key.length);
}

function processRoot(root) {
  if (!root || root.nodeType !== 1 || !root.isConnected) return;
  translateAttributes(root);
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node = walker.nextNode();
  while (node) {
    translateTextNode(node);
    node = walker.nextNode();
  }
  root.querySelectorAll('[title], [aria-label], [placeholder]').forEach(translateAttributes);
}

function flush() {
  rafId = 0;
  const roots = Array.from(pendingRoots);
  pendingRoots.clear();
  roots.forEach(processRoot);
}

function schedule(root) {
  const el = root && root.nodeType === 1 ? root : root && root.parentElement;
  if (!el) return;
  pendingRoots.add(el);
  if (!rafId) rafId = requestAnimationFrame(flush);
}

function observe() {
  processRoot(document.body);
  const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      if (mutation.type === 'attributes') {
        translateAttributes(mutation.target);
      } else if (mutation.type === 'characterData') {
        schedule(mutation.target.parentElement);
      } else {
        mutation.addedNodes.forEach((node) => {
          if (node.nodeType === 1) schedule(node);
          else if (node.nodeType === 3) schedule(node.parentElement);
        });
      }
    });
  });
  observer.observe(document.body, {
    subtree: true,
    childList: true,
    characterData: true,
    attributes: true,
    attributeFilter: ATTRIBUTES,
  });
  // 部分弹层/提示在点击后才挂载；点击/切换后补扫，确保新弹层被翻译
  const rescan = () => setTimeout(() => processRoot(document.body), 150);
  document.addEventListener('click', rescan, true);
  document.addEventListener('change', rescan, true);
  // 初始化后延迟挂载的提示再补扫两次
  setTimeout(() => processRoot(document.body), 1200);
  setTimeout(() => processRoot(document.body), 3500);
}

if (document.body) observe();
else document.addEventListener('DOMContentLoaded', observe);

window.__ketcherI18n = { exact: EXACT, translate: () => processRoot(document.body) };
