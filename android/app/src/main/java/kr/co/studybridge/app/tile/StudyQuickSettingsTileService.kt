package kr.co.studybridge.app.tile

import android.annotation.SuppressLint
import android.content.Intent
import android.content.SharedPreferences
import android.graphics.drawable.Icon
import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import kr.co.studybridge.app.MainActivity
import kr.co.studybridge.app.R
import kr.co.studybridge.app.notification.StudyActionSource
import kr.co.studybridge.app.notification.StudyPendingIntents
import kr.co.studybridge.app.study.StudyAction
import kr.co.studybridge.app.study.StudyRuntime
import java.util.concurrent.atomic.AtomicBoolean

class StudyQuickSettingsTileService : TileService() {

    private val statusChangeListener = SharedPreferences.OnSharedPreferenceChangeListener { _, _ -> renderTile() }

    override fun onStartListening() {
        super.onStartListening()
        StudyRuntime.statusStore(this).observe(statusChangeListener)
        renderTile()
        if (StudyRuntime.hasUsableSession(this) && isSnapshotStale()) {
            StudyRuntime.perform(this, StudyAction.REFRESH, StudyActionSource.TILE) { renderTile() }
        }
    }

    override fun onStopListening() {
        StudyRuntime.statusStore(this).stopObserving(statusChangeListener)
        super.onStopListening()
    }

    override fun onClick() {
        super.onClick()
        if (isLocked) {
            unlockAndRun { handleClick() }
        } else {
            handleClick()
        }
    }

    private fun handleClick() {
        if (working.get()) return
        val display = currentDisplay()
        val action = display.clickAction ?: return

        if (display.mode == StudyTileMode.LOGIN_REQUIRED) {
            StudyRuntime.rememberPendingAction(this, action)
            openApp()
            return
        }

        working.set(true)
        renderTile()
        StudyRuntime.perform(this, action, StudyActionSource.TILE) {
            working.set(false)
            renderTile()
        }
    }

    private fun renderTile() {
        val tile = qsTile ?: return
        val display = currentDisplay()
        tile.label = display.label
        tile.icon = Icon.createWithResource(this, R.drawable.ic_stat_study)
        tile.state = if (display.isActive) Tile.STATE_ACTIVE else Tile.STATE_INACTIVE
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            tile.subtitle = StudyTileDisplays.subtitleOf(display)
        }
        tile.updateTile()
    }

    private fun currentDisplay(): StudyTileDisplay =
        StudyTileDisplays.of(
            snapshot = StudyRuntime.currentSnapshot(this),
            hasUsableSession = StudyRuntime.hasUsableSession(this),
            isWorking = working.get(),
        )

    private fun isSnapshotStale(): Boolean =
        System.currentTimeMillis() - StudyRuntime.currentSnapshot(this).updatedAtMillis > STALE_AFTER_MS

    @SuppressLint("StartActivityAndCollapseDeprecated")
    private fun openApp() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startActivityAndCollapse(StudyPendingIntents.openApp(this, StudyActionSource.TILE))
        } else {
            @Suppress("DEPRECATION")
            startActivityAndCollapse(
                Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            )
        }
    }

    companion object {
        private const val STALE_AFTER_MS = 60_000L
        private val working = AtomicBoolean(false)
    }
}
