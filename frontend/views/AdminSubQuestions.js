/* AdminSubQuestions.js — 综合题小题管理 */
const AdminSubQuestions = {
  template: `
    <div class="max-w-4xl mx-auto px-4 py-8">
      <div class="flex items-center justify-between mb-6">
        <h2 class="text-2xl font-bold text-gray-800">小题管理</h2>
        <router-link to="/admin/questions" class="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 text-sm">返回题库</router-link>
      </div>

      <div v-if="question" class="bg-white rounded-lg shadow p-6 mb-6">
        <h3 class="font-semibold text-gray-800 mb-2">综合题背景</h3>
        <p class="text-gray-600 text-sm">{{ question.background || '无' }}</p>
        <p class="text-gray-500 text-sm mt-2">总分: {{ question.score }} | 小题数: {{ subs.length }}</p>
      </div>

      <div class="space-y-3 mb-8">
        <div v-for="(sub, idx) in subs" :key="sub.id" class="bg-white rounded-lg shadow p-4">
          <div class="flex items-start justify-between">
            <div class="flex-1">
              <div class="flex items-center space-x-2 mb-2">
                <span class="text-sm bg-gray-100 px-2 py-0.5 rounded">{{ idx + 1 }}</span>
                <span class="text-xs font-medium px-2 py-0.5 rounded" :class="typeClass(sub.question_type)">{{ typeLabel(sub.question_type) }}</span>
                <span class="text-xs text-gray-500">{{ sub.score }} 分</span>
              </div>
              <div class="text-sm text-gray-800" v-html="safeQuestionContent(sub.content)"></div>
              <div class="text-xs text-gray-500 mt-1">答案: {{ sub.answer }} | 选项: {{ sub.options || '无' }}</div>
            </div>
            <button @click="deleteSub(sub.id)" class="text-red-600 text-sm hover:underline ml-4">删除</button>
          </div>
        </div>
        <div v-if="loadError" class="bg-red-50 text-red-600 text-sm p-3 rounded-lg mb-3">
          <i class="fas fa-triangle-exclamation mr-1"></i>{{ loadError }}
        </div>
        <EmptyState v-if="!subs.length" message="暂无小题，请添加" />
      </div>

      <div class="bg-white rounded-lg shadow p-6">
        <h3 class="font-semibold text-gray-800 mb-4">添加小题</h3>
        <div class="space-y-3">
          <select v-model="newSub.question_type" class="w-full px-3 py-2 border rounded-lg">
            <option v-for="(l,k) in subTypes" :key="k" :value="k">{{ l }}</option>
          </select>
          <textarea v-model="newSub.content" rows="2" placeholder="小题内容" class="w-full px-3 py-2 border rounded-lg"></textarea>
          <input v-model="newSub.options" placeholder="选项 (| 分隔)" class="w-full px-3 py-2 border rounded-lg" />
          <input v-model="newSub.answer" placeholder="标准答案" class="w-full px-3 py-2 border rounded-lg" />
          <input v-model.number="newSub.score" type="number" step="0.5" min="0" placeholder="分值" class="w-full px-3 py-2 border rounded-lg" />
          <button @click="addSub" :disabled="!newSub.content||!newSub.answer"
            class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">添加</button>
          <p v-if="msg" class="text-sm" :class="msgType">{{ msg }}</p>
        </div>
      </div>
    </div>
  `,
  setup() {
    const route = VueRouter.useRoute()
    const question = Vue.ref(null)
    const subs = Vue.reactive([])
    const newSub = Vue.reactive({ question_type: 'single', content: '', options: '', answer: '', score: 1 })
    const msg = Vue.ref('')
    const msgType = Vue.ref('text-green-600')
    const loadError = Vue.ref('')

    const TYPE_MAP = { single: '单选题', multiple: '多选题', judge: '判断题', fill: '填空题', short_answer: '简答题' }
    const TYPE_CLS = { single: 'bg-blue-100 text-blue-700', multiple: 'bg-purple-100 text-purple-700', judge: 'bg-green-100 text-green-700', fill: 'bg-orange-100 text-orange-700' }

    function typeLabel(t) { return TYPE_MAP[t] || t }
    function typeClass(t) { return TYPE_CLS[t] || '' }
    function safeQuestionContent(value) { return window.safeQuestionHtml ? window.safeQuestionHtml(value) : '' }

    async function load() {
      loadError.value = ''
      try {
        const { data: q } = await questionsAPI.get(route.params.id)
        if (q.success) question.value = q.data
        const { data: s } = await questionsAPI.getSubQuestions(route.params.id)
        // 后端返回 data: {question_id, question_type, sub_questions: [...]}（对象而非数组）
        if (s.success) subs.splice(0, subs.length, ...(s.data?.sub_questions || []))
      } catch (e) { loadError.value = '加载失败：' + (e?.message || '网络错误') }
    }

    async function addSub() {
      msg.value = ''
      try {
        const { data } = await questionsAPI.addSubQuestion(route.params.id, { ...newSub })
        if (data.success) {
          newSub.content = ''; newSub.answer = ''; newSub.options = ''; newSub.score = 1
          msg.value = '添加成功'; msgType.value = 'text-green-600'
          await load()
        } else {
          msg.value = data.message; msgType.value = 'text-red-600'
        }
      } catch (e) { msg.value = '添加失败'; msgType.value = 'text-red-600' }
    }

    async function deleteSub(subId) {
      if (!confirm('确定删除？')) return
      try {
        await questionsAPI.deleteSubQuestion(route.params.id, subId)
        await load()
      } catch (e) { alert('删除失败') }
    }

    Vue.onMounted(load)
    return { question, subs, newSub, msg, msgType, loadError, subTypes: TYPE_MAP, typeLabel, typeClass, safeQuestionContent, addSub, deleteSub }
  }
}

// 导出到 window（供 router.js loadComponent 按名解析）
window.AdminSubQuestions = AdminSubQuestions;
