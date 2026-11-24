/**
 * 资源加载优化工具
 *  - 图片懒加载
 *  - 资源预加载
 *  - 多源 CDN 回退：本地 → 国内镜像源(多源) → 原始 CDN
 *  - 离线/在线自适应
 */

// 基础配置
const CONFIG = {
  debug: false,
  lazyload: {
    rootMargin: '0px 0px 200px 0px',
    threshold: 0.1
  },
  timeout: 5000,
  offline: {
    alwaysUseLocal: true,
    priorityResources: [
      'bootstrap/css/bootstrap.min.css',
      'css/main.min.css',
    ]
  }
};

// ---- 资源镜像源配置（按顺序回退） ----
// 优先使用本地，再尝试国内镜像源，最后回退到原始 CDN 源
const MIRROR_SOURCES = {
  bootstrap_css: {
    local: '/static/bootstrap/css/bootstrap.min.css',
    mirrors: [
      'https://cdn.bootcdn.net/ajax/libs/twitter-bootstrap/5.3.2/css/bootstrap.min.css',
      'https://cdn.staticfile.org/twitter-bootstrap/5.3.2/css/bootstrap.min.css',
      'https://lib.baomitu.com/twitter-bootstrap/5.3.2/css/bootstrap.min.css',
      'https://npm.elemecdn.com/bootstrap@5.3.2/dist/css/bootstrap.min.css',
      'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css'
    ]
  },
  bootstrap_js: {
    local: '/static/bootstrap/js/bootstrap.bundle.min.js',
    mirrors: [
      'https://cdn.bootcdn.net/ajax/libs/twitter-bootstrap/5.3.2/js/bootstrap.bundle.min.js',
      'https://cdn.staticfile.org/twitter-bootstrap/5.3.2/js/bootstrap.bundle.min.js',
      'https://lib.baomitu.com/twitter-bootstrap/5.3.2/js/bootstrap.bundle.min.js',
      'https://npm.elemecdn.com/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js',
      'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js'
    ]
  },
  fontawesome_css: {
    local: '/static/fontawesome/css/all.min.css',
    mirrors: [
      'https://cdn.bootcdn.net/ajax/libs/font-awesome/6.4.2/css/all.min.css',
      'https://cdn.staticfile.org/font-awesome/6.4.2/css/all.min.css',
      'https://lib.baomitu.com/font-awesome/6.4.2/css/all.min.css',
      'https://npm.elemecdn.com/@fortawesome/fontawesome-free@6.4.2/css/all.min.css',
      'https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.4.2/css/all.min.css'
    ]
  },
  jquery: {
    local: '/static/jquery/jquery-3.7.1.min.js',
    mirrors: [
      'https://cdn.bootcdn.net/ajax/libs/jquery/3.7.1/jquery.min.js',
      'https://cdn.staticfile.org/jquery/3.7.1/jquery.min.js',
      'https://lib.baomitu.com/jquery/3.7.1/jquery.min.js',
      'https://npm.elemecdn.com/jquery@3.7.1/dist/jquery.min.js',
      'https://cdn.jsdelivr.net/npm/jquery@3.7.1/dist/jquery.min.js'
    ]
  },
  bootstrap_icons: {
    local: '/static/bootstrap-icons/bootstrap-icons.min.css',
    mirrors: [
      'https://cdn.bootcdn.net/ajax/libs/bootstrap-icons/1.11.3/font/bootstrap-icons.min.css',
      'https://cdn.staticfile.org/bootstrap-icons/1.11.3/font/bootstrap-icons.min.css',
      'https://lib.baomitu.com/bootstrap-icons/1.11.3/font/bootstrap-icons.min.css',
      'https://npm.elemecdn.com/bootstrap-icons@1.11.3/font/bootstrap-icons.css',
      'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css'
    ]
  },
  chart_js: {
    local: '/static/chart.js/chart.umd.min.js',
    mirrors: [
      'https://cdn.bootcdn.net/ajax/libs/Chart.js/4.4.0/chart.umd.min.js',
      'https://cdn.staticfile.org/Chart.js/4.4.0/chart.umd.min.js',
      'https://lib.baomitu.com/Chart.js/4.4.0/chart.umd.min.js',
      'https://npm.elemecdn.com/chart.js@4.4.0/dist/chart.umd.min.js',
      'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js'
    ]
  },
  xlsx: {
    local: '/static/xlsx/xlsx.full.min.js',
    mirrors: [
      'https://cdn.bootcdn.net/ajax/libs/xlsx/0.18.5/xlsx.full.min.js',
      'https://cdn.staticfile.org/xlsx/0.18.5/xlsx.full.min.js',
      'https://lib.baomitu.com/xlsx/0.18.5/xlsx.full.min.js',
      'https://npm.elemecdn.com/xlsx@0.18.5/dist/xlsx.full.min.js',
      'https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js'
    ]
  },
  tailwind: {
    local: '/static/tailwind/tailwind.min.js',
    mirrors: [
      'https://cdn.bootcdn.net/ajax/libs/tailwindcss/2.2.19/tailwind.min.js',
      'https://cdn.staticfile.org/tailwindcss/2.2.19/tailwind.min.js',
      'https://lib.baomitu.com/tailwindcss/2.2.19/tailwind.min.js',
      'https://cdn.tailwindcss.com'
    ]
  },
  vue: {
    local: '/static/vue/vue.global.prod.js',
    mirrors: [
      'https://cdn.bootcdn.net/ajax/libs/vue/3.4.0/vue.global.prod.js',
      'https://cdn.staticfile.org/vue/3.4.0/vue.global.prod.js',
      'https://lib.baomitu.com/vue/3.4.0/vue.global.prod.js',
      'https://npm.elemecdn.com/vue@3.4.0/dist/vue.global.prod.js',
      'https://unpkg.com/vue@3.4.0/dist/vue.global.prod.js'
    ]
  },
  vue_router: {
    local: '/static/vue-router/vue-router.global.prod.js',
    mirrors: [
      'https://cdn.bootcdn.net/ajax/libs/vue-router/4.2.0/vue-router.global.prod.js',
      'https://cdn.staticfile.org/vue-router/4.2.0/vue-router.global.prod.js',
      'https://lib.baomitu.com/vue-router/4.2.0/vue-router.global.prod.js',
      'https://npm.elemecdn.com/vue-router@4.2.0/dist/vue-router.global.prod.js',
      'https://unpkg.com/vue-router@4.2.0/dist/vue-router.global.prod.js'
    ]
  },
  axios: {
    local: '/static/axios/axios.min.js',
    mirrors: [
      'https://cdn.bootcdn.net/ajax/libs/axios/1.4.0/axios.min.js',
      'https://cdn.staticfile.org/axios/1.4.0/axios.min.js',
      'https://lib.baomitu.com/axios/1.4.0/axios.min.js',
      'https://npm.elemecdn.com/axios@1.4.0/dist/axios.min.js',
      'https://unpkg.com/axios@1.4.0/dist/axios.min.js'
    ]
  },
  marked: {
    local: '/static/marked/marked.min.js',
    mirrors: [
      'https://cdn.bootcdn.net/ajax/libs/marked/12.0.2/marked.min.js',
      'https://cdn.staticfile.org/marked/12.0.2/marked.min.js',
      'https://lib.baomitu.com/marked/12.0.2/marked.min.js',
      'https://npm.elemecdn.com/marked@12.0.2/marked.min.js',
      'https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js'
    ]
  },
  hljs: {
    local: '/static/highlight/highlight.min.js',
    mirrors: [
      'https://cdn.bootcdn.net/ajax/libs/highlight.js/11.9.0/highlight.min.js',
      'https://cdn.staticfile.org/highlight.js/11.9.0/highlight.min.js',
      'https://lib.baomitu.com/highlight.js/11.9.0/highlight.min.js',
      'https://npm.elemecdn.com/@highlightjs/cdn-assets@11.9.0/highlight.min.js',
      'https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.9.0/highlight.min.js'
    ]
  }
};

