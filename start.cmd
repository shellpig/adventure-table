@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

set "DOCKER_EXE="
where docker >nul 2>&1
if not errorlevel 1 set "DOCKER_EXE=docker"
if defined DOCKER_EXE goto docker_cli_found

set "DOCKER_EXE=%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin\docker.exe"
if exist "!DOCKER_EXE!" goto docker_cli_found

set "DOCKER_EXE=C:\Program Files\Docker\Docker\resources\bin\docker.exe"
if exist "!DOCKER_EXE!" goto docker_cli_found

echo Docker CLI was not found. Install Docker Desktop first.
exit /b 1

:docker_cli_found
"!DOCKER_EXE!" info >nul 2>&1
if errorlevel 1 (
    set "DOCKER_DESKTOP=%LOCALAPPDATA%\Programs\DockerDesktop\Docker Desktop.exe"
    if not exist "!DOCKER_DESKTOP!" (
        set "DOCKER_DESKTOP=C:\Program Files\Docker\Docker\Docker Desktop.exe"
    )
    if not exist "!DOCKER_DESKTOP!" (
        echo Docker Desktop was not found.
        exit /b 1
    )

    echo Starting Docker Desktop...
    start "" "!DOCKER_DESKTOP!"
    call :wait_for_docker
    if errorlevel 1 exit /b 1
)

:docker_ready
echo Starting Adventure Table...
"!DOCKER_EXE!" compose up -d --build
if errorlevel 1 (
    echo Adventure Table failed to start.
    exit /b 1
)

echo.
"!DOCKER_EXE!" compose ps
echo.
echo Waiting for Adventure Table Web...
call :wait_for_web
if errorlevel 1 exit /b 1

echo Adventure Table is ready:
echo   Web:     http://localhost:5173
echo   Backend: http://localhost:8000/health
echo.
echo Opening Adventure Table in your default browser...
start "" "http://localhost:5173"

endlocal
exit /b 0

:wait_for_docker
set /a ATTEMPT=0
:wait_for_docker_loop
timeout /t 2 /nobreak >nul
"!DOCKER_EXE!" info >nul 2>&1
if not errorlevel 1 exit /b 0
set /a ATTEMPT+=1
if !ATTEMPT! geq 30 (
    echo Docker Desktop did not become ready within 60 seconds.
    exit /b 1
)
goto wait_for_docker_loop

:wait_for_web
set /a ATTEMPT=0
:wait_for_web_loop
powershell.exe -NoProfile -Command "try { $response = Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:5173' -TimeoutSec 2; if ($response.StatusCode -eq 200) { exit 0 }; exit 1 } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 exit /b 0
set /a ATTEMPT+=1
if !ATTEMPT! geq 30 (
    echo Adventure Table Web did not become ready within 60 seconds.
    exit /b 1
)
timeout /t 2 /nobreak >nul
goto wait_for_web_loop
