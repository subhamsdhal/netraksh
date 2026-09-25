import { Link, useLocation } from 'react-router-dom';
import {
  Eye, Shield, Map, Activity, Bell, Gauge, Settings,
  Users, Network, BarChart2, ClipboardList, Radio,
  Building2, Cpu
} from 'lucide-react';
import Logo from './Logo';
import useAuth from '../hooks/useAuth';

const ROLE_COLORS = {
  ADMIN:    'text-danger',
  OPERATOR: 'text-ok',
  AUDITOR:  'text-warning',
};

const ROLE_BORDER = {
  ADMIN:    'border-danger',
  OPERATOR: 'border-ok',
  AUDITOR:  'border-warning',
};

const NAV_SECTIONS = [
  {
    label: 'Surveillance',
    items: [
      { to: '/',              icon: Eye,          label: 'Command Center' },
      { to: '/camera-health', icon: Activity,     label: 'System Health'  },
      { to: '/map',           icon: Map,          label: 'Map Intelligence'},
    ],
  },
  {
    label: 'Intelligence',
    items: [
      { to: '/cross-command-alerts', icon: Bell,         label: 'Alerts & Incidents' },
      { to: '/evidence',             icon: Shield,       label: 'Evidence Vault'     },
      { to: '/watchlist',            icon: Users,        label: 'Face Watchlist'     },
      { to: '/analytics',            icon: BarChart2,    label: 'Analytics'          },
      { to: '/audit',                icon: ClipboardList,label: 'Audit Trail'        },
    ],
  },
  {
    label: 'Administration',
    items: [
      { to: '/performance',    icon: Gauge,   label: 'Edge Performance', },
      { to: '/architecture',   icon: Network, label: 'Architecture',     },
    ],
    adminItems: [
      { to: '/camera-management', icon: Settings, label: 'Camera Mgmt', adminOnly: true },
    ],
  },
];

export default function Sidebar() {
  const location = useLocation();
  const path = location.pathname;
  const { role, username } = useAuth();

  const isActive = (to) => {
    if (to === '/') return path === '/';
    return path.startsWith(to);
  };

  return (
    <nav className="sidebar-left">
      {/* Brand */}
      <div className="nav-brand">
        <Logo size={32} />
        <div className="nav-brand-text">
          <span className="nav-brand-name">Netraksh</span>
          <span className="nav-brand-sub">Border Intelligence</span>
        </div>
      </div>

      {/* Navigation */}
      <div style={{ flex: 1, overflowY: 'auto', paddingTop: '0.5rem' }}>
        {NAV_SECTIONS.map((section) => (
          <div key={section.label} className="nav-section">
            <div className="nav-section-label">{section.label}</div>
            <div className="nav-items">
              {section.items.map(({ to, icon: Icon, label }) => (
                <Link
                  key={to}
                  to={to}
                  className={`nav-item${isActive(to) ? ' active' : ''}`}
                  title={label}
                >
                  <Icon size={15} className="nav-item-icon" />
                  <span>{label}</span>
                </Link>
              ))}
              {section.adminItems && role === 'ADMIN' &&
                section.adminItems.map(({ to, icon: Icon, label }) => (
                  <Link
                    key={to}
                    to={to}
                    className={`nav-item${isActive(to) ? ' active' : ''}`}
                    title={label + ' (ADMIN)'}
                  >
                    <Icon size={15} className="nav-item-icon" />
                    <span>{label}</span>
                  </Link>
                ))
              }
            </div>
          </div>
        ))}
      </div>

      {/* Operator Footer */}
      <div className="nav-footer">
        <div className="nav-operator-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <div
              style={{
                width: 28, height: 28, borderRadius: '50%',
                background: 'var(--bg-base)',
                border: `1px solid var(--border-color)`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                flexShrink: 0,
              }}
            >
              <Cpu size={13} style={{ color: 'var(--text-muted)' }} />
            </div>
            <div style={{ minWidth: 0 }}>
              <div className="nav-operator-name" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {username || 'Operator'}
              </div>
              <div
                className={`nav-operator-role ${ROLE_COLORS[role] || 'text-muted'}`}
                style={{ fontSize: '0.6rem', letterSpacing: '0.08em', textTransform: 'uppercase' }}
              >
                {role || 'UNKNOWN'}
              </div>
            </div>
          </div>
        </div>
      </div>
    </nav>
  );
}
