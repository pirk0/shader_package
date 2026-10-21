# -*- coding: utf-8 -*-
"""ПРАВИЛА knobs.json — разбор формата и сверка с общей вкладкой шейдера (docs/format.md §8).

Вход — то, что дал json.load, любой формы: битый файл обязан дать жалобы, а не исключение. Выход —
жалобы списком (уровень, имя, правило, текст): 'E' — ошибка, 'W' — предупреждение; имя — имя
записи или «-» для файла целиком; правило — метка из RULES, по ней судят стенды.

Почему список, а не исключение: проверка обязана назвать ВСЕ ошибки разом, правка по одной на
запуск стоила бы прогона на каждую. Судья — tests/check_selftest.py: контроль, уронивший разбор
исключением, — провал, даже если нужная ошибка названа.
"""
import math
import re

TYPES = {'float': 1, 'vec2': 2, 'vec3': 3}
UI_TYPE = {'angle': 'vec2', 'deg': 'float', 'tint': 'vec3', 'origin': 'vec2'}
TOP = ('knobs', 'gates', 'pages', '_comment', 'languages', 'titles')
LANG_FIELDS = ('label', 'help', 'options', 'notable')   # тексты записи, у которых есть перевод
LANG_CODE = re.compile(r'[a-z]{2,3}\Z')
KNOB_REQ = ('name', 'type', 'default', 'min', 'max', 'group', 'label', 'order')
KNOB_OPT = ('help', 'sub', 'ui', 'angle', 'tint', 'periodic', 'probe', 'notable')
GATE_REQ = ('name', 'default', 'group', 'label', 'order')
GATE_OPT = ('help', 'sub', 'options', 'kind', 'min', 'max', 'step', 'probe', 'notable')
HELP_MAX = 100     # подсказка поля — одна строка; длиннее хосты показывают её простынёй
# Вид гейта задаёт, какие из четырёх полей у него ЕСТЬ: ровно эти. Гейт с options и
# kind:"number" разом хосты прочли бы по-разному.
KIND_HOLDS = {'options': ('options',), 'number': ('max', 'min', 'step'), 'text': ()}
BLOCKS = {'angle': ('default', 'min', 'max'), 'tint': ('amount', 'amount_max')}
IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')
# имя гейта может быть макросом-функцией: «WAVE(x)» — тело подставляется вместе с аргументом
MACRO = re.compile(r'[A-Za-z_][A-Za-z0-9_]*(?:\([A-Za-z_][A-Za-z0-9_]*'
                   r'(?:,\s*[A-Za-z_][A-Za-z0-9_]*)*\))?\Z')
NUM = r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?'
# имена, которые занимает прелюдия хоста или строка значений (docs/format.md §2.1, §7)
RESERVED = ('iResolution', 'iTime', 'iTimeDelta', 'iFrame', 'iMouse', 'iDate', 'iChannel0',
            'iChannel1', 'iChannel2', 'iChannel3', 'mainImage', 'main', 'ITIME')
RULES = ('файл', 'поле', 'имя', 'order', 'группа', 'тип', 'форма', 'диапазон', 'ui', 'kind',
         'options', 'точки', 'шейдер', 'страницы', 'help', 'подпись', 'язык')


def _num(v):
    """Число JSON: int или float, не bool и конечное."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _shape(v, n):
    """Значение формы ручки: число при n = 1, список из n чисел иначе."""
    if n == 1:
        return _num(v)
    return isinstance(v, list) and len(v) == n and all(_num(x) for x in v)


def _vec(v, n):
    return list(v) if isinstance(v, list) else [v] * n


def key(name):
    """Имя в шейдере без аргументов макроса: «WAVE(x)» объявлен как #define WAVE(x)."""
    return re.sub(r'\(.*\)\Z', '', name)


def lang_codes(kj):
    """Коды языков файла, первый — язык основных полей. Поля нет или оно битое — [] (о битом
    говорит _langs): файл одноязычный."""
    ls = kj.get('languages') if isinstance(kj, dict) else None
    if not (isinstance(ls, list) and ls and all(
            isinstance(x, list) and len(x) == 2 and isinstance(x[0], str) and LANG_CODE.match(x[0])
            and isinstance(x[1], str) and x[1].strip() for x in ls)):
        return []
    return [x[0] for x in ls]


