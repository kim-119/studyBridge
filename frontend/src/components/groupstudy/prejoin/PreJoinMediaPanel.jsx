import React from 'react';
import { resolvePreJoinLayout } from '../../../utils/groupStudy';
import GeneralPreJoinPanel from './GeneralPreJoinPanel';
import CamPreJoinPanel from './CamPreJoinPanel';

// 입장 준비 미디어 패널 분기점: 서버 studyType(GroupStudyType enum) 하나로 GENERAL/CAM 하위 컴포넌트를 선택한다.
//  · 상태/effect 는 GroupStudy.jsx 가 소유하고 여기서는 props 만 내려보낸다(렌더 테스트 가능).
export default function PreJoinMediaPanel({ studyType, general, cam }) {
  const layout = resolvePreJoinLayout(studyType);
  if (layout.isCam) return <CamPreJoinPanel {...cam} />;
  return <GeneralPreJoinPanel {...general} />;
}
