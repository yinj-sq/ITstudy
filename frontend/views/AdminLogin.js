/* AdminLogin.js — 管理员登录页面 */
const AdminLogin = {
  template: `
    <div class="min-h-screen flex items-center justify-center bg-gray-100 px-4">
      <div class="w-full max-w-md bg-white rounded-lg shadow-lg p-8">
        <div class="text-center mb-6">
          <h1 class="text-2xl font-bold text-blue-600">管理员登录</h1>
          <p class="text-gray-500 mt-2">请输入管理员账号和密码</p>
        </div>
        <form @submit.prevent="handleLogin" class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">用户名</label>
            <input v-model="form.username" type="text" required
              class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500" />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">密码</label>
            <input v-model="form.password" type="password" required
              class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500" />
          </div>
          <div v-if="error" class="text-red-600 text-sm bg-red-50 p-2 rounded">{{ error }}</div>
          <button type="submit" :disabled="loading || countdown.remaining > 0"
            class="w-full py-2 px-4 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 transition">
            {{ countdown.remaining > 0 ? ('请等待 ' + countdown.remaining + ' 秒') : (loading ? '登录中...' : '登录') }}
          </button>
        </form>
        <div class="text-center mt-4">
          <router-link to="/" class="text-blue-600 text-sm hover:underline">返回学生登录</router-link>
        </div>
      </div>
    </div>
  `,
  setup() {
    const form = Vue.reactive({ username: '', password: '' })
    const loading = Vue.ref(false)
    const error = Vue.ref('')
    const countdown = window.useLoginCountdown(error)
    const router = VueRouter.useRouter()

    async function handleLogin() {
      if (countdown.remaining.value > 0) return
      loading.value = true
      error.value = ''
      // 复用全局 auth 单例，登录成功后 user 状态即时同步
      const auth = window._appAuth || null
      try {
        const data = auth
          ? await auth.adminLogin(form.username, form.password)
          : (await authAPI.adminLogin(form)).data
        if (data && data.success) {
          countdown.reset()
          router.push('/admin/exams')
        } else {
          error.value = (data && data.message) || '登录失败'
        }
      } catch (e) {
        const msg = (auth && auth.error && auth.error.value) || e.response?.data?.message || '用户名或密码错误'
        if (!countdown.start(msg)) error.value = msg
      } finally {
        loading.value = false
      }
    }

    return { form, loading, error, countdown, handleLogin }
  }
}

// 导出到 window（供 router.js loadComponent 按名解析）
window.AdminLogin = AdminLogin;
