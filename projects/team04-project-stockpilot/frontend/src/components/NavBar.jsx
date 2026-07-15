function NavBar({ username, onHome, onLoginClick, onLogout }) {
  return (
    <div className="fixed inset-x-0 top-4 z-20 px-4">
      <nav className="mx-auto flex h-14 max-w-5xl items-center justify-between rounded-2xl border border-white/15 bg-white/10 px-6 shadow-lg shadow-black/20 backdrop-blur-lg">
        <button onClick={onHome} className="font-mono text-lg font-semibold tracking-tight text-white">
          Stock<span className="text-emerald-400">Pilot</span>
        </button>
        <div className="flex items-center gap-2 text-sm sm:gap-4">
          {username ? (
            <>
              <span className="hidden text-neutral-300 sm:inline">{username}님</span>
              <button onClick={onLogout} className="rounded-lg border border-white/15 bg-white/5 px-3 py-1.5 text-neutral-200 transition-colors hover:text-white">
                로그아웃
              </button>
            </>
          ) : (
            <button onClick={onLoginClick} className="rounded-lg bg-emerald-500 px-4 py-1.5 font-semibold text-neutral-950 transition-colors hover:bg-emerald-400">
              로그인
            </button>
          )}
        </div>
      </nav>
    </div>
  )
}

export default NavBar
