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
FAKE20 = "FAKEFAKEFAKEFAKE1234"
FAKE35 = "FakeFakeFakeFakeFakeFakeFakeFake000"
FAKE36 = "FAKE" * 9
HEX40 = "0123456789abcdef" * 2 + "01234567"
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
    ("env_assignment", "DB_PASSWORD=supersecretpassword", "supersecretpassword"),
    ("env_assignment", "export DB_PASSWORD=supersecretpassword", "supersecretpassword"),
    ("env_assignment", "PASSWORD=changeme", "changeme"),
    ("env_assignment", "POSTGRES_PASSWORD=correct_horse_battery", "correct_horse_battery"),
    ("env_assignment", "password: correcthorsebattery", "correcthorsebattery"),
    ("env_assignment", "password=correcthorsebattery", "correcthorsebattery"),
    ("env_assignment", "API_KEY=your_api_key_here", "your_api_key_here"),
    ("env_assignment", "ACCESS_KEY=abc123abc123abc123", "abc123abc123abc123"),
    ("env_assignment", "CREDENTIALS=abc123abc123abc123", "abc123abc123abc123"),
    ("env_assignment", "SUPABASE_ANON_KEY=abcdef0123456789abcdef", "abcdef0123456789abcdef"),
    ("env_assignment", "ENCRYPTION_KEY=abc123abc123abc123", "abc123abc123abc123"),
    ("env_assignment", "SIGNING_KEY=abc123abc123abc123", "abc123abc123abc123"),
    ("env_assignment", "PASSPHRASE=abc123abc123abc123", "abc123abc123abc123"),
    ("env_assignment", "AUTH=abc123abc123abc123", "abc123abc123abc123"),
    ("env_assignment", "BASIC_AUTH=abc123abc123abc123", "abc123abc123abc123"),
    ("env_assignment", "PIN_TOKEN=12345678", "12345678"),
    ("env_assignment", "PIN_TOKEN = 12345678", "12345678"),
    ("env_assignment", '"SIGNING_KEY": "abc123abc123abc123"', "abc123abc123abc123"),
    ("env_assignment", 'password = "12345678"', "12345678"),
    ("env_assignment", r'{"password":"p\"ssw0rd123456"}', "ssw0rd123456"),
    ("env_assignment", r"{'password':'it\'s-a-secret99'}", "a-secret99"),
    ("stripe_key", f"x sk_live_{FAKE20}", FAKE20),
    ("stripe_key", f"x sk_test_{FAKE20}", FAKE20),
    ("stripe_key", f"x rk_live_{FAKE20}", FAKE20),
    ("stripe_key", f"x whsec_{FAKE20}", FAKE20),
    ("slack_token", "x xoxb-0000000000-FAKEFAKEFAKE", "FAKEFAKEFAKE"),
    ("slack_token", "x xoxp-0000000000-FAKEFAKEFAKE", "FAKEFAKEFAKE"),
    ("slack_token", "x xoxa-0000000000-FAKEFAKEFAKE", "FAKEFAKEFAKE"),
    ("slack_token", "x xoxr-0000000000-FAKEFAKEFAKE", "FAKEFAKEFAKE"),
    ("slack_token", "x xoxs-0000000000-FAKEFAKEFAKE", "FAKEFAKEFAKE"),
    ("google_key", f"x AIza{FAKE35}", FAKE35),
    ("hf_token", f"x hf_{FAKE36}", FAKE36),
    ("npm_token", f"x npm_{FAKE36}", FAKE36),
    ("gitlab_token", f"x glpat-{FAKE20}", FAKE20),
    ("supabase_key", "x sbp_" + HEX40, HEX40),
    ("supabase_key", f"x sb_secret_{FAKE20}", FAKE20),
    ("basic_auth", "Authorization: Basic YWRtaW46SHVudGVyMkh1bnRlcjI=", "YWRtaW46SHVudGVyMkh1bnRlcjI="),
    ("cli_flag", "psql --password Hunter2Hunter2", "Hunter2Hunter2"),
    ("cli_flag", "tool --token Hunter2Hunter2", "Hunter2Hunter2"),
    ("cli_flag", "tool --api-key Hunter2Hunter2", "Hunter2Hunter2"),
    ("cli_flag", "tool --secret Hunter2Hunter2", "Hunter2Hunter2"),
    ("cli_flag", 'tool --password "Hunter2 Hunter2"', "Hunter2"),
    ("cli_flag", "curl -u admin:Hunter2Hunter2 https://x.com", "Hunter2Hunter2"),
    ("cli_flag", 'curl -u "admin:Hunter2Hunter2" https://x.com', "Hunter2Hunter2"),
    ("cli_flag", "curl -u 'admin:Hunter2Hunter2' https://x.com", "Hunter2Hunter2"),
    ("cli_flag", "curl -uadmin:Hunter2Hunter2 https://x.com", "Hunter2Hunter2"),
    ("cli_flag", "curl --user=admin:Hunter2Hunter2 https://x.com", "Hunter2Hunter2"),
    ("cli_flag", "tool --pass=supersecret123", "supersecret123"),
    ("cli_flag", "tool --password=short7", "short7"),
    ("cli_flag", "tool --token=x1 --verbose", "x1"),
    ("cli_flag", 'tool --password="Hunter2 Hunter2"', "Hunter2"),
    ("env_assignment", "DB_PASSWORD=dev123", "dev123"),
    ("env_assignment", "POSTGRES_PASSWORD=admin", "admin"),
    ("env_assignment", "MYSQL_PASSWD=root1", "root1"),
    ("env_assignment", "DB_PWD=abcd", "abcd"),
    ("env_assignment", 'export DB_PASSWORD="dev123"', "dev123"),
    ("url_credentials", "git clone https://oauth2tokenvalue12345@github.com/o/r.git", "oauth2tokenvalue12345"),
    ("url_signature", "https://s.test/o?X-Amz-Signature=abcdef0123456789&X-Amz-Expires=60", "abcdef0123456789"),
    ("url_signature", "https://s.test/o?a=1&x-goog-signature=abcdef0123456789", "abcdef0123456789"),
    ("url_signature", "https://s.blob.test/c?sv=2020&sig=abc%2Bdef%3D&se=2030", "abc%2Bdef%3D"),
    ("url_signature", "https://s.blob.test/c?sig=abc123", "abc123"),
    ("pypi_token", "t pypi-AgEI" + "FAKEfake0123_-" * 5, "FAKEfake0123_-"),
    ("sendgrid_key", "k SG." + "FAKEfake0123456789abcd" + "." + "FAKEfake0123456789abcdFAKEfake0123456789abc", "FAKEfake0123456789abcd"),
    ("azure_key", "Endpoint=sb://x.test/;SharedAccessKeyName=Root;SharedAccessKey=FAKEfake0123456789abcdFAKEfake0123=", "FAKEfake0123456789abcd"),
    ("azure_key", "DefaultEndpointsProtocol=https;AccountName=x;AccountKey=FAKEfake0123456789abcdFAKEfake0123456789abcdFAKEfake0123456789abcd==;EndpointSuffix=core.windows.net", "FAKEfake0123456789abcd"),
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
    "npm_config_registry=https://registry.test/",
    "from hf_hub import download",
    "hf_hub_download(repo_id)",
    "npm_config",
    "task_live_data and desk_test_runner",
    "xoxb-test and AIzaSomething",
    'primary_key = "id_column_name"',
    "sort_key = lambda_value",
    "cache_key = make_cache_key(x)",
    "docker run --user 1000:1000 img",
    "git push -u origin main",
    "tool --max-tokens 4096",
    "tool --password-file /etc/pw",
    "max_tokens=100000000",
    "token_expiry = 1700000000",
    "if password == expected_password:",
    "const password = userInput.trim();",
    "OAUTH_PROVIDER=github",
    "AUTHOR=someone_long_name",
    "Basic authentication is enabled",
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
    "PWD=/home/dev/project",
    "OLDPWD=/home/dev/project",
    "sort -u names.txt",
    "tool --password-file /run/secrets/x",
    "tool --password-file=/run/secrets/x",
    "https://example.com/?page=2&sig_figs=3",
    "https://example.com/@user/repo",
    "mail user@example.com now",
    "docker run -u 1000:1000 img",
    "docker run -u1000:1000 img",
    "API_TOKEN=abcdef",
    "PASSWORD=abc",
    "DB_PASSWORD=$DB_PW",
    "DB_PASSWORD=${PW}",
    "DB_PASSWORD=%PW%",
    "DB_PASSWORD=<pw>",
    "DB_PASSWORD=true",
    "DB_PASSWORD=FALSE",
    "DB_PASSWORD=None",
    "DB_PASSWORD=off",
    "DB_PASSWORD=",
    "tool --token=",
    "git clone https://github.com/o/r.git",
    "ssh://averyshortname@host",
    "see pypi-AgEI and pypi-core",
    "SG.abc.def and SG.something",
    "AccountKey=short and SharedAccessKey=abc",
    "AccountKeyName=x;SharedAccessKeyName=RootManageSharedAccessKey",
    "tool --token=[REDACTED:cli_flag]",
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
        "A" * 200_000,
        "password" * 20_000,
        "sk-" * 30_000,
        "token=" * 20_000,
        "-----BEGIN PRIVATE KEY-----\n" * 5_000,
        "http://" + "a" * 100_000,
        "cpf" * 30_000,
        "sk_live_" * 10_000,
        "xoxb-" * 20_000,
        "hf_" * 30_000,
        "AIza" * 20_000,
        "--password " * 10_000,
        "-u " * 20_000,
        "Authorization: Basic " * 5_000,
        "PASSWORD" * 10_000,
        "A_" * 50_000,
        "password: " * 10_000,
        '"password": "' + "a\\" * 20_000,
        "-uadmin" * 20_000,
        "-u" * 30_000,
        "--password=" * 10_000,
        "--user=" * 10_000,
        "sig=" * 30_000,
        "?sig=" * 20_000,
        "X-Amz-Signature=" * 10_000,
        "pypi-" * 30_000,
        "pypi-AgEI" * 10_000,
        "SG." * 30_000,
        "SG." + "a" * 22 + "." + "a" * 100_000,
        "AccountKey=" * 10_000,
        "SharedAccessKey=" * 10_000,
        "@" * 100_000,
        "http://" + "@" * 100_000,
        "http://" * 20_000,
        "https://" + "a" * 100_000 + "@",
        "DB_PASSWORD=" * 10_000,
        "A_PWD=" * 20_000,
    ):
        redact(text)
    assert time.perf_counter() - start < 20


