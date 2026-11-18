"""Supra falling from a jet above the clouds - 5 shots matching the original edit.
usage: python scene.py <blend_dir> <out_dir> <shot 1-5> [frame_step] [samples] [only_frame]"""
import bpy, sys, math, os
from mathutils import Vector, Euler

sys.path.insert(0, sys.argv[1])
import supra

OUT = sys.argv[2]
SHOT = int(sys.argv[3])
STEP = int(sys.argv[4]) if len(sys.argv) > 4 else 1
SAMPLES = int(sys.argv[5]) if len(sys.argv) > 5 else 48
ONLY = int(sys.argv[6]) if len(sys.argv) > 6 else None

# frames per shot (30 fps) -- cut points of the original: 2.6 / 5.17 / 7.7 / 10.33 / 12.87 s
LEN = {1: 86, 2: 77, 3: 76, 4: 79, 5: 76}

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = 'CYCLES'
cy = sc.cycles
cy.samples = SAMPLES
cy.use_adaptive_sampling = True
cy.adaptive_threshold = 0.03
cy.use_denoising = True
cy.max_bounces = 6
cy.diffuse_bounces = 1
cy.glossy_bounces = 3
cy.transmission_bounces = 4
cy.transparent_max_bounces = 8
cy.caustics_reflective = False
cy.caustics_refractive = False
cy.blur_glossy = 1.0
sc.render.resolution_x = 576
sc.render.resolution_y = 1024
sc.render.fps = 30
sc.render.use_motion_blur = True
sc.render.motion_blur_shutter = 0.35
sc.view_settings.view_transform = 'AgX'
sc.view_settings.look = 'AgX - Medium High Contrast'
sc.view_settings.exposure = 0.0
sc.render.image_settings.file_format = 'PNG'
sc.render.use_persistent_data = True

# ------------------------------------------------------------------ world
SUN_EL, SUN_ROT = math.radians(14), math.radians(200)
w = bpy.data.worlds.new('World')
sc.world = w
nt = w.node_tree
sky = nt.nodes.new('ShaderNodeTexSky')
sky.sky_type = 'MULTIPLE_SCATTERING'
sky.sun_elevation = SUN_EL
sky.sun_rotation = SUN_ROT
sky.altitude = 3000
sky.air_density = 1.2
sky.aerosol_density = 1.5
bg = nt.nodes['Background']
bg.inputs[1].default_value = 0.11
nt.links.new(sky.outputs[0], bg.inputs[0])
SUN_DIR = Vector((math.cos(SUN_EL) * math.sin(SUN_ROT), -math.cos(SUN_EL) * math.cos(SUN_ROT) * -1,
                  math.sin(SUN_EL)))


def make_mat(name):
    m = bpy.data.materials.new(name)
    return m, m.node_tree


