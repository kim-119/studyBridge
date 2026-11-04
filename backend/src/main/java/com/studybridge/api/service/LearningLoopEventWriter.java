package com.studybridge.api.service;

import com.studybridge.api.entity.LearningLoopEvent;
import com.studybridge.api.repository.LearningLoopEventRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/**
 * 학습 루프 이벤트의 유일한 쓰기 경로(별도 빈).
 *
 * LearningLoopService 가 같은 클래스의 @Transactional(REQUIRES_NEW) 메서드를 직접 호출하면 프록시를 거치지 않아
 * 독립 트랜잭션이 생기지 않는다(호출자 트랜잭션에 합류 → INSERT 실패가 호출자를 rollback-only 로 만든다).
 * 그래서 쓰기는 이 빈을 통해서만 하고, 여기서 항상 새 read-write 트랜잭션을 연다.
 */
@Component
@RequiredArgsConstructor
class LearningLoopEventWriter {

    private final LearningLoopEventRepository eventRepository;

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public LearningLoopEvent write(LearningLoopEvent event) {
        // saveAndFlush: DB 오류(길이 초과 등)를 이 트랜잭션 안에서 드러내 호출자 쪽으로 새지 않게 한다.
        return eventRepository.saveAndFlush(event);
    }
}
