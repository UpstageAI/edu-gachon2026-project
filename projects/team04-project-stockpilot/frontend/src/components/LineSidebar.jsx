import { Fragment, useRef, useState, useCallback, useEffect } from 'react';
import { createPortal } from 'react-dom';
import './LineSidebar.css';

const FALLOFF_CURVES = {
  linear: p => p,
  smooth: p => p * p * (3 - 2 * p),
  sharp: p => p * p * p
};

const LineSidebar = ({
  items = [],
  stars = [],
  separatorAfter = null,
  accentColor = '#34d399',
  textColor = '#c4c4c4',
  markerColor = '#6c6c6c',
  showIndex = true,
  showMarker = true,
  proximityRadius = 100,
  maxShift = 20,
  falloff = 'smooth',
  markerLength = 28,
  markerGap = 0,
  tickScale = 0.5,
  scaleTick = true,
  itemGap = 16,
  fontSize = 0.95,
  smoothing = 100,
  defaultActive = null,
  onItemClick,
  onItemDelete,
  onItemFavorite,
  className = ''
}) => {
  const listRef = useRef(null);
  const itemRefs = useRef([]);
  const targetsRef = useRef([]);
  const currentRef = useRef([]);
  const rafRef = useRef(null);
  const lastRef = useRef(0);
  const activeRef = useRef(defaultActive);
  const smoothingRef = useRef(smoothing);
  const [activeIndex, setActiveIndex] = useState(defaultActive);
  const [menu, setMenu] = useState(null); // 우클릭 메뉴 { index, x, y }

  activeRef.current = activeIndex;
  smoothingRef.current = smoothing;

  const runFrame = useCallback(now => {
    const dt = Math.min((now - lastRef.current) / 1000, 0.05);
    lastRef.current = now;
    const tau = Math.max(smoothingRef.current, 1) / 1000;
    const k = 1 - Math.exp(-dt / tau);

    let moving = false;
    const els = itemRefs.current;
    for (let i = 0; i < els.length; i++) {
      const el = els[i];
      if (!el) continue;
      const target = Math.max(targetsRef.current[i] || 0, activeRef.current === i ? 1 : 0);
      const cur = currentRef.current[i] || 0;
      const next = cur + (target - cur) * k;
      const settled = Math.abs(target - next) < 0.0015;
      const value = settled ? target : next;
      currentRef.current[i] = value;
      el.style.setProperty('--effect', value.toFixed(4));
      if (!settled) moving = true;
    }
    rafRef.current = moving ? requestAnimationFrame(runFrame) : null;
  }, []);

  const startLoop = useCallback(() => {
    if (rafRef.current != null) return;
    lastRef.current = performance.now();
    rafRef.current = requestAnimationFrame(runFrame);
  }, [runFrame]);

  const handlePointerMove = useCallback(
    e => {
      const list = listRef.current;
      if (!list) return;
      const rect = list.getBoundingClientRect();
      const pointerY = e.clientY - rect.top;
      const ease = FALLOFF_CURVES[falloff] ?? FALLOFF_CURVES.linear;
      const els = itemRefs.current;
      for (let i = 0; i < els.length; i++) {
        const el = els[i];
        if (!el) continue;
        const center = el.offsetTop + el.offsetHeight / 2;
        const distance = Math.abs(pointerY - center);
        targetsRef.current[i] = ease(Math.max(0, 1 - distance / proximityRadius));
      }
      startLoop();
    },
    [falloff, proximityRadius, startLoop]
  );

  const handlePointerLeave = useCallback(() => {
    targetsRef.current = targetsRef.current.map(() => 0);
    startLoop();
  }, [startLoop]);

  const handleItemEnter = useCallback(
    index => {
      targetsRef.current[index] = 1;
      startLoop();
    },
    [startLoop]
  );

  const handleClick = useCallback(
    (index, label) => {
      setActiveIndex(index);
      onItemClick?.(index, label);
    },
    [onItemClick]
  );

  const handleContextMenu = useCallback((e, index) => {
    e.preventDefault();
    e.stopPropagation();
    setMenu({ index, x: e.clientX, y: e.clientY });
  }, []);

  useEffect(() => {
    if (!menu) return undefined;
    const close = () => setMenu(null);
    document.addEventListener('click', close);
    document.addEventListener('scroll', close, true);
    return () => {
      document.removeEventListener('click', close);
      document.removeEventListener('scroll', close, true);
    };
  }, [menu]);

  useEffect(() => {
    startLoop();
  }, [activeIndex, startLoop]);

  useEffect(
    () => () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    },
    []
  );

  return (
    <nav
      className={`line-sidebar${showMarker ? ' line-sidebar--markers' : ''}${scaleTick ? ' line-sidebar--scale-tick' : ''}${className ? ` ${className}` : ''}`}
      style={{
        '--accent-color': accentColor,
        '--text-color': textColor,
        '--marker-color': markerColor,
        '--marker-length': `${markerLength}px`,
        '--marker-gap': `${markerGap}px`,
        '--tick-scale': tickScale,
        '--max-shift': `${maxShift}px`,
        '--item-gap': `${itemGap}px`,
        '--font-size': `${fontSize}rem`,
        '--smoothing': `${smoothing}ms`
      }}
    >
      <ul ref={listRef} className="line-sidebar__list" onPointerMove={handlePointerMove} onPointerLeave={handlePointerLeave}>
        {items.map((label, index) => (
          <Fragment key={`${label}-${index}`}>
            <li
              ref={el => {
                itemRefs.current[index] = el;
              }}
              className="line-sidebar__item"
              aria-current={activeIndex === index ? 'true' : undefined}
              onPointerEnter={() => handleItemEnter(index)}
              onClick={() => handleClick(index, label)}
              onContextMenu={e => handleContextMenu(e, index)}
            >
              {showMarker && <span className="line-sidebar__marker" aria-hidden="true" />}
              <span className="line-sidebar__label">
                {showIndex && <span className="line-sidebar__index">{String(index + 1).padStart(2, '0')}</span>}
                <span className="line-sidebar__text">{label}</span>
                {stars[index] && <span className="line-sidebar__star" aria-label="즐겨찾기">★</span>}
              </span>
            </li>
            {separatorAfter != null && index === separatorAfter - 1 && (
              <li className="line-sidebar__separator" aria-hidden="true" />
            )}
          </Fragment>
        ))}
      </ul>
      {menu &&
        createPortal(
          <div
            className="fixed z-[100] min-w-[9rem] overflow-hidden rounded-lg border border-white/15 bg-neutral-900/95 shadow-xl backdrop-blur"
            style={{ left: menu.x, top: menu.y }}
            onClick={e => e.stopPropagation()}
          >
            <button
              type="button"
              onClick={e => {
                e.stopPropagation();
                onItemFavorite?.(menu.index);
                setMenu(null);
              }}
              className="flex w-full items-center gap-2 whitespace-nowrap px-4 py-2 text-left text-sm text-yellow-300 transition-colors hover:bg-yellow-400/15"
            >
              {stars[menu.index] ? '★ 즐겨찾기 해제' : '☆ 즐겨찾기 추가'}
            </button>
            <button
              type="button"
              onClick={e => {
                e.stopPropagation();
                onItemDelete?.(menu.index);
                setMenu(null);
              }}
              className="flex w-full items-center gap-2 whitespace-nowrap px-4 py-2 text-left text-sm text-red-300 transition-colors hover:bg-red-500/20"
            >
              🗑 대화 삭제
            </button>
          </div>,
          document.body,
        )}
    </nav>
  );
};

export default LineSidebar;
