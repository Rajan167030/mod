import React from 'react';
import { Badge } from './ui';

interface StatusBadgeProps {
  status: string;
  className?: string;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status, className }) => (
  <Badge status={status} className={className} />
);
