# gen-images

给 Codex / Claude Code 用的图片生成 / 改图 skill，适用于通过 CLIProxyAPI 调用 `gpt-image-2` 的场景。

![gen-images 架构图](assets/architecture.png)

## 来源与改动说明

本项目基于 Linux.do 讨论帖整理和改造：

- https://linux.do/t/topic/2042175

本仓库在原始思路基础上做了以下调整，目标是让它更适合在 Codex、Claude Code 以及其他可执行 Bash 的 Agent 环境中复用：

- 支持 Codex 配置读取，按 `~/.codex/config.toml` 中当前 `model_provider` 读取对应 `base_url`，不再假设 provider 名称必须是 `OpenAI`
- 支持 `gen-images` 独立 API 配置，优先级高于 Codex / Claude Code 全局配置
- 保留 Claude Code 配置回退，Codex 配置不可用时再读取 `~/.claude/settings.json`
- 将 Python 启动方式改为探测式选择，优先使用本机可用的 Python 3.11+，`uv` 仅作为兜底选项
- 增加 LLM 参数整理规则，可根据用户 prompt 保守推断 `size`、`quality`、`background`、`output_format`、`n`、`input_fidelity`
- 增加 `--model` 支持说明，允许在后端开放时指定如 `pro/gpt-image-2` 等模型
- 默认优先使用 Responses API SSE 流式生成，降低长耗时图片请求被代理读超时中断的概率
- 为 HTTP 请求补充 `Accept` 与 `User-Agent` 请求头，避免部分反代链路拒绝 Python 默认请求
- 修正文档中的目录名、配置读取顺序和直接脚本调用示例

## 功能

- 支持文生图
- 支持改图 / 编辑图片
- 默认优先走流式 Responses API，必要时回退旧的非流式 Images API
- 支持自动触发
- 支持手动使用 `/gen-images ...`
- 优先读取 `gen-images` 独立 API 配置；没有独立配置时回退 Codex / Claude Code 配置
- 自动将生成结果保存到当前工作目录下的 `./gen-images/`

## 使用前提

### 1. CLIProxyAPI 版本

要求：

- **CLIProxyAPI >= v6.9.34**

### 2. Python 环境

本 skill 通过 Python 脚本执行实际接口请求，因此本机需要 Python 3.11+ 环境。

建议确认：

```bash
python3 --version
```

### 3. API 配置

本 skill 的 API 配置优先级如下：

1. 命令行显式参数：`--api-base`、`--api-key`、`--api-key-env`、`--model`
2. 独立环境变量：`GEN_IMAGES_API_BASE`、`GEN_IMAGES_API_KEY`、`GEN_IMAGES_MODEL`
3. `gen-images` 独立配置文件
4. Codex 全局配置
5. Claude Code 全局配置

独立配置文件自动检测顺序：

```text
$GEN_IMAGES_CONFIG
$XDG_CONFIG_HOME/gen-images/config.toml
~/.config/gen-images/config.toml
~/.gen-images/config.toml
```

推荐配置：

```toml
[api]
base_url = "https://your-api-base/v1"
api_key_env = "GEN_IMAGES_API_KEY"
model = "gpt-image-2"
```

然后在 shell 中设置：

```bash
export GEN_IMAGES_API_KEY="sk-..."
```

也支持直接写 key，但不推荐长期使用：

```toml
[api]
base_url = "https://your-api-base/v1"
api_key = "sk-..."
model = "gpt-image-2"
```

`base_url` 应填写版本化 API base，例如 `https://your-api-base/v1`。脚本会自动拼接 `/responses`、`/images/generations` 和 `/images/edits`。

可以用下面的命令查看当前实际使用的配置来源。输出不会展示完整 token：

```bash
python3.12 scripts/gen_images.py --show-config
```

如果 key 写在 `~/.zshrc` 里，运行前需要在同一个 shell 中 source 用户环境：

```bash
zsh -lc 'source ~/.zshrc >/dev/null 2>&1 || true; python3.12 scripts/gen_images.py --show-config'
```

不要把不同配置源混在一起使用。尤其不要把 Codex `~/.codex/auth.json` 里的 token 手动注入到 `GEN_IMAGES_API_KEY`，再去调用 `gen-images` 独立配置里的 `base_url`。脚本会按优先级原子解析 `base_url` 和 key；如果独立配置指定了 `api_key_env`，就应该让对应环境变量生效。

### 4. Codex / Claude Code 回退配置

如果没有检测到 `gen-images` 独立 API 配置，脚本会从 Codex 配置读取当前 provider：

```text
~/.codex/config.toml
~/.codex/auth.json
```

需要存在以下字段：

- `model_provider`
- `model_providers.<当前 model_provider>.base_url`
- `OPENAI_API_KEY`

其中 `OPENAI_API_KEY` 是 Codex `auth.json` 里的 token 字段名，不要求 provider 名称必须是 `OpenAI`。

如果 Codex 配置不可用，脚本才会回退读取 Claude Code 配置：

```text
~/.claude/settings.json
```

- `env.ANTHROPIC_BASE_URL`
- `env.ANTHROPIC_AUTH_TOKEN`

### 5. 后端接口支持

反代链路需要支持：

- Codex 模式流式优先：`POST <base_url>/responses`
- Claude Code 模式流式优先：`POST <base_url>/v1/responses`
- Codex 模式：`POST <base_url>/images/generations`、`POST <base_url>/images/edits`
- Claude Code 模式：`POST <base_url>/v1/images/generations`、`POST <base_url>/v1/images/edits`

