#!/usr/bin/env python3
import argparse
import base64
import json
import mimetypes
import os
import re
import sys
import time
import tomllib
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


DEFAULT_MODEL = "gpt-image-2"
IMAGE_FIELDS = [
    "size",
    "quality",
    "background",
    "output_format",
    "output_compression",
    "moderation",
]
RESPONSES_TOOL_FIELDS = [
    "quality",
    "background",
    "output_format",
    "output_compression",
    "moderation",
    "input_fidelity",
]


class RuntimeSettings:
    def __init__(self, source: str, base_url: str, token: str, model: str):
        self.source = source
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.model = model or DEFAULT_MODEL


class ApiHTTPError(RuntimeError):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"HTTP {code}: {message}")


def fail(message: str, status_code: int = 1):
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
    sys.exit(status_code)


def load_json(path: Path, label: str):
    if not path.exists():
        raise RuntimeError(f"未找到配置文件: {path}")

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"读取{label}失败: {exc}") from exc


def load_toml(path: Path, label: str):
    if not path.exists():
        raise RuntimeError(f"未找到配置文件: {path}")

    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"读取{label}失败: {exc}") from exc


def flatten_api_config(data: dict):
    api = data.get("api") if isinstance(data.get("api"), dict) else {}
    merged = dict(data)
    merged.update(api)
    return merged


def get_config_paths(args):
    if args.config:
        return [(Path(args.config).expanduser(), True, "--config")]

    env_path = os.environ.get("FIGFORGE_GEN_CONFIG")
    if env_path:
        return [(Path(env_path).expanduser(), True, "FIGFORGE_GEN_CONFIG")]

    paths = []
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        paths.append((Path(xdg_config_home).expanduser() / "figforge-gen" / "config.toml", False, "XDG_CONFIG_HOME"))
    paths.extend([
        (Path.home() / ".config" / "figforge-gen" / "config.toml", False, "user config"),
        (Path.home() / ".figforge-gen" / "config.toml", False, "alternate user config"),
    ])
    return paths


def load_figforge_gen_config(args):
    for path, required, source in get_config_paths(args):
        if path.exists():
            return flatten_api_config(load_toml(path, f"figforge-gen config ({source})")), path
        if required:
            raise RuntimeError(f"未找到 figforge-gen 配置文件: {path}")
    return {}, None


def get_config_value(config: dict, *names):
    for name in names:
        value = config.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def read_env_token(env_name: str | None, source: str):
    if not env_name:
        return None, None
    token = os.environ.get(env_name)
    if not token:
        raise RuntimeError(
            f"{source} 指定了 {env_name}，但环境变量未设置；"
            "如果 key 写在 ~/.zshrc 中，请先 source 用户 shell 配置后再运行；"
            "不要用其他配置源的 token 临时注入该变量"
        )
    return token, f"{source}:{env_name}"


def resolve_model(args, config: dict):
    return (
        args.model
        or os.environ.get("FIGFORGE_GEN_MODEL")
        or get_config_value(config, "model")
        or DEFAULT_MODEL
    )


def load_direct_settings(args, config: dict, config_path: Path | None, model: str):
    base_url = (
        args.api_base
        or os.environ.get("FIGFORGE_GEN_API_BASE")
        or get_config_value(config, "base_url", "api_base")
    )

    token = None
    token_source = None

    if args.api_key:
        token = args.api_key
        token_source = "--api-key"
    elif args.api_key_env:
        token, token_source = read_env_token(args.api_key_env, "--api-key-env")
    elif os.environ.get("FIGFORGE_GEN_API_KEY"):
        token = os.environ["FIGFORGE_GEN_API_KEY"]
        token_source = "FIGFORGE_GEN_API_KEY"
    else:
        config_key_env = get_config_value(config, "api_key_env", "token_env")
        if config_key_env:
            token, token_source = read_env_token(config_key_env, "figforge-gen config api_key_env")
        else:
            token = get_config_value(config, "api_key", "token")
            if token:
                token_source = "figforge-gen config api_key"

    config_value = get_config_value(
        config,
        "base_url",
        "api_base",
        "api_key",
        "token",
        "api_key_env",
        "token_env",
    )
    has_direct_config = any([
        args.api_base,
        args.api_key,
        args.api_key_env,
        os.environ.get("FIGFORGE_GEN_API_BASE"),
        config_value,
    ])

    if not has_direct_config:
        return None

    if not base_url:
        raise RuntimeError("已检测到 figforge-gen 独立 API 配置，但缺少 base_url")
    if not token:
        hint = "请设置 api_key、api_key_env，或环境变量 FIGFORGE_GEN_API_KEY"
        if config_path:
            hint = f"{hint}；当前配置文件: {config_path}"
        raise RuntimeError(f"已检测到 figforge-gen 独立 API 配置，但缺少 API key。{hint}")

    source_parts = ["figforge-gen"]
    if config_path:
        source_parts.append(str(config_path))
    if args.api_base or args.api_key or args.api_key_env:
        source_parts.append("cli")
    if os.environ.get("FIGFORGE_GEN_API_BASE") or os.environ.get("FIGFORGE_GEN_API_KEY"):
        source_parts.append("env")
    source_parts.append(token_source or "token")
    return RuntimeSettings("+".join(source_parts), str(base_url), token, model)


