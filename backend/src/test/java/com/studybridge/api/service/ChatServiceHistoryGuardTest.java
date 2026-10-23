package com.studybridge.api.service;

import com.studybridge.api.dto.ChatDTO;
import com.studybridge.api.entity.AgentChatRoom;
import com.studybridge.api.entity.ChatMessage;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.AgentChatRoomRepository;
import com.studybridge.api.repository.ChatMessageRepository;
import org.junit.jupiter.api.Test;

import java.time.LocalDateTime;
import java.util.List;
import java.util.NoSuchElementException;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.*;

/**
 * 학습메이트 history 엔드포인트 소유자 검증(IDOR 방지) + created_at,id 정렬 사용 회귀 테스트.
 *  이전: roomId 만으로 타인 방 대화가 200 으로 열렸고, 같은 턴의 AI 답변이 created_at 동률일 때 순서가 흔들렸다.
 */
class ChatServiceHistoryGuardTest {

    private static ChatService service(AgentChatRoomRepository rooms, ChatMessageRepository messages) {
        return new ChatService(rooms, messages, null, null, new com.fasterxml.jackson.databind.ObjectMapper(), null, null, null, null);
    }

    private static AgentChatRoom room(long roomId, long ownerId) {
        User owner = new User();
        owner.setId(ownerId);
        return AgentChatRoom.builder().id(roomId).user(owner).roomName("r").build();
    }

    @Test
    void history_otherUsersRoom_isForbidden() {
        AgentChatRoomRepository rooms = mock(AgentChatRoomRepository.class);
        ChatMessageRepository messages = mock(ChatMessageRepository.class);
        when(rooms.findById(226L)).thenReturn(Optional.of(room(226L, 8L)));

        assertThrows(SecurityException.class, () -> service(rooms, messages).getRoomChatHistory(55L, 226L));
        verify(messages, never()).findByAgentChatRoomIdOrderByCreatedAtAscIdAsc(anyLong());
    }

    @Test
    void history_unknownRoom_isNotFound() {
        AgentChatRoomRepository rooms = mock(AgentChatRoomRepository.class);
        when(rooms.findById(999L)).thenReturn(Optional.empty());
        assertThrows(NoSuchElementException.class,
                () -> service(rooms, mock(ChatMessageRepository.class)).getRoomChatHistory(55L, 999L));
    }

    @Test
    void history_owner_usesCreatedAtThenIdOrdering() {
        AgentChatRoomRepository rooms = mock(AgentChatRoomRepository.class);
        ChatMessageRepository messages = mock(ChatMessageRepository.class);
        AgentChatRoom r = room(234L, 55L);
        when(rooms.findById(234L)).thenReturn(Optional.of(r));
        ChatMessage m1 = ChatMessage.builder().id(1L).agentChatRoom(r).content("q").sender("USER").createdAt(LocalDateTime.now()).build();
        ChatMessage m2 = ChatMessage.builder().id(2L).agentChatRoom(r).content("a").sender("AI").createdAt(LocalDateTime.now()).build();
        when(messages.findByAgentChatRoomIdOrderByCreatedAtAscIdAsc(234L)).thenReturn(List.of(m1, m2));

        List<ChatDTO.MessageResponse> out = service(rooms, messages).getRoomChatHistory(55L, 234L);

        assertEquals(2, out.size());
        assertEquals(1L, out.get(0).getId());
        assertEquals("AI", out.get(1).getSender());
        assertNull(out.get(1).getAgentId(), "agent 미해석 행은 agentId null 로 내려간다(첫 교수 폴백 금지)");
        verify(messages).findByAgentChatRoomIdOrderByCreatedAtAscIdAsc(234L);
        verify(messages, never()).findByAgentChatRoomIdOrderByCreatedAtAsc(anyLong());
    }
}
