"""Unit tests for kachow.sbat (.sbat section insertion)."""
import struct

import pytest

from peimage import build_pe
from kachow import pe, sbat


def test_add_sbat_appends_a_readable_section():
    out = sbat.add_sbat(build_pe())
    img = pe.parse(out)
    s = img.section(b".sbat")
    assert s is not None
    assert s.virtual_size == len(sbat.SBAT)
    assert s.virtual_address == 0x3000
    assert s.raw_pointer == 0x800 and s.raw_size == 0x200
    assert len(out) == 0xA00
    assert sbat.read_sbat(out) == sbat.SBAT


def test_add_sbat_updates_headers():
    src = build_pe()
    out = sbat.add_sbat(src)
    oh = 0x80 + 24
    assert struct.unpack_from("<H", out, 0x86)[0] == 3                      # NumberOfSections
    assert struct.unpack_from("<I", out, oh + 56)[0] == 0x4000              # SizeOfImage
    before = struct.unpack_from("<I", src, oh + 8)[0]
    assert struct.unpack_from("<I", out, oh + 8)[0] == before + 0x200       # SizeOfInitializedData
    assert struct.unpack_from("<I", out, oh + 64)[0] == 0                   # CheckSum cleared
    flags = struct.unpack_from("<I", out, pe.parse(out).section_table + 2 * 40 + 36)[0]
    assert flags == sbat.SBAT_FLAGS


def test_original_sections_are_untouched():
    src = build_pe()
    out = sbat.add_sbat(src)
    assert out[0x400:0x800] == src[0x400:0x800]


def test_sbat_text_starts_with_the_shim_generation_line():
    assert sbat.SBAT.startswith(b"sbat,1,SBAT Version,sbat,1,")
    assert sbat.SBAT.count(b"\n") == 2


def test_read_sbat_is_none_without_section():
    assert sbat.read_sbat(build_pe()) is None


def test_refuses_signed_image():
    with pytest.raises(sbat.SbatError, match="already signed"):
        sbat.add_sbat(build_pe(cert=b"sig"))


def test_refuses_second_sbat():
    with pytest.raises(sbat.SbatError, match="already has .sbat"):
        sbat.add_sbat(sbat.add_sbat(build_pe()))


def test_refuses_when_headers_are_full():
    # table at 0x188: 15 headers + the new one end at 0x408, past SizeOfHeaders 0x400
    secs = tuple((f".s{i}".encode(), b"\x90") for i in range(15))
    with pytest.raises(sbat.SbatError, match="no room"):
        sbat.add_sbat(build_pe(sections=secs, headers=0x400))


def test_header_room_boundary_allows_exact_fit():
    # 14 headers + the new one end at 0x3E0, exactly SizeOfHeaders
    secs = tuple((f".s{i}".encode(), b"\x90") for i in range(14))
    assert pe.parse(sbat.add_sbat(build_pe(sections=secs, headers=0x3E0))).section(b".sbat")


def test_refuses_trailing_data():
    with pytest.raises(sbat.SbatError, match="trailing data"):
        sbat.add_sbat(build_pe(trailing=b"overlay"))


def _expected_sbat_image(src, file_align):
    """The bytes add_sbat must produce, computed from the PE spec independently of sbat.py."""
    img = pe.parse(src)
    po, oh, n = img.pe_offset, img.optional_offset, len(img.sections)
    end_va = max(s.virtual_address + max(s.virtual_size, s.raw_size) for s in img.sections)
    va = -(-end_va // 0x1000) * 0x1000
    raw_size = -(-191 // file_align) * file_align
    out = bytearray(src)
    struct.pack_into("<H", out, po + 6, n + 1)
    struct.pack_into("<I", out, oh + 8, struct.unpack_from("<I", src, oh + 8)[0] + raw_size)
    struct.pack_into("<I", out, oh + 56, va + 0x1000)
    struct.pack_into("<I", out, oh + 64, 0)
    out[oh + 240 + 40 * n:oh + 240 + 40 * (n + 1)] = (
        b".sbat\0\0\0" + struct.pack("<IIII", 191, va, raw_size, len(src)) + bytes(12) + bytes.fromhex("40000040"))
    return bytes(out) + sbat.SBAT + bytes(raw_size - 191)


@pytest.mark.parametrize("pe_offset", [0x80, 0x9C, 0xC4])
@pytest.mark.parametrize("file_align", [0x200, 0x20])
@pytest.mark.parametrize("sections", [
    ((b".text", b"\xc3" * 16),),
    ((b".text", b"\xc3" * 16), (b".data", b"\x01" * 8)),
    ((b".text", b"\xc3" * 16), (b".data", b"\x01" * 8), (b".reloc", b"\x02" * 4)),
    ((b".text", b"\x90" * 0x1800),),                 # VirtualAddress 0x1000 + size 0x1800 overlap bitwise
], ids=["1sec", "2sec", "3sec", "large"])
def test_add_sbat_changes_exactly_the_spec_fields(pe_offset, file_align, sections):
    src = bytearray(build_pe(sections, pe_offset=pe_offset, file_align=file_align))
    struct.pack_into("<I", src, pe_offset + 24 + 64, 0x1234ABCD)     # a CheckSum to clear
    out = sbat.add_sbat(bytes(src))
    assert out == _expected_sbat_image(bytes(src), file_align)
    assert sbat.read_sbat(out) == sbat.SBAT


def test_add_sbat_pads_an_unaligned_file_to_the_new_section():
    src = build_pe(headers=0x3E0)                    # sections start at 0x3E0, file ends at 0x7E0
    out = sbat.add_sbat(src)
    s = pe.parse(out).section(b".sbat")
    assert s.raw_pointer == 0x800 and len(out) == 0xA00
    assert out[0x7E0:0x800] == bytes(0x20)
    assert sbat.read_sbat(out) == sbat.SBAT


def test_refuses_truncated_last_section():
    with pytest.raises(sbat.SbatError):
        sbat.add_sbat(build_pe()[:-0x10])


def test_section_flags_are_initialized_readable_data():
    assert sbat.SBAT_FLAGS == 0x00000040 | 0x40000000


@pytest.mark.parametrize("v, a, aligned", [(0, 0x200, 0), (1, 0x200, 0x200), (0x200, 0x200, 0x200),
                                           (0x201, 0x200, 0x400), (0x2000, 0x1000, 0x2000)])
def test_align_rounds_up_to_the_next_multiple(v, a, aligned):
    assert sbat._align(v, a) == aligned
