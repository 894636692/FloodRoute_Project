"""Run the unchanged demo with an early browser measurement probe, local port 8504.

Injects into the HTTP response only. Does not modify installed packages or the
normal port 8502 server. Restart this process for a cold Python resource cache.
"""
from pathlib import Path
import sys
from starlette.responses import HTMLResponse
from streamlit.web.server.starlette import starlette_static_routes as static

ROOT = Path(__file__).resolve().parents[1]
factory = static.create_streamlit_static_handler

def instrumented_factory(directory, base_url):
    handler = factory(directory, base_url)
    original = handler.get_response
    async def get_response(path, scope):
        if path in ('.', '', 'index.html'):
            html = (Path(directory) / 'index.html').read_text(encoding='utf-8')
            probe = (ROOT / 'scripts/ui_browser_probe.js').read_text(encoding='utf-8')
            return HTMLResponse(html.replace('<head>', '<head><script>' + probe + '</script>', 1),
                                headers={'Cache-Control': 'no-store'})
        return await original(path, scope)
    handler.get_response = get_response
    return handler

static.create_streamlit_static_handler = instrumented_factory
if __name__ == '__main__':
    from streamlit.web.cli import main
    main(['run', str(ROOT/'src/floodroute/ui/app_v1_1.py'), '--server.address=127.0.0.1',
          '--server.port=8504', '--server.headless=true', '--browser.gatherUsageStats=false',
          '--server.fileWatcherType=none'])
