import { describe, expect, it } from 'vitest';
import { MAX_VISIBLE_CAMERAS, selectCameraSlots } from '../src/utils/cameraSlots';

describe('two-camera presentation slots', () => {
  it('caps the presentation surface at two real backend camera ids', () => {
    expect(MAX_VISIBLE_CAMERAS).toBe(2);
    expect(selectCameraSlots(['cam-border-01', 'cam-checkpoint-01', 'cam-extra-01'])).toEqual(['cam-border-01', 'cam-checkpoint-01']);
  });

  it('preserves valid operator selections and does not invent unavailable cameras', () => {
    expect(selectCameraSlots(['cam-extra-01'], ['cam-extra-01', 'missing-camera'])).toEqual(['cam-extra-01', null]);
  });

  it('preserves an explicit empty second slot for one-camera mode', () => {
    expect(selectCameraSlots(['cam-border-01', 'cam-checkpoint-01'], ['cam-border-01', null])).toEqual(['cam-border-01', null]);
    expect(selectCameraSlots(['cam-border-01', 'cam-checkpoint-01'], [null, 'cam-checkpoint-01'])).toEqual([null, 'cam-checkpoint-01']);
  });
});
