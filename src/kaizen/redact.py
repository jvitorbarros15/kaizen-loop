import re
from typing import Any

_TERM = r"""\s"'`\\()\[\]{}<>,;|&"""
_KEYWORDS = r"(?i:SECRET|TOKEN|PASSWORD|PASSWD|API[_-]?KEY|PRIVATE_KEY)[A-Za-z0-9_]{0,40}+"
_ASSIGN = _KEYWORDS + r"""\\?["']?[ \t]*[:=](?!=)[ \t]*"""
_NOT_MARKER = r"(?!\[REDACTED:)"
_SK_BOUNDARY = r"(?:(?<![A-Za-z0-9_-])|(?<=\\[nrt]))"
_PEM_KIND = r"(?:[A-Z]+ )*PRIVATE KEY(?: BLOCK)?"

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
    ("aws_key", re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])")),
    (
        "jwt",
        re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*"),
    ),
    (
        "bearer",
        re.compile(r"\b(?i:bearer)[ \t]+(?P<secret>[A-Za-z0-9._~+/=-]{16,}+)"),
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
            _ASSIGN
            + r"""\\?["']"""
            + _NOT_MARKER
            + r"""(?P<secret>(?:[^"'\\\r\n]|\\(?!["'])){8,}+)"""
        ),
    ),
    (
        "env_assignment",
        re.compile(
            _ASSIGN
            + _NOT_MARKER
            + rf"(?![A-Za-z_][A-Za-z0-9_]*+(?:\.[A-Za-z_][A-Za-z0-9_]*+)++(?:[{_TERM}]|$))"
            + rf"(?![a-z_]++(?:[{_TERM}]|$))"
            + rf"(?P<secret>[^{_TERM}]{{8,}}+)(?![(\[])"
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
        return {
            (redact(k) if isinstance(k, str) else k): redact_obj(v) for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact_obj(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(redact_obj(v) for v in obj)
    return obj
