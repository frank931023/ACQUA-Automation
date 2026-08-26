@echo off
rem ===========================================================
rem  ACQUA Automation launcher
rem
rem    run              start, open the browser, quit when idle
rem    run mock         same, without ACQUA (UI / flow only)
rem    run stay         start and keep running (no idle quit)
rem    run check        pre-flight checks only
rem    run stop         stop the running service
rem
rem  Idle quit: when no browser has talked to it for a while AND no
rem  test is running, the service exits and frees the port. Closing
rem  the page mid-run does NOT stop the run - that is deliberate.
rem ===========================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"
set "BACKEND=com"
set "PORT=5000"
set "IDLE=90"

rem The port can be overridden in .env - read it back so the
rem "already running" check and `run stop` look at the right one.
if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if /i "%%A"=="ACQUA_WEB_PORT" set "PORT=%%B"
  )
)

if not exist "%PY%" (
  echo.
  echo   Virtual environment not found: %PY%
  echo   Create it first - see SETUP.md, section 2.
  echo.
  exit /b 1
)

if /i "%~1"=="mock"  set "BACKEND=mock"
if /i "%~1"=="stay"  set "IDLE=0"
if /i "%~1"=="check" goto :check
if /i "%~1"=="stop"  goto :stop
if /i "%~1"=="help"  goto :usage
if /i "%~1"=="/?"    goto :usage

rem Refuse to start a second copy. Two instances on one port is a
rem silent mess: the second one dies, but you cannot tell which one
rem the browser is talking to.
netstat -ano | findstr /r /c:":%PORT% .*LISTENING" >nul 2>&1
if not errorlevel 1 (
  echo.
  echo   Port %PORT% is already in use - opening the page instead.
  start "" "http://127.0.0.1:%PORT%/acqua/"
  exit /b 0
)

rem Pre-flight. Exit code 1 = fatal, 2 = warnings only.
echo Checking...
"%PY%" tools\preflight.py --quiet
if errorlevel 2 goto :launch
if errorlevel 1 (
  echo.
  echo   Pre-flight failed. Fix the items above, then run again.
  echo   To start anyway:  .venv\Scripts\python.exe app.py --backend %BACKEND%
  echo.
  exit /b 1
)

:launch
echo.
echo   ACQUA Automation  [backend: %BACKEND%]
echo   http://127.0.0.1:%PORT%/acqua/
if "%IDLE%"=="0" (
  echo   Will keep running until you stop it.
) else (
  echo   Quits by itself after %IDLE%s idle, unless a test is running.
)
echo   Ctrl+C to stop now.
echo.

rem --open: app.py waits until the port answers, then opens the browser.
rem Doing that poll in cmd spawned a second console that echoed every
rem iteration into the log, and the quoting was a nightmare.
"%PY%" app.py --backend %BACKEND% --idle-exit %IDLE% --open
exit /b %errorlevel%

:check
"%PY%" tools\preflight.py
exit /b %errorlevel%

:stop
set "FOUND="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:":%PORT% .*LISTENING"') do (
  if not "%%P"=="0" (
    echo Stopping PID %%P ...
    taskkill /PID %%P /F >nul 2>&1
    set "FOUND=1"
  )
)
if defined FOUND (echo Stopped.) else (echo Nothing was listening on port %PORT%.)
exit /b 0

:usage
echo.
echo   run          start + open the browser, quits when idle
echo   run mock     same, without ACQUA
echo   run stay     start and keep running
echo   run check    pre-flight checks only
echo   run stop     stop the running service
echo.
exit /b 0
