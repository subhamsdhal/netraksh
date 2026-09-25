// Every datetime this backend emits (Event.timestamp, Alert.created_at,
// CameraHealth.timestamp, etc.) comes back as a naive ISO string with no
// UTC marker — e.g. "2026-09-05T05:21:00", not "...05:21:00Z" — even for
// fields the client originally sent WITH a "Z" suffix. SQLAlchemy `DateTime`
// columns store/return naive Python datetimes regardless of the input's
// timezone info, and Pydantic doesn't add one back when serializing a naive
// datetime to JSON.
//
// Every timestamp in this app is UTC by convention (every existing display
// already labels it "UTC") — but `new Date(str)` on a string with no
// timezone marker is parsed as LOCAL time by the browser's own JS engine.
// For any viewer not themselves in UTC+0 (IST, UTC+5:30, included — this is
// an India-based project), that silently shifts every displayed and
// elapsed time by that viewer's own UTC offset.
//
// Confirmed live, not hypothetical: a demo alert created moments earlier
// showed "T - 330 MINS" elapsed instead of ~1 minute. 330 minutes is
// exactly the IST UTC offset (5:30).
//
// This fixes it at the point every raw backend timestamp string becomes a
// JS Date, without touching the backend's DB layer (SQLAlchemy column
// types, migrations) — a much larger, riskier change for the same result,
// given this app's convention already treats every stored timestamp as UTC.
export function parseUtc(dateStr) {
  if (!dateStr) return null;
  const hasTimezoneMarker = /[zZ]|[+-]\d{2}:\d{2}$/.test(dateStr);
  return new Date(hasTimezoneMarker ? dateStr : `${dateStr}Z`);
}