def test_escaped_quote_value_fully_redacted():
    assert redact(r'{"password":"p\"ssw0rd123456"}') == '{"password":"[REDACTED:env_assignment]"}'


def test_basic_auth_replaces_only_base64():
    out = redact("Authorization: Basic YWRtaW46SHVudGVyMkh1bnRlcjI=")
    assert out == "Authorization: Basic [REDACTED:basic_auth]"


def test_curl_user_replaces_only_password():
    out = redact("curl -u admin:Hunter2Hunter2 https://x.com")
    assert out == "curl -u admin:[REDACTED:cli_flag] https://x.com"


def test_caps_env_after_escaped_newline():
    line = json.dumps({"o": "x\nDB_PASSWORD=supersecretpassword\ny"})
    out = redact(line)
    assert "supersecretpassword" not in out
    assert json.loads(out)["o"].endswith("\ny")


def test_redact_obj_colliding_keys_are_both_kept():
    k1 = f"ghp_{GH_BODY}"
    k2 = "ghp_" + "Z" * 36
    out = redact_obj({k1: 1, k2: 2})
    assert out == {"[REDACTED:github_token]": 1, "[REDACTED:github_token]#2": 2}


CREDENTIAL_DICTS = [
    ({"password": "hunter2hunter2"}, {"password": "[REDACTED:field]"}),
    ({"api_key": "abc123abc123abc123"}, {"api_key": "[REDACTED:field]"}),
    ({"token": "plainwordtoken"}, {"token": "[REDACTED:field]"}),
    (
        {"headers": {"Authorization": "Basic YWRtaW46SHVudGVyMkh1bnRlcjI="}},
        {"headers": {"Authorization": "[REDACTED:field]"}},
    ),
    (
        {"env": {"DB_PASSWORD": "supersecretpassword"}},
        {"env": {"DB_PASSWORD": "[REDACTED:field]"}},
    ),
    ({"password": "abc"}, {"password": "[REDACTED:field]"}),
    ({"X-Api-Key": "x"}, {"X-Api-Key": "[REDACTED:field]"}),
    ({"apiKey": "x"}, {"apiKey": "[REDACTED:field]"}),
    ({"Set-Cookie": "sid=1"}, {"Set-Cookie": "[REDACTED:field]"}),
    ({"cookie": "sid=1"}, {"cookie": "[REDACTED:field]"}),
    ({"AUTH": "x"}, {"AUTH": "[REDACTED:field]"}),
    ({"pwd": "x"}, {"pwd": "[REDACTED:field]"}),
    ({"client_secret": "x"}, {"client_secret": "[REDACTED:field]"}),
    ({"private-key": "x"}, {"private-key": "[REDACTED:field]"}),
    ({"AWS_ACCESS_KEY_ID": "x"}, {"AWS_ACCESS_KEY_ID": "[REDACTED:field]"}),
    ({"db_passphrase": "x"}, {"db_passphrase": "[REDACTED:field]"}),
    ({"credentials": "x"}, {"credentials": "[REDACTED:field]"}),
    ({"passwd": "x"}, {"passwd": "[REDACTED:field]"}),
    ({"secret": ["a", {"b": "c", "n": 1}, 2]}, {"secret": ["[REDACTED:field]", {"b": "[REDACTED:field]", "n": 1}, 2]}),
    ({"token": {"a": {"b": ("c",)}}}, {"token": {"a": {"b": ("[REDACTED:field]",)}}}),
]


