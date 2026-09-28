import React from 'react';

export default function VideoPreJoin({ groupTitle, onJoin }) {
  return (
    <button type="button" data-prejoin={groupTitle || ''} onClick={() => onJoin({ useCamera: false, useMicrophone: false })}>
      입장하기
    </button>
  );
}
