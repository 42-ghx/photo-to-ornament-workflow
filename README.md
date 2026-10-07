# 照片转镂空纹样高模工作流

项目云端地址：https://github.com/42-ghx/photo-to-ornament-workflow （私有仓库）。

照片 → 抠图与柔和去光照 → 材料遮罩 / 连续高度 → 镂空高模 → 厚度循环边 → 分区UV → FBX / Blender。

已认可案例为 **ding_detail_half_03**：恢复Before完整细节，只将正面浮雕起伏减半；底厚、轮廓、循环边和UV保持原样，不增加几何平滑或高度分层。具体数值和验收记录见 `WORKFLOW_SUMMARY.md`、`VALIDATION.json` 和 `cases/ding/accepted/`。

## 使用方法

安装 Git、Git LFS，并使用有权限的 GitHub 账号登录：

```sh
git clone https://github.com/42-ghx/photo-to-ornament-workflow.git
cd photo-to-ornament-workflow
git lfs pull
python setup/verify_manifest.py
```

`.blend`、`.fbx`、`.npz` 用 Git LFS 保存。下载 GitHub 普通源码ZIP可能只获得指针文件；优先使用上述克隆方式。项目技能已经放在 `.agents/skills/photo-to-ornament/`，无需复制旧电脑的个人技能或凭证。

Windows 本机安装与 Blender MCP 查看：读取 `START_HERE.md` 和 `MIGRATION.md`。Linux / Codex Cloud：读取 `CLOUD_SETUP.md`。

## 当前能力范围

本项目已验证独立纹样浮雕、密集四边面、厚度循环边、正面/厚度/底面UV及FBX重导入。生成式高度是艺术重建，不能当作照片测量结果。整器重建、完整PBR、Substance Painter自动导入、工业纸样和毛发仍需分别实现与验收。

GitHub 保存项目和版本；Codex云端执行需要另行创建并发布云环境。云端可使用后台Blender生成文件，桌面Blender实时查看和Substance Painter仍需执行电脑上的软件与连接。
