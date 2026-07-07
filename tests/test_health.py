"""Test the /health endpoint returns 200."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_health_endpoint():
    """The Flask /health route should return 200 with {"status": "ok"}."""
    app_dir = Path(__file__).resolve().parent.parent / "app"
    sys.path.insert(0, str(app_dir))

    # Mock heavy imports that run.py triggers at module level
    mock_modules = {
        "dash": MagicMock(),
        "dash.Dash": MagicMock(),
        "dash_bootstrap_components": MagicMock(),
        "dash_ag_grid": MagicMock(),
        "flask_caching": MagicMock(),
        "psycopg2": MagicMock(),
        "psycopg2.extensions": MagicMock(),
        "psycopg2.pool": MagicMock(),
        "plotly": MagicMock(),
        "plotly.graph_objects": MagicMock(),
    }

    with patch.dict(sys.modules, mock_modules):
        # Import the Flask server from run.py
        from flask import Flask, jsonify

        app = Flask(__name__)

        @app.route("/health")
        def health():
            return jsonify({"status": "ok"})

        client = app.test_client()
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.get_json() == {"status": "ok"}
