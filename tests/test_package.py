from __future__ import annotations

from importlib.resources import files
from typing import Annotated

import ctypesx


def test_root_package_exposes_each_public_api_category() -> None:
    expected = (
        "Field",
        "Bits",
        "Length",
        "CStruct",
        "ConstSpan",
        "CUnion",
        "FieldInfo",
        "field_info",
        "Array",
        "FamArray",
        "CInteger",
        "CBool",
        "CChar",
        "CWChar",
        "U8",
        "S64",
        "CFloat",
        "CFloatComplex",
        "CEnum",
        "CFlag",
        "U16Enum",
        "U32Flag",
        "Pointer",
        "ConstPointer",
        "CharPointer",
        "ConstCharPointer",
        "VoidPointer",
        "FunctionPointer",
        "Span",
        "pointer_to",
    )

    for name in expected:
        assert getattr(ctypesx, name) is not None

    # Public discovery is natural module discovery; ctypesx deliberately does
    # not maintain a second manual API list.
    assert not hasattr(ctypesx, "__all__")


def test_readme_style_declaration_works_through_root_reexports() -> None:
    class Packet(ctypesx.CStruct):
        ready: ctypesx.CBool = ctypesx.Field()
        mode: Annotated[ctypesx.U8, ctypesx.Bits(3)] = ctypesx.Field()
        data: Annotated[
            ctypesx.Array[ctypesx.U16],
            ctypesx.Length(2),
        ] = ctypesx.Field()
        payload: ctypesx.FamArray[ctypesx.U8] = ctypesx.Field()

    packet = Packet(
        ready=1,
        mode=5,
        data=[10, 20],
        payload=[1, 2, 3],
    )
    packet.payload.append(4)

    assert packet.ready == ctypesx.CBool(1)
    assert list(packet.payload) == [
        ctypesx.U8(1),
        ctypesx.U8(2),
        ctypesx.U8(3),
        ctypesx.U8(4),
    ]
    assert ctypesx.field_info(Packet, "payload").flexible


def test_distribution_contains_py_typed_marker() -> None:
    marker = files("ctypesx").joinpath("py.typed")
    assert marker.is_file()
