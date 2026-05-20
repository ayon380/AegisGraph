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

// POST /api/sessions/[id]/messages — persist a pair of messages
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const user = getUser(req);
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  const { id: sessionId } = await params;
  const { userMessage, assistantMessage, fileRefs } = await req.json();

  // Verify session belongs to user
  const sessions = await query(
    'SELECT id FROM chat_sessions WHERE id = $1 AND user_id = $2',
    [sessionId, user.userId]
  );
  if (sessions.length === 0) {
    return NextResponse.json({ error: 'Session not found' }, { status: 404 });
  }

  const userMsgId = uuidv4();
  const assistantMsgId = uuidv4();

  // Save user message
  await query(
    `INSERT INTO chat_messages (id, session_id, role, content, file_refs, created_at)
     VALUES ($1, $2, 'user', $3, $4, NOW())`,
    [userMsgId, sessionId, userMessage, JSON.stringify(fileRefs || [])]
  );

  // Save assistant message
  await query(
    `INSERT INTO chat_messages (id, session_id, role, content, file_refs, created_at)
     VALUES ($1, $2, 'assistant', $3, '[]', NOW())`,
    [assistantMsgId, sessionId, assistantMessage]
  );

  // Touch session updated_at
  await query(
    'UPDATE chat_sessions SET updated_at = NOW() WHERE id = $1',
    [sessionId]
  );

  // Mirror to Neo4j
  try {
    const now = new Date().toISOString();
    await runCypher(
      `MATCH (s:ChatSession {id: $sessionId})
       CREATE (um:ChatMessage {
         id: $userMsgId, role: 'user', content: $userContent, created_at: $now
       })
       CREATE (am:ChatMessage {
         id: $assistantMsgId, role: 'assistant', content: $assistantContent, created_at: $now
       })
       CREATE (s)-[:HAS_MESSAGE]->(um)
       CREATE (s)-[:HAS_MESSAGE]->(am)
       CREATE (um)-[:FOLLOWED_BY]->(am)`,
      {
        sessionId,
        userMsgId,
        assistantMsgId,
        userContent: userMessage,
        assistantContent: assistantMessage,
        now,
      }
    );
  } catch (e) {
    console.warn('[Neo4j] Message mirror failed:', e);
  }

  return NextResponse.json({
    userMessageId: userMsgId,
    assistantMessageId: assistantMsgId,
  });
}
