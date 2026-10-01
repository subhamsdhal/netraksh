export const MAX_VISIBLE_CAMERAS = 2;

export function selectCameraSlots(cameraIds = [], savedSlots = []) {
  const available = Array.from(new Set(cameraIds.filter(Boolean)));
  if (Array.isArray(savedSlots) && savedSlots.length === MAX_VISIBLE_CAMERAS) {
    const explicit = savedSlots.map((id) => (id && available.includes(id) ? id : null));
    if (explicit.some(Boolean) || savedSlots.every((id) => !id)) return explicit;
  }
  const selected = savedSlots.filter((id, index, list) => id && available.includes(id) && list.indexOf(id) === index);
  const ordered = [...selected, ...available].filter((id, index, list) => list.indexOf(id) === index);
  return Array.from({ length: MAX_VISIBLE_CAMERAS }, (_, index) => ordered[index] || null);
}

export function cameraDisplayMetadata(camera, slotIndex) {
  if (!camera) return { name: `Camera slot ${slotIndex + 1}`, location: 'Location not registered' };
  return {
    name: camera.name || camera.friendlyName || camera.camera_id || camera.cameraId,
    location: camera.location || 'Location not registered',
  };
}
