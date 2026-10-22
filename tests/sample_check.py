# -*- coding: utf-8 -*-
"""ПРАВДА ОБЪЯВЛЕНИЙ ОБРАЗЦА — sample/manifest.json против его вкладок, 8 блоков.

Проверка пакета судит форму, правду объявлений доказывает судья проекта (docs/format.md §4). У
образца проект — этот репо, и судья — этот стенд: хосты гоняют на образце свои пропуск, область
записи, время и указатель, и ложное объявление научило бы их ошибке.
  1 пропуск blur ↔ image: буфер A читает только image, и только под `if (BLUR != 0.0)`; условие
    пропуска равно отрицанию этой ветки на числах float32, включая −0, NaN и исчезающе малые;
  2 область записи ↔ discard пасса blur на кадрах разной чётности при каждом DOWNSCALE, и
    билинейная выборка image не выходит за неё;
  3 время ↔ стражи `#if`: каждая ссылка на iTime стоит под условием, равным time.when;
  4 предупреждение ↔ цикл точек: let равны формулам вкладки, и условие истинно ровно тогда, когда
    цикл обрезает решётку;
  5 указатель ↔ код: ручка указателя входит в кадр только долей кадра от левого нижнего угла;
  6 вкладки собираются glslangValidator при всех значениях гейтов-списков и краях гейтов-чисел,
    гейт — литералом типа своего #define (§2.1: у MARGIN край 0 — «0.0»); нужен GLSLANG=, без
    него блок говорит, что не работал;
  7 покрытие: в образце есть каждый тип ручки, каждое ui, каждый вид гейта и оба типа
    гейта-числа, подгруппа, страницы, особые точки, период, перевод, каждое объявление описания,
    набор в подпапке и картинка, у которой вкладка называет уровень мип-цепочки, — хост, прошедший
    свои стенды на образце, исполнил каждое поле правил;
  8 отрицательные контроли: испорченное объявление или вкладка ловится своим блоком.

Запуск из корня репо:  python tests/sample_check.py      (код 1 — нарушение)
"""
import copy
import io
import itertools
import json
import math
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import check  # noqa: E402
import expr  # noqa: E402
import knobs_rules  # noqa: E402

SAMPLE = os.path.join(ROOT, 'sample')
SIZES = ((8, 8), (9, 7), (15, 33), (640, 360), (641, 361), (1920, 1080), (1081, 1921))
BAD = []


def rd(rel):
    return io.open(os.path.join(SAMPLE, rel), encoding='utf-8').read()


def load():
    man = json.loads(rd('manifest.json'))
    src = {p['code']: rd(p['code']) for p in man['passes']}
    src['common.glsl'] = rd('common.glsl')
    return man, json.loads(rd('knobs.json')), src


def ev(s, vals):
    return expr.value(expr.parse(s), lambda n: vals[n])


def tree(s):
    return expr.parse(s)


def skip_vs_image(man, kj, src):
    out = []
    img = check.strip_comments(src['image.glsl'])
    lines = [ln for ln in img.splitlines() if 'iChannel1' in ln]
    if not lines or not all(re.search(r'\bif\s*\(\s*BLUR\s*!=\s*0\.0\s*\)', ln) for ln in lines):
        out.append('image читает iChannel1 не только под if (BLUR != 0.0)')
    readers = [(p['name'], i) for p in man['passes'] for i, c in enumerate(p.get('channels', []))
               if c == 'A']
    if readers != [('image', 1)]:
        out.append('буфер A читают %s, а не только image каналом 1' % readers)
    when = man['passes'][0]['skip'][0]['when']
    for b in (0.0, -0.0, 1e-50, 1e-45, 0.5, -2.0, float('nan'), float('inf')):
        v = {'BLUR': expr.f32(b)}
        if ev(when, v) != ev('!(BLUR != 0.0)', v):
            out.append('пропуск «%s» ≠ ветке image при BLUR = %r' % (when, b))
    return out


