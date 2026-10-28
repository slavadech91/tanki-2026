"""HTTP side of the server.

  /play/          our own page (play.html) that starts the official client bundle
  /static/...     the client bundle and the page fonts
  /config.xml     points the client at ws://127.0.0.1:<ws_port>/
  /resources/...  game resources (models, textures, maps, sounds)
No game files are kept in the repository: /static and /resources are downloaded once from the official CDN
(s.eu.tankionline.com) into the cache folder: cache/ at the repository root, or $TANKI_CACHE.
The client takes resources and config from its own origin when not on tankionline.com (bundle @1134473);
its UI images and translations it loads straight from the CDN (__webpack_require__.p).
"""
import asyncio, os, urllib.parse, urllib.request

from aiohttp import web

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.environ.get('TANKI_CACHE') or os.path.join(ROOT, 'cache')
PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'play.html')
CDN = 'https://s.eu.tankionline.com/'


def local(base, rel):
    """Path of URL path `rel` inside `base`; None when it would leave `base`."""
    parts = rel.split('/')
    if any(p in ('', '.', '..') or '\\' in p or ':' in p for p in parts):
        return None
    return os.path.join(base, *parts)


async def fetch(path, url, log):
    """Download `url` into `path`; False when the CDN does not give it."""
    try:
        data = await asyncio.to_thread(lambda: urllib.request.urlopen(url, timeout=60).read())
    except Exception as e:  # noqa: BLE001 - a missing file is a 404 for the client
        log('CDN miss', url, e)
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + '.part', 'wb') as f:
        f.write(data)
    os.replace(path + '.part', path)
    log('CDN fetched', url, len(data))
    return True


def make_app(ws_port, log):
    async def play(request):
        return web.FileResponse(PAGE, headers={'Cache-Control': 'no-cache'})

    async def config(request):
        xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cfg xmlns="http://alternativaplatform.com/core/config.xsd">'
               '<server address="127.0.0.1" version="local" mode="simple" wsProtocol="WS"><ports/>'
               '<webSocketPorts><port>%d</port></webSocketPorts></server><status>normal</status></cfg>' % ws_port)
        return web.Response(text=xml, content_type='application/xml')

    async def static(request):
        rel = request.match_info['path']
        path = local(os.path.join(CACHE, 'static'), rel)
        if path is None:
            raise web.HTTPNotFound()
        if not os.path.isfile(path) and not await fetch(path, CDN + 'static/' + urllib.parse.quote(rel), log):
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    async def resources(request):
        rel = request.match_info['path']
        # some resource names contain spaces; the cache keeps them under the URL-encoded name (bg1%201024.webp)
        raw = request.raw_path.split('?')[0][len('/resources/'):]
        files = os.path.join(CACHE, 'resources')
        path, plain = local(files, raw), local(files, rel)
        if path is None or plain is None:
            raise web.HTTPNotFound()
        if not os.path.isfile(path):
            if os.path.isfile(plain):
                path = plain
            elif not await fetch(path, CDN + urllib.parse.quote(rel), log):
                raise web.HTTPNotFound()
        return web.FileResponse(path, headers={'Access-Control-Allow-Origin': '*'})

    async def index(request):
        raise web.HTTPFound('/play/')

    app = web.Application()
    app.add_routes([web.get('/', index), web.get('/play/', play), web.get('/play', play),
                    web.get('/config.xml', config), web.get('/static/{path:.*}', static),
                    web.get('/resources/{path:.*}', resources)])
    return app
