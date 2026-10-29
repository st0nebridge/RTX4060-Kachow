"""Unit tests for kachow.signature (MOK signer and .sbat guard)."""
import struct

from peimage import build_pe, build_pe_with_cert
from kachow import sbat, signature

CERT = b"\x30\x82\x03\x54" + b"MOK-CERT-DER" * 4


def _signed(cert_bytes, *, with_sbat=True):
    base = sbat.add_sbat(build_pe()) if with_sbat else build_pe()
    return build_pe_with_cert(base, b"pkcs7-prefix" + cert_bytes + b"pkcs7-suffix")


def test_signed_by_mok_with_sbat_is_ok():
    c = signature.check(_signed(CERT), CERT)
    assert c.ok and c.reason == "ok"


def test_unsigned_image_is_refused():
    c = signature.check(sbat.add_sbat(build_pe()), CERT)
    assert not c.ok and not c.signed and c.reason == "not signed"


def test_other_signer_is_refused():
    c = signature.check(_signed(b"\x30\x82OTHER-CERT"), CERT)
    assert c.signed and not c.signer_matches and not c.ok
    assert c.reason == "signed, but not with the expected certificate"


def test_missing_sbat_is_refused():
    c = signature.check(_signed(CERT, with_sbat=False), CERT)
    assert c.signer_matches and not c.has_sbat and not c.ok
    assert c.reason == "signed, but has no .sbat section"


def test_non_pkcs_certificate_type_is_not_a_signature():
    data = build_pe_with_cert(sbat.add_sbat(build_pe()), CERT, ctype=1)
    assert not signature.check(data, CERT).signed


def test_certificates_walks_multiple_entries():
    first = build_pe_with_cert(build_pe(), b"A" * 5)
    entry2 = struct.pack("<IHH", 8 + 3, 0x200, 2) + b"BBB" + b"\0" * 5
    out = bytearray(first + entry2)
    off, size = struct.unpack_from("<II", out, 0x80 + 24 + 144)
    struct.pack_into("<II", out, 0x80 + 24 + 144, off, size + len(entry2))
    assert list(signature.certificates(bytes(out))) == [(2, b"A" * 5), (2, b"BBB")]


def test_certificates_stops_on_bad_length():
    out = bytearray(build_pe_with_cert(build_pe(), b"A" * 8))
    off = struct.unpack_from("<I", out, 0x80 + 24 + 144)[0]
    struct.pack_into("<I", out, off, 4)
    assert list(signature.certificates(bytes(out))) == []


def test_certificates_ignores_directory_past_end_of_file():
    out = bytearray(build_pe())
    struct.pack_into("<II", out, 0x80 + 24 + 144, len(out), 64)
    assert list(signature.certificates(bytes(out))) == []


def test_certificates_stops_on_entry_overrunning_directory():
    out = bytearray(build_pe_with_cert(build_pe(), b"A" * 8))
    off = struct.unpack_from("<I", out, 0x80 + 24 + 144)[0]
    struct.pack_into("<I", out, off, 64)
    assert list(signature.certificates(bytes(out))) == []


def _entry(blob, ctype=2, length=None):
    e = struct.pack("<IHH", 8 + len(blob) if length is None else length, 0x200, ctype) + blob
    return e + bytes(-len(e) % 8)


def _with_directory(directory, trailing=b""):
    out = bytearray(build_pe())
    struct.pack_into("<II", out, 0x80 + 24 + 144, len(out), len(directory))
    return bytes(out + directory + trailing)


def test_certificates_reads_a_directory_that_ends_before_the_file():
    assert list(signature.certificates(_with_directory(_entry(b"A" * 5), trailing=b"overlay"))) == [(2, b"A" * 5)]


def test_certificates_reads_empty_entries_at_both_ends():
    # an empty entry is exactly the 8-byte header; the middle one starts 8 bytes in
    entries = _entry(b"") + _entry(b"BBB") + _entry(b"")
    assert list(signature.certificates(_with_directory(entries))) == [(2, b""), (2, b"BBB"), (2, b"")]


def test_certificates_steps_by_the_8_byte_aligned_length():
    entries = _entry(b"A" * 8) + _entry(b"B") + _entry(b"CCC")     # lengths 16, 9 (padded to 16), 11
    assert list(signature.certificates(_with_directory(entries))) == [(2, b"A" * 8), (2, b"B"), (2, b"CCC")]


def test_certificates_ignores_slack_shorter_than_a_header_at_end_of_file():
    assert list(signature.certificates(_with_directory(_entry(b"A" * 8) + bytes(7)))) == [(2, b"A" * 8)]


def test_certificates_stops_on_length_below_the_header():
    assert list(signature.certificates(_with_directory(_entry(b"", length=7)))) == []


def test_certificates_stops_when_a_later_entry_overruns():
    # second entry at +0x10 claims 0x30 bytes but only 0x28 remain
    directory = _entry(b"A" * 8) + struct.pack("<IHH", 0x30, 0x200, 2) + bytes(0x20)
    assert list(signature.certificates(_with_directory(directory))) == [(2, b"A" * 8)]
