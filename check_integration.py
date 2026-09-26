"""Exercises the two custom actions directly, with no LLM involved.

Separates 'does the WebMCP bridge work' from 'does the agent choose to use it'.
Costs nothing to run.
"""
import asyncio, os
from browser_use import BrowserProfile, BrowserSession
from webmcp_tools import call_webmcp_tool, list_webmcp_tools

URL = os.environ.get('PLAYGROUND_URL', 'https://mach-five-group.github.io/webmcp-playground/')

async def main():
    session = BrowserSession(browser_profile=BrowserProfile(headless=True))
    await session.start()
    try:
        page = await session.must_get_current_page()
        await page.goto(URL)
        await asyncio.sleep(2)
        print(f'target: {URL}\n')

        listed = await list_webmcp_tools(browser_session=session)
        print(listed.extracted_content, '\n')

        for name, params in [
            ('search_products', '{"query":"tee","limit":3}'),
            ('add_to_cart', '{"sku":"M5T-001","qty":2,"size":"L","gift":true}'),
            ('apply_coupon', '{"code":"INVALID"}'),
            ('apply_coupon', '{"code":"MACHFIVE"}'),
            ('view_cart', '{}'),
        ]:
            r = await call_webmcp_tool(tool_name=name, params_json=params, browser_session=session)
            print(f'  {name}({params}) -> {r.extracted_content}')

        bad = await call_webmcp_tool(tool_name='add_to_cart', params_json='{not json', browser_session=session)
        print(f'\n  malformed params -> {bad.extracted_content}')
    finally:
        await session.kill()

asyncio.run(main())
