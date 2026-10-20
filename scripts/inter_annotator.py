"""Rotulagem humana e kappa entre anotadores (T09).

Uso: `uv run python scripts/inter_annotator.py -h`.
"""

import sys

from evals.inter_annotator import main

if __name__ == "__main__":
    sys.exit(main())
