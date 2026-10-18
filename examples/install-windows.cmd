@echo off
setlocal
cd /d "%~dp0.." || exit /b 1
py -3 -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11 or newer is required'" || exit /b 1
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install --upgrade pip || exit /b 1
if exist "sceneweaver_mcp-0.1.0-py3-none-any.whl" (
  ".venv\Scripts\python.exe" -m pip install ".\sceneweaver_mcp-0.1.0-py3-none-any.whl[voice]" || exit /b 1
) else (
  ".venv\Scripts\python.exe" -m pip install ".[voice]" || exit /b 1
)
".venv\Scripts\sceneweaver-mcp.exe" doctor || exit /b 1
echo Installed. To download local voice models, run:
echo .venv\Scripts\sceneweaver-mcp.exe setup-voice
echo MCP launcher: %CD%\examples\run-windows.cmd
