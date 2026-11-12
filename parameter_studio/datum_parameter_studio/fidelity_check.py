"""Compare a bounded subset of saved SolidCraft joint data with URDF.

These checks compare serialized design intent; they do not prove evaluated CAD
geometry, joint frames, motion equivalence, or material fidelity.
"""
import json
import math
import xml.etree.ElementTree as ET
import zipfile


def check_fidelity(assembly, urdf, *, tolerance=1e-6):
    """Report named-joint type and limits checks without asserting full fidelity."""
    report = {'schema': 'datum.cad-urdf-fidelity/1', 'status': 'unknown',
              'checks': [], 'tolerance': tolerance,
              'unverified': ['occurrence-to-link mapping', 'joint frames and axes',
                             'geometry and cache freshness', 'mass and material fidelity']}
    try:
        with zipfile.ZipFile(assembly) as archive:
            document = json.loads(archive.read('document.json'))
        root = ET.parse(urdf).getroot()
        joints = document.get('assembly', {}).get('joints', [])
        if not isinstance(joints, list):
            raise ValueError('invalid source joints')
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        report['checks'].append({'name': 'source_joint_data', 'status': 'unknown', 'reason': str(exc)})
        return report
    output = {}
    for joint in root.findall('joint'):
        output.setdefault(joint.get('name'), []).append(joint)
    names = [j.get('name') for j in joints]
    for joint in joints:
        name, kind = joint.get('name'), joint.get('kind')
        entry = {'name': 'joint', 'source_name': name, 'source_id': joint.get('id'), 'status': 'unknown'}
        matches = output.get(name, [])
        if not name or names.count(name) != 1 or len(matches) != 1:
            entry['reason'] = 'joint name mapping is absent or ambiguous'
            report['checks'].append(entry)
            continue
        target = matches[0]
        expected = {'fixed': 'fixed', 'revolute': 'revolute', 'slider': 'prismatic'}.get(kind)
        if expected is None:
            entry['reason'] = 'unsupported source joint type'
        elif target.get('type') != expected:
            entry.update(status='fail', reason='joint type mismatch', expected=expected, actual=target.get('type'))
        elif kind in ('revolute', 'slider'):
            limits = joint.get('limits') or []
            bounds = limits[0] if limits else None
            limit = target.find('limit')
            if not isinstance(bounds, list) or len(bounds) != 2 or limit is None:
                entry['reason'] = 'source or output joint limits are unavailable'
            else:
                try:
                    scale = 0.001 if kind == 'slider' else 1.0
                    expected_bounds = [float(v) * scale for v in bounds]
                    actual = [float(limit.get('lower')), float(limit.get('upper'))]
                    if not all(math.isfinite(v) for v in expected_bounds + actual):
                        raise ValueError('nonfinite limit')
                    errors = [abs(a-b) for a, b in zip(expected_bounds, actual)]
                    entry.update(status='pass' if max(errors) <= tolerance else 'fail',
                                 expected=expected_bounds, actual=actual, absolute_errors=errors,
                                 unit='m' if kind == 'slider' else 'rad')
                except (TypeError, ValueError):
                    entry['reason'] = 'invalid joint limit values'
        else:
            entry['status'] = 'pass'
        report['checks'].append(entry)
    if any(c['status'] == 'fail' for c in report['checks']):
        report['status'] = 'fail'
    return report
