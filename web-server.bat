@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0web-server.ps1" %*
