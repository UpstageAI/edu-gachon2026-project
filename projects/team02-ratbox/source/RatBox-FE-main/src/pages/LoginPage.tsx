import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import iconFace from '../assets/icon-face.png';
import { PrimaryButton } from '../components/PrimaryButton';
import { useWindowWidth } from '../hooks/useWindowWidth';
import { login, signup } from '../lib/api';
import { setAuth } from '../lib/storage';
import { colors, shadow } from '../theme';

export function LoginPage() {
  const navigate = useNavigate();
  const width = useWindowWidth();
  const mobile = width < 480;

  const [mode, setMode] = useState<'login' | 'signup'>('login');
  const [userId, setUserId] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const isSignup = mode === 'signup';

  const onSubmit = async () => {
    if (submitting) return;
    if (!userId.trim() || !password.trim() || (isSignup && !name.trim())) {
      setError('모든 항목을 입력해주세요.');
      return;
    }
    setError('');
    setSubmitting(true);
    try {
      if (isSignup) {
        await signup(userId.trim(), password, name.trim());
      }
      const result = await login(userId.trim(), password);
      setAuth({ accessToken: result.access_token, user: result.user });
      navigate(isSignup ? '/allergies' : '/home');
    } catch (err) {
      setError(err instanceof Error ? err.message : '요청에 실패했어요. 다시 시도해주세요.');
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
        alignItems: 'center',
        justifyContent: 'center',
        background: `radial-gradient(circle at 50% 0%, ${colors.bgCard} 0%, ${colors.bg} 60%)`,
        padding: '40px 20px',
        boxSizing: 'border-box',
      }}
    >
      <div
        onClick={() => navigate('/')}
        style={{
          alignSelf: 'center',
          marginBottom: 22,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          cursor: 'pointer',
        }}
      >
        <img src={iconFace} alt="뚜이" style={{ width: 30, height: 'auto' }} />
        <span style={{ fontWeight: 800, fontSize: 18, color: colors.navy }}>
          RatBox
        </span>
      </div>

      <div
        style={{
          width: '100%',
          maxWidth: 400,
          background: colors.white,
          borderRadius: 24,
          padding: mobile ? '28px 22px' : '38px 36px',
          boxShadow: shadow.cardXStrong,
          boxSizing: 'border-box',
        }}
      >
        <div style={{ textAlign: 'center', marginBottom: 26 }}>
          <div
            style={{
              fontWeight: 800,
              fontSize: 24,
              color: colors.navy,
              marginBottom: 6,
              wordBreak: 'keep-all',
            }}
          >
            {isSignup ? '반가워요, 뚜이랑 시작해요' : '만나서 반가워요!'}
          </div>
          <div
            style={{ fontSize: 14, color: colors.textMuted, wordBreak: 'keep-all' }}
          >
            {isSignup
              ? '몇 가지만 입력하면 바로 시작할 수 있어요'
              : '냉장고 속 재료로 오늘 뭐 해먹을지 알려드려요'}
          </div>
        </div>

        {isSignup && (
          <div style={{ marginBottom: 14 }}>
            <label
              style={{
                display: 'block',
                fontSize: 13,
                fontWeight: 700,
                color: colors.navy,
                marginBottom: 6,
              }}
            >
              이름
            </label>
            <input
              type="text"
              placeholder="이름을 입력해주세요"
              value={name}
              onChange={(e) => setName(e.target.value)}
              style={inputStyle}
            />
          </div>
        )}

        <div style={{ marginBottom: 14 }}>
          <label style={labelStyle}>아이디</label>
          <input
            type="text"
            placeholder="아이디를 입력해주세요"
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            style={inputStyle}
          />
        </div>

        <div style={{ marginBottom: isSignup ? 14 : 22 }}>
          <label style={labelStyle}>비밀번호</label>
          <input
            type="password"
            placeholder="8자 이상"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={inputStyle}
          />
        </div>

        {!isSignup && (
          <div style={{ textAlign: 'right', marginBottom: 22 }}>
            <span style={{ fontSize: 13, color: colors.textMuted, cursor: 'pointer' }}>
              비밀번호를 잊으셨나요?
            </span>
          </div>
        )}

        {error && (
          <div style={{ fontSize: 13, color: colors.allergyText, marginBottom: 14, wordBreak: 'keep-all' }}>
            {error}
          </div>
        )}

        <PrimaryButton onClick={onSubmit} disabled={submitting}>
          {submitting ? '처리 중...' : isSignup ? '회원가입' : '로그인'}
        </PrimaryButton>

        <div
          style={{
            textAlign: 'center',
            marginTop: 22,
            fontSize: 14,
            color: colors.textBody,
          }}
        >
          {isSignup ? '이미 계정이 있으신가요?' : '계정이 없으신가요?'}{' '}
          <span
            onClick={() => setMode(isSignup ? 'login' : 'signup')}
            style={{ fontWeight: 800, color: colors.teal, cursor: 'pointer' }}
          >
            {isSignup ? '로그인' : '회원가입'}
          </span>
        </div>
      </div>
    </div>
  );
}

const labelStyle = {
  display: 'block' as const,
  fontSize: 13,
  fontWeight: 700 as const,
  color: colors.navy,
  marginBottom: 6,
};

const inputStyle = {
  width: '100%',
  boxSizing: 'border-box' as const,
  border: `1.5px solid ${colors.border}`,
  borderRadius: 12,
  padding: '13px 14px',
  fontSize: 15,
  fontFamily: "'Noto Sans KR', sans-serif",
  outline: 'none',
  color: colors.navy,
};
