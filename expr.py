# -*- coding: utf-8 -*-
"""ЯЗЫК ВЫРАЖЕНИЙ shader-package/1 — эталон: разбор, типы, значение, шаблоны (docs/format.md §6).

Подмножество выражений GLSL ES 3.00. Типы проверяет проверка пакета (check.py), хост считает
значение в двойной точности, не зная типов: у выражения, прошедшего проверку, ответ тот же, что дал
бы GLSL на тех же числах, с точностью до float32 у шейдера (§6.4). Векторы соответствия —
vectors/expr.json, судья — tests/vectors_check.py.

Два исключения. ExprError — синтаксис или тип: описание неверно. Void — имени нет: у проверки пакета
это ошибка, у хоста объявление пусто, и он делает полную работу (§4.5). Пустоту решают имена, а не
значения: value() считает обе стороны && и ||, иначе пустота зависела бы от значения слева.
"""
import math
import re
import struct


class ExprError(Exception):
    """Синтаксис или тип: описание неверно."""


class Void(Exception):
    """Имени нет: у хоста объявление пусто (docs/format.md §4.5)."""


TOKEN = re.compile(r'\s*(?:(?P<f>(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?'
                   r'|[0-9]+[eE][-+]?[0-9]+)|(?P<i>[0-9]+)|(?P<id>[A-Za-z_][A-Za-z0-9_]*)'
                   r'|(?P<op>&&|\|\||==|!=|<=|>=|[-+*/<>!(),.]))')
INT_MAX = 2 ** 31 - 1
FUNCS = {'floor': 1, 'ceil': 1, 'abs': 1, 'float': 1, 'min': 2, 'max': 2, 'mod': 2, 'clamp': 3}
COMPS = {'x': 0, 'y': 1, 'z': 2}
DIM = {'vec2': 2, 'vec3': 3}
# приоритет GLSL снизу вверх; унарные и компонента — выше всех
LEVELS = (('||',), ('&&',), ('==', '!='), ('<', '<=', '>', '>='), ('+', '-'), ('*', '/'))
# функция → {типы аргументов: тип ответа}: перегрузки GLSL ES 3.00, иных он не примет
SIG = {'floor': {('float',): 'float'}, 'ceil': {('float',): 'float'},
       'abs': {('int',): 'int', ('float',): 'float'},
       'float': {('int',): 'float', ('float',): 'float', ('bool',): 'float'},
       'min': {('int', 'int'): 'int', ('float', 'float'): 'float'},
       'max': {('int', 'int'): 'int', ('float', 'float'): 'float'},
       'mod': {('float', 'float'): 'float'},
       'clamp': {('int', 'int', 'int'): 'int', ('float', 'float', 'float'): 'float'}}


def tokens(src):
    if not isinstance(src, str):
        raise ExprError('выражение — строка, а не %s' % type(src).__name__)
    out, i, src = [], 0, src.rstrip()
    while i < len(src):
        m = TOKEN.match(src, i)
        if not m or m.end() == i:
            raise ExprError('не разобрать «%s» в «%s»' % (src[i:i + 12], src))
        if m.group('f'):
            out.append(('n', float(m.group('f')), 'float'))
        elif m.group('i'):
            s = m.group('i')
            # ⚠ «010» в GLSL — восьмеричное 8: прочесть его десятичным значило бы соврать молча
            if len(s) > 1 and s[0] == '0':
                raise ExprError('«%s»: целое с ведущим нулём GLSL читает восьмеричным' % s)
            if int(s) > INT_MAX:
                raise ExprError('«%s» больше int GLSL' % s)
            out.append(('n', float(s), 'int'))
        elif m.group('id'):
            out.append(('id', m.group('id')))
        else:
            out.append(('op', m.group('op')))
        i = m.end()
    if not out:
        raise ExprError('пустое выражение')
    return out


