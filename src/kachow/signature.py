"""Check that an EFI image carries an Authenticode signature by a given certificate.

@module kachow.signature
@description Read the PE certificate table and confirm the PKCS#7 blob embeds the MOK
certificate, and that the image has .sbat; the guard that stops an unsigned or
wrongly signed image reaching the ESP (shim then fails with Security Violation).
@input bytes - a PE32+ image; bytes - the DER certificate expected as signer
@output SignatureCheck - signed / signer match / sbat present, with a reason
@dependencies kachow.pe, kachow.sbat

@example
    check(open("auto-grubx64.efi", "rb").read(), open("MOK.cer", "rb").read()).ok
"""
import struct
from dataclasses import dataclass

from . import pe, sbat

WIN_CERT_TYPE_PKCS_SIGNED_DATA = 2
SIGNATURE_TYPES = frozenset({WIN_CERT_TYPE_PKCS_SIGNED_DATA})


@dataclass(frozen=True)
class SignatureCheck:
    signed: bool
    signer_matches: bool
    has_sbat: bool

    @property
    def ok(self):
        return self.signed and self.signer_matches and self.has_sbat

    @property
    def reason(self):
        if not self.signed:
            return "not signed"
        if not self.signer_matches:
            return "signed, but not with the expected certificate"
        if not self.has_sbat:
            return "signed, but has no .sbat section"
        return "ok"


def certificates(data):
    """Yield (type, blob) for each WIN_CERTIFICATE entry in the image."""
    img = pe.parse(data)
    off, end = img.cert_offset, img.cert_offset + img.cert_size
    if not img.signed or end > len(data):
        return
    while off + 8 <= end:
        length, _rev, ctype = struct.unpack_from("<IHH", data, off)
        if length < 8 or off + length > end:
            return
        yield ctype, bytes(data[off + 8:off + length])
        off += (length + 7) // 8 * 8


def check(data, cert_der):
    blobs = [b for t, b in certificates(data) if t in SIGNATURE_TYPES]
    return SignatureCheck(
        signed=bool(blobs),
        signer_matches=any(cert_der in b for b in blobs),
        has_sbat=sbat.read_sbat(data) is not None,
    )
