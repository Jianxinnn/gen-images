#!/usr/bin/env python3
import argparse
import base64
import json
import mimetypes
import re
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path


DEFAULT_MODEL = "gpt-image-2"


class ApiHTTPError(RuntimeError):
    def __init__(self, code: int, message: str):
        self.code = code
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


def load_claude_settings():
    settings_path = Path.home() / ".claude" / "settings.json"
    data = load_json(settings_path, "Claude settings.json")

    env = data.get("env") or {}
    base_url = env.get("ANTHROPIC_BASE_URL")
    token = env.get("ANTHROPIC_AUTH_TOKEN")

    if not base_url:
        raise RuntimeError("settings.json 中缺少 env.ANTHROPIC_BASE_URL")
    if not token:
        raise RuntimeError("settings.json 中缺少 env.ANTHROPIC_AUTH_TOKEN")

    return base_url.rstrip("/"), token


def load_codex_settings():
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

    return str(base_url).rstrip("/"), str(token)


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


def load_runtime_settings():
    caller = detect_caller_from_script_dir()
    if caller == "claude":
        base_url, token = load_claude_settings()
        return caller, base_url, token
    if caller == "codex":
        base_url, token = load_codex_settings()
        return caller, base_url, token

    errors = []
    for name, loader in (("codex", load_codex_settings), ("claude", load_claude_settings)):
        try:
            base_url, token = loader()
            return name, base_url, token
        except RuntimeError as exc:
            errors.append(f"{name}: {exc}")

    raise RuntimeError("; ".join(errors))


def build_api_url(caller: str, base_url: str, mode: str):
    endpoint = "/images/generations" if mode == "generate" else "/images/edits"
    if caller == "claude":
        return f"{base_url}/v1{endpoint}"
    return f"{base_url}{endpoint}"


def build_responses_url(caller: str, base_url: str):
    if caller == "claude":
        return f"{base_url}/v1/responses"
    return f"{base_url}/responses"


def guess_mime(path: Path):
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def file_to_data_url(path_str: str):
    path = Path(path_str)
    if not path.exists():
        fail(f"图片文件不存在: {path_str}")
    data = path.read_bytes()
    mime = guess_mime(path)
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


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


def ensure_output_dir():
    output_dir = Path.cwd() / "gen-images"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def save_images(image_entries, output_format: str | None):
    output_dir = ensure_output_dir()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
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


def post_json(url: str, token: str, payload: dict):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "curl/8.7.1",
            "Authorization": f"Bearer {token}",
        },
    )
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
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": "curl/8.7.1",
            "Authorization": f"Bearer {token}",
        },
    )

    latest_partial_b64 = None
    final_b64 = None

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


def build_generation_payload(args):
    if not args.prompt:
        fail("缺少 prompt")

    payload = {
        "model": args.model or DEFAULT_MODEL,
        "prompt": args.prompt,
        "response_format": "b64_json",
        "stream": False,
        "n": args.n or 1,
    }

    optional_fields = [
        "size",
        "quality",
        "background",
        "output_format",
        "output_compression",
        "partial_images",
        "moderation",
    ]
    for field in optional_fields:
        value = getattr(args, field, None)
        if value is not None:
            payload[field] = value
    return payload


def build_edit_payload(args):
    if not args.prompt:
        fail("缺少 prompt")
    if not args.image:
        fail("缺少要编辑的图片来源")

    image_value = normalize_image_source(args.image)

    payload = {
        "model": args.model or DEFAULT_MODEL,
        "prompt": args.prompt,
        "images": [{"image_url": image_value}],
        "response_format": "b64_json",
        "stream": False,
        "n": args.n or 1,
    }

    if args.mask:
        mask_value = normalize_image_source(args.mask)
        payload["mask"] = {"image_url": mask_value}

    optional_fields = [
        "size",
        "quality",
        "background",
        "output_format",
        "output_compression",
        "partial_images",
        "moderation",
        "input_fidelity",
    ]
    for field in optional_fields:
        value = getattr(args, field, None)
        if value is not None:
            payload[field] = value
    return payload


def build_responses_payload(args, default_partial_images: bool = True):
    if not args.prompt:
        fail("缺少 prompt")

    tool_cfg = {"type": "image_generation"}
    if args.size and args.size != "auto":
        tool_cfg["size"] = args.size

    optional_fields = [
        "quality",
        "background",
        "output_format",
        "output_compression",
        "moderation",
        "input_fidelity",
    ]
    for field in optional_fields:
        value = getattr(args, field, None)
        if value is not None:
            tool_cfg[field] = value

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
    parser.add_argument("--mode", choices=["generate", "edit"], required=True)
    parser.add_argument("--prompt")
    parser.add_argument("--model")
    parser.add_argument("--image")
    parser.add_argument("--mask")
    parser.add_argument("--size")
    parser.add_argument("--quality")
    parser.add_argument("--background")
    parser.add_argument("--output-format", dest="output_format")
    parser.add_argument("--output-compression", dest="output_compression", type=int)
    parser.add_argument("--partial-images", dest="partial_images", type=int)
    parser.add_argument("--n", type=int)
    parser.add_argument("--moderation")
    parser.add_argument("--input-fidelity", dest="input_fidelity")
    parser.add_argument("--stream", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        caller, base_url, token = load_runtime_settings()
    except RuntimeError as exc:
        fail(str(exc))

    stream_used = False
    response = None

    if args.stream and not (args.mode == "edit" and args.mask):
        try:
            url = build_responses_url(caller, base_url)
            image_entries = []
            for _ in range(args.n or 1):
                try:
                    payload = build_responses_payload(args)
                    b64_json = post_responses_stream(url, token, payload)
                except ApiHTTPError as exc:
                    if args.partial_images is not None or exc.code not in (400, 422):
                        raise
                    payload = build_responses_payload(args, default_partial_images=False)
                    b64_json = post_responses_stream(url, token, payload)
                image_entries.append({"b64_json": b64_json})
            response = {"data": image_entries}
            stream_used = True
        except ApiHTTPError as exc:
            if exc.code not in (400, 404, 405, 415, 422):
                fail(f"接口调用失败: {exc}")
        except RuntimeError as exc:
            fail(str(exc))

    if response is None:
        if args.mode == "generate":
            payload = build_generation_payload(args)
        else:
            payload = build_edit_payload(args)

        url = build_api_url(caller, base_url, args.mode)
        response = post_json(url, token, payload)

    data = response.get("data")
    if not isinstance(data, list) or not data:
        fail("接口返回中缺少 data")

    used_params = {
        "model": args.model or DEFAULT_MODEL,
        "size": args.size,
        "quality": args.quality,
        "background": args.background,
        "output_format": args.output_format or "png",
        "n": args.n or 1,
        "stream": stream_used,
    }
    if args.mode == "edit" and args.input_fidelity is not None:
        used_params["input_fidelity"] = args.input_fidelity

    paths = save_images(data, args.output_format)
    print(json.dumps({"ok": True, "paths": paths, "used_params": used_params}, ensure_ascii=False))


if __name__ == "__main__":
    main()
