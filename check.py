# -*- coding: utf-8 -*-
"""ПРОВЕРКА ПАКЕТА ШЕЙДЕРА shader-package/1 — все ошибки разом (docs/format.md).

    python check.py <папка пакета>        код 0 — ошибок нет, 1 — есть, 2 — папки нет

Судит форму и имена: ключи описания, пути, граф пассов, картинки, буферы, выражения с типами,
вкладки против описания, knobs.json и его сверку с общей вкладкой, наборы. Правду объявлений — что
пасс при `skip` и вправду не входит в кадр — проверка не судит: её доказывает судья проекта (§4).

Жалоба — (уровень, где, правило, текст): 'E' — ошибка, 'W' — предупреждение; правило — метка из
RULES или knobs_rules.RULES, по ней судят стенды. Проверка не бросает исключений на битом входе:
упавший блок — жалоба 'разбор', и tests/check_selftest.py засчитывает её провалом. Каждое правило
покрыто там подсаженной ошибкой.
"""
import io
import json
import os
import re
import sys

import expr
import knobs_rules
import values

FORMAT = 'shader-package/1'
TOP = ('_comment', 'format', 'id', 'name', 'knobs', 'style', 'inputs', 'common', 'textures',
       'buffers', 'passes', 'time', 'pointer', 'let', 'warnings', 'presets')
REQ = ('format', 'id', 'name', 'knobs', 'style', 'inputs', 'passes')
INPUTS = ('iResolution', 'iTime', 'iTimeDelta', 'iFrame', 'iMouse', 'iDate')
NOT_V1 = ('iChannelResolution', 'iChannelTime', 'iFrameRate', 'iSampleRate')
CHANNELS = 4
FORMATS = ('rgba8', 'rgba16f', 'rgba32f')
WRAPS = ('clamp', 'repeat', 'mirror')
ID = re.compile(r'[a-z][a-z0-9_]*\Z')
IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')
MAIN_IMAGE = re.compile(r'\bvoid\s+mainImage\s*\(\s*out\s+vec4\s+\w+\s*,'
                        r'\s*(?:in\s+)?vec2\s+\w+\s*\)')
RULES = ('файл', 'ключ', 'формат', 'имя', 'путь', 'вход', 'картинка', 'буфер', 'пасс', 'вкладка',
         'выражение', 'объявление', 'предупреждение', 'язык', 'набор')


def strip_comments(src):
    """Комментарии GLSL прочь, переводы строк целы."""
    src = re.sub(r'/\*.*?\*/', lambda m: '\n' * m.group(0).count('\n'), src, flags=re.S)
    return re.sub(r'//[^\n]*', '', src)


def words(src):
    return set(re.findall(r'[A-Za-z_][A-Za-z0-9_]*', strip_comments(src)))


def image_info(path):
    """('png' | 'jpeg' | None, бит на канал или None) — по сигнатуре файла."""
    with open(path, 'rb') as f:
        data = f.read()
    if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data) > 24:
        return 'png', data[24]
    if data[:3] == b'\xff\xd8\xff':
        i = 2
        while i + 4 < len(data) and data[i] == 0xFF:
            mk = data[i + 1]
            if 0xC0 <= mk <= 0xCF and mk not in (0xC4, 0xC8, 0xCC):
                return 'jpeg', data[i + 4] if i + 4 < len(data) else None
            if mk in (0xD8, 0x01) or 0xD0 <= mk <= 0xD7:
                i += 2
                continue
            i += 2 + int.from_bytes(data[i + 2:i + 4], 'big')
        return 'jpeg', None
    return None, None


