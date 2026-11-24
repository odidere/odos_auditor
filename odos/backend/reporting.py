"""Efficiency score and the PDF cost report."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping


def calculate_efficiency(annual_burn: float, annual_waste: float) -> float:
    """Share of spend that was not flagged as waste, 0-100."""
    if annual_burn <= 0:
        return 100.0
    return max(0.0, 100.0 - (annual_waste / annual_burn * 100.0))


def _rows(anomalies: Any) -> list[Mapping[str, Any]]:
    if anomalies is None:
        return []
    if hasattr(anomalies, "to_dict"):  # pandas DataFrame
        return anomalies.to_dict(orient="records")
    return list(anomalies)


def generate_pdf_binary(metrics: dict, anomalies: Iterable[Mapping[str, Any]] | Any, project_name: str) -> bytes:
    """PDF report. ``anomalies`` may be a list of dicts or a DataFrame. Amounts are USD."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, text=f"Cost Report: {project_name}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "I", 10)
    pdf.cell(0, 10, text=f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
             new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.line(10, 30, 200, 30)

    pdf.ln(15)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(0, 10, text="1. Financial summary (USD)", new_x="LMARGIN", new_y="NEXT", fill=True)
    pdf.set_font("Helvetica", size=11)
    pdf.ln(2)
    pdf.cell(95, 10, text=f"Projected annual spend: ${metrics.get('burn', 0):,.2f}")
    pdf.cell(95, 10, text=f"Flagged waste (annualised): ${metrics.get('waste', 0):,.2f}",
             new_x="LMARGIN", new_y="NEXT")
    pdf.cell(95, 10, text=f"Monthly budget: ${metrics.get('budget', 0):,.2f}")
    pdf.cell(95, 10, text=f"Efficiency score: {metrics.get('efficiency', 0)}%", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(10)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 10, text="2. Top cost anomalies", new_x="LMARGIN", new_y="NEXT", fill=True)
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(80, 8, "Task", border=1)
    pdf.cell(40, 8, "Severity", border=1)
    pdf.cell(40, 8, "Excess cost ($)", border=1)
    pdf.ln()
    pdf.set_font("Helvetica", size=10)
    for row in _rows(anomalies)[:5]:
        pdf.cell(80, 8, text=str(row.get("task_id") or row.get("fingerprint") or "-")[:40], border=1)
        pdf.cell(40, 8, text=str(row.get("severity") or "-"), border=1)
        pdf.cell(40, 8, text=f"{float(row.get('waste_usd') or 0):.2f}", border=1)
        pdf.ln()

    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 10)
    pdf.multi_cell(0, 5, text="Review pending AI suggestions in the Suggestions tab. "
                              "Odos never changes production SQL without approval.")
    return bytes(pdf.output())
