"""Real Blender fixtures for the read-only quality audit."""
import importlib.util
import json
from pathlib import Path

import bpy
import bmesh


path = Path(__file__).resolve().parents[2] / 'examples/extensions/blender_mesh_audit/mesh_audit.py'
spec = importlib.util.spec_from_file_location('mesh_quality', path)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
results = []


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def box(name, center=(0, 0, 0), dimensions=(1, 1, 1)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=center)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    return obj


def record(name, report, expected):
    assert report['passed'] is expected, (name, report)
    results.append({'fixture': name, 'passed': report['passed'], 'summary': report['summary']})


reset()
obj = box('Good cube')
before = [(tuple(v.co), v.index) for v in obj.data.vertices]
record('closed_cube', audit.audit_scene(), True)
assert before == [(tuple(v.co), v.index) for v in obj.data.vertices]

modifier = obj.modifiers.new('Bevel', 'BEVEL')
modifier.width = 0.05
modifier.segments = 3
record('beveled_cube', audit.audit_scene(), True)

reset()
box('Lower', (0, 0, 0))
box('Upper', (0, 0, 1))
record('opposite_facing_contact_allowed', audit.audit_scene(), True)

reset()
box('First')
box('Overlapping', (0.25, 0, 0))
report = audit.audit_scene()
record('same_facing_coplanar_overlap', report, False)
assert report['overlaps']['evaluated']['pair_count'] > 0

reset()
box('First')
box('Offset', (0.25, 0.1, 0.1))
record('ordinary_intersection_not_rejected', audit.audit_scene(), True)

reset()
obj = box('Union result')
operand = box('Hidden union operand', (0.25, 0, 0))
modifier = obj.modifiers.new('Union', 'BOOLEAN')
modifier.operation = 'UNION'
modifier.solver = 'EXACT'
modifier.object = operand
operand.hide_render = True
record('valid_boolean_workflow_allowed', audit.audit_scene(), True)

reset()
obj = box('Inward cube')
bm = bmesh.new()
bm.from_mesh(obj.data)
bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
bm.to_mesh(obj.data)
bm.free()
report = audit.audit_scene()
record('inward_shell', report, False)
assert report['objects'][0]['source']['counts']['inward_closed_shells'] == 1

reset()
cube = box('Shell template')
vertices = [tuple(v.co) for v in cube.data.vertices]
faces = [tuple(p.vertices) for p in cube.data.polygons]
mixed = bpy.data.meshes.new('Mixed shell orientation')
mixed.from_pydata(vertices + [(x+2, y, z) for x, y, z in vertices], [],
                  faces + [tuple(8+i for i in face[::-1]) for face in faces])
bpy.data.objects.remove(cube, do_unlink=True)
obj = bpy.data.objects.new('Mixed shells', mixed)
bpy.context.collection.objects.link(obj)
report = audit.audit_scene()
record('inward_shell_not_hidden_by_outward_shell', report, False)
assert report['objects'][0]['source']['counts']['inward_closed_shells'] == 1

reset()
obj = box('Inconsistent cube')
bm = bmesh.new()
bm.from_mesh(obj.data)
bmesh.ops.reverse_faces(bm, faces=[next(iter(bm.faces))])
bm.to_mesh(obj.data)
bm.free()
report = audit.audit_scene()
record('inconsistent_winding', report, False)
assert report['objects'][0]['source']['counts']['inconsistent_winding_edges'] > 0

reset()
mesh = bpy.data.meshes.new('Duplicate triangles')
mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2), (2, 1, 0)])
obj = bpy.data.objects.new('Duplicate faces', mesh)
bpy.context.collection.objects.link(obj)
report = audit.audit_scene(require_closed=False)
record('duplicate_faces', report, False)
assert report['objects'][0]['source']['counts']['duplicate_faces'] == 1

reset()
bpy.ops.mesh.primitive_plane_add(size=1)
record('open_surface_allowed_when_declared', audit.audit_scene(require_closed=False), True)
record('open_surface_rejected_for_solids', audit.audit_scene(require_closed=True), False)

reset()
obj = box('Reflected cube')
obj.scale.x = -1
report = audit.audit_scene()
record('negative_scale_is_advisory', report, True)
assert 'negative_transform_determinant' in report['objects'][0]['source']['warnings']

reset()
box('Budgeted cube')
record('incomplete_audit_does_not_pass', audit.audit_scene(max_triangles=1), False)

reset()
obj = box('Collapsed transform')
obj.scale.z = 0
record('singular_transform', audit.audit_scene(), False)

reset()
mesh = bpy.data.meshes.new('Empty mesh')
obj = bpy.data.objects.new('Empty object', mesh)
bpy.context.collection.objects.link(obj)
record('empty_mesh', audit.audit_scene(), False)

print('RETICLE_MESH_PREFLIGHT=' + json.dumps(results))
