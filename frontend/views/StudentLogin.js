/* StudentLogin.js — 学生登录页面 */
const StudentLogin = {
  template: `
    <div class="min-h-screen flex items-center justify-center bg-gray-100 px-4">
      <div class="w-full max-w-md bg-white rounded-lg shadow-lg p-8">
        <div class="text-center mb-6">
          <h1 class="text-2xl font-bold text-blue-600">学科教学及测试平台</h1>
          <p class="text-gray-500 mt-2">请使用学号（或姓名）+ 密码登录</p>
        </div>
        <form @submit.prevent="handleLogin" class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">学号 / 姓名</label>
            <input v-model="form.account" type="text" required
              class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              placeholder="请输入学号或姓名" />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">密码</label>
            <input v-model="form.password" type="password" required
              class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              placeholder="请输入密码" />
          </div>
          <div v-if="error" class="text-red-600 text-sm bg-red-50 p-2 rounded">{{ error }}</div>
          <button type="submit" :disabled="loading || countdown.remaining > 0"
            class="w-full py-2 px-4 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 transition">
            {{ countdown.remaining > 0 ? ('请等待 ' + countdown.remaining + ' 秒') : (loading ? '登录中...' : '登录') }}
          </button>
        </form>
      </div>
    </div>
  `,
  setup() {
    const form = Vue.reactive({ account: '', password: '' })
    const loading = Vue.ref(false)
    const error = Vue.ref('')
    const countdown = window.useLoginCountdown(error)
    const router = VueRouter.useRouter()

    async function handleLogin() {
      if (countdown.remaining.value > 0) return
      loading.value = true
      error.value = ''
      // 复用全局 auth 单例（window._appAuth），登录成功后 user 状态即时同步，
      // 路由守卫无需再等 /auth/status 兜底
      const auth = window._appAuth || null
      try {
        const isNumeric = /^\d+$/.test(form.account)
        const payload = isNumeric
          ? { student_number: form.account, password: form.password }
          : { name: form.account, password: form.password }
        const data = auth ? await auth.login(payload) : (await authAPI.login(payload)).data
        if (data && data.success) {
          countdown.reset()
          // 强制首登改密（共享初始密码）：跳转 HTML 改密页完成改密
          // （SPA 无改密路由；此前 SPA 登录无视该标志可绕过强制改密）
          if (data.data && data.data.must_change_password) {
            window.location.href = '/change-password'
            return
          }
          router.push('/exams')
        } else {
          error.value = (data && data.message) || '登录失败'
        }
      } catch (e) {
        const msg = (auth && auth.error && auth.error.value) || e.response?.data?.message || '网络错误'
        if (!countdown.start(msg)) error.value = msg
      } finally {
        loading.value = false
      }
    }

    return { form, loading, error, countdown, handleLogin }
  }
}

// 导出到 window（供 router.js loadComponent 按名解析）
window.StudentLogin = StudentLogin;
