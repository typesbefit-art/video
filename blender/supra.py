"""Procedural Toyota GR Supra (A90)-style car built with bpy.
Car faces +X, width along Y, up Z. Origin at ground centre between axles."""
import bpy, bmesh, math
from mathutils import Vector

L = 4.38          # length
WB = 2.47         # wheelbase
FA = 1.03         # front overhang  -> front axle at x = L/2 - FA
WR = 0.335        # wheel radius
TRACK = 0.79      # half track (wheel centre y)


def mat(name, color, metal=0.0, rough=0.5, emit=None, estr=0.0, film=0.0, alpha=1.0,
        transmission=0.0, coat=0.0):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*color, 1)
    b.inputs['Metallic'].default_value = metal
    b.inputs['Roughness'].default_value = rough
    b.inputs['Coat Weight'].default_value = coat
    b.inputs['Transmission Weight'].default_value = transmission
    b.inputs['Alpha'].default_value = alpha
    if film:
        b.inputs['Thin Film Thickness'].default_value = film
        b.inputs['Thin Film IOR'].default_value = 1.5
    if emit:
        b.inputs['Emission Color'].default_value = (*emit, 1)
        b.inputs['Emission Strength'].default_value = estr
    return m


def materials():
    return dict(
        # liquid-silver paint with iridescent blue/purple sheen like the original
        paint=mat('Paint', (0.80, 0.80, 0.85), metal=1.0, rough=0.12, film=520, coat=1.0),
        glass=mat('Glass', (0.02, 0.02, 0.03), metal=0.0, rough=0.02, coat=1.0),
        black=mat('Trim', (0.015, 0.015, 0.017), rough=0.35),
        grille=mat('Grille', (0.01, 0.01, 0.01), metal=0.6, rough=0.4),
        tire=mat('Tire', (0.02, 0.02, 0.02), rough=0.75),
        rim=mat('Rim', (0.72, 0.70, 0.66), metal=1.0, rough=0.22),
        disc=mat('Disc', (0.3, 0.3, 0.3), metal=1.0, rough=0.45),
        caliper=mat('Caliper', (0.25, 0.1, 0.6), rough=0.3),
        head=mat('Headlight', (0.2, 0.1, 0.4), emit=(0.62, 0.18, 1.0), estr=40),
        tail=mat('Taillight', (0.3, 0.0, 0.0), emit=(1.0, 0.02, 0.02), estr=15),
        chrome=mat('HeadChrome', (0.9, 0.9, 0.95), metal=1.0, rough=0.05),
    )


# ---------------------------------------------------------------- body loft
# station: (x from nose, z_bottom, z_shoulder, z_top, half_width, half_width_top)
STATIONS = [
    (0.00, 0.26, 0.44, 0.47, 0.42, 0.30),
    (0.04, 0.17, 0.52, 0.56, 0.66, 0.45),
    (0.14, 0.15, 0.60, 0.635, 0.82, 0.60),
    (0.35, 0.15, 0.68, 0.70, 0.89, 0.74),
    (0.70, 0.15, 0.76, 0.775, 0.905, 0.80),
    (1.10, 0.16, 0.81, 0.83, 0.905, 0.80),
    (1.50, 0.16, 0.85, 0.875, 0.89, 0.76),
    (1.72, 0.16, 0.86, 0.91, 0.875, 0.73),   # windscreen base
    (2.05, 0.16, 0.87, 1.17, 0.865, 0.63),
    (2.35, 0.16, 0.88, 1.275, 0.870, 0.58),
    (2.70, 0.16, 0.90, 1.29, 0.895, 0.56),    # roof peak
    (3.05, 0.16, 0.95, 1.22, 0.930, 0.55),   # rear haunches
    (3.40, 0.17, 0.97, 1.07, 0.930, 0.58),   # rear glass base
    (3.75, 0.18, 0.96, 0.985, 0.905, 0.72),
    (4.05, 0.20, 0.97, 0.995, 0.86, 0.72),
    (4.28, 0.24, 1.00, 1.045, 0.80, 0.70),   # ducktail lip
    (4.37, 0.30, 0.92, 0.95, 0.72, 0.58),
]


def section(z0, zb, zt, w, wt):
    """Half cross-section, from bottom centre round to top centre (y>=0)."""
    return [
        (0.0, z0),
        (w * 0.55, z0),
        (w * 0.86, z0 + 0.005),
        (w * 0.97, z0 + 0.04),
        (w, z0 + (zb - z0) * 0.40),
        (w * 0.995, z0 + (zb - z0) * 0.80),
        (w * 0.975, zb - 0.015),
        (w * 0.94, zb),
        (w * 0.82 + wt * 0.18, zb + (zt - zb) * 0.10),
        (w * 0.35 + wt * 0.65, zb + (zt - zb) * 0.60),
        (wt * 0.98, zt - (zt - zb) * 0.10),
        (wt * 0.80, zt - 0.005),
        (wt * 0.40, zt),
        (0.0, zt - 0.012),
    ]


