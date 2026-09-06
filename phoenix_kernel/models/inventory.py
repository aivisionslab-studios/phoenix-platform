"""
ModelInventory — Persiste o inventário em disco.
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone

try:
    from phoenix_kernel.paths import PhoenixPaths
    from phoenix_kernel.models.model_scanner import ModelScanner
except ImportError:
    PhoenixPaths = None
    ModelScanner = None


class ModelInventory:

    @staticmethod
    def get_db_path() -> Path:
        if PhoenixPaths:
            return PhoenixPaths.get_inventory_db()
        return Path("data/models_inventory.json")

    @staticmethod
    def refresh() -> int:
        records = ModelScanner.scan_all() if ModelScanner else []
        db = ModelInventory.get_db_path()
        db.parent.mkdir(parents=True, exist_ok=True)
        with open(db, "w", encoding="utf-8") as f:
            json.dump({
                "total": len(records),
                "models": records,
                "scanned_at": datetime.now(timezone.utc).isoformat(),
            }, f, indent=2, ensure_ascii=False)
        return len(records)

    @staticmethod
    def load() -> dict:
        db = ModelInventory.get_db_path()
        if not db.exists():
            return {"total": 0, "models": []}
        with open(db, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def find(name: str = None, category: str = None, fmt: str = None) -> list[dict]:
        db = ModelInventory.load()
        results = db.get("models", [])
        if name:
            results = [m for m in results if name.lower() in m["name"].lower()]
        if category:
            results = [m for m in results if m["category"] == category]
        if fmt:
            results = [m for m in results if m["format"] == fmt]
        return results
