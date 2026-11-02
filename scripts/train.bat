@echo off
REM train.bat —— Jarvis 1.0 训练脚本（Windows）
REM
REM 用法：
REM   scripts\train.bat [--variant flash|pro|ultra] [--pb 0.5|1.0|3.0|5.0] [--moe] [--data <dir>]
setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
set ROOT=%SCRIPT_DIR%..
set VARIANT=flash
set PB=1.0
set MOE=
set DATA_DIR=%ROOT%\data

:parse
if "%~1"=="" goto :parsedone
if /i "%~1"=="--variant" (set VARIANT=%~2 & shift & shift & goto :parse)
if /i "%~1"=="--pb"      (set PB=%~2 & shift & shift & goto :parse)
if /i "%~1"=="--moe"     (set MOE=--moe & shift & goto :parse)
if /i "%~1"=="--data"    (set DATA_DIR=%~2 & shift & shift & goto :parse)
echo 未知参数: %~1
exit /b 1
:parsedone

if not defined RVDL_ROOT set RVDL_ROOT=%ROOT%\..\Ravendrel
set CLI=%RVDL_ROOT%\server\out\cli.js
if not exist "%CLI%" (
  echo [错误] 找不到 Ravendrel CLI：%CLI%
  echo        请先构建 Ravendrel（cd %RVDL_ROOT% ^&^& npm run build），或设 RVDL_ROOT。
  exit /b 1
)

if /i not "%VARIANT%"=="flash" if /i not "%VARIANT%"=="pro" if /i not "%VARIANT%"=="ultra" (
  echo [错误] --variant 必须是 flash^|pro^|ultra，得到 '%VARIANT%'
  exit /b 1
)
set CONFIG=%ROOT%\configs\%VARIANT%.json
if not exist "%CONFIG%" (
  echo [错误] 找不到配置 %CONFIG%
  exit /b 1
)
echo [Jarvis] 变体=%VARIANT%  pB=%PB%%MOE%

REM 校验训练数据
set HASDATA=
for /r "%DATA_DIR%" %%f in (*.txt *.md *.rvdl) do set HASDATA=1
if not defined HASDATA (
  echo [错误] 训练数据目录 %DATA_DIR% 为空或不存在（需要 .txt/.md/.rvdl 文本）。
  exit /b 1
)

REM 编译 Jarvis 模型
set MODEL=%ROOT%\models\jarvis_core.rvdl
set OUT_DIR=%ROOT%\out
if not exist "%OUT_DIR%" mkdir "%OUT_DIR%"
echo [Jarvis] 编译模型 %MODEL% ...
node "%CLI%" mmi "%MODEL%" -o "%OUT_DIR%\jarvis_%VARIANT%.rvdli"
if errorlevel 1 (
  echo [错误] 模型编译失败
  exit /b 1
)

REM 启动 Transmitter
set TRANSMITTER=%RVDL_ROOT%\runtime\build\transmitter.exe
if not exist "%TRANSMITTER%" (
  echo [提示] 找不到 Transmitter 二进制（%TRANSMITTER%）。
  echo        请先构建：cd %RVDL_ROOT%\runtime ^&^& cmake --build build --target transmitter
  exit /b 0
)
echo [Jarvis] 启动 Transmitter（训练）...
"%TRANSMITTER%"