"""Closed, layout-aware C integer enums and bit flags.

Unlike :class:`enum.IntEnum`, a ctypesx enum carries an explicit C integer
storage type.  There is intentionally no implicit 32-bit default.  Users may
either provide ``underlying=...`` as a class keyword or inherit one of the
precisely typed convenience bases such as :class:`U8Enum`.
"""

from __future__ import annotations

from enum import KEEP, Enum, EnumDict, EnumType, FlagBoundary, IntEnum, IntFlag
from operator import index
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Generic,
    Self,
    SupportsIndex,
    TypeVar,
    cast,
)

from .scalar import (
    CInt,
    CInteger,
    CIntPtr,
    CLong,
    CLongLong,
    CSChar,
    CShort,
    CSize,
    CSSize,
    CUChar,
    CUInt,
    CUIntPtr,
    CULong,
    CULongLong,
    CUShort,
    S8,
    S16,
    S32,
    S64,
    U8,
    U16,
    U32,
    U64,
)


_EnumT = TypeVar("_EnumT", bound=Enum)
_IntegerT = TypeVar("_IntegerT", bound=CInteger)
_MISSING = object()


def _bounded_flag_invert(self: CFlag) -> CFlag:
    """Invert only bits declared by a semantic CFlag class."""

    flag_mask = cast(int, getattr(type(self), "_flag_mask_"))
    return type(self)(flag_mask & ~int(self))


class _CEnumType(EnumType):
    """Resolve and freeze the C integer representation of enum classes."""

    def __new__(
        metacls,
        cls: str,
        bases: tuple[type, ...],
        classdict: EnumDict,
        *,
        underlying: type[CInteger] | None = None,
        boundary: FlagBoundary | None = None,
        _simple: bool = False,
        **kwds: Any,
    ) -> _CEnumType:
        root = classdict.get("__ctypesx_root__", False) is True
        inherited = {
            inherited_underlying
            for base in bases
            if (
                inherited_underlying := getattr(
                    base,
                    "__ctypesx_underlying__",
                    None,
                )
            )
            is not None
        }

        if len(inherited) > 1:
            raise TypeError(f"{cls} inherits conflicting C enum representations")

        inherited_underlying = next(iter(inherited), None)
        if underlying is None:
            resolved = inherited_underlying
        else:
            underlying_object = cast(object, underlying)
            if not isinstance(underlying_object, type) or not issubclass(
                underlying_object,
                CInteger,
            ):
                raise TypeError("underlying must be a CInteger type")
            if (
                inherited_underlying is not None
                and underlying is not inherited_underlying
            ):
                raise TypeError(
                    f"{cls} cannot change inherited enum representation from "
                    f"{inherited_underlying.__name__} to {underlying.__name__}"
                )
            resolved = underlying_object

        if not root and resolved is None:
            raise TypeError(
                f"{cls} must declare underlying=<CInteger type> or inherit a "
                "fixed-underlying enum base"
            )

        if resolved is not None:
            classdict["__ctypesx_underlying__"] = resolved
            classdict["__ctypesx_ctype__"] = resolved.__ctypesx_ctype__

        is_flag = bool(classdict.get("__ctypesx_flag_root__", False)) or any(
            issubclass(base, IntFlag) for base in bases
        )
        if is_flag and boundary is not None and boundary is not KEEP:
            raise TypeError("CFlag requires boundary=enum.KEEP")

        enum_type = cast(
            _CEnumType,
            super().__new__(
                metacls,
                cls,
                bases,
                classdict,
                boundary=boundary,
                _simple=_simple,
                **kwds,
            ),
        )
        if is_flag:
            type.__setattr__(enum_type, "__invert__", _bounded_flag_invert)
        return enum_type

    def __call__(  # pyright: ignore[reportIncompatibleMethodOverride]
        cls: type[_EnumT],  # pyright: ignore[reportGeneralTypeIssues]
        value: SupportsIndex,
        *args: object,
        **kwargs: object,
    ) -> _EnumT:
        if args or kwargs:
            raise TypeError("the functional Enum API is not supported")
        enum_class = cast(type[CEnum | CFlag], cls)
        if issubclass(enum_class, CFlag):
            pattern, _storage = enum_class._flag_components(value)  # pyright: ignore[reportPrivateUsage]
            return cast(_EnumT, super().__call__(pattern))
        underlying_type = enum_class._underlying_type()  # pyright: ignore[reportPrivateUsage]
        scalar = underlying_type(value)
        return cast(_EnumT, super().__call__(scalar))

    def __setattr__(cls, name: str, value: object, /) -> None:
        if name in {"__ctypesx_underlying__", "__ctypesx_ctype__"} and getattr(
            cls,
            name,
            _MISSING,
        ) is not _MISSING:
            raise TypeError(
                f"{cls.__name__}.{name} is immutable C representation metadata"
            )
        super().__setattr__(name, value)

    def __delattr__(cls, name: str, /) -> None:
        if name in {"__ctypesx_underlying__", "__ctypesx_ctype__"} and getattr(
            cls,
            name,
            _MISSING,
        ) is not _MISSING:
            raise TypeError(
                f"{cls.__name__}.{name} is immutable C representation metadata"
            )
        super().__delattr__(name)


