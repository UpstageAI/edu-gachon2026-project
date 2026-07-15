import { useState } from 'react';
import { colors, shadow } from '../theme';

export interface TagItem {
  id: string;
  label: string;
}

interface TagPickerProps {
  allItems: TagItem[];
  selected: Set<string>;
  onToggle: (id: string) => void;
  searchPlaceholder: string;
  selectedBg: string;
  selectedColor: string;
  itemLabel: string;
  emptyText: string;
  listMaxHeight?: number;
}

export function TagPicker({
  allItems,
  selected,
  onToggle,
  searchPlaceholder,
  selectedBg,
  selectedColor,
  itemLabel,
  emptyText,
  listMaxHeight = 260,
}: TagPickerProps) {
  const [search, setSearch] = useState('');

  const byId = new Map(allItems.map((item) => [item.id, item.label]));
  const trimmed = search.trim();
  const filtered = trimmed
    ? allItems.filter((item) => item.label.includes(trimmed))
    : allItems;
  const selectedItems = Array.from(selected);

  return (
    <>
      <div style={{ position: 'relative', marginBottom: 18 }}>
        <span
          style={{
            position: 'absolute',
            left: 16,
            top: '50%',
            transform: 'translateY(-50%)',
            fontSize: 15,
            color: colors.textFaint,
          }}
        >
          🔍
        </span>
        <input
          type="text"
          placeholder={searchPlaceholder}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{
            width: '100%',
            boxSizing: 'border-box',
            border: `1.5px solid ${colors.border}`,
            borderRadius: 14,
            padding: '13px 16px 13px 42px',
            fontSize: 15,
            fontFamily: "'Noto Sans KR', sans-serif",
            outline: 'none',
            color: colors.navy,
            background: colors.white,
          }}
        />
      </div>

      <div
        style={{
          background: colors.bgCard,
          borderRadius: 16,
          padding: '16px 18px',
          marginBottom: 18,
        }}
      >
        <div
          style={{
            fontSize: 13,
            fontWeight: 700,
            color: colors.navy,
            marginBottom: 10,
          }}
        >
          선택한 {itemLabel} {selectedItems.length}개
        </div>
        {selectedItems.length > 0 ? (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {selectedItems.map((id) => (
              <div
                key={id}
                onClick={() => onToggle(id)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '8px 12px 8px 14px',
                  borderRadius: 999,
                  background: selectedBg,
                  color: selectedColor,
                  fontSize: 13,
                  fontWeight: 700,
                  cursor: 'pointer',
                }}
              >
                {byId.get(id) ?? id}
                <span style={{ opacity: 0.75 }}>×</span>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ fontSize: 13, color: colors.textMuted }}>
            {emptyText}
          </div>
        )}
      </div>

      <div
        style={{
          maxHeight: listMaxHeight,
          overflowY: 'auto',
          background: colors.white,
          borderRadius: 16,
          padding: 16,
          boxShadow: shadow.card,
          marginBottom: 20,
        }}
      >
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
          {filtered.map((item) => {
            const isOn = selected.has(item.id);
            return (
              <div
                key={item.id}
                onClick={() => onToggle(item.id)}
                style={{
                  padding: '10px 18px',
                  borderRadius: 999,
                  background: isOn ? selectedBg : colors.bgCard,
                  color: isOn ? selectedColor : colors.textMuted,
                  fontSize: 14,
                  fontWeight: 700,
                  cursor: 'pointer',
                  userSelect: 'none',
                }}
              >
                {item.label}
                {isOn ? ' ✓' : ''}
              </div>
            );
          })}
        </div>
        {filtered.length === 0 && (
          <div
            style={{
              textAlign: 'center',
              color: colors.textFaint,
              fontSize: 14,
              padding: '30px 0',
            }}
          >
            검색 결과가 없어요
          </div>
        )}
      </div>
    </>
  );
}
