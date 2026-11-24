/* AdminQuestionForm.js — 添加/编辑题目 */
const AdminQuestionForm = {
  template: `
    <div class="max-w-3xl mx-auto px-4 py-8">
      <h2 class="text-2xl font-bold text-gray-800 mb-6">{{ isEdit ? '编辑题目' : '添加题目' }}</h2>
      <div class="bg-white rounded-lg shadow p-6 space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">所属试卷（可选：不选=仅存题库）</label>
          <select v-model="form.exam_id" class="w-full px-3 py-2 border border-gray-300 rounded-lg">
            <option value="">— 仅存题库（不入卷，可后续组卷加入） —</option>
            <option v-for="e in exams" :key="e.id" :value="e.id">{{ e.name }}</option>
          </select>
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">题目类型</label>
          <select v-model="form.question_type" @change="onTypeChange" class="w-full px-3 py-2 border border-gray-300 rounded-lg" :disabled="isEdit">
            <option v-for="(label, key) in TYPE_MAP" :key="key" :value="key">{{ label }}</option>
          </select>
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">题目内容</label>
          <textarea v-model="form.content" rows="4" class="w-full px-3 py-2 border border-gray-300 rounded-lg" placeholder="支持HTML格式"></textarea>
        </div>

        <div v-if="['single','multiple'].includes(form.question_type)">
          <label class="block text-sm font-medium text-gray-700 mb-1">选项 (用 | 分隔)</label>
          <input v-model="form.options" type="text" class="w-full px-3 py-2 border border-gray-300 rounded-lg" placeholder="A. 选项A | B. 选项B | C. 选项C | D. 选项D" />
        </div>

        <div v-if="form.question_type === 'python_fill'">
          <label class="block text-sm font-medium text-gray-700 mb-1">Python答案 (JSON格式: {"1": "答案1", "2": "答案2"})</label>
          <input v-model="form.python_answers" type="text" class="w-full px-3 py-2 border border-gray-300 rounded-lg font-mono text-sm" placeholder='{"1": "print(&#34;hello&#34;)"}' />
        </div>

        <div v-if="form.question_type === 'comprehensive'">
          <label class="block text-sm font-medium text-gray-700 mb-1">背景描述</label>
          <textarea v-model="form.background" rows="3" class="w-full px-3 py-2 border border-gray-300 rounded-lg"></textarea>
        </div>

        <div class="grid grid-cols-2 gap-4">
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">标准答案</label>
            <input v-model="form.answer" type="text" class="w-full px-3 py-2 border border-gray-300 rounded-lg" :placeholder="answerPlaceholder" />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">分值</label>
            <input v-model.number="form.score" type="number" step="0.5" min="0" class="w-full px-3 py-2 border border-gray-300 rounded-lg" />
          </div>
        </div>

        <div v-if="error" class="text-red-600 text-sm bg-red-50 p-2 rounded">{{ error }}</div>

        <div class="flex space-x-3 pt-4">
          <button @click="save" :disabled="saving"
            class="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">{{ saving ? '保存中...' : '保存' }}</button>
          <router-link to="/admin/questions" class="px-6 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200">取消</router-link>
          <button v-if="isEdit && form.question_type === 'comprehensive'" @click="goToSubQuestions" class="px-4 py-2 bg-indigo-100 text-indigo-700 rounded-lg hover:bg-indigo-200 text-sm">管理小题</button>
        </div>
      </div>
    </div>
  `,
  setup() {
    const route = VueRouter.useRoute()
    const router = VueRouter.useRouter()
    const isEdit = Vue.computed(() => !!route.params.id)
    const form = Vue.reactive({ exam_id: '', question_type: 'single', content: '', options: '', answer: '', score: 1, python_answers: '', background: '' })
    const exams = Vue.reactive([])
    const error = Vue.ref('')
    const saving = Vue.ref(false)

    const TYPE_MAP = { single: '单选题', multiple: '多选题', judge: '判断题', fill: '填空题', short_answer: '简答题', python_fill: 'Python填空题', comprehensive: '综合题' }
    const answerPlaceholder = Vue.computed(() => {
      if (form.question_type === 'single') return '如: A'
      if (form.question_type === 'multiple') return '如: A|B'
      if (form.question_type === 'judge') return '对/错（或 true/false）'
      if (form.question_type === 'fill') return '用 | 分隔多个空'
      return '标准答案'
    })

    async function loadExams() {
      try { const { data } = await examsAPI.list()
        if (data.success) exams.splice(0, exams.length, ...data.data) }
      catch (e) { error.value = '加载失败：' + (e?.message || '网络错误') }
    }

    async function loadQuestion() {
      if (!isEdit.value) return
      error.value = ''
      try {
        const { data } = await questionsAPI.get(route.params.id)
        if (data.success) {
          const q = data.data
          Object.assign(form, { exam_id: q.exam_id, question_type: q.question_type, content: q.content, options: q.options || '', answer: q.answer || '', score: q.score, python_answers: q.python_answers || '', background: q.background || '' })
        }
      } catch (e) { error.value = '加载失败：' + (e?.message || '网络错误') }
    }

    function onTypeChange() { form.options = ''; form.answer = '' }

    async function save() {
      // JS 侧校验：HTML required 不作用于 @click 提交
      // exam_id 可选：空 = 仅存题库（解耦）
      if (!form.content || !form.content.trim()) { error.value = '请输入题目内容'; return }
      if (['single', 'multiple'].includes(form.question_type) && !form.options) { error.value = '请输入选项'; return }
      if (form.score === '' || form.score === null || isNaN(form.score) || form.score < 0) { error.value = '分值必须为非负数'; return }
      if (form.question_type === 'judge' && !['true', 'false', '对', '错', '正确', '错误', '1', '0'].includes(String(form.answer).trim().toLowerCase())) { error.value = '判断题答案必须为「对/错」（或 true/false）'; return }
      error.value = ''
      saving.value = true
      try {
        const payload = { ...form }
        let resp
        if (isEdit.value) {
          resp = await questionsAPI.update(route.params.id, payload)
        } else {
          resp = await questionsAPI.create(payload)
        }
        if (resp.data.success) {
          // 后端 create 仅返回 {id}；判断题型用表单自身值
          if (form.question_type === 'comprehensive' && !isEdit.value) {
            router.push('/admin/questions/' + resp.data.data.id + '/sub')
          } else {
            router.push('/admin/questions')
          }
        } else {
          error.value = resp.data.message || '操作失败'
        }
      } catch (e) {
        error.value = e.response?.data?.message || '网络错误'
      } finally { saving.value = false }
    }

    function goToSubQuestions() {
      router.push('/admin/questions/' + route.params.id + '/sub')
    }

    Vue.onMounted(() => { loadExams(); loadQuestion() })
    return { isEdit, form, exams, error, saving, TYPE_MAP, answerPlaceholder, onTypeChange, save, goToSubQuestions }
  }
}

// 导出到 window（供 router.js loadComponent 按名解析）
window.AdminQuestionForm = AdminQuestionForm;
