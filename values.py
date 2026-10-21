# -*- coding: utf-8 -*-
"""СТРОКА ЗНАЧЕНИЙ shader-package/1 — эталон разбора и записи (docs/format.md §7).

Строка — токены `ИМЯ=ЗНАЧЕНИЕ` через пробел, только отличия от дефолтов: так её отдаёт хост и
принимает стенд, и так лежит набор в папке presets пакета. Имена — записи knobs.json, поля хоста по
правилам ui (`ИМЯ_deg`, `ИМЯ_color`, `ИМЯ_amount`), `ITIME` — время кадра в секундах; имя с `@` —
состояние хоста, чужой хост его пропускает и называет.

Разбор терпимый: из любого текста берутся токены с `=`, остальное возвращается вызывающему, а не
глотается молча. Кавычки — как у shell: токен со скобками или пробелом пишется в одинарных кавычках
ЦЕЛИКОМ, иначе формула с пробелом развалится на два токена.
"""
import math
import re

SAFE = re.compile(r'[\w.+=-]+\Z', re.ASCII)
TIME = 'ITIME'
UI_FIELDS = {'angle': ('_deg',), 'deg': ('_deg',), 'tint': ('_color', '_amount')}


def tokenize(text):
    """Разбиение по пробелам с учётом кавычек ' и " — как у shell, без экранирования."""
    out, cur, q, has = [], '', '', False
    for ch in str('' if text is None else text):
        if q:
            if ch == q:
                q = ''
            else:
                cur += ch
            has = True
        elif ch in ('"', "'"):
            q, has = ch, True
        elif ch.isspace():
            if has:
                out.append(cur)
                cur, has = '', False
        else:
            cur += ch
            has = True
    if has:
        out.append(cur)
    return out


def decode(text):
    """Текст → ([(имя, сырое значение)] по порядку, [токены без '=']). Позиционные токены не
    трактуются: их смысл знает только вызывающая сторона."""
    named, bare = [], []
    for t in tokenize(text):
        i = t.find('=')
        if i > 0:
            named.append((t[:i], t[i + 1:]))
        else:
            bare.append(t)
    return named, bare


def quote(tok):
    """Токен целиком в одинарные кавычки, если в нём есть что-то, кроме безопасного."""
    return tok if SAFE.match(tok) else "'%s'" % tok


def num_str(v):
    """Число → литерал, который читается обратно в то же число двойной точности."""
    v = float(v)
    return str(int(v)) if v.is_integer() and abs(v) < 1e15 else repr(v)


def vec_str(vs):
    """Вектор → `vecN(a,b,…)` без пробелов: токен обязан остаться одним словом."""
    return 'vec%d(%s)' % (len(vs), ','.join(num_str(x) for x in vs))


def encode(pairs):
    """[(имя, значение-строка)] → строка."""
    return ' '.join(quote('%s=%s' % (n, v)) for n, v in pairs)


def unwrap_file(text):
    """Файл набора: строки с '#' в начале — комментарии; остальное склеивается пробелом."""
    return ' '.join(ln for ln in str(text or '').splitlines() if not ln.strip().startswith('#'))


def parse_num(raw):
    try:
        v = float(str(raw).strip())
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def parse_vec(raw, n):
    """`vecN(a,b,…)` или голое `a,b,…` → список из n чисел, иначе None."""
    m = re.fullmatch(r'\s*(?:vec([234]))?\(?([^()]*)\)?\s*', str(raw))
    if not m or (m.group(1) and int(m.group(1)) != n):
        return None
    vs = [parse_num(x) for x in m.group(2).split(',')]
    return vs if len(vs) == n and all(v is not None for v in vs) else None


def fields(kj):
    """Имя → (вид, запись): 'knob', 'gate', 'ui' (поле хоста по правилу ui) и 'time'."""
    out = {TIME: ('time', None)}
    for k in kj.get('knobs') or []:
        if isinstance(k, dict) and isinstance(k.get('name'), str):
            out[k['name']] = ('knob', k)
            for suf in UI_FIELDS.get(k.get('ui'), ()):
                out[k['name'] + suf] = ('ui', k)
    for g in kj.get('gates') or []:
        if isinstance(g, dict) and isinstance(g.get('name'), str):
            out[g['name']] = ('gate', g)
    return out


def check_line(text, kj):
    """Строка значений против knobs.json → [(уровень, имя, текст)]. Незнакомое имя — 'W': набор
    пережил переименование, хост его назовёт; значение не той формы — 'E'."""
    out, known = [], fields(kj)
    named, bare = decode(text)
    for t in bare:
        out.append(('W', t, 'токен без «=» — не значение: хост вернёт его непонятым'))
    for nm, raw in named:
        if nm.startswith('@'):
            continue                          # состояние хоста: чужой хост пропустит и назовёт
        if nm not in known:
            out.append(('W', nm, 'имени нет в knobs.json — хост назовёт его непонятым'))
            continue
        kind, e = known[nm]
        if kind == 'time' or (kind == 'ui' and not nm.endswith('_color')):
            ok = parse_num(raw) is not None
        elif kind == 'ui':
            ok = parse_vec(raw, 3) is not None
        elif kind == 'knob':
            n = {'float': 1, 'vec2': 2, 'vec3': 3}.get(e.get('type'), 1)
            ok = (parse_num(raw) if n == 1 else parse_vec(raw, n)) is not None
        elif e.get('kind') == 'text':
            ok = bool(raw.strip())
        elif e.get('kind') == 'number':
            ok = parse_num(raw) is not None
        else:
            v = parse_num(raw)
            ok = v is not None and v in [p[0] for p in e.get('options') or []
                                         if isinstance(p, list) and p]
        if not ok:
            out.append(('E', nm, 'значение «%s» не той формы' % raw))
    return out