# ------------------------------------------------------------------ cloud sea (displaced)
def cloud_sea(z=-160.0):
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=500, y_subdivisions=500, size=4500, location=(0, 0, z))
    ob = bpy.context.object
    ob.name = 'CloudSea'
    def disp(name, kind, scale, strength, **kw):
        t = bpy.data.textures.new(name, kind)
        t.noise_scale = scale
        for k, v in kw.items():
            setattr(t, k, v)
        d = ob.modifiers.new(name, 'DISPLACE')
        d.texture = t
        d.texture_coords = 'LOCAL'
        d.strength = strength
        d.mid_level = 0.5
    disp('big', 'CLOUDS', 220, 90, noise_depth=2, noise_type='SOFT_NOISE')
    disp('dome', 'VORONOI', 85, -70, distance_metric='DISTANCE', noise_intensity=1.0)
    disp('puff', 'VORONOI', 22, -14, distance_metric='DISTANCE', noise_intensity=1.0)
    disp('fine', 'CLOUDS', 6, 4, noise_depth=2)
    bpy.ops.object.shade_smooth()
    m, n = make_mat('Cloud')
    b = n.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (0.95, 0.93, 0.90, 1)
    b.inputs['Roughness'].default_value = 1.0
    b.inputs['Specular IOR Level'].default_value = 0.0
    b.inputs['Subsurface Weight'].default_value = 0.0
    b.inputs['Emission Color'].default_value = (1.0, 0.96, 0.92, 1)
    b.inputs['Emission Strength'].default_value = 0.18
    # soft translucency + fine bump for cauliflower detail
    tr = n.nodes.new('ShaderNodeBsdfTranslucent')
    tr.inputs[0].default_value = (1.0, 0.97, 0.93, 1)
    mix = n.nodes.new('ShaderNodeMixShader')
    mix.inputs[0].default_value = 0.0
    n.links.new(b.outputs[0], mix.inputs[1])
    n.links.new(tr.outputs[0], mix.inputs[2])
    # aerial-perspective haze toward the horizon
    cd = n.nodes.new('ShaderNodeCameraData')
    mth = n.nodes.new('ShaderNodeMath'); mth.operation = 'MULTIPLY'; mth.inputs[1].default_value = -1 / 1400
    n.links.new(cd.outputs['View Distance'], mth.inputs[0])
    ex = n.nodes.new('ShaderNodeMath'); ex.operation = 'EXPONENT'
    n.links.new(mth.outputs[0], ex.inputs[0])
    inv = n.nodes.new('ShaderNodeMath'); inv.operation = 'SUBTRACT'; inv.inputs[0].default_value = 1.0
    n.links.new(ex.outputs[0], inv.inputs[1])
    hz = n.nodes.new('ShaderNodeEmission'); hz.inputs[0].default_value = (0.86, 0.88, 0.92, 1); hz.inputs[1].default_value = 1.15
    mix2 = n.nodes.new('ShaderNodeMixShader')
    n.links.new(inv.outputs[0], mix2.inputs[0])
    n.links.new(mix.outputs[0], mix2.inputs[1])
    n.links.new(hz.outputs[0], mix2.inputs[2])
    n.links.new(mix2.outputs[0], n.nodes['Material Output'].inputs[0])
    tc = n.nodes.new('ShaderNodeTexCoord')
    nz = n.nodes.new('ShaderNodeTexNoise')
    nz.inputs['Scale'].default_value = 0.08
    nz.inputs['Detail'].default_value = 3
    n.links.new(tc.outputs['Object'], nz.inputs['Vector'])
    bump = n.nodes.new('ShaderNodeBump')
    bump.inputs['Strength'].default_value = 0.6
    bump.inputs['Distance'].default_value = 3.0
    n.links.new(nz.outputs['Fac'], bump.inputs['Height'])
    n.links.new(bump.outputs['Normal'], b.inputs['Normal'])
    n.links.new(bump.outputs['Normal'], tr.inputs['Normal'])
    ob.data.materials.append(m)
    ob.visible_shadow = False  # cheaper, clouds are self-lit enough
    with bpy.context.temp_override(object=ob, active_object=ob, selected_objects=[ob], selected_editable_objects=[ob]):
        for md in list(ob.modifiers):
            bpy.ops.object.modifier_apply(modifier=md.name)
    return ob


# ------------------------------------------------------------------ flat scattered cloud layer
def cloud_layer(name, z, size, scale, thresh, color=(1, 1, 1), strength=1.0):
    bpy.ops.mesh.primitive_plane_add(size=size, location=(0, 0, z))
    ob = bpy.context.object
    ob.name = name
    m, n = make_mat(name)
    m.blend_method = 'BLEND' if hasattr(m, 'blend_method') else None
    out = n.nodes['Material Output']
    b = n.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*color, 1)
    b.inputs['Roughness'].default_value = 1.0
    b.inputs['Emission Color'].default_value = (*color, 1)
    b.inputs['Emission Strength'].default_value = strength
    tc = n.nodes.new('ShaderNodeTexCoord')
    nz = n.nodes.new('ShaderNodeTexNoise')
    nz.inputs['Scale'].default_value = scale
    nz.inputs['Detail'].default_value = 10
    nz.inputs['Roughness'].default_value = 0.6
    n.links.new(tc.outputs['Object'], nz.inputs['Vector'])
    ramp = n.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position = thresh
    ramp.color_ramp.elements[1].position = thresh + 0.12
    n.links.new(nz.outputs['Fac'], ramp.inputs[0])
    trn = n.nodes.new('ShaderNodeBsdfTransparent')
    mix = n.nodes.new('ShaderNodeMixShader')
    n.links.new(ramp.outputs[0], mix.inputs[0])
    n.links.new(trn.outputs[0], mix.inputs[1])
    n.links.new(b.outputs[0], mix.inputs[2])
    n.links.new(mix.outputs[0], out.inputs[0])
    ob.data.materials.append(m)
    ob.visible_shadow = False
    return ob


