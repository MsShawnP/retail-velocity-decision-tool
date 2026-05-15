"""Shared fixtures for the Cinderhaven test suite.

Tests run without a database. Any module that imports from db.py at import
time is patched here so the test process never attempts a Postgres connection.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

# Put app/ on the import path so bare imports (constants, data, etc.) resolve.
APP_DIR = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_DIR))

# Stub out db before anything imports data.py — the module-level cache setup
# and get_conn import must not trigger a real connection.
_mock_db = MagicMock()
_mock_db.get_conn = MagicMock()
_mock_db.get_pool = MagicMock()
sys.modules.setdefault("db", _mock_db)
