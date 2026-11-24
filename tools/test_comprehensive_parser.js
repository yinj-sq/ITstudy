/* 综合题识别预览工具 — 解析器自测（node 直接运行）
 * 用法：node tools/test_comprehensive_parser.js
 * 说明：从 comprehensive_import_preview.html 提取 <script> 内容，
 *       用 vm 沙箱加载（DOM 操作在 DOMContentLoaded 回调内，顶层安全），
 *       然后调用 parseAll 验证识别规则。 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const html = fs.readFileSync(
  path.join(__dirname, 'comprehensive_import_preview.html'), 'utf-8');
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m) { console.error('未找到 <script> 内容'); process.exit(1); }

const sandbox = {
  console,
  window: {},
  document: { addEventListener() {} },  // DOM 部分回调不执行，只取纯函数
};
vm.createContext(sandbox);
vm.runInContext(m[1], sandbox);
const parseAll = vm.runInContext('parseAll', sandbox);

let passed = 0, failed = 0;
function eq(name, actual, expected) {
  const a = JSON.stringify(actual), e = JSON.stringify(expected);
  if (a === e) { passed++; console.log('  ✓ ' + name); }
  else { failed++; console.log('  ✗ ' + name + '\n    期望: ' + e + '\n    实际: ' + a); }
}

/* ── 用例 1：单选/单选/填空 + 判断 ── */
const t1 = `【第1题】阅读以下程序，回答问题。
程序输入一个正整数 n，输出其阶乘。
（1）下列哪个语句能实现累乘？
A. s = s * i
B. s = s + i
C. s = i / s
D. s = i ** s
答案：A
（2）循环条件应写作：
A. i <= n
B. i < n
C. i >= n
D. i == n
答案：B
（3）写出程序运行结果：____
答案：120

【第2题】判断正误。
（1）Python 中列表用 [ ] 表示。
答案：对
（2）字典键必须是整数。
答案：错`;
console.log('用例 1：单选/单选/填空 + 判断');
const r1 = parseAll(t1, 2);
eq('切分 2 个综合题', r1.length, 2);
eq('第1题题干', r1[0].content, '阅读以下程序，回答问题。');
eq('第1题背景含材料', r1[0].background.indexOf('程序输入一个正整数') >= 0, true);
eq('第1题 3 个子题', r1[0].subs.length, 3);
eq('子题1 单选 + 选项数', [r1[0].subs[0].type, r1[0].subs[0].options.length], ['single', 4]);
eq('子题1 选项内容', r1[0].subs[0].options[0], 's = s * i');
eq('子题1 答案 A', r1[0].subs[0].answer, 'A');
eq('子题1 内容去标记', r1[0].subs[0].content, '下列哪个语句能实现累乘？');
eq('子题2 单选答案 B', r1[0].subs[1].answer, 'B');
eq('子题3 填空空数', r1[0].subs[2].blank_count, 1);
eq('子题3 填空答案', r1[0].subs[2].fill_answers, ['120']);
eq('子题3 blank_scores', r1[0].subs[2].blank_scores, [2]);
eq('第2题判断题1 对', r1[1].subs[0].answer, '对');
eq('第2题判断题2 错', r1[1].subs[1].answer, '错');

/* ── 用例 2：多选题识别 + 答案归一 ── */
console.log('用例 2：多选识别与归一');
const t2 = `【第1题】阅读材料。
以下哪些说法是正确的？（多选）
A. 列表有序
B. 字典键可重复
C. 元组不可变
D. 集合元素唯一
答案：A、C、D
（2）下列说法正确的是。
A. 正确
B. 错误
答案：A`;
const r2 = parseAll(t2, 3);
eq('含多选词 → multiple', r2[0].subs[0].type, 'multiple');
eq('多选答案归一 AC D', r2[0].subs[0].answer, 'ACD');
eq('默认单选', r2[0].subs[1].type, 'single');
eq('单选答案', r2[0].subs[1].answer, 'A');

/* ── 用例 3：判断归一（√/×/正确/错误） ── */
console.log('用例 3：判断归一');
const r3 = parseAll('【第1题】判断题。\n（1）Python 是解释型语言。\n答案：√\n（2）1 == 1.0 为假。\n答案：错误', 1);
eq('√ → 对', r3[0].subs[0].answer, '对');
eq('错误 → 错', r3[0].subs[1].answer, '错');

/* ── 用例 4：简答识别（无选项无空） ── */
console.log('用例 4：简答识别');
const r4 = parseAll('【第1题】简答题。\n（1）简述冒泡排序的思想。', 5);
eq('无选项无空 → short_answer', r4[0].subs[0].type, 'short_answer');
eq('简答无答案', r4[0].subs[0].answer, null);

/* ── 用例 5：数字编号子题 + fill 多空 ── */
console.log('用例 5：数字编号与 fill 多空');
const t5 = `【第1题】完成程序填空。
1. 补充循环：for i in range(____):
2. 计算：s = ____ + i
答案：1.  n
2.  0`;
const r5 = parseAll(t5, 4);
eq('数字编号切子题', r5[0].subs.length, 2);
eq('子题类型 fill', r5[0].subs[0].type, 'fill');
eq('子题2 内容', r5[0].subs[1].content, '计算：s = ____ + i');

