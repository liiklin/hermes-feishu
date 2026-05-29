"""Hermes Feishu Plugin - Enhanced Feishu messaging with card messages and table rendering.

This plugin enhances Hermes Agent's Feishu messaging capabilities by providing:

- send_feishu_card: Send rich card messages with table support (no footer)
- send_feishu_table: Send structured tables as card messages (no footer)
- post_api_request hook: Capture model/usage/duration for card footer
- transform_llm_output hook: Appends footer text ONLY to the final assistant response
- Auto-deploys a gateway:startup hook that wraps all outbound Feishu text in
  interactive cards for proper Markdown rendering (headings, tables, code blocks).

Thus:
  ✅ Final text response → text has footer (transform_llm_output) → wrapped in card → card+footer
  ✅ Intermediate messages → plain text → wrapped in card → card no footer
  ✅ Tool-sent cards (send_feishu_card/table) → direct Lark SDK call → card no footer
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .schemas import SEND_FEISHU_CARD_SCHEMA, SEND_FEISHU_TABLE_SCHEMA
from .sender import _has_credentials
from . import stats
from .tools import send_feishu_card, send_feishu_table

__version__ = "0.5.0"

logger = logging.getLogger("hermes-feishu")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(ctx):
    """Register plugin tools and hooks with Hermes Agent.

    Args:
        ctx: Plugin registration context provided by Hermes.
    """
    # Register tools with conditional availability
    ctx.register_tool(
        name="send_feishu_card",
        toolset="feishu",
        schema=SEND_FEISHU_CARD_SCHEMA,
        handler=send_feishu_card,
        check_fn=_has_credentials,
    )

    ctx.register_tool(
        name="send_feishu_table",
        toolset="feishu",
        schema=SEND_FEISHU_TABLE_SCHEMA,
        handler=send_feishu_table,
        check_fn=_has_credentials,
    )

    # Register post_api_request hook to capture model/usage/duration for footer.
    ctx.register_hook("post_api_request", _on_post_api_request)

    # Register transform_llm_output hook to append footer text to the FINAL
    # assistant response only.
    ctx.register_hook("transform_llm_output", _on_transform_llm_output)

    # Auto-deploy gateway startup hook so Feishu auto-replies get card wrapping.
    _auto_deploy_hook()

def _on_post_api_request(
    *,
    model: str = "",
    provider: str = "",
    base_url: str = "",
    usage: object = None,
    api_duration: float = 0.0,
    api_call_count: int = 0,
    **_: object,
) -> None:
    """Capture latest API call stats for the footer."""
    stats.update(
        model=model,
        provider=provider,
        usage=usage,
        api_duration=api_duration,
        base_url=base_url,
    )

    if api_call_count <= 1:
        footer = stats.build_footer()
        if footer:
            logger.info("[hermes-feishu] Captured API stats: %s", footer)
        else:
            logger.info(
                "[hermes-feishu] post_api_request: model=%s, provider=%s, usage=%s, duration=%.2fs",
                model, provider, usage, api_duration,
            )


def _on_transform_llm_output(**kwargs: object) -> str | None:
    """Append footer text to the FINAL assistant response."""
    response_text = kwargs.get("response_text", "")
    if not response_text or not isinstance(response_text, str):
        return None

    footer_line = stats.build_footer()
    if not footer_line:
        return None

    return f"{response_text}\n\n───\n{footer_line}"


# ---------------------------------------------------------------------------
# Auto-deploy gateway hook
# ---------------------------------------------------------------------------


HOOK_YAML = """\
name: feishu-card-wrapper
description: >-
  Wraps all Feishu text outbound messages in interactive cards for proper
  Markdown rendering. Auto-deployed by hermes-feishu plugin.
events:
  - gateway:startup
"""

HANDLER_PY = '''\
"""Handle gateway:startup — monkey-patch FeishuAdapter for card wrapping.

Auto-deployed by hermes-feishu plugin v{version}. Do not edit manually.
Update by running: hermes plugins upgrade <your-repo>/hermes-feishu
"""

import os
import sys


async def handle(event_type: str, context: object = None) -> None:
    """On gateway:startup, patch FeishuAdapter for card wrapping."""
    if event_type != "gateway:startup":
        return

    # Ensure plugin source is on sys.path (gateway process doesn\'t load plugins)
    hermes_home = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
    plugin_src = os.path.join(hermes_home, "plugins", "hermes-feishu", "src")
    if plugin_src not in sys.path:
        sys.path.insert(0, plugin_src)

    from hermes_feishu.card_patcher import patch_gateway

    patch_gateway()'''


def _auto_deploy_hook() -> None:
    """Write feishu-card-wrapper gateway hook files to ~/.hermes/hooks/.

    Called during plugin register(). Ensures every machine that installs
    this plugin also gets the gateway hook for card-wrapping auto-replies.
    Already-existing files are overwritten to keep them in sync.
    """
    hook_dir = Path.home() / ".hermes" / "hooks" / "feishu-card-wrapper"
    hook_dir.mkdir(parents=True, exist_ok=True)

    # Write HOOK.yaml
    hook_yaml_path = hook_dir / "HOOK.yaml"
    hook_yaml_path.write_text(HOOK_YAML, encoding="utf-8")

    # Write handler.py
    handler_py_path = hook_dir / "handler.py"
    handler_py_path.write_text(HANDLER_PY.format(version=__version__), encoding="utf-8")

    logger.info(
        "[hermes-feishu] Auto-deployed hook feishu-card-wrapper → %s (v%s)",
        hook_dir, __version__,
    )
