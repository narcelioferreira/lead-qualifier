"""Cadeia de suprimentos fixada (OWASP ASI04 / AST02): impede regressão para tags móveis."""

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
_SHA = re.compile(r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$")


def test_github_actions_are_pinned_by_commit_sha() -> None:
    for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
        data = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        for job in data["jobs"].values():
            for step in job["steps"]:
                if "uses" in step:
                    assert _SHA.match(step["uses"]), f"{workflow.name}: {step['uses']}"


_FROM = re.compile(r"^FROM\s+(\S+)", re.MULTILINE)


def _dockerfiles(compose: dict[str, Any]) -> list[Path]:
    return [
        ROOT / service["build"].get("dockerfile", "Dockerfile")
        for service in compose["services"].values()
        if "build" in service
    ]


def test_docker_images_are_pinned_by_digest() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    for name, service in compose["services"].items():
        if "build" in service:
            continue  # imagem construída aqui: os FROM do Dockerfile são conferidos abaixo
        assert re.search(r"@sha256:[0-9a-f]{64}$", service["image"]), name
        assert ":latest" not in service["image"], name


def test_dockerfiles_pin_base_images_and_drop_root() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    dockerfiles = _dockerfiles(compose)
    assert dockerfiles, "nenhum serviço com build"
    for dockerfile in dockerfiles:
        text = dockerfile.read_text(encoding="utf-8")
        for image in _FROM.findall(text):
            assert re.search(r"@sha256:[0-9a-f]{64}$", image), f"{dockerfile.name}: {image}"
        users = re.findall(r"^USER\s+(\S+)", text, re.MULTILINE)
        assert users and users[-1] not in {"root", "0"}, dockerfile.name


def test_built_services_drop_privileges() -> None:
    """Sem capabilities, disco só leitura e imagem sem setuid/setgid (no lugar do NNP)."""
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    for name, service in compose["services"].items():
        if "build" not in service:
            continue
        assert service.get("cap_drop") == ["ALL"], name
        assert service.get("read_only") is True, name
    for dockerfile in _dockerfiles(compose):
        assert "-perm /6000" in dockerfile.read_text(encoding="utf-8"), dockerfile.name


def test_dockerignore_keeps_secrets_out_of_the_build() -> None:
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    assert {".env", ".env.*", ".git"} <= set(ignored)


def test_ci_installs_from_lockfile_only() -> None:
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "uv sync --locked" in text
    assert "permissions:\n  contents: read" in text  # menor privilégio do token do CI


def test_services_listen_only_on_localhost() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    for name, service in compose["services"].items():
        for port in service.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), name
