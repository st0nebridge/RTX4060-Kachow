"""Build the shim MOK enrollment request (the payload `mokutil --import` writes).

@module kachow.mok
@description Produce MokNew (an EFI_SIGNATURE_LIST holding one X.509 certificate) and
MokAuth (SHA-256 of MokNew followed by the password in UCS-2); written to shim's
variables, they make MokManager open its "Enroll MOK" menu on the next boot.
@input bytes cert_der, str password
@output MokRequest - the MokNew and MokAuth variable contents
@dependencies hashlib, struct, uuid (stdlib)

@example
    req = request(open("MOK.cer", "rb").read(), "tensor")
    req.write(Path("local/mok"))
"""
import hashlib
import struct
import uuid
from dataclasses import dataclass
from pathlib import Path

EFI_CERT_X509_GUID = uuid.UUID('a5c059a1-94e4-4aa7-87b5-ab155c2bf072')
SHIM_LOCK_GUID = uuid.UUID('605dab50-e046-4300-abb6-3dd810dd8b23')
ESL_HEADER_SIZE = 28   # SignatureType GUID + ListSize + HeaderSize + SignatureSize
OWNER_SIZE = 16


@dataclass(frozen=True)
class MokRequest:
    mok_new: bytes
    mok_auth: bytes

    def write(self, outdir):
        outdir = Path(outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / 'MokNew.bin').write_bytes(self.mok_new)
        (outdir / 'MokAuth.bin').write_bytes(self.mok_auth)
        return outdir / 'MokNew.bin', outdir / 'MokAuth.bin'


def signature_list(cert_der, owner=SHIM_LOCK_GUID):
    if not cert_der:
        raise ValueError('empty certificate')
    sig_size = OWNER_SIZE + len(cert_der)
    return (EFI_CERT_X509_GUID.bytes_le
            + struct.pack('<III', ESL_HEADER_SIZE + sig_size, 0, sig_size)
            + owner.bytes_le + cert_der)


def auth(mok_new, password):
    if not password:
        raise ValueError('empty password')
    return hashlib.sha256(mok_new + password.encode('utf-16-le')).digest()


def request(cert_der, password):
    esl = signature_list(cert_der)
    return MokRequest(esl, auth(esl, password))
