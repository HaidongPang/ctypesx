# Security policy

ctypesx handles native addresses and ABI memory. A bug may cause memory
corruption, process crashes, use-after-free behavior, or unintended native code
execution rather than a normal Python exception.

## Supported versions

The project has not published a stable release yet. Security fixes are applied
to the latest `main` branch and, after releases exist, to versions explicitly
listed here.

| Version | Supported |
|---|---:|
| `main` / unreleased `0.1.x` | yes |
| older development snapshots | no |

## Reporting a vulnerability

Use GitHub's private vulnerability reporting for the repository when it is
available. Include:

- affected commit or version;
- operating system, architecture, and CPython build;
- a minimal reproducer;
- expected and observed behavior;
- whether untrusted input or foreign code is required; and
- any known crash, corruption, lifetime, or disclosure impact.

Do not include live secrets or third-party private data. If private reporting is
not available, open a public issue containing only a request for a private
maintainer contact; do not post exploit details.

## Inherent unsafe boundaries

The following are not vulnerabilities by themselves when they follow the
documented contract:

- dereferencing or calling an invalid raw integer address;
- foreign C retaining an address longer than its declared owner lifetime;
- writes through raw ctypes or foreign aliases despite Python-level constness;
- native data races not synchronized by the application;
- pointer bits copied without the Python owner sidecar; and
- crashes caused by an ABI declaration that does not match the actual native
  header/toolchain.

A report is still valuable when ctypesx claims to validate, retain, pin, reject,
or atomically convert one of these cases but fails to do so.

Read [Ownership and safety](docs/ownership-and-safety.md) for the supported
model and [Current limitations](docs/limitations.md) for explicit exclusions.
