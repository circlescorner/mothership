@echo off
REM Fix Python path issues by creating a python.bat in a directory that's in PATH

echo Setting up Python command alias...

REM Find Python installation
set "PYTHON_DIR=C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python314"
if not exist "%PYTHON_DIR%\python.exe" (
    echo Python not found at %PYTHON_DIR%
    echo Searching for Python installation...
    for /f "delims=" %%i in ('where python.exe 2^>nul') do (
        set "PYTHON_DIR=%%~dpi"
        goto :found
    )
    for /f "delims=" %%i in ('where py.exe 2^>nul') do (
        set "PY_EXE=%%i"
        goto :use_py
    )
    echo Python not found! Please install Python first.
    exit /b 1
)

:found
echo Found Python at: %PYTHON_DIR%

REM Add Python to user PATH if not already there
echo %PATH% | find /i "%PYTHON_DIR%" >nul
if errorlevel 1 (
    echo Adding Python to PATH...
    setx PATH "%PATH%;%PYTHON_DIR%;%PYTHON_DIR%\Scripts" >nul 2>&1
    echo Python added to PATH. Please restart your terminal.
)

REM Create python.bat in a location that's likely in PATH
if exist "%LOCALAPPDATA%\Microsoft\WindowsApps" (
    echo @echo off > "%LOCALAPPDATA%\Microsoft\WindowsApps\python.bat"
    echo "%PYTHON_DIR%\python.exe" %%* >> "%LOCALAPPDATA%\Microsoft\WindowsApps\python.bat"
    echo Created python.bat in WindowsApps
)

goto :done

:use_py
echo Using py launcher at: %PY_EXE%

REM Create python.bat that uses py
echo @echo off > "%LOCALAPPDATA%\Microsoft\WindowsApps\python.bat"
echo py %%* >> "%LOCALAPPDATA%\Microsoft\WindowsApps\python.bat"
echo Created python.bat using py launcher

:done
echo.
echo Setup complete! You can now use 'python' command.
echo Please restart your terminal for changes to take effect.
pause
