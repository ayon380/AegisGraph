'use client';

import { useState } from 'react';
import { LogOut, Shield, User } from 'lucide-react';
import { User as UserType } from '@/app/lib/types';

interface UserMenuProps {
  user: UserType;
  onLogout: () => void;
}

const CLEARANCE_LABELS: Record<number, string> = {
  1: 'Intern',
  2: 'Engineer',
  3: 'Executive',
};

export default function UserMenu({ user, onLogout }: UserMenuProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className="user-menu">
      {open && (
        <>
          {/* backdrop */}
          <div
            style={{ position: 'fixed', inset: 0, zIndex: 40 }}
            onClick={() => setOpen(false)}
          />
          <div className="user-dropdown" style={{ zIndex: 50 }}>
            {/* profile header */}
            <div
              style={{
                padding: '12px 14px 10px',
                borderBottom: '1px solid var(--border-subtle)',
              }}
            >
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
                {user.username}
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
                {user.email}
              </div>
              <div style={{ marginTop: 8, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                <span className={`clearance-badge clearance-${user.clearance_level}`}>
                  <Shield size={9} />
                  CL-{user.clearance_level} · {CLEARANCE_LABELS[user.clearance_level] ?? 'Unknown'}
                </span>
              </div>
              <div
                style={{
                  marginTop: 6,
                  fontSize: 11.5,
                  color: 'var(--text-muted)',
                }}
              >
                Depts: {user.departments.join(', ')}
              </div>
            </div>

            <button
              className="dropdown-item"
              onClick={() => { setOpen(false); }}
            >
              <User size={14} />
              Profile
            </button>

            <button
              className="dropdown-item danger"
              onClick={() => { setOpen(false); onLogout(); }}
            >
              <LogOut size={14} />
              Sign out
            </button>
          </div>
        </>
      )}

      <button className="user-menu-trigger" onClick={() => setOpen((v) => !v)}>
        <div className="user-avatar">
          {user.username[0].toUpperCase()}
        </div>
        <div className="user-info">
          <div className="user-name">{user.username}</div>
          <div className="user-role">{user.role}</div>
        </div>
      </button>
    </div>
  );
}
