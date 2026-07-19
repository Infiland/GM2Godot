@echo off
setlocal EnableExtensions DisableDelayedExpansion

set "PYTHON_BIN=python"
set "DEPENDENCY_CONSTRAINT=constraints\requirements-windows-py312.txt"
set "DEPENDENCY_VERIFIER=scripts\verify_dependency_environment.py"
set "PIP_CONFIG_FILE=nul"
set "BUILD_TEMP_ROOT="
set "EXIT_CODE=1"

pushd "%~dp0" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Could not enter the physical directory containing build.bat.
    endlocal & exit /b 1
)

for %%F in (
    "build.bat"
    "main.py"
    "requirements.txt"
    "%DEPENDENCY_CONSTRAINT%"
    "%DEPENDENCY_VERIFIER%"
) do (
    if not exist "%%~F" (
        echo ERROR: Refusing to build outside the physical GM2Godot repository root; missing %%~F.
        goto :fail
    )
    if exist "%%~F\" (
        echo ERROR: Refusing to build because repository sentinel %%~F is not a regular file.
        goto :fail
    )
)

where "%PYTHON_BIN%" >nul 2>&1
if errorlevel 1 (
    echo ERROR: CPython 3.12.10 for Windows x64 is required, but python was not found.
    goto :fail
)

"%PYTHON_BIN%" -c "import platform, sys; observed = (platform.python_implementation(), platform.python_version(), sys.platform, platform.system(), platform.machine()); expected = ('CPython', '3.12.10', 'win32', 'Windows', 'AMD64'); sys.exit(0 if observed == expected else f'ERROR: Unsupported Python/host tuple. Expected {expected!r}; observed {observed!r}.')"
if errorlevel 1 (
    echo Install CPython 3.12.10 for Windows x64 and make it available as python.
    goto :fail
)

for /f "delims=" %%I in ('%PYTHON_BIN% -c "import sys, tempfile; print(tempfile.mkdtemp(prefix=sys.argv[1]))" gm2godot-build-') do set "BUILD_TEMP_ROOT=%%I"
if not defined BUILD_TEMP_ROOT (
    echo ERROR: Could not create a temporary build directory.
    goto :fail
)

set "BUILD_VENV=%BUILD_TEMP_ROOT%\venv"
set "BUILD_RECEIPT=%BUILD_TEMP_ROOT%\dependency-environment-windows.json"
set "VENV_PYTHON=%BUILD_VENV%\Scripts\python.exe"

echo Creating isolated build environment...
"%PYTHON_BIN%" -m venv "%BUILD_VENV%"
if errorlevel 1 goto :fail
if not exist "%VENV_PYTHON%" (
    echo ERROR: The isolated build environment did not create a Python interpreter.
    goto :fail
)

echo Installing required packages...
"%VENV_PYTHON%" -m pip --isolated --disable-pip-version-check --no-input install --no-cache-dir --only-binary=:all: ^
    --constraint "%DEPENDENCY_CONSTRAINT%" ^
    pip==26.1.2
if errorlevel 1 goto :fail
"%VENV_PYTHON%" -m pip --isolated --disable-pip-version-check --no-input install --no-cache-dir --only-binary=:all: ^
    --constraint "%DEPENDENCY_CONSTRAINT%" ^
    -r requirements.txt PyInstaller==6.21.0
if errorlevel 1 goto :fail

echo Verifying dependency environment...
"%VENV_PYTHON%" "%DEPENDENCY_VERIFIER%" ^
    --constraint "%DEPENDENCY_CONSTRAINT%" ^
    --mode subset ^
    --require pip ^
    --require Pillow ^
    --require markdown2 ^
    --require requests ^
    --require PySide6 ^
    --require PyInstaller ^
    --expected-python 3.12.10 ^
    --expected-platform win32 ^
    --expected-machine AMD64 ^
    --expected-pip 26.1.2 ^
    --output "%BUILD_RECEIPT%"
