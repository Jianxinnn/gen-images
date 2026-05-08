---
name: figforge-gen
description: Use when user requests image generation, image editing, text-to-image (文生图), image editing (改图), 修改图片, 编辑图片, "使用 gpt-image-2", or invokes /figforge-gen. Calls gpt-image-2 via CLIProxyAPI.
argument-hint: <自然语言需求>
allowed-tools: [Bash, Read]
---

# figforge-gen

调用 CLIProxyAPI 上的 `gpt-image-2` 完成文生图与改图。支持自动触发与 `/figforge-gen ...` 手动调用。

## 资源

- `references/fields.md` — 字段定义、自然语言映射、LLM 推断规则、timeout 规则(权威单一来源)
- `references/api-config.md` — API 配置优先级、原子性约束、预检流程
- `scripts/figforge_gen.py` — 接口调用脚本
- `scripts/choose_python.sh` — 探测可用 Python 3.11+

手动调用时需求即 `$ARGUMENTS`:

```text
/figforge-gen 生成一张透明背景的猫咪头像,1024x1024,png
/figforge-gen 把 ./input.png 改成水彩风,保留主体,输出 webp
```

## 任务分类

- **文生图**:`生成图片`、`文生图`、`画一张图`、`用 gpt-image-2 生成`
- **改图**:`修改图片`、`编辑图片`、`改图`、`把这张图改成...`

同时出现图片来源(本地路径/URL/data URL)与修改意图 → 按**改图**处理。

## 必填字段与追问

缺字段时**先问,不执行**:

| 任务 | 缺什么 | 追问话术 |
|------|--------|----------|
| 文生图 | `prompt` | `请补充图片提示词,例如你想生成什么画面。` |
| 改图 | 图片来源 | `请提供要编辑的图片来源:1)本地路径 2)图片 URL / data URL` |
| 改图 | `prompt` | `请补充修改要求,例如你想把图片改成什么效果。` |

## 字段提取

**优先级**:用户明确字段值 > 自然语言明确要求 > LLM 保守推断 > 脚本默认值。

完整映射表与推断规则见 `references/fields.md`。要点:

- 用途明显时(头像/壁纸/海报/banner/logo...)可保守推断 `size`、`quality`、`background`、`output_format`、`n`、`input_fidelity`
- 信心不足 → 省略,使用脚本默认值,**不要为可选字段反复追问**
- `model`、`moderation`、`partial_images`、`output_compression` 默认不推断
- 推断出的字段只作为接口参数,**不要从原始 prompt 中删除对应语义**

直接从终端调用 `scripts/figforge_gen.py` 时,脚本不会自己推断;只有通过本 skill 由 LLM 整理参数时才发生这些推断。

## 执行步骤

### 1. 确定 task_cwd 与输出目录

`task_cwd` = 用户当前打开的项目/工作区目录。**不是** skill 安装目录、脚本目录、`$CODEX_HOME`、`~/.codex/generated_images/`。

默认输出目录 `<task_cwd>/figforge-gen/`。用户指定其他目录时,相对路径按 `task_cwd` 解析。

`--out-dir` 是本地保存参数,**不进入 API payload**。

### 2. 探测 Python

```bash
python_cmd=$(bash "<skill-dir>/scripts/choose_python.sh") || { echo "未找到可用 Python 3.11+"; exit 1; }
```

`$python_cmd` 可能含多个词(如 `uv run --python 3.12 python`)。在 `zsh -lc` 中使用时,先用 `python_argv=(${=python_cmd})` 拆成 argv,再用 `"${python_argv[@]}"` 调用。

### 3. API 配置预检(每次会话首次调用前)

```bash
zsh -lc 'source ~/.zshrc >/dev/null 2>&1 || true; cd "<task-cwd>" || exit 1; python_cmd=$(bash "<skill-dir>/scripts/choose_python.sh") || { echo "未找到可用 Python 3.11+"; exit 1; }; python_argv=(${=python_cmd}); "${python_argv[@]}" "<skill-dir>/scripts/figforge_gen.py" --show-config'
```

只检查输出 JSON 的 `ok`、`source`、`base_url`、`model`、`token_present`。**不要打印、读取、复制或拼接完整 token**。

预检失败处理与配置原子性约束见 `references/api-config.md`。

### 4. 计算 timeout

按 `references/fields.md` 的 `timeout 规则`,根据 `size` × `n` 决定本次 Bash 工具调用的 `timeout` 参数:

- 单张基准:总像素 ≥ 8,000,000(4k 级) → `900000`(15 分钟);其余 / `auto` / 无法解析 → `600000`(10 分钟)
- 实际 `timeout = 单张基准 × n`(脚本对 `n` 串行调用,必须按张累加)
- 超过 Bash 工具上限时取上限即可

### 5. 调用脚本

文生图:

```bash
zsh -lc 'source ~/.zshrc >/dev/null 2>&1 || true; cd "<task-cwd>" || exit 1; python_cmd=$(bash "<skill-dir>/scripts/choose_python.sh") || { echo "未找到可用 Python 3.11+"; exit 1; }; python_argv=(${=python_cmd}); "${python_argv[@]}" "<skill-dir>/scripts/figforge_gen.py" --mode generate --prompt "..." --out-dir "<task-cwd>/figforge-gen"'
```

改图:加 `--mode edit --image "..."`(可选 `--mask`)。

按已提取字段附加可选参数:
`--size --quality --background --output-format --n --moderation --output-compression --partial-images --input-fidelity --no-stream --model --api-base --api-key --api-key-env --config`

`--no-stream` 仅在用户明确要求非流式或 Responses 端点不可用排查时使用。

## 结果输出

脚本成功返回 `{"ok": true, "paths": [...], "used_params": {...}}`,向用户输出:

```text
图片已生成, 图片路径: <路径>
实际使用的关键参数: model=..., size=..., quality=..., output_format=..., n=..., stream=..., out_dir=...
```

多张图片列出全部路径。

脚本失败返回 `{"ok": false, "error": "..."}`,向用户输出:

```text
生成失败: <简短错误原因>
```

## 注意事项

- 缺必填字段不要猜测
- 不要为可选字段做冗长说明
- 改图支持本地路径、URL、data URL
- 不要为接口添加未定义的自定义字段
- 调用完成后优先返回结果,不要输出多余解释
