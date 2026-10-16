"""Independent furniture checks; executed by Blender outside the model workspace."""
import json
import importlib.util
from pathlib import Path
import sys

import bpy
from mathutils import Vector


def bounds(obj):
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    points = [evaluated.matrix_world @ Vector(corner) for corner in evaluated.bound_box]
    return ([min(p[i] for p in points) for i in range(3)],
            [max(p[i] for p in points) for i in range(3)])


def verify(spec):
    checks = {}
    dimensions = {}
    scene = bpy.context.scene
    checks['metric_units'] = scene.unit_settings.system == 'METRIC' and abs(scene.unit_settings.scale_length - 1) < 0.001
    checks['camera'] = scene.camera is not None
    surface = bpy.data.objects.get(spec['surface'])
    checks['surface_mesh'] = surface is not None and surface.type == 'MESH'
    if checks['surface_mesh']:
        low, high = bounds(surface)
        dims = [high[i] - low[i] for i in range(3)]
        dimensions[spec['surface']] = {'min': low, 'max': high, 'dimensions': dims}
        checks['surface_width'] = abs(dims[0] - spec['width']) < 0.015
        checks['surface_depth'] = abs(dims[1] - spec['depth']) < 0.015
        checks['surface_height'] = abs(high[2] - spec['height']) < 0.015
        checks['surface_thickness'] = abs(dims[2] - 0.05) < 0.015
        checks['surface_material'] = len(surface.data.materials) > 0
    else:
        for name in ('surface_width', 'surface_depth', 'surface_height', 'surface_thickness', 'surface_material'):
            checks[name] = False
    for name in spec['supports']:
        obj = bpy.data.objects.get(name)
        checks[name + '_mesh'] = obj is not None and obj.type == 'MESH'
        if checks[name + '_mesh']:
            low, high = bounds(obj)
            dimensions[name] = {'min': low, 'max': high}
            checks[name + '_ground_contact'] = abs(low[2]) < 0.015
            checks[name + '_surface_contact'] = abs(high[2] - (spec['height'] - 0.05)) < 0.025
    back = bpy.data.objects.get('Back')
    if spec.get('back_height'):
        checks['back_mesh'] = back is not None and back.type == 'MESH'
        if checks['back_mesh']:
            low, high = bounds(back)
            dimensions['Back'] = {'min': low, 'max': high}
            checks['back_height'] = abs(high[2] - spec['back_height']) < 0.02
            checks['back_width'] = abs(high[0] - low[0] - spec['width']) < 0.02
            if spec.get('curved'):
                obj = back.evaluated_get(bpy.context.evaluated_depsgraph_get())
                points = [obj.matrix_world @ v.co for v in obj.data.vertices]
                center_x = (low[0] + high[0]) / 2
                inner = [p.y for p in points if abs(p.x - center_x) < spec['width'] * 0.2]
                outer = [p.y for p in points if abs(p.x - center_x) > spec['width'] * 0.35]
                checks['back_curvature_heuristic'] = bool(inner and outer) and abs(sum(inner)/len(inner) - sum(outer)/len(outer)) > 0.025
        else:
            checks['back_height'] = checks['back_width'] = False
            if spec.get('curved'):
                checks['back_curvature_heuristic'] = False
    else:
        checks['no_back'] = back is None
    # Load the trusted verifier implementation outside the model's editable workspace.
    audit_path = Path(__file__).resolve().parents[2] / 'examples/extensions/blender_mesh_audit/mesh_audit.py'
    module_spec = importlib.util.spec_from_file_location('independent_mesh_audit', audit_path)
    audit = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(audit)
    quality = audit.audit_scene(require_closed=True)
    checks['mesh_audit_complete'] = quality['complete']
    checks['mesh_topology_valid'] = quality['summary']['evaluated_topology_error_categories'] == 0
    checks['no_same_facing_coplanar_overlap'] = quality['summary']['evaluated_coplanar_face_pairs'] == 0
    return {'checks': checks, 'passed': sum(checks.values()), 'total': len(checks),
            'all_passed': all(checks.values()), 'bounds': dimensions, 'mesh_quality': quality}


if __name__ == '__main__':
    arguments = sys.argv[sys.argv.index('--') + 1:]
    spec = json.loads(Path(arguments[0]).read_text(encoding='utf-8'))
    Path(arguments[1]).write_text(json.dumps(verify(spec), indent=2), encoding='utf-8')
