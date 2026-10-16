import bpy
import json
import struct
from pathlib import Path
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view
root = Path(__file__).resolve().parent.parent
bpy.ops.wm.open_mainfile(filepath=str(root / 'artifacts/01-chair.blend'))
scene = bpy.context.scene
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
png = root / 'artifacts/01-chair.png'
with png.open('rb') as f:
    header = f.read(24)
assert header[:8] == b'\x89PNG\r\n\x1a\n'
assert struct.unpack('>II', header[16:24]) == (512,512)
report_path = root / 'artifacts/01-chair-verification.json'
report = json.loads(report_path.read_text())
report['framing'] = {'normalized_x': xrange, 'normalized_y': yrange, 'all_furniture_in_frame': True}
report['png_dimensions'] = [512,512]
report_path.write_text(json.dumps(report, indent=2))
print('Framing and PNG verified:', report['framing'], 'artifact bytes:', png.stat().st_size)
