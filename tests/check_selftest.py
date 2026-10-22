# -*- coding: utf-8 -*-
"""ПРОВЕРКА ПАКЕТА НА ОБРАЗЦЕ И НА ПОДСАЖЕННЫХ ОШИБКАХ — check.py, 6 блоков.

  1 образец sample/ — ни ошибки, ни предупреждения; и с набором в подпапке на предельной глубине;
  2 отрицательные контроли: каждая подсаженная ошибка названа ЕЁ правилом и в ЕЁ месте, а каждое
    правило check.RULES и knobs_rules.RULES покрыто хотя бы одной (покрытие считается, а не
    обещается). Контроль, уронивший проверку исключением или жалобой «разбор», — провал;
  3 все ошибки разом: пять подсаженных в разные файлы — все пять в одном прогоне;
  4 битый вход любой формы — жалобы, а не исключение и не «разбор»;
  5 командная строка: код 0 на образце, 1 на испорченном, 2 без папки;
  6 репо не знает проектов: в правилах, коде, векторах и образце нет имён тех, от кого правила
    пришли (откуда они — только в docs/decisions.md); контроль — подсаженное имя ловится.

Запуск из корня репо:  python tests/check_selftest.py      (код 1 — нарушение)
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import check  # noqa: E402
import knobs_rules  # noqa: E402

SAMPLE = os.path.join(ROOT, 'sample')
BAD = []


def must(ok, msg):
    if not ok:
        BAD.append(msg)
        print('  ✗ ' + msg)
    return ok


class Pkg:
    """Копия образца во временной папке с правками."""

    def __init__(self, d):
        self.d = d

    def path(self, rel):
        return os.path.join(self.d, *rel.split('/'))

    def text(self, rel):
        return io.open(self.path(rel), encoding='utf-8').read()

    def write(self, rel, s):
        io.open(self.path(rel), 'w', encoding='utf-8', newline='\n').write(s)

    def sub(self, rel, old, new):
        s = self.text(rel)
        assert s.count(old) == 1, (rel, old)
        self.write(rel, s.replace(old, new))

    def json(self, rel, fn):
        d = json.loads(self.text(rel))
        fn(d)
        self.write(rel, json.dumps(d, ensure_ascii=False, indent=1))

    def man(self, fn):
        self.json('manifest.json', fn)

    def kj(self, fn):
        self.json('knobs.json', fn)


def knob(d, name):
    return [k for k in d['knobs'] + d['gates'] if k['name'] == name][0]


def review(edit):
    with tempfile.TemporaryDirectory() as tmp:
        d = os.path.join(tmp, 'pkg')
        shutil.copytree(SAMPLE, d)
        edit(Pkg(d))
        return check.review(d)


def _del(d, *ks):
    for k in ks:
        del d[k]


def deep_preset(p, rel, line):
    """Набор в подпапке пакета-копии: подпапки создаются."""
    os.makedirs(os.path.dirname(p.path(rel)), exist_ok=True)
    p.write(rel, '# набор в подпапке\n' + line + '\n')


# (имя, правка, правило, кусок «где») — правило и место той ошибки, которую подсадили
M = [
    ('описание не JSON', lambda p: p.write('manifest.json', '{'), 'файл', 'manifest.json'),
    ('незнакомый ключ', lambda p: p.man(lambda m: m.update(pass_=[])), 'ключ', 'manifest.json'),
    ('нет passes', lambda p: p.man(lambda m: _del(m, 'passes')), 'ключ', 'manifest.json'),
    ('чужая версия', lambda p: p.man(lambda m: m.update(format='shader-package/2')), 'формат',
     'format'),
    ('стиль не shadertoy', lambda p: p.man(lambda m: m.update(style='isf')), 'формат', 'style'),
    ('id не ASCII-идентификатор', lambda p: p.man(lambda m: m.update(id='Blur-Spot')), 'имя',
     'manifest.json id'),
    ('путь с ..', lambda p: p.man(lambda m: m['textures']['photo'].update(file='../x.png')),
     'путь', 'textures.photo.file'),
    ('путь в другом регистре',
     lambda p: p.man(lambda m: m['textures']['photo'].update(file='assets/Checker.png')),
     'путь', 'textures.photo.file'),
    ('нет файла knobs', lambda p: p.man(lambda m: m.update(knobs='knob.json')), 'путь',
     'manifest.json knobs'),
    ('вход не из списка',
     lambda p: p.man(lambda m: m.update(inputs=['iResolution', 'iTime', 'iMouse2'])), 'вход',
     'inputs'),
    ('вкладка читает iTime, его нет в inputs',
     lambda p: p.man(lambda m: m.update(inputs=['iResolution'])), 'вход', 'inputs'),
    ('вход не из версии 1',
     lambda p: p.write('image.glsl', p.text('image.glsl')
                       + 'float fr() { return iFrameRate; }\n'), 'вход', 'image.glsl'),
    ('картинка не PNG и не JPEG', lambda p: p.write('assets/checker.png', 'GIF89a'), 'картинка',
     'textures.photo.file'),
    ('wrap не пара', lambda p: p.man(lambda m: m['textures']['photo'].update(wrap=['clamp'])),
     'картинка', 'textures.photo.wrap'),
    ('формат буфера', lambda p: p.man(lambda m: m['buffers']['A'].update(format='rgb8')),
     'буфер', 'buffers.A.format'),
    ('очистка не RGBA', lambda p: p.man(lambda m: m['buffers']['A'].update(clear=[0, 0, 0])),
     'буфер', 'buffers.A.clear'),
    ('буфер не пишет никто',
     lambda p: p.man(lambda m: m['buffers'].update(B={'format': 'rgba8'})), 'буфер',
     'buffers.B'),
    ('буфер и картинка с одним именем',
     lambda p: p.man(lambda m: m['textures'].update(A=dict(m['textures']['photo']))), 'имя',
     'buffers.A'),
    ('экран пишет не последний пасс',
     lambda p: p.man(lambda m: m.update(passes=m['passes'][::-1])), 'пасс', 'passes[0].output'),
    ('канал пуст, а вкладка его читает',
     lambda p: p.man(lambda m: m['passes'][1].update(channels=['photo'])), 'пасс',
     'passes[1].channels[1]'),
    ('источника канала нет',
     lambda p: p.man(lambda m: m['passes'][1].update(channels=['photo', 'B'])), 'пасс',
     'passes[1].channels[1]'),
    ('нет mainImage', lambda p: p.sub('blur.glsl', 'void mainImage', 'void mainImg'), 'вкладка',
     'blur.glsl'),
    ('вкладка пишет main()',
     lambda p: p.write('image.glsl', p.text('image.glsl') + 'void main() {}\n'), 'вкладка',
     'image.glsl'),
    ('ручка объявлена второй раз',
     lambda p: p.write('image.glsl', 'uniform float BLUR;\n' + p.text('image.glsl')), 'вкладка',
     'image.glsl'),
    ('#version во вкладке',
     lambda p: p.write('common.glsl', '#version 300 es\n' + p.text('common.glsl')), 'вкладка',
     'common.glsl'),
    ('ручки есть, общей вкладки нет', lambda p: p.man(lambda m: _del(m, 'common')), 'вкладка',
     'manifest.json'),
    ('float == int', lambda p: p.man(lambda m: m['passes'][0]['skip'][0].update(when='BLUR == 0')),
     'выражение', 'skip[0].when'),
    ('when — не bool', lambda p: p.man(lambda m: m['passes'][0]['skip'][0].update(when='BLUR')),
     'выражение', 'skip[0].when'),
    ('имени нет',
     lambda p: p.man(lambda m: m['passes'][0]['skip'][0].update(when='BLURR == 0.0')),
     'выражение', 'skip[0].when'),
    ('текстовый гейт в выражении',
     lambda p: p.man(lambda m: m['time'].update(when='EDGE != 0')), 'выражение', 'time.when'),
    ('битый шаблон',
     lambda p: p.man(lambda m: m['warnings'][0].update(text='{nx +}')), 'выражение',
     'warnings[0].text'),
    ('let ссылается на let',
     lambda p: p.man(lambda m: m['let'].update(nz='nx * 2.0')), 'выражение', 'let.nz'),
    ('деление целых в live',
     lambda p: p.man(lambda m: m['buffers']['A']['live'].__setitem__(
         0, 'iResolution.x / DOWNSCALE')), 'выражение', 'live[0]'),
    ('указатель — не точка кадра',
     lambda p: p.man(lambda m: m.update(pointer=[{'knob': 'RADIUS'}])), 'объявление',
     'pointer[0]'),
    ('пропуск без why',
     lambda p: p.man(lambda m: _del(m['passes'][0]['skip'][0], 'why')), 'объявление',
     'skip[0]'),
    ('пропуск у пасса на экран',
     lambda p: p.man(lambda m: m['passes'][1].update(skip=[{'when': 'BLUR == 0.0',
                                                            'why': 'x'}])), 'объявление',
     'passes[1].skip'),
    ('id предупреждения',
     lambda p: p.man(lambda m: m['warnings'][0].update(id='Too-Many')), 'предупреждение',
     'warnings[0].id'),
    ('предупреждение без text',
     lambda p: p.man(lambda m: _del(m['warnings'][0], 'text', 'text_ru')), 'предупреждение',
     'warnings[0]'),
    ('перевод на необъявленный язык',
     lambda p: p.man(lambda m: m['warnings'][0].update(text_de='x')), 'язык', 'warnings[0]'),
    ('набор: значение не той формы',
     lambda p: p.sub('presets/pulse.txt', 'BLUR=3', 'BLUR=abc'), 'набор',
     'presets/pulse.txt BLUR'),
    ('набор в подпапке: значение не той формы',
     lambda p: deep_preset(p, 'presets/a/b/c.txt', 'BLUR=abc'), 'набор', 'presets/a/b/c.txt BLUR'),
    ('набор глубже трёх частей',
     lambda p: deep_preset(p, 'presets/a/b/c/d.txt', 'BLUR=3'), 'набор', 'presets/a/b/c/d.txt'),
    ('knobs.json — не объект', lambda p: p.write('knobs.json', '[]'), 'файл', 'knobs.json'),
    ('незнакомое поле ручки',
     lambda p: p.kj(lambda d: knob(d, 'RADIUS').update(defualt=0.2)), 'поле',
     'knobs.json RADIUS'),
    ('имя — не идентификатор',
     lambda p: p.kj(lambda d: knob(d, 'RADIUS').update(name='2RADIUS')), 'имя',
     'knobs.json 2RADIUS'),
    ('имя занято строкой значений',
     lambda p: p.kj(lambda d: knob(d, 'COLS').update(name='ITIME')), 'имя', 'knobs.json ITIME'),
    ('order повторяется', lambda p: p.kj(lambda d: knob(d, 'ROWS').update(order=8)), 'order',
     'knobs.json ROWS'),
    ('sub с заглавной', lambda p: p.kj(lambda d: knob(d, 'RADIUS').update(sub='Fine')), 'группа',
     'knobs.json RADIUS'),
    ('тип vec4', lambda p: p.kj(lambda d: knob(d, 'RADIUS').update(type='vec4')), 'тип',
     'knobs.json RADIUS'),
    ('default — строка', lambda p: p.kj(lambda d: knob(d, 'RADIUS').update(default='0.25')),
     'форма', 'knobs.json RADIUS'),
    ('default вне диапазона', lambda p: p.kj(lambda d: knob(d, 'RADIUS').update(default=0.9)),
     'диапазон', 'knobs.json RADIUS'),
    ('ui:angle у float', lambda p: p.kj(lambda d: knob(d, 'RADIUS').update(ui='angle')), 'ui',
     'knobs.json RADIUS'),
    ('число с options',
     lambda p: p.kj(lambda d: knob(d, 'MAX_DOTS').update(options=[[1, 'a'], [2, 'b']])), 'kind',
     'knobs.json MAX_DOTS'),
    ('список из одной пары',
     lambda p: p.kj(lambda d: knob(d, 'PULSE_MODE').update(options=[[0, 'still']])), 'options',
     'knobs.json PULSE_MODE'),
    ('notable вне диапазона',
     lambda p: p.kj(lambda d: knob(d, 'BLUR').update(notable=[[9, 'x']], notable_ru=[[9, 'x']])),
     'точки', 'knobs.json BLUR'),
    ('дефолт в шейдере другой', lambda p: p.sub('common.glsl', '// =0.25', '// =0.3'), 'шейдер',
     'knobs.json RADIUS'),
    ('два #define одного гейта',
     lambda p: p.write('common.glsl', p.text('common.glsl') + '#define MAX_DOTS 8\n'), 'шейдер',
     'knobs.json MAX_DOTS'),
    ('целый гейт с дробным шагом',
     lambda p: p.kj(lambda d: knob(d, 'MAX_DOTS').update(step=0.5)), 'шейдер',
     'knobs.json MAX_DOTS'),
    ('группа без страницы',
     lambda p: p.kj(lambda d: d['pages'][1].update(groups=['BLUR'])), 'страницы',
     'knobs.json COLS'),
    ('help длиннее строки', lambda p: p.kj(lambda d: knob(d, 'RADIUS').update(help='x' * 101)),
     'help', 'knobs.json RADIUS'),
    ('подпись повторяется в группе',
     lambda p: p.kj(lambda d: knob(d, 'ROWS').update(label='Columns')), 'подпись',
     'knobs.json ROWS'),
    ('перевод подписи на необъявленный язык',
     lambda p: p.kj(lambda d: knob(d, 'RADIUS').update(label_de='Radius')), 'язык',
     'knobs.json RADIUS'),
]


def block1():
    ps = check.review(SAMPLE)
    for p in ps:
        print('  ✗ %s [%s] %s: %s' % p)
    must(not ps, 'образец дал %d жалоб' % len(ps))
    if not ps:
        print('  образец sample/: ошибок 0, предупреждений 0')
    # законная подпапка на предельной глубине (§7.3): ни жалобы на имя, и строка проверена
    ps = review(lambda p: deep_preset(p, 'presets/demo/wide/grid.txt', 'BLUR=3 COLS=4'))
    must(not ps, 'набор presets/demo/wide/grid.txt (три части) дал жалобы: %s' % ps[:2])
    if not ps:
        print('  набор в подпапке на глубине три: ошибок 0, предупреждений 0')


def block2():
    hit = set()
    for name, edit, rule, where in M:
        ps = review(edit)
        crash = [p for p in ps if p[2] == 'разбор']
        ok = any(p[0] == 'E' and p[2] == rule and where in p[1] for p in ps)
        if must(ok and not crash, 'контроль «%s»: нет ошибки [%s] в «%s»%s — получено %s'
                % (name, rule, where, ', проверка упала' if crash else '', ps[:3])):
            hit.add(rule)
    print('  контролей %d, пойманы своим правилом и местом: %d'
          % (len(M), len(M) - sum(b.startswith('контроль') for b in BAD)))
    for rules, who in ((check.RULES, 'check.RULES'), (knobs_rules.RULES, 'knobs_rules.RULES')):
        miss = [r for r in rules if r not in hit]
        must(not miss, '%s без контроля: %s' % (who, ', '.join(miss)))
    print('  правил покрыто: %d из %d' % (len(hit), len(set(check.RULES) | set(knobs_rules.RULES))))


def block3():
    pick = [m for m in M if m[0] in ('чужая версия', 'формат буфера', 'float == int',
                                     'order повторяется', 'дефолт в шейдере другой')]

    def edit(p):
        for m in pick:
            m[1](p)
    ps = review(edit)
    got = [m[0] for m in pick if any(p[2] == m[2] and m[3] in p[1] for p in ps)]
    must(len(got) == len(pick), 'разом названы %d из %d: %s' % (len(got), len(pick), got))
    print('  пять ошибок в разных файлах — в одном прогоне: %d из %d' % (len(got), len(pick)))


BROKEN = [
    ('описание — список', lambda p: p.write('manifest.json', '[]')),
    ('passes — объект', lambda p: p.man(lambda m: m.update(passes={}))),
    ('passes из чисел', lambda p: p.man(lambda m: m.update(passes=[1, 'x']))),
    ('channels — строка', lambda p: p.man(lambda m: m['passes'][0].update(channels='photo'))),
    ('skip — строка', lambda p: p.man(lambda m: m['passes'][0].update(skip='BLUR'))),
    ('live — строка', lambda p: p.man(lambda m: m['buffers']['A'].update(live='x'))),
    ('live из чисел', lambda p: p.man(lambda m: m['buffers']['A'].update(live=[1, None]))),
    ('textures — список', lambda p: p.man(lambda m: m.update(textures=[]))),
    ('картинка — строка', lambda p: p.man(lambda m: m['textures'].update(photo='x'))),
    ('buffers — список', lambda p: p.man(lambda m: m.update(buffers=[]))),
    ('let — список', lambda p: p.man(lambda m: m.update(let=[]))),
    ('let — число', lambda p: p.man(lambda m: m['let'].update(nx=5))),
    ('warnings — объект', lambda p: p.man(lambda m: m.update(warnings={}))),
    ('text — число', lambda p: p.man(lambda m: m['warnings'][0].update(text=5))),
    ('pointer — строка', lambda p: p.man(lambda m: m.update(pointer='SPOT'))),
    ('time — строка', lambda p: p.man(lambda m: m.update(time='x'))),
    ('inputs — строка', lambda p: p.man(lambda m: m.update(inputs='iTime'))),
    ('knobs — число', lambda p: p.man(lambda m: m.update(knobs=5))),
    ('common — число', lambda p: p.man(lambda m: m.update(common=7))),
    ('presets — число', lambda p: p.man(lambda m: m.update(presets=7))),
    ('code — число', lambda p: p.man(lambda m: m['passes'][0].update(code=5))),
    ('clear — строка', lambda p: p.man(lambda m: m['buffers']['A'].update(clear='x'))),
    ('ручки — объект', lambda p: p.kj(lambda d: d.update(knobs={}))),
    ('ручка — число', lambda p: p.kj(lambda d: d.update(knobs=[5]))),
    ('имя ручки — число', lambda p: p.kj(lambda d: d['knobs'][0].update(name=5))),
    ('options — строка', lambda p: p.kj(lambda d: knob(d, 'PULSE_MODE').update(options='a'))),
    ('pages — строка', lambda p: p.kj(lambda d: d.update(pages='a'))),
    ('languages — строка', lambda p: p.kj(lambda d: d.update(languages='en'))),
]


def block4():
    n = 0
    for name, edit in BROKEN:
        try:
            ps = review(edit)
        except Exception as ex:              # ⚠ именно это и судим: исключения быть не должно
            must(False, 'битый вход «%s»: исключение %s: %s' % (name, type(ex).__name__, ex))
            continue
        crash = [p for p in ps if p[2] == 'разбор']
        if must(not crash and any(p[0] == 'E' for p in ps),
                'битый вход «%s»: %s' % (name, crash[:1] or 'ни одной ошибки')):
            n += 1
    print('  битых входов %d, названы жалобами без падения: %d' % (len(BROKEN), n))


def block5():
    py = [sys.executable, os.path.join(ROOT, 'check.py')]
    env = dict(os.environ, PYTHONUTF8='1')
    rc0 = subprocess.run(py + [SAMPLE], capture_output=True, env=env).returncode
    with tempfile.TemporaryDirectory() as tmp:
        d = os.path.join(tmp, 'pkg')
        shutil.copytree(SAMPLE, d)
        Pkg(d).man(lambda m: m.update(format='x'))
        rc1 = subprocess.run(py + [d], capture_output=True, env=env).returncode
        rc2 = subprocess.run(py + [os.path.join(tmp, 'нет')], capture_output=True,
                             env=env).returncode
    must((rc0, rc1, rc2) == (0, 1, 2), 'коды выхода %s, а нужно (0, 1, 2)' % ((rc0, rc1, rc2),))
    print('  коды выхода: образец %d, испорченный %d, нет папки %d' % (rc0, rc1, rc2))


LEAKS = ('liquid', 'glass', 'animation_knobs', 'shader_web_viewer', 'knobs_panel')


def leaks(text):
    low = text.lower()
    return [w for w in LEAKS if w in low]


def block6():
    files = ['docs/format.md', 'vectors/expr.json'] + \
        [f for f in os.listdir(ROOT) if f.endswith('.py')] + \
        ['sample/' + os.path.relpath(os.path.join(d, f), SAMPLE).replace(os.sep, '/')
         for d, _s, fs in os.walk(SAMPLE) for f in fs if not f.endswith('.png')]
    for rel in files:
        found = leaks(io.open(os.path.join(ROOT, rel), encoding='utf-8').read())
        must(not found, '%s называет %s' % (rel, ', '.join(found)))
    must(leaks('# пришло из Liquid_Glass') == ['liquid', 'glass'], 'контроль: имя не поймано')
    print('  файлов %d, имён проектов в них — %s'
          % (len(files), 'нет' if not any(b.startswith('docs') or ' называет ' in b
                                           for b in BAD) else 'есть'))


def main():
    for n, (t, fn) in enumerate((('образец', block1), ('отрицательные контроли', block2),
                                 ('все ошибки разом', block3), ('битый вход', block4),
                                 ('командная строка', block5), ('без имён проектов', block6)), 1):
        print('=== %d. %s %s' % (n, t, '=' * max(3, 86 - len(t))))
        fn()
    print('\nНАРУШЕНИЙ: %d' % len(BAD) if BAD else '\nВСЁ ЧИСТО')
    return 1 if BAD else 0


if __name__ == '__main__':
    sys.exit(main())
