"""Turn the start-screen art (config/banner.txt) into the unlocker's two banner files.

@module kachow.banner
@description Check the art fits a UEFI text console and encode it as UCS-2 with CR LF,
plus an ASCII copy the unlocker shows when the firmware font lacks a glyph (braille
cells become the ASCII character closest to their dots).
@input str - the art, one console row per line
@output Banner - the art and its ASCII copy; write() saves banner.txt and banner-ascii.txt
@dependencies unicodedata (stdlib)

@example
    banner.write(banner.parse(Path("config/banner.txt").read_text("utf-8")), Path("local/build/banner"))
"""
import unicodedata
from dataclasses import dataclass
from pathlib import Path

MAX_COLUMNS = 79  # mode 0 of every UEFI console is 80x25; text in the last column wraps
MAX_LINES = 20
FILES = ('banner.txt', 'banner-ascii.txt')
BRAILLE = 0x2800
TOP, BOTTOM = 0x1B, 0xE4  # braille dots 1 2 4 5 (upper half) and 3 6 7 8 (lower half)


class BannerError(ValueError):
    """The art cannot be shown on the unlocker's console as it is."""


@dataclass(frozen=True)
class Banner:
    text: str
    ascii: str


def to_ascii(ch):
    """The ASCII stand-in for one character: itself, a braille cell by its dots, else '?'."""
    o = ord(ch)
    if o < 0x80:
        return ch
    if (o & ~0xFF) != BRAILLE:  # U+2800-U+28FF: one cell per dot pattern
        return '?'
    n, top, bottom = (bin(o & m).count('1') for m in (0xFF, TOP, BOTTOM))
    if not n:
        return ' '
    if n >= 7:
        return '#'
    if not bottom:
        return "'" if top <= 2 else '"'
    if not top:
        return '.' if bottom <= 2 else '_'
    return ':' if n <= 4 else '%'


def _check(ch, row, col):
    where = f'line {row}, column {col}'
    if ord(ch) > 0xFFFF:
        raise BannerError(f'{where}: U+{ord(ch):X} is outside UCS-2, which UEFI consoles print')
    if unicodedata.category(ch).startswith('C'):
        raise BannerError(f'{where}: control or unassigned character U+{ord(ch):04X}')
    if unicodedata.combining(ch) or unicodedata.east_asian_width(ch) in 'WF':
        raise BannerError(f'{where}: U+{ord(ch):04X} does not take exactly one console cell')


def parse(text):
    """Validate the art and return it with its ASCII copy (trailing blanks dropped)."""
    rows = [r.rstrip() for r in text.removeprefix('﻿').splitlines()]
    while rows and not rows[-1]:
        rows.pop()
    if not rows:
        raise BannerError('banner is empty; delete the file to show none')
    if len(rows) > MAX_LINES:
        raise BannerError(f'{len(rows)} lines; the console shows at most {MAX_LINES} above the countdown')
    for i, r in enumerate(rows, 1):
        if len(r) > MAX_COLUMNS:
            raise BannerError(f'line {i} is {len(r)} columns wide; at most {MAX_COLUMNS} fit')
        for j, ch in enumerate(r, 1):
            _check(ch, i, j)
    return Banner('\n'.join(rows), '\n'.join(''.join(map(to_ascii, r)) for r in rows))


def encode(text):
    """UCS-2 little-endian, CR LF after every line and one blank line under the art."""
    return (text + '\n\n').replace('\n', '\r\n').encode('utf-16-le')


def write(b, out):
    """Save a parsed Banner as banner.txt and banner-ascii.txt (for the ESP's \\GPU4090-ASSETS\\)."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    paths = [out / name for name in FILES]
    for p, t in zip(paths, (b.text, b.ascii)):
        p.write_bytes(encode(t))
    return paths
