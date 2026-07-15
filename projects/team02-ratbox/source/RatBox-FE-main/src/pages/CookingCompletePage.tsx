import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import iconMouseComplete from '../assets/icon-mouse-complete.png';
import { PrimaryButton } from '../components/PrimaryButton';
import { getSelectedRecipe } from '../lib/storage';
import { colors } from '../theme';

export function CookingCompletePage() {
  const navigate = useNavigate();
  const [recipeName, setRecipeName] = useState('두부계란덮밥');

  useEffect(() => {
    setRecipeName(getSelectedRecipe());
    const timer = setTimeout(() => navigate('/home'), 6000);
    return () => clearTimeout(timer);
  }, [navigate]);

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        textAlign: 'center',
        background: `radial-gradient(circle at 50% 0%, ${colors.bgCard} 0%, ${colors.bg} 60%)`,
        padding: 24,
        boxSizing: 'border-box',
      }}
    >
      <div style={{ maxWidth: 420 }}>
        <img
          src={iconMouseComplete}
          alt="뚜이"
          style={{ width: 150, height: 'auto', marginBottom: 24, animation: 'ratboxCompletePop 0.6s ease' }}
        />
        <div
          style={{
            fontWeight: 800,
            fontSize: 26,
            color: colors.navy,
            marginBottom: 10,
            wordBreak: 'keep-all',
          }}
        >
          {recipeName} 완성!
        </div>
        <div
          style={{
            fontSize: 15,
            color: colors.textBody,
            lineHeight: 1.6,
            marginBottom: 34,
            wordBreak: 'keep-all',
          }}
        >
          오늘도 맛있는 한 끼 완성했어요.
          <br />
          맛있게 드세요!
        </div>
        <PrimaryButton onClick={() => navigate('/home')}>홈으로 돌아가기</PrimaryButton>
      </div>
      <style>{`
        @keyframes ratboxCompletePop {
          0% { opacity: 0; transform: scale(0.7); }
          60% { opacity: 1; transform: scale(1.06); }
          100% { opacity: 1; transform: scale(1); }
        }
      `}</style>
    </div>
  );
}
