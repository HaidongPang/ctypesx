# Callbacks and function pointers

`FunctionPointer[[Args...], Result]` creates a fixed-arity native C function
pointer type with semantic argument and result conversion.

`FunctionPointer` itself is only a factory. It must be subscripted with a full
signature before construction or use in an ABI declaration; a bare instance has
no supported ABI meaning.

## Declare a signature

```python
from ctypesx import FunctionPointer, U8


UnaryOperation = FunctionPointer[[U8], U8]
Notification = FunctionPointer[[U8], None]
```

The first parameter is a list or tuple of argument types. `None` as the result
means C `void`. Generated signature types are cached and are real
`ctypes.CFUNCTYPE` subclasses. Use an ordinary assignment when the generated
class must be called or passed to ctypes. A PEP 695 declaration such as
`type UnaryAlias = FunctionPointer[[U8], U8]` creates an annotation alias, not
a callable runtime class.

Signatures should use ctypesx scalar, enum, and pointer types when semantic
callback conversion and precise static types are wanted. A static record may be
used as an argument where ctypes and the target calling convention support it,
but dynamic/FAM and bit-field records must be passed by pointer. ctypes callback
trampolines do not support a structure or union as the by-value result type; use
an out-pointer or pointer result instead.

Raw ctypes-compatible types are accepted at runtime for low-level ABI
interoperability, but they retain normal ctypes callback value semantics. For
example, a `ctypes.c_int` callback argument arrives as Python `int`, and the
Python callback must return `int`, not a `ctypes.c_int` instance. The current
generic annotation cannot express that raw-ctypes primitive projection exactly,
so raw scalar signatures are not a type-safe gradual migration path. Prefer a
ctypesx semantic scalar or use `ctypes.CFUNCTYPE` directly for an intentionally
raw callback.

## Wrap a Python callable

```python
def increment(value: U8) -> U8:
    return U8(value + 1)


callback = UnaryOperation(increment)
assert callback(U8(3)) == U8(4)
```

The runnable version is in
[`examples/callback.py`](../examples/callback.py).

The trampoline converts native arguments to their declared semantic types,
calls Python, validates the result, and converts it back to C storage.

A callback object retains its Python callable/trampoline. A ctypesx record
field assigned from a Python callable retains the generated callback through
the record owner sidecar.

Foreign code may keep a callback address after the immediate call. The
application must keep the `FunctionPointer` object alive for at least that long;
ctypesx cannot infer the native retention lifetime.

## Raw addresses and NULL

A `FunctionPointer` also accepts:

- another instance of the same generated signature;
- `None` for NULL; or
- a native integer function address.

```python
null_callback = UnaryOperation(None)
assert null_callback.is_null

address_callback = UnaryOperation(0x12340000)
assert address_callback.address == 0x12340000
```

Calling an invalid address can immediately terminate the process. Address
validation establishes only native integer width.

## Invocation rules

Calling a managed function pointer:

- requires exactly the declared positional argument count;
- rejects keyword arguments;
- applies checked semantic conversion to every argument;
- returns the declared semantic type when the signature uses ctypesx value
  types; and
- returns `None` for a void signature.

Static typing carries the precise callable signature for ctypesx semantic
types, especially when a generated type is used as a record field. Some direct
runtime-generated constructor surfaces remain dynamic. Raw ctypes scalar
signatures have the primitive-projection gap described above.

## Exceptions at the callback boundary

Do not allow a Python exception to escape a callback invoked by C. ctypes and
the foreign caller do not provide a normal Python exception propagation path,
and continuing with an undefined C result is unsafe.

Catch exceptions inside the callback, translate them into the ABI's error
convention, and store diagnostic state separately:

```python
def safe_increment(value: U8) -> U8:
    try:
        return U8(value + 1)
    except Exception:
        return U8(0)  # use the real ABI's documented error convention
```

There is an additional boundary: argument conversion occurs before the user
callable runs, and final result conversion occurs after it returns. A
`try`/`except` inside the callable cannot catch either wrapper conversion error.

Use a closed enum directly in a callback signature only when the native ABI
guarantees every incoming value is a declared member. For untrusted or
forward-compatible input, declare the underlying open scalar, validate inside
the callable, and translate failure according to the ABI:

```python
from ctypesx import U8Enum


class Mode(U8Enum):
    OFF = 0
    ON = 1


CheckedModeCallback = FunctionPointer[[U8], U8]


def handle_mode(raw_mode: U8) -> U8:
    try:
        mode = Mode(raw_mode)
        result = U8(1 if mode is Mode.ON else 0)
    except (ValueError, OverflowError):
        result = U8(0)
    return result
```

Construct the final semantic result inside the protected block, as above, so
the wrapper receives an already validated value. The current callback API has
no configurable generic conversion-error policy.

## Pointer-valued results

Pointer results need backing storage that remains valid after the Python
callback returns. ctypesx lowers pointer-valued callback results through a
native `void *` representation. Every pointer-result invocation appends one
retention token that remains until the callback object is released, even when
the callback returns the same externally owned pointer repeatedly.

For an automatically owned pointer, the token also keeps its backing storage
alive. This avoids invalidating an earlier address if C retains multiple
returned pointers. Token metadata grows with every pointer-result call, and a
callback that creates a new owned buffer every time additionally retains every
full buffer:

```python
from ctypesx import Pointer


Producer = FunctionPointer[[], Pointer[U8]]


def produce() -> Pointer[U8]:
    return Pointer[U8]([1, 2, 3])
```

A pointer result derived from a dynamic record pins that record until the
callback object is released. FAM length changes raise `BufferError` for that
entire lifetime.

Use externally managed long-lived storage when the native API defines a
different result lifetime or when unbounded retention is undesirable.

Raw ctypes pointer, `c_char_p`, `c_wchar_p`, `c_void_p`, and function-pointer
result semantics are restored after the internal lowering step.

## Current callback limits

The current release models `ctypes.CFUNCTYPE` with a fixed argument count. It
does not yet model:

- variadic C functions;
- `WINFUNCTYPE` calling conventions;
- `use_errno` or `use_last_error` variants; or
- native declarations that need custom argument-conversion hooks outside the
  supported C value model.

Callbacks inherit the standard ctypes and platform restrictions for calling
conventions, threading, and interpreter lifetime.
