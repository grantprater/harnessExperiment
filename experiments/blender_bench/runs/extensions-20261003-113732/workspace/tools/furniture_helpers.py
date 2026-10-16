import bpy
from mathutils import Vector


def reset_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 1.0
    return scene


def material(name, color, roughness=0.4):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (*color, 1)
    bsdf.inputs['Roughness'].default_value = roughness
    return mat


def box(name, dimensions, center, mat, bevel=0.003):
    bpy.ops.mesh.primitive_cube_add(size=1, location=center)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(mat)
    if bevel:
        modifier = obj.modifiers.new('Soft furniture edges', 'BEVEL')
        modifier.width = bevel
        modifier.segments = 3
        modifier = obj.modifiers.new('Weighted corner normals', 'WEIGHTED_NORMAL')
        modifier.keep_sharp = True
    return obj


def aim(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat('-Z', 'Y').to_euler()


def studio(scene, floor_mat, target=(0, 0, 0.43), camera_location=(1.25, -1.65, 1.18), ortho_scale=1.32):
    box('Floor', (200, 200, 0.04), (0, 0, -0.02), floor_mat, bevel=0)
    bpy.ops.object.camera_add(location=camera_location)
    camera = bpy.context.object
    camera.name = 'Camera'
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = ortho_scale
    aim(camera, target)
    scene.camera = camera
    for name, location, power, size in [
        ('Key softbox', (-2.5, -3, 4), 450, 3),
        ('Fill softbox', (3, -1, 2.5), 220, 2.5),
        ('Rim softbox', (0.5, 2.5, 3), 350, 2),
    ]:
        bpy.ops.object.light_add(type='AREA', location=location)
        lamp = bpy.context.object
        lamp.name = name
        lamp.data.energy = power
        lamp.data.shape = 'DISK'
        lamp.data.size = size
        aim(lamp, target)
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs[0].default_value = (0.32, 0.36, 0.42, 1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value = 0.3
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 16
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 512
    scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.view_settings.view_transform = 'AgX'


def bounds(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    points = [evaluated.matrix_world @ Vector(corner) for corner in evaluated.bound_box]
    return {
        'min': [min(p[i] for p in points) for i in range(3)],
        'max': [max(p[i] for p in points) for i in range(3)],
        'dimensions': [max(p[i] for p in points)-min(p[i] for p in points) for i in range(3)],
    }
