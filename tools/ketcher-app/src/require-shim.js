// Ketcher 的可选 Raphael 渲染分支在浏览器中直接调用 require("raphael")。
// 浏览器 ESM 没有 require，这里提供最小映射，让该分支拿到真正的 Raphael。
import Raphael from 'raphael';

if (typeof window !== 'undefined') {
  window.require = function (name) {
    return name === 'raphael' ? Raphael : undefined;
  };
}
