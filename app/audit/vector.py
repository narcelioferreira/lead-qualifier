"""Tipo `vector` do pgvector para o SQLAlchemy, sem dependência extra.

O pacote `pgvector` faria o mesmo, mas são poucas linhas e uma dependência a menos na cadeia
de suprimentos (ASI04). O valor vai ao banco como texto (`'[0.1,0.2]'`) com `CAST`, e o
Postgres valida a dimensão; aqui a dimensão e os números finitos são conferidos antes.
"""

import math
from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy import Float, cast, literal
from sqlalchemy.dialects.postgresql.base import ischema_names
from sqlalchemy.engine import Dialect
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.types import UserDefinedType


def to_literal(values: Sequence[float]) -> str:
    if not all(math.isfinite(x) for x in values):
        raise ValueError("vetor com valor não finito")
    return "[" + ",".join(repr(float(x)) for x in values) + "]"


class Vector(UserDefinedType[list[float]]):
    cache_ok = True

    def __init__(self, dim: int | None = None) -> None:
        self.dim = dim

    def get_col_spec(self, **kw: Any) -> str:
        return "VECTOR" if self.dim is None else f"VECTOR({self.dim})"

    def bind_processor(self, dialect: Dialect) -> Callable[[Any], str | None]:
        def process(value: Sequence[float] | None) -> str | None:
            if value is None:
                return None
            if self.dim is not None and len(value) != self.dim:
                raise ValueError(f"vetor com {len(value)} dimensões; esperado {self.dim}")
            return to_literal(value)

        return process

    def bind_expression(self, bindvalue: Any) -> ColumnElement[Any]:
        return cast(bindvalue, self)

    def result_processor(
        self, dialect: Dialect, coltype: object
    ) -> Callable[[Any], list[float] | None]:
        def process(value: str | None) -> list[float] | None:
            if value is None:
                return None
            return [float(x) for x in value.strip("[]").split(",") if x]

        return process

    class comparator_factory(UserDefinedType.Comparator[list[float]]):  # noqa: N801
        def cosine_distance(self, other: Sequence[float]) -> ColumnElement[float]:
            """Operador `<=>` do pgvector: 0 = mesma direção, 2 = oposto."""
            vector = literal(list(other), type_=self.type)
            return self.expr.op("<=>", return_type=Float)(vector)


# A reflexão do Postgres (Alembic) passa a reconhecer a coluna, em vez de NullType.
ischema_names["vector"] = Vector
