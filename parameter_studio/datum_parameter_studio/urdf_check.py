"""Bounded structural URDF and STL checks; not a semantic or physics validator."""
import argparse
import json
import math
from pathlib import Path
import struct
import xml.etree.ElementTree as ET

MAX_XML = 4 * 1024 * 1024
MAX_MESH = 64 * 1024 * 1024
MAX_ELEMENTS = 100000


def check_urdf(urdf_path, bundle_dir, synthetic_base=None):
    """Return {status, findings, unknowns}; synthetic_base explicitly names an empty base."""
    findings = []
    unknowns = ["CAD semantic fidelity and source mapping are not checked", "Physics readiness, units, material provenance and engineering limits are not verified"]
    def fail(message):
        findings.append(message)
    def numbers(text, count):
        values = [float(x) for x in (text or '').split()]
        if len(values) != count or not all(math.isfinite(x) for x in values):
            raise ValueError('expected finite numeric values')
        return values
    try:
        root_dir = Path(bundle_dir).resolve(strict=True)
        path = Path(urdf_path).resolve(strict=True)
        if not path.is_relative_to(root_dir) or not path.is_file():
            raise ValueError('URDF must be a file inside the bundle')
        if path.stat().st_size > MAX_XML:
            raise ValueError('URDF exceeds size limit')
        data = path.read_bytes()
        # Comments and the XML prolog are allowed; DTD/entity declarations are not.
        # Reject NULs so UTF-16 cannot bypass the byte-level declaration check.
        import re
        without_comments = re.sub(br'<!--[\s\S]*?-->', b'', data)
        if b'\x00' in data or b'<!' in without_comments.upper():
            raise ValueError('DTD and entity declarations are forbidden')
        root = ET.fromstring(data)
        if root.tag != 'robot':
            raise ValueError('root must be robot')
        if sum(1 for _ in root.iter()) > MAX_ELEMENTS:
            raise ValueError('too many XML elements')
    except (OSError, ValueError, ET.ParseError) as exc:
        return {'status': 'fail', 'findings': [str(exc)], 'unknowns': unknowns}
    links = {}
    for link in root.findall('link'):
        name = link.get('name')
        if not name or name in links:
            fail('missing or duplicate link name: ' + str(name))
        else:
            links[name] = link
        inertial = link.find('inertial')
        if inertial is None:
            if name != synthetic_base:
                fail('missing inertial: ' + str(name))
            elif len(link):
                fail('synthetic base must be empty: ' + str(name))
            continue
        try:
            mass = numbers(inertial.find('mass').get('value'), 1)[0]
            i = inertial.find('inertia')
            xx, yy, zz, xy, xz, yz = [numbers(i.get(k), 1)[0] for k in ('ixx', 'iyy', 'izz', 'ixy', 'ixz', 'iyz')]
            # Positive definiteness of inertia and of (trace(I)/2)I - I enforces triangle inequalities.
            def positive(a,b,c,d,e,f):
                return a > 0 and a*b-d*d > 0 and a*b*c+2*d*e*f-a*f*f-b*e*e-c*d*d > 0
            h = (xx+yy+zz)/2
            if mass <= 0 or not positive(xx,yy,zz,xy,xz,yz) or not positive(h-xx,h-yy,h-zz,-xy,-xz,-yz):
                raise ValueError('nonphysical mass or inertia')
        except (ValueError, AttributeError, OverflowError) as exc:
            fail('invalid inertial for %s: %s' % (name, exc))
    if not links:
        fail('no links')
    joints = set(); incoming = {}; edges = {name: [] for name in links}
    for joint in root.findall('joint'):
        name = joint.get('name'); kind = joint.get('type')
        if not name or name in joints: fail('missing or duplicate joint name: ' + str(name))
        joints.add(name)
        if kind not in ('fixed', 'revolute', 'continuous', 'prismatic', 'floating', 'planar'): fail('unsupported joint type: ' + str(kind))
        try:
            parent = joint.find('parent').get('link'); child = joint.find('child').get('link')
            if parent not in links or child not in links: raise ValueError('unknown link reference')
            incoming[child] = incoming.get(child, 0) + 1
            edges[parent].append(child)
            axis = joint.find('axis')
            if axis is not None:
                v = numbers(axis.get('xyz'), 3)
                if not math.isclose(math.hypot(*v), 1, rel_tol=1e-6, abs_tol=1e-6): raise ValueError('axis must be normalized and nonzero')
            limit = joint.find('limit')
            if kind in ('revolute', 'prismatic') and limit is None: raise ValueError('missing limits')
            if limit is not None:
                for attr in ('effort', 'velocity'):
                    if numbers(limit.get(attr), 1)[0] <= 0: raise ValueError('invalid ' + attr)
                if kind in ('revolute', 'prismatic') and numbers(limit.get('lower'),1)[0] >= numbers(limit.get('upper'),1)[0]: raise ValueError('invalid bounds')
        except (ValueError, AttributeError) as exc: fail('invalid joint %s: %s' % (name, exc))
    roots = [x for x in links if incoming.get(x, 0) == 0]
    if len(roots) != 1 or any(n != 1 for n in incoming.values()): fail('graph must have one root and one parent per other link')
    if synthetic_base is not None and (roots != [synthetic_base] or synthetic_base not in links): fail('synthetic base must be the root')
    visited = set(); stack = roots[:]
    while stack:
        node = stack.pop()
        if node in visited: fail('cycle or repeated link'); break
        visited.add(node); stack.extend(edges[node])
    if len(visited) != len(links): fail('graph is disconnected or cyclic')
    for origin in root.iter('origin'):
        for attr in ('xyz', 'rpy'):
            if origin.get(attr) is not None:
                try: numbers(origin.get(attr), 3)
                except ValueError: fail('invalid origin ' + attr)
    for mesh in root.iter('mesh'):
        try:
            uri = mesh.get('filename', '')
            if not uri or ':' in uri or '\\' in uri or uri.startswith('/') or any(x in ('..', '') for x in uri.split('/')): raise ValueError('unsafe mesh path')
            target = (path.parent / uri).resolve(strict=True)
            if not target.is_relative_to(root_dir) or not target.is_file(): raise ValueError('mesh outside bundle')
            if target.suffix.lower() != '.stl' or target.stat().st_size > MAX_MESH: raise ValueError('unsupported or oversized mesh')
            if mesh.get('scale') is not None and any(x <= 0 for x in numbers(mesh.get('scale'),3)): raise ValueError('invalid mesh scale')
            raw = target.read_bytes(); vertices = []
            if len(raw) >= 84 and 84 + struct.unpack_from('<I', raw, 80)[0] * 50 == len(raw):
                count = struct.unpack_from('<I', raw, 80)[0]
                if not count: raise ValueError('empty STL')
                for offset in range(84, len(raw), 50):
                    values = struct.unpack_from('<12f', raw, offset)
                    if not all(math.isfinite(x) for x in values): raise ValueError('nonfinite STL')
                    vertices.extend([values[3:6], values[6:9], values[9:12]])
            else:
                import re
                text = raw.decode('ascii')
                pattern = r'\s*solid[^\n]*\n(?:\s*facet\s+normal\s+\S+\s+\S+\s+\S+\s+outer\s+loop\s+vertex\s+\S+\s+\S+\s+\S+\s+vertex\s+\S+\s+\S+\s+\S+\s+vertex\s+\S+\s+\S+\s+\S+\s+endloop\s+endfacet\s*)+endsolid[^\n]*\s*'
                if not re.fullmatch(pattern, text, re.IGNORECASE): raise ValueError('invalid ASCII STL')
                for match in re.finditer(r'\b(?:vertex|normal)\s+(\S+)\s+(\S+)\s+(\S+)', text, re.IGNORECASE):
                    v = numbers(' '.join(match.groups()), 3)
                    if match.group(0).lower().startswith('vertex'): vertices.append(v)
            if not vertices or any(max(v[i] for v in vertices) <= min(v[i] for v in vertices) for i in range(3)): raise ValueError('STL has zero extent')
        except (OSError, ValueError, UnicodeError, struct.error) as exc: fail('invalid mesh %s: %s' % (mesh.get('filename'), exc))
    return {'status': 'fail' if findings else 'pass', 'findings': findings, 'unknowns': unknowns}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('urdf'); parser.add_argument('bundle'); parser.add_argument('--synthetic-base')
    args = parser.parse_args()
    result = check_urdf(args.urdf, args.bundle, args.synthetic_base)
    print(json.dumps(result))
    return 0 if result['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
