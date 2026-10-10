# 可选浮雕几何

仅在要求建模时使用。内置 `build_quad_uv.py`、`contour_base.py`、`scale_relief.py`、`build_scene.py`，依赖见 `scripts/requirements-geometry.txt`。下列命令从技能根目录运行，其他位置使用绝对路径。

输入为同画布的 `03_material_mask.png` 和 `04_height.png`，至少 2×2。白色表示实体，透明像素不产生材料；支持真实 16 位灰度高度。输出固定名 `ding_quad_uv.npz` 是兼容格式，不表示只能处理鼎。

新地图指定 `--height-encoding linear --median-size 1 --height-sigma 0`，直接采样 0–1 高度，避免套用旧灰度处理。宽度、底厚、起伏、密度、侧壁层数按本次需求设置。以下仅为宽 10 cm 的制作示例：

```sh
python scripts/build_quad_uv.py --maps /path/to/maps --out /path/to/new-mesh --width-m 0.10 --base-m 0.002 --relief-m 0.004 --area 0.000002 --wall-layers 8 --height-encoding linear --median-size 1 --height-sigma 0 --min-component-px 1
```

流程为轮廓三角化、细分四边面、正面高度采样、恒定 Z 侧壁环、底面和 UV。最小部件过滤可能删除小孤岛，须按图判断 `--min-component-px`，保护眼睛和细连接；密度依据最小细节与尺寸。

正面/底面与侧壁分区 UV，侧壁按高度环分带并设纵缝。平面 UV 投影可能伸缩；密集高模不等于动画低模拓扑。脚本生成材料范围内的封闭底面；开放背面须另行改造和验收。

从认可数组调整起伏：

```sh
python scripts/scale_relief.py --source /path/to/accepted-mesh --out /path/to/new-scaled-mesh --factor 0.5
```

只改正面相对支撑面 Z：`base + factor * (old_z - base)`；保留 XY、底面、侧壁、索引、接缝和 UV。从认可源计算，不累积减半。

Blender 后台导出及重导入验证：

```sh
blender --factory-startup -b --python scripts/build_scene.py -- --source /path/to/new-mesh --out /path/to/new-result
```

脚本只在独立后台 Blender 清理该进程场景，输出 `.blend`、FBX、视图、UV SVG 和 `fbx_uv_checks.json`。检查水密性/预期边界、法线、厚度、侧壁、UV 及 FBX 重导入坐标与面数。后台生成和实时 MCP 导入分别报告。

输出使用新版本目录，脚本拒绝同名已有成果。PNG 输入只读。旧鼎 `accepted_case.json` 仅为历史资料；精确恢复需另行提供认可 Before 数组，轻量 Skill 不含大型历史模型。

旧案例重建为 legacy 编码、median=5、sigma=2、width=1 m、base=0.01285 m、relief=0.02215 m、area=6e-7、wall-layers=16，再 factor=0.5。这是历史设置，不能套作新任务尺寸；从图重建不保证与原 Before 完全一致。
