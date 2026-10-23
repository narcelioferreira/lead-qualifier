"""Integridade de prompts e configuração (OWASP ASI04 / AST07)."""

from pathlib import Path

import pytest

from app import integrity
from app.integrity import IntegrityError, current_digests, digest, load_lock, updated_lock, verify


def test_repository_matches_lock() -> None:
    """Falha se um prompt, a rubrica, as taxonomias ou o catálogo mudarem sem atualizar o lock."""
    assert len(verify()) == 64


def test_every_prompt_version_is_locked() -> None:
    lock = load_lock()
    for version in integrity.prompt_versions():
        assert f"prompts/{version}" in lock


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda lock: lock.update({"prompts/v1": "0" * 64}), "prompts/v1: alterado"),
        (lambda lock: lock.pop("models"), "models: ausente no lock"),
        (lambda lock: lock.update({"prompts/v9": "0" * 64}), "prompts/v9: removido"),
    ],
)
def test_drift_is_detected(change: object, expected: str) -> None:
    lock = load_lock()
    change(lock)  # type: ignore[operator]
    with pytest.raises(IntegrityError, match=expected):
        verify(lock)


def test_published_prompt_can_never_be_rewritten() -> None:
    lock = load_lock() | {"prompts/v1": "0" * 64}  # simula: o v1 em disco difere do publicado
    with pytest.raises(IntegrityError, match="já foi publicado"):
        updated_lock(lock, allow={"prompts/v1"})  # nem com --allow


def test_config_change_needs_explicit_allow() -> None:
    lock = load_lock() | {"models": "0" * 64}
    with pytest.raises(IntegrityError, match="--allow models"):
        updated_lock(lock, allow=set())
    assert updated_lock(lock, allow={"models"})["models"] == current_digests()["models"]


def test_new_prompt_version_is_added() -> None:
    lock = {k: v for k, v in load_lock().items() if k != "prompts/v2"}
    assert updated_lock(lock, allow=set())["prompts/v2"] == current_digests()["prompts/v2"]


def test_digest_is_sensitive_to_content_and_name(tmp_path: Path) -> None:
    a = tmp_path / "a.md"
    a.write_text("instrução", encoding="utf-8")
    first = digest([a], root=tmp_path)
    a.write_text("instrução ", encoding="utf-8")  # um espaço a mais
    assert digest([a], root=tmp_path) != first
    b = tmp_path / "b.md"
    a.rename(b)
    b.write_text("instrução", encoding="utf-8")
    assert digest([b], root=tmp_path) != first  # mesmo conteúdo, outro nome


@pytest.mark.anyio
async def test_production_graph_refuses_to_start_on_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from pydantic import SecretStr

    from app.config import Settings
    from app.graph import runtime

    bad = tmp_path / "integrity.lock.json"
    bad.write_text(json.dumps(load_lock() | {"rubric": "0" * 64}), encoding="utf-8")
    monkeypatch.setattr(integrity, "LOCK_PATH", bad)
    monkeypatch.setattr(runtime, "create_engine", lambda *_: pytest.fail("não pode abrir o banco"))
    settings = Settings(
        api_key=SecretStr("x" * 40),
        database_url=SecretStr("postgresql+psycopg://u:p@localhost:1/db"),
        groq_api_key=SecretStr("gsk-teste"),
        tools_mcp_token=SecretStr("t" * 40),
    )
    with pytest.raises(IntegrityError, match="rubric: alterado"):
        async with runtime.production_deps(settings):
            pass


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
