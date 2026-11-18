@echo off
setlocal
set "PYTHONPATH=%~dp0..;%PYTHONPATH%"
py -3 -m branch_guard %*
exit /b %ERRORLEVEL%
