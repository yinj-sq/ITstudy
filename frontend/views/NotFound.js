/* NotFound.js — 404 页面 */
const NotFound = {
  template: `
    <div class="min-h-[60vh] flex items-center justify-center">
      <div class="text-center">
        <h1 class="text-6xl font-bold text-gray-300 mb-4">404</h1>
        <p class="text-gray-500 mb-6">页面未找到</p>
        <router-link to="/" class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">返回首页</router-link>
      </div>
    </div>
  `
}

// 导出到 window（供 router.js loadComponent 按名解析）
window.NotFound = NotFound;
