from __future__ import annotations

import hashlib
import re
import struct
from pathlib import Path
from typing import Any


def _u16(b: bytes, off: int) -> int | None:
    if off < 0 or off + 2 > len(b):
        return None
    return struct.unpack_from('<H', b, off)[0]


def _u32(b: bytes, off: int) -> int | None:
    if off < 0 or off + 4 > len(b):
        return None
    return struct.unpack_from('<I', b, off)[0]


def _ascii_z(b: bytes, off: int, max_len: int = 128) -> str | None:
    if off < 0 or off >= len(b):
        return None
    raw = b[off: off + max_len].split(b'\0', 1)[0]
    raw = bytes(x for x in raw if x in (9, 10, 13) or 32 <= x < 127)
    try:
        s = raw.decode('ascii', errors='ignore').strip()
    except Exception:
        return None
    return s or None


def extract_strings(data: bytes, min_len: int = 6, max_items: int = 400) -> list[str]:
    ascii_hits = [m.group().decode('ascii', 'ignore') for m in re.finditer(rb'[\x20-\x7e]{%d,}' % min_len, data)]
    utf16_hits = []
    for m in re.finditer(rb'(?:[\x20-\x7e]\x00){%d,}' % min_len, data):
        try:
            utf16_hits.append(m.group().decode('utf-16le', 'ignore'))
        except Exception:
            pass
    out: list[str] = []
    seen = set()
    for s in ascii_hits + utf16_hits:
        s = s.strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
        if len(out) >= max_items:
            break
    return out


def parse_vbios_bytes(data: bytes) -> dict[str, Any]:
    report: dict[str, Any] = {
        'size_bytes': len(data),
        'sha256': hashlib.sha256(data).hexdigest(),
        'legacy_signature_ok': len(data) >= 2 and data[:2] == b'\x55\xaa',
        'checksum_mod256': sum(data) & 0xFF,
        'checksum_ok': (sum(data) & 0xFF) == 0,
    }

    # PCI Expansion ROM Data Structure pointer (PCI Firmware Spec).
    pcir_ptr = _u16(data, 0x18)
    report['pcir_offset'] = pcir_ptr
    if pcir_ptr is not None and pcir_ptr + 0x18 <= len(data) and data[pcir_ptr:pcir_ptr + 4] == b'PCIR':
        report['pcir'] = {
            'vendor_id': f'{_u16(data, pcir_ptr + 4):04X}',
            'device_id': f'{_u16(data, pcir_ptr + 6):04X}',
            'structure_length': _u16(data, pcir_ptr + 0x0A),
            'class_code': data[pcir_ptr + 0x0D:pcir_ptr + 0x10][::-1].hex().upper(),
            'image_length_512b_units': _u16(data, pcir_ptr + 0x10),
            'code_type': data[pcir_ptr + 0x14],
            'indicator': data[pcir_ptr + 0x15],
        }

    # AMD ATOMBIOS places a 16-bit pointer to the ROM header at 0x48.
    atom_ptr = _u16(data, 0x48)
    report['atom_rom_header_offset'] = atom_ptr
    if atom_ptr is not None and atom_ptr + 0x24 <= len(data):
        sig = data[atom_ptr + 4: atom_ptr + 8]
        if sig in (b'ATOM', b'MOTA'):
            fmt = data[atom_ptr + 2]
            content = data[atom_ptr + 3]
            # Layout shared by classic ATOM ROM header and later compatible variants.
            atom = {
                'signature': sig.decode('ascii', 'replace'),
                'structure_size': _u16(data, atom_ptr),
                'format_revision': fmt,
                'content_revision': content,
                'bios_runtime_segment': _u16(data, atom_ptr + 8),
                'protected_mode_info_offset': _u16(data, atom_ptr + 10),
                'config_filename_offset': _u16(data, atom_ptr + 12),
                'crc_block_offset': _u16(data, atom_ptr + 14),
                'boot_message_offset': _u16(data, atom_ptr + 16),
                'subsystem_vendor_id': f'{(_u16(data, atom_ptr + 24) or 0):04X}',
                'subsystem_id': f'{(_u16(data, atom_ptr + 26) or 0):04X}',
                'pci_info_offset': _u16(data, atom_ptr + 28),
                'master_command_table_offset': _u16(data, atom_ptr + 30),
                'master_data_table_offset': _u16(data, atom_ptr + 32),
            }
            if atom['boot_message_offset']:
                atom['boot_message'] = _ascii_z(data, int(atom['boot_message_offset']), 160)
            if atom['config_filename_offset']:
                atom['config_filename'] = _ascii_z(data, int(atom['config_filename_offset']), 100)
            report['atom'] = atom

    # Stable metadata offsets used by AMD ATOMBIOS generations.
    report['vbios_date'] = _ascii_z(data, 0x50, 24)
    report['vbios_part_number'] = _ascii_z(data, 0x80, 48)
    report['asic_bus_mem_type'] = _ascii_z(data, 0x94, 32)

    strings = extract_strings(data)
    interesting = []
    needles = ('ATOMBIOS', 'AMD', 'ATI', 'SAMSUNG', 'HYNIX', 'MICRON', 'ELPIDA', 'GDDR', 'DDR', '113-', 'D000', '580', '570', '2048')
    for s in strings:
        if any(n in s.upper() for n in needles):
            interesting.append(s)
    report['interesting_strings'] = interesting[:120]

    vendors = []
    upper_blob = data.upper()
    for name in ('SAMSUNG', 'HYNIX', 'MICRON', 'ELPIDA'):
        if name.encode() in upper_blob:
            vendors.append(name.title())
    report['memory_vendor_string_candidates'] = vendors
    return report


def parse_vbios(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    result = parse_vbios_bytes(p.read_bytes())
    result['path'] = str(p)
    return result
