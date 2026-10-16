"""Reference-derived image and CSS style profiles with explicit, limited transforms.

These measurements describe palette/tokens and coarse visual statistics. They do
not establish artistic style, semantic identity, accessibility, or overall quality.
"""
from __future__ import annotations

from collections import Counter
import difflib
import hashlib
import io
import json
import math
from pathlib import Path
import re

from PIL import Image, ImageFilter, ImageStat

from reticle.storage.artifacts import atomic_write_json


VERSION = 'style-measurements-v1'
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'}
COLOR = re.compile(r'#[0-9a-fA-F]{8}\b|#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{4}\b|#[0-9a-fA-F]{3}\b|rgba?\([^()]*\)', re.I)
LENGTH = re.compile(r'(?<![\w.-])(-?(?:\d+(?:\.\d*)?|\.\d+))(px|rem|em|%)(?![\w-])', re.I)
SPACING = {'padding', 'margin', 'gap', 'row-gap', 'column-gap'}
FONT_NAMES = {'font-family', 'font-size', 'font-weight', 'line-height', 'letter-spacing'}


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def color_rgb(token):
    token = token.lower()
    if token.startswith('#'):
        raw = token[1:]
        if len(raw) in (3, 4):
            raw = ''.join(c * 2 for c in raw)
        return [int(raw[i:i+2], 16) for i in (0, 2, 4)]
    values = token[token.index('(')+1:token.rindex(')')].replace(',', ' ').replace('/', ' ').split()
    if len(values) < 3:
        raise ValueError('Unsupported RGB color syntax')
    result = []
    for value in values[:3]:
        number = float(value[:-1]) * 255 / 100 if value.endswith('%') else float(value)
        if not math.isfinite(number) or not 0 <= number <= 255:
            raise ValueError('RGB color is outside its range')
        result.append(round(number))
    return result


def distance(a, b):
    return math.sqrt(sum((x-y)**2 for x, y in zip(a, b)))


def hex_rgb(rgb):
    return '#' + ''.join(f'{round(v):02x}' for v in rgb)


def uncomment(text):
    # Keep indices and line numbers intact for evidence and edits.
    return re.sub(r'/\*.*?\*/', lambda m: ''.join('\n' if c == '\n' else ' ' for c in m.group()), text, flags=re.S)


def declarations(text):
    """Small CSS declaration scanner respecting strings and parentheses.

    Handles declarations inside ordinary/nested rules; it is not a full CSS parser.
    """
    clean = uncomment(text)
    quote, escaped, parentheses, start = None, False, 0, 0
    found = []
    for index, character in enumerate(clean):
        if quote:
            if escaped:
                escaped = False
            elif character == '\\':
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in "\"'":
            quote = character
        elif character == '(':
            parentheses += 1
        elif character == ')':
            parentheses = max(0, parentheses-1)
        elif character in '{};' and parentheses == 0:
            if character in ';}':
                segment = clean[start:index]
                match = re.fullmatch(r'\s*([\w-]+)\s*:\s*(.*?)\s*', segment, flags=re.S)
                if match:
                    begin, end = start+match.start(2), start+match.end(2)
                    found.append({'property': match.group(1).lower(), 'value': match.group(2),
                                  'start': begin, 'end': end, 'line': clean.count('\n', 0, begin)+1})
            start = index+1
    if quote or parentheses:
        raise ValueError('Unterminated CSS string or parenthesis')
    return found


def family(value):
    # Keep commas/semicolons inside quoted family names from becoming CSS syntax.
    pieces, current, quote, escaped = [], [], None, False
    for character in value:
        if quote:
            if escaped:
                current.append(character)
                escaped = False
            elif character == '\\':
                escaped = True
            elif character == quote:
                quote = None
            else:
                current.append(character)
        elif character in "\"'":
            quote = character
        elif character == ',':
            pieces.append(''.join(current))
            current = []
        else:
            current.append(character)
    pieces.append(''.join(current))
    if quote:
        raise ValueError('Unterminated font family')
    generic = {'serif', 'sans-serif', 'monospace', 'system-ui', 'cursive', 'fantasy',
               'ui-serif', 'ui-sans-serif', 'ui-monospace', 'ui-rounded', 'inherit'}
    names = [re.sub(r'\s+', ' ', p).strip().lower() for p in pieces if p.strip()]
    return ','.join(name if name in generic else json.dumps(name) for name in names)


