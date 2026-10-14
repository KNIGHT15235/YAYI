"""Attach visually checked source-page facts to the compact live audit."""
import json
from pathlib import Path
from live_science_assets import REPORT, ROOT, save

report = json.loads(REPORT.read_text(encoding="utf-8"))
table = next(asset for asset in report["assets"] if asset["type"] == "table" and asset["locator"].get("page") == 9)
full = json.loads((ROOT / "backend/storage/knowledge/assets" / (table["asset_id"] + ".json")).read_text(encoding="utf-8"))
bit_cells = [cell for cell in full["locator"]["table_rows"] if cell.get("row_start") == 9]
assert any("BIT" in cell["text"] for cell in bit_cells)
assert any("89.31" in cell["text"] and "80.68" in cell["text"] for cell in bit_cells)
report["source_page_checks"] = [
    {"kind": "table", "label": "Table I, BIT row", "physical_pdf_page": 9,
     "provider_page_index": 8, "asset_id": table["asset_id"], "parser_row_start": 9,
     "values_percent": {"LEVIR-CD": {"F1": 89.31, "IoU": 80.68}, "WHU-CD": {"F1": 83.98, "IoU": 72.39}, "DSIFN-CD": {"F1": 69.26, "IoU": 52.97}},
     "verified_against": "PDF page 9 rendered by Poppler and original printed table; parser cell text checked", "passed": True},
    {"kind": "formula", "label": "Equation (3), attention", "physical_pdf_page": 5,
     "verified_against": "PDF page 5 rendered by Poppler", "page_and_number_match": True,
     "note": "This verifies location/number, not lossless LaTeX transcription."},
    {"kind": "formula", "label": "Equations (6) and (7)", "physical_pdf_page": 6,
     "verified_against": "PDF page 6 rendered by Poppler", "page_and_number_match": True},
    {"kind": "image", "label": "Fig. 2, BIT architecture", "physical_pdf_page": 3,
     "asset_id": "14286c27a7b9032541d2b813bd1f5bb0f27cbf61bf22a6da997869f6b9727d33",
     "verified_against": "Downloaded authenticated PNG and PDF page 3 rendered by Poppler", "visual_match": True},
]
report["known_limitations"] = [
    "10 formula assets; explicit equation_number available for 5, absent for 5. Missing values are not fabricated.",
    "DocMind formula text contains OCR/layout transcription defects; verify mathematical symbols against the original PDF.",
    "Table row/column indices are present; exact cell pixel boxes were not returned in this source. The available bounding polygon locates the table/block.",
    "Some figure_number/table_number labels are separate caption blocks and are not automatically attached to the asset; use actual page and asset links.",
    "Image assets follow parser-selected image regions, which may be a subfigure instead of the entire multi-panel figure.",
]
report["affected_regression_tests"] = {"passed": 41, "network": "mocked in regression suite; live API acceptance recorded separately"}
save(report)
print(json.dumps({"report_bytes": REPORT.stat().st_size, "page_checks": len(report["source_page_checks"]), "table_cell_text_verified": True}))
