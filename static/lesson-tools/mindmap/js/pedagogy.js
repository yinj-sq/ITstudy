/* ============================================================
   pedagogy.js — 思维图型 / 结构评分 / 课堂节奏 / 元认知提示
   ============================================================ */

/* ── 八种 Thinking Maps：按「思维动作」选图型，而不是按「好看」选 ── */
const THINKING_MAPS = {
  circle: {
    name: '圆圈图', ask: '想不出更多点子', action: '发散', layout: 'ring',
    desc: '中心概念 + 外圈联想',
    tip: '先不管对错，把能想到的全写下来；写完再圈出最关键的三个。',
    tree: {
      text: '中心概念',
      children: [
        { text: '联想 1' }, { text: '联想 2' }, { text: '联想 3' },
        { text: '联想 4' }, { text: '联想 5' }, { text: '联想 6' },
      ],
    },
  },
  bubble: {
    name: '气泡图', ask: '说不清它是什么样', action: '描述', layout: 'ring',
    desc: '用形容词描述一个事物',
    tip: '每个气泡只能放「性质」——颜色、大小、气味、感受，不要放例子。',
    tree: {
      text: '要描述的事物',
      children: [
        { text: '特征 1' }, { text: '特征 2' }, { text: '特征 3' },
        { text: '特征 4' }, { text: '特征 5' }, { text: '特征 6' },
      ],
    },
  },
  double: {
    name: '双气泡图', ask: '要比较两个东西', action: '比较', layout: 'double',
    desc: '两个事物比异同',
    tip: '两侧只放各自独有的，中间只放共同点。共同点写不出来，说明比较还没做完。',
    tree: {
      text: '比较：A 与 B',
      children: [
        { text: 'A', children: [{ text: 'A 独有 1' }, { text: 'A 独有 2' }] },
        { text: 'B', children: [{ text: 'B 独有 1' }, { text: 'B 独有 2' }] },
        { text: '共同点', children: [{ text: '相同 1' }, { text: '相同 2' }] },
      ],
    },
  },
  tree: {
    name: '树形图', ask: '要把一堆东西归类', action: '分类', layout: 'logical',
    desc: '按同一标准归类',
    tip: '一次只用一条分类标准。标准换了，要另起一张图。',
    tree: {
      text: '分类对象',
      children: [
        { text: '类别 A', children: [{ text: '成员 1' }, { text: '成员 2' }] },
        { text: '类别 B', children: [{ text: '成员 1' }, { text: '成员 2' }] },
        { text: '类别 C', children: [{ text: '成员 1' }] },
      ],
    },
  },
  brace: {
    name: '括号图', ask: '要把整体拆成部分', action: '分解', layout: 'logical',
    desc: '整体拆成部分',
    tip: '括号图管「组成」，树形图管「归类」——整体拆完各部分加起来要等于整体。',
    tree: {
      text: '整体',
      children: [
        { text: '部分一', children: [{ text: '组成 1' }, { text: '组成 2' }] },
        { text: '部分二', children: [{ text: '组成 1' }] },
        { text: '部分三', children: [{ text: '组成 1' }] },
      ],
    },
  },
  flow: {
    name: '流程图', ask: '要理清先后顺序', action: '排序', layout: 'timeline',
    desc: '按先后顺序排步骤',
    tip: '每一步只写一个动作。如果一步里有两个动词，就该拆成两步。',
    tree: {
      text: '过程名称',
      children: [
        { text: '第 1 步', children: [{ text: '要点' }] },
        { text: '第 2 步', children: [{ text: '要点' }] },
        { text: '第 3 步', children: [{ text: '要点' }] },
        { text: '第 4 步', children: [{ text: '要点' }] },
      ],
    },
  },
  multiflow: {
    name: '复流程图', ask: '要找出原因和结果', action: '因果', layout: 'multiflow',
    desc: '左边原因，右边结果',
    tip: '原因和结果要能一一对上；对不上的，多半是想当然了。',
    tree: {
      text: '事件',
      children: [
        { text: '原因 1' }, { text: '原因 2' }, { text: '原因 3' },
        { text: '结果 1', grp: 'effect' }, { text: '结果 2', grp: 'effect' }, { text: '结果 3', grp: 'effect' },
      ],
    },
  },
  bridge: {
    name: '桥形图', ask: '要找出相似的对应关系', action: '类比', layout: 'mindmap',
    desc: 'A 之于 B，如同 C 之于 D',
    tip: '先写清「关系词」（如：是……的工具），再看每一对是否都符合它。',
    tree: {
      text: '类比关系：___ 之于 ___',
      children: [
        { text: '甲 : 乙', children: [{ text: '甲' }, { text: '乙' }] },
        { text: '丙 : 丁', children: [{ text: '丙' }, { text: '丁' }] },
        { text: '戊 : 己', children: [{ text: '戊' }, { text: '己' }] },
      ],
    },
  },
};

