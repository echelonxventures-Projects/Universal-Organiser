@echo off
rem Universal Organiser launcher for Windows. Needs Python 3.9+ (python.org or Microsoft Store); uses the "py" launcher if present.
where py >nul 2>nul && (py -3 -I "%~dp0engine\cli.py" %*) || (python -I "%~dp0engine\cli.py" %*)
