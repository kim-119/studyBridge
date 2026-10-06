import { useEffect, useState } from 'react';

function coveredBottomOf(viewport) {
  const covered = window.innerHeight - (viewport.height + viewport.offsetTop);
  return covered > 1 ? Math.round(covered) : 0;
}

export function useKeyboardInset() {
  const [inset, setInset] = useState(0);

  useEffect(() => {
    const viewport = window.visualViewport;
    if (!viewport) return undefined;

    const update = () => setInset(coveredBottomOf(viewport));
    update();
    viewport.addEventListener('resize', update);
    viewport.addEventListener('scroll', update);

    return () => {
      viewport.removeEventListener('resize', update);
      viewport.removeEventListener('scroll', update);
    };
  }, []);

  return inset;
}
