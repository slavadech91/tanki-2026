"""Static view of the Kotlin/JS modules inside the minified webpack bundle.

A Kotlin module looks like
    12345:(t,n,i)=>{!function(t,n,i,r){"use strict";var a=n.$_$.rf,...;function X(){...}...
        ;t.$_$=t.$_$||{},t.$_$.a=X,...}(t.exports,i(37036),i(24635),i(61860))}
- the factory parameters map to module ids by position (`t` = own exports),
- `var a=n.$_$.rf` imports export `rf` of the module bound to `n`,
- `t.$_$.a=X` exports local `X` under key `a`,
- methods are attached as `<protoOf>(X).name=function(...){...}` where <protoOf> imports stdlib `he`.

Globally a class is (module id, local name); `Bundle.resolve(mod, name)` follows imports to it.

usage (as a library): from kjs import Bundle; b = Bundle(path)
"""
import re

STDLIB = '37036'
PROTO = '24635'


def match_brace(src, i):
    """src[i] is an opening bracket; return the index just past its matching bracket.
    Skips string literals, template literals and (heuristically) regex literals."""
    pairs = {'{': '}', '(': ')', '[': ']'}
    stack = [pairs[src[i]]]
    j = i + 1
    n = len(src)
    prev = src[i]
    while j < n:
        c = src[j]
        if c in '"\'`':
            q = c
            j += 1
            while j < n and src[j] != q:
                if src[j] == '\\':
                    j += 1
                j += 1
            prev = q
            j += 1
            continue
        if c == '/' and prev in '(,=:[!&|?{};+-*%<>~^' and j + 1 < n and src[j + 1] not in '/*':
            k = j + 1           # regex literal
            in_class = False
            while k < n:
                d = src[k]
                if d == '\\':
                    k += 2
                    continue
                if d == '[':
                    in_class = True
                elif d == ']':
                    in_class = False
                elif d == '/' and not in_class:
                    break
                elif d == '\n':
                    break
                k += 1
            j = k + 1
            while j < n and src[j].isalpha():
                j += 1
            prev = '/'
            continue
        if c in pairs:
            stack.append(pairs[c])
        elif c in ')}]':
            if not stack or stack[-1] != c:
                raise ValueError('unbalanced %r at %d' % (c, j))
            stack.pop()
            if not stack:
                return j + 1
        if not c.isspace():
            prev = c
        j += 1
    raise ValueError('no match for bracket at %d' % i)


def split_top(s, sep=','):
    """Split s on `sep` at bracket depth 0 (strings respected)."""
    out, depth, cur, i, n = [], 0, 0, 0, len(s)
    while i < n:
        c = s[i]
        if c in '"\'`':
            q = c
            i += 1
            while i < n and s[i] != q:
                if s[i] == '\\':
                    i += 1
                i += 1
        elif c in '([{':
            depth += 1
        elif c in ')]}':
            depth -= 1
        elif c == sep and depth == 0:
            out.append(s[cur:i])
            cur = i + 1
        i += 1
    out.append(s[cur:])
    return out


MOD_START = re.compile(r'[{,](\d+):\((?:t|t,n|t,n,i)\)=>\{')
FACTORY = re.compile(r'!function\(([\w$,]+)\)\{"use strict";')
FUNC = re.compile(r'function ([\w$]+)\(([\w$,]*)\)\{')