function isOnline() {
  return navigator.onLine;
}

function tryLoadByType(type) {
  const cfg = MIRROR_SOURCES[type];
  if (!cfg) return Promise.reject(new Error('未知资源类型: ' + type));
  return tryLoadSequence([cfg.local].concat(cfg.mirrors), type);
}

// 顺序尝试：先本地，再镜像，最后原始 CDN
// mirrors 列表的最后一项被视作"原始 CDN 兜底"
function tryLoadSequence(urls, type) {
  // 离线环境：直接用本地
  if (!isOnline() && urls[0]) {
    if (CONFIG.debug) console.log('[离线] 强制使用本地:', urls[0]);
    return loadByElement(urls[0], type, true).then(() => urls[0]).catch((err) => {
      throw new Error('离线且本地资源不可用: ' + err.message);
    });
  }

  // 在线：按顺序尝试，超时/失败则继续下一个
  return urls.reduce((p, url, idx) => {
    return p.then((resolved) => {
      if (resolved) return resolved;
      const isLast = idx === urls.length - 1;
      const tag = idx === 0 ? '本地' : (isLast ? '原始CDN' : '镜像' + idx);
      if (CONFIG.debug) console.log(`[${tag}] 尝试加载: ${url}`);
      return loadByElement(url, type, true)
        .then(() => {
          if (CONFIG.debug) console.log(`[${tag}] ✓ 成功: ${url}`);
          return url;
        })
        .catch((err) => {
          if (CONFIG.debug) console.log(`[${tag}] ✗ 失败: ${url} (${err.message})`);
          return null;
        });
    });
  }, Promise.resolve(null)).then((finalUrl) => {
    if (!finalUrl) {
      throw new Error('所有镜像源均不可用: ' + type);
    }
    return finalUrl;
  });
}

