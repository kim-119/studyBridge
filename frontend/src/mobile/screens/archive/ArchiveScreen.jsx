import React, { useCallback, useMemo, useRef, useState } from 'react';
import {
  ChevronRight,
  FileText,
  Folder,
  FolderInput,
  FolderPlus,
  Home,
  MoreVertical,
  PencilLine,
  Trash2,
  Upload,
} from 'lucide-react';
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
import FolderPicker from './FolderPicker';
import {
  ARCHIVE_TABS,
  SORT_OPTIONS,
  canUploadInto,
  formatDate,
  formatFileSize,
  matchesKeyword,
  sortItems,
} from './archiveDomain';

const SHEET = {
  ACTIONS: 'actions',
  NEW_FOLDER: 'new-folder',
  UPLOAD: 'upload',
  FOLDER_MENU: 'folder-menu',
  FOLDER_RENAME: 'folder-rename',
  FOLDER_MOVE: 'folder-move',
  MATERIAL_MENU: 'material-menu',
  MATERIAL_MOVE: 'material-move',
};

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
  const [targetFolder, setTargetFolder] = useState(null);
  const [targetMaterial, setTargetMaterial] = useState(null);

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
    setTargetFolder(null);
    setTargetMaterial(null);
  };

  const createFolder = useSubmit(async () => {
    await folderService.createFolder(newFolderName.trim(), folderId, domain);
    closeSheet();
    await archive.reload();
  });

  const renameFolder = useSubmit(async () => {
    await folderService.renameFolder(targetFolder.folderId ?? targetFolder.id, newFolderName.trim());
    closeSheet();
    await archive.reload();
  });

  const moveFolder = useSubmit(async (parentId) => {
    await folderService.moveFolder(targetFolder.folderId ?? targetFolder.id, parentId);
    closeSheet();
    await archive.reload();
  });

  const deleteFolder = useSubmit(async () => {
    await folderService.deleteFolder(targetFolder.folderId ?? targetFolder.id);
    closeSheet();
    await archive.reload();
  });

  const moveMaterial = useSubmit(async (destinationId) => {
    await materialService.moveMaterial(targetMaterial.materialId, destinationId);
    closeSheet();
    await archive.reload();
  });

  const deleteMaterial = useSubmit(async () => {
    await materialService.deleteMaterial(targetMaterial.materialId);
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
    setOpenSheet(SHEET.UPLOAD);
  };

  const openFolderMenu = (folder) => {
    setTargetFolder(folder);
    setNewFolderName(folder.name || '');
    setOpenSheet(SHEET.FOLDER_MENU);
  };

  const openMaterialMenu = (material) => {
    setTargetMaterial(material);
    setOpenSheet(SHEET.MATERIAL_MENU);
  };

  const isEmpty = folders.length === 0 && materials.length === 0;
  const actionError =
    renameFolder.errorMessage ||
    moveFolder.errorMessage ||
    deleteFolder.errorMessage ||
    moveMaterial.errorMessage ||
    deleteMaterial.errorMessage;

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

      {actionError && <p className="mobile-auth__error">{actionError}</p>}

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
                  trailing={
                    <button
                      type="button"
                      className="mobile-row__more"
                      aria-label={`${folder.name} 관리`}
                      onClick={(event) => {
                        event.stopPropagation();
                        openFolderMenu(folder);
                      }}
                    >
                      <MoreVertical size={18} />
                    </button>
                  }
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
                  trailing={
                    <button
                      type="button"
                      className="mobile-row__more"
                      aria-label={`${material.title} 관리`}
                      onClick={(event) => {
                        event.stopPropagation();
                        openMaterialMenu(material);
                      }}
                    >
                      <MoreVertical size={18} />
                    </button>
                  }
                />
              </li>
            ))}
          </ul>
        )}
      </ScreenState>

      <Fab label="자료 추가" onClick={() => setOpenSheet(SHEET.ACTIONS)} />

      <input
        ref={fileInput}
        type="file"
        accept="application/pdf"
        hidden
        onChange={handleFileSelected}
      />

      <BottomSheet title="자료 추가" isOpen={openSheet === SHEET.ACTIONS} onClose={closeSheet}>
        <ul className="mobile-list">
          <li>
            <ListRow
              icon={<FolderPlus size={20} />}
              title="새 폴더 만들기"
              onClick={() => setOpenSheet(SHEET.NEW_FOLDER)}
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

      <BottomSheet title="새 폴더" isOpen={openSheet === SHEET.NEW_FOLDER} onClose={closeSheet}>
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

      <BottomSheet title={targetFolder?.name || '폴더'} isOpen={openSheet === SHEET.FOLDER_MENU} onClose={closeSheet}>
        <ul className="mobile-list">
          <li>
            <ListRow
              icon={<PencilLine size={20} />}
              title="이름 변경"
              onClick={() => setOpenSheet(SHEET.FOLDER_RENAME)}
            />
          </li>
          <li>
            <ListRow
              icon={<FolderInput size={20} />}
              title="다른 폴더로 이동"
              onClick={() => setOpenSheet(SHEET.FOLDER_MOVE)}
            />
          </li>
          <li>
            <ListRow
              icon={<Trash2 size={20} />}
              title="폴더 삭제"
              onClick={() => deleteFolder.submit().catch(() => {})}
              trailing={<span />}
            />
          </li>
        </ul>
      </BottomSheet>

      <BottomSheet title="폴더 이름 변경" isOpen={openSheet === SHEET.FOLDER_RENAME} onClose={closeSheet}>
        <TextField
          label="새 이름"
          value={newFolderName}
          error={renameFolder.errorMessage}
          onChange={(event) => setNewFolderName(event.target.value)}
        />
        <Button
          fullWidth
          isLoading={renameFolder.isSubmitting}
          disabled={!newFolderName.trim()}
          onClick={() => renameFolder.submit().catch(() => {})}
        >
          변경
        </Button>
      </BottomSheet>

      <BottomSheet title="폴더 이동" isOpen={openSheet === SHEET.FOLDER_MOVE} onClose={closeSheet}>
        <FolderPicker
          domain={domain}
          excludeFolderId={targetFolder?.folderId ?? targetFolder?.id}
          onSelect={(parentId) => moveFolder.submit(parentId).catch(() => {})}
        />
      </BottomSheet>

      <BottomSheet
        title={targetMaterial?.title || '자료'}
        isOpen={openSheet === SHEET.MATERIAL_MENU}
        onClose={closeSheet}
      >
        <ul className="mobile-list">
          <li>
            <ListRow
              icon={<FolderInput size={20} />}
              title="다른 폴더로 이동"
              onClick={() => setOpenSheet(SHEET.MATERIAL_MOVE)}
            />
          </li>
          <li>
            <ListRow
              icon={<Trash2 size={20} />}
              title="자료 삭제"
              onClick={() => deleteMaterial.submit().catch(() => {})}
              trailing={<span />}
            />
          </li>
        </ul>
      </BottomSheet>

      <BottomSheet title="자료 이동" isOpen={openSheet === SHEET.MATERIAL_MOVE} onClose={closeSheet}>
        <FolderPicker domain={domain} onSelect={(destinationId) => moveMaterial.submit(destinationId).catch(() => {})} />
      </BottomSheet>

      <BottomSheet title="PDF 업로드" isOpen={openSheet === SHEET.UPLOAD} onClose={closeSheet}>
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
