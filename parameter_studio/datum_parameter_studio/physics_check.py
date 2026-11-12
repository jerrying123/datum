"""Standalone URDF plausibility diagnostics; never certifies physics readiness."""
import math
from pathlib import Path
import struct
import xml.etree.ElementTree as ET


def _check(status, evidence, reason):
    return {'status': status, 'evidence': evidence, 'reason': reason}


def _positive_definite(a, b, c, d, e, f):
    return a > 0 and a*b-d*d > 0 and a*b*c+2*d*e*f-a*f*f-b*e*e-c*d*d > 0


def _positive_semidefinite(a, b, c, d, e, f):
    scale = max(abs(v) for v in (a, b, c, d, e, f))
    tol = max(scale * 1e-10, 1e-18)
    return (min(a, b, c) >= -tol
            and min(a*b-d*d, a*c-e*e, b*c-f*f) >= -tol*max(scale, tol)
            and a*b*c+2*d*e*f-a*f*f-b*e*e-c*d*d >= -tol*max(scale, tol)**2)


def check_physics(urdf_path, bundle_dir=None):
    """Return per-check pass/fail/unknown diagnostics for a URDF file."""
    checks = {}
    path = Path(urdf_path)
    try:
        root = ET.parse(path).getroot()
        if root.tag != 'robot':
            raise ValueError('root element must be robot')
    except (OSError, ET.ParseError, ValueError) as exc:
        fail = _check('fail', str(exc), 'URDF could not be parsed')
        return {'checks': {k: fail for k in ('mass_inertia', 'inertia_triangle', 'collision_geometry')},
                'physics_readiness': _check('unknown', None, 'Plausibility diagnostics do not establish physics readiness')}
    links = [link for link in root.findall('link') if not (
        link.get('name') == 'base_link' and link.find('inertial') is None
        and not link.findall('collision') and not link.findall('visual'))]
    mass_evidence = []
    mass_ok = True
    tri_ok = True
    for link in links:
        name = link.get('name', '<unnamed>')
        it = link.find('inertial')
        try:
            if it is None: raise ValueError('missing inertial')
            mass = float(it.find('mass').get('value'))
            I = it.find('inertia'); vals = [float(I.get(k)) for k in ('ixx','iyy','izz','ixy','ixz','iyz')]
            if not math.isfinite(mass) or not all(map(math.isfinite, vals)) or mass <= 0: raise ValueError('mass must be finite and positive; inertia finite')
            x,y,z,xy,xz,yz=vals
            pd = _positive_definite(x,y,z,xy,xz,yz)
            h=(x+y+z)/2
            tr = _positive_semidefinite(h-x,h-y,h-z,-xy,-xz,-yz)
            mass_ok &= pd; tri_ok &= tr
            mass_evidence.append({'link':name,'mass':mass,'inertia_positive_definite':pd,'triangle_inequalities':tr})
        except (ValueError, AttributeError, TypeError, OverflowError) as exc:
            mass_ok = tri_ok = False; mass_evidence.append({'link':name,'error':str(exc)})
    checks['mass_inertia'] = _check('pass' if mass_ok and links else 'fail', mass_evidence, 'Finite positive mass and positive definite inertia' if mass_ok and links else 'One or more links has missing or implausible mass/inertia')
    checks['inertia_triangle'] = _check('pass' if tri_ok and links else 'fail', mass_evidence, 'Principal moments satisfy rigid-body triangle inequalities' if tri_ok and links else 'One or more inertia tensors violate triangle inequalities')
    missing = [l.get('name') for l in links if not l.findall('collision')]
    degenerate=[]; checked=[]; invalid=[]
    base = Path(bundle_dir) if bundle_dir is not None else path.parent
    for mesh in root.iter('collision'):
        geometry = mesh.find('geometry')
        children = list(geometry) if geometry is not None else []
        if len(children) != 1:
            invalid.append('collision must contain exactly one geometry')
            continue
        shape = children[0]
        if shape.tag in ('box', 'sphere', 'cylinder'):
            try:
                values = ([float(v) for v in shape.get('size', '').split()] if shape.tag == 'box'
                          else [float(shape.get('radius'))] if shape.tag == 'sphere'
                          else [float(shape.get('radius')), float(shape.get('length'))])
                if len(values) != (3 if shape.tag == 'box' else 1 if shape.tag == 'sphere' else 2) or not all(math.isfinite(v) and v > 0 for v in values):
                    raise ValueError('dimensions must be finite and positive')
            except (TypeError, ValueError):
                invalid.append('invalid ' + shape.tag + ' collision dimensions')
        elif shape.tag != 'mesh':
            checked.append({'geometry': shape.tag, 'degeneracy': 'unknown'})
        for node in mesh.findall('.//mesh'):
            uri=node.get('filename','')
            try:
                scale = [float(v) for v in node.get('scale', '1 1 1').split()]
                if len(scale) != 3 or not all(math.isfinite(v) and v != 0 for v in scale):
                    raise ValueError('invalid mesh scale')
            except ValueError:
                invalid.append('invalid mesh scale: ' + uri)
                continue
            try:
                target=(path.parent/uri).resolve(strict=True)
                if not target.is_relative_to(base.resolve()): raise ValueError('mesh escapes bundle')
                raw=target.read_bytes()
                if len(raw)>=84 and 84+struct.unpack_from('<I',raw,80)[0]*50==len(raw):
                    n=struct.unpack_from('<I',raw,80)[0]; tris=[struct.unpack_from('<9f',raw,o+12) for o in range(84,len(raw),50)]
                    if not n: raise ValueError('empty mesh')
                else:
                    raise ValueError('mesh format not inspectable')
                bad=0
                for t in tris:
                    if not all(math.isfinite(q) for q in t):
                        bad += 1
                        continue
                    a,b,c=[[t[i+j]*scale[j] for j in range(3)] for i in (0,3,6)]
                    u=[b[i]-a[i] for i in range(3)]; v=[c[i]-a[i] for i in range(3)]
                    cross=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
                    area = math.hypot(*cross)
                    product = math.hypot(*u) * math.hypot(*v)
                    bad += not math.isfinite(area) or not math.isfinite(product) or product == 0 or area <= 1e-12 * product
                checked.append({'mesh':uri,'triangles':len(tris),'degenerate_triangles':bad})
                if bad: degenerate.append(uri)
            except ValueError as exc:
                if str(exc) == 'empty mesh': invalid.append('empty mesh: ' + uri)
                else: checked.append({'mesh':uri,'degeneracy':'unknown'})
            except (OSError, struct.error): checked.append({'mesh':uri,'degeneracy':'unknown'})
    unknown = any(item.get('degeneracy') == 'unknown' for item in checked)
    status = 'fail' if missing or degenerate or invalid else ('unknown' if unknown else 'pass')
    checks['collision_geometry']=_check(status,{'links_without_collision':missing,'invalid':invalid,'meshes':checked},'Collision presence and inspectable mesh degeneracy; unsupported meshes remain unknown')
    return {'checks':checks,'physics_readiness':_check('unknown',None,'Plausibility does not establish source mass provenance, collision accuracy, or overall physics readiness; no physics safety claim is made')}
