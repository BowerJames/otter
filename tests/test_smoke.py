"""Smoke tests: verify the test harness and package import work."""

import otter


async def test_package_exposes_version() -> None:
    # Async with no marker: proves pytest-asyncio auto mode is active.
    assert otter.__version__ == "0.1.0"
