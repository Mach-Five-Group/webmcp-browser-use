"""
Can an AI agent use a page's business logic through WebMCP instead of clicking?

Points a Browser Use agent at the machvive playground with two custom actions —
discover tools, call a tool — and then checks the run history to see whether the
agent actually used them or fell back to the DOM. The check is the point: an
agent that quietly clicked its way to the answer has not proven anything.
"""

import asyncio
import json
import os
import sys

from browser_use import Agent, BrowserProfile, BrowserSession, ChatAnthropic
from dotenv import load_dotenv

from webmcp_tools import tools

load_dotenv()

URL = os.environ.get('PLAYGROUND_URL', 'https://mach-five-group.github.io/webmcp-playground/')

TASK = f"""Go to {URL}

That page publishes callable tools via WebMCP. Use list_webmcp_tools to discover
them, then use call_webmcp_tool to do the following. Do not click page elements —
everything you need is available as a tool call.

1. Search for products matching "tee".
2. Add 2 of SKU M5T-001 in size L to the cart, as a gift.
3. Try the coupon code INVALID, then the code MACHFIVE.
4. Report the final cart contents.

Finish by stating the cart total and what happened with each coupon."""

# Built-in actions that mean the agent interacted with the rendered page rather
# than calling a published function. Navigation is excluded — getting to the page
# is not the same as clicking through it.
DOM_ACTIONS = {'click_element_by_index', 'input_text', 'select_dropdown_option', 'scroll', 'send_keys', 'drag_drop'}


async def main() -> int:
    if not os.environ.get('ANTHROPIC_API_KEY'):
        print('ANTHROPIC_API_KEY is not set. Put it in .env or export it.', file=sys.stderr)
        return 2

    agent = Agent(
        task=TASK,
        # Adaptive thinking: the agent has to map a natural-language goal onto a
        # schema it discovers at runtime, which is exactly the kind of work it helps.
        llm=ChatAnthropic(model='claude-opus-5', thinking={'type': 'adaptive'}),
        tools=tools,
        # keep_alive so the page survives agent.run() — the corroboration step
        # below reads the page's own analytics, and a torn-down session loses it.
        browser_session=BrowserSession(
            browser_profile=BrowserProfile(
                headless=os.environ.get('HEADLESS', '1') != '0', keep_alive=True
            )
        ),
    )

    history = await agent.run(max_steps=20)

    print('\n' + '=' * 68)
    print('DID THE AGENT USE WEBMCP, OR DID IT CLICK?')
    print('=' * 68)

    used = history.action_names()
    webmcp = [a for a in used if a in {'list_webmcp_tools', 'call_webmcp_tool'}]
    dom = [a for a in used if a in DOM_ACTIONS]

    print(f'\n  actions taken      : {len(used)}')
    print(f'  via WebMCP         : {len(webmcp)}  {sorted(set(webmcp))}')
    print(f'  via DOM interaction: {len(dom)}  {sorted(set(dom)) or "none"}')

    print('\n  full sequence:')
    for i, a in enumerate(used, 1):
        mark = '  WebMCP' if a in {'list_webmcp_tools', 'call_webmcp_tool'} else ('  DOM' if a in DOM_ACTIONS else '')
        print(f'    {i:2}. {a}{mark}')

    print('\n  agent said:')
    print('   ', (history.final_result() or '(no final result)').replace('\n', '\n    '))

    # The playground's own analytics component captured each call independently.
    # If it agrees with the action count, the calls really reached the page.
    try:
        page = await agent.browser_session.must_get_current_page()
        raw = await page.evaluate(
            "() => { const el = document.querySelector('machvive-webmcp-analytics');"
            ' return el ? { total: el.log.size, errors: el.log.entries.filter(e => e.status === "error").length,'
            ' tools: el.log.entries.map(e => e.tool) } : null; }'
        )
        captured = json.loads(raw) if raw and raw != 'null' else None
        if captured:
            print(f'\n  page-side analytics captured {captured["total"]} calls '
                  f'({captured["errors"]} failed): {", ".join(captured["tools"])}')
    except Exception as e:  # noqa: BLE001 - diagnostics only, never fail the run
        print(f'\n  (could not read page analytics: {e})')

    await agent.browser_session.kill()

    ok = bool(webmcp) and not dom
    print('\n' + ('  PROVEN: the agent drove the page entirely through WebMCP.'
                  if ok else
                  '  NOT PROVEN: see the sequence above.'))
    print('=' * 68)
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
