import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import iconFaceChef from '../assets/icon-face-chef.png';
import { BackHeader } from '../components/BackHeader';
import { PrimaryButton } from '../components/PrimaryButton';
import { RecipeLoadingSpinner } from '../components/RecipeLoadingSpinner';
import { recommend, type IngredientRefDto, type RecipeDetailDto } from '../lib/api';
import { getAllergies, getIngredients, getSelectedRecipe, getSelectedRecipeId } from '../lib/storage';
import { colors, shadow } from '../theme';

// 화면에는 재료 선택 화면과 동일하게 재료명이 아니라 카테고리만 보여준다.
// 카테고리 매핑이 안 된 재료(category=null)는 재료명 그대로 노출한다.
function toCategoryLabels(refs: IngredientRefDto[]): string[] {
  return Array.from(new Set(refs.map((ref) => ref.category ?? ref.name)));
}

function categoryLabelsFor(names: string[], refs: IngredientRefDto[]): string[] {
  const categoryByName = new Map(refs.map((ref) => [ref.name, ref.category]));
  return Array.from(new Set(names.map((name) => categoryByName.get(name) ?? name)));
}

export function RecipeDetailPage() {
  const navigate = useNavigate();
  const [recipeName, setRecipeName] = useState(getSelectedRecipe());
  const [detail, setDetail] = useState<RecipeDetailDto | null>(null);
  const [phase, setPhase] = useState<'loading' | 'done' | 'error'>('loading');
  const [error, setError] = useState('');
  const [liveStatus, setLiveStatus] = useState<string | null>(null);

  useEffect(() => {
    const ingredientIds = getIngredients().map((i) => i.id);
    const allergenIds = getAllergies().selected.map((a) => a.id);
    const recipeId = getSelectedRecipeId();

    recommend(ingredientIds, allergenIds, recipeId, (status) => setLiveStatus(status.message))
      .then((result) => {
        if (!result.detail) {
          throw new Error('레시피 상세 정보를 불러오지 못했어요.');
        }
        setDetail(result.detail);
        setRecipeName(result.detail.name);
        setPhase('done');
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : '레시피 상세 정보를 불러오지 못했어요.');
        setPhase('error');
      });
  }, []);

  const steps = detail?.cooking_steps ?? [];
  const missingRefs = detail?.missing_ingredients ?? [];
  const ownedIngredients = toCategoryLabels(detail?.owned_ingredients ?? []);
  const requiredIngredients = detail?.classification?.required
    ? categoryLabelsFor(detail.classification.required, missingRefs)
    : toCategoryLabels(missingRefs);
  const optionalIngredients = detail?.classification?.optional
    ? categoryLabelsFor(detail.classification.optional, missingRefs)
    : [];

  if (phase === 'loading') {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
        <BackHeader title="레시피 상세" onBack={() => navigate(-1)} maxWidth={560} />
        <RecipeLoadingSpinner
          title="레시피를 준비하는 중.."
          subtitle={
            liveStatus ?? (
              <>
                선택한 레시피의 자세한 정보를
                <br />
                불러오고 있어요
              </>
            )
          }
        />
      </div>
    );
  }

  if (phase === 'error') {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
        <BackHeader title="레시피 상세" onBack={() => navigate(-1)} maxWidth={560} />
        <div
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 12,
            padding: '0 24px',
            textAlign: 'center',
          }}
        >
          <div style={{ fontSize: 15, color: colors.allergyText, wordBreak: 'keep-all' }}>{error}</div>
          <div
            onClick={() => navigate('/recipes/loading')}
            style={{ fontSize: 13, fontWeight: 800, color: colors.teal, cursor: 'pointer' }}
          >
            다시 시도하기
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <BackHeader
        title="레시피 상세"
        onBack={() => navigate(-1)}
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
        <div style={{ textAlign: 'center', marginBottom: 22 }}>
          <img
            src={iconFaceChef}
            alt="뚜이"
            style={{ width: 96, height: 'auto', marginBottom: 14 }}
          />
          <div
            style={{
              fontWeight: 800,
              fontSize: 24,
              color: colors.navy,
              marginBottom: 8,
              wordBreak: 'keep-all',
            }}
          >
            {recipeName}
          </div>
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 8,
              background: colors.gold,
              color: colors.goldText,
              fontSize: 13,
              fontWeight: 700,
              padding: '7px 16px',
              borderRadius: 999,
            }}
          >
            <span>⏱ {detail?.cooking_time != null ? `${detail.cooking_time}분` : '-'}</span>
            <span>·</span>
            <span>{steps.length}단계</span>
          </div>
        </div>

        <div
          style={{
            background: colors.white,
            borderRadius: 20,
            padding: '22px 24px',
            marginBottom: 16,
            boxShadow: shadow.card,
          }}
        >
          {ownedIngredients.length > 0 && (
            <>
              <div style={{ fontSize: 13, fontWeight: 700, color: colors.navy, marginBottom: 12 }}>
                내가 가진 재료
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 16 }}>
                {ownedIngredients.map((item) => (
                  <div
                    key={item}
                    style={{
                      padding: '8px 14px',
                      borderRadius: 999,
                      background: colors.teal,
                      color: colors.white,
                      fontSize: 13,
                      fontWeight: 700,
                    }}
                  >
                    {item}
                  </div>
                ))}
              </div>
            </>
          )}
          {requiredIngredients.length > 0 && (
            <>
              <div style={{ fontSize: 13, fontWeight: 700, color: colors.navy, marginBottom: 12 }}>
                추가로 필요한 재료
              </div>
              <div
                style={{
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: 8,
                  marginBottom: optionalIngredients.length ? 16 : 0,
                }}
              >
                {requiredIngredients.map((item) => (
                  <div
                    key={item}
                    style={{
                      padding: '8px 14px',
                      borderRadius: 999,
                      background: colors.bgCard,
                      color: colors.navy,
                      fontSize: 13,
                      fontWeight: 700,
                    }}
                  >
                    {item}
                  </div>
                ))}
              </div>
            </>
          )}
          {optionalIngredients.length > 0 && (
            <>
              <div style={{ fontSize: 13, fontWeight: 700, color: colors.navy, marginBottom: 12 }}>
                생략 가능한 재료
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {optionalIngredients.map((item) => (
                  <div
                    key={item}
                    style={{
                      padding: '8px 14px',
                      borderRadius: 999,
                      background: colors.bg,
                      color: colors.textMuted,
                      fontSize: 13,
                      fontWeight: 700,
                    }}
                  >
                    {item}
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        <div
          style={{
            background: colors.white,
            borderRadius: 20,
            padding: '22px 24px',
            marginBottom: 30,
            boxShadow: shadow.card,
          }}
        >
          <div style={{ fontSize: 13, fontWeight: 700, color: colors.navy, marginBottom: 12 }}>
            전체 단계 미리보기
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {steps.map((text, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                <div
                  style={{
                    flex: '0 0 auto',
                    width: 22,
                    height: 22,
                    borderRadius: 999,
                    background: colors.gold,
                    color: colors.goldText,
                    fontSize: 12,
                    fontWeight: 800,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  {i + 1}
                </div>
                <div style={{ fontSize: 14, color: colors.textBody, lineHeight: 1.5, wordBreak: 'keep-all' }}>
                  {text}
                </div>
              </div>
            ))}
          </div>
        </div>

        <PrimaryButton
          onClick={() => navigate('/cooking/steps', { state: { steps, name: recipeName } })}
        >
          요리 시작하기
        </PrimaryButton>
      </div>
    </div>
  );
}
