"""Run inside Blender: verify a known-good fixture and a deliberate defect."""
import importlib.util
import json
from pathlib import Path
import sys

import bpy


def cube(name, dimensions, location):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    return obj


bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.unit_settings.system = 'METRIC'
scene.unit_settings.scale_length = 1
seat = cube('Seat', (0.48, 0.48, 0.05), (0, 0, 0.425))
seat.data.materials.append(bpy.data.materials.new('Wood'))
for index, (x, y) in enumerate(((-0.2, -0.2), (-0.2, 0.2), (0.2, -0.2), (0.2, 0.2)), 1):
    cube('Leg_' + str(index), (0.04, 0.04, 0.4), (x, y, 0.2))
back = cube('Back', (0.48, 0.04, 0.45), (0, 0.22, 0.675))
bpy.ops.object.camera_add(location=(2, -2, 2))
scene.camera = bpy.context.object
path = Path(__file__).with_name('verify_furniture.py')
module_spec = importlib.util.spec_from_file_location('furniture_verifier', path)
module = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(module)
spec = {'surface': 'Seat', 'width': 0.48, 'depth': 0.48, 'height': 0.45, 'back_height': 0.90,
        'supports': ['Leg_1', 'Leg_2', 'Leg_3', 'Leg_4']}
good = module.verify(spec)
assert good['all_passed'], good
bpy.data.objects.remove(back, do_unlink=True)
bad = module.verify(spec)
assert not bad['all_passed'] and not bad['checks']['back_mesh'], bad
print('RETICLE_VERIFIER_PREFLIGHT=' + json.dumps({'good': good, 'deliberate_defect': bad}))
