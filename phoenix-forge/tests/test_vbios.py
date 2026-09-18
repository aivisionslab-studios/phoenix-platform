from phoenix_forge.modules.vbios import parse_vbios_bytes

def test_atom_and_pcir_parse():
    b=bytearray(512)
    b[0:2]=b'\x55\xaa'
    b[0x18:0x1a]=(0x100).to_bytes(2,'little')
    b[0x100:0x104]=b'PCIR'; b[0x104:0x106]=(0x1002).to_bytes(2,'little'); b[0x106:0x108]=(0x6FDF).to_bytes(2,'little')
    b[0x48:0x4a]=(0xC0).to_bytes(2,'little')
    b[0xC0:0xC2]=(36).to_bytes(2,'little');b[0xC2]=1;b[0xC3]=1;b[0xC4:0xC8]=b'ATOM'
    b[0xD8:0xDA]=(0x1002).to_bytes(2,'little');b[0xDA:0xDC]=(0x0B31).to_bytes(2,'little')
    r=parse_vbios_bytes(bytes(b))
    assert r['pcir']['vendor_id']=='1002'
    assert r['pcir']['device_id']=='6FDF'
    assert r['atom']['signature']=='ATOM'
    assert r['atom']['subsystem_vendor_id']=='1002'
    assert r['atom']['subsystem_id']=='0B31'
