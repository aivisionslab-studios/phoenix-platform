from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Any

from phoenix_forge.modules import provider_actions, provider_bridge

SCHEMA = "phoenix.forge.memory-spd/v4"

_MEMORY_TYPES = {
    0x0B: "DDR3",
    0x0C: "DDR4",
    0x12: "DDR5",
    0x13: "LPDDR5",
}

_DENSITY_MBIT = {
    0: 256,
    1: 512,
    2: 1024,
    3: 2048,
    4: 4096,
    5: 8192,
    6: 16384,
    7: 32768,
}
_DEVICE_WIDTH_BITS = {0: 4, 1: 8, 2: 16, 3: 32}
_PRIMARY_BUS_WIDTH_BITS = {0: 8, 1: 16, 2: 32, 3: 64}
_BUS_EXTENSION_BITS = {0: 0, 1: 8, 2: 16, 3: 32}


def _crc16_ccitt(data: bytes, init: int = 0) -> int:
    crc = init & 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if (crc & 0x8000) else ((crc << 1) & 0xFFFF)
    return crc


def _geometry(*, density_code: int, organization: int, bus_width: int) -> dict[str, Any]:
    density_mbit = _DENSITY_MBIT.get(density_code & 0x0F)
    device_width = _DEVICE_WIDTH_BITS.get(organization & 0x07)
    ranks = ((organization >> 3) & 0x07) + 1
    primary_bus = _PRIMARY_BUS_WIDTH_BITS.get(bus_width & 0x07)
    extension = _BUS_EXTENSION_BITS.get((bus_width >> 3) & 0x03)
    out: dict[str, Any] = {
        "sdram_density_mbit": density_mbit,
        "device_width_bits": device_width,
        "ranks": ranks,
        "primary_bus_width_bits": primary_bus,
        "bus_extension_bits": extension,
        "ecc_extension_present": bool(extension),
    }
    if density_mbit and device_width and primary_bus:
        # JEDEC geometry-derived module capacity. This is module layout capacity,
        # not OS-visible/usable memory and not a substitute for controller telemetry.
        capacity_mib = (density_mbit // 8) * (primary_bus // device_width) * ranks
        out["module_capacity_mib_estimate"] = capacity_mib
        out["module_capacity_gib_estimate"] = round(capacity_mib / 1024, 3)
        out["capacity_note"] = "Derived from raw SPD geometry only; not OS-visible usable memory."
    return out


def _decode_ddr3(raw: bytes) -> dict[str, Any]:
    out: dict[str, Any] = {"memory_type": "DDR3"}
    if len(raw) < 64:
        out["parse_status"] = "TRUNCATED"
        return out
    out.update({
        "spd_revision": f"{raw[1] >> 4}.{raw[1] & 0xF}",
        "module_type_code": raw[3] & 0x0F,
        "density_banks_code": raw[4],
        "module_organization_code": raw[7],
        "bus_width_code": raw[8],
    })
    out["geometry"] = _geometry(density_code=raw[4], organization=raw[7], bus_width=raw[8])
    dividend, divisor = int(raw[10]), int(raw[11])
    tck_units = int(raw[12])
    if dividend and divisor and tck_units:
        mtb_ns = dividend / divisor
        tck_ns = tck_units * mtb_ns
        out["medium_timebase_ns"] = round(mtb_ns, 6)
        out["tck_min_ns"] = round(tck_ns, 6)
        out["max_transfer_rate_mt_s_estimate"] = round(2000 / tck_ns) if tck_ns else None
        out["frequency_note"] = "Derived from DDR3 SPD MTB/tCKmin only; not current configured memory clock."
    out["parse_status"] = "DEEP_BASE_DECODED"
    return out


def _u16le(raw: bytes, offset: int) -> int:
    return int.from_bytes(raw[offset:offset + 2], "little") if len(raw) >= offset + 2 else 0


def _s8(value: int) -> int:
    return value - 256 if value > 127 else value


def _ascii_z(data: bytes) -> str:
    return data.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()


def _crc_record(data: bytes, stored: int) -> dict[str, Any]:
    computed = _crc16_ccitt(data)
    return {"stored": stored, "computed": computed, "valid": stored == computed}


def _decode_xmp2_voltage(code: int) -> float:
    # XMP 2.0 DDR4 voltage byte: bit 7 contributes one volt; low seven bits are hundredths.
    return round(((100 if code & 0x80 else 0) + (code & 0x7F)) / 100.0, 3)


def _decode_ddr5_voltage(code: int) -> float:
    # DDR5 XMP/EXPO encoding: top 3 bits are whole volts, low 5 bits are 0.05 V steps.
    hundredths = ((code >> 5) * 100) + ((code & 0x1F) * 5)
    return round(hundredths / 100.0, 3)


def _decode_ddr5_cas(bitmap: bytes) -> list[int]:
    bits = int.from_bytes(bitmap[:5].ljust(5, b"\x00"), "little")
    return [20 + 2 * bit for bit in range(40) if bits & (1 << bit)]


def _decode_xmp2_profile(block: bytes, index: int, enabled: bool) -> dict[str, Any]:
    out: dict[str, Any] = {"profile": index, "enabled": bool(enabled), "raw_size": len(block)}
    if len(block) < 47:
        out["decode_status"] = "TRUNCATED"
        return out
    tck_ps = int(block[3]) * 125 + _s8(block[38])
    cas_bitmap = int.from_bytes(block[4:7], "little")
    out.update({
        "decode_status": "DECODED",
        "voltage_v": _decode_xmp2_voltage(block[0]),
        "tck_min_ps": tck_ps if tck_ps > 0 else None,
        "data_rate_mt_s_estimate": round(2_000_000 / tck_ps) if tck_ps > 0 else None,
        "cas_latency_bitmap_raw": f"0x{cas_bitmap:06X}",
        "cas_latencies_supported": [7 + bit for bit in range(24) if cas_bitmap & (1 << bit)],
        "timings_cycles": {
            "cl": int(block[8]),
            "trcd": int(block[9]),
            "trp": int(block[10]),
            "tras": int(block[12]) | ((int(block[11]) & 0x0F) << 8),
            "trc": int(block[13]) | ((int(block[11]) & 0xF0) << 4),
            "trfc1": _u16le(block, 14),
            "trfc2": _u16le(block, 16),
            "trfc4": _u16le(block, 18),
            "tfaw": int(block[21]) | ((int(block[20]) & 0x0F) << 8),
            "trrds": int(block[22]),
            "trrdl": int(block[23]),
        },
        "fine_timebase_ps": {
            "trrdl": _s8(block[32]), "trrds": _s8(block[33]), "trc": _s8(block[34]),
            "trp": _s8(block[35]), "trcd": _s8(block[36]), "cl": _s8(block[37]), "tck": _s8(block[38]),
        },
        "raw_hex": block.hex().upper(),
    })
    return out


def _decode_ddr4_xmp(raw: bytes) -> dict[str, Any]:
    if len(raw) < 393:
        return {"detected": False, "decode_status": "NOT_AVAILABLE", "profiles": []}
    off = 384
    header = raw[off:off + 9]
    if header[:2] != b"\x0cJ":
        return {"detected": False, "decode_status": "NOT_DETECTED", "profiles": []}
    version = int(header[3])
    enabled = int(header[2])
    profiles = []
    for i in range(2):
        poff = off + 9 + i * 47
        profiles.append(_decode_xmp2_profile(raw[poff:poff + 47], i + 1, bool(enabled & (1 << i))))
    return {
        "detected": True,
        "decode_status": "DECODED" if version == 0x20 else "DECODED_UNKNOWN_VERSION",
        "version_raw": f"0x{version:02X}",
        "profile_enable_bits": enabled,
        "profiles": profiles,
        "source_offset": off,
        "evidence_note": "Advertised XMP profile data from raw SPD; not proof that BIOS selected or stabilized the profile.",
    }


def _decode_xmp3_profile(block: bytes, *, index: int, enabled: bool, name: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"profile": index, "enabled": bool(enabled), "name": name, "raw_size": len(block)}
    if len(block) < 64:
        out["decode_status"] = "TRUNCATED"
        return out
    tck_ps = _u16le(block, 5)
    out.update({
        "decode_status": "DECODED",
        "voltage_codes_raw": {"vpp": int(block[0]), "vdd": int(block[1]), "vddq": int(block[2]), "vmemctrl": int(block[4])},
        "voltages_v": {"vpp": _decode_ddr5_voltage(block[0]), "vdd": _decode_ddr5_voltage(block[1]), "vddq": _decode_ddr5_voltage(block[2]), "vmemctrl": _decode_ddr5_voltage(block[4])},
        "tck_min_ps": tck_ps or None,
        "data_rate_mt_s_estimate": round(2_000_000 / tck_ps) if tck_ps else None,
        "cas_latency_bitmap_raw": block[7:12].hex().upper(),
        "cas_latencies_supported": _decode_ddr5_cas(block[7:12]),
        "timings_ps": {
            "taa": _u16le(block, 13), "trcd": _u16le(block, 15), "trp": _u16le(block, 17),
            "tras": _u16le(block, 19), "trc": _u16le(block, 21), "twr": _u16le(block, 23),
            "trrd_l": _u16le(block, 31), "tccd_l_wr": _u16le(block, 34), "tccd_l_wr2": _u16le(block, 37),
            "tccd_l_wtr": _u16le(block, 40), "tccd_s_wtr": _u16le(block, 43), "tccd_l": _u16le(block, 46),
            "trtp": _u16le(block, 49), "tfaw": _u16le(block, 52),
        },
        "refresh_ns": {"trfc1": _u16le(block, 25), "trfc2": _u16le(block, 27), "trfcsb": _u16le(block, 29)},
        "timing_lower_limits_cycles": {"trrd_l": int(block[33]), "tccd_l_wr": int(block[36]), "tccd_l_wr2": int(block[39]), "tccd_l_wtr": int(block[42]), "tccd_s_wtr": int(block[45]), "tccd_l": int(block[48]), "trtp": int(block[51]), "tfaw": int(block[54])},
        "intel_dynamic_memory_boost": bool(block[59] & 0x01),
        "real_time_memory_frequency_oc": bool(block[59] & 0x02),
        "command_rate_code": int(block[60] & 0x0F),
        "raw_hex": block.hex().upper(),
        "voltage_note": "Voltage values decoded from the raw DDR5 XMP/EXPO byte encoding; active PMIC voltage is not inferred.",
    })
    return out


def _decode_expo_profile(block: bytes, *, index: int, enabled: bool) -> dict[str, Any]:
    out: dict[str, Any] = {"profile": index, "enabled": bool(enabled), "name": f"EXPO {index}", "raw_size": len(block)}
    if len(block) < 40:
        out["decode_status"] = "TRUNCATED"
        return out
    tck_ps = _u16le(block, 4)
    names = ["taa", "trcd", "trp", "tras", "trc", "twr", "trfc1", "trfc2", "trfcsb", "trrd_l", "tccd_l", "tccd_l_wr", "tccd_l_wr2", "tfaw", "tccd_l_wtr", "tccd_s_wtr", "trtp"]
    vals = [_u16le(block, 6 + 2 * i) for i in range(len(names))]
    timings = dict(zip(names, vals))
    refresh = {k: timings.pop(k) for k in ("trfc1", "trfc2", "trfcsb")}
    out.update({
        "decode_status": "DECODED",
        "voltage_codes_raw": {"vdd": int(block[0]), "vddq": int(block[1]), "vpp": int(block[2])},
        "voltages_v": {"vdd": _decode_ddr5_voltage(block[0]), "vddq": _decode_ddr5_voltage(block[1]), "vpp": _decode_ddr5_voltage(block[2])},
        "tck_min_ps": tck_ps or None,
        "data_rate_mt_s_estimate": round(2_000_000 / tck_ps) if tck_ps else None,
        "timings_ps": timings,
        "refresh_ns": refresh,
        "raw_hex": block.hex().upper(),
        "voltage_note": "Voltage values decoded from the raw DDR5 XMP/EXPO byte encoding; active PMIC voltage is not inferred.",
    })
    return out

def _decode_ddr5_xmp3(raw: bytes) -> dict[str, Any]:
    off = 0x280
    if len(raw) < off + 64 or raw[off:off + 2] != b"\x0cJ":
        return {"detected": False, "decode_status": "NOT_DETECTED", "profiles": []}
    header = raw[off:off + 64]
    version = int(header[2])
    enabled = int(header[3])
    names = [_ascii_z(header[14 + i * 16:30 + i * 16]) for i in range(3)]
    crc = _crc_record(header[:62], _u16le(header, 62))
    profiles = []
    for i in range(3):
        poff = off + 64 + i * 64
        block = raw[poff:poff + 64]
        if len(block) < 64 or block[:4] == b"EXPO":
            continue
        row = _decode_xmp3_profile(block, index=i + 1, enabled=bool(enabled & (1 << i)), name=names[i] or None)
        row["profile_crc"] = _crc_record(block[:62], _u16le(block, 62))
        profiles.append(row)
    return {
        "detected": True,
        "decode_status": "DECODED" if version == 0x30 else "DECODED_UNKNOWN_VERSION",
        "version_raw": f"0x{version:02X}",
        "profile_enable_bits": enabled,
        "header_crc": crc,
        "profiles": profiles,
        "source_offset": off,
        "evidence_note": "Raw XMP 3.0 SPD extension evidence only; active BIOS profile and stability are not inferred.",
    }


def _decode_ddr5_expo(raw: bytes) -> dict[str, Any]:
    # EXPO can coexist with XMP in the DDR5 end-user region. Search only that bounded region.
    area_start, area_end = 0x280, min(len(raw), 0x400)
    pos = raw.find(b"EXPO", area_start, area_end)
    if pos < 0:
        return {"detected": False, "decode_status": "NOT_DETECTED", "profiles": []}
    block = raw[pos:pos + 128]
    if len(block) < 128:
        return {"detected": True, "decode_status": "TRUNCATED", "source_offset": pos, "profiles": []}
    revision = int(block[4])
    enabled1, enabled2 = int(block[5]), int(block[6])
    profiles = []
    for i in range(2):
        poff = 10 + i * 40
        p = block[poff:poff + 40]
        enabled = bool((enabled1 & 0x01) if i == 0 else (enabled2 & 0x01 or enabled1 & 0x10))
        row = _decode_expo_profile(p, index=i + 1, enabled=enabled)
        profiles.append(row)
    return {
        "detected": True,
        "decode_status": "DECODED" if revision == 0x10 else "DECODED_UNKNOWN_VERSION",
        "revision_raw": f"0x{revision:02X}",
        "profile_enable_bits": [enabled1, enabled2],
        "bundle_crc": _crc_record(block[:126], _u16le(block, 126)),
        "profiles": profiles,
        "source_offset": pos,
        "evidence_note": "Raw EXPO SPD extension evidence only; active BIOS profile and stability are not inferred.",
    }


def _decode_ddr4(raw: bytes) -> dict[str, Any]:
    out: dict[str, Any] = {"memory_type": "DDR4"}
    if len(raw) < 128:
        out["parse_status"] = "TRUNCATED"
        return out
    b0 = raw[0]
    total_code = (b0 >> 4) & 0x7
    used_code = b0 & 0xF
    total_map = {1: 256, 2: 512}
    used_map = {1: 128, 2: 256, 3: 384, 4: 512}
    out.update({
        "spd_bytes_total_declared": total_map.get(total_code),
        "spd_bytes_used_declared": used_map.get(used_code),
        "spd_revision": f"{raw[1] >> 4}.{raw[1] & 0xF}",
        "module_type_code": raw[3] & 0x0F,
        "density_banks_code": raw[4],
        "module_organization_code": raw[12],
        "bus_width_code": raw[13],
    })
    out["geometry"] = _geometry(density_code=raw[4], organization=raw[12], bus_width=raw[13])
    stored = raw[126] | (raw[127] << 8)
    computed = _crc16_ccitt(raw[:126])
    out["base_crc"] = {"stored": stored, "computed": computed, "valid": stored == computed, "coverage_bytes": 126}
    if len(raw) >= 256:
        stored2 = raw[254] | (raw[255] << 8)
        computed2 = _crc16_ccitt(raw[128:254])
        out["module_crc"] = {"stored": stored2, "computed": computed2, "valid": stored2 == computed2, "coverage_bytes": 126, "range": "128-253"}
    if raw[18]:
        tck_ps = raw[18] * 125
        out["tckavg_min_ps"] = tck_ps
        out["max_transfer_rate_mt_s_estimate"] = round(2_000_000 / tck_ps) if tck_ps else None
        out["frequency_note"] = "Derived only from JEDEC DDR4 tCKAVGmin; not current configured memory clock."
    if len(raw) >= 24:
        bitmap = int.from_bytes(raw[20:24], "little")
        out["cas_latency_bitmap_raw"] = f"0x{bitmap:08X}"
        out["cas_latencies_supported"] = [7 + bit for bit in range(32) if bitmap & (1 << bit)]
        out["timing_note"] = "Supported SPD timings only; active controller timings require runtime telemetry."
    out["xmp"] = _decode_ddr4_xmp(raw)
    out["parse_status"] = "DEEP_BASE_DECODED"
    return out


def _decode_ddr5(raw: bytes) -> dict[str, Any]:
    out: dict[str, Any] = {"memory_type": "DDR5"}
    if len(raw) < 16:
        out["parse_status"] = "TRUNCATED"
        return out
    out.update({
        "spd_revision": f"{raw[1] >> 4}.{raw[1] & 0xF}",
        "module_type_code": raw[3] & 0x0F,
        "base_field_4": int(raw[4]),
        "base_field_5": int(raw[5]),
        "base_identity_only": True,
        "timing_decode_status": "BASE_IDENTITY_ONLY",
    })
    out["xmp"] = _decode_ddr5_xmp3(raw)
    out["expo"] = _decode_ddr5_expo(raw)
    out["xmp_expo_decode_status"] = "DECODED" if out["xmp"].get("detected") or out["expo"].get("detected") else "NOT_DETECTED"
    out["parse_status"] = "BASE_IDENTITY_PLUS_PROFILE_EXTENSIONS"
    return out

def parse_spd(raw: bytes, *, source: str = "raw") -> dict[str, Any]:
    result: dict[str, Any] = {
        "source": source,
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest().upper() if raw else None,
        "raw_available": bool(raw),
        "parse_status": "EMPTY" if not raw else "UNSUPPORTED_OR_MINIMAL",
    }
    if len(raw) < 3:
        return result
    code = raw[2]
    mem_type = _MEMORY_TYPES.get(code, f"UNKNOWN_0x{code:02X}")
    result["memory_type_code"] = code
    result["memory_type"] = mem_type
    if code == 0x0B:
        result.update(_decode_ddr3(raw))
    elif code == 0x0C:
        result.update(_decode_ddr4(raw))
    elif code == 0x12:
        result.update(_decode_ddr5(raw))
    else:
        result["parse_status"] = "RAW_CAPTURED_PARSER_NOT_IMPLEMENTED"
    return result


def _dump_dir() -> Path | None:
    value = os.environ.get("PHOENIX_FORGE_SPD_DIR", "").strip()
    if not value:
        return None
    p = Path(value)
    return p if p.is_dir() else None


def _collect_dump_files(directory: Path) -> list[dict[str, Any]]:
    modules: list[dict[str, Any]] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".bin", ".spd", ".rom"}:
            continue
        try:
            raw = path.read_bytes()
        except OSError as exc:
            modules.append({"source": str(path), "status": "READ_ERROR", "error": str(exc)})
            continue
        row = parse_spd(raw, source=str(path))
        row["status"] = "CAPTURED"
        modules.append(row)
    return modules


