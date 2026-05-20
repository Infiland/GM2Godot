# GML Language Checklist

This file tracks GML frontend and semantic coverage needed for full transpilation.

## Lexing And Literals

- [x] Decimal numeric literals.
- [x] Floating numeric literals.
- [x] Numeric separators.
- [x] Hex literals with `0x` and `0X`.
- [x] GameMaker `$` hex literals.
- [x] Binary `0b` literals.
- [x] Hash color literals with GameMaker color ordering.
- [x] Single-quoted strings.
- [x] Double-quoted strings.
- [x] Escaped string characters.
- [x] Boolean constants.
- [x] `undefined` lowering through runtime helpers.
- [x] `begin` and `end` block aliases.
- [x] `//` comments.
- [x] `/* */` comments.
- [ ] Preserve comments and source spans for source maps.
- [ ] Template strings or interpolation if supported by target GameMaker versions.
- [ ] Full reserved-name diagnostics.
- [ ] Case-sensitivity compatibility diagnostics.

## Expressions And Operators

- [x] Unary `+`.
- [x] Unary `-`.
- [x] Unary `!`.
- [x] Unary `not`.
- [x] Unary bitwise invert `~`.
- [x] Arithmetic `+`, `-`, `*`, `/`.
- [x] Modulo `%` and `mod`.
- [x] Integer division `div`.
- [x] Comparisons `<`, `<=`, `==`, `!=`, `>`, `>=`.
- [x] GameMaker single `=` expression equality.
- [x] Logical `and`, `or`, `&&`, `||`, and `^^`.
- [x] Bitwise `|`, `^`, `&`, `<<`, and `>>`.
- [x] Nullish coalescing `??`.
- [x] Ternary conditional `?:`.
- [x] Parenthesized expressions.
- [x] Function call expressions.
- [x] Omitted call arguments lowered to `GMRuntime.gml_undefined()`.
- [x] Array literals.
- [x] Struct literals.
- [x] Nested arrays and structs.
- [x] Struct shorthand fields.
- [x] Function-valued struct fields.
- [x] `nameof(...)`.
- [x] `new Constructor(...)`.
- [ ] Assignment result semantics across every expression context.
- [ ] Arbitrary `foo(i++)` and `foo(--i)` expression support.
- [ ] YYC/VM evaluation-order edge cases.
- [ ] Full GameMaker truthiness and boolean coercion auditing.
- [ ] Full `NaN`, `infinity`, divide-by-zero, and comparison edge-case parity.

## Variables And Scope

- [x] `var` declarations.
- [x] Multiple variable declarations in one statement.
- [x] `:=` local assignment syntax.
- [x] Uninitialized local variables as `undefined`.
- [x] Assignment operators `=`, `:=`, `+=`, `-=`, `*=`, `/=`, `%=`, `&=`, `|=`, `^=`, `<<=`, `>>=`, and `??=`.
- [x] Increment/decrement statements.
- [x] Limited increment/decrement assignment RHS uses.
- [x] `globalvar`.
- [x] Top-level global scope handling.
- [x] Documented built-in globals such as `score`, `health`, and `lives` where current GameMaker still exposes them.
- [x] Read-only builtin mutation rejection for known built-ins.
- [x] `global.name` scoped access.
- [x] `self` scoped access.
- [x] `other` scoped access.
- [x] `super` scoped access where valid.
- [x] Dynamic selector helpers for general dot access.
- [ ] Chained assignment.
- [ ] Full scope lookup parity for asset names, scripts, locals, instance variables, globals, constructors, methods, and struct fields.
- [ ] Dynamic variable functions such as full `variable_*` coverage.
- [ ] Full `struct_*` reflection coverage.
- [ ] Full instance variable creation-on-assignment semantics.
- [ ] Full method binding and unbound script reference semantics.

## Arrays, Structs, And Accessors

- [x] Array indexing reads.
- [x] Array indexing writes.
- [x] Struct dot access.
- [x] Struct selector runtime helpers.
- [x] Struct accessor `[$ key]`.
- [x] DS map accessor `[? key]`.
- [x] DS list accessor `[| index]`.
- [x] DS grid accessor `[# x, y]`.
- [x] Array reference accessor `[@ index]`.
- [x] Compound assignment through many accessor forms.
- [x] Reference semantics for arrays and structs are intentionally modeled by runtime helpers.
- [ ] DS grid increment/decrement target support.
- [ ] Mixed deeply chained accessor stress coverage.
- [ ] Undefined-on-missing behavior for every accessor and DS type.
- [ ] Array copy-on-write compatibility audit.
- [ ] Struct copy/reference compatibility audit.
- [ ] Accessor auto-expansion and handle lifetime edge cases.

## Functions, Methods, Constructors, Statics