def category(prop):
    if prop in SPACING or prop.startswith('padding-') or prop.startswith('margin-'):
        return 'spacing'
    if prop == 'border-radius' or prop.startswith('border-') and prop.endswith('-radius'):
        return 'radii'
    if prop == 'font-size':
        return 'font_sizes'
    return None


def css_measurements(data):
    text = data.decode('utf-8')
    rows = declarations(text)
    colors, fonts, lengths = [], [], defaultdict_list()
    unresolved = []
    definitions = {row['property']: row['value'] for row in rows if row['property'].startswith('--')}
    named_colors = []
    for row in rows:
        value = row['value']
        for _ in range(10):
            updated = re.sub(r'var\(\s*(--[\w-]+)\s*\)', lambda m: definitions.get(m.group(1), m.group()), value)
            if updated == value:
                break
            value = updated
        if 'var(' in value:
            unresolved.append({'line': row['line'], 'property': row['property']})
        # Strings/URLs are not colors, even when they contain hexadecimal fragments.
        unquoted = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|url\([^)]*\)', '', value, flags=re.I)
        for match in COLOR.finditer(unquoted):
            colors.append({'rgb': color_rgb(match.group()), 'line': row['line'], 'property': row['property']})
        if row['property'] == 'font-family' and 'var(' not in value:
            fonts.append({'family': family(value), 'line': row['line']})
        kind = category(row['property'])
        if kind:
            for match in LENGTH.finditer(value):
                lengths[kind].append({'value': float(match.group(1)), 'unit': match.group(2).lower(),
                                      'line': row['line'], 'property': row['property']})
        # Named/HSL colors are explicitly outside this first adapter's coverage.
        if row['property'] in {'color', 'background-color', 'fill', 'stroke'} and not COLOR.search(value):
            stripped = value.strip().lower()
            if stripped not in {'transparent', 'currentcolor', 'inherit', 'initial', 'unset', 'none'} and 'var(' not in value:
                named_colors.append({'line': row['line'], 'property': row['property'], 'value': stripped})
    return {'domain': 'css', 'colors': colors, 'fonts': fonts, 'lengths': lengths,
            'unresolved_variables': unresolved, 'unsupported_color_values': named_colors,
            'declaration_count': len(rows)}


def defaultdict_list():
    return {'spacing': [], 'radii': [], 'font_sizes': []}


def image_measurements(data):
    with Image.open(io.BytesIO(data)) as source:
        if source.width * source.height > 20_000_000:
            raise ValueError('Style images are limited to 20 million pixels')
        rgba = source.convert('RGBA')
        dimensions = list(rgba.size)
    rgba.thumbnail((128, 128))
    pixels = rgba.get_flattened_data() if hasattr(rgba, 'get_flattened_data') else rgba.getdata()
    visible = [(r, g, b) for r, g, b, a in pixels if a >= 128]
    if not visible:
        raise ValueError('Reference/candidate image has no sufficiently opaque pixels')
    strip = Image.new('RGB', (len(visible), 1))
    strip.putdata(visible)
    reduced = strip.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    palette = reduced.getpalette()
    counts = sorted(reduced.getcolors(), reverse=True)
    colors = [{'rgb': palette[3*index:3*index+3], 'weight': count/len(visible)} for count, index in counts]
    luminance = strip.convert('L')
    stats = ImageStat.Stat(luminance)
    # Composite alpha consistently for coarse visual statistics; palette excludes transparency.
    background = Image.new('RGBA', rgba.size, 'white')
    gray = Image.alpha_composite(background, rgba).convert('L').resize((64, 64))
    edges = gray.filter(ImageFilter.FIND_EDGES).crop((1, 1, 63, 63))
    samples = [{'rgb': list(rgb), 'weight': count/len(visible)} for rgb, count in Counter(visible).items()]
    return {'domain': 'image', 'palette': colors, 'color_samples': samples, 'dimensions': dimensions,
            'brightness': stats.mean[0]/255, 'contrast': stats.stddev[0]/255,
            'edge_density': ImageStat.Stat(edges).mean[0]/255}


