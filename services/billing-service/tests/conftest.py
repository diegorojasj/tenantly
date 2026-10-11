from __future__ import annotations

import uuid

import pytest


@pytest.fixture
def ids() -> dict[str, str]:
    return {k: str(uuid.uuid4()) for k in ("tenant", "org", "a", "b", "customer")}
