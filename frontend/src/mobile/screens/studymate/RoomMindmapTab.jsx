import React, { useMemo, useState } from 'react';
import { ArrowLeft, LayoutGrid, Save } from 'lucide-react';
import LegacyMindMapView from '../../../components/graph/LegacyMindMapView';
import { EmptyState, ErrorState } from '../../components/ScreenState';
import { materialService } from '../../../services/api';
import { convertMindMapToObsidianGraph } from '../../../utils/graph/mindmapToObsidianGraph';
import { useSubmit } from '../../data/useAsync';
import MindmapExplorer from '../mindmap/MindmapExplorer';
import SemanticStatusNotice from '../mindmap/SemanticStatusNotice';
import { buildMindmapArchivePayload } from '../mindmap/mindmapArchive';
import { buildMindmapView } from '../mindmap/mindmapModel';
import { useSemanticRoomGraph } from '../mindmap/useSemanticRoomGraph';
import { latestUserQuestion, mindmapSourceMessages } from './chatMessages';
import './studymateAgents.css';

const LEGACY_VIEW_OPEN_LABEL = 'Legacy 카드 보기';
const LEGACY_VIEW_CLOSE_LABEL = '마인드맵 보기';

function useLiveMindmap({ roomId, roomAgents, messages, interactions }) {
  const base = useMemo(() => {
    const question = latestUserQuestion(messages);
    const sourceMessages = mindmapSourceMessages(messages);
    const baseGraph = convertMindMapToObsidianGraph({
      question,
      agents: roomAgents,
      messages: sourceMessages,
      interactions,
    });
    return { question, sourceMessages, baseGraph };
  }, [interactions, messages, roomAgents]);

  const semantic = useSemanticRoomGraph({
    roomId: base.question ? roomId : null,
    question: base.question,
    messages: base.sourceMessages,
    agents: roomAgents,
    baseGraph: base.baseGraph,
  });
  const view = useMemo(() => buildMindmapView(semantic.graph), [semantic.graph]);

  return { ...base, ...semantic, view };
}

function LegacyViewToggle({ isLegacyOpen, onToggle }) {
  return (
    <button
      type="button"
      className="mobile-button mobile-button--secondary mobile-room-mindmap__view-toggle"
      aria-pressed={isLegacyOpen}
      onClick={onToggle}
    >
      {isLegacyOpen ? <ArrowLeft size={16} /> : <LayoutGrid size={16} />}
      {isLegacyOpen ? LEGACY_VIEW_CLOSE_LABEL : LEGACY_VIEW_OPEN_LABEL}
    </button>
  );
}

function LegacyCardView({ question, roomAgents, sourceMessages, interactions }) {
  return (
    <div className="mobile-room-mindmap__legacy">
      <LegacyMindMapView question={question} agents={roomAgents} messages={sourceMessages} interactions={interactions} />
    </div>
  );
}

function SaveButton({ save, isSaved, isWaitingForConcepts }) {
  return (
    <button
      type="button"
      className="mobile-button mobile-button--secondary mobile-mindmap-explorer__save"
      disabled={save.isSubmitting || isWaitingForConcepts}
      onClick={() => save.submit().catch(() => {})}
    >
      <Save size={16} />
      {save.isSubmitting ? '저장 중…' : isSaved ? '저장됨' : '저장'}
    </button>
  );
}

export default function RoomMindmapTab({ roomId, roomAgents, messages, interactions }) {
  const { question, sourceMessages, graph, view, semanticState, semanticReason, retrySemantic } = useLiveMindmap({
    roomId,
    roomAgents,
    messages,
    interactions,
  });
  const [savedGraph, setSavedGraph] = useState(null);
  const [isLegacyOpen, setLegacyOpen] = useState(false);

  const save = useSubmit(async () => {
    await materialService.saveMindMap(buildMindmapArchivePayload(graph, question));
    setSavedGraph(graph);
  });

  if (!question) {
    return <EmptyState message="질문을 보내면 교수님들의 답변이 마인드맵으로 정리됩니다." />;
  }

  const toggle = <LegacyViewToggle isLegacyOpen={isLegacyOpen} onToggle={() => setLegacyOpen((open) => !open)} />;

  if (isLegacyOpen) {
    return (
      <div className="mobile-room-mindmap">
        <div className="mobile-room-mindmap__view-bar">{toggle}</div>
        <LegacyCardView
          question={question}
          roomAgents={roomAgents}
          sourceMessages={sourceMessages}
          interactions={interactions}
        />
      </div>
    );
  }

  return (
    <div className="mobile-room-mindmap">
      <div className="mobile-room-mindmap__view-bar">{toggle}</div>
      <SemanticStatusNotice state={semanticState} reason={semanticReason} onRetry={retrySemantic} />
      {save.errorMessage && <p className="mobile-auth__error">마인드맵 저장 실패: {save.errorMessage}</p>}
      {view?.error ? (
        <ErrorState message={view.error} />
      ) : (
        <MindmapExplorer
          view={view}
          fitKey={`${roomId}:${semanticState}`}
          toolbarActions={
            <SaveButton save={save} isSaved={savedGraph === graph} isWaitingForConcepts={semanticState === 'loading'} />
          }
        />
      )}
    </div>
  );
}
