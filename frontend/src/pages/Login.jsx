import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  ArrowRight,
  Eye,
  EyeOff,
  LockKeyhole,
  ShieldCheck,
  User,
} from 'lucide-react';
import netrakshMark from '../assets/netraksh-mark.png';
import { login } from '../services/auth';
import './login.css';

export default function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const navigate = useNavigate();
  const location = useLocation();
  const from = location.state?.from?.pathname || '/';

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      await login(username, password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="auth-page">
      <section className="auth-hero" aria-label="NETRAKSH border surveillance overview">
        <div className="auth-brand-replacement" aria-label="NETRAKSH">
          <img src={netrakshMark} alt="NETRAKSH project logo" />
        </div>

        <div className="sr-only">
          <h1>AI-Assisted Border Surveillance</h1>
          <p>
            Operator command center for near-real-time edge video analytics, verifiable
            cryptographic evidence, and incident management.
          </p>
          <ul>
            <li>AI-assisted edge video analytics</li>
            <li>Cryptographic evidence verification</li>
            <li>Offline store-and-forward resilience</li>
            <li>Multi-camera corroboration and alert management</li>
          </ul>
        </div>
      </section>

      <section className="auth-auth-section" aria-label="Authentication">
        <div className="auth-duty-mark">
          <span className="auth-india-flag" aria-hidden="true">
            <svg viewBox="0 0 30 20" focusable="false">
              <path fill="#FF9933" d="M0 0h30v6.667H0z" />
              <path fill="#fff" d="M0 6.667h30v6.666H0z" />
              <path fill="#138808" d="M0 13.333h30V20H0z" />
              <g fill="none" stroke="#000080" strokeWidth=".34">
                <circle cx="15" cy="10" r="3" />
                {[...Array(24)].map((_, index) => (
                  <path
                    key={index}
                    d="M15 10V7"
                    transform={`rotate(${index * 15} 15 10)`}
                  />
                ))}
              </g>
              <circle cx="15" cy="10" r=".48" fill="#000080" />
            </svg>
          </span>
          <span>
            Our Borders
            <br />
            Our Responsibility
          </span>
        </div>

        <form className="auth-auth-card" onSubmit={handleSubmit}>
          <div className="auth-card-glow" aria-hidden="true" />

          <div className="auth-secure-label">
            <LockKeyhole size={25} strokeWidth={1.9} aria-hidden="true" />
            <span>Secure Operator Access</span>
          </div>

          <h2 className="auth-title">Sign In</h2>
          <p className="auth-auth-copy">
            Enter your operator credentials to access
            <br />
            the command center.
          </p>

          <div className="auth-form-stack">
            <label className="auth-field-wrap">
              <span className="auth-field-icon" aria-hidden="true">
                <User size={27} strokeWidth={1.75} />
              </span>
              <span className="sr-only">Username</span>
              <input
                className="auth-field"
                type="text"
                placeholder="operator_id"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                autoComplete="username"
                required
              />
            </label>

            <label className="auth-field-wrap">
              <span className="auth-field-icon" aria-hidden="true">
                <LockKeyhole size={27} strokeWidth={1.75} />
              </span>
              <span className="sr-only">Password</span>
              <input
                className="auth-field auth-field-password"
                type={showPassword ? 'text' : 'password'}
                placeholder="Password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                required
              />
              <button
                className="auth-password-toggle"
                type="button"
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                onClick={() => setShowPassword((value) => !value)}
              >
                {showPassword ? <EyeOff size={24} /> : <Eye size={24} />}
              </button>
            </label>

            {error && (
              <div className="auth-error" role="alert">
                {error}
              </div>
            )}

            <button className="auth-submit" type="submit" disabled={submitting}>
              <span>{submitting ? 'Authenticating' : 'Sign In'}</span>
              <ArrowRight size={25} strokeWidth={2.3} aria-hidden="true" />
            </button>
          </div>

          <p className="auth-authorized">Authorized personnel only</p>

          <div className="auth-security-note">
            <ShieldCheck size={34} strokeWidth={1.55} aria-hidden="true" />
            <p>
              Access is restricted to authorized personnel only. Session activity is logged
              for audit and security review.
            </p>
          </div>
        </form>
      </section>
    </main>
  );
}
