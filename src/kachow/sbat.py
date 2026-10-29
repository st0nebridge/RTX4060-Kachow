"""Add the .sbat section shim 15.4+ requires of every second-stage image.

@module kachow.sbat
@description Append an .sbat PE section (SBAT generation metadata) to an unsigned PE32+
EFI image; shim rejects a second stage without one under Secure Boot even when its
signing key is enrolled.
@input bytes - an unsigned PE32+ image with no .sbat section and no overlay
@output bytes - the same image with an .sbat section appended (sign it afterwards)
@dependencies kachow.pe

@example
    signed_input = add_sbat(open("UNLOCK4090.EFI", "rb").read())
"""
import struct

from . import pe

SBAT = (
    b"sbat,1,SBAT Version,sbat,1,https://github.com/rhboot/shim/blob/main/SBAT.md\n"
    b"tensor-unlock,1,NekoMirra,rtx4060-laptop-tensor-unlock,1,"
    b"https://github.com/NekoMirra/rtx4060-laptop-tensor-unlock\n"
)
SBAT_FLAGS = 0x40000040  # IMAGE_SCN_CNT_INITIALIZED_DATA | IMAGE_SCN_MEM_READ


class SbatError(ValueError):
    """The image cannot take an .sbat section as it is."""


def _align(v, a):
    return (v + a - 1) // a * a


def read_sbat(data):
    """Return the .sbat section's contents, or None if the image has none."""
    s = pe.parse(data).section(b".sbat")
    if s is None:
        return None
    return bytes(data[s.raw_pointer:s.raw_pointer + s.virtual_size])


def add_sbat(data):
    img = pe.parse(data)
    if img.signed:
        raise SbatError("binary is already signed; use the unsigned original")
    if img.section(b".sbat") is not None:
        raise SbatError("already has .sbat")
    nsec = len(img.sections)
    table = img.section_table
    if table + 40 * (nsec + 1) > img.size_of_headers:
        raise SbatError("no room in headers for another section")
    last_va_end = max(s.virtual_address + max(s.virtual_size, s.raw_size) for s in img.sections)
    last_raw_end = max(s.raw_pointer + s.raw_size for s in img.sections)
    if last_raw_end != len(data):
        raise SbatError("unexpected trailing data after last section")

    va = _align(last_va_end, img.section_alignment)
    raw_size = _align(len(SBAT), img.file_alignment)
    raw_ptr = _align(len(data), img.file_alignment)

    out = bytearray(data)
    out[table + 40 * nsec:table + 40 * (nsec + 1)] = struct.pack(
        "<8sIIIIIIHHI", b".sbat", len(SBAT), va, raw_size, raw_ptr, 0, 0, 0, 0, SBAT_FLAGS)
    oh = img.optional_offset
    struct.pack_into("<H", out, img.pe_offset + 6, nsec + 1)
    struct.pack_into("<I", out, oh + 56, va + _align(len(SBAT), img.section_alignment))  # SizeOfImage
    (init_data,) = struct.unpack_from("<I", out, oh + 8)
    struct.pack_into("<I", out, oh + 8, init_data + raw_size)
    struct.pack_into("<I", out, oh + 64, 0)
    out = out.ljust(raw_ptr, b"\0")  # pad an unaligned file up to the new section
    out += SBAT + b"\0" * (raw_size - len(SBAT))
    return bytes(out)
