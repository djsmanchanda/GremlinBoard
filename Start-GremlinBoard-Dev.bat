@echo off
setlocal
cd /d "%~dp0"
rem Launch the tray detached with a hidden window so no cmd console lingers
rem for the tray's lifetime; this window closes immediately.
start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -STA -File "%~dp0scripts\gremlinboard-tray.ps1" -Mode dev