默认会先尝试 Responses API SSE 流式调用。如果该端点不支持、返回兼容性错误，或改图请求使用 `mask`，脚本会回退到原来的非流式 Images API。

`size`、`quality`、`output_format` 等生成参数不放入 API 配置文件。它们由用户自然语言、skill 的 LLM 参数整理规则和命令行参数控制。

## 目录结构

```text
gen-images/
├── SKILL.md
├── README.md
├── scripts/
│   └── gen_images.py
└── references/
    └── fields.md
```

## 安装方法

将整个 `gen-images` 目录复制到对应 Agent 的 skills 目录。

Claude Code 用户级 skills 目录通常是：

```text
~/.claude/skills/
```

最终路径应为：

```text
~/.claude/skills/gen-images/SKILL.md
~/.claude/skills/gen-images/README.md
~/.claude/skills/gen-images/scripts/gen_images.py
~/.claude/skills/gen-images/references/fields.md
```

Windows 下通常对应：

```text
C:\Users\<用户名>\.claude\skills\gen-images\
```

复制后重启 Claude Code，或执行插件 / skill 重载。

Codex 或其他 Agent 的安装目录以各自的 skill/插件加载规则为准；只要 Agent 能读取 `SKILL.md` 并执行 Bash，就可以按本 skill 的调用逻辑运行。

## 使用方式

### 手动调用

```text
/gen-images 生成一张透明背景的猫咪头像，1024x1024，png
```

```text
/gen-images 把 ./input.png 改成水彩风，保留主体，输出 webp
```

### 直接脚本调用

默认模型是 `gpt-image-2`。如果后端开放了其他图片模型，可以用 `--model` 指定，例如：

```bash
python3.12 scripts/gen_images.py \
  --mode generate \
  --model pro/gpt-image-2 \
  --api-base https://your-api-base/v1 \
  --api-key-env GEN_IMAGES_API_KEY \
  --prompt "一张透明背景的猫咪头像" \
  --size 1024x1024 \
  --output-format png
```

如需排查旧接口，可显式关闭流式：

```bash
python3.12 scripts/gen_images.py \
  --mode generate \
  --no-stream \
  --prompt "一张透明背景的猫咪头像" \
  --size 1024x1024 \
  --output-format png
```

### 自动触发

例如：

```text
使用 gpt-image-2 生成一张透明背景的猫咪头像
```

## 支持的图片来源

改图模式支持：

- 本地文件路径
- 图片 URL
- data URL

如果缺少图片来源，skill 会提示用户补充：

1. 本地路径
2. 图片 URL / data URL

## 支持的 size 规则

当前规则如下：

- `1024x1024`（`1:1`）
- `1024x1536`（`3:4`）
- `1536x1024`（`4:3`）
- `2048x2048`（`1:1`）
- `3840x2160`（`16:9`）
- `2160x3840`（`9:16`）
- `auto`

支持识别这些写法：

```text
1:1
3:4
4:3
16:9
9:16
1024x1024
1024x1536
1536x1024
2048x2048
3840x2160
2160x3840
auto
```

说明：

- `2160x3840`
- `3840x2160`

在当前 `CLIProxyAPI + gpt-image-2` 链路中已实测可用。
但这两个值不等同于 OpenAI 官方公开文档中的标准 size 枚举，属于当前链路下的实测兼容尺寸。

## 常见自然语言映射

例如：

- `高清` -> `quality=high`
- `透明背景` -> `background=transparent`
- `9:16` -> `size=2160x3840`
- `16:9` -> `size=3840x2160`
- `png/webp/jpg/jpeg` -> `output_format`
- `生成3张` -> `n=3`

更完整规则见：

- `references/fields.md`

## 超时规则

Bash 调用 `scripts/gen_images.py` 时，timeout 按图片尺寸自动设置。脚本内部默认走 SSE 流式，这可以让代理链路在长任务中更早收到响应字节；但如果上游在 Cloudflare 超时窗口内完全不 flush 任何事件，仍可能发生 524。

统一规则以 `references/fields.md` 中的 `timeout 规则` 为准：
- 总像素量 `>= 8000000` 的 4k 级尺寸使用 15 分钟
- 其余情况使用 10 分钟
- `auto`、缺少 `size`、或无法解析时，按非 4k 处理

## 输出行为

默认输出目录：

```text
./gen-images/
```

成功时返回类似：

```text
图片已生成, 图片路径: C:\Users\xxx\gen-images\20260424-003204-01.png
实际使用的关键参数: model=gpt-image-2, size=2160x3840, quality=high, output_format=png, n=1, stream=true
```

失败时返回类似：

```text
生成失败: 缺少 prompt
```

## 注意事项

1. 本 skill 依赖 Python 3.11+ 环境
2. 本 skill 优先从 Codex 配置读取 API Base URL 和 Token，必要时回退 Claude Code 配置
3. 使用前请确认 `CLIProxyAPI >= v6.9.34`
4. `2160x3840` / `3840x2160` 为当前链路实测可用，不保证所有后端一致支持
5. 流式可以降低 524 风险，但不能绝对避免所有代理/源站超时；关键在于代理链路要把 SSE 事件及时 flush 出去
6. 如果复杂长提示词在超大尺寸下偶发失败，建议先做最小提示词对照测试

## 相关文件

- `SKILL.md`：skill 主定义与触发规则
- `scripts/gen_images.py`：实际图片接口调用脚本
- `references/fields.md`：字段、映射与交互规则
