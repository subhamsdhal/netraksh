import { useState, useEffect, useCallback } from 'react';
import { MapPin, Plus, Save, ShieldAlert } from 'lucide-react';
import { authFetch } from '../services/auth';
import useAuth from '../hooks/useAuth';

// The first genuinely ADMIN-exclusive page in this app — every other page
// is readable by any authenticated role (require_any_role on the backend).
// PUT /cameras/{id}/location and POST /cameras have always been real,
// ADMIN-gated endpoints (backend/api/cameras.py) — this is what actually
// exposes them anywhere in the UI, previously only reachable via a script
// or curl. Backend RBAC (require_admin) is the real enforcement; the
// client-side role check below is just an honest reflection of it, not a
// substitute for it — a non-admin hitting the real endpoints here would
// still get a real 403.
export default function CameraManagement() {
  const { role } = useAuth();
  const [cameras, setCameras] = useState([]);
  const [status, setStatus] = useState('loading'); // loading | ready | access-denied | error
  const [editingId, setEditingId] = useState(null);
  const [editLat, setEditLat] = useState('');
  const [editLon, setEditLon] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);

  const [newName, setNewName] = useState('');
  const [newLocation, setNewLocation] = useState('');
  const [newLat, setNewLat] = useState('');
  const [newLon, setNewLon] = useState('');
  const [registering, setRegistering] = useState(false);
  const [registerError, setRegisterError] = useState(null);

  const loadCameras = useCallback(async () => {
    setStatus('loading');
    try {
      const res = await authFetch('/cameras');
      if (res.status === 403) {
        setStatus('access-denied');
        return;
      }
      if (!res.ok) {
        setStatus('error');
        return;
      }
      setCameras(await res.json());
      setStatus('ready');
    } catch (_e) {
      setStatus('error');
    }
  }, []);

  useEffect(() => { loadCameras(); }, [loadCameras]);

  const startEdit = (cam) => {
    setEditingId(cam.camera_id);
    setEditLat(cam.latitude != null ? String(cam.latitude) : '');
    setEditLon(cam.longitude != null ? String(cam.longitude) : '');
    setSaveError(null);
  };

  const saveLocation = async (cameraId) => {
    const lat = parseFloat(editLat);
    const lon = parseFloat(editLon);
    if (Number.isNaN(lat) || Number.isNaN(lon)) {
      setSaveError('Latitude and longitude must both be real numbers.');
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const res = await authFetch(`/cameras/${cameraId}/location`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ latitude: lat, longitude: lon }),
      });
      if (res.status === 403) {
        setSaveError('Only ADMIN can set a camera location (real backend RBAC, not just this UI).');
        return;
      }
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setSaveError(data.detail || 'Save failed.');
        return;
      }
      setEditingId(null);
      await loadCameras();
    } catch (_e) {
      setSaveError('Could not reach the backend.');
    } finally {
      setSaving(false);
    }
  };

  const registerCamera = async (e) => {
    e.preventDefault();
    if (!newName.trim() || !newLocation.trim()) {
      setRegisterError('Name and location are both required.');
      return;
    }
    setRegistering(true);
    setRegisterError(null);
    try {
      const body = { name: newName.trim(), location: newLocation.trim() };
      const lat = parseFloat(newLat);
      const lon = parseFloat(newLon);
      if (!Number.isNaN(lat) && !Number.isNaN(lon)) {
        body.latitude = lat;
        body.longitude = lon;
      }
      const res = await authFetch('/cameras', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (res.status === 403) {
        setRegisterError('Only ADMIN can register a camera (real backend RBAC, not just this UI).');
        return;
      }
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setRegisterError(data.detail || 'Registration failed.');
        return;
      }
      setNewName(''); setNewLocation(''); setNewLat(''); setNewLon('');
      await loadCameras();
    } catch (_e) {
      setRegisterError('Could not reach the backend.');
    } finally {
      setRegistering(false);
    }
  };

  return (
    <div className="h-full flex flex-col gap-4 overflow-hidden">
      <div className="section-header flex-shrink-0">
        <div>
          <h2 className="section-title">Camera Management</h2>
          <div className="section-sub">
            Register cameras and set their real map coordinates — ADMIN role only, enforced by the
            real backend.
          </div>
        </div>
      </div>

      {status === 'access-denied' && (
        <div className="max-w-xs bg-panel border border-danger p-4 rounded text-center">
          <h3 className="text-danger font-display tracking-widest uppercase">Access Denied</h3>
          <p className="text-muted text-sm mt-2">You do not have permission to access this module.</p>
        </div>
      )}

      {status !== 'access-denied' && status === 'ready' && role !== 'ADMIN' && (
        <div className="max-w-md bg-panel border border-danger rounded flex items-center" style={{ padding: '1rem', gap: '0.75rem' }}>
          <ShieldAlert size={24} className="text-danger flex-shrink-0" />
          <span className="text-sm font-body text-main">
            Signed in as <strong>{role}</strong> — this page is ADMIN-only. The backend already
            enforces this for real (every request above used a real 403), this message just
            explains why nothing below is editable for you.
          </span>
        </div>
      )}

      {status === 'loading' && <div className="text-muted text-sm text-center mt-8">Loading real camera list…</div>}
      {status === 'error' && <div className="text-danger text-sm text-center mt-8">Could not reach the backend.</div>}

      {status === 'ready' && (
        <div className="flex h-full min-h-0" style={{ gap: '1.5rem' }}>
          
          {/* Main Table Column */}
          <div className="flex-grow flex flex-col border rounded overflow-hidden" style={{ background: 'rgba(15,23,42,0.6)', backdropFilter: 'blur(12px)', border: '1px solid rgba(255,255,255,0.05)' }}>
            <div className="overflow-y-auto h-full relative custom-scrollbar">
              <table className="w-full text-sm font-body border-collapse">
                <thead className="sticky top-0 z-10" style={{ background: 'rgba(10,15,13,0.95)', backdropFilter: 'blur(8px)' }}>
                  <tr className="text-left text-xs font-display text-muted uppercase border-b border-color">
                    <th style={{ padding: '1rem' }}>Camera Node</th>
                    <th style={{ padding: '1rem' }}>Location</th>
                    <th style={{ padding: '1rem' }}>Coordinates (Lat, Lon)</th>
                    <th style={{ padding: '1rem' }}>Edge Health</th>
                    {role === 'ADMIN' && <th style={{ padding: '1rem' }}>Actions</th>}
                  </tr>
                </thead>
                <tbody>
                  {cameras.map((cam) => (
                    <tr key={cam.camera_id} className="border-b border-color last:border-b-0 hover:bg-[rgba(255,255,255,0.02)] transition-colors group">
                      <td style={{ padding: '1rem' }}>
                        <div className="font-bold text-main tracking-wide">{cam.name}</div>
                        <div className="text-xs text-muted font-display tracking-widest uppercase">{cam.camera_id}</div>
                      </td>
                      <td className="text-muted" style={{ padding: '1rem' }}>{cam.location}</td>
                      <td style={{ padding: '1rem' }}>
                        {editingId === cam.camera_id ? (
                          <div className="flex flex-col" style={{ gap: '0.5rem' }}>
                            <div className="flex items-center" style={{ gap: '0.5rem' }}>
                              <input value={editLat} onChange={(e) => setEditLat(e.target.value)} placeholder="lat" className="w-24 bg-dark border border-color rounded text-xs text-main focus:outline-none focus:border-ok transition-colors" style={{ padding: '0.35rem 0.5rem' }} />
                              <input value={editLon} onChange={(e) => setEditLon(e.target.value)} placeholder="lon" className="w-24 bg-dark border border-color rounded text-xs text-main focus:outline-none focus:border-ok transition-colors" style={{ padding: '0.35rem 0.5rem' }} />
                              <button onClick={() => saveLocation(cam.camera_id)} disabled={saving} className="text-ok border border-ok rounded hover:bg-[rgba(74,222,128,0.1)] transition-colors disabled:opacity-50 flex items-center justify-center" style={{ padding: '0.35rem 0.75rem', gap: '0.25rem' }}>
                                <Save size={14} /> <span className="text-xs uppercase font-display">Save</span>
                              </button>
                            </div>
                            {saveError && <span className="text-[10px] text-danger font-display tracking-widest uppercase">{saveError}</span>}
                          </div>
                        ) : (
                          <span className="text-muted font-mono text-xs opacity-80 group-hover:opacity-100 transition-opacity">
                            {cam.latitude != null ? `${cam.latitude.toFixed(4)}, ${cam.longitude.toFixed(4)}` : '— not set —'}
                          </span>
                        )}
                      </td>
                      <td style={{ padding: '1rem' }}>
                        <div className="flex items-center">
                          <div className={`px-2 py-0.5 rounded text-[10px] font-display uppercase tracking-widest border ${
                            cam.health_state === 'OK' ? 'bg-[rgba(74,222,128,0.1)] text-ok border-ok' : 
                            cam.health_state === 'DEGRADED' ? 'bg-[rgba(251,191,36,0.1)] text-warning border-warning' : 
                            cam.health_state === 'FAILED' ? 'bg-[rgba(248,113,113,0.1)] text-danger border-danger' : 
                            'bg-[rgba(255,255,255,0.05)] text-muted border-muted'
                          }`}>
                            {cam.health_state || 'NO DATA'}
                          </div>
                        </div>
                      </td>
                      {role === 'ADMIN' && (
                        <td style={{ padding: '1rem' }}>
                          <div className="flex items-center justify-end opacity-0 group-hover:opacity-100 transition-opacity">
                            {editingId !== cam.camera_id && (
                              <button onClick={() => startEdit(cam)} className="text-ok hover:text-main flex items-center gap-1 text-xs border border-transparent hover:border-color rounded px-2 py-1 transition-all">
                                <MapPin size={14} /> Set Location
                              </button>
                            )}
                          </div>
                        </td>
                      )}
                    </tr>
                  ))}
                  {/* Empty state padding row to ensure nothing is clipped at the bottom */}
                  {cameras.length > 0 && (
                    <tr><td colSpan={5} style={{ height: '2rem' }}></td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Right Side Panel - Registration */}
          {role === 'ADMIN' && (
            <div className="card flex-shrink-0 h-min" style={{ width: '22rem' }}>
              {/* Header */}
              <div className="card-header border-b border-color" style={{ paddingBottom: '1rem' }}>
                <div className="flex items-center gap-3">
                  <div className="bg-[rgba(74,222,128,0.1)] p-1.5 rounded text-ok">
                    <Plus size={16} />
                  </div>
                  <div className="flex flex-col">
                    <span className="card-title">Register Node</span>
                    <span className="font-display text-muted uppercase tracking-widest" style={{ fontSize: '0.6rem' }}>Provision new camera</span>
                  </div>
                </div>
              </div>
              
              {/* Form */}
              <div style={{ padding: '1.5rem' }}>
                <form onSubmit={registerCamera} className="flex flex-col" style={{ gap: '1rem' }}>
                  
                  <div className="flex flex-col" style={{ gap: '0.25rem' }}>
                    <label className="text-[10px] font-display text-muted uppercase tracking-widest ml-1">Node Identifier</label>
                    <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="e.g. Border Post Gamma" className="w-full bg-dark border border-color rounded text-sm text-main focus:outline-none focus:border-ok transition-colors" style={{ padding: '0.6rem 0.75rem' }} />
                  </div>
                  
                  <div className="flex flex-col" style={{ gap: '0.25rem' }}>
                    <label className="text-[10px] font-display text-muted uppercase tracking-widest ml-1">Physical Location</label>
                    <input value={newLocation} onChange={(e) => setNewLocation(e.target.value)} placeholder="e.g. Sector 9" className="w-full bg-dark border border-color rounded text-sm text-main focus:outline-none focus:border-ok transition-colors" style={{ padding: '0.6rem 0.75rem' }} />
                  </div>
                  
                  <div className="flex flex-col" style={{ gap: '0.25rem' }}>
                    <label className="text-[10px] font-display text-muted uppercase tracking-widest ml-1">Initial Coordinates (Optional)</label>
                    <div className="flex" style={{ gap: '0.5rem' }}>
                      <input value={newLat} onChange={(e) => setNewLat(e.target.value)} placeholder="Lat" className="flex-1 bg-dark border border-color rounded text-sm text-main focus:outline-none focus:border-ok transition-colors" style={{ padding: '0.6rem 0.75rem' }} />
                      <input value={newLon} onChange={(e) => setNewLon(e.target.value)} placeholder="Lon" className="flex-1 bg-dark border border-color rounded text-sm text-main focus:outline-none focus:border-ok transition-colors" style={{ padding: '0.6rem 0.75rem' }} />
                    </div>
                  </div>

                  {registerError && (
                    <div className="text-[10px] font-display text-danger uppercase tracking-widest border border-danger rounded bg-[rgba(248,113,113,0.05)] mt-2" style={{ padding: '0.5rem' }}>
                      {registerError}
                    </div>
                  )}
                  
                  <button type="submit" disabled={registering} className="btn btn-primary w-full flex justify-center mt-2">
                    {registering ? 'Provisioning...' : 'Provision Node'}
                  </button>
                </form>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
