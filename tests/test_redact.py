import json
import time

import pytest

from kaizen.redact import find_secrets, redact, redact_obj

PEM = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "MIIFAKEFAKEFAKEFAKEFAKE0123456789abcdefABCDEF\n"
    "FAKEFAKEFAKEFAKEFAKE9876543210zyxwvuTSRQPO==\n"
    "-----END RSA PRIVATE KEY-----"
)
GH_PAT = "github_pat_" + "0123456789abcdefghij01" + "_" + "A1b2C3d4E5" * 5 + "fakefakef"
GH_BODY = "0123456789abcdefghijABCDEFGHIJ012345"
OPENAI_BODY = "AbCdEf0123456789AbCdEf0123456789"

CASES = [
    ("anthropic_key", f"key sk-ant-api03-{OPENAI_BODY} end", OPENAI_BODY),
    ("anthropic_key", "key=sk-ant-FAKEFAKEFAKEFAKEFAKE1234", "FAKEFAKEFAKEFAKEFAKE1234"),
    ("openai_key", f"k sk-proj-{OPENAI_BODY}", OPENAI_BODY),
    ("openai_key", f"k sk-{GH_BODY}", GH_BODY),
    ("github_token", f"t ghp_{GH_BODY}", GH_BODY),
    ("github_token", f"t gho_{GH_BODY}", GH_BODY),
    ("github_token", f"t ghs_{GH_BODY}", GH_BODY),
    ("github_token", "t " + GH_PAT, "0123456789abcdefghij01"),
    ("aws_key", "id AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE"),
    (
        "bearer",
        "Authorization: Bearer abc.def.ghi-123456789012345",
        "abc.def.ghi-123456789012345",
    ),
    (
        "jwt",
        "t eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcDEF123456789_-",
        "eyJzdWIiOiIxIn0",
    ),
    ("private_key", "before\n" + PEM + "\nafter", "MIIFAKEFAKEFAKEFAKEFAKE0123456789abcdefABCDEF"),
    ("private_key", "before\n" + PEM + "\nafter", "FAKEFAKEFAKEFAKEFAKE9876543210zyxwvuTSRQPO=="),
    ("env_assignment", "DB_PASSWORD=hunter2hunter2", "hunter2hunter2"),
    ("env_assignment", 'export API_TOKEN="abc123abc123"', "abc123abc123"),
    ("env_assignment", '"client_secret": "abc123abc123"', "abc123abc123"),
    ("env_assignment", "x-api-key: abc123abc123", "abc123abc123"),
    ("env_assignment", "https://x.test/?api_key=abc123abc123&q=1", "abc123abc123"),
    ("cpf", "doc 123.456.789-09 ok", "123.456.789-09"),
    ("cpf", "CPF: 12345678909", "12345678909"),
    ("cpf", '{"cpf": "12345678909"}', "12345678909"),
    ("url_credentials", "https://user:p4ssw0rd@host.com/x", "p4ssw0rd"),
]


@pytest.mark.parametrize(("kind", "text", "secret"), CASES)
def test_redacts_kind(kind, text, secret):
    out = redact(text)
    assert secret not in out
    assert f"[REDACTED:{kind}]" in out


@pytest.mark.parametrize(("kind", "text", "secret"), CASES)
def test_idempotent_per_kind(kind, text, secret):
    once = redact(text)
    assert redact(once) == once
    assert find_secrets(once) == []


@pytest.mark.parametrize(("kind", "text", "secret"), CASES)
def test_find_secrets_reports_kind(kind, text, secret):
    assert kind in find_secrets(text)


def test_plain_text_untouched():
    s = "def pass_rate(tokens): return tokens / 2  # sk is a variable"
    assert redact(s) == s


def test_redact_obj_walks_nested_and_does_not_mutate():
    src = {"a": ["x", {"k": "ghp_0123456789abcdefghijABCDEFGHIJ012345"}]}
    out = redact_obj(src)
    assert "ghp_" not in json.dumps(out)
    assert "ghp_" in json.dumps(src)


def test_redact_is_idempotent():
    once = redact("DB_PASSWORD=hunter2hunter2")
    assert redact(once) == once


ORDINARY = [
    "token = get_token()",
    "password = None",
    'password = ""',
    "max_tokens=4096",
    'API_KEY = os.environ["API_KEY"]',
    "api_key = os.environ.get('API_KEY')",
    "const apiKey = process.env.API_KEY;",
    "token = self.token",
    "if token == expected_token_value:",
    "def f(password: str, token: Optional[str] = None): ...",
    "API_KEY=your_api_key_here",
    "GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}",
    "commit 3f2a9c1d4b5e6f708192a3b4c5d6e7f801234567",
    "id 123e4567-e89b-12d3-a456-426614174000",
    "order 12345678909 shipped",
    "version 1.2.3-09 and 123.456.789",
    "the bearer of this message",
    "risk-assessment-framework-for-the-whole-team",
    "ssh://git@github.com:org/repo.git",
    "http://localhost:8080/path",
    "tokenizer = Tokenizer(max_length=512)",
]


