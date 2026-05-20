# Project Instructions

- When Python or generated-code logic changes, run `./venv/bin/pyright --warnings` and fix every reported error or warning before considering the code change complete.
- Do not leave new Pylance/Pyright diagnostics, lint errors, or warnings in changed code.
- Run the relevant tests after lint/type-check fixes when code behavior changes. For broad code changes, run `./venv/bin/python -m unittest`.
- Do not run Pyright or tests for documentation-only changes unless the user explicitly asks for verification.
