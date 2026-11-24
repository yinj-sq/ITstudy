/* AdminQuestions.js — 题库管理 */
const AdminQuestions = {
  template: `
    <div class="max-w-6xl mx-auto px-4 py-8">
      <div class="flex items-center justify-between mb-6">
        <h2 class="text-2xl font-bold text-gray-800">题库管理</h2>
        <div class="flex space-x-2">
          <router-link to="/admin/questions/add" class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm">添加题目</router-link>
        </div>
      </div>

      <div class="bg-white rounded-lg shadow p-4 mb-6 flex flex-wrap gap-2">
        <select v-model="filters.exam_id" @change="resetAndLoad" class="px-3 py-1.5 border rounded-lg text-sm">
          <option value="">全部试卷</option>
          <option v-for="e in exams" :key="e.id" :value="e.id">{{ e.name }}</option>
        </select>
        <select v-model="filters.question_type" @change="resetAndLoad" class="px-3 py-1.5 border rounded-lg text-sm">
          <option value="">全部题型</option>
          <option v-for="(label, key) in TYPE_MAP" :key="key" :value="key">{{ label }}</option>
        </select>
        <button v-if="selectedIds.length" @click="batchDelete" class="px-4 py-1.5 bg-red-600 text-white rounded-lg text-sm">删除选中({{ selectedIds.length }})</button>
      </div>

      <LoadingSpinner v-if="loading" />
      <div v-else-if="loadError" class="bg-red-50 text-red-600 text-sm p-3 rounded-lg mb-4">
        <i class="fas fa-triangle-exclamation mr-1"></i>{{ loadError }}
      </div>
      <EmptyState v-else-if="!questions.length" message="暂无题目" />

      <div v-else class="bg-white rounded-lg shadow overflow-hidden">
        <table class="min-w-full divide-y divide-gray-200">
          <thead class="bg-gray-50">
            <tr>
              <th class="px-3 py-3"><input type="checkbox" :checked="selectAll" @change="toggleAll" /></th>
              <th class="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">ID</th>
              <th class="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">题型</th>
              <th class="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">内容</th>
              <th class="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">分值</th>
              <th class="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-200">
            <tr v-for="q in questions" :key="q.id" class="hover:bg-gray-50">
              <td class="px-3 py-3"><input type="checkbox" :value="q.id" v-model="selectedIds" /></td>
              <td class="px-3 py-3 text-sm text-gray-500">{{ q.id }}</td>
              <td class="px-3 py-3">
                <span class="text-xs px-2 py-0.5 rounded" :class="typeBadge(q.question_type)">{{ TYPE_MAP[q.question_type] || q.question_type }}</span>
              </td>
              <td class="px-3 py-3 text-sm text-gray-800 max-w-xs truncate">{{ stripHtml(q.content) }}</td>
              <td class="px-3 py-3 text-sm text-gray-500">{{ q.score }}</td>
              <td class="px-3 py-3 text-sm space-x-2">
                <router-link :to="'/admin/questions/' + q.id + '/edit'" class="text-blue-600 hover:underline">编辑</router-link>
                <router-link v-if="q.question_type === 'comprehensive'" :to="'/admin/questions/' + q.id + '/sub'" class="text-indigo-600 hover:underline">小题</router-link>
                <button @click="deleteQuestion(q.id)" class="text-red-600 hover:underline">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
        <!-- 分页（题库上千题时列表不再全量加载） -->
        <div class="px-4 py-3 border-t border-gray-200 flex items-center justify-between">
          <span class="text-sm text-gray-500">共 {{ total }} 题</span>
          <AppPagination :current-page="page" :total-pages="totalPages" @page-change="goToPage" />
        </div>
      </div>
    </div>
  `,
  setup() {
    const route = VueRouter.useRoute()
    const questions = Vue.reactive([])
    const exams = Vue.reactive([])
    const loading = Vue.ref(true)
    const loadError = Vue.ref('')
    const selectedIds = Vue.ref([])
    const selectAll = Vue.ref(false)
    const page = Vue.ref(1)
    const total = Vue.ref(0)
    const totalPages = Vue.ref(1)
    // 支持从 URL query 带入筛选（AdminExams「题目」链接传 ?exam_id=X）
    const filters = Vue.reactive({ exam_id: route.query.exam_id || '', question_type: '' })

    const TYPE_MAP = { single: '单选', multiple: '多选', judge: '判断', fill: '填空', short_answer: '简答', python_fill: 'Python填空', comprehensive: '综合', link: '外链' }
    const TYPE_CLASS = { single: 'bg-blue-100 text-blue-700', multiple: 'bg-purple-100 text-purple-700', judge: 'bg-green-100 text-green-700', fill: 'bg-orange-100 text-orange-700', python_fill: 'bg-cyan-100 text-cyan-700', comprehensive: 'bg-indigo-100 text-indigo-700', link: 'bg-gray-100 text-gray-600' }

    function typeBadge(t) { return TYPE_CLASS[t] || '' }
    function stripHtml(s) { if (!s) return ''; return s.replace(/<[^>]+>/g, '').substring(0, 60) }

    async function loadQuestions() {
      loading.value = true
      loadError.value = ''
      try {
        const params = { page: page.value, page_size: 20 }
        if (filters.exam_id) params.exam_id = filters.exam_id
        if (filters.question_type) params.question_type = filters.question_type
        const { data } = await questionsAPI.list(params)
        const { data: eData } = await examsAPI.list()
        if (data.success) {
          questions.splice(0, questions.length, ...(data.data || []))
          if (typeof data.total === 'number') {
            total.value = data.total
            totalPages.value = data.total_pages || 1
          }
        }
        if (eData.success) exams.splice(0, exams.length, ...(eData.data || []))
      } catch (e) { loadError.value = '加载失败：' + (e?.message || '网络错误') }
      finally {
        loading.value = false
        // 数据刷新后重置全选状态，避免与 selectedIds 不同步
        selectAll.value = false
        selectedIds.value = []
      }
    }

    function goToPage(p) {
      page.value = p
      loadQuestions()
    }

    // 筛选变更：回到第 1 页（此前停留在末页时切换筛选可能看到空列表）
    function resetAndLoad() {
      page.value = 1
      loadQuestions()
    }

    function toggleAll(e) {
      selectAll.value = e.target.checked
      selectedIds.value = e.target.checked ? questions.map(q => q.id) : []
    }

    async function deleteQuestion(id) {
      if (!confirm('确定删除？')) return
      try {
        await questionsAPI.delete(id)
        // 删除后当前页可能为空（末页最后一条），自动回退一页
        if (questions.length === 1 && page.value > 1) page.value -= 1
        await loadQuestions()
      }
      catch (e) { alert('删除失败') }
    }

    async function batchDelete() {
      if (!confirm('确定删除选中的 ' + selectedIds.value.length + ' 道题目？')) return
      try {
        // 先取快照再清空：selectedIds 清空后比较恒为 0，
        // 末页全选删除后无法回退页码（此前缺陷，删除后停留空列表）
        const n = selectedIds.value.length
        await questionsAPI.batchDelete(selectedIds.value)
        selectedIds.value = []
        selectAll.value = false
        if (questions.length === n && page.value > 1) page.value -= 1
        await loadQuestions()
      }
      catch (e) { alert('删除失败') }
    }

    Vue.onMounted(loadQuestions)
    return { questions, exams, loading, loadError, selectedIds, selectAll, filters, page, total, totalPages, TYPE_MAP, typeBadge, stripHtml, loadQuestions, goToPage, resetAndLoad, toggleAll, deleteQuestion, batchDelete }
  }
}

// 导出到 window（供 router.js loadComponent 按名解析）
window.AdminQuestions = AdminQuestions;
