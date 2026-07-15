import type { ReactNode } from 'react';
import { colors } from '../theme';

interface BackHeaderProps {
  title: string;
  onBack: () => void;
  maxWidth?: number;
  trailing?: ReactNode;
}

export function BackHeader({
  title,
  onBack,
  maxWidth = 560,
  trailing,
}: BackHeaderProps) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: trailing ? 'space-between' : 'flex-start',
        gap: 14,
        padding: '24px 28px 8px 28px',
        maxWidth,
        margin: '0 auto',
        width: '100%',
        boxSizing: 'border-box',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <div
          onClick={onBack}
          style={{ fontSize: 20, color: colors.navy, cursor: 'pointer', lineHeight: 1 }}
        >
          ←
        </div>
        <span style={{ fontWeight: 800, fontSize: 17, color: colors.navy }}>
          {title}
        </span>
      </div>
      {trailing}
    </div>
  );
}
