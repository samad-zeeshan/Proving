"""Skip client-backed tests when a client checkout is missing."""

import pytest

from proving.adapters._root import client_root


def _have(name: str) -> bool:
    try:
        client_root(name)
        return True
    except FileNotFoundError:
        return False


@pytest.fixture(scope="session")
def warden():
    if not _have("warden"):
        pytest.skip("Warden checkout not found")
    from proving.adapters import load

    return load("warden")


@pytest.fixture(scope="session")
def parley():
    if not _have("parley"):
        pytest.skip("Parley checkout not found")
    from proving.adapters import load

    return load("parley")
