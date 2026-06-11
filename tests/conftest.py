import pytest

import app as appmod


@pytest.fixture(autouse=True)
def _no_rate_limit():
    """Keep the limiter out of unrelated tests — /chat calls accumulate across
    the suite and would trip the per-minute cap. test_rate_limit re-enables it."""
    appmod.limiter.enabled = False
    yield