# ------------------------------------------------------------------ airliner (generic T-tail jet)
def airliner():
    white = supra.mat('JetWhite', (0.85, 0.86, 0.88), rough=0.3, coat=0.5)
    blue = supra.mat('JetBlue', (0.05, 0.08, 0.35), metal=0.3, rough=0.3, coat=0.5, film=480)
    grey = supra.mat('JetGrey', (0.4, 0.42, 0.45), metal=0.6, rough=0.35)
    win = supra.mat('JetWin', (0.01, 0.01, 0.02), rough=0.1)
    root = bpy.data.objects.new('Jet', None)
    sc.collection.objects.link(root)

    def part(ob, m):
        ob.data.materials.append(m)
        ob.parent = root
        return ob
    # fuselage: lofted circle sections
    import bmesh
    bm = bmesh.new()
    secs = [(-17, 0.05, 0.6), (-16.2, 0.9, 0.3), (-14.5, 1.65, 0.0), (-11, 1.75, 0.0), (10, 1.75, 0.0),
            (13, 1.55, 0.25), (16, 0.9, 0.7), (18, 0.25, 1.1)]
    rings = []
    N = 24
    for x, r, zo in secs:
        rings.append([bm.verts.new((x, r * math.cos(2 * math.pi * k / N), zo + r * 1.05 * math.sin(2 * math.pi * k / N)))
                      for k in range(N)])
    for a, b in zip(rings, rings[1:]):
        for k in range(N):
            bm.faces.new((a[k], a[(k + 1) % N], b[(k + 1) % N], b[k]))
    bm.faces.new(rings[0][::-1])
    bm.faces.new(rings[-1])
    me = bpy.data.meshes.new('Fuse')
    bm.to_mesh(me)
    fu = bpy.data.objects.new('Fuse', me)
    sc.collection.objects.link(fu)
    fu.modifiers.new('s', 'SUBSURF').levels = 2
    fu.modifiers['s'].render_levels = 2
    part(fu, white)
    fu.data.materials.append(blue)
    for p in me.polygons:  # blue rear half / belly stripe
        if p.center.x > 6 or (p.center.z < -0.9 and p.center.x > -12):
            p.material_index = 1
    with bpy.context.temp_override(selected_editable_objects=[fu], active_object=fu, object=fu):
        bpy.ops.object.shade_smooth()

    def wing(name, root_x, span, chord, tip_chord, sweep, z, y0=0.0, dihedral=0.08, thick=0.35, vertical=False, m=white):
        bm = bmesh.new()
        rx0, rx1 = root_x, root_x - chord
        tx0 = root_x - sweep
        tx1 = tx0 - tip_chord
        tz = z + span * dihedral
        if vertical:
            pts = [(rx0, 0, z), (rx1, 0, z), (tx1, 0, z + span), (tx0, 0, z + span)]
            v = [bm.verts.new((x, y + d, zz)) for d in (-thick / 2, thick / 2) for (x, y, zz) in pts]
        else:
            pts = [(rx0, y0, z), (rx1, y0, z), (tx1, y0 + span, tz), (tx0, y0 + span, tz)]
            v = [bm.verts.new((x, y, zz + d)) for d in (-thick / 2, thick / 2) for (x, y, zz) in pts]
        f = [(0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
        for q in f:
            bm.faces.new([v[i] for i in q])
        me = bpy.data.meshes.new(name)
        bm.to_mesh(me)
        ob = bpy.data.objects.new(name, me)
        sc.collection.objects.link(ob)
        bv = ob.modifiers.new('b', 'BEVEL')
        bv.width = 0.12
        bv.segments = 3
        return part(ob, m)
    for s in (1, -1):
        wg = wing('Wing', 2.0, 14.5, 6.0, 1.6, 7.0, -1.0, y0=1.2)
        if s < 0:
            wg.scale.y = -1
        hs = wing('HStab', 16.8, 5.5, 2.6, 1.0, 2.6, 5.9, y0=0.1, dihedral=0.0, thick=0.2, m=blue)
        if s < 0:
            hs.scale.y = -1
        # rear engines on pylons
        bpy.ops.mesh.primitive_cylinder_add(radius=0.95, depth=5.5, vertices=32, location=(10.5, s * 2.9, 1.0),
                                            rotation=(0, math.pi / 2, 0))
        e = part(bpy.context.object, grey)
        e.data.materials.append(white)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.75, depth=0.1, location=(7.72, s * 2.9, 1.0),
                                            rotation=(0, math.pi / 2, 0))
        part(bpy.context.object, win)
        wing('Pylon', 11.5, 1.2, 2.5, 2.5, 0.0, 1.0, y0=s * 1.5 if s > 0 else -2.7, dihedral=0, thick=0.25)
        # cabin windows
        for k in range(22):
            bpy.ops.mesh.primitive_uv_sphere_add(radius=0.16, location=(-11 + k * 0.85, s * 1.72, 0.45))
            o = part(bpy.context.object, win)
            o.scale.y = 0.3
    fin = wing('Fin', 14.2, 5.6, 4.6, 2.4, 3.2, 0.9, vertical=True, thick=0.3, m=blue)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(-15.0, 0, 0.55))  # cockpit glass
    ck = part(bpy.context.object, win)
    ck.scale = (1.2, 2.2, 0.45)
    ck.rotation_euler = (0, 0.35, 0)
    return root


