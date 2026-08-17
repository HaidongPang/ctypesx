"""Annotation-driven, checked ctypes structures and unions."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import annotationlib
import ctypes
import operator
import sys
from collections.abc import Buffer, Mapping, Sequence
from dataclasses import dataclass, field as dataclass_field
from types import MappingProxyType
from typing import (
    Annotated,
    Any,
    ClassVar,
    Generic,
    Self,
    TYPE_CHECKING,
    TypeAliasType,
    TypeVar,
    cast,
    dataclass_transform,
    get_args,
    get_origin,
)

from .array import Array, FamArray
from .field import Bits, Length, _FieldMarker

_ValueT = TypeVar("_ValueT")
_RecordT = TypeVar("_RecordT", bound="CStruct | CUnion")


@dataclass(frozen=True, slots=True)
class _TypeSpec:
    kind: str
    python_type: Any
    ctype: type[Any]
    element: _TypeSpec | None = None
    length: int | None = None
    dynamic: bool = False


@dataclass(frozen=True, slots=True)
class _FieldPlan:
    name: str
    spec: _TypeSpec
    bit_width: int | None = None

    def as_ctypes_field(self) -> tuple[Any, ...]:
        if self.bit_width is None:
            return self.name, self.spec.ctype
        return self.name, self.spec.ctype, self.bit_width


@dataclass(frozen=True, slots=True)
class FieldInfo(Generic[_ValueT]):
    """Immutable physical layout information for one declared field."""

    name: str
    python_type: Any
    ctype: type[Any]
    offset: int
    size: int
    bit_width: int | None
    bit_offset: int | None
    flexible: bool


@dataclass(frozen=True, slots=True)
class _TailInfo:
    offset: int
    element_size: int


@dataclass(frozen=True, slots=True)
class _RecordLayout:
    union: bool
    plans: tuple[_FieldPlan, ...]
    fields: MappingProxyType[str, FieldInfo[Any]]
    tails: tuple[_TailInfo, ...]

    @property
    def dynamic(self) -> bool:
        return bool(self.tails)


@dataclass(frozen=True, slots=True)
class _OwnerEntry:
    owner: object
    committed: bytes
    start: int
    end: int
    value_type: object


@dataclass(frozen=True, slots=True)
class _RelativeOwner:
    offset: int
    size: int
    value_type: object
    owner: object


@dataclass(frozen=True, slots=True)
class _StagedValue:
    raw: Any
    owners: tuple[_RelativeOwner, ...] = ()


@dataclass(slots=True)
class _RecordState:
    extent: int
    borrowed: bool = False
    backing: object | None = None
    backing_offset: int = 0
    follows_backing_extent: bool = False
    pins: int = 0
    owners: dict[tuple[int, object], _OwnerEntry] = dataclass_field(
        default_factory=lambda: dict[tuple[int, object], _OwnerEntry]()
    )


_PENDING: dict[type[Any], tuple[_FieldPlan, ...]] = {}
_LAYOUTS: dict[type[Any], _RecordLayout] = {}
_cstruct_state_slot: Any | None = None
_cunion_state_slot: Any | None = None


_RESERVED_FIELD_NAMES = frozenset(
    {
        "_align_",
        "_anonymous_",
        "_fields_",
        "_layout_",
        "_pack_",
        "__slots__",
    }
)


def _substitute_alias_parameters(
    annotation: Any,
    replacements: Mapping[object, Any],
) -> Any:
    """Substitute type parameters while expanding a generic type alias."""

    if isinstance(annotation, TypeVar):
        return replacements.get(annotation, annotation)
    if isinstance(annotation, list):
        return [
            _substitute_alias_parameters(item, replacements)
            for item in cast(list[Any], annotation)
        ]
    if isinstance(annotation, tuple):
        return tuple(
            _substitute_alias_parameters(item, replacements)
            for item in cast(tuple[Any, ...], annotation)
        )

    arguments = get_args(annotation)
    if not arguments:
        return annotation
    converted = tuple(
        _substitute_alias_parameters(item, replacements)
        for item in arguments
    )
    copy_with = getattr(annotation, "copy_with", None)
    if copy_with is not None:
        return copy_with(converted)

    origin = get_origin(annotation)
    if origin is Annotated:
        return Annotated[converted[0], *converted[1:]]
    if origin is None:
        return annotation
    key: Any = converted[0] if len(converted) == 1 else converted
    try:
        return origin[key]
    except TypeError:
        # Some typing constructs contain values rather than replaceable type
        # parameters.  Returning the original object is safe here: an
        # unresolved parameter will be rejected by the field compiler.
        return annotation


def _resolve_type_alias(
    annotation: Any,
    seen: frozenset[int] = frozenset(),
) -> Any:
    """Expand PEP 695 aliases before interpreting a field annotation."""

    if isinstance(annotation, TypeAliasType):
        identity = id(annotation)
        if identity in seen:
            raise TypeError(f"recursive type alias {annotation!r} is unsupported")
        return _resolve_type_alias(
            annotation.__value__,
            seen | {identity},
        )

    origin = get_origin(annotation)
    if not isinstance(origin, TypeAliasType):
        return annotation
    identity = id(origin)
    if identity in seen:
        raise TypeError(f"recursive type alias {origin!r} is unsupported")
    parameters = origin.__type_params__
    arguments = get_args(annotation)
    if len(parameters) != len(arguments):
        raise TypeError(f"type alias {origin!r} has unresolved parameters")
    expanded = _substitute_alias_parameters(
        origin.__value__,
        dict(zip(parameters, arguments, strict=True)),
    )
    return _resolve_type_alias(expanded, seen | {identity})


def _annotations_from_namespace(namespace: dict[str, Any]) -> dict[str, Any]:
    annotate = annotationlib.get_annotate_from_class_namespace(namespace)
    if annotate is not None:
        return annotationlib.call_annotate_function(
            annotate,
            annotationlib.Format.VALUE,
        )

    raw = cast(dict[str, Any], namespace.get("__annotations__", {}))
    module_name = cast(str, namespace.get("__module__", ""))
    module = sys.modules.get(module_name)
    globalns = {} if module is None else vars(module)
    localns = dict(namespace)
    return {
        name: eval(value, globalns, localns) if isinstance(value, str) else value
        for name, value in raw.items()
    }


def _ctype_for(value_type: Any) -> type[Any]:
    ctype = getattr(value_type, "__ctypesx_ctype__", None)
    if isinstance(ctype, type):
        try:
            ctypes.sizeof(ctype)
        except TypeError:
            pass
        else:
            return ctype
    if isinstance(value_type, type) and issubclass(
        value_type,
        (ctypes.Structure, ctypes.Union),
    ):
        if value_type not in _LAYOUTS:
            raise TypeError(
                f"{value_type.__name__} must derive from CStruct or CUnion"
            )
        return value_type
    raise TypeError(f"unsupported C field type {value_type!r}")


def _compile_value(annotation: Any) -> _TypeSpec:
    annotation = _resolve_type_alias(annotation)
    if not isinstance(annotation, type):
        raise TypeError(f"unsupported C field annotation {annotation!r}")
    ctype = _ctype_for(annotation)
    if issubclass(ctype, (ctypes.Structure, ctypes.Union)):
        layout = _LAYOUTS[ctype]
        return _TypeSpec(
            "record",
            annotation,
            ctype,
            dynamic=layout.dynamic,
        )
    return _TypeSpec("value", annotation, ctype)


def _compile_array(annotation: Any, dimensions: tuple[int, ...]) -> _TypeSpec:
    if get_origin(annotation) is not Array:
        raise TypeError("Length(...) requires an Array[T] annotation")
    arguments = get_args(annotation)
    if len(arguments) != 1:
        raise TypeError("Array must have exactly one element type")
    if not dimensions:
        raise TypeError("an Array annotation needs a matching dimension")

    element_annotation = arguments[0]
    if get_origin(element_annotation) is Array:
        element = _compile_array(element_annotation, dimensions[1:])
    else:
        if len(dimensions) != 1:
            raise TypeError(
                "Length dimensions must match nested Array annotations"
            )
        element = _compile_value(element_annotation)

    if element.dynamic:
        raise TypeError("a dynamic-tail record cannot be an array element")
    if ctypes.sizeof(element.ctype) == 0:
        raise TypeError("an array element cannot have size zero")
    length = dimensions[0]
    ctype = cast(type[Any], cast(Any, element.ctype) * length)
    return _TypeSpec("array", annotation, ctype, element, length)


def _unwrap_annotated(
    annotation: Any,
) -> tuple[Any, Bits | None, Length | None]:
    if get_origin(annotation) is not Annotated:
        return annotation, None, None
    value_type, *metadata = get_args(annotation)
    bits = [item for item in metadata if isinstance(item, Bits)]
    lengths = [item for item in metadata if isinstance(item, Length)]
    unknown = [
        item for item in metadata if not isinstance(item, (Bits, Length))
    ]
    if unknown:
        raise TypeError(f"unsupported C field metadata {unknown!r}")
    if len(bits) > 1:
        raise TypeError("a field cannot have multiple Bits metadata")
    if len(lengths) > 1:
        raise TypeError("a field cannot have multiple Length metadata")
    return (
        value_type,
        bits[0] if bits else None,
        lengths[0] if lengths else None,
    )


def _is_integer_ctype(ctype: type[Any]) -> bool:
    type_code = getattr(ctype, "_type_", None)
    return type_code in frozenset("?bBhHiIlLqQnN")


def _compile_field(name: str, annotation: Any) -> _FieldPlan:
    annotation = _resolve_type_alias(annotation)
    annotation, bits, length = _unwrap_annotated(annotation)
    annotation = _resolve_type_alias(annotation)
    origin = get_origin(annotation)

    if origin is Array:
        if bits is not None:
            raise TypeError("Bits cannot annotate an array")
        if length is None:
            raise TypeError("Array[T] requires Length(...) metadata")
        return _FieldPlan(name, _compile_array(annotation, length.dimensions))

    if origin is FamArray:
        if bits is not None:
            raise TypeError("Bits cannot annotate a flexible array")
        if length is not None:
            raise TypeError("FamArray[T] must not have Length metadata")
        arguments = get_args(annotation)
        if len(arguments) != 1:
            raise TypeError("FamArray must have exactly one element type")
        element = _compile_value(arguments[0])
        if element.dynamic:
            raise TypeError(
                "a dynamic-tail record cannot be a flexible-array element"
            )
        if ctypes.sizeof(element.ctype) == 0:
            raise TypeError("a flexible-array element cannot have size zero")
        ctype = cast(type[Any], cast(Any, element.ctype) * 0)
        return _FieldPlan(
            name,
            _TypeSpec("fam", annotation, ctype, element, 0, True),
        )

    if length is not None:
        raise TypeError("Length(...) can only annotate Array[T]")
    spec = _compile_value(annotation)
    if bits is None:
        return _FieldPlan(name, spec)
    if spec.kind != "value" or not _is_integer_ctype(spec.ctype):
        raise TypeError("Bits can only annotate an integer scalar")
    storage_width = ctypes.sizeof(spec.ctype) * 8
    if bits.width > storage_width:
        raise ValueError(
            f"{bits.width}-bit field does not fit in "
            f"{cast(type[Any], spec.python_type).__name__}"
        )
    return _FieldPlan(name, spec, bits.width)


def _prepare_namespace(
    metaclass: type[Any],
    name: str,
    bases: tuple[type[Any], ...],
    namespace: dict[str, Any],
    *,
    union: bool,
) -> tuple[_FieldPlan, ...] | None:
    if not any(isinstance(base, metaclass) for base in bases):
        return None

    concrete_bases = [base for base in bases if base in _LAYOUTS]
    if concrete_bases:
        raise TypeError(
            f"{name} cannot extend concrete C record "
            f"{concrete_bases[0].__name__}"
        )
    if "_fields_" in namespace:
        raise TypeError(f"{name} must declare fields with annotations")
    if "_anonymous_" in namespace:
        raise TypeError(f"{name} must use explicit nested union access")
    for layout_attribute in ("_pack_", "_align_", "_layout_"):
        if layout_attribute in namespace:
            raise TypeError(
                f"{name}: direct {layout_attribute} declarations are not "
                "supported"
            )

    annotations = _annotations_from_namespace(namespace)
    plans: list[_FieldPlan] = []
    for field_name, annotation in annotations.items():
        annotation = _resolve_type_alias(annotation)
        if get_origin(annotation) is ClassVar:
            continue
        if field_name in _RESERVED_FIELD_NAMES:
            raise TypeError(f"{name}.{field_name} is reserved")
        if field_name.startswith("__") and field_name.endswith("__"):
            raise TypeError(f"{name}.{field_name} is a reserved Python name")
        marker = namespace.get(field_name)
        if not isinstance(marker, _FieldMarker):
            raise TypeError(
                f"{name}.{field_name} must be declared with Field()"
            )
        namespace.pop(field_name)
        try:
            plans.append(_compile_field(field_name, annotation))
        except (TypeError, ValueError) as error:
            raise type(error)(f"{name}.{field_name}: {error}") from None

    carriers = [
        index
        for index, plan in enumerate(plans)
        if plan.spec.kind == "fam" or plan.spec.dynamic
    ]
    if not union and len(carriers) > 1:
        raise TypeError(
            f"{name} can contain at most one flexible or dynamic-tail field"
        )
    if not union and carriers and carriers[0] != len(plans) - 1:
        raise TypeError(
            f"{name}.{plans[carriers[0]].name}: a dynamic-tail field must "
            "be the final field"
        )
    if (
        not union
        and carriers
        and carriers[0] == 0
        and plans[0].spec.kind == "fam"
    ):
        raise TypeError(
            f"{name}.{plans[0].name}: a flexible-array member must follow "
            "at least one named field"
        )

    namespace.setdefault("__slots__", ())
    namespace["_fields_"] = [plan.as_ctypes_field() for plan in plans]
    return tuple(plans)


def _layout_for(record_type: type[Any]) -> _RecordLayout:
    try:
        return _LAYOUTS[record_type]
    except KeyError:
        raise TypeError(
            f"{record_type.__name__} is not a concrete C record"
        ) from None


def _state_slot(instance: object) -> Any:
    if isinstance(instance, CStruct):
        slot = _cstruct_state_slot
    elif isinstance(instance, CUnion):
        slot = _cunion_state_slot
    else:
        raise TypeError(f"{type(instance).__name__} is not a C record")
    if slot is None:
        raise RuntimeError("C record runtime state is not initialized")
    return slot


def _try_state(instance: object) -> _RecordState | None:
    try:
        return cast(
            _RecordState,
            _state_slot(instance).__get__(instance, type(instance)),
        )
    except AttributeError:
        return None


def _set_state(instance: object, state: _RecordState) -> None:
    _state_slot(instance).__set__(instance, state)


def _require_state(instance: object) -> _RecordState:
    state = _try_state(instance)
    if state is not None:
        if state.follows_backing_extent and isinstance(
            state.backing,
            (CStruct, CUnion),
        ):
            parent_state = _require_state(state.backing)
            state.extent = max(0, parent_state.extent - state.backing_offset)
        return state
    layout = _layout_for(type(instance))
    if layout.dynamic:
        raise BufferError(
            f"{type(instance).__name__} has an unknown dynamic-tail extent"
        )
    return _RecordState(
        ctypes.sizeof(cast(Any, type(instance))),
        borrowed=True,
    )


def _root_context(
    instance: object,
) -> tuple[object, _RecordState, int]:
    state = _require_state(instance)
    offset = 0
    current = instance
    seen: set[int] = set()
    while isinstance(state.backing, (CStruct, CUnion)):
        if id(current) in seen:
            raise RuntimeError("cyclic C record backing state")
        seen.add(id(current))
        offset += state.backing_offset
        current = state.backing
        state = _require_state(current)
    return current, state, offset


def _record_address(instance: object) -> int:
    root, _state, offset = _root_context(instance)
    return ctypes.addressof(cast(Any, root)) + offset


def _record_extent(  # pyright: ignore[reportUnusedFunction]
    instance: object,
) -> int:
    """Return the live byte extent of a record or nested record view."""

    return _require_state(instance).extent


def _native_metaclass(record_type: type[Any]) -> type[Any]:
    if issubclass(record_type, ctypes.Structure):
        return type(ctypes.Structure)
    if issubclass(record_type, ctypes.Union):
        return type(ctypes.Union)
    raise TypeError(f"{record_type.__name__} is not a ctypes record")


def _live_instance(instance: object) -> object:
    state = _try_state(instance)
    if state is None or not isinstance(state.backing, (CStruct, CUnion)):
        return instance
    record_type = type(instance)
    live = _native_metaclass(record_type).from_address(
        record_type,
        _record_address(instance),
    )
    _set_state(
        live,
        _RecordState(
            state.extent,
            borrowed=True,
            backing=state.backing,
            backing_offset=state.backing_offset,
            follows_backing_extent=state.follows_backing_extent,
        ),
    )
    return live


def _field_position(
    instance: object,
    offset: int,
    size: int,
) -> tuple[_RecordState, int, int]:
    _root, root_state, record_offset = _root_context(instance)
    start = record_offset + offset
    return root_state, start, start + size


def _field_fingerprint(instance: object, offset: int, size: int) -> bytes:
    if size == 0:
        return b""
    return ctypes.string_at(_record_address(instance) + offset, size)


def _drop_owner_range(instance: object, offset: int, size: int) -> None:
    root_state, start, end = _field_position(instance, offset, size)
    for key, entry in tuple(root_state.owners.items()):
        if entry.start < end and start < entry.end:
            del root_state.owners[key]


def _relative_owners_from_range(
    instance: object,
    offset: int,
    size: int,
) -> tuple[_RelativeOwner, ...]:
    root_state, start, end = _field_position(instance, offset, size)
    return tuple(
        _RelativeOwner(
            entry.start - start,
            entry.end - entry.start,
            entry.value_type,
            entry.owner,
        )
        for entry in root_state.owners.values()
        if start <= entry.start and entry.end <= end
    )


def _commit_relative_owners(
    instance: object,
    offset: int,
    size: int,
    owners: tuple[_RelativeOwner, ...],
) -> None:
    _drop_owner_range(instance, offset, size)
    root_state, start, _end = _field_position(instance, offset, size)
    address = _record_address(instance) + offset
    for relative in owners:
        if relative.offset < 0 or relative.offset + relative.size > size:
            raise RuntimeError("array owner sidecar exceeds its storage range")
        entry_start = start + relative.offset
        entry_end = entry_start + relative.size
        root_state.owners[(entry_start, relative.value_type)] = _OwnerEntry(
            relative.owner,
            ctypes.string_at(address + relative.offset, relative.size),
            entry_start,
            entry_end,
            relative.value_type,
        )


def _owner_for_value(
    instance: object,
    offset: int,
    size: int,
    value_type: object,
) -> object | None:
    root_state, start, _end = _field_position(instance, offset, size)
    key = (start, value_type)
    entry = root_state.owners.get(key)
    if entry is None:
        return None
    current = _field_fingerprint(instance, offset, size)
    if current == entry.committed:
        return entry.owner
    del root_state.owners[key]
    return None


def _copy_owner_range(
    destination: object,
    destination_offset: int,
    source: object,
    source_offset: int,
    size: int,
) -> None:
    destination_state, destination_start, destination_end = _field_position(
        destination,
        destination_offset,
        size,
    )
    source_state, source_start, source_end = _field_position(
        source,
        source_offset,
        size,
    )
    source_entries = [
        entry
        for entry in source_state.owners.values()
        if source_start <= entry.start and entry.end <= source_end
    ]
    for key, entry in tuple(destination_state.owners.items()):
        if entry.start < destination_end and destination_start < entry.end:
            del destination_state.owners[key]
    for entry in source_entries:
        relative_start = entry.start - source_start
        copied_start = destination_start + relative_start
        copied_end = copied_start + (entry.end - entry.start)
        destination_state.owners[(copied_start, entry.value_type)] = _OwnerEntry(
            entry.owner,
            entry.committed,
            copied_start,
            copied_end,
            entry.value_type,
        )


def _resize_extent(instance: object, new_extent: int) -> None:
    if new_extent < ctypes.sizeof(cast(Any, type(instance))):
        raise ValueError("a C record cannot be smaller than its static layout")
    state = _require_state(instance)
    old_extent = state.extent
    if new_extent == old_extent:
        return
    if isinstance(state.backing, (CStruct, CUnion)):
        _resize_extent(state.backing, state.backing_offset + new_extent)
        state.extent = new_extent
        return

    root, root_state, _offset = _root_context(instance)
    if root is not instance:
        raise RuntimeError("invalid dynamic-tail ownership chain")
    if root_state.borrowed:
        raise BufferError("borrowed C record storage cannot be resized")
    if root_state.pins:
        raise BufferError("pinned C record storage cannot be resized")
    ctypes.resize(cast(Any, root), new_extent)
    if new_extent > old_extent:
        ctypes.memset(
            ctypes.addressof(cast(Any, root)) + old_extent,
            0,
            new_extent - old_extent,
        )
    else:
        for key, entry in tuple(root_state.owners.items()):
            if entry.end > new_extent:
                del root_state.owners[key]
    root_state.extent = new_extent


def _pin_record(
    instance: CStruct | CUnion,
) -> None:
    _root, state, _offset = _root_context(instance)
    state.pins += 1


def _unpin_record(
    instance: CStruct | CUnion,
) -> None:
    _root, state, _offset = _root_context(instance)
    if state.pins <= 0:
        raise RuntimeError("unbalanced C record pin release")
    state.pins -= 1


def _read_value(spec: _TypeSpec, raw_value: Any, owner: object | None) -> Any:
    value_type = spec.python_type
    from_ctypes = getattr(value_type, "_from_ctypes_value", None)
    if callable(from_ctypes):
        if hasattr(value_type, "_to_ctypes_assignment"):
            return from_ctypes(raw_value, owner)
        return from_ctypes(raw_value)
    if raw_value is None:
        raw_value = 0
    return value_type(raw_value)


def _coerce_value(spec: _TypeSpec, value: object) -> tuple[Any, object | None]:
    value_type = spec.python_type
    assignment = getattr(value_type, "_to_ctypes_assignment", None)
    if callable(assignment):
        result: object = assignment(value)
        if not isinstance(result, tuple):
            raise TypeError(
                f"{value_type.__name__}._to_ctypes_assignment() must "
                "return (raw, owner)"
            )
        typed_result = cast(tuple[object, ...], result)
        if len(typed_result) != 2:
            raise TypeError(
                f"{value_type.__name__}._to_ctypes_assignment() must "
                "return (raw, owner)"
            )
        raw, owner = cast(tuple[Any, object | None], typed_result)
        return raw, owner
    to_ctypes = getattr(value_type, "_to_ctypes_value", None)
    if callable(to_ctypes):
        return to_ctypes(value), None
    coerce = getattr(value_type, "_coerce", None)
    if callable(coerce):
        converted = coerce(value)
        return getattr(converted, "value", converted), None
    if isinstance(value, value_type):
        return value, None
    raise TypeError(
        f"expected {value_type.__name__}, got {type(value).__name__}"
    )


def _bitfield_bounds(ctype: type[Any], width: int) -> tuple[int, int]:
    try:
        signed = operator.index(ctype(-1).value) == -1
    except (AttributeError, TypeError, ValueError):
        signed = False
    if signed:
        limit = 1 << (width - 1)
        return -limit, limit - 1
    return 0, (1 << width) - 1


def _stage_element(spec: _TypeSpec, value: object) -> _StagedValue:
    if spec.kind == "value":
        raw, owner = _coerce_value(spec, value)
        owners: tuple[_RelativeOwner, ...] = ()
        if owner is not None:
            owners = (
                _RelativeOwner(
                    0,
                    ctypes.sizeof(spec.ctype),
                    spec.python_type,
                    owner,
                ),
            )
        return _StagedValue(raw, owners)
    if spec.kind == "record":
        if isinstance(value, spec.ctype):
            if spec.dynamic:
                raise TypeError("dynamic-tail records cannot be array elements")
            size = ctypes.sizeof(spec.ctype)
            staged = spec.ctype()
            ctypes.memmove(
                ctypes.addressof(staged),
                _record_address(value),
                size,
            )
            return _StagedValue(
                staged,
                _relative_owners_from_range(value, 0, size),
            )
        if isinstance(value, Mapping):
            constructed = spec.ctype(**dict(cast(Mapping[str, object], value)))
            return _stage_element(spec, constructed)
        raise TypeError(
            f"expected {spec.ctype.__name__}, got {type(value).__name__}"
        )
    if spec.kind == "array":
        return _stage_array(spec, value)
    raise TypeError("a flexible array cannot be nested as an element")


def _stage_array(spec: _TypeSpec, value: object) -> _StagedValue:
    if spec.kind not in {"array", "fam"} or spec.element is None:
        raise TypeError("internal array specification is incomplete")
    try:
        values = list(cast(Sequence[object], value))
    except TypeError:
        raise TypeError("a C array field requires an iterable") from None
    if spec.kind == "array" and len(values) != spec.length:
        raise ValueError(
            f"fixed C array requires exactly {spec.length} elements"
        )
    element_size = ctypes.sizeof(spec.element.ctype)
    if len(values) > sys.maxsize // element_size:
        raise OverflowError("C array allocation size overflows")
    array_type = cast(type[Any], cast(Any, spec.element.ctype) * len(values))
    staged = cast(ctypes.Array[Any], array_type())
    converted = [_stage_element(spec.element, item) for item in values]
    owners: list[_RelativeOwner] = []
    for index, item in enumerate(converted):
        staged[index] = item.raw
        element_offset = index * element_size
        owners.extend(
            _RelativeOwner(
                element_offset + entry.offset,
                entry.size,
                entry.value_type,
                entry.owner,
            )
            for entry in item.owners
        )
    return _StagedValue(staged, tuple(owners))


def _array_read(
    spec: _TypeSpec,
    instance: object,
    base_offset: int,
    provider: Any,
    raw: ctypes.Array[Any],
    index: int,
) -> Any:
    normalized = index if index >= 0 else len(raw) + index
    if not 0 <= normalized < len(raw):
        raise IndexError("C array index out of range")
    element_offset = base_offset + normalized * ctypes.sizeof(spec.ctype)
    if spec.kind == "value":
        owner = _owner_for_value(
            instance,
            element_offset,
            ctypes.sizeof(spec.ctype),
            spec.python_type,
        )
        return _read_value(spec, raw[normalized], owner)
    if spec.kind == "record":
        child = raw[normalized]
        _set_state(
            child,
            _RecordState(
                ctypes.sizeof(spec.ctype),
                borrowed=True,
                backing=instance,
                backing_offset=element_offset,
            ),
        )
        return child
    if spec.kind == "array" and spec.element is not None:
        child_spec = spec.element

        def child_provider() -> ctypes.Array[Any]:
            return cast(ctypes.Array[Any], provider()[normalized])

        def child_reader(
            child_raw: ctypes.Array[Any],
            child_index: int,
        ) -> Any:
            return _array_read(
                child_spec,
                instance,
                element_offset,
                child_provider,
                child_raw,
                child_index,
            )

        def child_coercer(value: Any) -> _StagedValue:
            return _stage_element(child_spec, value)

        def child_committer(index: int, staged: Any) -> None:
            _commit_array_element(
                instance,
                element_offset,
                child_spec,
                child_provider,
                index,
                cast(_StagedValue, staged),
            )

        return Array[Any](
            child_provider,
            child_reader,
            child_coercer,
            child_committer,
            lambda: _pin_record(cast(CStruct | CUnion, instance)),
            lambda: _unpin_record(cast(CStruct | CUnion, instance)),
        )
    raise TypeError("invalid C array element specification")


def _commit_array_element(
    instance: object,
    base_offset: int,
    element: _TypeSpec,
    provider: Any,
    index: int,
    staged: _StagedValue,
) -> None:
    raw = cast(ctypes.Array[Any], provider())
    normalized = index if index >= 0 else len(raw) + index
    if not 0 <= normalized < len(raw):
        raise IndexError("C array assignment index out of range")
    element_size = ctypes.sizeof(element.ctype)
    element_offset = base_offset + normalized * element_size
    raw[normalized] = staged.raw
    _commit_relative_owners(
        instance,
        element_offset,
        element_size,
        staged.owners,
    )


class _CheckedField(Generic[_ValueT]):
    __slots__ = (
        "_plan",
        "_raw",
        "bit_width",
        "ctype",
        "offset",
        "size",
    )

    def __init__(self, plan: _FieldPlan, raw: Any) -> None:
        self._plan = plan
        self._raw = raw
        self.ctype = plan.spec.ctype
        self.offset = cast(int, raw.byte_offset)
        self.size = cast(int, raw.byte_size)
        self.bit_width = plan.bit_width

    def _raw_value(self, instance: object) -> Any:
        live = _live_instance(instance)
        return self._raw.__get__(live, type(live))

    def _raw_array(self, instance: object) -> ctypes.Array[Any]:
        return cast(ctypes.Array[Any], self._raw_value(instance))

    def _fam_array(self, instance: object) -> ctypes.Array[Any]:
        spec = self._plan.spec
        element = cast(_TypeSpec, spec.element)
        state = _require_state(instance)
        available = state.extent - self.offset
        element_size = ctypes.sizeof(element.ctype)
        if available < 0 or available % element_size:
            raise BufferError(
                "flexible-array extent does not end on an element boundary"
            )
        array_type = cast(type[Any], cast(Any, element.ctype) * (
            available // element_size
        ))
        raw = cast(
            ctypes.Array[Any],
            array_type.from_address(_record_address(instance) + self.offset),
        )
        setattr(raw, "_ctypesx_owner", instance)
        return raw

    def _array_view(self, instance: object, *, fam: bool) -> Array[Any]:
        spec = self._plan.spec
        element = cast(_TypeSpec, spec.element)
        provider = (
            (lambda: self._fam_array(instance))
            if fam
            else (lambda: self._raw_array(instance))
        )
        def reader(raw: ctypes.Array[Any], index: int) -> Any:
            return _array_read(
                element,
                instance,
                self.offset,
                provider,
                raw,
                index,
            )

        def coercer(value: Any) -> _StagedValue:
            return _stage_element(element, value)

        def committer(index: int, staged: Any) -> None:
            _commit_array_element(
                instance,
                self.offset,
                element,
                provider,
                index,
                cast(_StagedValue, staged),
            )
        if fam:
            return FamArray(
                provider,
                reader,
                coercer,
                lambda values: self.__set__(instance, values),
                committer,
                lambda: _pin_record(cast(CStruct | CUnion, instance)),
                lambda: _unpin_record(cast(CStruct | CUnion, instance)),
            )
        return Array(
            provider,
            reader,
            coercer,
            committer,
            lambda: _pin_record(cast(CStruct | CUnion, instance)),
            lambda: _unpin_record(cast(CStruct | CUnion, instance)),
        )

    def __get__(
        self,
        instance: object | None,
        owner: type[Any] | None = None,
    ) -> Any:
        del owner
        if instance is None:
            return self
        spec = self._plan.spec
        if spec.kind == "array":
            return self._array_view(instance, fam=False)
        if spec.kind == "fam":
            return self._array_view(instance, fam=True)
        if spec.kind == "record":
            child = self._raw_value(instance)
            parent_state = _require_state(instance)
            _set_state(
                child,
                _RecordState(
                    (
                        max(0, parent_state.extent - self.offset)
                        if spec.dynamic
                        else ctypes.sizeof(spec.ctype)
                    ),
                    borrowed=True,
                    backing=instance,
                    backing_offset=self.offset,
                    follows_backing_extent=spec.dynamic,
                ),
            )
            return child

        raw_value = self._raw_value(instance)
        owner_value = _owner_for_value(
            instance,
            self.offset,
            self.size,
            spec.python_type,
        )
        return _read_value(spec, raw_value, owner_value)

    def _set_value(self, instance: object, value: object) -> None:
        spec = self._plan.spec
        raw_value, owner = _coerce_value(spec, value)
        if self.bit_width is not None:
            number = operator.index(raw_value)
            minimum, maximum = _bitfield_bounds(spec.ctype, self.bit_width)
            if not minimum <= number <= maximum:
                raise OverflowError(
                    f"{number} does not fit in this {self.bit_width}-bit field"
                )
            raw_value = number

        _drop_owner_range(instance, self.offset, self.size)
        live = _live_instance(instance)
        self._raw.__set__(live, raw_value)
        if owner is not None:
            root_state, start, end = _field_position(
                instance,
                self.offset,
                self.size,
            )
            root_state.owners[(start, spec.python_type)] = _OwnerEntry(
                owner,
                _field_fingerprint(instance, self.offset, self.size),
                start,
                end,
                spec.python_type,
            )

    def _set_record(self, instance: object, value: object) -> None:
        spec = self._plan.spec
        if isinstance(value, Mapping):
            value = spec.ctype(**dict(cast(Mapping[str, object], value)))
        if not isinstance(value, spec.ctype):
            raise TypeError(
                f"expected {spec.ctype.__name__}, got {type(value).__name__}"
            )
        source_state = _require_state(value)
        size = source_state.extent if spec.dynamic else ctypes.sizeof(spec.ctype)
        if spec.dynamic:
            _resize_extent(instance, self.offset + size)
        if size:
            ctypes.memmove(
                _record_address(instance) + self.offset,
                _record_address(value),
                size,
            )
        _copy_owner_range(instance, self.offset, value, 0, size)

    def _set_array(self, instance: object, value: object) -> None:
        spec = self._plan.spec
        staged = _stage_array(spec, value)
        raw = cast(ctypes.Array[Any], staged.raw)
        size = ctypes.sizeof(raw)
        if spec.kind == "fam":
            _resize_extent(instance, self.offset + size)
        if size:
            ctypes.memmove(
                _record_address(instance) + self.offset,
                ctypes.addressof(raw),
                size,
            )
        _commit_relative_owners(
            instance,
            self.offset,
            max(self.size, size),
            staged.owners,
        )

    def __set__(self, instance: object, value: object) -> None:
        kind = self._plan.spec.kind
        if kind == "value":
            self._set_value(instance, value)
        elif kind == "record":
            self._set_record(instance, value)
        else:
            self._set_array(instance, value)


def _install_fields(record_type: type[Any], *, union: bool) -> None:
    plans = _PENDING.pop(record_type, None)
    if plans is None:
        return
    fields: dict[str, FieldInfo[Any]] = {}
    tails: list[_TailInfo] = []
    for plan in plans:
        raw = record_type.__dict__[plan.name]
        descriptor = _CheckedField[Any](plan, raw)
        setattr(record_type, plan.name, descriptor)
        fields[plan.name] = FieldInfo(
            plan.name,
            plan.spec.python_type,
            plan.spec.ctype,
            descriptor.offset,
            descriptor.size,
            plan.bit_width,
            cast(int, raw.bit_offset) if raw.is_bitfield else None,
            plan.spec.kind == "fam",
        )
        if plan.spec.kind == "fam":
            element = cast(_TypeSpec, plan.spec.element)
            tails.append(
                _TailInfo(descriptor.offset, ctypes.sizeof(element.ctype))
            )
        elif plan.spec.kind == "record" and plan.spec.dynamic:
            for child_tail in _LAYOUTS[plan.spec.ctype].tails:
                tails.append(
                    _TailInfo(
                        descriptor.offset + child_tail.offset,
                        child_tail.element_size,
                    )
                )

    static_size = ctypes.sizeof(record_type)
    if any(tail.offset != static_size for tail in tails):
        raise TypeError(
            f"{record_type.__name__}: every dynamic tail must begin at "
            f"the static record size ({static_size} bytes)"
        )
    _LAYOUTS[record_type] = _RecordLayout(
        union,
        plans,
        MappingProxyType(fields),
        tuple(tails),
    )


@dataclass_transform(kw_only_default=True)
class _CStructMeta(type(ctypes.Structure)):
    def __new__(
        cls,
        name: str,
        bases: tuple[type[Any], ...],
        namespace: dict[str, Any],
        **kwargs: Any,
    ) -> _CStructMeta:
        plans = _prepare_namespace(
            cls,
            name,
            bases,
            namespace,
            union=False,
        )
        created = cast(
            _CStructMeta,
            super().__new__(cls, name, bases, namespace, **kwargs),
        )
        if plans is not None:
            _PENDING[created] = plans
        return created

    def __init__(
        cls,
        name: str,
        bases: tuple[type[Any], ...],
        namespace: dict[str, Any],
        **kwargs: Any,
    ) -> None:
        super().__init__(name, bases, namespace, **kwargs)
        _install_fields(cls, union=False)

    def __setattr__(cls, name: str, value: object, /) -> None:
        layout = _LAYOUTS.get(cls)
        if layout is not None and name in layout.fields:
            raise AttributeError(f"C field descriptor {name!r} is immutable")
        super().__setattr__(name, value)

    def __delattr__(cls, name: str, /) -> None:
        layout = _LAYOUTS.get(cls)
        if layout is not None and name in layout.fields:
            raise AttributeError(f"C field descriptor {name!r} is immutable")
        super().__delattr__(name)


@dataclass_transform(kw_only_default=True)
class _CUnionMeta(type(ctypes.Union)):
    def __new__(
        cls,
        name: str,
        bases: tuple[type[Any], ...],
        namespace: dict[str, Any],
        **kwargs: Any,
    ) -> _CUnionMeta:
        plans = _prepare_namespace(
            cls,
            name,
            bases,
            namespace,
            union=True,
        )
        created = cast(
            _CUnionMeta,
            super().__new__(cls, name, bases, namespace, **kwargs),
        )
        if plans is not None:
            _PENDING[created] = plans
        return created

    def __init__(
        cls,
        name: str,
        bases: tuple[type[Any], ...],
        namespace: dict[str, Any],
        **kwargs: Any,
    ) -> None:
        super().__init__(name, bases, namespace, **kwargs)
        _install_fields(cls, union=True)

    def __setattr__(cls, name: str, value: object, /) -> None:
        layout = _LAYOUTS.get(cls)
        if layout is not None and name in layout.fields:
            raise AttributeError(f"C field descriptor {name!r} is immutable")
        super().__setattr__(name, value)

    def __delattr__(cls, name: str, /) -> None:
        layout = _LAYOUTS.get(cls)
        if layout is not None and name in layout.fields:
            raise AttributeError(f"C field descriptor {name!r} is immutable")
        super().__delattr__(name)


def _initialize_record(instance: CStruct | CUnion, fields: Mapping[str, object]) -> None:
    layout = _layout_for(type(instance))
    unknown = [name for name in fields if name not in layout.fields]
    if unknown:
        raise TypeError(
            f"{type(instance).__name__} has no C field {unknown[0]!r}"
        )
    if layout.union and len(fields) > 1:
        raise TypeError("a C union constructor accepts at most one field")
    _set_state(instance, _RecordState(ctypes.sizeof(type(instance))))
    for plan in layout.plans:
        if plan.name in fields:
            setattr(instance, plan.name, fields[plan.name])


def _normalize_buffer(buffer: Buffer, offset: int, *, writable: bool) -> memoryview:
    if isinstance(offset, bool):
        raise TypeError("bool is not a buffer offset")
    start = operator.index(offset)
    if start < 0:
        raise ValueError("buffer offset cannot be negative")
    complete = memoryview(buffer).cast("B")
    if start > complete.nbytes:
        raise ValueError("buffer offset exceeds the available storage")
    span = complete[start:]
    if writable and span.readonly:
        raise TypeError("from_buffer() requires writable storage")
    return span


def _validate_extent(record_type: type[Any], extent: int) -> None:
    layout = _layout_for(record_type)
    static_size = ctypes.sizeof(record_type)
    if extent < static_size:
        raise ValueError(f"buffer has {extent} bytes, {static_size} required")
    if not layout.dynamic:
        if extent != static_size:
            raise ValueError(
                f"buffer has {extent} bytes, expected exactly {static_size}"
            )
        return
    if not any(
        extent >= tail.offset
        and (extent - tail.offset) % tail.element_size == 0
        for tail in layout.tails
    ):
        raise ValueError(
            f"buffer size {extent} does not end on a flexible-array "
            f"element boundary for {record_type.__name__}"
        )


def _from_buffer(
    record_type: type[_RecordT],
    buffer: Buffer,
    offset: int,
) -> _RecordT:
    span = _normalize_buffer(buffer, offset, writable=True)
    _validate_extent(record_type, span.nbytes)
    instance = cast(
        _RecordT,
        _native_metaclass(record_type).from_buffer(record_type, span, 0),
    )
    _set_state(
        instance,
        _RecordState(span.nbytes, borrowed=True, backing=span),
    )
    return instance


def _from_buffer_copy(
    record_type: type[_RecordT],
    buffer: Buffer,
    offset: int,
) -> _RecordT:
    span = _normalize_buffer(buffer, offset, writable=False)
    _validate_extent(record_type, span.nbytes)
    instance = record_type()
    _resize_extent(instance, span.nbytes)
    if span.nbytes:
        ctypes.memmove(
            ctypes.addressof(instance),
            bytes(span),
            span.nbytes,
        )
    return instance


def _from_address(record_type: type[_RecordT], address: int) -> _RecordT:
    layout = _layout_for(record_type)
    if layout.dynamic:
        raise TypeError(
            f"{record_type.__name__}.from_address() cannot infer a "
            "flexible-array extent"
        )
    if isinstance(address, bool):
        raise TypeError("record address must be an integer address, not bool")
    try:
        checked_address = operator.index(address)
    except TypeError:
        raise TypeError("record address must be an integer address") from None
    maximum = (1 << (ctypes.sizeof(ctypes.c_void_p) * 8)) - 1
    if not 0 <= checked_address <= maximum:
        raise OverflowError(
            f"record address {checked_address} is outside the native "
            f"pointer range [0, {maximum}]"
        )
    instance = cast(
        _RecordT,
        _native_metaclass(record_type).from_address(
            record_type,
            checked_address,
        ),
    )
    _set_state(
        instance,
        _RecordState(ctypes.sizeof(record_type), borrowed=True),
    )
    return instance


def _record_buffer(instance: CStruct | CUnion) -> memoryview:
    state = _require_state(instance)
    raw_type = cast(type[Any], ctypes.c_ubyte * state.extent)
    raw = cast(
        ctypes.Array[Any],
        raw_type.from_address(_record_address(instance)),
    )
    setattr(raw, "_ctypesx_owner", instance)
    return memoryview(raw).cast("B")


class _RecordMethods:
    __slots__ = ()

    def __init__(self, **fields: object) -> None:
        super().__init__()
        _initialize_record(cast(CStruct | CUnion, self), fields)

    def __buffer__(self, flags: int, /) -> memoryview:
        del flags
        record = cast(CStruct | CUnion, self)
        _pin_record(record)
        try:
            return _record_buffer(record)
        except BaseException:
            _unpin_record(record)
            raise

    def __release_buffer__(self, buffer: memoryview, /) -> None:
        del buffer
        _unpin_record(cast(CStruct | CUnion, self))

    def __bytes__(self) -> bytes:
        return bytes(_record_buffer(cast(CStruct | CUnion, self)))

    @classmethod
    def from_buffer(
        cls,
        buffer: Buffer,
        offset: int = 0,
        /,
    ) -> Self:
        return cast(Self, _from_buffer(cast(Any, cls), buffer, offset))

    @classmethod
    def from_buffer_copy(
        cls,
        buffer: Buffer,
        offset: int = 0,
        /,
    ) -> Self:
        return cast(Self, _from_buffer_copy(cast(Any, cls), buffer, offset))

    @classmethod
    def from_address(
        cls,
        address: int,
        /,
    ) -> Self:
        return cast(Self, _from_address(cast(Any, cls), address))

class CStruct(
    _RecordMethods,
    ctypes.Structure,
    metaclass=_CStructMeta,
):
    """Base class for annotation-defined, naturally aligned C structures."""

    __slots__ = ("__ctypesx_state", "__weakref__")

    if TYPE_CHECKING:

        def __get__(
            self,
            instance: object | None,
            owner: type[object] | None = None,
            /,
        ) -> Self: ...

        def __set__(self, instance: object, value: Self, /) -> None: ...


class CUnion(
    _RecordMethods,
    ctypes.Union,
    metaclass=_CUnionMeta,
):
    """Base class for annotation-defined, naturally aligned C unions."""

    __slots__ = ("__ctypesx_state", "__weakref__")

    if TYPE_CHECKING:

        def __get__(
            self,
            instance: object | None,
            owner: type[object] | None = None,
            /,
        ) -> Self: ...

        def __set__(self, instance: object, value: Self, /) -> None: ...


def field_info(
    record_type: type[CStruct] | type[CUnion],
    name: str,
    /,
) -> FieldInfo[Any]:
    """Return immutable physical layout metadata for one C record field."""

    try:
        return _layout_for(record_type).fields[name]
    except KeyError:
        raise KeyError(
            f"{record_type.__name__} has no field {name!r}"
        ) from None


_cstruct_state_slot = CStruct.__dict__["_CStruct__ctypesx_state"]
_cunion_state_slot = CUnion.__dict__["_CUnion__ctypesx_state"]