def validate(kj):
    """Формат knobs.json → [(уровень, имя, правило, текст)]. Шейдер не нужен."""
    out = []

    def bad(lvl, nm, rule, txt):
        out.append((lvl, nm, rule, txt))

    if not isinstance(kj, dict):
        bad('E', '-', 'файл', 'верхний уровень — не объект')
        return out
    codes = lang_codes(kj)
    for k in kj:
        if k not in TOP and not (k.startswith('titles_') and k[7:] in codes[1:]):
            bad('E', '-', 'язык' if k.startswith('titles_') else 'поле',
                'неизвестное поле верхнего уровня «%s»%s'
                % (k, ' — языка «%s» нет в languages' % k[7:] if k.startswith('titles_') else ''))
    sects = []
    for sect, req, opt in (('knobs', KNOB_REQ, KNOB_OPT), ('gates', GATE_REQ, GATE_OPT)):
        lst = kj.get(sect, [] if sect == 'gates' else None)
        if not isinstance(lst, list):
            bad('E', '-', 'файл', '«%s» — не список' % sect)
            continue
        sects.append((sect, lst, req, opt))
    names, orders = {}, {}
    for sect, lst, req, opt in sects:
        for i, e in enumerate(lst):
            nm = e.get('name') if isinstance(e, dict) and isinstance(e.get('name'), str) \
                else '%s[%d]' % (sect, i)
            if not isinstance(e, dict):
                bad('E', nm, 'поле', 'запись — не объект')
                continue
            try:
                _entry(sect, e, nm, req, opt, names, orders, bad, codes)
            except Exception as ex:          # ⚠ разбор не падает: стенд засчитывает это провалом
                bad('E', nm, 'разбор', 'разбор упал: %s: %s' % (type(ex).__name__, ex))
    # Подпись различает поля своей группы — ручки и гейты вместе: группа — папка или заголовок
    # над её полями, и одинаковые подписи под ним неотличимы.
    for f in ['label'] + ['label_' + c for c in codes[1:]]:
        labels = {}
        for _s, lst, _r, _o in sects:
            for e in lst:
                if not (isinstance(e, dict) and isinstance(e.get(f), str)
                        and isinstance(e.get('group'), str) and e[f].strip()):
                    continue
                k2 = (e['group'], e[f].strip())
                if k2 in labels:
                    bad('E', str(e.get('name')), 'подпись',
                        '%s «%s» уже у %s в группе «%s»: поля группы неотличимы'
                        % (f, e[f], labels[k2], e['group']))
                labels.setdefault(k2, str(e.get('name')))
    origins = [str(k.get('name')) for _s, lst, _r, _o in sects if _s == 'knobs' for k in lst
               if isinstance(k, dict) and k.get('ui') == 'origin']
    if len(origins) > 1:
        bad('E', origins[1], 'ui', 'ui:origin у двух ручек (%s): точка кадра у пакета одна'
            % ', '.join(origins))
    entries = [e for _s, lst, _r, _o in sects for e in lst if isinstance(e, dict)]
    if 'pages' in kj:
        try:
            _pages(kj['pages'], entries, bad, codes)
        except Exception as ex:              # ⚠ и здесь
            bad('E', '-', 'разбор', 'разбор pages упал: %s: %s' % (type(ex).__name__, ex))
    try:
        _langs(kj, entries, bad)
    except Exception as ex:                  # ⚠ и здесь
        bad('E', '-', 'разбор', 'разбор языков упал: %s: %s' % (type(ex).__name__, ex))
    return out