def live_vs_discard(man, kj, src):
    out = []
    blur = check.strip_comments(src['blur.glsl'])
    img = check.strip_comments(src['image.glsl'])
    m = re.search(r'if\s*\(\s*fragCoord\.x\s*>\s*(.+?)\s*\|\|\s*fragCoord\.y\s*>\s*(.+?)\s*\)\s*'
                  r'discard;', blur)
    defs = ('vec2 R = iResolution.xy;' in blur and 'float DS = float(DOWNSCALE);' in blur)
    reads = ('vec2 uv = fragCoord / R;' in img and 'R = iResolution.xy;' in img
             and 'texture(iChannel1, uv / float(DOWNSCALE))' in img)
    if not (m and defs and reads):
        return ['не узнать discard пасса blur или выборку image из буфера A']

    def glsl(s):
        s = re.sub(r'\bR\.([xy])\b', r'iResolution.\1', s)
        return re.sub(r'\bDS\b', 'float(DOWNSCALE)', s)
    live = man['buffers']['A']['live']
    for (w, h), ds in itertools.product(SIZES, (1, 2, 4)):
        v = {'iResolution': (float(w), float(h), 1.0), 'DOWNSCALE': float(ds)}
        for ax, lim in ((0, w), (1, h)):
            dis, lv = ev(glsl(m.group(ax + 1)), v), ev(live[ax], v)
            if dis != lv:
                out.append('%dx%d DOWNSCALE %d, ось %d: discard после %r, live %r'
                           % (w, h, ds, ax, dis, lv))
            # центр крайнего текселя, который берёт билинейная выборка image
            far = math.floor((lim - 0.5) / ds - 0.5) + 1.5
            if far > lv:
                out.append('%dx%d DOWNSCALE %d, ось %d: image читает тексель %r за live %r'
                           % (w, h, ds, ax, far, lv))
    return out


def time_vs_guards(man, kj, src):
    out = []
    want = tree(man['time']['when'])
    for rel, s in src.items():
        guard = []
        for n, ln in enumerate(check.strip_comments(s).splitlines(), 1):
            m = re.match(r'\s*#\s*if\s+(.+?)\s*$', ln)
            if m:
                guard.append(m.group(1))
            elif re.match(r'\s*#\s*endif\b', ln) and guard:
                guard.pop()
            elif re.search(r'\biTime\b', ln) and not any(tree(g) == want for g in guard):
                out.append('%s:%d — iTime не под #if %s' % (rel, n, man['time']['when']))
    return out


def warning_vs_loop(man, kj, src):
    out = []
    img = check.strip_comments(src['image.glsl'])
    if not ('for (int i = 0; i < MAX_DOTS; i++)' in img
            and 'if (float(i) >= nx * ny) break;' in img):
        return ['не узнать цикл точек в image']
    for n in ('nx', 'ny'):
        m = re.search(r'float %s = (.+?);' % n, img)
        if not m or tree(m.group(1)) != tree(man['let'][n]):
            out.append('let.%s ≠ формуле image' % n)
    w = man['warnings'][0]['when']
    lets = {n: tree(s) for n, s in man['let'].items()}
    for c, r, mx in itertools.product((-1.0, 0.4, 0.5, 1.0, 2.5, 3.0, 4.0, 7.49, 12.0),
                                      (0.0, 1.0, 1.5, 3.0, 4.4999999), (1, 4, 12, 16, 64)):
        v = {'COLS': expr.f32(c), 'ROWS': expr.f32(r), 'MAX_DOTS': float(mx)}
        v.update({n: expr.value(t, lambda k: v[k]) for n, t in lets.items()})
        need = v['nx'] * v['ny']
        drawn = sum(1 for i in range(mx) if not i >= need)    # цикл с break по nx * ny
        if (drawn < need) != bool(ev(w, v)):
            out.append('COLS %r ROWS %r MAX_DOTS %d: цикл рисует %d из %d, предупреждение %s'
                       % (c, r, mx, drawn, need, bool(ev(w, v))))
    return out


def pointer_vs_code(man, kj, src):
    ks = [p['knob'] for p in man.get('pointer', [])]
    if ks != ['SPOT']:
        return ['указатель водит %s, а точка кадра образца — SPOT' % ks]
    uses = [(rel, m.group(0)) for rel, s in src.items() if rel != 'common.glsl'
            for m in re.finditer(r'\bSPOT\b[^;\n]{0,6}', check.strip_comments(s))]
    if not uses or any(not u.startswith('SPOT * R') for _r, u in uses):
        return ['SPOT входит в кадр не только как SPOT * R: %s' % uses]
    return []


