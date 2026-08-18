from app.observability.pii import redact_pii, prompt_hash

RAW = "Мой email ivan@mail.ru, тел +7 (999) 123-45-67, карта 4111 1111 1111 1111"


def test_redact_removes_email():
    assert "ivan@mail.ru" not in redact_pii(RAW)


def test_redact_removes_phone():
    assert "+7 (999) 123-45-67" not in redact_pii(RAW)


def test_redact_removes_card():
    assert "4111 1111 1111 1111" not in redact_pii(RAW)


def test_redact_has_placeholders():
    result = redact_pii(RAW)
    assert "[EMAIL]" in result
    assert "[PHONE_RU]" in result
    assert "[CARD]" in result


def test_prompt_hash_format():
    h = prompt_hash(RAW)
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 16