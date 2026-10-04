# Included Files ownership

`src.conversion.included_files` remains the caller entry point and owns conversion
orchestration, bounded workers, filesystem operations and the transaction. The
first split moves records, tuple aliases and fixed protocol constants into
`included_files_parts.models` and `included_files_parts.constants`. Package init
has no imports. Both leaves have only standard-library dependencies and perform
no I/O, callbacks, platform selection, descriptor ownership or graph traversal.

Each leaf defines the original private spelling once and exposes a finite named
internal alias. The facade explicitly imports that same object under its old
private spelling. The nineteen records retain exact field order, annotations,
decorators, defaults and property bodies; `_IncludedProjectLock` remains mutable.
The cancellation exception and seven tuple aliases are single definitions too.
Private record and exception `__module__` values now name the models owner.
Their names and qualified names remain; this does not promise legacy private
pickle module paths or bytes. `IncludedFilesConverter` and external public types
remain at their original definitions.

The twenty-one protocol constants retain expression/dependency order and values.
Unchanged helpers still read facade globals, including test-patched constants.
The recovery cap remains 16 MiB, entry limit 100,000, integer width 16 hex digits,
recovery formats 1/2, stage-marker format 1 and worker window multiplier 2. All
journal/marker/tree/registry codecs stay in the facade with their exact key
order, bytes, size checks and schemas. This split changes no security or
transaction behavior and does not yet make the facade thin.

Later owners should follow this direction: records/constants → separate path
validation and filesystem metadata → POSIX and Windows primitives → finite
filesystem interface → source snapshots/planning/codec/locking/workers → record
I/O/staging/recorded cleanup → rollback/committed cleanup → recovery/publication
→ converter driver → facade. Recovery and publication must not import each
other; record I/O must not import cleanup. Platform selection belongs in the
filesystem interface, and orchestration composes it. Only the two landed leaves
are enforced in this first slice; the remaining owners require separately
reviewed helper closures and tests.

Existing test IDs, transaction/scale/native workflow selectors and runtime pins
stay in place. Four focused tests cover all finite facade/owner aliases and
original public bindings, sampled record/property annotations and reflection,
frozen records and mutable locks with borrowed descriptors, ordinary
new-runtime pickle round trips, and the two leaves' directed import policy.
Exact declaration AST/source controls and existing transaction tests preserve
the remaining field defaults, constant expressions and protocol values; the
four new tests do not individually enumerate all of those contracts. Global
typing/lint, relevant old/new tests and existing full/native/parity release
checks remain required. #798 remains open until the later ownership and test
splits and thin facade are complete.