@pytest.mark.parametrize(("src", "expected"), CREDENTIAL_DICTS)
def test_redact_obj_masks_values_under_credential_keys(src, expected):
    before = json.dumps(src, default=list)
    out = redact_obj(src)
    assert out == expected
    assert json.dumps(src, default=list) == before
    assert redact_obj(out) == out


def test_redact_obj_credential_key_edge_values():
    src = {"password": "", "token": "[REDACTED:github_token]", "secret": None, "api_key": 5}
    assert redact_obj(src) == src


def test_redact_obj_token_counters_untouched():
    src = {"total_tokens": 7115, "max_tokens": 4096, "usage": {"input_tokens": 12}}
    assert redact_obj(src) == src


def test_redact_obj_ordinary_keys_untouched():
    src = {"author": "someone", "command": "ls", "path": "/tmp/x", "keys": ["a"]}
    assert redact_obj(src) == src


def test_redact_obj_still_scrubs_text_under_ordinary_keys():
    out = redact_obj({"cmd": "DB_PASSWORD=hunter2hunter2"})
    assert out == {"cmd": "DB_PASSWORD=[REDACTED:env_assignment]"}
    assert redact_obj(out) == out


def test_token_only_url_keeps_vendor_kind():
    text = f"https://ghp_{GH_BODY}@github.com/o/r.git"
    assert redact(text) == "https://[REDACTED:github_token]@github.com/o/r.git"
    assert find_secrets(text) == ["github_token"]


