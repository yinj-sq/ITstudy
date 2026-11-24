/* StudyResources.js — 学习资源浏览页面 */
const StudyResources = {
  template: `
    <div class="max-w-5xl mx-auto px-4 py-8">
      <h2 class="text-2xl font-bold text-gray-800 mb-6">学习资源</h2>
      <LoadingSpinner v-if="loading" />
      <div v-else-if="loadError" class="bg-red-50 text-red-600 text-sm p-6 rounded-lg text-center">
        {{ loadError }}
        <button @click="loadResources" class="block mx-auto mt-3 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm">重新加载</button>
      </div>
      <EmptyState v-else-if="!resources.length" message="暂无学习资源" />
      <div v-else class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        <div v-for="res in resources" :key="res.id"
          class="bg-white rounded-lg shadow p-5 hover:shadow-md transition border border-gray-100">
          <h3 class="text-lg font-semibold text-gray-800 mb-2">{{ res.title }}</h3>
          <a :href="safeUrl(res.url)" target="_blank" rel="noopener"
            class="inline-block mt-3 text-blue-600 hover:text-blue-800 text-sm font-medium">
            访问资源 →
          </a>
        </div>
      </div>
    </div>
  `,
  setup() {
    const resources = Vue.reactive([])
    const loading = Vue.ref(true)
    const loadError = Vue.ref('')

    // 协议白名单校验：拦截 javascript: 等危险协议（仅管理员可录入，纵深防御）
    function safeUrl(url) {
      if (window.isSafeUrl && url && !window.isSafeUrl(url)) return '#'
      return url
    }

    async function loadResources() {
      try {
        const { data } = await resourcesAPI.list()
        if (data.success) resources.splice(0, resources.length, ...data.data)
      } catch (e) {
        // 错误态区分"加载失败"与"无资源"：此前失败时显示"暂无学习资源"
        console.error('加载资源失败', e)
        loadError.value = '学习资源加载失败，请检查网络连接'
      } finally {
        loading.value = false
      }
    }

    Vue.onMounted(loadResources)
    return { resources, loading, loadError, safeUrl }
  }
}

// 导出到 window（供 router.js loadComponent 按名解析）
window.StudyResources = StudyResources;
