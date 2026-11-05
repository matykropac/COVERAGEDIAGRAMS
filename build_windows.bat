@echo off
setlocal
cd /d "%~dp0.."
py -3.12 -m venv .venv-win
if errorlevel 1 goto :failed
call .venv-win\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 goto :failed
python -m pip install -r requirements.txt -r desktop\requirements-windows.txt
if errorlevel 1 goto :failed
python -m PyInstaller --clean --noconfirm desktop\windows.spec
if errorlevel 1 goto :failed
echo.
echo SUCCESS: dist\COVERAGEDIAGRAMS\COVERAGEDIAGRAMS.exe
echo Copy the ENTIRE dist\COVERAGEDIAGRAMS folder, not just the EXE.
pause
exit /b 0
:failed
echo ERROR: Build failed. Check messages above.
pause
exit /b 1
