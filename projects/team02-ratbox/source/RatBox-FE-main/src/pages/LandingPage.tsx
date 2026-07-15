import { useNavigate } from 'react-router-dom';
import mascot from '../assets/mascot-transparent.png';
import iconFridgeOpen from '../assets/icon-fridge-open.png';
import iconMouseCarrot from '../assets/icon-mouse-carrot.png';
import { NavBar } from '../components/NavBar';
import { useWindowWidth } from '../hooks/useWindowWidth';
import { colors } from '../theme';

export function LandingPage() {
  const navigate = useNavigate();
  const width = useWindowWidth();
  const mobile = width < 640;
  const tablet = width >= 640 && width < 980;

  const navPadding = mobile ? '18px 20px' : tablet ? '22px 40px' : '28px 80px';
  const navBtnPadding = mobile ? '9px 18px' : '11px 24px';
  const heroPadding = mobile
    ? '28px 24px 36px 24px'
    : tablet
      ? '36px 50px 44px 50px'
      : '40px 70px 50px 70px';
  const heroTitleSize = mobile ? '30px' : tablet ? '38px' : '48px';
  const heroSubSize = mobile ? '14px' : '16px';
  const heroMascotBox = mobile ? '160px' : tablet ? '190px' : '220px';
  const heroMascotImg = mobile ? '135px' : tablet ? '165px' : '190px';
  const previewPadding = mobile
    ? '10px 20px 40px 20px'
    : tablet
      ? '10px 40px 60px 40px'
      : '10px 70px 70px 70px';

  const goToLogin = () => navigate('/login');

  const features = [
    {
      icon: iconFridgeOpen,
      title: '있는 재료만 콕콕',
      desc: '재료를 체크하면 뚜이가 레시피를 찾아요',
    },
    {
      number: 3,
      title: '딱 맞는 후보 3가지',
      desc: '부족한 재료가 적은 순으로 추천해요',
    },
    {
      icon: iconMouseCarrot,
      title: '조리 중에도 뚜이 호출',
      desc: '말로 물어보면 바로 대체재를 알려줘요',
    },
  ];

  return (
    <div style={{ background: colors.bg, minHeight: '100vh' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: navPadding,
          maxWidth: 1280,
          margin: '0 auto',
        }}
      >
        <NavBar size={32} fontSize={19} />
        <div
          onClick={goToLogin}
          style={{
            display: 'inline-block',
            background: colors.navy,
            color: colors.white,
            fontWeight: 700,
            fontSize: 14,
            padding: navBtnPadding,
            borderRadius: 999,
            whiteSpace: 'nowrap',
            cursor: 'pointer',
          }}
        >
          시작하기
        </div>
      </div>

      <div
        style={{
          padding: heroPadding,
          textAlign: 'center',
          background: `radial-gradient(circle at 50% 0%, ${colors.bgCard} 0%, ${colors.bg} 65%)`,
          maxWidth: 1280,
          margin: '0 auto',
        }}
      >
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 8,
            background: colors.gold,
            color: colors.goldText,
            fontWeight: 800,
            fontSize: 13,
            padding: '8px 18px',
            borderRadius: 999,
            marginBottom: 20,
          }}
        >
          AI 요리 비서
        </div>
        <div
          style={{
            fontFamily: "'Noto Sans KR', sans-serif",
            fontWeight: 800,
            fontSize: heroTitleSize,
            lineHeight: 1.32,
            color: colors.navy,
            marginBottom: 14,
            wordBreak: 'keep-all',
          }}
        >
          뭐 해먹지 고민될 땐,
          <br />
          뚜이한테 물어봐요
        </div>
        <div
          style={{
            fontSize: heroSubSize,
            color: colors.textBody,
            marginBottom: 26,
            wordBreak: 'keep-all',
          }}
        >
          냉장고 속 재료만 골라도, 딱 맞는 레시피와 대체재까지!
        </div>
        <div
          style={{
            width: heroMascotBox,
            height: heroMascotBox,
            margin: '0 auto 18px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <img
            src={mascot}
            alt="뚜이"
            style={{ width: heroMascotImg, height: 'auto' }}
          />
        </div>
      </div>

      <div style={{ maxWidth: 1280, margin: '0 auto', padding: previewPadding }}>
        <div
          style={{
            textAlign: 'center',
            fontSize: 14,
            fontWeight: 700,
            color: colors.textMuted,
            marginBottom: 18,
          }}
        >
          이렇게 사용해요
        </div>
        <div
          style={{
            display: mobile ? 'flex' : 'grid',
            flexDirection: 'column',
            gridTemplateColumns: mobile ? 'none' : '1fr 1fr 1fr',
            gap: 16,
          }}
        >
          {features.map((f) => (
            <div
              key={f.title}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 16,
                background: colors.bgCard,
                borderRadius: 20,
                padding: '20px 22px',
              }}
            >
              {f.icon ? (
                <img
                  src={f.icon}
                  alt={f.title}
                  style={{ width: 52, height: 'auto', flex: '0 0 auto' }}
                />
              ) : (
                <div
                  style={{
                    width: 52,
                    height: 52,
                    borderRadius: 16,
                    background: colors.gold,
                    flex: '0 0 auto',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: 22,
                    fontWeight: 800,
                    color: colors.goldText,
                  }}
                >
                  {f.number}
                </div>
              )}
              <div>
                <div
                  style={{
                    fontWeight: 800,
                    fontSize: 15,
                    color: colors.navy,
                    marginBottom: 4,
                    wordBreak: 'keep-all',
                  }}
                >
                  {f.title}
                </div>
                <div
                  style={{
                    fontSize: 13,
                    color: colors.textBody,
                    wordBreak: 'keep-all',
                  }}
                >
                  {f.desc}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 10,
          padding: '20px 0 50px',
        }}
      >
        <div style={{ color: colors.textMuted, fontSize: 13 }}>© 2026 RatBox</div>
      </div>
    </div>
  );
}
