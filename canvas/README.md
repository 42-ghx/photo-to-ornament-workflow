# 纹样节点工作台

画板已支持节点内预览、参数编辑、真实任务进度、历史回退、红色密度绘制、模型 UV 读取和导出。原照片、认可地图和已生成的 Blender 资料作为初始素材保留。

## 启动

在仓库根目录运行：

```sh
.venv/bin/python canvas/server.py --port 8001
```

服务默认仅在本机的 8001 端口监听。使用运行该服务的电脑上的浏览器打开对应端口；云环境设置聊天不提供网页预览入口。直接双击 HTML 可以查看界面提示，执行任务需要上述服务。Python 依赖沿用 `setup/requirements.txt`；Blender 使用 `.tools/blender-5.2.2-linux-x64/blender`，后台显示依赖自动从 `.tools/xvfb/` 加载。

## 三条工作线

- **图片管线**：照片、抠图、去光照、材料遮罩、连续高度；每个节点可编辑提示词、替换素材、查看和下载图片。AI 参数作为 Codex 生成指引；工具未公开原生种子、强度或具体模型版本选择接口，不能保证 AI 像本地算法一样按 seed 重复。
- **UV / 密度纹样**：导入已有 UV 的 OBJ，或上传白色允许、黑色禁止的 UV 遮罩。`CylinderPipe.obj` 已预载并提取 UV。添加「纹样密度引导」，连接参考图片或 UV 遮罩后涂红，再接到纹样节点。整体密度控制全部区域，红区倍率控制局部加密；可以擦除、撤销、重做、清空并保存版本。连接密度节点后，两处滑块编辑同一组密度参数。本地排布使用已有纹样重复排列并严格裁切；Codex 节点用于艺术生成。
- **Blender 几何**：独立执行，不随图片节点自动运行。可从认可 Before 数组调整浮雕，也可明确选择从连接的高度图与材料遮罩建模；后者需设置真实尺寸和采样面积。它生成独立平面浮雕，不会自动把新几何包裹到导入的筒形模型上。UV 线输出可供模型使用的图像。

上传模型目前支持 OBJ，必须包含面对应的 UV（`vt`）。不会猜测缺失 UV，也不会重排 UV；超出 0–1 的部分只裁切并报告。纹样与生成图严格限制在白色遮罩范围内；透明遮罩外部也视为禁止区域。

## Codex 图片生成如何执行

选择 Codex 图片节点并点击「重新生成」，画板会保存真实请求并显示「等待 Codex 图像工具」。点击任务中的「复制对话执行请求」，在当前 Codex 聊天中发送。Codex 执行后结果自动回填到节点。

**网页无法直接调用聊天图像工具，因此目前仍需要上述聊天执行步骤。** 没有常驻代理，不会用计时器模拟完成状态。需要无人值守一键生成时，仍需可由服务调用的图片 API。具体桥接方法见 [CODEX_GENERATION.md](CODEX_GENERATION.md)。

## 编辑、历史与导出

- 拖动节点标题调整位置，拖动空白平移，滚轮缩放。三条工作线可分别聚焦。
- 节点标题、提示词、参数和上游输入都可编辑。支持通过下拉框或端口连接，并阻止循环依赖。
- 每次生成保存独立结果和参数。初始资料、替换图片及绘制遮罩也有版本；回退不会删除后续版本。上游改变时旧结果需要重新生成。
- 图片可单独下载；节点右下角导出该节点及上游资料；「导出全部」下载所有节点、图片、模型、版本和项目描述的 ZIP。
- 「导出项目」仅保存节点 JSON；将 ZIP 解压回相同仓库相对路径后，可导入其中的项目 JSON。项目 JSON 本身不包含图像二进制数据。

项目状态和新结果保存在 Git 忽略的 `runs/canvas-studio/`。迁移时应携带整个目录，以及节点引用的 `cases/` 与历史 `runs/ding-blender-5.2.2-validation/`。画板没有自动提交或推送 GitHub。

## 开发与检查

`studio.json` 是首次启动的默认项目；已有工作区使用 `runs/canvas-studio/project.json`。前端为 `template.html`、`studio.js` 和 `studio.css`，后端为 `server.py` 与 `uv_engine.py`。

```sh
python3 setup/build_node_canvas.py
.venv/bin/python -m unittest discover -s canvas/tests -v
node --check canvas/studio.js
python3 setup/verify_manifest.py
```

修改受清单管理的文件后，应更新 `MANIFEST.json` 的字节数和 SHA256。原静态流程的数据与 JSON Canvas 格式仍保留在 `workflow.json` 和 `photo-to-ornament.canvas`；[之前的云端复现报告](cloud-validation.md)可继续查阅。
