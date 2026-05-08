# figforge-gen API 配置

## 优先级链(从高到低)

1. **命令行参数**:`--api-base`、`--api-key`、`--api-key-env`、`--model`
2. **独立环境变量**:`FIGFORGE_GEN_API_BASE`、`FIGFORGE_GEN_API_KEY`、`FIGFORGE_GEN_MODEL`
3. **独立配置文件**:
   - `$FIGFORGE_GEN_CONFIG`
   - `$XDG_CONFIG_HOME/figforge-gen/config.toml`
   - `~/.config/figforge-gen/config.toml`
   - `~/.figforge-gen/config.toml`
4. **Codex 配置**:`~/.codex/config.toml` + `~/.codex/auth.json`
   - 需要 `model_provider`、`model_providers.<当前 provider>.base_url`、`OPENAI_API_KEY`(provider 名不要求是 `OpenAI`)
5. **Claude Code 配置**:`~/.claude/settings.json` 中 `env.ANTHROPIC_BASE_URL` + `env.ANTHROPIC_AUTH_TOKEN`

脚本会基于自身所在目录向上检查祖先目录是否为 `.codex` 或 `.claude` 来决定优先尝试哪个回退。

## 配置文件字段

API 连接配置只包含:

- `base_url` / `api_base`
- `api_key` / `token`
- `api_key_env` / `token_env`
- `model`

**不要写入** `size`、`quality`、`output_format`、`out_dir` 等生成 / 本地参数。

## 配置原子性(关键)

任意一次调用,`base_url` 与 `token` **必须来自同一配置源**。常见错误组合:

- ❌ `~/.codex/auth.json` 的 token + 独立配置的 `base_url`
- ❌ 独立配置的 token + Codex / Claude 的 `base_url`
- ❌ 临时 export 其他配置源的 key 来"绕过"配置错误(除非用户明确要求临时覆盖)

正确做法:如果独立配置指定 `api_key_env`,在同一 shell 里 `source` 用户环境后让脚本自己解析,**不要手动注入 key**。

## 预检

每次会话首次调用前:

```bash
zsh -lc 'source ~/.zshrc >/dev/null 2>&1 || true; cd "<task-cwd>" || exit 1; python_cmd=$(bash "<skill-dir>/scripts/choose_python.sh") || { echo "未找到可用 Python 3.11+"; exit 1; }; python_argv=(${=python_cmd}); "${python_argv[@]}" "<skill-dir>/scripts/figforge_gen.py" --show-config'
```

只检查输出 JSON 的:

- `ok`
- `source`
- `base_url`
- `model`
- `token_present`

**永远不要**打印、读取、复制或拼接完整 token。

## 预检失败处理

`token_present=false` 或脚本报 `api_key_env ... 环境变量未设置` 时:

1. 先尝试 `source ~/.zshrc`(或对应 shell 配置)
2. 仍失败 → 让用户设置对应环境变量

## 推荐配置

`~/.config/figforge-gen/config.toml`:

```toml
[api]
base_url = "https://your-api-base/v1"
api_key_env = "FIGFORGE_GEN_API_KEY"
model = "gpt-image-2"
```

shell 中:

```bash
export FIGFORGE_GEN_API_KEY="sk-..."
```

`base_url` 应填版本化的 API base(如 `https://your-api-base/v1`),脚本会自动拼接 `/responses`、`/images/generations`、`/images/edits`。

## 后端端点

| 调用模式 | Responses (流式优先) | Images (回退) |
|---------|---------------------|--------------|
| Codex | `POST <base>/responses` | `POST <base>/images/generations`、`POST <base>/images/edits` |
| Claude Code | `POST <base>/v1/responses` | `POST <base>/v1/images/generations`、`POST <base>/v1/images/edits` |

回退条件:

- Responses 端点返回兼容性错误(400/404/405/415/422)
- Responses 端点返回明确的 Images-only 兼容错误(例如 `gpt-image-2 is only supported on /v1/images/generations and /v1/images/edits`)
- 改图请求带 `mask`
- 用户传 `--no-stream`

如果只设置了 `FIGFORGE_GEN_API_KEY` 但没有 `FIGFORGE_GEN_API_BASE` 或配置文件
`base_url`,脚本不会把它当作完整独立配置;这允许旧环境变量残留时继续回退到
Codex / Claude 配置。完整独立配置仍必须提供匹配的 `base_url` 与 token 来源。