# ------------------------------------------------------------------ build
car, M = supra.build()
jet = airliner()

cam_data = bpy.data.cameras.new('Cam')
cam = bpy.data.objects.new('Cam', cam_data)
sc.collection.objects.link(cam)
sc.camera = cam
cam_data.sensor_fit = 'VERTICAL'
cam_data.clip_end = 20000
target = bpy.data.objects.new('Target', None)
sc.collection.objects.link(target)
tc = cam.constraints.new('TRACK_TO')
tc.target = target
tc.track_axis = 'TRACK_NEGATIVE_Z'
tc.up_axis = 'UP_Y'

sea = None


def key(ob, f, loc=None, rot=None):
    if loc is not None:
        ob.location = loc
        ob.keyframe_insert('location', frame=f)
    if rot is not None:
        ob.rotation_euler = [math.radians(a) for a in rot]
        ob.keyframe_insert('rotation_euler', frame=f)


def smooth_all():
    for ob in bpy.data.objects:
        ad = ob.animation_data
        if ad and ad.action:
            try:
                for fc in ad.action.fcurves[:0] if False else ad.action.fcurves:
                    for kp in fc.keyframe_points:
                        kp.interpolation = 'LINEAR'
            except AttributeError:  # layered actions (Blender 5)
                for layer in ad.action.layers:
                    for strip in layer.strips:
                        for cb in strip.channelbags:
                            for fc in cb.fcurves:
                                for kp in fc.keyframe_points:
                                    kp.interpolation = 'LINEAR'


N = LEN[SHOT]
sc.frame_start, sc.frame_end = 1, N
from mathutils import Matrix, Quaternion
car.rotation_mode = 'QUATERNION'
jet.rotation_mode = 'QUATERNION'
UP = Vector((0, 0, 1))


def basis(f, u):
    f = Vector(f).normalized()
    u = (Vector(u) - f * Vector(u).dot(f)).normalized()
    r = f.cross(u)
    return Matrix((f, u, r)).transposed()


def lerp(a, b, t):
    if isinstance(a, (int, float)):
        return a + (b - a) * t
    return Vector(a).lerp(Vector(b), t)


def frame_shot(A, B, jet_fn=None):
    """A/B: dicts at first/last frame: ldir, lup, wdir, roll, dist, look(local), lens."""
    for f in range(1, N + 1):
        t = (f - 1) / max(1, N - 1)
        P = {k: lerp(A[k], B[k], t) for k in A}
        wdir = Vector(P['wdir']).normalized()
        R = basis(wdir, UP) @ basis(P['ldir'], P['lup']).inverted()
        R = Matrix.Rotation(math.radians(P['roll']), 3, wdir) @ R
        q = R.to_quaternion()
        car.location = (0, 0, 0)
        car.rotation_quaternion = q
        car.keyframe_insert('rotation_quaternion', frame=f)
        car.keyframe_insert('location', frame=f)
        tgt = R @ Vector(P['look'])
        target.location = tgt
        target.keyframe_insert('location', frame=f)
        cam.location = tgt + wdir * P['dist']
        cam.keyframe_insert('location', frame=f)
        cam_data.lens = P['lens']
        cam_data.keyframe_insert('lens', frame=f)
        if jet_fn:
            right = (-wdir).cross(UP).normalized()
            loc, fwd = jet_fn(t, tgt, -wdir, right)
            jet.location = loc
            jet.rotation_quaternion = basis(Vector((-1, 0, 0)), UP).inverted().to_quaternion()
            jq = (basis(fwd, UP + right * 0.15) @ basis(Vector((-1, 0, 0)), UP).inverted()).to_quaternion()
            jet.rotation_quaternion = jq
            jet.keyframe_insert('location', frame=f)
            jet.keyframe_insert('rotation_quaternion', frame=f)


