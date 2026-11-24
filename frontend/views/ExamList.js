/* ExamList.js — 学生考试列表页面 */
const ExamList = {
  template: `
    <div class="max-w-4xl mx-auto px-4 py-8">
      <h2 class="text-2xl font-bold text-gray-800 mb-6">选择考试</h2>
      <LoadingSpinner v-if="loading" />
      <div v-else-if="error" class="bg-white rounded-lg shadow p-8 text-center">
        <p class="text-gray-700 mb-4">{{ error }}</p>
        <button @click="loadExams" class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm">重新加载</button>
      </div>
      <EmptyState v-else-if="!exams.length" message="暂无可用的考试" />
      <div v-else class="grid gap-4 md:grid-cols-2">
        <div v-for="exam in exams" :key="exam.id"
          class="bg-white rounded-lg shadow p-6 hover:shadow-md transition cursor-pointer"
          @click="enterExam(exam)">
          <h3 class="text-lg font-semibold text-gray-800">{{ exam.name }}</h3>
          <div class="flex items-center justify-between mt-4">
            <span class="text-sm text-gray-500">{{ exam.question_count || 0 }} 道题</span>
            <span v-if="exam.existing_result" class="text-xs bg-yellow-100 text-yellow-700 px-2 py-1 rounded">
              已提交<template v-if="exam.existing_result.total_score != null"> ({{ exam.existing_result.total_score }}分)</template>
            </span>
            <span v-else-if="exam.is_collected" class="text-xs bg-gray-100 text-gray-600 px-2 py-1 rounded">
              已收卷
            </span>
          </div>
          <div class="mt-4 flex space-x-2">
            <!-- 外链试卷：渲染"打开链接"新标签打开（与 SSR exam.html 同口径）；
                 此前 SPA 渲染成答题页，学生可提交一张 0 分卷 -->
            <a v-if="exam.is_link && exam.link_url && !isExamClosed(exam)"
              :href="exam.link_url" target="_blank" rel="noopener noreferrer" @click.stop
              class="flex-1 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm text-center no-underline">
              <i class="fas fa-external-link-alt mr-1"></i>打开链接
            </a>
            <button v-else-if="exam.existing_result && exam.allow_view_results" @click.stop="enterExam(exam)"
              class="flex-1 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm">
              查看结果
            </button>
            <!-- 成绩未公布（含待批改）：显示"成绩未公布"徽章，与 SSR 口径一致 -->
            <span v-else-if="exam.existing_result"
              class="flex-1 py-2 text-center text-sm bg-gray-100 text-gray-600 rounded-lg">
              成绩未公布
            </span>
            <button v-else @click.stop="enterExam(exam)"
              class="flex-1 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm"
              :class="{ 'opacity-50 cursor-not-allowed': isExamClosed(exam) }">
              {{ isExamClosed(exam) ? '已收卷' : '开始考试' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  `,
  setup() {
    const exams = Vue.reactive([])
    const loading = Vue.ref(true)
    const error = Vue.ref('')
    const router = VueRouter.useRouter()

    async function loadExams() {
      loading.value = true
      error.value = ''
      try {
        const { data } = await examsAPI.list()
        if (data.success) exams.splice(0, exams.length, ...(data.data || []))
        else error.value = data.message || '加载失败'
      } catch (e) {
        console.error('加载考试列表失败', e)
        error.value = '加载失败，请检查网络连接'
      } finally {
        loading.value = false
      }
    }

    function isExamClosed(exam) {
      // 已收卷且未提交：入口禁用（后端提交通道已关闭，放进去只会白答一场）
      return exam.is_collected && !exam.existing_result
    }

    function enterExam(exam) {
      if (isExamClosed(exam)) return
      // 外链试卷：新标签打开外链，不进入答题页（与 SSR 同口径）
      if (exam.is_link && exam.link_url && !exam.existing_result) {
        window.open(exam.link_url, '_blank', 'noopener')
        return
      }
      if (exam.existing_result) {
        router.push('/result/' + exam.existing_result.id)
      } else {
        router.push('/exam/' + exam.id)
      }
    }

    Vue.onMounted(loadExams)
    return { exams, loading, error, loadExams, enterExam, isExamClosed }
  }
}

// 导出到 window（供 router.js loadComponent 按名解析）
window.ExamList = ExamList;
