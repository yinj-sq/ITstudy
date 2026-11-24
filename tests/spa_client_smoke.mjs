/**
 * SPA API 层加载时序冒烟测试（Node 模拟环境）
 *
 * 回归对象: frontend/api/client.js 的 axios 等待逻辑与 CSRF 注入分工。
 * 此前缺陷: client.js 以同步 <script> 加载,而 axios 由 resource-loader
 * 异步注入,执行瞬间 window.axios 为 undefined → configureAxiosCsrf
 * 抛 TypeError → window.apiClient 从未挂载,SPA 全部 API 调用失败。
 *
 * CSRF 分工（2026-10-19）：统一由 static/js/ui-feedback.js 的 XHR/fetch
 * 补丁注入 X-CSRFToken；axios 内建 XSRF 必须保持关闭，否则同一请求头被
 * 写两次（"token, token"），服务端 compare_digest 恒失败（SPA 登录 403）。
 */
import { readFileSync } from 'fs';
import { join } from 'path';

const root = process.cwd();
const clientSrc = readFileSync(join(root, 'frontend/api/client.js'), 'utf-8');

// ---- 浏览器环境 stub ----
const reqHandlers = [];
global.window = {
  location: { href: 'http://localhost:5000/app/', origin: 'http://localhost:5000' },
};
global.document = { cookie: 'csrf_token=probe-token-123; session=abc123' };

// ① axios 未就绪时执行 client.js: 应静默进入等待,绝不抛错
let firstError = null;
try {
  eval(clientSrc);
} catch (e) {
  firstError = e;
}
if (firstError) {
  console.error(`FAIL: axios 未就绪时执行抛错: ${firstError.message}`);
  process.exit(1);
}
if (global.window.apiClient !== undefined) {
  console.error('FAIL: axios 未就绪时不应挂载 apiClient');
  process.exit(1);
}
console.log('PASS 1/4: axios 未就绪时静默等待,不抛错');

// 假 axios stub: 记录请求拦截器,模拟 create 与 defaults
function makeAxios() {
  const create = (cfg) => ({
    defaults: Object.assign({}, cfg),
    interceptors: {
      request: { use: (fn) => { reqHandlers.push(fn); } },
      response: { use: () => {} },
    },
  });
  return {
    defaults: {},
    interceptors: {
      request: { use: (fn) => { reqHandlers.push(fn); } },
      response: { use: () => {} },
    },
    create,
  };
}

// ② 注入 axios,等待轮询(50ms 间隔)完成初始化
global.window.axios = makeAxios();
await new Promise((r) => setTimeout(r, 300));

const client = global.window.apiClient;
if (!client) {
  console.error('FAIL: axios 就绪后 apiClient 仍未挂载');
  process.exit(1);
}
console.log('PASS 2/4: axios 就绪后 window.apiClient 已挂载');

if (client.defaults.xsrfCookieName !== undefined) {
  console.error(`FAIL: 不应启用 axios 内建 XSRF（会与全局补丁重复注入）: ${client.defaults.xsrfCookieName}`);
  process.exit(1);
}
if (client.defaults.withCredentials !== true) {
  console.error('FAIL: withCredentials 未开启');
  process.exit(1);
}
const feedbackSrc = readFileSync(join(root, 'static/js/ui-feedback.js'), 'utf-8');
if (!feedbackSrc.includes("xhr.setRequestHeader('X-CSRFToken'") ||
    !feedbackSrc.includes("headers.set('X-CSRFToken'")) {
  console.error('FAIL: ui-feedback 未提供 XHR/fetch 的 CSRF 注入');
  process.exit(1);
}
console.log('PASS 3/4: apiClient 配置正确(withCredentials / 关闭内建 XSRF)；补丁注入 CSRF');

// ③ CSRF 头由 ui-feedback 补丁注入；client.js 只负责 AJAX 标识
const cfg = { method: 'POST', url: '/api/exams', headers: {} };
for (const h of reqHandlers) h(cfg);
if (cfg.headers['X-Requested-With'] !== 'XMLHttpRequest') {
  console.error('FAIL: AJAX 标识未附加');
  process.exit(1);
}
// GET 请求不改变方法
const cfgGet = { method: 'GET', url: '/api/exams', headers: {} };
for (const h of reqHandlers) h(cfgGet);
console.log('PASS 4/4: 请求拦截器正确(写请求带 AJAX 标识)');
console.log('ALL SPA CLIENT TESTS PASSED');
