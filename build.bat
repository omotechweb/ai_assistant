@echo off
REM ==================================================================
REM  YamanAI - Nuitka build script
REM  Put this file next to ai_assistant.py and requirements.txt,
REM  then double-click it (or run it from a command prompt).
REM
REM  It uses a Python 3.13 virtual environment in the "venv" folder and
REM  creates it automatically (PyAudio has no Windows build for 3.14 yet).
REM ==================================================================
setlocal
cd /d "%~dp0"

set "ICON=C:\YamanAIapp\ico\icon.ico"
set "MAIN=ai_assistant.py"
set "VERSION=1.0.0.0"
set "VENV_DIR=%~dp0venv"
set "VENV_PY=%~dp0venv\Scripts\python.exe"

REM Optional: full path of a python.exe (3.13 or older) to skip the automatic venv,
REM e.g.  set PYTHON_EXE=C:\Python313\python.exe
set "PYTHON_EXE="

if not exist "%ICON%" (
    echo [ERROR] Icon not found: %ICON%
    goto :failed
)
if not exist "%MAIN%" (
    echo [ERROR] %MAIN% not found in %CD%
    goto :failed
)

REM ------------------------------------------------------------------
REM  Choose Python
REM ------------------------------------------------------------------
set PY=
if defined PYTHON_EXE if exist "%PYTHON_EXE%" set PY="%PYTHON_EXE%"
if defined PY goto :check_version

if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import sys; sys.exit(0 if sys.version_info < (3, 14) else 1)"
    if not errorlevel 1 (
        set PY="%VENV_PY%"
        goto :check_version
    )
    echo The existing venv uses Python 3.14 or newer, which PyAudio does not support yet.
    echo It will be replaced with a Python 3.13 venv.
    echo.
)
call :make_venv
if errorlevel 1 goto :failed
set PY="%VENV_PY%"

:check_version
echo.
echo Using Python: %PY%
%PY% --version
if errorlevel 1 goto :failed
%PY% -c "import sys; sys.exit(0 if sys.version_info < (3, 14) else 1)"
if errorlevel 1 (
    echo [ERROR] This Python is 3.14 or newer. PyAudio has no Windows build for it yet.
    echo  Clear PYTHON_EXE at the top of this file to let the script create a 3.13 venv.
    goto :failed
)

REM ------------------------------------------------------------------
REM  Build
REM ------------------------------------------------------------------
echo.
echo [1/3] Installing dependencies and Nuitka...
%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt
if errorlevel 1 goto :failed
%PY% -m pip install --upgrade nuitka ordered-set zstandard
if errorlevel 1 goto :failed

echo.
echo [2/3] Generating the Windows speech wrapper used by pyttsx3...
REM pyttsx3 creates this module on first use. Generating it now lets
REM Nuitka bundle it, so Text-to-Speech also works in the .exe.
%PY% -c "import comtypes.client as cc; cc.CreateObject('SAPI.SpVoice'); from comtypes.gen import SpeechLib; print('SpeechLib OK')"
if errorlevel 1 goto :failed

echo.
echo [3/3] Compiling YamanAI (the first build can take 10-30 minutes)...
REM openai, httpx2, anyio and pydantic load parts of themselves at runtime with
REM importlib, which Nuitka cannot see; --include-package bundles them fully.
%PY% -m nuitka ^
    --mode=standalone ^
    --assume-yes-for-downloads ^
    --windows-console-mode=disable ^
    --enable-plugins=pyqt6 ^
    --include-package-data=qtawesome ^
    --include-package-data=speech_recognition ^
    --include-package-data=certifi ^
    --include-package=openai ^
    --include-package=httpx2 ^
    --include-package=httpcore2 ^
    --include-package=anyio ^
    --include-package=pydantic ^
    --include-module=pyttsx3.drivers.sapi5 ^
    --include-package=comtypes.gen ^
    --windows-icon-from-ico="%ICON%" ^
    --include-data-files="%ICON%=icon.ico" ^
    --output-dir=build ^
    --output-filename=YamanAI.exe ^
    --product-name=YamanAI ^
    --file-description=YamanAI ^
    --company-name=YamanAI ^
    --file-version=%VERSION% ^
    --product-version=%VERSION% ^
    --remove-output ^
    "%MAIN%"
if errorlevel 1 goto :failed

echo.
echo ==================================================================
echo  Build finished:
echo  %CD%\build\ai_assistant.dist\YamanAI.exe
echo  Share or zip the whole "ai_assistant.dist" folder, not just the .exe.
echo ==================================================================
pause
exit /b 0

REM ------------------------------------------------------------------
REM  Creates venv\ with Python 3.13 (installs 3.13 first if needed).
REM  The new "py" install manager can report success even when it fails,
REM  so every step is checked by its real output or by files on disk.
REM ------------------------------------------------------------------
:make_venv
where py >nul 2>&1
if errorlevel 1 (
    echo [ERROR] The "py" launcher was not found.
    echo  Install Python 3.13 from https://www.python.org/downloads/windows/ and run this file again.
    exit /b 1
)
call :probe_313
if not defined HAS313 (
    echo Python 3.13 is not installed. Installing it now...
    py install 3.13
    call :probe_313
)
if not defined HAS313 (
    echo.
    echo [ERROR] Python 3.13 could not be installed automatically.
    echo  Install it manually with ONE of these, then run this file again:
    echo    - In a command prompt:  py install 3.13
    echo    - Or download "Python 3.13" from https://www.python.org/downloads/windows/
    exit /b 1
)
if exist "%VENV_DIR%" (
    echo Removing the old venv...
    rmdir /s /q "%VENV_DIR%"
)
if exist "%VENV_DIR%" (
    echo [ERROR] The old venv folder could not be deleted because a program is using it.
    echo  Close YamanAI, VS Code / PyCharm terminals and any command prompts that use it, then try again.
    exit /b 1
)
echo Creating a new venv with Python 3.13...
py -3.13 -m venv "%VENV_DIR%"
if not exist "%VENV_PY%" (
    echo [ERROR] The venv was not created. See the message above.
    exit /b 1
)
exit /b 0

REM Sets HAS313=1 only if Python 3.13 really runs and prints the expected text
:probe_313
set "HAS313="
for /f "delims=" %%V in ('py -3.13 -c "import sys; print('PY313' if sys.version_info[:2] == (3, 13) else 'NO')" 2^>nul') do (
    if "%%V"=="PY313" set "HAS313=1"
)
exit /b 0

:failed
echo.
echo [ERROR] Build failed. Scroll up to see the first error message.
pause
exit /b 1