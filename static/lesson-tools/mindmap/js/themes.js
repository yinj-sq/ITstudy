/* ============================================================
   themes.js — 配色主题、节点尺寸、课堂模板
   ============================================================ */

/* 每层节点的排版参数 */
const NODE_STYLE = [
  { size: 20, weight: 700, padX: 22, padY: 15, maxW: 300, minW: 96, radius: 14, shadow: true },
  { size: 16, weight: 600, padX: 17, padY: 11, maxW: 250, minW: 72, radius: 11, shadow: true },
  { size: 14, weight: 500, padX: 14, padY: 9,  maxW: 230, minW: 56, radius: 9,  shadow: false },
  { size: 13.5, weight: 400, padX: 13, padY: 8, maxW: 220, minW: 50, radius: 8, shadow: false },
];

const THEMES = {
  paper: {
    /* 米黄护眼纸。这不是"把画布调暖"一个值的事，三件事必须一起做：
       ① 画布从冷白 #f7f8fa（相对亮度 .96）换成米黄 #f5eede（.86）——
          大面积高亮度才是"刺眼"的主因，色相只是次要因素；
       ② 节点底不能再用纯白。纯白落在米黄上只亮 1.16，会变成一块块发光的纸片，
          比底色更晃眼。改成奶白 #fffdf7 / 米白 #fdf9ee，只比画布亮 1.14 / 1.10，
          层次交给边框（÷画布 1.33 / 1.37）而不是亮度差；
       ③ 网格点与连线从冷灰换暖褐。冷灰线落在米黄纸上会显脏，这一条最容易被忽略。
       L1 保留淡靛，与米黄形成便签感；根节点压深到 #4f4fca，白字对比 6.36。 */
    name: '素纸', swatch: '#e8d9b8',
    canvas: '#f5eede', dot: 'rgba(146,124,86,.20)', line: '#c8b795',
    levels: [
      { bg: '#4f4fca', fg: '#ffffff', border: 'transparent', shadow: '0 6px 18px -6px rgba(70,70,180,.55)' },
      { bg: '#ebe8f8', fg: '#3a3a95', border: '#d5cfeb', shadow: '0 2px 6px -2px rgba(58,58,149,.14)' },
      { bg: '#fffdf7', fg: '#2b3040', border: '#dbd0b4', shadow: '0 1px 2px rgba(120,100,60,.07)' },
      { bg: '#fdf9ee', fg: '#4a5163', border: '#d8cdb0', shadow: '0 1px 2px rgba(120,100,60,.05)' },
    ],
  },
  chalk: {
    /* 重做过的一版。旧版三个问题叠在一起：
       ① 根节点是霓虹薄荷绿 #34d399 + 绿色辉光，在暗底上是一块发光体，视线被它钉住；
       ② L2/L3 底色 #1d2c24 与画布 #1b2620 只差 1.07，节点只能靠 1.43 的边框硬撑边界；
       ③ 画布、文字、连线全是同一个绿色相，大面积单一色相会快速视觉疲劳。
       新版：画布改中性深灰绿，节点用"面比画布亮一档"分层，文字改暖白，
       根节点换粉笔黄（黑板上最经典的强调色）并去掉辉光，只留暗投影。 */
    name: '黑板', swatch: '#e9c46a',
    canvas: '#1f2724', dot: 'rgba(255,255,255,.07)', line: '#6b8a78',
    levels: [
      { bg: '#e9c46a', fg: '#241d0d', border: 'transparent', shadow: '0 4px 16px -6px rgba(0,0,0,.55)' },
      { bg: '#38453f', fg: '#e8f0eb', border: '#4d5f56', shadow: 'none' },
      { bg: '#313d38', fg: '#d6e2db', border: '#44554d', shadow: 'none' },
      { bg: '#313d38', fg: '#bccac2', border: '#44554d', shadow: 'none' },
    ],
  },
  sunset: {
    name: '暖阳', swatch: '#ea580c',
    canvas: '#fff8f3', dot: 'rgba(200,140,90,.2)', line: '#e0bc9d',
    levels: [
      { bg: '#ea580c', fg: '#ffffff', border: 'transparent', shadow: '0 6px 18px -6px rgba(234,88,12,.55)' },
      { bg: '#ffeadb', fg: '#92400e', border: '#fbd9bf', shadow: '0 2px 6px -2px rgba(146,64,14,.14)' },
      { bg: '#ffffff', fg: '#3f2a1c', border: '#f2ddc9', shadow: '0 1px 2px rgba(120,70,30,.06)' },
      { bg: '#ffffff', fg: '#6b4f3a', border: '#ecddcf', shadow: 'none' },
    ],
  },
  ocean: {
    name: '深海', swatch: '#0284c7',
    canvas: '#f3f9fd', dot: 'rgba(90,150,190,.2)', line: '#a8cde4',
    levels: [
      { bg: '#0284c7', fg: '#ffffff', border: 'transparent', shadow: '0 6px 18px -6px rgba(2,132,199,.55)' },
      { bg: '#e0f2fe', fg: '#075985', border: '#c3e6f9', shadow: '0 2px 6px -2px rgba(7,89,133,.14)' },
      { bg: '#ffffff', fg: '#12303f', border: '#d0e1eb', shadow: '0 1px 2px rgba(16,24,40,.05)' },
      { bg: '#ffffff', fg: '#3d5b6b', border: '#d4dfe7', shadow: 'none' },
    ],
  },
  forest: {
    name: '青竹', swatch: '#16a34a',
    canvas: '#f5faf6', dot: 'rgba(90,160,110,.2)', line: '#a5cbb2',
    levels: [
      { bg: '#16a34a', fg: '#ffffff', border: 'transparent', shadow: '0 6px 18px -6px rgba(22,163,74,.55)' },
      { bg: '#dcfce7', fg: '#147239', border: '#bee9ce', shadow: '0 2px 6px -2px rgba(21,128,61,.14)' },
      { bg: '#ffffff', fg: '#17301f', border: '#cfe4d7', shadow: '0 1px 2px rgba(16,24,40,.05)' },
      { bg: '#ffffff', fg: '#3f5a49', border: '#d4e2d9', shadow: 'none' },
    ],
  },
  mono: {
    name: '墨白', swatch: '#111827',
    canvas: '#ffffff', dot: 'rgba(0,0,0,.1)', line: '#b9bdc7',
    levels: [
      { bg: '#111827', fg: '#ffffff', border: 'transparent', shadow: '0 6px 18px -8px rgba(17,24,39,.5)' },
      { bg: '#f2f3f5', fg: '#111827', border: '#dcdfe5', shadow: 'none' },
      { bg: '#ffffff', fg: '#1f2430', border: '#d5d8de', shadow: 'none' },
      { bg: '#ffffff', fg: '#4b5162', border: '#e2e5ea', shadow: 'none' },
    ],
  },
};

