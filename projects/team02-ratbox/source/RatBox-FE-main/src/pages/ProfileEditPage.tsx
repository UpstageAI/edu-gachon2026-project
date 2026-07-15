import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import iconMouseBack from '../assets/icon-mouse-back.png';
import { PrimaryButton } from '../components/PrimaryButton';
import { logout } from '../lib/api';
import { clearAuth, getAuth } from '../lib/storage';
import { colors } from '../theme';

export function ProfileEditPage() {
  const navigate = useNavigate();
  const auth = getAuth();
  const [name, setName] = useState(auth?.user.name ?? '뚜이친구');
  const [userId] = useState(auth?.user.username ?? 'ratbox_user');
  const [newPassword, setNewPassword] = useState('');
  const [newPasswordConfirm, setNewPasswordConfirm] = useState('');
  const [loggingOut, setLoggingOut] = useState(false);

  const goHome = () => navigate('/home');

  const onLogout = async () => {
    if (loggingOut) return;
    setLoggingOut(true);
    try {
      await logout();
    } finally {
      clearAuth();
      navigate('/');
    }
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 14,
          padding: '24px 28px 8px 28px',
          maxWidth: 480,
          margin: '0 auto',
          width: '100%',
          boxSizing: 'border-box',
        }}
      >
        <div onClick={goHome} style={{ fontSize: 20, color: colors.navy, cursor: 'pointer', lineHeight: 1 }}>
          ←
        </div>
        <span style={{ fontWeight: 800, fontSize: 17, color: colors.navy }}>내 정보 수정</span>
      </div>

      <div
        style={{
          flex: 1,
          padding: '20px 24px 40px',
          maxWidth: 480,
          margin: '0 auto',
          width: '100%',
          boxSizing: 'border-box',
        }}
      >
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <img src={iconMouseBack} alt="뚜이" style={{ width: 88, height: 'auto' }} />
        </div>

        <div style={{ marginBottom: 14 }}>
          <label style={labelStyle}>닉네임</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            style={inputStyle}
          />
        </div>

        <div style={{ marginBottom: 20 }}>
          <label style={labelStyle}>아이디</label>
          <input
            type="text"
            value={userId}
            disabled
            style={{ ...inputStyle, color: colors.textFaint, background: colors.bg }}
          />
        </div>

        <div style={{ height: 1, background: colors.bgCard, margin: '8px 0 20px' }} />

        <div style={{ marginBottom: 14 }}>
          <label style={labelStyle}>새 비밀번호</label>
          <input
            type="password"
            placeholder="변경하지 않으면 비워두세요"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            style={inputStyle}
          />
        </div>

        <div style={{ marginBottom: 28 }}>
          <label style={labelStyle}>새 비밀번호 확인</label>
          <input
            type="password"
            placeholder="한 번 더 입력해주세요"
            value={newPasswordConfirm}
            onChange={(e) => setNewPasswordConfirm(e.target.value)}
            style={inputStyle}
          />
        </div>

        <PrimaryButton onClick={goHome} style={{ marginBottom: 14 }}>
          저장하기
        </PrimaryButton>
        <PrimaryButton onClick={goHome} variant="text" style={{ marginBottom: 14 }}>
          취소
        </PrimaryButton>

        <div style={{ height: 1, background: colors.bgCard, margin: '4px 0 18px' }} />

        <PrimaryButton
          onClick={onLogout}
          variant="text"
          disabled={loggingOut}
          style={{ color: colors.allergyText }}
        >
          {loggingOut ? '로그아웃 중...' : '로그아웃'}
        </PrimaryButton>
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
  background: colors.white,
};
