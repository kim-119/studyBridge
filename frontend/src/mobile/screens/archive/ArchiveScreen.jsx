import React, { useCallback, useMemo, useRef, useState } from 'react';
import { ChevronRight, FileText, Folder, FolderPlus, Home, Upload } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import BottomSheet from '../../components/BottomSheet';
import Button from '../../components/Button';
import Fab from '../../components/Fab';
import ListRow from '../../components/ListRow';
import ScreenState, { EmptyState } from '../../components/ScreenState';
import SubTabs from '../../components/SubTabs';
import TextField from '../../components/TextField';
import MobileScreen from '../../shell/MobileScreen';
import { folderService, materialService } from '../../../services/api';
import { useAsync, useSubmit } from '../../data/useAsync';
import {
  ARCHIVE_TABS,
  SORT_OPTIONS,
  canUploadInto,
  formatDate,
  formatFileSize,
  matchesKeyword,
  sortItems,
} from './archiveDomain';

export default function ArchiveScreen() {
  const navigate = useNavigate();
  const fileInput = useRef(null);
  const [domain, setDomain] = useState(ARCHIVE_TABS[0].key);
  const [folderId, setFolderId] = useState(null);
  const [keyword, setKeyword] = useState('');
  const [sortKey, setSortKey] = useState(SORT_OPTIONS[0].key);
  const [openSheet, setOpenSheet] = useState(null);
  const [newFolderName, setNewFolderName] = useState('');
  const [pendingFile, setPendingFile] = useState(null);
  const [uploadTitle, setUploadTitle] = useState('');
  const [uploadKeywords, setUploadKeywords] = useState('');

  const archive = useAsync(
    () => materialService.getArchiveItems(folderId, domain),
    [folderId, domain]
  );

  const changeDomain = useCallback((nextDomain) => {
    setDomain(nextDomain);
    setFolderId(null);
    setKeyword('');
  }, []);

  const folders = useMemo(
    () => sortItems((archive.data?.folders || []).filter((item) => matchesKeyword(item, keyword)), sortKey),
    [archive.data, keyword, sortKey]
  );

  const materials = useMemo(
    () => sortItems((archive.data?.materials || []).filter((item) => matchesKeyword(item, keyword)), sortKey),
    [archive.data, keyword, sortKey]
  );

  const breadcrumb = archive.data?.breadcrumb || [];

  const closeSheet = () => {
    setOpenSheet(null);
    setNewFolderName('');
    setPendingFile(null);
    setUploadTitle('');
    setUploadKeywords('');
  };

  const createFolder = useSubmit(async () => {
    await folderService.createFolder(newFolderName.trim(), folderId, domain);
    closeSheet();
    await archive.reload();
  });

  const uploadMaterial = useSubmit(async () => {
    await materialService.uploadMaterial(
      uploadTitle.trim() || pendingFile.name,
      'PDF',
      uploadKeywords.trim(),
      pendingFile,
      folderId
    );
    closeSheet();
    await archive.reload();
  });

  const handleFileSelected = (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;

    setPendingFile(file);
    setUploadTitle(file.name.replace(/\.[^.]+$/, ''));
    setOpenSheet('upload');
  };

  const isEmpty = folders.length === 0 && materials.length === 0;

  return (
    <MobileScreen title="자료보관함">
      <SubTabs tabs={ARCHIVE_TABS} activeKey={domain} onChange={changeDomain} />

      <nav className="mobile-breadcrumb">
        <button type="button" onClick={() => setFolderId(null)}>
          <Home size={14} />홈
        </button>
        {breadcrumb.map((crumb) => (
          <span key={crumb.folderId ?? crumb.id}>
            <ChevronRight size={14} />
            <button type="button" onClick={() => setFolderId(crumb.folderId ?? crumb.id)}>
              {crumb.name}
            </button>
          </span>
        ))}
      </nav>

      <div className="mobile-toolbar">
        <input
          className="mobile-search"
          type="search"
          value={keyword}
          placeholder="자료 검색"
          onChange={(event) => setKeyword(event.target.value)}
        />
        <select
          className="mobile-select"
          value={sortKey}
          aria-label="정렬 기준"
          onChange={(event) => setSortKey(event.target.value)}
        >
          {SORT_OPTIONS.map((option) => (
            <option key={option.key} value={option.key}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      <ScreenState query={archive} loadingLabel="자료를 불러오는 중입니다">
        {isEmpty ? (
          <EmptyState message={keyword ? '검색 결과가 없습니다.' : '이 폴더에는 아직 자료가 없습니다.'} />
        ) : (
          <ul className="mobile-list">
            {folders.map((folder) => (
              <li key={`folder-${folder.folderId ?? folder.id}`}>
                <ListRow
                  icon={<Folder size={20} />}
                  title={folder.name}
                  subtitle={formatDate(folder.createdAt || folder.updatedAt)}
                  onClick={() => setFolderId(folder.folderId ?? folder.id)}
                />
              </li>
            ))}

            {materials.map((material) => (
              <li key={`material-${material.materialId}`}>
                <ListRow
                  icon={<FileText size={20} />}
                  title={material.title}
                  subtitle={[formatDate(material.uploadedAt), formatFileSize(material.fileSize)]
                    .filter(Boolean)
                    .join(' · ')}
                  onClick={() => navigate(`/archive/${material.materialId}`)}
                />
              </li>
            ))}
          </ul>
        )}
      </ScreenState>

      <Fab label="자료 추가" onClick={() => setOpenSheet('actions')} />

      <input
        ref={fileInput}
        type="file"
        accept="application/pdf"
        hidden
        onChange={handleFileSelected}
      />

      <BottomSheet title="자료 추가" isOpen={openSheet === 'actions'} onClose={closeSheet}>
        <ul className="mobile-list">
          <li>
            <ListRow
              icon={<FolderPlus size={20} />}
              title="새 폴더 만들기"
              onClick={() => setOpenSheet('folder')}
            />
          </li>
          {canUploadInto(domain) && (
            <li>
              <ListRow
                icon={<Upload size={20} />}
                title="PDF 업로드"
                onClick={() => fileInput.current?.click()}
              />
            </li>
          )}
        </ul>
      </BottomSheet>

      <BottomSheet title="새 폴더" isOpen={openSheet === 'folder'} onClose={closeSheet}>
        <TextField
          label="폴더 이름"
          value={newFolderName}
          error={createFolder.errorMessage}
          onChange={(event) => setNewFolderName(event.target.value)}
        />
        <Button
          fullWidth
          isLoading={createFolder.isSubmitting}
          disabled={!newFolderName.trim()}
          onClick={() => createFolder.submit().catch(() => {})}
        >
          만들기
        </Button>
      </BottomSheet>

      <BottomSheet title="PDF 업로드" isOpen={openSheet === 'upload'} onClose={closeSheet}>
        <p className="mobile-sheet__note">
          {pendingFile?.name} · {formatFileSize(pendingFile?.size)}
        </p>

        <TextField
          label="제목"
          value={uploadTitle}
          onChange={(event) => setUploadTitle(event.target.value)}
        />
        <TextField
          label="키워드"
          value={uploadKeywords}
          hint="쉼표로 구분해 입력하세요"
          error={uploadMaterial.errorMessage}
          onChange={(event) => setUploadKeywords(event.target.value)}
        />

        <Button
          fullWidth
          isLoading={uploadMaterial.isSubmitting}
          disabled={!pendingFile}
          onClick={() => uploadMaterial.submit().catch(() => {})}
        >
          업로드
        </Button>
      </BottomSheet>
    </MobileScreen>
  );
}
