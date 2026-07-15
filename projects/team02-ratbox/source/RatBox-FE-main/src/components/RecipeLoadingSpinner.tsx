import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import iconFoodCheese from '../assets/icon-food-cheese.png';
import iconFoodBread from '../assets/icon-food-bread.png';
import iconFoodEggs from '../assets/icon-food-eggs.png';
import iconFoodFish from '../assets/icon-food-fish.png';
import iconFoodMilk from '../assets/icon-food-milk.png';
import iconFoodBanana from '../assets/icon-food-banana.png';
import { colors, shadow } from '../theme';

const LOADING_ICONS = [
  iconFoodCheese,
  iconFoodBread,
  iconFoodEggs,
  iconFoodFish,
  iconFoodMilk,
  iconFoodBanana,
];

interface RecipeLoadingSpinnerProps {
  title: string;
  subtitle: ReactNode;
}

export function RecipeLoadingSpinner({ title, subtitle }: RecipeLoadingSpinnerProps) {
  const [iconIndex, setIconIndex] = useState(0);

  useEffect(() => {
    const iconTimer = setInterval(() => {
      setIconIndex((i) => (i + 1) % LOADING_ICONS.length);
    }, 750);
    return () => clearInterval(iconTimer);
  }, []);

  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        textAlign: 'center',
        padding: '20px 24px 60px',
        maxWidth: 480,
        margin: '0 auto',
        width: '100%',
        boxSizing: 'border-box',
      }}
    >
      <div
        style={{
          width: 150,
          height: 150,
          borderRadius: 999,
          background: colors.white,
          boxShadow: shadow.cardStrong,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          marginBottom: 32,
          position: 'relative',
        }}
      >
        {LOADING_ICONS.map((icon, i) => (
          <img
            key={icon}
            src={icon}
            alt=""
            style={{
              position: 'absolute',
              width: 'auto',
              height: 'auto',
              maxWidth: 78,
              maxHeight: 70,
              opacity: i === iconIndex ? 1 : 0,
              transition: 'opacity 0.3s ease',
            }}
          />
        ))}
      </div>

      <div style={{ fontWeight: 800, fontSize: 22, color: colors.navy, marginBottom: 10, wordBreak: 'keep-all' }}>
        {title}
      </div>
      <div
        style={{
          fontSize: 14,
          color: colors.textMuted,
          lineHeight: 1.6,
          marginBottom: 22,
          wordBreak: 'keep-all',
        }}
      >
        {subtitle}
      </div>

      <div style={{ display: 'flex', gap: 8 }}>
        {[0, 0.2, 0.4].map((delay) => (
          <div
            key={delay}
            style={{
              width: 9,
              height: 9,
              borderRadius: 999,
              background: colors.teal,
              animation: 'ratboxDotPulse 1.2s infinite',
              animationDelay: `${delay}s`,
            }}
          />
        ))}
      </div>
      <style>{`
        @keyframes ratboxDotPulse {
          0%, 80%, 100% { opacity: 0.25; }
          40% { opacity: 1; }
        }
      `}</style>
    </div>
  );
}
