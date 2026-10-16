"""Opt-in image/CSS style extraction, checking and explicit application."""
import json
import hashlib

from reticle.runtime.extensions import check_arguments
from reticle.tools.primitives import ToolOutcome, _function
from reticle.storage.artifacts import atomic_write_bytes


def check_summary(result):
    summary = {key: result[key] for key in ('profile_id', 'candidate', 'domain', 'complete',
               'measured_checks_passed', 'outside_palette_fraction', 'semantic_style_assessed') if key in result}
    summary['advisory_features'] = sorted({row['feature'] for row in result.get('advisory', [])})
    if not result['measured_checks_passed']:
        summary['findings'] = [{key: (value[:8] if key == 'allowed' and isinstance(value, list) else value)
                                for key, value in row.items()} for row in result.get('findings', [])[:3]]
        summary['finding_count'] = result.get('mismatched_color_count', len(result.get('findings', [])))
    return summary


STYLE_SCHEMAS = [
    _function('style_profile', 'Read the pinned project style target or an explicitly selected immutable profile, '
              'including palette, CSS tokens, measurement policy and reference evidence.',
              {'profile_id': {'type': 'string'}}, []),
    _function('style_extract', 'Extract a versioned project style profile from 1-20 workspace raster images and/or CSS files. '
              'Measures image palettes/coarse visual density and CSS colors, font families, spacing, font sizes and radii. '
              'Returns profile_id and the JSON profile. Profiles are immutable; extraction never replaces a pinned target. '
              'These features do not establish semantic or artistic style.',
              {'references': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'maxItems': 20},
               'name': {'type': 'string'}}, ['references']),
    _function('style_check', 'Compare a workspace image or CSS file with a measured style profile. '
              'Returns a compact decision and up to three actionable mismatches on failure. Full report is at report_path. Unknown CSS coverage cannot pass. '
              'Use profile_id from style_extract, or omit it when the session has a pinned --style-profile target.',
              {'candidate': {'type': 'string'}, 'profile_id': {'type': 'string'}}, ['candidate']),
    _function('style_apply', 'Write a NEW output file using explicit limited operations, preserving the source and existing files. '
              'Images: palette remapping only, to PNG with original size/alpha. CSS: palette, fonts, spacing, radii, font_sizes. '
              'Returns change count and a compact post-check; full changes/diff at report_path. Does not transfer shapes, composition, '
              'semantic style or establish accessibility. Use a pinned target or explicit profile_id.',
              {'candidate': {'type': 'string'}, 'output_path': {'type': 'string'},
               'operations': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1},
               'profile_id': {'type': 'string'}}, ['candidate', 'output_path', 'operations']),
]
PARAMETERS = {schema['function']['name']: schema['function']['parameters'] for schema in STYLE_SCHEMAS}


class StyleTools:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style = None

    def schemas(self):
        schemas = super().schemas()
        return [*schemas, *STYLE_SCHEMAS] if self.style else schemas

    def _dispatch(self, name, arguments, call_id):
        if not self.style or name not in PARAMETERS:
            return super()._dispatch(name, arguments, call_id)
        try:
            parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
            check_arguments(parsed, PARAMETERS[name])
        except (ValueError, TypeError) as exc:
            message = str(exc)
            return self._journaled(call_id, name, {}, lambda: ToolOutcome('ERROR: ' + message, 'rejected'))
        def action():
            method = {'style_profile': self.style.profile, 'style_extract': self.style.extract, 'style_check': self.style.check,
                      'style_apply': self.style.apply}[name]
            result = method(**parsed)
            if name in {'style_check', 'style_apply'}:
                raw = json.dumps(result, sort_keys=True).encode('utf-8')
                relative = '.reticle/style-reports/' + hashlib.sha256(raw).hexdigest() + '.json'
                atomic_write_bytes(self.runtime.workspace._resolve(relative), raw)
                if name == 'style_check':
                    summary = check_summary(result)
                else:
                    summary = {'profile_id': result['profile_id'], 'output_path': result['output_path'],
                               'change_count': len(result['changes']), 'after': check_summary(result['after'])}
                summary['report_path'] = relative
                result = summary
            return ToolOutcome(json.dumps(result, sort_keys=True, separators=(',', ':')), 'success')
        return self._journaled(call_id, name, parsed, action)
