/* AdminExams.js — 试卷管理页面 */
const AdminExams = {
  template: `
    <div class="max-w-4xl mx-auto px-4 py-8">
      <div class="flex items-center justify-between mb-6">
        <h2 class="text-2xl font-bold text-gray-800">试卷管理</h2>
        <button @click="showAdd = true" class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">添加试卷</button>
      </div>

      <div v-if="showAdd" class="bg-white rounded-lg shadow p-4 mb-4">
        <input v-model="newName" type="text" placeholder="试卷名称" @keyup.enter="addExam"
          class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-blue-500 mb-3" />
        <input v-model="newDuration" type="number" min="1" placeholder="考试时长（分钟，必填）" @keyup.enter="addExam"
          class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-blue-500 mb-3" />
        <div class="flex space-x-2">
          <button @click="addExam" :disabled="!newName.trim() || !newDuration || saving"
            class="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50">{{ saving ? '保存中...' : '保存' }}</button>
          <button @click="showAdd = false; newName = ''; newDuration = ''" :disabled="saving" class="px-4 py-2 bg-gray-100 rounded-lg hover:bg-gray-200">取消</button>
        </div>
        <p v-if="error" class="text-red-600 text-sm mt-2">{{ error }}</p>
      </div>

      <LoadingSpinner v-if="loading" />
      <div v-else-if="listError" class="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 mb-4 text-sm">{{ listError }}</div>
      <EmptyState v-else-if="!exams.length" message="暂无试卷" />

      <div v-else class="bg-white rounded-lg shadow overflow-hidden">
        <table class="min-w-full divide-y divide-gray-200">
          <thead class="bg-gray-50">
            <tr>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">名称</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">创建时间</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">题目数</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">状态控制</th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-200">
            <tr v-for="exam in exams" :key="exam.id" class="hover:bg-gray-50">
              <td class="px-6 py-4 text-sm text-gray-800">
                <span v-if="editingId === exam.id">
                  <input v-model="editName" @keyup.enter="updateExam(exam.id)" class="px-2 py-1 border rounded text-sm" />
                </span>
                <span v-else>{{ exam.name }}</span>
              </td>
              <td class="px-6 py-4 text-sm text-gray-500">{{ exam.create_time }}</td>
              <td class="px-6 py-4 text-sm text-gray-500">{{ exam.question_count || 0 }}</td>
              <td class="px-6 py-4 text-sm whitespace-nowrap">
                <label v-for="f in FLAGS" :key="f.key" class="inline-flex items-center mr-3 cursor-pointer select-none" :title="f.title">
                  <input type="checkbox" class="mr-1 accent-blue-600" :checked="!!exam[f.key]"
                    :disabled="flagSaving === exam.id + ':' + f.key"
                    @change="toggleFlag(exam, f.key, $event.target.checked)" /> {{ f.label }}
                </label>
              </td>
              <td class="px-6 py-4 text-sm space-x-2">
                <button v-if="editingId === exam.id" @click="updateExam(exam.id)" :disabled="saving"
                  class="text-green-600 hover:underline disabled:opacity-50">{{ saving ? '保存中...' : '保存' }}</button>
                <button v-else @click="startEdit(exam)" :disabled="saving" class="text-blue-600 hover:underline disabled:opacity-50">编辑</button>
                <a :href="'/admin/exams/' + exam.id + '/compose'" class="text-green-600 hover:underline" title="从题库选题组卷">组卷</a>
                <button @click="deleteExam(exam.id)" class="text-red-600 hover:underline">删除</button>
                <button @click="clearStale(exam.id)" class="text-gray-600 hover:underline"
                  title="清除超时未交卷的开考记录（学生弃考/断网后解锁重考）">清超时</button>
                <router-link :to="'/admin/questions?exam_id=' + exam.id" class="text-gray-600 hover:underline">题目</router-link>
                <router-link :to="'/admin/trend/' + exam.id" class="text-gray-600 hover:underline">成绩</router-link>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  `,
  setup() {
    const exams = Vue.reactive([])
    const loading = Vue.ref(true)
    const showAdd = Vue.ref(false)
    const newName = Vue.ref('')
    const newDuration = Vue.ref('')
    const editingId = Vue.ref(null)
    const editName = Vue.ref('')
    const error = Vue.ref('')
    const listError = Vue.ref('')
    const saving = Vue.ref(false)

    async function loadExams() {
      error.value = ''
      listError.value = ''
      try {
        const { data } = await examsAPI.list()
        if (data.success) exams.splice(0, exams.length, ...data.data)
      } catch (e) {
        // 独立错误条（此前 error 只渲染在"添加试卷"折叠面板内，面板未展开
        // 时接口失败页面仅显示"暂无试卷"，管理员误以为无试卷）
        listError.value = '试卷列表加载失败：' + ((e.response && e.response.data && e.response.data.message) || e?.message || '网络错误')
      }
      finally { loading.value = false }
    }

    // 清除超时开考记录（与 SSR 管理端「清超时开考记录」按钮同端点同语义；
    // 此前该补救入口只加在 SSR 页，从 SPA 进入的管理员无法给弃考学生解锁）
    async function clearStale(id) {
      if (!confirm('确定清除该试卷的超时开考记录吗？\n仅删除"超过考试时长+5分钟仍未交卷"的残留记录，相关学生可重新参加考试。')) return
      try {
        // 根路径 HTML 端点，不在 /api 前缀下，用带 CSRF 头的全局 axios
        const { data } = await window.axios.post('/admin/exams/' + id + '/clear-stale-attempts', null, { withCredentials: true })
        alert(data && data.success !== false ? '操作完成' : ((data && data.message) || '操作失败'))
      } catch (e) {
        alert((e.response && e.response.data && e.response.data.message) || '操作失败')
      }
    }

    async function addExam() {
      if (!newName.value.trim() || !newDuration.value || saving.value) return
      saving.value = true
      error.value = ''
      try {
        // duration 必填（后端强制）：没有时长的试卷会跳过服务端超时校验
        const { data } = await examsAPI.create({
          name: newName.value.trim(),
          duration: parseInt(newDuration.value, 10)
        })
        if (data.success) {
          await loadExams()
          showAdd.value = false
          newName.value = ''
          newDuration.value = ''
        } else { error.value = data.message }
      } catch (e) { error.value = '添加失败' }
      finally { saving.value = false }
    }

    function startEdit(exam) { editingId.value = exam.id; editName.value = exam.name }

    async function updateExam(id) {
      if (saving.value || !editName.value.trim()) return
      saving.value = true
      error.value = ''
      try {
        await examsAPI.update(id, { name: editName.value.trim() })
        editingId.value = null
        await loadExams()
      } catch (e) {
        console.error(e)
        error.value = '保存失败：' + ((e.response && e.response.data && e.response.data.message) || '请稍后重试')
      }
      finally { saving.value = false }
    }

    async function deleteExam(id) {
      if (!confirm('确定要删除该试卷吗？')) return
      try {
        await examsAPI.delete(id)
        await loadExams()
      } catch (e) {
        // 透出后端明确拒绝原因（409 已有成绩/在考锁定等），
        // 此前一律 alert('删除失败')，管理员无从得知要先清成绩还是先收卷
        alert((e.response && e.response.data && e.response.data.message) || '删除失败')
      }
    }

    // 考试控制开关（与 HTML 管理端 /admin/exams/toggle 同一路由同语义）：
    // 可见=学生端列表可见；开放=允许作答；收卷=禁止提交并通知在考学生；
    // 公布成绩=学生可查看成绩。此前 SPA 完全缺失这组考试日高频操作
    const FLAGS = [
      { key: 'is_visible', label: '可见', title: '学生端考试列表是否显示该试卷' },
      { key: 'is_enabled', label: '开放', title: '是否开放学生作答' },
      { key: 'is_collected', label: '收卷', title: '收卷后禁止提交，并通知在考学生自动交卷' },
      { key: 'allow_view_results', label: '公布成绩', title: '学生是否可查看本次成绩' }
    ]
    const flagSaving = Vue.ref(null)

    async function toggleFlag(exam, flag, checked) {
      const token = exam.id + ':' + flag
      flagSaving.value = token
      try {
        // 表单编码直发管理端 toggle 路由；CSRF 由 axios 拦截器自动携带。
        // 该端点在根路径（/admin/exams/toggle/<id>，exam_management.py），
        // 不在 /api 前缀下——必须用无 baseURL 的全局 axios；此前误用
        // baseURL='/api' 的 apiClient 拼出 /api/admin/exams/toggle/<id>
        // 必 404，四个状态开关全部失效（checkbox 回弹+报"切换失败"）
        const { data } = await window.axios.post(
          '/admin/exams/toggle/' + exam.id,
          new URLSearchParams({ flag: flag, value: String(checked) }),
          { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }
        )
        if (data && data.success) {
          exam[flag] = checked
        } else {
          exam[flag] = !checked
          alert((data && data.message) || '切换失败')
        }
      } catch (e) {
        exam[flag] = !checked
        alert((e.response && e.response.data && e.response.data.message) || '切换失败')
      } finally {
        flagSaving.value = null
      }
    }

    Vue.onMounted(loadExams)
    return { exams, loading, showAdd, newName, newDuration, editingId, editName, error, listError, saving, FLAGS, flagSaving, addExam, startEdit, updateExam, deleteExam, clearStale, toggleFlag }
  }
}

// 导出到 window（供 router.js loadComponent 按名解析）
window.AdminExams = AdminExams;
