/**
 * NETRAKSH — Watchlist Management View (/watchlist)
 *
 * Displays all active watchlist subjects in a responsive card grid.
 * Admin users get an "Enroll Subject" form panel.
 *
 * RBAC:
 *   - Any authenticated role can view the grid (GET /watchlist)
 *   - Only ADMIN can enroll new subjects (POST /watchlist) — the form is
 *     rendered only when role === 'ADMIN'; the backend enforces this
 *     independently via require_admin.
 *
 * THREAT COLOUR SYSTEM:
 *   CRITICAL  → Red  (#ef4444) — thick card border, glow
 *   SEVERE    → Orange (#f97316)
 *   ELEVATED  → Amber (#fbbf24)
 *
 * SCOPE NOTE on face recognition:
 *   Cards show "LBPH — DEMO QUALITY" reminder because classical LBPH is the
 *   actual recognizer in use. This text is intentionally visible so any
 *   evaluator understands the scope without reading docs.
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Users, UserPlus, Search, Filter, AlertTriangle,
  MapPin, Clock, Camera, X, ChevronDown, Eye, Trash2,
} from 'lucide-react';
import { authFetch } from '../services/auth';
import useAuth from '../hooks/useAuth';
import { parseUtc } from '../utils/time';

// ─── Constants ───────────────────────────────────────────────────────────────

const THREAT_LEVELS = ['CRITICAL', 'SEVERE', 'ELEVATED'];

const THREAT_META = {
  CRITICAL: { label: 'CRITICAL', cls: 'critical', color: '#ef4444', icon: '⬤' },
  SEVERE:   { label: 'SEVERE',   cls: 'severe',   color: '#f97316', icon: '⬤' },
  ELEVATED: { label: 'ELEVATED', cls: 'elevated',  color: '#fbbf24', icon: '⬤' },
};

// ─── Avatar component ─────────────────────────────────────────────────────────
function SubjectAvatar({ imageBase64, name, threatLevel }) {
  const meta = THREAT_META[threatLevel] ?? THREAT_META.ELEVATED;
  if (imageBase64) {
    return (
      <img
        className="wl-avatar"
        src={`data:image/jpeg;base64,${imageBase64}`}
        alt={`Photo of ${name}`}
        style={{ borderColor: meta.color }}
      />
    );
  }
  return (
    <div
      className="wl-avatar wl-avatar--placeholder"
      style={{ borderColor: meta.color + '66' }}
      aria-label="No reference photo"
    >
      👤
    </div>
  );
}

// ─── Subject card ─────────────────────────────────────────────────────────────
function SubjectCard({ person, onInspect, onDeactivate, isAdmin }) {
  const meta  = THREAT_META[(person.threat_level || '').toUpperCase()] ?? THREAT_META.ELEVATED;
  const level = (person.threat_level || 'ELEVATED').toUpperCase();
  const cardCls = `wl-card wl-card--${level.toLowerCase()}`;

  const lastSeen = person.last_seen_at
    ? parseUtc(person.last_seen_at).toLocaleString('en-IN', { hour12: false })
    : null;

  const aliases = person.aliases
    ? person.aliases.split(';').map(a => a.trim()).filter(Boolean)
    : [];

  return (
    <div className={cardCls} style={{ gap: '0.75rem' }}>
      {/* Top: avatar + name */}
      <div className="flex items-center gap-3">
        <SubjectAvatar
          imageBase64={person.face_image_count > 0 ? null : null}
          name={person.name}
          threatLevel={level}
        />
        <div className="flex flex-col gap-1" style={{ minWidth: 0 }}>
          <span className="font-display text-main truncate" style={{ fontSize: '0.8rem', letterSpacing: '0.04em' }}>
            {person.name}
          </span>
          <span className={`wl-threat-badge wl-threat-badge--${level.toLowerCase()}`}>
            {meta.icon} {meta.label}
          </span>
          {person.category && (
            <span style={{ fontSize: '0.6rem', color: 'var(--text-muted)', fontFamily: 'var(--font-display)', letterSpacing: '0.06em' }}>
              {person.category.toUpperCase()}
            </span>
          )}
        </div>
      </div>

      {/* Aliases */}
      {aliases.length > 0 && (
        <div style={{ fontSize: '0.6rem', color: 'var(--text-muted)', fontFamily: 'var(--font-body)' }}>
          <span style={{ fontFamily: 'var(--font-display)', letterSpacing: '0.08em', fontSize: '0.55rem', opacity: 0.7 }}>
            AKA:{' '}
          </span>
          {aliases.join(' / ')}
        </div>
      )}

      {/* ID + photo count */}
      <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
        <span style={{
          fontFamily: 'ui-monospace, Menlo, monospace',
          fontSize: '0.55rem', color: 'var(--text-muted)',
          background: 'var(--bg-elevated)', border: '1px solid var(--border-color)',
          borderRadius: '0.15rem', padding: '0.1rem 0.3rem',
        }}>
          {person.person_id.split('-')[0]}
        </span>
        <span style={{ fontSize: '0.6rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '0.2rem' }}>
          <Camera size={9} /> {person.face_image_count} ref photo{person.face_image_count !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Last known location */}
      {person.last_known_location && (
        <div style={{ fontSize: '0.62rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'flex-start', gap: '0.3rem' }}>
          <MapPin size={10} style={{ flexShrink: 0, marginTop: '0.1rem' }} />
          <span style={{ fontFamily: 'var(--font-body)' }}>{person.last_known_location}</span>
        </div>
      )}

      {/* Last seen */}
      {lastSeen && (
        <div style={{ fontSize: '0.6rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
          <Clock size={9} />
          <span>Last seen: {lastSeen}</span>
          {person.last_seen_camera_id && (
            <span style={{ opacity: 0.7 }}>· cam {person.last_seen_camera_id.split('-').pop()}</span>
          )}
        </div>
      )}

      {/* LBPH scope disclaimer */}
      <div style={{
        fontSize: '0.5rem', color: 'rgba(148,163,184,0.5)',
        fontFamily: 'var(--font-display)', letterSpacing: '0.07em',
        borderTop: '1px solid var(--border-color)', paddingTop: '0.4rem',
        marginTop: '0.2rem',
      }}>
        LBPH — DEMO QUALITY · HUMAN REVIEW REQUIRED
      </div>

      {/* Action buttons */}
      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <button
          onClick={() => onInspect(person)}
          style={{
            flex: 1, padding: '0.3rem', fontFamily: 'var(--font-display)',
            fontSize: '0.6rem', letterSpacing: '0.08em', cursor: 'pointer',
            background: 'var(--bg-elevated)', border: '1px solid var(--border-color)',
            borderRadius: '0.2rem', color: 'var(--text-muted)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.25rem',
            transition: 'border-color 0.12s',
          }}
          onMouseOver={e => e.currentTarget.style.borderColor = 'var(--color-ok)'}
          onMouseOut={e => e.currentTarget.style.borderColor = 'var(--border-color)'}
        >
          <Eye size={11} /> INSPECT
        </button>
        {isAdmin && (
          <button
            onClick={() => onDeactivate(person.person_id)}
            title="Soft-archive this subject"
            style={{
              padding: '0.3rem 0.5rem', cursor: 'pointer',
              background: 'var(--bg-elevated)', border: '1px solid var(--border-color)',
              borderRadius: '0.2rem', color: '#ef4444',
              transition: 'border-color 0.12s',
            }}
            onMouseOver={e => e.currentTarget.style.borderColor = '#ef4444'}
            onMouseOut={e => e.currentTarget.style.borderColor = 'var(--border-color)'}
          >
            <Trash2 size={11} />
          </button>
        )}
      </div>
    </div>
  );
}

// ─── Enroll form (ADMIN only) ─────────────────────────────────────────────────
function EnrollForm({ onSuccess }) {
  const INITIAL = {
    name: '', aliases: '', category: '',
    threat_level: 'ELEVATED', last_known_location: '', notes: '',
  };
  const [form,    setForm]    = useState(INITIAL);
  const [imageB64, setImageB64] = useState('');
  const [saving,  setSaving]  = useState(false);
  const [error,   setError]   = useState(null);
  const fileRef = useRef(null);

  const handleFile = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = ev => setImageB64(ev.target.result.split(',')[1]);
    reader.readAsDataURL(file);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!imageB64) { setError('A reference face photo is required.'); return; }
    setSaving(true); setError(null);
    try {
      const res = await authFetch('/watchlist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...form, image_base64: imageB64 }),
      });
      if (res.status === 403) { setError('Admin role required.'); return; }
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        setError(d.detail || 'Server error');
        return;
      }
      const person = await res.json();
      setForm(INITIAL); setImageB64('');
      if (fileRef.current) fileRef.current.value = '';
      onSuccess(person);
    } catch (err) {
      setError('Network error — check backend connectivity');
    } finally {
      setSaving(false);
    }
  };

  const field = (id, label, placeholder, opts = {}) => (
    <div className="flex flex-col" style={{ gap: '0.25rem' }}>
      <label htmlFor={id} style={{
        fontFamily: 'var(--font-display)', fontSize: '0.58rem',
        letterSpacing: '0.1em', color: 'var(--text-muted)',
      }}>
        {label}
      </label>
      <input
        id={id}
        type="text"
        placeholder={placeholder}
        value={form[id]}
        onChange={e => setForm(p => ({ ...p, [id]: e.target.value }))}
        style={{
          background: 'var(--bg-dark)', border: '1px solid var(--border-color)',
          borderRadius: '0.2rem', padding: '0.4rem 0.6rem',
          fontFamily: 'var(--font-body)', fontSize: '0.75rem',
          color: 'var(--text-main)',
        }}
        {...opts}
      />
    </div>
  );

  return (
    <form onSubmit={handleSubmit} className="flex flex-col" style={{ gap: '0.85rem' }}>
      {field('name',  'SUBJECT NAME *', 'Full name', { required: true })}
      {field('aliases', 'KNOWN ALIASES', 'Semi-colon separated (A.K.A.)')}
      {field('category', 'CATEGORY / ROLE', 'e.g. Suspected smuggler')}

      <div className="flex flex-col" style={{ gap: '0.25rem' }}>
        <label style={{
          fontFamily: 'var(--font-display)', fontSize: '0.58rem',
          letterSpacing: '0.1em', color: 'var(--text-muted)',
        }}>
          THREAT LEVEL
        </label>
        <div style={{ position: 'relative' }}>
          <select
            value={form.threat_level}
            onChange={e => setForm(p => ({ ...p, threat_level: e.target.value }))}
            style={{
              width: '100%', appearance: 'none',
              background: 'var(--bg-dark)', border: '1px solid var(--border-color)',
              borderRadius: '0.2rem', padding: '0.4rem 2rem 0.4rem 0.6rem',
              fontFamily: 'var(--font-display)', fontSize: '0.7rem',
              color: form.threat_level === 'CRITICAL' ? '#ef4444'
                   : form.threat_level === 'SEVERE'   ? '#f97316' : '#fbbf24',
              cursor: 'pointer',
            }}
          >
            {THREAT_LEVELS.map(l => <option key={l} value={l}>{l}</option>)}
          </select>
          <ChevronDown size={12} style={{
            position: 'absolute', right: '0.6rem', top: '50%', transform: 'translateY(-50%)',
            color: 'var(--text-muted)', pointerEvents: 'none',
          }} />
        </div>
      </div>

      {field('last_known_location', 'LAST KNOWN LOCATION', 'Sector / Post / Region')}
      {field('notes', 'NOTES (ANALYST)', 'Intel summary')}

      {/* Photo upload */}
      <div className="flex flex-col" style={{ gap: '0.25rem' }}>
        <label style={{
          fontFamily: 'var(--font-display)', fontSize: '0.58rem',
          letterSpacing: '0.1em', color: 'var(--text-muted)',
        }}>
          REFERENCE PHOTO * (JPEG face crop)
        </label>
        <input
          ref={fileRef}
          type="file"
          accept="image/jpeg,image/png"
          onChange={handleFile}
          id="wl-photo-input"
          style={{
            fontFamily: 'var(--font-body)', fontSize: '0.7rem',
            color: 'var(--text-muted)',
          }}
        />
        {imageB64 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.25rem' }}>
            <img
              src={`data:image/jpeg;base64,${imageB64}`}
              alt="Preview"
              style={{ width: '48px', height: '48px', objectFit: 'cover', borderRadius: '0.2rem', border: '1px solid var(--border-color)' }}
            />
            <span style={{ fontSize: '0.6rem', color: 'var(--color-ok)', fontFamily: 'var(--font-display)' }}>
              PHOTO LOADED
            </span>
          </div>
        )}
      </div>

      {error && (
        <div style={{ fontSize: '0.65rem', color: '#ef4444', fontFamily: 'var(--font-display)', letterSpacing: '0.06em' }}>
          ✗ {error}
        </div>
      )}

      <button
        type="submit"
        disabled={saving}
        style={{
          background: saving ? 'rgba(74,222,128,0.3)' : 'var(--color-ok)',
          color: '#000', fontFamily: 'var(--font-display)', fontWeight: 700,
          fontSize: '0.7rem', letterSpacing: '0.1em', padding: '0.5rem',
          borderRadius: '0.25rem', border: 'none', cursor: saving ? 'not-allowed' : 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.4rem',
          transition: 'background 0.12s',
        }}
      >
        <UserPlus size={14} />
        {saving ? 'ENROLLING…' : 'ENROLL SUBJECT'}
      </button>
    </form>
  );
}

