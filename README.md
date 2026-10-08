# 纹样节点工作台 · 照片 / UV / Blender

一个可编辑的节点画板，用于照片纹样制作、UV 范围内纹样生成和独立浮雕建模。效果图、参数、任务状态和历史版本都保存在节点中；图片、UV 和 Blender 分为三条工作线。

**[下载完整项目 ZIP（约 1.57 GB）](downloads/photo-to-ornament-workflow-full.zip) · [下载与启动说明](downloads/README.md) · [SHA256](downloads/photo-to-ornament-workflow-full.zip.sha256)**

本分支为 `download-node-studio-20261008`。完整包包含 13 个节点、15 个历史版本、上传的 `CylinderPipe.obj`、效果图，以及 Blender / FBX 产物。登录有权访问此私有仓库的 GitHub 账号，打开 ZIP 文件页，点击 **Download raw file** 下载真实文件。

## 节点工作台

![节点工作台：红色密度引导、UV 纹样预览、参数与历史版本](docs/images/node-studio.png)

在节点内调整提示词、密度、分辨率和输入连接，查看生成结果及历史版本。红色遮罩由画笔直接绘制，整体密度滑块控制全部区域，局部倍率控制红色区域的纹样密度。

## 已完成的效果图

| 鼎案例 · 浮雕正面 | 鼎案例 · 侧视厚度 |
| --- | --- |
| ![鼎案例浮雕正面](docs/images/ding-front.png) | ![鼎案例侧视厚度](docs/images/ding-thickness.png) |

| CylinderPipe · UV 范围内纹样 | 鼎案例 · UV 棋盘格 |
| --- | --- |
| ![Codex 生成的 CylinderPipe UV 纹样图](docs/images/uv-pattern.png) | ![鼎案例 UV 棋盘格预览](docs/images/ding-uv-checker.png) |

UV 纹样图由 Codex 图像工具生成，并按导入模型的白色 UV 遮罩裁切，是二维图像输出。鼎案例图片来自 Blender 5.2.2 后台渲染：保留 Before 原细节，只将正面浮雕起伏减半，底面、侧壁和 UV 保持不变。

## 三条工作线

| 工作线 | 输入与可调内容 | 输出 |
| --- | --- | --- |
| 图片管线 | 照片、参考图、提示词、抠图、去光照、材料遮罩、连续高度 | 节点内预览、独立图片和生成版本 |
| UV / 密度纹样 | 含 UV 的 OBJ 或白色允许区域遮罩、红色密度引导、整体密度与局部倍率 | UV 遮罩、本地纹样排布、Codex 纹样图 |
| Blender 几何 | 已认可 Before 数组，或明确选择的材料遮罩与高度图、尺寸、厚度和浮雕系数 | 高模数组、FBX、可编辑 `.blend`、渲染预览与回读检查 |

- 拖动节点、平移和缩放画板，添加节点、编辑标题与参数、连接上游输入。
- 绘制红色密度遮罩，支持画笔、橡皮、撤销、重做和清空。
- 每次生成保留独立版本，可回退到初始资料、上传版本或生成版本；上游改变后提示旧结果需要重新生成。
- 画板显示实际任务状态与进度；Blender 单独执行。
- 支持单图下载、节点及上游资料打包、全部节点资料打包，以及项目 JSON 导入 / 导出。

## 在本机启动

1. 下载完整 ZIP，完整解压到可写目录，进入其中的 `photo-to-ornament-workflow` 文件夹。
2. 安装 **Python 3.12**。Windows 双击 `start_workbench.cmd`；Linux / macOS 执行 `bash start_workbench.sh`。首次启动会创建虚拟环境并安装依赖。
3. 服务启动后，在运行服务的同一台电脑上，用浏览器打开 `http://localhost:8001/`。详细说明见包内 `PACKAGE_START.md`。

该地址用于本机运行的服务。云环境设置聊天不提供网页预览入口。已保存的效果图和模型文件可在完整包中直接查看；运行新 Blender 任务还需安装 Blender，并让 `blender` 命令位于 PATH。仓库验证使用 Blender **5.2.2**。

## 图片生成与模型范围

Codex 图片节点提交请求后显示“等待 Codex 图像工具”。将任务中的对话执行请求发送给当前 Codex 聊天，由真实图像工具生成并回填节点。网页没有常驻 Codex 代理，不能自行调用聊天工具。具体步骤见 [Codex 图片生成说明](canvas/CODEX_GENERATION.md)。

本地纹样排布可直接在网页执行，使用已有纹样重复排列并裁切到白色遮罩。AI 节点中的 seed、强度等参数作为生成指引；当前聊天工具不提供原生种子、强度或指定模型版本的选择接口。

模型导入目前支持含 `vt` 和面 UV 索引的 **OBJ**，读取原有 UV；超出 0–1 的部分会裁切并报告。Blender 线生成独立浮雕；将纹样图应用或包裹到导入的筒形模型上需要后续处理。

迁移时保留完整的 `runs/canvas-studio/` 及包内相对路径，它保存项目、上传资料、绘制遮罩和历史结果。项目 JSON 本身不含图片或模型二进制数据。软件安装本体、虚拟环境、Git 历史及账号凭证不在包内。

## 验证与资料

| 已执行的检查 | 结果 |
| --- | --- |
| 节点服务、UV 与密度测试 | 25 项通过 |
| 完整 ZIP 逐文件校验 | 170 个文件；SHA256 校验通过 |
| 解压后启动与资料恢复 | 13 个节点、15 个历史版本恢复；模型与预览读取通过 |
| GitHub 完整包回下载 | 文件大小与 SHA256 与本地一致 |
| 鼎案例底面 / 侧壁 / UV 保持检查 | 通过 |
| FBX 回读坐标 / 尺寸 / UV 最大误差 | 0 / 0 / 0 |

[节点工作台使用说明](canvas/README.md) · [鼎案例验证记录](canvas/cloud-validation.md) · [原工作流](WORKFLOW_SUMMARY.md) · [跨电脑迁移](MIGRATION.md) · [云环境准备](CLOUD_SETUP.md) · [通用 .canvas 文件](canvas/photo-to-ornament.canvas)

开发者可克隆本分支并拉取 Git LFS 文件：

```sh
git clone --branch download-node-studio-20261008 https://github.com/42-ghx/photo-to-ornament-workflow.git
cd photo-to-ornament-workflow
git lfs pull
python setup/verify_manifest.py
```

GitHub 普通源码 ZIP 可能包含 LFS 指针。要恢复已生成的画板资料，使用上方完整项目 ZIP；当前运行状态位于完整包的 `runs/` 目录。
