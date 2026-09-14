from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import blender_env as be

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
FIXTURE_BLEND = FIXTURE_DIR / "prop_studio.blend"

SETUP_SCRIPT = f"""
import bpy
import math

# 1. Reset scene
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.name = "Prop_Studio"
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 1280
scene.render.resolution_y = 720

# 2. Build multi-component mechanical prop
# Chassis_Base
bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0.5))
chassis = bpy.context.active_object
chassis.name = "Chassis_Base"
chassis.dimensions = (2.0, 1.2, 0.6)

# Turret_Mount (child of Chassis)
bpy.ops.mesh.primitive_cylinder_add(radius=0.4, depth=0.3, location=(0, 0, 0.95))
turret = bpy.context.active_object
turret.name = "Turret_Mount"
turret.parent = chassis

# Sensor_Array (child of Turret)
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.25, location=(0.3, 0, 1.25))
sensor = bpy.context.active_object
sensor.name = "Sensor_Array"
sensor.parent = turret

# Antenna_Mast (child of Chassis)
bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=1.0, location=(-0.7, -0.4, 1.3))
antenna = bpy.context.active_object
antenna.name = "Antenna_Mast"
antenna.parent = chassis

# 3. 3-Point Studio Lighting
# Key_Light
bpy.ops.object.light_add(type="POINT", radius=0.25, location=(3.0, -3.0, 3.5))
key = bpy.context.active_object
key.name = "Key_Light"
key.data.energy = 100.0
key.data.color = (1.0, 1.0, 1.0)

# Fill_Light
bpy.ops.object.light_add(type="POINT", radius=0.5, location=(-3.0, -2.0, 2.0))
fill = bpy.context.active_object
fill.name = "Fill_Light"
fill.data.energy = 40.0
fill.data.color = (0.7, 0.8, 1.0)

# Rim_Light
bpy.ops.object.light_add(type="POINT", radius=0.3, location=(0.0, 3.5, 3.0))
rim = bpy.context.active_object
rim.name = "Rim_Light"
rim.data.energy = 60.0
rim.data.color = (1.0, 0.9, 0.7)

# 4. Studio Camera
bpy.ops.object.camera_add(location=(3.5, -3.5, 2.5), rotation=(math.radians(65), 0, math.radians(45)))
cam = bpy.context.active_object
cam.name = "Studio_Camera"
cam.data.lens = 35.0
scene.camera = cam

# 5. Save blend file
bpy.ops.wm.save_as_mainfile(filepath=r"{FIXTURE_BLEND}")
print("FIXTURE_SAVED_SUCCESSFULLY")
"""


def create_fixture():
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    res = be.run_blender_script(SETUP_SCRIPT)
    if "FIXTURE_SAVED_SUCCESSFULLY" in res.stdout:
        print(f"Prop studio fixture created successfully at: {FIXTURE_BLEND}")
    else:
        raise RuntimeError(f"Failed to create fixture: {res.traceback or res.stderr}")


if __name__ == "__main__":
    create_fixture()
