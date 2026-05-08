import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "figforge_gen.py"
SPEC = importlib.util.spec_from_file_location("figforge_gen", SCRIPT_PATH)
figforge_gen = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(figforge_gen)


def test_responses_images_only_503_falls_back_to_images_endpoint():
    error = figforge_gen.ApiHTTPError(
        503,
        "model gpt-image-2 is only supported on /v1/images/generations and /v1/images/edits",
    )

    assert figforge_gen.should_fall_back_to_images(error)


def test_lone_figforge_api_key_env_does_not_block_fallback(monkeypatch):
    monkeypatch.setenv("FIGFORGE_GEN_API_KEY", "dummy")
    monkeypatch.delenv("FIGFORGE_GEN_API_BASE", raising=False)
    args = type("Args", (), {"api_base": None, "api_key": None, "api_key_env": None})()

    assert figforge_gen.load_direct_settings(args, {}, None, "gpt-image-2") is None
