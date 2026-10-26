import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { EmptyState, ErrorState, LoadingState } from '../../components/ScreenState';
import SubTabs from '../../components/SubTabs';
import MobileScreen from '../../shell/MobileScreen';
import { agentService } from '../../../services/api';
import { agentIdOf } from '../../../utils/agentIdentity';
import { useMinuteRecap } from '../../../components/studymate/pixel/useMinuteRecap';
import { ROLE_TO_AGENT_INDEX } from '../../../components/studymate/pixel/professorSprites';
import { useAsync } from '../../data/useAsync';
import { useBackDismiss } from '../../platform/useBackDismiss';
import ChatComposer from './ChatComposer';
import ChatMessageList from './ChatMessageList';
import ProfessorTab from './ProfessorTab';
import RoomMindmapTab from './RoomMindmapTab';
import { latestAnswer, latestUserQuestion } from './chatMessages';
import { describeRoomMode } from './learningModes';
import { buildProfessorActionPrompt, mentionForAgent, prefillMention, professorDisplayName } from './professorActions';
import { useKeyboardInset } from './useKeyboardInset';
import { useProfessorStage } from './useProfessorStage';
import { useStickToBottom } from './useStickToBottom';
import { useStudyMateStream } from './useStudyMateStream';
import { STUDYBRIDGE_ROOM_TITLE } from './agentDrafts';

const ROOM_TABS = [
  { key: 'chat', label: '채팅' },
  { key: 'professor', label: '교수님들과 대화' },
  { key: 'mindmap', label: '마인드맵' },
];

function roomTitleOf(room) {
  return room?.roomName || room?.name || room?.title || STUDYBRIDGE_ROOM_TITLE;
}

function RoomStatus({ room }) {
  const modeInfo = describeRoomMode(room);
  const agents = room.agents || [];

  return (
    <div className="mobile-chat__room-status">
      <p className="mobile-chat__mode">
        <strong>{modeInfo.label}</strong>
        <span>{modeInfo.rows.map((row) => `${row.key} ${row.value}`).join(' · ')}</span>
      </p>
      {agents.length > 0 && (
        <p className="mobile-chat__agents">{agents.map((agent) => agent.name).filter(Boolean).join(' · ')}</p>
      )}
    </div>
  );
}

function contentVersionOf(stream) {
  const lastMessage = stream.messages[stream.messages.length - 1];
  return `${stream.messages.length}:${stream.isStreaming}:${lastMessage?.content?.length ?? 0}:${lastMessage?.stages?.length ?? 0}`;
}

function useRecap(messages, turnDoneAt) {
  const question = useMemo(() => latestUserQuestion(messages), [messages]);
  const answer = useMemo(() => latestAnswer(messages)?.content || '', [messages]);
  return useMinuteRecap({ question, answer, trigger: turnDoneAt });
}

function useDraft(roomAgents, stream) {
  const [draft, setDraft] = useState('');
  const inputRef = useRef(null);

  const focusInput = () => requestAnimationFrame(() => inputRef.current?.focus());

  const prefill = (text) => {
    setDraft(text);
    focusInput();
  };

  const mentionAgent = (agent) => {
    stream.pinAgent(agentIdOf(agent));
    prefill(prefillMention(draft, mentionForAgent(agent), roomAgents));
  };

  const submit = () => {
    if (!draft.trim()) return;
    stream.send(draft);
    setDraft('');
  };

  return { draft, setDraft, inputRef, focusInput, prefill, mentionAgent, submit };
}

function createProfessorHandlers({ roomAgents, stage, stream, composer, messages, setTab }) {
  const refine = () => {
    stage.setSelectedRole(null);
    stage.setStatusMessage('입력창에서 질문을 더 구체적으로 다듬어 전송해 주세요.');
    composer.focusInput();
  };

  const askOne = (role) => {
    const agent = roomAgents[ROLE_TO_AGENT_INDEX[role] ?? 0];
    stage.setSelectedRole(null);
    composer.mentionAgent(agent);
    stage.setStatusMessage(`${professorDisplayName(roomAgents, role)}님에게 보낼 질문을 입력해 주세요.`);
  };

  const askAll = () => {
    stream.pinAgent(null);
    stage.setSelectedRole(null);
    composer.prefill(prefillMention(composer.draft, mentionForAgent(null), roomAgents));
    stage.setStatusMessage('모든 교수에게 보낼 질문을 입력해 전송해 주세요.');
  };

  const compare = () => {
    stage.setSelectedRole(null);
    setTab('professor');
    composer.prefill(
      buildProfessorActionPrompt({ actionKey: 'compare', targetKey: 'all', baseText: latestAnswer(messages)?.content || '' })
    );
  };

  return { refine, askOne, askAll, compare };
}

