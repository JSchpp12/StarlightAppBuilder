@echo off
setlocal

REM Build a StarAppBuilder wheel inside a Docker builder image matching the
REM remote target. The builder image only provisions the toolchain; the actual
REM wheel build runs in a container with the project mounted at /work, so the
REM wheel lands directly in .\dist on the host.
REM
REM Usage:
REM   build_wheel.bat [target]    target defaults to "ubuntu"

if "%~1"=="" (
    set TARGET=ubuntu
) else (
    set TARGET=%~1
)

set IMAGE_TAG=starappbuilder-builder-%TARGET%
set DOCKERFILE=dist\Dockerfile.%TARGET%

if not exist "%DOCKERFILE%" (
    echo No Dockerfile for target '%TARGET%' ^(looked for %DOCKERFILE%^).
    echo Available targets:
    for %%f in (dist\Dockerfile.*) do echo   %%~nxf
    exit /b 1
)

echo ==^> Ensuring BasisUniversal submodule is present
git submodule update --init -- extern/BasisUniversal
if errorlevel 1 goto :fail

echo ==^> Building builder image: %IMAGE_TAG% (%DOCKERFILE%)
docker build -t %IMAGE_TAG% - < %DOCKERFILE%
if errorlevel 1 goto :fail

echo ==^> Building wheel inside container (project mounted at /work)
set HOSTDIR=%CD%
set HOSTDIR=%HOSTDIR:\=/%
docker run --rm -v "%HOSTDIR%:/work" %IMAGE_TAG% sh /work/dist/build_inside.sh
if errorlevel 1 goto :fail

echo ==^> Done. Wheel(s) in .\dist:
dir /b dist\*.whl
goto :eof

:fail
echo Build failed.
exit /b 1