// SRI 完整性哈希（sha384，按官方发布内容计算；适用于所有镜像源，因为同一版本文件内容一致）。
// 可变版本源（cdn.tailwindcss.com、unpkg vue@3/dist 等无版本路径）不设 SRI——
// 其内容不可预测，但回退链中其后总无其他源，且仅在本地不可用+在线时才会走到。
const SRI_BY_TYPE = {
  bootstrap_css: 'sha384-T3c6CoIi6uLrA9TneNEoa7RxnatzjcDSCmG1MXxSR1GAsXEV/Dwwykc2MPK8M2HN',
  bootstrap_js: 'sha384-C6RzsynM9kWDrMNeT87bh95OGNyZPhcTNXj1NW7RuBCsyN/o0jlpcV8Qyq46cDfL',
  fontawesome_css: 'sha384-blOohCVdhjmtROpu8+CfTnUWham9nkX7P7OZQMst+RUnhtoY/9qemFAkIKOYxDI3',
  jquery: 'sha256-/JqT3SQfawRcv/BIHPThkBvs0OEvtFFmqPF/lYI/Cxo=',
  bootstrap_icons: 'sha384-XGjxtQfXaH2tnPFa9x+ruJTuLE3Aa6LhHSWRr1XeTyhezb4abCG4ccI5AkVDxqC+',
  chart_js: 'sha384-DhxhYObIMeMNGyAG7iK11OHzBIKyEIeRL0ad1iFPAOwZB8iirUlTT0O/WJJUk8+o',
  xlsx: 'sha384-vtjasyidUo0kW94K5MXDXntzOJpQgBKXmE7e2Ga4LG0skTTLeBi97eFAXsqewJjw',
  vue: 'sha384-xivezcHTLn8ZURcEJQ/odnHkFWiOcnxHS8wNwls4xv0RZ+dSzIjp//XKDplVo2Al',
  vue_router: 'sha384-eq5CW++D0xoh2OmiKCJVhTcQaAXXPS/hgn9dixIxUrpjxdeieFs5pcOskicFcXQ9',
  axios: 'sha384-I4Qw/vWb/sK/7VwepTtkaq636YLYClbEgEwKp3ueUCvjiLFrcoKUFAY5mOl40Fj3',
  marked: 'sha384-/TQbtLCAerC3jgaim+N78RZSDYV7ryeoBCVqTuzRrFec2akfBkHS7ACQ3PQhvMVi',
  hljs: 'sha384-F/bZzf7p3Joyp5psL90p/p89AZJsndkSoGwRpXcZhleCWhd8SnRuoYo4d0yirjJp',
};

