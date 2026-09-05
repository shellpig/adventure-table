@echo off
setlocal EnableExtensions

set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
set "SERVER_DIR=%ROOT%\apps\server"
set "WEB_DIR=%ROOT%\apps\web"
set "VENV_DIR=%ROOT%\.standalone-venv"
set "CONSTRAINTS=%SERVER_DIR%\constraints-standalone-win.txt"
set "ENV_CHECK=%ROOT%\scripts\check_standalone_env.py"
if not defined STANDALONE_PYTHON set "STANDALONE_PYTHON=python"
set "BUILD_DIR=%ROOT%\build\standalone"
set "DIST_DIR=%ROOT%\dist"
set "ARTIFACT_DIR=%DIST_DIR%\adventure-table-standalone"
set "VERSION=dev"
set "DRY_RUN=0"
set "SKIP_FRONTEND=0"

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--version" (
  if "%~2"=="" (
    echo ERROR: --version requires a value.
    exit /b 2
  )
  set "VERSION=%~2"
  shift
  shift
  goto parse_args
)
if /I "%~1"=="--dry-run" (
  set "DRY_RUN=1"
  shift
  goto parse_args
)
if /I "%~1"=="--skip-frontend" (
  set "SKIP_FRONTEND=1"
  shift
  goto parse_args
)
echo ERROR: unknown argument %~1
exit /b 2

:args_done
set "ZIP_PATH=%DIST_DIR%\adventure-table-standalone-%VERSION%.zip"
echo [M03-E] Adventure Table standalone build
 echo   version: %VERSION%
 echo   server:  %SERVER_DIR%
 echo   artifact:%ARTIFACT_DIR%
 echo   zip:     %ZIP_PATH%
 echo   frontend skipped: %SKIP_FRONTEND%

if "%DRY_RUN%"=="1" (
  echo [dry-run] remove previous venv/build/dist output
  echo [dry-run] "%STANDALONE_PYTHON%" -m venv "%VENV_DIR%"
  echo [dry-run] verify interpreter against "%CONSTRAINTS%"
  echo [dry-run] pip install -c "%CONSTRAINTS%" --upgrade pip
  echo [dry-run] pip install -e "%SERVER_DIR%[standalone]" -c "%CONSTRAINTS%" ^(no web extra^)
  echo [dry-run] verify installed versions against "%CONSTRAINTS%"
  if "%SKIP_FRONTEND%"=="0" echo [dry-run] npm ci ^&^& npm run build in "%WEB_DIR%"
  echo [dry-run] pyinstaller "%SERVER_DIR%\pyinstaller\standalone.spec"
  echo [dry-run] copy data/ and apps/web/dist/ beside adventure-table.exe
  echo [dry-run] copy LICENSE.txt and README-standalone.*.txt
  echo [dry-run] write build-id.txt = %VERSION%
  echo [dry-run] Compress-Archive to "%ZIP_PATH%"
  exit /b 0
)

if exist "%VENV_DIR%" rmdir /s /q "%VENV_DIR%"
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
if exist "%ARTIFACT_DIR%" rmdir /s /q "%ARTIFACT_DIR%"
if exist "%ZIP_PATH%" del /q "%ZIP_PATH%"

"%STANDALONE_PYTHON%" -m venv "%VENV_DIR%"
if errorlevel 1 goto fail
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
"%VENV_PY%" "%ENV_CHECK%" --constraints "%CONSTRAINTS%" --mode python
if errorlevel 1 goto fail
"%VENV_PY%" -m pip install -c "%CONSTRAINTS%" --upgrade pip
if errorlevel 1 goto fail
"%VENV_PY%" -m pip install -e "%SERVER_DIR%[standalone]" -c "%CONSTRAINTS%"
if errorlevel 1 goto fail
"%VENV_PY%" "%ENV_CHECK%" --constraints "%CONSTRAINTS%" --mode packages
if errorlevel 1 goto fail

if "%SKIP_FRONTEND%"=="0" (
  pushd "%WEB_DIR%"
  call npm ci
  if errorlevel 1 (
    popd
    goto fail
  )
  call npm run build
  if errorlevel 1 (
    popd
    goto fail
  )
  popd
) else (
  if not exist "%WEB_DIR%\dist\index.html" (
    echo ERROR: --skip-frontend requires an existing apps\web\dist build.
    goto fail
  )
)

set "ADVENTURE_TABLE_BUILD_ID=%VERSION%"
"%VENV_DIR%\Scripts\pyinstaller.exe" --noconfirm --clean --workpath "%BUILD_DIR%" --distpath "%DIST_DIR%" "%SERVER_DIR%\pyinstaller\standalone.spec"
if errorlevel 1 goto fail

powershell -NoProfile -Command "Copy-Item -Path '%ROOT%\data' -Destination '%ARTIFACT_DIR%\data' -Recurse -Force"
if errorlevel 1 goto fail
powershell -NoProfile -Command "Copy-Item -Path '%WEB_DIR%\dist' -Destination '%ARTIFACT_DIR%\web' -Recurse -Force"
if errorlevel 1 goto fail
copy /Y "%ROOT%\LICENSE.txt" "%ARTIFACT_DIR%\LICENSE.txt" >nul
if errorlevel 1 goto fail
copy /Y "%ROOT%\README-standalone.en.txt" "%ARTIFACT_DIR%\README-standalone.en.txt" >nul
if errorlevel 1 goto fail
copy /Y "%ROOT%\README-standalone.zh-TW.txt" "%ARTIFACT_DIR%\README-standalone.zh-TW.txt" >nul
if errorlevel 1 goto fail
>"%ARTIFACT_DIR%\build-id.txt" echo %VERSION%

powershell -NoProfile -Command "Compress-Archive -Path '%ARTIFACT_DIR%\*' -DestinationPath '%ZIP_PATH%' -Force"
if errorlevel 1 goto fail

echo [M03-E] Build complete: %ZIP_PATH%
exit /b 0

:fail
echo [M03-E] Build failed with errorlevel %errorlevel%.
exit /b 1
