"""Validated lifetime adapter for feeding exported URDF bundles to simulators."""
import json
import math
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

from .runtime_urdf import bring_up_urdf
from .urdf_check import check_urdf


class SimulationInput:
    """Context manager exposing a validated URDF and its live mesh bundle."""
    def __init__(self, result, assembly=None, *, supports_couplings=False):
        self.result = result
        try:
            report = result.report
            if report.get('freshness') != 'current':
                raise ValueError('simulation input is stale')
            fidelity = report.get('assembly_fidelity')
            self.couplings = []
            if fidelity == 'fail' and assembly is not None and supports_couplings:
                self.couplings = _supported_couplings(result, assembly)
            elif fidelity not in ('unknown', 'pass'):
                raise ValueError('simulation requires non-failing assembly fidelity')
            if report.get('cad_urdf_fidelity_checks', {}).get('status') == 'fail':
                raise ValueError('CAD to URDF fidelity comparison failed')
            if check_urdf(result.urdf_path, result.bundle, synthetic_base='base_link')['status'] != 'pass':
                raise ValueError('simulation URDF validation failed')
        except Exception:
            result.close()
            raise
        self.urdf_path = result.urdf_path
        self.bundle = result.bundle

    def close(self): self.result.close()
    def __enter__(self): return self
    def __exit__(self, *exc): self.close(); return False


def _supported_couplings(result, assembly):
    """Map one captured, 1:1 zero-offset slider link; reject other failures.

    The general URDF export remains unmodified and reports coupling unexported.
    Only simulation engines implementing the constraint may consume this mapping.
    """
    report = result.report
    preflight = report.get('source_preflight', {})
    if preflight.get('issues') != ['unsupported_assembly_links']:
        raise ValueError('unsupported source fidelity failure')
    project = Path(result._holder.name) / 'project'
    for name in preflight.get('sources', {}):
        if name != assembly:
            with zipfile.ZipFile(project / name) as archive:
                child = json.loads(archive.read('document.json'))
            if child.get('assembly', {}).get('links'):
                raise ValueError('nested coupling is unsupported')
    captured = project / assembly
    with zipfile.ZipFile(captured) as archive:
        document = json.loads(archive.read('document.json'))
    assembly_data = document.get('assembly', {})
    links = assembly_data.get('links', [])
    joints = assembly_data.get('joints', [])
    if not isinstance(links, list) or len(links) != 1 or not isinstance(joints, list):
        raise ValueError('only one simple slider coupling is supported')
    link = links[0]
    if (not isinstance(link, dict) or set(link) - {'a', 'b', 'ia', 'ib', 'ratio', 'offset'}
        or any(isinstance(link.get(k), bool) or not isinstance(link.get(k), int) for k in ('a', 'b'))
        or any(isinstance(link.get(k, 0), bool) or not isinstance(link.get(k, 0), int) for k in ('ia', 'ib'))
        or link.get('ia', 0) != 0 or link.get('ib', 0) != 0
        or isinstance(link.get('ratio'), bool) or link.get('ratio') != 1
        or isinstance(link.get('offset'), bool) or link.get('offset') != 0):
        raise ValueError('unsupported motion link')
    by_id = {j.get('id'): j for j in joints if isinstance(j, dict)}
    a, b = by_id.get(link.get('a')), by_id.get(link.get('b'))
    if not a or not b or a is b or a.get('kind') != 'slider' or b.get('kind') != 'slider':
        raise ValueError('coupling requires two distinct slider joints')
    names = [j.get('name') for j in joints if isinstance(j, dict)]
    if not all(isinstance(j.get('name'), str) and names.count(j['name']) == 1 for j in (a, b)):
        raise ValueError('ambiguous coupling joint names')
    if a.get('limits') != b.get('limits'):
        raise ValueError('coupled slider limits differ')
    urdf = ET.parse(result.urdf_path).getroot()
    for joint in (a, b):
        matches = [x for x in urdf.findall('joint') if x.get('name') == joint['name']]
        if len(matches) != 1 or matches[0].get('type') != 'prismatic':
            raise ValueError('coupled joint is absent or ambiguous in URDF')
        bounds = joint.get('limits')
        limit = matches[0].find('limit')
        try:
            if not isinstance(bounds, list) or len(bounds) != 1 or not isinstance(bounds[0], list) or len(bounds[0]) != 2 or limit is None:
                raise ValueError('missing bounds')
            expected = [float(v) * .001 for v in bounds[0]]
            actual = [float(limit.get('lower')), float(limit.get('upper'))]
            if not all(math.isfinite(v) for v in expected + actual) or any(abs(x-y) > 1e-6 for x, y in zip(expected, actual)):
                raise ValueError('bounds differ')
        except (TypeError, ValueError) as exc:
            raise ValueError('coupled joint limits unavailable or inconsistent') from exc
    return [{'driver': a['name'], 'driven': b['name'], 'ratio': 1.0, 'offset': 0.0}]


def simulation_input(project=None, assembly=None, *, bundle=None, preflight=None, exporter=None, timeout=120, supports_couplings=False):
    """Create simulator input from saved CAD, retaining its temporary bundle.

    A caller opting into ``supports_couplings`` must enforce every relationship
    in the returned ``couplings`` list. The URDF itself does not encode them.
    The default rejects such exports, as required for ordinary URDF consumers.
    """
    if bundle is not None:
        raise ValueError('existing URDF bundles have no verified freshness or fidelity metadata')
    if project is None or assembly is None:
        raise ValueError('project and assembly are required')
    return SimulationInput(bring_up_urdf(project, assembly, preflight=preflight, exporter=exporter, timeout=timeout), assembly=assembly, supports_couplings=supports_couplings)
