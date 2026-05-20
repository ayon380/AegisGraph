import { NextRequest, NextResponse } from 'next/server';
import { verifyToken, SESSION_COOKIE } from '@/app/lib/jwt';
import { query } from '@/app/lib/db';
import { runCypher } from '@/app/lib/neo4j';
import { v4 as uuidv4 } from 'uuid';

function getUser(req: NextRequest) {
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  if (!token) return null;
  return verifyToken(token);
}

// GET /api/sessions — list sessions for current user
export async function GET(req: NextRequest) {
  const user = getUser(req);
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  const sessions = await query<{
    id: string;
    title: string;
    created_at: string;
    updated_at: string;
    message_count: string;
  }>(
    `SELECT s.id, s.title, s.created_at, s.updated_at,
            COUNT(m.id)::text AS message_count
     FROM chat_sessions s
     LEFT JOIN chat_messages m ON m.session_id = s.id
     WHERE s.user_id = $1
     GROUP BY s.id
     ORDER BY s.updated_at DESC`,
    [user.userId]
  );

  return NextResponse.json({ sessions });
}

// POST /api/sessions — create a new session
export async function POST(req: NextRequest) {
  const user = getUser(req);
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  const body = await req.json().catch(() => ({}));
  const title = body.title || 'New Chat';
  const id = uuidv4();
  const now = new Date().toISOString();

  await query(
    `INSERT INTO chat_sessions (id, user_id, title, created_at, updated_at)
     VALUES ($1, $2, $3, NOW(), NOW())`,
    [id, user.userId, title]
  );

  // Mirror to Neo4j
  try {
    await runCypher(
      `MERGE (u:AegisUser {id: $userId})
       ON CREATE SET u.username = $username, u.email = $email, u.role = $role
       CREATE (s:ChatSession {
         id: $sessionId,
         title: $title,
         created_at: $now,
         org_id: $orgId
       })
       CREATE (u)-[:OWNS]->(s)`,
      {
        userId: user.userId,
        username: user.username,
        email: user.email,
        role: user.role,
        sessionId: id,
        title,
        now,
        orgId: user.org_id,
      }
    );
  } catch (e) {
    console.warn('[Neo4j] Session mirror failed:', e);
  }

  return NextResponse.json({
    session: { id, title, created_at: now, updated_at: now, message_count: 0 },
  });
}
