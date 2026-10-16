import bpy
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from furniture_helpers import reset_scene, material, box, studio, bounds

root = Path(__file__).resolve().parent.parent
out = root / 'artifacts'
out.mkdir(exist_ok=True)
scene = reset_scene()
oak = material('Natural oak | satin finish', (0.48, 0.285, 0.125), 0.34)
# Subtle procedural grain, stretched along the timber's vertical direction.
nodes = oak.node_tree.nodes
links = oak.node_tree.links
tex = nodes.new('ShaderNodeTexNoise')
tex.inputs['Scale'].default_value = 4
tex.inputs['Detail'].default_value = 2
coord = nodes.new('ShaderNodeTexCoord')
mapping = nodes.new('ShaderNodeVectorMath')
mapping.operation = 'MULTIPLY'
mapping.inputs[1].default_value = (4, 4, 0.35)
links.new(coord.outputs['Generated'], mapping.inputs[0])
links.new(mapping.outputs['Vector'], tex.inputs['Vector'])
ramp = nodes.new('ShaderNodeValToRGB')
ramp.color_ramp.elements[0].position = 0.15
ramp.color_ramp.elements[0].color = (0.29, 0.135, 0.047, 1)
ramp.color_ramp.elements[1].position = 0.85
ramp.color_ramp.elements[1].color = (0.56, 0.34, 0.16, 1)
links.new(tex.outputs['Fac'], ramp.inputs[0])
links.new(ramp.outputs[0], nodes.get('Principled BSDF').inputs['Base Color'])
box('Seat', (0.48, 0.48, 0.05), (0, 0, 0.425), oak, 0.006)
for i, (x,y) in enumerate([(-0.195,-0.195),(0.195,-0.195),(-0.195,0.195),(0.195,0.195)], 1):
    box('Leg_' + str(i), (0.045, 0.045, 0.4), (x,y,0.2), oak, 0.003)
# Back stays within the seat's depth footprint; upright stiles connect it to seat.
for side, x in [('Left', -0.213), ('Right', 0.213)]:
    box('Back upright ' + side, (0.04, 0.04, 0.435), (x,0.213,0.6675), oak, 0.003)
box('Back', (0.48, 0.04, 0.22), (0,0.213,0.79), oak, 0.005)
# A compact apron stiffens all four legs without hiding their distinct placement.
for y, name in [(-0.195, 'Front'), (0.195, 'Rear')]:
    box('Apron ' + name, (0.39,0.024,0.055), (0,y,0.3675), oak, 0.002)
for x, name in [(-0.195, 'Left'), (0.195, 'Right')]:
    box('Apron ' + name, (0.024,0.39,0.055), (x,0,0.3675), oak, 0.002)
floor = material('Warm neutral studio floor', (0.30,0.32,0.33), 0.8)
studio(scene, floor)
scene.render.filepath = str(out / '01-chair.png')
bpy.ops.wm.save_as_mainfile(filepath=str(out / '01-chair.blend'))
bpy.ops.render.render(write_still=True)
# Reopen the saved artifact rather than only checking transient construction values.
bpy.ops.wm.open_mainfile(filepath=str(out / '01-chair.blend'))
scene = bpy.context.scene
report = {'units': scene.unit_settings.system, 'scale_length': scene.unit_settings.scale_length,
          'engine': scene.render.engine, 'device': scene.cycles.device, 'samples': scene.cycles.samples,
          'resolution': [scene.render.resolution_x, scene.render.resolution_y], 'objects': {}}
for name in ['Seat', 'Leg_1', 'Leg_2', 'Leg_3', 'Leg_4', 'Back']:
    obj = bpy.data.objects[name]
    assert obj.type == 'MESH'
    report['objects'][name] = bounds(obj)
def close(a,b):
    assert abs(a-b)<1e-5, (a,b)
seat = report['objects']['Seat']
for a,b in zip(seat['dimensions'], (0.48,0.48,0.05)): close(a,b)
close(seat['min'][2], 0.4)
close(seat['max'][2], 0.45)
for i in range(1,5):
    leg = report['objects']['Leg_'+str(i)]
    close(leg['min'][2],0)
    close(leg['max'][2],0.4)
back = report['objects']['Back']
close(back['dimensions'][0],0.48)
close(back['max'][2],0.9)
assert scene.unit_settings.system == 'METRIC'
close(scene.unit_settings.scale_length, 1)
assert scene.render.engine == 'CYCLES' and scene.cycles.device == 'CPU' and scene.cycles.samples == 16
assert (out / '01-chair.png').is_file() and (out / '01-chair.blend').is_file()
report['checks_passed'] = True
(out / '01-chair-verification.json').write_text(json.dumps(report, indent=2))
print('VERIFIED', json.dumps(report))
