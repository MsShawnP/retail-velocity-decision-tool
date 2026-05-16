"""Tests for chart helper functions -- pure layout logic, no DB needed."""

from __future__ import annotations

import plotly.graph_objects as go
import pytest

from charts import apply_hbar_layout, base_chart_layout, text_annotation, add_vline_at_date
from constants import NAVY, PAGE_BG, WHITE


# ============================================================
# base_chart_layout
# ============================================================

class TestBaseChartLayout:
    def test_returns_dict(self):
        layout = base_chart_layout(height=400)
        assert isinstance(layout, dict)

    def test_height_applied(self):
        layout = base_chart_layout(height=350)
        assert layout["height"] == 350

    def test_brand_colors(self):
        layout = base_chart_layout(height=400)
        assert layout["paper_bgcolor"] == PAGE_BG
        assert layout["plot_bgcolor"] == WHITE

    def test_axis_titles(self):
        layout = base_chart_layout(height=400, x_title="Velocity", y_title="SKU")
        assert layout["xaxis"]["title"] == "Velocity"
        assert layout["yaxis"]["title"] == "SKU"

    def test_legend_toggle(self):
        assert base_chart_layout(height=400, show_legend=True)["showlegend"] is True
        assert base_chart_layout(height=400, show_legend=False)["showlegend"] is False

    def test_left_margin(self):
        layout = base_chart_layout(height=400, left_margin=200)
        assert layout["margin"]["l"] == 200


# ============================================================
# apply_hbar_layout
# ============================================================

class TestApplyHbarLayout:
    def _make_fig(self, x_values, y_labels):
        fig = go.Figure(go.Bar(x=x_values, y=y_labels, orientation="h"))
        return fig

    def test_hides_default_ticklabels(self):
        fig = self._make_fig([3.0, 5.0], ["A", "B"])
        apply_hbar_layout(fig, ["A", "B"], height=300)
        assert fig.layout.yaxis.showticklabels is False

    def test_adds_label_annotations(self):
        fig = self._make_fig([3.0, 5.0], ["SKU-A", "SKU-B"])
        apply_hbar_layout(fig, ["SKU-A", "SKU-B"], height=300)
        annots = [a for a in fig.layout.annotations if a.text in ("SKU-A", "SKU-B")]
        assert len(annots) == 2

    def test_deduplicates_labels(self):
        fig = self._make_fig([3.0, 5.0], ["Same", "Same"])
        apply_hbar_layout(fig, ["Same", "Same"], height=300)
        annots = [a for a in fig.layout.annotations if a.text == "Same"]
        assert len(annots) == 1

    def test_x_range_pads_positive_data(self):
        fig = self._make_fig([10.0], ["A"])
        apply_hbar_layout(fig, ["A"], height=300, x_pad_pct=0.20)
        xrange = fig.layout.xaxis.range
        assert xrange[0] == 0  # positive-only data pins left at 0
        assert xrange[1] > 10.0  # right extends past max

    def test_x_range_extends_below_zero_for_negative(self):
        fig = self._make_fig([-5.0, 10.0], ["A", "B"])
        apply_hbar_layout(fig, ["A", "B"], height=300, x_pad_pct=0.20)
        xrange = fig.layout.xaxis.range
        assert xrange[0] < -5.0  # extends below negative min

    def test_empty_labels_no_error(self):
        fig = self._make_fig([3.0], ["A"])
        apply_hbar_layout(fig, [], height=300)
        # Should not raise; no annotations for labels
        annots = [a for a in fig.layout.annotations]
        assert len(annots) == 0


# ============================================================
# text_annotation
# ============================================================

class TestTextAnnotation:
    def test_returns_dict_with_text(self):
        result = text_annotation("Hello")
        assert result["text"] == "Hello"
        assert "font" in result

    def test_override_kwargs(self):
        result = text_annotation("Test", xanchor="left")
        assert result["xanchor"] == "left"


# ============================================================
# add_vline_at_date
# ============================================================

class TestAddVlineAtDate:
    def test_adds_shape_and_annotation(self):
        fig = go.Figure(go.Scatter(x=["2025-01-01", "2025-02-01"], y=[1, 2]))
        add_vline_at_date(fig, "2025-01-15", "Start", color="#FF0000")
        assert len(fig.layout.shapes) == 1
        assert len(fig.layout.annotations) == 1
        assert fig.layout.shapes[0].line.color == "#FF0000"

    def test_bottom_position(self):
        fig = go.Figure(go.Scatter(x=["2025-01-01"], y=[1]))
        add_vline_at_date(fig, "2025-01-01", "X", color="#000", annotation_position="bottom left")
        annot = fig.layout.annotations[0]
        assert annot.y == 0.0
        assert annot.xanchor == "right"
