"""Atualiza o `app/integrity.lock.json` (OWASP ASI04 / AST07).

Uso:
    uv run python scripts/lock_config.py                 # registra versões novas de prompt
    uv run python scripts/lock_config.py --allow models  # aceita mudança no catálogo

Versão de prompt já registrada nunca é reescrita. Toda mudança aceita deve ir para o CHANGELOG.
"""

import argparse
import json

from app.integrity import LOCK_PATH, IntegrityError, current_digests, load_lock, updated_lock

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow", action="append", default=[], help="artefato a aceitar")
    parser.add_argument("--init", action="store_true", help="cria o lock do zero")
    args = parser.parse_args()
    try:
        lock = current_digests() if args.init else updated_lock(load_lock(), allow=set(args.allow))
    except IntegrityError as exc:
        raise SystemExit(f"erro: {exc}") from None
    LOCK_PATH.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"lock atualizado: {LOCK_PATH}")