/* ── 课堂节奏脚本 ── */
const PACER_PRESETS = {
  closing10: {
    name: '结课 10 分钟',
    phases: [
      { name: '回忆', sec: 120, prompt: '合上书，先说出这节课的 3 个关键词。' },
      { name: '梳理', sec: 300, prompt: '把关键词挂到中心主题上，先搭骨架，再补细节。' },
      { name: '展示', sec: 180, prompt: '讲的时候先说结构，再说内容。' },
      { name: '自评', sec: 120, prompt: '合上导图，你能复述几条主线？' },
    ],
  },
  lesson40: {
    name: '完整一课时',
    phases: [
      { name: '导入', sec: 300, prompt: '这节课要解决什么问题？先写在中心。' },
      { name: '新授', sec: 1200, prompt: '每讲完一块，回头看看它在整张图里的位置。' },
      { name: '梳理', sec: 420, prompt: '把黑板上的内容压缩成一张图，删掉可有可无的。' },
      { name: '展示', sec: 300, prompt: '请一位同学用导图讲一遍，其他人补充。' },
      { name: '自评', sec: 180, prompt: '哪一条你最没把握？圈出来。' },
    ],
  },
  review15: {
    name: '习题讲评 15 分钟',
    phases: [
      { name: '看错', sec: 180, prompt: '先别改答案，说出错在哪一步。' },
      { name: '归因', sec: 420, prompt: '把错因归到分支上：概念不清、审题、计算、还是表达？' },
      { name: '变式', sec: 300, prompt: '换一个条件，结论还成立吗？' },
    ],
  },
};

/* ── 元认知提示卡（计划 → 监控 → 评价） ── */
const PROMPTS = [
  { stage: '计划', text: '这节课的核心问题是什么？用一句话写下来。' },
  { stage: '计划', text: '我打算分几个分支？先想好再动手，别边想边加。' },
  { stage: '计划', text: '哪些是必须记住的，哪些只要理解就行？' },
  { stage: '监控', text: '我卡在哪里？是没听懂，还是没想起来？' },
  { stage: '监控', text: '这个分支还能再往下拆吗？拆到不能再拆为止。' },
  { stage: '监控', text: '有没有两个分支其实是一回事？该合并了。' },
  { stage: '监控', text: '有没有哪两个分支之间存在因果或对比？连一条跨分支关系。' },
  { stage: '评价', text: '合上导图，你能复述几条主线？' },
  { stage: '评价', text: '如果只能用 5 个词概括这张图，是哪 5 个？' },
  { stage: '评价', text: '换我来教别人，我会从哪个分支讲起？' },
];

