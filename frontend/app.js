/**
 * Vue 应用入口
 *
 * 负责：
 * 1. 创建 Vue Router 实例（Hash 模式）
 * 2. 创建 Vue 应用实例
 * 3. 注册全局导航守卫（认证检查）
 * 4. 全局 provide auth 状态
 * 5. 挂载到 #app
 */
// 等待 Vue/VueRouter/axios 加载完成后再执行（resource-loader 多源回退机制）。
// Chart.js 已按需化：仅 AdminTrend 趋势页使用时加载（此前所有页面启动
// 都等待并解析 208KB 图表库）。
function startAppWhenReady() {
  if (typeof Vue === 'undefined' || typeof VueRouter === 'undefined' ||
      typeof axios === 'undefined') {
    setTimeout(startAppWhenReady, 30);
    return;
  }
  initApp();
}

function initApp() {
  'use strict';

  var createApp = Vue.createApp;
  var createRouter = VueRouter.createRouter;
  var createWebHashHistory = VueRouter.createWebHashHistory;

  // ============================================================
  // 1. 创建 Router
  // ============================================================
  var router = createRouter({
    history: createWebHashHistory(),
    routes: window.routes || [],
    // 滚动行为：进入新路由时滚动到顶部
    scrollBehavior: function () {
      return { top: 0 };
    }
  });

  // 暴露 router 到全局，供 axios 拦截器等使用
  window._appRouter = router;

  // ============================================================
  // 2. 创建 Vue App
  // ============================================================
  var app = createApp({
    // 根组件——顶部导航（登录页隐藏）+ router-view 渲染
    // AppHeader 是 SPA 内唯一的导航与退出登录入口；此前只注册未挂载，
    // 登录后无法切换模块或退出（只能手改地址栏）。
    template: '<AppHeader v-if="!isAuthPage" />' +
      '<router-view v-slot="{ Component, route }">' +
      '  <transition name="fade" mode="out-in">' +
      '    <component :is="Component" :key="route.path" />' +
      '  </transition>' +
      '</router-view>',
    computed: {
      isAuthPage: function () {
        return !!(this.$route.meta && this.$route.meta.guest);
      }
    },
    // 页面标题自动更新
    watch: {
      '$route': function (to) {
        document.title = (to.meta && to.meta.title) ? to.meta.title + ' - 在线考试系统' : '在线考试系统';
      }
    },
    created: function () {
      // 初始化页面标题
      var title = this.$route.meta && this.$route.meta.title;
      document.title = title ? title + ' - 在线考试系统' : '在线考试系统';
    }
  });

  // ============================================================
  // 3. 全局导航守卫
  // ============================================================

  /**
   * 前置守卫：认证状态检查
   *
   * - meta.auth = 'student'  → 必须是学生登录
   * - meta.auth = 'admin'     → 必须是管理员登录
   * - meta.guest = true       → 必须是未登录状态（已登录则重定向）
   */
  router.beforeEach(async function (to, from, next) {
    // 登录态缓存（性能优化）：TTL 内复用 useAuth 内存状态，
    // 避免每次点击导航都发起 /auth/status 网络请求；
    // 登录/登出成功后缓存标记会被刷新，保证首次导航立即生效。
    if (!auth.isAuthCacheFresh()) {
      await auth.checkAuth();
    }
    var user = auth.user;
    var isLoggedIn = !!(user.studentId || user.isAdmin);
    var role = user.isAdmin ? 'admin' : (user.studentId ? 'student' : 'guest');

    // ---- 需要认证的页面 ----
    if (to.meta && to.meta.auth) {
      var requiredRole = to.meta.auth; // 'student' 或 'admin'

      if (!isLoggedIn) {
        // 未登录 → 跳转对应登录页
        if (requiredRole === 'admin') {
          next({ path: '/admin/login', replace: true });
        } else {
          next({ path: '/', replace: true });
        }
        return;
      }

      // 已登录但角色不匹配
      if (requiredRole === 'admin' && role !== 'admin') {
        // 学生访问管理页面 → 跳转学生首页
        next({ path: '/', replace: true });
        return;
      }
      if (requiredRole === 'student' && role !== 'student') {
        // 管理员访问学生页面 → 跳转管理首页
        next({ path: '/admin', replace: true });
        return;
      }

      // 认证通过
      next();
      return;
    }

    // ---- 仅游客页面（已登录则跳过） ----
    if (to.meta && to.meta.guest) {
      if (isLoggedIn) {
        // 已登录用户访问登录页 → 根据角色跳转
        if (role === 'admin') {
          next({ path: '/admin/exams', replace: true });
        } else {
          next({ path: '/exams', replace: true });
        }
        return;
      }
      // 未登录，正常访问
      next();
      return;
    }

    // ---- 其他页面 ----
    next();
  });

  // ============================================================
  // 4. 全局 Provide: Auth 状态
  // ============================================================

  // 使用 useAuth 获取认证状态
  var auth = window.useAuth();
  app.provide('auth', auth);

  // 在 app 实例上挂载 auth，方便组件通过 this.$auth 访问
  app.config.globalProperties.$auth = auth;

  // 暴露全局单例，供登录页等组件复用同一份认证状态
  window._appAuth = auth;

  // ============================================================
  // 5. 注册全局组件
  // ============================================================

  // 注册通用组件（各组件在 components/*.js 中定义为全局 const）
  app.component('LoadingSpinner', LoadingSpinner);
  app.component('EmptyState', EmptyState);
  app.component('ConfirmModal', ConfirmModal);
  app.component('AppHeader', AppHeader);
  app.component('AppPagination', AppPagination);
  app.component('FileUploader', FileUploader);
  app.component('QuestionCard', QuestionCard);

  // ============================================================
  // 6. 使用 Router & 挂载
  // ============================================================
  app.use(router);

  // 挂载应用
  app.mount('#app');

  // ============================================================
  // 7. 初始化认证检查
  // ============================================================
  // 应用启动后检查当前登录状态
  auth.checkAuth().then(function () {
    console.log('[App] 认证状态检查完成，用户:', auth.user.name || '未登录');
  }).catch(function () {
    console.log('[App] 认证状态检查完成（未登录）');
  });

}

// 启动应用：等待 Vue 等库就绪
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', startAppWhenReady);
} else {
  startAppWhenReady();
}
