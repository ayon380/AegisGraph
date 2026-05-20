'use client';

import { useEffect, useRef } from 'react';
import MessageBubble from './MessageBubble';
import ThinkingIndicator from './ThinkingIndicator';
import ChatInput, { AttachedFile } from './ChatInput';
import { ChatMessage, User } from '@/app/lib/types';

interface ChatThreadProps {
  messages: ChatMessage[];
  streamingContent: string;
  isStreaming: boolean;
  user: User;
  sessionId: string;
  onSend: (message: string, files: AttachedFile[]) => void;
}

export default function ChatThread({
  messages,
  streamingContent,
  isStreaming,
  user,
  sessionId,
  onSend,
}: ChatThreadProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, streamingContent]);

  return (
    <>
      <div className="messages-container">
        <div className="messages-inner">
          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} username={user.username} />
          ))}

          {/* Live streaming message */}
          {isStreaming && streamingContent && (
            <MessageBubble
              key="streaming"
              message={{
                id: 'streaming',
                session_id: sessionId,
                role: 'assistant',
                content: streamingContent,
                created_at: new Date().toISOString(),
              }}
              username={user.username}
            />
          )}

          {/* Thinking dots before first token */}
          {isStreaming && !streamingContent && <ThinkingIndicator />}

          <div ref={bottomRef} />
        </div>
      </div>

      <ChatInput onSend={onSend} disabled={isStreaming} sessionId={sessionId} />
    </>
  );
}