def load_claude_settings(model: str):
    settings_path = Path.home() / ".claude" / "settings.json"
    data = load_json(settings_path, "Claude settings.json")

    env = data.get("env") or {}
    base_url = env.get("ANTHROPIC_BASE_URL")
    token = env.get("ANTHROPIC_AUTH_TOKEN")

    if not base_url:
        raise RuntimeError("settings.json 中缺少 env.ANTHROPIC_BASE_URL")
    if not token:
        raise RuntimeError("settings.json 中缺少 env.ANTHROPIC_AUTH_TOKEN")

    base_url = str(base_url).rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"
    return RuntimeSettings("claude", base_url, token, model)


def load_codex_settings(model: str):
    config_path = Path.home() / ".codex" / "config.toml"
    auth_path = Path.home() / ".codex" / "auth.json"

    config = load_toml(config_path, "Codex config.toml")
    auth = load_json(auth_path, "Codex auth.json")

    provider_name = config.get("model_provider")
    if not provider_name:
        raise RuntimeError("config.toml 中缺少 model_provider")

    model_providers = config.get("model_providers") or {}
    active_provider = model_providers.get(provider_name) or {}
    base_url = active_provider.get("base_url")
    token = auth.get("OPENAI_API_KEY")

    if not base_url:
        raise RuntimeError(f"config.toml 中缺少 model_providers.{provider_name}.base_url")
    if not token:
        raise RuntimeError("auth.json 中缺少 OPENAI_API_KEY")

    return RuntimeSettings(f"codex:{provider_name}", str(base_url), str(token), model)


def detect_caller_from_script_dir():
    current = Path(__file__).resolve().parent
    directories = (current, *current.parents)

    for directory in directories:
        if directory.name == ".codex":
            return "codex"

    for directory in directories:
        if directory.name == ".claude":
            return "claude"

    return None


def load_runtime_settings(args):
    config, config_path = load_figforge_gen_config(args)
    model = resolve_model(args, config)

    direct_settings = load_direct_settings(args, config, config_path, model)
    if direct_settings:
        return direct_settings

    caller = detect_caller_from_script_dir()
    if caller == "claude":
        return load_claude_settings(model)
    if caller == "codex":
        return load_codex_settings(model)

    errors = []
    for name, loader in (("codex", load_codex_settings), ("claude", load_claude_settings)):
        try:
            return loader(model)
        except RuntimeError as exc:
            errors.append(f"{name}: {exc}")

    raise RuntimeError("; ".join(errors))


def file_to_data_url(path_str: str):
    path = Path(path_str)
    if not path.exists():
        fail(f"图片文件不存在: {path_str}")
    data = path.read_bytes()
    mime, _ = mimetypes.guess_type(str(path))
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime or 'application/octet-stream'};base64,{b64}"


def normalize_image_source(image_value: str):
    if image_value.startswith("http://") or image_value.startswith("https://") or image_value.startswith("data:"):
        return image_value
    return file_to_data_url(image_value)


DATA_URL_RE = re.compile(r"^data:(?P<mime>[^;]+);base64,(?P<data>.+)$", re.IGNORECASE)


def parse_data_url(data_url: str):
    match = DATA_URL_RE.match(data_url)
    if not match:
        fail("返回的 data URL 格式无效")
    mime = match.group("mime")
    raw = match.group("data")
    try:
        data = base64.b64decode(raw)
    except Exception as exc:
        fail(f"解析返回图片失败: {exc}")
    return mime, data


def choose_extension(output_format: str | None, mime: str | None = None):
    if output_format:
        normalized = output_format.lower()
        if normalized == "jpeg":
            return "jpg"
        return normalized
    if mime:
        ext = mimetypes.guess_extension(mime)
        if ext:
            return ext.lstrip(".").replace("jpe", "jpg")
    return "png"


def resolve_output_dir(out_dir: str | None):
    if out_dir:
        output_dir = Path(out_dir).expanduser()
        if not output_dir.is_absolute():
            output_dir = Path.cwd() / output_dir
        return output_dir
    return Path.cwd() / "figforge-gen"


