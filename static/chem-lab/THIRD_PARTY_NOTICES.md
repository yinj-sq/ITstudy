# 化学仿真第三方组件声明

## Ketcher 3.18.0（含 Indigo standalone WASM）

- 来源：https://github.com/epam/ketcher
- 许可：Apache License 2.0（Copyright 2021 EPAM Systems）
- 文件：`ketcher/`（构建产物，含 `assets/index-*.js`、`ocl-resources.json`）
- 许可见 `ketcher/LICENSES/KETCHER-APACHE-2.0.txt`
- 说明：离线 2D 结构/反应式编辑器，WASM 版 Indigo 随包本地运行。

## 3Dmol.js 2.5.5

- 来源：https://github.com/3dmol/3Dmol.js
- 许可：BSD-3-Clause（Copyright (c) 2014, University of Pittsburgh and contributors）
- 文件：`vendor/3dmol/3Dmol-min.js`
- 许可见 `vendor/3dmol/LICENSE`、`vendor/3dmol/3Dmol-min.js.LICENSE.txt`

## OpenChemLib 9.26.0

- 来源：https://github.com/cheminfo/openchemlib-js
- 许可：BSD-3-Clause（Copyright (c) 2015-2017, cheminfo）
- 用途：在浏览器本地生成 3D 构象；构建进 Ketcher 编辑器包，资源文件为
  `ketcher/ocl-resources.json`
- 许可见 `ketcher/LICENSES/OPENCHEMLIB-BSD-3.txt`

## Molstar 5.13.1

- 来源：https://www.npmjs.com/package/molstar
- 许可：MIT（Copyright (c) 2017 - now, Mol* contributors）
- 文件：`vendor/molstar/molstar.js`、`vendor/molstar/molstar.css`
- 许可见 `vendor/molstar/LICENSE`

## molview（54yyyu/molview）

- 来源：https://github.com/54yyyu/molview
- 许可：MIT（Copyright (c) 2025 MolView Contributors）
- 用途：仅参考其 Molstar 初始化与结构加载逻辑，未整体复制其 Jupyter 模板
- 许可见 `LICENSE-MOLVIEW`

## 可视化化学

- 来源：https://xunweichem.cn/
- 用途：经用户确认作为免费教学内容整合；仅保留模型页面与画布内容，
  去除原站导航、登录/VIP 逻辑与署名外壳。

## 分子结构数据

- 小分子：PubChem PUG REST（构建期固化，运行时离线）
- 蛋白质：RCSB PDB 公共数据
- 晶体：自建 CIF / 公开晶体数据
- 每个文件的来源与 SHA256 记录在 `molecules/catalog.json`
