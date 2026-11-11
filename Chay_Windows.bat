@echo off
rem Dich Video Studio - tep khoi dong cho Windows. Bam dup de chay.
rem Lan dau: tu tai cong cu uv, tao moi truong Python 3.12 rieng trong thu muc nay va cai thu vien.
setlocal EnableExtensions
chcp 65001 >nul 2>nul
title Dich Video Studio
cd /d "%~dp0"
set "ROOT=%~dp0"
set "UV=%ROOT%runtime\uv.exe"
set "PY=%ROOT%.venv\Scripts\python.exe"
set "DVS_ROOT=%ROOT%"

if exist "%PY%" goto have_venv

echo.
echo  === Dich Video Studio: cai dat lan dau - can mang, mat vai phut ===
echo.

if exist "%UV%" goto have_uv
where uv >nul 2>nul
if errorlevel 1 goto download_uv
set "UV=uv"
goto have_uv

:download_uv
echo  Dang tai cong cu cai dat uv...
if not exist "%ROOT%runtime" mkdir "%ROOT%runtime"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $z=Join-Path $env:TEMP 'uv-dvs.zip'; Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' -OutFile $z; Expand-Archive -Force -LiteralPath $z -DestinationPath (Join-Path $env:DVS_ROOT 'runtime'); Remove-Item -LiteralPath $z"
if exist "%UV%" goto have_uv
echo  Khong tai duoc uv. Thu dung Python co san tren may...
goto system_python

:have_uv
echo  Dang tao moi truong Python 3.12...
"%UV%" venv --python 3.12 "%ROOT%.venv"
if exist "%PY%" goto have_venv
echo  Khong tao duoc moi truong bang uv. Thu dung Python co san tren may...

:system_python
py -3.12 -m venv "%ROOT%.venv" >nul 2>nul
if exist "%PY%" goto have_venv
py -3.13 -m venv "%ROOT%.venv" >nul 2>nul
if exist "%PY%" goto have_venv
python -m venv "%ROOT%.venv" >nul 2>nul
if exist "%PY%" goto have_venv
echo.
echo  [LOI] Khong tao duoc moi truong Python.
echo  Hay cai Python 3.12 tu https://www.python.org/downloads/
echo  Khi cai nho tich o "Add python.exe to PATH", roi chay lai tep nay.
echo.
pause
exit /b 1

:have_venv
"%PY%" "%ROOT%tools\bootstrap.py" --uv "%UV%"
if errorlevel 1 goto deps_failed
"%PY%" "%ROOT%run.py" %*
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" pause
exit /b %CODE%

:deps_failed
echo.
echo  [LOI] Cai thu vien chua xong. Kiem tra mang roi chay lai tep nay.
echo.
pause
exit /b 1
