package kr.co.studybridge.app.study

import android.content.Context
import android.content.SharedPreferences

interface StudyStatusRepository {
    fun read(): StudySnapshot
    fun write(snapshot: StudySnapshot)
}

data class PendingStudyAction(val action: StudyAction, val requestedAtMillis: Long) {
    fun isFreshAt(nowMillis: Long): Boolean = nowMillis - requestedAtMillis in 0..MAX_AGE_MS

    companion object {
        const val MAX_AGE_MS = 5 * 60 * 1000L
    }
}

class StudyStatusStore(private val preferences: SharedPreferences) : StudyStatusRepository {

    @Synchronized
    override fun read(): StudySnapshot = StudySnapshot(
        phase = StudyPhase.fromStorageKey(preferences.getString(PHASE_KEY, null)),
        startedAtMillis = readOptionalLong(STARTED_AT_KEY),
        todayCompletedSeconds = readOptionalLong(TODAY_SECONDS_KEY),
        todayDateKey = preferences.getString(TODAY_DATE_KEY, null),
        issue = StudyIssue.fromStorageKey(preferences.getString(ISSUE_KEY, null)),
        updatedAtMillis = preferences.getLong(UPDATED_AT_KEY, 0L),
    )

    @Synchronized
    override fun write(snapshot: StudySnapshot) {
        preferences.edit()
            .putString(PHASE_KEY, snapshot.phase.storageKey)
            .putOptionalLong(STARTED_AT_KEY, snapshot.startedAtMillis)
            .putOptionalLong(TODAY_SECONDS_KEY, snapshot.todayCompletedSeconds)
            .putString(TODAY_DATE_KEY, snapshot.todayDateKey)
            .putString(ISSUE_KEY, snapshot.issue.storageKey)
            .putLong(UPDATED_AT_KEY, snapshot.updatedAtMillis)
            .commit()
    }

    @Synchronized
    fun savePendingAction(pending: PendingStudyAction) {
        preferences.edit()
            .putString(PENDING_ACTION_KEY, pending.action.storageKey)
            .putLong(PENDING_REQUESTED_AT_KEY, pending.requestedAtMillis)
            .commit()
    }

    @Synchronized
    fun takePendingAction(): PendingStudyAction? {
        val action = StudyAction.fromStorageKey(preferences.getString(PENDING_ACTION_KEY, null))
        val requestedAt = preferences.getLong(PENDING_REQUESTED_AT_KEY, 0L)
        clearPendingAction()
        return action?.let { PendingStudyAction(it, requestedAt) }
    }

    @Synchronized
    fun hasPendingAction(): Boolean = preferences.contains(PENDING_ACTION_KEY)

    @Synchronized
    fun clearAll() {
        preferences.edit().clear().commit()
    }

    @Synchronized
    fun clearSnapshot() {
        val editor = preferences.edit()
        SNAPSHOT_KEYS.forEach { editor.remove(it) }
        editor.commit()
    }

    fun observe(listener: SharedPreferences.OnSharedPreferenceChangeListener) {
        preferences.registerOnSharedPreferenceChangeListener(listener)
    }

    fun stopObserving(listener: SharedPreferences.OnSharedPreferenceChangeListener) {
        preferences.unregisterOnSharedPreferenceChangeListener(listener)
    }

    private fun clearPendingAction() {
        preferences.edit().remove(PENDING_ACTION_KEY).remove(PENDING_REQUESTED_AT_KEY).commit()
    }

    private fun readOptionalLong(key: String): Long? =
        if (preferences.contains(key)) preferences.getLong(key, 0L) else null

    private fun SharedPreferences.Editor.putOptionalLong(key: String, value: Long?): SharedPreferences.Editor =
        if (value == null) remove(key) else putLong(key, value)

    companion object {
        private const val PREFERENCES_NAME = "studybridge_study_status"
        private const val PHASE_KEY = "phase"
        private const val STARTED_AT_KEY = "started_at"
        private const val TODAY_SECONDS_KEY = "today_completed_seconds"
        private const val TODAY_DATE_KEY = "today_date"
        private const val ISSUE_KEY = "issue"
        private const val UPDATED_AT_KEY = "updated_at"
        private const val PENDING_ACTION_KEY = "pending_action"
        private const val PENDING_REQUESTED_AT_KEY = "pending_requested_at"
        private val SNAPSHOT_KEYS = listOf(
            PHASE_KEY,
            STARTED_AT_KEY,
            TODAY_SECONDS_KEY,
            TODAY_DATE_KEY,
            ISSUE_KEY,
            UPDATED_AT_KEY,
        )

        fun from(context: Context): StudyStatusStore = StudyStatusStore(
            context.applicationContext.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE),
        )
    }
}
