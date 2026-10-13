@echo off
cd /d "%~dp0"
py -3.10 "%~dp0app.py"
if errorlevel 1 pause
