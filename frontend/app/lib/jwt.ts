import jwt from 'jsonwebtoken';
import { AuthPayload } from './types';

const JWT_SECRET = process.env.JWT_SECRET || 'super-secure-shared-secret-key-12345';
const JWT_EXPIRES_IN = '8h';

export function signToken(payload: Omit<AuthPayload, 'exp' | 'iat'>): string {
  return jwt.sign(payload, JWT_SECRET, { expiresIn: JWT_EXPIRES_IN, algorithm: 'HS256' });
}

export function verifyToken(token: string): AuthPayload | null {
  try {
    return jwt.verify(token, JWT_SECRET, { algorithms: ['HS256'] }) as AuthPayload;
  } catch {
    return null;
  }
}

export function decodeToken(token: string): AuthPayload | null {
  try {
    return jwt.decode(token) as AuthPayload;
  } catch {
    return null;
  }
}

/** Cookie name for the session token */
export const SESSION_COOKIE = 'aegis_session';
