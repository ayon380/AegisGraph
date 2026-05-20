import { NextResponse } from 'next/server';
import { SESSION_COOKIE } from '@/app/lib/jwt';

export async function POST() {
  const res = NextResponse.json({ success: true });
  res.cookies.set(SESSION_COOKIE, '', {
    httpOnly: true,
    maxAge: 0,
    path: '/',
  });
  return res;
}