def parse(src):
    """Дерево: ('num', v, тип) ('name', имя) ('comp', имя, i) ('un', оп, x) ('call', ф, [x])
    ('bin', оп, a, b). Приоритет и ассоциативность — GLSL."""
    toks, pos = tokens(src), [0]

    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else ('end', None)

    def take(kind=None, val=None):
        t = peek()
        if (kind and t[0] != kind) or (val is not None and t[1] != val):
            raise ExprError('ждал «%s», а стоит «%s» в «%s»' % (val or kind, t[1], src))
        pos[0] += 1
        return t

    def level(i):
        if i == len(LEVELS):
            return unary()
        node = level(i + 1)
        while peek()[0] == 'op' and peek()[1] in LEVELS[i]:
            node = ('bin', take()[1], node, level(i + 1))
        return node

    def unary():
        t = peek()
        if t[0] == 'op' and t[1] in ('-', '+', '!'):
            take()
            return ('un', t[1], unary())
        node = primary()
        if peek() == ('op', '.'):
            take()
            c = take('id')[1]
            if c not in COMPS or node[0] != 'name':
                raise ExprError('компонента «.%s» — только .x .y .z и только у имени, в «%s»'
                                % (c, src))     # «(V).x» — тоже у имени: скобки узла не дают
            node = ('comp', node[1], COMPS[c])
        return node

    def primary():
        t = take()
        if t[0] == 'n':
            return ('num', t[1], t[2])
        if t[0] == 'id' and peek() == ('op', '('):
            if t[1] not in FUNCS:
                raise ExprError('функции «%s» нет в языке' % t[1])
            take()
            args = [level(0)]
            while peek() == ('op', ','):
                take()
                args.append(level(0))
            take('op', ')')
            if len(args) != FUNCS[t[1]]:
                raise ExprError('%s ждёт %d аргумент(а), дано %d' % (t[1], FUNCS[t[1]], len(args)))
            return ('call', t[1], args)
        if t[0] == 'id':
            return ('name', t[1])
        if t == ('op', '('):
            node = level(0)
            take('op', ')')
            return node
        raise ExprError('не ждал «%s» в «%s»' % (t[1], src))

    node = level(0)
    if pos[0] != len(toks):
        raise ExprError('лишнее «%s» в «%s»' % (toks[pos[0]][1], src))
    return node


def names(node, out=None):
    """[(имя, компонента или None)] — все имена выражения."""
    out = [] if out is None else out
    k = node[0]
    if k == 'name':
        out.append((node[1], None))
    elif k == 'comp':
        out.append((node[1], node[2]))
    elif k == 'un':
        names(node[2], out)
    elif k == 'call':
        for a in node[2]:
            names(a, out)
    elif k == 'bin':
        names(node[2], out)
        names(node[3], out)
    return out


def typeof(node, types):
    """Тип выражения: 'int', 'float' или 'bool'. types(имя) → 'int' 'float' 'bool' 'vec2'
    'vec3' или Void. Неявных преобразований нет, как в GLSL ES 3.00."""
    k = node[0]
    if k == 'num':
        return node[2]
    if k == 'name':
        t = types(node[1])
        if t in DIM:
            raise ExprError('«%s» — %s: нужна компонента .x .y .z' % (node[1], t))
        return t
    if k == 'comp':
        t = types(node[1])
        if t not in DIM or node[2] >= DIM[t]:
            raise ExprError('у «%s» (%s) нет компоненты .%s' % (node[1], t, 'xyz'[node[2]]))
        return 'float'
    if k == 'un':
        t = typeof(node[2], types)
        if node[1] == '!':
            if t != 'bool':
                raise ExprError('«!» — только у bool, а здесь %s' % t)
            return 'bool'
        if t not in ('int', 'float'):
            raise ExprError('унарный «%s» — у int или float, а здесь %s' % (node[1], t))
        return t
    if k == 'call':
        args = tuple(typeof(a, types) for a in node[2])
        if args not in SIG[node[1]]:
            raise ExprError('%s(%s) — нет в GLSL ES 3.00' % (node[1], ', '.join(args)))
        return SIG[node[1]][args]
    op, a, b = node[1], typeof(node[2], types), typeof(node[3], types)
    if op in ('&&', '||'):
        if (a, b) != ('bool', 'bool'):
            raise ExprError('«%s» — между bool, а здесь %s и %s' % (op, a, b))
        return 'bool'
    if a != b:
        raise ExprError('«%s» между %s и %s: в GLSL ES 3.00 неявных преобразований нет — нужен '
                        'float(…)' % (op, a, b))
    if op in ('==', '!='):
        return 'bool'
    if a == 'bool':
        raise ExprError('«%s» не берёт bool' % op)
    if op in ('<', '<=', '>', '>='):
        return 'bool'
    # ⚠ целое деление GLSL отбрасывает дробь, а значение у хоста — двойной точности: 7 / 2 дало
    # бы 3.5 вместо 3. Язык его не берёт, чтобы ответ не зависел от того, кто считает
    if op == '/' and a == 'int':
        raise ExprError('деление целых не входит в язык: float(a) / float(b)')
    return a


