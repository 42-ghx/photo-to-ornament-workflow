> 本项目已迁到私有GitHub仓库：https://github.com/42-ghx/photo-to-ornament-workflow 。跨电脑优先按README.md克隆并拉取LFS；Codex云端按CLOUD_SETUP.md准备环境。以下保留本机安装说明。

# 不同PC如何继续使用

同一账号可在公司电脑使用Codex，但**仅登录不等于本地工作环境已经搬过去**。本次工程文件、脚本、Blender安装与本地技能需要带过去；MCP也需在执行任务的那台电脑检查并连接。即使看到聊天内容，本机D:/或E:/路径不会因此在公司电脑存在。

OpenAI官方说明：技能可由本地文件夹发现，MCP配置按同一执行主机共享；本地项目访问该电脑的文件夹。这里选择可迁移文件包，不要求对话历史跨PC完整同步。

## 推荐步骤

1. 将ZIP通过你选择的U盘或网盘复制到公司电脑，完整解压。不要只保存此对话里的D:/本地链接。
2. 安装并登录Codex，添加解压目录为本地项目，让Codex读取START_HERE.md与AGENTS.md。无需旧电脑在线。
3. 安装Python 3.12（本案3.12.9），安装Blender（本案5.2.2 LTS）。已有兼容安装先检查。运行`setup/bootstrap.ps1 -PythonCommand '你的python.exe'`创建包内`.venv`；依赖见setup/requirements.txt，不复制旧PC虚拟环境。
4. 运行`setup/install_skill.py`安装photo-to-ornament。默认使用官方文档的用户技能位置`~/.agents/skills/photo-to-ornament`；项目内可选择安装到`.agents/skills`。本案旧客户端已存在`~/.codex/skills/photo-to-ornament`时，指定该旧路径更新以避免同名技能重复。脚本仅更新本技能，先备份，不覆盖整个客户端配置。
5. Blender中安装/启用MCP插件，启动它的本地服务；Codex配置对应stdio服务。Blender版本、端口及服务器工具要实际核对，不能复用旧PC的绝对exe路径。
6. 有Rodin任务时，配置服务名`hyper3d`、Streamable HTTP地址`https://api.hyper3d.com/api/mcp`，点击Authenticate或运行`codex mcp login hyper3d`。已有同名配置先复用/更新，保留其他设置；不要拷贝旧电脑的OAuth令牌。
7. 若新技能或MCP未出现在当前任务中，重启客户端或新建任务后检查。先做场景读取与截图，再进行建模导入。

## 安装技能

在包根目录执行（项目内Python虚拟环境创建后）：

```powershell
& .venv/Scripts/python.exe setup/install_skill.py --scope user
```

仅本项目可见：

```powershell
& .venv/Scripts/python.exe setup/install_skill.py --scope project
```

指定已有旧版安装位置时：

```powershell
& .venv/Scripts/python.exe setup/install_skill.py --destination 'C:/Users/你的用户名/.codex/skills/photo-to-ornament'
```

技能可能支持自动识别，也可显式调用`$photo-to-ornament`。在其他目录开展新任务时使用用户范围安装；本包的相对示例路径以包根目录为起点。

## Blender MCP

本机已用的Python服务器为blender-mcp 1.9.1；包内记录其依赖/源码信息。若携带了`setup/blender_addon.py`，可先安装该副本匹配复现；服务器需在公司电脑自己的Python环境安装。它和Blender插件是两个部分。

配置示例见`setup/mcp.template.toml`；按实际可执行文件改路径。已有`blender`配置先复用，不另起多个指向同一端口的服务器。

公司电脑没有服务器时可运行`setup/install_blender_server.ps1`建立独立环境，安装本案的blender-mcp 1.9.1，并打印新的exe路径；它不覆盖MCP配置。Blender侧通过Preferences安装包内`setup/blender_addon.py`并启用，在侧栏MCP for Blender启动服务。该插件副本版本与来源记录在`setup/blender_mcp_snapshot.json`，含MIT许可证。具体配置由公司Codex读取现有设置后合并。

`python setup/diagnose.py --blender '公司电脑Blender.exe路径'`提供只读检查；它不会验证OAuth成功或保证工具已连接，最终用Codex的实际场景读取/工具列表核实。

项目官方近期改名为mcp-for-blender，说明旧配置继续工作。新装可按[Blender MCP项目说明](https://github.com/ahujasid/mcp-for-blender)配置，检查版本与工具兼容再替换；本包不擅自升级公司已有配置。无需启用Rodin/Tripo等付费生成功能来跑当前浮雕案例。

## 复现当前认可结果

```powershell
./run_case.ps1 -BlenderPath '公司电脑的Blender.exe路径'
```

完整版从携带的Before数组复现，每个正面顶点仅减半起伏。轻量版没有Before数组时，脚本会从携带地图重建，再缩放；有轻微浮点/库差异时核对QA。产物在`runs/ding/result/`，工程只保存认可版本与辅助查看对象，不包含被否定的6级平台模型。

想强制验证从地图开始：

```powershell
./run_case.ps1 -BlenderPath '公司电脑的Blender.exe路径' -RebuildFromMaps
```

这些后台脚本可在没有MCP时生成并打开Blender工程；要Codex实时操作Blender，仍需上面的连接步骤。图像生成工具、其他插件、Substance Painter和MD也按公司电脑实际环境配置；本包没有其自动集成。

## 官方依据与远程备选

- [本地技能发现与重载](https://learn.chatgpt.com/docs/build-skills)：技能是文件夹，按本地作用域加载。
- [MCP配置与OAuth](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)：配置共享范围为同一Codex主机；本地配置及云端工具分开。
- [本地项目与文件](https://learn.chatgpt.com/docs/projects)：本地项目连接电脑文件夹。
- [Remote](https://learn.chatgpt.com/docs/remote)：官方的手机远程控制在连接的电脑执行，需要该电脑在线并保持唤醒；这不是把文件迁到公司PC。本次没有启用远程控制，不据此承诺公司PC直接访问家庭电脑。

不同电脑聊天显示与同步能力可能随客户端/工作区不同而变化，以上资料不足以保证本次本地任务在另一PC完整自动出现。带迁移包并开本地项目即可继续，不依赖这项不确定性。