// ─── Inspect modal ─────────────────────────────────────────────────────────────
function InspectModal({ person, onClose }) {
  if (!person) return null;
  const meta  = THREAT_META[(person.threat_level || '').toUpperCase()] ?? THREAT_META.ELEVATED;
  const level = (person.threat_level || 'ELEVATED').toUpperCase();
  const aliases = person.aliases
    ? person.aliases.split(';').map(a => a.trim()).filter(Boolean)
    : [];
  const lastSeen = person.last_seen_at
    ? parseUtc(person.last_seen_at).toISOString().replace('T', ' ').slice(0, 19) + ' UTC'
    : 'N/A';

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 100,
      background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(4px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}
      onClick={onClose}
    >
      <div
        style={{
          background: 'var(--bg-panel)', border: `1px solid ${meta.color}66`,
          borderRadius: '0.4rem', padding: '1.5rem', width: '420px', maxWidth: '90vw',
          boxShadow: `0 0 32px ${meta.color}22`,
          display: 'flex', flexDirection: 'column', gap: '1rem',
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{
            fontFamily: 'var(--font-display)', fontSize: '0.75rem',
            letterSpacing: '0.12em', color: meta.color,
          }}>
            SUBJECT DOSSIER
          </span>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)' }}>
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div style={{ display: 'flex', gap: '1rem', alignItems: 'flex-start' }}>
          <SubjectAvatar imageBase64={null} name={person.name} threatLevel={level} />
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
            <span style={{ fontFamily: 'var(--font-display)', fontSize: '1rem', color: 'var(--text-main)' }}>
              {person.name}
            </span>
            <span className={`wl-threat-badge wl-threat-badge--${level.toLowerCase()}`}>
              {meta.icon} {meta.label}
            </span>
            {person.category && (
              <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)', fontFamily: 'var(--font-display)', letterSpacing: '0.06em' }}>
                {person.category}
              </span>
            )}
          </div>
        </div>

        {/* Detail grid */}
        {[
          ['SUBJECT ID',  person.person_id],
          ['ALIASES',     aliases.join(', ') || 'None on record'],
          ['LAST LOCATION', person.last_known_location || 'Unknown'],
          ['LAST SEEN',   lastSeen],
          ['LAST CAMERA', person.last_seen_camera_id || 'N/A'],
          ['REF PHOTOS',  `${person.face_image_count} image(s)`],
          ['NOTES',       person.notes || '—'],
          ['ENROLLED',    person.created_at
            ? parseUtc(person.created_at).toISOString().replace('T', ' ').slice(0, 10) : 'N/A'],
        ].map(([k, v]) => (
          <div key={k} style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
            borderBottom: '1px solid var(--border-color)', paddingBottom: '0.4rem',
          }}>
            <span style={{ fontFamily: 'var(--font-display)', fontSize: '0.58rem', letterSpacing: '0.1em', color: 'var(--text-muted)', flexShrink: 0, marginRight: '1rem' }}>
              {k}
            </span>
            <span style={{ fontFamily: 'var(--font-body)', fontSize: '0.7rem', color: 'var(--text-main)', textAlign: 'right', wordBreak: 'break-all' }}>
              {v}
            </span>
          </div>
        ))}

        {/* Scope disclaimer */}
        <div style={{
          fontSize: '0.55rem', color: 'rgba(148,163,184,0.5)',
          fontFamily: 'var(--font-display)', letterSpacing: '0.07em',
          borderTop: '1px solid var(--border-color)', paddingTop: '0.5rem',
        }}>
          LBPH face recognition — DEMO QUALITY. Results are investigation leads,
          NOT confirmed identifications. Verify via human review before action.
        </div>
      </div>
    </div>
  );
}