def _langs(kj, entries, bad):
    """languages — [[код, название]], первый — язык основных полей; перевод — поле
    «<поле>_<код>»; названия групп и подгрупп — titles и titles_<код>. Нет перевода —
    предупреждение: хост покажет текст языка по умолчанию."""
    if 'languages' in kj:
        codes = lang_codes(kj)
        if not codes:
            bad('E', '-', 'язык', 'languages — непустой список [код, «название»], код — 2–3 '
                                  'строчные латинские буквы')
            return
        if len(set(codes)) != len(codes):
            bad('E', '-', 'язык', 'languages: код повторяется — %s' % (codes,))
    codes = lang_codes(kj)
    heads = {e[f] for e in entries for f in ('group', 'sub') if isinstance(e.get(f), str)}
    for i, c in enumerate(codes or ['']):
        k = 'titles' if i == 0 else 'titles_' + c
        t = kj.get(k)
        if t is None:
            continue
        if not (isinstance(t, dict) and all(isinstance(v, str) and v.strip() for v in t.values())):
            bad('E', '-', 'язык', '%s — объект {группа или подгруппа: «название»}' % k)
            continue
        for g in t:
            if g not in heads:
                bad('W', '-', 'язык', '%s: «%s» — нет такой группы или подгруппы' % (k, g))
    for c in codes[1:]:
        miss = [e['name'] + '.' + f for e in entries for f in LANG_FIELDS
                if f in e and f + '_' + c not in e and isinstance(e.get('name'), str)]
        miss += ['pages[%d].name' % i for i, p in enumerate(kj.get('pages') or [])
                 if isinstance(p, dict) and 'name_' + c not in p]
        if miss:
            bad('W', '-', 'язык', 'нет перевода на «%s» у %d текстов — хост покажет их на «%s»: %s'
                % (c, len(miss), codes[0], ', '.join(miss[:5]) + ('…' if len(miss) > 5 else '')))


def _lang_fields(e, nm, bad, codes):
    """Переводы записи: «<поле>_<код>» только у объявленного языка, той же формы, что основное;
    у пунктов и особых значений — те же значения в том же порядке."""
    for k in e:
        base, _u, c = k.rpartition('_')
        if base not in LANG_FIELDS:
            continue
        if c not in codes[1:]:
            bad('E', nm, 'язык', 'поле «%s» — перевод на «%s», которого нет в languages%s'
                % (k, c, '' if codes else ' (поля languages нет)'))
            continue
        v = e[k]
        if base == 'label' and not (isinstance(v, str) and v.strip()):
            bad('E', nm, 'язык', '%s — непустая строка' % k)
        elif base == 'help' and not (isinstance(v, str) and v.strip() and '\n' not in v
                                     and len(v) <= HELP_MAX):
            bad('E', nm, 'help', '%s — одна строка до %d символов' % (k, HELP_MAX))
        elif base in ('options', 'notable'):
            main = e.get(base) if isinstance(e.get(base), list) else []
            ok = isinstance(v, list) and len(v) == len(main) and all(
                isinstance(p, list) and len(p) >= 2 and isinstance(m, list) and p[0] == m[0]
                and isinstance(p[1], str) and p[1].strip() for p, m in zip(v, main))
            if not ok:
                bad('E', nm, 'язык', '%s — те же значения, что у %s, в том же порядке, у каждого '
                                     '— непустая подпись' % (k, base))


