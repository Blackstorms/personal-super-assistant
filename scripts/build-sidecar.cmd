@echo off
setlocal EnableExtensions
rem Windows entry for sidecar build. Bypasses PowerShell ExecutionPolicy.
cd /d "%~dp0\.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-sidecar.ps1" %*
exit /b %ERRORLEVEL%
