"""One new synthetic image job with documented DocMind VLM OCR parameters."""
import argparse
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "app"))
from dotenv import load_dotenv
load_dotenv(ROOT / "backend" / ".env")
from PIL import Image, ImageDraw, ImageFont

parser = argparse.ArgumentParser()
parser.add_argument("--submit", action="store_true")
args = parser.parse_args()
path = ROOT / "audit" / "ocr-synthetic.png"
picture = Image.new("RGB", (1000, 220), "white")
font_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
font = ImageFont.truetype(str(font_path), 42) if font_path.exists() else ImageFont.load_default()
ImageDraw.Draw(picture).text((40, 70), "YAYI OCR AUDIT 7342", fill="black", font=font)
picture.save(path, "PNG")
if not args.submit:
    print(json.dumps({"fixture_path": str(path), "font_exists": font_path.exists(), "size": picture.size}))
    raise SystemExit(0)

from service.docmind_service import DocMindService
service = DocMindService()
original = service.client.submit_doc_parser_job_advance
def submit_with_ocr(request, runtime):
    request.llm_enhancement = True
    request.enhancement_mode = "VLM"
    request.need_header_footer = True
    return original(request, runtime)
service.client.submit_doc_parser_job_advance = submit_with_ocr
job = service.submit_job(str(path), "scan-vlm.png")
result = {"new_submissions": 1, "source": "synthetic image only", "job_id": job,
          "parameters": {"LlmEnhancement": True, "EnhancementMode": "VLM", "NeedHeaderFooter": True}}
if job:
    result["completed"] = service.wait_for_completion(job, poll_interval=5, max_wait=150)
    if result["completed"]:
        text = service.collect_all_results(job)
        result.update({"parsed_length": len(text), "contains_synthetic_marker": "7342" in text,
                       "contains_synthetic_title": "YAYI" in text, "parse_error": service.last_error})
else:
    result["error"] = service.last_error
(ROOT / "audit" / "ocr_vlm_probe_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