/* 结构类型 */
const LAYOUTS = [
  {
    key: 'logical', name: '左右分支', desc: '从左往右一层层展开',
    icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="2.5" y="9.5" width="5" height="5" rx="1.5"/><rect x="16" y="3" width="5.5" height="4.6" rx="1.4"/><rect x="16" y="16.4" width="5.5" height="4.6" rx="1.4"/><path d="M7.5 12h3.6V5.3H16M11.1 12v6.7H16"/></svg>',
  },
  {
    key: 'mindmap', name: '中心发散', desc: '中心在中间，两边都长',
    icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="9" y="9.4" width="6" height="5.2" rx="1.5"/><rect x="2" y="3" width="5" height="4.4" rx="1.3"/><rect x="2" y="16.6" width="5" height="4.4" rx="1.3"/><rect x="17" y="3" width="5" height="4.4" rx="1.3"/><rect x="17" y="16.6" width="5" height="4.4" rx="1.3"/><path d="M9 12H7V5.2H7M9 12H7v6.8M15 12h2V5.2M15 12h2v6.8"/></svg>',
  },
  {
    key: 'org', name: '上下分层', desc: '上面是上级，下面是下级',
    icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="9" y="2.6" width="6" height="4.4" rx="1.3"/><rect x="2.4" y="16.8" width="5.2" height="4.4" rx="1.3"/><rect x="9.4" y="16.8" width="5.2" height="4.4" rx="1.3"/><rect x="16.4" y="16.8" width="5.2" height="4.4" rx="1.3"/><path d="M12 7v4.5M5 16.8V11.5h14v5.3M12 11.5v5.3"/></svg>',
  },
  {
    key: 'timeline', name: '时间轴', desc: '按时间先后排',
    icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M4.5 3.4v17.2" stroke-linecap="round"/><circle cx="4.5" cy="6.4" r="1.5"/><circle cx="4.5" cy="12" r="1.5"/><circle cx="4.5" cy="17.6" r="1.5"/><rect x="9.4" y="4.2" width="10" height="4.4" rx="1.3"/><rect x="9.4" y="9.8" width="10" height="4.4" rx="1.3"/><rect x="9.4" y="15.4" width="10" height="4.4" rx="1.3"/></svg>',
  },
  {
    key: 'fishbone', name: '鱼骨', desc: '主干是问题，刺是原因',
    icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M2 12h14.5"/><path d="M6 12l3.4-5M6 12l3.4 5M11.4 12l3.4-5M11.4 12l3.4 5"/><rect x="16.6" y="9.2" width="5.4" height="5.6" rx="1.5"/></svg>',
  },
  {
    key: 'ring', name: '环形', desc: '中心一个圈，外面一圈',
    icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="3.2"/><circle cx="12" cy="3.4" r="1.5"/><circle cx="19.4" cy="7.6" r="1.5"/><circle cx="19.4" cy="16.4" r="1.5"/><circle cx="12" cy="20.6" r="1.5"/><circle cx="4.6" cy="16.4" r="1.5"/><circle cx="4.6" cy="7.6" r="1.5"/></svg>',
  },
  {
    key: 'double', name: '双中心', desc: '左右各一个，中间比异同',
    icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="3.8" cy="12" r="2.4"/><circle cx="20.2" cy="12" r="2.4"/><circle cx="12" cy="6.6" r="1.6"/><circle cx="12" cy="17.4" r="1.6"/><path d="M6.4 12h3.4M14.2 12h3.4" stroke-linecap="round"/></svg>',
  },
  {
    key: 'multiflow', name: '因果流', desc: '左边原因，右边结果',
    icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><rect x="1.8" y="9.4" width="4.6" height="5.2" rx="1.2"/><rect x="9.6" y="7.8" width="4.8" height="8.4" rx="1.4"/><rect x="17.6" y="9.4" width="4.6" height="5.2" rx="1.2"/><path d="M6.6 12h2.8M14.6 12h2.8"/></svg>',
  },
];

