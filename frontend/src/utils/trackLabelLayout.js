const intersects = (a, b) => (
  a.left < b.left + b.width
  && a.left + a.width > b.left
  && a.top < b.top + b.height
  && a.top + a.height > b.top
);

/** Place track labels inside the visible video area without changing track IDs. */
export function trackLabelPosition(box, label, frame, occupied = []) {
  const width = Math.min(frame.width, Math.max(1, label.width));
  const height = Math.max(1, label.height);
  const maxLeft = frame.left + frame.width - width;
  const maxTop = frame.top + frame.height - height;
  const left = Math.min(maxLeft, Math.max(frame.left, box.left));
  const gap = 2;
  const step = height + gap;
  const candidates = [];

  for (let row = 0; row <= occupied.length + 2; row += 1) {
    const above = box.top - height - row * step;
    const below = box.top + box.height + row * step;
    if (above >= frame.top) candidates.push({ left, top: above, width, height });
    if (below <= maxTop) candidates.push({ left, top: below, width, height });
  }

  const primary = { left, top: Math.max(frame.top, box.top - height), width, height };
  candidates.unshift(primary);
  const free = candidates.find(candidate => !occupied.some(other => intersects(candidate, other)));
  if (free) return free;

  // Dense groups can exhaust the nearby rows. Continue upward within the frame
  // and choose the first free slot; the label remains anchored to its real box.
  for (let top = maxTop; top >= frame.top; top -= step) {
    const candidate = { left, top, width, height };
    if (!occupied.some(other => intersects(candidate, other))) return candidate;
  }
  return primary;
}
