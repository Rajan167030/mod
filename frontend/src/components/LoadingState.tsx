import React from 'react';
import { SkeletonPage, ErrorState as UiErrorState, EmptyState as UiEmptyState } from './ui';

/** Page-level loading placeholder. `message` is kept for screen readers. */
export const LoadingState: React.FC<{ message?: string }> = ({ message = 'Loading' }) => (
  <div>
    <span className="sr-only">{message}</span>
    <SkeletonPage />
  </div>
);

export const ErrorState = UiErrorState;

export const EmptyState: React.FC<{ title: string; description: string; actionLabel?: string; onAction?: () => void }> = ({
  title,
  description,
  actionLabel,
  onAction,
}) => (
  <UiEmptyState
    title={title}
    description={description}
    action={
      actionLabel && onAction ? (
        <button onClick={onAction} className="btn-primary">
          {actionLabel}
        </button>
      ) : undefined
    }
  />
);
