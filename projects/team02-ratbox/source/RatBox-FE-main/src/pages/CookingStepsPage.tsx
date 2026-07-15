import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { PrimaryButton } from '../components/PrimaryButton';
import { useVoiceRecorder } from '../hooks/useVoiceRecorder';
import { askTuiStream } from '../lib/askTuiStream';
import { recommend } from '../lib/api';
import { transcribeAudio } from '../lib/googleStt';
import {
  getAllergies,
  getIngredients,
  getSelectedRecipe,
  getSelectedRecipeId,
} from '../lib/storage';
import { colors, shadow } from '../theme';

interface CookingStepsNavState {
  steps?: string[];
  name?: string;
}

export function CookingStepsPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const navState = (location.state as CookingStepsNavState | null) ?? null;
  const [recipeName, setRecipeName] = useState(navState?.name ?? getSelectedRecipe());
  const [steps, setSteps] = useState<string[]>(navState?.steps ?? []);
  const [stepIndex, setStepIndex] = useState(0);
  const [question, setQuestion] = useState('');
  const [isAsking, setIsAsking] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [lastQuestion, setLastQuestion] = useState('');
  const [lastAnswer, setLastAnswer] = useState('');
  const [micError, setMicError] = useState('');
  const recorder = useVoiceRecorder();

  useEffect(() => {
    if (navState?.steps?.length) return;

    const ingredientIds = getIngredients().map((i) => i.id);
    const allergenIds = getAllergies().selected.map((a) => a.id);
    const recipeId = getSelectedRecipeId();

    recommend(ingredientIds, allergenIds, recipeId)
      .then((result) => {
        if (!result.detail) return;
        setRecipeName(result.detail.name);
        setSteps(result.detail.cooking_steps);
      })
      .catch(() => {
        // 조리 단계를 못 불러와도 화면은 유지하고, 아래 질문 기능은 계속 쓸 수 있게 둔다.
      });
  }, [navState]);

  const total = steps.length || 1;
  const isLast = stepIndex >= total - 1;

  const resetAsk = () => {
    setLastAnswer('');
    setLastQuestion('');
    setMicError('');
    setIsAsking(false);
    setIsStreaming(false);
  };

  const nextStep = () => {
    if (isLast) {
      navigate('/cooking/complete');
    } else {
      setStepIndex((i) => i + 1);
      resetAsk();
    }
  };

  const prevStep = () => {
    setStepIndex((i) => Math.max(0, i - 1));
    resetAsk();
  };

  const onAsk = async (text?: string) => {
    const q = (text ?? question).trim();
    if (!q || isStreaming) return;
    setQuestion('');
    setLastQuestion(q);
    setLastAnswer('');
    setIsAsking(true);
    setIsStreaming(true);
    try {
      const context = {
        recipeId: getSelectedRecipeId(),
        allergenIds: getAllergies().selected.map((a) => a.id),
        currentStepText: steps[stepIndex],
      };
      await askTuiStream(q, context, (textSoFar) => {
        setIsAsking(false);
        setLastAnswer(textSoFar);
      });
    } catch (err) {
      setLastAnswer(err instanceof Error ? err.message : '답변을 가져오지 못했어요. 다시 시도해주세요.');
    } finally {
      setIsAsking(false);
      setIsStreaming(false);
    }
  };

  const onMicClick = async () => {
    setMicError('');
    if (recorder.status === 'recording') {
      const audioBlob = await recorder.stop();
      try {
        const transcript = await transcribeAudio(audioBlob);
        recorder.reset();
        await onAsk(transcript);
      } catch (err) {
        recorder.reset();
        setMicError(err instanceof Error ? err.message : '음성 인식에 실패했어요.');
      }
      return;
    }

    if (!window.isSecureContext) {
      setMicError('마이크는 HTTPS 환경에서만 사용할 수 있어요.');
      return;
    }

    try {
      await recorder.start();
    } catch (err) {
      if (err instanceof DOMException && err.name === 'NotFoundError') {
        setMicError('마이크를 찾을 수 없어요. 장치를 확인해주세요.');
      } else {
        setMicError('마이크 권한을 확인해주세요.');
      }
    }
  };

  return (
    <div className="ratbox-cooking-steps-shell" style={{ display: 'flex', flexDirection: 'column', background: colors.bg }}>
      <div
        style={{
          flex: '0 0 auto',
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
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <div
            onClick={() => navigate('/recipes/detail')}
            style={{ fontSize: 20, color: colors.navy, cursor: 'pointer', lineHeight: 1 }}
          >
            ←
          </div>
          <span style={{ fontWeight: 800, fontSize: 17, color: colors.navy }}>{recipeName}</span>
        </div>
        <span style={{ fontSize: 13, fontWeight: 700, color: colors.textMuted }}>
          {stepIndex + 1} / {total}단계
        </span>
      </div>

      <div
        style={{
          flex: '0 0 auto',
          maxWidth: 560,
          margin: '0 auto',
          width: '100%',
          padding: '0 28px',
          boxSizing: 'border-box',
        }}
      >
        <div style={{ height: 6, borderRadius: 999, background: colors.bgCard, overflow: 'hidden' }}>
          <div
            style={{
              height: '100%',
              width: `${((stepIndex + 1) / total) * 100}%`,
              background: colors.gold,
              borderRadius: 999,
              transition: 'width 0.3s ease',
            }}
          />
        </div>
      </div>

      <div
        style={{
          flex: '1 1 auto',
          minHeight: 0,
          overflowY: 'auto',
          WebkitOverflowScrolling: 'touch',
          padding: '26px 24px 12px',
          maxWidth: 560,
          margin: '0 auto',
          width: '100%',
          boxSizing: 'border-box',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <div
          style={{
            background: colors.white,
            borderRadius: 22,
            padding: '32px 26px',
            textAlign: 'center',
            boxShadow: shadow.card,
            marginBottom: 24,
          }}
        >
          <div
            style={{
              width: 56,
              height: 56,
              borderRadius: 999,
              background: colors.gold,
              color: colors.goldText,
              fontWeight: 800,
              fontSize: 22,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              margin: '0 auto 20px',
            }}
          >
            {stepIndex + 1}
          </div>
          <div style={{ fontSize: 19, fontWeight: 700, color: colors.navy, lineHeight: 1.6, wordBreak: 'keep-all' }}>
            {steps[stepIndex] || ''}
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10, marginBottom: 22 }}>
          <div
            onClick={recorder.status === 'processing' ? undefined : onMicClick}
            role="button"
            aria-label={recorder.status === 'recording' ? '녹음 중지 및 질문하기' : '뚜이에게 질문하기'}
            style={{
              width: 64,
              height: 64,
              borderRadius: 999,
              background: recorder.status === 'recording' ? colors.allergyText : colors.teal,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: recorder.status === 'processing' ? 'default' : 'pointer',
              opacity: recorder.status === 'processing' ? 0.6 : 1,
              animation:
                recorder.status === 'recording' ? 'ratboxMicPulse 1s infinite' : 'ratboxMicPulse 2.4s infinite',
            }}
          >
            <div style={{ position: 'relative', width: 20, height: 28 }}>
              <div
                style={{
                  position: 'absolute',
                  left: '50%',
                  top: 0,
                  width: 12,
                  height: 20,
                  borderRadius: 6,
                  background: colors.white,
                  transform: 'translateX(-50%)',
                }}
              />
              <div
                style={{
                  position: 'absolute',
                  left: '50%',
                  bottom: 0,
                  width: 22,
                  height: 2.5,
                  borderRadius: 2,
                  background: colors.white,
                  transform: 'translateX(-50%)',
                }}
              />
            </div>
          </div>
          <div style={{ fontSize: 13, color: colors.textMuted, wordBreak: 'keep-all' }}>
            {recorder.status === 'recording'
              ? '녹음 중이에요. 다시 누르면 질문이 전송돼요'
              : recorder.status === 'processing'
                ? '음성을 인식하는 중이에요...'
                : '궁금한 점이 있으면 눌러서 물어보세요'}
          </div>
          {micError && (
            <div style={{ fontSize: 12, color: colors.allergyText, wordBreak: 'keep-all', textAlign: 'center' }}>
              {micError}
            </div>
          )}
        </div>
        <style>{`
          @keyframes ratboxMicPulse {
            0%, 100% { box-shadow: 0 0 0 0 rgba(242,187,85,0.45); }
            50% { box-shadow: 0 0 0 12px rgba(242,187,85,0); }
          }
          @keyframes ratboxDotPulse2 {
            0%, 80%, 100% { opacity: 0.25; }
            40% { opacity: 1; }
          }
          @keyframes ratboxCursorBlink {
            0%, 100% { opacity: 1; }
            50% { opacity: 0; }
          }
        `}</style>

        <div
          style={{
            background: colors.white,
            borderRadius: 18,
            padding: '18px 20px',
            marginBottom: 22,
            boxShadow: shadow.card,
          }}
        >
          {lastQuestion && (
            <div style={{ background: colors.bgCard, borderRadius: 14, padding: '12px 14px', marginBottom: 12 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: colors.textMuted, marginBottom: 4 }}>내 질문</div>
              <div style={{ fontSize: 14, color: colors.navy, marginBottom: 10 }}>{lastQuestion}</div>
              <div style={{ fontSize: 12, fontWeight: 700, color: colors.teal, marginBottom: 4 }}>뚜이의 답변</div>
              {isAsking && !lastAnswer ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0' }}>
                  <div style={{ display: 'flex', gap: 6 }}>
                    {[0, 0.2, 0.4].map((delay) => (
                      <div
                        key={delay}
                        style={{
                          width: 8,
                          height: 8,
                          borderRadius: 999,
                          background: colors.teal,
                          animation: 'ratboxDotPulse2 1.2s infinite',
                          animationDelay: `${delay}s`,
                        }}
                      />
                    ))}
                  </div>
                  <span style={{ fontSize: 13, color: colors.textMuted }}>뚜이가 생각하는 중..</span>
                </div>
              ) : (
                <div
                  style={{
                    fontSize: 14,
                    color: colors.navy,
                    lineHeight: 1.6,
                    wordBreak: 'keep-all',
                    whiteSpace: 'pre-wrap',
                  }}
                >
                  {lastAnswer}
                  {isStreaming && (
                    <span
                      style={{
                        display: 'inline-block',
                        width: 8,
                        height: 14,
                        marginLeft: 2,
                        background: colors.teal,
                        verticalAlign: 'text-bottom',
                        animation: 'ratboxCursorBlink 0.8s step-end infinite',
                      }}
                    />
                  )}
                </div>
              )}
            </div>
          )}
          <div
            style={{
              display: 'flex',
              gap: 8,
              opacity: isStreaming ? 0.5 : 1,
              pointerEvents: isStreaming ? 'none' : 'auto',
            }}
          >
            <input
              type="text"
              placeholder="마이크 대신 직접 입력해서 물어봐도 돼요"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') onAsk();
              }}
              style={{
                flex: 1,
                minWidth: 0,
                boxSizing: 'border-box',
                border: `1.5px solid ${colors.border}`,
                borderRadius: 12,
                padding: '12px 14px',
                fontSize: 14,
                fontFamily: "'Noto Sans KR', sans-serif",
                outline: 'none',
                color: colors.navy,
              }}
            />
            <div
              onClick={() => onAsk()}
              style={{
                flex: '0 0 auto',
                background: colors.navy,
                color: colors.white,
                fontWeight: 700,
                fontSize: 14,
                padding: '12px 18px',
                borderRadius: 12,
                cursor: 'pointer',
              }}
            >
              전송
            </div>
          </div>
        </div>

      </div>

      <div
        style={{
          flex: '0 0 auto',
          maxWidth: 560,
          margin: '0 auto',
          width: '100%',
          padding: '12px 24px calc(18px + env(safe-area-inset-bottom, 0px))',
          boxSizing: 'border-box',
          background: colors.bg,
          borderTop: `1px solid ${colors.border}`,
        }}
      >
        <div style={{ display: 'flex', gap: 10 }}>
          {stepIndex > 0 && (
            <div
              onClick={prevStep}
              style={{
                flex: '0 0 auto',
                background: colors.bgCard,
                color: colors.textBody,
                fontWeight: 700,
                fontSize: 15,
                padding: '15px 22px',
                borderRadius: 999,
                textAlign: 'center',
                cursor: 'pointer',
              }}
            >
              이전
            </div>
          )}
          <PrimaryButton onClick={nextStep} style={{ flex: 1 }}>
            {isLast ? '요리 완료' : '다음 단계'}
          </PrimaryButton>
        </div>
      </div>
      <style>{`
        .ratbox-cooking-steps-shell {
          height: 100vh;
          height: 100dvh;
        }
      `}</style>
    </div>
  );
}
