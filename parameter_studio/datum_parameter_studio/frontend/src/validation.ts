import { isRecord } from './models';
import type {
    CadCatalog, Capability, CommandAcknowledgement, CommandReceipt, GeneratedFiles,
    SimulationCapability, SimulationHistory, SimulationRecordings, SimulationScene,
    SimulationState, SimulationStatus, UrdfJob, UrdfJobStatus, UrdfStartResponse,
} from './models';

export type Validator<T> = (value: unknown) => value is T;
type Check = (value: unknown) => boolean;
const string: Check = value => typeof value === 'string';
const nonemptyString: Check = value => typeof value === 'string' && value.length > 0;
const number: Check = value => typeof value === 'number' && Number.isFinite(value);
const boolean: Check = value => typeof value === 'boolean';
const nullable = (check: Check): Check => value => value === null || check(value);
const array = (check: Check): Check => value => Array.isArray(value) && value.every(item => check(item));
const strings = array(string);
const oneOf = (...values: readonly string[]): Check => value => typeof value === 'string' && values.includes(value);
const record = (check: Check): Check => value => isRecord(value) && Object.values(value).every(check);

// Validate the fields consumed by the UI, accepting extra backend/CAD metadata.
// Missing optional fields are allowed; supplied fields must have their real type.
function shape(required: Record<string, Check>, optional: Record<string, Check> = {}): Check {
    return value => isRecord(value)
        && Object.entries(required).every(([key, check]) => Object.hasOwn(value, key) && check(value[key]))
        && Object.entries(optional).every(([key, check]) => !Object.hasOwn(value, key) || check(value[key]));
}

const cadId: Check = value => string(value) || number(value);
const dimension: Check = value => string(value) || number(value);
const constraint = shape({ type: string }, { value: dimension, param: string });
const feature = shape({ type: string }, {
    id: cadId, name: string, suppressed: boolean, component: cadId, file: string,
    body_names: strings, components: array(shape({}, { name: string })),
    sketch: shape({}, { constraints: array(constraint) }),
});
const cadFile = shape({
    path: string, units: string, fingerprint: nonemptyString, previewId: nonemptyString,
    features: array(feature), fields: array(shape({ pointer: string, value: dimension })),
    params: array(shape({ name: string }, { unit: string, expr: string })),
}, {
    name: string,
    occurrences: array(shape({ id: cadId }, { name: string, component: cadId })),
    links: record(shape({}, { feature: cadId, path: string })),
});
export const isCadCatalog: Validator<CadCatalog> = (value): value is CadCatalog =>
    shape({ files: array(cadFile) }, { project_id: string, projectId: string, error: string })(value);
export const isGeneratedFiles: Validator<GeneratedFiles> = (value): value is GeneratedFiles =>
    shape({ manifest: string, header: string })(value);
export const isCapability: Validator<Capability> = (value): value is Capability =>
    shape({ available: boolean, capability: string })(value);

const urdfState = oneOf('queued', 'capturing', 'exporting', 'checking', 'succeeded', 'failed', 'cancelled', 'canceled');
const evidence: Check = value => nullable(string)(value) || shape({}, { status: string })(value);
const checkStatus = shape({}, { status: string });
const urdfFields = shape({}, {
    state: urdfState,
    freshness: evidence, structural_checks: evidence, assembly_fidelity: evidence,
    report: shape({}, {
        cad_urdf_fidelity_checks: checkStatus,
        physics_checks: shape({}, { checks: shape({}, { mass_inertia: checkStatus, collision_geometry: checkStatus }) }),
        source_preflight: shape({}, { issues: strings }),
        structural_checks: shape({}, { findings: strings }),
    }),
    // error is deliberately unknown: workers may return structured error details.
});
export const isUrdfJobStatus: Validator<UrdfJobStatus> = (value): value is UrdfJobStatus =>
    shape({ state: urdfState })(value) && urdfFields(value);
export const isUrdfStartResponse: Validator<UrdfStartResponse> = (value): value is UrdfStartResponse =>
    urdfFields(value) && shape({}, { id: nonemptyString, job_id: nonemptyString })(value)
    && isRecord(value) && (nonemptyString(value.id) || nonemptyString(value.job_id));
export const isUrdfJob: Validator<UrdfJob> = (value): value is UrdfJob =>
    urdfFields(value) && shape({ id: nonemptyString }, { assembly: string })(value);
export const isUrdfCancellation = (value: unknown): value is { cancelled: true } =>
    isRecord(value) && value.cancelled === true;

const commands = oneOf('pause', 'resume', 'step', 'reset', 'stop', 'record_start', 'record_stop', 'set_joint');
const backend = shape({ supported: boolean }, { commands: array(commands), reason: string, dependency: string });
export const isSimulationCapability: Validator<SimulationCapability> = (value): value is SimulationCapability =>
    isCapability(value) && shape({ backends: record(backend) })(value);
const simulationStatus = shape({ state: oneOf('queued', 'starting', 'paused', 'running', 'stopped', 'failed', 'cancelled', 'succeeded', 'completed') }, {
    recording: boolean, error: nullable(string),
});
export const isSimulationStatus: Validator<SimulationStatus> = (value): value is SimulationStatus => simulationStatus(value);
export const isSimulationHistory: Validator<SimulationHistory> = (value): value is SimulationHistory =>
    shape({ sessions: array(item => simulationStatus(item) && shape({ id: nonemptyString, backend: string, assembly: string })(item)) })(value);
export const isSimulationScene: Validator<SimulationScene> = (value): value is SimulationScene =>
    shape({ links: array(shape({ id: string }, { geometry: strings })) })(value);
const tuple = (length: number): Check => value => Array.isArray(value) && value.length === length && value.every(item => number(item));
export const isSimulationState: Validator<SimulationState> = (value): value is SimulationState =>
    shape({ epoch: number }, {
        time: number,
        links: array(shape({ id: string, position: tuple(3), quaternion: tuple(4) })),
        // MuJoCo returns null for unnamed joints; the selector skips those.
        joints: array(shape({ id: nullable(string) }, { position: number, velocity: number })),
    })(value);
export const isSimulationRecordings: Validator<SimulationRecordings> = (value): value is SimulationRecordings =>
    shape({ recordings: strings })(value);
export const isCommandReceipt: Validator<CommandReceipt> = (value): value is CommandReceipt =>
    shape({ id: nonemptyString })(value);
export const isCommandAcknowledgement: Validator<CommandAcknowledgement> = (value): value is CommandAcknowledgement =>
    shape({ status: oneOf('processing', 'applied', 'rejected', 'unknown') }, { error: string })(value);
