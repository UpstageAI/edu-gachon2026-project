import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import iconMouseChef from '../assets/icon-mouse-chef.png';
import { NavBar } from '../components/NavBar';
import { RecipeLoadingSpinner } from '../components/RecipeLoadingSpinner';
import { recommend, type RecipeSummaryDto } from '../lib/api';
import {
  getAllergies,
  getIngredients,
  getRecommendCache,
  setRecommendCache,
  setSelectedRecipe,
  setSelectedRecipeId,
} from '../lib/storage';
import { colors, shadow } from '../theme';

export function RecipeLoadingPage() {
  const navigate = useNavigate();
  const [phase, setPhase] = useState<'loading' | 'done' | 'error'>('loading');
  const [candidates, setCandidates] = useState<RecipeSummaryDto[]>([]);
  const [error, setError] = useState('');
  const [liveStatus, setLiveStatus] = useState<string | null>(null);

  useEffect(() => {
    const ingredientIds = getIngredients().map((i) => i.id);
    const allergenIds = getAllergies().selected.map((a) => a.id);
    const signature = JSON.stringify({
      ingredientIds: [...ingredientIds].sort(),
      allergenIds: [...allergenIds].sort(),
    });

    const cached = getRecommendCache(signature);
    if (cached) {
      setCandidates(cached);
      setPhase('done');
      return;
    }

    recommend(ingredientIds, allergenIds, undefined, (status) => setLiveStatus(status.message))
      .then((result) => {
        setCandidates(result.recipes);
        setPhase('done');
        setRecommendCache(signature, result.recipes);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : '레시피 추천에 실패했어요.');
        setPhase('error');
      });
  }, []);

  const selectRecipe = (recipe: RecipeSummaryDto) => {
    setSelectedRecipe(recipe.name);
    setSelectedRecipeId(recipe.id);
    navigate('/recipes/detail');
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', background: colors.bg }}>
      <div
        style={{
          padding: '24px 28px 8px 28px',
          maxWidth: 560,
          margin: '0 auto',
          width: '100%',
          boxSizing: 'border-box',
        }}
      >
        <NavBar size={26} fontSize={16} />
      </div>

      {phase === 'loading' ? (
        <RecipeLoadingSpinner
          title="레시피를 생각하는 중.."
          subtitle={
            liveStatus ?? (
              <>
                선택한 재료와 알레르기 정보를 바탕으로
                <br />
                딱 맞는 레시피를 찾고 있어요
              </>
            )
          }
        />
      ) : phase === 'error' ? (
        <div
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            textAlign: 'center',
            padding: '20px 24px 60px',
          }}
        >
          <div style={{ fontSize: 15, color: colors.allergyText, marginBottom: 16, wordBreak: 'keep-all' }}>
            {error}
          </div>
          <div
            onClick={() => navigate('/recipes/confirm')}
            style={{ fontSize: 13, fontWeight: 800, color: colors.teal, cursor: 'pointer' }}
          >
            다시 시도하기
          </div>
        </div>
      ) : (
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
              src={iconMouseChef}
              alt="뚜이"
              style={{ width: 88, height: 'auto', marginBottom: 14 }}
            />
            <div
              style={{
                fontWeight: 800,
                fontSize: 22,
                color: colors.navy,
                marginBottom: 6,
                wordBreak: 'keep-all',
              }}
            >
              {candidates.length > 0
                ? `딱 맞는 레시피 ${candidates.length}가지를 찾았어요!`
                : '조건에 맞는 레시피를 찾지 못했어요'}
            </div>
            <div style={{ fontSize: 14, color: colors.textMuted, wordBreak: 'keep-all' }}>
              {candidates.length > 0 ? '부족한 재료가 적은 순서로 보여드려요' : '다른 재료를 선택해보세요'}
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 20 }}>
            {candidates.map((recipe, index) => (
              <div
                key={recipe.id}
                onClick={() => selectRecipe(recipe)}
                style={{
                  background: colors.white,
                  border: index === 0 ? `2px solid ${colors.gold}` : undefined,
                  borderRadius: 16,
                  padding: '18px 20px',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  boxShadow: index === 0 ? undefined : shadow.card,
                  cursor: 'pointer',
                }}
              >
                <span style={{ fontWeight: 800, color: colors.navy, fontSize: 16 }}>
                  {recipe.name}
                </span>
                <span
                  style={{
                    fontSize: 13,
                    fontWeight: 700,
                    color: index === 0 ? colors.goldText : colors.textMuted,
                    background: index === 0 ? colors.gold : colors.bgCard,
                    padding: '6px 12px',
                    borderRadius: 999,
                  }}
                >
                  부족한 재료 {recipe.missing_ingredients.length}개
                </span>
              </div>
            ))}
          </div>

          <div
            style={{
              textAlign: 'center',
              fontSize: 13,
              color: colors.textMuted,
              marginBottom: 16,
              wordBreak: 'keep-all',
            }}
          >
            레시피를 눌러 자세히 볼 수 있어요
          </div>

          <div
            onClick={() => navigate('/home')}
            style={{
              width: '100%',
              boxSizing: 'border-box',
              color: colors.textMuted,
              fontWeight: 700,
              fontSize: 14,
              padding: '6px 0',
              textAlign: 'center',
              cursor: 'pointer',
            }}
          >
            홈으로 돌아가기
          </div>
        </div>
      )}
    </div>
  );
}
