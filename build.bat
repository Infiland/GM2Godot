@echo off
echo Cleaning up old build files...
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"
if exist "*.spec" del /f /q *.spec

echo Installing required packages...
pip install markdown2 tkhtmlview Pillow pyinstaller

echo.
echo Creating Windows build...
pyinstaller --onefile ^
            --windowed ^
            --clean ^
            --name GM2Godot ^
            --icon img/Logo.png ^
            --hidden-import markdown2 ^
            --hidden-import tkhtmlview ^
            --hidden-import PIL ^
            --add-data "img;img" ^
            --add-data "src;src" ^
            main.py

echo Creating build folders...
mkdir "dist\windows"
mkdir "dist\macos"
mkdir "dist\linux"

echo Moving Windows build...
move "dist\GM2Godot.exe" "dist\windows\"
copy "README.md" "dist\windows\"

echo Creating Linux build...
pyinstaller --onefile ^
            --clean ^
            --name GM2Godot ^
            --icon img/Logo.png ^
            --hidden-import markdown2 ^
            --hidden-import tkhtmlview ^
            --hidden-import PIL ^
            --add-data "img:img" ^
            --add-data "src:src" ^
            main.py
move "dist\GM2Godot" "dist\linux\"
copy "README.md" "dist\linux\"

echo Creating macOS build...
pyinstaller --onefile ^
            --clean ^
            --name GM2Godot ^
            --icon img/Logo.png ^
            --hidden-import markdown2 ^
            --hidden-import tkhtmlview ^
            --hidden-import PIL ^
            --add-data "img:img" ^
            --add-data "src:src" ^
            --target-architecture universal2 ^
            main.py
move "dist\GM2Godot" "dist\macos\GM2Godot.app"
copy "README.md" "dist\macos\"

echo.
echo Creating platform-specific README files...
(
echo # GM2Godot - Windows Version
echo.
echo ## Running the Application
echo 1. Double-click `GM2Godot.exe` to run the application
echo 2. If you get a Windows security warning, click "More info" and then "Run anyway"
) > "dist\windows\README_WINDOWS.txt"

(
echo # GM2Godot - Linux Version
echo.
echo ## Running the Application
echo 1. Open terminal in this directory
echo 2. Make the file executable: `chmod +x GM2Godot`
echo 3. Run the application: `./GM2Godot`
) > "dist\linux\README_LINUX.txt"

(
echo # GM2Godot - macOS Version
echo.
echo ## Running the Application
echo 1. Open terminal in this directory
echo 2. Make the file executable: `chmod +x GM2Godot.app`
echo 3. Run the application by double-clicking or using: `open GM2Godot.app`
echo.
echo Note: If you get a security warning, go to System Preferences > Security & Privacy and allow the app to run.
) > "dist\macos\README_MACOS.txt"

echo.
echo Build complete! The executables are in the 'dist' folder:
echo - Windows: dist\windows\GM2Godot.exe
echo - Linux:   dist\linux\GM2Godot
echo - macOS:   dist\macos\GM2Godot.app
echo.
echo Note: For best compatibility, it's recommended to build on each target platform natively.
echo Press any key to exit...
pause > nul 