- [x] Function literals.
- [x] Named function literals.
- [x] Anonymous function literals.
- [x] Function parameters.
- [x] Default parameter values.
- [x] Return statements inside functions.
- [x] Function-valued struct method fields.
- [x] Runtime method binding with `GMRuntime.gml_method`.
- [x] Constructor functions.
- [x] `new Constructor(...)` calls.
- [x] Constructor inheritance syntax.
- [x] Static declarations inside functions and constructors.
- [x] Static declarations outside functions rejected.
- [ ] Full closure capture parity.
- [ ] Full constructor static inheritance behavior.
- [ ] `method_get_self` and `method_get_index` parity.
- [ ] Static chain APIs such as `static_get` and `static_set`.
- [ ] Full script asset behavior for GMS2+ projects that current GameMaker can still import and run.

## Control Flow

- [x] `if`.
- [x] `else`.
- [x] `else if`.
- [x] `while`.
- [x] `repeat`.
- [x] `do ... until`.
- [x] `for` lowered to initializer plus `while`.
- [x] `switch`, `case`, `default`, and fallthrough.
- [x] `break` validation.
- [x] `continue` validation.
- [x] `return` validation.
- [x] `exit` lowered to return behavior.
- [x] `throw`.
- [x] `try/catch/finally` through runtime exception helpers.
- [x] `with (target)` blocks through runtime target expansion.
- [x] `event_inherited()` calls.
- [ ] Exact `finally` semantics when return/break/continue/exit occur.
- [ ] Full nested `with` and collision `other` semantics.
- [ ] Full object parent-chain target expansion for `with` and events.
- [ ] Full switch fallthrough and nested loop control conformance traces.

## Preprocessor And Macros

- [x] Strip comments before preprocessing.
- [x] Join multiline `#macro` continuations.
- [x] `#macro` declarations.
- [x] Macro configuration override syntax such as target-specific macro names.
- [x] Recursive macro detection.
- [x] `#define` symbols and macro values.
- [x] `#if`.
- [x] `#ifdef`.
- [x] `#ifndef`.
- [x] `#elif`.
- [x] `#else`.
- [x] `#endif`.
- [x] `defined(NAME)`.
- [x] Active macro configuration symbols.
- [x] Ignore `#region` and `#endregion`.
- [x] Reject unsupported directives with errors.
- [ ] Full preprocessor expression evaluator.
- [ ] `gml_pragma` support or documented no-op policy.
- [ ] `#import` or replacement policy.
- [ ] Config/platform macro integration from project settings.
- [ ] Source map preservation through preprocessing.

## Enums And Constants

- [x] `enum NAME { ... }` declarations.
- [x] Explicit enum values from expressions.
- [x] Implicit enum value increments.
- [x] Prior enum references during compile-time evaluation.
- [x] Macro references during enum evaluation.
- [x] Enum reassignment rejection.
- [x] Enum member mutation rejection.
- [ ] Full constant namespace conflict diagnostics.
- [ ] Full built-in constant coverage for every manual category.

## Built-In API Dispatch

- [x] Function descriptor table.
- [x] Arity validation.
- [x] Runtime-call lowering.
- [x] Keyboard-specific lowering.
- [x] Method binding lowering.
- [x] Print/debug lowering.
- [x] Runtime `self` and default argument lowering.
- [x] Instance keyword conversion.
- [x] Asset argument conversion.
- [x] Variadic-one APIs such as selected `script_execute` and `ds_list_add` patterns.
- [x] Platform-service call routing to hook framework.
- [x] Known unsupported APIs produce diagnostics.
- [x] Unknown project-local calls pass through as normal calls.
- [x] Known extension functions require mapping or raise actionable diagnostics.
- [ ] Unify function dispatch descriptors and API manifest into a single source of truth.
- [ ] Ensure every implemented manifest API has parser/emitter/runtime/smoke coverage or an explicit waiver.
- [ ] Add compatibility report CLI output for manifest status.

## GML Semantics Still Needing Dedicated Work

- [ ] Exact GameMaker number model and integer/real conversions.
- [ ] Exact string conversion and Unicode behavior.
- [ ] Exact array/struct copy and reference behavior.
- [ ] Exact handle reuse and invalid handle behavior.
- [ ] Exact asset identifier behavior as values.
- [ ] Exact `noone`, `all`, `self`, `other`, and documented numeric instance constants.
- [ ] Exact `with` semantics for nested calls, parent objects, and instance/object targets.
- [ ] Exact event inheritance and `event_inherited` behavior.
- [ ] Exact script/function/method identity behavior.
- [ ] Exact dynamic scope behavior for local, instance, global, asset, enum, macro, script, and constructor names.
- [ ] DnD/GML Visual action lowering.
