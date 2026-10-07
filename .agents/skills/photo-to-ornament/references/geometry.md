# 几何执行与已验证参数

`build_quad_uv.py`要求地图目录包含`03_material_mask.png`和`04_height.png`，共享画布。输出`ding_quad_uv.npz`为兼容现有数据格式的固定文件名，实际可表示其他纹样；含vertices、quads、uv、face_kind（0正面/1侧壁/2底面）、face_component、face_chart、seams。输入PNG不改写。

该脚本是轮廓约束三角化→细分为密集四边面→正面高度采样→恒定Z侧壁环→底面→UV。不会把整件青铜器的背面或不可见纹样自动测出来；只处理已确认的独立平面浮雕区域。

参数均是制作设置，真实尺寸按任务提供。已测的鼎配置：width-m=1，base-m=0.01285，relief-m=0.02215，area=6e-7 m²，wall-layers=16，view-distance-m=5，shoulder-m=0.004。然后从Before数组执行factor=0.5，得到起伏0.011075 m、总高0.023925 m。

照片高度草稿的旧采样处理为median-size=5、height-sigma=2，并修补材料内部错误黑值；它已经包含在认可的Before模型中。恢复细节时不重新采样，也不再滤波；直接使用Before数组。新照片可在图像质量允许时使用median-size=1、height-sigma=0；不得因此改写已确认模型。height的0.14背景底值、0.97上限和有效灰度范围属于本类生成图的约定，其他编码需要适配。

从图重建（只生成几何数组，尚未导入Blender）：

```powershell
python .agents/skills/photo-to-ornament/scripts/build_quad_uv.py --maps cases/ding/maps --out runs/ding/rebuilt_before --width-m 1 --base-m 0.01285 --relief-m 0.02215 --wall-layers 16 --area 6e-7
```

从已确认数组调整强度：

```powershell
python .agents/skills/photo-to-ornament/scripts/scale_relief.py --source cases/ding/mesh_before --out runs/ding/mesh --factor 0.5
```

Blender原生生成、渲染、FBX导出及重导入检查：

```powershell
& '你的Blender.exe路径' -b --python .agents/skills/photo-to-ornament/scripts/build_scene.py -- --source runs/ding/mesh --out runs/ding/result
```

厚度横向16层（17个高度位置）；每个环带UV独立，长环带另切纵向缝。正/底面平面投影，侧壁弧长×高度展平，统一打包0–1，4096参考分辨率下4 px间隔。主表面坡面仍有平面UV投影伸缩，需要更高要求时另作优化；不能宣称它是无拉伸UV。

本例约296万四边面。四边面由高模采样构造，部分非规则顶点价数；适合静态浮雕高模和后续烘焙，不代替动画低模拓扑。密度与最小细节尺度有关，换尺寸/画布需要检查，不能只看面数。

`build_scene.py`的Smooth Shading是沿用Before的显示法线方式，不改变顶点坐标；用户撤销的是新增的几何平滑/高度分层。本包没有6级平台处理脚本。
