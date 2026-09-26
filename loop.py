"""
Interactive loop for designing WebMCP tool surfaces.

The browser stays open and visible across commands. Vite HMR means editing a
tool in the playground is live by the time you switch windows — `reload` picks
it up without restarting anything.

The split that matters: `tools` and `call` cost nothing, `run` spends an API
call. Most tool-design iteration is schema shape and description wording, which
you can do entirely for free. Only "does a model understand this?" needs `run`.

    uv run loop.py                    # against the Vite dev server
    PLAYGROUND_URL=... uv run loop.py # against anything else
"""

import asyncio
import json
import os
import shlex
import sys

from browser_use import Agent, BrowserProfile, BrowserSession, ChatAnthropic
from dotenv import load_dotenv

from webmcp_tools import call_webmcp_tool, list_webmcp_tools, tools

load_dotenv()

# Defaults to the deployed site so the loop needs no other terminal. For HMR
# iteration on the tools themselves, run `npm run dev` in the playground repo and
# set PLAYGROUND_URL=http://localhost:5173/webmcp-playground/
URL = os.environ.get('PLAYGROUND_URL', 'https://mach-five-group.github.io/webmcp-playground/')
MODEL = os.environ.get('MODEL', 'claude-opus-5')
DOM_ACTIONS = {'click_element_by_index', 'input_text', 'select_dropdown_option', 'scroll', 'send_keys', 'drag_drop'}

HELP = """
  tools                  list what the page publishes            (free)
  call <name> <json>     invoke one directly, no model           (free)
  run <task…>            let the agent attempt it                ($$)
  task                   re-run the last task                    ($$)
  reload                 reload the page (picks up HMR)          (free)
  open <url>             navigate somewhere else                 (free)
  help / quit
"""


def verdict(history) -> None:
    # An agent that never ran and an agent that ignored the tools both produce
    # zero WebMCP actions. Separate them, or a billing failure reads as a design
    # failure and you go looking in the wrong place.
    errors = [e for e in history.errors() if e]
    used = history.action_names()
    if errors and not used:
        print(f'\n  the agent did not run: {errors[-1]}\n')
        return
    webmcp = [a for a in used if a in {'list_webmcp_tools', 'call_webmcp_tool'}]
    dom = [a for a in used if a in DOM_ACTIONS]
    print(f'\n  {len(webmcp)} WebMCP · {len(dom)} DOM · {len(used)} total')
    if dom:
        # The agent fell back to clicking, which almost always means a tool was
        # missing, mis-described, or its schema did not fit what the task needed.
        print(f'  ⚠  fell back to the DOM: {sorted(set(dom))}')
        print('     usually means a missing tool or an ambiguous description')
    print(f'\n  {(history.final_result() or "(no result)")}\n')


async def main() -> None:
    session = BrowserSession(browser_profile=BrowserProfile(headless=False, keep_alive=True))
    await session.start()
    page = await session.must_get_current_page()
    await page.goto(URL)
    print(f'\nbrowser open at {URL}  (model: {MODEL})')
    print(HELP)

    last_task = ''
    loop = asyncio.get_event_loop()

    while True:
        try:
            raw = (await loop.run_in_executor(None, input, '› ')).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not raw:
            continue
        cmd, _, rest = raw.partition(' ')
        cmd, rest = cmd.lower(), rest.strip()

        try:
            if cmd in {'quit', 'q', 'exit'}:
                break
            elif cmd in {'help', 'h', '?'}:
                print(HELP)
            elif cmd == 'reload':
                await (await session.must_get_current_page()).reload()
                print('  reloaded')
            elif cmd == 'open':
                await (await session.must_get_current_page()).goto(rest)
                print(f'  → {rest}')
            elif cmd == 'tools':
                r = await list_webmcp_tools(browser_session=session)
                print('  ' + r.extracted_content.replace('\n', '\n  '))
            elif cmd == 'call':
                name, _, params = rest.partition(' ')
                r = await call_webmcp_tool(
                    tool_name=name, params_json=params.strip() or '{}', browser_session=session
                )
                print(f'  {r.extracted_content}')
            elif cmd in {'run', 'task'}:
                task = rest if cmd == 'run' and rest else last_task
                if not task:
                    print('  no task yet — use: run <what the agent should do>')
                    continue
                last_task = task
                agent = Agent(
                    task=f'{task}\n\nThe page publishes tools via WebMCP. Discover them with '
                         'list_webmcp_tools and use call_webmcp_tool. Do not click page elements.',
                    llm=ChatAnthropic(model=MODEL, thinking={'type': 'adaptive'}),
                    tools=tools,
                    browser_session=session,
                )
                verdict(await agent.run(max_steps=20))
            else:
                print(f'  unknown: {cmd} (try help)')
        except Exception as e:  # noqa: BLE001 — a bad command should not end the session
            print(f'  ! {type(e).__name__}: {e}')

    await session.kill()
    print('closed')


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
