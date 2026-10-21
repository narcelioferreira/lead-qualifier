"""Integridade dos artefatos que definem o comportamento do agente (OWASP ASI04 / AST07).

Prompts, rubrica, taxonomias e catálogo de modelos têm um SHA-256 registrado em
`integrity.lock.json`, versionado no git:
- **versão de prompt publicada é imutável**: mudar o `v1` exige criar `v2`;
- rubrica, taxonomias e catálogo podem mudar, mas só com a atualização explícita do lock
  (`scripts/lock_config.py`), que aparece no diff e passa por revisão;
- o grafo de produção verifica o lock ao iniciar e **recusa rodar** se houver divergência
  (fail closed), e cada execução auditada registra o digest da configuração.
"""

import hashlib
import json
from pathlib import Path

APP_DIR = Path(__file__).parent
LOCK_PATH = APP_DIR / "integrity.lock.json"
PROMPTS_DIR = APP_DIR / "prompts"

# Artefatos não versionados por pasta (podem mudar com atualização explícita do lock).
CONFIG_ARTIFACTS = {
    "rubric": [APP_DIR / "ontology" / "rubric.yaml"],
    "taxonomy": sorted((APP_DIR / "ontology" / "taxonomy").glob("*.yaml")),
    "models": [APP_DIR / "routing" / "models.yaml"],
}


class IntegrityError(RuntimeError):
    """Artefato diferente do registrado no lock."""


def digest(paths: list[Path], root: Path = APP_DIR) -> str:
    """SHA-256 do conjunto de arquivos (caminho relativo + conteúdo, em ordem estável)."""
    h = hashlib.sha256()
    for path in sorted(paths):
        h.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        h.update(path.read_bytes() + b"\0")
    return h.hexdigest()


def prompt_versions() -> list[str]:
    return sorted(p.name for p in PROMPTS_DIR.iterdir() if p.is_dir() and p.name[0] == "v")


def current_digests() -> dict[str, str]:
    entries = {
        f"prompts/{version}": digest(sorted((PROMPTS_DIR / version).glob("*.md")))
        for version in prompt_versions()
    }
    entries |= {name: digest(paths) for name, paths in CONFIG_ARTIFACTS.items()}
    return entries


def load_lock(path: Path | None = None) -> dict[str, str]:
    data: dict[str, str] = json.loads((path or LOCK_PATH).read_text(encoding="utf-8"))
    return data


def verify(lock: dict[str, str] | None = None) -> str:
    """Confere todos os artefatos contra o lock. Devolve o digest da configuração inteira."""
    lock = load_lock() if lock is None else lock
    current = current_digests()
    problems = [
        f"{name}: {'ausente no lock' if name not in lock else 'alterado'}"
        for name, value in current.items()
        if lock.get(name) != value
    ] + [f"{name}: removido" for name in lock.keys() - current.keys()]
    if problems:
        raise IntegrityError(
            "configuração difere do integrity.lock.json: "
            + "; ".join(sorted(problems))
            + ". Prompt publicado não muda (crie nova versão); demais artefatos: "
            "rode scripts/lock_config.py e registre no CHANGELOG."
        )
    return config_digest(current)


def config_digest(entries: dict[str, str]) -> str:
    payload = json.dumps(entries, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def updated_lock(lock: dict[str, str], *, allow: set[str]) -> dict[str, str]:
    """Novo lock: inclui versões de prompt novas e atualiza só os artefatos em `allow`.

    Versão de prompt já registrada nunca é reescrita.
    """
    current = current_digests()
    new = dict(lock)
    for name, value in current.items():
        if name not in lock:
            new[name] = value
        elif lock[name] != value:
            if name.startswith("prompts/"):
                raise IntegrityError(f"{name} já foi publicado e não pode mudar: crie nova versão")
            if name not in allow:
                raise IntegrityError(f"{name} mudou: passe --allow {name} para aceitar")
            new[name] = value
    return dict(sorted(new.items()))
