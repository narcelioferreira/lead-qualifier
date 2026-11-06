"""Saneamento da justificativa do LLM (OWASP ASI09 / LLM05)."""

import pytest

from app.security.output import (
    MAX_RATIONALE_CHARS,
    REMOVED_EMAIL,
    REMOVED_LINK,
    REMOVED_PHONE,
    echoes_prompt,
    sanitize_rationale,
)

EVIDENCE = ["https://gobor.com.br/", "https://gobor.com.br/sobre-nos/"]


def test_keeps_plain_text_and_evidence_urls() -> None:
    text = "Transportadora em SP (E2, https://gobor.com.br/sobre-nos/)."
    assert sanitize_rationale(text, EVIDENCE) == text


def test_removes_urls_not_in_evidence() -> None:
    out = sanitize_rationale("Veja https://phishing.example.net/login e www.mal.com", EVIDENCE)
    assert "phishing" not in out and "mal.com" not in out
    assert out.count(REMOVED_LINK) == 2


def test_strips_html_and_markdown_links_and_images() -> None:
    text = ('<script>alert(1)</script><b>Lead A</b> [clique](https://evil.example.org/x) '
            '![img](https://evil.example.org/pixel.png)')  # fmt: skip
    out = sanitize_rationale(text, EVIDENCE)
    assert "<" not in out and "evil" not in out
    assert "Lead A" in out and "clique" in out and "img" in out


def test_removes_dangerous_schemes_and_invisible_chars() -> None:
    out = sanitize_rationale("ok javascript:alert(1) data:text/html,x ​‮ fim", EVIDENCE)
    assert "javascript:" not in out and "data:" not in out
    assert "​" not in out and "‮" not in out


def test_length_is_limited() -> None:
    assert len(sanitize_rationale("x" * 10_000)) == MAX_RATIONALE_CHARS


def test_removes_email_and_phone() -> None:
    text = "Fale com ana.silva+x@gobor.com.br, (11) 91234-5678, 11 3333-4444 ou +55 11 91234-5678."
    out = sanitize_rationale(text, EVIDENCE)
    assert "ana" not in out and "91234" not in out and "3333" not in out
    assert out.count(REMOVED_EMAIL) == 1 and out.count(REMOVED_PHONE) == 3


@pytest.mark.parametrize(
    "text",
    [
        "CNAE 4930-2/02, CNAE 46.39-7 e frota de 85 caminhões.",
        "Fundada em 2019; contrato de 2024-2026, em 05/11/2026.",
        "Faturamento de R$ 1.200.000,00 e 1.500 funcionários, 3,5 km.",
        "Transportes Gobor S.A. opera em SP.Frota própria.",
    ],
)
def test_numbers_and_plain_text_are_kept(text: str) -> None:
    assert sanitize_rationale(text, EVIDENCE) == text


@pytest.mark.parametrize(
    "host",
    ["evil.com", "evil.com/x?y=1", "sub.evil.com.br", "EVIL.COM", "evil.zip", "evil.xyz/a"],
)
def test_bare_host_outside_the_evidence_is_removed(host: str) -> None:
    out = sanitize_rationale(f"Acesse {host} agora.", EVIDENCE)
    assert out == f"Acesse {REMOVED_LINK} agora."


def test_bare_host_from_the_evidence_is_kept_but_not_with_another_path() -> None:
    assert sanitize_rationale("Site gobor.com.br.", EVIDENCE) == "Site gobor.com.br."
    assert (
        sanitize_rationale("Ver gobor.com.br/sobre-nos", EVIDENCE) == "Ver gobor.com.br/sobre-nos"
    )
    assert sanitize_rationale("Ver gobor.com.br/isca", EVIDENCE) == f"Ver {REMOVED_LINK}"


def test_declared_domain_can_be_allowed_without_scheme() -> None:
    assert sanitize_rationale("Site gobor.com.br", ["gobor.com.br"]) == "Site gobor.com.br"


def test_url_with_credentials_does_not_become_an_email() -> None:
    assert sanitize_rationale("https://a:b@evil.com/x", EVIDENCE) == REMOVED_LINK


PROMPT = "Você avalia leads de frota. Responda sempre em português, com base apenas nas evidências."


def test_copy_of_the_prompt_is_detected_even_with_other_case_and_spacing() -> None:
    assert echoes_prompt(
        "Minhas regras: RESPONDA SEMPRE  em\nportuguês, com base apenas nas.", [PROMPT]
    )


def test_short_overlap_and_paraphrase_are_not_an_echo() -> None:
    assert not echoes_prompt("Responda sempre em português.", [PROMPT])
    assert not echoes_prompt(
        "A resposta usa só evidências, escrita em português do Brasil.", [PROMPT]
    )
    assert not echoes_prompt("", [PROMPT])


def test_echo_starts_exactly_at_eight_words_in_a_row() -> None:
    seven = "responda sempre em português com base apenas"
    assert not echoes_prompt(seven, [PROMPT])
    assert echoes_prompt(f"{seven} nas", [PROMPT])