def _provider_name() -> str:
    return os.environ.get("PHOENIX_FORGE_SMBUS_PROVIDER", "phoenix-smbus-windows").strip() or "phoenix-smbus-windows"


def _collect_live_provider() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    name = _provider_name()
    probe = provider_bridge.probe(name, timeout_s=1.5)
    status = {
        "provider": name,
        "probe_status": probe.get("status"),
        "capabilities": probe.get("capabilities") or [],
        "privilege": probe.get("privilege"),
        "provider_version": probe.get("provider_version"),
        "available": False,
    }
    modules: list[dict[str, Any]] = []
    caps = set(map(str, probe.get("capabilities") or []))
    if probe.get("status") != "READY" or "spd.enumerate" not in caps:
        return status, modules
    enum = provider_actions.call(name, "spd.enumerate", {}, timeout_s=3.0)
    status["enumerate_status"] = enum.get("status")
    if enum.get("status") not in {"OK", "PARTIAL"}:
        return status, modules
    rows = ((enum.get("data") or {}).get("modules") or [])
    for slot in rows:
        if not isinstance(slot, dict):
            continue
        slot_id = slot.get("slot_id")
        if slot_id is None or "spd.read" not in caps:
            modules.append({**slot, "status": "ENUMERATED", "raw_available": False})
            continue
        read = provider_actions.call(name, "spd.read", {"slot_id": slot_id}, timeout_s=3.0)
        data = read.get("data") or {}
        hex_text = data.get("spd_hex")
        if read.get("status") in {"OK", "PARTIAL"} and isinstance(hex_text, str):
            try:
                raw = bytes.fromhex(hex_text)
                parsed = parse_spd(raw, source=f"provider:{name}:slot:{slot_id}")
                parsed.update({"status": "LIVE_CAPTURED", "slot_id": slot_id})
                modules.append(parsed)
                continue
            except ValueError:
                pass
        modules.append({**slot, "status": read.get("status", "UNAVAILABLE"), "raw_available": False})
    status["available"] = any(m.get("raw_available") for m in modules)
    return status, modules