def measure(path):
    path = Path(path)
    if path.stat().st_size > 10_000_000:
        raise ValueError('Style inputs are limited to 10 MB')
    data = path.read_bytes()
    if path.suffix.lower() == '.css':
        return css_measurements(data)
    if path.suffix.lower() in IMAGE_SUFFIXES:
        return image_measurements(data)
    raise ValueError('Supported style inputs: raster images and .css files')


def profile_from_references(records, name='Project style'):
    profiles = {}
    for domain in ('image', 'css'):
        items = [row['measurements'] for row in records if row['measurements']['domain'] == domain]
        if not items:
            continue
        colors = []
        for item in items:
            source = item['palette'] if domain == 'image' else item['colors']
            for color in source:
                rgb = color['rgb']
                if not any(distance(rgb, existing) < 12 for existing in colors):
                    colors.append(rgb)
        if len(colors) > 128:
            raise ValueError('References contain too many distinct colors for a project palette; narrow the references')
        entry = {'palette': colors, 'reference_count': len(items)}
        if domain == 'image':
            entry['statistics'] = {key: {'min': min(item[key] for item in items),
                                         'max': max(item[key] for item in items)}
                                   for key in ('brightness', 'contrast', 'edge_density')}
        else:
            entry['font_families'] = sorted({f['family'] for item in items for f in item['fonts']})
            entry['length_tokens'] = {key: [{'value': value, 'unit': unit} for value, unit in sorted({
                (length['value'], length['unit']) for item in items for length in item['lengths'][key]})]
                for key in ('spacing', 'radii', 'font_sizes')}
        profiles[domain] = entry
    if not any(p['palette'] or p.get('font_families') or any(p.get('length_tokens', {}).values()) for p in profiles.values()):
        raise ValueError('References contain no supported style features')
    return {'profile_version': 1, 'extractor_version': VERSION, 'name': name, 'domains': profiles,
            'references': [{'path': row['path'], 'sha256': row['sha256'], 'domain': row['measurements']['domain'],
                            'coverage': {key: row['measurements'].get(key, []) for key in
                                         ('unresolved_variables', 'unsupported_color_values')}} for row in records],
            'policy': {'color_distance_rgb': 30, 'image_outside_palette_fraction': 0.1,
                       'length_tolerance': 0.01, 'statistics': 'advisory'},
            'limitations': 'Reference-derived palette/tokens and coarse image statistics; not a semantic or artistic style judgment.'}


def check_measurements(measured, profile):
    domain = measured['domain']
    target = profile['domains'].get(domain)
    if not target:
        raise ValueError(f'Profile has no {domain} references')
    findings, advisory = [], []
    palette = target['palette']
    threshold = profile['policy']['color_distance_rgb']
    if domain == 'image':
        if not palette:
            raise ValueError('Image profile has no palette')
        outside = 0.0
        for color in measured['color_samples']:
            difference = min(distance(color['rgb'], reference) for reference in palette)
            if difference > threshold:
                outside += color['weight']
                findings.append({'feature': 'palette', 'observed': hex_rgb(color['rgb']),
                                 'weight': color['weight'], 'nearest_distance_rgb': round(difference, 2)})
        passed = outside <= profile['policy']['image_outside_palette_fraction']
        for key, limits in target['statistics'].items():
            value = measured[key]
            if value < limits['min']-0.08 or value > limits['max']+0.08:
                advisory.append({'feature': key, 'observed': value, 'reference_range': limits})
        findings.sort(key=lambda row: -row['weight'])
        return {'domain': domain, 'measured_checks_passed': passed, 'complete': True,
                'outside_palette_fraction': round(outside, 4), 'findings': findings[:20],
                'mismatched_color_count': len(findings),
                'advisory': advisory, 'semantic_style_assessed': False}
    for color in measured['colors']:
        if palette and min(distance(color['rgb'], ref) for ref in palette) > threshold:
            findings.append({'feature': 'palette', 'line': color['line'], 'property': color['property'],
                             'observed': hex_rgb(color['rgb']), 'allowed': [hex_rgb(c) for c in palette]})
    for font in measured['fonts']:
        if target['font_families'] and font['family'] not in target['font_families']:
            findings.append({'feature': 'font_family', 'line': font['line'], 'observed': font['family'],
                             'allowed': target['font_families']})
    for key, lengths in measured['lengths'].items():
        allowed = target['length_tokens'][key]
        for length in lengths:
            if length['value'] == 0 or not allowed:
                continue
            if not any(token['unit'] == length['unit'] and abs(token['value']-length['value']) <= profile['policy']['length_tolerance'] for token in allowed):
                findings.append({'feature': key, **length, 'allowed': allowed})
    unsupported = measured['unresolved_variables'] + measured['unsupported_color_values']
    assessed = (len(measured['colors']) if palette else 0) + (len(measured['fonts']) if target['font_families'] else 0)
    assessed += sum(len(values) for key, values in measured['lengths'].items() if target['length_tokens'][key])
    complete = assessed > 0 and not unsupported
    if not assessed:
        advisory.append({'feature': 'insufficient_supported_style_evidence'})
    return {'domain': domain, 'measured_checks_passed': complete and not findings, 'complete': complete,
            'assessed_feature_count': assessed, 'findings': findings,
            'advisory': advisory + [{'feature': 'unsupported_or_unresolved_css', **row} for row in unsupported],
            'semantic_style_assessed': False}


