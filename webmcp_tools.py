"""
Custom Browser Use actions that reach the page through WebMCP instead of the DOM.

This is the whole point of the experiment. Browser Use's built-in actions work
the way agents normally do: screenshot the page, pick an element index, click it.
These two actions do something different — they ask the page what functions it
publishes, then call those functions by name. No selectors, no coordinates, no
guessing which div is a button.
"""

import asyncio
import json

from browser_use import ActionResult, BrowserSession, Tools

tools = Tools()

# Page.evaluate requires an arrow function and JSON-stringifies whatever it
# returns, so every snippet below is written in that form.
_HAS_WEBMCP = "() => typeof navigator.modelContext !== 'undefined'"
_LIST_TOOLS = "() => (navigator.modelContext && navigator.modelContext.tools) || null"
_CALL_TOOL = "(name, params) => navigator.modelContext.callTool(name, params)"

_NOT_AVAILABLE = (
    'This page does not expose navigator.modelContext. WebMCP requires a secure '
    'context (https:// or localhost), and the page must have finished loading.'
)


async def _await_webmcp(page, timeout: float = 5.0) -> bool:
    """Poll until the polyfill has installed.

    Navigation returns before the page's modules execute, so a call issued
    immediately after `goto` finds `navigator.modelContext` undefined. Polling
    beats a fixed sleep: fast pages do not pay for it, slow ones still work.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if (await page.evaluate(_HAS_WEBMCP)).lower() == 'true':
            return True
        await asyncio.sleep(0.25)
    return False


@tools.action(
    description=(
        'List the tools this page publishes via WebMCP (navigator.modelContext). '
        'Returns each tool name, description, and its JSON Schema of parameters. '
        'Call this FIRST to discover what the page can do — it is faster and more '
        'reliable than reading the page visually.'
    )
)
async def list_webmcp_tools(browser_session: BrowserSession) -> ActionResult:
    page = await browser_session.must_get_current_page()

    if not await _await_webmcp(page):
        return ActionResult(extracted_content=_NOT_AVAILABLE + ' Fall back to the DOM.')

    raw = await page.evaluate(_LIST_TOOLS)
    listed = json.loads(raw) if raw and raw != 'null' else []
    if not listed:
        return ActionResult(extracted_content='The page exposes WebMCP but has registered no tools.')

    lines = [f'{len(listed)} WebMCP tools available:']
    for t in listed:
        schema = t.get('inputSchema') or {}
        props = schema.get('properties') or {}
        required = set(schema.get('required') or [])
        params = ', '.join(
            f'{n}: {(s or {}).get("type", "any")}{"" if n in required else "?"}'
            + (f' [{"|".join(map(str, s["enum"]))}]' if isinstance(s, dict) and s.get('enum') else '')
            for n, s in props.items()
        )
        lines.append(f'- {t["name"]}({params}) — {t.get("description", "no description")}')

    # include_in_memory keeps the tool list in context so the agent does not
    # rediscover it on every step
    return ActionResult(extracted_content='\n'.join(lines), include_in_memory=True)


@tools.action(
    description=(
        'Call one of the page\'s WebMCP tools by name. params_json is a JSON object '
        'matching that tool\'s inputSchema, with values of the declared types (numbers '
        'unquoted, booleans as true/false). Omit it for tools that take no parameters. '
        'Use this instead of clicking.'
    )
)
async def call_webmcp_tool(tool_name: str, browser_session: BrowserSession, params_json: str = '{}') -> ActionResult:
    try:
        params = json.loads(params_json) if params_json.strip() else {}
    except json.JSONDecodeError as e:
        # Hand the model a correctable message rather than raising — a malformed
        # argument should cost one retry, not the run.
        return ActionResult(extracted_content=f'params_json was not valid JSON ({e}). Send a JSON object.')

    page = await browser_session.must_get_current_page()
    if not await _await_webmcp(page):
        return ActionResult(extracted_content=_NOT_AVAILABLE)

    try:
        raw = await page.evaluate(_CALL_TOOL, tool_name, params)
    except Exception as e:  # noqa: BLE001
        # A raw CDP exception is unusable to a model. Name the likely cause.
        return ActionResult(
            extracted_content=(
                f'Calling "{tool_name}" threw in the page: {e}. '
                'Check the tool name against list_webmcp_tools.'
            )
        )

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        return ActionResult(extracted_content=str(raw))

    # callTool never rejects; failures arrive as {content, isError}. Surface the
    # distinction so the agent can react instead of treating errors as success.
    text = ' '.join(b.get('text', '') for b in (result.get('content') or []) if isinstance(b, dict))
    if result.get('isError'):
        return ActionResult(extracted_content=f'Tool "{tool_name}" failed: {text}')
    return ActionResult(extracted_content=text or json.dumps(result))
