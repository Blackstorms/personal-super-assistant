@echo off
setlocal EnableExtensions
rem Windows entry for desktop installer. Bypasses PowerShell ExecutionPolicy.
cd /d "%~dp0\.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-desktop.ps1" %*
exit /b %ERRORLEVEL%
