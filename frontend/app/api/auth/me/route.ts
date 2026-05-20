import { NextRequest, NextResponse } from 'next/server';
import { verifyToken, SESSION_COOKIE } from '@/app/lib/jwt';

export async function GET(req: NextRequest) {
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  if (!token) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const payload = verifyToken(token);
  if (!payload) {
    return NextResponse.json({ error: 'Invalid or expired session' }, { status: 401 });
  }

  return NextResponse.json({
    user: {
      id: payload.userId,
      username: payload.username,
      email: payload.email,
      role: payload.role,
      org_id: payload.org_id,
      clearance_level: payload.clearance_level,
      departments: payload.departments,
      projects: payload.projects,
    },
  });
}
