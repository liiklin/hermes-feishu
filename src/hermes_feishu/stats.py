"""API call stats — module-level variables for in-process sharing.

post_api_request and transform_llm_output run in the same Hermes agent
session process, so a module-level dict is all we need.  No os.environ
trickery required.

The previous os.environ-based approach was conceptually wrong:
os.environ is per-process and is NEVER a cross-process transport on
any OS (Linux, macOS, or Windows).
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

# Module-level state — shared by reference within the same process.
_stats: Dict[str, Any] = {}


def update(
    model: str = "",
    provider: str = "",
    usage: Any = None,
    api_duration: float = 0.0,
    base_url: str = "",
) -> None:
    """Store latest API call metadata in module-level dict.

    Args:
        model: Model name (e.g. "deepseek-v4-flash").
        provider: Provider name (e.g. "opencode-go").
        usage: Dict or object with prompt_tokens / output_tokens / total_tokens.
        api_duration: API call duration in seconds.
        base_url: API base URL (optional).
    """
    global _stats
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

    _stats = {
        "model": model or "",
        "provider": provider or "",
        "prompt": prompt,
        "completion": completion,
        "total": total,
        "duration": api_duration,
        "updated_at": time.time(),
    }


def build_footer() -> str:
    """Build a markdown footer line from module-level API stats.

    Returns:
        "🤖 opencode-go/deepseek-v4-flash  |  💬 135,583↑ 992↓  |  ⏱ 10.8s  |  🕐 14:30:25"
    """
    global _stats
    model = _stats.get("model", "")
    provider = _stats.get("provider", "")
    prompt = _stats.get("prompt", 0)
    completion = _stats.get("completion", 0)
    total = _stats.get("total", 0)
    duration = _stats.get("duration", 0.0)

    parts: list[str] = []

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
