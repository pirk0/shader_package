# -*- coding: utf-8 -*-
"""ЯЗЫК ВЫРАЖЕНИЙ НА ВЕКТОРАХ — эталон expr.py против vectors/expr.json, 7 блоков.

Векторы — договор для каждого хоста: вторая реализация языка обязана пройти их так же. Стенд судит
эталон и сами векторы:
  1 значение и тип; 2 пустота — имени нет, и решают имена, а не значения; 3 ошибки синтаксиса и
  типа; 4 шаблоны текста; 5 float32, которое получит шейдер;
  6 язык — подмножество GLSL ES 3.00: каждое выражение блока 1 собирает glslangValidator с тем же
    типом, а у каждой ошибки блока 3 подтверждено, принимает ли её сам GLSL (true — язык строже
    намеренно). Нужен GLSLANG=<путь к glslangValidator>; без него блок говорит, что не работал;
  7 отрицательные контроли: испорченный эталон (mod как fmod, min без NaN, деление целых,
    неявное int→float, приоритет && и ||, ceil без −0, шаблон без правила целых, половина вверх,
    f32 без округления, короткое замыкание) обязан провалить хотя бы один вектор.

Запуск из корня репо:  python tests/vectors_check.py      (код 1 — нарушение)
"""
import io
import json
import math
import os
import subprocess
import sys
import tempfile
from decimal import ROUND_HALF_UP, Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import expr  # noqa: E402

VEC = json.load(io.open(os.path.join(ROOT, 'vectors', 'expr.json'), encoding='utf-8'))
SPECIAL = {'nan': math.nan, 'inf': math.inf, '-inf': -math.inf, '-0': -0.0}
GLSL_T = {'float': 'float', 'int': 'int', 'bool': 'bool', 'vec2': 'vec2', 'vec3': 'vec3'}
BAD = []


def num(v):
    if isinstance(v, str):
        return SPECIAL[v]
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    return float(v)


def same(got, want):
    w = num(want)
    if w != w:
        return got != got
    return got == w and math.copysign(1.0, got) == math.copysign(1.0, w)


def env_of(over):
    vals = dict(VEC['values'], **(over or {}))

    def env(name):
        if name not in vals:
            raise expr.Void(name)
        v = vals[name]
        return tuple(num(x) for x in v) if isinstance(v, list) else num(v)
    return env


def types(name):
    if name not in VEC['names']:
        raise expr.Void(name)
    return VEC['names'][name]


def run_vectors(say=None):
    """Блоки 1–5 → число провалов; say(блок, текст) печатает провал."""
    fails = [0]

    def fail(blk, txt):
        fails[0] += 1
        if say:
            say(blk, txt)

    for v in VEC['eval']:
        try:
            node = expr.parse(v['expr'])
            t = expr.typeof(node, types)
            got = expr.value(node, env_of(v.get('values')))
        except (expr.ExprError, expr.Void) as ex:
            fail(1, '«%s»: %s' % (v['expr'], ex))
            continue
        if t != v['type'] or not same(got, v['value']):
            fail(1, '«%s»: %s %r, а нужно %s %r' % (v['expr'], t, got, v['type'], v['value']))
    for v in VEC['void']:
        for what, call in (('тип', lambda n: expr.typeof(n, types)),
                           ('значение', lambda n: expr.value(n, env_of(None)))):
            try:
                r = call(expr.parse(v['expr']))
                fail(2, '«%s»: %s %r вместо пустоты' % (v['expr'], what, r))
            except expr.Void:
                pass
            except expr.ExprError as ex:
                fail(2, '«%s»: %s — ошибка «%s» вместо пустоты' % (v['expr'], what, ex))
    for v in VEC['error']:
        try:
            r = expr.typeof(expr.parse(v['expr']), types)
            fail(3, '«%s» принято как %s' % (v['expr'], r))
        except expr.ExprError:
            pass
        except expr.Void as ex:
            fail(3, '«%s»: пустота (%s) вместо ошибки' % (v['expr'], ex))
    for v in VEC['templates']:
        try:
            got = expr.fill(v['text'], env_of(v.get('values')))
        except (expr.ExprError, expr.Void) as ex:
            fail(4, '«%s»: %s' % (v['text'], ex))
            continue
        if got != v['result']:
            fail(4, '«%s» → «%s», а нужно «%s»' % (v['text'], got, v['result']))
    for v in VEC['template_error']:
        try:
            for s in expr.template_exprs(v['text']):
                expr.parse(s)
            fail(4, 'шаблон «%s» принят' % v['text'])
        except expr.ExprError:
            pass
    for v in VEC['f32']:
        got = expr.f32(num(v['in']))
        if not same(got, v['out']):
            fail(5, 'f32(%r) = %r, а нужно %r' % (v['in'], got, v['out']))
    return fails[0]


# ------------------------------------------------------------------ блок 6: GLSL --------------
def glsl_ok(glslang, body):
    """Собирает ли glslangValidator фрагментный шейдер с именами векторов и телом body."""
    decl = ''.join('uniform %s %s;\n' % (GLSL_T[t], n) for n, t in VEC['names'].items()
                   if n != 'iResolution')
    src = ('#version 300 es\nprecision highp float;\nprecision highp int;\nuniform vec3 '
           'iResolution;\n%sout vec4 o;\nvoid main() {\n%s\n  o = vec4(0.0);\n}\n' % (decl, body))
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, 'v.frag')
        io.open(f, 'w', encoding='utf-8').write(src)
        r = subprocess.run([glslang, '-S', 'frag', f], capture_output=True, text=True)
    return r.returncode == 0


