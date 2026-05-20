import { NextRequest, NextResponse } from 'next/server';
import { verifyToken, SESSION_COOKIE } from '@/app/lib/jwt';
import { query } from '@/app/lib/db';
import { runCypher } from '@/app/lib/neo4j';

function getUser(req: NextRequest) {
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  if (!token) return null;
  return verifyToken(token);
}

// GET /api/sessions/[id] — fetch session with messages
export async function GET(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const user = getUser(req);
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  const { id } = await params;

  const sessions = await query<{ id: string; title: string; user_id: string }>(
    'SELECT * FROM chat_sessions WHERE id = $1 AND user_id = $2',
    [id, user.userId]
  );

  if (sessions.length === 0) {
    return NextResponse.json({ error: 'Session not found' }, { status: 404 });
  }

  const messages = await query<{
    id: string;
    role: string;
    content: string;
    file_refs: unknown;
    created_at: string;
  }>(
    'SELECT id, role, content, file_refs, created_at FROM chat_messages WHERE session_id = $1 ORDER BY created_at ASC',
    [id]
  );

  return NextResponse.json({ session: sessions[0], messages });
}

// PATCH /api/sessions/[id] — update session title
export async function PATCH(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const user = getUser(req);
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  const { id } = await params;
  const { title } = await req.json();

  await query(
    'UPDATE chat_sessions SET title = $1, updated_at = NOW() WHERE id = $2 AND user_id = $3',
    [title, id, user.userId]
  );

  try {
    await runCypher(
      'MATCH (s:ChatSession {id: $id}) SET s.title = $title',
      { id, title }
    );
  } catch (e) {
    console.warn('[Neo4j] Session title update failed:', e);
  }

  return NextResponse.json({ success: true });
}

// DELETE /api/sessions/[id]
export async function DELETE(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const user = getUser(req);
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  const { id } = await params;

  await query(
    'DELETE FROM chat_sessions WHERE id = $1 AND user_id = $2',
    [id, user.userId]
  );

  try {
    await runCypher(
      'MATCH (s:ChatSession {id: $id}) DETACH DELETE s',
      { id }
    );
  } catch (e) {
    console.warn('[Neo4j] Session delete failed:', e);
  }

  return NextResponse.json({ success: true });
}
