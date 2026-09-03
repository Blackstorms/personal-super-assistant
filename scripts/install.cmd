@echo off
setlocal EnableExtensions
rem Windows entry for one-click deploy. Bypasses PowerShell ExecutionPolicy.
cd /d "%~dp0\.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
exit /b %ERRORLEVEL%
