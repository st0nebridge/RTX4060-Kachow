"""Test factory: build small, valid PE32+ images for the PE, SBAT and signature tests.

@module tests.peimage
@description Produces byte-exact PE32+ images with chosen sections, alignments and an
optional certificate table, so tests never depend on real EFI binaries.
@dependencies struct (stdlib)
"""
import struct

FILE_ALIGN = 0x200
SECT_ALIGN = 0x1000


def _align(v, a):
    return (v + a - 1) // a * a


def build_pe(sections=((b".text", b"\xc3" * 16), (b".data", b"\x01" * 8)), *, headers=0x400,
             machine_magic=0x20B, cert=None, trailing=b"", pe_offset=0x80, file_align=FILE_ALIGN):
    """Return a PE32+ image. `cert` appends a WIN_CERTIFICATE holding those bytes.

    A pe_offset with low bits set (e.g. 0xE4) makes `a + b` and `a | b` differ for the
    header field offsets, which the aligned default 0x80 never does."""
    pe = pe_offset
    opt_size = 240
    table = pe + 24 + opt_size
    out = bytearray(headers)
    out[:2] = b"MZ"
    struct.pack_into("<I", out, 0x3C, pe)
    out[pe:pe + 4] = b"PE\0\0"
    struct.pack_into("<HH", out, pe + 4, 0x8664, len(sections))
    struct.pack_into("<H", out, pe + 20, opt_size)
    oh = pe + 24
    struct.pack_into("<H", out, oh, machine_magic)
    struct.pack_into("<II", out, oh + 32, SECT_ALIGN, file_align)
    struct.pack_into("<I", out, oh + 60, headers)
    va = SECT_ALIGN
    init = 0
    for i, (name, body) in enumerate(sections):
        raw_size = _align(len(body), file_align)
        raw_ptr = len(out)
        struct.pack_into("<8sIIII", out, table + 40 * i, name, len(body), va, raw_size, raw_ptr)
        out += body + b"\0" * (raw_size - len(body))
        init += raw_size
        va += _align(len(body), SECT_ALIGN)
    struct.pack_into("<I", out, oh + 8, init)
    struct.pack_into("<I", out, oh + 56, va)
    out += trailing
    if cert is not None:
        blob = struct.pack("<IHH", 8 + len(cert), 0x200, 2) + cert
        blob += b"\0" * (_align(len(blob), 8) - len(blob))
        struct.pack_into("<II", out, oh + 112 + 8 * 4, len(out), len(blob))
        out += blob
    return bytes(out)


def build_pe_with_cert(image, blob, ctype=2):
    """Attach one WIN_CERTIFICATE (default type PKCS#7) holding `blob` to an image from build_pe()."""
    entry = struct.pack("<IHH", 8 + len(blob), 0x200, ctype) + blob
    entry += b"\0" * ((8 - len(entry) % 8) % 8)
    out = bytearray(image)
    (pe,) = struct.unpack_from("<I", out, 0x3C)
    struct.pack_into("<II", out, pe + 24 + 112 + 32, len(out), len(entry))
    return bytes(out + entry)