def block6():
    glslang = os.environ.get('GLSLANG')
    if not glslang or not os.path.isfile(glslang):
        print('  блок не работал: нет GLSLANG=<путь к glslangValidator>')
        return None
    body = '\n'.join('  %s r%d = (%s);' % (v['type'], i, v['expr'])
                     for i, v in enumerate(VEC['eval']))
    if glsl_ok(glslang, body):
        print('  выражения блока 1 (%d) собраны glslang с их типами одним шейдером'
              % len(VEC['eval']))
    else:
        for v in VEC['eval']:
            if not glsl_ok(glslang, '  %s r = (%s);' % (v['type'], v['expr'])):
                BAD.append('блок 6: GLSL не собирает «%s» как %s' % (v['expr'], v['type']))
                print('  ✗ ' + BAD[-1])
    stricter = 0
    for v in VEC['error']:
        acc = any(glsl_ok(glslang, '  %s r = (%s);' % (t, v['expr'])) for t in GLSL_T)
        stricter += acc
        if acc != v['glsl']:
            BAD.append('блок 6: «%s» — glsl %s, а glslang %s' % (v['expr'], v['glsl'],
                                                               'принимает' if acc else 'нет'))
            print('  ✗ ' + BAD[-1])
    print('  ошибок блока 3: %d, из них GLSL принимает %d — там язык строже намеренно'
          % (len(VEC['error']), stricter))
    return True


# ------------------------------------------------------------------ блок 7: контроли ----------
def patched(name, setup):
    """Контекст: setup() портит эталон и возвращает функцию отката."""
    class Ctx:
        def __enter__(self):
            self.undo = setup()

        def __exit__(self, *a):
            self.undo()
    return name, Ctx()


def _swap(attr, value):
    def setup():
        old = getattr(expr, attr)
        setattr(expr, attr, value)
        return lambda: setattr(expr, attr, old)
    return setup


def _call(fn, impl):
    def setup():
        old = expr.CALL[fn]
        expr.CALL[fn] = impl
        return lambda: expr.CALL.__setitem__(fn, old)
    return setup


def _wrap(attr, make):
    def setup():
        old = getattr(expr, attr)
        setattr(expr, attr, make(old))
        return lambda: setattr(expr, attr, old)
    return setup


def lenient_div(orig):
    def typeof(node, types_):
        if node[0] == 'bin' and node[1] == '/':
            a, b = typeof(node[2], types_), typeof(node[3], types_)
            if a == b == 'int':
                return 'int'
        return orig(node, types_)
    return typeof


def implicit(orig):
    def typeof(node, types_):
        if node[0] == 'bin' and node[1] not in ('&&', '||'):
            a, b = typeof(node[2], types_), typeof(node[3], types_)
            if {a, b} == {'int', 'float'}:
                return 'bool' if node[1] in ('<', '<=', '>', '>=', '==', '!=') else 'float'
        return orig(node, types_)
    return typeof


def short_circuit(orig):
    def value(node, env):
        if node[0] == 'bin' and node[1] == '&&' and orig(node[2], env) == 0.0:
            return 0.0
        return orig(node, env)
    return value


def half_up(orig):
    def fmt(x):
        if x == x and not math.isinf(x) and not (x == math.floor(x) and abs(x) < 1e15):
            d = Decimal(x)
            e = d.adjusted()
            if -4 <= e < 6:
                q = d.quantize(Decimal(1).scaleb(e - 5), rounding=ROUND_HALF_UP)
                return format(q.normalize(), 'f')
        return orig(x)
    return fmt


CONTROLS = [
    patched('mod как fmod', _call('mod', math.fmod)),
    patched('min без NaN', _call('min', min)),
    patched('деление целых разрешено', _wrap('typeof', lenient_div)),
    patched('неявное int→float', _wrap('typeof', implicit)),
    patched('приоритет && и || перепутан',
            _swap('LEVELS', (('&&',), ('||',)) + expr.LEVELS[2:])),
    patched('ceil без −0', _call('ceil', lambda x: float(math.ceil(x)))),
    patched('шаблон без правила целых', _swap('fmt', lambda x: '%.6g' % x)),
    patched('половина — вверх', _wrap('fmt', half_up)),
    patched('f32 без округления', _swap('f32', lambda x: x)),
    patched('короткое замыкание', _wrap('value', short_circuit)),
]


def main():
    print('=== 1–5. векторы: значение, пустота, ошибки, шаблоны, float32 ' + '=' * 30)
    n = run_vectors(lambda b, t: (BAD.append('блок %d: %s' % (b, t)), print('  ✗ ' + BAD[-1])))
    total = sum(len(VEC[k]) for k in ('eval', 'void', 'error', 'templates', 'template_error',
                                      'f32'))
    print('  векторов %d, провалов %d' % (total, n))
    print('=== 6. язык — подмножество GLSL ES 3.00 ' + '=' * 52)
    block6()
    print('=== 7. отрицательные контроли ' + '=' * 62)
    for name, ctx in CONTROLS:
        with ctx:
            k = run_vectors()
        print('  %s %-30s провалов векторов: %d' % ('✓' if k else '✗', name, k))
        if not k:
            BAD.append('блок 7: контроль «%s» не пойман векторами' % name)
    print('\nНАРУШЕНИЙ: %d' % len(BAD) if BAD else '\nВСЁ ЧИСТО')
    return 1 if BAD else 0


if __name__ == '__main__':
    sys.exit(main())
