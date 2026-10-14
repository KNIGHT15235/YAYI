"""Build a non-sensitive, explicitly synthetic PDF for the real ingestion test."""
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
destination = ROOT / "output" / "pdf" / "yayi-live-synthetic-study.pdf"
destination.parent.mkdir(parents=True, exist_ok=True)
styles = getSampleStyleSheet()
story = []
def paragraph(text, style="BodyText"):
    story.append(Paragraph(text, styles[style]))
    story.append(Spacer(1, 3 * mm))

paragraph("YAYI-LIVE-20261014: Synthetic Retrieval Study", "Title")
paragraph("ENGINEERING TEST FIXTURE - NOT A REAL RESEARCH PUBLICATION", "Heading2")
paragraph("This document contains invented data for testing ingestion, table extraction, citation grounding and research workflow behavior. It has no real authors, journal, DOI, clinical participants or confidential information. Its numbers must not be described as real-world experimental evidence.")
paragraph("1. Scope and protocol", "Heading2")
paragraph("The fictional experiment compares lexical, vector and hybrid retrieval on 100 synthetic queries against 500 synthetic documents. All methods use the same corpus, query list and top-20 cutoff. Relevant-document labels are invented and are fixed solely for this engineering test. Evaluation covers one synthetic domain only. There are no independent replications, significance tests, other disciplines or production-scale experiments.")
paragraph("2. Table 1: Invented top-20 retrieval results", "Heading2")
table = Table([
    ["Method", "Recall@20 (%)", "Latency p50 (ms)", "Queries"],
    ["Lexical-only", "64.0", "22", "100"],
    ["Vector-only", "78.0", "47", "100"],
    ["Hybrid RRF", "86.0", "63", "100"],
], colWidths=[48*mm, 39*mm, 44*mm, 26*mm], repeatRows=1)
table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#e3ebf5")),
    ("GRID",(0,0),(-1,-1),0.6,colors.grey), ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
    ("FONTSIZE",(0,0),(-1,-1),10), ("BOTTOMPADDING",(0,0),(-1,-1),7),
    ("TOPPADDING",(0,0),(-1,-1),7)]))
story.extend([table, Spacer(1, 6*mm)])
paragraph("Table 1 unit note: recall is a percentage; latency is milliseconds. Hybrid minus vector recall is 8.0 percentage points, not 8 percent relative improvement. Hybrid latency is 16 ms higher than vector latency. These values describe only this invented test table.")
paragraph("3. Equation (1) and interpretation", "Heading2")
paragraph("Recall@20 = relevant documents retrieved in top 20 / all relevant documents. (1)")
paragraph("The fictional results illustrate a recall/latency trade-off. Table 1 does not support the claim that hybrid retrieval always outperforms vector retrieval in every scientific discipline. It does not report Recall@20 of 91%, citation error rate, million-document scalability, causal effects or statistical significance. A responsible summary must state these limits and must not fabricate absent references.")
paragraph("4. Intended acceptance question", "Heading2")
paragraph("Using only this synthetic document, compare the three methods in Table 1, explain the recall/latency trade-off, show exact supporting values, and list what cannot be concluded. If asked for independent real-world validation, state that this document cannot provide it.")
SimpleDocTemplate(str(destination), pagesize=(210*mm, 297*mm), rightMargin=22*mm, leftMargin=22*mm,
                  topMargin=18*mm, bottomMargin=18*mm, title="YAYI synthetic acceptance fixture").build(story)
print(destination)
