export function buildAnalyticsCsv(summary, timeseries, byType, byCamera, bySeverity) {
  const lines = ['NETRAKSH Analytics Export'];
  lines.push(`Window: ${summary?.window?.since ?? ''} to ${summary?.window?.until ?? ''}`);
  lines.push('Scope: selected time window and filters');
  lines.push('');

  lines.push('=== Summary ===');
  lines.push(`Total Event Records,${summary?.events?.raw_total ?? ''}`);
  lines.push(`Detected,${summary?.events?.detected ?? ''}`);
  lines.push(`ABSTAIN,${summary?.events?.abstain ?? ''}`);
  lines.push(`Detection Rate,${summary?.events?.detection_rate_pct ?? ''}`);
  lines.push(`Total Alerts,${summary?.alerts?.total ?? ''}`);
  lines.push(`Acknowledged,${summary?.alerts?.acknowledged ?? ''}`);
  lines.push(`Unresolved,${summary?.alerts?.unresolved ?? ''}`);
  lines.push(`Closed,${summary?.alerts?.closed ?? ''}`);
  lines.push(`Watchlist Matches,${summary?.events?.watchlist_matches ?? ''}`);
  lines.push(`ANPR Events,${summary?.events?.anpr ?? ''}`);
  lines.push(`Intrusion Events,${summary?.events?.intrusion ?? ''}`);
  lines.push(`Vehicle Events,${summary?.events?.vehicle ?? ''}`);
  lines.push(`Person Events,${summary?.events?.person ?? ''}`);
  lines.push(`Verified Event Packages,${summary?.events?.verified_packages ?? ''}`);
  lines.push(`Average Reliability (Computed Rows),${summary?.events?.reliability?.average ?? ''}`);
  lines.push(`Average Detection Confidence,${summary?.events?.confidence?.average ?? ''}`);
  lines.push(`Cameras With Events,${summary?.cameras?.with_events ?? ''}`);
  lines.push('Uptime,Not available (see Performance page)');
  lines.push('');

  lines.push('=== Detected Event Timeseries ===');
  lines.push('Bucket,Detected,Watchlist,Intrusion,Vehicle,Person');
  (timeseries?.series ?? []).forEach((row) =>
    lines.push(`${row.bucket},${row.total},${row.watchlist},${row.intrusion},${row.vehicle},${row.person}`)
  );
  lines.push('');

  lines.push('=== Detected Events By Type ===');
  lines.push('Event Type,Count');
  (byType?.by_type ?? []).forEach((row) => lines.push(`${row.event_type},${row.count}`));
  lines.push('');

  lines.push('=== Detected Events By Camera ===');
  lines.push('Camera ID,Camera Name,Count');
  (byCamera?.by_camera ?? []).forEach((row) =>
    lines.push(`${row.camera_id},${row.camera_name},${row.count}`)
  );
  lines.push('');

  lines.push('=== Detected Events By Severity ===');
  lines.push('Severity,Count');
  (bySeverity?.by_severity ?? []).forEach((row) => lines.push(`${row.severity},${row.count}`));

  return lines.join('\n');
}
