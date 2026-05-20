'use client';

import {
  useState,
  useRef,
  useCallback,
  KeyboardEvent,
  ChangeEvent,
} from 'react';
import { Send, Paperclip, X, FileText, Image as ImageIcon } from 'lucide-react';

export interface AttachedFile {
  file: File;
  previewUrl?: string;
}

interface ChatInputProps {
  onSend: (message: string, files: AttachedFile[]) => void;
  disabled?: boolean;
  sessionId?: string | null;
}

function fileIcon(type: string) {
  if (type.startsWith('image/')) return <ImageIcon size={12} />;
  return <FileText size={12} />;
}

const ACCEPTED = '.pdf,.png,.jpg,.jpeg,.webp,.gif,.txt,.md,.docx';
const MAX_SIZE_MB = 20;

export default function ChatInput({ onSend, disabled, sessionId }: ChatInputProps) {
  const [value, setValue] = useState('');
  const [files, setFiles] = useState<AttachedFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const autoResize = () => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 200) + 'px';
  };

  const handleChange = (e: ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value);
    autoResize();
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const submit = useCallback(() => {
    const msg = value.trim();
    if (!msg && files.length === 0) return;
    if (disabled || uploading) return;
    onSend(msg, files);
    setValue('');
    setFiles([]);
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  }, [value, files, disabled, uploading, onSend]);

  const handleFileSelect = async (e: ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(e.target.files || []);
    e.target.value = '';

    const valid = selected.filter((f) => {
      if (f.size > MAX_SIZE_MB * 1024 * 1024) {
        alert(`${f.name} exceeds ${MAX_SIZE_MB}MB limit`);
        return false;
      }
      return true;
    });

    if (!valid.length) return;

    setUploading(true);
    try {
      const newFiles: AttachedFile[] = await Promise.all(
        valid.map(async (file) => {
          let previewUrl: string | undefined;
          if (file.type.startsWith('image/')) {
            previewUrl = URL.createObjectURL(file);
          }
          return { file, previewUrl };
        })
      );
      setFiles((prev) => [...prev, ...newFiles]);
    } finally {
      setUploading(false);
    }
  };

  const removeFile = (index: number) => {
    setFiles((prev) => {
      const next = [...prev];
      if (next[index].previewUrl) URL.revokeObjectURL(next[index].previewUrl!);
      next.splice(index, 1);
      return next;
    });
  };

  const canSend = (value.trim().length > 0 || files.length > 0) && !disabled && !uploading;

  return (
    <div className="input-area">
      <div className="input-inner">
        <div className="input-box">
          {/* Attached file chips */}
          {files.length > 0 && (
            <div className="file-preview-bar">
              {files.map((f, i) => (
                <div key={i} className="file-chip">
                  {f.previewUrl ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={f.previewUrl}
                      alt={f.file.name}
                      style={{ width: 16, height: 16, objectFit: 'cover', borderRadius: 3 }}
                    />
                  ) : (
                    fileIcon(f.file.type)
                  )}
                  <span
                    style={{
                      maxWidth: 120,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {f.file.name}
                  </span>
                  <button
                    className="file-chip-remove"
                    onClick={() => removeFile(i)}
                    aria-label={`Remove ${f.file.name}`}
                  >
                    <X size={11} />
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="input-row">
            {/* Hidden file input */}
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPTED}
              multiple
              className="sr-only"
              onChange={handleFileSelect}
              aria-label="Upload file"
            />

            {/* Textarea */}
            <textarea
              ref={textareaRef}
              className="chat-textarea"
              placeholder="Message AegisGraph..."
              value={value}
              onChange={handleChange}
              onKeyDown={handleKeyDown}
              rows={1}
              disabled={disabled}
              aria-label="Chat message"
              id="chat-message-input"
            />

            <div className="input-actions">
              <button
                className="upload-btn"
                onClick={() => fileInputRef.current?.click()}
                disabled={disabled}
                title="Attach file (PDF, image, text, docx)"
                aria-label="Attach file"
              >
                <Paperclip size={17} />
              </button>

              <button
                className="send-btn"
                onClick={submit}
                disabled={!canSend}
                title="Send message (Enter)"
                aria-label="Send message"
                id="send-message-btn"
              >
                <Send size={15} />
              </button>
            </div>
          </div>
        </div>

        <p className="input-hint">
          AegisGraph enforces your role-based access clearance on every query.
        </p>
      </div>
    </div>
  );
}
