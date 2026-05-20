export interface User {
  id: string;
  username: string;
  email: string;
  role: 'intern' | 'engineer' | 'hr' | 'executive';
  org_id: string;
  clearance_level: number;
  departments: string[];
  projects: string[];
}

export interface ChatSession {
  id: string;
  user_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count?: number;
}

export interface ChatMessage {
  id: string;
  session_id: string;
  role: 'user' | 'assistant';
  content: string;
  file_refs?: FileRef[];
  created_at: string;
}

export interface FileRef {
  name: string;
  type: string;
  size: number;
}

export interface AuthPayload {
  userId: string;
  username: string;
  email: string;
  role: string;
  org_id: string;
  clearance_level: number;
  departments: string[];
  projects: string[];
  exp: number;
  iat: number;
}
