import coverNotes from './presets/cover-notes.jpg';
import coverWriting from './presets/cover-writing.jpg';
import coverTeam from './presets/cover-team.jpg';
import { selectCoverPreset } from '../../utils/groupCover';

// 그룹 생성 '기본 이미지' 프리셋 — 번들 정적 asset(빌드 시 /assets/<name>-<hash>.jpg, nginx immutable 캐시).
//  기존에 외부(unsplash)에서 불러오던 같은 3장을 로컬로 옮겼다(Unsplash License: 상업적 사용·수정 허용, 출처 표기 불요).
//  생성 시 groupCover.resolveCoverImageFile 이 asset 을 File 로 바꿔 업로드 → 서버는 사용자 업로드와 같은 S3 경로로 저장.
export const GROUP_COVER_PRESETS = [
  { id: 'notes', label: '노트', url: coverNotes },
  { id: 'writing', label: '필기', url: coverWriting },
  { id: 'team', label: '팀 스터디', url: coverTeam },
];

// 생성 폼 초기값: 화면에 보이는 기본 이미지(첫 프리셋)가 실제로 저장된다.
export const initialCoverForm = () => selectCoverPreset({}, GROUP_COVER_PRESETS[0]);