def _pages(pages, entries, bad, codes=()):
    """pages — надгруппы [{name, groups}]. Поля нет — хост ставит страницу на группу. Поле есть —
    каждая группа записей стоит ровно в одной странице: не названная ушла бы на «прочее» молча,
    названная дважды показалась бы дважды."""
    if not isinstance(pages, list) or not pages:
        bad('E', '-', 'страницы', 'pages — непустой список {name, groups}')
        return
    seen, where = set(), {}
    for i, p in enumerate(pages):
        extra = set(p) - {'name', 'groups'} if isinstance(p, dict) else set()
        if not (isinstance(p, dict) and {'name', 'groups'} <= set(p)):
            bad('E', '-', 'страницы', 'pages[%d] — объект с полями name и groups' % i)
            continue
        for k in sorted(extra):
            c = k[5:] if k.startswith('name_') else None
            if c is None:
                bad('E', '-', 'страницы', 'pages[%d]: неизвестное поле «%s»' % (i, k))
            elif c not in codes[1:]:
                bad('E', '-', 'язык', 'pages[%d]: «%s» — языка «%s» нет в languages' % (i, k, c))
            elif not (isinstance(p[k], str) and p[k].strip()):
                bad('E', '-', 'язык', 'pages[%d]: %s — непустая строка' % (i, k))
        nm, gs = p['name'], p['groups']
        if not (isinstance(nm, str) and nm.strip()):
            bad('E', '-', 'страницы', 'pages[%d]: name — непустая строка' % i)
            continue
        if nm in seen:
            bad('E', '-', 'страницы', 'страница «%s» повторяется' % nm)
        seen.add(nm)
        if not (isinstance(gs, list) and gs and all(isinstance(g, str) and g.strip() for g in gs)):
            bad('E', '-', 'страницы', 'страница «%s»: groups — непустой список строк' % nm)
            continue
        for g in gs:
            if g in where:
                bad('E', '-', 'страницы', 'группа «%s» в двух страницах: «%s» и «%s»'
                    % (g, where[g], nm))
            where.setdefault(g, nm)
    first = {}
    for e in entries:
        g = e.get('group')
        if isinstance(g, str):
            first.setdefault(g, str(e.get('name')))
    for g, nm in first.items():
        if g not in where:
            bad('E', nm, 'страницы', 'группа «%s» не названа ни в одной странице pages' % g)
    for g in where:
        if g not in first:
            bad('W', '-', 'страницы', 'группа «%s» есть в pages, но записей с ней нет' % g)


def _entry(sect, e, nm, req, opt, names, orders, bad, codes=()):
    for k in e:
        if k not in req and k not in opt and k.rpartition('_')[0] not in LANG_FIELDS:
            bad('E', nm, 'поле', 'неизвестное поле «%s» — опечатка или поле, которого формат не '
                                 'знает' % k)
    miss = [k for k in req if k not in e]
    if miss:
        bad('E', nm, 'поле', 'нет обязательного поля: ' + ', '.join(miss))
        return
    if not isinstance(e['name'], str) or not (IDENT if sect == 'knobs' else MACRO).match(e['name']):
        bad('E', nm, 'имя', 'имя не идентификатор GLSL%s'
            % ('' if sect == 'knobs' else ' (у гейта можно «ИМЯ(x)»)'))
    elif key(e['name']) in RESERVED:
        bad('E', nm, 'имя', 'имя «%s» занято прелюдией хоста или строкой значений' % e['name'])
    if nm in names:
        bad('E', nm, 'имя', 'имя повторяется (уже есть в %s)' % names[nm])
    names.setdefault(nm, sect)
    o = e['order']
    if not (isinstance(o, int) and not isinstance(o, bool) and o >= 0):
        bad('E', nm, 'order', 'order — целое ≥ 0')
    elif o in orders:
        bad('E', nm, 'order', 'order %d уже у %s: порядок полей неоднозначен' % (o, orders[o]))
    else:
        orders[o] = nm
    for f in ('group', 'sub'):
        if f in e and not (isinstance(e[f], str) and e[f].strip()):
            bad('E', nm, 'группа', '%s — непустая строка' % f)
    # заголовок подгруппы отличает от заголовка группы только регистр
    if isinstance(e.get('sub'), str) and e['sub'].strip() and e['sub'] != e['sub'].lower():
        bad('E', nm, 'группа', 'sub «%s» — строчными: иначе её заголовок не отличить от заголовка '
                               'группы' % e['sub'])
    if 'help' in e:
        h = e['help']
        if not (isinstance(h, str) and h.strip()):
            bad('E', nm, 'help', 'help — непустая строка')
        elif '\n' in h or len(h) > HELP_MAX:
            bad('E', nm, 'help', 'help — одна строка до %d символов (сейчас %d%s)'
                % (HELP_MAX, len(h), ', с переводом строки' if '\n' in h else ''))
    (_knob if sect == 'knobs' else _gate)(e, nm, bad)
    _points(e, nm, bad)
    _lang_fields(e, nm, bad, codes)


