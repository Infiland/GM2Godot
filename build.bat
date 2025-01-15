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
            --add-data "Languages;Languages" ^
            --add-data "Current Language;." ^
            main.py

echo Creating build folder...
mkdir "dist\windows"

echo Moving Windows build...
move "dist\GM2Godot.exe" "dist\windows\"
copy "README.md" "dist\windows\"

echo.
echo Creating platform-specific README file...
(
echo # GM2Godot - Windows Version
echo.
echo ## Running the Application
echo 1. Double-click `GM2Godot.exe` to run the application
echo 2. If you get a Windows security warning, click "More info" and then "Run anyway"
) > "dist\windows\README_WINDOWS.txt"

echo.
echo Build complete! The executable is in:
echo - Windows: dist\windows\GM2Godot.exe
echo.
echo Press any key to exit...
pause > nul 