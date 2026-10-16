"""Offline visual asset/UI demonstration. No model requests or downloads.

Run from the repository root:
  .venv/Scripts/python.exe experiments/style_tools/run_style_demo.py --output-dir experiments/style_tools/demo
Use a fresh output directory for each run; prior artifacts are preserved.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PIL import Image, ImageDraw
from reticle.runtime.session import LocalRuntime
from reticle.runtime.style import StyleService


REFERENCE = '''/* Reference UI tokens */
:root { --ink: #203040; --paper: #e0d0c0; --accent: #508080; --space: 16px; --radius: 8px; }
body { background: var(--paper); color: var(--ink); font-family: Arial, sans-serif; padding: var(--space); }
.card { background: var(--accent); padding: 16px; border-radius: var(--radius); font-size: 16px; }
'''
CANDIDATE = '''/* Deliberate drift from the reference */
:root { --ink: #60203f; --paper: #dbeda8; --accent: #408fa0; --space: 23px; --radius: 19px; }
body { background: var(--paper); color: var(--ink); font-family: Georgia, serif; padding: var(--space); }
.card { background: var(--accent); padding: 23px; border-radius: var(--radius); font-size: 21px; }
'''


def asset(path, colors):
    image = Image.new('RGBA', (360, 240), colors[0])
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((36, 40, 324, 200), radius=24, fill=colors[1])
    draw.ellipse((64, 76, 144, 156), fill=colors[2])
    draw.rectangle((180, 92, 288, 108), fill=colors[0])
    draw.rectangle((180, 124, 264, 140), fill=colors[0])
    image.save(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    options = parser.parse_args()
    root = options.output_dir.resolve()
    if root.exists():
        parser.error('Use a new output directory')
    root.mkdir(parents=True)
    workspace = root / 'workspace'
    workspace.mkdir()
    (workspace / 'reference.css').write_text(REFERENCE, encoding='utf-8')
    (workspace / 'candidate.css').write_text(CANDIDATE, encoding='utf-8')
    asset(workspace / 'reference.png', ['#e0d0c0', '#508080', '#203040'])
    asset(workspace / 'candidate.png', ['#dbeda8', '#408fa0', '#60203f'])
    runtime = LocalRuntime(root / 'session', workspace)
    style = StyleService(runtime)
    profile = style.extract(['reference.css', 'reference.png'], name='Visual/UI demo target')
    (root / 'target-profile.json').write_text(json.dumps(profile['profile'], indent=2), encoding='utf-8')
    # Start a new session with the independent target pinned, as in a batch experiment.
    style = StyleService(LocalRuntime(root / 'pinned-session', workspace), root / 'target-profile.json')
    style.begin_turn('offline-style-demo')
    results = {}
    for domain, operations in [('css', ['palette', 'fonts', 'spacing', 'radii', 'font_sizes']), ('png', ['palette'])]:
        candidate, output = f'candidate.{domain}', f'aligned.{domain}'
        before = style.check(candidate)
        applied = style.apply(candidate, output, operations)
        results[domain] = {'before': before, 'application': applied}
        if before['measured_checks_passed'] or not applied['after']['measured_checks_passed']:
            raise RuntimeError(f'Demo did not demonstrate correction for {domain}')
        if applied['diff']:
            (root / 'ui.diff').write_text(applied['diff'], encoding='utf-8')
    (root / 'report.json').write_text(json.dumps({'profile_id': profile['profile_id'], 'results': results}, indent=2), encoding='utf-8')
    (root / 'preview.html').write_text('''<!doctype html><html lang="en"><meta charset="utf-8">
<title>Visual and UI style demo</title>
<style>body{font:16px system-ui;margin:32px;background:#fafafa;color:#222}section{display:flex;gap:24px;flex-wrap:wrap}iframe{width:360px;height:190px;border:1px solid #ccc}img{width:360px}p{max-width:760px}</style>
<h1>Reference → candidate → aligned copy</h1>
<p>A controlled demonstration of palette and CSS token alignment. Shapes and composition stay the same. Passing these measurements does not establish artistic style or overall UI quality.</p>
<section><article><h2>Reference</h2><img src="workspace/reference.png"><iframe src="workspace/reference.html" title="Reference UI"></iframe></article>
<article><h2>Candidate</h2><img src="workspace/candidate.png"><iframe src="workspace/candidate.html" title="Candidate UI"></iframe></article>
<article><h2>Aligned</h2><img src="workspace/aligned.png"><iframe src="workspace/aligned.html" title="Aligned UI"></iframe></article></section>
<p>See report.json for measurements and ui.diff for the CSS changes.</p></html>''', encoding='utf-8')
    for name in ('reference', 'candidate', 'aligned'):
        (workspace / f'{name}.html').write_text(f'<!doctype html><html lang="en"><meta charset="utf-8"><link rel="stylesheet" href="{name}.css"><title>{name} UI</title><div class="card">Project card<br>Palette · type · spacing · radius</div></html>', encoding='utf-8')
    print(json.dumps({'output_dir': str(root), 'profile_id': profile['profile_id'],
                      'before_passed': {key: value['before']['measured_checks_passed'] for key, value in results.items()},
                      'after_passed': {key: value['application']['after']['measured_checks_passed'] for key, value in results.items()}}, indent=2))


if __name__ == '__main__':
    main()