def _knob(k, nm, bad):
    t = k['type']
    if not isinstance(t, str) or t not in TYPES:
        bad('E', nm, 'тип', 'type «%s» не из %s' % (t, '/'.join(TYPES)))
        return
    n = TYPES[t]
    for f in ('default', 'min', 'max'):
        if not _shape(k[f], n):
            bad('E', nm, 'форма', '%s — %s' % (f, 'число' if n == 1 else 'список из %d чисел' % n))
            return
    d, lo, hi = (_vec(k[f], n) for f in ('default', 'min', 'max'))
    if any(a > b for a, b in zip(lo, hi)):
        bad('E', nm, 'диапазон', 'min %s > max %s' % (k['min'], k['max']))
    elif any(not (a <= v <= b) for v, a, b in zip(d, lo, hi)):
        bad('E', nm, 'диапазон', 'default %s вне [%s … %s]' % (k['default'], k['min'], k['max']))
    if not (isinstance(k['label'], str) and k['label'].strip()):
        bad('E', nm, 'поле', 'label — непустая строка')
    ui = k.get('ui')
    if ui is not None and (not isinstance(ui, str) or ui not in UI_TYPE):
        bad('E', nm, 'ui', 'ui «%s» не из %s' % (ui, '/'.join(UI_TYPE)))
    elif ui is not None and UI_TYPE[ui] != t:
        bad('E', nm, 'ui', 'ui:%s бывает только у %s, а здесь %s' % (ui, UI_TYPE[ui], t))
    for blk, need in BLOCKS.items():
        if (blk in k) != (ui == blk):
            bad('E', nm, 'ui', 'блок %s нужен ровно при ui:%s' % (blk, blk))
            continue
        if blk in k and not (isinstance(k[blk], dict) and sorted(k[blk]) == sorted(need)
                             and all(_num(k[blk][x]) for x in need)):
            bad('E', nm, 'ui', 'блок %s — {%s}, все числа' % (blk, ', '.join(need)))
    a = k.get('angle')
    if ui == 'angle' and isinstance(a, dict) and all(_num(a.get(x)) for x in BLOCKS['angle']):
        if not a['min'] <= a['default'] <= a['max']:
            bad('E', nm, 'диапазон', 'angle.default вне [angle.min … angle.max]')
        # ⚠ default-вектор обязан быть (cos, sin) угла: шейдер и стенды читают default, поле
        # хоста — angle.default; разойдутся — хосты начнут с разного поворота
        r = math.radians(a['default'])
        if abs(d[0] - math.cos(r)) > 1e-6 or abs(d[1] - math.sin(r)) > 1e-6:
            bad('E', nm, 'ui', 'default %s ≠ (cos, sin) угла angle.default = %s'
                % (k['default'], a['default']))
    tn = k.get('tint')
    if ui == 'tint' and isinstance(tn, dict) and all(_num(tn.get(x)) for x in BLOCKS['tint']):
        if not 0 <= tn['amount'] <= tn['amount_max']:
            bad('E', nm, 'диапазон', 'tint.amount вне [0 … amount_max]')
        # ⚠ поле хоста стартует с белого цвета: (1 − 1)·сила = 0 при любом default
        if any(v != 0 for v in d):
            bad('E', nm, 'ui', 'ui:tint: хост начинает с нуля (белый цвет), а default %s'
                % (k['default'],))
    if 'periodic' in k:
        per = k['periodic']
        if not _num(per) or per <= 0:
            bad('E', nm, 'точки', 'periodic — положительное число')
        elif n > 1 and ui != 'angle':
            bad('E', nm, 'точки', 'periodic у вектора — только при ui:angle')


