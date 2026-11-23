import copy
import tomllib
from pathlib import Path

from kaizen.store import kaizen_home

DEFAULTS = {
    "score": {"quality": 0.4, "efficiency": 0.3, "cost": 0.3},
    "judge": {"backends": ["codex", "haiku"], "codex_repos": []},
    "budget": {"tokens_per_day": 2000000},
}


def load_config(root: Path | None = None) -> dict:
    root = kaizen_home() if root is None else Path(root)
    cfg = copy.deepcopy(DEFAULTS)
    path = root / "config.toml"
    if path.exists():
        with path.open("rb") as f:
            for section, values in tomllib.load(f).items():
                if isinstance(values, dict):
                    cfg.setdefault(section, {}).update(values)
    return cfg
