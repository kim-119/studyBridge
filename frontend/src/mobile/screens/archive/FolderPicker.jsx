import React, { useMemo } from 'react';
import { Folder, Home } from 'lucide-react';
import ListRow from '../../components/ListRow';
import ScreenState from '../../components/ScreenState';
import { folderService } from '../../../services/api';
import { useAsync } from '../../data/useAsync';

function descendantIds(folders, rootId) {
  const blocked = new Set([rootId]);
  let changed = true;

  while (changed) {
    changed = false;
    folders.forEach((folder) => {
      const id = folder.folderId ?? folder.id;
      const parentId = folder.parentId ?? folder.parent?.folderId ?? null;
      if (parentId != null && blocked.has(parentId) && !blocked.has(id)) {
        blocked.add(id);
        changed = true;
      }
    });
  }

  return blocked;
}

/**
 * 이동 대상 폴더 선택기. 폴더 이동 시 자기 자신과 하위 폴더를 후보에서 제외해 순환을 막는다.
 */
export default function FolderPicker({ domain, excludeFolderId, onSelect }) {
  const folders = useAsync(() => folderService.listFolders(), []);

  const candidates = useMemo(() => {
    const all = Array.isArray(folders.data) ? folders.data : [];
    const sameDomain = all.filter((folder) => (folder.domain || 'LEARNING_MATERIAL') === domain);

    if (excludeFolderId == null) return sameDomain;

    const blocked = descendantIds(sameDomain, excludeFolderId);
    return sameDomain.filter((folder) => !blocked.has(folder.folderId ?? folder.id));
  }, [folders.data, domain, excludeFolderId]);

  return (
    <ScreenState query={folders} loadingLabel="폴더를 불러오는 중입니다">
      <ul className="mobile-list">
        <li>
          <ListRow icon={<Home size={20} />} title="홈 (최상위)" onClick={() => onSelect(null)} />
        </li>

        {candidates.map((folder) => (
          <li key={folder.folderId ?? folder.id}>
            <ListRow
              icon={<Folder size={20} />}
              title={folder.name}
              onClick={() => onSelect(folder.folderId ?? folder.id)}
            />
          </li>
        ))}
      </ul>
    </ScreenState>
  );
}