def _gate(g, nm, bad):
    if not (isinstance(g['label'], str) and g['label'].strip()):
        bad('E', nm, 'поле', 'label — непустая строка')
    kind = g.get('kind', 'options')
    if not isinstance(kind, str) or kind not in KIND_HOLDS:
        bad('E', nm, 'kind', 'kind «%s» не из %s' % (kind, '/'.join(KIND_HOLDS)))
        return
    has = tuple(sorted(f for f in ('options', 'min', 'max', 'step') if f in g))
    if has != KIND_HOLDS[kind]:
        bad('E', nm, 'kind', 'гейт вида %s держит %s, а здесь %s'
            % (kind, '/'.join(KIND_HOLDS[kind]) or 'ни одного из options/min/max/step',
               '/'.join(has) or 'ничего'))
        return
    d = g['default']
    if kind == 'options':
        o = g['options']
        if not (isinstance(o, list) and len(o) >= 2 and all(
                isinstance(p, list) and len(p) == 2 and isinstance(p[0], int)
                and not isinstance(p[0], bool) and isinstance(p[1], str) and p[1].strip()
                for p in o)):
            bad('E', nm, 'options', 'options — список из двух и более пар [целое, «подпись»]')
            return
        vals = [p[0] for p in o]
        if len(set(vals)) != len(vals):
            bad('E', nm, 'options', 'значения в options повторяются')
        if isinstance(d, bool) or d not in vals:
            bad('E', nm, 'диапазон', 'default %r не из options %s' % (d, vals))
    elif kind == 'number':
        if not all(_num(x) for x in (d, g['min'], g['max'], g['step'])):
            bad('E', nm, 'форма', 'default/min/max/step — числа')
            return
        if g['step'] <= 0:
            bad('E', nm, 'форма', 'step > 0')
        if not g['min'] <= d <= g['max']:
            bad('E', nm, 'диапазон', 'default %s вне [%s … %s]' % (d, g['min'], g['max']))
    elif not (isinstance(d, str) and d.strip()) or '\n' in d or '\r' in d:
        bad('E', nm, 'форма', 'default текстового гейта — непустая строка без переноса')


def _points(e, nm, bad):
    """notable — внутри диапазона (иначе ползунок туда не доедет); probe вне диапазона — только с
    причиной третьим элементом, внутри — без неё."""
    n = TYPES.get(e.get('type'), 1)
    lo, hi = e.get('min'), e.get('max')
    for tag in ('notable', 'probe'):
        if tag not in e:
            continue
        if not isinstance(e[tag], list):
            bad('E', nm, 'точки', '%s — список' % tag)
            continue
        for i, p in enumerate(e[tag]):
            top = 3 if tag == 'probe' else 2
            if not (isinstance(p, list) and 2 <= len(p) <= top and isinstance(p[1], str)
                    and all(isinstance(x, str) for x in p[2:])):
                bad('E', nm, 'точки', '%s[%d] — [значение, «подпись»%s]'
                    % (tag, i, '(, «причина»)' if tag == 'probe' else ''))
                continue
            v = p[0]
            if isinstance(v, str) or lo is None or not _shape(lo, n) or not _shape(hi, n):
                continue                       # выражение текстового гейта или гейт-список
            if not _shape(v, n):
                bad('E', nm, 'точки', '%s[%d]: значение не той формы, что default' % (tag, i))
                continue
            out_ = any(not (a <= b <= c) for b, a, c in zip(_vec(v, n), _vec(lo, n), _vec(hi, n)))
            if out_ and tag == 'notable':
                bad('E', nm, 'точки', 'notable %s вне [%s … %s]' % (v, lo, hi))
            if out_ and tag == 'probe' and len(p) < 3:
                bad('E', nm, 'точки', 'probe %s вне [%s … %s] без причины (третий элемент)'
                    % (v, lo, hi))
            if not out_ and tag == 'probe' and len(p) > 2:
                bad('E', nm, 'точки', 'probe %s внутри диапазона — причина не нужна' % (v,))


def define_re(name):
    """Строка `#define ИМЯ значение // комментарий`: значение — всё от имени до `//` или конца
    строки. Хост меняет гейт подменой значения в этой строке (docs/format.md §8.6)."""
    return re.compile(r'^[ \t]*#define[ \t]+' + re.escape(name) + r'[ \t]+(.*?)[ \t]*(?://.*)?$',
                      re.M)


def literal_type(val):
    """Тип литерала #define по GLSL: с точкой или порядком — float, целое — int, иначе None."""
    if re.fullmatch(r'[-+]?(?:\d+\.\d*|\.\d+)(?:[eE][-+]?\d+)?|[-+]?\d+[eE][-+]?\d+', val):
        return 'float'
    if re.fullmatch(r'[-+]?\d+', val):
        return 'int'
    return None


