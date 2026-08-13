from integri_audit_tool.attestation import prompt_attestation


def test_prompt_attestation_yes_without_authorizer(monkeypatch):
    answers = iter(["y"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))

    confirmed, authorizer = prompt_attestation("Is this real?", require_authorizer_name=False)

    assert confirmed is True
    assert authorizer is None


def test_prompt_attestation_yes_with_authorizer_name(monkeypatch):
    answers = iter(["y", "Jane Smith"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))

    confirmed, authorizer = prompt_attestation("Is this authorized?", require_authorizer_name=True)

    assert confirmed is True
    assert authorizer == "Jane Smith"


def test_prompt_attestation_no_never_asks_for_authorizer(monkeypatch):
    calls = []
    monkeypatch.setattr("builtins.input", lambda *a: calls.append(1) or "n")

    confirmed, authorizer = prompt_attestation("Is this real?", require_authorizer_name=True)

    assert confirmed is False
    assert authorizer is None
    assert len(calls) == 1  # only the yes/no prompt, never a second input() for the name


def test_prompt_attestation_blank_authorizer_name_becomes_none(monkeypatch):
    answers = iter(["y", "   "])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))

    _, authorizer = prompt_attestation("Is this authorized?", require_authorizer_name=True)

    assert authorizer is None


def test_prompt_attestation_eof_on_yes_no_returns_false_none(monkeypatch):
    def raise_eof(*a):
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)

    confirmed, authorizer = prompt_attestation("Is this real?", require_authorizer_name=True)

    assert confirmed is False
    assert authorizer is None


def test_prompt_attestation_eof_on_authorizer_name_returns_confirmed_with_none_name(monkeypatch):
    answers = iter(["y"])

    def fake_input(prompt=""):
        try:
            return next(answers)
        except StopIteration:
            raise EOFError

    monkeypatch.setattr("builtins.input", fake_input)

    confirmed, authorizer = prompt_attestation("Is this authorized?", require_authorizer_name=True)

    assert confirmed is True
    assert authorizer is None
