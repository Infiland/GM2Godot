# Python distribution and installed launchers

GM2Godot's Python namespace is `src`. The wheel contains that namespace, the
existing top-level `main` dispatcher, runtime GDScript segments, and copies of
canonical GUI assets. The optional Deep extension continues to be provisioned
by its existing commands; packaging the client does not download an agent or
extension.

Install an actual built wheel in a Python 3.12 or newer environment with the
runtime dependencies from `requirements.txt`. Native release verification uses
the project's exact interpreter and architecture-specific locked graph. The
wheel's runtime requirement versions agree with that file; build and lint tools
are not additional runtime requirements.

Use `gm2godot --version`, `gm2godot --help`, `gm2godot list-converters --format json`,
or `gm2godot deep --help` for console commands. Running `gm2godot` with no arguments
opens the GUI. `gm2godot-gui` uses the same dispatcher through a GUI launcher;
use the console launcher for commands that print output. Existing `python main.py`
source and frozen application entrypoints remain supported.

The root `img/*.png`, `Languages/*.json`, and `Current Language` files remain the
canonical GUI inputs. The build-only setuptools command copies their bytes into
`src/application_assets` in build output. It never generates copies in the source
checkout. Runtime GDScript remains at its existing package-relative location
`src/conversion/gml_runtime_parts/segments`. Source distributions retain the
canonical inputs and the build command, allowing the same wheel to be built from
an extracted sdist.

Source and frozen apps use their existing root asset and language preference
paths. An installed wheel reads its packaged language default until a user
preference exists. The language dialog writes that preference to
`~/.gm2godot/Current Language` and leaves installed assets unchanged. Reads do not
create this directory. Language fallback, parsing, and existing error handling
remain unchanged. The installed dialog restarts through `python -m main` with the
same argument tail, so a Windows GUI-launcher executable is not supplied to
Python as if it were a source file. Source and frozen restart calls are unchanged.

Build verification uses fresh owned source/build directories and the pinned
setuptools backend; editable installs do not demonstrate wheel contents. Check
both a direct wheel and a wheel built from the sdist in a fresh native environment,
from an unrelated directory with `PYTHONPATH` unset. Verify distribution/version
metadata, entrypoints, exact runtime requirements and data bytes, then `pip check`,
console commands, a report/conversion that consumes GDScript, and offscreen GUI
startup/icons/translations with a writable user preference. Wheel installs are
unpacked filesystem layouts; importing the wheel archive directly as a zip is
not supported. No PyPI upload is part of this change.
