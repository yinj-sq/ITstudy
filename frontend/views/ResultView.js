/* ResultView.js — 考试结果查看页面 */
const ResultView = {
  template: `
    <div class="max-w-4xl mx-auto px-4 py-8">
      <LoadingSpinner v-if="loading" />
      <template v-else-if="error">
        <div class="bg-white rounded-lg shadow p-8 text-center">
          <i class="fas fa-exclamation-triangle text-4xl text-yellow-500 mb-3"></i>
          <p class="text-gray-700 mb-4">{{ error }}</p>
          <div class="flex justify-center space-x-3">
            <router-link to="/exams" class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm">返回考试列表</router-link>
            <router-link to="/trend" class="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 text-sm">查看成绩趋势</router-link>
          </div>
        </div>
      </template>
      <template v-else-if="result">
        <div class="bg-white rounded-lg shadow p-6 mb-6">
          <div class="flex items-center justify-between">
            <div>
              <h2 class="text-2xl font-bold text-gray-800">{{ exam?.name }}</h2>
              <p class="text-gray-500 mt-1">提交时间: {{ result.submit_time }}</p>
            </div>
            <div class="text-center">
              <div class="text-4xl font-bold" :class="scoreColor">{{ result.total_score }}</div>
              <div class="text-sm text-gray-500">总分</div>
            </div>
          </div>
          <!-- 批改状态提示条（与 SSR 版 result.html 同语义） -->
          <div v-if="gradingPending"
            class="mt-4 bg-yellow-50 border border-yellow-200 text-yellow-800 rounded-lg px-4 py-3 text-sm">
            <i class="fas fa-hourglass-half mr-2"></i>含人工批改题目，教师批改完成后分数可能有变化，请稍后刷新查看。
          </div>
        </div>

        <div v-if="questions.length" class="space-y-4">
          <div v-for="(q, idx) in questions" :key="q.id"
            class="bg-white rounded-lg shadow p-5">
            <div class="flex items-start justify-between mb-3">
              <div>
                <span class="text-sm font-medium px-2 py-0.5 rounded mr-2" :class="typeBadgeClass(q.question_type)">{{ typeLabel(q.question_type) }}</span>
                <span class="text-gray-500 text-sm">{{ q.score }} 分</span>
              </div>
              <span class="font-bold" :class="getQuestionScore(q.id) >= q.score ? 'text-green-600' : 'text-red-600'">
                {{ getQuestionScore(q.id) }} / {{ q.score }}
              </span>
            </div>
            <QuestionCard :question="q" :show-answer="true" :user-answer="getUserAnswer(q.id)" :score="getQuestionScore(q.id)" :question-index="idx + 1" :sub-answers="getSubAnswers(q.id)" :sub-scores="getSubScores(q.id)" />
          </div>
        </div>

        <div class="mt-6 flex space-x-3">
          <router-link to="/exams" class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">返回考试列表</router-link>
          <router-link to="/trend" class="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200">查看成绩趋势</router-link>
        </div>
      </template>
    </div>
  `,
  setup() {
    const route = VueRouter.useRoute()
    const result = Vue.ref(null)
    const exam = Vue.ref(null)
    const questions = Vue.ref([])
    const userAnswers = Vue.reactive({})
    const scores = Vue.reactive({})
    const pythonFiles = Vue.reactive({})
    const loading = Vue.ref(true)
    const error = Vue.ref('')

    const scoreColor = Vue.computed(() => {
      const s = result.value?.total_score || 0
      if (s >= 80) return 'text-green-600'
      if (s >= 60) return 'text-yellow-600'
      return 'text-red-600'
    })

    const TYPE_MAP = { single: '单选题', multiple: '多选题', judge: '判断题', fill: '填空题', python_fill: 'Python填空题', comprehensive: '综合题' }
    const TYPE_CLASS = { single: 'bg-blue-100 text-blue-700', multiple: 'bg-purple-100 text-purple-700', judge: 'bg-green-100 text-green-700', fill: 'bg-orange-100 text-orange-700', python_fill: 'bg-cyan-100 text-cyan-700', comprehensive: 'bg-indigo-100 text-indigo-700' }

    function typeLabel(t) { return TYPE_MAP[t] || t }
    function typeBadgeClass(t) { return TYPE_CLASS[t] || '' }
    function safeQuestionContent(value) { return window.safeQuestionHtml ? window.safeQuestionHtml(value) : '' }
    function getUserAnswer(qid) {
      // Python 填空题优先展示上传的 .py 文件内容
      const fileInfo = pythonFiles[qid] || pythonFiles[String(qid)]
      if (fileInfo && fileInfo.file_content) return fileInfo.file_content
      return userAnswers[qid] || userAnswers[String(qid)] || ''
    }
    function getQuestionScore(qid) { return parseFloat(scores[qid] || scores[String(qid)] || 0) }
    // 综合题子题作答/得分：后端以 'sub_<id>' 为键存于 answers/scores
    function getSubAnswers(qid) {
      const out = {}
      const q = questions.value.find((item) => String(item.id) === String(qid))
      for (const sub of (q && q.sub_questions) || []) {
        const key = 'sub_' + sub.id
        if (userAnswers[key] !== undefined) out[sub.id] = userAnswers[key]
      }
      return out
    }
    function getSubScores(qid) {
      const out = {}
      const q = questions.value.find((item) => String(item.id) === String(qid))
      for (const sub of (q && q.sub_questions) || []) {
        const key = 'sub_' + sub.id
        if (scores[key] !== undefined) out[sub.id] = parseFloat(scores[key] || 0)
      }
      return out
    }

    async function loadResult() {
      error.value = ''
      try {
        const { data } = await resultsAPI.get(route.params.id)
        if (data.success) {
          result.value = data.data.result
          exam.value = data.data.exam
          questions.value = data.data.questions || []
          Object.assign(userAnswers, data.data.answers || {})
          Object.assign(scores, data.data.scores || {})
          Object.assign(pythonFiles, data.data.python_files || {})
        } else {
          // 后端返回 success=false（如成绩未公布 403）时给出明确提示
          error.value = data.message || '无法查看该考试结果'
        }
      } catch (e) {
        console.error('加载结果失败', e)
        error.value = e.response?.data?.message || '加载失败，请检查网络连接'
      }
      finally { loading.value = false }
    }

    Vue.onMounted(loadResult)
    const gradingPending = Vue.computed(() =>
      result.value?.grading_status === 'pending_review'
    )

    return { result, exam, questions, userAnswers, scores, pythonFiles, loading, error, scoreColor, gradingPending, typeLabel, typeBadgeClass, safeQuestionContent, getUserAnswer, getQuestionScore, getSubAnswers, getSubScores }
  }
}

// 导出到 window（供 router.js loadComponent 按名解析）
window.ResultView = ResultView;
