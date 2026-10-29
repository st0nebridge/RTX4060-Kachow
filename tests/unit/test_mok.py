"""Unit tests for kachow.mok (MokNew / MokAuth payload)."""
import hashlib
import struct

import pytest

from kachow import mok

CERT = b'\x30\x82\x03\x54' + bytes(range(200))


def test_signature_list_layout():
    esl = mok.signature_list(CERT)
    assert esl[:16] == bytes.fromhex('a159c0a5e494a74a87b5ab155c2bf072')
    list_size, header_size, sig_size = struct.unpack_from('<III', esl, 16)
    assert (list_size, header_size, sig_size) == (28 + 16 + len(CERT), 0, 16 + len(CERT))
    assert list_size == len(esl)
    assert esl[28:44] == bytes.fromhex('50ab5d6046e00043abb63dd810dd8b23')
    assert esl[44:] == CERT


def test_auth_hashes_list_then_ucs2_password():
    esl = mok.signature_list(CERT)
    assert mok.auth(esl, 'tensor') == hashlib.sha256(esl + 't\0e\0n\0s\0o\0r\0'.encode()).digest()
    assert len(mok.auth(esl, 'tensor')) == 32


def test_request_combines_both(tmp_path):
    req = mok.request(CERT, 'pw')
    assert req.mok_new == mok.signature_list(CERT)
    assert req.mok_auth == mok.auth(req.mok_new, 'pw')
    new, au = req.write(tmp_path / 'mok')
    assert new.read_bytes() == req.mok_new and au.read_bytes() == req.mok_auth
    assert (new.name, au.name) == ('MokNew.bin', 'MokAuth.bin')


def test_different_passwords_give_different_auth():
    assert mok.request(CERT, 'a').mok_auth != mok.request(CERT, 'b').mok_auth


@pytest.mark.parametrize('fn, arg', [(mok.signature_list, b''), (lambda p: mok.auth(b'x', p), '')])
def test_rejects_empty_input(fn, arg):
    with pytest.raises(ValueError):
        fn(arg)


@pytest.mark.parametrize('cert', [CERT, b'\x30' * 20])    # 16 + 20: the sizes share a bit
def test_signature_size_is_owner_plus_certificate(cert):
    esl = mok.signature_list(cert)
    assert struct.unpack_from('<III', esl, 16) == (28 + 16 + len(cert), 0, 16 + len(cert))
    assert len(esl) == 44 + len(cert)


def test_write_creates_missing_parents_and_overwrites(tmp_path):
    req = mok.request(CERT, 'pw')
    req.write(tmp_path / 'a' / 'b')
    new, _au = mok.request(CERT, 'other').write(tmp_path / 'a' / 'b')
    assert new.read_bytes() == req.mok_new
