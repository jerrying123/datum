"""Validated lifetime adapter for feeding exported URDF bundles to simulators."""
from .runtime_urdf import bring_up_urdf
from .urdf_check import check_urdf


class SimulationInput:
    """Context manager exposing a validated URDF and its live mesh bundle."""
    def __init__(self, result):
        self.result = result
        try:
            report = result.report
            if report.get('freshness') != 'current':
                raise ValueError('simulation input is stale')
            fidelity = report.get('assembly_fidelity')
            if fidelity not in ('unknown', 'pass'):
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


def simulation_input(project=None, assembly=None, *, bundle=None, preflight=None, exporter=None, timeout=120):
    """Create simulator input from saved CAD, retaining its temporary bundle."""
    if bundle is not None:
        raise ValueError('existing URDF bundles have no verified freshness or fidelity metadata')
    if project is None or assembly is None:
        raise ValueError('project and assembly are required')
    return SimulationInput(bring_up_urdf(project, assembly, preflight=preflight, exporter=exporter, timeout=timeout))
