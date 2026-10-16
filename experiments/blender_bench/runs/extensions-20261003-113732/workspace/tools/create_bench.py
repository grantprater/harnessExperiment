import bpy
import sys
import json
import struct
from pathlib import Path
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view
sys.path.insert(0, str(Path(__file__).resolve().parent))
from furniture_helpers import reset_scene, material, box, studio, bounds

root = Path(__file__).resolve().parent.parent
out = root / 'artifacts'
out.mkdir(exist_ok=True)
scene = reset_scene()
oak = material('Bench | satin natural oak', (0.48, 0.285, 0.125), 0.34)
nodes = oak.node_tree.nodes
links = oak.node_tree.links
coord = nodes.new('ShaderNodeTexCoord')
stretch = nodes.new('ShaderNodeVectorMath')
stretch.operation = 'MULTIPLY'
stretch.inputs[1].default_value = (0.35, 4, 4)
noise = nodes.new('ShaderNodeTexNoise')
noise.inputs['Scale'].default_value = 4
noise.inputs['Detail'].default_value = 2
ramp = nodes.new('ShaderNodeValToRGB')
ramp.color_ramp.elements[0].position = 0.15
ramp.color_ramp.elements[0].color = (0.29, 0.135, 0.047, 1)
ramp.color_ramp.elements[1].position = 0.85
ramp.color_ramp.elements[1].color = (0.56, 0.34, 0.16, 1)
links.new(coord.outputs['Generated'], stretch.inputs[0])
links.new(stretch.outputs['Vector'], noise.inputs['Vector'])
links.new(noise.outputs['Fac'], ramp.inputs[0])
links.new(ramp.outputs[0], nodes.get('Principled BSDF').inputs['Base Color'])
box('Seat', (1.2, 0.4, 0.05), (0, 0, 0.425), oak, 0.005)
# Each end support is a single solid slab, inset slightly from seat ends.
for i, x in enumerate([-0.51,0.51], 1):
    box('Support_' + str(i), (0.075, 0.36, 0.4), (x,0,0.2), oak, 0.003)
# Rear uprights connect the full-width back panel firmly to the seat.
for side, x in [('Left',-0.51),('Right',0.51)]:
    box('Back upright ' + side, (0.05,0.045,0.385), (x,0.175,0.6425), oak, 0.003)
box('Back', (1.2,0.045,0.25), (0,0.175,0.725), oak, 0.005)
box('Underseat rail', (1.02,0.045,0.065), (0,0.12,0.3675), oak, 0.002)
floor = material('Bench studio | warm neutral', (0.30,0.32,0.33), 0.8)
studio(scene, floor, target=(0,0,0.40), camera_location=(1.6,-2.5,1.5), ortho_scale=1.85)
scene.render.filepath = str(out / '03-bench.png')
bpy.ops.wm.save_as_mainfile(filepath=str(out / '03-bench.blend'))
bpy.ops.render.render(write_still=True)

# Inspect saved artifact, not just construction inputs.
bpy.ops.wm.open_mainfile(filepath=str(out / '03-bench.blend'))
scene = bpy.context.scene
report = {'units': scene.unit_settings.system, 'scale_length': scene.unit_settings.scale_length,
          'engine': scene.render.engine, 'device': scene.cycles.device, 'samples': scene.cycles.samples,
          'resolution': [scene.render.resolution_x, scene.render.resolution_y], 'objects': {}}
def close(a,b):
    assert abs(a-b) < 1e-5, (a,b)
for name in ['Seat','Support_1','Support_2','Back']:
    obj = bpy.data.objects[name]
    assert obj.type == 'MESH'
    report['objects'][name] = bounds(obj)
seat = report['objects']['Seat']
for a,b in zip(seat['dimensions'], (1.2,0.4,0.05)): close(a,b)
close(seat['min'][2], 0.40)
close(seat['max'][2], 0.45)
for i in range(1,3):
    support = report['objects']['Support_'+str(i)]
    close(support['min'][2], 0)
    close(support['max'][2], 0.40)
    for a,b in zip(support['dimensions'], (0.075,0.36,0.4)): close(a,b)
assert bpy.data.objects['Support_1'].location.x < 0 < bpy.data.objects['Support_2'].location.x
back = report['objects']['Back']
close(back['dimensions'][0], 1.2)
close(back['max'][2], 0.85)
assert scene.unit_settings.system == 'METRIC'
close(scene.unit_settings.scale_length, 1)
assert scene.render.engine == 'CYCLES' and scene.cycles.device == 'CPU' and scene.cycles.samples == 16
assert scene.render.resolution_percentage == 100
assert scene.render.resolution_x == scene.render.resolution_y == 512
points = []
for obj in scene.objects:
    if obj.type == 'MESH' and obj.name != 'Floor':
        for corner in obj.bound_box:
            points.append(world_to_camera_view(scene, scene.camera, obj.matrix_world @ Vector(corner)))
xrange = [min(p.x for p in points), max(p.x for p in points)]
yrange = [min(p.y for p in points), max(p.y for p in points)]
assert 0.04 < xrange[0] < xrange[1] < 0.96
assert 0.04 < yrange[0] < yrange[1] < 0.96
assert all(p.z > 0 for p in points)
report['framing'] = {'normalized_x': xrange, 'normalized_y': yrange, 'all_furniture_in_frame': True}
assert (out / '03-bench.blend').is_file()
with (out / '03-bench.png').open('rb') as f:
    header = f.read(24)
assert header[:8] == b'\x89PNG\r\n\x1a\n'
assert struct.unpack('>II', header[16:24]) == (512,512)
report['checks_passed'] = True
(out / '03-bench-verification.json').write_text(json.dumps(report, indent=2))
print('VERIFIED', json.dumps(report))