/* 课堂模板 */
const TEMPLATES = {
  summary: {
    name: '课堂总结', desc: '结课前 5 分钟梳理',
    tree: {
      text: '本节课总结',
      children: [
        { text: '核心知识点', children: [{ text: '知识点一' }, { text: '知识点二' }, { text: '知识点三' }] },
        { text: '重点', children: [{ text: '必须掌握' }] },
        { text: '难点', children: [{ text: '容易卡住的地方' }] },
        { text: '易错点', children: [{ text: '常见错误' }, { text: '纠正方法' }] },
        { text: '方法归纳', children: [{ text: '解题思路' }] },
        { text: '课后作业', children: [{ text: '必做' }, { text: '选做' }] },
      ],
    },
  },
  unit: {
    name: '单元知识树', desc: '概念 · 规律 · 例题',
    tree: {
      text: '单元知识梳理',
      children: [
        { text: '基本概念', children: [{ text: '定义' }, { text: '性质' }] },
        { text: '公式与规律', children: [{ text: '公式一' }] },
        { text: '典型例题', children: [{ text: '例题 1' }] },
        { text: '易混辨析', children: [{ text: '对比项' }] },
      ],
    },
  },
  review: {
    name: '习题讲评', desc: '错因 · 思路 · 变式',
    tree: {
      text: '习题讲评',
      children: [
        { text: '考查目标' },
        { text: '解题思路', children: [{ text: '第 1 步' }, { text: '第 2 步' }] },
        { text: '典型错误', children: [{ text: '错因分析' }] },
        { text: '变式训练' },
        { text: '方法提炼' },
      ],
    },
  },
  blank: { name: '空白画布', desc: '从中心主题开始', tree: { text: '中心主题', children: [] } },
};
