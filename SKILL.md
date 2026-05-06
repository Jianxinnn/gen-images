---
name: gen-images
description: This skill should be used when the user asks to "使用 gpt-image-2", "生成图片", "文生图", "修改图片", "编辑图片", "改图", wants to create or edit images through CLIProxyAPI, or invokes `/gen-images` to run image generation or image editing.
argument-hint: <自然语言需求>
allowed-tools: [Bash, Read]
---

# gen-images

使用这个 skill 处理通过 CLIProxyAPI 调用 `gpt-image-2` 的图片生成和图片编辑任务。支持自动触发，也支持用户手动输入 `/gen-images ...`。

## 目标

- 识别用户是要文生图还是改图
- 从用户自然语言中提取可用字段
- 缺少关键字段时先追问用户，不要盲目执行
- 字段足够时调用 `scripts/gen_images.py`
- 完成后向用户输出图片路径和实际使用的关键参数

## 资源

- `references/fields.md`：字段、默认值、自然语言映射、交互规则
- `scripts/gen_images.py`：真正执行图片接口调用和文件保存

## 手动命令用法

用户手动调用时，参数就是自然语言需求：

```text
/gen-images 生成一张透明背景的猫咪头像，1024x1024，png
/gen-images 把 ./input.png 改成水彩风，保留主体，输出 webp
```

命令参数内容在本次执行中就是：

`$ARGUMENTS`

如果是通过自动触发进入本 skill，则直接根据用户原始消息理解需求。

## 任务分类

先判断任务类型：

### 文生图
出现这类意图时，按文生图处理：
- `生成图片`
- `文生图`
- `画一张图`
- `用 gpt-image-2 生成`

### 改图
出现这类意图时，按改图处理：
- `修改图片`
- `编辑图片`
- `改图`
- `把这张图改成...`

如果同时出现图片来源（本地路径、URL、data URL）和修改意图，优先按改图处理。

## 字段提取规则

先参考 `references/fields.md` 的规则提取字段。

### 必填字段

#### 文生图
- `prompt`

如果缺少 `prompt`，先向用户追问：

`请补充图片提示词，例如你想生成什么画面。`

#### 改图
- `prompt`
- 图片来源

图片来源支持：
- 本地路径
- URL
- data URL

如果缺少图片来源，先向用户追问：

`请提供要编辑的图片来源：1）本地路径 2）图片 URL / data URL`

如果缺少修改要求，先向用户追问：

`请补充修改要求，例如你想把图片改成什么效果。`

### 可选字段

可选字段可以来自两类信息：
- 用户明确写出的字段、比例、格式、数量、质量要求
- 当前 LLM 对用户 prompt 的保守语义推断，例如头像倾向正方形、手机壁纸倾向竖屏、横幅倾向横屏

尽量提取以下字段，并只对适合推断的字段做保守推断：
- `size`
- `quality`
- `background`
- `output_format`
- `n`
- `moderation`
- `output_compression`
- `partial_images`
- `input_fidelity`（改图）

如果用户没有明确提供，但 prompt 的用途很清楚，可以由 LLM 推断 `size`、`quality`、`background`、`output_format`、`n`、`input_fidelity`。如果信心不足，不要追问，直接省略该字段并使用脚本默认值。不要为了可选字段反复追问。

直接从终端调用 `scripts/gen_images.py` 时，脚本不会自己根据 prompt 推断参数；只有通过本 skill 由 LLM 整理参数时，才会发生这些语义推断。

字段优先级：
1. 用户明确写出的字段值
2. 用户自然语言中的明确要求
3. LLM 根据 prompt 和用途做出的保守推断
4. 脚本默认值

### 自然语言映射

优先识别这些自然语言：
- `高清` -> `quality=high`
- `透明背景` -> `background=transparent`
- `1024x1024`、`1:1` -> `size=1024x1024`
- `1024x1536`、`3:4` -> `size=1024x1536`
- `1536x1024`、`4:3` -> `size=1536x1024`
- `2048x2048` -> `size=2048x2048`
- `3840x2160`、`16:9` -> `size=3840x2160`
- `2160x3840`、`9:16` -> `size=2160x3840`
- `4k横向`、`16:9` -> `size=3840x2160`
- `4k竖向`、`9:16` -> `size=2160x3840`
- `auto` -> `size=auto`
- `png/jpg/jpeg/webp` -> `output_format=...`
- `生成3张` -> `n=3`

