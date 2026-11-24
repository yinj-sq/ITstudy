/* AdminPythonLogs.js — Python日志查看 */
const AdminPythonLogs = {
  template: `
    <div class="max-w-6xl mx-auto px-4 py-8">
      <div class="flex items-center justify-between mb-6">
        <h2 class="text-2xl font-bold text-gray-800">Python 评分日志</h2>
        <button @click="clearLogs" class="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 text-sm">清除日志</button>
      </div>

      <div class="bg-white rounded-lg shadow p-4 mb-6 flex flex-wrap gap-2">
        <input v-model="filters.search" placeholder="搜索关键字" @keyup.enter="loadLogs" class="px-3 py-1.5 border rounded-lg text-sm w-48" />
        <input v-model="filters.question_id" placeholder="题目ID" class="px-3 py-1.5 border rounded-lg text-sm w-24" />
        <input v-model="filters.student_id" placeholder="学生ID" class="px-3 py-1.5 border rounded-lg text-sm w-24" />
        <select v-model="filters.log_level" @change="loadLogs" class="px-3 py-1.5 border rounded-lg text-sm">
          <option value="">全部级别</option>
          <option value="ERROR">ERROR</option>
          <option value="WARNING">WARNING</option>
          <option value="INFO">INFO</option>
        </select>
        <button @click="searchLogs" class="px-4 py-1.5 bg-blue-600 text-white rounded-lg text-sm">搜索</button>
      </div>

      <LoadingSpinner v-if="loading" />
      <div v-else-if="loadError" class="bg-red-50 text-red-600 text-sm p-3 rounded-lg mb-4">
        <i class="fas fa-triangle-exclamation mr-1"></i>{{ loadError }}
      </div>
      <EmptyState v-else-if="!logs.length" message="暂无Python日志" />

      <div v-else class="bg-gray-900 text-green-400 p-4 rounded-lg font-mono text-xs overflow-auto max-h-96">
        <div v-for="(log, idx) in logs" :key="idx" class="py-0.5" :class="log.class">
          {{ log.text }}
        </div>
      </div>

      <AppPagination v-if="total > perPage" :current-page="page" :total-pages="Math.ceil(total/perPage)" @page-change="p => { page = p; loadLogs() }" />
    </div>
  `,
  setup() {
    const logs = Vue.reactive([])
    const loading = Vue.ref(true)
    const loadError = Vue.ref('')
    const page = Vue.ref(1)
    const perPage = Vue.ref(50)
    const total = Vue.ref(0)
    const filters = Vue.reactive({ search: '', question_id: '', student_id: '', log_level: '' })

    async function loadLogs() {
      loading.value = true
      try {
        // 后端参数名为 search_term（搜索关键字），其余同名透传
        const params = {
          page: page.value,
          per_page: perPage.value,
          search_term: filters.search,
          question_id: filters.question_id,
          student_id: filters.student_id,
          log_level: filters.log_level
        }
        const { data } = await apiClient.get('/logs/python', { params })
        if (data.success) {
          logs.splice(0, logs.length, ...(data.logs?.map(t => ({ text: t, class: '' })) || []))
          total.value = data.total || 0
        }
      } catch (e) { loadError.value = '加载失败：' + (e?.message || '网络错误') }
      finally { loading.value = false }
    }

    // 搜索条件变化后必须回到第 1 页：停留在第 2 页时结果不足一页会显示
    // "暂无 Python 日志"，实际第 1 页有数据。
    function searchLogs() {
      page.value = 1
      loadLogs()
    }

    async function clearLogs() {
      if (!confirm('确定清除？')) return
      try {
        // 清除接口是根路径 HTML 端点（/admin/python_logs/clear），
        // 不在 /api 前缀下，用带 CSRF 头的全局 axios 调用
        await window.axios.post('/admin/python_logs/clear', null, { withCredentials: true })
        logs.splice(0, logs.length)
        total.value = 0
      } catch (e) { alert('清除失败') }
    }

    Vue.onMounted(loadLogs)
    return { logs, loading, loadError, page, perPage, total, filters, loadLogs, searchLogs, clearLogs }
  }
}

// 导出到 window（供 router.js loadComponent 按名解析）
window.AdminPythonLogs = AdminPythonLogs;
