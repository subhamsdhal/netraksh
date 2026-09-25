import { describe, expect, it } from 'vitest';
import { MAX_VISIBLE_CAMERAS, selectDemoCameraSlots } from '../src/utils/demoCameraSlots';

describe('SIH two-camera presentation slots', () => {
  it('caps the presentation surface at two real backend camera ids', () => {
    expect(MAX_VISIBLE_CAMERAS).toBe(2);
    expect(selectDemoCameraSlots(['cam-border-01', 'cam-checkpoint-01', 'cam-extra-01'])).toEqual(['cam-border-01', 'cam-checkpoint-01']);
  });

  it('preserves valid operator selections and does not invent unavailable cameras', () => {
    expect(selectDemoCameraSlots(['cam-extra-01'], ['cam-extra-01', 'missing-camera'])).toEqual(['cam-extra-01', null]);
  });

  it('preserves an explicit empty second slot for one-camera mode', () => {
    expect(selectDemoCameraSlots(['cam-border-01', 'cam-checkpoint-01'], ['cam-border-01', null])).toEqual(['cam-border-01', null]);
    expect(selectDemoCameraSlots(['cam-border-01', 'cam-checkpoint-01'], [null, 'cam-checkpoint-01'])).toEqual([null, 'cam-checkpoint-01']);
  });
});
