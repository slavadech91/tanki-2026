"""Download every URL in urls.txt into files/<path>, skipping files already present.

usage: python -I download_urls.py <urls_file> <out_dir>
"""
import os, sys, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

MAIN = 's.eu.tankionline.com'


def get(url, out):
    u = urllib.parse.urlsplit(url)
    # s.eu keeps the original layout; other hosts get their own top folder
    parts = ([] if u.hostname == MAIN else ['_' + u.hostname]) + u.path.strip('/').split('/')
    path = os.path.join(out, *parts)
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        return 'skip'
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for _ in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                data = r.read()
            with open(path, 'wb') as f:
                f.write(data)
            return 'ok'
        except Exception as e:
            err = e
    return 'FAIL %s %s' % (url, err)


if __name__ == '__main__':
    URLS, OUT = sys.argv[1], sys.argv[2]
    with open(URLS, encoding='utf-8') as fh:
        urls = sorted({l.strip() for l in fh if l.strip().startswith('https://')})
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda u: get(u, OUT), urls))
    print('urls:', len(urls), 'new:', res.count('ok'), 'skipped:', res.count('skip'))
    for r in res:
        if r.startswith('FAIL'):
            print(r)
