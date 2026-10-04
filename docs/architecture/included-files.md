# Included Files ownership

`src.conversion.included_files.IncludedFilesConverter` remains the caller entry
point. Its constructor, state, entry point and callable signatures stay stable.
Its thin methods delegate to operation owners using the same converter instance.
Thirty internal modules own the models, typed contracts and operations.

The landed dependency direction is:

```text
models -> filesystem_operations
models / constants -> path_validation
models -> stat_metadata
path_validation / stat_metadata -> recovery_codec
models / stat_metadata -> native_posix
filesystem_operations / models / path_validation / stat_metadata -> native_windows
filesystem_operations / native_posix / native_windows / stat_metadata -> native_filesystem
native filesystem / stat metadata / paths / models -> source_snapshots
source_snapshots / native filesystem / phase_observer -> guarded_mutations
source_snapshots / native filesystem / recovery_codec -> record_io
source_snapshots / guarded_mutations / native filesystem / phase_observer -> recorded_cleanup
models / typed converter ports -> planning / source_access / diagnostics / copy_worker
constants -> worker_pool
snapshots / records / native filesystem -> staging / locking / file_publication
snapshots / records / cleanup -> transaction_state / record_lifecycle / transaction_cleanup
transaction state / lifecycle / cleanup -> recovery / publisher
planning / source access / workers / staging / locking / recovery / publisher -> driver
operation owners -> thin included_files facade
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

`filesystem_operations` defines the finite twenty-operation filesystem contract
and the owned Windows cleanup-parent resource contract. `native_filesystem`
provides the typed concrete composition. It stores no platform choice or bound
native callable: each operation reads its actual native owner's export when
called. Transaction owners use this interface at the existing operation stages.

`native_posix` owns descriptor-relative operations, mount checks, exclusive
rename, directory synchronization and output metadata. `native_windows` owns
the Win32 loaders and structures, cleanup-parent handles, locking, durable
rename and the complete cross-platform validation-stream selector. The
redirection metadata probe belongs to `stat_metadata`. These owners retain the
original capability checks, native flags, loader caches, errors and cleanup
precedence. Caller-supplied descriptors remain borrowed; returned descriptors,
validation streams and Windows cleanup-parent bindings retain their original
ownership. Lock release continues to use the platform flag captured at lock
acquisition.

`source_snapshots` owns confined source and output-tree observation, inventories
and descriptor/path bindings. `guarded_mutations` owns confined creation, rename,
quarantine and removal. `record_io` owns bounded record reads and exclusive
canonical record writes. `recorded_cleanup` owns receipt-verified cleanup and
resumable tombstones. `phase_observer` owns the existing durable-phase observer,
looked up at the original phase boundaries. These owners share the existing
typed native filesystem composition; no lower owner imports the converter.
Record I/O does not import cleanup. Borrowed descriptors and Windows bindings
remain borrowed through success and injected errors.

Each moved definition retains its private spelling and has a finite named
internal export. The facade keeps explicit aliases to those same objects for
existing private imports. Operational calls use the actual owner's namespace;
private fault-injection patches therefore target that owner. Shared protocol
constants have one actual constants owner and are read there at the original
operation stages. The move preserves public API and observable behavior while
making internal ownership explicit; it does not provide a second implementation
or dynamic forwarding module.

`planning` owns declarations and logical source planning. `source_access` owns
source discovery, confined reads and unchanged-source receipts; `copy_worker`
owns one payload copy. `diagnostics` preserves reporting order and the converter
collector. `worker_pool` owns bounded admission and cancellation;
`generation_matching` compares previous output with the current source plan.

`staging`, `locking` and `file_publication` retain their original stages.
`record_lifecycle`, `transaction_state` and `transaction_cleanup` coordinate
durable records and owned output generations. `recovery` and `publisher` depend
on those owners and do not import each other. The driver coordinates operations
without importing POSIX or Win32 implementations. Native operations preserve
no-follow, mount-boundary, hard-link, no-replace, ownership and durability
contracts. Borrowed descriptors remain borrowed.

Six finite receiver contracts in `converter_ports` describe consumed methods
and state. Typed operation classes provide a scope for protected methods;
their unbound methods receive the original converter directly. These classes
are never instantiated. Dynamic calls retain subclass overrides, class and
instance patches, cancellation and resource accounting. There is no second
controller or callback dictionary.

The paired tests are grouped into basic conversion, file publication, generation
matching, locking, recovery, staging, state contracts, transactions and worker
admission. `tests.included_files_support` contains shared fixtures with no test
methods or concrete-case reexports. Existing cases and assertions stay intact;
private fault-injection sites follow their actual operation owners.

Native workflow selectors follow the exact old-to-new case map. Windows selects
all seven transaction groups and file publication; its scale job retains the
single 10,000-entry case. The twelve explicit macOS cases retain their order.
Runtime pins, N01 selectors and generated-output fixtures stay unchanged.

Full-graph architecture coverage rejects cycles, facade backedges and direct
native/publication calls from orchestration. Existing owner tests exercise live
native delegation, late platform selection, borrowed descriptors, real Windows
bindings, bounded records and durable quarantine observers. Transaction,
recovery, scale and Godot tests remain authoritative for their wider contracts.
Required verification includes zero-warning global typing, Ruff, relevant tests,
the full suite after shared-boundary changes, native Windows transaction checks
and pinned Godot output validation.
