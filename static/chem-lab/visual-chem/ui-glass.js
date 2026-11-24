// ui-glass.js：磨砂玻璃 UI 共享辅助（功能标签、水印定位、视角旋转动画）
// ★ 传统 UMD 版：不再使用 ES Module，见 Engine.js 顶部说明。
(function () {
'use strict';
var THREE = window.THREE;

const GlassUI = {
    /* ★ 相机动画代际（2026-11-12）：每次 animateOrtho 开始都 +1，帧里发现代际变了就收工。
       这样「后发起的视角/功能」自然接管，旧轨迹不会再拖相机；页面 cancelAnim 时调 cancelCam() 即可作废在途动画。 */
    __camSeq: 0,
    cancelCam() { this.__camSeq++; },

    // 创建画布级水印（供不使用 Engine.js 的页面使用）
    createWatermark() {
        const wmCanvas = document.createElement('canvas');
        wmCanvas.width = 1200; wmCanvas.height = 50;
        const ctx = wmCanvas.getContext('2d');
        const texture = new THREE.CanvasTexture(wmCanvas);
        const material = new THREE.MeshBasicMaterial({ map: texture, transparent: true, depthTest: false, depthWrite: false });
        const geometry = new THREE.PlaneGeometry(0.52, 0.0347);
        const mesh = new THREE.Mesh(geometry, material);
        mesh.position.set(0, -0.93, 0);
        const scene = new THREE.Scene();
        scene.add(mesh);
        const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

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

        return {
            setPosition(cx, cy, width) {
                const k = width / 0.52;
                mesh.scale.set(k, k, 1);
                mesh.position.set(cx, cy, 0);
            },
            setTheme(light) { drawWatermark(light); texture.needsUpdate = true; },
            render(renderer) {
                renderer.clearDepth();
                renderer.render(scene, camera);
            }
        };
    },

    // 晶胞面板右上角功能名称
    setCellFunction(name) {
        const el = document.getElementById('cell-fn-label');
        if (el) el.textContent = name;
    },

    // 水印定位到晶胞面板正下方（画布底部居中）
    placeWatermark(canvasArea, watermark) {
        if (!watermark || !canvasArea) return;
        const r = canvasArea.getBoundingClientRect();
        const cy = 1 - 2 * (r.height - 22) / r.height;
        const targetPx = Math.min(620, r.width * 0.48);
        const wmWidth = (targetPx / r.width) * 2 / 0.82;
        watermark.setPosition(0, cy, wmWidth);
    },

    // 视角切换过渡：先回到"标准正方体视角"的正交投影，再缓慢匀速转动到目标角度
    //   （10-04：点「对角」时第一步改成"初始视角向右转一些、再向上仰一点"，见函数内 wantCubePose）
    // opts: { orthoCamera, controls, engineState?, canvasArea, type, isLargeCell, maxCoord, pauseBtn,
    //         target, initPos, endPos(type, target, d), onStart(orthoCamera), up?(默认(0,0,1)), viewRadius? }
    // 返回 Promise，动画结束时 resolve
    animateOrtho(opts) {
        return new Promise((resolve) => {
            const __camSeq = ++GlassUI.__camSeq;   /* 本段动画的代际；被新动画/取消超过就不再写帧 */
            const { orthoCamera, controls, engineState, canvasArea, type } = opts;
            const isLargeCell = opts.isLargeCell || (() => false);
            const maxCoord = opts.maxCoord || (() => 4);
            const pauseBtn = opts.pauseBtn || document.getElementById('btn-pause');

            const centerPt = maxCoord() / 2;
            const target = opts.target ? opts.target.clone() : new THREE.Vector3(centerPt, centerPt, centerPt);
            const camD = isLargeCell() ? 24 : 12;
            const initPos = opts.initPos || new THREE.Vector3(
                target.x + camD * 0.8, target.y - camD * 0.8, target.z + camD * 0.6
            );
            const d = isLargeCell() ? 24 : 16.5;
            let endPos;
            if (opts.endPos) endPos = opts.endPos(type, target, d);
            else {
                if (type === 'x') endPos = new THREE.Vector3(target.x + d, target.y, target.z);
                else if (type === 'y') endPos = new THREE.Vector3(target.x, target.y - d, target.z);
                else if (type === 'z') endPos = new THREE.Vector3(target.x, target.y, target.z + d); // 纯天顶，下方 zenithSafe 会摆正
                else endPos = new THREE.Vector3(target.x + d, target.y - d, target.z + d);
            }

            /* ★ 10-04 用户要求：点「对角」时，第一步**不停在初始视角**，而是停在
               「标准正方体视角」= 初始视角**绕竖轴右转 cubeYawDeg°**，俯角压到 **cubeElDeg°**（绝对值）
               （就是课本里最常见的那个"能看清三个面"的正方体角度），
               停到这个角度之后，再匀速转到对角线投影（正六边形那个角度）。
               ★ 只对 diag 生效 —— X / Y / Z 三个轴视角仍照旧直接回初始视角，别乱动。
               ★ 方向/大小都可覆盖：opts.cubeYawDeg / opts.cubeElDeg；
                 若某页不想用这套，传 opts.cubePose = false。 */
            const wantCubePose = (type === 'diag') && opts.cubePose !== false;
            const cubeYawDeg = (opts.cubeYawDeg !== undefined) ? opts.cubeYawDeg : 25;
            /* ★ 停点的**俯角**（绝对仰角，10-04 三次修）：
               用户截图标定的角度是「正面基本正对、顶面压成扁菱形」，俯角约 20°。
               ⚠ 初始视角自身已经是 el≈28°（camD×(0.8,-0.8,0.6)），所以要**往下压到 20°**，
                 不是再往上抬 —— 上一版写成 el0+10°（=38°，俯得太狠），这才是他一直不满意的原因。
               ⇒ 这里改用**绝对角度**，以后他直接说「俯 15°」就改这个数，别再写成相对增量。 */
            const cubeElDeg = (opts.cubeElDeg !== undefined) ? opts.cubeElDeg : 20;
            let startPos = initPos;
            if (wantCubePose) {
                const v0 = initPos.clone().sub(target);
                const r0 = v0.length() || 1;
                const az0 = Math.atan2(v0.y, v0.x);
                const az1 = az0 + THREE.MathUtils.degToRad(cubeYawDeg);   // 绕竖轴右转（保持相对增量）
                const el1 = THREE.MathUtils.degToRad(cubeElDeg);          // 俯角：绝对值
                const ce = Math.cos(el1);
                startPos = target.clone().add(new THREE.Vector3(
                    r0 * ce * Math.cos(az1), r0 * ce * Math.sin(az1), r0 * Math.sin(el1)
                ));
            }

            /* ★★ Z 轴（沿 up 轴看）过渡"最后猛顿一下 / 绕远"的根因与修法（10-04 二次修）：
               终点几乎正对天顶（el≈90°，只在 y 上偏 0.001），球面上经度在高纬被压缩 ~70 倍，
               于是最后几帧画面绕视线轴猛扫 135°（看着就是卡顿，而且路径明显绕远）。
               修法：① 天顶终点按 el 留出 ZENITH_GAP 余量（不再贴着极点，数值也稳了）；
                     ② 把它的方位角**吸附到离起始方位最近的正交方位**（-90/0/90/180，
                        平手时取 -90° ⇒ 标准俯视：+X 向右、+Y 向上），roll 只变 ≤45°，路径最短。
                     ③ 只对接近天顶的终点生效（|el| > 88°），X / Y / 对角一律不碰。 */
            const ZENITH_GAP = THREE.MathUtils.degToRad(0.8);
            (function zenithSafe() {
                /* 下面这段是**按 Z-up 写死的**（用 v.z 量仰角、把方位角摆到 x/y 平面）。
                   传了 opts.up（Y-up 页面，如 zn）就**直接跳过** —— 它们本来就该像冰 / 石墨那样
                   给终点加极小倾角（Z_TILT）跨过退化点，用不着这里的吸附。
                   ⚠️ 这里只能用 opts.up，**不能写 up**：up 在这一段之后才声明（const 有暂时性死区），
                      写 up 会抛 "Cannot access 'up' before initialization" ⇒ 全站视角按钮失效。 */
                const upIsZ = !opts.up || Math.abs(opts.up.z) > 0.999;
                if (!upIsZ) return;
                const v = endPos.clone().sub(target);
                const r = v.length() || 1;
                const el = Math.asin(THREE.MathUtils.clamp(v.z / r, -1, 1));
                if (Math.abs(el) < THREE.MathUtils.degToRad(88)) return;
                const v0 = startPos.clone().sub(target);
                const az0 = Math.atan2(v0.y, v0.x);
                const cands = [-Math.PI / 2, 0, Math.PI / 2, Math.PI]; // 平手优先 -90°（标准俯视）
                let best = cands[0], bd = Infinity;
                for (let i = 0; i < cands.length; i++) {
                    const raw = ((cands[i] - az0) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI);
                    const dd = raw > Math.PI ? 2 * Math.PI - raw : raw;
                    if (dd < bd - 1e-6) { bd = dd; best = cands[i]; }
                }
                const e2 = (el < 0 ? -1 : 1) * (Math.PI / 2 - ZENITH_GAP);
                const ce = Math.cos(e2);
                endPos = target.clone().add(new THREE.Vector3(
                    r * ce * Math.cos(best), r * ce * Math.sin(best), r * Math.sin(e2)
                ));
            })();

            const viewRadius = opts.viewRadius || (isLargeCell() ? 10 : 6);
            const asp = canvasArea.clientWidth / canvasArea.clientHeight;
            orthoCamera.left = -viewRadius * asp; orthoCamera.right = viewRadius * asp;
            orthoCamera.top = viewRadius; orthoCamera.bottom = -viewRadius;
            orthoCamera.updateProjectionMatrix();

            /* ★ 全站晶胞页的"竖直"约定是 (0,0,1)（c 轴朝屏幕上方）。
               ⚠️ **例外**：锌（zn.html）是 Y-up —— 层堆叠方向 c 在 three.js 里是 +Y。
                  这类页面必须传 opts.up，否则这里算出来的 lookAt 基准和它自己的 camera.up 不是一套，
                  动画结束后画面会被 lookAt 重算 ⇒ 看起来"到位了又跳一下"，拖拽行为也会怪。 */
            const up = (opts.up ? opts.up.clone() : new THREE.Vector3(0, 0, 1)).normalize();
            const dist = startPos.distanceTo(target);
            /* ★★★★ 真凶与修法（10-04 十二次修，一次改到位）
               现象：Z 轴动画快到位时「正方形一个角朝下」，下一瞬被硬拉成「一条边水平」。
               数值实测（_sim_zview.js）：最后 1/60 段一次甩 36.37°，而全程总滚转才 25.1°，
                   最后 20% 的时间承担了 167.6% 的滚转；方位角在前 95% 只从 -45° 挪到 -53.6°，
                   最后 5% 才冲到 -90° —— 画面就是在这最后几帧整块甩正的。
               根因：**我们写进相机的姿态，下一帧就被抹掉了** ——
                   Engine.js 渲染循环每帧执行 controls.update()，而 OrbitControls.update() 最后一句
                   是 `object.lookAt(target)`，它只用「相机位置 + camera.up」重算**整套**姿态。
                   ⇒ 之前写的"画面滚转线性插值"根本没显示出来（写了也被 lookAt 覆盖），
                     屏幕上看到的是"相机沿大圆走位"自带的那条滚转曲线 —— 而大圆在接近天顶时
                     经度被压扁约 70 倍 ⇒ 方位角全挤在末帧变化 ⇒ 就是那一下硬拉。
               修法（两处，缺一不可）：
                 ① 每帧把 camera.up 写成**本帧自己的竖轴 camY**：cross(camY, 视线) ≡ camX，
                    于是 lookAt **原样复现**我们的姿态，插值才真正生效（画面滚转严格线性）。
                 ② 收工时把 up 恢复成全站约定 (0,0,1)：终点姿态本来就是 lookAt(endPos, up) 算出来的，
                    所以恢复那一刻**零跳变**，之后拖拽行为也和从前一致。 */
            // 画面滚转读数：世界 +X 轴在屏幕里的方向角（0° = 正方形一条边水平）
            function rollStd(b) { return Math.atan2(b.y.x, b.x.x); }
            const mkRot = new THREE.Matrix4();
            // 与 THREE.Matrix4.lookAt(eye,target,up) **逐行一致**的标准姿态（单一 truth，别再另起一套 ref）
            function lookBasis(dir) {
                const z = dir.clone().normalize();
                const x = new THREE.Vector3().crossVectors(up, z);
                if (x.lengthSq() < 1e-12) {                      // 退化兜底照抄 three
                    if (Math.abs(up.z) === 1) z.x += 0.0001; else z.z += 0.0001;
                    z.normalize(); x.crossVectors(up, z);
                }
                x.normalize();
                return { x, y: new THREE.Vector3().crossVectors(z, x), z };
            }
            // 「视线方向 + 绝对画面滚转角」→ 相机姿态；顺带返回 camY（写 camera.up 用）
            function poseOf(dir, rollAbs) {
                const b = lookBasis(dir);
                const psi = rollStd(b) - rollAbs;
                const camX = b.x.clone().multiplyScalar(Math.cos(psi)).addScaledVector(b.y, Math.sin(psi));
                const camY = new THREE.Vector3().crossVectors(b.z, camX).normalize();
                const q = new THREE.Quaternion().setFromRotationMatrix(mkRot.makeBasis(camX, camY, b.z));
                return { q, camY };
            }
            const d0 = startPos.clone().sub(target).normalize();
            const d1 = endPos.clone().sub(target).normalize();
            const roll0 = rollStd(lookBasis(d0)), roll1 = rollStd(lookBasis(d1));
            let dRoll = roll1 - roll0;
            while (dRoll > Math.PI) dRoll -= 2 * Math.PI;
            while (dRoll < -Math.PI) dRoll += 2 * Math.PI;
            /* ★★ 只对「视线贴着 up 轴」的视角启用"画面滚转线性插值"（典型就是 Z 轴俯视）：
                  X / Y / 对角一律保持原样 —— 姿态完全由 lookAt(位置, up) 决定（12 次修用户原话：
                  「x、y轴原来就很好不要动」；上一版把它们也改成线性插值 ⇒ 末帧出现同款硬拉）。
               判据 = 终点方向与 up 的夹角 < 10°（等价于 |d1·up| > cos10°）；可用 opts.linearRoll 覆盖。 */
            const linearRoll = (opts.linearRoll !== undefined)
                ? opts.linearRoll
                : Math.abs(d1.dot(up)) > Math.cos(THREE.MathUtils.degToRad(10));
            const qArc = new THREE.Quaternion().setFromUnitVectors(d0, d1);
            const qId = new THREE.Quaternion();
            const p0 = poseOf(d0, roll0), p1 = poseOf(d1, roll1);   // 等价于 lookAt(start/endPos, target, up)
            const q0 = p0.q, q1 = p1.q;
            /* ★ 判"匀不匀"要测**画面滚转**（世界 +X 在屏幕上转过的角度），不能只测点的位移：
               只测 8 个角点的屏幕位移时一切正常（最后 1 秒占 19.7%，理想 20%），
               但同一条路径的画面滚转在末段是首段的几倍 —— 眼睛看的正是后者。 */
            /* （旧的 basisRef / rollRefOf / quatFrom 已在十二次修中删掉：
                 它们用 (0,1,0) 兜底、和 lookAt 的兜底不是一套 ⇒ 补偿角对不上；现在统一走 lookBasis + poseOf。） */
            /* ★ 匀速的实现就是 slerp：四元数插值保证**每一帧转过的角度恒定**
               （实测 Z 轴：每帧 0.747°，峰值/均值 = 1.00）。
               ⚠️ 试过改成「方位角/仰角各自线性插值」，反而更不均（末段画面自转是首段的 1.93 倍，
               因为画面自转分量 ∝ sin(仰角)，越接近天顶越大）⇒ 别再改回球坐标插值。 */

            if (engineState) engineState.activeCamera = orthoCamera;
            if (opts.onStart) opts.onStart(orthoCamera);
            controls.object = orthoCamera;
            controls.target.copy(target);
            controls.autoRotate = false;
            // ★ 动画期间关掉阻尼：渲染循环里每帧 controls.update() 会把上一次拖动的惯性
            //   叠回我们刚设好的相机位上，收尾时表现为"抖一下 / 顿一下"。
            const hadDamping = controls.enableDamping === true;
            if (hadDamping) controls.enableDamping = false;
            if (pauseBtn) {
                pauseBtn.classList.add('paused');
                pauseBtn.innerText = "▶️ 恢复模型自转";
            }
            document.querySelectorAll('.view-btn:not(.pause-btn)').forEach(b => b.classList.remove('active'));
            const targetBtn = document.getElementById('view-' + type);
            if (targetBtn) targetBtn.classList.add('active');

            /* ★★ `up` 的写法（10-04 十二次修，**最关键的一行**）：
               Engine.js 渲染循环每帧 controls.update() → OrbitControls.update() 结尾 `camera.lookAt(target)`，
               lookAt 只用「相机位置 + camera.up」重算整套姿态 ⇒ 我们不改 up，写好的 quaternion 就会被抹掉。
               把 up 写成本帧的竖轴 camY（cross(camY, 视线) ≡ camX），lookAt 就是**恒等复现**。
               本站全部晶胞页约定 up=(0,0,1) ⇒ **动画结束后必须还原**（见 frame 末尾），否则拖拽会怪。 */
            orthoCamera.up.copy(linearRoll ? p0.camY : up);

            // 第一步：先停在「标准正方体视角」的正交投影（diag 时是"初始视角右转+俯 20°"，见上方 wantCubePose）
            orthoCamera.position.copy(target).addScaledVector(d0, dist);
            orthoCamera.quaternion.copy(q0);
            orthoCamera.updateMatrixWorld();

            /* ★ 停留（10-04 六次修 + 七次修）：
               必须跑在**动画帧里**，不能用 setTimeout —— 否则这段时间没有帧推进相机，
               画面冻在点击前那一帧（用户反馈"卡顿 + 角度还是原来那个"就是这个）。
               ★ 七次修：**四个视角一视同仁** —— X轴 / Y轴 / Z轴 / 对角都先停一下再匀速转；
                 diag 停的是"标准正方体角度"，其余停的是初始视角的正交投影（给一个"要往哪转"的参照）。
                 某页想跳过停留：传 opts.holdMs = 0。 */
            const holdMs = (opts.holdMs !== undefined) ? opts.holdMs
                         : (opts.cubeHoldMs !== undefined) ? opts.cubeHoldMs : 550;
            const delay = holdMs;

            // 第二步：从停止角度转到目标角度（基准 15°/秒，末段平滑减速）
            const totalAngle = q0.angleTo(q1);
            const degSpeed = 15;
            let duration = Math.max(900, THREE.MathUtils.radToDeg(totalAngle) / degSpeed * 1000);

            /* ★★ 末段平滑减速（10-04 八次修）：
               几何上 slerp 是匀速的（用晶胞 8 个角点的屏幕位移实测：最后 1 秒占 19.7%，理想 20%，
               末段/首段 = 0.95），所以不是"算错了"。真正的问题是 **Z 轴终点紧贴天顶**：
               同样的相机角速度，在正俯视的画面上被感知成"猛地甩过去"，看着就是最后一秒变快。
               ⇒ 路径前 tailFrom 段保持原速度不变，之后速度**平滑线性**降到 tailSlow 倍收尾
                 （不是突然刹车，全程没有速度突变）；为了不让前半段变快，总时长按解析解同步延长。
               ★ 想回到纯粹匀速：传 opts.tailSlow = 1。
               ★ 想更慢的收尾：把 tailSlow 调小（0.4 左右很稳）；想更早开始减速：tailFrom 调小。 */
            const tailFrom = (opts.tailFrom !== undefined) ? opts.tailFrom : 0.6;
            const tailSlow = (opts.tailSlow !== undefined) ? opts.tailSlow : 0.7;
            const tailK = 1 - tailSlow;
            // 后段相对耗时倍率 = ∫₀¹ du/(1-tailK·u) = ln(1/tailSlow)/tailK
            const tailF = (tailSlow >= 1) ? 1 : Math.log(1 / tailSlow) / tailK;
            const unitTotal = tailFrom + (1 - tailFrom) * tailF;
            duration *= unitTotal;
            /* ★ 「对角」整体放慢 1.5 倍（10-04 用户要求，**只动对角**，X / Y / Z 保持原速）：
               停留段 holdMs 不受影响，只把旋转段拉长；某页要改倍率传 opts.diagSlow。 */
            const diagSlow = (opts.diagSlow !== undefined) ? opts.diagSlow : 1.5;
            if (type === 'diag') duration *= diagSlow;
            // 时间进度 s(0..1) → 路径参数 t(0..1)：反解 前段耗时 + (1-tailFrom)·∫₀^r du/(1-tailK·u)
            function progAt(s) {
                const x = s * unitTotal;
                if (tailSlow >= 1 || x <= tailFrom) return x;
                const X = (x - tailFrom) / (1 - tailFrom);   // 归一到后段内部时间
                const r = (1 - Math.exp(-tailK * X)) / tailK;
                return tailFrom + r * (1 - tailFrom);
            }

            const startTime = performance.now();
            let settleFrames = 0;
            function frame(now) {
                /* ★ 被打断（新视角动画接管 / 页面取消动画 / 点了别的功能）：一帧都不再写，立刻收工。
                   这里必须先把 up 与阻尼还原，否则相机停在「动画专用 up」上，之后拖拽会怪。 */
                if (__camSeq !== GlassUI.__camSeq) {
                    try {
                        orthoCamera.up.copy(up);
                        if (hadDamping) controls.enableDamping = true;
                    } catch (err) { }
                    resolve();
                    return;
                }
                /* ★ 可选打断：调用方传 opts.isCancelled()（如页面自己的动画令牌），
                   返回 true 就立刻收工 —— 不再写任何一帧姿态，把相机交给新动画。 */
                if (typeof opts.isCancelled === 'function' && opts.isCancelled()) {
                    orthoCamera.up.copy(up);
                    if (hadDamping) controls.enableDamping = true;
                    resolve();
                    return;
                }
                const elapsed = now - startTime;
                /* ★★ 结束条件改成**走到位才算完**，不再按时间硬性截止（10-04 十一次修）：
                   用户多次反馈「动画停了但没到目标视角，然后被硬拉过去」——
                   这只能是"时间到了、相机还差一截"，剩下的一截被后续逻辑一次补齐。
                   之前 `elapsed >= delay+duration` 就收工，只要 progAt/duration 有任何偏差
                   （页面传了自定义 endPos、掉帧、首帧时间戳偏晚……）就会停在中途，
                   而且停留/减速参数改得越保守，攒下的差距越大 —— 完美吻合"越改越离谱"。
                   ⇒ 现在：**t 不到 1 就绝不收工**；只有真正走到终点才进入稳定帧。
                   ★ 兜底：超时 3 倍时长强制结束，防止异常情况下卡死（此时也先跳到终点姿态）。 */
                let t = 0;
                if (elapsed >= delay) {
                    t = progAt(Math.min((elapsed - delay) / duration, 1));
                    if (t > 1) t = 1;
                    if (elapsed - delay > duration * 3) t = 1;
                }
                let pose, dir;
                if (t <= 0) { pose = p0; dir = d0; }                       // 停留段：每帧写回 stop 姿态
                else if (t >= 1) { pose = p1; dir = d1; }                  // 收尾精确对齐终点，避免浮点累积留下最后一小跳
                else {
                    dir = d0.clone().applyQuaternion(qId.clone().slerp(qArc, t)).normalize();  // 视线方向：球面插值（最短路）
                    // 画面滚转：只有贴轴视角线性插值，其余沿用 lookAt 的自然滚转（= 改之前的行为）
                    pose = poseOf(dir, linearRoll ? (roll0 + dRoll * t) : rollStd(lookBasis(dir)));
                }
                orthoCamera.position.copy(target).addScaledVector(dir, dist);
                orthoCamera.quaternion.copy(pose.q);
                // ★★ up 跟着本帧姿态走，lookAt 才会原样复现它（详见上方注释）。
                //    不启用线性滚转时 up 保持全站约定的 (0,0,1) —— 此时我们的姿态本来就是 lookAt 的那一套。
                orthoCamera.up.copy(linearRoll ? pose.camY : up);
                orthoCamera.updateMatrixWorld();
                /* ★ 到位后**再稳 8 帧**（约 130ms）才收工（10-04 九次修，十次修由 3 帧加到 8 帧）：
                   用户反馈「好像时间到了还没到目标视角，最后硬拉回来」——
                   数值模拟里最后几帧是平滑的（末帧位移只有峰值 7%），所以问题出在**结束那一瞬之后**：
                    resolve() 之后页面的 `controls.update()` / 其它逻辑可能在同一帧把相机挪一下。
                   ⇒ 到位后再多跑若干帧并每帧写回终点姿态，把任何外部干扰按回去，肉眼就看不到最后那一下。 */
                if (elapsed < delay + duration) requestAnimationFrame(frame);
                else if (settleFrames < 8) { settleFrames++; requestAnimationFrame(frame); }
                else {
                    /* ★ 收工：先把 up 还原成全站约定的 (0,0,1)。
                       终点姿态 p1 本来就是 lookAt(endPos, target, up) 的标准姿态（roll1 就是它自己的滚转），
                       ⇒ 还原 up 之后 lookAt 算出来的结果**逐位相同**，画面不会有最后一跳；
                       之后用户拖拽的行为也和以前完全一致。 */
                    orthoCamera.up.copy(up);
                    orthoCamera.position.copy(target).addScaledVector(d1, dist);
                    orthoCamera.quaternion.copy(q1);
                    orthoCamera.updateMatrixWorld();
                    if (hadDamping) controls.enableDamping = true;
                    controls.update();
                    resolve();
                }
            }
            requestAnimationFrame(frame);
        });
    }
};

// ==========================================
// 教学面板内容切换淡入（全站同步）：
// 监听 #teach-content 的内容变化，自动触发一次淡入。
// 配合 ui-glass.css 中 #teach-content.content-swap 样式使用。
// ==========================================
(function () {
    const target = document.getElementById('teach-content');
    if (!target || target.__contentFadeBound) return;
    target.__contentFadeBound = true;
    const observer = new MutationObserver(() => {
        target.classList.add('content-swap');
        void target.offsetWidth;
        target.classList.remove('content-swap');
    });
    observer.observe(target, { childList: true, subtree: true, characterData: true });
})();

window.GlassUI = GlassUI;
})();
