# 可选局部磨损

`assets/Edge Damage Modifer.blend` 为原包节点资产副本，只在要求磨损时加载，不改源库。`scripts/contour_damage.py` 在副本中保留噪声、映射和法线位移，绕开体素重构、全体模糊与布尔，保护拓扑。

先建立 POINT 域 `alpha_edge_weight` 和 `wear_z` 权重，将损伤限于用户指定区域，保护刻线、眼部和连接。没有属性和实际坐标变化，不能声称磨损生效。

在 Blender 加载模块后调用 `make_group(library_path)`、`attach(obj, group)`。源组名 `Mesh Edge Damage` 依赖具体节点名称，换版本先核对。默认 0.0009 m 噪声来自旧 1 m 案例，按当前尺寸调整。

保留干净版和磨损版，检查坐标、法线、边界、循环边和 UV。FBX 需烘焙几何，节点保留在 `.blend`；旧鼎验收状态未含新增磨损，不用于验证新结果。
