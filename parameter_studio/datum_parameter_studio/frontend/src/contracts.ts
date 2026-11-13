import {isRecord} from './models';
export type {Validator as Guard} from './validation';
export {
    isCadCatalog as catalog, isCapability as capability, isCommandReceipt as receipt,
    isUrdfStartResponse as urdfStart, isUrdfJobStatus as urdfStatus,
    isSimulationCapability as simCapability, isSimulationStatus as simStatus,
    isSimulationHistory as history, isSimulationScene as scene,
    isSimulationState as state, isSimulationRecordings as recordings,
    isCommandAcknowledgement as acknowledgement, isGeneratedFiles as generation,
    isUrdfCancellation as cancellation,
} from './validation';
export const record = isRecord;

export async function jsonResponse<T>(response: Response, guard: (value: unknown) => value is T): Promise<T> {
    let value: unknown;
    try { value = await response.json(); }
    catch { throw Object.assign(Error(`Invalid JSON response (${response.status})`), {status:response.status}); }
    if (!response.ok) {
        const error = Error(isRecord(value) && typeof value.error === 'string' ? value.error : `HTTP ${response.status}`);
        Object.assign(error, {status: response.status});
        throw error;
    }
    if (!guard(value)) throw Error('Unexpected response from Studio API');
    return value;
}
