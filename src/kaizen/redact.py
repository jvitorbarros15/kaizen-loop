import re
from typing import Any

_TERM = r"""\s"'`\\()\[\]{}<>,;|&"""
_KW = r"SECRET|TOKEN|PASSWORD|PASSWD|API[_-]?KEY|PRIVATE_KEY|CREDENTIAL|PASSPHRASE|ACCESS_KEY"
_KW_UP = _KW.replace("[_-]?", "_?")
_NAME_ANY = rf"(?i:{_KW})[A-Za-z0-9_]{{0,40}}+"
_ID_START = r"(?:(?<![A-Za-z0-9_])|(?<=\\[nrt]))"
_NAME_CAPS = (
    _ID_START
    + rf"(?:[A-Z0-9_]{{0,60}}?(?:{_KW_UP})[A-Z0-9_]{{0,40}}+|[A-Z0-9_]{{0,60}}?(?:_KEY|AUTH))"
)
_NAMES = rf"(?:{_NAME_ANY}|{_NAME_CAPS})"
_SEP = r"""\\?["']?[ \t]*[:=](?!=)[ \t]*"""
_SEP_COLON = r"""\\?["']?[ \t]*:[ \t]*"""
_NOT_MARKER = r"(?!\[REDACTED:)"
_LINE_END = r"(?=[ \t]*(?:[\r\n]|\\[nr]|\Z))"
_NOT_DIGITS = rf"(?![0-9]++(?:[{_TERM}]|$))"
_NOT_DIGITS_LINE = r"(?![0-9]++[ \t]*(?:[\r\n]|\\[nr]|\Z))"
_NOT_IDENT = (
    rf"(?![A-Za-z_][A-Za-z0-9_]*+(?:\.[A-Za-z_][A-Za-z0-9_]*+)++(?:[{_TERM}]|$))"
    rf"(?![a-z_]++(?:[{_TERM}]|$))"
)
_UNQ = rf"(?P<secret>[^{_TERM}]{{8,}}+)"
_BOUNDARY = r"(?:(?<![A-Za-z0-9_])|(?<=\\[nrt]))"
_SK_BOUNDARY = r"(?:(?<![A-Za-z0-9_-])|(?<=\\[nrt]))"
_PEM_KIND = r"(?:[A-Z]+ )*PRIVATE KEY(?: BLOCK)?"
_FLAGS = (
    "password|passwd|pass|token|api-key|apikey|api_key|secret|client-secret"
    "|auth-token|access-token|access-key|secret-key"
)

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "private_key",
        re.compile(
            rf"-----BEGIN {_PEM_KIND}-----"
            rf"(?:(?:(?!-----END )[\s\S]){{0,20000}}+-----END {_PEM_KIND}-----"
            r"|[A-Za-z0-9+/=\s\\:,-]{0,8192}+)"
        ),
    ),
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}")),
    (
        "openai_key",
        re.compile(
            _SK_BOUNDARY
            + r"sk-(?:(?:proj|svcacct|admin)-[A-Za-z0-9_-]{20,}|[A-Za-z0-9]{20,})"
        ),
    ),
    (
        "github_token",
        re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})"),
    ),
    ("stripe_key", re.compile(r"(?:(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}|whsec_[A-Za-z0-9]{16,})")),
    ("slack_token", re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}")),
    ("google_key", re.compile(r"AIza[A-Za-z0-9_-]{35}")),
    ("hf_token", re.compile(_BOUNDARY + r"hf_[A-Za-z0-9]{30,}")),
    ("npm_token", re.compile(_BOUNDARY + r"npm_[A-Za-z0-9]{30,}")),
    ("gitlab_token", re.compile(r"glpat-[A-Za-z0-9_-]{20,}")),
    (
        "supabase_key",
        re.compile(
            _BOUNDARY + r"sbp_[A-Za-z0-9]{30,}|sb_secret_[A-Za-z0-9_-]{20,}"
        ),
    ),
    ("aws_key", re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])")),
    (
        "jwt",
        re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*"),
    ),
    (
        "basic_auth",
        re.compile(
            r"""(?i:authorization)\\?["']?[ \t]*[:=][ \t]*\\?["']?(?i:basic)[ \t]+"""
            r"(?P<secret>[A-Za-z0-9+/]{8,}+={0,2})"
        ),
    ),
    (
        "bearer",
        re.compile(r"\b(?i:bearer)[ \t]+(?P<secret>[A-Za-z0-9._~+/=-]{16,}+)"),
    ),
    (
        "cli_flag",
        re.compile(
            rf"(?<![\w-])--(?:{_FLAGS})(?![\w-])[ \t]+" + _NOT_MARKER
            + r"""(?P<secret>"(?:[^"\\\r\n]|\\.)*+"|'[^'\r\n]*+'|\\["'][^\\\r\n]*+\\["']"""
            r"""|[^\s"'\\-][^\s"'\\]*+)"""
        ),
    ),
    (
        "cli_flag",
        re.compile(
            r"""(?<![\w-])(?:-u|--user)[ \t]+(?![0-9]+:)[^\s:"'\\]+:""" + _NOT_MARKER
            + r"""(?P<secret>[^\s"'\\]+)"""
        ),
    ),
    (
        "url_credentials",
        re.compile(
            r"""(?<=://)[^\s:/@"']+:""" + _NOT_MARKER + r"""(?P<secret>[^\s@/"']+)(?=@)"""
        ),
    ),
    (
        "env_assignment",
        re.compile(
            _NAMES + _SEP + r"""(?<!\\)(?P<q>["'])""" + _NOT_MARKER
            + r"(?P<secret>(?:(?!(?P=q))[^\\\r\n]|\\.){8,}+)"
        ),
    ),
    (
        "env_assignment",
        re.compile(
            _NAMES + _SEP + r"""\\(?P<q>["'])""" + _NOT_MARKER
            + r"(?P<secret>(?:[^\\\r\n]|\\(?!(?P=q))[\s\S]){8,}+)"
        ),
    ),
    (
        "env_assignment",
        re.compile(
            _NAME_CAPS + r"=(?!=)" + _NOT_MARKER + r"""(?P<secret>[^\s"'`\\&;,<>|]{8,}+)"""
        ),
    ),
    (
        "env_assignment",
        re.compile(_NAME_CAPS + _SEP_COLON + _NOT_MARKER + _UNQ + _LINE_END),
    ),
    (
        "env_assignment",
        re.compile(
            _NAME_ANY + _SEP_COLON + _NOT_MARKER + _NOT_DIGITS_LINE + _UNQ + _LINE_END
        ),
    ),
    (
        "env_assignment",
        re.compile(
            _NAME_ANY + r"=(?!=)" + _NOT_MARKER + _NOT_DIGITS + _UNQ + r"(?![(\[])"
        ),
    ),
    (
        "env_assignment",
        re.compile(
            _NAME_CAPS + _SEP + _NOT_MARKER + _NOT_IDENT + _UNQ + r"(?![(\[])"
        ),
    ),
    (
        "env_assignment",
        re.compile(
            _NAME_ANY + _SEP + _NOT_MARKER + _NOT_DIGITS + _NOT_IDENT + _UNQ + r"(?![(\[])"
        ),
    ),
    ("cpf", re.compile(r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)")),
    (
        "cpf",
        re.compile(
            r"(?<![A-Za-z])(?i:cpf)[A-Za-z_]{0,12}[^\w\n]{0,8}(?<!\d)(?P<secret>\d{11})(?!\d)"
        ),
    ),
]


def _scrub(text: str) -> tuple[str, list[str]]:
    kinds: list[str] = []
    for kind, pattern in _PATTERNS:
        tag = f"[REDACTED:{kind}]"

        def repl(m: re.Match[str], tag: str = tag) -> str:
            if m.re.groupindex.get("secret") is None:
                return tag
            whole, base = m.group(0), m.start()
            return whole[: m.start("secret") - base] + tag + whole[m.end("secret") - base :]

        text, n = pattern.subn(repl, text)
        if n and kind not in kinds:
            kinds.append(kind)
    return text, kinds


def redact(text: str) -> str:
    return _scrub(text)[0]


def find_secrets(text: str) -> list[str]:
    return _scrub(text)[1]


def redact_obj(obj: Any) -> Any:
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        out: dict[Any, Any] = {}
        for k, v in obj.items():
            key = redact(k) if isinstance(k, str) else k
            if key in out:
                n = 2
                while f"{key}#{n}" in out:
                    n += 1
                key = f"{key}#{n}"
            out[key] = redact_obj(v)
        return out
    if isinstance(obj, list):
        return [redact_obj(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(redact_obj(v) for v in obj)
    return obj
