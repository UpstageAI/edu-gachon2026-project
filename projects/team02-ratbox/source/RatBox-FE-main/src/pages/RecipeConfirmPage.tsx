import { useMemo, useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import mascot from '../assets/mascot-transparent.png';
import { BackHeader } from '../components/BackHeader';
import { PrimaryButton } from '../components/PrimaryButton';
import { getAllergies, getSelectedCategories } from '../lib/storage';
import { colors } from '../theme';

export function RecipeConfirmPage() {
  const navigate = useNavigate();
  const [selectedCategoryNames, setSelectedCategoryNames] = useState<string[]>([]);
  const [allergyItems, setAllergyItems] = useState<string[]>([]);

  useEffect(() => {
    setSelectedCategoryNames(getSelectedCategories().map((c) => c.name));
    const allergies = getAllergies();
    const items = allergies.selected.map((a) => a.name);
    if (allergies.custom && allergies.custom.trim()) {
      allergies.custom
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
        .forEach((c) => items.push(c));
    }
    setAllergyItems(items);
  }, []);

  const hasAllergyInfo = useMemo(() => allergyItems.length > 0, [allergyItems]);

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <BackHeader
        title="확인하기"
        onBack={() => navigate('/ingredients')}
        maxWidth={560}
      />

      <div
        style={{
          flex: 1,
          padding: '14px 24px 40px',
          maxWidth: 560,
          margin: '0 auto',
          width: '100%',
          boxSizing: 'border-box',
        }}
      >
        <div style={{ textAlign: 'center', marginBottom: 26 }}>
          <img
            src={mascot}
            alt="뚜이"
            style={{ width: 120, height: 'auto', marginBottom: 14 }}
          />
          <div
            style={{
              fontWeight: 800,
              fontSize: 21,
              color: colors.navy,
              marginBottom: 6,
              wordBreak: 'keep-all',
            }}
          >
            이 정보로 레시피를 찾아드릴게요
          </div>
          <div style={{ fontSize: 14, color: colors.textMuted, wordBreak: 'keep-all' }}>
            선택한 재료와 알레르기 정보를 확인해주세요
          </div>
        </div>

        <div
          style={{
            background: colors.navy,
            borderRadius: 18,
            padding: '20px 22px',
            marginBottom: 16,
          }}
        >
          <div style={{ fontSize: 13, fontWeight: 700, color: colors.chipTeal, marginBottom: 12 }}>
            선택한 재료 {selectedCategoryNames.length}개
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {selectedCategoryNames.map((item) => (
              <div
                key={item}
                style={{
                  padding: '8px 14px',
                  borderRadius: 999,
                  background: 'rgba(255,255,255,0.14)',
                  color: colors.white,
                  fontSize: 13,
                  fontWeight: 700,
                }}
              >
                {item}
              </div>
            ))}
          </div>
        </div>

        <div
          style={{
            background: colors.white,
            borderRadius: 18,
            padding: '20px 22px',
            marginBottom: 30,
            boxShadow: '0 4px 18px rgba(51,73,94,0.06)',
          }}
        >
          <div style={{ fontSize: 13, fontWeight: 700, color: colors.navy, marginBottom: 12 }}>
            내 알레르기 정보
          </div>

          {hasAllergyInfo ? (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {allergyItems.map((item) => (
                <div
                  key={item}
                  style={{
                    padding: '8px 14px',
                    borderRadius: 999,
                    background: colors.allergyBg,
                    color: colors.allergyText,
                    fontSize: 13,
                    fontWeight: 700,
                  }}
                >
                  {item}
                </div>
              ))}
            </div>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
              <div style={{ fontSize: 13, color: colors.textMuted, wordBreak: 'keep-all' }}>
                등록된 알레르기 정보가 없어요
              </div>
              <div
                onClick={() => navigate('/allergies?edit=1')}
                style={{ fontSize: 13, fontWeight: 800, color: colors.teal, cursor: 'pointer', whiteSpace: 'nowrap' }}
              >
                등록하기
              </div>
            </div>
          )}
        </div>

        <PrimaryButton onClick={() => navigate('/recipes/loading')}>
          레시피 추천받기
        </PrimaryButton>
      </div>
    </div>
  );
}
