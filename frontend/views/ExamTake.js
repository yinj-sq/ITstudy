/* ExamTake.js — 在线考试答题页面（核心页面）*/
const ExamTake = {
  template: `
    <div class="max-w-4xl mx-auto px-4 py-8">
      <div v-if="loading"><LoadingSpinner /></div>
      <template v-else-if="error">
        <div class="bg-white rounded-lg shadow p-8 text-center">
          <i class="fas fa-exclamation-triangle text-4xl text-yellow-500 mb-3"></i>
          <p class="text-gray-700 mb-4">{{ error }}</p>
          <div class="flex justify-center space-x-3">
            <button @click="loadExam" class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm">重新加载</button>
            <router-link to="/exams" class="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 text-sm">返回考试列表</router-link>
          </div>
        </div>
      </template>
      <template v-else-if="exam">
        <div class="bg-white rounded-lg shadow p-6 mb-6">
          <div class="flex items-center justify-between">
            <h2 class="text-xl font-bold text-gray-800">{{ exam.name }}</h2>
            <div class="flex items-center space-x-4">
              <span v-if="timeLeftText" class="text-sm font-medium px-3 py-1 rounded"
                :class="timeLeftText.indexOf('时间到') === 0 ? 'bg-red-100 text-red-700' : 'bg-gray-100 text-gray-700'">
                {{ timeLeftText }}
              </span>
              <span class="text-sm text-gray-500">第 {{ currentQuestion.seq || (currentIndex + 1) }} 题 / 共 {{ questions.length }} 题</span>
              <span class="text-sm font-medium px-3 py-1 rounded" :class="progressColor">
                进度: {{ answeredCount }} / {{ questions.length }}
              </span>
            </div>
          </div>
          <div class="w-full bg-gray-200 rounded-full h-2 mt-3">
            <div class="bg-blue-600 h-2 rounded-full transition-all" :style="{ width: progressPercent + '%' }"></div>
          </div>
        </div>

        <div v-if="questions.length" class="space-y-6">
          <div class="bg-white rounded-lg shadow p-6">
            <div class="flex items-start mb-4">
              <span class="text-sm font-medium px-2 py-1 rounded mr-3" :class="typeBadgeClass(currentQuestion.question_type)">
                {{ typeLabel(currentQuestion.question_type) }}
              </span>
              <span class="text-gray-500 text-sm">分值: {{ currentQuestion.score }} 分</span>
            </div>

            <!-- 题目内容 -->
            <div class="text-gray-800 mb-6" v-html="safeQuestionContent(currentQuestion.content)"></div>
            <div v-if="currentQuestion.image_url" class="mb-4">
              <img :src="currentQuestion.image_url" alt="题目图片" class="img-fluid rounded" style="max-height:300px;">
            </div>

            <!-- 综合题背景（SSR 考试页向学生渲染，SPA 同口径展示） -->
            <div v-if="currentQuestion.question_type === 'comprehensive' && currentQuestion.background" class="bg-gray-50 p-4 rounded mb-4 text-sm text-gray-600">
              {{ currentQuestion.background }}
            </div>

            <!-- 单选/多选 -->
            <div v-if="['single','multiple'].includes(currentQuestion.question_type)" class="space-y-3">
              <div v-for="(opt, idx) in parsedOptions" :key="idx"
                class="p-3 border rounded-lg cursor-pointer transition hover:border-blue-400"
                :class="isOptionSelected(idx) ? 'border-blue-500 bg-blue-50' : 'border-gray-200'"
                @click="selectOption(idx)">
                <span class="font-medium text-gray-600 mr-2">{{ optionLetter(idx) }}.</span>
                <span>{{ opt }}</span>
                <img v-if="optionImage(currentQuestion, idx, opt)" :src="optionImage(currentQuestion, idx, opt)"
                  alt="选项图片" class="img-fluid mt-1 rounded" style="max-height:150px;">
              </div>
            </div>

            <!-- 判断题 -->
            <div v-if="currentQuestion.question_type === 'judge'" class="flex space-x-4">
              <button v-for="val in ['true','false']" :key="val"
                class="px-6 py-2 rounded-lg border transition"
                :class="currentAnswer === val ? 'border-blue-500 bg-blue-50 text-blue-700' : 'border-gray-300'"
                @click="currentAnswer = val">{{ val === 'true' ? '正确' : '错误' }}</button>
            </div>

            <!-- 填空题 -->
            <div v-if="currentQuestion.question_type === 'fill'" class="space-y-2">
              <input v-model="currentAnswer" type="text" placeholder="多个填空用 | 分隔"
                class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500" />
            </div>

            <!-- 简答题（主题型）：此前 SPA 无作答控件，该题只显示题干，
                 交卷按未作答处理且无提示；SSR 考试页有同型 textarea -->
            <div v-if="currentQuestion.question_type === 'short_answer'" class="space-y-2">
              <textarea v-model="currentAnswer" rows="5" placeholder="请在此作答..."
                class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"></textarea>
              <p class="text-sm text-gray-500">简答题提交后由教师批改评分</p>
            </div>

            <!-- Python 填空题 -->
            <div v-if="currentQuestion.question_type === 'python_fill'" class="space-y-4">
              <div class="bg-gray-900 text-green-400 p-4 rounded-lg font-mono text-sm overflow-auto">
                <pre>{{ currentQuestion.content.replace(/<[^>]+>/g, '') }}</pre>
              </div>
              <p class="text-sm text-gray-500">请编辑填空区域，或下载 .py 文件修改后上传</p>
              <div class="flex space-x-3">
                <a :href="'/download_python_file/' + currentQuestion.id"
                  class="px-4 py-2 bg-gray-100 border rounded-lg text-sm hover:bg-gray-200">下载 .py 文件</a>
                <FileUploader :accept="'.py'" :upload-url="'/upload_python_answer'"
                  :extra-fields="{ question_id: currentQuestion.id }"
                  @uploaded="onPythonUpload" />
              </div>
            </div>

            <!-- 综合题子题 -->
            <div v-if="currentQuestion.question_type === 'comprehensive' && currentQuestion.sub_questions" class="mt-6 space-y-6">
              <div v-for="(sub, idx) in currentQuestion.sub_questions" :key="sub.id"
                class="border-l-4 border-blue-300 pl-4">
                <span class="text-xs text-blue-500 font-medium">{{ idx + 1 }}. {{ typeLabel(sub.question_type) }} ({{ sub.score }}分)</span>
                <div class="text-gray-700 mt-1" v-html="safeQuestionContent(sub.content)"></div>
                <div v-if="sub.image_url" class="mt-1">
                  <img :src="sub.image_url" alt="子题图片" class="img-fluid rounded" style="max-height:250px;">
                </div>
                <div v-if="['single','multiple'].includes(sub.question_type)" class="mt-2 space-y-1">
                  <div v-for="(opt, oidx) in parseSubOptions(sub)" :key="oidx"
                    class="text-sm p-2 rounded cursor-pointer"
                    :class="isSubOptionSelected(sub, optionLetter(oidx)) ? 'bg-blue-100 text-blue-700' : ''"
                    @click="setSubAnswer(sub, optionLetter(oidx))">
                    {{ optionLetter(oidx) }}. {{ opt }}
                    <img v-if="optionImage(sub, oidx, opt)" :src="optionImage(sub, oidx, opt)"
                      alt="选项图片" class="img-fluid mt-1 rounded" style="max-height:120px;">
                  </div>
                </div>
                <input v-else-if="sub.question_type === 'fill'" v-model="subAnswers[sub.id]" type="text"
                  class="mt-1 w-full px-3 py-1 border border-gray-300 rounded text-sm" placeholder="多个填空用 | 分隔" />
                <!-- 判断小题：对/错按钮，选中态高亮；提交值 true/false 与 HTML 版一致 -->
                <div v-else-if="sub.question_type === 'judge'" class="mt-2 flex space-x-2">
                  <button v-for="val in ['true','false']" :key="val"
                    class="px-4 py-1 text-sm rounded-lg border transition"
                    :class="subAnswers[sub.id] === val ? 'border-blue-500 bg-blue-100 text-blue-700' : 'border-gray-300'"
                    @click="setSubAnswer(sub, val)">{{ val === 'true' ? '正确' : '错误' }}</button>
                </div>
                <!-- 简答小题：文本域作答 -->
                <textarea v-else-if="sub.question_type === 'short_answer'" v-model="subAnswers[sub.id]" rows="4"
                  class="mt-1 w-full px-3 py-1 border border-gray-300 rounded text-sm" placeholder="请在此作答..."></textarea>
              </div>
            </div>
            <!-- 综合题结尾说明 / 参考代码 -->
            <div v-if="currentQuestion.question_type === 'comprehensive' && currentQuestion.footer_content"
              class="mt-4 p-4 bg-gray-50 border rounded text-sm text-gray-700 whitespace-pre-wrap">{{ currentQuestion.footer_content }}</div>
          </div>

          <!-- 导航按钮 -->
          <div class="flex justify-between items-center">
            <button @click="prevQuestion" :disabled="currentIndex === 0"
              class="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 disabled:opacity-50">
              上一题
            </button>
            <div class="flex space-x-1 flex-wrap">
              <button v-for="(q, idx) in questions" :key="q.id"
                @click="currentIndex = idx"
                class="w-8 h-8 text-xs rounded"
                :class="getQuestionBtnClass(idx)"
                :title="typeLabel(q.question_type) + ' · 第' + (q.seq || (idx+1)) + '题'">
                {{ q.seq || (idx + 1) }}
              </button>
            </div>
            <button v-if="currentIndex < questions.length - 1" @click="nextQuestion"
              class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">下一题</button>
            <button v-else @click="submitExam" :disabled="submitting"
              class="px-6 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed">
              {{ submitting ? '提交中...' : '提交试卷' }}
            </button>
          </div>
        </div>
        <EmptyState v-else message="该试卷暂无题目" />
      </template>
    </div>
  `,
  setup() {
    const route = VueRouter.useRoute()
    const router = VueRouter.useRouter()
    const exam = Vue.ref(null)
    const questions = Vue.ref([])
    const currentIndex = Vue.ref(0)
    const answers = Vue.reactive({})
    const subAnswers = Vue.reactive({})
    const loading = Vue.ref(true)
    const error = Vue.ref('')
    const submitting = Vue.ref(false)
    const pythonUploaded = Vue.reactive({})
    // 考试倒计时与强制收卷（与 HTML 考试页语义一致）：
    // 以服务端开考时间为基准，刷新不重置；到点/收卷自动提交并锁定。
    const timeLeftText = Vue.ref('')
    let examTimer = null
    let examPollTimer = null
    let examSSE = null
    let examLocked = false

    function formatTimeLeft(ms) {
      if (ms <= 0) return ''
      const s = Math.floor(ms / 1000)
      const h = Math.floor(s / 3600)
      const m = Math.floor((s % 3600) / 60)
      const sec = s % 60
      return (h > 0 ? h + ':' : '') + (m < 10 && h > 0 ? '0' : '') + m + ':' + (sec < 10 ? '0' : '') + sec
    }

    function startExamTimer() {
      if (examTimer || !exam.value) return
      const durationMin = parseInt(exam.value.duration || 0, 10)
      const startSec = parseFloat(exam.value.exam_start_time || 0)
      if (!durationMin || !startSec) return
      const endTime = startSec * 1000 + durationMin * 60 * 1000
      function tick() {
        const left = endTime - Date.now()
        if (left <= 0) {
          timeLeftText.value = '时间到！'
          clearInterval(examTimer)
          examTimer = null
          lockAndSubmit()
          return
        }
        timeLeftText.value = '剩余 ' + formatTimeLeft(left)
      }
      tick()
      examTimer = setInterval(tick, 1000)
    }

    function lockAndSubmit() {
      if (examLocked || submitting.value) return
      examLocked = true
      // 自动交卷（超时/收卷）传 force=true 跳过 confirm：
      // 后台标签页的 confirm() 被浏览器抑制直接返回 false，
      // 此前会导致到点不交卷、答案永久丢失（只能手动重试）
      submitExam(true)
    }

    // 收卷通知：5s 轮询（状态端点 2s TTL 缓存、零 DB 命中）。不再使用
    // SSE——Waitress 一线程一连接模型下，N 名学生 × 300s 常驻连接会
    // 耗尽 48 线程池（250 人考试时交卷/心跳排队）。
    function startCollectionPolling() {
      if (examPollTimer || !exam.value) return
      function checkCollected() {
        if (examLocked || submitting.value) return
        axios.get('/exam/' + exam.value.id + '/status', { withCredentials: true })
          .then(function (resp) {
            if (resp.data && resp.data.is_collected) {
              clearInterval(examPollTimer); examPollTimer = null
              lockAndSubmit()
            }
          })
          .catch(function () { /* 网络错误忽略，下次重试 */ })
      }
      examPollTimer = setInterval(checkCollected, 5000)
    }

    // 组件卸载时清理定时器：防止离开考试页后计时/轮询继续运行
    // （每秒 tick 可能触发异常提交、每 5s 泄漏网络请求、多次进出累积实例）
    Vue.onUnmounted(function () {
      if (examTimer) { clearInterval(examTimer); examTimer = null }
      if (examPollTimer) { clearInterval(examPollTimer); examPollTimer = null }
    })

    const currentQuestion = Vue.computed(() => questions.value[currentIndex.value] || {})

    // 进度统计：覆盖单选/多选/判断/填空（answers）、
    // Python填空题（上传标记 pythonUploaded）、综合题（子题答案 subAnswers）
    const answeredCount = Vue.computed(() => {
      return questions.value.filter((q) => {
        if (answers[q.id] !== undefined && answers[q.id] !== '') return true
        if (q.question_type === 'python_fill') return !!pythonUploaded[q.id]
        if (q.question_type === 'comprehensive') {
          const subs = q.sub_questions || []
          if (!subs.length) return true
          return subs.every((sub) => subAnswers[sub.id] !== undefined && subAnswers[sub.id] !== '')
        }
        return false
      }).length
    })
    const progressPercent = Vue.computed(() =>
      questions.value.length ? Math.round(answeredCount.value / questions.value.length * 100) : 0
    )
    const progressColor = Vue.computed(() =>
      progressPercent.value === 100 ? 'bg-green-100 text-green-700' : 'bg-blue-100 text-blue-700'
    )

    const parsedOptions = Vue.computed(() => {
      const q = currentQuestion.value
      if (!q || !q.options) return []
      if (typeof q.options === 'string') return q.options.split('|').map(o => stripOptionPrefix(o))
      return q.options
    })

    // 后端 normalize_options 统一存为 "A.选项|B.选项" 带字母前缀格式，
    // 模板已单独渲染字母（optionLetter），此处剥离前缀避免 "A. A.选项" 重复
    function stripOptionPrefix(opt) {
      const m = String(opt || '').trim().match(/^([A-Za-z])\s*[.:、)）\]】\-]\s*(.*)$/s)
      if (m) return m[2].trim()
      return String(opt || '').trim()
    }

    const currentAnswer = Vue.computed({
      get: () => answers[currentQuestion.value.id] || (currentQuestion.value.question_type === 'judge' ? '' : ''),
      set: (val) => { answers[currentQuestion.value.id] = val }
    })

    const TYPE_MAP = { single: '单选题', multiple: '多选题', judge: '判断题', fill: '填空题', short_answer: '简答题', python_fill: 'Python填空题', comprehensive: '综合题' }
    const TYPE_CLASS = { single: 'bg-blue-100 text-blue-700', multiple: 'bg-purple-100 text-purple-700', judge: 'bg-green-100 text-green-700', fill: 'bg-orange-100 text-orange-700', short_answer: 'bg-pink-100 text-pink-700', python_fill: 'bg-cyan-100 text-cyan-700', comprehensive: 'bg-indigo-100 text-indigo-700' }

    function typeLabel(t) { return TYPE_MAP[t] || t }
    function typeBadgeClass(t) { return TYPE_CLASS[t] || '' }
    // 净化组件缺失时回退显示原文（题目内容来自教师端可信源，
    // 保证学生能看到题干），并给出控制台告警便于排查
    function safeQuestionContent(value) {
      if (window.safeQuestionHtml) return window.safeQuestionHtml(value)
      console.warn('[ExamTake] safeQuestionHtml 未加载，题目内容未净化')
      return value || ''
    }
    function optionLetter(idx) { return String.fromCharCode(65 + idx) }

    // 选项图片：兼容按字母（A/B/...）或按选项文本存储的两种历史编码
    function optionImage(question, idx, opt) {
      const map = question && question.image_options
      if (!map || typeof map !== 'object') return ''
      const letter = optionLetter(idx)
      return map[letter] || map[String(opt || '').trim()] || ''
    }

    async function loadExam() {
      const id = route.params.id
      loading.value = true
      error.value = ''
      try {
        const { data } = await examsAPI.get(id)
        if (data.already_submitted) {
          // 已提交过：跳转结果页，避免重复看到答题界面
          if (data.result_id) {
            router.push('/result/' + data.result_id)
            return
          }
          error.value = data.message || '您已提交过该试卷'
        } else if (data.success) {
          exam.value = data.data
          // 超时结束（开考后弃考/断网，超过 时长+宽限）：服务端提交通道
          // 已关闭，直接提示而非渲染倒计时归零→自动交卷→403 报错循环
          if (data.data.exam_ended) {
            error.value = '考试时间已结束，无法继续作答；如需重考请联系教师'
            return
          }
          // 已收卷试卷：从未开考的学生禁止进入作答界面（后端提交通道已
          // 关闭，放进去学生白答一场）。收卷时在考的学生（服务端返回其
          // 真实开考时间）放行——收卷轮询 5s 内自动交卷，submit_exam 收卷
          // 分支在宽限内接受其提交，与 SSR 通道行为一致（此前一律拦截，
          // 学生刷新后无法补交已作答内容，答卷丢失）
          if (data.data.is_collected && !data.data.exam_start_time) {
            error.value = '该试卷已收卷，无法继续作答'
            return
          }
          // 外链试卷（卷内首题为 link 型）：SPA 无作答控件（与 SSR 一致
          // 不渲染答题页），从列表进入应走"打开链接"；直连 URL 时明确提示
          if (((data.data.questions || [])[0] || {}).question_type === 'link') {
            error.value = '该试卷为外链形式，请返回考试列表点击"打开链接"作答'
            return
          }
          questions.value = data.data.questions || []
          startExamTimer()
          startCollectionPolling()
        } else {
          error.value = data.message || '试卷加载失败'
        }
      } catch (e) {
        console.error('加载试卷失败', e)
        error.value = e.response?.data?.message || '试卷加载失败，请检查网络连接或确认考试存在'
      }
      finally { loading.value = false }
    }

    function parseSubOptions(sub) {
      if (!sub.options) return []
      if (typeof sub.options === 'string') return sub.options.split('|').map(o => stripOptionPrefix(o))
      return sub.options
    }

    function selectOption(idx) {
      const letter = optionLetter(idx)
      if (currentQuestion.value.question_type === 'multiple') {
        const current = (answers[currentQuestion.value.id] || '').split('|').filter(Boolean)
        const pos = current.indexOf(letter)
        if (pos >= 0) current.splice(pos, 1)
        else current.push(letter)
        answers[currentQuestion.value.id] = current.join('|')
      } else {
        answers[currentQuestion.value.id] = letter
      }
    }

    function isOptionSelected(idx) {
      const ans = answers[currentQuestion.value.id] || ''
      const letter = optionLetter(idx)
      return ans.split('|').includes(letter)
    }

    function getSubAnswer(subId) { return subAnswers[subId] || '' }
    // 子题答题：多选为 toggle 模式（用 | 分隔存储，与主题目多选一致），单选为赋值。
    function setSubAnswer(sub, val) {
      if (sub.question_type === 'multiple') {
        const current = (subAnswers[sub.id] || '').split('|').filter(Boolean)
        const pos = current.indexOf(val)
        if (pos >= 0) current.splice(pos, 1)
        else current.push(val)
        subAnswers[sub.id] = current.join('|')
      } else {
        subAnswers[sub.id] = val
      }
    }
    function isSubOptionSelected(sub, val) {
      if (sub.question_type === 'multiple') {
        return (subAnswers[sub.id] || '').split('|').indexOf(val) !== -1
      }
      return getSubAnswer(sub.id) === val
    }

    function getQuestionBtnClass(idx) {
      const base = 'transition'
      if (idx === currentIndex.value) return base + ' bg-blue-600 text-white'
      if (isQuestionAnswered(questions.value[idx])) return base + ' bg-green-200 text-green-700'
      return base + ' bg-gray-100 text-gray-500'
    }

    function nextQuestion() { if (currentIndex.value < questions.value.length - 1) currentIndex.value++ }
    function prevQuestion() { if (currentIndex.value > 0) currentIndex.value-- }

    function onPythonUpload(resp, extraFields) {
      // 用上传请求附带的 question_id 标记（而非回调时的当前题）：
      // 上传耗时期间切题会把"已上传"误标到新题上
      const qid = extraFields && extraFields.question_id !== undefined
        ? extraFields.question_id
        : currentQuestion.value.id
      pythonUploaded[qid] = true
      // 上传成功（响应留待页面状态反映，不再打印响应细节）
    }

    function isQuestionAnswered(q) {
      if (answers[q.id] !== undefined && answers[q.id] !== '') return true
      if (q.question_type === 'python_fill') return !!pythonUploaded[q.id]
      if (q.question_type === 'comprehensive') {
        const subs = q.sub_questions || []
        if (!subs.length) return true
        return subs.every((sub) => subAnswers[sub.id] !== undefined && subAnswers[sub.id] !== '')
      }
      return false
    }

    async function submitExam(force) {
      // 手动点击需要确认；超时/收卷自动交卷（force=true）直接提交
      if (!force && !confirm('确定要提交试卷吗？提交后将无法修改答案。')) return
      submitting.value = true
      const allAnswers = { ...answers }
      Object.entries(subAnswers).forEach(([k, v]) => { allAnswers['sub_' + k] = v })
      try {
        // 该接口走根路径，未经过 apiClient；全局 axios 已带 CSRF 头，
        // 这里显式补 X-Requested-With 标识 AJAX（与 apiClient 行为一致）
        const { data } = await axios.post('/submit_exam/' + exam.value.id, allAnswers, { withCredentials: true, headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' } })
        if (data.success) {
          router.push('/result/' + data.result_id)
        } else {
          alert(data.message || '提交失败')
        }
      } catch (e) {
        // session 失效时跳转登录页（该接口走根路径，未经过 apiClient 的 401 拦截器）
        if (e.response?.status === 401) {
          router.push('/')
          return
        }
        alert('提交失败: ' + (e.response?.data?.message || e.message))
      } finally {
        submitting.value = false
      }
    }

    Vue.onMounted(loadExam)
    return {
      exam, questions, currentIndex, answers, subAnswers, loading, error, submitting,
      timeLeftText,
      currentQuestion, answeredCount, progressPercent, progressColor,
      parsedOptions, currentAnswer, pythonUploaded,
      typeLabel, typeBadgeClass, safeQuestionContent, optionLetter, optionImage, parseSubOptions,
      selectOption, isOptionSelected, getSubAnswer, setSubAnswer,
      getQuestionBtnClass, nextQuestion, prevQuestion, isQuestionAnswered,
      onPythonUpload, submitExam
    }
  }
}

// 导出到 window（供 router.js loadComponent 按名解析）
window.ExamTake = ExamTake;
