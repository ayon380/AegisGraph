import { NextRequest } from 'next/server';
import { verifyToken, SESSION_COOKIE } from '@/app/lib/jwt';

const CORE_API = process.env.CORE_API_URL || 'http://localhost:8000';

export async function POST(req: NextRequest) {
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  if (!token) {
    return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401 });
  }

  const payload = verifyToken(token);
  if (!payload) {
    return new Response(JSON.stringify({ error: 'Invalid session' }), { status: 401 });
  }

  const { query: userQuery } = await req.json();

  if (!userQuery?.trim()) {
    return new Response(JSON.stringify({ error: 'Query is required' }), { status: 400 });
  }

  // Forward to Python backend with the JWT (which carries all claims the backend needs)
  const upstreamRes = await fetch(`${CORE_API}/api/query`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ query: userQuery }),
  });

  if (!upstreamRes.ok || !upstreamRes.body) {
    return new Response(JSON.stringify({ error: 'Upstream error' }), { status: 502 });
  }

  // Pipe SSE stream back to client
  return new Response(upstreamRes.body, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
    },
  });
}
