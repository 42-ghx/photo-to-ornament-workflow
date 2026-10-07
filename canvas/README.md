# 节点画布

克隆仓库并拉取LFS后，直接在浏览器中打开 `canvas/index.html`；无需安装网页依赖或启动服务。关联图片和工程按仓库相对路径读取，所以请保留完整目录。

- 滚轮缩放、拖动空白平移、拖动节点调整位置。
- 单击节点或按回车，查看输入、输出、结构约束、案例参数和文件；制作节点提供可复制命令。
- 注释与布局自动保存在当前浏览器，支持导出和导入 `.canvas`。导入已知节点时只采用布局和注释，制作约束仍以仓库定义为准。
- “扩展路线”显示Rodin整器生成、UV模板、PBR、MD和毛发的后续路线，并明确标记尚未验收。
- 画布用于流程组织与命令交接；不会自动执行Blender、图像生成或提交Git。模型仍用现有脚本和实际可用工具制作。

`photo-to-ornament.canvas` 遵循 [JSON Canvas 1.0](https://jsoncanvas.org/spec/1.0/) 的文本、分组与连接格式，可导入支持该格式的工具。独立查看器当前支持文本和分组节点，不支持其他工具添加的文件/链接节点。

维护时编辑 `workflow.json`（步骤与参数）或 `template.html`（交互界面），然后在仓库根目录运行：

```sh
python setup/build_node_canvas.py
```

它会更新 `index.html`、标准 `.canvas` 和GitHub预览 `overview.svg`。最后更新 `MANIFEST.json` 中变动文件的大小与SHA256，再提交。不要把浏览器保存的布局当作已同步到GitHub；需要导出并提交相应 `.canvas` 文件。

修改内置步骤或连接时递增 `workflow.json` 的 `revision`，避免旧版浏览器布局覆盖新的流程定义。原版本的布局文件可再次导入。