class Module:
    def __init__(self, bundle, mid, start, text):
        self.b, self.id, self.start, self.text = bundle, mid, start, text
        self.params, self.args = [], []
        self.imports = {}      # alias -> (module id, export key) | ('expr', text)
        self.exports = {}      # key -> local name (or None for inline expressions)
        self.funcs = {}        # local function name -> (body start, body end) in self.text (inside braces)
        self.methods = {}      # class -> {method: (start, end)}  (function body incl. braces)
        self.proto_aliases = set()
        self._parse()

    def _parse(self):
        t = self.text
        m = FACTORY.search(t, 0, 6000)
        if not m:
            return
        self.params = m.group(1).split(',')
        tail = t.rfind('}(t.exports')
        if tail == -1:
            return
        args = re.findall(r't\.exports|i\((\d+)\)', t[tail + 2:match_brace(t, tail + 1)])
        self.args = ['self'] + [a for a in args[1:]]
        pmap = dict(zip(self.params, self.args))
        body_start = m.end()
        v = t.find('var ', body_start, body_start + 300)      # a few bare statements may come first
        if v != -1:
            body_start = v
        # imports: the first `var` declaration list
        if t.startswith('var ', body_start):
            end = body_start + 4
            depth = 0
            while end < len(t):          # declaration list ends at the first ';' at depth 0
                c = t[end]
                if c in '([{':
                    end = match_brace(t, end)
                    continue
                if c == ';':
                    break
                end += 1
            for decl in split_top(t[body_start + 4:end]):
                if '=' not in decl:
                    continue
                name, expr = decl.split('=', 1)
                name, expr = name.strip(), expr.strip()
                if expr.startswith('(') and expr.endswith(')'):
                    expr = split_top(expr[1:-1])[-1].strip()      # (a,b,c) -> c
                im = re.fullmatch(r'([\w$]+)\.\$_\$\.([\w$]+)', expr)
                if im and im.group(1) in pmap:
                    self.imports[name] = (pmap[im.group(1)], im.group(2))
                else:
                    self.imports[name] = ('expr', expr)
        # exports
        for em in re.finditer(r't\.\$_\$\.([\w$]+)=([\w$]+)(?=[,;}])', t):
            self.exports[em.group(1)] = em.group(2)
        for em in re.finditer(r't\.\$_\$\.([\w$]+)=function', t):
            self.exports.setdefault(em.group(1), None)
        # protoOf aliases (stdlib `he`)
        self.proto_aliases = {a for a, v in self.imports.items() if v == (STDLIB, 'he')}
        # functions (top level and nested; names are unique enough within a module for our use)
        for fm in FUNC.finditer(t):
            name = fm.group(1)
            if name in self.funcs:
                continue
            try:
                end = match_brace(t, fm.end() - 1)
            except ValueError:
                continue
            self.funcs[name] = (fm.start(), end)
        # methods: <protoOf>(X).name=function(args){...}
        if self.proto_aliases:
            pat = re.compile(r'(?<![\w$.])(?:' + '|'.join(re.escape(a) for a in self.proto_aliases) +
                             r')\(([\w$]+)\)\.([\w$]+)=function\(([\w$,]*)\)\{')
            for mm in pat.finditer(t):
                try:
                    end = match_brace(t, mm.end() - 1)
                except ValueError:
                    continue
                self.methods.setdefault(mm.group(1), {})[mm.group(2)] = (mm.start(), end)

    def func_text(self, name):
        s = self.funcs.get(name)
        return self.text[s[0]:s[1]] if s else None

    def method_text(self, cls, meth):
        s = self.methods.get(cls, {}).get(meth)
        return self.text[s[0]:s[1]] if s else None

    def method_body(self, cls, meth):
        s = self.methods.get(cls, {}).get(meth)
        if not s:
            return None
        t = self.text[s[0]:s[1]]
        return t[t.find('{') + 1:-1]

    def pos(self, offset):
        return self.start + offset


class Bundle:
    def __init__(self, path):
        self.src = open(path, encoding='utf-8').read()
        starts = [(m.group(1), m.start() + 1) for m in MOD_START.finditer(self.src)]
        self.modules = {}
        for k, (mid, st) in enumerate(starts):
            text = self.src[st:starts[k + 1][1] - 1] if k + 1 < len(starts) else self.src[st:]
            if not FACTORY.search(text, 0, 6000) or '.$_$' not in text[:20000]:
                continue
            mod = Module(self, mid, st, text)
            if mod.params:
                self.modules[mid] = mod

    def resolve(self, mid, name, depth=0):
        """Follow an alias in module `mid` to (defining module, local name). Returns None if unknown."""
        mod = self.modules.get(mid)
        if mod is None or depth > 10:
            return None
        if name in mod.imports:
            v = mod.imports[name]
            if v[0] == 'expr':
                return None
            tm, key = v
            if tm == 'self':
                tm = mid
            tmod = self.modules.get(tm)
            if tmod is None:
                return (tm, '$' + key)
            local = tmod.exports.get(key)
            if local is None:
                return (tm, '$' + key)
            return self.resolve(tm, local, depth + 1) if local in tmod.imports else (tm, local)
        return (mid, name)

    def import_of(self, mid, name):
        """(module, export key) an alias imports, or None."""
        v = self.modules[mid].imports.get(name)
        if v and v[0] != 'expr':
            return ('%s' % (mid if v[0] == 'self' else v[0]), v[1])
        return None
