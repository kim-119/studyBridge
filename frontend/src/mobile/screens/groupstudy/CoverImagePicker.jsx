import React, { useEffect, useState } from 'react';
import { Check, ImagePlus } from 'lucide-react';
import BottomSheet from '../../components/BottomSheet';
import Button from '../../components/Button';
import {
  COVER_IMAGE_ACCEPT,
  COVER_IMAGE_PRESETS,
  DEFAULT_COVER_PRESET_KEY,
  validateCoverImageFile,
} from './groupStudyModel';

export const INITIAL_COVER = { presetKey: DEFAULT_COVER_PRESET_KEY, file: null };

function presetByKey(key) {
  return COVER_IMAGE_PRESETS.find((preset) => preset.key === key) || COVER_IMAGE_PRESETS[0];
}

async function downloadPresetFile(preset) {
  const response = await fetch(preset.sourceUrl);
  if (!response.ok) throw new Error('기본 이미지를 불러오지 못했습니다. 기기에서 이미지를 선택해주세요.');
  const blob = await response.blob();
  return new File([blob], `${preset.key}.jpg`, { type: blob.type || 'image/jpeg' });
}

export async function resolveCoverUpload(cover) {
  if (cover.file) return cover.file;
  if (cover.presetKey === DEFAULT_COVER_PRESET_KEY) return null;

  const file = await downloadPresetFile(presetByKey(cover.presetKey));
  const validationError = validateCoverImageFile(file);
  if (validationError) throw new Error(validationError);
  return file;
}

function useObjectUrl(file) {
  const [url, setUrl] = useState(null);

  useEffect(() => {
    if (!file) {
      setUrl(null);
      return undefined;
    }
    const objectUrl = URL.createObjectURL(file);
    setUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [file]);

  return url;
}

export default function CoverImagePicker({ cover, onChange }) {
  const [isSheetOpen, setSheetOpen] = useState(false);
  const [fileError, setFileError] = useState(null);
  const filePreviewUrl = useObjectUrl(cover.file);
  const previewUrl = filePreviewUrl || presetByKey(cover.presetKey).previewUrl;

  const selectFile = (event) => {
    const [file] = event.target.files || [];
    event.target.value = '';
    if (!file) return;

    const validationError = validateCoverImageFile(file);
    setFileError(validationError);
    if (!validationError) onChange({ presetKey: null, file });
  };

  const selectPreset = (presetKey) => {
    setFileError(null);
    onChange({ presetKey, file: null });
  };

  return (
    <>
      <div className="mobile-cover-picker">
        <img className="mobile-cover-picker__preview" src={previewUrl} alt="선택한 커버 이미지" />
        <Button variant="secondary" onClick={() => setSheetOpen(true)}>
          <ImagePlus size={16} />
          이미지 변경
        </Button>
      </div>
      {fileError && <p className="mobile-field__error">{fileError}</p>}

      <BottomSheet title="커버 이미지" isOpen={isSheetOpen} onClose={() => setSheetOpen(false)}>
        <img className="mobile-cover-picker__large" src={previewUrl} alt="" />

        <ul className="mobile-cover-picker__presets">
          {COVER_IMAGE_PRESETS.map((preset) => (
            <li key={preset.key}>
              <button
                type="button"
                className={cover.presetKey === preset.key ? 'is-selected' : ''}
                aria-label={`기본 이미지 ${preset.key}`}
                onClick={() => selectPreset(preset.key)}
              >
                <img src={preset.previewUrl} alt="" />
                {cover.presetKey === preset.key && <Check size={22} />}
              </button>
            </li>
          ))}
        </ul>

        <label className="mobile-button mobile-button--secondary mobile-button--block mobile-cover-picker__upload">
          <ImagePlus size={16} />
          기기에서 불러오기
          <input type="file" accept={COVER_IMAGE_ACCEPT} hidden onChange={selectFile} />
        </label>
        <p className="mobile-field__hint">JPG, PNG, WEBP · 최대 5MB</p>
        {fileError && <p className="mobile-field__error">{fileError}</p>}

        <Button fullWidth onClick={() => setSheetOpen(false)}>
          완료
        </Button>
      </BottomSheet>
    </>
  );
}
