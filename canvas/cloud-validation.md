# 鼎案例云端生成资料

当前实例使用 Blender 5.2.2 LTS（构建 d13f752e3b9c）完成鼎案例，保持认可状态 ding_detail_half_03：Before 原细节、正面浮雕起伏减半、底厚不变。原照片、抠图、地图和原认可资料继续保留在对应节点；本次没有重新生成地图。

## 预览与模型

- [正面](../runs/ding-blender-5.2.2-validation/result/01_form.png)
- [侧视厚度](../runs/ding-blender-5.2.2-validation/result/02_thickness.png)
- [底面](../runs/ding-blender-5.2.2-validation/result/03_bottom.png)
- [侧壁循环边](../runs/ding-blender-5.2.2-validation/result/04_side_loops.png)
- [UV 棋盘格](../runs/ding-blender-5.2.2-validation/result/05_uv_checker.png)
- [UV 布局](../runs/ding-blender-5.2.2-validation/result/UV_layout_4096.svg)
- [FBX 模型](../runs/ding-blender-5.2.2-validation/result/ornament_highpoly.fbx)
- [Blender 工程](../runs/ding-blender-5.2.2-validation/result/ornament_highpoly.blend)
- [高模数组](../runs/ding-blender-5.2.2-validation/mesh/ding_quad_uv.npz)

## 实际验证结果

| 检查 | 结果 |
| --- | --- |
| 顶点 / 四边面 | 2,958,056 / 2,958,074 |
| 基础厚度 | 约 12.85 mm |
| 浮雕幅度 | 约 11.075 mm（系数 0.5） |
| 总高 | 约 23.925 mm |
| 底面、侧壁、XY、面索引、UV、接缝 | 与 Before 数组完全一致 |
| 正面缩放最大误差 | 9.313225746154785e-10 m |
| FBX 回读坐标 / 尺寸 / UV 最大误差 | 0 / 0 / 0 |
| Blender 生成与回读耗时 | 228.22 s |

[浮雕检查](../runs/ding-blender-5.2.2-validation/mesh/scale_checks.json) · [逐项保持检查](../runs/ding-blender-5.2.2-validation/array_preservation_checks.json) · [FBX 回读检查](../runs/ding-blender-5.2.2-validation/result/fbx_uv_checks.json)

新结果在 Git 忽略的 `runs/ding-blender-5.2.2-validation/`，画板链接不会自动将这些文件提交到 GitHub。下载或迁移画板时请携带完整仓库及该目录，并保持相对位置。画板关联云端输出，不代表已连接桌面 Blender MCP。
