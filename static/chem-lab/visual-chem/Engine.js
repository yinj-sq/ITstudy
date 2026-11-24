// ==========================================
// 可视化化学 - 3D 舞台通用渲染引擎 (Engine.js)
// 集成：安保、不死水印、全设备自适应、UI皮肤动态注入、防穿透裁剪机制、动态黄金视角
// ==========================================
// ★ 传统 UMD 版：不再使用 ES Module —— 教室一体机上的老浏览器（含 Edge Legacy）也能运行。
//   使用前请确保页面已加载 three.min.js 与 OrbitControls-umd.js（两者都会挂到 window.THREE）。
(function () {
'use strict';
var THREE = window.THREE;
var OrbitControls = THREE && THREE.OrbitControls;


// 1. 核心安全防御系统 (直接内联，不再依赖 common.js)
function initSecurity() {
    document.addEventListener('contextmenu', event => event.preventDefault());
    document.addEventListener('keydown', event => {
        if (
            event.key === 'F12' || 
            (event.ctrlKey && event.shiftKey && event.key === 'I') || 
            (event.ctrlKey && event.shiftKey && event.key === 'C') || 
            (event.ctrlKey && event.shiftKey && event.key === 'J') || 
            (event.ctrlKey && event.key === 'U')
        ) {
            event.preventDefault();
        }
    });
}

// 2. 品牌专属水印（直接渲染进 WebGL 底层画布，无法通过 DOM 修改/删除）
function initWatermark() {
    const wmCanvas = document.createElement('canvas');
    wmCanvas.width = 1200; wmCanvas.height = 50;
    const ctx = wmCanvas.getContext('2d');

    function drawWatermark(light) {
        ctx.clearRect(0, 0, 1200, 50);
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.letterSpacing = '1px';
        const mainColor = light ? 'rgba(25, 45, 75, 0.9)' : 'rgba(255, 255, 255, 0.9)';
        const subColor = light ? 'rgba(25, 45, 75, 0.55)' : 'rgba(255, 255, 255, 0.55)';
        const outline = light ? 'rgba(255, 255, 255, 0.7)' : 'rgba(0, 0, 0, 0.6)';
        const part1 = '';
        const part2 = '';
        ctx.font = 'bold 26px "Microsoft YaHei", "PingFang SC", sans-serif';
        const w1 = ctx.measureText(part1).width;
        const w2 = ctx.measureText(part2).width;
        const gap = 18;
        const total = w1 + gap + w2;
        const x1 = 600 - total / 2 + w1 / 2;
        const x2 = x1 + w1 / 2 + gap + w2 / 2;
        ctx.lineWidth = 5;
        ctx.strokeStyle = outline;
        ctx.strokeText(part1, x1, 25);
        ctx.strokeText(part2, x2, 25);
        ctx.fillStyle = mainColor;
        ctx.fillText(part1, x1, 25);
        ctx.fillStyle = subColor;
        ctx.fillText(part2, x2, 25);
    }
    drawWatermark(false);

    const texture = new THREE.CanvasTexture(wmCanvas);
    const material = new THREE.MeshBasicMaterial({ map: texture, transparent: true, depthTest: false, depthWrite: false });
    const geometry = new THREE.PlaneGeometry(0.52, 0.0347);
    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.set(0, -0.93, 0);
    const scene = new THREE.Scene();
    scene.add(mesh);
    const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

    return {
        scene, camera,
        setTheme(light) { drawWatermark(light); texture.needsUpdate = true; },
        setPosition(cx, cy, width) {
            const k = width / 0.52;
            mesh.scale.set(k, k, 1);
            mesh.position.set(cx, cy, 0);
        }
    };
}

// 3. 动态注入全局 UI 皮肤
function injectGlobalStyles() {
    if (document.getElementById('xunwei-engine-styles')) return;
    const styleElement = document.createElement('style');
    styleElement.id = 'xunwei-engine-styles';
    styleElement.innerHTML = `
        body { margin: 0; padding: 0; overflow: hidden; font-family: 'Microsoft YaHei', sans-serif; background-color: #000; }
        #app-container { display: flex; width: 100vw; height: 100vh; background-color: #111122; overflow: hidden; }
        #sidebar {
            width: 145px; position: relative; z-index: 100; flex-shrink: 0; 
            background: rgba(20, 20, 30, 0.6); border-right: 1px solid #334;
            box-shadow: 2px 0 10px rgba(0,0,0,0.5); display: flex; flex-direction: column;
        }
        #canvas-area { flex: 1; position: relative; overflow: hidden; background: #0a0a12; }
        canvas { display: block; width: 100%; height: 100%; outline: none; }
        #info { 
            padding: 15px 8px 10px 8px; background: rgba(15, 15, 25, 0.85); color: white; 
            border-bottom: 1px solid #444; display: flex; flex-direction: column; gap: 8px; 
            font-size: 11px; box-sizing: border-box; pointer-events: none; flex-shrink: 0;
        }
        #info-title { font-weight: bold; font-size: 13px; border-bottom: 1px solid #555; padding-bottom: 5px; text-align: center; color: #55cc55;}
        .legend-item { display: flex; align-items: center; gap: 6px; line-height: 1.2; }
        .color-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0;}
        .dot-cl { background: #55cc55; box-shadow: 0 0 5px #55cc55;} 
        .dot-na { background: #aa66cc; box-shadow: 0 0 5px #aa66cc;} 
        #controls-panel { 
            padding: 10px 8px; color: white; display: flex; flex-direction: column; gap: 8px; 
            box-sizing: border-box; font-size: 11px; overflow-y: auto; flex-grow: 1;
        }
        #controls-panel::-webkit-scrollbar { width: 3px; }
        #controls-panel::-webkit-scrollbar-thumb { background: #55aa55; border-radius: 3px; }
        .control-section { display: flex; flex-direction: column; gap: 5px; margin-bottom: 4px;}
        .control-section h4 { margin: 0; font-size: 11px; color: #ddd; text-align: center; border-bottom: 1px dashed #555; padding-bottom: 3px;}
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; }
        .btn-ico { display: inline-block; width: 13px; height: 13px; margin-right: 5px; vertical-align: -2px; flex-shrink: 0; }
        .view-btn, .filter-btn, .large-cell-btn, .step-btn, .intro-btn, .toggle-btn, .reset-btn, .diamond-btn {
            background: linear-gradient(145deg, rgba(255,255,255,0.11) 0%, rgba(255,255,255,0.05) 100%);
            border: 1px solid rgba(255,255,255,0.16);
            color: #eaf2ff; padding: 6px 0; border-radius: 12px; font-size: 11px;
            cursor: pointer; transition: all 0.2s; text-align: center;
            text-shadow: 0 1px 3px rgba(0,0,0,0.7);
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.16), 0 4px 10px rgba(0,0,0,0.18);
            -webkit-backdrop-filter: blur(10px) saturate(160%);
            backdrop-filter: blur(10px) saturate(160%);
        }
        .view-btn:hover, .filter-btn:hover, .large-cell-btn:hover, .step-btn:hover, .intro-btn:hover, .toggle-btn:hover, .reset-btn:hover, .diamond-btn:hover {
            background: linear-gradient(145deg, rgba(255,255,255,0.18) 0%, rgba(255,255,255,0.09) 100%);
            border-color: rgba(150,190,255,0.55);
        }
        .filter-btn.active-filter, .view-btn.active {
            background: linear-gradient(145deg, rgba(102,170,255,0.30) 0%, rgba(80,140,230,0.17) 100%);
            border-color: rgba(140,195,255,0.85);
            color: #fff;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.20), 0 0 12px rgba(102,170,255,0.40);
        }
        .anim-btn, .transform-btn, #btn-intro, #btn-start, #btn-next {
            background: linear-gradient(145deg, var(--crystal-c1, rgba(90,170,255,0.34)), var(--crystal-c2, rgba(40,110,220,0.20)));
            border: 1px solid rgba(255,255,255,0.35);
            color: #fff; padding: 8px 4px; border-radius: 12px;
            font-weight: bold; cursor: pointer; font-size: 11px; text-align: center; line-height: 1.3;
            text-shadow: 0 1px 3px rgba(0,0,0,0.8);
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.25), 0 4px 12px rgba(0,0,0,0.22);
            -webkit-backdrop-filter: blur(10px) saturate(160%);
            backdrop-filter: blur(10px) saturate(160%);
        }
        .anim-btn:hover, .transform-btn:hover { border-color: rgba(255,255,255,0.60); }
        /* 交互分析四键角色色（方案 A：蓝/紫/青/橙） */
        .role-coord { background: linear-gradient(145deg, rgba(88,166,255,0.16) 0%, rgba(50,110,220,0.08) 100%); border-color: rgba(88,166,255,0.45); }
        .role-coord:hover { border-color: rgba(88,166,255,0.75); }
        .role-coord.active-filter, .role-coord.active { background: linear-gradient(145deg, rgba(88,166,255,0.32) 0%, rgba(60,130,235,0.18) 100%); border-color: rgba(140,195,255,0.85); box-shadow: inset 0 1px 0 rgba(255,255,255,0.20), 0 0 12px rgba(88,166,255,0.40); }
        .role-same { background: linear-gradient(145deg, rgba(176,108,255,0.16) 0%, rgba(120,70,220,0.08) 100%); border-color: rgba(176,108,255,0.45); }
        .role-same:hover { border-color: rgba(176,108,255,0.75); }
        .role-same.active-filter, .role-same.active { background: linear-gradient(145deg, rgba(176,108,255,0.32) 0%, rgba(140,85,235,0.18) 100%); border-color: rgba(205,165,255,0.85); box-shadow: inset 0 1px 0 rgba(255,255,255,0.20), 0 0 12px rgba(176,108,255,0.40); }
        .role-void { background: linear-gradient(145deg, rgba(53,208,224,0.16) 0%, rgba(30,150,180,0.08) 100%); border-color: rgba(53,208,224,0.45); }
        .role-void:hover { border-color: rgba(53,208,224,0.75); }
        .role-void.active-filter, .role-void.active { background: linear-gradient(145deg, rgba(53,208,224,0.32) 0%, rgba(35,170,200,0.18) 100%); border-color: rgba(130,235,245,0.85); box-shadow: inset 0 1px 0 rgba(255,255,255,0.20), 0 0 12px rgba(53,208,224,0.40); }
        .role-share { background: linear-gradient(145deg, rgba(255,171,94,0.16) 0%, rgba(220,130,60,0.08) 100%); border-color: rgba(255,171,94,0.45); }
        .role-share:hover { border-color: rgba(255,171,94,0.75); }
        .role-share.active-filter, .role-share.active { background: linear-gradient(145deg, rgba(255,171,94,0.32) 0%, rgba(235,145,75,0.18) 100%); border-color: rgba(255,200,140,0.85); box-shadow: inset 0 1px 0 rgba(255,255,255,0.20), 0 0 12px rgba(255,171,94,0.40); }
        .atom-filter-group { display: flex; flex-direction: column; gap: 4px; }
        @media (prefers-reduced-transparency: reduce) {
            .view-btn, .filter-btn, .large-cell-btn, .step-btn, .intro-btn, .toggle-btn, .reset-btn, .diamond-btn, .anim-btn, .transform-btn {
                background: rgba(24, 32, 48, 0.95) !important;
                -webkit-backdrop-filter: none !important;
                backdrop-filter: none !important;
            }
        }
        #app-container.light-bg .view-btn, #app-container.light-bg .filter-btn, #app-container.light-bg .diamond-btn,
        #app-container.light-bg .large-cell-btn, #app-container.light-bg .step-btn,
        #app-container.light-bg .intro-btn, #app-container.light-bg .toggle-btn,
        #app-container.light-bg .reset-btn, #app-container.light-bg .anim-btn,
        #app-container.light-bg .transform-btn {
            background: rgba(255,255,255,0.55);
            border-color: rgba(70,90,120,0.35);
            color: #223;
            text-shadow: none;
        }
        .slider-container { display: flex; flex-direction: column; gap: 2px; }
        .slider-container label { font-size: 11px; color: #ccc; display: flex; justify-content: space-between; font-weight: bold; }
        .slider-container input { width: 100%; cursor: pointer; height: 4px; margin-top: 3px; }
        #axes-container { position: absolute; right: 15px; bottom: 60px; width: 80px; height: 80px; pointer-events: none; z-index: 1000; }
        #info-tooltip { position: absolute; top: 15px; right: 15px; background: rgba(10, 15, 25, 0.95); color: #fff; padding: 12px 25px 12px 15px; border-radius: 10px; border: 1px solid #55cc55; pointer-events: auto; display: none; z-index: 1000; font-size: 13px; line-height: 1.5; box-shadow: 0 4px 15px rgba(0,0,0,0.8); min-width: 200px; max-width: 260px; }
        #info-tooltip strong { font-size: 14px; border-bottom: 1px solid #555; padding-bottom: 5px; display: block; margin-bottom: 6px; }
        .close-btn { position: absolute; top: 5px; right: 8px; font-size: 18px; color: #999; cursor: pointer; font-weight: bold; line-height: 1; transition: 0.2s;}
        .close-btn:hover { color: #ff3333; transform: scale(1.2); }
    `;
    document.head.appendChild(styleElement);
}

// 渲染器安全工厂：部分 GPU/驱动会对特定属性组合拒绝创建 WebGL 上下文，
// 这里按优先级逐级降级（去掉 stencil → 去掉抗锯齿 → 最简参数）重试，
// 避免直接抛出 “Error creating WebGL context.”
//
// ★ 关键：必须先把「three.js 没加载成功」和「WebGL 真的不可用」区分开。
//   若 THREE 未定义，new THREE.WebGLRenderer 抛的是 ReferenceError，
//   会被下面的 catch 吞掉，最终伪装成「WebGL 创建失败」——报错完全指错方向。
function createRenderer(attrs) {
    if (typeof THREE === 'undefined' || !THREE.WebGLRenderer) {
        throw new Error('three.js 未加载成功（three.min.js 可能下载失败或被浏览器缓存损坏）。'
            + '请按 Ctrl+F5 强制刷新本页；若仍无效，请清空浏览器缓存后重试。');
    }
    const attempts = [
        attrs,
        Object.assign({}, attrs, { stencil: false }),
        Object.assign({}, attrs, { stencil: false, antialias: false }),
        { alpha: true },
        {}
    ];
    let lastErr = null;
    for (const attempt of attempts) {
        try {
            return new THREE.WebGLRenderer(attempt);
        } catch (e) {
            lastErr = e;          // 保留最后一次的真实原因，别无声吞掉
        }
    }
    throw new Error('无法创建 WebGL 渲染上下文。请依次尝试：'
        + '①完全退出浏览器（不是关窗口）再重新打开；'
        + '②浏览器设置里开启“使用硬件加速”后重启浏览器；'
        + '③换用 Chrome / Edge 最新版；'
        + '④关掉其他已打开的 3D 页面后刷新。'
        + '（原始错误：' + ((lastErr && lastErr.message) || '未知') + '）');
}

// ==========================================
// 🚀 对外暴露的大管家核心函数
// ==========================================
// 扁平线性图标（全站按钮统一符号）
const ICONS = {
    play: '<svg class="btn-ico" viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden="true"><path d="M8 5.14v13.72L19 12z"/></svg>',
    rotate: '<svg class="btn-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>',
    eye: '<svg class="btn-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>',
    sun: '<svg class="btn-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.2M12 19.3v2.2M4.3 4.3l1.6 1.6M18.1 18.1l1.6 1.6M2.5 12h2.2M19.3 12h2.2M4.3 19.7l1.6-1.6M18.1 5.9l1.6-1.6"/></svg>',
    moon: '<svg class="btn-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>',
    box: '<svg class="btn-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>'
};

function createStage(containerId, axesContainerId) {
    // 启动基础环境
    initSecurity();
    const watermark = initWatermark();
    injectGlobalStyles();

    const container = document.getElementById(containerId);
    const axesContainer = document.getElementById(axesContainerId);

    let w = container.clientWidth || window.innerWidth;
    let h = container.clientHeight || window.innerHeight;
    let aspect = w / h;

    const scene = new THREE.Scene();
    scene.add(new THREE.AmbientLight(0xffffff, 0.7));
    const dirLight1 = new THREE.DirectionalLight(0xffffff, 0.6);
    dirLight1.position.set(10, 20, 15);
    scene.add(dirLight1);
    const dirLight2 = new THREE.DirectionalLight(0xaaccff, 0.3);
    dirLight2.position.set(-10, -10, -10);
    scene.add(dirLight2);

    const perspCamera = new THREE.PerspectiveCamera(45, aspect, 0.1, 1000);
    perspCamera.up.set(0, 0, 1);
    
    // 修复：将正交相机的近裁剪面 (near) 修改为 -100 防穿透
    const orthoCamera = new THREE.OrthographicCamera(-6 * aspect, 6 * aspect, 6, -6, -100, 1000);
    orthoCamera.up.set(0, 0, 1);

    const engineState = { activeCamera: perspCamera };

    const renderer = createRenderer({ antialias: true, alpha: true, stencil: true });
    renderer.setSize(w, h);
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.autoClear = false;
    renderer.localClippingEnabled = true;
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(perspCamera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 1.0;
    
    // 限制鼠标滚轮的最远和最近缩放距离
    controls.minDistance = 4.0;  
    controls.maxDistance = 60.0; 

    /* 小坐标轴要占第二个 WebGL 上下文。某些预览环境（如 VS Code 内置预览）只给一个上下文，
       这里建不出来就静默跳过坐标轴——绝不中断后面的渲染循环、按钮绑定和转换动画。 */
    let axesRenderer = null;
    try {
        axesRenderer = createRenderer({ alpha: true, antialias: true });
    } catch (axesErr) {
        axesRenderer = null;
    }
    if (axesRenderer) {
        axesRenderer.setSize(80, 80);
        axesContainer.appendChild(axesRenderer.domElement);
    }
    const axesScene = new THREE.Scene();
    const axesCamera = new THREE.PerspectiveCamera(50, 1, 0.1, 100);
    
    function makeTextSprite(msg, color) {
        const canvas = document.createElement('canvas'); canvas.width = 64; canvas.height = 64;
        const ctx = canvas.getContext('2d'); ctx.fillStyle = color; ctx.font = 'bold 44px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText(msg, 32, 32); const tex = new THREE.CanvasTexture(canvas);
        const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false })); sprite.scale.set(0.6, 0.6, 0.6); return sprite;
    }
    axesScene.add(new THREE.ArrowHelper(new THREE.Vector3(1,0,0), new THREE.Vector3(0,0,0), 1.2, 0xff3333, 0.4, 0.2));
    const xLbl = makeTextSprite('X', '#ff3333'); xLbl.position.set(1.5, 0, 0); axesScene.add(xLbl);
    axesScene.add(new THREE.ArrowHelper(new THREE.Vector3(0,1,0), new THREE.Vector3(0,0,0), 1.2, 0x33ff33, 0.4, 0.2));
    const yLbl = makeTextSprite('Y', '#33ff33'); yLbl.position.set(0, 1.5, 0); axesScene.add(yLbl);
    axesScene.add(new THREE.ArrowHelper(new THREE.Vector3(0,0,1), new THREE.Vector3(0,0,0), 1.2, 0x3388ff, 0.4, 0.2));
    const zLbl = makeTextSprite('Z', '#3388ff'); zLbl.position.set(0, 0, 1.5); axesScene.add(zLbl);

    // ==========================================
    // 🌟 核心：全局统一的自适应视角管理
    // ==========================================
    function setCameraView(type, gridSize) {
        // 1. 获取新模型的三维中心点
        const centerPos = gridSize / 2;
        const targetPos = new THREE.Vector3(centerPos, centerPos, centerPos);
        controls.target.copy(targetPos);

        // 2. 根据尺寸动态绑定距离系数
        let camD = gridSize * 3;

        if (type === 'perspective') {
            engineState.activeCamera = perspCamera;
            // 3. 注入黄金比例视角，确保 Z 轴朝上
            perspCamera.position.set(targetPos.x + camD * 0.8, targetPos.y - camD * 0.8, targetPos.z + camD * 0.6);
            perspCamera.up.set(0, 0, 1);
        } else {
            engineState.activeCamera = orthoCamera;
            let d = gridSize * 3.5;
            
            // 动态调节正交相机的视锥体范围以适配大小晶胞
            let orthoRange = gridSize === 8 ? 10 : 6;
            let currentAspect = container.clientWidth / container.clientHeight;
            orthoCamera.left = -orthoRange * currentAspect;
            orthoCamera.right = orthoRange * currentAspect;
            orthoCamera.top = orthoRange;
            orthoCamera.bottom = -orthoRange;

            if (type === 'x') { orthoCamera.position.set(targetPos.x + d, targetPos.y, targetPos.z); orthoCamera.up.set(0, 0, 1); }
            if (type === 'y') { orthoCamera.position.set(targetPos.x, targetPos.y - d, targetPos.z); orthoCamera.up.set(0, 0, 1); }
            // 加入 + 0.001 跨越计算临界点，完美解决顶视拖拽反向问题
            if (type === 'z') { orthoCamera.position.set(targetPos.x, targetPos.y + 0.001, targetPos.z + d); orthoCamera.up.set(0, 0, 1); }
            if (type === 'diag') { orthoCamera.position.set(targetPos.x + d, targetPos.y - d, targetPos.z + d); orthoCamera.up.set(0, 0, 1); }

            orthoCamera.lookAt(targetPos);
            orthoCamera.updateProjectionMatrix();
        }
        
        // 4. 让控制器更新生效
        controls.object = engineState.activeCamera;
        controls.update();
    }

    let wmTheme = null;
    function animate() {
        requestAnimationFrame(animate);
        controls.update();
        renderer.clear();
        renderer.setViewport(0, 0, container.clientWidth, container.clientHeight);
        renderer.render(scene, engineState.activeCamera);
        renderer.clearDepth();
        renderer.render(watermark.scene, watermark.camera);
        const lightNow = container.classList.contains('light-bg');
        if (lightNow !== wmTheme) { wmTheme = lightNow; watermark.setTheme(lightNow); }

        if (axesRenderer) {
            axesCamera.position.copy(engineState.activeCamera.position).sub(controls.target).normalize().multiplyScalar(4);
            axesCamera.lookAt(0,0,0);
            axesCamera.up.copy(engineState.activeCamera.up);
            axesRenderer.clear();
            axesRenderer.render(axesScene, axesCamera);
        }
    }
    animate();

    window.addEventListener('resize', () => {
        w = container.clientWidth || window.innerWidth;
        h = container.clientHeight || window.innerHeight;
        perspCamera.aspect = w / h;
        perspCamera.updateProjectionMatrix();
        renderer.setSize(w, h);
    }, false);

    // 页面被替换/关闭时主动释放 WebGL 上下文，
    // 防止 iframe 中反复切换模型导致上下文耗尽而创建失败
    window.addEventListener('pagehide', (event) => {
        if (event.persisted) return;
        try { renderer.forceContextLoss(); } catch (e) {}
        try { axesRenderer.forceContextLoss(); } catch (e) {}
    });

    // 把 setCameraView 方法暴露给 HTML 业务层
    const api = { scene, perspCamera, orthoCamera, renderer, controls, engineState, setCameraView, watermark };

    /* ★ 把舞台句柄挂到画布元素上：_capture.js（保存图片）要靠它拿 renderer / scene / 当前相机，
       才能按 2 倍分辨率重渲一张高清图。挂在元素上而不是 window，是为了多画布页面不打架。 */
    try { renderer.domElement.__stage = api; } catch (e) {}

    return api;
}

// —— 暴露为全局变量，供传统 <script> 页面直接调用 ——
window.ICONS = ICONS;
window.createStage = createStage;
})();
