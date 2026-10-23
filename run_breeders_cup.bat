@echo off
setlocal
rem Resolve paths from this file, regardless of Task Scheduler's working folder.
pushd "%~dp0" || exit /b 1
if not exist "logs" mkdir "logs"
if not exist "logs" (
    echo ERROR: Cannot create the logs folder.
    popd
    exit /b 1
)
echo [%DATE% %TIME%] Starting Breeders Cup update>>"logs\scheduled-run.log"
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Missing .venv. Follow the README setup steps.>>"logs\scheduled-run.log"
    popd
    exit /b 2
)
".venv\Scripts\python.exe" -u -m breeders_cup.cli update %* >>"logs\scheduled-run.log" 2>&1
set "RUN_EXIT=%ERRORLEVEL%"
echo [%DATE% %TIME%] Finished with exit code %RUN_EXIT% >>"logs\scheduled-run.log"
popd
exit /b %RUN_EXIT%