if SHOT == 1:
    cloud_layer('Scatter', -600, 6000, 0.0016, 0.47, strength=0.25)
    cloud_layer('Scatter2', -900, 9000, 0.0011, 0.50, strength=0.2)
    bpy.ops.mesh.primitive_plane_add(size=40000, location=(0, 0, -2500))
    bpy.context.object.data.materials.append(supra.mat('Ocean', (0.01, 0.04, 0.12), rough=0.15))
    car.rotation_mode = 'XYZ'
    cam_data.lens = 30
    key(cam, 1, (0, 0, 0)); key(cam, N, (0, 0, -18))
    key(target, 1, (0.3, 0.6, -100)); key(target, N, (0.3, 0.6, -118))
    key(car, 1, (-6, 9, -230), (20, 40, 10)); key(car, N, (-1, 2.5, -48), (110, 160, 120))
    jet.rotation_mode = 'XYZ'
    key(jet, 1, (40, -60, -500), (0, 0, 30)); key(jet, N, (60, -80, -520), (0, 0, 30))

elif SHOT == 2:
    sea = cloud_sea(-140)
    frame_shot(dict(ldir=(0.18, -1, 0.45), lup=(-1, 0, 0.1), wdir=(0, -1, 0.04), roll=-10, dist=13.0,
                    look=(0, 0, 0.6), lens=45),
               dict(ldir=(-0.12, -1, 0.40), lup=(-1, 0, 0.1), wdir=(0, -1, 0.04), roll=-4, dist=12.6,
                    look=(0, 0, 0.6), lens=45),
               lambda t, c, fwd, right: (c + fwd * 150 + UP * (36 + 2 * t) - right * (14 - 10 * t), right))

elif SHOT == 3:
    sea = cloud_sea(-150)
    frame_shot(dict(ldir=(1, -0.85, 0.9), lup=(-1, 0, 0.3), wdir=(0, -1, 0.18), roll=-28, dist=5.4,
                    look=(0.9, 0, 0.6), lens=24),
               dict(ldir=(1, -0.75, 0.85), lup=(-1, 0, 0.3), wdir=(0, -1, 0.18), roll=-24, dist=5.0,
                    look=(0.9, 0, 0.6), lens=24),
               lambda t, c, fwd, right: (c + fwd * 60 + right * 18 + UP * (12 + t), right))

elif SHOT == 4:
    sea = cloud_sea(-130)
    X = supra.L / 2
    frame_shot(dict(ldir=(1.0, -0.75, 0.55), lup=(1, 0, 0.6), wdir=(0, -1, 0.42), roll=8, dist=2.0,
                    look=(X - 0.55, -0.62, 0.55), lens=22),
               dict(ldir=(0.85, -0.85, 0.50), lup=(1, 0, 0.6), wdir=(0, -1, 0.42), roll=12, dist=1.85,
                    look=(X - 0.62, -0.62, 0.52), lens=22))
    jet.location = (0, 0, 5000)

elif SHOT == 5:
    cloud_layer('SkyClouds', 900, 12000, 0.0012, 0.50, strength=0.9)
    sea = cloud_sea(-260)
    frame_shot(dict(ldir=(1, 0.05, 0.55), lup=(-0.5, 0, 1), wdir=(1, 0.0, -0.55), roll=20, dist=8.2,
                    look=(0.5, 0, 0.6), lens=30),
               dict(ldir=(1, -0.10, 0.55), lup=(-0.5, 0, 1), wdir=(1, 0.0, -0.55), roll=14, dist=7.9,
                    look=(0.5, 0, 0.6), lens=30),
               lambda t, c, fwd, right: (c + fwd * 90 + right * (24 + 4 * t) + UP * 18, -fwd * 0.6 + right))

smooth_all()

# subtle camera shake for the hand-held "falling" feel
for c in ('location',):
    pass

os.makedirs(f'{OUT}/s{SHOT}', exist_ok=True)
if ONLY:
    sc.frame_set(ONLY)
    sc.render.filepath = f'{OUT}/s{SHOT}/{ONLY:04d}.png'
    bpy.ops.render.render(write_still=True)
else:
    sc.frame_start = int(sys.argv[7]) if len(sys.argv) > 7 else 1
    sc.frame_end = int(sys.argv[8]) if len(sys.argv) > 8 else N
    sc.frame_step = STEP
    sc.render.filepath = f'{OUT}/s{SHOT}/'
    sc.render.use_overwrite = False
    bpy.ops.render.render(animation=True)
