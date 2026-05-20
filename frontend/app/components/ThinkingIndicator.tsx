'use client';

export default function ThinkingIndicator() {
  return (
    <div className="message-row assistant">
      <div className="message-header">
        <div className="message-avatar assistant">⬡</div>
        <span className="message-label">AegisGraph</span>
      </div>
      <div className="thinking">
        <div className="thinking-dot" />
        <div className="thinking-dot" />
        <div className="thinking-dot" />
      </div>
    </div>
  );
}