def build_body(M):
    bm = bmesh.new()
    rings = []
    for (x, z0, zb, zt, w, wt) in STATIONS:
        pts = section(z0, zb, zt, w, wt)
        full = [(-y, z) for (y, z) in reversed(pts[1:-1])]
        full = [pts[0]] + [p for p in pts[1:-1]] + [pts[-1]] + full
        # full ring: bottom centre -> +y side -> top centre -> -y side
        ring = [bm.verts.new((L / 2 - x, y, z)) for (y, z) in full]
        rings.append(ring)
    n = len(rings[0])
    for a, b in zip(rings, rings[1:]):
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new((a[i], a[j], b[j], b[i]))
    bm.faces.new(list(reversed(rings[0])))
    bm.faces.new(rings[-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new('Body')
    bm.to_mesh(me)
    ob = bpy.data.objects.new('Body', me)
    bpy.context.collection.objects.link(ob)
    ob.data.materials.append(M['paint'])
    ob.data.materials.append(M['glass'])
    ob.data.materials.append(M['black'])
    # windows: faces in cabin zone above the shoulder line
    xs = [L / 2 - s[0] for s in STATIONS]
    for f in me.polygons:
        c = f.center
        xn = L / 2 - c.x
        st = min(STATIONS, key=lambda s: abs(s[0] - xn))
        if 1.74 <= xn <= 3.45 and c.z > st[2] + 0.035:
            # roof centre stays body colour (double bubble), rest is glass
            if abs(c.y) < 0.40 and 2.15 < xn < 3.10:
                f.material_index = 0
            else:
                f.material_index = 1
        if c.z < 0.22:
            f.material_index = 2
    sub = ob.modifiers.new('sub', 'SUBSURF')
    sub.levels = 3
    sub.render_levels = 4
    sub.levels = 4
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.modifier_apply(modifier='sub')
    # wheel arches
    fx = L / 2 - FA
    for x in (fx, fx - WB):
        bpy.ops.mesh.primitive_cylinder_add(radius=WR + 0.05, depth=0.7, vertices=64,
                                            location=(x, 0.0, WR), rotation=(math.pi / 2, 0, 0))
        cut = bpy.context.object
        cut.location.y = 0.0
        cut.scale.z = 3.0  # through both sides
        bpy.context.view_layer.update()
        mod = ob.modifiers.new('arch', 'BOOLEAN')
        mod.object = cut
        mod.operation = 'DIFFERENCE'
        mod.solver = 'EXACT'
        bpy.context.view_layer.objects.active = ob
        bpy.ops.object.modifier_apply(modifier='arch')
        bpy.data.objects.remove(cut)
    bpy.ops.object.shade_smooth()
    # inner arch liners (black) so the cut doesn't look hollow
    for x in (fx, fx - WB):
        for s in (1, -1):
            bpy.ops.mesh.primitive_cylinder_add(radius=WR + 0.05, depth=0.40, vertices=48,
                                                end_fill_type='NOTHING',
                                                location=(x, s * 0.72, WR), rotation=(math.pi / 2, 0, 0))
            lin = bpy.context.object
            lin.data.materials.append(M['black'])
            lin.parent = ob
    return ob


def strip(name, pts, width, m, parent, thick=0.02):
    """Thin emissive/trim strip following a polyline (list of 3D points)."""
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = '3D'
    sp = cu.splines.new('POLY')
    sp.points.add(len(pts) - 1)
    for p, c in zip(sp.points, pts):
        p.co = (*c, 1)
    cu.bevel_depth = width
    cu.bevel_resolution = 2
    ob = bpy.data.objects.new(name, cu)
    bpy.context.collection.objects.link(ob)
    ob.data.materials.append(m)
    ob.parent = parent
    return ob


def box(name, loc, size, m, parent, rot=(0, 0, 0), bevel=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rot)
    ob = bpy.context.object
    ob.name = name
    ob.scale = size
    if bevel:
        b = ob.modifiers.new('bev', 'BEVEL')
        b.width = bevel
        b.segments = 3
    ob.data.materials.append(m)
    ob.parent = parent
    return ob


def _hit(body, origin, direction):
    ok, loc, nor, _ = body.ray_cast(Vector(origin), Vector(direction).normalized())
    return (loc, nor) if ok else (None, None)


def top(body, x, y, off=0.004):
    loc, nor = _hit(body, (x, y, 3.0), (0, 0, -1))
    return (loc + nor * off) if loc is not None else Vector((x, y, 0.8))


def front(body, y, z, off=0.004):
    loc, nor = _hit(body, (4.0, y, z), (-1, 0, 0))
    return (loc + nor * off) if loc is not None else Vector((L / 2, y, z))


def rear(body, y, z, off=0.004):
    loc, nor = _hit(body, (-4.0, y, z), (1, 0, 0))
    return (loc + nor * off) if loc is not None else Vector((-L / 2, y, z))


def side(body, x, z, s, off=0.004):
    loc, nor = _hit(body, (x, s * 3.0, z), (0, -s, 0))
    return (loc + nor * off) if loc is not None else Vector((x, s * 0.9, z))


def patch(name, rows, m, parent):
    """Thin surface patch from a grid of points (rows x cols)."""
    bm = bmesh.new()
    vs = [[bm.verts.new(p) for p in r] for r in rows]
    for r0, r1 in zip(vs, vs[1:]):
        for i in range(len(r0) - 1):
            bm.faces.new((r0[i], r0[i + 1], r1[i + 1], r1[i]))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    so = ob.modifiers.new('solid', 'SOLIDIFY')
    so.thickness = 0.01
    so.offset = 0
    ob.data.materials.append(m)
    ob.parent = parent
    return ob


def details(body, M):
    X = L / 2
    for s in (1, -1):
        # slim swept headlights (A90 shape) -- dark lens with purple DRL like the original
        outline_t = [(X - 0.10, 0.44), (X - 0.20, 0.60), (X - 0.36, 0.74), (X - 0.52, 0.80)]
        outline_b = [(X - 0.06, 0.48), (X - 0.12, 0.64), (X - 0.22, 0.78), (X - 0.40, 0.86)]
        rows = []
        for (xt, yt), (xb, yb) in zip(outline_t, outline_b):
            r = []
            for k in range(4):
                f = k / 3
                x = xt + (xb - xt) * f
                y = yt + (yb - yt) * f
                r.append(top(body, x, s * y, 0.006) if y < 0.80 else side(body, x, 0.62, s, 0.006))
            rows.append(r)
        patch('HeadLens', rows, M['black'], body)
        strip('DRL', [top(body, X - 0.09, s * 0.47, 0.014), top(body, X - 0.16, s * 0.62, 0.014),
                      top(body, X - 0.30, s * 0.76, 0.014), top(body, X - 0.46, s * 0.82, 0.014)],
              0.011, M['head'], body)
        strip('DRL2', [top(body, X - 0.13, s * 0.53, 0.014), top(body, X - 0.20, s * 0.66, 0.014),
                       top(body, X - 0.27, s * 0.74, 0.014)], 0.008, M['head'], body)
        for k, yy in enumerate((0.58, 0.68)):
            bpy.ops.mesh.primitive_uv_sphere_add(radius=0.035, location=top(body, X - 0.17 - k * 0.08, s * yy, 0.0))
            pr = bpy.context.object
            pr.data.materials.append(M['chrome'])
            pr.parent = body
        # front corner vertical intakes
        p = front(body, s * 0.66, 0.36, -0.03)
        box('SideIntake', p, (0.10, 0.18, 0.20), M['grille'], body, rot=(0, 0, s * 0.6), bevel=0.02)
        # side skirt
        box('Skirt', side(body, 0.05, 0.20, s, -0.01), (1.60, 0.06, 0.06), M['black'], body, bevel=0.015)
        # door-side scoop (A90)
        box('Scoop', side(body, X - 2.45, 0.52, s, -0.015), (0.40, 0.05, 0.12), M['black'], body,
            rot=(0, 0.10, 0), bevel=0.02)
        # rear fender vent
        box('RearVent', side(body, X - 3.25, 0.70, s, -0.01), (0.22, 0.05, 0.06), M['black'], body,
            rot=(0, -0.2, 0), bevel=0.01)
        # mirrors on stalks
        mp = side(body, X - 1.95, 0.97, s, 0.10)
        box('Mirror', mp, (0.20, 0.10, 0.10), M['paint'], body, rot=(0, 0, s * 0.10), bevel=0.035)
        # tail light strips
        strip('Tail', [rear(body, s * 0.25, 0.93, 0.006), rear(body, s * 0.55, 0.94, 0.006),
                       rear(body, s * 0.70, 0.90, 0.006), side(body, X - 4.18, 0.88, s, 0.006)],
              0.018, M['tail'], body)
        # twin exhaust
        bpy.ops.mesh.primitive_cylinder_add(radius=0.05, depth=0.16, location=rear(body, s * 0.30, 0.30, 0.02),
                                            rotation=(0, math.pi / 2, 0))
        e = bpy.context.object
        e.data.materials.append(M['chrome'])
        e.parent = body
    # big central intake + mesh + splitter
    box('Intake', front(body, 0, 0.32, -0.04), (0.14, 0.95, 0.20), M['grille'], body, bevel=0.05)
    box('NoseSplit', front(body, 0, 0.26, -0.01), (0.10, 0.04, 0.16), M['black'], body)
    box('Splitter', front(body, 0, 0.17, -0.05), (0.18, 1.60, 0.025), M['black'], body, bevel=0.01)
    # hood vents
    for s in (1, -1):
        box('HoodVent', top(body, X - 1.10, s * 0.33, 0.0), (0.24, 0.13, 0.03), M['grille'], body,
            rot=(0, -0.09, 0), bevel=0.01)
    # roof double-bubble groove
    strip('RoofGroove', [top(body, X - 2.20, 0, 0.0), top(body, X - 2.70, 0, 0.0), top(body, X - 3.10, 0, 0.0)],
          0.012, M['black'], body)
    # rear diffuser
    box('Diffuser', rear(body, 0, 0.24, -0.03), (0.16, 1.2, 0.08), M['black'], body, bevel=0.01)
    # third brake light
    strip('Brake3', [rear(body, -0.25, 1.03, 0.004), rear(body, 0.25, 1.03, 0.004)], 0.008, M['tail'], body)


def wheel(name, loc, side, M, parent):
    root = bpy.data.objects.new(name, None)
    bpy.context.collection.objects.link(root)
    root.location = loc
    root.parent = parent
    # tyre
    bpy.ops.mesh.primitive_torus_add(major_radius=WR - 0.075, minor_radius=0.085,
                                     major_segments=64, minor_segments=24)
    t = bpy.context.object
    t.scale = (1, 1, 1.45)
    t.rotation_euler = (math.pi / 2, 0, 0)
    t.data.materials.append(M['tire'])
    bpy.ops.object.shade_smooth()
    t.parent = root
    # rim barrel + face
    bpy.ops.mesh.primitive_cylinder_add(radius=WR - 0.12, depth=0.22, vertices=64,
                                        rotation=(math.pi / 2, 0, 0))
    b = bpy.context.object
    b.data.materials.append(M['rim'])
    bpy.ops.object.shade_smooth()
    b.parent = root
    # brake disc + caliper
    bpy.ops.mesh.primitive_cylinder_add(radius=WR - 0.15, depth=0.03, vertices=48,
                                        location=(0, -side * 0.02, 0), rotation=(math.pi / 2, 0, 0))
    d = bpy.context.object
    d.data.materials.append(M['disc'])
    d.parent = root
    box('Caliper', (0.0, side * 0.03, WR - 0.20), (0.18, 0.07, 0.08), M['caliper'], root, bevel=0.02)
    # five-spoke face (TE37-like, as in the original)
    hub_y = side * 0.105
    bpy.ops.mesh.primitive_cylinder_add(radius=0.07, depth=0.05, vertices=32, location=(0, hub_y, 0),
                                        rotation=(math.pi / 2, 0, 0))
    h = bpy.context.object
    h.data.materials.append(M['rim'])
    h.parent = root
    for k in range(5):
        a = k * 2 * math.pi / 5
        r = (WR - 0.12) / 2
        box('Spoke', (math.cos(a) * r, hub_y, math.sin(a) * r), (WR - 0.10, 0.03, 0.055),
            M['rim'], root, rot=(0, -a, 0), bevel=0.012)
    # lip
    bpy.ops.mesh.primitive_torus_add(major_radius=WR - 0.12, minor_radius=0.012,
                                     location=(0, hub_y, 0), rotation=(math.pi / 2, 0, 0))
    lp = bpy.context.object
    lp.data.materials.append(M['rim'])
    lp.parent = root
    return root


def build(M=None):
    M = M or materials()
    rig = bpy.data.objects.new('CarRig', None)   # animate this
    bpy.context.collection.objects.link(rig)
    body = build_body(M)
    body.parent = rig
    details(body, M)
    fx = L / 2 - FA
    wheels = []
    for x in (fx, fx - WB):
        for s in (1, -1):
            wheels.append(wheel('Wheel', (x, s * TRACK, WR), s, M, body))
    # interior: dark seats/dash so windows aren't see-through
    box('Interior', (L / 2 - 2.6, 0, 0.75), (1.4, 1.5, 0.35), M['black'], body)
    return rig, M
