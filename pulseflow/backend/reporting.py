from datetime import datetime

import pandas as pd
from fpdf import FPDF


def calculate_efficiency(annual_burn: float, annual_waste: float) -> float:
    """Calculates efficiency score (0-100)."""
    if annual_burn <= 0:
        return 100.0
    return max(0.0, 100.0 - (annual_waste / annual_burn * 100.0))


def generate_pdf_binary(metrics: dict, anomalies: pd.DataFrame, project_name: str) -> bytes:
    """
    Generates the PDF report and returns binary data.
    """
    pdf = FPDF()
    pdf.add_page()
    # 'Arial' is not standard in base FPDF2, 'Helvetica' is safer
    pdf.set_font("Helvetica", size=12)

    # 1. Title & Header
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(
        0, 10, text=f"Weekly Cost Report: {project_name}", new_x="LMARGIN", new_y="NEXT", align='C')
    pdf.set_font("Helvetica", "I", 10)
    pdf.cell(0, 10, text=f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
             new_x="LMARGIN", new_y="NEXT", align='C')
    pdf.line(10, 30, 200, 30)

    # 2. Executive Summary
    pdf.ln(15)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(0, 10, text="1. Executive Financial Summary",
             new_x="LMARGIN", new_y="NEXT", fill=True)

    pdf.set_font("Helvetica", size=11)
    pdf.ln(2)
    pdf.cell(
        95, 10, text=f"Projected Annual Burn: EUR {metrics.get('burn', 0):,.2f}")
    pdf.cell(
        95, 10, text=f"Avoidable Waste: EUR {metrics.get('waste', 0):,.2f}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(95, 10, text=f"Budget Cap: EUR {metrics.get('budget', 0):,.2f}")
    pdf.cell(
        95, 10, text=f"Current Efficiency Score: {metrics.get('efficiency', 0)}%", new_x="LMARGIN", new_y="NEXT")

    # 3. Top Anomalies Table
    pdf.ln(10)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 10, text="2. Top 5 Cost Anomalies (Action Required)",
             new_x="LMARGIN", new_y="NEXT", fill=True)

    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 10)
    # Table Header
    pdf.cell(80, 8, "Task ID", border=1)
    pdf.cell(40, 8, "Severity", border=1)
    pdf.cell(40, 8, "Waste (EUR)", border=1)
    pdf.ln()

    # Table Rows
    pdf.set_font("Helvetica", size=10)
    if not anomalies.empty:
        for _, row in anomalies.head(5).iterrows():
            pdf.cell(80, 8, text=str(row['task_id']), border=1)
            pdf.cell(40, 8, text=str(row['severity']), border=1)
            pdf.cell(40, 8, text=f"{row['waste_usd']:.2f}", border=1)
            pdf.ln()

    # 4. Footer
    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 10)
    pdf.multi_cell(
        0, 5, text="Recommendation: Review the high-severity anomalies in the 'Zombie Hunter' tab.")

    # FIX: FPDF2 returns a bytearray directly. No 'dest' arg needed.
    return bytes(pdf.output())