如果用户明确要求保存格式，按用户要求保存；否则默认保存为 `png`。

### LLM 语义推断规则

在用户没有明确给出可选字段时，允许根据 prompt 的目标用途推断参数：

- `头像`、`图标`、`logo`、`表情包`、`贴纸`、`商品主图`、`方形社媒图` -> `size=1024x1024`
- `海报`、`封面`、`人物半身/全身`、`竖版构图`、`小红书封面` -> `size=1024x1536`
- `横幅`、`banner`、`视频封面`、`演示背景`、`横版构图` -> `size=1536x1024`
- `手机壁纸`、`竖屏壁纸`、`短视频封面`、`9:16` -> `size=2160x3840`
- `桌面壁纸`、`4k横向壁纸`、`16:9` -> `size=3840x2160`
- `高清`、`精细`、`商用`、`主视觉`、`壁纸`、`海报`、`产品图` -> `quality=high`
- `草图`、`快速预览`、`低成本试稿` -> `quality=low`
- `透明背景`、`无背景`、`抠图`、`贴纸`、`图标`、`logo` 且不是完整场景图 -> `background=transparent`
- `白底`、`黑底` -> 分别映射 `background=white`、`background=black`
- `多方案`、`给几个版本` 且没有明确数量 -> `n=3`
- 改图时，`保持脸/人物/主体/产品一致`、`只改风格` -> `input_fidelity=high`
- 改图时，`大幅重绘`、`重新设计`、`完全换风格` -> 不设置 `input_fidelity`，或在用户明确要求低保真时设置 `input_fidelity=low`

保守原则：
- 不要仅因为 prompt 很长就自动选择 4k；只有用户用途明显需要壁纸、大幅展示、16:9/9:16，或明确提到 4k 时才用 4k 尺寸。
- 不要擅自推断 `model`、`moderation`、`partial_images`。这些字段只有用户明确要求时才传。
- `output_compression` 只在用户明确要求压缩、小体积、控制文件大小，且输出格式为 `jpg/jpeg/webp` 时传。
- `output_format` 优先按用户明确要求；若推断 `background=transparent` 且用户未指定格式，使用 `png`。
- 推断出的字段只作为接口参数传递，不要从原始 prompt 中删除对应语义；prompt 应尽量保留用户完整意图。

## 执行步骤

### 1. 整理参数

从用户消息或 `$ARGUMENTS` 中整理出：
- `mode`: `generate` 或 `edit`
- `prompt`
- `image`（改图时）
- `mask`（如果用户明确提供）
- 其他可选字段

### 2. 缺字段就停下来问

缺少必填字段时，不要调用脚本。

### 3. 调用脚本

使用 Bash 调用 Python 脚本。脚本路径应通过 skill 所在目录推导，不要写死绝对路径。

不要固定使用某一种 Python 启动方式。先测试本机可用启动器，选择第一个能运行 Python 3.11+ 且能导入 `tomllib` 的命令。

推荐探测顺序：
- `python3.12`
- `python3.11`
- `python3`
- `python`
- `py -3.12`
- `py -3.11`
- `py -3`
- `uv run --python 3.12 python`

推荐探测命令：

```bash
choose_python_cmd() {
  for cmd in \
    "python3.12" \
    "python3.11" \
    "python3" \
    "python" \
    "py -3.12" \
    "py -3.11" \
    "py -3" \
    "uv run --python 3.12 python"; do
    if sh -c "$cmd - <<'PY'
import sys
import tomllib
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY" >/dev/null 2>&1; then
      printf '%s\n' "$cmd"
      return 0
    fi
  done
  return 1
}
python_cmd=$(choose_python_cmd) || {
  echo "未找到可用的 Python 3.11+ 启动方式"
  exit 1
}
```

