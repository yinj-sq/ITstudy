/**
 * AppHeader - 顶部导航栏组件
 * 支持三种状态:
 *   - guest:   显示"学生登录"和"管理后台"链接
 *   - student: 显示"学习资源"、"在线测试"、"成绩趋势"、"退出"
 *   - admin:   显示"试卷管理"、"题库管理"、"资源管理"、"在线学生"、
 *              "操作日志"、"Python日志"、成绩趋势(dropdown)、"退出"
 * 注入 useAuth 获取用户状态
 * 使用 Vue Router 导航
 */
const AppHeader = {
  name: 'AppHeader',
  template: `
    <header class="bg-blue-600 text-white shadow-md">
      <nav class="container mx-auto px-4">
        <div class="flex items-center justify-between h-14">
          <!-- Logo / 品牌 -->
          <div class="flex items-center space-x-2 flex-shrink-0">
            <i class="fas fa-graduation-cap text-xl"></i>
            <span class="font-bold text-lg tracking-tight">ITstudy</span>
          </div>

          <!-- 移动端菜单按钮 -->
          <button
            @click="mobileMenuOpen = !mobileMenuOpen"
            class="md:hidden p-2 rounded-lg hover:bg-blue-700 transition-colors"
            aria-label="切换导航菜单"
          >
            <i :class="mobileMenuOpen ? 'fas fa-times' : 'fas fa-bars'" class="text-lg"></i>
          </button>

          <!-- 桌面端导航链接 -->
          <div class="hidden md:flex items-center space-x-1">
            <template v-if="userRole === 'guest'">
              <router-link to="/"
                class="px-3 py-2 text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
                :class="{ 'bg-blue-700': isActive('/') }">
                <i class="fas fa-sign-in-alt mr-1"></i>学生登录
              </router-link>
              <router-link to="/admin/login"
                class="px-3 py-2 text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
                :class="{ 'bg-blue-700': isActive('/admin/login') }">
                <i class="fas fa-user-shield mr-1"></i>管理后台
              </router-link>
            </template>

            <template v-else-if="userRole === 'student'">
              <span class="text-sm text-blue-200 mr-3 hidden lg:inline">
                <i class="fas fa-user mr-1"></i>{{ userName }}
              </span>
              <router-link to="/resources"
                class="px-3 py-2 text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
                :class="{ 'bg-blue-700': isActive('/resources') }">
                <i class="fas fa-book mr-1"></i>学习资源
              </router-link>
              <a href="/sim-lab"
                class="px-3 py-2 text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors">
                <i class="fas fa-flask mr-1"></i>仿真实验
              </a>
              <router-link to="/exams"
                class="px-3 py-2 text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
                :class="{ 'bg-blue-700': isActive('/exams') }">
                <i class="fas fa-pencil-alt mr-1"></i>在线测试
              </router-link>
              <router-link to="/trend"
                class="px-3 py-2 text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
                :class="{ 'bg-blue-700': isActive('/trend') }">
                <i class="fas fa-chart-line mr-1"></i>成绩趋势
              </router-link>
              <button @click="handleLogout"
                class="px-3 py-2 text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors ml-2">
                <i class="fas fa-sign-out-alt mr-1"></i>退出
              </button>
            </template>

            <template v-else-if="userRole === 'admin'">
              <span class="text-sm text-blue-200 mr-2 hidden lg:inline">
                <i class="fas fa-user-cog mr-1"></i>管理员
              </span>
              <a href="/admin/dashboard" class="px-3 py-2 text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors">管理总览</a>
              <details class="relative">
                <summary class="px-3 py-2 text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors cursor-pointer" style="list-style:none;">考试与练习</summary>
                <div class="absolute right-0 mt-1 w-44 bg-white text-gray-800 rounded-lg shadow-lg py-1 z-50">
                  <router-link to="/admin/exams" class="block px-3 py-2 text-sm hover:bg-gray-100">试卷管理</router-link>
                  <router-link to="/admin/questions" class="block px-3 py-2 text-sm hover:bg-gray-100">题库管理</router-link>
                  <a href="/admin/grading" class="block px-3 py-2 text-sm hover:bg-gray-100">批改中心</a>
                  <a href="/admin/tools/import-python-fill" class="block px-3 py-2 text-sm hover:bg-gray-100">导入 Python 填空题</a>
                </div>
              </details>
              <details class="relative">
                <summary class="px-3 py-2 text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors cursor-pointer" style="list-style:none;">班级与考勤</summary>
                <div class="absolute right-0 mt-1 w-44 bg-white text-gray-800 rounded-lg shadow-lg py-1 z-50">
                  <a href="/admin/classes" class="block px-3 py-2 text-sm hover:bg-gray-100">班级信息</a>
                  <a href="/admin/groups" class="block px-3 py-2 text-sm hover:bg-gray-100">学习小组</a>
                  <a href="/admin/attendance" class="block px-3 py-2 text-sm hover:bg-gray-100">签到管理</a>
                  <a href="/admin/online_students" class="block px-3 py-2 text-sm hover:bg-gray-100">在线学生</a>
                  <a href="/admin/student-drive" class="block px-3 py-2 text-sm hover:bg-gray-100">学生网盘</a>
                </div>
              </details>
              <details class="relative">
                <summary class="px-3 py-2 text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors cursor-pointer" style="list-style:none;">教学资源</summary>
                <div class="absolute right-0 mt-1 w-44 bg-white text-gray-800 rounded-lg shadow-lg py-1 z-50">
                  <router-link to="/admin/resources" class="block px-3 py-2 text-sm hover:bg-gray-100">资源管理</router-link>
                  <a href="/sim-lab" class="block px-3 py-2 text-sm hover:bg-gray-100">仿真实验</a>
                  <a href="/admin/homework" class="block px-3 py-2 text-sm hover:bg-gray-100">作业管理</a>
                  <a href="/admin/works" class="block px-3 py-2 text-sm hover:bg-gray-100">作品云盘</a>
                </div>
              </details>
              <details class="relative">
                <summary class="px-3 py-2 text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors cursor-pointer" style="list-style:none;">课堂工具</summary>
                <div class="absolute right-0 mt-1 w-44 bg-white text-gray-800 rounded-lg shadow-lg py-1 z-50">
                  <a href="/admin/classroom" class="block px-3 py-2 text-sm hover:bg-gray-100">课堂大屏</a>
                  <a href="/admin/ai_config" class="block px-3 py-2 text-sm hover:bg-gray-100">AI 配置</a>
                </div>
              </details>
              <details class="relative">
                <summary class="px-3 py-2 text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors cursor-pointer" style="list-style:none;">数据与审计</summary>
                <div class="absolute right-0 mt-1 w-44 bg-white text-gray-800 rounded-lg shadow-lg py-1 z-50">
                  <a href="/admin/students" class="block px-3 py-2 text-sm hover:bg-gray-100">学生信息</a>
                  <a href="/admin/schedule" class="block px-3 py-2 text-sm hover:bg-gray-100">作息时间</a>
                  <a href="/admin/class_schedule" class="block px-3 py-2 text-sm hover:bg-gray-100">课程表</a>
                  <a href="/admin/statistics" class="block px-3 py-2 text-sm hover:bg-gray-100">数据统计</a>
                  <a href="/admin/teaching-sessions" class="block px-3 py-2 text-sm hover:bg-gray-100">教学记录</a>
                  <a href="/admin/account-trail" class="block px-3 py-2 text-sm hover:bg-gray-100">账号轨迹</a>
                </div>
              </details>
              <details class="relative">
                <summary class="px-3 py-2 text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors cursor-pointer" style="list-style:none;">系统</summary>
                <div class="absolute right-0 mt-1 w-44 bg-white text-gray-800 rounded-lg shadow-lg py-1 z-50">
                  <router-link to="/admin/logs" class="block px-3 py-2 text-sm hover:bg-gray-100">操作日志</router-link>
                  <router-link to="/admin/python-logs" class="block px-3 py-2 text-sm hover:bg-gray-100">Python 日志</router-link>
                  <a href="/admin/teacher_account" class="block px-3 py-2 text-sm hover:bg-gray-100">教师账号</a>
                  <a href="/admin/accounts" class="block px-3 py-2 text-sm hover:bg-gray-100">管理员账号</a>
                  <a href="/admin/system" class="block px-3 py-2 text-sm hover:bg-gray-100">系统开关</a>
                </div>
              </details>
              <button @click="handleLogout"
                class="px-3 py-2 text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors ml-1">
                <i class="fas fa-sign-out-alt mr-1"></i>退出
              </button>
            </template>
          </div>
        </div>

        <!-- 移动端导航菜单 -->
        <transition name="slide-down">
          <div v-if="mobileMenuOpen" class="md:hidden pb-3 border-t border-blue-500">
            <template v-if="userRole === 'guest'">
              <router-link to="/" @click="mobileMenuOpen = false"
                class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors mt-1">
                <i class="fas fa-sign-in-alt mr-2"></i>学生登录
              </router-link>
              <router-link to="/admin/login" @click="mobileMenuOpen = false"
                class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">
                <i class="fas fa-user-shield mr-2"></i>管理后台
              </router-link>
            </template>

            <template v-else-if="userRole === 'student'">
              <div class="text-sm text-blue-200 px-3 py-2 border-b border-blue-500 mb-1">
                <i class="fas fa-user mr-1"></i>{{ userName }}
              </div>
              <router-link to="/resources" @click="mobileMenuOpen = false"
                class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">
                <i class="fas fa-book mr-2"></i>学习资源
              </router-link>
              <a href="/sim-lab" @click="mobileMenuOpen = false"
                class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">
                <i class="fas fa-flask mr-2"></i>仿真实验
              </a>
              <router-link to="/exams" @click="mobileMenuOpen = false"
                class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">
                <i class="fas fa-pencil-alt mr-2"></i>在线测试
              </router-link>
              <router-link to="/trend" @click="mobileMenuOpen = false"
                class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">
                <i class="fas fa-chart-line mr-2"></i>成绩趋势
              </router-link>
              <button @click="handleLogout"
                class="block w-full text-left px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors mt-1">
                <i class="fas fa-sign-out-alt mr-2"></i>退出
              </button>
            </template>

            <template v-else-if="userRole === 'admin'">
              <div class="text-sm text-blue-200 px-3 py-2 border-b border-blue-500 mb-1">
                <i class="fas fa-user-cog mr-1"></i>管理员
              </div>
              <a href="/admin/dashboard" class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">管理总览</a>
              <div class="px-3 pt-2 pb-1 text-xs text-blue-200">考试与练习</div>
              <router-link to="/admin/exams" @click="mobileMenuOpen = false"
                class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">试卷管理</router-link>
              <router-link to="/admin/questions" @click="mobileMenuOpen = false"
                class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">题库管理</router-link>
              <a href="/admin/grading" class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">批改中心</a>
              <div class="px-3 pt-2 pb-1 text-xs text-blue-200">班级与考勤</div>
              <a href="/admin/classes" class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">班级信息</a>
              <a href="/admin/groups" class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">学习小组</a>
              <a href="/admin/attendance" class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">签到管理</a>
              <a href="/admin/online_students" class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">在线学生</a>
              <a href="/admin/student-drive" class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">学生网盘</a>
              <div class="px-3 pt-2 pb-1 text-xs text-blue-200">教学资源</div>
              <router-link to="/admin/resources" @click="mobileMenuOpen = false"
                class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">资源管理</router-link>
              <a href="/sim-lab" @click="mobileMenuOpen = false"
                class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">仿真实验</a>
              <a href="/admin/homework" class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">作业管理</a>
              <a href="/admin/works" class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">作品云盘</a>
              <div class="px-3 pt-2 pb-1 text-xs text-blue-200">课堂工具</div>
              <a href="/admin/classroom" class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">课堂大屏</a>
              <a href="/admin/ai_config" class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">AI 配置</a>
              <div class="px-3 pt-2 pb-1 text-xs text-blue-200">数据与审计</div>
              <a href="/admin/students" class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">学生信息</a>
              <a href="/admin/schedule" class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">作息时间</a>
              <a href="/admin/class_schedule" class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">课程表</a>
              <a href="/admin/statistics" class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">数据统计</a>
              <a href="/admin/teaching-sessions" class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">教学记录</a>
              <a href="/admin/account-trail" class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">账号轨迹</a>
              <div class="px-3 pt-2 pb-1 text-xs text-blue-200">系统</div>
              <router-link to="/admin/logs" @click="mobileMenuOpen = false"
                class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">操作日志</router-link>
              <router-link to="/admin/python-logs" @click="mobileMenuOpen = false"
                class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">Python日志</router-link>
              <a href="/admin/teacher_account" class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">教师账号</a>
              <a href="/admin/accounts" class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">管理员账号</a>
              <a href="/admin/system" class="block px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors">系统开关</a>
              <button @click="handleLogout"
                class="block w-full text-left px-3 py-2 text-sm rounded-lg hover:bg-blue-700 transition-colors mt-1">
                <i class="fas fa-sign-out-alt mr-2"></i>退出
              </button>
            </template>
          </div>
        </transition>
      </nav>
    </header>
  `,
  props: {
    // 可选: 允许父组件直接传入角色（覆盖 inject）
    role: {
      type: String,
      default: null,
      validator: (value) => [null, 'guest', 'student', 'admin'].includes(value)
    }
  },
  setup(props) {
    const { ref, computed, inject, onMounted, onUnmounted } = Vue;

    const router = VueRouter.useRouter();
    const mobileMenuOpen = ref(false);

    // 注入全局 provide 的 auth 状态（key 为 'auth'，见 app.js app.provide('auth', auth)）
    const auth = inject('auth', null);

    // 用户角色: 优先使用 prop 传入的 role，否则从 auth 中获取
    const userRole = computed(() => {
      if (props.role) return props.role;
      if (auth && auth.user) {
        // auth.user 是 reactive 对象（无 .value），无 role 字段，
        // 根据 isAdmin/studentId 推导角色
        return auth.user.isAdmin ? 'admin' : (auth.user.studentId ? 'student' : 'guest');
      }
      return 'guest';
    });

    // 用户名
    const userName = computed(() => {
      if (auth && auth.user) {
        return auth.user.name || '';
      }
      return '';
    });

    // 当前路由路径
    const currentRoute = computed(() => {
      try {
        return router.currentRoute.value.path;
      } catch (e) {
        return '';
      }
    });

    // 判断指定路径是否为当前活跃路由（根路径须精确匹配，
    // startsWith('/') 会恒真 → 游客页多个导航项同时高亮）
    const isActive = (path) => {
      if (path === '/') return currentRoute.value === '/';
      return currentRoute.value.startsWith(path);
    };

    // 退出登录
    const handleLogout = async () => {
      mobileMenuOpen.value = false;
      if (auth && auth.logout) {
        try {
          await auth.logout();
        } catch (e) {
          // 登出接口失败时本地状态已重置，继续跳转
        }
      }
      try {
        router.push('/');
      } catch (e) {
        window.location.href = '/';
      }
    };

    // 点击外部关闭移动菜单
    const handleClickOutside = (event) => {
      if (mobileMenuOpen.value) {
        const header = event.target.closest('header');
        if (!header) {
          mobileMenuOpen.value = false;
        }
      }
    };

    onMounted(() => {
      document.addEventListener('click', handleClickOutside);
    });

    onUnmounted(() => {
      document.removeEventListener('click', handleClickOutside);
    });

    return {
      mobileMenuOpen,
      userRole,
      userName,
      isActive,
      handleLogout
    };
  }
};
