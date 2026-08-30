@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "DOCKER_EXE="
where docker >nul 2>&1
if not errorlevel 1 set "DOCKER_EXE=docker"
if defined DOCKER_EXE goto docker_cli_found

set "DOCKER_EXE=%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin\docker.exe"
if exist "%DOCKER_EXE%" goto docker_cli_found

set "DOCKER_EXE=C:\Program Files\Docker\Docker\resources\bin\docker.exe"
if exist "%DOCKER_EXE%" goto docker_cli_found

echo Docker CLI was not found. Adventure Table cannot be running through Docker.
exit /b 0

:docker_cli_found
"%DOCKER_EXE%" info >nul 2>&1
if errorlevel 1 (
    echo Docker Desktop is not running. Adventure Table is already stopped.
    exit /b 0
)

echo Stopping Adventure Table...
"%DOCKER_EXE%" compose down
if errorlevel 1 (
    echo Adventure Table failed to stop cleanly.
    exit /b 1
)

echo Adventure Table stopped. PostgreSQL data was preserved.

endlocal
