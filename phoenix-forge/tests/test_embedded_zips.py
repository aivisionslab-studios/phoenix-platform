from io import BytesIO
from zipfile import ZipFile

from tools.extract_embedded_zips import discover, safe_member


def _zip(name: str, payload: bytes) -> bytes:
    b = BytesIO()
    with ZipFile(b, "w") as zf:
        zf.writestr(name, payload)
    return b.getvalue()


def test_discovers_concatenated_archives():
    data = b"MZ" + b"stub"*20 + _zip("one.exe", b"1") + b"gap" + _zip("two.dll", b"22")
    rows = discover(data)
    assert [r.entries for r in rows] == [("one.exe",), ("two.dll",)]
    assert rows[0].start < rows[1].start


def test_rejects_path_traversal():
    assert safe_member("dir/file.exe")
    assert not safe_member("../outside.exe")
    assert not safe_member("C:/outside.exe")
