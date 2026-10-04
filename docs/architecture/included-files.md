# Included Files ownership

`src.conversion.included_files.IncludedFilesConverter` remains the caller entry
point. The facade currently also owns conversion orchestration, bounded workers,
native filesystem operations and the transaction. The records/constants and
helper splits establish five internal owners; they do not yet make the facade
thin.

The landed dependency direction is:

```text
models / constants
  -> path_validation and stat_metadata (independent)
  -> recovery_codec
  -> remaining included_files orchestration
```

Package init has no imports. `models` and `constants` depend only on the standard
library and perform no I/O, callbacks, platform selection, descriptor ownership
or traversal. Records retain their original field order, annotations,
decorators, defaults and properties; the project lock remains mutable. The
nineteen records, cancellation exception and seven tuple aliases have one actual
definition each. Private record and exception module names identify the models
owner; their names and qualified names remain. This does not promise legacy
private pickle module paths or bytes. Public converter and external public types
remain at their original definitions.

`path_validation` owns managed-name and recovery-path grammar, output
confinement, Windows ambiguous-component checks, extended-path spelling and
registry/backup/tombstone path construction. Platform-dependent validation still
reads the platform when the original operation requires it. These helpers do
not acquire descriptors, inspect file metadata or mutate the filesystem.

`stat_metadata` owns stat/fstat/lstat observations and immutable projections,
directory and output identity checks, inventory/receipt validation, tree
topology checks and record-size validation. It observes borrowed descriptors
without opening or closing them. It does not scan trees, acquire locks, publish
outputs or mutate filesystem entries.

`recovery_codec` owns version-1/version-2 tree, registry, journal and commit
marker parsing and rendering, canonical JSON bytes, base64/digests and recovery
preflight sizing. It calls path grammar and metadata validation, without
performing I/O, native platform selection or transaction/recovery execution.
The 16 MiB recovery cap, 100,000-entry limit, 16-digit integer representation,
record schemas, key order and error precedence remain unchanged.

Each moved definition retains its private spelling and has a finite named
internal export. The facade keeps explicit aliases to those same objects for
existing private imports. Operational calls use the actual owner's namespace;
private fault-injection patches therefore target that owner. Shared protocol
constants have one actual constants owner and are read there at the original
operation stages. The move preserves public API and observable behavior while
making internal ownership explicit; it does not provide a second implementation
or dynamic forwarding module.

The remaining target direction is: records/constants and validation/codec
owners -> POSIX and Windows primitives -> finite typed filesystem interface ->
source snapshots/planning/locking/workers -> record I/O/staging/recorded cleanup
-> rollback/committed cleanup -> recovery/publication -> converter driver ->
thin facade. Recovery and publication must not import each other, and record
I/O must not import cleanup. Native operations must preserve no-follow,
mount-boundary, hard-link, no-replace, ownership and durability guarantees.
Orchestration will compose the typed interface without selecting a platform
early or taking ownership of borrowed descriptors.

Existing transaction/security test IDs and assertions remain, with private
fault-injection sites following the moved owners. Native workflow selectors,
runtime pins and generated-output fixtures remain unchanged. Focused owner
tests enforce the current dependency direction and exercise operation boundaries;
the existing transaction, recovery, scale and Godot tests remain authoritative
for their wider contracts. Required verification includes zero-warning global
typing, Ruff, relevant tests, the full suite after shared-boundary changes,
native Windows transaction checks and pinned Godot output validation.

Issue #798 remains open until native interfaces, source/planning/staging and
transaction owners, the driver, thin facade and matching test split are complete.
