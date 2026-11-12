import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { ThreeMFLoader } from 'three/addons/loaders/3MFLoader.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { $, requiredElement, simulationElement, renderChangeFields } from './dom';
import * as contract from './contracts';
import type { Guard } from './contracts';
import { errorMessage, errorStatus, isParameterMapping, isRecord, pointerValue } from './models';
import type { CadCatalog, CadChange, CadConstraint, CadFeature, CadField, CadFile, Capability, CommandAcknowledgement, CommandReceipt, DimensionInput, GeneratedFiles, GenerationResponse, ParameterMapping, ParameterSource, ParameterSpec, PartOccurrence, SimulationCapability, SimulationCommandRequest, SimulationHistory, SimulationRecordings, SimulationScene, SimulationSession, SimulationState, SimulationStatus, UrdfJob, UrdfJobState, UrdfJobStatus, UrdfStartResponse, Vector3Tuple, } from './models';
let files: CadFile[] = [];
let mappings: ParameterMapping[] = [];
const snapshots = new Map<string, CadFile>();
let pendingChange: CadChange | null = null;
let selectedPath: string | null = null;
let inspectionPath: string | null = null;
let selectedOccurrence: string | null = null;
let selectedFeature: number | string | null = null;
let viewportHighlight: () => void = () => {
};
let viewportRenderer: THREE.WebGLRenderer | null = null;
let viewportControls: OrbitControls | null = null;
let resizeObserver: ResizeObserver | null = null;
let viewportState: 'idle' | 'loading' | 'ready' | 'failed' = 'idle';
type WorkspaceTab = 'parts' | 'features' | 'mappings' | 'export';
let activeTab: WorkspaceTab = 'parts';
let navigation: string[] = [];
let storageKey: string | null = null;
let lastPartTap: {
    key: string;
    path: string;
    time: number;
    x: number;
    y: number;
} | null = null;
const selectedParts = new Set<string>();
const expandedParts = new Set<string>();
function showTab(tab: WorkspaceTab) {
    activeTab = tab;
    document.body.dataset.tab = tab;
    document.querySelectorAll<HTMLElement>('[data-tab]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.tab === tab)));
    updateFlow();
}
function showDatasetTab(tab: string | undefined) {
    if (tab === 'parts' || tab === 'features' || tab === 'mappings' || tab === 'export')
        showTab(tab);
}
function updateFlow() {
    const status = $('#flow-status');
    if (status)
        status.textContent = activeTab === 'parts' ? 'Choose a source part, then continue to Dimensions.' : activeTab === 'features' ? 'Choose a feature and add a dimension as a code parameter.' : activeTab === 'mappings' ? `${mappings.length} code parameter${mappings.length === 1 ? '' : 's'} selected. Review names, then generate.` : 'Generate files from the selected code parameters.';
}
document.querySelectorAll<HTMLElement>('[data-go]').forEach(b => b.onclick = () => showDatasetTab(b.dataset.go));
document.querySelectorAll<HTMLElement>('[data-tab]').forEach(b => b.onclick = () => showDatasetTab(b.dataset.tab));
showTab('parts');
const panelToggle = $('#panel-toggle'), workspacePanel = $('#workspace-panel');
panelToggle.onclick = () => {
    const expanded = panelToggle.getAttribute('aria-expanded') === 'true';
    panelToggle.setAttribute('aria-expanded', String(!expanded));
    panelToggle.textContent = expanded ? 'Show tools' : 'Hide tools';
    workspacePanel.hidden = expanded;
};
function saveWorkspace() {
    if (!storageKey)
        return;
    try {
        localStorage.setItem(storageKey, JSON.stringify({ mappings, worktree: $('#worktree').value }));
    }
    catch {
    }
}
function loadWorkspace(body: CadCatalog) {
    const identity = body.project_id || body.projectId;
    const key = identity ? `dparams-workspace-v1:${identity}` : null;
    if (key === storageKey)
        return;
    {
        mappings = [];
        navigation = [];
        selectedPath = null;
        inspectionPath = null;
        selectedOccurrence = null;
        selectedParts.clear();
        expandedParts.clear();
        selectedFeature = null;
        catalogSignature = null;
        snapshots.clear();
        pendingChange = null;
        $('#changes').hidden = true;
        $('#worktree').value = 'main';
    }
    storageKey = key;
    if (key)
        try {
            const saved: unknown = JSON.parse(localStorage.getItem(key) || 'null');
            if (isRecord(saved) && Array.isArray(saved.mappings)) {
                mappings = saved.mappings.filter(isParameterMapping).map(m => ({ ...m, stale: true }));
                $('#worktree').value = typeof saved.worktree === 'string' ? saved.worktree : 'main';
            }
        }
        catch {
        }
}
function renderNavigation() {
    renderUrdfSelection();
    $('#assembly-back').disabled = !navigation.length;
    $('#assembly-location').textContent = [...navigation, selectedPath].filter(Boolean).join(' → ') || 'Select a document';
    const occ = files.find(f => f.path === selectedPath);
    const entry = occ && occurrences(occ).find(o => o.key === selectedOccurrence);
    $('#inspection-location').textContent = entry ? `Inspecting ${entry.name} · ${inspectionPath || 'source unavailable'}` : `Inspecting ${selectedPath || 'no document'}`;
    $('#clear-inspection').hidden = !entry;
    $('#open-part').hidden = !entry || !files.some(f => f.path === inspectionPath);
    $('#selected-part').textContent = entry ? `Selected: ${entry.name} · source ${inspectionPath || 'unavailable'}` : 'Select a part in the viewer or tree';
}
$('#clear-inspection').onclick = clearInspection;
$('#open-part').onclick = () => {
    if (inspectionPath)
        selectFile(inspectionPath);
};
$('#assembly-back').onclick = () => {
    const path = navigation.pop();
    if (path) {
        selectFile(path, false);
        showTab('parts');
    }
};
$('#worktree').oninput = () => {
    saveWorkspace();
    updateSpecPreview();
};
function resolveCadPath(from: string, to: string): string {
    const a = from.split('/');
    a.pop();
    for (const part of to.replaceAll('\\', '/').split('/')) {
        if (part === '..')
            a.pop();
        else if (part !== '.' && part)
            a.push(part);
    }
    return a.join('/');
}
function sourcePath(file: CadFile, feature: CadFeature): string | null {
    const links = Object.values(file.links || {}), link = links.find(x => x.feature === feature.id) || file.links?.[String(feature.component)] || file.links?.[String(feature.id)];
    const source = link?.path || feature.file;
    return source ? resolveCadPath(file.path, source) : null;
}
let partColors = false;
try {
    partColors = localStorage.getItem('dparams-part-colors') === 'on';
}
catch {
}
$('#part-colors').checked = partColors;
$('#part-colors').onchange = () => {
    partColors = $('#part-colors').checked;
    try {
        localStorage.setItem('dparams-part-colors', partColors ? 'on' : 'off');
    }
    catch {
    }
    renderAssemblyTree();
    viewportHighlight();
};
interface PreviewData {
    occurrenceKey?: string;
    paletteIndex?: number;
    updateOutline?: (camera: THREE.Camera) => void;
}
type PreviewMesh = Omit<THREE.Mesh<THREE.BufferGeometry, THREE.MeshStandardMaterial>, 'userData'> & {
    userData: PreviewData;
};
function previewData(object: THREE.Object3D): PreviewData {
    return object.userData;
}
// Weld triangle vertices to identify view-dependent silhouettes without drawing
// the tessellation diagonals across planar faces.
function addPartLines(mesh: PreviewMesh) {
    const geometry = mesh.geometry, positions = geometry.getAttribute('position'), index = geometry.index, edges = new Map<string, {
        a: THREE.Vector3;
        b: THREE.Vector3;
        normals: THREE.Vector3[];
    }>();
    const vertex = (i: number) => new THREE.Vector3().fromBufferAttribute(positions, i);
    const key = (v: THREE.Vector3) => [v.x, v.y, v.z].map(n => Math.round(n * 1e6)).join(',');
    for (let i = 0; i < (index ? index.count : positions.count); i += 3) {
        const points = [0, 1, 2].map(j => vertex(index ? index.getX(i + j) : i + j));
        const normal = new THREE.Vector3().subVectors(points[1], points[0]).cross(new THREE.Vector3().subVectors(points[2], points[0])).normalize();
        for (let j = 0; j < 3; j++) {
            const a = points[j], b = points[(j + 1) % 3], id = [key(a), key(b)].sort().join('|');
            let edge = edges.get(id);
            if (!edge) {
                edge = { a, b, normals: [] };
                edges.set(id, edge);
            }
            edge.normals.push(normal);
        }
    }
    const internal = new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 20), new THREE.LineBasicMaterial({ color: 0x73787c, depthTest: true }));
    internal.raycast = () => {
    };
    mesh.add(internal);
    const outlineGeometry = new THREE.BufferGeometry(), buffer = new Float32Array(edges.size * 6);
    outlineGeometry.setAttribute('position', new THREE.BufferAttribute(buffer, 3));
    const outline = new THREE.LineSegments(outlineGeometry, new THREE.LineBasicMaterial({ color: 0x000000, depthTest: true }));
    outline.frustumCulled = false;
    outline.raycast = () => {
    };
    mesh.add(outline);
    mesh.userData.updateOutline = (camera: THREE.Camera) => {
        const eye = mesh.worldToLocal(camera.getWorldPosition(new THREE.Vector3()));
        let count = 0;
        for (const e of edges.values()) {
            const direction = eye.clone().sub(e.a);
            const front = e.normals.some(n => n.dot(direction) > 0), back = e.normals.some(n => n.dot(direction) <= 0);
            if (e.normals.length === 1 || (front && back)) {
                e.a.toArray(buffer, count);
                e.b.toArray(buffer, count + 3);
                count += 6;
            }
        }
        outlineGeometry.setDrawRange(0, count / 3);
        outlineGeometry.attributes.position.needsUpdate = true;
    };
}
const palette = [0x3c78a8, 0xd17a43, 0x63966e, 0xa56a97, 0xc2a449, 0x4e9d9c, 0xb85c61, 0x7c80bb];
function occurrences(file: CadFile): PartOccurrence[] {
    return file.features.filter(f => f.type === 'import' && !f.suppressed).flatMap(feature => {
        const found = (file.occurrences || []).filter(o => String(o.component) === String(feature.component));
        return (found.length ? found : [{ id: `feature-${feature.id}`, name: feature.name, component: feature.component }]).map(o => ({ key: String(o.id), name: o.name || feature.name || feature.file || '', feature, path: sourcePath(file, feature) }));
    });
}
let inspectionRequest: AbortController | null = null;
async function inspectOccurrence(file: CadFile, occ: PartOccurrence, stayOnParts = false) {
    if (inspectionRequest)
        inspectionRequest.abort();
    const request = new AbortController();
    inspectionRequest = request;
    inspectionPath = occ.path;
    selectedOccurrence = occ.key;
    selectedParts.add(occ.key);
    if (selectedParts.size === 1)
        expandedParts.add(occ.key);
    selectedFeature = null;
    renderNavigation();
    renderAssemblyTree();
    viewportHighlight();
    if (!stayOnParts)
        showTab('features');
    const tree = $('#feature-tree'), inspector = $('#inspector');
    tree.replaceChildren();
    inspector.replaceChildren();
    const status = document.createElement('div');
    status.className = 'inspection-loading';
    status.setAttribute('role', 'status');
    const text = document.createElement('p');
    text.textContent = `Inspecting ${occ.name}…`;
    const progress = document.createElement('progress');
    progress.setAttribute('aria-label', `Inspecting ${occ.name}`);
    const cancel = document.createElement('button');
    cancel.className = 'secondary';
    cancel.textContent = 'Cancel inspection';
    cancel.onclick = () => {
        clearInspection();
        showTab('parts');
    };
    status.append(text, progress, cancel);
    tree.append(status);
    try {
        const response = await fetch('/api/cad', { cache: 'no-store', signal: request.signal });
        if (!response.ok)
            throw Error('Could not read the CAD project.');
        const body = await contract.jsonResponse(response, contract.catalog);
        if (inspectionRequest !== request)
            return;
        const source = body.files.find(f => f.path === occ.path);
        if (!source)
            throw Error(`Source part ${occ.path || 'path'} is unavailable.`);
        files = body.files;
        inspectionRequest = null;
        if (selectedParts.size === 1 && source.features.length === 1 && source.features[0].type !== 'import')
            selectedFeature = 0;
        renderNavigation();
        renderAssemblyTree();
        renderFeatureTree();
        renderInspector();
    }
    catch (error) {
        if (error instanceof Error && error.name === 'AbortError' || inspectionRequest !== request)
            return;
        inspectionRequest = null;
        tree.textContent = errorMessage(error);
    }
}
function clearInspection() {
    if (inspectionRequest) {
        inspectionRequest.abort();
        inspectionRequest = null;
    }
    inspectionPath = selectedPath;
    selectedOccurrence = null;
    selectedParts.clear();
    expandedParts.clear();
    selectedFeature = null;
    renderNavigation();
    renderAssemblyTree();
    renderFeatureTree();
    renderInspector();
    viewportHighlight();
}
function openSource(file: CadFile, feature: CadFeature) {
    const path = sourcePath(file, feature);
    if (path && files.some(x => x.path === path)) {
        selectFile(path);
        showTab('features');
    }
    else
        showInspectorMessage(`Source part ${path || 'path'} is not present in the mounted project.`);
}
function selectFile(path: string, remember = true) {
    if (inspectionRequest) {
        inspectionRequest.abort();
        inspectionRequest = null;
    }
    const f = files.find(x => x.path === path);
    if (!f)
        return;
    if (remember && selectedPath && selectedPath !== path)
        navigation.push(selectedPath);
    selectedPath = path;
    inspectionPath = path;
    selectedOccurrence = null;
    selectedParts.clear();
    expandedParts.clear();
    selectedFeature = f.features.length === 1 && f.features[0].type !== 'import' ? 0 : null;
    renderNavigation();
    drawPreview(f);
    renderFiles();
    renderAssemblyTree();
    renderFeatureTree();
    renderInspector();
}
function renderFiles() {
    const list = $('#cad-list');
    list.replaceChildren();
    if (!files.length) {
        list.textContent = 'No SolidCraft files found in the mounted project.';
        return;
    }
    for (const f of files) {
        const b = document.createElement('button');
        b.className = 'file-line' + (f.path === selectedPath ? ' active' : '');
        const name = document.createElement('span'), detail = document.createElement('small');
        name.textContent = f.path;
        detail.textContent = `${f.units} · ${f.features.length} features`;
        b.append(name, detail);
        b.onclick = () => selectFile(f.path);
        list.append(b);
    }
    if (!selectedPath || !files.some(f => f.path === selectedPath)) {
        selectedPath = files[0].path;
        inspectionPath = selectedPath;
        drawPreview(files[0]);
    }
}
function renderAssemblyTree() {
    const host = $('#assembly-tree');
    host.replaceChildren();
    const f = files.find(x => x.path === selectedPath);
    if (!f)
        return;
    const entries = occurrences(f);
    if (!entries.length)
        return;
    const title = document.createElement('strong');
    title.textContent = `Select parts in ${f.name || f.path}`;
    host.append(title);
    entries.forEach((occ, i) => {
        const row = document.createElement('label');
        row.className = 'tree-row part-row' + (selectedParts.has(occ.key) ? ' selected' : '');
        const check = document.createElement('input');
        check.type = 'checkbox';
        check.checked = selectedParts.has(occ.key);
        check.setAttribute('aria-label', `Select ${occ.name}`);
        const swatch = document.createElement('span');
        swatch.className = 'part-swatch';
        swatch.style.background = partColors ? `#${palette[i % palette.length].toString(16).padStart(6, '0')}` : '#c2c7ca';
        row.append(check, swatch, document.createTextNode(`${occ.name} · ${occ.path || 'source unavailable'}`));
        check.onchange = () => {
            if (check.checked) {
                inspectOccurrence(f, occ, true);
            }
            else {
                if (inspectionRequest && selectedOccurrence === occ.key) {
                    inspectionRequest.abort();
                    inspectionRequest = null;
                }
                selectedParts.delete(occ.key);
                expandedParts.delete(occ.key);
                if (selectedParts.size === 1)
                    expandedParts.add([...selectedParts][0]);
                if (selectedOccurrence === occ.key) {
                    const remaining = entries.find(x => selectedParts.has(x.key));
                    inspectionPath = remaining?.path || selectedPath;
                    selectedOccurrence = remaining?.key || null;
                    selectedFeature = null;
                }
                renderNavigation();
                renderAssemblyTree();
                renderFeatureTree();
                renderInspector();
                viewportHighlight();
            }
        };
        host.append(row);
    });
}
function drawPreview(file: CadFile) {
    viewportState = 'loading';
    $('#preview-label').textContent = `${file.path} · drag to orbit · tap to inspect · double-tap to open part`;
    const host = $('#preview');
    if (resizeObserver)
        resizeObserver.disconnect();
    if (viewportControls)
        viewportControls.dispose();
    if (viewportRenderer) {
        viewportRenderer.dispose();
        viewportRenderer = null;
    }
    host.replaceChildren();
    try {
        const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
        viewportRenderer = renderer;
        renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
        renderer.setSize(host.clientWidth, host.clientHeight);
        renderer.outputColorSpace = THREE.SRGBColorSpace;
        renderer.setClearColor(0xdce3e6);
        host.append(renderer.domElement);
        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0xdce3e6);
        const camera = new THREE.PerspectiveCamera(35, host.clientWidth / host.clientHeight, .1, 100000);
        scene.add(new THREE.HemisphereLight(0xffffff, 0x66716c, 1.05));
        const key = new THREE.DirectionalLight(0xffffff, 1.15);
        key.position.set(1, -2, 3);
        scene.add(key);
        const fill = new THREE.DirectionalLight(0xffffff, .5);
        fill.position.set(-2, 1, 1);
        scene.add(fill);
        const controls = new OrbitControls(camera, renderer.domElement);
        viewportControls = controls;
        controls.enableDamping = true;
        const raycaster = new THREE.Raycaster(), pointer = new THREE.Vector2();
        let model: THREE.Group | null = null;
        let down: [
            number,
            number
        ] | null = null;
        viewportHighlight = () => {
        };
        const render = () => {
            if (viewportRenderer !== renderer)
                return;
            controls.update();
            scene.updateMatrixWorld();
            if (model)
                model.traverse(m => previewData(m).updateOutline?.(camera));
            renderer.render(scene, camera);
            requestAnimationFrame(render);
        };
        requestAnimationFrame(render);
        resizeObserver = new ResizeObserver(() => {
            if (!host.clientWidth || !host.clientHeight)
                return;
            renderer.setSize(host.clientWidth, host.clientHeight);
            camera.aspect = host.clientWidth / host.clientHeight;
            camera.updateProjectionMatrix();
        });
        resizeObserver.observe(host);
        new ThreeMFLoader().load(`/api/model/${file.previewId}?v=${file.fingerprint}`, group => {
            if (viewportRenderer !== renderer)
                return;
            viewportState = 'ready';
            model = group;
            scene.add(group);
            const entries = occurrences(file), meshCounts = new Map<string, number>();
            group.traverse(object => {
                if (!(object instanceof THREE.Mesh))
                    return;
                const mesh = object as PreviewMesh;
                let node: THREE.Object3D | null = mesh;
                while (node && !node.name)
                    node = node.parent;
                const label = node?.name || '', base = label.replace(/ \(\d+\)$/, ''), explicit = Number(label.match(/ \((\d+)\)$/)?.[1] || 0);
                const candidates = entries.filter(o => [o.name, o.feature.name, ...(o.feature.body_names || []), ...(o.feature.components || []).map(c => c.name)].some(n => n === label || n === base));
                const count = meshCounts.get(base) || 0;
                meshCounts.set(base, count + 1);
                const occ = candidates[(explicit || count + 1) - 1] || (candidates.length === 1 ? candidates[0] : null);
                mesh.userData.occurrenceKey = occ?.key;
                const index = Math.max(0, occ ? entries.indexOf(occ) : -1);
                mesh.userData.paletteIndex = index;
                if (!mesh.geometry.getAttribute('normal'))
                    mesh.geometry.computeVertexNormals();
                mesh.material = new THREE.MeshStandardMaterial({ flatShading: true, side: THREE.DoubleSide, color: partColors ? palette[index % palette.length] : 0xc2c7ca, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1, roughness: .72, metalness: .05 });
                addPartLines(mesh);
            });
            viewportHighlight = () => group.traverse(object => {
                if (!(object instanceof THREE.Mesh))
                    return;
                const mesh = object as PreviewMesh;
                const chosen = selectedParts.has(previewData(mesh).occurrenceKey || '');
                mesh.material.emissive.set(chosen ? 0x0066ff : 0x000000);
                mesh.material.emissiveIntensity = chosen ? 0.55 : 1;
                mesh.material.color.setHex(chosen ? 0x0088ff : (partColors ? palette[(mesh.userData.paletteIndex ?? 0) % palette.length] : 0xc2c7ca));
                if (selectedParts.size && !chosen)
                    mesh.material.color.multiplyScalar(.85);
            });
            viewportHighlight();
            const box = new THREE.Box3().setFromObject(group), size = box.getSize(new THREE.Vector3()), center = box.getCenter(new THREE.Vector3()), span = Math.max(size.x, size.y, size.z, 1);
            camera.position.set(center.x + span * 1.5, center.y - span * 1.5, center.z + span * 1.15);
            camera.near = Math.max(span / 10000, .01);
            camera.far = span * 100;
            camera.updateProjectionMatrix();
            controls.target.copy(center);
            controls.minDistance = span * .05;
            controls.maxDistance = span * 20;
            controls.update();
        }, undefined, () => {
            if (viewportRenderer === renderer) {
                viewportState = 'failed';
                renderer.dispose();
                viewportRenderer = null;
                host.replaceChildren();
                drawPreviewPng(file, host);
            }
        });
        renderer.domElement.addEventListener('pointerdown', e => {
            down = [e.clientX, e.clientY];
        });
        renderer.domElement.addEventListener('pointerup', e => {
            if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5 || !model)
                return;
            const rect = renderer.domElement.getBoundingClientRect();
            pointer.set((e.clientX - rect.left) / rect.width * 2 - 1, -(e.clientY - rect.top) / rect.height * 2 + 1);
            raycaster.setFromCamera(pointer, camera);
            const hit = raycaster.intersectObject(model, true)[0];
            if (hit)
                selectMesh(file, hit.object, e);
        });
    }
    catch (e) {
        viewportState = 'failed';
        host.textContent = `3D viewport unavailable: ${errorMessage(e)}`;
    }
}
function drawPreviewPng(file: CadFile, host: HTMLElement) {
    const img = document.createElement('img');
    img.className = 'solidcraft-render';
    img.alt = `SolidCraft render of ${file.path}`;
    img.src = `/api/preview/${file.previewId}?v=${file.fingerprint}`;
    img.onerror = () => {
        if (!host.contains(img))
            return;
        img.remove();
        drawPrimitivePreview(file, host);
    };
    host.append(img);
}
function selectMesh(file: CadFile, mesh: THREE.Object3D, event: PointerEvent) {
    const label = mesh.name || 'mesh';
    if (file.features.some(f => f.type === 'import')) {
        const occ = occurrences(file).find(o => o.key === previewData(mesh).occurrenceKey);
        if (occ) {
            const now = performance.now(), prior = lastPartTap;
            lastPartTap = { key: occ.key, path: file.path, time: now, x: event.clientX, y: event.clientY };
            if (prior && prior.key === occ.key && prior.path === file.path && now - prior.time < 500 && Math.hypot(event.clientX - prior.x, event.clientY - prior.y) < 35) {
                lastPartTap = null;
                if (occ.path && files.some(f => f.path === occ.path)) {
                    selectFile(occ.path);
                    showTab('features');
                }
                else
                    showInspectorMessage('This part’s source file is unavailable.');
            }
            else {
                selectedParts.clear();
                expandedParts.clear();
                inspectOccurrence(file, occ);
            }
        }
        else
            showInspectorMessage(`Selected mesh “${label}”. No SolidCraft occurrence matched its mesh identity.`);
        return;
    }
    const index = file.features.findIndex(f => (f.body_names || []).includes(label) || f.name === label);
    if (index >= 0) {
        selectedFeature = index;
        renderFeatureTree();
        renderInspector();
        showTab('features');
        return;
    }
    showInspectorMessage(`Selected mesh “${label}”. Choose a feature or sketch in the history tree to see its code inputs.`);
}
function showInspectorMessage(message: string, action?: string, callback?: () => void) {
    showTab('features');
    const host = $('#inspector');
    host.replaceChildren();
    const p = document.createElement('p');
    p.textContent = message;
    host.append(p);
    if (action) {
        const b = document.createElement('button');
        b.className = 'secondary';
        b.textContent = action;
        b.onclick = callback ?? null;
        host.append(b);
    }
}
function drawPrimitivePreview(file: CadFile, host: HTMLElement) {
    const shapes = (file.features || []).filter(x => !x.suppressed && ['box', 'cylinder'].includes(x.type));
    if (!shapes.length) {
        host.textContent = 'SolidCraft render is being prepared; no primitive preview is available.';
        return;
    }
    host.textContent = 'SolidCraft render is being prepared. Primitive geometry is available after the render finishes.';
}
function renderFeatureTree() {
    const host = $('#feature-tree');
    host.replaceChildren();
    const assembly = files.find(x => x.path === selectedPath);
    const entries = assembly ? occurrences(assembly).filter(o => selectedParts.has(o.key)) : [];
    function featureButtons(file: CadFile, container: HTMLElement, occ: PartOccurrence | null = null) {
        for (const [i, item] of file.features.entries()) {
            const b = document.createElement('button');
            b.className = 'tree-row feature-row' + (inspectionPath === file.path && selectedFeature === i && (!occ || selectedOccurrence === occ.key) ? ' selected' : '');
            const kind = String(item.type || 'feature').toLowerCase();
            b.textContent = `${kind === 'sketch' ? '✎' : '◇'}  ${item.name || `${item.type} ${item.id}`} · ${item.type}`;
            b.onclick = () => {
                inspectionPath = file.path;
                if (occ)
                    selectedOccurrence = occ.key;
                selectedFeature = i;
                renderNavigation();
                renderFeatureTree();
                renderInspector();
            };
            container.append(b);
        }
    }
    if (entries.length) {
        for (const occ of entries) {
            const file = files.find(x => x.path === occ.path), details = document.createElement('details');
            details.open = expandedParts.has(occ.key);
            const summary = document.createElement('summary');
            summary.textContent = `${occ.name} · ${file ? file.features.length + ' features' : 'source unavailable'}`;
            details.append(summary);
            details.ontoggle = () => {
                if (details.open)
                    expandedParts.add(occ.key);
                else
                    expandedParts.delete(occ.key);
            };
            if (file)
                featureButtons(file, details, occ);
            host.append(details);
        }
        return;
    }
    const f = files.find(x => x.path === inspectionPath);
    if (!f) {
        host.textContent = 'Source document is unavailable.';
        return;
    }
    featureButtons(f, host, null);
}
function renderInspector() {
    const host = $('#inspector');
    host.replaceChildren();
    const f = files.find(x => x.path === inspectionPath);
    if (!f || selectedFeature === null) {
        host.textContent = 'Choose a feature or sketch from the tree to inspect its source values.';
        return;
    }
    if (typeof selectedFeature === 'string') {
        host.textContent = `Sketch ${selectedFeature.slice(7)} is selected. Sketch geometry is shown by name; only dimensions explicitly present in the CAD document can be mapped.`;
        return;
    }
    const item = f.features[selectedFeature];
    if (item.type === 'import') {
        const title = document.createElement('h3');
        title.textContent = `${item.name || 'Part'} · Part`;
        const p = document.createElement('p');
        p.textContent = `Open the source part to choose its dimensions: ${sourcePath(f, item) || 'source path unavailable'}`;
        const b = document.createElement('button');
        b.className = 'secondary';
        b.textContent = 'Open source part';
        b.onclick = () => openSource(f, item);
        host.append(title, p, b);
        return;
    }
    const prefix = `/features/${selectedFeature}/`;
    const allowed = new Set(['length', 'width', 'height', 'radius', 'diameter', 'thickness', 'depth', 'distance']);
    let inputs: DimensionInput[];
    if (item.type === 'sketch') {
        const types = new Set(['length', 'distance', 'radius', 'diameter']);
        inputs = (item.sketch?.constraints || []).map((c, j) => ({ c, j })).filter((entry): entry is {
            c: CadConstraint & {
                value: number;
            };
            j: number;
        } => types.has(entry.c.type) && typeof entry.c.value === 'number' && Number.isFinite(entry.c.value)).map(({ c, j }) => {
            const param = f.params.find(p => p.name === c.param);
            return { pointer: `${prefix}sketch/constraints/${j}/value`, value: c.value, units: param?.unit || f.units, paramName: param?.expr, label: `${c.type}${param?.expr ? ` · ${param.expr}` : ''}` };
        });
    }
    else {
        inputs = f.fields.filter(x => x.pointer.startsWith(prefix) && allowed.has(x.pointer.slice(prefix.length).split('/')[0])).map(x => ({ ...x, units: f.units, label: x.pointer.slice(prefix.length) }));
    }
    const title = document.createElement('h3');
    title.textContent = `${item.name || item.type} · ${item.type}${item.id !== undefined ? ` #${item.id}` : ''}`;
    host.append(title);
    const body = document.createElement('p');
    body.textContent = `Source: ${f.path} · SolidCraft units: ${f.units}`;
    host.append(body);
    if (item.suppressed) {
        const warn = document.createElement('p');
        warn.textContent = 'This feature is suppressed.';
        host.append(warn);
    }
    if (!inputs.length) {
        const empty = document.createElement('p');
        empty.textContent = 'No supported literal dimensions on this feature. Named expressions and arbitrary formulas are not eligible for direct parameter export yet.';
        host.append(empty);
    }
    for (const x of inputs) {
        const row = document.createElement('div');
        row.className = 'input-row';
        const label = document.createElement('span');
        label.textContent = `${x.label} = ${x.value} ${x.units}`;
        const button = document.createElement('button');
        button.className = 'secondary';
        button.textContent = 'Add code parameter';
        button.onclick = () => {
            mappings = mappings.filter(m => !(m.path === f.path && m.pointer === x.pointer));
            mappings.push({ sourceFingerprint: f.fingerprint, path: f.path, pointer: x.pointer, units: x.units, unit: 'm', value: x.value, featureId: item.id, featureName: item.name, featureType: item.type, name: `${String(x.paramName || `${item.name || item.type}_${x.pointer.split('/').pop()}`).toLowerCase().replace(/[^a-z0-9]+/g, '_')}_m` });
            renderMappings();
            showTab('mappings');
        };
        row.append(label, button);
        host.append(row);
    }
}
function renderMappings() {
    updateFlow();
    saveWorkspace();
    updateSpecPreview();
    $('#mapping-count').textContent = String(mappings.length);
    const host = $('#mappings');
    host.replaceChildren();
    if (!mappings.length) {
        host.textContent = 'No code parameters mapped yet. Open a source part, select a dimension, and choose Add code parameter.';
        return;
    }
    for (const [i, m] of mappings.entries()) {
        const row = document.createElement('div');
        row.className = 'mapping';
        row.innerHTML = '<label>Code name<input class="name"></label><span class="source-ref"></span><label>Output unit<input class="unit" value="m"></label><button class="remove" type="button">Remove</button>';
        const name = requiredElement(row, '.name', HTMLInputElement);
        const unit = requiredElement(row, '.unit', HTMLInputElement);
        const reference = requiredElement(row, '.source-ref', HTMLSpanElement);
        const remove = requiredElement(row, '.remove', HTMLButtonElement);
        name.value = m.name || '';
        unit.value = m.unit || 'm';
        reference.textContent = `${m.stale ? 'RESELECT FEATURE · ' : ''}${m.path} ${m.pointer} = ${m.value} ${m.units}`;
        if (m.stale)
            row.classList.add('stale');
        name.oninput = () => {
            m.name = name.value;
            saveWorkspace();
            updateSpecPreview();
        };
        unit.oninput = () => {
            m.unit = unit.value;
            saveWorkspace();
            updateSpecPreview();
        };
        remove.onclick = () => {
            mappings.splice(i, 1);
            renderMappings();
        };
        host.append(row);
    }
}
function renderChange(change: CadChange) {
    pendingChange = change;
    $('#changes').hidden = false;
    $('#change-path').textContent = change.path;
    renderChangeFields($('#before'), change.before.fields);
    renderChangeFields($('#after'), change.after.fields);
    $('#change-summary').textContent = 'Review updated dimensions before regenerating parameters.';
    requiredElement(document, '[data-tab=export]', HTMLButtonElement).textContent = '4 Generate • Review changes';
}
$('#ack-change').onclick = () => {
    $('#changes').hidden = true;
    pendingChange = null;
    requiredElement(document, '[data-tab=export]', HTMLButtonElement).textContent = '4 Generate';
};
function updateHelp() {
    const enabled = $('#help-toggle').checked;
    localStorage.setItem('dparams-help', enabled ? 'on' : 'off');
    document.querySelectorAll<HTMLElement>('[data-help]').forEach(el => {
        if (enabled)
            el.title = el.dataset.help || '';
        else
            el.removeAttribute('title');
    });
    document.body.classList.toggle('help-off', !enabled);
}
$('#help-toggle').checked = localStorage.getItem('dparams-help') !== 'off';
$('#help-toggle').onchange = updateHelp;
updateHelp();
let catalogSignature: string | null = null;
async function refresh() {
    try {
        const response = await fetch('/api/cad', { cache: 'no-store' }), body = await contract.jsonResponse(response, contract.catalog);
        if (!response.ok)
            throw Error(body.error);
        loadWorkspace(body);
        const signature = JSON.stringify(body.files.map(f => [f.path, f.fingerprint]));
        if (signature === catalogSignature) {
            files = body.files;
            for (const file of files)
                snapshots.set(file.path, file);
            const current = files.find(f => f.path === selectedPath);
            if (current && viewportState === 'failed')
                drawPreview(current);
            return;
        }
        const firstLoad = catalogSignature === null;
        if (firstLoad)
            for (const mapping of mappings) {
                const file = body.files.find(f => f.path === mapping.path), feature = file?.features[Number(mapping.pointer.split('/')[2])];
                if (file && mapping.sourceFingerprint === file.fingerprint && feature?.id === mapping.featureId && feature?.type === mapping.featureType && feature?.name === mapping.featureName)
                    mapping.stale = false;
            }
        let selectedChanged = false, inspectionChanged = false;
        for (const file of body.files) {
            const old = snapshots.get(file.path);
            if (old && old.fingerprint !== file.fingerprint) {
                renderChange({ path: file.path, before: old, after: file });
                selectedChanged ||= file.path === selectedPath;
                if (file.path === inspectionPath && file.path !== selectedPath)
                    inspectionChanged = true;
                for (const mapping of mappings.filter(m => m.path === file.path && m.featureId !== undefined)) {
                    const index = Number(mapping.pointer.split('/')[2]), current = file.features[index];
                    const parts = mapping.pointer.split('/').slice(3).map(p => p.replaceAll('~1', '/').replaceAll('~0', '~'));
                    const value = pointerValue(current, parts);
                    const field = file.fields.find(x => x.pointer === mapping.pointer);
                    const constraint = current?.type === 'sketch' && parts[0] === 'sketch' && parts[1] === 'constraints' ? current.sketch?.constraints?.[Number(parts[2])] : null;
                    if (!current || current.id !== mapping.featureId || current.type !== mapping.featureType || current.name !== mapping.featureName || (!field && !constraint) || (typeof value !== 'number' && typeof value !== 'string' && typeof value !== 'boolean'))
                        mapping.stale = true;
                    else if (!mapping.stale) {
                        mapping.sourceFingerprint = file.fingerprint;
                        mapping.value = value;
                        mapping.units = constraint ? (file.params.find(p => p.name === constraint.param)?.unit || file.units) : file.units;
                    }
                }
            }
            snapshots.set(file.path, file);
        }
        const paths = new Set(body.files.map(f => f.path));
        for (const mapping of mappings)
            if (!paths.has(mapping.path))
                mapping.stale = true;
        const selectedRemoved = selectedPath && !paths.has(selectedPath);
        if (selectedRemoved) {
            selectedPath = null;
            inspectionPath = null;
            selectedOccurrence = null;
            selectedFeature = null;
        }
        else if (inspectionPath && !paths.has(inspectionPath)) {
            inspectionChanged = true;
        }
        files = body.files;
        // Keep DOM nodes and keyboard focus stable between unchanged polls.
        renderFiles();
        renderUrdfSelection();
        if (!inspectionRequest && (firstLoad || selectedRemoved || selectedChanged || inspectionChanged)) {
            const current = files.find(f => f.path === selectedPath);
            if (current && selectedChanged)
                drawPreview(current);
            if (selectedChanged || inspectionChanged)
                selectedFeature = null;
            renderNavigation();
            renderAssemblyTree();
            renderFeatureTree();
            renderInspector();
        }
        renderMappings();
        catalogSignature = signature;
    }
    catch (error) {
        // Preserve existing controls during a transient refresh failure.
        $('#message').textContent = `Could not refresh CAD files: ${errorMessage(error)}`;
    }
}
function buildSpec() {
    const params: Record<string, ParameterSource> = {};
    for (const m of mappings) {
        if (m.stale)
            throw Error(`${m.name} points to a feature that changed or was restored. Reselect that feature input before exporting.`);
        if (!m.name || !/^[a-z][a-z0-9_]*$/.test(m.name))
            throw Error('Use a snake_case code name beginning with a lowercase letter.');
        if (Object.hasOwn(params, m.name))
            throw Error(`Duplicate code name: ${m.name}`);
        params[m.name] = { path: m.path, pointer: m.pointer, source_units: m.units, unit: m.unit };
    }
    if (!Object.keys(params).length)
        throw Error('Choose at least one dimension and add it as a code parameter first.');
    const worktree = $('#worktree').value.trim();
    if (!/^[a-z][a-z0-9_]*$/.test(worktree))
        throw Error('Worktree must be lowercase snake_case.');
    return JSON.stringify({ schema: 'datum.robot.parameter-spec/2', units: 'm', worktrees: { [worktree]: { parameters: params } } }, null, 2) + '\n';
}
function updateSpecPreview() {
    $('#generated-files').hidden = true;
    try {
        $('#spec-preview').value = buildSpec();
    }
    catch (error) {
        $('#spec-preview').value = '';
        $('#spec-preview').placeholder = errorMessage(error);
    }
}
$('#download').onclick = () => {
    try {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(new Blob([buildSpec()], { type: 'application/json' }));
        a.download = 'spec.json';
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 1000);
        $('#message').textContent = 'Downloaded spec.json. Use datum-params generate to generate parameters.';
    }
    catch (error) {
        $('#message').textContent = errorMessage(error);
    }
};
let generatedFiles: GeneratedFiles | null = null;
function downloadText(text: string, name: string, type: string) {
    const url = URL.createObjectURL(new Blob([text], { type }));
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$('#generate').onclick = async () => {
    const button = $('#generate');
    try {
        const spec: ParameterSpec = JSON.parse(buildSpec());
        button.disabled = true;
        $('#generated-files').hidden = true;
        $('#message').textContent = 'Generating from the current saved CAD files…';
        const response = await fetch('/api/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ spec, worktree: $('#worktree').value.trim() }) });
        const body = await contract.jsonResponse(response, contract.generation);
        if (typeof body.manifest !== 'string' || typeof body.header !== 'string')
            throw Error('Generation returned no manifest or header.');
        if (buildSpec() !== JSON.stringify(spec, null, 2) + '\n')
            throw Error('Code parameters changed during generation. Generate again.');
        generatedFiles = { manifest: body.manifest, header: body.header };
        $('#generated-files').hidden = false;
        $('#message').textContent = 'Generated from saved CAD. Download the manifest and C++ header below.';
    }
    catch (error) {
        $('#message').textContent = errorMessage(error);
    }
    finally {
        button.disabled = false;
    }
};
$('#download-manifest').onclick = () => {
    if (generatedFiles)
        downloadText(generatedFiles.manifest, 'parameters.json', 'application/json');
};
$('#download-header').onclick = () => {
    if (generatedFiles)
        downloadText(generatedFiles.header, 'parameters.hpp', 'text/plain');
};
$('#copy-spec').onclick = async () => {
    try {
        const spec = buildSpec();
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(spec);
            $('#message').textContent = 'Spec JSON copied.';
        }
        else {
            $('#spec-preview').value = spec;
            $('#spec-preview').focus();
            $('#spec-preview').select();
            $('#message').textContent = 'Spec selected. Use your device’s Copy command.';
        }
    }
    catch (error) {
        $('#message').textContent = errorMessage(error);
    }
};
refresh();
setInterval(refresh, 2000);
// URDF jobs are scoped to the server origin and mounted project identity.
let urdfCapability: string | null = null;
let urdfJob: UrdfJob | null = null;
let urdfScope: string | null = null;
let urdfBusy = false;
let urdfTimer: ReturnType<typeof setTimeout> | undefined;
const urdfTerminal = new Set(['succeeded', 'failed', 'cancelled', 'canceled']);
function renderUrdfSelection() {
    $('#urdf-selection').textContent = `Selected source assembly: ${selectedPath || 'none — choose a document in Parts'}`;
    $('#urdf-start').disabled = !selectedPath || !urdfCapability || urdfBusy || !!urdfJob && !urdfTerminal.has(urdfJob.state || '');
}
function rememberUrdf() {
    try {
        if (urdfScope)
            localStorage.setItem(urdfScope, JSON.stringify(urdfJob));
    }
    catch {
    }
}
// Successful responses are typed at each endpoint call; error payloads are
// untrusted and narrowed independently of that endpoint's success contract.
async function urdfRequest<T>(path: string, guard: Guard<T>, options: RequestInit = {}): Promise<T> {
    return contract.jsonResponse(await fetch(path, {cache:'no-store', ...options}), guard);
}
function showUrdfJob(body: UrdfJobStatus) {
    if (!urdfJob)
        return;
    urdfJob = { ...urdfJob, ...body };
    rememberUrdf();
    const state = urdfJob.state || 'queued';
    const names: Record<UrdfJobState, string> = { queued: 'Queued', capturing: 'Capturing saved CAD source', exporting: 'Exporting URDF', checking: 'Running structural checks', succeeded: 'Export complete — review evidence', failed: 'Export failed', cancelled: 'Export cancelled', canceled: 'Export cancelled' };
    $('#urdf-status').textContent = (names[state] || `Stage: ${state}`) + (body.error ? ` · ${typeof body.error === 'string' ? body.error : JSON.stringify(body.error)}` : '');
    $('#urdf-progress').hidden = urdfTerminal.has(state);
    $('#urdf-cancel').hidden = urdfTerminal.has(state);
    $('#urdf-job-source').textContent = `Job source: ${urdfJob.assembly || 'unknown'}`;
    const host = $('#urdf-evidence');
    host.replaceChildren();
    for (const [label, value] of [['Source freshness at export', body.freshness ?? 'unknown'], ['Structural checks', body.structural_checks ?? 'unknown'], ['Assembly fidelity', body.assembly_fidelity ?? 'unknown'], ['Joint fidelity checks', body.report?.cad_urdf_fidelity_checks?.status ?? 'unknown'], ['Mass and inertia plausibility', body.report?.physics_checks?.checks?.mass_inertia?.status ?? 'unknown'], ['Collision checks', body.report?.physics_checks?.checks?.collision_geometry?.status ?? 'unknown'], ['Physics readiness', 'unknown']]) {
        const p = document.createElement('p');
        p.textContent = `${label}: ${typeof value === 'string' ? value : value.status || 'unknown'}`;
        host.append(p);
    }
    for (const issue of body.report?.source_preflight?.issues || []) {
        const p = document.createElement('p');
        p.className = 'urdf-warning';
        p.textContent = issue === 'unsupported_assembly_links' ? 'Assembly coupling was not exported. Review linked joints before using this URDF.' : `Source issue: ${issue}`;
        host.append(p);
    }
    for (const issue of body.report?.structural_checks?.findings || []) {
        const p = document.createElement('p');
        p.className = 'urdf-warning';
        p.textContent = `Structural issue: ${issue}`;
        host.append(p);
    }
    $('#urdf-downloads').hidden = state !== 'succeeded';
    for (const kind of ['report', 'bundle'] as const) {
        $(`#urdf-${kind}`).href = `/api/urdf/jobs/${encodeURIComponent(urdfJob.id)}/${kind}`;
        $(`#urdf-${kind}`).setAttribute('download', '');
    }
    renderUrdfSelection();
}
async function pollUrdf() {
    clearTimeout(urdfTimer);
    if (!urdfJob)
        return;
    const job = urdfJob, scope = urdfScope;
    try {
        const body = await urdfRequest(`/api/urdf/jobs/${encodeURIComponent(job.id)}`, contract.urdfStatus);
        if (scope !== urdfScope || job.id !== urdfJob?.id)
            return;
        showUrdfJob(body);
        if (!urdfTerminal.has(body.state || ''))
            urdfTimer = setTimeout(pollUrdf, 1500);
    }
    catch (e) {
        $('#urdf-status').textContent = `Connection interrupted: ${errorMessage(e)}. Reconnect to resume this job.`;
    }
}
async function reconnectUrdf() {
    clearTimeout(urdfTimer);
    urdfCapability = null;
    renderUrdfSelection();
    try {
        const b = await urdfRequest('/api/urdf/capabilities', contract.capability);
        if (!b.available || !b.capability)
            throw Error('URDF export unavailable on this host.');
        urdfCapability = b.capability;
        $('#urdf-status').textContent = 'Ready to export the selected saved assembly.';
        if (urdfJob)
            await pollUrdf();
    }
    catch (e) {
        $('#urdf-status').textContent = errorMessage(e);
    }
    renderUrdfSelection();
}
$('#urdf-start').onclick = async () => {
    const assembly = selectedPath;
    if (!assembly || !urdfCapability)
        return;
    urdfBusy = true;
    renderUrdfSelection();
    try {
        const b = await urdfRequest('/api/urdf/jobs', contract.urdfStart, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Dparams-Capability': urdfCapability }, body: JSON.stringify({ assembly }) });
        const id = b.id || b.job_id;
        if (!id)
            throw Error('Server returned no job ID.');
        urdfJob = { ...b, id, assembly };
        showUrdfJob(urdfJob);
        await pollUrdf();
    }
    catch (e) {
        $('#urdf-status').textContent = errorMessage(e);
    }
    finally {
        urdfBusy = false;
        renderUrdfSelection();
    }
};
$('#urdf-cancel').onclick = async () => {
    if (!urdfJob || !urdfCapability)
        return;
    try {
        await urdfRequest(`/api/urdf/jobs/${encodeURIComponent(urdfJob.id)}/cancel`, contract.record, { method: 'POST', headers: { 'X-Dparams-Capability': urdfCapability } });
        $('#urdf-status').textContent = 'Cancellation requested…';
        await pollUrdf();
    }
    catch (e) {
        $('#urdf-status').textContent = `Cancel failed: ${errorMessage(e)}`;
    }
};
$('#urdf-reconnect').onclick = reconnectUrdf;
setInterval(() => {
    const scope = storageKey ? `urdf-job-v1:${location.origin}:${storageKey}` : null;
    if (scope === urdfScope)
        return;
    clearTimeout(urdfTimer);
    urdfScope = scope;
    urdfJob = null;
    try {
        const saved: UrdfJob | null = scope ? JSON.parse(localStorage.getItem(scope) || 'null') : null;
        if (scope && saved && typeof saved.id === 'string')
            urdfJob = saved;
    }
    catch {
    }
    reconnectUrdf();
}, 1000);
reconnectUrdf();
// Simulation viewport uses engine-reported link transforms, never CAD animation.
(() => {
    let capability: SimulationCapability | null = null;
    let session: SimulationSession | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let sceneId: string | null = null;
    interface SimulationView {
        scene: THREE.Scene;
        camera: THREE.PerspectiveCamera;
        renderer: THREE.WebGLRenderer;
        controls: OrbitControls;
        objects: Map<string, THREE.Group>;
    }
    let view: SimulationView | null = null;
    let pollGeneration = 0;
    const el = simulationElement, terminal = new Set(['stopped', 'failed', 'cancelled']);
    const headers = () => ({ 'X-Dparams-Capability': capability?.capability || '' });
    async function req<T>(url: string, guard: Guard<T>, options: RequestInit = {}): Promise<T> {
        return contract.jsonResponse(await fetch(url, {cache:'no-store', ...options}), guard);
    }
    function assemblies() {
        const select = el('assembly'), prev = select.value;
        select.replaceChildren();
        for (const f of files) {
            const o = document.createElement('option');
            o.value = f.path;
            o.textContent = f.path;
            select.append(o);
        }
        select.value = files.some(f => f.path === prev) ? prev : (selectedPath || select.options[0]?.value || '');
    }
    function buttons(status: SimulationStatus | null) {
        const s = status?.state, active = s === 'paused' || s === 'running';
        el('start').disabled = !capability?.available || !capability.backends?.[el('backend').value.toLowerCase()]?.supported || !!(session && !terminal.has(s || ''));
        for (const action of ['pause', 'resume', 'step', 'reset', 'stop', 'record'] as const)
            el(action).disabled = !active;
        el('pause').disabled = s !== 'running';
        el('resume').disabled = s !== 'paused';
        el('step').disabled = s !== 'paused';
        el('record').textContent = status?.recording ? 'Stop recording' : 'Start recording';
        el('set-joint').disabled = s !== 'paused' || !el('joint').options.length || !capability?.backends?.[session?.backend || '']?.commands?.includes('set_joint');
    }
    function closeView() {
        view?.controls.dispose();
        view?.renderer.dispose();
        view = null;
        el('view').replaceChildren();
    }
    function setupView(): SimulationView {
        closeView();
        const host = el('view');
        const renderer = new THREE.WebGLRenderer({ antialias: true });
        renderer.setSize(host.clientWidth || 320, 300);
        renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
        host.append(renderer.domElement);
        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0xe1e7e8);
        const camera = new THREE.PerspectiveCamera(40, (host.clientWidth || 320) / 300, .001, 1000);
        camera.up.set(0, 0, 1);
        camera.position.set(.8, -1, .7);
        scene.add(new THREE.HemisphereLight(0xffffff, 0x555566, 2));
        const light = new THREE.DirectionalLight(0xffffff, 2);
        light.position.set(1, -1, 2);
        scene.add(light);
        const controls = new OrbitControls(camera, renderer.domElement);
        controls.target.set(0, 0, .1);
        controls.update();
        const own: SimulationView = { renderer, scene, camera, controls, objects: new Map() };
        view = own;
        const loop = () => {
            if (view !== own)
                return;
            controls.update();
            renderer.render(scene, camera);
            requestAnimationFrame(loop);
        };
        loop();
        return own;
    }
    async function loadScene(manifest: SimulationScene, id: string, valid: () => boolean) {
        const own = setupView();
        const loader = new STLLoader();
        for (const link of manifest.links || []) {
            const group = new THREE.Group();
            group.visible = false;
            own.objects.set(link.id, group);
            own.scene.add(group);
            for (const xml of link.geometry || []) {
                const doc = new DOMParser().parseFromString(xml, 'application/xml'), visual = doc.documentElement, geo = visual.querySelector('geometry');
                if (!geo)
                    continue;
                const origin = visual.querySelector('origin'), g = new THREE.Group();
                const vec = (v: string | null | undefined, fallback: Vector3Tuple): Vector3Tuple => v ? v.trim().split(/\s+/).map(Number) as Vector3Tuple : fallback;
                g.position.fromArray(vec(origin?.getAttribute('xyz'), [0, 0, 0]));
                g.rotation.set(...vec(origin?.getAttribute('rpy'), [0, 0, 0]), 'ZYX');
                let geometry: THREE.BufferGeometry | null = null;
                const box = geo.querySelector('box'), sphere = geo.querySelector('sphere'), cylinder = geo.querySelector('cylinder'), mesh = geo.querySelector('mesh');
                if (box)
                    geometry = new THREE.BoxGeometry(...vec(box.getAttribute('size'), [1, 1, 1]));
                else if (sphere)
                    geometry = new THREE.SphereGeometry(Number(sphere.getAttribute('radius')), 20, 12);
                else if (cylinder) {
                    geometry = new THREE.CylinderGeometry(Number(cylinder.getAttribute('radius')), Number(cylinder.getAttribute('radius')), Number(cylinder.getAttribute('length')), 20);
                    geometry.rotateX(Math.PI / 2);
                }
                else if (mesh) {
                    const name = mesh.getAttribute('filename');
                    if (name && !name.includes('/'))
                        try {
                            geometry = await loader.loadAsync(`/api/simulation/sessions/${encodeURIComponent(id)}/mesh?name=${encodeURIComponent(name)}`);
                            geometry.scale(...vec(mesh.getAttribute('scale'), [1, 1, 1]));
                        }
                        catch {
                            el('view-status').textContent = `Could not load mesh ${name}.`;
                        }
                }
                if (!valid())
                    return;
                if (geometry) {
                    g.add(new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color: 0x4484a5, roughness: .7 })));
                    group.add(g);
                }
            }
        }
    }
    function poses(state: SimulationState) {
        let shown = 0;
        for (const pose of state.links || []) {
            const obj = view?.objects.get(pose.id);
            if (!obj || !Array.isArray(pose.position) || !Array.isArray(pose.quaternion))
                continue;
            obj.position.fromArray(pose.position);
            obj.quaternion.fromArray(pose.quaternion);
            obj.visible = true;
            shown++;
        }
        el('view-status').textContent = shown ? `Live engine poses: ${shown} links · t=${Number(state.time || 0).toFixed(2)} s` : 'No matching link poses received; viewport is not live.';
    }
    async function poll() {
        if (!session)
            return;
        clearTimeout(timer);
        const current = { ...session }, generation = ++pollGeneration;
        const valid = () => generation === pollGeneration && session?.id === current.id;
        try {
            const status = await req(`/api/simulation/sessions/${current.id}`, contract.simStatus);
            if (!valid())
                return;
            el('status').textContent = `${status.state || 'starting'} · ${current.backend}${status.error ? ' · ' + status.error : ''}`;
            buttons(status);
            if (['paused', 'running', 'stopped'].includes(status.state)) {
                if (sceneId !== current.id) {
                    const data = await req(`/api/simulation/sessions/${current.id}/scene`, contract.scene);
                    if (!valid())
                        return;
                    await loadScene(data, current.id, valid);
                    if (!valid())
                        return;
                    sceneId = current.id;
                }
                const state = await req(`/api/simulation/sessions/${current.id}/state`, contract.state);
                if (!valid())
                    return;
                poses(state);
                const joint = el('joint'), previous = joint.value, names = (state.joints || []).map(j => j.id).filter((id): id is string => typeof id === 'string' && !!id);
                if ([...joint.options].map(x => x.value).join('\0') !== names.join('\0')) {
                    joint.replaceChildren();
                    for (const name of names) {
                        const option = document.createElement('option');
                        option.value = name;
                        option.textContent = name;
                        joint.append(option);
                    }
                    if (names.includes(previous))
                        joint.value = previous;
                }
                el('set-joint').disabled = status.state !== 'paused' || !names.length || !capability?.backends?.[current.backend]?.commands?.includes('set_joint');
                el('telemetry').textContent = `Time: ${Number(state.time || 0).toFixed(3)} s · reset ${state.epoch}\nJoints: ${JSON.stringify(state.joints)}`;
                el('record').dataset.recording = status.recording ? 'yes' : 'no';
            }
            const recordings = await req(`/api/simulation/sessions/${current.id}/recordings`, contract.recordings);
            if (!valid())
                return;
            const list = el('recordings');
            list.replaceChildren();
            for (const name of recordings.recordings || []) {
                const li = document.createElement('li'), link = document.createElement('a');
                link.href = `/api/simulation/sessions/${current.id}/recordings/${encodeURIComponent(name)}`;
                link.textContent = `Download ${name}`;
                link.download = name;
                li.append(link);
                list.append(li);
            }
            if (!terminal.has(status.state))
                timer = setTimeout(poll, 200);
        }
        catch (e) {
            if (!valid())
                return;
            if (errorStatus(e) === 404) {
                session = null;
                sceneId = null;
                closeView();
                el('status').textContent = 'Session no longer exists. Start a new session.';
                buttons({ state: 'stopped' });
                return;
            }
            el('status').textContent = `Disconnected: ${errorMessage(e)} · retrying`;
            el('view-status').textContent = 'Disconnected; last pose frozen.';
            timer = setTimeout(poll, 2000);
        }
    }
    async function reconnect() {
        clearTimeout(timer);
        try {
            capability = await req('/api/simulation/capabilities', contract.simCapability);
            const history = await req('/api/simulation/sessions', contract.history);
            const recent = el('recent');
            recent.replaceChildren();
            for (const item of (history.sessions || []).slice(-10).reverse()) {
                const li = document.createElement('li'), button = document.createElement('button');
                button.type = 'button';
                button.textContent = `${item.backend} · ${item.assembly} · ${item.state}`;
                button.onclick = () => {
                    clearTimeout(timer);
                    session = { id: item.id, backend: item.backend, assembly: item.assembly };
                    sceneId = null;
                    poll();
                };
                li.append(button);
                recent.append(li);
            }
            const info = capability.backends?.[el('backend').value.toLowerCase()];
            el('capabilities').textContent = capability.available ? (info?.supported ? (info.reason || 'Available') : info?.reason || `Install ${info?.dependency || 'backend dependencies'}`) : 'Simulation worker unavailable';
            buttons(null);
            if (!session) {
                const active = (history.sessions || []).find(item => !terminal.has(item.state));
                if (active)
                    session = { id: active.id, backend: active.backend, assembly: active.assembly };
            }
            if (session)
                await poll();
        }
        catch (e) {
            el('capabilities').textContent = errorMessage(e);
        }
    }
    el('backend').onchange = reconnect;
    el('reconnect').onclick = reconnect;
    el('start').onclick = async () => {
        try {
            const backend = el('backend').value.toLowerCase(), assembly = el('assembly').value, r = await req('/api/simulation/sessions', contract.receipt, { method: 'POST', headers: { ...headers(), 'Content-Type': 'application/json' }, body: JSON.stringify({ backend, assembly }) });
            session = { id: r.id, backend, assembly };
            sceneId = null;
            await poll();
        }
        catch (e) {
            el('status').textContent = errorMessage(e);
        }
    };
    async function command(request: SimulationCommandRequest) {
        if (!session)
            return;
        const id = session.id;
        try {
            const sent = await req(`/api/simulation/sessions/${id}/commands`, contract.receipt, { method: 'POST', headers: { ...headers(), 'Content-Type': 'application/json' }, body: JSON.stringify(request) });
            const deadline = Date.now() + 10000;
            let ack: CommandAcknowledgement | null = null;
            while (Date.now() < deadline && session?.id === id) {
                try {
                    ack = await req(`/api/simulation/sessions/${id}/commands/${sent.id}`, contract.acknowledgement);
                    if (ack.status !== 'processing')
                        break;
                }
                catch (e) {
                    if (errorStatus(e) !== 404)
                        throw e;
                }
                await new Promise(resolve => setTimeout(resolve, 100));
            }
            if (session?.id !== id)
                return;
            if (!ack || ack.status === 'processing')
                throw Error('Command outcome not confirmed; inspect session status before retrying.');
            if (ack.status !== 'applied')
                throw Error(ack.error || `Command ${ack.status}`);
            clearTimeout(timer);
            await poll();
        }
        catch (e) {
            if (session?.id === id)
                el('status').textContent = errorMessage(e);
        }
    }
    el('set-joint').onclick = () => {
        const position = el('position').valueAsNumber;
        if (Number.isFinite(position))
            command({ command: 'set_joint', joint: el('joint').value, position });
        else
            el('status').textContent = 'Enter a finite joint position.';
    };
    for (const action of ['pause', 'resume', 'step', 'reset', 'stop'] as const)
        el(action).onclick = () => command({ command: action });
    el('record').onclick = () => command({ command: el('record').dataset.recording === 'yes' ? 'record_stop' : 'record_start' });
    new MutationObserver(assemblies).observe($('#cad-list'), { childList: true, subtree: true });
    assemblies();
    reconnect();
})();
