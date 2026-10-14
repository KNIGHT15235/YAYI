"""Idempotent additive migration for the two science provenance tables."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "app"))


def main():
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend" / ".env", override=False)
    from core.database import engine
    import models  # register ForeignKey targets
    from models.knowledge import DocumentAsset, DocumentChunkProvenance
    for table in (DocumentAsset.__table__, DocumentChunkProvenance.__table__):
        table.create(engine, checkfirst=True)
    print("Science asset tables ready (additive migration; existing documents unchanged).")


if __name__ == "__main__":
    main()
