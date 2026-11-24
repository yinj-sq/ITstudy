/* AdminTrend.js — 成绩趋势分析 (集成 Chart.js) */
const AdminTrend = {
  template: `
    <div class="max-w-6xl mx-auto px-4 py-8">
      <LoadingSpinner v-if="loading" />
      <div v-else-if="loadError" class="bg-red-50 text-red-600 text-sm p-3 rounded-lg mb-4">
        <i class="fas fa-triangle-exclamation mr-1"></i>{{ loadError }}
      </div>
      <template v-else-if="data">
      <div v-if="chartError" class="bg-yellow-50 text-yellow-700 text-sm p-3 rounded-lg mb-4">
        <i class="fas fa-triangle-exclamation mr-1"></i>{{ chartError }}
      </div>

        <!-- 头部 -->
        <div class="flex flex-wrap items-center justify-between mb-6 gap-2">
          <div>
            <h2 class="text-2xl font-bold text-gray-800">{{ data.exam?.name }} - 成绩分析</h2>
            <p class="text-gray-500 text-sm">共 {{ totalCount }} 人提交</p>
          </div>
          <div class="flex gap-2 flex-wrap">
            <select v-model="classFilter" @change="loadData" class="px-3 py-2 border rounded-lg text-sm bg-white">
              <option value="">全部班级</option>
              <option v-for="c in data.available_classes" :key="c" :value="c">{{ c }}</option>
            </select>
            <a :href="'/admin/export_scores/' + examId" class="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 text-sm no-underline inline-flex items-center">
              <svg class="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
              导出Excel
            </a>
          </div>
        </div>

        <!-- 卡片网格：分数段分布 + 班级统计 -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
          <!-- 分数段柱状图 -->
          <div class="bg-white rounded-lg shadow p-5">
            <h3 class="text-sm font-semibold text-gray-600 mb-4">分数段分布</h3>
            <canvas ref="distChart" height="220"></canvas>
          </div>

          <!-- 分数段卡片 -->
          <div class="bg-white rounded-lg shadow p-5">
            <h3 class="text-sm font-semibold text-gray-600 mb-4">各段人数</h3>
            <div class="space-y-2">
              <div v-for="(label, idx) in binLabels" :key="idx" class="flex items-center">
                <span class="w-28 text-xs text-gray-500">{{ label.replace(/[\(\)]/g,'').replace('-','~') }}</span>
                <span class="flex-1 text-right font-bold mr-2" :class="['text-red-600','text-yellow-600','text-blue-600','text-green-600','text-emerald-700'][idx]">
                  {{ distValues[idx] || 0 }}人
                </span>
                <div class="flex-1 bg-gray-100 rounded-full h-4">
                  <div class="h-4 rounded-full transition-all" :class="['bg-red-400','bg-yellow-400','bg-blue-400','bg-green-400','bg-emerald-500'][idx]"
                    :style="{ width: maxDist ? (distValues[idx]||0)/maxDist*100 + '%' : '0%' }"></div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 班级统计表 -->
        <div v-if="Object.keys(data.class_stats||{}).length" class="bg-white rounded-lg shadow overflow-hidden mb-8">
          <div class="px-5 py-3 border-b">
            <h3 class="text-sm font-semibold text-gray-600">班级对比</h3>
          </div>
          <table class="min-w-full divide-y divide-gray-200">
            <thead class="bg-gray-50"><tr>
              <th class="px-4 py-3 text-left text-xs font-medium text-gray-500">班级</th>
              <th class="px-4 py-3 text-center text-xs font-medium text-gray-500">人数</th>
              <th class="px-4 py-3 text-center text-xs font-medium text-gray-500">平均分</th>
              <th class="px-4 py-3 text-center text-xs font-medium text-gray-500">最高</th>
              <th class="px-4 py-3 text-center text-xs font-medium text-gray-500">最低</th>
            </tr></thead>
            <tbody class="divide-y">
              <tr v-for="(stat, cls) in data.class_stats" :key="cls" class="hover:bg-gray-50">
                <td class="px-4 py-3 text-sm font-medium text-gray-800">{{ cls }}</td>
                <td class="px-4 py-3 text-sm text-center text-gray-600">{{ stat.count }}</td>
                <td class="px-4 py-3 text-sm text-center font-semibold" :class="stat.average >= 60 ? 'text-green-600' : 'text-red-600'">{{ stat.average }}</td>
                <td class="px-4 py-3 text-sm text-center text-green-600">{{ stat.max }}</td>
                <td class="px-4 py-3 text-sm text-center text-red-500">{{ stat.min }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 每题正确率 -->
        <div class="bg-white rounded-lg shadow overflow-hidden mb-8">
          <div class="px-5 py-3 border-b">
            <h3 class="text-sm font-semibold text-gray-600">逐题正确率</h3>
          </div>
          <div class="p-5 space-y-3">
            <div v-for="(qstat, idx) in qStats" :key="idx" class="flex items-center gap-3">
              <span class="w-16 text-xs text-gray-500 text-right">第{{ idx + 1 }}题</span>
              <div class="flex-1 bg-gray-100 rounded-full h-5">
                <div class="h-5 rounded-full text-xs text-white text-center leading-5 transition-all"
                  :class="qstat.correct_rate >= 70 ? 'bg-green-500' : qstat.correct_rate >= 40 ? 'bg-yellow-500' : 'bg-red-400'"
                  :style="{ width: Math.max(qstat.correct_rate, 8) + '%' }">{{ qstat.correct_rate }}%</div>
              </div>
            </div>
          </div>
        </div>

        <!-- 学生明细 -->
        <div v-if="data.student_details?.length" class="bg-white rounded-lg shadow overflow-hidden">
          <div class="px-5 py-3 border-b flex justify-between items-center">
            <h3 class="text-sm font-semibold text-gray-600">学生成绩明细</h3>
            <span class="text-xs text-gray-400">{{ data.student_details.length }} 人</span>
          </div>
          <div class="overflow-x-auto">
            <table class="min-w-full divide-y divide-gray-200 text-sm">
              <thead class="bg-gray-50"><tr>
                <th class="px-4 py-2 text-left text-xs font-medium text-gray-500">姓名</th>
                <th class="px-4 py-2 text-left text-xs font-medium text-gray-500">班级</th>
                <th class="px-4 py-2 text-left text-xs font-medium text-gray-500">总分</th>
                <th class="px-4 py-2 text-left text-xs font-medium text-gray-500">时间</th>
                <th class="px-4 py-2 text-left text-xs font-medium text-gray-500">操作</th>
              </tr></thead>
              <tbody class="divide-y">
                <tr v-for="(s, idx) in data.student_details.slice(0, 50)" :key="idx" class="hover:bg-gray-50">
                  <td class="px-4 py-2">{{ s.name }}</td>
                  <td class="px-4 py-2 text-gray-500">{{ s.class }}</td>
                  <td class="px-4 py-2 font-medium" :class="s.total_score >= 60 ? 'text-green-600' : 'text-red-600'">{{ s.total_score }}</td>
                  <td class="px-4 py-2 text-gray-500 text-xs">{{ s.submit_time }}</td>
                  <td class="px-4 py-2">
                    <button @click="deleteResult(s.result_id)" class="text-red-500 hover:text-red-700 text-xs">删除</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
      <EmptyState v-else message="暂无学生提交该试卷" />
    </div>
  `,
  setup() {
    const route = VueRouter.useRoute()
    const data = Vue.ref(null)
    const chartError = Vue.ref('')
    const loading = Vue.ref(true)
    const loadError = Vue.ref('')
    const classFilter = Vue.ref('')
    const distChart = Vue.ref(null)
    const examId = Vue.computed(() => route.params.examId)

    // 后端返回 distribution: [{label, count} x5]，前端转换为展示所需结构
    const binLabels = Vue.computed(() => {
      if (!data.value) return []
      return (data.value.distribution || []).map(d => d.label || '')
    })
    const distValues = Vue.computed(() => {
      if (!data.value) return []
      return (data.value.distribution || []).map(d => d.count || 0)
    })
    const qStats = Vue.computed(() => data.value?.question_stats || [])
    const totalCount = Vue.computed(() => data.value?.student_details?.length || 0)

    const maxDist = Vue.computed(() => {
      return Math.max(...(distValues.value.length ? distValues.value : [0]), 1)
    })

    let chartInstance = null

    // Chart.js 按需加载：此前所有 SPA 页面启动即加载 208KB 图表库，
    // 仅趋势页使用（index.html 不再把 chart_js 列入启动必等库）。
    // 进入本视图时经 resource-loader 多源回退加载，就绪后渲染图表。
    function ensureChart() {
      // Chart.js 按需多源加载。此前 tryLoad 无限重试永不 resolve：离线部署
      // CDN 全挂时 loading 永久转圈 + setTimeout 链无限自续——加最大等待
      // 次数，超时正常 resolve，由 loadData 判 Chart 缺失给出明确错误提示
      return new Promise((resolve) => {
        if (typeof Chart !== 'undefined') { resolve(); return; }
        let attempts = 0;
        const MAX_ATTEMPTS = 40;  // ~20s（间隔 100-500ms 递增）
        const tryLoad = () => {
          if (typeof Chart !== 'undefined' || attempts >= MAX_ATTEMPTS) { resolve(); return; }
          attempts += 1;
          const delay = Math.min(100 * attempts, 500);
          if (window.resourceLoader && typeof window.resourceLoader.tryLoadByType === 'function') {
            window.resourceLoader.tryLoadByType('chart_js')
              .then(() => (typeof Chart !== 'undefined') ? resolve() : setTimeout(tryLoad, delay))
              .catch(() => setTimeout(tryLoad, delay));
          } else {
            setTimeout(tryLoad, delay);
          }
        };
        tryLoad();
      });
    }

    function renderChart() {
      if (!data.value || !distChart.value) return
      if (chartInstance) chartInstance.destroy()
      const ctx = distChart.value.getContext('2d')
      const labels = binLabels.value.map(l => l.replace(/[\(\)]/g, '').replace('-', '~'))
      const values = distValues.value
      const bgColors = ['rgba(220,38,38,0.6)', 'rgba(202,138,4,0.6)', 'rgba(37,99,235,0.6)', 'rgba(22,163,74,0.6)', 'rgba(4,120,87,0.6)']
      const borderColors = ['#dc2626', '#ca8a04', '#2563eb', '#16a34a', '#047857']

      chartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: labels,
          datasets: [{
            label: '人数',
            data: values,
            backgroundColor: bgColors,
            borderColor: borderColors,
            borderWidth: 1,
            borderRadius: 4,
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: { callbacks: { label: ctx => ctx.raw + ' 人' } }
          },
          scales: {
            y: {
              beginAtZero: true,
              ticks: { stepSize: 1, precision: 0 },
              grid: { color: '#f3f4f6' }
            },
            x: { grid: { display: false } }
          }
        }
      })
    }

    async function loadData() {
      await ensureChart()
      chartError.value = (typeof Chart === 'undefined')
        ? '图表组件加载失败（离线部署请检查本地静态资源完整），下方数据列表仍可查看'
        : ''
      loading.value = true
      loadError.value = ''
      try {
        const params = {}
        if (classFilter.value) params.class_filter = classFilter.value
        const { data: resp } = await resultsAPI.trend(examId.value, params)
        if (resp.success) {
          // 0 提交的试卷后端返回 success+空对象——走 EmptyState 而非
          // 渲染"共 0 人提交"头部和全 0 图表（EmptyState v-else 永不触发）
          const empty = !(resp.data.student_details || []).length
          data.value = empty ? null : resp.data
          if (!empty && typeof Chart !== 'undefined') Vue.nextTick(() => renderChart())
        }
      } catch (e) { loadError.value = '加载失败：' + (e?.message || '网络错误') }
      finally { loading.value = false }
    }

    async function deleteResult(resultId) {
      if (!confirm('确定删除该学生的成绩吗？')) return
      try {
        const { data: resp } = await resultsAPI.delete(resultId)
        if (resp.success) await loadData()
        else alert(resp.message)
      } catch (e) { alert('删除失败') }
    }

    Vue.onMounted(loadData)
    // 组件卸载时销毁 Chart 实例，避免多次进出页面累积实例导致内存泄漏
    Vue.onUnmounted(() => {
      if (chartInstance) {
        chartInstance.destroy()
        chartInstance = null
      }
    })
    return { data, loading, loadError, chartError, classFilter, distChart, examId, binLabels, distValues, qStats, totalCount, maxDist, loadData, deleteResult }
  }
}

// 导出到 window（供 router.js loadComponent 按名解析）
window.AdminTrend = AdminTrend;
