'use client';

import { useState, FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { AlertCircle } from 'lucide-react';

const TEST_USERS = [
  { email: 'alice@org-alpha.internal', name: 'alice_intern', role: 'Intern', clearance: 1 },
  { email: 'bob@org-alpha.internal',   name: 'bob_engineer', role: 'Engineer', clearance: 2 },
  { email: 'carol@org-alpha.internal', name: 'carol_hr',     role: 'HR Mgr', clearance: 2 },
  { email: 'dave@org-alpha.internal',  name: 'dave_executive', role: 'Executive', clearance: 3 },
];

const CLEARANCE_COLORS: Record<number, string> = {
  1: 'var(--accent)',
  2: '#f59e0b',
  3: '#ef4444',
};

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail]       = useState('');
  const [password, setPassword] = useState('');
  const [error, setError]       = useState('');
  const [loading, setLoading]   = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim(), password }),
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data.error || 'Login failed. Please check your credentials.');
        return;
      }

      router.push('/chat');
    } catch {
      setError('Network error. Is the server running?');
    } finally {
      setLoading(false);
    }
  };

  const fillTestUser = (u: typeof TEST_USERS[0]) => {
    setEmail(u.email);
    setPassword('password123');
    setError('');
  };

  return (
    <div className="login-page">
      <div className="login-card">
        {/* Logo */}
        <div className="login-logo">
          <div className="login-logo-icon">⬡</div>
          <span className="login-logo-text">AegisGraph</span>
        </div>

        <h1 className="login-title">Welcome back</h1>
        <p className="login-subtitle">
          Sign in to access the secure intelligence platform
        </p>

        {/* Error */}
        {error && (
          <div className="form-error">
            <AlertCircle size={13} />
            {error}
          </div>
        )}

        {/* Form */}
        <form onSubmit={submit} noValidate>
          <div className="form-group">
            <label className="form-label" htmlFor="email">Email address</label>
            <input
              id="email"
              type="email"
              className="form-input"
              placeholder="you@org-alpha.internal"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              autoFocus
              required
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              className="form-input"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>

          <button
            type="submit"
            className="btn-primary"
            disabled={loading || !email || !password}
            id="login-submit-btn"
          >
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        {/* Test users */}
        <div className="login-test-users">
          <div className="login-test-title">Quick access — test accounts</div>
          <div className="test-user-grid">
            {TEST_USERS.map((u) => (
              <button
                key={u.email}
                className="test-user-btn"
                onClick={() => fillTestUser(u)}
                type="button"
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span
                    style={{
                      width: 7,
                      height: 7,
                      borderRadius: '50%',
                      background: CLEARANCE_COLORS[u.clearance],
                      flexShrink: 0,
                    }}
                  />
                  <span className="test-user-name">{u.name}</span>
                </div>
                <span className="test-user-role">
                  CL-{u.clearance} · {u.role}
                </span>
              </button>
            ))}
          </div>
          <p
            style={{
              marginTop: 10,
              fontSize: 11.5,
              color: 'var(--text-muted)',
              textAlign: 'center',
            }}
          >
            All test accounts use password: <code style={{ color: 'var(--text-secondary)' }}>password123</code>
          </p>
        </div>
      </div>
    </div>
  );
}
