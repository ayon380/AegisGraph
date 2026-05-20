'use client';

import { useState, useRef } from 'react';
import { Trash2, Pencil, Check, X, MessageSquare } from 'lucide-react';
import { ChatSession } from '@/app/lib/types';

interface SidebarProps {
  sessions: ChatSession[];
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  onDeleteSession: (id: string) => void;
  onRenameSession: (id: string, title: string) => void;
  isLoading?: boolean;
}

function groupSessions(sessions: ChatSession[]) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86400000);
  const week = new Date(today.getTime() - 7 * 86400000);

  const groups: Record<string, ChatSession[]> = {
    Today: [],
    Yesterday: [],
    'Previous 7 days': [],
    Older: [],
  };

  for (const s of sessions) {
    const d = new Date(s.updated_at);
    if (d >= today) groups.Today.push(s);
    else if (d >= yesterday) groups.Yesterday.push(s);
    else if (d >= week) groups['Previous 7 days'].push(s);
    else groups.Older.push(s);
  }

  return groups;
}

export default function Sidebar({
  sessions,
  activeSessionId,
  onSelectSession,
  onNewChat,
  onDeleteSession,
  onRenameSession,
}: SidebarProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const startEdit = (s: ChatSession) => {
    setEditingId(s.id);
    setEditTitle(s.title);
    setTimeout(() => inputRef.current?.focus(), 50);
  };

  const confirmEdit = (id: string) => {
    if (editTitle.trim()) onRenameSession(id, editTitle.trim());
    setEditingId(null);
  };

  const groups = groupSessions(sessions);

  return (
    <>
      <div className="sidebar-header">
        <button className="new-chat-btn" onClick={onNewChat}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 5v14M5 12h14"/>
          </svg>
          New chat
        </button>
      </div>

      <div className="sidebar-sessions">
        {sessions.length === 0 && (
          <div style={{ padding: '24px 10px', textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
            No chats yet
          </div>
        )}
        {Object.entries(groups).map(([label, items]) =>
          items.length === 0 ? null : (
            <div key={label}>
              <div className="session-group-label">{label}</div>
              {items.map((s) => (
                <div
                  key={s.id}
                  className={`session-item${s.id === activeSessionId ? ' active' : ''}`}
                  onClick={() => editingId !== s.id && onSelectSession(s.id)}
                >
                  <MessageSquare size={13} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
                  {editingId === s.id ? (
                    <input
                      ref={inputRef}
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') confirmEdit(s.id);
                        if (e.key === 'Escape') setEditingId(null);
                      }}
                      onClick={(e) => e.stopPropagation()}
                      style={{
                        flex: 1,
                        background: 'var(--bg-active)',
                        border: '1px solid var(--accent)',
                        borderRadius: 5,
                        padding: '2px 6px',
                        color: 'var(--text-primary)',
                        fontSize: 13,
                        outline: 'none',
                      }}
                    />
                  ) : (
                    <span className="session-item-title">{s.title}</span>
                  )}
                  <div className="session-item-actions" onClick={(e) => e.stopPropagation()}>
                    {editingId === s.id ? (
                      <>
                        <button className="icon-btn" onClick={() => confirmEdit(s.id)} title="Save">
                          <Check size={13} />
                        </button>
                        <button className="icon-btn" onClick={() => setEditingId(null)} title="Cancel">
                          <X size={13} />
                        </button>
                      </>
                    ) : (
                      <>
                        <button className="icon-btn" onClick={() => startEdit(s)} title="Rename">
                          <Pencil size={12} />
                        </button>
                        <button
                          className="icon-btn danger"
                          onClick={() => onDeleteSession(s.id)}
                          title="Delete"
                        >
                          <Trash2 size={12} />
                        </button>
                      </>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )
        )}
      </div>
    </>
  );
}