// 实际创建 link/script 元素加载资源
function loadByElement(url, type, withTimeout) {
  return new Promise((resolve, reject) => {
    let el;
    let isCSS = /\.css(\?|$)/.test(url);
    if (isCSS) {
      el = document.createElement('link');
      el.rel = 'stylesheet';
      el.href = url;
    } else {
      el = document.createElement('script');
      el.src = url;
      el.async = true;
      el.defer = true;
    }

    // 外部镜像源附加 SRI 完整性校验：任一镜像被投毒即校验失败（onerror），
    // 回退链继续尝试下一源，杜绝被投毒内容执行。本地资源无需（同源可信）。
    const sri = SRI_BY_TYPE[type];
    if (sri && /^https?:/.test(url)) {
      el.crossOrigin = 'anonymous';
      el.integrity = sri;
    }

    let done = false;
    let timer = null;

    const cleanup = (removeElement = true) => {
      // CSS 的 <link> 加载成功后必须保留：移除元素会连同其规则一起从
      // 文档样式表中卸载（SPA 的 FontAwesome 图标因此全部消失）；
      // 脚本执行完成后移除则无副作用。
      if (removeElement && el.parentNode) el.parentNode.removeChild(el);
      if (timer) clearTimeout(timer);
    };

    el.onload = () => {
      if (done) return;
      done = true;
      cleanup(!isCSS);
      resolve();
    };
    el.onerror = () => {
      if (done) return;
      done = true;
      cleanup();
      reject(new Error('onerror'));
    };

    if (withTimeout) {
      timer = setTimeout(() => {
        if (done) return;
        done = true;
        cleanup();
        reject(new Error('timeout'));
      }, CONFIG.timeout);
    }

    (document.head || document.body).appendChild(el);
  });
}

// 暴露给外部的 API
function loadCSSByType(type) { return tryLoadByType(type); }
function loadScriptByType(type) { return tryLoadByType(type); }

// 兼容旧 API
function loadCSS(url, options = {}) {
  // 如果传的是已知 type 名称（无 http），走多源
  if (!/^https?:|^[/]/.test(url) && MIRROR_SOURCES[url]) {
    return tryLoadByType(url);
  }
  return loadByElement(url, 'css', true);
}

function loadScript(url, options = {}) {
  if (!/^https?:|^[/]/.test(url) && MIRROR_SOURCES[url]) {
    return tryLoadByType(url);
  }
  return loadByElement(url, 'js', true);
}

// ---- 图片懒加载 ----
function initLazyLoading() {
  if ('IntersectionObserver' in window) {
    const lazyImages = document.querySelectorAll('img[data-src]');
    const imageObserver = new IntersectionObserver((entries, observer) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          const img = entry.target;
          const src = img.dataset.src;
          if (!img.style.opacity) {
            img.style.opacity = '0';
            img.style.transition = 'opacity 0.3s ease-in';
          }
          if (src) {
            img.src = src;
            img.addEventListener('load', () => {
              img.style.opacity = '1';
              delete img.dataset.src;
            });
            observer.unobserve(img);
          }
        }
      });
    }, CONFIG.lazyload);
    lazyImages.forEach(img => imageObserver.observe(img));
  } else {
    document.querySelectorAll('img[data-src]').forEach(img => {
      img.src = img.dataset.src;
    });
  }
}

// ---- 预加载关键资源 ----
function preloadResources(resources) {
  if (!resources || !resources.length) return;
  resources.forEach(resource => {
    if (!resource.url) return;
    const link = document.createElement('link');
    link.rel = 'preload';
    link.href = resource.url;
    link.as = resource.type || 'image';
    if (resource.type === 'font') link.crossOrigin = 'anonymous';
    document.head.appendChild(link);
  });
}

// ---- 加载所有延迟样式/脚本（基于多源） ----
function loadAllStyles() {
  if (window.DEFERRED_STYLES && window.DEFERRED_STYLES.length) {
    window.DEFERRED_STYLES.forEach(style => {
      const url = new URL(style, window.location.origin);
      const path = url.pathname;
      let type = null;
      if (path.includes('bootstrap-icons')) type = 'bootstrap_icons';
      else if (path.includes('fontawesome') || path.includes('font-awesome')) type = 'fontawesome_css';
      else if (path.includes('bootstrap')) type = 'bootstrap_css';

      if (type) {
        tryLoadByType(type).catch(err => console.error('加载CSS资源失败:', err));
      } else {
        loadByElement(style, 'css', true).catch(err => console.error('加载CSS资源失败:', err));
      }
    });
  }
}

