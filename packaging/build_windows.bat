@echo off
rem Builds the Windows installer on a Windows PC.
rem Needs: Python 3.12 (python.org) and Inno Setup 6 (jrsoftware.org/isinfo.php).
cd /d "%~dp0\.."
python -m venv .buildenv || goto :err
call .buildenv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller || goto :err
pyinstaller packaging\BalajiXRays.spec --noconfirm --distpath dist --workpath build || goto :err
for /f %%v in ('python -c "import bethesda; print(bethesda.__version__)"') do set APPVER=%%v
"%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" /DAppVersion=%APPVER% packaging\installer.iss || goto :err
echo.
echo Done: dist\installer\BalajiXRays-Setup-%APPVER%.exe
pause
exit /b 0
:err
echo BUILD FAILED
pause
exit /b 1