def test_token_only_url_user_kept_host_kept():
    out = redact("https://oauth2tokenvalue12345@github.com/o/r.git")
    assert out == "https://[REDACTED:url_credentials]@github.com/o/r.git"


def test_signature_replaces_only_value():
    out = redact("https://s.test/o?X-Amz-Signature=abcdef0123&X-Amz-Expires=60")
    assert out == "https://s.test/o?X-Amz-Signature=[REDACTED:url_signature]&X-Amz-Expires=60"


@pytest.mark.parametrize(
    "flag",
    [
        "password", "passwd", "pass", "token", "api-key", "apikey", "api_key", "secret",
        "client-secret", "auth-token", "access-token", "access-key", "secret-key",
    ],
)
def test_cli_flag_equals_form_for_every_flag(flag):
    out = redact(f"tool --{flag}=v1")
    assert out == f"tool --{flag}=[REDACTED:cli_flag]"
    assert redact(out) == out


def test_cli_u_forms_keep_username():
    assert redact("curl -uadmin:Hunter2Hunter2 x") == "curl -uadmin:[REDACTED:cli_flag] x"
    assert redact('curl -u "admin:Hunter2Hunter2" x') == 'curl -u "admin:[REDACTED:cli_flag]" x'


def test_supabase_boundary_applies_to_both_alternatives():
    text = f"x_sb_secret_{FAKE20}"
    assert redact(text) == text
    assert redact(f"x sb_secret_{FAKE20}") == "x [REDACTED:supabase_key]"


def test_kind_order_is_stable():
    text = (
        "DB_PASSWORD=dev123 https://s.test/?sig=abc pypi-AgEI" + "FAKEfake0123_-" * 5
    )
    assert find_secrets(text) == ["pypi_token", "url_signature", "env_assignment"]


@pytest.mark.parametrize(
    "text",
    [
        'curl -u "user:pass word" https://x.test',
        "curl -u 'admin:Hunter2 Hunter2' https://x.test",
        'curl --user "admin:two words here" https://x.test',
        'curl -u"admin:pass word" https://x.test',
    ],
)
def test_quoted_user_password_with_spaces_is_redacted_to_the_closing_quote(text):
    out = redact(text)
    assert "word" not in out and "Hunter2" not in out
    assert out.count("[REDACTED:cli_flag]") == 1
    assert out.endswith(" https://x.test")
    assert redact(out) == out