def compile_all(man, kj, src):
    glslang = os.environ.get('GLSLANG')
    if not glslang or not os.path.isfile(glslang):
        print('  блок не работал: нет GLSLANG=<путь к glslangValidator>')
        return []
    lists = [g for g in kj['gates'] if g.get('kind', 'options') == 'options']
    nums = [g for g in kj['gates'] if g.get('kind') == 'number']
    combos = list(itertools.product(*[[o[0] for o in g['options']] for g in lists],
                                    *[(g['min'], g['max']) for g in nums]))
    pre = ('#version 300 es\nprecision highp float;\nprecision highp int;\nprecision highp '
           'sampler2D;\n' + ''.join('uniform %s %s;\n' % (t, n) for t, n in
                                    (('vec3', 'iResolution'), ('float', 'iTime'))
                                    if n in man['inputs'])
           + ''.join('uniform sampler2D iChannel%d;\n' % i for i in range(4))
           + 'out vec4 shaderOut;\n')
    out, n = [], 0
    for combo in combos:
        common = src['common.glsl']
        for g, val in zip(lists + nums, combo):
            m = knobs_rules.define_re(g['name']).search(common)
            lit = (repr(float(val)) if knobs_rules.gate_type(g, src['common.glsl']) == 'float'
                   else str(int(val)))
            common = common[:m.start(1)] + lit + common[m.end(1):]
        for p in man['passes']:
            text = pre + common + src[p['code']] + \
                '\nvoid main() { mainImage(shaderOut, gl_FragCoord.xy); }\n'
            with tempfile.TemporaryDirectory() as d:
                f = os.path.join(d, 't.frag')
                io.open(f, 'w', encoding='utf-8').write(text)
                r = subprocess.run([glslang, '-S', 'frag', f], capture_output=True, text=True)
            n += 1
            if r.returncode:
                out.append('%s при %s: %s' % (p['code'], combo, r.stdout.strip()[-200:]))
    print('  сборок %d: %d сочетаний гейтов × %d пасса' % (n, len(combos), len(man['passes'])))
    return out


def coverage(man, kj, src):
    out = []
    ks, gs = kj['knobs'], kj['gates']
    nums = [g for g in gs if g.get('kind') == 'number']
    has = {
        'тип ручки': ({k['type'] for k in ks}, set(knobs_rules.TYPES)),
        'ui': ({k['ui'] for k in ks if 'ui' in k}, set(knobs_rules.UI_TYPE)),
        'вид гейта': ({g.get('kind', 'options') for g in gs}, {'options', 'number', 'text'}),
        'тип гейта-числа': ({knobs_rules.gate_type(g, src['common.glsl']) for g in nums},
                            {'int', 'float'}),
        'объявление': ({k for k in ('time', 'pointer', 'let', 'warnings', 'presets') if k in man}
                       | {k for p in man['passes'] for k in ('skip',) if k in p}
                       | {k for b in man.get('buffers', {}).values() for k in ('live',) if k in b},
                       {'skip', 'live', 'time', 'pointer', 'let', 'warnings', 'presets'}),
        'поле записи': ({f for e in ks + gs for f in ('sub', 'notable', 'periodic') if f in e}
                        | {'pages'} & set(kj) | {'languages'} & set(kj),
                        {'sub', 'notable', 'periodic', 'pages', 'languages'}),
    }
    for what, (got, want) in has.items():
        if want - got:
            out.append('%s: в образце нет %s' % (what, ', '.join(sorted(want - got))))
    deep = [d for d, _s, fs in os.walk(os.path.join(SAMPLE, man.get('presets', 'presets')))
            if fs and os.path.relpath(d, SAMPLE).count(os.sep) >= 1]
    if not deep:
        out.append('наборы: в образце нет набора в подпапке')
    tex = man.get('textures', {})
    lod = [p['name'] for p in man['passes'] for i, c in enumerate(p.get('channels', []))
           if tex.get(c, {}).get('mipmaps') and re.search(
               r'\btexture(?:Lod|Grad)\s*\(\s*iChannel%d\b' % i,
               check.strip_comments(src[p['code']]))]
    if not lod:
        out.append('картинки: ни одна вкладка не называет уровень мип-цепочки — хост, забывший '
                   'mipmaps, прошёл бы стенды на образце')
    return out


