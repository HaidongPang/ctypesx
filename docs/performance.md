# Performance and copy model

ctypesx prioritizes exact C layout, checked conversion, typing, and explicit
lifetime behavior. It is pure Python on top of ctypes and does not claim C- or
Rust-level per-field throughput.

This page documents where the current implementation copies, converts, creates
views, or may relocate memory so applications can keep hot paths deliberate.

## Copy and view matrix

| Operation | Cost model | Copy or view |
|---|---|---|
| scalar construction/field read | constant-time conversion | semantic value object |
| fixed record field read/write | constant-time descriptor work | record bytes shared/updated |
| `Array`/`FamArray` field read | creates a lightweight view | zero-copy |
| array element read/write | constant-time plus semantic conversion | shared storage |
| array slice read | proportional to selected elements | returns Python list |
| fixed-array slice write | proportional to selected elements | stages conversion, then writes |
| `Record.from_buffer` | constant setup | zero-copy borrowed view |
| `Record.from_buffer_copy` | proportional to extent | full byte copy |
| `bytes(record)` / `bytes(array)` | proportional to extent | full byte copy |
| `memoryview(record/array)` | constant setup | zero-copy pinned view |
| `Pointer[T](sequence)` | proportional to element count | converted owned snapshot |
| char/wchar pointer from string | proportional to string length | encoded/copied NUL-terminated buffer |
| `Span[T](sequence)` | proportional to element count | delegates to owned pointer snapshot |
| span from managed pointer | constant setup | view, no element copy |
| `pointer_to(record)` | constant setup | refers to existing record |
| `pointer_to(scalar, T)` | constant-time conversion | one owned native scalar copy |

“Constant-time” here describes growth with object extent, not a promise about
absolute latency. Python descriptors and semantic wrapper construction still
cost more than unchecked raw C memory access.

## FAM mutation is list-like in API, not complexity

`FamArray` deliberately presents familiar list operations, but the current
storage algorithm does not provide Python list's amortized append behavior.

Every length-changing operation builds the complete logical element sequence,
converts/stages it, resizes the record, and commits the complete tail. Therefore:

- one `append`, `insert`, `pop`, deletion, `clear`, length-changing slice, or
  `extend` is generally O(n) in the resulting/current tail size;
- repeated single-element append can be O(n²);
- a length change may relocate the entire owning record; and
- pointer/owner sidecar metadata is also reconstructed as needed.

Prefer one bulk assignment or `extend` over a loop of single-element appends:

```python
# Better for a known batch:
message.data.extend(values)

# Avoid in a large hot path when values is already available as a batch:
for value in values:
    message.data.append(value)
```

Element replacement without a length change does not resize the record. A
borrowed FAM supports only such equal-length changes.

ctypesx does not expose public capacity/reserve/allocate methods. Its API
chooses Pythonic logical contents over a capacity-management protocol. If a hot
path needs amortized growth, build the values in a Python list or another
buffer first and assign once.

## Record relocation and pins

An owned FAM resize may move the allocation. Checked held views resolve the new
root location. Tracked native exports pin instead, causing a resize attempt to
raise `BufferError`.

Pinning avoids stale addresses but can turn an otherwise valid mutation into an
exception. Organize code into phases:

1. construct or resize logical contents;
2. obtain/pin the native address;
3. perform the foreign operation; and
4. release the export before the next resize.

Long-lived foreign retention and frequent FAM growth are fundamentally in
tension. Use fixed/borrowed backing or a higher-level storage strategy when the
native API retains addresses indefinitely.

## Pointer and span hot paths

`Pointer[T](sequence)` and `Span[T](sequence)` convert every element and allocate
a native snapshot. Reuse the resulting pointer/span when the native contract and
lifetime permit instead of rebuilding it for every call.

Direct pointer indexing is unchecked and cheap relative to span bookkeeping,
but unsafe and unbounded. Span indexing validates bounds and, for record-backed
storage, temporarily pins and refreshes the pointer on each operation. For a
large transfer, avoid a Python loop over individual elements when a bulk native
operation or buffer-based API is available.

## Callbacks

Every callback crosses C → Python → C and converts each argument/result. This is
appropriate for control-plane events and ABI integration, but high-frequency
per-byte or per-packet callbacks can be expensive.

Pointer-valued callbacks also append one retention token per invocation until
the callback is destroyed. Returning a new owned buffer each time retains all
of those buffers.

Prefer batching, shared queues/rings, eventfd-style notification, or a native
data-plane implementation when callback frequency dominates execution time.

## Measuring an application

Benchmark the complete workload on the deployment Python, OS, architecture, and
native library. Include:

- conversion and record construction frequency;
- FAM mutation pattern and tail sizes;
- pointer snapshot allocation;
- number of Python/native crossings;
- callback frequency;
- buffer copies versus borrowed views; and
- contention or pin lifetime around dynamic records.

Do not infer performance from layout equivalence alone. ctypesx preserves the C
representation, but semantic Python objects and safety bookkeeping remain part
of the runtime cost.
