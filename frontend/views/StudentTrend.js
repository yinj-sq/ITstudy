/* StudentTrend.js — 学生个人成绩趋势 */
const StudentTrend = {
  template: `
    <div class="max-w-4xl mx-auto px-4 py-8">
      <h2 class="text-2xl font-bold text-gray-800 mb-6">我的成绩</h2>
      <LoadingSpinner v-if="loading" />
      <div v-else-if="loadError" class="bg-red-50 text-red-600 text-sm p-6 rounded-lg text-center">
        {{ loadError }}
        <button @click="loadTrend" class="block mx-auto mt-3 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm">重新加载</button>
      </div>
      <EmptyState v-else-if="!trendData.length" message="还没有参加过任何考试" />
      <div v-else>
        <div class="bg-white rounded-lg shadow overflow-hidden">
          <table class="min-w-full divide-y divide-gray-200">
            <thead class="bg-gray-50">
              <tr>
                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">试卷</th>
                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">成绩</th>
                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">提交时间</th>
                <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-200">
              <tr v-for="(row, idx) in trendData" :key="idx" class="hover:bg-gray-50">
                <td class="px-6 py-4 text-sm text-gray-800">{{ row.exam_name }}</td>
                <td class="px-6 py-4">
                  <span class="px-2 py-1 rounded text-sm font-medium"
                    :class="row.total_score >= 60 ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'">
                    {{ row.total_score }}
                  </span>
                </td>
                <td class="px-6 py-4 text-sm text-gray-500">{{ row.submit_time }}</td>
                <td class="px-6 py-4">
                  <router-link :to="'/result/' + row.result_id"
                    class="text-blue-600 hover:text-blue-800 text-sm">查看详情</router-link>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `,
  setup() {
    const trendData = Vue.reactive([])
    const loading = Vue.ref(true)
    const loadError = Vue.ref('')

    async function loadTrend() {
      try {
        const { data } = await resultsAPI.studentTrend('me')
        if (data.success) {
          const exams = data.data?.exam_results || {}
          const rows = []
          Object.entries(exams).forEach(([examId, info]) => {
            // 防御 info.scores 字段缺失导致 forEach 抛错
            const scores = info.scores || []
            const resultIds = info.result_ids || []
            scores.forEach((score, i) => {
              rows.push({
                exam_name: info.name,
                total_score: score,
                submit_time: (info.dates && info.dates[i]) || '-',
                result_id: resultIds[i] !== undefined ? resultIds[i] : null
              })
            })
          })
          trendData.splice(0, trendData.length, ...rows)
        }
      } catch (e) {
        // 错误态区分"加载失败"与"无数据"：此前 catch 仅 console.error，
        // 页面显示"还没有参加过任何考试"误导学生
        console.error('加载成绩趋势失败', e)
        loadError.value = '成绩趋势加载失败，请检查网络连接'
      } finally {
        loading.value = false
      }
    }

    Vue.onMounted(loadTrend)
    return { trendData, loading, loadError }
  }
}

// 导出到 window（供 router.js loadComponent 按名解析）
window.StudentTrend = StudentTrend;