if errorlevel 1 goto :fail

echo Cleaning up old build files...
if exist "dist" (
    rmdir /s /q "dist"
    if errorlevel 1 goto :fail
)
if exist "build" (
    rmdir /s /q "build"
    if errorlevel 1 goto :fail
)
if exist "GM2Godot.spec" (
    del /f /q "GM2Godot.spec"
    if errorlevel 1 goto :fail
)

echo.
echo Creating Windows build...
"%VENV_PYTHON%" -m PyInstaller --onefile ^
            --windowed ^
            --clean ^
            --name GM2Godot ^
            --icon img/Logo.png ^
            --hidden-import markdown2 ^
            --hidden-import PIL ^
            --hidden-import PySide6.QtWidgets ^
            --hidden-import PySide6.QtCore ^
            --hidden-import PySide6.QtGui ^
            --add-data "img;img" ^
            --add-data "src;src" ^
            --add-data "Languages;Languages" ^
            --add-data "Current Language;." ^
            main.py
if errorlevel 1 goto :fail
if not exist "dist\GM2Godot.exe" (
    echo ERROR: PyInstaller did not create dist\GM2Godot.exe.
    goto :fail
)

echo Creating build folder...
mkdir "dist\windows"
if errorlevel 1 goto :fail
if not exist "dist\windows\" (
    echo ERROR: Could not create dist\windows.
    goto :fail
)

echo Moving Windows build...
move "dist\GM2Godot.exe" "dist\windows\"
if errorlevel 1 goto :fail
copy /y "README.md" "dist\windows\"
if errorlevel 1 goto :fail

echo.
echo Creating platform-specific README file...
(
echo # GM2Godot - Windows Version
echo.
echo ## Running the Application
echo 1. Double-click `GM2Godot.exe` to run the application
echo 2. If you get a Windows security warning, click "More info" and then "Run anyway"
) > "dist\windows\README_WINDOWS.txt"
if errorlevel 1 goto :fail
if not exist "dist\windows\README_WINDOWS.txt" (
    echo ERROR: Could not create dist\windows\README_WINDOWS.txt.
    goto :fail
)

set "EXIT_CODE=0"
goto :finish

:fail
echo.
echo ERROR: GM2Godot Windows build failed.
set "EXIT_CODE=1"

:finish
call :cleanup_temp
if errorlevel 1 set "EXIT_CODE=1"
popd
if errorlevel 1 set "EXIT_CODE=1"
if not "%EXIT_CODE%"=="0" (
    endlocal & exit /b 1
)

echo.
echo Build complete! The executable is in:
echo - Windows: dist\windows\GM2Godot.exe
echo.
endlocal & exit /b 0

:cleanup_temp
if not defined BUILD_TEMP_ROOT exit /b 0
if not exist "%BUILD_TEMP_ROOT%\" (
    set "BUILD_TEMP_ROOT="
    exit /b 0
)
"%PYTHON_BIN%" -c "import pathlib, shutil, sys, tempfile; original = pathlib.Path(sys.argv[1]); parent = pathlib.Path(tempfile.gettempdir()).resolve(); prefix = sys.argv[2]; valid = original.parent.resolve() == parent and original.name.startswith(prefix) and len(original.name) > len(prefix) and original.is_dir() and not original.is_symlink() and not original.is_junction(); valid or sys.exit(1); shutil.rmtree(original)" "%BUILD_TEMP_ROOT%" gm2godot-build-
if errorlevel 1 (
    echo ERROR: Refusing or unable to remove temporary build environment %BUILD_TEMP_ROOT%.
    exit /b 1
)
if exist "%BUILD_TEMP_ROOT%\" (
    echo ERROR: Temporary build environment still exists after cleanup: %BUILD_TEMP_ROOT%.
    exit /b 1
)
set "BUILD_TEMP_ROOT="
exit /b 0
