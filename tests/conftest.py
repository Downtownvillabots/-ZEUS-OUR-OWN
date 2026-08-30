"""
Shared pytest fixtures.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def fake_settings():
    """
    Minimal settings object for integration-unit tests.

    Replace this fixture with the project's actual Settings factory
    once the concrete configuration contract is finalized.
    """

    class FakeSettings:

        environment = "test"

        def validate(
            self,
            raise_on_error: bool = False,
        ):
            return []

    return FakeSettings()