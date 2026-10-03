import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop("MIHWAR_LLM", None)

from fastapi.testclient import TestClient  # noqa: E402

from mihwar.app import create_app  # noqa: E402
from mihwar.config import load_settings  # noqa: E402
from mihwar.context import Context  # noqa: E402
from mihwar.db import Database  # noqa: E402
from mihwar.seed import seed  # noqa: E402

# demo identities (see mihwar/seed.py)
MANAGER, SARAH, FAHAD, NOURA, ABDULRAHMAN, LAMA, MAJED, LAYAN = 1, 2, 3, 4, 5, 6, 7, 8
CLIENT1, CLIENT2, CLIENT3, CLIENT4 = 9, 10, 11, 12


def H(uid: int) -> dict:
    return {"X-Demo-User": str(uid)}


@pytest.fixture
def settings(tmp_path):
    return load_settings(data_dir=tmp_path, llm_enabled=False, scenario_delay=0.0, seed_activity=True)


@pytest.fixture
def ctx(settings, tmp_path):
    c = Context(settings, Database(tmp_path / "test.db"))
    seed(c)
    yield c
    c.db.close()


@pytest.fixture
def client(ctx):
    return TestClient(create_app(ctx=ctx))


@pytest.fixture
def pid(ctx):
    """Project ids by code."""
    return {p["code"]: p["id"] for p in ctx.db.all("SELECT id, code FROM projects")}
