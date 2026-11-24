/* hifi-compat.js —— 老页面代码兼容垫片（必须紧跟 three170-bundle.js 之后加载）
 *
 * 背景：页面原本用 MeshPhongMaterial，改造后统一换成 MeshPhysicalMaterial。
 * 但有些页面（cu / po 等）的动画代码会直接写 mat.specular.copy(...)、mat.shininess = 40，
 * 而 Physical 材质没有这两个属性，会当场抛 TypeError。
 *
 * 这里给 MeshPhysicalMaterial 原型挂上惰性的 specular / shininess / reflectivity，
 * 让老代码读写都不报错（specular 不参与渲染，仅保命）。
 */
(function () {
    var T = window.THREE;
    if (!T || !T.MeshPhysicalMaterial) return;
    var P = T.MeshPhysicalMaterial;

    function lazyProp(name, make) {
        var key = '__compat_' + name;
        Object.defineProperty(P.prototype, name, {
            configurable: true,
            get: function () {
                if (this[key] === undefined) this[key] = make();
                return this[key];
            },
            set: function (v) { this[key] = v; }
        });
    }

    lazyProp('specular', function () { return new T.Color(0x222222); });
    lazyProp('shininess', function () { return 30; });
    lazyProp('reflectivity', function () { return 1; });
})();
