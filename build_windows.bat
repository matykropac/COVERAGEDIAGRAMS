@echo off
setlocal
cd /d "%~dp0"
py -3.12 -m venv .venv-win
if errorlevel 1 goto :failed
call .venv-win\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 goto :failed
python -m pip install -r requirements.txt -r requirements-desktop.txt
if errorlevel 1 goto :failed
python -m PyInstaller --clean --noconfirm desktop.spec
if errorlevel 1 goto :failed
echo.
echo SUCCESS: dist\COVERAGEDIAGRAMS\COVERAGEDIAGRAMS.exe
echo Copy the whole dist\COVERAGEDIAGRAMS folder.
pause
exit /b 0
:failed
echo Build failed. Read the error messages above.
pause
exit /b 1