def save_images(image_entries, output_format: str | None, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    paths = []

    for index, item in enumerate(image_entries, start=1):
        ext = choose_extension(output_format)
        if item.get("b64_json"):
            try:
                binary = base64.b64decode(item["b64_json"])
            except Exception as exc:
                fail(f"解码返回图片失败: {exc}")
        elif item.get("url", "").startswith("data:"):
            mime, binary = parse_data_url(item["url"])
            ext = choose_extension(output_format, mime)
        else:
            fail("接口返回中未找到可保存的图片数据")

        file_path = output_dir / f"{timestamp}-{index:02d}.{ext}"
        file_path.write_bytes(binary)
        paths.append(str(file_path))

    return paths


def read_http_error(exc: urllib.error.HTTPError):
    try:
        raw = exc.read().decode("utf-8")
        data = json.loads(raw)
        return data.get("error", {}).get("message") or data.get("message") or raw
    except Exception:
        return exc.reason or f"HTTP {exc.code}"


def build_request(url: str, token: str, payload: dict, accept: str):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": accept,
            "User-Agent": "curl/8.7.1",
            "Authorization": f"Bearer {token}",
        },
    )


def post_json(url: str, token: str, payload: dict):
    req = build_request(url, token, payload, "application/json")
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        fail(f"接口调用失败: {read_http_error(exc)}")
    except urllib.error.URLError as exc:
        fail(f"网络请求失败: {exc.reason}")


def find_final_image_b64(value):
    if isinstance(value, dict):
        if value.get("type") == "image_generation_call":
            result = value.get("result") or value.get("b64_json")
            if isinstance(result, str) and result:
                return result
        for child in value.values():
            result = find_final_image_b64(child)
            if result:
                return result
    elif isinstance(value, list):
        for child in value:
            result = find_final_image_b64(child)
            if result:
                return result
    return None


def post_responses_stream(url: str, token: str, payload: dict):
    req = build_request(url, token, payload, "text/event-stream")
    latest_partial_b64 = None
    final_b64 = None
    partial_count = 0
    started_at = time.monotonic()

    try:
        with urllib.request.urlopen(req) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue

                payload_str = line[5:].strip()
                if payload_str == "[DONE]":
                    break

                try:
                    event = json.loads(payload_str)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type", "")
                if event_type == "response.image_generation_call.partial_image":
                    partial = event.get("partial_image_b64")
                    if partial:
                        latest_partial_b64 = partial
                        partial_count += 1
                        elapsed = time.monotonic() - started_at
                        print(
                            f"[partial #{partial_count} elapsed={elapsed:.1f}s]",
                            file=sys.stderr,
                            flush=True,
                        )
                    continue

                if event_type == "response.failed":
                    error = event.get("response", {}).get("error") or event.get("error") or {}
                    message = error.get("message") if isinstance(error, dict) else str(error)
                    raise RuntimeError(message or "Responses 流式请求失败")

                result = find_final_image_b64(event)
                if result:
                    final_b64 = result
    except urllib.error.HTTPError as exc:
        raise ApiHTTPError(exc.code, read_http_error(exc)) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"网络请求失败: {exc.reason}") from exc

    result_b64 = final_b64 or latest_partial_b64
    if not result_b64:
        raise RuntimeError("接口返回中未找到可保存的图片数据")
    return result_b64


def should_fall_back_to_images(error: ApiHTTPError):
    if error.code in (400, 404, 405, 415, 422):
        return True
    if error.code == 503 and "/v1/images/generations" in error.message:
        return True
    return False


def add_optional_fields(target: dict, args, fields):
    for field in fields:
        value = getattr(args, field, None)
        if value is not None:
            target[field] = value


def build_images_payload(args):
    if not args.prompt:
        fail("缺少 prompt")

    payload = {
        "model": args.model or DEFAULT_MODEL,
        "prompt": args.prompt,
        "response_format": "b64_json",
        "stream": False,
        "n": args.n or 1,
    }

    fields = list(IMAGE_FIELDS)
    if args.mode == "edit":
        if not args.image:
            fail("缺少要编辑的图片来源")
        payload["images"] = [{"image_url": normalize_image_source(args.image)}]
        fields.append("input_fidelity")
        if args.mask:
            payload["mask"] = {"image_url": normalize_image_source(args.mask)}

    add_optional_fields(payload, args, fields)
    return payload


