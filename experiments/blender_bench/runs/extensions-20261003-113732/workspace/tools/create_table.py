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
oak = material('Table | satin natural oak', (0.48,0.285,0.125), 0.34)
nodes, links = oak.node_tree.nodes, oak.node_tree.links
coord = nodes.new('ShaderNodeTexCoord')
stretch = nodes.new('ShaderNodeVectorMath')
stretch.operation = 'MULTIPLY'
stretch.inputs[1].default_value = (0.35,4,4)
noise = nodes.new('ShaderNodeTexNoise')
noise.inputs['Scale'].default_value = 4
noise.inputs['Detail'].default_value = 2
ramp = nodes.new('ShaderNodeValToRGB')
ramp.color_ramp.elements[0].position = 0.15
ramp.color_ramp.elements[0].color = (0.29,0.135,0.047,1)
ramp.color_ramp.elements[1].position = 0.85
ramp.color_ramp.elements[1].color = (0.56,0.34,0.16,1)
links.new(coord.outputs['Generated'],stretch.inputs[0])
links.new(stretch.outputs['Vector'],noise.inputs['Vector'])
links.new(noise.outputs['Fac'],ramp.inputs[0])
links.new(ramp.outputs[0],nodes.get('Principled BSDF').inputs['Base Color'])
box('Tabletop', (1.2,0.7,0.05), (0,0,0.725), oak, 0.005)
for i,(x,y) in enumerate([(-0.51,-0.26),(0.51,-0.26),(-0.51,0.26),(0.51,0.26)],1):
    box('Leg_'+str(i), (0.06,0.06,0.7), (x,y,0.35), oak,0.003)
for y,side in [(-0.26,'Front'),(0.26,'Rear')]:
    box('Apron '+side,(1.02,0.028,0.085),(0,y,0.6575),oak,0.002)
for x,side in [(-0.51,'Left'),(0.51,'Right')]:
    box('Apron '+side,(0.028,0.52,0.085),(x,0,0.6575),oak,0.002)
floor = material('Table studio | warm neutral',(0.30,0.32,0.33),0.8)
studio(scene,floor,target=(0,0,0.38),camera_location=(1.7,-2.3,1.65),ortho_scale=1.95)
scene.render.filepath = str(out/'05-table.png')
bpy.ops.wm.save_as_mainfile(filepath=str(out/'05-table.blend'))
bpy.ops.render.render(write_still=True)

# Inspect evaluated geometry from the saved scene.
bpy.ops.wm.open_mainfile(filepath=str(out/'05-table.blend'))
scene = bpy.context.scene
report = {'units':scene.unit_settings.system,'scale_length':scene.unit_settings.scale_length,
          'engine':scene.render.engine,'device':scene.cycles.device,'samples':scene.cycles.samples,
          'resolution':[scene.render.resolution_x,scene.render.resolution_y],'objects':{}}
def close(a,b):
    assert abs(a-b)<1e-5,(a,b)
for name in ['Tabletop','Leg_1','Leg_2','Leg_3','Leg_4']:
    obj=bpy.data.objects[name]
    assert obj.type=='MESH'
    assert obj.data.materials
    report['objects'][name]=bounds(obj)
top=report['objects']['Tabletop']
for a,b in zip(top['dimensions'],(1.2,0.7,0.05)): close(a,b)
close(top['min'][2],0.70)
close(top['max'][2],0.75)
centers=set()
for i in range(1,5):
    obj=bpy.data.objects['Leg_'+str(i)]
    leg=report['objects'][obj.name]
    close(leg['min'][2],0)
    close(leg['max'][2],0.70)
    centers.add((round(obj.location.x,4),round(obj.location.y,4)))
    for axis in [0,1]:
        assert top['min'][axis] < leg['min'][axis] < leg['max'][axis] < top['max'][axis]
assert len(centers)==4
assert 'Back' not in bpy.data.objects
assert scene.unit_settings.system=='METRIC'
close(scene.unit_settings.scale_length,1)
assert scene.render.engine=='CYCLES' and scene.cycles.device=='CPU' and scene.cycles.samples==16
assert scene.render.resolution_x==scene.render.resolution_y==512
assert scene.render.resolution_percentage==100
points=[]
for obj in scene.objects:
    if obj.type=='MESH' and obj.name!='Floor':
        points.extend(world_to_camera_view(scene,scene.camera,obj.matrix_world @ Vector(c)) for c in obj.bound_box)
xrange=[min(p.x for p in points),max(p.x for p in points)]
yrange=[min(p.y for p in points),max(p.y for p in points)]
assert 0.04<xrange[0]<xrange[1]<0.96
assert 0.04<yrange[0]<yrange[1]<0.96
assert all(p.z>0 for p in points)
report['framing']={'normalized_x':xrange,'normalized_y':yrange,'all_furniture_in_frame':True}
assert (out/'05-table.blend').is_file()
with (out/'05-table.png').open('rb') as f:
    header=f.read(24)
assert header[:8]==b'\x89PNG\r\n\x1a\n'
assert struct.unpack('>II',header[16:24])==(512,512)
report['back_absent']=True
report['checks_passed']=True
(out/'05-table-verification.json').write_text(json.dumps(report,indent=2))
print('VERIFIED',json.dumps(report))
