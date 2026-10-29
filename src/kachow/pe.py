"""PE32+ image layout: headers, section table and certificate directory.

@module kachow.pe
@description Parse the parts of a PE32+ EFI image that SBAT insertion and signature
checks need, without modifying the image.
@input bytes - a PE32+ image
@output PeImage - header offsets, alignments, sections and the security directory
@dependencies struct (stdlib)

@example
    img = parse(open("UNLOCK4090.EFI", "rb").read())
    [s.name for s in img.sections]
"""
import struct
from dataclasses import dataclass

PE32_PLUS = 0x20B
SECTION_HEADER_SIZE = 40
SECURITY_DIRECTORY = 4


class PeError(ValueError):
    """The bytes are not a PE32+ image this tool can handle."""


@dataclass(frozen=True)
class Section:
    name: bytes
    virtual_size: int
    virtual_address: int
    raw_size: int
    raw_pointer: int


@dataclass(frozen=True)
class PeImage:
    pe_offset: int
    optional_offset: int
    optional_size: int
    section_alignment: int
    file_alignment: int
    size_of_headers: int
    cert_offset: int
    cert_size: int
    sections: tuple

    @property
    def section_table(self):
        return self.optional_offset + self.optional_size

    @property
    def signed(self):
        return bool(self.cert_offset or self.cert_size)

    def section(self, name):
        for s in self.sections:
            if s.name == name:
                return s
        return None


def parse(data):
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise PeError("not a PE file (no MZ header)")
    (pe,) = struct.unpack_from("<I", data, 0x3C)
    if data[pe:pe + 4] != b"PE\0\0":
        raise PeError("not a PE file")
    (nsec,) = struct.unpack_from("<H", data, pe + 6)
    (opt_size,) = struct.unpack_from("<H", data, pe + 20)
    oh = pe + 24
    (magic,) = struct.unpack_from("<H", data, oh)
    if magic != PE32_PLUS:
        raise PeError("not PE32+")
    sec_align, file_align = struct.unpack_from("<II", data, oh + 32)
    (size_of_headers,) = struct.unpack_from("<I", data, oh + 60)
    cert_off, cert_size = struct.unpack_from("<II", data, oh + 112 + 8 * SECURITY_DIRECTORY)
    table = oh + opt_size
    sections = []
    for i in range(nsec):
        name, vs, va, rs, rp = struct.unpack_from("<8sIIII", data, table + SECTION_HEADER_SIZE * i)
        sections.append(Section(name.rstrip(b"\0"), vs, va, rs, rp))
    return PeImage(pe, oh, opt_size, sec_align, file_align, size_of_headers, cert_off, cert_size, tuple(sections))
