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
from typing import Any, Dict, Optional

logger = logging.getLogger("hermes_feishu.card_patcher")

_PATCHED = False


def patch_gateway() -> None:
    """Monkey-patch FeishuAdapter._build_outbound_payload in the gateway process.

    Call this from a ``gateway:startup`` hook handler.  Idempotent.
    """
    global _PATCHED
    if _PATCHED:
        return
    try:
        hermes_home = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
        agent_root = os.path.join(hermes_home, "hermes-agent")
        if agent_root not in sys.path:
            sys.path.insert(0, agent_root)

        from gateway.platforms.feishu import FeishuAdapter  # type: ignore[import-untyped]

        original = FeishuAdapter._build_outbound_payload
        FeishuAdapter._build_outbound_payload = _build_card_payload

        _PATCHED = True
        print(
            f"[hermes-feishu] Patched FeishuAdapter._build_outbound_payload "
            f"→ card wrapper (was {original.__module__}.{original.__qualname__})",
            flush=True,
        )
    except Exception as exc:
        print(
            f"[hermes-feishu] Failed to patch FeishuAdapter._build_outbound_payload: {exc}",
            flush=True,
        )


# ---------------------------------------------------------------------------
# Card building
# ---------------------------------------------------------------------------


def _build_card_payload(self: object, content: str) -> tuple:
    """Patched ``_build_outbound_payload`` — structured card with header/table support.

    Args:
        self: FeishuAdapter instance (unused, for method-signature compat).
        content: The message text (may include footer after ``───``).

    Returns:
        Tuple of (``"interactive"``, ``card_json_string``).
    """

    # Separate main content from footer
    footer_text = ""
    main_content = content
    sep = "\n───\n"
    if sep in content:
        main_content, footer_text = content.rsplit(sep, 1)
        footer_text = footer_text.strip()

    # ── Heading processing ──────────────────────────────────────────────
    # 1. Extract first ``## Title`` as card header title
    title: Optional[str] = None
    h2_match = re.search(r"^##\s+(.+)", main_content, re.MULTILINE)
    if h2_match:
        title = h2_match.group(1).strip()
        main_content = re.sub(
            r"^##\s+.+\n?", "", main_content, count=1, flags=re.MULTILINE
        ).strip()

    # 2. Convert ``###`` … ``######`` headings → **bold** text
    main_content = re.sub(
        r"^#{3,6}\s+(.+)\n?",
        r"**\1**\n",
        main_content,
        flags=re.MULTILINE,
    ).strip()

    # ── Build card ──────────────────────────────────────────────────────
    # Try plugin's own card_builder first (handles tables), fallback to simple
    card = _build_card_via_plugin(main_content, title=title)
    if card is None:
        card = _build_simple_card(main_content, title=title)

    # ── Append footer ───────────────────────────────────────────────────
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
