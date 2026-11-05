"""Finds other enabled plugins that rewrite the final reply.

Hermes runs every `transform_llm_output` callback but keeps only the first non-empty rewrite,
so two plugins that both append to the reply silently hide one another. grounded-web steps
aside when another one is active (setting `show_sources: auto`), whatever that plugin is.

Uses Hermes's public plugin summaries, which list the hooks each plugin really registered.
"""

from __future__ import annotations

HOOK = "transform_llm_output"


def other_reply_rewriters(own_key: str) -> list[str]:
    """Names of the other loaded plugins with a transform_llm_output callback; [] when unknown."""
    try:
        from hermes_cli.plugins import get_plugin_manager
        from hermes_cli.plugins_activation import activation_summaries

        summaries = activation_summaries(get_plugin_manager())
    except Exception:  # noqa: BLE001 - older or newer Hermes without these helpers: assume none
        return []
    names = []
    for summary in summaries:
        if summary.get("key") == own_key or summary.get("name") == own_key:
            continue
        now = summary.get("activated_now") or {}
        if HOOK in (now.get("gateway_transforms") or []) + (now.get("hooks") or []):
            names.append(str(summary.get("name") or summary.get("key")))
    return sorted(names)


def sources_mode(value) -> str:
    """show_sources as auto / always / never. true/false (YAML turns on/off into those) map to auto / never."""
    if value is True:
        return "auto"
    if value is False:
        return "never"
    value = str(value or "auto").lower()
    return {"on": "always", "off": "never"}.get(value, value if value in ("auto", "always", "never") else "auto")
