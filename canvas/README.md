# 纹样节点工作台

默认显示一张案例原照片与四步：**补全与透明抠图 → 柔光参考 → 主纹剪影 → 连续高度**。案例结果清楚标记为已有素材。新任务替换原照片后，从上游逐步生成并确认。

## 启动

需要 Python 3.11+、NumPy 和 Pillow。先在所选 Python 环境执行 `python -m pip install -r setup/requirements-studio.txt`。Windows 双击仓库根目录的 `launch_studio.cmd`；macOS / Linux 运行 `sh launch_studio.sh`。启动器复用 `.venv-studio`、`.venv` 或当前 Python，不自动安装软件。可通过 `ORNAMENT_PYTHON` 指定解释器。

命令行也可执行 `python setup/start_studio.py --port 8001`。浏览器访问 `http://127.0.0.1:8001/`，仅本机可连接。`--check` 检查依赖，`--no-browser` 禁止自动打开浏览器。

## 图片生成

在节点编辑提示词、选择上游输入，然后点击「重新生成」。网页保存请求并显示「等待 Codex」；将任务中的执行请求交给当前聊天，实际图像工具生成后回填节点。独立网页没有图像模型 API，也不会自动使用账号或密钥。接口说明见 [Codex 图像桥接](CODEX_GENERATION.md)。

补全与照片高度属于艺术重建。主纹剪影白色表示装饰实体；刻线、眼眶、眼部凹陷仍有实体支撑。高度和剪影必须保持同一画布与布局，刻线深浅体现在连续灰度中。

普通四步结果回填保留 PNG 原字节、尺寸与位深；连接材料剪影不会自动裁切或转换高度图。只有连接明确的 UV 遮罩节点才执行 UV 裁切；当前该扩展只处理 8 位生成图，高位深输入会明确拒绝。

## 按需扩展

- **UV 遮罩匹配**：提供目标模型或明确提出 UV 要求后，通过「添加节点」选择 OBJ UV 读取或导入遮罩。OBJ 必须带已有 UV。遮罩外部（包括透明部分）禁止输出，超出 0–1 的 UV 被裁切并报告。
- **局部纹样铺排**：用户明确要求重复铺排时，添加本地纹样铺排及可选密度引导节点。这是确定性本地图像排布；AI 图片生成仍由聊天工具完成。
- **Blender 几何**：仅在明确建模时添加，连接当前高度图和材料遮罩，填写目标宽度、底厚、浮雕高度及面采样面积。两张 PNG 必须同尺寸。所需 Python 包为 `scipy scikit-image shapely triangle trimesh`，另需 Blender；可设置 `ORNAMENT_BLENDER` 指向其可执行文件。Linux 无显示环境还需 `xvfb-run`。几何节点从当前地图构建，不调用旧模型。详细说明见 [完整工作台参考](../references/workbench.md)。

## 版本与迁移

节点参数和上下游连接可编辑。生成或替换素材会保留独立历史版本，回退切换当前结果。变更上游后，依赖节点会标记过期。

「导出项目」只下载节点 JSON；「导出全部」下载包含项目与引用素材的 ZIP。后者适合迁移素材，导入 JSON 前仍需将 ZIP 中素材按原相对路径放回 skill 目录。服务状态位于 `runs/canvas-studio/`，初始案例定义位于 `canvas/studio.json`。迁移完整工作区时携带整个 `runs/canvas-studio/`，不要只复制 HTML。

## 开发检查

后端为 `server.py` 与 `uv_engine.py`；界面为 `index.html`、`studio.js` 和 `studio.css`，`template.html` 保留模板。静态流程见 `workflow.json`、`photo-to-ornament.canvas` 与 `overview.svg`。

在 skill 根目录运行：

```sh
python setup/start_studio.py --check
python -m unittest discover -s canvas/tests -v
node --check canvas/studio.js
```

几何依赖未安装时，对应采样测试会明确跳过。测试和界面启动成功不等于已执行当前照片生成或实际 Blender 导出。