class CEnum(IntEnum, metaclass=_CEnumType):
    """Closed C integer enum with an explicitly selected representation."""

    __ctypesx_root__ = True
    __ctypesx_underlying__: ClassVar[type[CInteger]]
    __ctypesx_ctype__: ClassVar[type[object]]

    def __init_subclass__(
        cls,
        *,
        underlying: type[CInteger] | None = None,
        **kwargs: Any,
    ) -> None:
        # _CEnumType consumes ``underlying`` before type.__new__ invokes this
        # hook.  Keeping it in the signature lets static checkers validate the
        # declarative class keyword.
        del underlying
        super().__init_subclass__(**kwargs)

    def __new__(cls, value: SupportsIndex, /) -> Self:
        scalar = cls._underlying_type()(value)
        member = int.__new__(cls, int(scalar))
        object.__setattr__(member, "_value_", scalar)
        return member

    @classmethod
    def _underlying_type(cls) -> type[CInteger]:
        try:
            return cls.__ctypesx_underlying__
        except AttributeError:
            raise TypeError(f"{cls.__name__} has no C integer representation") from None

    @property
    def value(self) -> CInteger:
        return cast(CInteger, object.__getattribute__(self, "_value_"))

    @classmethod
    def _missing_(cls, value: object) -> Self | None:
        # Preserve Enum's ValueError for an unknown but representable member,
        # while invalid C scalar values retain TypeError/OverflowError.
        cls._underlying_type()(cast(SupportsIndex, value))
        return None

    @classmethod
    def _coerce(cls, value: SupportsIndex, /) -> Self:
        return cls(value)

    @classmethod
    def _to_ctypes_value(cls, value: SupportsIndex, /) -> int:
        return int(cls._coerce(value))

    if TYPE_CHECKING:

        def __get__(
            self,
            instance: object | None,
            owner: type[object] | None = None,
            /,
        ) -> Self: ...

        def __set__(
            self,
            instance: object,
            value: SupportsIndex,
            /,
        ) -> None: ...


class CFlag(IntFlag, metaclass=_CEnumType, boundary=KEEP):
    """C integer bitmask whose range is bounded by its storage width.

    A signed C storage type does not make the logical bit mask negative.
    Public ``int(flag)`` values use the complete unsigned bit pattern, while
    ``flag.value`` retains the exact signed or unsigned C scalar that will be
    stored.  Consequently an ``S8Flag`` can naturally define ``HIGH = 0x80``
    and exposes ``HIGH.value == S8(-128)``.
    """

    __ctypesx_root__ = True
    __ctypesx_flag_root__ = True
    __ctypesx_underlying__: ClassVar[type[CInteger]]
    __ctypesx_ctype__: ClassVar[type[object]]

    def __init_subclass__(
        cls,
        *,
        underlying: type[CInteger] | None = None,
        **kwargs: Any,
    ) -> None:
        del underlying
        super().__init_subclass__(**kwargs)

    def __new__(cls, value: SupportsIndex, /) -> Self:
        pattern, storage = cls._flag_components(value)
        member = int.__new__(cls, pattern)
        object.__setattr__(member, "_value_", pattern)
        object.__setattr__(member, "_ctypesx_storage_value_", storage)
        return member

    @classmethod
    def _underlying_type(cls) -> type[CInteger]:
        try:
            return cls.__ctypesx_underlying__
        except AttributeError:
            raise TypeError(f"{cls.__name__} has no C integer representation") from None

    @classmethod
    def _flag_components(
        cls,
        value: SupportsIndex,
        /,
    ) -> tuple[int, CInteger]:
        if isinstance(value, bool):
            raise TypeError("bool is not a C flag value")
        try:
            number = index(value)
        except TypeError:
            raise TypeError(
                f"expected an integer, got {type(value).__name__}"
            ) from None

        underlying = cls._underlying_type()
        if not underlying.SIGNED:
            storage = underlying(number)
            return int(storage), storage

        mask = (1 << underlying.BITS) - 1
        if number < 0:
            storage = underlying(number)
            return int(storage) & mask, storage
        if number > mask:
            raise OverflowError(
                f"{number} is outside {cls.__name__} bit-pattern range "
                f"[0, {mask}]"
            )
        storage = underlying.from_bits(number)
        return number, storage

    @property
    def value(self) -> CInteger:
        return cast(
            CInteger,
            object.__getattribute__(self, "_ctypesx_storage_value_"),
        )

    @classmethod
    def _missing_(cls, value: object) -> Self | None:
        pattern, storage = cls._flag_components(
            cast(SupportsIndex, value)
        )
        member = super()._missing_(pattern)
        if member is not None:
            object.__setattr__(
                member,
                "_ctypesx_storage_value_",
                storage,
            )
        return member

    @classmethod
    def _coerce(cls, value: SupportsIndex, /) -> Self:
        return cls(value)

    @classmethod
    def _to_ctypes_value(cls, value: SupportsIndex, /) -> int:
        return int(cls._coerce(value).value)

    if TYPE_CHECKING:

        def __get__(
            self,
            instance: object | None,
            owner: type[object] | None = None,
            /,
        ) -> Self: ...

        def __set__(
            self,
            instance: object,
            value: SupportsIndex,
            /,
        ) -> None: ...


