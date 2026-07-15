import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import iconMouseBelly from '../assets/icon-mouse-belly.png';
import { PrimaryButton } from '../components/PrimaryButton';
import { TagPicker, type TagItem } from '../components/TagPicker';
import { getAllergens, getMyInfo, updateMyAllergens } from '../lib/api';
import { getAuth, setAllergies } from '../lib/storage';
import { colors } from '../theme';

export function AllergySetupPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const isEdit = searchParams.get('edit') === '1';

  const [items, setItems] = useState<TagItem[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const loggedIn = Boolean(getAuth());
    Promise.all([getAllergens(), loggedIn ? getMyInfo().catch(() => null) : Promise.resolve(null)])
      .then(([allergens, myInfo]) => {
        setItems(allergens.map((a) => ({ id: a.id, label: a.allergen_name })));
        if (myInfo) {
          setSelected(new Set(myInfo.allergens.map((a) => a.id)));
        }
      })
      .catch(() => {
        setError('알레르기 목록을 불러오지 못했어요. 백엔드 서버 연결을 확인해주세요.');
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

  const goHome = () => navigate('/home');
  const goToLogin = () => navigate('/login');

  const onComplete = async () => {
    if (saving) return;
    const chosen = items.filter((i) => selected.has(i.id)).map((i) => ({ id: i.id, name: i.label }));
    setError('');
    setSaving(true);
    try {
      if (getAuth()) {
        await updateMyAllergens(chosen.map((c) => c.id));
      }
      setAllergies({ selected: chosen, custom: '' });
      navigate(isEdit ? '/home' : '/login');
    } catch (err) {
      setError(err instanceof Error ? err.message : '알레르기 정보 저장에 실패했어요.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '24px 28px 8px 28px',
          maxWidth: 560,
          margin: '0 auto',
          width: '100%',
          boxSizing: 'border-box',
        }}
      >
        {isEdit ? (
          <div
            onClick={goHome}
            style={{ fontSize: 20, color: colors.navy, cursor: 'pointer', lineHeight: 1 }}
          >
            ←
          </div>
        ) : (
          <div />
        )}
        {!isEdit && (
          <div
            onClick={goToLogin}
            style={{ fontSize: 14, fontWeight: 700, color: colors.textMuted, cursor: 'pointer' }}
          >
            나중에 할게요
          </div>
        )}
      </div>

      <div
        style={{
          flex: 1,
          padding: '14px 24px 40px',
          maxWidth: 560,
          margin: '0 auto',
          width: '100%',
          boxSizing: 'border-box',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <img
            src={iconMouseBelly}
            alt="뚜이"
            style={{ width: 88, height: 'auto', marginBottom: 16 }}
          />
          <div
            style={{
              fontWeight: 800,
              fontSize: 23,
              color: colors.navy,
              marginBottom: 8,
              wordBreak: 'keep-all',
            }}
          >
            {isEdit ? '알레르기 정보 수정' : '알레르기가 있으신가요?'}
          </div>
          <div style={{ fontSize: 14, color: colors.textMuted, wordBreak: 'keep-all' }}>
            알레르기 재료는 레시피 추천에서 자동으로 제외돼요
          </div>
        </div>

        {error && (
          <div style={{ fontSize: 13, color: colors.allergyText, marginBottom: 14, wordBreak: 'keep-all' }}>
            {error}
          </div>
        )}
        {loading ? (
          <div style={{ fontSize: 14, color: colors.textMuted, textAlign: 'center', padding: '40px 0' }}>
            알레르기 목록을 불러오는 중이에요...
          </div>
        ) : (
          <TagPicker
            allItems={items}
            selected={selected}
            onToggle={toggle}
            searchPlaceholder="알레르기 재료를 검색해보세요"
            selectedBg={colors.navy}
            selectedColor={colors.white}
            itemLabel="알레르기"
            emptyText="아직 선택한 알레르기가 없어요"
          />
        )}

        <PrimaryButton onClick={onComplete} disabled={saving} style={{ marginTop: 6 }}>
          {saving ? '저장 중...' : isEdit ? '저장하기' : '완료'}
        </PrimaryButton>
      </div>
    </div>
  );
}
