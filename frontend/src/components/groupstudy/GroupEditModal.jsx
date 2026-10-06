import React, { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { groupService } from '../../services/api';
import SettingRow from './SettingRow';
import GroupSettingsFields from './GroupSettingsFields';
import GroupProfileField from './GroupProfileField';
import { buildSettingsPayload, validateSettingsForm, normalizeGroup } from '../../utils/groupStudy';

const TITLE_MAX = 100;
const DESCRIPTION_MAX = 1000;

const toForm = (study) => ({
  title: study.title || '',
  description: study.description || '',
  studyType: study.studyType,
  targetStudyMinutes: study.targetStudyMinutes,
  joinQuestionEnabled: study.joinQuestionEnabled,
  joinQuestion: study.joinQuestion || '',
  nicknameRuleEnabled: study.nicknameRuleEnabled,
  nicknameRule: study.nicknameRule || '',
  studyIconId: study.studyIconId || null,
});

// 그룹장 전용 수정 모달. 버튼 노출은 UX 이고 실제 권한 검증은 서버(PUT /api/groups/{id}, 방장 검증 → 403).
//  · 저장 성공 시 서버 응답(GroupStudyDTO.Response)을 normalizeGroup 해 onSaved 로 돌려준다(목록/프리조인 즉시 반영).
export default function GroupEditModal({ study, onClose, onSaved, notify }) {
  const [form, setForm] = useState(() => toForm(study));
  const [imageFile, setImageFile] = useState(null);
  const [clearImage, setClearImage] = useState(false);
  const [previewUrl, setPreviewUrl] = useState(study.hasCoverImage ? study.thumbnailUrl : null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!imageFile) return undefined;
    const url = URL.createObjectURL(imageFile);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [imageFile]);

  const handleSave = async () => {
    const title = form.title.trim();
    const description = form.description.trim();
    if (!title) { setError('그룹 이름을 입력해주세요.'); return; }
    if (!description) { setError('그룹 설명(공지사항)을 입력해주세요.'); return; }
    const settingsError = validateSettingsForm(form);
    if (settingsError) { setError(settingsError); return; }

    setSaving(true);
    setError('');
    try {
      const payload = {
        title,
        description,
        ...buildSettingsPayload(form),
        image: imageFile || null,
        clearImage: clearImage && !imageFile ? true : undefined,
      };
      const res = await groupService.updateGroup(study.id, payload);
      const updated = normalizeGroup(res);
      notify?.('저장 완료', '스터디 설정이 저장되었습니다.');
      onSaved(updated);
    } catch (err) {
      const status = err?.response?.status;
      const message = err?.response?.data?.message
        || (status === 403 ? '방장만 스터디 설정을 수정할 수 있습니다.' : '스터디 설정 저장에 실패했습니다.');
      setError(message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 10001, padding: '16px', boxSizing: 'border-box' }}
      onClick={() => { if (!saving) onClose(); }}
    >
      <div className="gs-modal" role="dialog" aria-modal="true" aria-label="스터디 설정 수정" onClick={(e) => e.stopPropagation()}>
        <div className="gs-modal-header">
          <h2>스터디 설정 수정</h2>
          <button type="button" onClick={onClose} disabled={saving} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '6px', display: 'flex' }} aria-label="닫기">
            <X size={22} color="#6B7280" />
          </button>
        </div>

        <div className="gs-modal-body">
          <h3 className="gs-section-title">기본 정보</h3>
          <SettingRow label="그룹 이름" required>
            <input
              type="text"
              className="gs-input"
              value={form.title}
              maxLength={TITLE_MAX}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              placeholder="스터디 이름을 입력하세요"
            />
          </SettingRow>
          <SettingRow label="그룹 설명" required hint="스터디 규칙, 공지 사항 등을 입력해주세요.">
            <textarea
              className="gs-textarea"
              style={{ minHeight: '120px' }}
              value={form.description}
              maxLength={DESCRIPTION_MAX}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
            <div className="gs-counter">{form.description.length} / {DESCRIPTION_MAX}</div>
          </SettingRow>
          <SettingRow label="최대 인원" hint="정원과 공개 여부는 이 화면에서 변경하지 않습니다.">
            <div style={{ fontSize: '14px', color: '#374151', paddingTop: '10px' }}>{study.currentMembers} / {study.maxMembers}명</div>
          </SettingRow>

          <GroupSettingsFields value={form} onChange={setForm} />

          <h3 className="gs-section-title">그룹 프로필</h3>
          <SettingRow label="프로필 이미지">
            <GroupProfileField
              previewUrl={previewUrl}
              studyType={form.studyType}
              onPickFile={(file) => { setImageFile(file); setClearImage(false); }}
              onClear={() => { setImageFile(null); setPreviewUrl(null); setClearImage(true); }}
              onError={(msg) => setError(msg)}
            />
          </SettingRow>

          {error && <div className="error-text" role="alert" style={{ fontSize: '13px' }}>{error}</div>}
        </div>

        <div className="gs-modal-footer">
          <button type="button" className="btn-outline" onClick={onClose} disabled={saving}>취소</button>
          <button type="button" className="btn-primary" onClick={handleSave} disabled={saving}>{saving ? '저장 중…' : '저장'}</button>
        </div>
      </div>
    </div>
  );
}
