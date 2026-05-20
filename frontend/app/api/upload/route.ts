import { NextRequest, NextResponse } from 'next/server';
import { verifyToken, SESSION_COOKIE } from '@/app/lib/jwt';
import { query } from '@/app/lib/db';

const CORE_API = process.env.CORE_API_URL || 'http://localhost:8000';

function getUser(req: NextRequest) {
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  if (!token) return null;
  return verifyToken(token);
}

export async function POST(req: NextRequest) {
  const user = getUser(req);
  if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  const token = req.cookies.get(SESSION_COOKIE)?.value!;

  try {
    const formData = await req.formData();
    const file = formData.get('file') as File | null;
    const sessionId = formData.get('session_id') as string | null;
    const orgId = formData.get('org_id') as string || user.org_id;
    const clearanceLevel = parseInt(formData.get('clearance_level') as string || String(user.clearance_level));
    const departments = (formData.get('departments') as string || user.departments.join(',')).split(',').filter(Boolean);
    const projects = (formData.get('projects') as string || user.projects.join(',')).split(',').filter(Boolean);

    if (!file) {
      return NextResponse.json({ error: 'No file provided' }, { status: 400 });
    }

    const allowedTypes = [
      'application/pdf',
      'image/png',
      'image/jpeg',
      'image/jpg',
      'image/webp',
      'image/gif',
      'text/plain',
      'text/markdown',
      'application/msword',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    ];

    if (!allowedTypes.includes(file.type)) {
      return NextResponse.json(
        { error: `Unsupported file type: ${file.type}` },
        { status: 415 }
      );
    }

    // Forward file to Python ingest endpoint
    const upstreamForm = new FormData();
    upstreamForm.append('file', file, file.name);
    upstreamForm.append('org_id', orgId);
    upstreamForm.append('clearance_level', String(clearanceLevel));
    upstreamForm.append('departments', JSON.stringify(departments));
    upstreamForm.append('projects', JSON.stringify(projects));

    const upstreamRes = await fetch(`${CORE_API}/api/ingest`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: upstreamForm,
    });

    if (!upstreamRes.ok) {
      const err = await upstreamRes.text();
      console.error('[Upload] Upstream ingest failed:', err);
      return NextResponse.json({ error: 'Ingest failed on backend' }, { status: 502 });
    }

    const result = await upstreamRes.json();

    // Optionally record the file reference in the session
    if (sessionId) {
      await query(
        `UPDATE chat_sessions SET updated_at = NOW() WHERE id = $1 AND user_id = $2`,
        [sessionId, user.userId]
      ).catch(() => {});
    }

    return NextResponse.json({
      success: true,
      doc_id: result.doc_id,
      filename: file.name,
      size: file.size,
      type: file.type,
      extracted_preview: result.extracted_preview,
    });
  } catch (err) {
    console.error('[Upload] Error:', err);
    return NextResponse.json({ error: 'Upload processing failed' }, { status: 500 });
  }
}