function StudyRoom({ roomId, room }) {
  const roomAgents = useMemo(() => room.agents || [], [room.agents]);
  const [tab, setTab] = useState(ROOM_TABS[0].key);
  useBackDismiss(tab !== ROOM_TABS[0].key, () => setTab(ROOM_TABS[0].key));
  const keyboardInset = useKeyboardInset();
  const stage = useProfessorStage(roomAgents);
  const stream = useStudyMateStream({ roomId, room, stage });
  const history = useAsync(() => agentService.getChatHistory(null, roomId), [roomId]);
  const recap = useRecap(stream.messages, stage.turnDoneAt);
  const composer = useDraft(roomAgents, stream);
  const professor = createProfessorHandlers({ roomAgents, stage, stream, composer, messages: stream.messages, setTab });
  const isChatTab = tab === 'chat';
  const { containerRef, handleScroll } = useStickToBottom(contentVersionOf(stream), isChatTab);
  const { loadHistory } = stream;
  const { setSelectedRole } = stage;

  useEffect(() => {
    if (history.data) loadHistory(history.data);
  }, [history.data, loadHistory]);

  useEffect(() => {
    if (tab !== 'professor') setSelectedRole(null);
  }, [setSelectedRole, tab]);

  useLayoutEffect(() => {
    if (!isChatTab && containerRef.current) containerRef.current.scrollTop = 0;
  }, [containerRef, isChatTab]);

  const chooseSimulationOption = (choice) => composer.prefill(stream.chooseSimulationOption(choice));

  return (
    <div className="mobile-chat" style={{ '--mobile-keyboard-inset': `${keyboardInset}px` }}>
      <div className="mobile-chat__header">
        <RoomStatus room={room} />
        <SubTabs tabs={ROOM_TABS} activeKey={tab} onChange={setTab} />
      </div>

      <div className="mobile-chat__body" ref={containerRef} onScroll={handleScroll}>
        {stream.syncErrorMessage && <p className="mobile-chat__status">{stream.syncErrorMessage}</p>}

        {tab === 'chat' &&
          (history.isError && stream.messages.length === 0 ? (
            <ErrorState message={history.errorMessage} onRetry={history.reload} />
          ) : history.isLoading && stream.messages.length === 0 ? (
            <LoadingState label="대화를 불러오는 중입니다" />
          ) : (
            <ChatMessageList
              messages={stream.messages}
              roomAgents={roomAgents}
              isStreaming={stream.isStreaming}
              onMention={composer.mentionAgent}
              onRetry={stream.retry}
              onChoose={chooseSimulationOption}
            />
          ))}

        {tab === 'professor' && (
          <ProfessorTab
            roomAgents={roomAgents}
            messages={stream.messages}
            stage={{ ...stage, recap: recap.recap, dismissRecap: recap.dismissRecap }}
            onRefine={professor.refine}
            onAskOne={professor.askOne}
            onAskAll={professor.askAll}
            onCompare={professor.compare}
          />
        )}

        {tab === 'mindmap' && (
          <RoomMindmapTab roomId={roomId} roomAgents={roomAgents} messages={stream.messages} interactions={stage.interactions} />
        )}
      </div>

      {tab !== 'mindmap' && (
        <ChatComposer
          inputRef={composer.inputRef}
          draft={composer.draft}
          onDraftChange={composer.setDraft}
          onSubmit={composer.submit}
          onStop={stream.stop}
          onPickMention={stream.pinAgent}
          onSendFollowUp={stream.send}
          followUps={stream.followUps}
          roomAgents={roomAgents}
          isStreaming={stream.isStreaming}
        />
      )}
    </div>
  );
}

export default function StudyMateChatScreen() {
  const { roomId } = useParams();
  const rooms = useAsync(() => agentService.getAgents(), []);
  const room = (Array.isArray(rooms.data) ? rooms.data : []).find((item) => String(item.id) === String(roomId)) || null;

  return (
    <MobileScreen title={room ? roomTitleOf(room) : '학습메이트'} showBackButton>
      {rooms.isLoading && !rooms.data ? (
        <LoadingState label="학습방을 불러오는 중입니다" />
      ) : rooms.isError ? (
        <ErrorState message={rooms.errorMessage} onRetry={rooms.reload} />
      ) : !room ? (
        <EmptyState message="학습방을 찾을 수 없습니다. 삭제되었거나 다른 계정의 방일 수 있어요." />
      ) : (
        <StudyRoom key={roomId} roomId={roomId} room={room} />
      )}
    </MobileScreen>
  );
}
