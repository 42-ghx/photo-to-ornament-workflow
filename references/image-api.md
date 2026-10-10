# 生图模型与 OpenAI 兼容接口

## 模型记录的含义

- **已有示例**：源工作台把请求提供方标为 `Codex image 2`，实际执行通过 Codex 图像工具；原始记录没有服务商返回的模型 ID，不能据此认定为某个 GPT Image 快照。
- **Codex 聊天路径**：继续使用当前聊天提供的图像工具，不需要把 API Key 交给本仓库。工具没有公开版本时记录为未知。
- **直接 API 路径**：新增 `scripts/image_api.py`，支持 OpenAI Images API 格式和兼容服务。模型由 `ORNAMENT_IMAGE_MODEL` 指定，接入示例采用 `gpt-image-1.5`；也可填服务商支持的 GPT Image 模型或自有模型 ID。它不是已有示例的模型归因。

按官方文档，有参考图时使用 `POST /images/edits` 的 multipart 上传；无参考图时使用 `POST /images/generations` 的 JSON 请求。接入要求返回 `data[0].b64_json` PNG。第三方兼容服务必须支持这些字段、编辑图片和所选模型；只有聊天补全接口并不足够。官方格式依据：[图像编辑](https://developers.openai.com/api/reference/python/resources/images/methods/edit)、[图像生成](https://developers.openai.com/api/reference/resources/images/methods/generate)（核对日期：2026-10-10）。

## 最简单的安全配置

安装工作台依赖后，在自己的交互式终端运行：

```sh
python scripts/run_image_api_secure.py --check
```

按提示填写服务地址、模型和 API Key。Key 输入不回显，只存在本次进程内，不写配置文件或 shell 历史。`--check` 仅检查本地格式，不访问服务商、不产生生图费用，也不证明账号额度或模型权限。

已有安全的环境变量管理方式时，可直接设置以下变量并运行 `python scripts/image_api.py --check`：

| 环境变量 | 含义 |
| --- | --- |
| `ORNAMENT_IMAGE_API_KEY` | 必填，仅由本机 API 执行器读取；不要放在项目、提示词、聊天或 Git 中 |
| `ORNAMENT_IMAGE_MODEL` | 必填，如 `gpt-image-1.5`；以服务商实际开放的模型 ID 为准 |
| `ORNAMENT_IMAGE_BASE_URL` | 默认 `https://api.openai.com/v1`；第三方地址应包含其 API 前缀，不能含 Key、账号、密码、查询参数 |

远程接口必须是 HTTPS；本机代理可用 `http://127.0.0.1:<端口>/v1`。执行器不继承系统代理、不跟随 HTTP 重定向，也不下载服务商返回的图片 URL，以免密钥被转发到其他主机。

## 与节点工作台连接

1. 启动工作台，在目标图像节点填好提示词、连接参考图，点击「重新生成」。
2. 从任务面板复制该任务的 ID。保持工作台运行。
3. 在本机终端执行（把 `任务ID` 替换成实际 ID）：

```sh
python scripts/run_image_api_secure.py --job 任务ID
```

使用已有环境变量时，可直接运行 `python scripts/image_api.py --job 任务ID`。每次只领取这一个待执行任务：读取参考图 → 原子领取 → 调用服务商 → 校验 PNG → 上传到本机工作台 → 回填为新版本。已领取或完成的任务不能被此执行器重复领取。浏览器不会接收 API Key，也没有保存 Key 的输入框。

非默认端口用 `--studio-url http://127.0.0.1:8765`。四步按上游结果依次执行并目视验收；批量任务可逐个显式执行，不会自动启动全队列。工作台网页本身不会常驻运行 API 执行器。

材料剪影和 UV 遮罩作为参考图片传入，不冒充 API 的透明修补遮罩。普通图像保留返回 PNG 的原始尺寸与位深，UV 裁切仍遵守[生成桥接](../canvas/CODEX_GENERATION.md)的限制。

## 独立生成或编辑

把本次提示词保存在 UTF-8 文件，先建立 `runs/my-job` 目录。有参考图时：

```sh
python scripts/run_image_api_secure.py --prompt-file runs/my-job/prompt.txt --image runs/my-job/source.png --out runs/my-job/01_cutout.png --background transparent
```

可重复 `--image` 传入多张参考图；省略 `--image` 时使用文生图。输出文件必须尚不存在。旁边生成 `.generation.json`，仅记录提供方类型、请求模型，以及服务商确实返回的模型名；不保存接口地址、认证头、完整响应或密钥。

可选参数：`--size auto`、`--quality auto|low|medium|high`、`--background auto|transparent|opaque`。支持范围取决于所选服务和模型。`seed`、工作台 `strength`、任意精确尺寸等不会被伪装为兼容接口已支持的参数。

## 费用与失败处理

实际执行 `--job` 或 `--prompt-file` 会把输入发送到所选服务商，并可能计费；本仓库不附带额度、密钥或账号。没有自动重试、自动换模型或备用服务商。超时或取消回填不保证远端生成已停止；再次执行前先查看服务商任务和账单。不要同时用 Codex 和 API 处理同一任务。

错误信息只显示固定说明和 HTTP 状态码，服务商响应体、地址和认证头不会写入工作台日志。当前实现通过模拟服务和真实本机工作台测试，未使用个人密钥进行付费验收。
