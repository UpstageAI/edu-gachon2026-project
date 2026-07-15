import { useNavigate } from 'react-router-dom';
import iconFaceWindow from '../assets/icon-face-window.png';
import iconFridgeOpen from '../assets/icon-fridge-open.png';
import iconMouseCarrot from '../assets/icon-mouse-carrot.png';
import iconMouseBack from '../assets/icon-mouse-back.png';
import { NavBar } from '../components/NavBar';
import { colors, shadow } from '../theme';

export function HomePage() {
  const navigate = useNavigate();

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        background: colors.bg,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '24px 28px',
          maxWidth: 1280,
          margin: '0 auto',
          width: '100%',
          boxSizing: 'border-box',
        }}
      >
        <NavBar />
        <div
          onClick={() => navigate('/profile')}
          style={{
            width: 38,
            height: 38,
            borderRadius: 999,
            background: colors.gold,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 15,
            fontWeight: 800,
            color: colors.goldText,
            cursor: 'pointer',
          }}
        >
          뚜
        </div>
      </div>

      <div
        style={{
          flex: 1,
          padding: '16px 24px 60px',
          maxWidth: 560,
          margin: '0 auto',
          width: '100%',
          boxSizing: 'border-box',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 30 }}>
          <img
            src={iconFaceWindow}
            alt="뚜이"
            style={{ width: 56, height: 'auto', flex: '0 0 auto' }}
          />
          <div>
            <div
              style={{
                fontWeight: 800,
                fontSize: 20,
                color: colors.navy,
                marginBottom: 2,
                wordBreak: 'keep-all',
              }}
            >
              안녕하세요!
            </div>
            <div style={{ fontSize: 14, color: colors.textMuted, wordBreak: 'keep-all' }}>
              오늘은 뭐 해먹을까요?
            </div>
          </div>
        </div>

        <div
          onClick={() => navigate('/ingredients')}
          style={{
            background: colors.navy,
            borderRadius: 22,
            padding: '26px',
            display: 'flex',
            alignItems: 'center',
            gap: 20,
            cursor: 'pointer',
            marginBottom: 16,
            width: '100%',
            minHeight: 132,
            boxSizing: 'border-box',
          }}
        >
          <div
            style={{
              width: 90,
              height: 90,
              borderRadius: 999,
              background: colors.white,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flex: '0 0 auto',
            }}
          >
            <img
              src={iconFridgeOpen}
              alt="열린 냉장고"
              style={{ width: 56, height: 'auto' }}
            />
          </div>
          <div style={{ flex: 1 }}>
            <div
              style={{
                fontWeight: 800,
                fontSize: 18,
                color: colors.white,
                marginBottom: 4,
                wordBreak: 'keep-all',
              }}
            >
              냉장고 재료 선택하기
            </div>
            <div style={{ fontSize: 13, color: colors.chipTeal, wordBreak: 'keep-all' }}>
              있는 재료로 딱 맞는 레시피를 찾아드려요
            </div>
          </div>
          <span style={{ color: colors.white, fontSize: 20 }}>→</span>
        </div>

        <HomeCard
          icon={iconMouseCarrot}
          title="알레르기 정보 등록하기"
          desc="레시피 추천에서 제외할 재료를 관리해요"
          onClick={() => navigate('/allergies?edit=1')}
          style={{ marginBottom: 16 }}
        />

        <HomeCard
          icon={iconMouseBack}
          title="내 정보 수정하기"
          desc="닉네임, 비밀번호 등 계정 정보를 관리해요"
          onClick={() => navigate('/profile')}
        />
      </div>
    </div>
  );
}

function HomeCard({
  icon,
  title,
  desc,
  onClick,
  style,
}: {
  icon: string;
  title: string;
  desc: string;
  onClick: () => void;
  style?: React.CSSProperties;
}) {
  return (
    <div
      onClick={onClick}
      style={{
        background: colors.white,
        border: `2px solid ${colors.gold}`,
        borderRadius: 22,
        padding: '22px 26px',
        display: 'flex',
        alignItems: 'center',
        gap: 20,
        cursor: 'pointer',
        boxShadow: shadow.card,
        ...style,
      }}
    >
      <img src={icon} alt={title} style={{ width: 52, height: 'auto', flex: '0 0 auto' }} />
      <div style={{ flex: 1 }}>
        <div
          style={{
            fontWeight: 800,
            fontSize: 16,
            color: colors.navy,
            marginBottom: 4,
            wordBreak: 'keep-all',
          }}
        >
          {title}
        </div>
        <div style={{ fontSize: 13, color: colors.textMuted, wordBreak: 'keep-all' }}>
          {desc}
        </div>
      </div>
      <span style={{ color: colors.textFaint, fontSize: 18 }}>→</span>
    </div>
  );
}
