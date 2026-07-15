import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { BackHeader } from '../components/BackHeader';
import { PrimaryButton } from '../components/PrimaryButton';
import { TagPicker, type TagItem } from '../components/TagPicker';
import { confirmIngredientSelection, getIngredients as fetchIngredientCategories } from '../lib/api';
import { setIngredients, setSelectedCategories } from '../lib/storage';
import { colors } from '../theme';

export function IngredientSelectPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<TagItem[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    fetchIngredientCategories()
      .then((categories) => {
        setItems(categories.map((c) => ({ id: c.id, label: c.name })));
      })
      .catch(() => {
        setError('재료 카테고리를 불러오지 못했어요. 백엔드 서버 연결을 확인해주세요.');
      })
      .finally(() => setLoading(false));
  }, []);

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const onComplete = async () => {
    if (selected.size === 0 || submitting) return;
    setSubmitting(true);
    setError('');
    try {
      const results = await Promise.all(
        Array.from(selected).map((categoryId) => confirmIngredientSelection(categoryId)),
      );
      const chosen = new Map<string, { id: string; name: string }>();
      results.forEach(({ ingredients }) => {
        ingredients.forEach((i) => chosen.set(i.id, { id: i.id, name: i.name }));
      });
      setIngredients(Array.from(chosen.values()));

      // 화면에는 사용자가 고른 카테고리명만 보여준다 (세부 재료는 recommend 호출에만 쓰임).
      const selectedCategories = items.filter((item) => selected.has(item.id));
      setSelectedCategories(selectedCategories.map((c) => ({ id: c.id, name: c.label })));

      navigate('/recipes/confirm');
    } catch {
      setError('재료 정보를 불러오지 못했어요. 다시 시도해주세요.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <BackHeader
        title="재료 선택"
        onBack={() => navigate('/home')}
        maxWidth={640}
      />

      <div
        style={{
          flex: 1,
          padding: '10px 24px 40px',
          maxWidth: 640,
          margin: '0 auto',
          width: '100%',
          boxSizing: 'border-box',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {error && (
          <div style={{ fontSize: 13, color: colors.allergyText, marginBottom: 14, wordBreak: 'keep-all' }}>
            {error}
          </div>
        )}
        {loading ? (
          <div style={{ fontSize: 14, color: colors.textMuted, textAlign: 'center', padding: '40px 0' }}>
            재료 목록을 불러오는 중이에요...
          </div>
        ) : (
          <TagPicker
            allItems={items}
            selected={selected}
            onToggle={toggle}
            searchPlaceholder="재료를 검색해보세요"
            selectedBg={colors.teal}
            selectedColor={colors.white}
            itemLabel="재료"
            emptyText="아직 선택한 재료가 없어요"
            listMaxHeight={400}
          />
        )}

        <PrimaryButton onClick={onComplete} disabled={selected.size === 0 || submitting}>
          {submitting ? '재료를 불러오는 중이에요...' : '재료 선택 완료'}
        </PrimaryButton>
      </div>
    </div>
  );
}
