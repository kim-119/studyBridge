package com.studybridge.api.service.support;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.entity.Agent;
import com.studybridge.api.entity.AgentChatRoom;
import com.studybridge.api.entity.ChatMessage;
import com.studybridge.api.repository.AgentChatRoomRepository;
import com.studybridge.api.repository.ChatMessageRepository;
import com.studybridge.api.service.AiIntegrationService;
import com.studybridge.api.service.AiMultiChatFailoverService;
import com.studybridge.api.service.ChatService;
import com.studybridge.api.service.IntentRouterService;
import com.studybridge.api.service.RedisChatService;
import org.mockito.Mockito;
import org.springframework.transaction.support.TransactionCallback;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.reactive.function.client.WebClient;

import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;

/** ChatService 영속화 경로를 mock 저장소로 검증하기 위한 팩토리. saved 리스트에 저장된 ChatMessage 가 쌓인다. */
public final class ChatServiceTestFactory {

    public final List<ChatMessage> saved = new ArrayList<>();
    public final ChatMessageRepository messages = Mockito.mock(ChatMessageRepository.class);
    public final AgentChatRoomRepository rooms = Mockito.mock(AgentChatRoomRepository.class);
    public final RedisChatService redis = Mockito.mock(RedisChatService.class);
    public final ChatService service;
    public final AgentChatRoom room;

    @SuppressWarnings("unchecked")
    public ChatServiceTestFactory(long roomId, List<Agent> agents) {
        room = new AgentChatRoom();
        room.setId(roomId);
        room.setAgents(agents);
        Mockito.when(rooms.findById(roomId)).thenReturn(Optional.of(room));
        Mockito.when(messages.save(any(ChatMessage.class))).thenAnswer(inv -> {
            ChatMessage m = inv.getArgument(0);
            saved.add(m);
            return m;
        });
        Mockito.when(messages.existsByAgentChatRoomIdAndEventId(anyLong(), anyString()))
                .thenAnswer(inv -> saved.stream().anyMatch(m -> inv.getArgument(1).equals(m.getEventId())));
        TransactionTemplate tt = Mockito.mock(TransactionTemplate.class);
        Mockito.when(tt.execute(any())).thenAnswer(inv -> ((TransactionCallback<Object>) inv.getArgument(0)).doInTransaction(null));
        service = new ChatService(rooms, messages, Mockito.mock(WebClient.class), tt, new ObjectMapper(),
                Mockito.mock(IntentRouterService.class), Mockito.mock(AiIntegrationService.class), redis,
                Mockito.mock(AiMultiChatFailoverService.class));
    }
}
