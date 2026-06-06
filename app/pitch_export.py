"""Retailer Pitch Export — multi-sheet Excel and branded PDF.

Pulls data from the same queries used by the decision modes and packages
it into a buyer-ready document: portfolio summary + shelf defense +
production planning + SKU rationalization + launch health.
"""

from __future__ import annotations

from datetime import date
from io import BytesIO

import pandas as pd
from fpdf import FPDF

from calcs import classify_launch, classify_quadrant, classify_shelf_status
from constants import CHICAGO, GREY, LAUNCH_BENCHMARK, INK, TEXT_SEC
from data import (
    get_latest_week,
    get_launch_data,
    get_production_data,
    get_rationalization_data,
    get_shelf_defense_data,
)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert '#rrggbb' to (r, g, b) integers for FPDF."""
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# ============================================================
# Shared data assembly
# ============================================================

def _gather(retailer: str, product_line: str | None, threshold: float) -> dict:
    """Fetch and classify all data needed for the pitch export."""
    latest = get_latest_week()

    shelf_df = get_shelf_defense_data(retailer, product_line)
    if not shelf_df.empty:
        shelf_df = classify_shelf_status(shelf_df, threshold)

    prod_df = get_production_data(retailer, product_line)

    rat_df = get_rationalization_data(retailer, product_line)
    if not rat_df.empty:
        median_v = rat_df["velocity"].median()
        median_m = rat_df["margin_per_sw"].median()
        rat_df["high_velocity"] = rat_df["velocity"] > median_v
        rat_df["high_margin"] = rat_df["margin_per_sw"] > median_m
        rat_df["quadrant"] = rat_df.apply(classify_quadrant, axis=1)

    launch_df = get_launch_data()
    if not launch_df.empty:
        launch_df["status"] = launch_df.apply(
            lambda r: classify_launch(r, threshold=LAUNCH_BENCHMARK), axis=1
        )

    return {
        "latest": latest,
        "shelf": shelf_df,
        "production": prod_df,
        "rationalization": rat_df,
        "launch": launch_df,
    }


def _display_shelf(df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    if df.empty:
        return df
    return pd.DataFrame({
        "SKU": df["sku"],
        "Product Name": df["product_name"],
        "Product Line": df["product_line"],
        "Current Velocity": df["current_v"].round(2),
        "Trailing Velocity": df["trailing_v"].round(2),
        "Trend %": df["trend_pct"].round(2),
        "Threshold": round(threshold, 2),
        "Status": df["status"],
    })


def _display_production(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    cols = {
        "SKU": df["sku"],
        "Product Name": df["product_name"],
        "Doors": df["doors"],
        "Weekly Units": df["weekly_units"].round(0).astype(int),
        "Weekly Cases": df["weekly_cases"].fillna(0).round(0).astype(int),
        "4-Wk Forecast (cases)": df["forecast_4w_cases"].fillna(0).round(0).astype(int),
        "Trend %": df["trend_pct"].round(2),
        "Status": df["status"],
    }
    return pd.DataFrame(cols)


def _display_rationalization(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return pd.DataFrame({
        "SKU": df["sku"],
        "Product Name": df["product_name"],
        "Velocity": df["velocity"].round(2),
        "Margin/Unit": df["margin_per_sw"].round(2),
        "Weekly Total Margin": df["weekly_total_margin"].round(2),
        "Quadrant": df["quadrant"],
    })


def _display_launch(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    cols = {
        "SKU": df["sku"],
        "Product Name": df["product_name"],
        "Launch Date": df["launch_date"],
        "Weeks Since": df["weeks_since_launch"],
        "Wks 1-4 Vel": df["v_w14"].round(2),
        "Current Vel": df["v_current"].round(2),
        "Status": df["status"],
    }
    return pd.DataFrame(cols)


# ============================================================
# Excel builder
# ============================================================

def build_pitch_excel(
    retailer: str,
    product_line: str | None,
    threshold: float,
) -> dict:
    """Return {content: bytes, filename: str} for dcc.send_bytes."""
    data = _gather(retailer, product_line, threshold)
    buf = BytesIO()

    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        wb = writer.book

        # -- Formats --
        title_fmt = wb.add_format({
            "bold": True, "font_size": 16, "font_color": INK,
        })
        subtitle_fmt = wb.add_format({
            "bold": True, "font_size": 11, "font_color": GREY,
        })
        header_fmt = wb.add_format({
            "bold": True, "bg_color": CHICAGO, "font_color": "#FFFFFF",
            "border": 1,
        })

        # -- Summary sheet --
        ws = wb.add_worksheet("Summary")
        writer.sheets["Summary"] = ws
        ws.set_column("A:A", 30)
        ws.set_column("B:B", 40)
        ws.write("A1", "Cinderhaven Provisions — Retailer Pitch", title_fmt)
        ws.write("A3", "Retailer", subtitle_fmt)
        ws.write("B3", retailer)
        ws.write("A4", "Product Line", subtitle_fmt)
        ws.write("B4", product_line or "All")
        ws.write("A5", "Delisting Threshold", subtitle_fmt)
        ws.write("B5", f"{threshold:.2f} units/store/week")
        ws.write("A6", "Most Recent Week", subtitle_fmt)
        ws.write("B6", data["latest"])
        ws.write("A7", "Export Date", subtitle_fmt)
        ws.write("B7", date.today().isoformat())

        row = 9
        if not data["shelf"].empty:
            n_risk = int((data["shelf"]["status"] == "At Risk").sum())
            n_warn = int((data["shelf"]["status"] == "Warning").sum())
            n_safe = int((data["shelf"]["status"] == "Safe").sum())
            ws.write(row, 0, "Portfolio Health", subtitle_fmt)
            row += 1
            ws.write(row, 0, "Total SKUs")
            ws.write(row, 1, len(data["shelf"]))
            row += 1
            ws.write(row, 0, "At Risk")
            ws.write(row, 1, n_risk)
            row += 1
            ws.write(row, 0, "Warning")
            ws.write(row, 1, n_warn)
            row += 1
            ws.write(row, 0, "Safe")
            ws.write(row, 1, n_safe)
            row += 2

        if not data["production"].empty:
            ws.write(row, 0, "Production Outlook", subtitle_fmt)
            row += 1
            n_accel = int((data["production"]["status"] == "Accelerating").sum())
            n_decel = int((data["production"]["status"] == "Decelerating").sum())
            ws.write(row, 0, "Accelerating SKUs")
            ws.write(row, 1, n_accel)
            row += 1
            ws.write(row, 0, "Decelerating SKUs")
            ws.write(row, 1, n_decel)
            row += 1
            ws.write(row, 0, "4-Wk Forecast (total cases)")
            ws.write(row, 1, int(data["production"]["forecast_4w_cases"].sum()))
            row += 2

        if not data["rationalization"].empty:
            ws.write(row, 0, "SKU Rationalization", subtitle_fmt)
            row += 1
            for q in ["Winner", "Volume play", "Niche / slow", "Cut candidate"]:
                ws.write(row, 0, q)
                ws.write(row, 1, int((data["rationalization"]["quadrant"] == q).sum()))
                row += 1

        # -- Detail sheets --
        def _write_sheet(name, df):
            if df.empty:
                return
            df.to_excel(writer, sheet_name=name, index=False, startrow=1)
            ws = writer.sheets[name]
            ws.write("A1", name, title_fmt)
            for col_num, col_name in enumerate(df.columns):
                ws.write(1, col_num, col_name, header_fmt)

        if not data["shelf"].empty:
            _write_sheet("Shelf Defense", _display_shelf(data["shelf"], threshold))

        if not data["production"].empty:
            _write_sheet("Production Planning", _display_production(data["production"]))

        if not data["rationalization"].empty:
            _write_sheet("SKU Rationalization", _display_rationalization(data["rationalization"]))

        if not data["launch"].empty:
            _write_sheet("Launch Health", _display_launch(data["launch"]))

    safe_ret = retailer.lower().replace(" ", "_")
    safe_pl = (product_line or "all").lower().replace(" ", "_")
    return {
        "content": buf.getvalue(),
        "filename": f"cinderhaven_pitch_{safe_ret}_{safe_pl}.xlsx",
    }


# ============================================================
# PDF builder
# ============================================================

class _PitchPDF(FPDF):
    """Branded Cinderhaven PDF with header/footer."""

    def header(self):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*_hex_to_rgb(INK))
        self.cell(0, 6, "CINDERHAVEN PROVISIONS", align="L")
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*_hex_to_rgb(GREY))
        self.cell(0, 6, f"Generated {date.today().isoformat()}", align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*_hex_to_rgb(CHICAGO))
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    def section_title(self, title: str):
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(*_hex_to_rgb(INK))
        self.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def kv_line(self, label: str, value: str):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*_hex_to_rgb(TEXT_SEC))
        self.cell(55, 7, label)
        self.set_font("Helvetica", "", 10)
        self.set_text_color(60, 60, 60)
        self.cell(0, 7, str(value), new_x="LMARGIN", new_y="NEXT")

    def add_table(self, df: pd.DataFrame, col_widths: list[float] | None = None):
        if df.empty:
            return
        cols = list(df.columns)
        available = self.w - self.l_margin - self.r_margin
        if col_widths is None:
            col_widths = [available / len(cols)] * len(cols)

        self.set_font("Helvetica", "B", 8)
        self.set_fill_color(*_hex_to_rgb(CHICAGO))
        self.set_text_color(255, 255, 255)
        for i, col in enumerate(cols):
            self.cell(col_widths[i], 7, str(col)[:20], border=1, fill=True)
        self.ln()

        self.set_font("Helvetica", "", 7.5)
        self.set_text_color(60, 60, 60)
        for _, row in df.head(50).iterrows():
            if self.get_y() > self.h - 25:
                self.add_page()
                self.set_font("Helvetica", "B", 8)
                self.set_fill_color(*_hex_to_rgb(CHICAGO))
                self.set_text_color(255, 255, 255)
                for i, col in enumerate(cols):
                    self.cell(col_widths[i], 7, str(col)[:20], border=1, fill=True)
                self.ln()
                self.set_font("Helvetica", "", 7.5)
                self.set_text_color(60, 60, 60)

            for i, col in enumerate(cols):
                val = row[col]
                text = "" if pd.isna(val) else str(val)
                self.cell(col_widths[i], 6, text[:25], border=1)
            self.ln()

        if len(df) > 50:
            self.set_font("Helvetica", "I", 7)
            self.set_text_color(100, 100, 100)
            self.cell(0, 5, f"Showing 50 of {len(df)} rows", ln=True)
        self.ln(4)


def build_pitch_pdf(
    retailer: str,
    product_line: str | None,
    threshold: float,
) -> dict:
    """Return {content: bytes, filename: str} for dcc.send_bytes."""
    data = _gather(retailer, product_line, threshold)

    pdf = _PitchPDF(orientation="L", format="letter")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # -- Title --
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*_hex_to_rgb(INK))
    pdf.cell(0, 12, "Retailer Pitch Report", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # -- Summary --
    pdf.kv_line("Retailer:", retailer)
    pdf.kv_line("Product Line:", product_line or "All")
    pdf.kv_line("Delisting Threshold:", f"{threshold:.2f} units/store/week")
    pdf.kv_line("Most Recent Week:", data["latest"])
    pdf.ln(6)

    # -- Portfolio health --
    if not data["shelf"].empty:
        n_risk = int((data["shelf"]["status"] == "At Risk").sum())
        n_warn = int((data["shelf"]["status"] == "Warning").sum())
        n_safe = int((data["shelf"]["status"] == "Safe").sum())
        pdf.kv_line("Total SKUs:", str(len(data["shelf"])))
        pdf.kv_line("At Risk:", str(n_risk))
        pdf.kv_line("Warning:", str(n_warn))
        pdf.kv_line("Safe:", str(n_safe))
        pdf.ln(4)

    # -- Shelf Defense table --
    if not data["shelf"].empty:
        pdf.add_page()
        pdf.section_title("Shelf Defense")
        shelf_display = _display_shelf(data["shelf"], threshold)
        widths = [22, 55, 35, 30, 30, 22, 22, 22]
        pdf.add_table(shelf_display, widths)

    # -- Production Planning table --
    if not data["production"].empty:
        pdf.add_page()
        pdf.section_title("Production Planning — Next 4 Weeks")
        prod_display = _display_production(data["production"])
        widths = [22, 55, 18, 28, 28, 38, 22, 27]
        pdf.add_table(prod_display, widths)

    # -- SKU Rationalization table --
    if not data["rationalization"].empty:
        pdf.add_page()
        pdf.section_title("SKU Rationalization")
        rat_display = _display_rationalization(data["rationalization"])
        widths = [25, 60, 30, 30, 40, 35]
        pdf.add_table(rat_display, widths)

    # -- Launch Health table --
    if not data["launch"].empty:
        pdf.add_page()
        pdf.section_title("Launch Health")
        launch_display = _display_launch(data["launch"])
        widths = [25, 55, 30, 25, 30, 30, 30]
        pdf.add_table(launch_display, widths)

    safe_ret = retailer.lower().replace(" ", "_")
    safe_pl = (product_line or "all").lower().replace(" ", "_")
    return {
        "content": pdf.output(),
        "filename": f"cinderhaven_pitch_{safe_ret}_{safe_pl}.pdf",
    }
