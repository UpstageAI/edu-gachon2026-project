import { useState } from 'react'

import Stepper, { Step } from './Stepper'
import { loginUser, registerUser } from '../lib/api'

const inputCls =
  'mt-2 w-full rounded-xl border border-white/15 bg-white/10 px-4 py-2.5 text-white placeholder-neutral-400 outline-none focus:border-emerald-400/50'

function AuthModal({ onClose, onAuthed }) {
  const [mode, setMode] = useState('login') // 'login' | 'signup'
  const [error, setError] = useState('')

  // 로그인
  const [loginId, setLoginId] = useState('')
  const [loginPw, setLoginPw] = useState('')

  // 회원가입 (단계별 입력값은 여기서 유지)
  const [suId, setSuId] = useState('')
  const [suPw, setSuPw] = useState('')
  const [suPw2, setSuPw2] = useState('')
  const [stepperKey, setStepperKey] = useState(0)

  async function handleLogin(e) {
    e.preventDefault()
    setError('')
    try {
      const r = await loginUser(loginId.trim(), loginPw)
      onAuthed(r.username)
    } catch (err) {
      setError(err.message)
    }
  }

  // 각 단계 입력 검증 — 통과해야 '다음/가입 완료' 진행
  function validateSignupStep(step) {
    if (step === 1) {
      if (suId.trim().length < 2) { setError('아이디를 2자 이상 입력해주세요.'); return false }
    } else if (step === 2) {
      if (suPw.length < 4) { setError('비밀번호는 4자 이상이어야 해요.'); return false }
    } else if (step === 3) {
      if (suPw2.length < 1) { setError('비밀번호 확인을 입력해주세요.'); return false }
    }
    setError('')
    return true
  }

  async function handleSignupComplete() {
    setError('')
    if (suPw !== suPw2) return failSignup('비밀번호가 일치하지 않아요.')
    try {
      const r = await registerUser(suId.trim(), suPw)
      onAuthed(r.username)
    } catch (err) {
      failSignup(err.message)
    }
  }

  function failSignup(msg) {
    setError(msg)
    setStepperKey((k) => k + 1) // 스텝을 1단계로 되돌림(입력값은 유지)
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm animate-fade-in"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-2xl border border-white/15 bg-neutral-900/90 p-6 shadow-2xl backdrop-blur-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-5 flex gap-2 rounded-xl bg-white/5 p-1">
          {['login', 'signup'].map((m) => (
            <button
              key={m}
              onClick={() => { setMode(m); setError('') }}
              className={`flex-1 rounded-lg py-2 text-sm font-semibold transition-colors ${
                mode === m ? 'bg-emerald-500 text-neutral-950' : 'text-neutral-300 hover:text-white'
              }`}
            >
              {m === 'login' ? '로그인' : '회원가입'}
            </button>
          ))}
        </div>

        {error && (
          <p className="mb-3 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-300">{error}</p>
        )}

        {mode === 'login' ? (
          <form onSubmit={handleLogin} className="space-y-3">
            <div>
              <label className="text-sm text-neutral-300">아이디</label>
              <input className={inputCls} value={loginId} onChange={(e) => setLoginId(e.target.value)} placeholder="아이디" />
            </div>
            <div>
              <label className="text-sm text-neutral-300">비밀번호</label>
              <input className={inputCls} type="password" value={loginPw} onChange={(e) => setLoginPw(e.target.value)} placeholder="비밀번호" />
            </div>
            <button type="submit" className="mt-2 w-full rounded-xl bg-emerald-500 py-2.5 font-semibold text-neutral-950 transition-colors hover:bg-emerald-400">
              로그인
            </button>
          </form>
        ) : (
          <Stepper
            key={stepperKey}
            backButtonText="이전"
            nextButtonText="다음"
            completeButtonText="가입 완료"
            disableStepIndicators={true}
            validateStep={validateSignupStep}
            onFinalStepCompleted={handleSignupComplete}
          >
            <Step>
              <h3 className="text-lg font-semibold text-white">아이디를 정해주세요</h3>
              <input className={inputCls} value={suId} onChange={(e) => setSuId(e.target.value)} placeholder="아이디 (2자 이상)" />
            </Step>
            <Step>
              <h3 className="text-lg font-semibold text-white">비밀번호를 입력하세요</h3>
              <input className={inputCls} type="password" value={suPw} onChange={(e) => setSuPw(e.target.value)} placeholder="비밀번호 (4자 이상)" />
            </Step>
            <Step>
              <h3 className="text-lg font-semibold text-white">비밀번호를 한 번 더</h3>
              <input className={inputCls} type="password" value={suPw2} onChange={(e) => setSuPw2(e.target.value)} placeholder="비밀번호 확인" />
            </Step>
          </Stepper>
        )}
      </div>
    </div>
  )
}

export default AuthModal