@pytest.mark.parametrize("line", ORDINARY)
def test_ordinary_code_untouched(line):
    assert redact(line) == line
    assert find_secrets(line) == []


def test_env_assignment_keeps_name():
    assert redact("DB_PASSWORD=hunter2hunter2") == "DB_PASSWORD=[REDACTED:env_assignment]"
    assert (
        redact('export API_TOKEN="abc123abc123"')
        == 'export API_TOKEN="[REDACTED:env_assignment]"'
    )
    assert (
        redact('"client_secret": "abc123abc123"')
        == '"client_secret": "[REDACTED:env_assignment]"'
    )


def test_url_credentials_keeps_user_and_host():
    assert (
        redact("https://user:p4ssw0rd@host.com/x")
        == "https://user:[REDACTED:url_credentials]@host.com/x"
    )


def test_secret_in_json_escaped_string():
    line = json.dumps({"cmd": 'cat <<X\n{"API_KEY": "abc123abc123"}\nX'})
    assert '\\"API_KEY\\": \\"abc123abc123\\"' in line
    out = redact(line)
    assert "abc123abc123" not in out
    assert json.loads(out)["cmd"].count("[REDACTED:env_assignment]") == 1


def test_private_key_with_literal_backslash_n():
    line = json.dumps({"output": PEM + "\nnext line"})
    assert "\\n" in line and "\n" not in line
    out = redact(line)
    assert "FAKEFAKE" not in out
    assert "[REDACTED:private_key]" in out
    assert json.loads(out)["output"].endswith("next line")


def test_openai_key_after_escaped_newline():
    line = json.dumps({"o": f"x\nsk-proj-{OPENAI_BODY}"})
    assert OPENAI_BODY not in redact(line)


def test_unterminated_private_key_is_still_redacted():
    out = redact("-----BEGIN PRIVATE KEY-----\nMIIFAKEFAKE0123456789\nabcdefFAKE/+==")
    assert "FAKE" not in out


def test_private_key_marker_in_code_does_not_eat_following_code():
    out = redact('if "-----BEGIN PRIVATE KEY-----" in line:\n    return 1')
    assert "return 1" in out


def test_two_secrets_on_one_line():
    text = f"a ghp_{GH_BODY} b AKIAIOSFODNN7EXAMPLE c"
    assert redact(text) == "a [REDACTED:github_token] b [REDACTED:aws_key] c"
    assert find_secrets(text) == ["github_token", "aws_key"]


def test_two_env_assignments_on_one_line():
    out = redact("A_TOKEN=abc123abc123 B_SECRET=def456def456")
    assert out == "A_TOKEN=[REDACTED:env_assignment] B_SECRET=[REDACTED:env_assignment]"


def test_specific_format_wins_over_env_assignment():
    text = "ANTHROPIC_API_KEY=sk-ant-FAKEFAKEFAKEFAKEFAKE1234"
    out = redact(text)
    assert out == "ANTHROPIC_API_KEY=[REDACTED:anthropic_key]"
    assert redact(out) == out
    assert find_secrets(text) == ["anthropic_key"]


def test_secret_as_dict_key():
    key = f"ghp_{GH_BODY}"
    src = {key: 1}
    out = redact_obj(src)
    assert out == {"[REDACTED:github_token]": 1}
    assert key in src


def test_redact_obj_passthrough_and_containers():
    src = {"n": 1, "f": 1.5, "b": True, "z": None, "t": ("AKIAIOSFODNN7EXAMPLE", 2), 3: "x"}
    out = redact_obj(src)
    assert out == {
        "n": 1, "f": 1.5, "b": True, "z": None, "t": ("[REDACTED:aws_key]", 2), 3: "x",
    }
    assert src["t"][0] == "AKIAIOSFODNN7EXAMPLE"
    assert out is not src


def test_find_secrets_clean_and_redacted():
    assert find_secrets("nothing here") == []
    text = "DB_PASSWORD=hunter2hunter2 cpf 12345678909 123.456.789-09"
    assert find_secrets(text) == ["env_assignment", "cpf"]
    assert find_secrets(redact(text)) == []


def test_large_inputs_do_not_blow_up():
    start = time.perf_counter()
    for text in (
        "A" * 2_000_000,
        "password" * 200_000,
        "sk-" * 300_000,
        "token=" * 200_000,
        "-----BEGIN PRIVATE KEY-----\n" * 50_000,
        "http://" + "a" * 1_000_000,
        "cpf" * 300_000,
    ):
        redact(text)
    assert time.perf_counter() - start < 20
