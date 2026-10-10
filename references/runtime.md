# 环境、路径与安装

仓库根目录就是技能目录，包含脚本、引用、节点工作台和少量示例，不依赖原始完整包或个人配置。

## 安装技能

```sh
python scripts/install_skill.py --dry-run
python scripts/install_skill.py
```

默认安装到 `$CODEX_HOME/skills/photo-to-ornament`，未设置时为 `~/.codex/skills/photo-to-ornament`。已有技能先整体备份再更新。可用 `--destination` 指定其他目录；不改账号、MCP 或其他技能。新技能尚未显示时，重新打开聊天后检查发现情况。

## 地图与工作台

Python 3.11 或更新版本，推荐 3.12。地图检查和 UV 抽取仅依赖 NumPy、Pillow。先在选定的虚拟环境安装依赖；启动器优先使用已有 `.venv-studio` / `.venv`，不会自动安装软件。

```sh
python -m pip install -r setup/requirements-studio.txt
python setup/start_studio.py
```

已有依赖环境可直接运行 `python canvas/server.py --host 127.0.0.1 --port 8001`。网页本身不提供图像生成能力，需要当前聊天可用的真实图像工具。

从其他工作目录调用时，给脚本、输入和输出传绝对路径：

```sh
python /path/to/photo-to-ornament/scripts/inspect_maps.py --maps /path/to/job/maps
```

## 可选几何

几何依赖列在 `scripts/requirements-geometry.txt`，安装到本次项目虚拟环境。后台导出需本机 Blender；MCP 用于实时查看/操作时按实际环境连接。不要搬运旧电脑路径和令牌。

```sh
python -m pip install -r scripts/requirements-geometry.txt
```

历史环境与验收数据不等于新环境验证。四步地图不需要 Blender 或全部几何依赖。
