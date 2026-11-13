// Saved CAD and local Studio API contracts. Dimensions can be numeric literals,
// unit-bearing strings, or references to named parameters.
export type CadId = string | number;
export type DimensionValue = number | string;

export interface CadConstraint {
    type: string;
    value?: DimensionValue;
    param?: string;
}

export interface CadFeature {
    id?: CadId;
    type: string;
    name?: string;
    suppressed?: boolean;
    component?: CadId;
    file?: string;
    body_names?: string[];
    components?: { name?: string }[];
    sketch?: { constraints?: CadConstraint[] };
}

export interface CadField {
    pointer: string;
    value: DimensionValue;
}

export interface CadFile {
    path: string;
    name?: string;
    units: string;
    fingerprint: string;
    previewId: string;
    features: CadFeature[];
    fields: CadField[];
    occurrences?: { id: CadId; name?: string; component?: CadId }[];
    links?: Record<string, { feature?: CadId; path?: string }>;
    params: { name: string; unit?: string; expr?: string }[];
}

export interface CadCatalog {
    project_id?: string;
    projectId?: string;
    files: CadFile[];
    error?: string;
}

export interface PartOccurrence {
    key: string;
    name: string;
    feature: CadFeature;
    path: string | null;
}

// Older persisted workspaces may contain only a path and pointer. Such entries
// remain stale until the user selects the dimension again.
export interface ParameterMapping {
    path: string;
    pointer: string;
    sourceFingerprint?: string;
    units?: string;
    unit?: string;
    value?: DimensionValue | boolean;
    featureId?: CadId;
    featureName?: string;
    featureType?: string;
    name?: string;
    stale?: boolean;
}

export interface DimensionInput extends CadField {
    units: string;
    label: string;
    paramName?: string;
}

export interface CadChange {
    path: string;
    before: CadFile;
    after: CadFile;
}

export interface ParameterSource {
    path: string;
    pointer: string;
    source_units?: string;
    unit?: string;
}

export interface ParameterSpec {
    schema: 'datum.robot.parameter-spec/2';
    units: 'm';
    worktrees: Record<string, { parameters: Record<string, ParameterSource> }>;
}

export interface GeneratedFiles {
    manifest: string;
    header: string;
}

export interface GenerationResponse extends Partial<GeneratedFiles> {
    error?: string;
}

export interface Capability {
    available: boolean;
    capability: string;
}

export type UrdfJobState = 'queued' | 'capturing' | 'exporting' | 'checking' | 'succeeded' | 'failed' | 'cancelled' | 'canceled';
export type Evidence = string | { status?: string } | null;
export interface UrdfJobStatus {
    state?: UrdfJobState;
    error?: unknown;
    freshness?: Evidence;
    structural_checks?: Evidence;
    assembly_fidelity?: Evidence;
    report?: {
        cad_urdf_fidelity_checks?: { status?: string };
        physics_checks?: { checks?: { mass_inertia?: { status?: string }; collision_geometry?: { status?: string } } };
        source_preflight?: { issues?: string[] };
        structural_checks?: { findings?: string[] };
    };
}

export interface UrdfJob extends UrdfJobStatus {
    id: string;
    assembly?: string;
}

export interface UrdfStartResponse extends UrdfJobStatus {
    id?: string;
    job_id?: string;
}

export interface SimulationBackend {
    supported: boolean;
    commands?: SimulationCommand[];
    reason?: string;
    dependency?: string;
}

export interface SimulationCapability extends Capability {
    backends: Record<string, SimulationBackend | undefined>;
}

export type SimulationSessionState = 'queued' | 'starting' | 'paused' | 'running' | 'stopped' | 'failed' | 'cancelled' | 'succeeded' | 'completed';
export interface SimulationStatus {
    speed?: number;
    actual_speed?: number;
    timeline?: { min: number; max: number; current: number; generation: number } | null;
    state: SimulationSessionState;
    recording?: boolean;
    error?: string | null;
}

export interface SimulationSession {
    id: string;
    backend: string;
    assembly: string;
}

export interface SimulationHistory {
    sessions: (SimulationSession & SimulationStatus)[];
}

export interface SimulationScene {
    couplings?: { driver: string; driven: string; ratio: number; offset: number }[];
    links?: { id: string; geometry?: string[] }[];
}

export type Vector3Tuple = [number, number, number];
export interface SimulationState {
    seq?: number;
    time?: number;
    epoch: number;
    links?: { id: string; position: Vector3Tuple; quaternion: [number, number, number, number] }[];
    joints?: { id: string | null; position?: number; velocity?: number }[];
}

export interface SimulationRecordings {
    recordings?: string[];
}

export type SimulationCommand = 'pause' | 'resume' | 'step' | 'reset' | 'stop' | 'record_start' | 'record_stop' | 'set_joint' | 'set_position_control' | 'set_speed' | 'seek';
export type SimulationCommandRequest = { command: Exclude<SimulationCommand, 'set_joint' | 'set_position_control' | 'set_speed' | 'seek'> }
    | { command: 'set_speed'; speed: number }
    | { command: 'seek'; frame: number; generation: number }
    | { command: 'set_joint'; joint: string; position: number }
    | { command: 'set_position_control'; joint: string; position: number; profile: { kp: number; kd: number; max_force: number } };
export interface CommandReceipt {
    id: string;
}
export interface CommandAcknowledgement {
    status: 'processing' | 'applied' | 'rejected' | 'unknown';
    error?: string;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function isParameterMapping(value: unknown): value is ParameterMapping {
    if (!isRecord(value) || typeof value.path !== 'string' || typeof value.pointer !== 'string') return false;
    for (const key of ['sourceFingerprint', 'units', 'unit', 'featureName', 'featureType', 'name']) {
        if (value[key] !== undefined && typeof value[key] !== 'string') return false;
    }
    return (value.featureId === undefined || typeof value.featureId === 'string' || typeof value.featureId === 'number')
        && (value.value === undefined || typeof value.value === 'string' || typeof value.value === 'number' || typeof value.value === 'boolean')
        && (value.stale === undefined || typeof value.stale === 'boolean');
}

export function errorMessage(error: unknown): string {
    return error instanceof Error ? error.message : isRecord(error) && typeof error.message === 'string' ? error.message : String(error);
}

export function errorStatus(error: unknown): number | undefined {
    return isRecord(error) && typeof error.status === 'number' ? error.status : undefined;
}

// Keep arbitrary JSON pointer traversal at the untyped saved-document boundary.
export function pointerValue(value: unknown, parts: string[]): unknown {
    for (const key of parts) {
        if (value === null || value === undefined) return undefined;
        value = Reflect.get(Object(value), key);
    }
    return value;
}
