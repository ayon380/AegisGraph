import { NextRequest, NextResponse } from 'next/server';
import bcrypt from 'bcryptjs';
import { query } from '@/app/lib/db';
import { signToken, SESSION_COOKIE } from '@/app/lib/jwt';

export async function POST(req: NextRequest) {
  try {
    const { email, password } = await req.json();

    if (!email || !password) {
      return NextResponse.json({ error: 'Email and password are required' }, { status: 400 });
    }

    const rows = await query<{
      id: string;
      username: string;
      email: string;
      password_hash: string;
      role: string;
      org_id: string;
      clearance_level: number;
      departments: string[];
      projects: string[];
    }>('SELECT * FROM aegis_users WHERE email = $1 LIMIT 1', [email.toLowerCase()]);

    if (rows.length === 0) {
      return NextResponse.json({ error: 'Invalid credentials' }, { status: 401 });
    }

    const user = rows[0];
    const valid = await bcrypt.compare(password, user.password_hash);

    if (!valid) {
      return NextResponse.json({ error: 'Invalid credentials' }, { status: 401 });
    }

    const tokenPayload = {
      userId: user.id,
      username: user.username,
      email: user.email,
      role: user.role,
      org_id: user.org_id,
      clearance_level: user.clearance_level,
      departments: user.departments,
      projects: user.projects,
    };

    const token = signToken(tokenPayload);

    const res = NextResponse.json({
      user: {
        id: user.id,
        username: user.username,
        email: user.email,
        role: user.role,
        org_id: user.org_id,
        clearance_level: user.clearance_level,
        departments: user.departments,
        projects: user.projects,
      },
    });

    res.cookies.set(SESSION_COOKIE, token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      maxAge: 60 * 60 * 8, // 8 hours
      path: '/',
    });

    return res;
  } catch (err) {
    console.error('[Login]', err);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
