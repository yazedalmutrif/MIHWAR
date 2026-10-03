"""Settings, read from environment variables and an optional .env file.

No secrets live in code. The Anthropic API key is read by the SDK from the
environment (ANTHROPIC_API_KEY) only when LLM mode is switched on.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent
DATA_CONFIG_DIR = PACKAGE_DIR / "data"
WEB_DIR = PACKAGE_DIR / "web"


def _load_dotenv() -> None:
    """Minimal .env loader (KEY=VALUE lines). Never overrides real env vars."""
    env_file = PROJECT_DIR / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _flag(name: str, default: str = "off") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "on", "true", "yes"}


@dataclass
class Settings:
    host: str = "127.0.0.1"
    port: int = 8090
    data_dir: Path = PROJECT_DIR / "var"
    llm_enabled: bool = False
    model: str = "claude-opus-5-5"
    llm_timeout: float = 30.0
    scenario_delay: float = 0.6
    seed_activity: bool = True
    extra: dict = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "mihwar.db"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"


def load_settings(**overrides) -> Settings:
    _load_dotenv()
    s = Settings(
        host=os.environ.get("MIHWAR_HOST", "127.0.0.1"),
        port=int(os.environ.get("MIHWAR_PORT", "8090")),
        data_dir=Path(os.environ.get("MIHWAR_DATA_DIR", str(PROJECT_DIR / "var"))),
        llm_enabled=_flag("MIHWAR_LLM"),
        model=os.environ.get("MIHWAR_MODEL", "claude-opus-5-5"),
        llm_timeout=float(os.environ.get("MIHWAR_LLM_TIMEOUT", "30")),
        scenario_delay=float(os.environ.get("MIHWAR_SCENARIO_DELAY", "0.6")),
        seed_activity=_flag("MIHWAR_SEED_ACTIVITY", "on"),
    )
    for key, value in overrides.items():
        setattr(s, key, value)
    return s


@lru_cache(maxsize=None)
def load_config(name: str) -> dict:
    """Editable JSON configuration (price list, rule pack, phase templates...)."""
    with open(DATA_CONFIG_DIR / f"{name}.json", encoding="utf-8") as fh:
        return json.load(fh)
