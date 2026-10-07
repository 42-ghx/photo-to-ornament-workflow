> 本项目已迁到私有GitHub仓库：https://github.com/42-ghx/photo-to-ornament-workflow 。跨电脑优先按README.md克隆并拉取LFS；Codex云端按CLOUD_SETUP.md准备环境。以下保留本机安装说明。

# 照片纹样→镂空浮雕工作流 1.0

2026-10-01 固化，最终认可版本为 **ding_detail_half_03：恢复Before细节，只将浮雕高度减半**。

工作顺序：照片 → 透明抠图 → 柔和去光照 → 材料遮罩与连续高度图 → 按任务要求验收地图 → 高密度浮雕 → 恒定高度的侧壁循环边 → 正面/厚度/底面UV → 从已认可源版本单独调整浮雕强度 → FBX与Blender查看。

核心原则：刻线写进高度，镂空写进遮罩；底厚与浮雕幅度分开控制；保留认可细节。禁止默认全局抹平或6级高度量化。原图、地图和源模型保留，阶段版本不覆盖。

## 公司电脑开始使用

1. 将本包完整解压到公司电脑任意可写目录，用Codex打开这个目录为本地项目。
2. 让Codex读取`AGENTS.md`、`MIGRATION.md`与`.agents/skills/photo-to-ornament/SKILL.md`。这一步不依赖旧电脑上的对话能否出现。
3. 按`MIGRATION.md`安装/检查Python、Blender、技能和Blender MCP；Hyper3D在需要Rodin时重新OAuth授权。
4. 运行鼎案例复现或提供新照片。地图阶段本案使用内置image_gen；当前客户端没有可用图像编辑工具时，应先配置相应能力，不能假称完成照片生成。

可直接复制给公司Codex：

> 请读取当前项目的START_HERE.md、AGENTS.md和MIGRATION.md，安装本包photo-to-ornament技能并检查本机Python、Blender、Blender MCP和Hyper3D连接。保留现有其他配置，不复制旧电脑凭证。先复现cases/ding的最终认可版本：Before细节完整、浮雕强度0.5、底厚不变、不做新平滑或高度分层。核对FBX、UV和侧壁循环边后导入本机Blender供我查看。

## 目录

- `.agents/skills/photo-to-ornament/`：可安装技能、提示词、建模/缩放/导出脚本、验收规则。
- `cases/ding/source_photo.png`、`maps/`：当前案例照片及认可中间图。
- `cases/ding/mesh_before/`：Before高模数组与UV数据；完整版携带，轻量版省略。
- `cases/ding/accepted/reproduced/`：用包内脚本复现的最终模型、独立Blender工程、FBX检查；完整版携带模型。
- `cases/ding/accepted/`：已认可模型的正面/侧面和循环边、UV预览、数值验收。
- `assets/Edge Damage Modifer.blend`：用户原资产副本，可选使用。
- `setup/`：依赖版本、安装入口、MCP模板、Blender插件副本（如已取得）。
- `WORKFLOW_SUMMARY.md`：流程总结、当前能力范围。
- `MANIFEST.json`：包内文件大小与SHA256。

## 使用范围

此版固定的是**独立纹样浮雕**，不是照片整器重建。当前已完成照片地图、材料轮廓高模、密集四边面、厚度循环边、分区UV及FBX导入验证。磨损脚本与资产可选，当前最终模型未加磨损。PBR整模型贴图、Substance Painter自动导入、工业服装打版和毛发流程仍需单独实现与验收；本包不把这些列为已完成。

轻量包适合安装技能和从新照片开始；完整包还包含高模与Before复现数据。Python虚拟环境、Blender安装本体与客户端凭证不在包里，按新电脑重建。