/* ── 用例 6：fill 多空答案拆分 + blank_scores 均分 ── */
console.log('用例 6：fill 多空拆分与分值');
const t6 = `【第1题】填空。
（1）输入 a、b 两个数，输出和：____，____
答案：a, b`;
const r6 = parseAll(t6, 3);
eq('fill 空数 2', r6[0].subs[0].blank_count, 2);
eq('fill 答案拆分', r6[0].subs[0].fill_answers, ['a', 'b']);
eq('blank_scores 3分2空', r6[0].subs[0].blank_scores, [1.5, 1.5]);
const r6b = parseAll('【第1题】\n（1）填空：____，____，____\n答案：1, 2, 3', 2);
eq('blank_scores 2分3空', r6b[0].subs[0].blank_scores, [0.7, 0.7, 0.6]);

/* ── 用例 7：无子题标记 → 整题单子题 ── */
console.log('用例 7：无子题标记');
const r7 = parseAll('【第1题】写出程序输出结果。\n程序代码：\nprint(1+2)', 10);
eq('单简答子题', [r7[0].subs.length, r7[0].subs[0].type], [1, 'short_answer']);
eq('整题内容入子题', r7[0].subs[0].content.indexOf('print(1+2)') >= 0, true);

/* ── 用例 8：导出格式（对齐项目存储约定） ── */
console.log('用例 8：导出数据格式');
const exportFns = vm.runInContext('({calcBlankScores, splitFillAnswers})', sandbox);
eq('calcBlankScores 5分3空', exportFns.calcBlankScores(5, 3), [1.7, 1.7, 1.6]);
eq('calcBlankScores 4分3空', exportFns.calcBlankScores(4, 3), [1.3, 1.3, 1.4]);
eq('splitFillAnswers | 显式分空', exportFns.splitFillAnswers('a//b|c', 2), ['a//b', 'c']);
eq('splitFillAnswers 超出并入末空', exportFns.splitFillAnswers('1 2 3', 2), ['1', '2 // 3']);

/* ── 用例 9：导出 payload 结构（buildExportPayload） ── */
console.log('用例 9：导出 payload 结构');
const buildExportPayload = vm.runInContext('buildExportPayload', sandbox);
const r9 = parseAll(t1, 2);
const payload = buildExportPayload(r9);
eq('顶层 questions 数组', Array.isArray(payload.questions), true);
const q9 = payload.questions[0];
eq('综合题字段', Object.keys(q9).sort(),
   ['background', 'content', 'footer_content', 'num', 'sub_questions'].sort());
eq('子题1 导出', {
  type: q9.sub_questions[0].type,
  options: q9.sub_questions[0].options,
  answer: q9.sub_questions[0].answer,
  score: q9.sub_questions[0].score,
  order: q9.sub_questions[0].order,
  blank_scores: q9.sub_questions[0].blank_scores,
}, {
  type: 'single',
  options: 's = s * i|s = s + i|s = i / s|s = i ** s',
  answer: 'A',
  score: 2,
  order: 1,
  blank_scores: null,
});
eq('子题3 fill 导出', {
  type: q9.sub_questions[2].type,
  options: q9.sub_questions[2].options,
  answer: q9.sub_questions[2].answer,
  blank_scores: q9.sub_questions[2].blank_scores,
}, {
  type: 'fill',
  options: null,
  answer: '120',
  blank_scores: [2],
});
const p2 = buildExportPayload(parseAll('【第1题】\n（1）a？\nA. 1\nB. 2\n答案：A\n（2）判断\n答案：对\n（3）简述思路', 3));
const types = p2.questions[0].sub_questions.map(s => s.type);
const ans = p2.questions[0].sub_questions.map(s => s.answer);
eq('三类子题导出', { types, ans }, {
  types: ['single', 'judge', 'short_answer'],
  ans: ['A', '对', null],
});

/* ── 用例 10：页面渲染/导出冒烟（stub DOM 触发 DOMContentLoaded） ── */
console.log('用例 10：页面渲染/导出冒烟');
const realHandlers = {};
function fakeEl(props) {
  const el = {
    value: '', style: {}, dataset: {},
    classList: { add() {}, remove() {} },
    addEventListener() {}, querySelector() { return null; },
    querySelectorAll() { return []; }, click() {}, files: [],
    _html: '',
    set textContent(v) { this._html = String(v == null ? '' : v); },
    get textContent() { return this._html; },
    set innerHTML(v) { this._html = v; },
    get innerHTML() { return this._html; },
    ...(props || {}),
  };
  return el;
}
const areaEl = fakeEl();
const pageSandbox = {
  console,
  window: {},
  document: {
    addEventListener(name, fn) { realHandlers[name] = fn; },
    getElementById(id) {
      if (id === 'resultArea') return areaEl;
      if (id === 'emptyState') return fakeEl();
      if (id === 'questionsText') return fakeEl({ value: t1 });
      if (id === 'defaultScore') return fakeEl({ value: '2' });
      return fakeEl();
    },
    createElement(tag) {
      return fakeEl(tag === 'a' ? { click() { this.clicked = true; } } : {});
    },
  },
  URL: { createObjectURL() { return 'blob:x'; }, revokeObjectURL() {} },
  Blob: function () {},
  alert() {},
  setTimeout() {},
};
vm.createContext(pageSandbox);
vm.runInContext(m[1], pageSandbox);
realHandlers.DOMContentLoaded();  // 执行回调（内部函数定义）
pageSandbox.window.runParse();    // 识别 + 渲染
eq('渲染产生卡片', /qcard-0/.test(areaEl.innerHTML), true);
eq('渲染含子题选项', /s = s \* i/.test(areaEl.innerHTML), true);
pageSandbox.window.exportReview();  // 导出走 Blob 构造路径（已 stub）
eq('导出函数可调用（无异常）', true, true);

console.log(`\n结果: ${passed} 通过, ${failed} 失败`);
process.exit(failed ? 1 : 0);