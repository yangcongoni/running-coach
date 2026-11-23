"""Public desktop projection. Only the authenticated gateway calls these functions."""
import html
from desk_views import enhance
import http.client
import re
from archive_config import desktop_template


def is_desktop_read(path):
    return path in ('/api/data', '/api/today-runs') or bool(re.fullmatch(
        r'/api/running/[0-9]{1,10}/raw|/assets/(?:strength-anatomy-(?:v2|back)|race-map-[0-9]+)\.png', path))


def serve_read(handler, path):
    if not is_desktop_read(path):
        return handler.reply(404, {})
    if path == '/api/today-runs':
        from mobile_archive import open_read
        from today_run import today_runs
        with open_read() as db:
            return handler.reply(200, today_runs(db))
    conn = http.client.HTTPConnection('127.0.0.1', 8765, timeout=180)
    try:
        accepts = handler.headers.get('Accept-Encoding', '')
        conn.request('GET', path, headers={'Accept-Encoding': accepts})
        response = conn.getresponse()
        handler.send_response(response.status)
        for key in ('Content-Type', 'Content-Encoding', 'Content-Length', 'Vary'):
            if response.getheader(key):
                handler.send_header(key, response.getheader(key))
        handler.send_header('Cache-Control', 'no-store')
        handler.send_header('X-Content-Type-Options', 'nosniff')
        handler.send_header('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'")
        handler.end_headers()
        while chunk := response.read(64*1024):
            handler.wfile.write(chunk)
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        handler.close_connection = True
    finally:
        conn.close()


def document(nonce):
    page = enhance(desktop_template())
    # Both the main UI and its maintenance panel generate these links dynamically.
    page = re.sub(r'<a\b[^>]*\bhref="/(?:backup\.sqlite3|export\.json|download/[^"]*)"[^>]*>[^<]*</a>', '', page)
    page = page.replace(' onclick="this.parentElement.close()"', ' data-close-dialog')
    page = page.replace('<script>', '<script nonce="'+html.escape(nonce, quote=True)+'">')
    controls = ('<div class="public-account"><a href="/mobile">手机版</a>'
                '<form method="post" action="/logout"><input type="hidden" name="return" value="login">'
                '<button type="submit">退出登录</button></form></div>')
    style = '<style>.public-account{display:flex;justify-content:flex-end;align-items:center;gap:14px;margin:8px 20px;font-size:14px}.public-account form{margin:0}.public-account a{color:inherit}.public-account button{font:inherit;cursor:pointer}</style>'
    if '</header>' in page:
        page = page.replace('</header>', '</header>'+style+controls, 1)
    else:
        page = page.replace('<main>', style+controls+'<main>', 1)
    return (page + '<script nonce="'+nonce+'">document.querySelector(".public-account form")?.addEventListener("submit",()=>{try{for(const k of Object.keys(localStorage))if(k.startsWith("running-coach:daily:v1:"))localStorage.removeItem(k);sessionStorage.clear()}catch{}});document.querySelector("[data-close-dialog]")?.addEventListener("click",e=>e.target.closest("dialog").close())</script>').encode()
