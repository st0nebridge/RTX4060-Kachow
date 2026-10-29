"""Every result type the tools return is immutable, so a check cannot be altered after it is made."""
import dataclasses
from pathlib import Path

import pytest

from kachow import banner, lifecycle, manifest, mok, pe, runlog, signature, zigbuild


@pytest.mark.parametrize('value', [
    pe.Section(b'.text', 1, 2, 3, 4),
    pe.PeImage(0, 0, 0, 0, 0, 0, 0, 0, ()),
    signature.SignatureCheck(True, True, True),
    mok.MokRequest(b'n', b'a'),
    runlog.parse(''),
    zigbuild.Built(Path('x'), 1, 'ab'),
    manifest.FileCheck('p', 'e', 'a'),
    banner.Banner("a", "a"),
    lifecycle.Step("a", "b", "c"),
], ids=lambda v: type(v).__name__)
def test_result_types_are_frozen(value):
    field = dataclasses.fields(value)[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(value, field, None)