def build_responses_payload(args, default_partial_images: bool = True):
    if not args.prompt:
        fail("缺少 prompt")

    tool_cfg = {"type": "image_generation"}
    if args.size and args.size != "auto":
        tool_cfg["size"] = args.size

    add_optional_fields(tool_cfg, args, RESPONSES_TOOL_FIELDS)

    # Ask the backend to flush at least one image event, reducing proxy
    # read-timeout risk for long generations.
    if args.partial_images is not None:
        tool_cfg["partial_images"] = args.partial_images
    elif default_partial_images:
        tool_cfg["partial_images"] = 1

    if args.mode == "generate":
        input_data = args.prompt
    else:
        if not args.image:
            fail("缺少要编辑的图片来源")
        input_data = [
            {
                "role": "user",
                "content": [
                    {"type": "input_image", "image_url": normalize_image_source(args.image)},
                    {"type": "input_text", "text": args.prompt},
                ],
            }
        ]

    return {
        "model": args.model or DEFAULT_MODEL,
        "input": input_data,
        "tools": [tool_cfg],
        "stream": True,
    }


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["generate", "edit"])
    parser.add_argument("--prompt")
    parser.add_argument("--model")
    parser.add_argument("--config")
    parser.add_argument("--api-base", dest="api_base")
    parser.add_argument("--api-key", dest="api_key")
    parser.add_argument("--api-key-env", dest="api_key_env")
    parser.add_argument("--show-config", action="store_true")
    parser.add_argument("--image")
    parser.add_argument("--mask")
    parser.add_argument("--size")
    parser.add_argument("--quality")
    parser.add_argument("--background")
    parser.add_argument("--output-format", dest="output_format")
    parser.add_argument("--output-compression", dest="output_compression", type=int)
    parser.add_argument("--out-dir", "--output-dir", dest="out_dir")
    parser.add_argument("--partial-images", dest="partial_images", type=int)
    parser.add_argument("--n", type=int)
    parser.add_argument("--moderation")
    parser.add_argument("--input-fidelity", dest="input_fidelity")
    parser.add_argument("--stream", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--dry-run", dest="dry_run", action="store_true")
    return parser.parse_args()


def print_runtime_settings(settings: RuntimeSettings):
    print(json.dumps({
        "ok": True,
        "source": settings.source,
        "base_url": settings.base_url,
        "model": settings.model,
        "token_present": bool(settings.token),
    }, ensure_ascii=False))


def redact_payload_for_output(value):
    if isinstance(value, dict):
        redacted = {}
        for key, child in value.items():
            if key == "image_url":
                redacted[key] = "<redacted image_url>"
            else:
                redacted[key] = redact_payload_for_output(child)
        return redacted
    if isinstance(value, list):
        return [redact_payload_for_output(item) for item in value]
    return value


def main():
    args = parse_args()
    try:
        settings = load_runtime_settings(args)
    except RuntimeError as exc:
        fail(str(exc))

    if args.show_config:
        print_runtime_settings(settings)
        return

    if not args.mode:
        fail("缺少 mode")

    args.model = settings.model

    if args.dry_run:
        if args.stream and not (args.mode == "edit" and args.mask):
            url = f"{settings.base_url}/responses"
            payload = build_responses_payload(args)
        else:
            endpoint = "/images/generations" if args.mode == "generate" else "/images/edits"
            url = f"{settings.base_url}{endpoint}"
            payload = build_images_payload(args)
        print(json.dumps({
            "ok": True,
            "dry_run": True,
            "url": url,
            "payload": redact_payload_for_output(payload),
        }, ensure_ascii=False))
        return

    stream_used = False
    response = None

    if args.stream and not (args.mode == "edit" and args.mask):
        try:
            url = f"{settings.base_url}/responses"
            image_entries = []
            for _ in range(args.n or 1):
                try:
                    payload = build_responses_payload(args)
                    b64_json = post_responses_stream(url, settings.token, payload)
                except ApiHTTPError as exc:
                    if args.partial_images is not None or exc.code not in (400, 422):
                        raise
                    payload = build_responses_payload(args, default_partial_images=False)
                    b64_json = post_responses_stream(url, settings.token, payload)
                image_entries.append({"b64_json": b64_json})
            response = {"data": image_entries}
            stream_used = True
        except ApiHTTPError as exc:
            if not should_fall_back_to_images(exc):
                fail(f"接口调用失败: {exc}")
        except RuntimeError as exc:
            fail(str(exc))

    if response is None:
        payload = build_images_payload(args)
        endpoint = "/images/generations" if args.mode == "generate" else "/images/edits"
        url = f"{settings.base_url}{endpoint}"
        response = post_json(url, settings.token, payload)

    data = response.get("data")
    if not isinstance(data, list) or not data:
        fail("接口返回中缺少 data")

    output_dir = resolve_output_dir(args.out_dir)
    used_params = {
        "model": settings.model,
        "size": args.size,
        "quality": args.quality,
        "background": args.background,
        "output_format": args.output_format or "png",
        "n": args.n or 1,
        "stream": stream_used,
        "out_dir": str(output_dir),
    }
    if args.mode == "edit" and args.input_fidelity is not None:
        used_params["input_fidelity"] = args.input_fidelity

    paths = save_images(data, args.output_format, output_dir)
    print(json.dumps({"ok": True, "paths": paths, "used_params": used_params}, ensure_ascii=False))


if __name__ == "__main__":
    main()
