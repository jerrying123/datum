import type { CadField } from './models';

type ElementKind<E extends Element> = { new(): E };

function checkedElement<E extends Element>(element: Element, selector: string, kind: ElementKind<E>): E {
    if (!(element instanceof kind))
        throw Error(`Studio element ${selector} must be ${kind.name}; found <${element.localName}>.`);
    return element;
}

// The constructor is required: callers cannot claim an arbitrary element type.
export function requiredElement<E extends Element>(root: ParentNode, selector: string, kind: ElementKind<E>): E {
    const element = root.querySelector(selector);
    if (!element) throw Error(`Required Studio element is missing: ${selector}`);
    return checkedElement(element, selector, kind);
}

export function elementsOfKind<E extends Element>(root: ParentNode, selector: string, kind: ElementKind<E>): E[] {
    return Array.from(root.querySelectorAll(selector), element => checkedElement(element, selector, kind));
}

// Required controls supplied by public/index.html. Unknown selectors are errors
// at compile time, and changed HTML element kinds fail at runtime.
const studioControls = {
    '#worktree': HTMLInputElement,
    '#part-colors': HTMLInputElement,
    '#help-toggle': HTMLInputElement,
    '#spec-preview': HTMLTextAreaElement,
    '#assembly-back': HTMLButtonElement,
    '#clear-inspection': HTMLButtonElement,
    '#open-part': HTMLButtonElement,
    '#panel-toggle': HTMLButtonElement,
    '#generate': HTMLButtonElement,
    '#download': HTMLButtonElement,
    '#download-manifest': HTMLButtonElement,
    '#download-header': HTMLButtonElement,
    '#copy-spec': HTMLButtonElement,
    '#ack-change': HTMLButtonElement,
    '#urdf-start': HTMLButtonElement,
    '#urdf-cancel': HTMLButtonElement,
    '#urdf-reconnect': HTMLButtonElement,
    '#urdf-report': HTMLAnchorElement,
    '#urdf-bundle': HTMLAnchorElement,
    '#urdf-progress': HTMLProgressElement,
    '#workspace-panel': HTMLElement,
    '#assembly-location': HTMLSpanElement,
    '#inspection-location': HTMLSpanElement,
    '#selected-part': HTMLParagraphElement,
    '#preview-label': HTMLSpanElement,
    '#mapping-count': HTMLSpanElement,
    '#change-path': HTMLSpanElement,
    '#flow-status': HTMLParagraphElement,
    '#change-summary': HTMLParagraphElement,
    '#message': HTMLParagraphElement,
    '#changes': HTMLElement,
    '#before': HTMLDivElement,
    '#after': HTMLDivElement,
    '#feature-tree': HTMLDivElement,
    '#inspector': HTMLDivElement,
    '#cad-list': HTMLDivElement,
    '#assembly-tree': HTMLDivElement,
    '#preview': HTMLDivElement,
    '#mappings': HTMLDivElement,
    '#generated-files': HTMLDivElement,
    '#urdf-selection': HTMLParagraphElement,
    '#urdf-status': HTMLParagraphElement,
    '#urdf-job-source': HTMLParagraphElement,
    '#urdf-evidence': HTMLDivElement,
    '#urdf-downloads': HTMLDivElement,
};

export function $<S extends keyof typeof studioControls>(selector: S): InstanceType<(typeof studioControls)[S]>;
export function $(selector: keyof typeof studioControls): HTMLElement {
    return requiredElement<HTMLElement>(document, selector, studioControls[selector]);
}

const simulationControls = {
    start: HTMLButtonElement, pause: HTMLButtonElement, resume: HTMLButtonElement,
    step: HTMLButtonElement, reset: HTMLButtonElement, stop: HTMLButtonElement,
    record: HTMLButtonElement, reconnect: HTMLButtonElement, 'set-joint': HTMLButtonElement, 'drive-joint': HTMLButtonElement, kp: HTMLInputElement, kd: HTMLInputElement, 'max-force': HTMLInputElement,
    assembly: HTMLSelectElement, backend: HTMLSelectElement, joint: HTMLSelectElement,
    position: HTMLInputElement, capabilities: HTMLParagraphElement, status: HTMLParagraphElement,
    view: HTMLDivElement, 'view-status': HTMLParagraphElement, telemetry: HTMLPreElement,
    recordings: HTMLOListElement, recent: HTMLOListElement,
};

export function simulationElement<S extends keyof typeof simulationControls>(id: S): InstanceType<(typeof simulationControls)[S]>;
export function simulationElement(id: keyof typeof simulationControls): HTMLElement {
    return requiredElement<HTMLElement>(document, `#sim-${id}`, simulationControls[id]);
}

export function renderChangeFields(host: HTMLElement, fields: CadField[]): void {
    host.replaceChildren();
    for (const field of fields) {
        const line = document.createElement('div');
        line.className = 'diff-line';
        const pointer = document.createElement('code'), value = document.createElement('strong');
        pointer.textContent = field.pointer;
        value.textContent = String(field.value);
        line.append(pointer, value);
        host.append(line);
    }
}