def f32(x):
    """Число, которое получит шейдер: ближайшее float32."""
    try:
        return struct.unpack('<f', struct.pack('<f', x))[0]
    except OverflowError:
        return math.copysign(math.inf, x)


def _div(a, b):
    if b == 0.0:
        if a != a or a == 0.0:
            return math.nan
        return math.copysign(math.inf, a) * math.copysign(1.0, b)
    return a / b


def _round(fn):
    def g(x):
        if not math.isfinite(x):
            return x
        r = float(fn(x))
        return math.copysign(0.0, x) if r == 0.0 else r     # floor(-0.0) и ceil(-0.5) — это −0
    return g


_floor, _ceil = _round(math.floor), _round(math.ceil)


def _mn(a, b):
    return math.nan if a != a or b != b else min(a, b)


def _mx(a, b):
    return math.nan if a != a or b != b else max(a, b)


CALL = {'floor': _floor, 'ceil': _ceil, 'abs': math.fabs, 'float': float, 'min': _mn, 'max': _mx,
        'mod': lambda a, b: a - b * _floor(_div(a, b)),
        'clamp': lambda x, lo, hi: _mn(_mx(x, lo), hi)}
CMP = {'<': lambda a, b: a < b, '<=': lambda a, b: a <= b, '>': lambda a, b: a > b,
       '>=': lambda a, b: a >= b, '==': lambda a, b: a == b, '!=': lambda a, b: a != b}


def value(node, env):
    """Значение в двойной точности; bool — 1.0 или 0.0. env(имя) → число, кортеж чисел (вектор)
    или Void. Типов не знает: их уже проверила проверка пакета."""
    k = node[0]
    if k == 'num':
        return node[1]
    if k == 'name':
        v = env(node[1])
        if isinstance(v, tuple):
            raise ExprError('вектор «%s» без компоненты' % node[1])
        return float(v)
    if k == 'comp':
        v = env(node[1])
        if not isinstance(v, tuple) or node[2] >= len(v):
            raise ExprError('у «%s» нет компоненты .%s' % (node[1], 'xyz'[node[2]]))
        return float(v[node[2]])
    if k == 'un':
        x = value(node[2], env)
        return -x if node[1] == '-' else x if node[1] == '+' else (1.0 if x == 0.0 else 0.0)
    if k == 'call':
        return CALL[node[1]](*[value(a, env) for a in node[2]])
    op, a, b = node[1], value(node[2], env), value(node[3], env)
    if op in CMP:
        return 1.0 if CMP[op](a, b) else 0.0
    if op == '&&':
        return 1.0 if (a != 0.0 and b != 0.0) else 0.0
    if op == '||':
        return 1.0 if (a != 0.0 or b != 0.0) else 0.0
    return a + b if op == '+' else a - b if op == '-' else a * b if op == '*' else _div(a, b)


def fmt(x):
    """Число в тексте шаблона: целое — без точки, иначе 6 значащих, как %g у printf."""
    if x != x:
        return 'NaN'
    if math.isinf(x):
        return 'inf' if x > 0 else '-inf'
    if x == math.floor(x) and abs(x) < 1e15:
        return str(int(x))
    return '%.6g' % x


TEMPLATE = re.compile(r'\{([^{}]*)\}')


def template_exprs(text):
    """Выражения шаблона по порядку; непарная фигурная скобка — ExprError."""
    if not isinstance(text, str):
        raise ExprError('текст — строка, а не %s' % type(text).__name__)
    rest = TEMPLATE.sub('', text)
    if '{' in rest or '}' in rest:
        raise ExprError('непарная фигурная скобка в «%s»' % text)
    return TEMPLATE.findall(text)


def fill(text, env):
    """Шаблон → текст: {выражение} заменено числом по fmt."""
    template_exprs(text)
    return TEMPLATE.sub(lambda m: fmt(value(parse(m.group(1)), env)), text)
