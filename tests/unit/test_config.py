import pytest
from pydantic import ValidationError

from app.config import Settings

STRONG_KEY = "k" * 40
DB_URL = "postgresql+psycopg://u:p@localhost:5432/db"


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory) -> None:
    # Não deixa um .env local ou variáveis da máquina vazarem para os testes.
    monkeypatch.chdir(tmp_path)  # type: ignore[arg-type]
    for var in [
        "API_KEY",
        "DATABASE_URL",
        "GROQ_API_KEY",
        "APP_ENV",
        "MAX_MESSAGE_CHARS",
        "TOOLS_MCP_URL",
    ]:
        monkeypatch.delenv(var, raising=False)


def test_loads_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", STRONG_KEY)
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("GROQ_API_KEY", "sk-test")
    settings = Settings()  # type: ignore[call-arg]
    assert settings.api_key.get_secret_value() == STRONG_KEY
    assert settings.groq_api_key is not None
    assert settings.app_env == "dev"


def test_missing_required_vars_fail() -> None:
    with pytest.raises(ValidationError) as exc:
        Settings()  # type: ignore[call-arg]
    missing = {e["loc"][0] for e in exc.value.errors()}
    assert {"api_key", "database_url"} <= missing


@pytest.mark.parametrize("weak", ["curta", "troque-por-um-valor-aleatorio-longo-xxxxxxxxxx"])
def test_weak_or_example_api_key_is_rejected(monkeypatch: pytest.MonkeyPatch, weak: str) -> None:
    monkeypatch.setenv("API_KEY", weak)
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_secrets_are_not_exposed_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", STRONG_KEY)
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("GROQ_API_KEY", "sk-super-secreta")
    text = repr(Settings())  # type: ignore[call-arg]
    assert STRONG_KEY not in text
    assert "sk-super-secreta" not in text
    assert "u:p@" not in text


def test_invalid_env_value_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", STRONG_KEY)
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("APP_ENV", "staging")
    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8001/mcp",
        "http://localhost:8001/mcp",
        "http://tools-mcp:8001/mcp",
        "https://tools.exemplo.com.br/mcp",
    ],
)
def test_tools_mcp_url_aceita_local_compose_ou_https(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("TOOLS_MCP_URL", url)
    settings = Settings(api_key=STRONG_KEY, database_url=DB_URL)  # type: ignore[arg-type]
    assert str(settings.tools_mcp_url).startswith(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://tools.exemplo.com.br/mcp",
        "http://10.0.0.5:8001/mcp",
        "https://u:p@tools.exemplo.com/mcp",
    ],
)
def test_tools_mcp_url_que_exporia_o_token_e_recusada(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    # Token em http para outra máquina trafega em claro; credencial na URL vaza em logs.
    monkeypatch.setenv("TOOLS_MCP_URL", url)
    with pytest.raises(ValidationError, match="TOOLS_MCP_URL"):
        Settings(api_key=STRONG_KEY, database_url=DB_URL)  # type: ignore[arg-type]
