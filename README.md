# Can an agent use a page through WebMCP instead of clicking it?

A [Browser Use](https://github.com/browser-use/browser-use) agent, driven by Claude,
pointed at the [machvive WebMCP playground](https://mach-five-group.github.io/webmcp-playground/).

The agent gets two custom actions and no instructions about the DOM:

- `list_webmcp_tools` — asks the page what functions it publishes
- `call_webmcp_tool` — calls one by name with typed arguments

Then the run **checks itself**. It reads the action history and reports whether the
agent reached the goal through WebMCP or quietly fell back to clicking. An agent
that clicked its way to the right answer has proven nothing, so the verdict is
part of the output rather than something you infer from a transcript.

## Run it

```bash
cp .env.example .env     # add your ANTHROPIC_API_KEY
uv sync                  # or: uv pip install browser-use python-dotenv
uv run main.py
```

Watch it work with `HEADLESS=0 uv run main.py`. Point it somewhere else with
`PLAYGROUND_URL=http://localhost:4173/webmcp-playground/`.

## What you should see

```
DID THE AGENT USE WEBMCP, OR DID IT CLICK?

  via WebMCP         : 7  ['call_webmcp_tool', 'list_webmcp_tools']
  via DOM interaction: 0  none

  page-side analytics captured 6 calls (1 failed): search_products, add_to_cart, ...

  PROVEN: the agent drove the page entirely through WebMCP.
```

The last line before the verdict is independent corroboration: the playground's own
`<machvive-webmcp-analytics>` component recorded each call as it arrived. If the
page's count agrees with the agent's, the calls genuinely reached the page rather
than being something the model claimed to have done.

The task deliberately includes a coupon that fails. An agent that only handles the
happy path isn't finished, and `callTool` returns `{isError: true}` rather than
throwing — so the agent branches on data, not exceptions.

## Why this is the interesting comparison

Browser Use's default mode is how agents usually work: screenshot the page, pick an
element index, click it. That works until the markup changes, and it carries no
notion of what an action *means* — a click is a click whether it adds to a cart or
deletes an account.

WebMCP inverts it. The page declares `add_to_cart(sku, qty, gift, size)` with a
schema, and the agent calls that. No selectors to break, arguments validated
against a contract, and the page decides what it is willing to expose.

## Files

| | |
| --- | --- |
| `webmcp_tools.py` | the two custom actions — this is the integration |
| `main.py` | the task, the run, and the self-check |

## Notes

`Page.evaluate` requires an arrow function and JSON-stringifies what it returns, so
the JS snippets are written that way and parsed back in Python.

WebMCP needs a secure context — `https://` or `localhost`. Over plain HTTP
`navigator.modelContext` is undefined, and `list_webmcp_tools` says so rather than
failing obscurely.