class Review:
    def __init__(self, folder):
        self.root = folder
        self.out = []
        self.kj = {}
        self.codes = []
        self.common = ''
        self.lets = {}          # имя let → тип
        self.let_names = set()
        self.code = {}          # номер пасса → текст его вкладки

    def bad(self, lvl, where, rule, txt):
        self.out.append((lvl, where, rule, txt))

    # ------------------------------------------------------------------ файлы и пути ---------
    def exact(self, rel):
        """Путь есть в пакете с тем же регистром букв: Windows простит «Grid.png», веб-сервер —
        нет."""
        cur = self.root
        for part in rel.split('/'):
            try:
                if part not in os.listdir(cur):
                    return None
            except OSError:
                return None
            cur = os.path.join(cur, part)
        return cur

    def path(self, p, where, kind='file'):
        """Путь пакета → полный путь или None. kind: 'file', 'dir' или 'maybe' (папки может не
        быть)."""
        if not isinstance(p, str) or not p or p.startswith('/') or '\\' in p or ':' in p \
                or '..' in p.split('/') or '' in p.split('/'):
            self.bad('E', where, 'путь', 'путь «%s» — относительный, через /, внутри пакета' % p)
            return None
        full = self.exact(p)
        if full is None:
            if kind != 'maybe':
                self.bad('E', where, 'путь', 'в пакете нет «%s» (регистр букв считается)' % p)
            return None
        if (kind == 'file') != os.path.isfile(full):
            self.bad('E', where, 'путь', '«%s» — %s' % (p, 'папка, а нужен файл' if kind == 'file'
                                                         else 'файл, а нужна папка'))
            return None
        return full

    def read(self, p, where):
        full = self.path(p, where)
        if full is None:
            return None
        try:
            return io.open(full, encoding='utf-8-sig').read()
        except (OSError, UnicodeDecodeError) as ex:
            self.bad('E', where, 'файл', 'не прочесть «%s» как UTF-8: %s' % (p, ex))
            return None

    # ------------------------------------------------------------------ тексты на языках ------
    def keys(self, d, allowed, texts, where, quiet=()):
        """Ключи объекта: незнакомый — ошибка; у текстов — переводы «поле_код» на языки
        knobs.json, пропуск перевода — предупреждение (у текстов из quiet перевод не обязателен:
        имя проекта обычно одно на всех языках)."""
        if not isinstance(d, dict):
            self.bad('E', where, 'ключ', 'не объект')
            return False
        for k in d:
            base, _u, c = k.rpartition('_')
            if k in allowed:
                continue
            if base in texts:
                if c not in self.codes[1:]:
                    self.bad('E', where, 'язык', '«%s» — языка «%s» нет в languages knobs.json'
                             % (k, c))
                elif not (isinstance(d[k], str) and d[k].strip()):
                    self.bad('E', where, 'язык', '%s — непустая строка' % k)
                continue
            self.bad('E', where, 'ключ', 'незнакомый ключ «%s»' % k)
        for t in texts:
            if t in d and t not in quiet:
                miss = [c for c in self.codes[1:] if '%s_%s' % (t, c) not in d]
                if miss:
                    self.bad('W', where, 'язык', 'нет перевода %s на %s — хост покажет текст '
                             'на «%s»' % (t, ', '.join(miss), self.codes[0]))
        return True

    # ------------------------------------------------------------------ выражения -------------
    def types(self, with_lets):
        kn = {k['name']: k for k in self.kj.get('knobs') or []
              if isinstance(k, dict) and isinstance(k.get('name'), str)}
        gt = {knobs_rules.key(g['name']): g for g in self.kj.get('gates') or []
              if isinstance(g, dict) and isinstance(g.get('name'), str)}

        def t(name):
            if with_lets and name in self.lets:
                return self.lets[name]
            if name == 'iResolution':
                return 'vec3'
            if name in kn:
                return kn[name].get('type')
            if name in gt:
                if gt[name].get('kind') == 'text':
                    raise expr.ExprError('текстовый гейт «%s» в выражении: значение — '
                                         'формула, а не число' % name)
                ty = knobs_rules.gate_type(gt[name], self.common)
                if ty is None:
                    raise expr.ExprError('тип гейта «%s» не известен: в общей вкладке нет его '
                                         'литерала' % name)
                return ty
            if name in INPUTS:
                raise expr.ExprError('вход «%s» в выражении: из входов выражения знают только '
                                     'iResolution' % name)
            if not with_lets and name in self.let_names:
                raise expr.ExprError('let ссылается на let «%s»' % name)
            raise expr.Void(name)
        return t

    def expr(self, src, where, want, with_lets=True):
        """Выражение → тип или None; want — допустимые типы."""
        try:
            ty = expr.typeof(expr.parse(src), self.types(with_lets))
        except expr.ExprError as ex:
            self.bad('E', where, 'выражение', str(ex))
            return None
        except expr.Void as ex:
            self.bad('E', where, 'выражение', 'имени «%s» нет ни в knobs.json, ни в let' % ex)
            return None
        if ty not in want:
            self.bad('E', where, 'выражение', '«%s» — %s, а нужно %s'
                     % (src, ty, ' или '.join(want)))
            return None
        return ty

    def templates(self, d, fields, where):
        for f in [k for k in d if k.rpartition('_')[0] in fields or k in fields]:
            if not isinstance(d[f], str):
                continue                      # о форме уже сказал раздел
            try:
                parts = expr.template_exprs(d[f])
            except expr.ExprError as ex:
                self.bad('E', '%s.%s' % (where, f), 'выражение', str(ex))
                continue
            for s in parts:
                self.expr(s, '%s.%s {%s}' % (where, f, s), ('int', 'float'))

    # ------------------------------------------------------------------ разделы описания ------
    def run(self):
        man = self.load_json('manifest.json', 'manifest.json')
        if man is None:
            return
        if not isinstance(man, dict):
            self.bad('E', 'manifest.json', 'файл', 'верхний уровень — не объект')
            return
        for k in REQ:
            if k not in man:
                self.bad('E', 'manifest.json', 'ключ', 'нет обязательного ключа «%s»' % k)
        if man.get('format') != FORMAT:
            self.bad('E', 'manifest.json format', 'формат', '«%s» — эти правила знают только %s'
                     % (man.get('format'), FORMAT))
        if man.get('style') != 'shadertoy':
            self.bad('E', 'manifest.json style', 'формат', '«%s» — в версии 1 только shadertoy'
                     % man.get('style'))
        if not (isinstance(man.get('id'), str) and ID.match(man['id'])):
            self.bad('E', 'manifest.json id', 'имя', '«%s» — нужно [a-z][a-z0-9_]*' % man.get('id'))
        if not (isinstance(man.get('name'), str) and man['name'].strip()):
            self.bad('E', 'manifest.json name', 'имя', 'name — непустая строка')
        self.section('knobs.json', self.knobs, man)
        self.keys(man, TOP, ('name',), 'manifest.json', quiet=('name',))
        # let — до всех выражений: live, skip и предупреждения ссылаются на его имена
        for nm, fn in (('inputs', self.inputs), ('textures', self.textures), ('let', self.let),
                       ('buffers', self.buffers), ('passes', self.passes), ('tabs', self.tabs),
                       ('time', self.time), ('pointer', self.pointer),
                       ('warnings', self.warnings), ('presets', self.presets)):
            self.section('manifest.json ' + nm, fn, man)

    def section(self, where, fn, man):
        try:
            fn(man)
        except Exception as ex:              # ⚠ проверка не падает: стенд засчитывает это провалом
            self.bad('E', where, 'разбор', 'проверка упала: %s: %s' % (type(ex).__name__, ex))

    def load_json(self, p, where):
        txt = self.read(p, where)
        if txt is None:
            return None
        try:
            return json.loads(txt)
        except ValueError as ex:
            self.bad('E', where, 'файл', 'не JSON: %s' % ex)
            return None

    def knobs(self, man):
        kj = self.load_json(man['knobs'], 'manifest.json knobs') if 'knobs' in man else None
        for lvl, nm, rule, txt in knobs_rules.validate(kj) if kj is not None else []:
            self.bad(lvl, 'knobs.json' + ('' if nm == '-' else ' %s' % nm), rule, txt)
        if not isinstance(kj, dict):
            return
        self.kj, self.codes = kj, knobs_rules.lang_codes(kj)
        entries = [e for s in ('knobs', 'gates') for e in kj.get(s) or [] if isinstance(e, dict)]
        if 'common' in man:
            self.common = self.read(man['common'], 'manifest.json common') or ''
        elif entries:
            self.bad('E', 'manifest.json', 'вкладка', 'ручки и гейты объявляются в общей вкладке '
                                                       '`common`, а её нет')
            return
        for lvl, nm, rule, txt in knobs_rules.shader_check(kj, self.common):
            self.bad(lvl, 'knobs.json %s' % nm, rule, txt)

    def inputs(self, man):
        if 'inputs' not in man:
            return                            # об отсутствии уже сказано
        inp = man.get('inputs')
        if not (isinstance(inp, list) and all(isinstance(x, str) for x in inp)
                and len(set(inp)) == len(inp) and not set(inp) - set(INPUTS)):
            self.bad('E', 'manifest.json inputs', 'вход', '%s — список без повторов из %s'
                     % (inp, ' '.join(INPUTS)))

    def textures(self, man):
        tex = man.get('textures', {})
        if not isinstance(tex, dict):
            self.bad('E', 'manifest.json textures', 'ключ', 'не объект')
            return
        for n, t in tex.items():
            w = 'manifest.json textures.' + n
            if not IDENT.match(n):
                self.bad('E', w, 'имя', 'имя картинки — идентификатор')
            if not self.keys(t, ('file', 'mipmaps', 'wrap'), (), w):
                continue
            if 'file' not in t:
                self.bad('E', w, 'ключ', 'нет обязательного ключа «file»')
            else:
                full = self.path(t['file'], w + '.file')
                kind, bits = image_info(full) if full else (None, None)
                if full and kind is None:
                    self.bad('E', w + '.file', 'картинка', '«%s» — не PNG и не JPEG' % t['file'])
                elif full and bits != 8 and not (kind == 'png' and bits in (1, 2, 4)):
                    self.bad('E', w + '.file', 'картинка', '«%s»: %s бит на канал, а хосты читают '
                                                           '8' % (t['file'], bits))
            if not isinstance(t.get('mipmaps', False), bool):
                self.bad('E', w + '.mipmaps', 'картинка', 'mipmaps — true или false')
            wr = t.get('wrap', ['clamp', 'clamp'])
            if not (isinstance(wr, list) and len(wr) == 2 and all(x in WRAPS for x in wr)):
                self.bad('E', w + '.wrap', 'картинка', '%s — пара из %s' % (wr, ', '.join(WRAPS)))

    def buffers(self, man):
        buf, tex = man.get('buffers', {}), man.get('textures', {})
        if not isinstance(buf, dict):
            self.bad('E', 'manifest.json buffers', 'ключ', 'не объект')
            return
        for n, b in buf.items():
            w = 'manifest.json buffers.' + n
            if not IDENT.match(n):
                self.bad('E', w, 'имя', 'имя буфера — идентификатор')
            if isinstance(tex, dict) and n in tex:
                self.bad('E', w, 'имя', 'имя занято картинкой: канал пасса стал бы неоднозначен')
            if not self.keys(b, ('format', 'clear', 'live'), (), w):
                continue
            if b.get('format') not in FORMATS:
                self.bad('E', w + '.format', 'буфер', '«%s» — из %s'
                         % (b.get('format'), ', '.join(FORMATS)))
            c = b.get('clear', [0, 0, 0, 0])
            if not (isinstance(c, list) and len(c) == 4 and all(knobs_rules._num(x) for x in c)):
                self.bad('E', w + '.clear', 'буфер', 'clear — четыре числа RGBA')
            if 'live' in b:
                lv = b['live']
                if not (isinstance(lv, list) and len(lv) == 2):
                    self.bad('E', w + '.live', 'буфер', 'live — пара выражений [x, y]')
                    continue
                for i, s in enumerate(lv):
                    self.expr(s, '%s.live[%d]' % (w, i), ('int', 'float'))

    def let(self, man):
        lt = man.get('let', {})
        if not isinstance(lt, dict):
            self.bad('E', 'manifest.json let', 'ключ', 'не объект')
            return
        taken = {e.get('name') for s in ('knobs', 'gates') for e in self.kj.get(s) or []
                 if isinstance(e, dict)} | set(INPUTS)
        taken |= {knobs_rules.key(n) for n in taken if isinstance(n, str)}
        self.let_names = set(lt)
        for n, s in lt.items():
            w = 'manifest.json let.' + n
            if not IDENT.match(n) or n in taken:
                self.bad('E', w, 'имя', 'имя let — идентификатор, не занятый ручкой, гейтом или '
                                        'входом')
                continue
            ty = self.expr(s, w, ('int', 'float', 'bool'), with_lets=False)
            if ty:
                self.lets[n] = ty

    def passes(self, man):
        passes, buf, tex = man.get('passes'), man.get('buffers', {}), man.get('textures', {})
        buf = buf if isinstance(buf, dict) else {}
        tex = tex if isinstance(tex, dict) else {}
        if 'passes' not in man:
            return
        if not (isinstance(passes, list) and passes):
            self.bad('E', 'manifest.json passes', 'пасс', 'passes — непустой список')
            return
        seen, written, read = set(), {}, set()
        for i, p in enumerate(passes):
            w = 'manifest.json passes[%d]' % i
            if not self.keys(p, ('name', 'code', 'output', 'channels', 'skip'), (), w):
                continue
            for k in ('name', 'code', 'output'):
                if k not in p:
                    self.bad('E', w, 'ключ', 'нет обязательного ключа «%s»' % k)
            nm = p.get('name')
            if not (isinstance(nm, str) and ID.match(nm)) or nm in seen:
                self.bad('E', w + '.name', 'имя', '«%s» — [a-z][a-z0-9_]*, без повторов' % nm)
            seen.add(nm)
            if 'code' in p:
                src = self.read(p['code'], w + '.code')
                if src is not None:
                    self.code[i] = src
            out = p.get('output')
            if out == 'screen':
                if i != len(passes) - 1:
                    self.bad('E', w + '.output', 'пасс', 'на экран пишет только последний пасс')
            elif isinstance(out, str) and out in buf:
                if out in written:
                    self.bad('E', w + '.output', 'пасс', 'буфер %s уже пишет passes[%d]'
                             % (out, written[out]))
                written.setdefault(out, i)
            elif 'output' in p:
                self.bad('E', w + '.output', 'пасс', '«%s» — не буфер и не screen' % (out,))
            ch = p.get('channels', [])
            if not (isinstance(ch, list) and len(ch) <= CHANNELS):
                self.bad('E', w + '.channels', 'пасс', 'channels — список до %d' % CHANNELS)
                ch = []
            for j, c in enumerate(ch):
                if c is None:
                    continue
                if isinstance(c, str) and c in buf:
                    read.add(c)
                    if written.get(c, i) >= i:
                        self.bad('E', '%s.channels[%d]' % (w, j), 'пасс',
                                 'буфер %s читается раньше, чем его пишут, или своим же пассом: '
                                 'обратной связи в версии 1 нет' % c)
                elif isinstance(c, str) and c in tex:
                    read.add(c)
                else:
                    self.bad('E', '%s.channels[%d]' % (w, j), 'пасс',
                             '«%s» нет ни в textures, ни в buffers' % (c,))
            sk = p.get('skip', [])
            if not isinstance(sk, list):
                self.bad('E', w + '.skip', 'объявление', 'skip — список {when, why}')
                continue
            if sk and out == 'screen':
                self.bad('E', w + '.skip', 'объявление', 'пасс на экран не пропускается')
            for k, s in enumerate(sk):
                ws = '%s.skip[%d]' % (w, k)
                if not self.keys(s, ('when', 'why'), (), ws):
                    continue
                if not (isinstance(s.get('why'), str) and s['why'].strip()):
                    self.bad('E', ws, 'объявление', 'why — непустая строка: зачем пасс не нужен')
                if 'when' not in s:
                    self.bad('E', ws, 'ключ', 'нет обязательного ключа «when»')
                else:
                    self.expr(s['when'], ws + '.when', ('bool',))
        if sum(isinstance(p, dict) and p.get('output') == 'screen' for p in passes) != 1:
            self.bad('E', 'manifest.json passes', 'пасс', 'на экран пишет не ровно один пасс')
        for n in buf:
            if n not in written:
                self.bad('E', 'manifest.json buffers.' + n, 'буфер', 'буфер не пишет ни один пасс')
            elif n not in read:
                self.bad('W', 'manifest.json buffers.' + n, 'буфер', 'буфер никто не читает')
        for n in tex:
            if n not in read:
                self.bad('W', 'manifest.json textures.' + n, 'картинка', 'картинку не читает ни '
                                                                          'один пасс')

    def tabs(self, man):
        passes = man.get('passes') if isinstance(man.get('passes'), list) else []
        knob_names = [k['name'] for k in self.kj.get('knobs') or []
                      if isinstance(k, dict) and isinstance(k.get('name'), str)]
        gate_names = [knobs_rules.key(g['name']) for g in self.kj.get('gates') or []
                      if isinstance(g, dict) and isinstance(g.get('name'), str)]
        prelude = list(INPUTS) + ['iChannel%d' % i for i in range(CHANNELS)]
        used = set()
        cw = words(self.common)
        tabs = [('common', man.get('common'), self.common, None)]
        tabs += [('passes[%d]' % i, passes[i].get('code'), src, passes[i])
                 for i, src in sorted(self.code.items())]
        for role, rel, src, p in tabs:
            if not isinstance(rel, str):
                continue
            w, code = rel, strip_comments(src)
            if re.search(r'^\s*#\s*version\b', code, re.M):
                self.bad('E', w, 'вкладка', '#version пишет прелюдия хоста')
            if re.search(r'\bvoid\s+main\s*\(', code):
                self.bad('E', w, 'вкладка', 'main() пишет хост: вкладка определяет mainImage')
            has_main = bool(MAIN_IMAGE.search(code))
            if p is None and has_main:
                self.bad('E', w, 'вкладка', 'общая вкладка не определяет mainImage')
            if p is not None and not has_main:
                self.bad('E', w, 'вкладка', 'нет «void mainImage(out vec4 …, in vec2 …)»')
            for nm in prelude:
                if re.search(r'\buniform\s+\w+\s+%s\b' % nm, code):
                    self.bad('E', w, 'вкладка', '«%s» объявляет прелюдия хоста' % nm)
            if p is not None:
                for nm in knob_names:
                    if re.search(r'^\s*uniform\s+\w+\s+%s\s*;' % re.escape(nm), code, re.M):
                        self.bad('E', w, 'вкладка', 'ручка %s объявлена в общей вкладке — второе '
                                                    'объявление не соберётся' % nm)
                for nm in gate_names:
                    if re.search(r'^\s*#\s*define\s+%s\b' % re.escape(nm), code, re.M):
                        self.bad('E', w, 'вкладка', 'гейт %s объявлен в общей вкладке — второй '
                                                    '#define не соберётся' % nm)
            ws = words(src)
            used |= ws
            for nm in NOT_V1:
                if nm in ws:
                    self.bad('E', w, 'вход', '«%s» — вход не из версии 1' % nm)
            if p is not None:
                ch = p.get('channels') if isinstance(p.get('channels'), list) else []
                for j in range(CHANNELS):
                    on = j < len(ch) and ch[j] is not None
                    wj = 'manifest.json %s.channels[%d]' % (role, j)
                    if ('iChannel%d' % j) in (ws | cw) and not on:
                        self.bad('E', wj, 'пасс', 'вкладка %s читает iChannel%d, а канал пуст'
                                 % (rel, j))
                    elif on and ('iChannel%d' % j) not in (ws | cw):
                        self.bad('W', wj, 'пасс', 'канал занят, а вкладка %s его не читает' % rel)
        inp = man.get('inputs') if isinstance(man.get('inputs'), list) else []
        for nm in INPUTS:
            if nm in used and nm not in inp:
                self.bad('E', 'manifest.json inputs', 'вход', 'вкладки читают «%s», а в inputs его '
                                                              'нет' % nm)
            elif nm in inp and nm not in used:
                self.bad('W', 'manifest.json inputs', 'вход', '«%s» в inputs, а вкладки его не '
                                                              'читают' % nm)

    def time(self, man):
        if 'time' not in man:
            return
        t, w = man['time'], 'manifest.json time'
        if not self.keys(t, ('when', 'help'), ('help',), w):
            return
        if 'when' not in t:
            self.bad('E', w, 'ключ', 'нет обязательного ключа «when»')
        else:
            self.expr(t['when'], w + '.when', ('bool',))
        if 'help' in t and not (isinstance(t['help'], str) and t['help'].strip()):
            self.bad('E', w + '.help', 'объявление', 'help — непустая строка')
        if 'iTime' not in (man.get('inputs') or []):
            self.bad('W', w, 'объявление', 'iTime нет в inputs: время в кадр не входит, объявление '
                                           'лишнее')

    def pointer(self, man):
        if 'pointer' not in man:
            return
        ps, w = man['pointer'], 'manifest.json pointer'
        if not (isinstance(ps, list) and len(ps) <= 1):
            self.bad('E', w, 'объявление', 'pointer — список не длиннее одного: точка кадра в '
                                           'версии 1 одна')
            return
        kn = {k.get('name'): k for k in self.kj.get('knobs') or [] if isinstance(k, dict)}
        for i, p in enumerate(ps):
            wi = '%s[%d]' % (w, i)
            if not self.keys(p, ('knob',), (), wi):
                continue
            k = kn.get(p.get('knob'))
            if not (k and k.get('type') == 'vec2' and k.get('ui') == 'origin'
                    and k.get('min') == [0, 0] and k.get('max') == [1, 1]):
                self.bad('E', wi, 'объявление', '«%s» — нужна ручка vec2 с ui:origin и диапазоном '
                                                '[0,0]…[1,1]' % p.get('knob'))

    def warnings(self, man):
        ws = man.get('warnings', [])
        if not isinstance(ws, list):
            self.bad('E', 'manifest.json warnings', 'ключ', 'не список')
            return
        ids = set()
        for i, wn in enumerate(ws):
            w = 'manifest.json warnings[%d]' % i
            if not self.keys(wn, ('id', 'when', 'short', 'text'), ('short', 'text'), w):
                continue
            if not (isinstance(wn.get('id'), str) and ID.match(wn['id'])) or wn.get('id') in ids:
                self.bad('E', w + '.id', 'предупреждение', '«%s» — [a-z][a-z0-9_]*, без повторов'
                         % wn.get('id'))
            ids.add(wn.get('id'))
            for f in ('when', 'text'):
                if f not in wn:
                    self.bad('E', w, 'предупреждение', 'нет обязательного ключа «%s»' % f)
            for f in [k for k in wn if k.rpartition('_')[0] in ('short', 'text')
                      or k in ('short', 'text')]:
                if not (isinstance(wn[f], str) and wn[f].strip()):
                    self.bad('E', '%s.%s' % (w, f), 'предупреждение', 'непустая строка')
            if 'when' in wn:
                self.expr(wn['when'], w + '.when', ('bool',))
            self.templates(wn, ('short', 'text'), w)

    def presets(self, man):
        if 'presets' not in man:
            return
        full = self.path(man['presets'], 'manifest.json presets', 'maybe')
        if full is None or not os.path.isdir(full):
            if full is not None:
                self.bad('E', 'manifest.json presets', 'путь', 'presets — папка')
            return
        for fn in sorted(os.listdir(full)):
            rel = man['presets'] + '/' + fn
            if not fn.endswith('.txt'):
                self.bad('W', rel, 'набор', 'набор — файл <имя>.txt; этот хосты не прочтут')
                continue
            try:
                text = io.open(os.path.join(full, fn), encoding='utf-8-sig').read()
            except (OSError, UnicodeDecodeError) as ex:
                self.bad('E', rel, 'набор', 'не прочесть как UTF-8: %s' % ex)
                continue
            for lvl, nm, txt in values.check_line(values.unwrap_file(text), self.kj):
                self.bad(lvl, '%s %s' % (rel, nm), 'набор', txt)


def review(folder):
    """Папка пакета → [(уровень, где, правило, текст)]."""
    r = Review(folder)
    try:
        r.run()
    except Exception as ex:                  # ⚠ последняя страховка: жалоба вместо исключения
        r.bad('E', '-', 'разбор', 'проверка упала: %s: %s' % (type(ex).__name__, ex))
    return r.out


def main(argv):
    if len(argv) != 1:
        print(__doc__)
        return 2
    if not os.path.isdir(argv[0]):
        print('папки «%s» нет' % argv[0])
        return 2
    ps = review(argv[0])
    for lvl, where, rule, txt in ps:
        print('%s [%s] %s: %s' % ('ОШИБКА' if lvl == 'E' else 'внимание', rule, where, txt))
    ne = sum(p[0] == 'E' for p in ps)
    print('ошибок %d, предупреждений %d — %s' % (ne, len(ps) - ne, os.path.abspath(argv[0])))
    return 1 if ne else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
