# Codex Cloud 与跨电脑执行

私有仓库：https://github.com/42-ghx/photo-to-ornament-workflow

## 创建云环境

1. 用同一ChatGPT账号打开Codex，选择 **Work in → Cloud → Select environment → Create environment**。
2. 选择 `42-ghx/photo-to-ornament-workflow`。若仓库未出现，在GitHub连接设置中把此新建私有仓库加入允许列表。
3. 在环境准备对话中要求Python 3.12、Blender 5.2.2、Git LFS和Linux x86_64，并运行 `bash setup/bootstrap_cloud.sh`。允许GitHub/LFS、PyPI和 `download.blender.org` 的下载域名；依赖见脚本。
4. 在环境内执行 `python setup/verify_manifest.py`、`.venv/bin/python run_case.py --blender .tools/blender-5.2.2-linux-x64/blender`。核对 `runs/ding/result/fbx_uv_checks.json` 的 `status` 为 `passed` 以及渲染预览。
5. 查看环境准备报告，保存并 **Publish**。显示 **Environment published** 后使用它启动云端任务。

推荐给环境准备对话的提示词：

> 请读取README.md、AGENTS.md和CLOUD_SETUP.md，准备此私有仓库的Python 3.12、Git LFS及Blender 5.2.2环境。运行bash setup/bootstrap_cloud.sh并检查MANIFEST.json。用run_case.py复现鼎案例：Before细节、浮雕0.5、底厚不变，不做新平滑或分层。核对FBX重导入、UV及预览，并报告环境能否发布。保留我的其他连接配置，不读取或复制旧PC的OAuth/API凭证。

## 脚本入口

```sh
bash setup/bootstrap_cloud.sh
.venv/bin/python run_case.py --blender .tools/blender-5.2.2-linux-x64/blender
# 仅验证几何缩放，暂不运行Blender
.venv/bin/python run_case.py --mesh-only
# 需要从已确认地图重建时显式指定
.venv/bin/python run_case.py --rebuild-from-maps --blender .tools/blender-5.2.2-linux-x64/blender
```

默认从认可Before数组缩放；`--mesh-only`只生成数组，不能称为已导出FBX。输出位于 `runs/ding/`，不自动提交到GitHub。新的最终模型在确认后以独立资产版本提交，使用LFS。

## 执行范围与验证状态

已验证：原工作流的Windows建模/导出/重导入，以及本仓库跨平台Python入口的Windows执行。Linux安装入口将在云环境准备时实际验证，不能把脚本准备等同于云环境已经发布。

云端后台Blender可生成FBX、工程和预览；不会自动连接公司电脑的localhost Blender MCP。桌面查看需把结果拉到公司电脑并连接当地Blender。照片地图阶段依赖当前任务实际可用的图像编辑工具；没有此工具时须先配置能力，不把明暗直接转换为测量高度。Hyper3D OAuth在需要使用的执行环境单独授权。

官方依据：[Cloud environments](https://learn.chatgpt.com/docs/environments/cloud-environments)。仓库内技能可在云任务发现；本地个人技能不会自动同步。云端准备需安装和验证执行环境，上传GitHub本身不会移动当前本地聊天的执行主机。
