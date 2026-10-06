// 표준 SSE(text/event-stream) 프레이밍 파서 — 프로덕션(api.js streamMessage)과 테스트가 같은 구현을 쓴다.
//  · TCP 청크 ≠ SSE 이벤트: 청크 경계에서 잘린 프레임/멀티바이트(UTF-8 한글)는 push 간에 버퍼링한다(디코딩은 호출부 TextDecoder stream:true).
//  · 줄 구분자: CRLF, LF, CR 모두 허용. 프레임 구분자 = 빈 줄.
//  · 'data:' 는 여러 줄이 올 수 있고 개행으로 이어 붙인다(멀티라인 JSON/코드블록). 'data:' 바로 뒤 공백 1개만 제거.
//  · ':' 로 시작하는 줄은 주석(Spring ':hb' keepalive) — 이벤트가 아니라 liveness 신호로만 전달한다.
//  · 'event:' 없으면 'message'. 'id:' 는 lastEventId 로 전달, 'retry:'/미지 필드는 무시(표준).
//  · 프레임 하나의 파싱 실패가 스트림 전체를 죽이지 않는다(호출부가 JSON.parse 를 프레임 단위로 시도).
export function createSseParser(onFrame) {
  let buffer = '';
  let lastEventId = null;

  const dispatchFrame = (raw) => {
    if (!raw) return;
    let event = 'message';
    const dataLines = [];
    let comment = null;
    let id = null;
    let sawField = false;
    for (const line of raw.split('\n')) {
      if (line === '') continue;
      if (line.startsWith(':')) { comment = (comment == null ? '' : comment + '\n') + line.slice(1).trim(); continue; }
      const colon = line.indexOf(':');
      const field = colon === -1 ? line : line.slice(0, colon);
      let value = colon === -1 ? '' : line.slice(colon + 1);
      if (value.startsWith(' ')) value = value.slice(1);
      if (field === 'event') { event = value.trim() || 'message'; sawField = true; }
      else if (field === 'data') { dataLines.push(value); sawField = true; }
      else if (field === 'id') { if (value.indexOf(String.fromCharCode(0)) === -1) { id = value; lastEventId = value; } sawField = true; }
      // retry / 미지 필드는 표준대로 무시
    }
    if (dataLines.length === 0) {
      if (comment != null || sawField) onFrame({ event: null, data: null, comment, id, control: true });
      return;
    }
    onFrame({ event, data: dataLines.join('\n'), comment, id: id ?? lastEventId, control: false });
  };

  const drain = () => {
    // 표준: CRLF → LF, 단독 CR → LF 로 정규화한 뒤 빈 줄로 프레임 분리.
    buffer = buffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    let idx;
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      if (frame.trim()) dispatchFrame(frame);
    }
  };

  return {
    push(text) {
      if (!text) return;
      // UTF-8 BOM(스트림 첫 청크) 제거
      if (buffer.length === 0 && text.charCodeAt(0) === 0xfeff) text = text.slice(1);
      buffer += text;
      drain();
    },
    // 스트림 종료: 종결 빈 줄 없이 끝난 마지막 프레임도 유실 없이 처리한다.
    flush() {
      drain();
      const tail = buffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
      buffer = '';
      if (tail) dispatchFrame(tail);
    },
    get lastEventId() { return lastEventId; },
    get pending() { return buffer.length; },
  };
}