function loadAllScripts() {
  if (window.DEFERRED_SCRIPTS && window.DEFERRED_SCRIPTS.length) {
    const tasks = window.DEFERRED_SCRIPTS.map(script => {
      const url = new URL(script, window.location.origin);
      const path = url.pathname;
      let type = null;
      if (path.includes('chart')) type = 'chart_js';
      else if (path.includes('xlsx')) type = 'xlsx';
      else if (path.includes('bootstrap')) type = 'bootstrap_js';
      else if (path.includes('jquery')) type = 'jquery';
      else if (path.includes('vue-router')) type = 'vue_router';
      else if (path.includes('vue')) type = 'vue';
      else if (path.includes('axios')) type = 'axios';
      else if (path.includes('tailwind')) type = 'tailwind';

      if (type) {
        return tryLoadByType(type).catch(err => { console.error('加载JS资源失败:', err); });
      } else {
        return loadByElement(script, 'js', true).catch(err => { console.error('加载JS资源失败:', err); });
      }
    });
    // 所有延迟脚本加载完成后派发事件，供依赖 Chart.js/xlsx 等的页面初始化
    return Promise.all(tasks).then(() => {
      window.dispatchEvent(new CustomEvent('all-scripts-loaded'));
    });
  }
  // 无延迟脚本时也立即通知，避免页面等待事件超时
  window.dispatchEvent(new CustomEvent('all-scripts-loaded'));
  return Promise.resolve();
}

// 页面资源初始化
function initPageResources() {
  initLazyLoading();
  window.addEventListener('load', () => {
    setTimeout(() => {
      loadAllStyles();
      loadAllScripts();
      if (CONFIG.debug) console.log('延迟加载资源已完成');
    }, 300);
  });
  initLazyResources();
}

// 按需加载资源
function initLazyResources() {
  document.querySelectorAll('img[data-lazy-src]').forEach(img => {
    if (!('IntersectionObserver' in window)) {
      img.src = img.dataset.lazySrc;
      delete img.dataset.lazySrc;
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          const img = entry.target;
          img.src = img.dataset.lazySrc;
          delete img.dataset.lazySrc;
          observer.unobserve(img);
        }
      });
    }, CONFIG.lazyload);
    observer.observe(img);
  });
  lazyLoadScripts();
}

function lazyLoadScripts() {
  document.querySelectorAll('script[data-lazy-load]').forEach(script => {
    const src = script.getAttribute('data-src');
    if (!src) return;
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          const newScript = document.createElement('script');
          newScript.src = src;
          Array.from(script.attributes).forEach(attr => {
            if (attr.name !== 'data-src' && attr.name !== 'data-lazy-load') {
              newScript.setAttribute(attr.name, attr.value);
            }
          });
          script.parentNode.replaceChild(newScript, script);
          observer.disconnect();
        }
      });
    }, { rootMargin: '200px 0px', threshold: 0.01 });
    observer.observe(script);
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initPageResources);
} else {
  initPageResources();
}

window.resourceLoader = {
  loadCSS: loadCSS,
  loadScript: loadScript,
  preloadResources: preloadResources,
  tryLoadByType: tryLoadByType,
  MIRROR_SOURCES: MIRROR_SOURCES,
  lazyLoad: {
    image: (selector) => {
      document.querySelectorAll(selector).forEach(img => {
        img.setAttribute('data-lazy-src', img.src);
        img.removeAttribute('src');
      });
      initLazyLoading();
    },
    script: (src, options) => {
      const script = document.createElement('script');
      script.setAttribute('data-src', src);
      script.setAttribute('data-lazy-load', 'true');
      if (options) {
        if (options.async) script.async = true;
        if (options.defer) script.defer = true;
        if (options.id) script.id = options.id;
      }
      document.body.appendChild(script);
    }
  }
};