BLOCKS = [('пропуск blur ↔ image', skip_vs_image), ('область записи ↔ discard', live_vs_discard),
          ('время ↔ стражи #if', time_vs_guards), ('предупреждение ↔ цикл точек', warning_vs_loop),
          ('указатель ↔ код', pointer_vs_code), ('сборка glslang', compile_all),
          ('покрытие правил', coverage)]


def _m(fn):
    def mut(man, src):
        fn(man, src)
    return mut


CONTROLS = [
    ('область на полпикселя уже', 1, _m(lambda m, s: m['buffers']['A']['live'].__setitem__(
        0, 'iResolution.x / float(DOWNSCALE) + 0.5'))),
    ('пропуск при BLUR < 0', 0, _m(lambda m, s: m['passes'][0]['skip'][0].update(
        when='BLUR < 0.0'))),
    ('image читает A без ветки', 0, _m(lambda m, s: s.update({'image.glsl': s['image.glsl'].replace(
        'if (BLUR != 0.0) inside = ', 'inside = ')}))),
    ('время при PULSE_MODE == 2', 2, _m(lambda m, s: m['time'].update(when='PULSE_MODE == 2'))),
    ('предупреждение при ==', 3, _m(lambda m, s: m['warnings'][0].update(
        when='nx * ny >= float(MAX_DOTS)'))),
    ('let без max', 3, _m(lambda m, s: m['let'].update(nx='floor(COLS + 0.5)'))),
    ('указатель на RADIUS', 4, _m(lambda m, s: m.update(pointer=[{'knob': 'RADIUS'}]))),
    ('int вместо float во вкладке', 5, _m(lambda m, s: s.update(
        {'blur.glsl': s['blur.glsl'].replace('float DS = float(DOWNSCALE);',
                                             'float DS = DOWNSCALE;')}))),
    ('гейт MARGIN целым литералом', 5, _m(lambda m, s: s.update(
        {'common.glsl': s['common.glsl'].replace('#define MARGIN     0.02',
                                                 '#define MARGIN     1')}))),
    ('описание без указателя', 6, _m(lambda m, s: m.pop('pointer'))),
    ('уровень мип-цепочки не назван', 6, _m(lambda m, s: s.update(
        {'blur.glsl': s['blur.glsl'].replace('textureLod(iChannel0, ', 'texture(iChannel0, ')
                                    .replace(' * DS / R, lod);', ' * DS / R);')}))),
]


def main():
    man, kj, src = load()
    for n, (t, fn) in enumerate(BLOCKS, 1):
        print('=== %d. %s %s' % (n, t, '=' * max(3, 86 - len(t))))
        bad = fn(man, kj, src)
        for b in bad:
            BAD.append('блок %d: %s' % (n, b))
            print('  ✗ ' + b)
        if not bad and n < 6:
            print('  ✓ объявление верно')
        if not bad and n == 7:
            print('  ✓ каждое поле правил в образце есть')
    print('=== 8. отрицательные контроли ' + '=' * 62)
    for name, blk, mut in CONTROLS:
        if blk == 5 and not os.path.isfile(os.environ.get('GLSLANG') or ''):
            print('  - %-30s блок 6 не работал: нет GLSLANG' % name)
            continue
        m2, s2 = copy.deepcopy(man), dict(src)
        mut(m2, s2)
        got = BLOCKS[blk][1](m2, kj, s2)
        print('  %s %-30s блок %d: %s' % ('✓' if got else '✗', name, blk + 1,
                                         got[0][:60] if got else 'не пойман'))
        if not got:
            BAD.append('блок 8: контроль «%s» не пойман' % name)
    print('\nНАРУШЕНИЙ: %d' % len(BAD) if BAD else '\nВСЁ ЧИСТО')
    return 1 if BAD else 0


if __name__ == '__main__':
    sys.exit(main())
