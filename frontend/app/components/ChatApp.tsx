'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter, useParams } from 'next/navigation';
import Sidebar from '@/app/components/Sidebar';
import UserMenu from '@/app/components/UserMenu';
import ChatThread from '@/app/components/ChatThread';
import ChatInput, { AttachedFile } from '@/app/components/ChatInput';
import { User, ChatSession, ChatMessage } from '@/app/lib/types';

/* =========================================================
   EMPTY STATE / LANDING
   ========================================================= */
function EmptyState({
  user,
  onSelectPrompt,
}: {
  user: User;
  onSelectPrompt: (p: string) => void;
}) {
  const prompts = [
    {
      title: 'Code style guidelines',
      sub: 'What are the coding guidelines?',
      q: 'What are the AegisGraph coding style guidelines?',
    },
    {
      title: 'Core engine architecture',
      sub: 'Explain the engine design',
      q: 'Explain the AegisGraph Core Engine ring buffer architecture.',
    },
    {
      title: 'Compensation bands',
      sub: 'What are the salary grades?',
      q: 'What are the 2026 employee compensation bands?',
    },
    {
      title: 'Acquisition intel',
      sub: 'Project Aegis Phoenix status',
      q: 'What is the current status of the BetaGraph acquisition?',
    },
  ];

  return (
    <div className="empty-state">
      <div className="empty-logo">⬡</div>
      <div>
        <h1 className="empty-title">
          How can I help, {user.username.split('_')[0]}?
        </h1>
        <p className="empty-subtitle">
          Ask anything within your clearance scope. Your access is enforced at
          CL-{user.clearance_level} across{' '}
          {user.departments.join(' & ')} data.
        </p>
      </div>
      <div className="prompt-grid">
        {prompts.map((p) => (
          <button
            key={p.q}
            className="prompt-card"
            onClick={() => onSelectPrompt(p.q)}
          >
            <span className="prompt-card-title">{p.title}</span>
            <span className="prompt-card-sub">{p.sub}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

/* =========================================================
   MAIN CHAT APP
   ========================================================= */
export default function ChatApp() {
  const router = useRouter();
  const params = useParams();
  const activeSessionId = (params?.sessionId as string) ?? null;

  const [user, setUser] = useState<User | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streamingContent, setStreamingContent] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [pendingPrompt, setPendingPrompt] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  /* ---- Auth ---- */
  useEffect(() => {
    fetch('/api/auth/me')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!d) { router.push('/login'); return; }
        setUser(d.user);
      })
      .catch(() => router.push('/login'));
  }, [router]);

  /* ---- Load sessions ---- */
  const loadSessions = useCallback(async () => {
    const r = await fetch('/api/sessions');
    if (!r.ok) return;
    const d = await r.json();
    setSessions(d.sessions ?? []);
  }, []);

  useEffect(() => { if (user) loadSessions(); }, [user, loadSessions]);

  /* ---- Load messages when active session changes ---- */
  useEffect(() => {
    if (!activeSessionId) { setMessages([]); return; }
    fetch(`/api/sessions/${activeSessionId}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d) setMessages(d.messages ?? []);
      })
      .catch(console.error);
  }, [activeSessionId]);

  /* ---- New chat ---- */
  const handleNewChat = useCallback(async () => {
    const r = await fetch('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'New Chat' }),
    });
    if (!r.ok) return;
    const d = await r.json();
    await loadSessions();
    router.push(`/chat/${d.session.id}`);
  }, [loadSessions, router]);

  /* ---- Delete session ---- */
  const handleDeleteSession = useCallback(
    async (id: string) => {
      await fetch(`/api/sessions/${id}`, { method: 'DELETE' });
      await loadSessions();
      if (activeSessionId === id) router.push('/chat');
    },
    [activeSessionId, loadSessions, router]
  );

  /* ---- Rename session ---- */
  const handleRenameSession = useCallback(
    async (id: string, title: string) => {
      await fetch(`/api/sessions/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
      });
      await loadSessions();
    },
    [loadSessions]
  );

  /* ---- Logout ---- */
  const handleLogout = useCallback(async () => {
    await fetch('/api/auth/logout', { method: 'POST' });
    router.push('/login');
  }, [router]);

  /* ---- Upload files before sending ---- */
  const uploadFiles = useCallback(
    async (files: AttachedFile[], sessionId: string): Promise<{ name: string; type: string; size: number; doc_id: string }[]> => {
      const refs: { name: string; type: string; size: number; doc_id: string }[] = [];

      for (const { file } of files) {
        const form = new FormData();
        form.append('file', file, file.name);
        form.append('session_id', sessionId);
        try {
          const r = await fetch('/api/upload', { method: 'POST', body: form });
          if (r.ok) {
            const d = await r.json();
            refs.push({ name: file.name, type: file.type, size: file.size, doc_id: d.doc_id });
          }
        } catch (e) {
          console.error('[Upload]', e);
        }
      }

      return refs;
    },
    []
  );

  /* ---- Core send + stream ---- */
  const handleSend = useCallback(
    async (message: string, files: AttachedFile[]) => {
      if (!user) return;
      if (isStreaming) {
        abortRef.current?.abort();
        return;
      }

      let sessionId = activeSessionId;

      /* Create session if needed */
      if (!sessionId) {
        const title = message.slice(0, 60) || 'New Chat';
        const r = await fetch('/api/sessions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title }),
        });
        if (!r.ok) return;
        const d = await r.json();
        sessionId = d.session.id;
        await loadSessions();
        router.push(`/chat/${sessionId}`);
        // Small delay to let navigation complete
        await new Promise((res) => setTimeout(res, 80));
      }

      /* Upload attached files */
      let fileRefs: { name: string; type: string; size: number; doc_id: string }[] = [];
      if (files.length > 0) {
        fileRefs = await uploadFiles(files, sessionId);
      }

      /* Optimistically add user message */
      const userMsg: ChatMessage = {
        id: crypto.randomUUID(),
        session_id: sessionId,
        role: 'user',
        content: message,
        file_refs: fileRefs,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMsg]);
      setIsStreaming(true);
      setStreamingContent('');

      /* Update session title from first message */
      if (sessions.find((s) => s.id === sessionId)?.title === 'New Chat') {
        handleRenameSession(sessionId, message.slice(0, 60) || 'New Chat');
      }

      /* Stream from /api/chat */
      const controller = new AbortController();
      abortRef.current = controller;
      let accumulated = '';

      try {
        const res = await fetch('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: message }),
          signal: controller.signal,
        });

        if (!res.ok || !res.body) throw new Error('Chat request failed');

        const reader = res.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          const chunk = decoder.decode(value, { stream: true });
          const lines = chunk.split('\n');

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            try {
              const payload = JSON.parse(line.slice(6));
              if (payload.token) {
                accumulated += payload.token;
                setStreamingContent(accumulated);
              }
            } catch { /* skip malformed */ }
          }
        }
      } catch (err: unknown) {
        if (err instanceof Error && err.name !== 'AbortError') {
          accumulated = accumulated || 'Sorry, an error occurred while processing your request.';
        }
      } finally {
        setIsStreaming(false);

        if (accumulated) {
          const assistantMsg: ChatMessage = {
            id: crypto.randomUUID(),
            session_id: sessionId,
            role: 'assistant',
            content: accumulated,
            created_at: new Date().toISOString(),
          };
          setMessages((prev) => [...prev, assistantMsg]);
          setStreamingContent('');

          /* Persist to DB + Neo4j */
          fetch(`/api/sessions/${sessionId}/messages`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              userMessage: message,
              assistantMessage: accumulated,
              fileRefs,
            }),
          }).catch(console.error);
        }
      }
    },
    [user, isStreaming, activeSessionId, sessions, loadSessions, router, uploadFiles, handleRenameSession]
  );

  /* ---- Prompt card → start chat ---- */
  const handleSelectPrompt = useCallback(
    (prompt: string) => {
      setPendingPrompt(prompt);
    },
    []
  );

  /* Execute pending prompt after state settles */
  useEffect(() => {
    if (pendingPrompt && !isStreaming) {
      handleSend(pendingPrompt, []);
      setPendingPrompt(null);
    }
  }, [pendingPrompt, isStreaming, handleSend]);

  if (!user) return null;

  const activeSession = sessions.find((s) => s.id === activeSessionId);

  return (
    <div className="app-shell">
      {/* Sidebar */}
      <aside className="sidebar">
        <Sidebar
          sessions={sessions}
          activeSessionId={activeSessionId}
          onSelectSession={(id) => router.push(`/chat/${id}`)}
          onNewChat={handleNewChat}
          onDeleteSession={handleDeleteSession}
          onRenameSession={handleRenameSession}
        />
        <div className="sidebar-footer">
          <UserMenu user={user} onLogout={handleLogout} />
        </div>
      </aside>

      {/* Main */}
      <main className="chat-main">
        {/* Header */}
        <div className="chat-header">
          {activeSession && (
            <span className="chat-header-title">{activeSession.title}</span>
          )}
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
            <span className={`clearance-badge clearance-${user.clearance_level}`}>
              CL-{user.clearance_level}
            </span>
          </div>
        </div>

        {/* Content */}
        {activeSessionId ? (
          <ChatThread
            messages={messages}
            streamingContent={streamingContent}
            isStreaming={isStreaming}
            user={user}
            sessionId={activeSessionId}
            onSend={handleSend}
          />
        ) : (
          <>
            <EmptyState user={user} onSelectPrompt={handleSelectPrompt} />
            <ChatInput onSend={handleSend} disabled={isStreaming} sessionId={null} />
          </>
        )}
      </main>
    </div>
  );
}
