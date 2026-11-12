@echo off
call "%~dp0start-radio.cmd" --codex %*
exit /b %errorlevel%
