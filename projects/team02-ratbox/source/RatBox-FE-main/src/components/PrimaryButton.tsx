import type { CSSProperties, ReactNode } from 'react';
import { colors } from '../theme';

interface PrimaryButtonProps {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: 'solid' | 'outline' | 'text';
  style?: CSSProperties;
}

export function PrimaryButton({
  children,
  onClick,
  disabled,
  variant = 'solid',
  style,
}: PrimaryButtonProps) {
  const base: CSSProperties = {
    width: '100%',
    boxSizing: 'border-box',
    fontWeight: 700,
    fontSize: 16,
    padding: '15px 0',
    borderRadius: 999,
    textAlign: 'center',
    cursor: disabled ? 'default' : 'pointer',
  };

  const variants: Record<string, CSSProperties> = {
    solid: {
      background: disabled ? colors.textFaint : colors.teal,
      color: colors.white,
    },
    outline: {
      background: colors.bgCard,
      color: colors.textBody,
    },
    text: {
      background: 'transparent',
      color: colors.textMuted,
      fontWeight: 700,
      fontSize: 14,
      padding: '6px 0',
    },
  };

  return (
    <div
      onClick={disabled ? undefined : onClick}
      style={{ ...base, ...variants[variant], ...style }}
    >
      {children}
    </div>
  );
}
