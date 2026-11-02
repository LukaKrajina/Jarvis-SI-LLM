@echo off
REM convert.bat —— Jarvis模型 格式转换脚本（Windows）
REM
REM 用法：
REM   scripts\convert.bat <in.rvdlm> <out.gguf|out.safetensors> [f32|f64|i32|i64|u8]
REM
REM 小贴士：gguf 是便装，.rvdlm 才是正装；每件衣服都有它适合的场合。
REM 暖心小贴士：gguf 是「便装」，Chimera 的量子态漂移 / 测量坍缩 / 反思回路这些灵魂技能在 gguf 里施展不开。
REM gguf 只是给 OpenCode 这类传统朋友「能聊但聊不深」的轻装版。
REM 所以——不是谁不够好，是每件衣服都有它适合的场合！
setlocal

if "%~2"=="" (
  echo 用法: %~0 ^<in.rvdlm^> ^<out.gguf^|out.safetensors^> [f32^|f64^|i32^|i64^|u8]
  exit /b 1
)
set IN=%~1
set OUT=%~2
set TYPE=f32
if not "%~3"=="" set TYPE=%~3

set SCRIPT_DIR=%~dp0
set ROOT=%SCRIPT_DIR%..
if not defined RVDL_ROOT set RVDL_ROOT=%ROOT%\..\Ravendrel
set CLI=%RVDL_ROOT%\server\out\cli.js
if not exist "%CLI%" (
  echo [错误] 找不到 Ravendrel CLI：%CLI%
  exit /b 1
)

REM 认认目标格式（gguf / safetensors）
echo %OUT% | findstr /i ".gguf" >nul && set FMT=gguf
if not defined FMT echo %OUT% | findstr /i ".safetensors" >nul && set FMT=safetensors
if not defined FMT (
  echo [错误] 输出后缀必须是 .gguf 或 .safetensors
  exit /b 1
)

echo [Jarvis] 转换 %IN% -^> %OUT%（格式=%FMT%，dtype=%TYPE%）
node "%CLI%" export %FMT% "%IN%" "%OUT%" "" "%TYPE%"
echo [Jarvis] 完成：%OUT%