/*
 * Crystal Frost Atoms
 * ---------------------------------------------------------------
 * Optional, page-local frosted atom renderer for crystal-cell pages.
 *
 * This file deliberately does not patch Engine.js, ui-glass.js or
 * three.min.js. Pages opt in by loading this script. Existing opaque
 * spherical atom meshes are wrapped with the same silk-frost material
 * used by caf2.html, while transparent ghost atoms and analysis shapes
 * keep their original appearance.
 */
(function () {
    'use strict';

    if (window.CrystalFrostAtoms) return;

    // 分子晶体（干冰 CO₂ / 碘 I₂ / 冰 / 乙酸晶体）和石墨不提供磨砂玻璃模式，
    // 这些页面已经不再引用本脚本；名单是给线上还没更新的旧 html 兜底的，
    // 命中就直接退出：不建按钮、不换任何材质，页面保持原来的样子。
    // 2026-11-05 加入「晶胞实验室 wannengjingbao」「2026山东高考 2026shandong」：
    // 这两页不要实体金属键，也不要玻璃磨砂质感，保持页面自己的哑光球 + 普通圆柱键。
    var DISABLED_PAGES = ['graphite', 'co2', 'i2', 'ice', 'yisuan-jingti', 'wannengjingbao', '2026shandong'];
    function pageDisabled() {
        if (window.CRYSTAL_FROST_DISABLE) return true;
        try {
            var file = (window.location.pathname.split('/').pop() || '').replace(/\.html?$/i, '').toLowerCase();
            return DISABLED_PAGES.indexOf(file) !== -1;
        } catch (error) {
            return false;
        }
    }
    /* 上面这些页面里，有一部分仍然会调 CrystalFrostAtoms.attach()（晶胞实验室、2026 山东）。
       直接 return 会留下一个 undefined，页面那句 attach 抛 TypeError，把整个脚本块打断。
       所以这里先装一个空壳 API：调用全部返回 null，不建按钮、不动任何材质。 */
    function installNoopApi() {
        if (window.CrystalFrostAtoms) return;
        var noop = function () { return null; };
        window.CrystalFrostAtoms = {
            attach: noop,
            setEnabled: noop,
            refresh: noop,
            reflowBonds: noop,
            isEnabled: function () { return false; },
            materialOf: function () { return null; },
            bondMaterialOf: function () { return null; },
            applyBondsNow: noop,
            syncClipping: noop,
            pauseScan: noop,
            baseOf: function () { return null; }
        };
    }
    if (pageDisabled()) { installNoopApi(); return; }

    var state = {
        enabled: false,
        attached: false,
        scene: null,
        renderer: null,
        THREE: null,
        entries: new WeakMap(),
        entrySet: new Set(),   /* WeakMap 不能遍历，这里再挂一份可遍历的引用，供 syncClipping 用 */
        atomRadii: new WeakMap(),
        frostCache: new Map(),
        bondCache: new Map(),
        sourceLights: [],
        studioLights: [],
        scanTimer: 0,
        scanPaused: false,   /* 转换动画期间由页面暂停：动画里临时键的 opacity 由页面每帧自己写，扫描那一下会重置 */
        normalMap: null,
        envMap: null,
        nativeTransmission: false,
        rendererToneMapping: null,
        rendererExposure: null,
        sceneEnvironment: null,
        sceneEnvironmentIntensity: null,
        glowTexture: null,
        boundaryLines: new WeakSet(),
        boundaries: [],
        fuseEntries: new Set(),   /* 挂过接头辉光（fuse sprite）的 entry 都记在这里，供 syncClipping 复查 */
        gainedLights: new WeakSet(),
        legacyGain: 1,
        button: null
    };

    /*
     * 经典模式的亮度补偿 —— 已废弃（2026-10-20 晚）
     * ---------------------------------------------------------------
     * 这里原来是把场景灯光强度整体乘 π。实测：只补亮度，补不回立体感，
     * 而且页面中途新建的灯光还要反复补扫。
     * 现在改为 caf2 的原方案 installClassicPhongPatch()：直接改写
     * MeshPhongMaterial / MeshLambertMaterial 的输出式（uClassicLightScale 3.0
     * + uClassicSpecScale 35.5），一次到位、可随模式切换。下面两个函数保留给
     * 旧调用点兜底，不要再用。
     */
    var LEGACY_LIGHT_GAIN = Math.PI;

    function needsLegacyGain(THREE) {
        var revision = parseInt(String(THREE && THREE.REVISION || '0'), 10);
        if (revision < 155) return false;
        return !!document.querySelector('script[src*="three170-bundle"]');
    }

    function applyLegacyLightGain() {
        return 0;
    }

    var ICON = '<svg class="tb-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M8 9.5a4.5 4.5 0 0 1 6.5-1"/></svg>';

    function setTextureColorSpace(texture, THREE) {
        if (!texture) return;
        if (THREE.SRGBColorSpace && 'colorSpace' in texture) {
            texture.colorSpace = THREE.SRGBColorSpace;
        } else if (THREE.sRGBEncoding !== undefined) {
            texture.encoding = THREE.sRGBEncoding;
        }
    }

    function makeSilkNormalMap(THREE, renderer) {
        var size = 256;
        var canvas = document.createElement('canvas');
        canvas.width = canvas.height = size;
        var ctx = canvas.getContext('2d');
        var hMap = new Float32Array(size * size);
        for (var i = 0; i < hMap.length; i++) hMap[i] = Math.random();

        var smooth = new Float32Array(size * size);
        for (var pass = 0; pass < 2; pass++) {
            var src = pass === 0 ? hMap : smooth;
            var dst = pass === 0 ? smooth : hMap;
            for (var y = 0; y < size; y++) {
                for (var x = 0; x < size; x++) {
                    var sum = 0;
                    for (var dy = -1; dy <= 1; dy++) {
                        for (var dx = -1; dx <= 1; dx++) {
                            var nx = (x + dx + size) % size;
                            var ny = (y + dy + size) % size;
                            sum += src[ny * size + nx];
                        }
                    }
                    dst[y * size + x] = sum / 9;
                }
            }
        }

        var image = ctx.createImageData(size, size);
        for (var py = 0; py < size; py++) {
            for (var px = 0; px < size; px++) {
                var xl = hMap[py * size + ((px - 1 + size) % size)];
                var xr = hMap[py * size + ((px + 1) % size)];
                var yu = hMap[((py - 1 + size) % size) * size + px];
                var yd = hMap[((py + 1) % size) * size + px];
                var vx = (xl - xr) * 2.2;
                var vy = (yu - yd) * 2.2;
                var vz = 1;
                var length = Math.sqrt(vx * vx + vy * vy + vz * vz);
                var index = (py * size + px) * 4;
                image.data[index] = Math.floor((vx / length * 0.5 + 0.5) * 255);
                image.data[index + 1] = Math.floor((vy / length * 0.5 + 0.5) * 255);
                image.data[index + 2] = Math.floor((vz / length * 0.5 + 0.5) * 255);
                image.data[index + 3] = 255;
            }
        }
        ctx.putImageData(image, 0, 0);

        var texture = new THREE.CanvasTexture(canvas);
        texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
        texture.repeat.set(2.5, 2.5);
        if (renderer && renderer.capabilities) {
            texture.anisotropy = Math.min(4, renderer.capabilities.getMaxAnisotropy());
        }
        return texture;
    }

    function makeStudioEnvironment(THREE, renderer) {
        var canvas = document.createElement('canvas');
        canvas.width = 1024;
        canvas.height = 512;
        var ctx = canvas.getContext('2d');
        ctx.fillStyle = '#0c121e';
        ctx.fillRect(0, 0, 1024, 512);

        var background = ctx.createLinearGradient(0, 0, 0, 512);
        background.addColorStop(0, '#24344d');
        background.addColorStop(0.45, '#0d1422');
        background.addColorStop(0.55, '#090e18');
        background.addColorStop(1, '#1e2c42');
        ctx.fillStyle = background;
        ctx.fillRect(0, 0, 1024, 512);

        function softLight(x, y, w, h, color, blur) {
            ctx.save();
            ctx.filter = 'blur(' + blur + 'px)';
            ctx.fillStyle = color;
            ctx.fillRect(x, y, w, h);
            ctx.restore();
        }
        softLight(110, 36, 280, 130, 'rgba(255, 253, 248, 0.98)', 22);
        softLight(640, 75, 190, 250, 'rgba(185, 225, 255, 0.68)', 26);
        softLight(200, 370, 260, 65, 'rgba(220, 240, 255, 0.48)', 24);

        var source = new THREE.CanvasTexture(canvas);
        source.mapping = THREE.EquirectangularReflectionMapping;
        setTextureColorSpace(source, THREE);

        if (!THREE.PMREMGenerator || !renderer) {
            return source;
        }
        try {
            var pmrem = new THREE.PMREMGenerator(renderer);
            var env = pmrem.fromEquirectangular(source).texture;
            pmrem.dispose();
            source.dispose();
            return env;
        } catch (error) {
            return source;
        }
    }

    function makeSoftGlowTexture(THREE) {
        var canvas = document.createElement('canvas');
        canvas.width = canvas.height = 128;
        var context = canvas.getContext('2d');
        var gradient = context.createRadialGradient(64, 64, 2, 64, 64, 62);
        gradient.addColorStop(0, 'rgba(255,255,255,0.95)');
        gradient.addColorStop(0.28, 'rgba(255,255,255,0.65)');
        gradient.addColorStop(0.62, 'rgba(255,255,255,0.18)');
        gradient.addColorStop(1, 'rgba(255,255,255,0)');
        context.fillStyle = gradient;
        context.fillRect(0, 0, 128, 128);
        return new THREE.CanvasTexture(canvas);
    }

    function attachFrostShader(material, uniforms) {
        material.onBeforeCompile = function (shader) {
            shader.uniforms.uBaseColor = uniforms.uBaseColor;
            shader.uniforms.uAttenColor = uniforms.uAttenColor;
            shader.vertexShader = 'varying vec3 vFrostGeoN;\nvarying vec3 vFrostViewPos;\nvarying vec3 vFrostWorldPos;\n' + shader.vertexShader.replace(
                '#include <begin_vertex>',
                '#include <begin_vertex>\n' +
                'vFrostGeoN = normalize(normalMatrix * objectNormal);\n' +
                'vFrostViewPos = -(modelViewMatrix * vec4(position, 1.0)).xyz;\n' +
                'vFrostWorldPos = (modelMatrix * vec4(position, 1.0)).xyz;'
            );

            var helper = [
                'varying vec3 vFrostGeoN;',
                'varying vec3 vFrostViewPos;',
                'varying vec3 vFrostWorldPos;',
                'uniform vec3 uBaseColor;',
                'uniform vec3 uAttenColor;',
                'vec3 frostSrgbToLinear(vec3 c) { return pow(max(c, vec3(0.0)), vec3(2.2)); }',
                'vec3 frostLinearToSrgb(vec3 c) { return pow(clamp(c, 0.0, 1.0), vec3(1.0 / 2.2)); }',
                'vec3 frostAcesFilmic(vec3 x) {',
                '  x *= 0.76;',
                '  vec3 a = x * (x + 0.0245786) - 0.000090537;',
                '  vec3 b = x * (0.983729 * x + 0.4329510) + 0.238081;',
                '  return clamp(a / b, 0.0, 1.0);',
                '}',
                'vec3 frostSampleStudioEnv(vec3 d, float rough) {',
                '  float y = clamp(d.y, -1.0, 1.0);',
                '  vec3 topCol = vec3(0.017, 0.034, 0.076);',
                '  vec3 midCol = vec3(0.003, 0.006, 0.014);',
                '  vec3 botCol = vec3(0.013, 0.025, 0.054);',
                '  vec3 bg = y >= 0.0 ? mix(midCol, topCol, pow(y, 0.8)) : mix(midCol, botCol, pow(-y, 0.8));',
                '  vec3 sb1Dir = normalize(vec3(-0.48, 0.62, 0.62));',
                '  vec3 sb2Dir = normalize(vec3(0.78, 0.18, 0.60));',
                '  vec3 sb3Dir = normalize(vec3(-0.15, -0.78, 0.60));',
                '  float exp1 = rough > 0.2 ? 5.5 : 12.0;',
                '  vec3 sb1 = pow(max(0.0, dot(d, sb1Dir)), exp1) * vec3(1.0, 0.985, 0.94) * 1.45;',
                '  vec3 sb2 = pow(max(0.0, dot(d, sb2Dir)), 4.5) * vec3(0.48, 0.75, 1.0) * 0.70;',
                '  vec3 sb3 = pow(max(0.0, dot(d, sb3Dir)), 4.5) * vec3(0.71, 0.87, 1.0) * 0.50;',
                '  return bg + sb1 + sb2 + sb3;',
                '}',
                'vec3 frostGgxSpec(vec3 N, vec3 V, vec3 L, vec3 lightCol, float intensity, float rough, float F) {',
                '  vec3 H = normalize(L + V);',
                '  float NdH = max(0.0, dot(N, H));',
                '  float NdL = max(0.0, dot(N, L));',
                '  float a = rough * rough;',
                '  float a2 = a * a;',
                '  float denom = NdH * NdH * (a2 - 1.0) + 1.0;',
                '  float D = a2 / (3.14159265 * denom * denom + 1e-5);',
                '  return D * F * NdL * 0.22 * lightCol * intensity;',
                '}'
            ].join('\n');

            var fragment = [
                'vec3 geoN = normalize(vFrostGeoN);',
                'vec3 N = normalize(normal);',
                'vec3 V = normalize(vFrostViewPos);',
                'float NdV = clamp(dot(N, V), 0.001, 1.0);',
                'float NdV_geo = clamp(dot(geoN, V), 0.001, 1.0);',
                'float rScreen = sqrt(clamp(1.0 - NdV * NdV, 0.0, 1.0));',
                'vec3 colLin = frostSrgbToLinear(uBaseColor);',
                'vec3 attLin = frostSrgbToLinear(uAttenColor);',
                'vec3 whiteLin = vec3(1.0);',
                'vec3 matCol = mix(colLin, whiteLin, 0.28);',
                'vec3 sheenCol = mix(colLin, whiteLin, 0.65);',
                'vec3 coreCol = mix(colLin, whiteLin, 0.28);',
                'vec3 emissiveLin = colLin * (0.62 * 0.24);',
                'float eta = 1.0 / 1.50;',
                'float kRefr = max(0.0, 1.0 - eta * eta * (1.0 - NdV * NdV));',
                'vec3 refractVec = normalize(-eta * V + (eta * NdV - sqrt(kRefr)) * N);',
                'vec3 transEnv = frostSampleStudioEnv(refractVec, 0.26) * 1.52;',
                'float rayLen = 0.56 * (0.72 + 0.48 * (1.0 - NdV_geo));',
                'vec3 attenCoeff = -log(max(attLin, vec3(1e-4))) / 1.28;',
                'vec3 transmittance = exp(-attenCoeff * rayLen);',
                'float F_fres = 0.04 + 0.96 * pow(1.0 - NdV, 5.0);',
                'vec3 transmittedLight = transEnv * transmittance * (1.0 - F_fres);',
                'float uCore = clamp(rScreen / 0.85, 0.0, 1.0);',
                'float coreFalloff = exp(-2.3 * uCore * uCore) * pow(1.0 - uCore * uCore, 1.15);',
                'vec3 subsurfaceCore = mix(attLin, colLin, 0.70) * (coreFalloff * 0.52) + coreCol * (pow(coreFalloff, 2.2) * 0.28);',
                'vec3 L_key = normalize(vec3(-7.0, 9.0, 9.0));',
                'vec3 L_back = normalize(vec3(6.0, 4.0, -9.0));',
                'vec3 L_bot = normalize(vec3(0.0, -9.0, 4.0));',
                'vec3 diffKey = max(0.0, dot(N, L_key)) * vec3(1.0, 0.98, 0.91) * (2.2 / 3.14159265);',
                'vec3 diffBack = max(0.0, dot(N, L_back)) * vec3(0.38, 0.90, 0.97) * (1.1 / 3.14159265);',
                'vec3 diffBot = max(0.0, dot(N, L_bot)) * vec3(1.0, 0.78, 0.46) * (0.75 / 3.14159265);',
                'float hemiW = 0.5 * N.y + 0.5;',
                'vec3 diffHemi = mix(vec3(0.013, 0.022, 0.044), vec3(0.87, 0.92, 1.0), hemiW) * (0.65 / 3.14159265);',
                'vec3 totalDiff = matCol * 0.14 * (diffKey + diffBack + diffBot + diffHemi);',
                'vec3 reflVec = reflect(-V, N);',
                'vec3 iblSpec = frostSampleStudioEnv(reflVec, 0.26) * 1.35 * F_fres;',
                'vec3 iblCoat = frostSampleStudioEnv(reflVec, 0.17) * 1.35 * 0.38 * F_fres;',
                'vec3 dirSpec = frostGgxSpec(N, V, L_key, vec3(1.0, 0.98, 0.91), 1.35, 0.36, F_fres) +',
                '  frostGgxSpec(N, V, L_bot, vec3(1.0, 0.78, 0.46), 0.55, 0.38, F_fres) +',
                '  0.28 * frostGgxSpec(N, V, L_key, vec3(1.0, 0.98, 0.91), 1.15, 0.24, F_fres);',
                'float keyHighlight = pow(max(0.0, dot(N, L_key)), 42.0) * 0.42;',
                'float backHighlight = pow(max(0.0, dot(N, L_back)), 52.0) * 0.14;',
                'vec3 directionalHighlights = vec3(1.0, 0.985, 0.95) * keyHighlight + vec3(0.58, 0.90, 1.0) * backHighlight;',
                'vec3 sheenRim = pow(1.0 - NdV, 2.5) * sheenCol * (0.72 * 0.55);',
                'vec3 frostTotalLin = totalDiff + transmittedLight + subsurfaceCore + iblSpec + iblCoat + dirSpec + sheenRim + emissiveLin + directionalHighlights;',
                'gl_FragColor = vec4(frostLinearToSrgb(frostAcesFilmic(frostTotalLin)), opacity);'
            ].join('\n');

            var anchor = '#include <dithering_fragment>';
            if (shader.fragmentShader.indexOf(anchor) !== -1) {
                shader.fragmentShader = helper + '\n' + shader.fragmentShader.replace(anchor, fragment + '\n' + anchor);
            }
        };
    }

    /* ★★ 键 / 晶胞杆的「金属质感」= envMap 反射 + 边缘自发光 + 经典模式的三盏虚拟高光。
       最后那段是照抄 caf2.html 的 attachBondEdgeGlow（uClassicBondBoost = 1 时生效）——
       缺了它，只靠 envMap 在 r170 下会渲染成一片塑料灰，就是「和氟化钙的键完全不一样」的原因。
       四个 uniform 用**全局共享**的一个对象：模式切换时改一次值，所有键/杆的 shader 同时生效。 */
    var bondGlowUniforms = null;
    function getBondGlowUniforms() {
        if (bondGlowUniforms) return bondGlowUniforms;
        bondGlowUniforms = {
            uEdgeColor: { value: new state.THREE.Color(0xa9c8ef) },
            uEdgeStrength: { value: 0.3 },
            uEdgePower: { value: 2.6 },
            uClassicBondBoost: { value: 0 }
        };
        return bondGlowUniforms;
    }

    function setBondClassicBoost(on) {
        if (!state.THREE) return;
        getBondGlowUniforms().uClassicBondBoost.value = on ? 1 : 0;
    }

    function attachBondEdgeGlow(material) {
        var glow = getBondGlowUniforms();
        material.onBeforeCompile = function (shader) {
            shader.uniforms.uEdgeColor = glow.uEdgeColor;
            shader.uniforms.uEdgeStrength = glow.uEdgeStrength;
            shader.uniforms.uEdgePower = glow.uEdgePower;
            shader.uniforms.uClassicBondBoost = glow.uClassicBondBoost;
            shader.vertexShader = 'varying float vBondU;\nvarying vec3 vBondViewPos;\n' + shader.vertexShader.replace(
                '#include <begin_vertex>',
                '#include <begin_vertex>\nvBondU = uv.y;\nvBondViewPos = -(modelViewMatrix * vec4(position, 1.0)).xyz;'
            );
            var anchor = '#include <emissivemap_fragment>';
            if (shader.fragmentShader.indexOf(anchor) !== -1) {
                shader.fragmentShader =
                    'varying float vBondU;\nvarying vec3 vBondViewPos;\nuniform vec3 uEdgeColor;\nuniform float uEdgeStrength;\nuniform float uEdgePower;\nuniform float uClassicBondBoost;\n' +
                    shader.fragmentShader.replace(
                        anchor,
                        anchor + '\n' +
                        'float bondEdge = pow(abs(vBondU * 2.0 - 1.0), uEdgePower);\n' +
                        'totalEmissiveRadiance += uEdgeColor * uEdgeStrength * bondEdge;'
                    );
            } else {
                shader.fragmentShader = 'varying float vBondU;\nvarying vec3 vBondViewPos;\n' + shader.fragmentShader;
            }
            var lightEndAnchor = '#include <lights_fragment_end>';
            if (shader.fragmentShader.indexOf(lightEndAnchor) !== -1) {
                shader.fragmentShader = shader.fragmentShader.replace(
                    lightEndAnchor,
                    lightEndAnchor + `
    if (uClassicBondBoost > 0.5) {
        vec3 bN = normalize(normal);
        vec3 bV = normalize(vBondViewPos);
        vec3 bL1 = normalize((viewMatrix * vec4(normalize(vec3(-7.0, 9.0, 9.0)), 0.0)).xyz);
        vec3 bL2 = normalize((viewMatrix * vec4(normalize(vec3(6.0, 4.0, -9.0)), 0.0)).xyz);
        vec3 bL3 = normalize((viewMatrix * vec4(normalize(vec3(0.0, -9.0, 4.0)), 0.0)).xyz);
        vec3 bH1 = normalize(bL1 + bV);
        vec3 bH2 = normalize(bL2 + bV);
        vec3 bH3 = normalize(bL3 + bV);
        float sp1 = pow(max(0.0, dot(bN, bH1)), 38.0) * 0.82 + pow(max(0.0, dot(bN, bH1)), 12.0) * 0.24;
        float sp2 = pow(max(0.0, dot(bN, bH2)), 26.0) * 0.45;
        float sp3 = pow(max(0.0, dot(bN, bH3)), 22.0) * 0.28;
        float rimF = pow(1.0 - clamp(dot(bN, bV), 0.0, 1.0), 2.4);
        reflectedLight.directSpecular += vec3(1.0, 0.985, 0.94) * sp1 + vec3(0.55, 0.92, 1.0) * sp2 + vec3(1.0, 0.88, 0.65) * sp3 + vec3(0.78, 0.88, 1.0) * (rimF * 0.18);
        reflectedLight.directDiffuse += diffuseColor.rgb * (max(0.0, dot(bN, bL1)) * 0.22 + max(0.0, dot(bN, bL2)) * 0.12 + 0.08);
    }
`
                );
            }
        };
    }

    function materialColor(material, THREE) {
        var color = material.color ? material.color.clone() : new THREE.Color(0x8eb8e8);
        var hsl = {};
        color.getHSL(hsl);
        if (hsl.l > 0.9 && material.emissive) {
            var emissive = material.emissive.clone();
            var eh = {};
            emissive.getHSL(eh);
            if (eh.l > 0.04) color = emissive.lerp(new THREE.Color(0xffffff), 0.22);
        }
        return color;
    }

    function crystalGlassTint(color, THREE) {
        return color.clone();
    }

    /* ------------------------------------------------------------------
       按页微调钩子（opt-in，默认完全不生效）
       页面可在自己的脚本里写：
           window.CRYSTAL_FROST_TINT = function (base, THREE) {
               if (base === siMaterial) return { color: 0x74b4f0, attenuation: 0x1e4f80,
                                                 whiteMix: 0.10, sheenMix: 0.42 };
               return null;                       // 其余材质走默认（caf2）配方
           };
       只影响「磨砂玻璃」材质本身，经典实心模式一点不动。
       没设这个钩子的 28 个页面行为与之前逐字节相同。
       whiteMix 默认 0.28（掺白越多越容易发白），sheenMix 默认 0.65。
       ------------------------------------------------------------------ */
    function pageFrostTint(base, THREE, color, attenuation) {
        var hook = (typeof window !== 'undefined') ? window.CRYSTAL_FROST_TINT : null;
        if (typeof hook !== 'function') return null;
        var res;
        try { res = hook(base, THREE, color, attenuation); } catch (e) { return null; }
        if (!res) return null;
        function toColor(v, fallback) {
            if (v === undefined || v === null) return fallback;
            if (v && v.isColor) return v.clone();
            try { return new THREE.Color(v); } catch (e) { return fallback; }
        }
        return {
            color: toColor(res.color, color),
            attenuation: toColor(res.attenuation, attenuation),
            whiteMix: (typeof res.whiteMix === 'number') ? res.whiteMix : 0.28,
            sheenMix: (typeof res.sheenMix === 'number') ? res.sheenMix : 0.65,
            // 通透度也允许单页调：金属色（铜/金）按 caf2 的 0.88 会显得"虚"，
            // 页面可以把 transmission 压到 0.5 左右、thickness 抬一点，看着更实。
            transmission: (typeof res.transmission === 'number') ? res.transmission : 0.88,
            thickness: (typeof res.thickness === 'number') ? res.thickness : 0.96,
            attenuationDistance: (typeof res.attenuationDistance === 'number') ? res.attenuationDistance : 1.28
        };
    }

    function createFrostMaterial(base, THREE, renderer, normalMap, envMap) {
        var sourceColor = materialColor(base, THREE);
        var color = crystalGlassTint(sourceColor, THREE);
        var attenuation = sourceColor.clone();
        var hsl = {};
        sourceColor.getHSL(hsl);
        attenuation.setHSL(hsl.h, Math.min(1, hsl.s * 1.1), Math.max(0.1, hsl.l * 0.48));

        var tint = pageFrostTint(base, THREE, color, attenuation);
        if (tint) { color = tint.color; attenuation = tint.attenuation; }
        var whiteMix = tint ? tint.whiteMix : 0.28;
        var sheenMix = tint ? tint.sheenMix : 0.65;

        var common = {
            color: color.clone().lerp(new THREE.Color(0xffffff), whiteMix),
            metalness: 0,
            roughness: 0.26,
            normalMap: normalMap,
            normalScale: new THREE.Vector2(
                state.nativeTransmission ? 0.042 : 0.052,
                state.nativeTransmission ? 0.042 : 0.052
            ),
            clearcoat: 0.38,
            clearcoatRoughness: 0.17,
            side: base.side,
            transparent: false,
            opacity: 1,
            depthWrite: base.depthWrite,
            depthTest: base.depthTest,
            clippingPlanes: base.clippingPlanes,
            clipIntersection: base.clipIntersection,
            clipShadows: base.clipShadows,
            envMap: envMap,
            envMapIntensity: state.nativeTransmission ? 1.48 : 1.35
        };
        var material = new THREE.MeshPhysicalMaterial(common);
        material.name = 'CrystalFrostAtom';
        material.userData = {
            crystalFrostMaterial: true,
            crystalFrostBaseUuid: base.uuid
        };

        if (state.nativeTransmission) {
            // ★ 逐字段照抄 caf2.html createFrostedAtomMaterial() 的原生分支，不要自行"改良"。
            // 之前为了挡住"透出对面键"把 0.88/0.96/1.28 改成 0.58/1.35/0.95，
            // 结果原子发白、颜色变淡、通透感全丢；透键的真因是棱杆太细留下的几何缝，
            // 已在 createBoundaryRods() 里加粗解决，所以这里恢复 caf2 原值。
            var roughVal = 0.26;
            material.roughness = roughVal;
            material.transmission = tint ? tint.transmission : 0.88;
            material.thickness = tint ? tint.thickness : 0.96;
            material.ior = 1.5;
            material.attenuationColor.copy(attenuation);
            material.attenuationDistance = tint ? tint.attenuationDistance : 1.28;
            material.clearcoat = 0.42;
            material.clearcoatRoughness = Math.max(0.06, roughVal * 0.65);
            material.sheen = 0.75;
            material.sheenColor.copy(color).lerp(new THREE.Color(0xffffff), sheenMix);
            material.sheenRoughness = 0.3;
            material.emissive.copy(color);
            material.emissiveIntensity = 0.62 * 0.24;
        } else {
            attachFrostShader(material, {
                uBaseColor: { value: new THREE.Vector3(color.r, color.g, color.b) },
                uAttenColor: { value: new THREE.Vector3(attenuation.r, attenuation.g, attenuation.b) }
            });
        }
        material.needsUpdate = true;
        return material;
    }

    function createBondMaterial(base, THREE, normalMap, envMap) {
        var material = new THREE.MeshPhysicalMaterial({
            color: 0xdce4ee,
            metalness: 0.85,
            roughness: 0.22,
            normalMap: normalMap,
            normalScale: new THREE.Vector2(0.02, 0.02),
            transmission: 0,
            clearcoat: 0.48,
            clearcoatRoughness: 0.12,
            envMap: envMap,
            envMapIntensity: 1.48,
            side: base.side,
            transparent: false,
            opacity: 1,
            depthWrite: true,
            depthTest: base.depthTest,
            clippingPlanes: base.clippingPlanes,
            clipIntersection: base.clipIntersection,
            clipShadows: base.clipShadows
        });
        material.name = 'CrystalFrostBond';
        material.userData = {
            crystalFrostMaterial: true,
            crystalFrostBondMaterial: true,
            crystalFrostBaseUuid: base.uuid
        };

        /* 键材质默认写死 0xdce4ee（近白、金属度 .85）。页面可用
           window.CRYSTAL_FROST_BOND_TINT 单独调色，不设则与原来完全一致。 */
        var bondTint = null;
        if (typeof window !== 'undefined' && typeof window.CRYSTAL_FROST_BOND_TINT === 'function') {
            try { bondTint = window.CRYSTAL_FROST_BOND_TINT(base, THREE); } catch (e) { bondTint = null; }
        }
        if (bondTint) {
            if (bondTint.color !== undefined && bondTint.color !== null) {
                try { material.color = (bondTint.color && bondTint.color.isColor) ? bondTint.color.clone() : new THREE.Color(bondTint.color); } catch (e) {}
            }
            if (typeof bondTint.metalness === 'number') material.metalness = bondTint.metalness;
            if (typeof bondTint.roughness === 'number') material.roughness = bondTint.roughness;
            if (typeof bondTint.envMapIntensity === 'number') material.envMapIntensity = bondTint.envMapIntensity;
        }
        attachBondEdgeGlow(material);
        material.needsUpdate = true;
        return material;
    }

    function getFrostMaterial(base) {
        var cached = state.frostCache.get(base.uuid);
        if (cached) return cached;
        var material = createFrostMaterial(base, state.THREE, state.renderer, state.normalMap, state.envMap);
        state.frostCache.set(base.uuid, material);
        return material;
    }

    function getBondMaterial(base) {
        var cached = state.bondCache.get(base.uuid);
        if (cached) return cached;
        var material = createBondMaterial(base, state.THREE, state.normalMap, state.envMap);
        state.bondCache.set(base.uuid, material);
        return material;
    }

    function bondRadiusScale(x, length, embed, fillet, peak) {
        var distanceFromEnd = Math.min(x, length - x);
        if (distanceFromEnd >= fillet) return 1;
        if (distanceFromEnd <= embed) {
            var embedded = embed > 1e-5 ? distanceFromEnd / embed : 0;
            return peak * (0.88 + 0.12 * embedded);
        }
        var blend = (distanceFromEnd - embed) / Math.max(1e-5, fillet - embed);
        return 1 + (peak - 1) * Math.pow(1 - blend, 2.2);
    }

    function buildFluidBondGeometry(length, rodRadius, embed, fillet, peak) {
        var heightSegments = Math.max(48, Math.min(140, Math.round(length * 90)));
        var geometry = new state.THREE.CylinderGeometry(
            rodRadius, rodRadius, length, 28, heightSegments, false
        );
        var position = geometry.attributes.position;
        var half = length / 2;
        for (var i = 0; i < position.count; i++) {
            var scale = bondRadiusScale(position.getY(i) + half, length, embed, fillet, peak);
            position.setX(i, position.getX(i) * scale);
            position.setZ(i, position.getZ(i) * scale);
        }
        position.needsUpdate = true;
        geometry.computeVertexNormals();
        return geometry;
    }

    function worldSphereRadius(mesh) {
        if (!mesh.geometry) return 0;
        if (!mesh.geometry.boundingSphere) mesh.geometry.computeBoundingSphere();
        var radius = mesh.geometry.boundingSphere ? mesh.geometry.boundingSphere.radius : 0;
        var scale = mesh.getWorldScale(new state.THREE.Vector3());
        return radius * Math.max(Math.abs(scale.x), Math.abs(scale.y), Math.abs(scale.z));
    }

    function nearestAtomToPoint(point, atomMeshes) {
        var best = null;
        var bestDistance = Infinity;
        for (var i = 0; i < atomMeshes.length; i++) {
            var atom = atomMeshes[i];
            var center = atom.getWorldPosition(new state.THREE.Vector3());
            var distance = center.distanceTo(point);
            var radius = worldSphereRadius(atom);
            if (distance <= radius * 1.35 + 0.02 && distance < bestDistance) {
                best = { center: center, radius: radius, mesh: atom };
                bestDistance = distance;
            }
        }
        return best;
    }

    function pickRememberedAtom(remembered, point, atomMeshes) {
        if (remembered && remembered.mesh && remembered.mesh.parent) {
            return {
                center: remembered.mesh.getWorldPosition(new state.THREE.Vector3()),
                radius: worldSphereRadius(remembered.mesh),
                mesh: remembered.mesh
            };
        }
        return atomMeshes ? nearestAtomToPoint(point, atomMeshes) : null;
    }

    function fluidizeBond(mesh, atomMeshes, entry, isCage, overrideWorldRadius) {
        if (!mesh.geometry || !mesh.geometry.parameters) return null;
        var height = Number(mesh.geometry.parameters.height);
        var radiusTop = Number(mesh.geometry.parameters.radiusTop);
        var radiusBottom = Number(mesh.geometry.parameters.radiusBottom);
        if (!(height > 0)) return null;

        var rodRadius = Math.max(0.001, (radiusTop + radiusBottom) * 0.5);
        mesh.updateWorldMatrix(true, false);
        var p1 = mesh.localToWorld(new state.THREE.Vector3(0, height / 2, 0));
        var p2 = mesh.localToWorld(new state.THREE.Vector3(0, -height / 2, 0));
        var fullLength = p1.distanceTo(p2);
        if (fullLength < 1e-4) return null;

        var direction = p2.clone().sub(p1).normalize();
        var alongScale = fullLength / height;
        var worldScale = mesh.getWorldScale(new state.THREE.Vector3());
        var radialScale = (Math.abs(worldScale.x) + Math.abs(worldScale.z)) * 0.5;
        // 有些页面的"晶胞棱"也是细圆柱（nacl 只有 0.015），这里允许把世界半径
        // 直接指定成 caf2 的「键 × 0.55」，几何重建时按局部单位换算。
        if (overrideWorldRadius > 0 && radialScale > 1e-6) {
            rodRadius = overrideWorldRadius / radialScale;
        }
        var worldRodRadius = Math.max(0.0005, rodRadius * radialScale);
        var previous = entry && entry.shape ? entry.shape : null;
        var atom1 = pickRememberedAtom(previous ? previous.atom1 : null, p1, atomMeshes);
        var atom2 = pickRememberedAtom(previous ? previous.atom2 : null, p2, atomMeshes);
        var cageFactor = isCage ? 0.72 : 1;
        var embedWorld = 0.012 * cageFactor;
        var filletWorld = 0.16 * cageFactor;

        function surfacePoint(point, atom, sign) {
            if (!atom) return point.clone();
            var surface = Math.sqrt(Math.max(0.0001, atom.radius * atom.radius - worldRodRadius * worldRodRadius));
            return atom.center.clone().addScaledVector(direction, sign * (surface - embedWorld));
        }

        var start = surfacePoint(p1, atom1, 1);
        var end = surfacePoint(p2, atom2, -1);
        var fluidWorldLength = Math.max(0.025, start.distanceTo(end));
        var localLength = Math.max(0.02, fluidWorldLength / alongScale);
        var localEmbed = Math.max(0.002, embedWorld / alongScale);
        var localFillet = Math.min(localLength * 0.42, Math.max(localEmbed, filletWorld / alongScale));
        var peak = isCage ? 1.15 : 1.35;
        var geometry = buildFluidBondGeometry(localLength, rodRadius, localEmbed, localFillet, peak);

        var middleWorld = start.clone().add(end).multiplyScalar(0.5);
        var middleLocal = mesh.parent ? mesh.parent.worldToLocal(middleWorld.clone()) : middleWorld;
        entry.originalGeometry = mesh.geometry;
        entry.originalPosition = mesh.position.clone();
        entry.originalQuaternion = mesh.quaternion.clone();
        // 记住"这根杆的世界半径被强制成多少"：原子大小滑杆重算时要沿用，
        // 否则晶胞棱会掉回页面原来的 0.015，白补粗一次。
        entry.overrideWorldRadius = overrideWorldRadius > 0 ? overrideWorldRadius : 0;
        entry.fluidGeometry = geometry;
        mesh.geometry = geometry;
        mesh.position.copy(middleLocal);
        mesh.userData.crystalFluidBondShape = true;
        return {
            atom1: atom1,
            atom2: atom2,
            start: start,
            end: end,
            worldRodRadius: worldRodRadius,
            isCage: isCage
        };
    }

    function removeFuseSprites(entry) {
        if (!entry || !entry.fuseSprites) return;
        state.fuseEntries.delete(entry);
        entry.fuseSprites.forEach(function (sprite) {
            if (sprite.parent) sprite.parent.remove(sprite);
            if (sprite.material) sprite.material.dispose();
        });
        entry.fuseSprites = [];
    }

    function addFuseSprites(mesh, entry, shape, isCage) {
        if (!shape || !mesh.parent || !state.glowTexture) return;
        removeFuseSprites(entry);
        var sprites = [];
        var endpoints = [
            { point: shape.start, atom: shape.atom1 },
            { point: shape.end, atom: shape.atom2 }
        ];
        endpoints.forEach(function (endpoint) {
            var color = endpoint.atom ?
                materialColor(endpoint.atom.mesh.material, state.THREE) :
                new state.THREE.Color(0xbcd7ff);
            var spriteMaterial = new state.THREE.SpriteMaterial({
                map: state.glowTexture,
                color: color.clone().lerp(new state.THREE.Color(0xffffff), 0.45),
                opacity: isCage ? 0.089936 : 0.11242,
                transparent: true,
                depthWrite: false,
                depthTest: true,
                blending: state.THREE.AdditiveBlending
            });
            var sprite = new state.THREE.Sprite(spriteMaterial);
            var size = shape.worldRodRadius * (isCage ? 3.78 : 5.46);
            sprite.scale.setScalar(size);
            /* ★ 辉光挂在「这根键/这个原子自己的 mesh」下面，不再挂它的父组。
               组装动画是直接改单个 mesh 的 visible / scale 的（先整批隐藏只留晶胞轮廓、
               再让离子一个个长大），挂父组的话辉光不跟着走 ⇒ 原子没了、辉光还留在
               原位，画面上就是「一行行一列列的白斑点拼成一个正方体」。
               挂到 mesh 上以后：mesh 隐藏、缩放、重建，辉光自动同步。 */
            mesh.updateWorldMatrix(true, false);
            sprite.position.copy(mesh.worldToLocal(endpoint.point.clone()));
            sprite.renderOrder = 80;
            sprite.raycast = function () {};
            /* 记下「挂在谁下面 + 局部坐标」：均摊法裁剪时可能把辉光临时摘下来，
               摘下来之后还能靠这两个值算回它的世界坐标。 */
            sprite.userData.fuseParent = mesh;
            sprite.userData.fuseLocal = sprite.position.clone();
            sprite.userData.fuseMesh = mesh;
            /* 记下它「本来应该在哪」（世界坐标），诊断口拿它核对坐标有没有算偏 */
            sprite.userData.fuseWorld = endpoint.point.clone();
            mesh.add(sprite);
            sprites.push(sprite);
        });
        entry.fuseSprites = sprites;
        state.fuseEntries.add(entry);
        syncFuseClippingEntry(entry);
    }

    /* 均摊法（实心切片）用的 stencil 裁剪面只管网格，不管 Sprite ——
       接头辉光小球会原样留在切面上，看起来就是「截面上一堆小白点」。
       这里按裁剪面把落在切面外（含正好压在切面上）的辉光摘掉，关掉切片再装回去。 */
    function syncFuseClippingEntry(entry) {
        if (!entry || !entry.fuseSprites || !entry.fuseSprites.length) return 0;
        var planes = (entry.frost && entry.frost.clippingPlanes) ||
            (entry.base && entry.base.clippingPlanes) || null;
        var changed = 0;
        entry.fuseSprites.forEach(function (sprite) {
            var parent = sprite.userData.fuseParent;
            if (!parent) return;
            var hide = false;
            if (planes && planes.length) {
                var world = parent.localToWorld(sprite.userData.fuseLocal.clone());
                var margin = sprite.scale.x * 0.5;
                for (var i = 0; i < planes.length; i++) {
                    if (!planes[i]) continue;
                    if (planes[i].distanceToPoint(world) < margin) { hide = true; break; }
                }
            }
            if (hide && sprite.parent) { parent.remove(sprite); changed++; }
            else if (!hide && !sprite.parent) { parent.add(sprite); changed++; }
        });
        return changed;
    }

    /* 只做「有没有变」的廉价判断：几万个指针比较，不碰几何、不建对象。
       命中一条就够 —— 页面是整批材质一起改可见面的。 */
    function clippingDiffers() {
        var differs = false;
        state.entrySet.forEach(function (entry) {
            if (differs || !entry || !entry.base || !entry.frost) return;
            if (entry.frost.clippingPlanes !== entry.base.clippingPlanes) differs = true;
        });
        return differs;
    }

    /* ★ 交互后补一轮对齐（都在下一帧 / 少量延时里跑，不在每帧跑）：
       ① 均摊法开关改的是页面自己那几个材质的 clippingPlanes，我们手里的金属 /
          磨砂材质是另建的 —— 不对齐的话「金属键」要等 650ms 那轮扫描才被切掉/换上；
       ② 换晶胞、切规模、切显示模式会新建键和晶胞棱，也一样要等那 650ms，
          画面上就是「先出现一根素的、过半秒才镀上金属」，反之亦然。
       所以任何一次点击 / 滑杆之后，主动补扫一次；再在 140ms / 380ms 各补一次，
       接住那些在 rAF、过渡动画、setTimeout 里才建好的键。 */
    var refreshQueued = false;
    function refreshNow() {
        if (!state.attached || !state.scene) return;
        if (state.scanPaused) return;
        pruneOrphanBoundaries();
        if (clippingDiffers()) syncClipping();
        if (state.enabled) scanAndApply(); else applyClassicMetalBonds();
        syncBoundaryVisibility();
    }
    function queueRefresh() {
        if (refreshQueued) return;
        refreshQueued = true;
        requestAnimationFrame(function () {
            refreshQueued = false;
            refreshNow();
        });
        setTimeout(refreshNow, 140);
        setTimeout(refreshNow, 380);
    }

    /* 页面开/关均摊法时会改 material.clippingPlanes，但磨砂脚本持有的材质与
       辉光是另建的，不会自动跟着变；这里做一次全量对齐（材质 + 辉光）。 */
    function syncClipping() {
        if (!state.THREE) return 0;
        var changed = 0;
        /* ★ entries 是 WeakMap（不可遍历），改用 entrySet。
           并且逐条 try/catch：这里被页面的 updateClipping 每帧调，抛一次就会把
           转换动画整段打断（画面卡住、按钮像失灵），绝不能连坐。 */
        state.entrySet.forEach(function (entry) {
            if (!entry) return;
            try {
                if (entry.base && entry.frost) {
                    if (entry.frost.clippingPlanes !== entry.base.clippingPlanes) {
                        var had = !!(entry.frost.clippingPlanes && entry.frost.clippingPlanes.length);
                        var has = !!(entry.base.clippingPlanes && entry.base.clippingPlanes.length);
                        entry.frost.clippingPlanes = entry.base.clippingPlanes;
                        entry.frost.clipIntersection = entry.base.clipIntersection;
                        entry.frost.clipShadows = entry.base.clipShadows;
                        /* 只有「有裁剪面 ⇄ 没裁剪面」的切换需要重编着色器，
                           平常那次扫描别动 needsUpdate，免得每次都重编译。 */
                        if (had !== has) entry.frost.needsUpdate = true;
                        changed++;
                    }
                }
            } catch (e) { /* 单条坏掉不影响其它 */ }
        });
        state.fuseEntries.forEach(function (entry) {
            try { changed += syncFuseClippingEntry(entry); } catch (e) {}
        });
        return changed;
    }

    function isEligibleAtom(mesh) {
        if (!mesh || !mesh.isMesh || !mesh.geometry || Array.isArray(mesh.material)) return false;
        var geometryType = String(mesh.geometry.type || '');
        if (geometryType.indexOf('SphereGeometry') === -1) return false;

        var material = mesh.material;
        if (!material || material.userData && material.userData.crystalFrostMaterial) return false;
        if (!(material.isMeshPhongMaterial || material.isMeshStandardMaterial || material.isMeshPhysicalMaterial)) return false;
        if (material.opacity !== undefined && material.opacity < 0.08) return false;
        if (material.side === state.THREE.DoubleSide) return false;

        return true;
    }

    function isEligibleBond(mesh) {
        if (!mesh || !mesh.isMesh || !mesh.geometry || Array.isArray(mesh.material)) return false;
        var geometryType = String(mesh.geometry.type || '');
        if (geometryType.indexOf('CylinderGeometry') === -1 &&
            geometryType.indexOf('CapsuleGeometry') === -1) return false;

        var material = mesh.material;
        if (!material || material.userData && material.userData.crystalFrostMaterial) return false;
        /* ★ 2026-11-05 页面显式声明「这根键正在做生长动画」：
           组装动画里的键是从 0 缩放到 1 的，本模块按 mesh 当前的世界端点量长度，
           量到的是"半截"，于是把几何改成半截长度 —— 动画结束后键就永久短一截，
           不同时刻被扫描到的键短得还不一样（看着像"键长忽长忽短"）。
           打上本标记的对象整轮跳过；页面在动画收尾时撤掉标记，下一轮再按最终尺寸接管。 */
        if (material.userData && material.userData.crystalFrostSkip) return false;
        if (!(material.isMeshPhongMaterial || material.isMeshStandardMaterial ||
            material.isMeshPhysicalMaterial || material.isMeshBasicMaterial)) return false;
        if (material.side === state.THREE.DoubleSide) return false;
        if (material.transparent && material.opacity !== undefined && material.opacity < 0.12) return false;
        if (material.blending === state.THREE.AdditiveBlending || material.wireframe) return false;
        return true;
    }

    function isBoundaryLineMaterial(material) {
        if (!material || !material.isLineBasicMaterial) return false;
        /* 页面显式声明「这不是晶胞棱」：辅助网格线不该被换成金属杆。
           只认这个标记，没打的页面行为完全不变。 */
        if (material.userData && material.userData.crystalFrostSkip) return false;
        if (material.blending === state.THREE.AdditiveBlending || material.wireframe) return false;
        var opacity = material.opacity === undefined ? 1 : material.opacity;
        if (opacity < 0.15 || opacity > 0.8) return false;
        var hsl = {};
        material.color.getHSL(hsl);
        return hsl.s < 0.55;
    }

    function findBoundaryOwner(line, atomMeshes) {
        var node = line.parent;
        for (var depth = 0; node && depth < 3; depth++, node = node.parent) {
            var atomCount = 0;
            node.traverse(function (child) {
                if (atomMeshes.indexOf(child) !== -1) atomCount++;
            });
            if (atomCount >= 4) return node;
        }
        return null;
    }

    function restoreBaseBondShape(mesh, entry) {
        if (!entry || !mesh.userData.crystalFluidBondShape) return;
        removeFuseSprites(entry);
        if (entry.originalGeometry) mesh.geometry = entry.originalGeometry;
        if (entry.originalPosition) mesh.position.copy(entry.originalPosition);
        if (entry.originalQuaternion) mesh.quaternion.copy(entry.originalQuaternion);
        if (entry.fluidGeometry) entry.fluidGeometry.dispose();
        mesh.userData.crystalFluidBondShape = false;
    }

    function createBoundaryRods(line, owner, atomMeshes, bondWorldRadius) {
        if (state.boundaryLines.has(line)) return 0;
        var position = line.geometry && line.geometry.attributes && line.geometry.attributes.position;
        if (!position || position.count < 2 || position.count % 2 !== 0) return 0;

        var averageRadius = 0;
        var radiusSamples = 0;
        for (var a = 0; a < atomMeshes.length; a++) {
            var atomRadius = worldSphereRadius(atomMeshes[a]);
            if (atomRadius > 0) {
                averageRadius += atomRadius;
                radiusSamples++;
            }
        }
        if (radiusSamples) averageRadius /= radiusSamples;
        var ownerScale = owner.getWorldScale(new state.THREE.Vector3());
        var ownerScaleAverage = Math.max(0.0001,
            (Math.abs(ownerScale.x) + Math.abs(ownerScale.y) + Math.abs(ownerScale.z)) / 3);
        // 棱杆加粗：caf2 是球面切面封盖 + 拼接棱，杆与原子球之间没有缝；
        // 这里用圆柱杆代替，杆太细（0.07）时杆端与原子球之间会留一道缝，
        // 透过磨砂原子看到的就是缝里的背景，看起来像"键被透出来了"。
        // 加粗到 0.12（上限 0.06）把缝补掉，这样 transmission 才能回到 caf2 的 0.88。
        var targetWorldRadius;
        if (bondWorldRadius > 0) {
            // 经典模式按 caf2 的比例走：caf2 键杆 0.055、棱杆 0.055*0.55，
            // 也就是棱比键细 55%。这样任何晶胞的「棱 vs 键」粗细关系都和 caf2 一致。
            targetWorldRadius = bondWorldRadius * 0.55;
        } else {
            targetWorldRadius = Math.min(0.06, Math.max(0.012, averageRadius * 0.10));
        }
        var localRadius = targetWorldRadius / ownerScaleAverage;
        var baseMaterial = line.material;
        var frostMaterial = getBondMaterial(baseMaterial);
        var rods = [];

        line.updateWorldMatrix(true, false);
        owner.updateWorldMatrix(true, false);
        for (var i = 0; i + 1 < position.count; i += 2) {
            var worldA = line.localToWorld(new state.THREE.Vector3(
                position.getX(i), position.getY(i), position.getZ(i)
            ));
            var worldB = line.localToWorld(new state.THREE.Vector3(
                position.getX(i + 1), position.getY(i + 1), position.getZ(i + 1)
            ));
            if (worldA.distanceTo(worldB) < 1e-4) continue;
            var localA = owner.worldToLocal(worldA.clone());
            var localB = owner.worldToLocal(worldB.clone());
            var direction = localB.clone().sub(localA);
            var localLength = direction.length();
            var geometry = new state.THREE.CylinderGeometry(
                localRadius, localRadius, localLength, 16, 1, false
            );
            var rod = new state.THREE.Mesh(geometry, frostMaterial);
            rod.position.copy(localA).add(localB).multiplyScalar(0.5);
            rod.quaternion.setFromUnitVectors(
                new state.THREE.Vector3(0, 1, 0), direction.normalize()
            );
            rod.castShadow = false;
            rod.receiveShadow = true;
            owner.add(rod);
            var rodEntry = {
                base: baseMaterial,
                frost: frostMaterial,
                kind: 'edge',
                originalGeometry: geometry,
                originalPosition: rod.position.clone(),
                originalQuaternion: rod.quaternion.clone(),
                fluidGeometry: null,
                fuseSprites: [],
                shape: null
            };
            rodEntry.shape = fluidizeBond(rod, atomMeshes, rodEntry, true);
            // 端点光斑两种模式都挂：caf2 的晶胞棱在经典模式下也有这对亮点。
            addFuseSprites(rod, rodEntry, rodEntry.shape, true);
            rods.push({ mesh: rod, entry: rodEntry });
        }
        if (!rods.length) return 0;
        state.boundaryLines.add(line);
        state.boundaries.push({ line: line, rods: rods });
        line.visible = false;
        return rods.length;
    }

    function convertBoundaryLines(objects, atomMeshes, bondWorldRadius) {
        var converted = 0;
        objects.forEach(function (object) {
            if (!(object.isLine || object.isLineSegments) || !object.visible) return;
            if (state.boundaryLines.has(object) || !isBoundaryLineMaterial(object.material)) return;
            var owner = findBoundaryOwner(object, atomMeshes);
            if (owner) converted += createBoundaryRods(object, owner, atomMeshes, bondWorldRadius);
        });
        return converted;
    }

    // 页面重建晶胞后旧的 Line 会被丢弃，它生成的金属杆得跟着撤掉，否则会留下孤儿杆。
    function pruneOrphanBoundaries() {
        var kept = [];
        state.boundaries.forEach(function (boundary) {
            var node = boundary.line;
            var inScene = false;
            while (node) {
                if (node === state.scene) { inScene = true; break; }
                node = node.parent;
            }
            if (inScene) { kept.push(boundary); return; }
            boundary.rods.forEach(function (item) {
                removeFuseSprites(item.entry);
                if (item.mesh.parent) item.mesh.parent.remove(item.mesh);
                if (item.mesh.geometry) item.mesh.geometry.dispose();
            });
        });
        state.boundaries = kept;
    }

    /* 辉光现在挂在「键/原子的 mesh」下面，mesh 被页面整组清掉（clearGroup）时
       辉光会跟着从画面上消失，但它的材质不会再被 clearGroup dispose 到 ——
       这里补一次回收，连续两轮发现 mesh 已脱离父级才动手（避免误删正在被
       页面 remove→add 重挂的 mesh）。 */
    function pruneOrphanFuses() {
        state.fuseEntries.forEach(function (entry) {
            if (!entry || !entry.fuseSprites || !entry.fuseSprites.length) {
                state.fuseEntries.delete(entry);
                return;
            }
            var mesh = entry.fuseSprites[0] && entry.fuseSprites[0].userData.fuseMesh;
            if (mesh && !mesh.parent) {
                entry.__orphanFuse = (entry.__orphanFuse || 0) + 1;
                if (entry.__orphanFuse >= 2) removeFuseSprites(entry);
            } else {
                entry.__orphanFuse = 0;
            }
        });
    }

    // 晶胞框（Line）隐藏时金属杆也要跟着隐藏，不然「隐藏晶胞」关不掉。
    function syncBoundaryVisibility() {
        state.boundaries.forEach(function (boundary) {
            var visible = boundary.line.visible && boundary.line.parent !== null;
            boundary.rods.forEach(function (item) {
                item.mesh.visible = visible;
                if (item.entry && item.entry.fuseSprites) {
                    item.entry.fuseSprites.forEach(function (sprite) { sprite.visible = visible; });
                }
            });
        });
    }

    function restoreBoundaryLines() {
        state.boundaries.forEach(function (boundary) {
            boundary.line.visible = true;
            boundary.rods.forEach(function (item) {
                removeFuseSprites(item.entry);
                if (item.mesh.parent) item.mesh.parent.remove(item.mesh);
                if (item.mesh.geometry) item.mesh.geometry.dispose();
                if (item.entry.originalGeometry && item.entry.originalGeometry !== item.mesh.geometry) {
                    item.entry.originalGeometry.dispose();
                }
            });
        });
        state.boundaries = [];
        state.boundaryLines = new WeakSet();
    }

    function syncMaterialSettings(base, frost, preserveTransparency) {
        frost.clippingPlanes = base.clippingPlanes;
        frost.clipIntersection = base.clipIntersection;
        frost.clipShadows = base.clipShadows;
        frost.depthWrite = base.depthWrite;
        frost.depthTest = base.depthTest;
        frost.side = base.side;
        if (preserveTransparency) {
            frost.transparent = base.transparent;
            frost.opacity = base.opacity === undefined ? 1 : base.opacity;
            frost.blending = base.blending;
        } else {
            frost.transparent = false;
            frost.opacity = 1;
            frost.blending = state.THREE.NormalBlending;
            frost.depthWrite = true;
        }
    }

    function applyToMesh(mesh) {
        var entry = state.entries.get(mesh);
        if (entry && mesh.material === entry.frost && entry.kind === 'atom') {
            syncMaterialSettings(entry.base, entry.frost, true);
            return true;
        }

        if (!isEligibleAtom(mesh)) return false;
        var base = mesh.material;
        if (!entry || base !== entry.base) {
            entry = {
                base: base,
                frost: getFrostMaterial(base),
                kind: 'atom'
            };
            state.entries.set(mesh, entry);
            state.entrySet.add(entry);
        }
        syncMaterialSettings(entry.base, entry.frost, true);
        mesh.material = entry.frost;
        return true;
    }

    // 经典模式不换形状（还是页面原来的直圆柱），只按原子球面算出两端位置，
    // 用来挂 caf2 那对端点光斑——金属棒"亮起来"靠的就是这对光斑。
    function measureClassicBondShape(mesh, atomMeshes, entry) {
        if (!mesh.geometry || !mesh.geometry.parameters) return null;
        var height = Number(mesh.geometry.parameters.height);
        if (!(height > 0)) return null;
        var radiusTop = Number(mesh.geometry.parameters.radiusTop);
        var radiusBottom = Number(mesh.geometry.parameters.radiusBottom);
        var rodRadius = Math.max(0.001, (radiusTop + radiusBottom) * 0.5);
        mesh.updateWorldMatrix(true, false);
        var p1 = mesh.localToWorld(new state.THREE.Vector3(0, height / 2, 0));
        var p2 = mesh.localToWorld(new state.THREE.Vector3(0, -height / 2, 0));
        if (p1.distanceTo(p2) < 1e-4) return null;
        var direction = p2.clone().sub(p1).normalize();
        var worldScale = mesh.getWorldScale(new state.THREE.Vector3());
        var radialScale = (Math.abs(worldScale.x) + Math.abs(worldScale.z)) * 0.5;
        var worldRodRadius = Math.max(0.0005, rodRadius * radialScale);
        var previous = entry ? entry.shape : null;
        var atom1 = pickRememberedAtom(previous ? previous.atom1 : null, p1, atomMeshes);
        var atom2 = pickRememberedAtom(previous ? previous.atom2 : null, p2, atomMeshes);

        function surfacePoint(point, atom, sign) {
            if (!atom) return point.clone();
            var surface = Math.sqrt(Math.max(0.0001, atom.radius * atom.radius - worldRodRadius * worldRodRadius));
            return atom.center.clone().addScaledVector(direction, sign * (surface - 0.012));
        }
        return {
            atom1: atom1,
            atom2: atom2,
            start: surfacePoint(p1, atom1, 1),
            end: surfacePoint(p2, atom2, -1),
            worldRodRadius: worldRodRadius,
            isCage: false
        };
    }

    function addClassicGlints(mesh, entry, atomMeshes, preserveTransparent) {
        if (preserveTransparent) return;                 // 磨砂流程自己挂光斑，别重复
        if (!mesh.parent || !state.glowTexture) return;
        if (entry.fuseSprites && entry.fuseSprites.length === 2) return;
        entry.shape = measureClassicBondShape(mesh, atomMeshes, entry);
        if (!entry.shape) return;
        var base = entry.base;
        var isCage = !!(base && (base.isMeshBasicMaterial ||
            (base.transparent && base.opacity !== undefined && base.opacity < 0.7)));
        entry.shape.isCage = isCage;
        addFuseSprites(mesh, entry, entry.shape, isCage);
    }

    // 只把键换成金属材质，形状保持页面原来的直圆柱（经典模式要的就是球棍模型）。
    // 磨砂模式在同一函数之后才做 fluidize（两端嵌进原子球、中段收腰）。
    function applyMetalBondMaterial(mesh, preserveTransparent, atomMeshes) {
        var entry = state.entries.get(mesh);
        if (entry && entry.kind === 'bond' && mesh.material === entry.frost) {
            syncMaterialSettings(entry.base, entry.frost, !!preserveTransparent);
            addClassicGlints(mesh, entry, atomMeshes, !!preserveTransparent);
            return true;
        }
        if (!isEligibleBond(mesh)) return false;
        var base = mesh.material;
        if (!entry || base !== entry.base || entry.kind !== 'bond') {
            entry = {
                base: base,
                frost: getBondMaterial(base),
                kind: 'bond',
                originalGeometry: mesh.geometry,
                originalPosition: mesh.position.clone(),
                originalQuaternion: mesh.quaternion.clone(),
                fluidGeometry: null,
                fuseSprites: [],
                shape: null
            };
            state.entries.set(mesh, entry);
        }
        syncMaterialSettings(entry.base, entry.frost, !!preserveTransparent);
        mesh.material = entry.frost;
        addClassicGlints(mesh, entry, atomMeshes, !!preserveTransparent);
        return true;
    }

    function worldRodRadiusOf(mesh) {
        var parameters = mesh.geometry && mesh.geometry.parameters;
        if (!parameters || !(Number(parameters.height) > 0)) return 0;
        var radius = (Number(parameters.radiusTop) + Number(parameters.radiusBottom)) * 0.5;
        if (!(radius > 0)) return 0;
        var scale = mesh.getWorldScale(new state.THREE.Vector3());
        return radius * (Math.abs(scale.x) + Math.abs(scale.z)) * 0.5;
    }

    function medianOf(values) {
        if (!values.length) return 0;
        var sorted = values.slice().sort(function (a, b) { return a - b; });
        return sorted[Math.floor(sorted.length / 2)];
    }

    // 经典原子模式：原子还是原来的实心材质，但键和晶胞边界用和磨砂模式一样的金属材质。
    // 一律强制不透明（caf2 就是这样）：原来 30%~70% 透明度的键/棱照搬过来只会显得
    // "淡淡一层银白"，看不出金属。
    function applyClassicMetalBonds() {
        if (!state.attached || !state.scene || state.enabled) return { bonds: 0, edges: 0 };
        var objects = [];
        state.scene.traverse(function (object) { objects.push(object); });
        var atomMeshes = collectAtomMeshes();

        /* 先量这批杆的世界半径，中位数就是页面自己的"化学键"粗细。
           比它细一半以上的杆（nacl 的晶胞棱只有 0.015）其实是晶胞边界，
           按 caf2 的「棱 = 键 × 0.55」补粗，否则边界细得像根线。 */
        var samples = [];
        objects.forEach(function (object) {
            if (!object.visible || !isEligibleBond(object)) return;
            var sample = worldRodRadiusOf(object);
            if (sample > 0) samples.push(sample);
        });
        var median = medianOf(samples);
        var edgeRadius = median * 0.55;
        var thinLimit = edgeRadius * 0.98;

        var bonds = 0;
        var bondRadii = [];
        objects.forEach(function (object) {
            var isThinEdge = false;
            if (median > 0 && object.visible && isEligibleBond(object)) {
                var raw = worldRodRadiusOf(object);
                isThinEdge = raw > 0 && raw < thinLimit;
            }
            if (!applyMetalBondMaterial(object, false, atomMeshes)) return;
            bonds++;
            /* 形状也照 caf2：键两端收进原子球、中段圆角过渡（buildFluidBondGeometry），
               不是页面原来的直圆柱。caf2 的经典模式就是流体键，直圆柱看着像"塑料棍"。 */
            var entry = state.entries.get(object);
            if (!entry || entry.kind !== 'bond') return;
            if (!object.userData.crystalFluidBondShape) {
                entry.shape = fluidizeBond(object, atomMeshes, entry, isThinEdge,
                    isThinEdge ? edgeRadius : 0);
                if (entry.shape) addFuseSprites(object, entry, entry.shape, isThinEdge);
            } else if (!entry.fuseSprites || entry.fuseSprites.length !== 2) {
                addFuseSprites(object, entry, entry.shape, entry.shape && entry.shape.isCage);
            }
            if (!isThinEdge && entry.shape && entry.shape.worldRodRadius > 0) {
                bondRadii.push(entry.shape.worldRodRadius);
            }
        });
        // 棱杆粗细按这批键的实际半径定（caf2：棱 = 键 × 0.55），键棱比例与 caf2 一致。
        var averageBondRadius = 0;
        if (bondRadii.length) {
            bondRadii.forEach(function (value) { averageBondRadius += value; });
            averageBondRadius /= bondRadii.length;
        } else if (median > 0) {
            averageBondRadius = median;
        }
        var edges = convertBoundaryLines(objects, atomMeshes, averageBondRadius);
        syncClipping();
        return { bonds: bonds, edges: edges };
    }

    function applyBondToMesh(mesh, atomMeshes) {
        var entry = state.entries.get(mesh);
        if (entry && entry.kind === 'bond' && mesh.material === entry.frost) {
            syncMaterialSettings(entry.base, entry.frost, false);
        } else {
            // 经典模式可能已经把键换成金属材质了，这里要认出来，别重复建 entry
            if (!applyMetalBondMaterial(mesh)) return false;
            entry = state.entries.get(mesh);
        }
        if (!mesh.userData.crystalFluidBondShape) {
            var isCage = entry.base.isMeshBasicMaterial ||
                (entry.base.transparent && entry.base.opacity !== undefined && entry.base.opacity < 0.7);
            entry.shape = fluidizeBond(mesh, atomMeshes, entry, isCage);
            if (state.enabled) addFuseSprites(mesh, entry, entry.shape, isCage);
        } else if (state.enabled && entry.shape && (!entry.fuseSprites || entry.fuseSprites.length !== 2)) {
            addFuseSprites(mesh, entry, entry.shape, entry.shape.isCage);
        }
        return true;
    }

    function scanAndApply(skipAtoms) {
        if (!state.enabled || !state.scene) return { atoms: 0, bonds: 0, edges: 0 };
        var atoms = 0;
        var bonds = 0;
        var objects = [];
        var atomMeshes = [];
        state.scene.traverse(function (object) {
            objects.push(object);
            if (object.isMesh && object.geometry &&
                String(object.geometry.type || '').indexOf('SphereGeometry') !== -1 &&
                object.visible) {
                atomMeshes.push(object);
            }
        });
        var edges = convertBoundaryLines(objects, atomMeshes);
        objects.forEach(function (object) {
            /* skipAtoms：转换动画里临时原子球要由页面自己控 opacity 淡入淡出，
               一旦被接管成磨砂材质，页面手里那份材质就失效了（原子不会淡出）。 */
            if (!skipAtoms && applyToMesh(object)) {
                atoms++;
            } else if (applyBondToMesh(object, atomMeshes)) {
                bonds++;
            }
        });
        reflowFluidBonds(atomMeshes, false);
        syncClipping();
        return { atoms: atoms, bonds: bonds, edges: edges };
    }

    // 页面把原子球改大 / 改小（缩放滑杆）之后，键的长度要跟着重算，
    // 否则磨砂模式下键还是老长度：要么埋进球里，要么两头悬空。
    // caf2 那类页面自己写了 updateFluidBond，其余页面没写 —— 这里统一兜住。
    function isSelectedAtom(mesh) {
        return !!(mesh.userData && (mesh.userData.origMat || mesh.userData.isHighlighted));
    }

    function globalAtomSizeChanged(atomMeshes) {
        var tracked = 0;
        var changed = 0;
        for (var i = 0; i < atomMeshes.length; i++) {
            var mesh = atomMeshes[i];
            if (isSelectedAtom(mesh)) continue;      // 选中/高亮的脉动不算尺寸调整
            var radius = worldSphereRadius(mesh);
            var last = state.atomRadii.get(mesh);
            if (last === undefined) { state.atomRadii.set(mesh, radius); continue; }
            tracked++;
            if (Math.abs(radius - last) > Math.max(1e-4, last * 0.002)) changed++;
        }
        if (tracked === 0) return false;
        return (changed / tracked) > 0.6;
    }

    function reflowFluidBonds(atomMeshes, force) {
        // 经典模式也要重算：键形状和 caf2 一样是"贴着原子球面"的流体键，
        // 原子被放大/缩小后不重算就会埋进球里或悬空。
        if (!state.scene) return 0;
        if (!atomMeshes) atomMeshes = collectAtomMeshes();
        if (!force && !globalAtomSizeChanged(atomMeshes)) return 0;
        var pending = [];
        state.scene.traverse(function (object) {
            var entry = state.entries.get(object);
            if (!entry || entry.kind !== 'bond') return;
            if (!object.userData.crystalFluidBondShape || !entry.shape) return;
            pending.push({ mesh: object, entry: entry });
        });
        for (var i = 0; i < pending.length; i++) {
            var item = pending[i];
            var isCage = !!(item.entry.shape && item.entry.shape.isCage);
            restoreBaseBondShape(item.mesh, item.entry);
            item.entry.shape = fluidizeBond(item.mesh, atomMeshes, item.entry, isCage,
                item.entry.overrideWorldRadius || 0);
            addFuseSprites(item.mesh, item.entry, item.entry.shape, isCage);
            var shape = item.entry.shape;
            if (shape) {
                if (shape.atom1) state.atomRadii.set(shape.atom1.mesh, shape.atom1.radius);
                if (shape.atom2) state.atomRadii.set(shape.atom2.mesh, shape.atom2.radius);
            }
        }
        return pending.length;
    }

    function collectAtomMeshes() {
        var atomMeshes = [];
        if (!state.scene) return atomMeshes;
        state.scene.traverse(function (object) {
            if (object.isMesh && object.geometry &&
                String(object.geometry.type || '').indexOf('SphereGeometry') !== -1 &&
                object.visible) {
                atomMeshes.push(object);
            }
        });
        return atomMeshes;
    }

    var reflowPending = false;
    var lastReflowAt = 0;
    function nowMs() {
        return (window.performance && performance.now) ? performance.now() : Date.now();
    }
    // 拖得太快时交给下一轮补算一次，别每个事件都重建全部键
    function queueReflow() {
        if (reflowPending) return;
        reflowPending = true;
        setTimeout(function () {
            reflowPending = false;
            if (!state.scene) return;
            lastReflowAt = nowMs();
            reflowFluidBonds(collectAtomMeshes(), true);
        }, 40);
    }
    function scheduleReflow() {
        if (!state.scene) return;
        if (nowMs() - lastReflowAt < 50) { queueReflow(); return; }
        lastReflowAt = nowMs();
        reflowFluidBonds(collectAtomMeshes(), true);
    }

    function restoreMeshes() {
        if (!state.scene) return;
        var pending = [];
        state.scene.traverse(function (object) {
            var entry = state.entries.get(object);
            if (entry && object.material === entry.frost) {
                pending.push({ object: object, entry: entry });
            }
        });
        pending.forEach(function (item) {
            item.object.material = item.entry.base;
            if (item.entry.kind === 'bond') {
                restoreBaseBondShape(item.object, item.entry);
            }
        });
    }

    function captureRenderSettings() {
        state.rendererToneMapping = state.renderer ? state.renderer.toneMapping : null;
        state.rendererExposure = state.renderer ? state.renderer.toneMappingExposure : null;
        state.sceneEnvironment = state.scene ? state.scene.environment : null;
        state.sceneEnvironmentIntensity = state.scene && ('environmentIntensity' in state.scene) ?
            state.scene.environmentIntensity : null;
    }

    function captureLights() {
        state.sourceLights = [];
        if (!state.scene) return;
        state.scene.traverse(function (object) {
            if (object.isLight && state.studioLights.indexOf(object) === -1) {
                state.sourceLights.push({ light: object, visible: object.visible });
            }
        });
    }

    function normalizeLegacyLights(scene) {
        if (!scene) return;
        scene.traverse(function (object) {
            if (object.isPointLight) object.decay = 0;
        });
    }

    function createStudioLights(THREE, scene) {
        var hemi = new THREE.HemisphereLight(0xf0f6ff, 0x1e293b, 0.78);
        var key = new THREE.DirectionalLight(0xfffcf5, 2.45);
        key.position.set(-7, 9, 9);
        var back = new THREE.DirectionalLight(0xa5f3fc, 1.28);
        back.position.set(6, 4, -9);
        var bottom = new THREE.DirectionalLight(0xffe4b5, 0.85);
        bottom.position.set(0, -9, 4);
        state.studioLights = [hemi, key, back, bottom];
        state.studioLights.forEach(function (light) {
            light.visible = false;
            light.__crystalFrostStudio = true;   // 不参与经典模式亮度补偿
            scene.add(light);
        });
    }

    function updateButton() {
        if (!state.button) return;
        state.button.innerHTML = ICON + (state.enabled ? '切换经典实心原子' : '切换磨砂玻璃原子');
        state.button.classList.toggle('atom-style-active', state.enabled);
        state.button.setAttribute('aria-pressed', state.enabled ? 'true' : 'false');
        if (state.button.parentNode && state.button.parentNode.classList.contains('topbar-actions')) {
            state.button.style.background = state.enabled ? 'rgba(85, 153, 255, 0.32)' : '';
            state.button.style.borderColor = state.enabled ? '#88bbff' : '';
            state.button.style.color = state.enabled ? '#fff' : '';
        } else {
            state.button.style.background = state.enabled ? 'rgba(85, 153, 255, 0.92)' : 'rgba(16, 22, 36, 0.9)';
            state.button.style.borderColor = state.enabled ? '#88bbff' : 'rgba(255,255,255,.3)';
        }
    }

    function ensureButton() {
        if (state.button && document.body.contains(state.button)) return state.button;
        var button = document.createElement('button');
        button.type = 'button';
        button.id = 'btn-crystal-frost';
        button.className = 'top-btn';
        button.title = '切换晶体原子的磨砂玻璃与经典实心材质';
        button.addEventListener('click', function () {
            setEnabled(!state.enabled);
        });

        var actions = document.querySelector('.topbar-actions');
        if (actions) {
            var pause = actions.querySelector('#btn-pause');
            actions.insertBefore(button, pause || actions.firstChild);
        } else {
            button.style.position = 'fixed';
            button.style.top = '14px';
            button.style.right = '14px';
            button.style.zIndex = '12000';
            button.style.padding = '8px 12px';
            button.style.borderRadius = '10px';
            button.style.color = '#fff';
            button.style.cursor = 'pointer';
            button.style.font = '600 12px "Microsoft YaHei", sans-serif';
            document.body.appendChild(button);
        }
        state.button = button;
        updateButton();
        return button;
    }

    function setEnabled(enabled) {
        if (!state.attached) return;
        enabled = !!enabled;
        if (state.enabled === enabled) {
            updateButton();
            return;
        }
        state.enabled = enabled;
        setBondClassicBoost(!enabled);   // 金属高光只在经典模式开；磨砂模式靠透射/环境光
        if (enabled) {
            captureLights();
            setClassicScale(true);
            if (state.nativeTransmission) {
                state.sourceLights.forEach(function (item) { item.light.visible = false; });
                state.studioLights.forEach(function (light) { light.visible = true; });
            }
            if (state.nativeTransmission && state.renderer) {
                state.renderer.toneMapping = state.THREE.ACESFilmicToneMapping;
                state.renderer.toneMappingExposure = 1.16;
                state.scene.environment = state.envMap;
                if ('environmentIntensity' in state.scene) state.scene.environmentIntensity = 1;
            }
            scanAndApply();
        } else {
            restoreBoundaryLines();
            restoreMeshes();
            applyClassicMetalBonds();
            setClassicScale(false);
            if (state.nativeTransmission) {
                state.scene.environment = state.sceneEnvironment;
            } else {
                restoreClassicEnvironment();
            }
            if (state.nativeTransmission && state.renderer) {
                state.sourceLights.forEach(function (item) { item.light.visible = item.visible; });
                state.studioLights.forEach(function (light) { light.visible = false; });
                state.renderer.toneMapping = state.rendererToneMapping;
                state.renderer.toneMappingExposure = state.rendererExposure;
                state.scene.environment = state.sceneEnvironment;
                if ('environmentIntensity' in state.scene) {
                    state.scene.environmentIntensity = state.sceneEnvironmentIntensity;
                }
            }
        }
        updateButton();
    }

    /*
     * 磨砂模式下页面自有材质（棱、辅助线、旧的物理材质）的环境贴图补齐
     * ---------------------------------------------------------------
     * 注意：经典模式**不**走这里 —— 经典模式交给 installClassicPhongPatch()
     * 改写 Phong/Lambert 输出式（caf2 原方案）。给 Phong 硬塞 envMap 在 r170 下
     * 会让球体反黑/发白，实测整屏变黑。
     */
    function applyClassicEnvironment() {
        if (!state.scene || !state.envMap || state.classicEnvironed) return 0;
        var applied = 0;
        state.scene.traverse(function (object) {
            var material = object.material;
            if (!material) return;
            var list = Array.isArray(material) ? material : [material];
            list.forEach(function (item) {
                if (!item || item.__crystalFrostStudioMap) return;
                if (item.__crystalFrostClassicEnv) return;
                if (!('envMap' in item)) return;
                if (state.entries.get(object)) return;
                item.userData = item.userData || {};
                if (item.userData.crystalFrostMaterial) return;
                // r170 里 Phong/Standard 的 envMap 也要按 PBR 走辐照度，老材质会过曝或反黑；
                // 只给「原本就吃 envMap」的物理/标准材质补，普通材质交给灯光+π 补偿。
                if (!item.envMap && item.isMeshPhysicalMaterial !== true && item.isMeshStandardMaterial !== true) return;
                item.__cfPrevEnvMap = item.envMap || null;
                item.__cfPrevEnvIntensity = ('envMapIntensity' in item) ? item.envMapIntensity : null;
                item.envMap = state.envMap;
                if ('envMapIntensity' in item) item.envMapIntensity = 1.15;
                item.__crystalFrostClassicEnv = true;
                item.needsUpdate = true;
                applied++;
            });
        });
        if (!state.scene.environment && state.envMap) {
            state.scene.__cfPrevEnvironment = state.scene.environment || null;
            state.scene.environment = state.envMap;
            if ('environmentIntensity' in state.scene) state.scene.environmentIntensity = 0.36;
        }
        state.classicEnvironed = true;
        return applied;
    }

    function restoreClassicEnvironment() {
        if (!state.scene || !state.classicEnvironed) return;
        state.scene.traverse(function (object) {
            var material = object.material;
            if (!material) return;
            var list = Array.isArray(material) ? material : [material];
            list.forEach(function (item) {
                if (!item || !item.__crystalFrostClassicEnv) return;
                item.envMap = item.__cfPrevEnvMap || null;
                if ('envMapIntensity' in item) {
                    item.envMapIntensity = item.__cfPrevEnvIntensity === null ? 1 : item.__cfPrevEnvIntensity;
                }
                item.__crystalFrostClassicEnv = false;
                item.needsUpdate = true;
            });
        });
        if (state.scene.__cfPrevEnvironment === null) state.scene.environment = null;
        state.classicEnvironed = false;
    }

    /*
     * 经典实心原子的 r128 光学还原（整套照搬 caf2）
     * ---------------------------------------------------------------
     * r155+ 移除了 legacyLights（×π）、PointLight 默认 decay 变化、
     * ColorManagement 也把暗部压掉，单纯"把灯乘 π"只能补亮度，
     * 补不回 12.92 线性段和 35.5 倍窄高光 —— 球看着还是平的。
     * caf2 的做法是直接改写 MeshPhongMaterial / MeshLambertMaterial 的输出式，
     * 用两个 uniform 在经典/磨砂之间切换；这里原样搬过来，保证和氟化钙一模一样。
     */
    var CLASSIC_LIGHT_SCALE = 3.0;   // 经典模式灯光增益
    var CLASSIC_SPEC_SCALE = 35.5;   // 经典模式高光增益
    /*
     * 磨砂模式下，页面自有材质（未换成磨砂材质的辅助线、部分棱）仍在跑这套改写式。
     * 这里不能用 1.15/12.0：那会让它们被 ACES 之后的亮度堆到接近纯白（球体发白、
     * 化学键和晶胞边界的银灰变白）。
     * 磨砂模式场景本就切到 studio 环境 + ACES，所以给一个更克制的中性值。
     */
    var FROST_LIGHT_SCALE = 0.42;
    var FROST_SPEC_SCALE = 3.2;

    function installClassicPhongPatch(THREE) {
        if (window.__classicPhongUniforms) {
            state.classicPhongUniforms = window.__classicPhongUniforms;
            return;
        }
        var uniforms = {
            uClassicLightScale: { value: CLASSIC_LIGHT_SCALE },
            uClassicSpecScale: { value: CLASSIC_SPEC_SCALE }
        };
        window.__classicPhongUniforms = uniforms;
        state.classicPhongUniforms = uniforms;

        var SRGB_CONVERT =
            '\tvec3 cSrgb = mix(diffuseColor.rgb * 12.92, 1.055 * pow(max(diffuseColor.rgb, vec3(0.0)), vec3(1.0 / 2.4)) - 0.055, step(0.0031308, diffuseColor.rgb));\n';

        if (THREE.MeshPhongMaterial) {
            THREE.MeshPhongMaterial.prototype.onBeforeCompile = function (shader) {
                shader.uniforms.uClassicLightScale = uniforms.uClassicLightScale;
                shader.uniforms.uClassicSpecScale = uniforms.uClassicSpecScale;
                var endAnchor = '#include <dithering_fragment>';
                if (shader.fragmentShader.indexOf(endAnchor) === -1) return;
                shader.fragmentShader =
                    'uniform float uClassicLightScale;\nuniform float uClassicSpecScale;\n' +
                    shader.fragmentShader.replace(
                        endAnchor,
                        SRGB_CONVERT +
                        '\tvec3 rawLightSum = (reflectedLight.directDiffuse + reflectedLight.indirectDiffuse) * uClassicLightScale / max(diffuseColor.rgb, vec3(1e-4));\n' +
                        '\tvec3 rawSpec = reflectedLight.directSpecular * uClassicSpecScale;\n' +
                        '\tvec3 emSrgb = mix(totalEmissiveRadiance * 12.92, 1.055 * pow(max(totalEmissiveRadiance, vec3(0.0)), vec3(1.0 / 2.4)) - 0.055, step(0.0031308, totalEmissiveRadiance));\n' +
                        '\tvec3 softEm = emSrgb * (1.0 - 0.72 * clamp(rawLightSum, 0.0, 1.0));\n' +
                        '\tgl_FragColor = vec4(clamp(cSrgb * rawLightSum + softEm + rawSpec, 0.0, 1.0), diffuseColor.a);\n' +
                        endAnchor
                    );
            };
        }
        if (THREE.MeshLambertMaterial) {
            THREE.MeshLambertMaterial.prototype.onBeforeCompile = function (shader) {
                shader.uniforms.uClassicLightScale = uniforms.uClassicLightScale;
                var endAnchor = '#include <dithering_fragment>';
                if (shader.fragmentShader.indexOf(endAnchor) === -1) return;
                shader.fragmentShader =
                    'uniform float uClassicLightScale;\n' +
                    shader.fragmentShader.replace(
                        endAnchor,
                        SRGB_CONVERT +
                        '\tvec3 rawLightSum = (reflectedLight.directDiffuse + reflectedLight.indirectDiffuse) * uClassicLightScale / max(diffuseColor.rgb, vec3(1e-4));\n' +
                        '\tvec3 emSrgb = mix(totalEmissiveRadiance * 12.92, 1.055 * pow(max(totalEmissiveRadiance, vec3(0.0)), vec3(1.0 / 2.4)) - 0.055, step(0.0031308, totalEmissiveRadiance));\n' +
                        '\tgl_FragColor = vec4(clamp(cSrgb * rawLightSum + emSrgb, 0.0, 1.0), diffuseColor.a);\n' +
                        endAnchor
                    );
            };
        }
    }

    /*
     * 经典补丁装晚了的补救：模块是在 window load 之后才 attach 的，那时页面材质
     * 早就编译好 program 了。改 prototype.onBeforeCompile 不会让已编译的材质重新编译，
     * 必须显式 needsUpdate = true 才会重新走一遍 —— 否则经典模式看起来"补丁没生效"。
     */
    function refreshClassicMaterials(scene, THREE) {
        if (!scene) return;
        var seen = [];
        scene.traverse(function (object) {
            var material = object.material;
            if (!material) return;
            var list = Array.isArray(material) ? material : [material];
            list.forEach(function (item) {
                if (!item || seen.indexOf(item) !== -1) return;
                var isPhong = item.isMeshPhongMaterial ||
                    (THREE && THREE.MeshPhongMaterial && item instanceof THREE.MeshPhongMaterial);
                var isLambert = item.isMeshLambertMaterial ||
                    (THREE && THREE.MeshLambertMaterial && item instanceof THREE.MeshLambertMaterial);
                if (!isPhong && !isLambert) return;
                seen.push(item);
                item.needsUpdate = true;
            });
        });
        return seen.length;
    }

    function setClassicScale(frosted) {
        var uniforms = state.classicPhongUniforms || window.__classicPhongUniforms;
        if (!uniforms) return;
        uniforms.uClassicLightScale.value = frosted ? FROST_LIGHT_SCALE : CLASSIC_LIGHT_SCALE;
        uniforms.uClassicSpecScale.value = frosted ? FROST_SPEC_SCALE : CLASSIC_SPEC_SCALE;
    }

    function attach(options) {
        options = options || {};
        var THREE = options.THREE || window.THREE;
        var scene = options.scene || null;
        var renderer = options.renderer || null;
        if (!THREE || !scene) return null;

        if (state.attached && state.scene === scene && state.renderer === renderer) {
            ensureButton();
            return api;
        }
        if (state.attached) setEnabled(false);
        state.THREE = THREE;
        state.scene = scene;
        state.renderer = renderer;
        state.entries = new WeakMap();
        state.entrySet = new Set();
        state.atomRadii = new WeakMap();
        state.frostCache = new Map();
        state.bondCache = new Map();
        state.boundaryLines = new WeakSet();
        state.boundaries = [];
        var probe = new THREE.MeshPhysicalMaterial();
        state.nativeTransmission = ('sheenColor' in probe) && ('thickness' in probe);
        probe.dispose();
        state.normalMap = makeSilkNormalMap(THREE, renderer);
        state.envMap = makeStudioEnvironment(THREE, renderer);
        state.glowTexture = makeSoftGlowTexture(THREE);
        // 照抄 caf2.html：r155+ 的 PointLight 默认 decay=2（物理平方衰减），
        // 老页面按 r128 的 decay=0 设计的灯会直接变暗、球面失去明暗层次。
        // 经典模式靠的就是页面自带的灯，所以这里一律恢复 decay=0。
        normalizeLegacyLights(scene);
        createStudioLights(THREE, scene);
        state.attached = true;
        // 经典模式光学还原：和 caf2 完全一致的做法（改写 Phong/Lambert 输出式），
        // 取代之前"把灯乘 π"的粗糙补偿 —— 那个只补亮度，补不回立体感。
        // 只给"本次从 r128 升到 r170 的页面"打经典补丁。wannengjingbao 这类
        // r160 + ES Module 的页面灯光本来就是物理单位，打补丁会过曝（同 10-20 的教训）。
        state.classicPatchApplies = needsLegacyGain(THREE);
        if (state.classicPatchApplies) {
            installClassicPhongPatch(THREE);
            setClassicScale(false);
            refreshClassicMaterials(scene, THREE);
            // 页面里后建的材质会在首次编译时自动吃到 prototype 上的补丁；
            // 这里再补两轮，接住那些在 attach 之后才被创建的原子材质。
            setTimeout(function () { refreshClassicMaterials(state.scene, state.THREE); }, 0);
            setTimeout(function () { refreshClassicMaterials(state.scene, state.THREE); }, 800);
        }
        captureRenderSettings();
        setBondClassicBoost(!state.enabled);   // 经典模式给键/杆挂 caf2 那套虚拟高光
        // 常驻扫描：磨砂开时铺材质 + 流态键；磨砂关时也要跑，让经典模式的金属键/金属棱
        // 能接住页面后来新建的键和晶胞（比如切规模、重建晶胞）。
        clearInterval(state.scanTimer);
        state.scanTimer = setInterval(function () {
            if (state.scanPaused) return;
            pruneOrphanBoundaries();
            pruneOrphanFuses();
            if (state.enabled) scanAndApply();
            else applyClassicMetalBonds();
            syncBoundaryVisibility();
        }, 650);
        applyClassicMetalBonds();
        /* ★ 交互后立刻补扫（见 queueRefresh 注释）：点一下就把对齐排到下一帧，
           再在 200ms 兜一次底（滑杆、定时器改的裁剪面 / 后建的键）。 */
        if (!state.clipWatchInstalled) {
            state.clipWatchInstalled = true;
            ['pointerdown', 'click', 'input', 'change'].forEach(function (type) {
                document.addEventListener(type, queueRefresh, true);
            });
            clearInterval(state.clipTimer);
            state.clipTimer = setInterval(function () {
                if (!clippingDiffers()) return;      // 便宜的那半：只是指针比较
                refreshNow();
            }, 200);
        }
        ensureButton();
        /* 首屏补三轮：有些页的键/晶胞是在 rAF 或 setTimeout 里才建好的，
           只靠 650ms 那轮扫描会晚 —— 画面上就是「打开后过半秒键才一闪换成金属质感」。
           这里在 attach 之后立刻再扫几次，把延迟创建的键接住（函数内部幂等）。 */
        [0, 120, 400].forEach(function (delay) {
            setTimeout(function () {
                if (state.scene !== scene) return;
                if (state.enabled) scanAndApply(); else applyClassicMetalBonds();
            }, delay);
        });
        return api;
    }

    var api = {
        attach: attach,
        setEnabled: setEnabled,
        refresh: scanAndApply,
        // 页面改完原子半径后主动调一下，键长立刻跟上（拖滑杆时模块已经自动调了）
        reflowBonds: function () { return reflowFluidBonds(collectAtomMeshes(), true); },
        isEnabled: function () { return state.enabled; },
        /* 页面自己管理透明度的原子/键（晶体环分析会把同一批 mesh 反复改 opacity，
           不能交给扫描器统一接管）：给一份「干净底料对应的磨砂材质」，
           页面只改底料的 opacity/transparent，再把这份材质挂到 mesh 上即可。
           baseOf(mesh) 用来取回某个 mesh 接管前的干净底料（颜色是原色，不是被漂白的磨砂色）。 */
        materialOf: function (base) { return (state.attached && base) ? getFrostMaterial(base) : null; },
        bondMaterialOf: function (base) { return (state.attached && base) ? getBondMaterial(base) : null; },
        /* 页面重建晶胞 / 转换动画结束时「立刻」接管一次，不要等 650ms 那轮常驻扫描。
           不调它的话，新建出来的键会先以页面自己的旧材质旧形状显示，
           过半秒被扫描接住才「一闪」变成金属键 —— 也就是「先旧后新、不流畅」的根源。 */
        applyBondsNow: function (bondsOnly) {
            if (!state.attached || !state.scene) return null;
            return state.enabled ? scanAndApply(!!bondsOnly) : applyClassicMetalBonds();
        },
        /* 页面开/关「均摊法（实心切片）」时调一次：把裁剪面同步到磨砂材质，
           并把压在切面上的接头辉光摘掉（否则截面上一堆小白点）。 */
        syncClipping: function () { return syncClipping(); },
        /* 转换动画期间暂停常驻扫描：动画里的临时键/原子的 opacity 由页面每帧自己写，
           扫描那一下（applyClassicMetalBonds 走 preserveTransparent=false）会把
           transparent/opacity 重置成不透明，画面上就是键闪一下。动画结束记得传 false。 */
        pauseScan: function (on) { state.scanPaused = !!on; },
        baseOf: function (mesh) {
            var entry = mesh ? state.entries.get(mesh) : null;
            return (entry && entry.base) ? entry.base : null;
        },
        /* 诊断口：接头辉光一共几个、此刻真正会被画出来的有几个。
           组装/缩放动画里页面把原子、键的 visible 关掉时，这里应当同步掉到 0 ——
           掉不下去就说明辉光脱离了 mesh，正是「原子没了、斑点还在」的成因。 */
        glowStats: function () {
            var total = 0, visible = 0, detached = 0, maxOffset = 0;
            var meshHidden = 0, groupHidden = 0, sample = '';
            state.fuseEntries.forEach(function (entry) {
                (entry.fuseSprites || []).forEach(function (sprite) {
                    total++;
                    var node = sprite, shown = true, blocker = null;
                    while (node) {
                        if (node.visible === false) { shown = false; blocker = node; break; }
                        node = node.parent;
                    }
                    if (shown) visible++;
                    else if (blocker) {
                        if (blocker === sprite.parent) meshHidden++; else groupHidden++;
                        if (!sample) sample = (blocker.type || '?') + '|' + (blocker.name || '') + '|' + (blocker.isMesh ? 'mesh' : (blocker.isGroup ? 'group' : 'other'));
                    }
                    var mesh = sprite.userData.fuseMesh;
                    if (!mesh || !mesh.parent) detached++;
                    if (mesh && sprite.userData.fuseWorld && state.THREE) {
                        sprite.updateWorldMatrix(true, false);
                        var wp = sprite.getWorldPosition(new state.THREE.Vector3());
                        var d = wp.distanceTo(sprite.userData.fuseWorld);
                        if (d > maxOffset) maxOffset = d;
                    }
                });
            });
            return { total: total, visible: visible, detached: detached, offset: Math.round(maxOffset * 1000) / 1000,
                meshHidden: meshHidden, groupHidden: groupHidden, sample: sample };
        },
        stats: function () {
            var frost = 0;
            var bonds = 0;
            var edges = 0;
            if (state.scene) {
                state.scene.traverse(function (object) {
                    var entry = state.entries.get(object);
                    if (entry && object.material === entry.frost) {
                        if (entry.kind === 'bond') bonds++;
                        else frost++;
                    }
                });
            }
            state.boundaries.forEach(function (boundary) {
                edges += boundary.rods.length;
            });
            return { enabled: state.enabled, frostMeshes: frost, frostBonds: bonds, frostEdges: edges };
        }
    };
    window.CrystalFrostAtoms = api;

    // 模块脚本排在页面脚本之后加载，这里 THREE 已经就绪：立刻把经典补丁挂到
    // prototype 上，让之后任何新建的材质第一次编译就带上它（caf2 也是这么做的）。
    if (window.THREE && needsLegacyGain(window.THREE)) installClassicPhongPatch(window.THREE);

    function autoAttach() {
        try {
            var pageScene = (typeof scene !== 'undefined' && scene) ? scene :
                (typeof stage !== 'undefined' && stage ? stage.scene : null);
            var pageRenderer = (typeof renderer !== 'undefined' && renderer) ? renderer :
                (typeof stage !== 'undefined' && stage ? stage.renderer : null);
            if (pageScene && pageRenderer) {
                attach({ scene: pageScene, renderer: pageRenderer, THREE: window.THREE });
            }
        } catch (error) {
            // The module-based crystal lab passes scene/renderer explicitly.
        }
    }
    /* 尽早挂上，别等 load：load 要等图片/字体全部就位，往往比主脚本晚几百毫秒，
       画面会先用旧的平淡材质渲染出来，过 0.5 秒才「一闪」变成立体 / 金属质感。
       经典 Phong 补丁挂在 prototype 上，之后新建的材质首次编译就自带补丁，
       所以越早 attach 越好；DOMContentLoaded 时页面主脚本已跑完，scene/renderer 通常已就绪。
       万一某页是在 load 里才初始化，下面仍保留 load 兜底（attach 自身幂等）。 */
    var autoAttached = false;
    function tryAutoAttach() {
        if (autoAttached || state.attached) return;
        autoAttach();
        if (state.attached) autoAttached = true;
    }
    /* 同步先试一次：本脚本排在页面主脚本之后，此时 scene / renderer 已经建好，
       而页面末尾调用的 animate() 只是注册了 rAF —— 首帧还没画出来。
       趁这个空档同步挂上，材质补丁和金属键在第一帧之前就已经就位，
       不会再出现「打开瞬间是旧材质、过半秒才一闪」。
       万一某页把本脚本放在主脚本之前（那时 scene 还没有），下面 DCL / load 继续兜底。 */
    tryAutoAttach();
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', tryAutoAttach, { once: true });
        window.addEventListener('load', tryAutoAttach, { once: true });
    } else {
        setTimeout(tryAutoAttach, 0);
    }
    // 拖原子大小滑杆时立刻重算键长（不等 650ms 那轮扫描），手感才跟得上。
    // 用冒泡阶段：等页面自己的 handler 把原子改完，再同步重算，零延迟。
    ['input', 'change'].forEach(function (eventType) {
        document.addEventListener(eventType, function (event) {
            var target = event.target;
            if (target && target.tagName === 'INPUT' && target.type === 'range') scheduleReflow();
        }, false);
    });
})();
