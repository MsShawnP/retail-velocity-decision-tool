"""Tests for callback dispatch routing and filter visibility logic.

These test the mapping structures and routing tables in callbacks.py
without needing a running Dash app or database.
"""

from __future__ import annotations

import pytest

from constants import DECISIONS, DECISION_TITLES, PORTFOLIO_HEALTH


# ============================================================
# Decision / filter mapping integrity
# ============================================================

class TestDecisionMapping:
    """Verify the DECISIONS list and supporting maps are consistent."""

    def test_eight_decisions_in_list(self):
        assert len(DECISIONS) == 8

    def test_every_decision_has_title(self):
        for d in DECISIONS:
            assert d in DECISION_TITLES

    def test_portfolio_health_is_separate(self):
        """Portfolio Health is NOT in the DECISIONS list — it's a landing page."""
        assert PORTFOLIO_HEALTH not in DECISIONS

    def test_no_duplicate_decisions(self):
        assert len(DECISIONS) == len(set(DECISIONS))


class TestFilterIds:
    """The _FILTER_IDS list in callbacks.py must have len(DECISIONS) + 1 entries
    (one extra for the portfolio filter group)."""

    def test_filter_ids_length(self):
        from callbacks import _FILTER_IDS
        # Portfolio (1) + 8 decision modes
        assert len(_FILTER_IDS) == 9

    def test_filter_ids_are_unique(self):
        from callbacks import _FILTER_IDS
        assert len(_FILTER_IDS) == len(set(_FILTER_IDS))


class TestModeInputs:
    """_MODE_INPUTS maps mode index → set of component IDs that trigger re-render."""

    def test_all_mode_indices_covered(self):
        from callbacks import _MODE_INPUTS
        for i in range(8):
            assert i in _MODE_INPUTS

    def test_launch_has_no_inputs(self):
        """Mode 6 (Launch Health) has no filter inputs — it shows all launches."""
        from callbacks import _MODE_INPUTS
        assert _MODE_INPUTS[6] == set()

    def test_all_input_ids_are_strings(self):
        from callbacks import _MODE_INPUTS
        for idx, ids in _MODE_INPUTS.items():
            for comp_id in ids:
                assert isinstance(comp_id, str), f"Mode {idx}: {comp_id}"


class TestDecisionIndexing:
    """The dispatch logic uses DECISIONS.index() to route modes.
    Verify each mode name resolves to the expected index."""

    def test_shelf_defense_is_index_0(self):
        assert DECISIONS[0] == "Is this SKU at risk of being delisted?"

    def test_production_is_index_1(self):
        assert DECISIONS[1] == "How much should I produce over the next 4 weeks?"

    def test_launch_health_is_index_6(self):
        assert DECISIONS[6] == "Is my new launch on track?"
