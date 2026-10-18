@echo off
setlocal
if not exist "%~dp0..\.venv\Scripts\sceneweaver-mcp.exe" (
  echo Run install-windows.cmd first. 1>&2
  exit /b 1
)
"%~dp0..\.venv\Scripts\sceneweaver-mcp.exe" serve
