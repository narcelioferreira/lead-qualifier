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


def _compose() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((ROOT / "docker-compose.yml").read_text("utf-8"))
    return data


def test_cada_servico_recebe_so_os_segredos_que_usa() -> None:
    """ASI03: a API não vê as chaves da Tavily e do HubSpot; as tools não veem a da Groq."""
    services = _compose()["services"]
    for name, service in services.items():
        assert "env_file" not in service, name  # variáveis uma a uma, nunca o .env inteiro
    api = set(services["api"]["environment"])
    assert {"API_KEY", "GROQ_API_KEY", "TOOLS_MCP_TOKEN"} <= api
    assert not {"TAVILY_API_KEY", "HUBSPOT_TOKEN"} & api
    tools = set(services["tools-mcp"]["environment"])
    assert {"TAVILY_API_KEY", "HUBSPOT_TOKEN", "TOOLS_MCP_TOKEN"} <= tools
    assert not {"API_KEY", "GROQ_API_KEY"} & tools
    migrate = set(services["migrate"]["environment"])
    assert migrate == {"API_KEY", "DATABASE_URL"}


def test_api_sobe_so_depois_das_migrations_e_do_mcp() -> None:
    services = _compose()["services"]
    depends = services["api"]["depends_on"]
    assert depends["migrate"]["condition"] == "service_completed_successfully"
    assert depends["tools-mcp"]["condition"] == "service_healthy"
    assert services["migrate"]["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert services["api"]["environment"]["TOOLS_MCP_URL"].startswith("http://tools-mcp:")


def test_servicos_longos_tem_healthcheck() -> None:
    services = _compose()["services"]
    for name, service in services.items():
        if service.get("restart") == "no":
            continue  # tarefa única (migrate)
        dockerfile = service.get("build", {}).get("dockerfile")
        built_check = dockerfile and "HEALTHCHECK" in (ROOT / dockerfile).read_text("utf-8")
        assert "healthcheck" in service or built_check, name


def test_workflow_da_demo_e_manual_sem_secrets_e_so_leitura() -> None:
    text = (ROOT / ".github" / "workflows" / "demo.yml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert set(data[True]) == {"workflow_dispatch"}  # o YAML lê `on:` como True
    assert data["permissions"] == {"contents": "read"}
    assert "secrets." not in text  # a demo roda da fita gravada, sem chave nenhuma
    assert "uv sync --locked" in text
