/**
 * Vue Router 路由表定义（Hash 模式）
 *
 * 组件通过全局 ComponentRegistry 注册表延迟解析（路由访问时按名查找
 * 已挂载的组件引用）。注意：组件 JS 本身由 index.html 静态 <script>
 * 全量加载，此处并非真正的代码分割/懒加载；如需按需下载组件代码，
 * 需引入 Vite/esbuild 构建后改用动态 import()。
 *
 * 注册表访问方式：
 * 1. 避免污染全局命名空间
 * 2. 便于组件的隔离和测试
 */

// 组件注册表 - 存储所有可用的组件
const ComponentRegistry = {
  // 学生端组件
  StudentLogin: null,
  ExamList: null,
  ExamTake: null,
  ResultView: null,
  StudyResources: null,
  StudentTrend: null,

  // 管理端组件
  AdminLogin: null,
  AdminExams: null,
  AdminQuestions: null,
  AdminQuestionForm: null,
  AdminSubQuestions: null,
  AdminResources: null,
  AdminTrend: null,
  AdminOnlineStudents: null,
  AdminLogs: null,
  AdminPythonLogs: null,

  // 公共组件
  PythonMarkerGuide: null,
  NotFound: null
};

// 动态组件加载函数（运行时代码分割，免构建）
// 1. 注册表命中 → 直接返回
// 2. window 全局命中（历史/测试挂载）→ 注册后返回
// 3. 均未命中 → 动态注入 <script src="views/<Name>.js"> 按需下载
//    该视图脚本（首屏仅下载核心层 + 登录页视图；此前 18 个视图脚本全部
//    同步加载约 200KB，页面切换也全部加载）。视图脚本的浏览器缓存与
//    serve_spa 的 10 分钟 max-age 一致，重复进入零额外请求。
function loadComponent(componentName) {
  return function() {
    // 首先尝试从注册表获取
    if (ComponentRegistry[componentName] !== null && ComponentRegistry[componentName] !== undefined) {
      return Promise.resolve(ComponentRegistry[componentName]);
    }

    // 尝试从全局window对象获取（向后兼容）
    const globalComponent = window[componentName];
    if (globalComponent) {
      ComponentRegistry[componentName] = globalComponent;
      return Promise.resolve(globalComponent);
    }

    // 按需注入视图脚本（运行时代码分割）
    return new Promise(function(resolve) {
      var s = document.createElement('script');
      s.src = 'views/' + componentName + '.js';
      s.onload = function() {
        var comp = window[componentName];
        if (comp) {
          ComponentRegistry[componentName] = comp;
          resolve(comp);
        } else {
          console.warn('组件 ' + componentName + ' 脚本已加载但未注册到 window');
          resolve(window.NotFound || null);
        }
      };
      s.onerror = function() {
        console.warn('组件 ' + componentName + ' 加载失败，使用 NotFound 作为备选');
        resolve(window.NotFound || null);
      };
      document.body.appendChild(s);
    });
  };
}

// ============================================================
// 路由表
// ============================================================
var routes = [
  // ===== 学生端 =====
  {
    path: '/',
    component: loadComponent('StudentLogin'),
    meta: { title: '学生登录', guest: true }
  },
  {
    path: '/exams',
    component: loadComponent('ExamList'),
    meta: { title: '选择考试', auth: 'student' }
  },
  {
    path: '/exam/:id',
    component: loadComponent('ExamTake'),
    meta: { title: '在线考试', auth: 'student' }
  },
  {
    path: '/result/:id',
    component: loadComponent('ResultView'),
    meta: { title: '考试结果', auth: 'student' }
  },
  {
    path: '/resources',
    component: loadComponent('StudyResources'),
    meta: { title: '学习资源', auth: 'student' }
  },
  {
    path: '/trend',
    component: loadComponent('StudentTrend'),
    meta: { title: '成绩趋势', auth: 'student' }
  },

  // ===== 管理端 =====
  {
    path: '/admin/login',
    component: loadComponent('AdminLogin'),
    meta: { title: '管理员登录', guest: true }
  },
  {
    path: '/admin',
    redirect: '/admin/exams'
  },
  {
    path: '/admin/exams',
    component: loadComponent('AdminExams'),
    meta: { title: '试卷管理', auth: 'admin' }
  },
  {
    path: '/admin/questions',
    component: loadComponent('AdminQuestions'),
    meta: { title: '题库管理', auth: 'admin' }
  },
  {
    path: '/admin/questions/add',
    component: loadComponent('AdminQuestionForm'),
    meta: { title: '添加题目', auth: 'admin' }
  },
  {
    path: '/admin/questions/:id/edit',
    component: loadComponent('AdminQuestionForm'),
    meta: { title: '编辑题目', auth: 'admin' }
  },
  {
    path: '/admin/questions/:id/sub',
    component: loadComponent('AdminSubQuestions'),
    meta: { title: '小题管理', auth: 'admin' }
  },
  {
    path: '/admin/resources',
    component: loadComponent('AdminResources'),
    meta: { title: '资源管理', auth: 'admin' }
  },
  {
    path: '/admin/trend/:examId',
    component: loadComponent('AdminTrend'),
    meta: { title: '成绩分析', auth: 'admin' }
  },
  {
    path: '/admin/students',
    component: loadComponent('AdminOnlineStudents'),
    meta: { title: '在线学生', auth: 'admin' }
  },
  {
    path: '/admin/logs',
    component: loadComponent('AdminLogs'),
    meta: { title: '操作日志', auth: 'admin' }
  },
  {
    path: '/admin/python-logs',
    component: loadComponent('AdminPythonLogs'),
    meta: { title: 'Python日志', auth: 'admin' }
  },

  // ===== 公共 =====
  {
    path: '/python-marker-guide',
    component: loadComponent('PythonMarkerGuide'),
    meta: { title: '标记指南' }
  },

  // ===== 404 =====
  {
    path: '/:pathMatch(.*)*',
    component: loadComponent('NotFound'),
    meta: { title: '页面未找到' }
  }
];

// 暴露到全局（供初始化使用）
window.routes = routes;
window.ComponentRegistry = ComponentRegistry;
