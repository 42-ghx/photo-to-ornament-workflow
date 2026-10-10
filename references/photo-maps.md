# 地图流程与可改写提示词

查看当前照片，识别外轮廓、连接、凹槽、负空间与被裁切边缘。模板约束需要按本图改写，不是固定器形。尺寸按用户要求及工具能力设定；工具不支持精确尺寸、seed 或 strength 时不能声称已控制。

## 1. 补全与透明抠图

仅补足确实被裁切的边缘，保留可见结构、方向、部件数量及刻线。双侧对称只在参考支持或用户要求时采用。棋盘格画进 RGB 图不算透明。

> Edit the supplied ornament photograph. Isolate [requested motif], preserving [observed distinguishing features]. [If cropped: conservatively reconstruct missing edges from visible structure.] Keep the complete outline with clear margins. Remove the surrounding vessel/background and cast shadow as requested. Preserve grooves as surface carving, not holes. Genuine transparent background, no text, frame, extra motifs or pedestal. Missing sections are an artistic reconstruction.

## 2. 柔光参考

以上一步为参考，锁定画布、轮廓、位置和部件；减弱反光、锈色与大块阴影，保留读形细节。

> Keep exactly the same framing, silhouette and feature positions. Soften uneven illumination, specular highlights, color cast and distracting patina. Retain fine carved lines and the hierarchy of rounded and recessed shapes. Neutral soft material reference, transparent exterior, no redesign or cast shadow. Do not remove dark grooves or supported eye recesses.

## 3. 主纹剪影

白色表示本次装饰实体。提取凸起纹带时，可将指定的纹带间底地作为负空间；这不证明历史器物实际贯通。不能仅凭照片中的深色判断孔洞。

> Create a black-and-white mask of [chosen decorative material footprint], keeping canvas and registration unchanged. Solid WHITE means material; BLACK means exterior and explicitly selected negative spaces [describe]. Fill incised carving, supported eye disks/pupils and shallow pits with white support. No lighting, gray shading, speckle, rectangular backing or invented holes. Preserve the complete outline and recognizable features.

## 4. 连续高度

同时提供剪影与柔光参考：剪影控制位置范围，柔光图提供刻线与形体。黑色为外部/零值，亮部为高；内部凹陷仍由实体支撑，不能在遮罩上删孔。

> Input 1 is the authoritative material mask and registration. Input 2 supplies sculptural and incised detail. Create a neutral grayscale height map only within the white mask. Keep the entire outline, feature positions and framing unchanged. Use continuous slopes and distinct primary/secondary relief, shallow incised lines and supported eye depressions. No directional light, cast shadow, AO, metallic reflection, patina noise or stepped quantization. Background stays black. Do not redesign the mask.

## 对齐与版本

保存实际提示词、输入、输出及已知参数。发生轮廓或刻线漂移时回到该阶段修正，不通过任意拉伸宣称对齐。`inspect_maps.py` 只检查结构、尺寸、透明度、灰度和范围，不能判断补全合理性、历史真实性或眼部语义。

`ding_prompts.json` 是旧案例档案，只在复现时参考，不套用固定部件、尺寸或旧高度编码。仓库图库使用已有批次结果，不是本次新生成。
