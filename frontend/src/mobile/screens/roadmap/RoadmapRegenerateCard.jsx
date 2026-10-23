import React, { useState } from 'react';
import { RefreshCw } from 'lucide-react';
import BottomSheet from '../../components/BottomSheet';
import Button from '../../components/Button';
import { ROADMAP_LEVELS } from './roadmapModel';

function levelOf(value) {
  return ROADMAP_LEVELS.find((level) => level.value === value) || ROADMAP_LEVELS[1];
}

export default function RoadmapRegenerateCard({ level, onChangeLevel, isRegenerating, errorMessage, onRegenerate }) {
  const [isConfirmOpen, setConfirmOpen] = useState(false);
  const selectedLevel = levelOf(level);

  const confirmRegenerate = () => {
    onRegenerate()
      .catch(() => {})
      .finally(() => setConfirmOpen(false));
  };

  return (
    <section className="mobile-card mobile-section">
      <p className="mobile-roadmap-detail__label">로드맵 난이도</p>

      <div className="mobile-choice" role="radiogroup" aria-label="로드맵 난이도">
        {ROADMAP_LEVELS.map((option) => (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={option.value === level}
            className={option.value === level ? 'is-active' : ''}
            onClick={() => onChangeLevel(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>

      <p className="mobile-card__meta">{selectedLevel.description}</p>

      <Button fullWidth variant="secondary" isLoading={isRegenerating} onClick={() => setConfirmOpen(true)}>
        <RefreshCw size={16} />
        AI 84일 로드맵 재생성
      </Button>

      {errorMessage && <p className="mobile-auth__error mobile-roadmap__error">{errorMessage}</p>}

      <BottomSheet
        title="로드맵 재생성"
        isOpen={isConfirmOpen}
        onClose={() => {
          if (!isRegenerating) setConfirmOpen(false);
        }}
      >
        <p className="mobile-sheet__note">
          AI가 {selectedLevel.label} 난이도로 12주 × 7일(84일) 로드맵을 다시 생성합니다. 기존 로드맵은 교체됩니다.
          계속할까요?
        </p>

        <div className="mobile-actions">
          <Button variant="ghost" disabled={isRegenerating} onClick={() => setConfirmOpen(false)}>
            취소
          </Button>
          <Button isLoading={isRegenerating} onClick={confirmRegenerate}>
            재생성
          </Button>
        </div>
      </BottomSheet>
    </section>
  );
}
