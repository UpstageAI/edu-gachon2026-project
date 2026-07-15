import { useNavigate } from 'react-router-dom';
import iconFace from '../assets/icon-face.png';
import { colors } from '../theme';

interface NavBarProps {
  size?: number;
  fontSize?: number;
}

export function NavBar({ size = 30, fontSize = 18 }: NavBarProps) {
  const navigate = useNavigate();

  return (
    <div
      onClick={() => navigate('/home')}
      style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}
    >
      <img src={iconFace} alt="뚜이" style={{ width: size, height: 'auto' }} />
      <span
        style={{ fontWeight: 800, fontSize, color: colors.navy }}
      >
        RatBox
      </span>
    </div>
  );
}
