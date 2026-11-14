"""Inspect and activate CAD-native history states without modifying saved sources."""
import hashlib
from collections import Counter
import json
import os
from pathlib import Path
import tempfile
import zipfile


def discover(source):
    path = Path(source)
    payload = path.read_bytes()
    if len(payload) > 100 * 1024 * 1024:
        raise ValueError('CAD file exceeds size limit')
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo('document.json')
        if info.file_size > 100 * 1024 * 1024:
            raise ValueError('CAD document exceeds size limit')
        doc = json.loads(archive.read(info))
    features = doc.get('features', [])
    if not isinstance(features, list):
        raise ValueError('Invalid feature history')
    ids = Counter(f['id'] for f in features if isinstance(f, dict) and type(f.get('id')) is int)
    history = [{'id': f['id'], 'name': f.get('name') or str(f['id'])}
               for f in features if isinstance(f, dict) and isinstance(f.get('id'), int)
               and not isinstance(f.get('id'), bool) and ids[f['id']] == 1]
    configs = doc.get('configs') or {}
    rows = configs.get('rows', []) if isinstance(configs, dict) else []
    names = [r.get('name') for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    counts = Counter(name for name in names if isinstance(name, str))
    rows = [name for name in names if isinstance(name, str) and name and counts[name] == 1]
    return {'sha256': hashlib.sha256(payload).hexdigest(), 'history': history, 'configurations': rows,
            'active': configs.get('active') if isinstance(configs, dict) else None,
            'branch_tips': [], 'branch_reason': 'SolidCraft does not expose feature-history branches.'}


def _document(source):
    with zipfile.ZipFile(source) as archive:
        return json.loads(archive.read('document.json'))


def validate_capture(before, activated, assembly):
    """Ensure activated imports were present and unchanged in the original capture."""
    old = before.get('sources')
    new = activated.get('sources')
    if not isinstance(old, dict) or not isinstance(new, dict):
        raise ValueError('Invalid source preflight')
    for path, digest in new.items():
        if path != assembly and (path not in old or old[path] != digest):
            raise ValueError('Selected CAD state requires a dependency absent from the original capture: ' + path)


def activate(source, selection, exporter, run, timeout):
    """Activate a state in an already captured source; return its resulting SHA-256."""
    if not isinstance(selection, dict) or set(selection) != {'kind', 'value', 'sha256'}:
        raise ValueError('Invalid CAD state selection')
    catalog = discover(source)
    if selection['sha256'] != catalog['sha256']:
        raise ValueError('CAD state selection is stale; select it again')
    kind, value = selection['kind'], selection['value']
    if kind == 'history' and type(value) is int and any(f['id'] == value for f in catalog['history']):
        command, params = 'timeline.roll_to', {'feature': value}
    elif kind == 'configuration' and isinstance(value, str) and value in catalog['configurations']:
        command, params = 'config.activate', {'row': value}
    else:
        raise ValueError('CAD state no longer exists or is unsupported')
    source = Path(source)
    original = _document(source)
    with tempfile.TemporaryDirectory(prefix='datum-state-') as tmp:
        script = Path(tmp) / 'script.json'
        descriptor, name = tempfile.mkstemp(prefix='.datum-activated-', suffix='.solidcraft', dir=source.parent)
        os.close(descriptor)
        result = Path(name)
        result.unlink()
        script.write_text(json.dumps({'commands': [{'command': command, 'params': params}]}))
        try:
            code, output = run([str(exporter), 'run', str(script), '--in', str(source), '--save', str(result)], timeout)
            if code or not result.is_file():
                raise ValueError('CAD state activation failed: ' + output[-1000:])
            payload = result.read_bytes()
            activated = _document(result)
            previous = {f.get('id'): f for f in original.get('features', []) if isinstance(f, dict)}
            for feature in activated.get('features', []):
                if not isinstance(feature, dict) or feature.get('type') != 'import' or feature.get('suppressed') is True:
                    continue
                old = previous.get(feature.get('id'))
                if not old or old.get('type') != 'import' or old.get('suppressed') is True or old.get('file') != feature.get('file'):
                    raise ValueError('Selected CAD state activates an import absent from the original capture; save the desired state in SolidCraft first')
            os.replace(result, source)
        finally:
            result.unlink(missing_ok=True)
    return hashlib.sha256(payload).hexdigest()
