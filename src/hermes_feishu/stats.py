"""API call stats — stored via os.environ to survive process boundaries.

Hermes gateway may run the agent conversation loop and plugin tools in
separate processes (subprocess). Module-level variables are NOT shared.
os.environ propagates to child processes via fork/exec, so using it as
the transport ensures stats survive process boundaries.

The post_api_request hook writes stats to env vars.
The tool handler reads them and builds the footer.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

# Env var keys
_ENV_MODEL = "_HERMES_FOOTER_MODEL"
_ENV_PROVIDER = "_HERMES_FOOTER_PROVIDER"
_ENV_PROMPT = "_HERMES_FOOTER_PROMPT_TOKENS"
_ENV_COMPLETION = "_HERMES_FOOTER_COMPLETION_TOKENS"
_ENV_TOTAL = "_HERMES_FOOTER_TOTAL_TOKENS"
_ENV_DURATION = "_HERMES_FOOTER_API_DURATION"
_ENV_TIMESTAMP = "_HERMES_FOOTER_UPDATED_AT"


def update(
    model: str = "",
    provider: str = "",
    usage: Any = None,
    api_duration: float = 0.0,
    base_url: str = "",
) -> None:
    """Store latest API call metadata in os.environ (cross-process safe).

    Args:
        model: Model name (e.g. "deepseek-v4-flash").
        provider: Provider name (e.g. "opencode-go").
        usage: Dict or object with prompt_tokens / output_tokens / total_tokens.
        api_duration: API call duration in seconds.
        base_url: API base URL (optional).
    """
    prompt = 0
    completion = 0
    total = 0
    if usage is not None and isinstance(usage, dict):
        prompt = usage.get("prompt_tokens", 0) or 0
        completion = usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0
        total = usage.get("total_tokens", 0) or (prompt + completion)
    elif usage is not None:
        prompt = getattr(usage, "prompt_tokens", 0) or 0
        completion = getattr(usage, "output_tokens", getattr(usage, "completion_tokens", 0)) or 0
        total = getattr(usage, "total_tokens", 0) or (prompt + completion)

    os.environ[_ENV_MODEL] = model or ""
    os.environ[_ENV_PROVIDER] = provider or ""
    os.environ[_ENV_PROMPT] = str(prompt)
    os.environ[_ENV_COMPLETION] = str(completion)
    os.environ[_ENV_TOTAL] = str(total)
    os.environ[_ENV_DURATION] = f"{api_duration:.2f}"
    os.environ[_ENV_TIMESTAMP] = str(time.time())


def build_footer() -> str:
    """Build a markdown footer line from env-var-passed API stats.

    Returns:
        "🤖 opencode-go/deepseek-v4-flash  |  💬 135,583↑ 992↓  |  ⏱ 10.8s  |  🕐 14:30:25"
    """
    model = os.environ.get(_ENV_MODEL, "")
    provider = os.environ.get(_ENV_PROVIDER, "")

    prompt_s = os.environ.get(_ENV_PROMPT, "0")
    completion_s = os.environ.get(_ENV_COMPLETION, "0")
    total_s = os.environ.get(_ENV_TOTAL, "0")
    duration_s = os.environ.get(_ENV_DURATION, "0")

    prompt = int(prompt_s) if prompt_s.isdigit() else 0
    completion = int(completion_s) if completion_s.isdigit() else 0
    total = int(total_s) if total_s.isdigit() else 0
    duration = float(duration_s) if duration_s else 0.0

    parts = []  # Will hold sub-parts for line 2 (tokens + duration)

    # Line 1: Model badge
    label = ""
    if model:
        label = f"{provider}/{model}" if provider else model

    # Line 2 parts: Token count
    if total:
        parts.append(f"💬 {prompt:,}⬆️ {completion:,}⬇️")

    # API duration
    if duration:
        parts.append(f"⏱ {duration:.1f}s")

    # Wall-clock reply time — line 3 with calendar emoji
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    time_str = now.strftime('%Y-%m-%d %H:%M:%S')

    if not label and not parts:
        return ""

    lines = []
    if label:
        lines.append(f"🤖 {label}")
    if parts:
        lines.append(" | ".join(parts))
    lines.append(f"📅 {time_str}")

    return "\n".join(lines)
