"""Print code around regex matches in a one-line minified bundle.

usage: python -I js_find.py <file> <regex> [after=600] [before=0] [max=5]
"""
import re, sys

src = open(sys.argv[1], encoding='utf-8').read()
after = int(sys.argv[3]) if len(sys.argv) > 3 else 600
before = int(sys.argv[4]) if len(sys.argv) > 4 else 0
limit = int(sys.argv[5]) if len(sys.argv) > 5 else 5
for i, m in enumerate(re.finditer(sys.argv[2], src)):
    if i >= limit:
        break
    print('@%d: %s\n' % (m.start(), src[max(0, m.start() - before):m.start() + after]))
