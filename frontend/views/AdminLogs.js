/* AdminLogs.js — 操作日志 */
const AdminLogs = {
  template: `
    <div class="max-w-5xl mx-auto px-4 py-8">
      <div class="flex items-center justify-between mb-6">
        <h2 class="text-2xl font-bold text-gray-800">操作日志</h2>
        <button @click="clearLogs" class="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 text-sm">清除日志</button>
      </div>
      <LoadingSpinner v-if="loading" />
      <div v-else-if="loadError" class="bg-red-50 text-red-600 text-sm p-3 rounded-lg mb-4">
        <i class="fas fa-triangle-exclamation mr-1"></i>{{ loadError }}
      </div>
      <EmptyState v-else-if="!logs.length" message="暂无操作日志" />
      <div v-else class="bg-white rounded-lg shadow overflow-hidden">
        <table class="min-w-full divide-y divide-gray-200">
          <thead class="bg-gray-50">
            <tr>
              <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">时间</th>
              <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">操作</th>
              <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">详情</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-200">
            <tr v-for="log in logs" :key="log.id" class="hover:bg-gray-50">
              <td class="px-4 py-3 text-sm text-gray-500 whitespace-nowrap">{{ log.time }}</td>
              <td class="px-4 py-3 text-sm text-gray-800">{{ log.action }}</td>
              <td class="px-4 py-3 text-sm text-gray-500 max-w-xs truncate">{{ log.detail }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `,
  setup() {
    const logs = Vue.reactive([])
    const loading = Vue.ref(true)
    const loadError = Vue.ref('')

    async function loadLogs() {
      try {
        const { data } = await apiClient.get('/logs')
        if (data.success) logs.splice(0, logs.length, ...(data.data || []))
      } catch (e) { loadError.value = '加载失败：' + (e?.message || '网络错误') }
      finally { loading.value = false }
    }

    async function clearLogs() {
      if (!confirm('确定要清除所有日志吗？')) return
      try {
        await apiClient.post('/logs/clear')
        logs.splice(0, logs.length)
      } catch (e) { alert('清除失败') }
    }

    Vue.onMounted(loadLogs)
    return { logs, loading, loadError, clearLogs }
  }
}

// 导出到 window（供 router.js loadComponent 按名解析）
window.AdminLogs = AdminLogs;
