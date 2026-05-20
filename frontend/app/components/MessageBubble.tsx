'use client';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import { ChatMessage } from '@/app/lib/types';
import { useState } from 'react';
import { Copy, Check } from 'lucide-react';

interface MessageBubbleProps {
  message: ChatMessage;
  username?: string;
}

function CodeBlock({ children, className }: { children?: React.ReactNode; className?: string }) {
  const [copied, setCopied] = useState(false);
  const code = String(children).replace(/\n$/, '');

  const copy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const isBlock = className?.startsWith('language-');

  if (!isBlock) {
    return <code className={className}>{children}</code>;
  }

  return (
    <div style={{ position: 'relative' }}>
      <button
        onClick={copy}
        style={{
          position: 'absolute',
          top: 8,
          right: 8,
          background: 'var(--bg-hover)',
          border: '1px solid var(--border)',
          borderRadius: 6,
          padding: '3px 8px',
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          fontSize: 11.5,
          color: 'var(--text-secondary)',
          cursor: 'pointer',
          transition: 'all 0.12s',
          zIndex: 1,
        }}
      >
        {copied ? <Check size={12} /> : <Copy size={12} />}
        {copied ? 'Copied' : 'Copy'}
      </button>
      <code className={className}>{children}</code>
    </div>
  );
}

// Try to parse JSON answer format from the backend
function parseContent(content: string): string {
  try {
    const parsed = JSON.parse(content);
    if (parsed && typeof parsed.answer === 'string') {
      return parsed.answer;
    }
  } catch {
    // not JSON, use as-is
  }
  return content;
}

export default function MessageBubble({ message, username }: MessageBubbleProps) {
  const isUser = message.role === 'user';
  const displayContent = isUser ? message.content : parseContent(message.content);

  return (
    <div className={`message-row ${message.role}`}>
      <div className="message-header">
        <div className={`message-avatar ${message.role}`}>
          {isUser
            ? (username?.[0] ?? 'U').toUpperCase()
            : '⬡'}
        </div>
        <span className="message-label">
          {isUser ? (username || 'You') : 'AegisGraph'}
        </span>
      </div>

      {message.file_refs && message.file_refs.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 4 }}>
          {(message.file_refs as Array<{name: string; type: string}>).map((f, i) => (
            <span key={i} className="file-chip">
              📎 {f.name}
            </span>
          ))}
        </div>
      )}

      <div className={`message-bubble ${message.role}`}>
        {isUser ? (
          <span style={{ whiteSpace: 'pre-wrap' }}>{displayContent}</span>
        ) : (
          <div className="prose">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeHighlight]}
              components={{
                code: ({ className, children }) => (
                  <CodeBlock className={className}>{children}</CodeBlock>
                ),
              }}
            >
              {displayContent}
            </ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
}
