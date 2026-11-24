/* AdminOnlineStudents.js — 在线学生管理 */
const AdminOnlineStudents = {
  template: `
    <div class="max-w-5xl mx-auto px-4 py-8">
      <div class="flex items-center justify-between mb-6">
        <h2 class="text-2xl font-bold text-gray-800">
          在线学生
          <span class="text-base font-normal text-gray-500 ml-2">(30分钟内登录)</span>
        </h2>
        <div class="space-x-2">
          <a href="/admin/online_students/export" class="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 text-sm">导出Excel</a>
          <button @click="clearAll" class="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 text-sm">清除</button>
        </div>
      </div>

      <LoadingSpinner v-if="loading" />
      <div v-else-if="loadError" class="bg-red-50 text-red-600 text-sm p-3 rounded-lg mb-4">
        <i class="fas fa-triangle-exclamation mr-1"></i>{{ loadError }}
      </div>
      <EmptyState v-else-if="!students.length" message="当前没有在线学生" />

      <div v-else class="bg-white rounded-lg shadow overflow-hidden">
        <table class="min-w-full divide-y divide-gray-200">
          <thead class="bg-gray-50">
            <tr>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">姓名</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">班级</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">IP地址</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">登录时间</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-200">
            <tr v-for="s in students" :key="s.id" class="hover:bg-gray-50">
              <td class="px-6 py-4 text-sm text-gray-800">{{ s.name }}</td>
              <td class="px-6 py-4 text-sm text-gray-500">{{ s.class || s.student_class }}</td>
              <td class="px-6 py-4 text-sm text-gray-500">{{ s.ip_address }}</td>
              <td class="px-6 py-4 text-sm text-gray-500">{{ s.login_time }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `,
  setup() {
    const students = Vue.reactive([])
    const loading = Vue.ref(true)
    const loadError = Vue.ref('')

    async function loadStudents() {
      try {
        const { data } = await apiClient.get('/students/online')
        // 后端返回 data: {total, students: [...]}（对象而非数组）
        if (data.success) students.splice(0, students.length, ...(data.data?.students || []))
      } catch (e) { loadError.value = '加载失败：' + (e?.message || '网络错误') }
      finally { loading.value = false }
    }

    async function clearAll() {
      if (!confirm('确定要清除在线学生列表吗？')) return
      try {
        await apiClient.post('/students/clear')
        students.splice(0, students.length)
      } catch (e) { alert('清除失败') }
    }

    Vue.onMounted(loadStudents)
    return { students, loading, loadError, clearAll }
  }
}

// 导出到 window（供 router.js loadComponent 按名解析）
window.AdminOnlineStudents = AdminOnlineStudents;