class _TypedIntegerValue(Generic[_IntegerT]):
    """Give fixed-underlying convenience bases an exact ``value`` type."""

    @property
    def value(self) -> _IntegerT:
        storage = getattr(self, "_ctypesx_storage_value_", _MISSING)
        if storage is not _MISSING:
            return cast(_IntegerT, storage)
        return cast(_IntegerT, object.__getattribute__(self, "_value_"))


class S8Enum(_TypedIntegerValue[S8], CEnum, underlying=S8):
    """Base for closed enums stored as signed 8-bit integers."""


class U8Enum(_TypedIntegerValue[U8], CEnum, underlying=U8):
    """Base for closed enums stored as unsigned 8-bit integers."""


class S16Enum(_TypedIntegerValue[S16], CEnum, underlying=S16):
    """Base for closed enums stored as signed 16-bit integers."""


class U16Enum(_TypedIntegerValue[U16], CEnum, underlying=U16):
    """Base for closed enums stored as unsigned 16-bit integers."""


class S32Enum(_TypedIntegerValue[S32], CEnum, underlying=S32):
    """Base for closed enums stored as signed 32-bit integers."""


class U32Enum(_TypedIntegerValue[U32], CEnum, underlying=U32):
    """Base for closed enums stored as unsigned 32-bit integers."""


class S64Enum(_TypedIntegerValue[S64], CEnum, underlying=S64):
    """Base for closed enums stored as signed 64-bit integers."""


class U64Enum(_TypedIntegerValue[U64], CEnum, underlying=U64):
    """Base for closed enums stored as unsigned 64-bit integers."""


class CIntEnum(_TypedIntegerValue[CInt], CEnum, underlying=CInt):
    """Base for closed enums stored as native C ``int`` values."""


class CSCharEnum(_TypedIntegerValue[CSChar], CEnum, underlying=CSChar):
    """Base for closed enums stored as native C ``signed char`` values."""


class CUCharEnum(_TypedIntegerValue[CUChar], CEnum, underlying=CUChar):
    """Base for closed enums stored as native C ``unsigned char`` values."""


class CShortEnum(_TypedIntegerValue[CShort], CEnum, underlying=CShort):
    """Base for closed enums stored as native C ``short`` values."""


class CUShortEnum(_TypedIntegerValue[CUShort], CEnum, underlying=CUShort):
    """Base for closed enums stored as native C ``unsigned short`` values."""


class CUIntEnum(_TypedIntegerValue[CUInt], CEnum, underlying=CUInt):
    """Base for closed enums stored as native C ``unsigned int`` values."""


class CLongEnum(_TypedIntegerValue[CLong], CEnum, underlying=CLong):
    """Base for closed enums stored as native C ``long`` values."""


class CULongEnum(_TypedIntegerValue[CULong], CEnum, underlying=CULong):
    """Base for closed enums stored as native C ``unsigned long`` values."""


class CLongLongEnum(
    _TypedIntegerValue[CLongLong],
    CEnum,
    underlying=CLongLong,
):
    """Base for closed enums stored as native C ``long long`` values."""


