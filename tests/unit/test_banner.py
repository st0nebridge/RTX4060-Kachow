"""Unit tests for kachow.banner: console limits, the ASCII copy and the UCS-2 files."""
import pytest

from kachow import banner
from kachow.banner import BannerError


def cell(*dots):
    """The braille character with these dots (1-8) raised."""
    return chr(0x2800 + sum(1 << (d - 1) for d in dots))


@pytest.mark.parametrize('ch, want', [
    ('A', 'A'), ('~', '~'), (' ', ' '), ('\x7f', '\x7f'),
    (cell(), ' '), (cell(*range(1, 9)), '#'), (cell(1, 2, 3, 4, 5, 6, 7), '#'),
    (cell(1), "'"), (cell(1, 4), "'"), (cell(1, 2, 4), '"'), (cell(1, 2, 4, 5), '"'),
    (cell(7), '.'), (cell(7, 8), '.'), (cell(3, 7, 8), '_'), (cell(3, 6, 7, 8), '_'),
    (cell(1, 7), ':'), (cell(1, 2, 7, 8), ':'), (cell(1, 2, 3, 7, 8), '%'), (cell(1, 2, 3, 4, 7, 8), '%'),
    ('█', '?'), ('é', '?'), ('⟿', '?'), ('⤀', '?'), ('\x80', '?'), ('Ĩ', '?'),
])
def test_to_ascii(ch, want):
    assert banner.to_ascii(ch) == want


def test_braille_dot_halves():
    # dots 1 2 4 5 are the upper half of a cell, 3 6 7 8 the lower
    assert banner.to_ascii(cell(4, 5)) == "'" and banner.to_ascii(cell(1, 2, 4, 5)) == '"'
    assert banner.to_ascii(cell(6)) == '.' and banner.to_ascii(cell(3, 6, 7)) == '_'
    assert (banner.TOP, banner.BOTTOM) == (0x1B, 0xE4)


def test_parse_keeps_rows_and_builds_the_ascii_copy():
    b = banner.parse(f'﻿{cell()}{cell(1, 2, 3, 4, 5, 6, 7, 8)}x  \n\n  ab\n\n\n')
    assert b.text == f'{cell()}{cell(*range(1, 9))}x\n\n  ab'
    assert b.ascii == ' #x\n\n  ab'


def test_parse_accepts_the_limits_exactly():
    b = banner.parse('\n'.join(['x' * banner.MAX_COLUMNS] * banner.MAX_LINES))
    assert b.text.count('\n') == banner.MAX_LINES - 1
    assert (banner.MAX_COLUMNS, banner.MAX_LINES) == (79, 20)


@pytest.mark.parametrize('text, message', [
    ('', 'empty'), ('\n \n', 'empty'),
    ('x\n' * 21, '21 lines'),
    ('x' * 80, 'line 1 is 80 columns'),
    ('ok\nab\tc', 'line 2, column 3: control'),
    ('a​b', 'column 2: control'),           # format character (Cf)
    ('\U0001F600', 'outside UCS-2'),
    ('\U00010000', r'U\+10000 is outside UCS-2'),  # the first code point past the BMP
    ('￿', r'control or unassigned character U\+FFFF'),  # the last one inside it
    ('中', 'exactly one console cell'),      # wide
    ('Ａ', 'exactly one console cell'),      # fullwidth
    ('é', r'column 2: U\+0301 does not take'),  # combining
])
def test_parse_rejects(text, message):
    with pytest.raises(BannerError, match=message):
        banner.parse(text)


def test_halfwidth_and_ambiguous_characters_are_accepted():
    assert banner.parse('ｱé').ascii == '??'


def test_encode_is_ucs2_with_crlf_and_a_blank_line():
    assert banner.encode('a\nb') == 'a\r\nb\r\n\r\n'.encode('utf-16-le')


def test_write_saves_both_files(tmp_path):
    b = banner.parse(f'{cell(1)}A')
    paths = banner.write(b, tmp_path / 'new' / 'out')
    assert [p.name for p in paths] == ['banner.txt', 'banner-ascii.txt']
    assert paths[0].read_bytes() == banner.encode(f'{cell(1)}A')
    assert paths[1].read_bytes() == banner.encode("'A")
    banner.write(b, tmp_path / 'new' / 'out')  # an existing directory is fine


def test_the_projects_banner_fits():
    from pathlib import Path
    art = Path(__file__).resolve().parents[2] / 'config' / 'banner.txt'
    b = banner.parse(art.read_text('utf-8'))
    assert b.ascii.isascii() and len(banner.encode(b.text)) <= 16384  # BANNER_MAX in the patch
