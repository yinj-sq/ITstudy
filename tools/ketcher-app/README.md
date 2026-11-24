# ITstudy Ketcher 离线绘制应用

化学仿真工作台左侧的 2D 编辑器构建源码。产物直接写入
`static/chem-lab/ketcher/`，随安装包分发；本目录不进入安装包/镜像。

## 构建

需 Node.js ≥ 24.14（`ketcher-react` 的 engines 要求）。

```bash
cd tools/ketcher-app
npm install
npm run build      # vite build + 复制许可证
```

构建后产物：

- `static/chem-lab/ketcher/index.html`
- `static/chem-lab/ketcher/assets/index-*.js`（约 29 MB，gzip 后约 8.5 MB）
- `static/chem-lab/ketcher/assets/conformer.worker-*.js`（3D 构象 Worker，
  OpenChemLib 资源已内联，无运行时 fetch）
- `static/chem-lab/ketcher/LICENSES/`（Ketcher/Indigo Apache-2.0、OpenChemLib
  BSD-3、Raphael MIT、React MIT）

发布前在项目根目录运行：

```bash
venv/Scripts/python.exe tools/precompress_static.py
venv/Scripts/python.exe tools/verify_chem_lab_artifacts.py
```

## 关键实现

- `src/main.jsx`：`Editor` + `StandaloneStructServiceProvider`；监听
  `ketcher.changeEvent`，防抖导出 molfile/SMILES，把 3D 构象生成交给
  `conformer.worker.js`（独立线程，避免阻塞编辑与 3D 工具栏），完成后
  `postMessage` 给宿主页。
- `src/i18n.js`：Ketcher 上游英文界面的运行期中文映射（工具栏 title、右键
  菜单、打开/保存、设置、结构检查等），MutationObserver 补扫动态弹层。
- `src/require-shim.js`：Ketcher 的可选 Raphael 渲染分支在浏览器 ESM 中
  直接调用 `require("raphael")`；这里提供最小映射，避免启动崩溃。
- 芳香 SMILES（如 `c1ccccc1`）先经 OpenChemLib 规范化为 2D molfile 再载入
  Ketcher，规避 Indigo 自动识别按单键环解析的问题。
- 宿主页协议（`static/js/chem_lab.js`）：
  - 父 → 子：`chem-sketch-load`、`chem-sketch-clear`、`chem-sketch-sync`、
    `chem-sketch-ping`
  - 子 → 父：`chem-sketch-ready`、`chem-sketch-change`、`chem-sketch-3d`、
    `chem-sketch-3d-empty`、`chem-sketch-3d-error`、`chem-sketch-error`
- 3D 生成上限 160 个原子；反应式/聚合物/超限结构只保留 2D，并提示原因。
