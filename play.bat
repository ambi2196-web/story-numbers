@echo off
rem Double-click to play Story <-> Numbers on this computer, using Claude (your Claude Pro plan) for the AI.
rem The app opens in your browser at http://localhost:8501 (or the next free port). Close this window to stop it.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo The Python environment is missing. Run the setup steps in README.md first.
    pause
    exit /b 1
)
where claude >nul 2>nul
if errorlevel 1 (
    echo The Claude CLI was not found, so the app will use Gemini if GEMINI_API_KEY is set in .env.
    set LLM_PROVIDER=auto
) else (
    set LLM_PROVIDER=claude_cli
)
".venv\Scripts\python.exe" -m streamlit run app\ui\streamlit_app.py --server.headless false
pause