def apply_css(text, target, operations):
    changes, edits = [], []
    rows = declarations(text)
    variable_roles = {}
    for row in rows:
        role = 'fonts' if row['property'] == 'font-family' else category(row['property'])
        if role:
            for variable in re.findall(r'var\(\s*(--[\w-]+)', row['value']):
                variable_roles.setdefault(variable, set()).add(role)
    for row in rows:
        original = value = row['value']
        if 'palette' in operations and target['palette']:
            def recolor(match):
                rgb = color_rgb(match.group())
                # Preserve alpha syntax: alpha colors require an explicit richer adapter.
                if match.group().lower().startswith('rgba') or len(match.group()) in (5, 9):
                    return match.group()
                return hex_rgb(min(target['palette'], key=lambda color: distance(rgb, color)))
            # Avoid changing strings/URLs and custom-variable references.
            if not re.search(r'url\(|[\"\']|var\(', value, re.I):
                value = COLOR.sub(recolor, value)
        roles = variable_roles.get(row['property'], set())
        role = next(iter(roles)) if len(roles) == 1 else None
        if 'fonts' in operations and (row['property'] == 'font-family' or role == 'fonts') and target['font_families'] and 'var(' not in value:
            if family(value) not in target['font_families']:
                value = target['font_families'][0]
        kind = role if role in ('spacing', 'radii', 'font_sizes') else category(row['property'])
        operation = {'spacing': 'spacing', 'radii': 'radii', 'font_sizes': 'font_sizes'}.get(kind)
        if operation in operations and target['length_tokens'].get(kind):
            def align(match):
                amount, unit = float(match.group(1)), match.group(2).lower()
                tokens = [token for token in target['length_tokens'][kind] if token['unit'] == unit]
                if not tokens or amount == 0:
                    return match.group()
                closest = min(tokens, key=lambda token: abs(token['value']-amount))
                return f'{closest["value"]:g}{unit}'
            value = LENGTH.sub(align, value)
        if value != original:
            changes.append({'line': row['line'], 'property': row['property'], 'before': original, 'after': value})
            edits.append((row['start'], row['end'], value))
    for start, end, value in reversed(edits):
        text = text[:start]+value+text[end:]
    return text, changes


