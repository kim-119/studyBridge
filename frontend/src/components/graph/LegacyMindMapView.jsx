import React from 'react';
import ProfessorGraphView from '../studymate/ProfessorGraphView';

// 기존 카드형 마인드맵을 fallback 으로 보존한다.
//  · Obsidian 경로에서는 PDF 저장 버튼을 숨긴다(mindmap PDF 저장 금지).
export default function LegacyMindMapView(props) {
  return <ProfessorGraphView {...props} hidePdfSave />;
}