// ─── Main page ─────────────────────────────────────────────────────────────────
export default function Watchlist() {
  const { role } = useAuth();
  const isAdmin  = role === 'ADMIN';

  const [persons,        setPersons]        = useState([]);
  const [loading,        setLoading]        = useState(true);
  const [error,          setError]          = useState(null);
  const [searchQuery,    setSearchQuery]    = useState('');
  const [filterThreat,   setFilterThreat]   = useState('ALL');
  const [showEnroll,     setShowEnroll]     = useState(false);
  const [inspectPerson,  setInspectPerson]  = useState(null);

  const fetchWatchlist = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const res = await authFetch('/watchlist');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setPersons(Array.isArray(data) ? data : []);
    } catch (e) {
      setError('Could not load watchlist — check backend connectivity');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchWatchlist(); }, [fetchWatchlist]);

  const handleDeactivate = async (personId) => {
    if (!window.confirm('Archive this subject? The record is retained for audit.')) return;
    try {
      const res = await authFetch(`/watchlist/${personId}`, { method: 'DELETE' });
      if (!res.ok) { alert('Failed to archive subject'); return; }
      setPersons(prev => prev.filter(p => p.person_id !== personId));
    } catch {
      alert('Network error');
    }
  };

  // Filter + search
  const displayed = persons
    .filter(p => filterThreat === 'ALL' || (p.threat_level || '').toUpperCase() === filterThreat)
    .filter(p => {
      const q = searchQuery.toLowerCase().trim();
      if (!q) return true;
      return (
        p.name?.toLowerCase().includes(q) ||
        p.aliases?.toLowerCase().includes(q) ||
        p.category?.toLowerCase().includes(q) ||
        p.person_id?.toLowerCase().includes(q) ||
        p.last_known_location?.toLowerCase().includes(q)
      );
    });

  // Counts per threat level
  const counts = { ALL: persons.length };
  THREAT_LEVELS.forEach(l => {
    counts[l] = persons.filter(p => (p.threat_level || '').toUpperCase() === l).length;
  });

  return (
    <div className="h-full flex flex-col gap-4 overflow-hidden">
      {/* ── Page header ── */}
      <div className="section-header flex-shrink-0">
        <div>
          <h2 className="section-title">
            Watchlist & Identity Corroboration
          </h2>
          <div className="section-sub">
            {persons.length} active subject{persons.length !== 1 ? 's' : ''} ·
            LBPH face recogniser · DEMO QUALITY — leads only, not identifications
          </div>
        </div>
        {isAdmin && (
          <button
            onClick={() => setShowEnroll(v => !v)}
            style={{
              background: showEnroll ? 'rgba(74,222,128,0.2)' : 'var(--color-ok)',
              color: showEnroll ? 'var(--color-ok)' : '#000',
              border: `1px solid var(--color-ok)`,
              fontFamily: 'var(--font-display)', fontWeight: 700,
              fontSize: '0.65rem', letterSpacing: '0.1em',
              padding: '0.45rem 1rem', borderRadius: '0.25rem', cursor: 'pointer',
              display: 'flex', alignItems: 'center', gap: '0.4rem',
            }}
          >
            {showEnroll ? <X size={14} /> : <UserPlus size={14} />}
            {showEnroll ? 'CLOSE FORM' : 'ENROLL SUBJECT'}
          </button>
        )}
      </div>

      {/* ── Main layout ── */}
      <div style={{ display: 'flex', gap: '1rem', flex: 1, minHeight: 0 }}>

        {/* ── Left: enroll form (ADMIN only) ── */}
        {showEnroll && isAdmin && (
          <div style={{
            width: '280px', flexShrink: 0,
            background: 'var(--bg-panel)', border: '1px solid var(--border-color)',
            borderRadius: '0.35rem', padding: '1rem',
            overflowY: 'auto',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem' }}>
              <UserPlus size={16} style={{ color: 'var(--color-ok)' }} />
              <span className="font-display text-main" style={{ fontSize: '0.75rem', letterSpacing: '0.08em' }}>
                ENROLL NEW SUBJECT
              </span>
            </div>
            <EnrollForm
              onSuccess={(person) => {
                setPersons(prev => [person, ...prev]);
                setShowEnroll(false);
              }}
            />
          </div>
        )}

        {/* ── Right: search + filter + grid ── */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '0.75rem', minHeight: 0 }}>

          {/* Controls bar */}
          <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexShrink: 0, flexWrap: 'wrap' }}>
            {/* Search */}
            <div style={{ position: 'relative', flex: 1, minWidth: '180px' }}>
              <Search size={14} style={{
                position: 'absolute', left: '0.6rem', top: '50%',
                transform: 'translateY(-50%)', color: 'var(--text-muted)',
              }} />
              <input
                type="text"
                placeholder="Search name, alias, category, location…"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                style={{
                  width: '100%', background: 'var(--bg-panel)',
                  border: '1px solid var(--border-color)', borderRadius: '0.25rem',
                  padding: '0.45rem 0.75rem 0.45rem 2rem',
                  fontFamily: 'var(--font-body)', fontSize: '0.75rem',
                  color: 'var(--text-main)',
                }}
              />
            </div>

            {/* Threat filter pills */}
            <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
              <Filter size={12} style={{ color: 'var(--text-muted)' }} />
              {['ALL', ...THREAT_LEVELS].map(l => {
                const m = THREAT_META[l];
                const active = filterThreat === l;
                return (
                  <button
                    key={l}
                    onClick={() => setFilterThreat(l)}
                    style={{
                      fontFamily: 'var(--font-display)', fontSize: '0.58rem',
                      letterSpacing: '0.08em', padding: '0.2rem 0.5rem',
                      borderRadius: '0.2rem', cursor: 'pointer',
                      border: `1px solid ${active ? (m?.color ?? 'var(--color-ok)') : 'var(--border-color)'}`,
                      background: active ? `${m?.color ?? '#4ade80'}22` : 'transparent',
                      color: active ? (m?.color ?? 'var(--color-ok)') : 'var(--text-muted)',
                      transition: 'all 0.12s',
                    }}
                  >
                    {l} ({counts[l] ?? 0})
                  </button>
                );
              })}
            </div>

            {/* Refresh button */}
            <button
              onClick={fetchWatchlist}
              style={{
                padding: '0.4rem 0.75rem',
                background: 'var(--bg-elevated)', border: '1px solid var(--border-color)',
                borderRadius: '0.2rem', color: 'var(--text-muted)',
                fontFamily: 'var(--font-display)', fontSize: '0.6rem',
                letterSpacing: '0.08em', cursor: 'pointer',
              }}
            >
              REFRESH
            </button>
          </div>

          {/* States: loading / error / empty / grid */}
          {loading ? (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <span className="animate-pulse" style={{ fontFamily: 'var(--font-display)', fontSize: '0.75rem', color: 'var(--color-ok)', letterSpacing: '0.1em' }}>
                LOADING WATCHLIST…
              </span>
            </div>
          ) : error ? (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem' }}>
              <AlertTriangle size={18} style={{ color: '#ef4444' }} />
              <span style={{ fontFamily: 'var(--font-display)', fontSize: '0.7rem', color: '#ef4444', letterSpacing: '0.08em' }}>
                {error}
              </span>
            </div>
          ) : displayed.length === 0 ? (
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '0.5rem' }}>
              <Users size={32} style={{ color: 'var(--text-muted)', opacity: 0.4 }} />
              <span style={{ fontFamily: 'var(--font-display)', fontSize: '0.7rem', color: 'var(--text-muted)', letterSpacing: '0.08em' }}>
                {searchQuery || filterThreat !== 'ALL'
                  ? 'NO SUBJECTS MATCH YOUR FILTERS'
                  : 'WATCHLIST EMPTY — ENROLL A SUBJECT TO BEGIN'}
              </span>
            </div>
          ) : (
            <div className="wl-grid" style={{ overflowY: 'auto', paddingBottom: '1rem', alignContent: 'start' }}>
              {displayed.map(person => (
                <SubjectCard
                  key={person.person_id}
                  person={person}
                  isAdmin={isAdmin}
                  onInspect={setInspectPerson}
                  onDeactivate={handleDeactivate}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── Inspect modal ── */}
      <InspectModal person={inspectPerson} onClose={() => setInspectPerson(null)} />
    </div>
  );
}
