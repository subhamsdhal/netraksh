export const MAX_VISIBLE_CAMERAS = 2;

export const DEMO_CAMERA_LABELS = {
  'cam-border-01': { name: 'Border Gate / Check Post', location: 'Border Gate' },
  'cam-checkpoint-01': { name: 'Restricted Perimeter', location: 'Restricted Perimeter' },
};

export function selectDemoCameraSlots(cameraIds = [], savedSlots = []) {
  const available = Array.from(new Set(cameraIds.filter(Boolean)));
  // A two-item saved selection is authoritative, including explicit empty
  // slots. This lets the operator run Camera 1 only (or Camera 2 only)
  // without the helper silently refilling the other slot.
  if (Array.isArray(savedSlots) && savedSlots.length === MAX_VISIBLE_CAMERAS) {
    const explicit = savedSlots.map((id) => (id && available.includes(id) ? id : null));
    if (explicit.some(Boolean) || savedSlots.every((id) => !id)) return explicit;
  }
  const selected = savedSlots.filter((id, index, list) => id && available.includes(id) && list.indexOf(id) === index);
  const preferred = ['cam-border-01', 'cam-checkpoint-01'].filter((id) => available.includes(id));
  if (preferred.length === MAX_VISIBLE_CAMERAS && selected.some((id) => preferred.includes(id))) return preferred;
  const ordered = [...selected, ...preferred, ...available].filter((id, index, list) => list.indexOf(id) === index);
  return Array.from({ length: MAX_VISIBLE_CAMERAS }, (_, index) => ordered[index] || null);
}
