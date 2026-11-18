@echo off
rem Universal Organiser installer for Windows: double-click, or run from a terminal. Options are passed on (-Yes -NoStart -Autostart -Dir).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
