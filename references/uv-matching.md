# UV 遮罩匹配

本次用户提供模型或明确要求后执行。抽取器支持含 `v`、`vt` 与面角 UV 索引的 OBJ。缺 UV、错误索引或非 OBJ 输入时明确报告限制，不自动展开。

```sh
python scripts/extract_uv_mask.py --obj /path/to/target.obj --out /path/to/new-uv-version --resolution 1024
```

输出 `mask.png`、`uv_layout.png`、`report.json`，支持 256–2048 方形栅格，图像上方为 V=1。超出 0–1 的 UV 裁切到 tile 1001 并报告，不 wrap、不重排，不声称完整 UDIM。输出目录须不存在或为空。

图像遮罩白色允许、黑色禁止，透明区为禁止。明确目标部位、方向、留边与允许的裁切。多 UV 岛的遮罩不保证表面跨岛无缝。

单纹样匹配对剪影和高度使用完全相同的位置、缩放、旋转、裁切与允许区域，保存变换记录，检查眼部、卷纹和连接处。生成式适配后再次检查两图对齐；无法锁定一致变换时如实说明。

重复铺排与红色密度引导是另行请求的工作台节点。`canvas/uv_engine.py` 的 `generate_pattern` 是本地重复合成，不能当作单纹样匹配或图像模型编辑。
