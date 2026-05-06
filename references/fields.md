# gen-images 字段与交互规则

## 任务类型

- 文生图：默认优先调用 `POST /v1/responses` 的 SSE 流式 Responses API；代理不支持时回退 `POST /v1/images/generations`
- 改图：默认优先调用 `POST /v1/responses` 的 SSE 流式 Responses API；代理不支持或使用 `mask` 时回退 `POST /v1/images/edits`

如果用户表达包含明确的图片来源（本地路径、URL、data URL）且语义是“修改图片 / 编辑图片 / 改图”，优先识别为改图。

## 必填字段

### 文生图
- `prompt`

如果缺少 `prompt`，先向用户追问，不要执行脚本。

### 改图
- `prompt`
- 图片来源

图片来源支持：
- 本地图片路径
- 图片 URL
- data URL

如果缺少图片来源，向用户明确提示二选一：
1. 提供本地图片路径
2. 提供图片 URL / data URL

## 可选字段

- `model`：默认 `gpt-image-2`
- `response_format`：默认 `b64_json`
- `stream`：默认 `true`，可用 `--no-stream` 强制走旧的非流式 `/images/*` 接口
- `size`
- `quality`
- `background`
- `output_format`
- `output_compression`
- `partial_images`：流式调用未显式传入时脚本默认使用 `1`
- `n`：默认 `1`
- `moderation`
- `input_fidelity`（改图可用）

## 自然语言映射

### size
- `1024x1024`、`1:1` -> `size=1024x1024`
- `1024x1536`、`3:4` -> `size=1024x1536`
- `1536x1024`、`4:3` -> `size=1536x1024`
- `2048x2048` -> `size=2048x2048`
- `3840x2160`、`16:9` -> `size=3840x2160`
- `2160x3840`、`9:16` -> `size=2160x3840`
- `4k横向`、`16:9` -> `size=3840x2160`
- `4k竖向`、`9:16` -> `size=2160x3840`
- `auto` -> `size=auto`
- 如果用户明确给出上述尺寸或比例，优先映射到对应 `size`

### LLM 语义推断 size

如果用户没有明确给出尺寸或比例，但 prompt 的用途清楚，允许当前 LLM 做保守推断：

- `头像`、`图标`、`logo`、`表情包`、`贴纸`、`商品主图`、`方形社媒图` -> `size=1024x1024`
- `海报`、`封面`、`人物半身/全身`、`竖版构图`、`小红书封面` -> `size=1024x1536`
- `横幅`、`banner`、`视频封面`、`演示背景`、`横版构图` -> `size=1536x1024`
- `手机壁纸`、`竖屏壁纸`、`短视频封面`、`9:16` -> `size=2160x3840`
- `桌面壁纸`、`4k横向壁纸`、`16:9` -> `size=3840x2160`

不要仅因为 prompt 很长、风格复杂或包含“高清”就自动选择 4k；只有用途明显需要大尺寸展示、壁纸、16:9/9:16，或用户明确提到 4k 时才选择 4k 尺寸。

### quality
- `高清`、`高质量`、`高品质` -> `quality=high`
- `中等质量` -> `quality=medium`
- `低质量` -> `quality=low`
- `精细`、`商用`、`主视觉`、`壁纸`、`海报`、`产品图` -> `quality=high`
- `草图`、`快速预览`、`低成本试稿` -> `quality=low`

### background
- `透明背景` -> `background=transparent`
- `白色背景` -> `background=white`
- `黑色背景` -> `background=black`
- `无背景`、`抠图`、`贴纸`、`图标`、`logo` 且不是完整场景图 -> `background=transparent`
- `白底`、`黑底` -> 分别映射 `background=white`、`background=black`

### output_format
- `png` -> `output_format=png`
- `jpg` -> `output_format=jpg`
- `jpeg` -> `output_format=jpeg`
- `webp` -> `output_format=webp`

如果用户自然语言中明确要求保存格式，按要求保存；否则默认保存为 `png`。
如果推断出 `background=transparent` 且用户没有指定格式，使用 `output_format=png`。

### n
- `生成3张`、`来3张`、`输出3张` -> `n=3`
- `多方案`、`给几个版本` 且没有明确数量 -> `n=3`
- 未指定时默认 `n=1`

### output_compression

- 用户明确要求 `压缩`、`小体积`、`控制文件大小`，且 `output_format` 为 `jpg`、`jpeg` 或 `webp` 时，才传 `output_compression`
- 如果用户没有给具体压缩率，不要猜具体数值，省略该字段

### input_fidelity

仅改图可用：

- `保持脸/人物/主体/产品一致`、`只改风格` -> `input_fidelity=high`
- `大幅重绘`、`重新设计`、`完全换风格` -> 不设置 `input_fidelity`，或在用户明确要求低保真时设置 `input_fidelity=low`

### 不建议推断的字段

- `model`：只有用户明确指定模型或明确要求使用 pro/某个模型名时才传
- `moderation`：只有用户明确要求时才传
- `partial_images`：只有用户明确要求中间图数量时才传；否则交给脚本默认值

## timeout 规则

Bash 调用 `scripts/gen_images.py` 前，先根据 `size` 计算本次工具调用的 `timeout`：

- 当 `size` 可解析为 `宽x高`，且总像素量 `宽 * 高 >= 8000000` 时，使用 `timeout=900000`（15 分钟）
- 其余情况使用 `timeout=600000`（10 分钟）
- `auto`、缺少 `size`、或无法解析尺寸时，按非 4k 处理，使用 `timeout=600000`

执行时按这个顺序判断：
1. 读取已提取的 `size`
2. 如果 `size` 匹配 `^\d+x\d+$`，拆出宽高并计算总像素量
3. 若总像素量 `>= 8000000`，本次 Bash 调用使用 `timeout=900000`
4. 否则本次 Bash 调用使用 `timeout=600000`

## 字段优先级

1. 用户明确写出的字段值
2. 用户自然语言中的明确要求
3. 当前 LLM 根据 prompt 和用途做出的保守推断
4. 脚本默认值

## 交互规则

### 文生图缺 prompt
使用简短追问：

`请补充图片提示词，例如你想生成什么画面。`

### 改图缺图片来源
使用简短追问：

`请提供要编辑的图片来源：1）本地路径 2）图片 URL / data URL`

### 改图缺 prompt
使用简短追问：

`请补充修改要求，例如你想把图片改成什么效果。`

## 成功输出格式

成功后向用户报告：
- `图片已生成, 图片路径: <路径>`
- `实际使用的关键参数: model=..., size=..., quality=..., output_format=..., n=..., stream=...`

## 失败输出格式

失败后向用户报告：
- `生成失败: <简短错误原因>`
