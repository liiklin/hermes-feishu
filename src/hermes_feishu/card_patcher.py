"""Gateway monkey-patch for FeishuAdapter — wraps text replies as interactive cards.

This module contains the card-building logic and the gateway patcher function.
The hermes-feishu plugin auto-deploys a thin gateway hook (feishu-card-wrapper)
that imports this module and calls ``patch_gateway()`` on startup.

All versions live in the plugin, so ``hermes plugins upgrade`` keeps everything
in sync across machines.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("hermes_feishu.card_patcher")

_PATCHED = False
_original_build_outbound_payload: Optional[Callable] = None


# ---------------------------------------------------------------------------
# Gateway patcher
# ---------------------------------------------------------------------------


def patch_gateway() -> None:
    """Monkey-patch FeishuAdapter._build_outbound_payload in the gateway process.

    Call this from a ``gateway:startup`` hook handler.  Idempotent.
    Saves the original method so short/simple messages can fall through
    as plain post messages instead of getting card-wrapped.
    """
    global _PATCHED, _original_build_outbound_payload
    if _PATCHED:
        return
    try:
        hermes_home = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
        agent_root = os.path.join(hermes_home, "hermes-agent")
        if agent_root not in sys.path:
            sys.path.insert(0, agent_root)

        from gateway.platforms.feishu import FeishuAdapter  # type: ignore[import-untyped]

        _original_build_outbound_payload = FeishuAdapter._build_outbound_payload
        FeishuAdapter._build_outbound_payload = _build_card_payload

        _PATCHED = True
        print(
            f"[hermes-feishu] Patched FeishuAdapter._build_outbound_payload "
            f"→ card wrapper (was {_original_build_outbound_payload.__module__}."
            f"{_original_build_outbound_payload.__qualname__})",
            flush=True,
        )
    except Exception as exc:
        print(
            f"[hermes-feishu] Failed to patch FeishuAdapter._build_outbound_payload: {exc}",
            flush=True,
        )


# ---------------------------------------------------------------------------
# Heuristic: is this content worth wrapping in a card?
# ---------------------------------------------------------------------------


def _is_complex_markdown(text: str) -> bool:
    """Return True when ``text`` has formatting that needs a card (not just a post).

    Short status messages (tool progress, simple confirmations) pass through
    as plain text.  Only wrap when there's actual rich content.
    """
    # Very short messages are tool status / intermediate updates — skip
    if len(text) < 80:
        return False

    # Check for complex markdown patterns
    patterns = [
        r"^##\s+",             # H2 heading (would become card header)
        r"^#{3,6}\s+",         # H3–H6 (would become bold)
        r"^\|.+\|$",           # table row
        r"^```",               # code block
        r"^-\s+",              # unordered list
        r"^\d+\.\s+",          # ordered list
        # NOTE: blockquote (^>.+) intentionally omitted — Feishu post with
        # lark_md tag already renders > blockquotes correctly; the card
        # markdown tag does not support them.
    ]
    for p in patterns:
        if re.search(p, text, re.MULTILINE):
            return True

    return False


# ---------------------------------------------------------------------------
# Blockquote handling — Feishu card markdown doesn't support >
# ---------------------------------------------------------------------------


def _strip_blockquotes(text: str) -> str:
    """Wrap consecutive blockquote lines in fenced code blocks.

    Feishu card's ``markdown`` tag does not render ``>`` blockquotes.
    Wrapping consecutive quoted lines in ```...``` gives them a visible
    gray-background block that visually separates quoted content.
    """
    lines = text.split("\n")
    result: list[str] = []
    in_block = False
    for line in lines:
        m = re.match(r"^>\s?(.*)", line)
        if m:
            if not in_block:
                result.append("```")
                in_block = True
            result.append(m.group(1))
        else:
            if in_block:
                result.append("```")
                in_block = False
            result.append(line)
    if in_block:
        result.append("```")
    return "\n".join(result)


# ---------------------------------------------------------------------------
# Card building
# ---------------------------------------------------------------------------


def _build_card_payload(self: object, content: str) -> tuple:
    """Patched ``_build_outbound_payload`` — card wrapping with smart fallback.

    Short or simple-content outbound messages are forwarded to the original
    ``_build_outbound_payload`` so tool-status updates stay lean.  Only
    messages with complex markdown (headings, tables, code blocks, lists) are
    wrapped in interactive cards.

    Args:
        self: FeishuAdapter instance (for compatibility).
        content: The message text (may include footer after ``───``).

    Returns:
        Tuple of ``(type, payload_string)``.
    """

    # ── Smart fallback ───────────────────────────────────────────────────
    # Short/simple messages → original post (no card, no clutter)
    if _original_build_outbound_payload and not _is_complex_markdown(content):
        # Strip any footer that transform_llm_output appended
        clean = re.sub(r"\n───\n.*", "", content, flags=re.DOTALL).strip()
        return _original_build_outbound_payload(self, clean)

    # ── Card wrapping ────────────────────────────────────────────────────
    # Separate main content from footer
    footer_text = ""
    main_content = content
    sep = "\n───\n"
    if sep in content:
        main_content, footer_text = content.rsplit(sep, 1)
        footer_text = footer_text.strip()

    # 1. Extract first heading as card header title
    H1_EMOJI = "📌"
    HEADING_EMOJI = {1: "📌", 2: "📍", 3: "🔹", 4: "🔸", 5: "▫️", 6: "▪️"}
    title: Optional[str] = None
    h1_match = re.search(r"^#\s+(.+)", main_content, re.MULTILINE)
    if h1_match:
        title = f"{H1_EMOJI} {h1_match.group(1).strip()}"
    # All headings (H1-H6) → emoji + bold in body
    main_content = re.sub(
        r"^(#)\s+(.+)",  # H1
        lambda m: f"**{HEADING_EMOJI[1]} {m.group(2)}**",
        main_content,
        flags=re.MULTILINE,
    )
    main_content = re.sub(
        r"^(##)(?!#)\s+(.+)",  # H2 (exact, not ###)
        lambda m: f"**{HEADING_EMOJI[2]} {m.group(2)}**",
        main_content,
        flags=re.MULTILINE,
    )
    main_content = re.sub(
        r"^(###)(?!#)\s+(.+)",  # H3
        lambda m: f"**{HEADING_EMOJI[3]} {m.group(2)}**",
        main_content,
        flags=re.MULTILINE,
    )
    main_content = re.sub(
        r"^(#{4,6})\s+(.+)",  # H4-H6
        lambda m: f"**{HEADING_EMOJI.get(len(m.group(1)), '📌')} {m.group(2)}**",
        main_content,
        flags=re.MULTILINE,
    ).strip()

    # 3. Strip blockquotes — Feishu card markdown doesn't support >
    main_content = _strip_blockquotes(main_content)

    # 4. Build card (table-aware when possible)
    card = _build_card_via_plugin(main_content, title=title)
    if card is None:
        card = _build_simple_card(main_content, title=title)

    # 4. Append footer
    if footer_text:
        card.setdefault("elements", []).append({
            "tag": "markdown",
            "content": f"───\n{footer_text}",
        })

    return "interactive", json.dumps(card, ensure_ascii=False)


def _build_card_via_plugin(
    markdown: str,
    title: Optional[str] = None,
    template: str = "blue",
) -> Optional[Dict[str, Any]]:
    """Try the plugin's ``card_builder`` (table-aware).  Returns ``None`` on failure."""
    try:
        from hermes_feishu.card_builder import build_content_card, build_mixed_card
        from hermes_feishu.table_parser import contains_table

        has_tables = contains_table(markdown)
        card: Optional[Dict[str, Any]] = None

        if has_tables:
            card = build_mixed_card(markdown, title=title, template=template)

        if card is None:
            card = build_content_card(markdown, title=title, template=template)

        return card
    except Exception as exc:
        logger.debug("Plugin card builder unavailable: %s", exc)
        return None


def _build_simple_card(
    content: str,
    title: Optional[str] = None,
    template: str = "blue",
) -> Dict[str, Any]:
    """Fallback: plain markdown card when the builder plugin isn't reachable."""
    card: Dict[str, Any] = {
        "config": {"wide_screen_mode": True},
    }
    if title:
        card["header"] = {
            "title": {"content": title, "tag": "plain_text"},
            "template": template,
        }
    card["elements"] = [{"tag": "markdown", "content": content}]
    return card
