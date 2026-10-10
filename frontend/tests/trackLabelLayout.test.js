import { describe, expect, it } from 'vitest';
import { trackLabelPosition } from '../src/utils/trackLabelLayout';

const frame = { left: 20, top: 10, width: 640, height: 360 };
const label = { width: 112, height: 13 };

describe('track label layout', () => {
  it('keeps labels inside the visible source frame', () => {
    const position = trackLabelPosition({ left: 630, top: 10, width: 20, height: 50 }, label, frame);
    expect(position.left + position.width).toBeLessThanOrEqual(frame.left + frame.width);
    expect(position.top).toBeGreaterThanOrEqual(frame.top);
  });

  it('moves colliding labels to a clear row without changing box identity', () => {
    const box = { left: 250, top: 100, width: 30, height: 80 };
    const first = trackLabelPosition(box, label, frame);
    const second = trackLabelPosition(box, label, frame, [first]);
    expect(second).not.toEqual(first);
    expect(second.left).toBe(first.left);
    expect(second.top).not.toBe(first.top);
    expect(second.left + second.width).toBeLessThanOrEqual(frame.left + frame.width);
  });
});