class CULongLongEnum(
    _TypedIntegerValue[CULongLong],
    CEnum,
    underlying=CULongLong,
):
    """Base for closed enums stored as native C ``unsigned long long`` values."""


class CSizeEnum(_TypedIntegerValue[CSize], CEnum, underlying=CSize):
    """Base for closed enums stored as native C ``size_t`` values."""


class CSSizeEnum(_TypedIntegerValue[CSSize], CEnum, underlying=CSSize):
    """Base for closed enums stored as native C ``ssize_t`` values."""


class CIntPtrEnum(
    _TypedIntegerValue[CIntPtr],
    CEnum,
    underlying=CIntPtr,
):
    """Base for closed enums stored as native C ``intptr_t`` values."""


class CUIntPtrEnum(
    _TypedIntegerValue[CUIntPtr],
    CEnum,
    underlying=CUIntPtr,
):
    """Base for closed enums stored as native C ``uintptr_t`` values."""


class S8Flag(_TypedIntegerValue[S8], CFlag, underlying=S8):
    """Base for bit flags stored as signed 8-bit integers."""


class U8Flag(_TypedIntegerValue[U8], CFlag, underlying=U8):
    """Base for bit flags stored as unsigned 8-bit integers."""


class S16Flag(_TypedIntegerValue[S16], CFlag, underlying=S16):
    """Base for bit flags stored as signed 16-bit integers."""


class U16Flag(_TypedIntegerValue[U16], CFlag, underlying=U16):
    """Base for bit flags stored as unsigned 16-bit integers."""


class S32Flag(_TypedIntegerValue[S32], CFlag, underlying=S32):
    """Base for bit flags stored as signed 32-bit integers."""


class U32Flag(_TypedIntegerValue[U32], CFlag, underlying=U32):
    """Base for bit flags stored as unsigned 32-bit integers."""


class S64Flag(_TypedIntegerValue[S64], CFlag, underlying=S64):
    """Base for bit flags stored as signed 64-bit integers."""


class U64Flag(_TypedIntegerValue[U64], CFlag, underlying=U64):
    """Base for bit flags stored as unsigned 64-bit integers."""


class CIntFlag(_TypedIntegerValue[CInt], CFlag, underlying=CInt):
    """Base for bit flags stored as native C ``int`` values."""


class CSCharFlag(_TypedIntegerValue[CSChar], CFlag, underlying=CSChar):
    """Base for bit flags stored as native C ``signed char`` values."""


class CUCharFlag(_TypedIntegerValue[CUChar], CFlag, underlying=CUChar):
    """Base for bit flags stored as native C ``unsigned char`` values."""


class CShortFlag(_TypedIntegerValue[CShort], CFlag, underlying=CShort):
    """Base for bit flags stored as native C ``short`` values."""


class CUShortFlag(_TypedIntegerValue[CUShort], CFlag, underlying=CUShort):
    """Base for bit flags stored as native C ``unsigned short`` values."""


class CUIntFlag(_TypedIntegerValue[CUInt], CFlag, underlying=CUInt):
    """Base for bit flags stored as native C ``unsigned int`` values."""


class CLongFlag(_TypedIntegerValue[CLong], CFlag, underlying=CLong):
    """Base for bit flags stored as native C ``long`` values."""


class CULongFlag(_TypedIntegerValue[CULong], CFlag, underlying=CULong):
    """Base for bit flags stored as native C ``unsigned long`` values."""


class CLongLongFlag(
    _TypedIntegerValue[CLongLong],
    CFlag,
    underlying=CLongLong,
):
    """Base for bit flags stored as native C ``long long`` values."""


class CULongLongFlag(
    _TypedIntegerValue[CULongLong],
    CFlag,
    underlying=CULongLong,
):
    """Base for bit flags stored as native C ``unsigned long long`` values."""


class CSizeFlag(_TypedIntegerValue[CSize], CFlag, underlying=CSize):
    """Base for bit flags stored as native C ``size_t`` values."""


class CSSizeFlag(_TypedIntegerValue[CSSize], CFlag, underlying=CSSize):
    """Base for bit flags stored as native C ``ssize_t`` values."""


class CIntPtrFlag(
    _TypedIntegerValue[CIntPtr],
    CFlag,
    underlying=CIntPtr,
):
    """Base for bit flags stored as native C ``intptr_t`` values."""


class CUIntPtrFlag(
    _TypedIntegerValue[CUIntPtr],
    CFlag,
    underlying=CUIntPtr,
):
    """Base for bit flags stored as native C ``uintptr_t`` values."""
