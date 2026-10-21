"""Saneamento da justificativa do LLM (OWASP ASI09 / LLM05)."""

from app.security.output import MAX_RATIONALE_CHARS, REMOVED_LINK, sanitize_rationale

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
