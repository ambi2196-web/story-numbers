"""Claude via the Claude Code CLI in headless mode, billed to the user's Claude Pro plan.

Local / personal use only: it needs the CLI installed and logged in on this machine.
"""
import json
import os
import shutil
import subprocess
import tempfile

from app.llm.base import LLMError, LLMProvider


def claude_cli_path() -> str | None:
    return shutil.which("claude")


class ClaudeCLIProvider(LLMProvider):
    name = "claude_cli"

    def __init__(self, model: str = "sonnet", timeout: int = 180, allow_web: bool = False):
        exe = claude_cli_path()
        if not exe:
            raise LLMError("Claude Code CLI not found. Install it and run `claude` once to log in.")
        self.exe = exe
        self.model = model
        self.timeout = timeout
        self.allow_web = allow_web

    def complete(self, prompt: str, system: str | None = None, json_mode: bool = False) -> str:
        cmd = [self.exe, "-p", "--output-format", "json", "--model", self.model, "--no-session-persistence",
               "--tools", "WebSearch,WebFetch" if self.allow_web else ""]
        if system:
            cmd += ["--system-prompt", system]

        # Use the logged-in Pro subscription, never an API key that would bill separately, and drop
        # variables inherited from a parent Claude Code session (e.g. the desktop app during development),
        # which would otherwise switch the child CLI to API-key-only auth.
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("CLAUDE_CODE_", "CLAUDE_AGENT_SDK_"))
               and k not in ("CLAUDECODE", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL")}

        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                                  timeout=self.timeout, env=env, cwd=tempfile.gettempdir())
        except subprocess.TimeoutExpired as exc:
            raise LLMError(f"Claude CLI timed out after {self.timeout}s") from exc

        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Claude CLI failed (exit {proc.returncode}): {(proc.stderr or proc.stdout)[:500]}") from exc
        if payload.get("is_error"):
            raise LLMError(f"Claude CLI error: {payload.get('result', '')[:500]}")
        return payload.get("result", "")
