"""Tests for startup data contract validation.

Mocks the database connection to verify each of the 7 SQL checks
returns correct (passed, detail) tuples for both healthy and degraded data.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from validation import EXPECTED_RETAILERS, log_validation_results, validate_data_contract


@contextmanager
def _mock_conn():
    conn = MagicMock()
    yield conn


def _make_cursor(responses: list):
    """Build a mock cursor that returns successive fetchone/fetchall results."""
    cur = MagicMock()
    it = iter(responses)
    cur.fetchone = MagicMock(side_effect=lambda: next(it))
    cur.fetchall = MagicMock(side_effect=lambda: next(it))
    return cur


def _healthy_cursor():
    """Cursor that returns all-passing data for every check."""
    retailers_rows = [(r,) for r in EXPECTED_RETAILERS]
    responses = [
        # Check 1: 6 table counts
        (100,), (50,), (30,), (20,), (10,), (5,),
        # Check 2: date coverage
        ("2024-01-01", "2025-03-01", 425),
        # Check 3: case_pack_qty
        (0,),
        # Check 4: volume tiers (fetchall — no bad tiers)
        [],
        # Check 5: retailer names (fetchall)
        retailers_rows,
        # Check 6: orphan SKUs
        (0,),
        # Check 7: distribution dates
        (100, 0),
    ]
    return _make_cursor(responses)


class TestTableExistence:
    @patch("validation.get_conn", side_effect=_mock_conn)
    def test_all_tables_present(self, mock_conn):
        conn = MagicMock()
        cur = _healthy_cursor()
        conn.cursor.return_value = cur
        with patch("validation.get_conn") as gc:
            gc.return_value.__enter__ = MagicMock(return_value=conn)
            gc.return_value.__exit__ = MagicMock(return_value=False)
            results = validate_data_contract()
        assert results["table_stg_scan_data"][0] is True
        assert results["table_dim_products"][0] is True

    @patch("validation.get_conn")
    def test_empty_table_fails(self, mock_gc):
        conn = MagicMock()
        retailers_rows = [(r,) for r in EXPECTED_RETAILERS]
        responses = [
            (0,), (50,), (30,), (20,), (10,), (5,),
            ("2024-01-01", "2025-03-01", 425),
            (0,), [], retailers_rows, (0,), (100, 0),
        ]
        cur = _make_cursor(responses)
        conn.cursor.return_value = cur
        mock_gc.return_value.__enter__ = MagicMock(return_value=conn)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        results = validate_data_contract()
        assert results["table_stg_scan_data"][0] is False
        assert "empty" in results["table_stg_scan_data"][1]

    @patch("validation.get_conn")
    def test_missing_table_fails(self, mock_gc):
        conn = MagicMock()
        cur = MagicMock()
        cur.execute.side_effect = Exception("relation does not exist")
        conn.cursor.return_value = cur
        mock_gc.return_value.__enter__ = MagicMock(return_value=conn)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        results = validate_data_contract()
        assert results["table_stg_scan_data"][0] is False
        assert "missing" in results["table_stg_scan_data"][1]


class TestDateCoverage:
    @patch("validation.get_conn")
    def test_sufficient_coverage(self, mock_gc):
        conn = MagicMock()
        retailers_rows = [(r,) for r in EXPECTED_RETAILERS]
        cur = _make_cursor([
            (100,), (50,), (30,), (20,), (10,), (5,),
            ("2024-01-01", "2025-03-01", 400),
            (0,), [], retailers_rows, (0,), (100, 0),
        ])
        conn.cursor.return_value = cur
        mock_gc.return_value.__enter__ = MagicMock(return_value=conn)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        results = validate_data_contract()
        assert results["date_coverage"][0] is True

    @patch("validation.get_conn")
    def test_insufficient_coverage(self, mock_gc):
        conn = MagicMock()
        retailers_rows = [(r,) for r in EXPECTED_RETAILERS]
        cur = _make_cursor([
            (100,), (50,), (30,), (20,), (10,), (5,),
            ("2024-06-01", "2025-03-01", 273),
            (0,), [], retailers_rows, (0,), (100, 0),
        ])
        conn.cursor.return_value = cur
        mock_gc.return_value.__enter__ = MagicMock(return_value=conn)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        results = validate_data_contract()
        assert results["date_coverage"][0] is False
        assert "392" in results["date_coverage"][1]


class TestCasePackQty:
    @patch("validation.get_conn")
    def test_all_valid(self, mock_gc):
        conn = MagicMock()
        retailers_rows = [(r,) for r in EXPECTED_RETAILERS]
        cur = _make_cursor([
            (100,), (50,), (30,), (20,), (10,), (5,),
            ("2024-01-01", "2025-03-01", 425),
            (0,), [], retailers_rows, (0,), (100, 0),
        ])
        conn.cursor.return_value = cur
        mock_gc.return_value.__enter__ = MagicMock(return_value=conn)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        results = validate_data_contract()
        assert results["case_pack_qty"][0] is True

    @patch("validation.get_conn")
    def test_zero_case_pack_fails(self, mock_gc):
        conn = MagicMock()
        retailers_rows = [(r,) for r in EXPECTED_RETAILERS]
        cur = _make_cursor([
            (100,), (50,), (30,), (20,), (10,), (5,),
            ("2024-01-01", "2025-03-01", 425),
            (3,), [], retailers_rows, (0,), (100, 0),
        ])
        conn.cursor.return_value = cur
        mock_gc.return_value.__enter__ = MagicMock(return_value=conn)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        results = validate_data_contract()
        assert results["case_pack_qty"][0] is False
        assert "3" in results["case_pack_qty"][1]


class TestVolumeTiers:
    @patch("validation.get_conn")
    def test_unexpected_tier_fails(self, mock_gc):
        conn = MagicMock()
        retailers_rows = [(r,) for r in EXPECTED_RETAILERS]
        cur = _make_cursor([
            (100,), (50,), (30,), (20,), (10,), (5,),
            ("2024-01-01", "2025-03-01", 425),
            (0,), [("D",), ("E",)], retailers_rows, (0,), (100, 0),
        ])
        conn.cursor.return_value = cur
        mock_gc.return_value.__enter__ = MagicMock(return_value=conn)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        results = validate_data_contract()
        assert results["volume_tiers"][0] is False
        assert "D" in results["volume_tiers"][1]


class TestRetailerNames:
    @patch("validation.get_conn")
    def test_missing_retailer_fails(self, mock_gc):
        conn = MagicMock()
        partial = [(r,) for r in list(EXPECTED_RETAILERS)[:2]]
        cur = _make_cursor([
            (100,), (50,), (30,), (20,), (10,), (5,),
            ("2024-01-01", "2025-03-01", 425),
            (0,), [], partial, (0,), (100, 0),
        ])
        conn.cursor.return_value = cur
        mock_gc.return_value.__enter__ = MagicMock(return_value=conn)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        results = validate_data_contract()
        assert results["retailer_names"][0] is False
        assert "missing" in results["retailer_names"][1]


class TestSKUCostCoverage:
    @patch("validation.get_conn")
    def test_orphan_skus_fail(self, mock_gc):
        conn = MagicMock()
        retailers_rows = [(r,) for r in EXPECTED_RETAILERS]
        cur = _make_cursor([
            (100,), (50,), (30,), (20,), (10,), (5,),
            ("2024-01-01", "2025-03-01", 425),
            (0,), [], retailers_rows, (5,), (100, 0),
        ])
        conn.cursor.return_value = cur
        mock_gc.return_value.__enter__ = MagicMock(return_value=conn)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        results = validate_data_contract()
        assert results["sku_cost_coverage"][0] is False
        assert "5" in results["sku_cost_coverage"][1]


class TestDistributionDates:
    @patch("validation.get_conn")
    def test_null_dates_fail(self, mock_gc):
        conn = MagicMock()
        retailers_rows = [(r,) for r in EXPECTED_RETAILERS]
        cur = _make_cursor([
            (100,), (50,), (30,), (20,), (10,), (5,),
            ("2024-01-01", "2025-03-01", 425),
            (0,), [], retailers_rows, (0,), (100, 10),
        ])
        conn.cursor.return_value = cur
        mock_gc.return_value.__enter__ = MagicMock(return_value=conn)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        results = validate_data_contract()
        assert results["distribution_dates"][0] is False
        assert "10" in results["distribution_dates"][1]

    @patch("validation.get_conn")
    def test_empty_distribution_fails(self, mock_gc):
        conn = MagicMock()
        retailers_rows = [(r,) for r in EXPECTED_RETAILERS]
        cur = _make_cursor([
            (100,), (50,), (30,), (20,), (10,), (5,),
            ("2024-01-01", "2025-03-01", 425),
            (0,), [], retailers_rows, (0,), (0, 0),
        ])
        conn.cursor.return_value = cur
        mock_gc.return_value.__enter__ = MagicMock(return_value=conn)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        results = validate_data_contract()
        assert results["distribution_dates"][0] is False
        assert "empty" in results["distribution_dates"][1]


class TestLogValidation:
    def test_all_passed_logs_info(self, caplog):
        results = {"check_a": (True, "ok"), "check_b": (True, "ok")}
        with caplog.at_level("INFO", logger="validation"):
            log_validation_results(results)
        assert "2/2 checks passed" in caplog.text

    def test_partial_failure_logs_warning(self, caplog):
        results = {"check_a": (True, "ok"), "check_b": (False, "bad")}
        with caplog.at_level("WARNING", logger="validation"):
            log_validation_results(results)
        assert "1/2 checks passed" in caplog.text


class TestExpectedRetailers:
    def test_excludes_regional_aggregate(self):
        assert "Regional" not in EXPECTED_RETAILERS

    def test_includes_physical_retailers(self):
        assert "Walmart" in EXPECTED_RETAILERS
        assert "Costco" in EXPECTED_RETAILERS

    def test_includes_unfi_dtc(self):
        assert "UNFI" in EXPECTED_RETAILERS
        assert "DTC" in EXPECTED_RETAILERS
