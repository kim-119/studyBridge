package kr.co.studybridge.app.study

import org.json.JSONException
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class StudySessionCoordinator(
    private val api: StudyTimerApi,
    private val credentials: StudyCredentials,
    private val statusRepository: StudyStatusRepository,
    private val clock: () -> Long = System::currentTimeMillis,
) {

    @Synchronized
    fun perform(action: StudyAction): StudyActionResult = when (action) {
        StudyAction.START -> start()
        StudyAction.STOP -> stop()
        StudyAction.REFRESH -> refresh()
    }

    @Synchronized
    fun start(): StudyActionResult = withAuthorizedUser { user ->
        val current = api.currentSession(user.accessToken)?.takeIf { it.isActive }
        when {
            current == null -> {
                val started = api.startPersonalSession(user.accessToken)
                recordActiveSession(started, user)
                StudyActionResult.Started(started)
            }
            current.isPersonal -> {
                recordActiveSession(current, user)
                StudyActionResult.AlreadyStudying(current)
            }
            else -> {
                recordActiveSession(current, user)
                StudyActionResult.GroupSessionActive(current)
            }
        }
    }

    @Synchronized
    fun stop(): StudyActionResult = withAuthorizedUser { user ->
        val current = api.currentSession(user.accessToken)?.takeIf { it.isActive }
        when {
            current == null -> {
                recordIdle(user)
                StudyActionResult.NotStudying
            }
            !current.isPersonal -> {
                recordActiveSession(current, user)
                StudyActionResult.GroupSessionActive(current)
            }
            else -> {
                val ended = api.endSession(user.accessToken)
                recordIdle(user)
                StudyActionResult.Stopped(ended)
            }
        }
    }

    @Synchronized
    fun refresh(): StudyActionResult = withAuthorizedUser { user ->
        val current = api.currentSession(user.accessToken)?.takeIf { it.isActive }
        if (current == null) recordIdle(user) else recordActiveSession(current, user)
        StudyActionResult.Refreshed(statusRepository.read())
    }

    private fun withAuthorizedUser(block: (AuthorizedUser) -> StudyActionResult): StudyActionResult {
        val user = credentials.authorizedUser(clock())
        if (user == null) {
            recordIssue(StudyIssue.LOGIN_REQUIRED)
            return StudyActionResult.LoginRequired
        }

        return try {
            block(user)
        } catch (error: StudyApiException) {
            when (error.failure) {
                StudyApiFailure.UNAUTHORIZED -> {
                    recordIssue(StudyIssue.LOGIN_REQUIRED)
                    StudyActionResult.LoginRequired
                }
                StudyApiFailure.NETWORK -> {
                    recordIssue(StudyIssue.NETWORK)
                    StudyActionResult.NetworkUnavailable
                }
                StudyApiFailure.SERVER -> {
                    recordIssue(StudyIssue.SERVER)
                    StudyActionResult.ServerFailed
                }
            }
        } catch (error: JSONException) {
            recordIssue(StudyIssue.SERVER)
            StudyActionResult.ServerFailed
        }
    }

    private fun recordActiveSession(session: TimerSession, user: AuthorizedUser) {
        val phase = if (session.isPersonal) StudyPhase.STUDYING else StudyPhase.GROUP_STUDYING
        writeWithToday(user, phase, session.startedAtMillis)
    }

    private fun recordIdle(user: AuthorizedUser) {
        writeWithToday(user, StudyPhase.IDLE, startedAtMillis = null)
    }

    private fun writeWithToday(user: AuthorizedUser, phase: StudyPhase, startedAtMillis: Long?) {
        val now = clock()
        val previous = statusRepository.read()
        val todaySeconds = readTodaySeconds(user)
        val todayKey = serverDateKey(now)

        statusRepository.write(
            StudySnapshot(
                phase = phase,
                startedAtMillis = startedAtMillis,
                todayCompletedSeconds = todaySeconds ?: previous.todayCompletedSeconds.takeIf { previous.todayDateKey == todayKey },
                todayDateKey = if (todaySeconds != null) todayKey else previous.todayDateKey.takeIf { it == todayKey },
                issue = StudyIssue.NONE,
                updatedAtMillis = now,
            ),
        )
    }

    private fun readTodaySeconds(user: AuthorizedUser): Long? =
        try {
            api.todayCompletedSeconds(user.accessToken)
        } catch (error: StudyApiException) {
            null
        } catch (error: JSONException) {
            null
        }

    private fun recordIssue(issue: StudyIssue) {
        statusRepository.write(statusRepository.read().copy(issue = issue, updatedAtMillis = clock()))
    }

    companion object {
        fun serverDateKey(epochMillis: Long): String {
            val format = SimpleDateFormat("yyyy-MM-dd", Locale.US)
            format.timeZone = TimerResponseParser.SERVER_TIME_ZONE
            return format.format(Date(epochMillis))
        }
    }
}
