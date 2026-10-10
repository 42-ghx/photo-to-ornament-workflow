# 本仓库

根目录即 `photo-to-ornament` 技能目录，先读 `SKILL.md`。四阶段图片为默认流程；工作台包含按需 UV、局部铺排和浮雕导出。新任务保留输入与版本，不把示例和历史验收当成新结果。

修改工作台后运行 `python -m unittest discover -s canvas/tests -v` 和 `node --check canvas/studio.js`。修改脚本后验证实际行为；缺少可选依赖时说明未执行范围。运行输出存入 `runs/`，不加入版本库。

仓库已改为可直接安装的 Skill；不要恢复旧完整运行包或大型历史高模。图库仅为已有成果缩小展示，不作为生产地图。