/* ── 概念图结构评分（Novak 评分法的可计算版本） ── */
const Scorer = (() => {
  function analyze() {
    const root = Store.root;
    const rows = [];
    Store.walk((n, d, p) => rows.push({ n, d, p }));

    const total = rows.length;
    const texts = rows.map(r => (r.n.text || '').trim());
    const filled = texts.filter(Boolean);
    const empty = texts.length - filled.length;
    const maxDepth = rows.reduce((m, r) => Math.max(m, r.d), 0);
    const leaves = rows.filter(r => !r.n.children.length).length;
    const branches = root.children.length;
    /* 命题：父子两端都写了字的边 */
    const prop = rows.filter(r => r.p && (r.n.text || '').trim() && (r.p.text || '').trim()).length;
    const cross = Store.links.length;
    const avgLen = filled.length ? filled.reduce((a, t) => a + t.length, 0) / filled.length : 0;

    /* ── 两条口径修正，都是为了别把学生引向"多写就高分" ──
       ① 末端例子改成边际递减。原来「例子 ×1」是线性的，实测「1 个分支挂 30 个例子」
          拿 71 分，「5 个分支各 2 层」只有 35 分——学生在课堂里会立刻学会刷数量。
          前 8 个仍然每个 1 分（具体化确实有价值），之后每个 0.25 分，
          因为第 20 个例子多半只是在同一个分支里重复。
       ② 加「平衡」维度：最大分支占总节点的比例。比例过高说明图退化成一根竖条，
          这不是概念图，是一份加了缩进的清单。 */
    const countSub = n => (n.children || []).reduce((a, c) => a + countSub(c), 1);
    const biggest = root.children.length ? Math.max(...root.children.map(countSub)) : 0;
    const concentration = total ? biggest / total : 0;
    const leafScore = Math.min(leaves, 8) + Math.max(0, leaves - 8) * 0.25;

    const score = Math.round(prop + maxDepth * 5 + cross * 10 + leafScore);
    const bar = v => Math.max(0, Math.min(100, Math.round(v)));

    /* 维度名就是界面上显示的名字，这里定死，别处不要再起别名。
       「跨分支」曾经在三处叫三个名字：维度条叫「连接」、数字行叫「跨分支」、
       帮助里叫「关系边」，教材里还叫「交叉连接」——同一个东西五个称呼，
       学生看到「连接 0 条」不知道说的是哪个东西。现在统一成「跨分支」，
       「交叉连接」只作为教材别名出现在弹窗注释的括号里。
       命名规范见 naming-audit.js N7。 */
    const dims = [
      { key: '广度', v: bar((branches / 5) * 100), hint: branches + ' 个主分支' },
      { key: '深度', v: bar((maxDepth / 3) * 100), hint: (maxDepth + 1) + ' 层' },
      { key: '跨分支', v: bar((cross / 3) * 100), hint: cross + ' 条' },
      { key: '具体', v: bar((leaves / Math.max(4, total * 0.45)) * 100), hint: leaves + ' 个末端例子' },
      {
        key: '平衡', v: bar(concentration <= 0.4 ? 100 : 100 - (concentration - 0.4) * 160),
        hint: branches > 1 ? '最大分支占 ' + Math.round(concentration * 100) + '%' : '只有一条主线',
      },
      {
        key: '精炼', v: bar(avgLen <= 8 ? 100 : 100 - (avgLen - 8) * 9),
        hint: filled.length ? avgLen.toFixed(1) + ' 字 / 节点' : '—',
      },
    ];
    const maturity = Math.round(dims.reduce((a, d) => a + d.v, 0) / dims.length);

    const tips = [];
    if (maxDepth < 2) tips.push({ k: '深度', t: '只有 ' + (maxDepth + 1) + ' 层。挑一个主分支再往下拆一层——概念图至少三级才看得出结构。' });
    if (cross === 0) tips.push({ k: '跨分支', t: '还没有跨分支关系。选中一个节点，按住 Shift 点另一个节点，把「因为 / 对比 / 举例」连出来。' });
    if (branches === 1) {
      tips.push({ k: '结构', t: '只有一个主分支，这更像一份提纲，不是概念图。把内容按 4–6 个方面重新分组，再看哪些组之间有关系。' });
    } else if (concentration > 0.6) {
      tips.push({ k: '平衡', t: '有 ' + Math.round(concentration * 100) + '% 的内容堆在同一个分支下。力气该花在「分出几条主线」，而不是把一条写长。' });
    } else if (branches < 3) {
      tips.push({ k: '广度', t: '只有 ' + branches + ' 个主分支，一节课的骨架通常需要 4–6 个。' });
    }
    if (empty > 0) tips.push({ k: '完整', t: '有 ' + empty + ' 个节点还是空的，先补上或删掉。' });
    if (avgLen > 9) tips.push({ k: '精炼', t: '节点平均 ' + avgLen.toFixed(1) + ' 个字。投影时后排看不清，压到 8 字以内，细节放到下一级。' });
    if (!tips.length) tips.push({ k: '不错', t: '层级、跨分支、文字密度都到位了。下一步合上图复述一遍，检验是不是真记住了。' });

    return { score, maturity, prop, maxDepth, cross, leaves, branches, total, empty, avgLen, dims, tips, concentration, leafScore };
  }

  return { analyze };
})();
