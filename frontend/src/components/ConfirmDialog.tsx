import React, { useEffect } from 'react';

interface ConfirmDialogProps {
  isOpen: boolean;
  title: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  isDestructive?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  isOpen,
  title,
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  isDestructive = false,
  onConfirm,
  onCancel,
}) => {
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onCancel();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isOpen, onCancel]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50" onClick={onCancel}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        className="panel w-full max-w-md shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-4 pt-4 pb-3">
          <h3 id="confirm-title" className="text-sm font-semibold text-slate-100">
            {title}
          </h3>
          <p className="mt-1.5 text-xs text-slate-400 leading-relaxed">{description}</p>
        </div>
        <div className="flex justify-end gap-2 px-4 py-3 border-t border-slate-800">
          <button onClick={onCancel} className="btn-secondary">
            {cancelLabel}
          </button>
          <button onClick={onConfirm} className={isDestructive ? 'btn-danger' : 'btn-primary'} autoFocus>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
};
