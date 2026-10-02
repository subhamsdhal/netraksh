const BASE_ALERTS_SUBTITLE = 'Recorded security alerts';

export function alertsPageSubtitle(capabilities) {
  return capabilities?.corroboration?.temporal_spatial === true
    ? `${BASE_ALERTS_SUBTITLE} · Corroboration capability available`
    : BASE_ALERTS_SUBTITLE;
}

export function isCrossCommandEscalation(alert) {
  return alert?.crosses_jurisdiction_boundary === true;
}

export function isCorroboratedAlert(alert) {
  return alert?.escalated_via_corroboration === true;
}

export function totalRecordedAlerts(alerts) {
  return Array.isArray(alerts) ? alerts.length : 0;
}