后续调用统一使用探测出的 `$python_cmd`。注意 `$python_cmd` 可能包含多个词（例如 `uv run --python 3.12 python`），调用时不要把 `$python_cmd` 整体加引号；脚本路径和参数值仍然按需加引号。

推荐调用方式：

```bash
$python_cmd "<skill-dir>/scripts/gen_images.py" --mode generate --prompt "..."
```

或：

```bash
$python_cmd "<skill-dir>/scripts/gen_images.py" --mode edit --prompt "..." --image "..."
```

### 3.1 timeout 计算规则

`timeout` 规则以 `references/fields.md` 为准。

在发起 Bash 工具调用前，先按 `references/fields.md` 中的 `timeout 规则` 计算本次调用的 `timeout`，不要把 timeout 判断交给脚本。

### 3.2 Bash 调用模板

文生图：
- 先按上面的规则算出 `timeout`
- 然后调用 Bash，工具调用的 `timeout` 参数必须使用刚算出的值

示例：

```bash
$python_cmd "<skill-dir>/scripts/gen_images.py" --mode generate --prompt "..." --size "1024x1024"
```

对应工具调用要求：
- `size=1024x1024` -> `timeout=600000`

```bash
$python_cmd "<skill-dir>/scripts/gen_images.py" --mode generate --prompt "..." --size "3840x2160"
```

对应工具调用要求：
- `size=3840x2160` -> `timeout=900000`

改图同理：

```bash
$python_cmd "<skill-dir>/scripts/gen_images.py" --mode edit --prompt "..." --image "..." --size "2160x3840"
```

对应工具调用要求：
- `size=2160x3840` -> `timeout=900000`

根据已提取到的字段，继续附加参数：
- `--size`
- `--quality`
- `--background`
- `--output-format`
- `--n`
- `--moderation`
- `--output-compression`
- `--partial-images`
- `--input-fidelity`
- `--mask`

## 脚本行为

`scripts/gen_images.py` 会：
- 先基于 `scripts/gen_images.py` 自身所在目录向上逐级检查祖先目录名是否为 `.codex` 或 `.claude`，据此判断当前调用者
- 找到 `.codex/` 时按 Codex 调用处理，读取 `~/.codex/config.toml` 中的 `model_provider`，再读取 `model_providers.<当前 model_provider>.base_url`
- 找到 `.claude/` 时按 Claude 调用处理，读取 `~/.claude/settings.json` 中的 `env.ANTHROPIC_BASE_URL` 与 `env.ANTHROPIC_AUTH_TOKEN`
- Codex 调用时再读取 `~/.codex/auth.json` 中的 `OPENAI_API_KEY`
- 如果无法判定当前调用者，则按回退顺序先尝试 Codex 配置，再尝试 Claude 配置
- 使用 `Authorization: Bearer <token>` 调用接口
- Claude 调用时，文生图走 `/v1/images/generations`，改图走 `/v1/images/edits`
- Codex 调用时，文生图直接走 `/images/generations`，改图直接走 `/images/edits`
- 将返回图片保存到当前工作目录下的 `./gen-images/`
- 输出 JSON 结果

## 结果处理

脚本成功时会输出 JSON，例如：

```json
{"ok": true, "paths": ["..."], "used_params": {"model": "gpt-image-2", "size": "1024x1024", "quality": "high", "output_format": "png", "n": 1}}
```

脚本失败时会输出 JSON，例如：

```json
{"ok": false, "error": "缺少 prompt"}
```

### 成功回复格式

向用户输出：

- `图片已生成, 图片路径: <路径>`
- `实际使用的关键参数: model=..., size=..., quality=..., output_format=..., n=...`

如果生成多张图片，列出所有路径。

### 失败回复格式

向用户输出：

- `生成失败: <简短错误原因>`

## 注意事项

- 不要在缺少必填字段时猜测用户意图
- 不要为可选字段做冗长说明
- 改图时，本地路径、URL、data URL 都要支持
- 除非用户明确要求，不要增加接口里没有的自定义字段
- 调用完成后，优先返回结果，不要输出多余解释
