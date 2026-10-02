import { describe, expect, it } from 'vitest';
import {
  alertsPageSubtitle,
  isCorroboratedAlert,
  isCrossCommandEscalation,
  totalRecordedAlerts,
} from '../src/utils/alertTruth';

describe('alerts page truth labels', () => {
  it('labels the collection as recorded security alerts when corroboration is available', () => {
    expect(alertsPageSubtitle({ corroboration: { temporal_spatial: true } })).toBe(
      'Recorded security alerts · Corroboration capability available',
    );
  });

  it('does not imply corroboration capability when it is disabled or unavailable', () => {
    expect(alertsPageSubtitle({ corroboration: { temporal_spatial: false } })).toBe(
      'Recorded security alerts',
    );
    expect(alertsPageSubtitle(null)).toBe('Recorded security alerts');
  });

  it('does not classify a non-cross-command alert as an escalation', () => {
    expect(isCrossCommandEscalation({ crosses_jurisdiction_boundary: false })).toBe(false);
    expect(isCrossCommandEscalation({ crosses_jurisdiction_boundary: 'false' })).toBe(false);
  });

  it('classifies an alert as cross-command only when the flag is exactly true', () => {
    expect(isCrossCommandEscalation({ crosses_jurisdiction_boundary: true })).toBe(true);
  });

  it('does not classify a non-corroborated alert as multi-camera corroborated', () => {
    expect(isCorroboratedAlert({ escalated_via_corroboration: false })).toBe(false);
    expect(isCorroboratedAlert({ escalated_via_corroboration: 'false' })).toBe(false);
  });

  it('classifies an alert as corroborated only when the flag is exactly true', () => {
    expect(isCorroboratedAlert({ escalated_via_corroboration: true })).toBe(true);
  });

  it('derives the total from the actual alert collection', () => {
    const alerts = Array.from({ length: 6 }, (_, index) => ({ alert_id: `alert-${index}` }));

    expect(totalRecordedAlerts(alerts)).toBe(6);
    expect(totalRecordedAlerts(alerts.slice(0, 4))).toBe(4);
    expect(totalRecordedAlerts(undefined)).toBe(0);
  });
});
