package kr.co.studybridge.app.media

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * VoiceSessionController 의 상태 전이 규칙을 검증한다.
 * AudioManager 는 계측 테스트가 필요하므로, 여기서는 세션 상태 기계만 순수 로직으로 재현해
 * "중복 start 는 스피커만 갱신", "stop 은 이전 상태로 복원" 계약이 깨지지 않도록 고정한다.
 */
class VoiceSessionStateTest {

    private class SessionState(
        var active: Boolean = false,
        var speakerphone: Boolean = false,
        var restoredMode: Int? = null
    ) {
        var previousMode: Int = MODE_NORMAL

        fun start(currentMode: Int, useSpeakerphone: Boolean) {
            if (active) {
                speakerphone = useSpeakerphone
                return
            }
            previousMode = currentMode
            speakerphone = useSpeakerphone
            active = true
        }

        fun stop() {
            if (!active) return
            restoredMode = previousMode
            active = false
        }

        companion object {
            const val MODE_NORMAL = 0
        }
    }

    @Test
    fun `세션 시작 시 활성화되고 스피커 설정이 반영된다`() {
        val state = SessionState()

        state.start(currentMode = 0, useSpeakerphone = true)

        assertTrue(state.active)
        assertTrue(state.speakerphone)
    }

    @Test
    fun `이미 활성 상태에서 다시 시작하면 이전 모드를 덮어쓰지 않는다`() {
        val state = SessionState()

        state.start(currentMode = 0, useSpeakerphone = true)
        state.start(currentMode = 3, useSpeakerphone = false)

        assertEquals(0, state.previousMode)
        assertFalse(state.speakerphone)
    }

    @Test
    fun `세션 종료 시 직전 오디오 모드로 복원한다`() {
        val state = SessionState()

        state.start(currentMode = 2, useSpeakerphone = true)
        state.stop()

        assertFalse(state.active)
        assertEquals(2, state.restoredMode)
    }

    @Test
    fun `활성 상태가 아니면 종료는 아무것도 복원하지 않는다`() {
        val state = SessionState()

        state.stop()

        assertEquals(null, state.restoredMode)
    }
}
