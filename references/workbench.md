# 纹样节点工作台与条件扩展

本 skill 根目录同时是工作台项目目录。保留 `canvas/`、`scripts/`、`cases/taotie/` 与 `setup/` 相对位置。运行 `python setup/start_studio.py`，访问 `http://127.0.0.1:8001/`。Python 3.11+ 与基础依赖由用户已有环境提供；安装命令为 `python -m pip install -r setup/requirements-studio.txt`。

工作台提供节点连接、提示词、参数编辑、素材上传、任务状态、独立历史版本、回退和 ZIP 导出。默认流程只有原照片和四步图像，全部示例图片属于随包案例。

图像任务由真实聊天图像工具执行。读取 `GET /api/codex/requests`，查看实际参考图，将生成结果副本放入 `runs/canvas-studio/uploads/`，然后回填完成接口。具体请求格式见 [桥接说明](../canvas/CODEX_GENERATION.md)。

## UV 和局部铺排

只有当前任务提供模型或明确要求 UV 匹配时才添加 UV 节点。已有 UV 的 OBJ 可以提取白色允许区域；缺少 UV 不会自动展开。局部重复铺排需单独明确要求；通过密度引导绘制局部增加重复的范围，并连接到本地纹样节点。两者均不需要 Blender。

## 当前地图生成几何

几何属于单独扩展。添加 Blender 节点，连接同尺寸 PNG 的高度图 (`image`) 和白色材料遮罩 (`mask`)。参数 `width_m`、`base_m`、`relief_m`、`area` 必须按本次任务填写。`factor` 默认 1、`wall_layers` 默认 16；不自动填写旧案例尺寸，也不回退历史网格。

所选 Python 环境另外需要：

```sh
python -m pip install scipy scikit-image shapely triangle trimesh
```

另外安装 Blender，必要时设置 `ORNAMENT_BLENDER`。启动器不自动安装 Blender 或系统软件。Linux 无图形显示环境的渲染使用 `xvfb-run`。

几何执行依次调用根目录的 `scripts/build_quad_uv.py`、`scripts/scale_relief.py`、`scripts/build_scene.py`。采样使用 `--height-encoding linear --median-size 1 --height-sigma 0` 保留作者连续高度。脚本内部保留 `ding_quad_uv.npz` 等兼容输出文件名，文件内容来自当前任务地图。

每个任务输出到新的 `runs/canvas-studio/nodes/<node>/<job>/`，保留地图副本、网格、校验与渲染。`scale_checks.json` 和 `fbx_uv_checks.json` 均通过才标记成功。完整 Blender 链需要安装依赖后在目标环境实际验证。

更多界面、版本和迁移说明见 [工作台说明](../canvas/README.md)。