class StyleService:
    def __init__(self, runtime, target_profile=None):
        self.runtime = runtime
        self.root = runtime.workspace.root / '.reticle/style-profiles'
        self.root.mkdir(parents=True, exist_ok=True)
        self.task_id = None
        self.target_path = runtime.session_dir / 'style-target.json'
        saved = json.loads(self.target_path.read_text(encoding='utf-8')) if self.target_path.exists() else None
        self.target_id = saved['profile_id'] if saved else None
        if target_profile:
            path = Path(target_profile)
            if not path.is_absolute():
                path = runtime.workspace.root / path
            profile = json.loads(path.read_text(encoding='utf-8'))
            profile_id = self.store(profile)
            if self.target_id and self.target_id != profile_id:
                raise ValueError('Changing a pinned style target requires a fresh session')
            self.target_id = profile_id
            atomic_write_json(self.target_path, {'profile_id': profile_id})
        if self.target_id:
            self.load(self.target_id)

    def store(self, profile):
        if not isinstance(profile, dict) or profile.get('profile_version') != 1 or profile.get('extractor_version') != VERSION:
            raise ValueError('Unsupported style profile version')
        if not isinstance(profile.get('domains'), dict) or not profile['domains'] or set(profile['domains']) - {'css', 'image'}:
            raise ValueError('Invalid style profile domains')
        # Imported targets must retain the measured-profile shape and policy types.
        policy = profile.get('policy', {})
        if not isinstance(policy, dict):
            raise ValueError('Invalid style profile policy')
        for key in ('color_distance_rgb', 'image_outside_palette_fraction', 'length_tolerance'):
            value = policy.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError('Invalid style profile policy')
        if policy['image_outside_palette_fraction'] > 1:
            raise ValueError('Invalid outside-palette fraction')
        for domain, entry in profile['domains'].items():
            if not isinstance(entry, dict):
                raise ValueError('Invalid style profile domain entry')
            colors = entry.get('palette')
            if not isinstance(colors, list) or len(colors) > 128 or any(not isinstance(c, list) or len(c) != 3 or
                    any(isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 255 for v in c) for c in colors):
                raise ValueError('Invalid profile palette')
            if domain == 'css':
                if not isinstance(entry.get('font_families'), list) or any(not isinstance(f, str) for f in entry['font_families']):
                    raise ValueError('Invalid profile font families')
                if any(family(f) != f for f in entry['font_families']):
                    raise ValueError('Profile font families must use canonical CSS syntax')
                lengths = entry.get('length_tokens')
                if not isinstance(lengths, dict):
                    raise ValueError('Invalid profile length tokens')
                for key in ('spacing', 'radii', 'font_sizes'):
                    if not isinstance(lengths.get(key), list):
                        raise ValueError('Invalid profile length tokens')
                    for token in lengths[key]:
                        if not isinstance(token, dict) or not isinstance(token.get('value'), (int, float)) or isinstance(token['value'], bool) or not math.isfinite(token['value']) or token.get('unit') not in {'px', 'rem', 'em', '%'}:
                            raise ValueError('Invalid profile length token')
            else:
                if not colors or not isinstance(entry.get('statistics'), dict):
                    raise ValueError('Invalid image style profile')
                for key in ('brightness', 'contrast', 'edge_density'):
                    limits = entry.get('statistics', {}).get(key, {})
                    if not isinstance(limits, dict) or not all(isinstance(limits.get(k), (int, float)) and not isinstance(limits[k], bool)
                               and math.isfinite(limits[k]) for k in ('min', 'max')) or limits['min'] > limits['max']:
                        raise ValueError('Invalid image statistics')
        profile_id = sha(encoded(profile))
        path = self.root / (profile_id + '.json')
        if path.exists() and path.read_bytes() != encoded(profile):
            raise ValueError('Style profile changed after extraction')
        if not path.exists():
            from reticle.storage.artifacts import atomic_write_bytes
            atomic_write_bytes(path, encoded(profile))
        return profile_id

    def begin_turn(self, task_id):
        self.task_id = task_id
        if self.target_id:
            self.load(self.target_id)
        self.runtime.journal.append('style_turn_snapshot', {'task_id': task_id, 'profile_id': self.target_id})

    def load(self, profile_id=None):
        profile_id = profile_id or self.target_id
        if self.target_id and profile_id != self.target_id:
            raise ValueError('This session has a pinned style target; proposals cannot replace it')
        if not isinstance(profile_id, str) or not re.fullmatch('[a-f0-9]{64}', profile_id):
            raise ValueError('Supply a profile_id from style_extract or pin --style-profile')
        data = (self.root / (profile_id + '.json')).read_bytes()
        if sha(data) != profile_id:
            raise ValueError('Style profile changed after extraction')
        profile = json.loads(data)
        return profile_id, profile

    def extract(self, references, name='Project style'):
        if not isinstance(references, list) or not 1 <= len(references) <= 20 or any(not isinstance(p, str) for p in references):
            raise ValueError('Supply 1 to 20 workspace reference paths')
        records = []
        for relative in references:
            path = self.runtime.workspace._resolve(relative)
            if path.stat().st_size > 10_000_000:
                raise ValueError('Style inputs are limited to 10 MB')
            records.append({'path': path.relative_to(self.runtime.workspace.root).as_posix(),
                            'sha256': sha(path.read_bytes()), 'measurements': measure(path)})
        profile = profile_from_references(records, name)
        profile_id = self.store(profile)
        self.runtime.journal.append('style_profile_extracted', {'task_id': self.task_id, 'profile_id': profile_id,
                                                               'reference_count': len(records)})
        return {'profile_id': profile_id, 'profile_path': (self.root / (profile_id+'.json')).relative_to(self.runtime.workspace.root).as_posix(),
                'profile': profile, 'pinned_target': self.target_id, 'proposal_only': self.target_id is not None}

    def profile(self, profile_id=None):
        profile_id, profile = self.load(profile_id)
        return {'profile_id': profile_id, 'pinned_target': self.target_id, 'profile': profile}

    def check(self, candidate, profile_id=None):
        profile_id, profile = self.load(profile_id)
        path = self.runtime.workspace._resolve(candidate)
        measured = measure(path)
        result = check_measurements(measured, profile)
        self.runtime.journal.append('style_check', {'task_id': self.task_id, 'profile_id': profile_id,
            'candidate': candidate, 'candidate_sha256': sha(path.read_bytes()), 'domain': measured['domain'],
            'complete': result['complete'], 'measured_checks_passed': result['measured_checks_passed']})
        return {'profile_id': profile_id, 'candidate': candidate, **result}

    def apply(self, candidate, output_path, operations, profile_id=None):
        profile_id, profile = self.load(profile_id)
        source = self.runtime.workspace._resolve(candidate)
        destination = self.runtime.workspace._resolve(output_path)
        if destination == source or destination.exists():
            raise ValueError('style_apply requires a new output path; existing files are preserved')
        measured = measure(source)
        domain = measured['domain']
        if domain not in profile['domains']:
            raise ValueError('Profile does not cover the candidate domain')
        valid = {'palette'} if domain == 'image' else {'palette', 'fonts', 'spacing', 'radii', 'font_sizes'}
        if not isinstance(operations, list) or not operations or any(not isinstance(op, str) or op not in valid for op in operations):
            raise ValueError('Supply explicit supported operations: ' + ', '.join(sorted(valid)))
        target = profile['domains'][domain]
        if domain == 'css':
            if destination.suffix.lower() != '.css':
                raise ValueError('CSS output must use .css')
            original = source.read_text(encoding='utf-8')
            transformed, changes = apply_css(original, target, operations)
            data = transformed.encode('utf-8')
            difference = ''.join(difflib.unified_diff(original.splitlines(True), transformed.splitlines(True),
                                                    fromfile=candidate, tofile=output_path))
        else:
            if destination.suffix.lower() != '.png' or not target['palette']:
                raise ValueError('Image application requires a palette and a new .png output')
            with Image.open(source) as image:
                rgba = image.convert('RGBA')
            palette_image = Image.new('P', (1, 1))
            colors = target['palette']
            palette_image.putpalette([v for color in colors for v in color] + colors[-1] * (256-len(colors)))
            transformed = rgba.convert('RGB').quantize(palette=palette_image, dither=Image.Dither.NONE).convert('RGBA')
            transformed.putalpha(rgba.getchannel('A'))
            stream = io.BytesIO()
            transformed.save(stream, format='PNG')
            data, changes, difference = stream.getvalue(), [{'operation': 'palette', 'colors': [hex_rgb(c) for c in colors]}], None
        self.runtime.workspace.write(output_path, data)
        after = self.check(output_path, profile_id)
        self.runtime.journal.append('style_applied', {'task_id': self.task_id, 'profile_id': profile_id,
            'candidate': candidate, 'output_path': output_path, 'operations': operations,
            'output_sha256': sha(data), 'domain': domain})
        return {'profile_id': profile_id, 'output_path': output_path, 'changes': changes,
                'diff': difference, 'after': after,
                'scope': 'Palette/token alignment only; semantic/artistic style and overall quality are unassessed.'}