def collect() -> dict[str, Any]:
    directory = _dump_dir()
    dump_modules = _collect_dump_files(directory) if directory else []
    live_provider, live_modules = _collect_live_provider()
    modules = live_modules if live_modules else dump_modules

    if live_provider.get("available"):
        provider = live_provider.get("provider")
        status = "COMPLETE"
    elif dump_modules:
        provider = "SPD_DUMP_DIRECTORY"
        status = "PARTIAL"
    else:
        provider = live_provider.get("provider") if live_provider.get("probe_status") not in (None, "NOT_FOUND") else "NONE"
        status = "MISSING_PROVIDER"

    return {
        "schema": SCHEMA,
        "generated_at": time.time(),
        "status": status,
        "provider": provider,
        "provider_path": str(directory) if directory else None,
        "provider_runtime": live_provider,
        "modules": modules,
        "raw_spd_available": any(m.get("raw_available") for m in modules),
        "live_smbus_available": bool(live_provider.get("available")),
        "capabilities": {
            "raw_capture_from_dump": True,
            "live_smbus_read": bool(live_provider.get("available")),
            "ddr3_geometry_decode": True,
            "ddr4_geometry_decode": True,
            "ddr4_crc_blocks": True,
            "ddr4_cas_latency_bitmap": True,
            "ddr4_xmp_signature_detection": True,
            "xmp2_profile_decode": True,
            "xmp3_profile_decode": True,
            "xmp_expo_decode": True,
            "ddr5_identity_decode": True,
            "ddr5_full_timing_decode": False,
            "jedec_manufacturer_name_decode": False,
            "xmp_profile_full_decode": True,
            "expo_profile_decode": True,
        },
        "missing": [
            x for x, missing in [
                ("privileged_smbus_provider_or_driver", not live_provider.get("available")),
                ("jedec_manufacturer_database", True),
                ("ddr5_full_timing_parser", True),
            ] if missing
        ],
        "invariants": {
            "cim_is_not_raw_spd": True,
            "raw_spd_is_never_inferred": True,
            "configured_clock_is_not_derived_from_spd_tck": True,
            "active_timings_are_not_inferred_from_supported_spd_timings": True,
            "xmp_expo_is_unknown_until_parsed_from_raw_bytes": True,
            "profile_presence_does_not_mean_profile_active": True,
            "profile_decode_does_not_claim_stability": True,
            "provider_absence_is_not_memory_failure": True,
        },
    }
