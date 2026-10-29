"""Unit tests for kachow.pe (PE32+ parsing)."""
import struct

import pytest

from peimage import build_pe
from kachow import pe


def test_parse_reads_sections_and_alignment():
    img = pe.parse(build_pe())
    assert [s.name for s in img.sections] == [b".text", b".data"]
    assert (img.section_alignment, img.file_alignment, img.size_of_headers) == (0x1000, 0x200, 0x400)
    assert img.section(b".data").raw_pointer == 0x600
    assert img.section(b".sbat") is None
    assert img.section_table == img.optional_offset + 240


def test_unsigned_image_reports_unsigned():
    img = pe.parse(build_pe())
    assert not img.signed
    assert (img.cert_offset, img.cert_size) == (0, 0)


def test_signed_image_reports_cert_directory():
    data = build_pe(cert=b"x" * 10)
    img = pe.parse(data)
    assert img.signed
    assert img.cert_offset == 0x800 and img.cert_size == 24


@pytest.mark.parametrize("mutate, message", [
    (lambda d: b"ZM" + d[2:], "no MZ header"),
    (lambda d: d[:0x80] + b"XX\0\0" + d[0x84:], "not a PE file"),
    (lambda d: d[:0x98] + struct.pack("<H", 0x10B) + d[0x9A:], "not PE32+"),
])
def test_rejects_non_pe32_plus(mutate, message):
    with pytest.raises(pe.PeError, match=message):
        pe.parse(mutate(build_pe()))


def test_rejects_truncated_input():
    with pytest.raises(pe.PeError):
        pe.parse(b"MZ")


# pe_offset 0x9C and 0xC4 share bits with the header field offsets (+4, +6, +20, +24 from the
# PE signature; +8 ... +144 from the optional header), so `a + b` and `a | b` read different bytes
@pytest.mark.parametrize("pe_offset", [0x80, 0x9C, 0xC4])
def test_parse_reads_every_field_at_any_header_offset(pe_offset):
    data = build_pe(pe_offset=pe_offset, cert=b"sig")
    img = pe.parse(data)
    assert img == pe.PeImage(
        pe_offset=pe_offset, optional_offset=pe_offset + 24, optional_size=240,
        section_alignment=0x1000, file_alignment=0x200, size_of_headers=0x400,
        cert_offset=0x800, cert_size=16,
        sections=(pe.Section(b".text", 16, 0x1000, 0x200, 0x400), pe.Section(b".data", 8, 0x2000, 0x200, 0x600)))


@pytest.mark.parametrize("offset, size", [(0x800, 0), (0, 16)])
def test_either_half_of_the_cert_directory_marks_the_image_signed(offset, size):
    out = bytearray(build_pe())
    struct.pack_into("<II", out, 0x80 + 24 + 144, offset, size)
    assert pe.parse(bytes(out)).signed


def test_size_boundary_for_the_dos_header():
    stub = b"MZ" + bytes(0x3E)                       # 0x40 bytes: long enough, e_lfanew = 0
    with pytest.raises(pe.PeError, match="not a PE file$"):
        pe.parse(stub)
    with pytest.raises(pe.PeError, match="no MZ header"):
        pe.parse(stub[:-1])


@pytest.mark.parametrize("mutate, message", [
    (lambda d: b"AZ" + d[2:], "no MZ header"),                                  # sorts below "MZ"
    (lambda d: d[:0x80] + b"AA\0\0" + d[0x84:], "not a PE file"),               # sorts below "PE"
    (lambda d: d[:0x98] + struct.pack("<H", 0x30B) + d[0x9A:], "not PE32+"),    # above 0x20B
])
def test_rejects_signatures_on_either_side(mutate, message):
    with pytest.raises(pe.PeError, match=message):
        pe.parse(mutate(build_pe()))
