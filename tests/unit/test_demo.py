"""Demo offline (T22): reprodução pela API sem rede, fita gravada, guarda de rede e relatório."""

import json
import subprocess  # nosec B404 - roda a própria CLI da demo nos testes
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from app.graph.nodes.extraction import Assessment, Extraction
from app.graph.nodes.mvp import MvpDeps
from app.llm.base import LLMUnavailableError
from evals import demo
from evals.dataset import load_dataset
from tests.graph.test_mvp import ASSESSMENT, SEARCH_OK, SITE_OK, FakeLLM, extraction
from tools_mcp.base import ToolUnavailableError

pytestmark = pytest.mark.anyio
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="module")
def cassette() -> demo.Cassette:
    return demo.load_cassette()


def test_fita_tem_so_leads_dev_e_nenhum_email(cassette: demo.Cassette) -> None:
    split = {item.id: item.split for item in load_dataset()}
    assert set(cassette.leads) == set(demo.DEMO_LEADS)
    assert all(split[lead_id] == "dev" for lead_id in cassette.leads)
    assert demo._EMAIL.search(demo.CASSETTE_PATH.read_text(encoding="utf-8")) is None


async def test_demo_reproduz_pela_api_sem_rede(cassette: demo.Cassette) -> None:
    report = await demo.run_demo(cassette)

    assert report.no_key_status == 401
    assert report.forged_tier_status == 422
    assert {e["type"] for e in report.forged_tier_errors} == {"extra_forbidden"}
    runs = {r.lead_id: r for r in report.runs}
    assert all(r.accepted_status == 202 for r in report.runs)
    assert all(r.run["status"] in {"completed", "needs_review"} for r in report.runs)
    # Ataques: o código desqualifica, com ou sem LLM.
    assert runs["L005"].run["tier"] == "D" and "K1" in runs["L005"].run["result"]["disqualifiers"]
    assert runs["L020"].run["tier"] == "D"
    assert "não foi enviado ao LLM" in runs["L005"].run["result"]["rationale"]
    assert runs["L024"].run["tier"] == "A"
    assert runs["L024"].label == "A"


async def test_relatorio_markdown(cassette: demo.Cassette) -> None:
    text = demo.render(await demo.run_demo(cassette))
    assert text.startswith("# Demo offline")
    assert "| `POST /v1/leads/qualify` sem `X-API-Key` | **401** |" in text
    assert all(f"| {lead_id} |" in text for lead_id in demo.DEMO_LEADS)
    assert "Concordância com o rótulo humano" in text


def test_texto_do_llm_nao_vira_html_nem_quebra_tabela() -> None:
    assert demo._md("<script>alert(1)</script> | x\n y") == (
        "&lt;script&gt;alert(1)&lt;/script&gt; \\| x y"
    )


async def test_fita_esgotada_vira_erro_tratavel() -> None:
    tape = demo.LeadTape(lead_id="L024")
    with pytest.raises(LLMUnavailableError):
        await demo.ReplayLLM(tape).structured(None, [], Extraction)  # type: ignore[arg-type]
    tools = demo.ReplayTools(tape)
    with pytest.raises(ToolUnavailableError):
        await tools.search("x")
    with pytest.raises(ToolUnavailableError):
        await tools.fetch("x.com.br")


def test_demo_nunca_usa_o_split_test(monkeypatch: pytest.MonkeyPatch) -> None:
    test_lead = next(item.id for item in load_dataset() if item.split == "test")
    monkeypatch.setattr(demo, "DEMO_LEADS", ("L024", test_lead))
    with pytest.raises(ValueError, match="split dev"):
        demo.demo_items()


async def test_gravacao_registra_llm_busca_e_site_e_mascara_email(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.graph import runtime

    @asynccontextmanager
    async def fake_deps(settings: Any, **kwargs: Any) -> AsyncIterator[MvpDeps]:
        assert kwargs == {"prompt_version": demo.PROMPT_VERSION}  # sem CRM
        llm = FakeLLM({Extraction: [extraction()] * 5, Assessment: [ASSESSMENT] * 5})
        yield MvpDeps(llm=llm, search=SEARCH_OK, site=SITE_OK, config_digest="abc")

    monkeypatch.setattr(runtime, "production_deps", fake_deps)
    monkeypatch.setattr(demo, "get_settings", lambda: None)
    monkeypatch.setattr(demo, "DEMO_LEADS", ("L024", "L005"))
    path = tmp_path / "fita.json"
    recorded = await demo.record(path)

    assert recorded.config_digest == "abc"
    assert [c.schema_name for c in recorded.leads["L024"].llm] == ["Extraction", "Assessment"]
    assert recorded.leads["L005"].llm == []  # injeção: o detector barra antes do LLM
    assert len(recorded.leads["L024"].searches) == 1 and len(recorded.leads["L024"].sites) == 1
    saved = demo.load_cassette(path)
    assert set(saved.leads) == {"L024", "L005"}


def test_save_cassette_mascara_emails(tmp_path: Path, cassette: demo.Cassette) -> None:
    tape = cassette.leads["L024"].model_copy(deep=True)
    leaky = tape.searches[0].results[0].model_copy(update={"snippet": "fale com joao@empresa.com"})
    tape.searches[0] = tape.searches[0].model_copy(update={"results": [leaky]})
    path = tmp_path / "fita.json"
    demo.save_cassette(cassette.model_copy(update={"leads": {"L024": tape}}), path)
    text = path.read_text(encoding="utf-8")
    assert "joao@empresa.com" not in text and demo.EMAIL_MASK in text


def _python(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  # nosec B603 - interpretador atual, código fixo
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60
    )


def test_guarda_de_rede_bloqueia_fora_do_loopback() -> None:
    blocked = _python(
        "from evals.demo import install_network_guard\n"
        "install_network_guard()\n"
        "import socket\n"
        "s = socket.socket()\n"
        "try:\n"
        "    s.connect(('1.1.1.1', 443))\n"
        "except PermissionError as exc:\n"
        "    print('bloqueado', exc)\n"
        "try:\n"
        "    socket.getaddrinfo('api.groq.com', 443)\n"
        "except PermissionError as exc:\n"
        "    print('dns', exc)\n"
        "try:\n"
        "    socket.create_connection(('127.0.0.1', 9), 1)\n"
        "except PermissionError:\n"
        "    print('loopback bloqueado')\n"
        "except OSError:\n"
        "    print('loopback liberado')\n"
    )
    assert blocked.returncode == 0, blocked.stderr
    # A mensagem é da guarda: um sandbox sem rede também daria PermissionError, sem ela.
    assert "bloqueado demo offline: conexão de rede bloqueada" in blocked.stdout
    assert "dns demo offline: resolução de nome bloqueada" in blocked.stdout
    assert "loopback liberado" in blocked.stdout


def test_cli_roda_offline_e_escreve_o_summary(tmp_path: Path) -> None:
    summary = tmp_path / "summary.md"
    summary.write_text("cabeçalho existente\n", encoding="utf-8")
    result = subprocess.run(  # noqa: S603  # nosec B603 - interpretador atual, módulo do projeto
        [sys.executable, "-m", "evals.demo", "--summary", str(summary)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    text = summary.read_text(encoding="utf-8")
    assert text.startswith("cabeçalho existente\n# Demo offline")  # acrescenta, não apaga


def test_fita_gravada_e_json_valido() -> None:
    data = json.loads(demo.CASSETTE_PATH.read_text(encoding="utf-8"))
    assert data["prompt_version"] == demo.PROMPT_VERSION
