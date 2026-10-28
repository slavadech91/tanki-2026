"""List distinct string literals in a bundle matching a regex, with counts.

usage: python -I js_strings.py <file> <regex>
"""
import collections, re, sys

src = open(sys.argv[1], encoding='utf-8').read()
pat = re.compile(sys.argv[2], re.I)
c = collections.Counter(s for s in re.findall(r'"([^"\\]{2,80})"', src) if pat.search(s))
for s, n in sorted(c.items()):
    print('%4d  %s' % (n, s))