def shader_check(kj, src):
    """Сверка с общей вкладкой: объявление каждой ручки и гейта, дефолт, тип литерала гейта.
    У пакета отставание json от шейдера — ошибка: хост его переживёт (§8.7), а образец — нет."""
    out = []

    def bad(lvl, nm, rule, txt):
        out.append((lvl, nm, rule, txt))

    decl = {}
    for m in re.finditer(r'^uniform\s+(\w+)\s+(\w+)\s*;(.*)$', src, re.M):
        decl.setdefault(m.group(2), []).append((m.group(1), m.group(3)))
    knobs = [k for k in kj.get('knobs') or [] if isinstance(k, dict)
             and isinstance(k.get('name'), str)]
    for k in knobs:
        nm, typ = k['name'], k.get('type')
        ds = decl.get(nm)
        if not ds:
            bad('E', nm, 'шейдер', 'в общей вкладке нет «uniform %s %s;»' % (typ, nm))
            continue
        if len(ds) > 1:
            bad('E', nm, 'шейдер', 'uniform %s объявлен %d раз' % (nm, len(ds)))
        st, tail = ds[0]
        if st != typ:
            bad('E', nm, 'шейдер', 'тип в шейдере %s, в json %s' % (st, typ))
            continue
        m = re.match(r'\s*//\s*=(%s|vec[234]\([^)]*\))' % NUM, tail)
        if not m:
            # без «// =…» ручка, отставшая от json, получит 0: инициализатора у uniform в GLSL
            # ES 3.00 нет, другого значения в коде у неё не бывает (§8.7)
            bad('E', nm, 'шейдер', 'у объявления нет «// =дефолт»')
            continue
        lit = m.group(1)
        nums = [float(x) for x in re.findall(NUM, lit[lit.index('(') + 1:] if '(' in lit else lit)]
        want = _vec(k.get('default'), TYPES.get(typ, 1) if isinstance(typ, str) else 1)
        if len(nums) != len(want) or not all(_num(b) and abs(a - b) <= 1e-9
                                             for a, b in zip(nums, want)):
            bad('E', nm, 'шейдер', 'дефолт в шейдере =%s, в json %s' % (lit, k.get('default')))
    for nm in sorted(set(decl) - {k['name'] for k in knobs}):
        bad('E', nm, 'шейдер', 'uniform есть в общей вкладке, но не в json: хост не знает, что '
                               'ему подать')
    for g in kj.get('gates') or []:
        if not (isinstance(g, dict) and isinstance(g.get('name'), str)):
            continue
        nm = g['name']
        hits = list(define_re(nm).finditer(src))
        if not hits:
            bad('E', nm, 'шейдер', 'в общей вкладке нет «#define %s …»' % nm)
            continue
        if len(hits) > 1:
            bad('E', nm, 'шейдер', '#define %s объявлен %d раз: подмене нужен ровно один'
                % (nm, len(hits)))
        val = hits[0].group(1).strip()
        kind = g.get('kind', 'options')
        if kind == 'text':
            same = val == str(g.get('default')).strip()
        else:
            try:
                same = abs(float(val) - float(g.get('default'))) <= 1e-12
            except (TypeError, ValueError):
                same = False
        if not same:
            bad('E', nm, 'шейдер', 'дефолт в шейдере «%s», в json «%s»' % (val, g.get('default')))
            continue
        lt = literal_type(val)
        # ⚠ тип гейта в выражениях — тип его литерала (§6.2): целый гейт с дробным шагом хост
        # подставил бы дробью, и шейдер перестал бы собираться
        if kind == 'options' and lt != 'int':
            bad('E', nm, 'шейдер', 'гейт-список: литерал «%s» — не целое' % val)
        elif kind == 'number' and lt == 'int' and not all(
                _num(g.get(f)) and float(g[f]).is_integer() for f in ('min', 'max', 'step')):
            bad('E', nm, 'шейдер', 'гейт-число с целым литералом «%s»: min, max и step — целые'
                % val)
    return out


def gate_type(g, src):
    """Тип гейта в выражении: список — int, число — тип литерала в шейдере, текст — None."""
    kind = g.get('kind', 'options')
    if kind == 'options':
        return 'int'
    if kind == 'number':
        hits = list(define_re(g['name']).finditer(src))
        return literal_type(hits[0].group(1).strip()) if hits else None
    return None
