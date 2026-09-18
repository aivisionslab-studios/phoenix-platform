#!/usr/bin/env python3
"""Inventory or extract concatenated ZIP payloads from a binary.

This static forensics helper never executes the input or extracted files.
Candidates are validated from their EOCD record, paths are checked against
traversal, and SHA-256 hashes are recorded for reproducibility.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

EOCD = b"PK\x05\x06"
EOCD_STRUCT = struct.Struct("<4s4H2LH")


@dataclass(frozen=True)
class EmbeddedZip:
    index: int
    start: int
    end: int
    entries: tuple[str, ...]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_member(name: str) -> bool:
    p = PurePosixPath(name.replace("\\", "/"))
    return not p.is_absolute() and ".." not in p.parts and not (
        p.parts and ":" in p.parts[0]
    )


def discover(data: bytes) -> list[EmbeddedZip]:
    """Find classic non-ZIP64 archives embedded or concatenated in *data*."""
    found: list[EmbeddedZip] = []
    cursor = 0
    while True:
        eocd = data.find(EOCD, cursor)
        if eocd < 0:
            break
        cursor = eocd + 1
        if eocd + EOCD_STRUCT.size > len(data):
            continue
        try:
            _, disk, cd_disk, disk_entries, entries, cd_size, cd_offset, comment = EOCD_STRUCT.unpack_from(data, eocd)
        except struct.error:
            continue
        if disk or cd_disk or disk_entries != entries or entries > 100_000:
            continue
        start = eocd - cd_size - cd_offset
        end = eocd + EOCD_STRUCT.size + comment
        if start < 0 or end > len(data):
            continue
        try:
            with ZipFile(BytesIO(data[start:end])) as zf:
                names = tuple(zf.namelist())
                if len(names) != entries or any(not safe_member(n) for n in names):
                    continue
                if zf.testzip() is not None:
                    continue
        except (BadZipFile, OSError, RuntimeError):
            continue
        found.append(EmbeddedZip(len(found), start, end, names))
    return found


def extract_one(data: bytes, item: EmbeddedZip, root: Path) -> list[dict]:
    target = root / f"archive_{item.index:02d}_{item.start}"
    target.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    with ZipFile(BytesIO(data[item.start:item.end])) as zf:
        for info in zf.infolist():
            if not safe_member(info.filename):
                raise ValueError(f"unsafe ZIP member: {info.filename!r}")
            out = target / PurePosixPath(info.filename)
            if info.is_dir():
                out.mkdir(parents=True, exist_ok=True)
                continue
            payload = zf.read(info)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(payload)
            rows.append({"name": info.filename, "size": len(payload), "compressed_size": info.compress_size, "sha256": sha256_bytes(payload), "path": str(out)})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("binary", type=Path)
    ap.add_argument("--out", type=Path, default=Path("OCCT_EXTRACTED"))
    ap.add_argument("--extract", action="store_true")
    ap.add_argument("--archive", type=int, action="append", help="extract only this archive index; repeatable")
    ap.add_argument("--report", type=Path, help="JSON report path (default: OUT/inventory.json)")
    ns = ap.parse_args()

    data = ns.binary.read_bytes()
    archives = discover(data)
    selected = set(ns.archive or range(len(archives)))
    result = {"schema": "phoenix.forge.embedded-zips/v1", "input": str(ns.binary.resolve()), "input_size": len(data), "input_sha256": sha256_bytes(data), "archive_count": len(archives), "archives": []}
    if ns.extract:
        ns.out.mkdir(parents=True, exist_ok=True)
    for item in archives:
        row = {"index": item.index, "start_offset": item.start, "end_offset": item.end, "archive_size": item.end-item.start, "entry_count": len(item.entries), "entries": list(item.entries)}
        if ns.extract and item.index in selected:
            row["extracted"] = extract_one(data, item, ns.out)
        result["archives"].append(row)

    report = ns.report or ns.out / "inventory.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    print(json.dumps({"archive_count": len(archives), "report": str(report), "extracted": bool(ns.extract)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
