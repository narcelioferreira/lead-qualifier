"""Cadeia de suprimentos fixada (OWASP ASI04 / AST02): impede regressão para tags móveis."""

import re
from pathlib import Path

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


def test_docker_images_are_pinned_by_digest() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    for name, service in compose["services"].items():
        assert re.search(r"@sha256:[0-9a-f]{64}$", service["image"]), name
        assert ":latest" not in service["image"], name


def test_ci_installs_from_lockfile_only() -> None:
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "uv sync --locked" in text
    assert "permissions:\n  contents: read" in text  # menor privilégio do token do CI


def test_services_listen_only_on_localhost() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    for name, service in compose["services"].items():
        for port in service.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), name
