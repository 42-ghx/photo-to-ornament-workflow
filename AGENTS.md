# 本项目规则

先读取START_HERE.md及.agents/skills/photo-to-ornament/SKILL.md，按对应阶段加载references。最终认可状态是ding_detail_half_03：Before原细节，正面浮雕形变50%，底厚、循环边、UV不变。

不要默认采用6级平台量化、全局几何平滑、统一高度挤出或矩形底板。地图中白色材料/黑色孔洞与高度里的刻线必须分开。用户已认可地图且要求建模时直接继续；用户要求先看图时交付地图后等待。

新照片的尺寸、区域、观看距离与开闭背面依据当前任务，不把本例1m/5m套作实际尺寸。保留输入及确认版本；版本分别存入runs或新资产目录。脚本使用项目相对路径，新电脑的软件路径单独配置。

有实际工具才声称自动导入Blender；后台生成文件与实时MCP连接分开验证。原始PNG不由数值几何脚本改写。不携带或打印客户端账号、OAuth、API密钥。

GitHub私有仓库是跨电脑项目来源。云端先读取CLOUD_SETUP.md，核实Git LFS文件不是指针。技能在.agents/skills/photo-to-ornament；跨平台入口run_case.py。云端后台输出与本地MCP实时查看分别报告；没有环境发布证据不能说当前聊天已迁到云端。
