"""Use only a unique audit checkpoint; delete it in finally. No external APIs."""
import asyncio
from datetime import datetime
from pathlib import Path
import sys
import uuid

from dotenv import load_dotenv

project = Path(__file__).resolve().parents[1]
load_dotenv(project / "backend" / ".env")
sys.path.insert(0, str(project / "backend" / "app"))

from service.checkpoint_service import CheckpointService

service = CheckpointService()
session = "audit-roundtrip-" + uuid.uuid4().hex
try:
    state = {"query": "audit synthetic checkpoint", "phase": "reviewing", "iteration": 1,
             "final_report": "audit report", "_next_step": "reviewing",
             "_message_queue": asyncio.Queue(), "created": datetime(2026, 1, 1)}
    checkpoint = service.save_checkpoint(session, state, ui_state={"research_steps": []}, final_report="audit report")
    assert checkpoint, "checkpoint save failed"
    loaded = service.load_full_checkpoint(session)
    assert loaded["state_json"]["final_report"] == "audit report"
    assert "_message_queue" not in loaded["state_json"]
    assert loaded["state_json"]["_next_step"] == "reviewing"
    assert service.update_status(session, "paused")
    assert service.get_checkpoint_info(session)["status"] == "paused"
    print("PASS: PostgreSQL JSONB checkpoint save/load/status roundtrip")
finally:
    assert service.delete_checkpoint(session), "audit checkpoint cleanup failed"
    assert service.load_checkpoint(session) is None
    print("PASS: unique audit checkpoint removed")
