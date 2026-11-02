package kr.co.studybridge.app.ui

import android.Manifest
import android.app.StatusBarManager
import android.appwidget.AppWidgetManager
import android.content.ActivityNotFoundException
import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.drawable.Icon
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.View
import android.widget.Button
import android.widget.ListView
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import kr.co.studybridge.app.R
import kr.co.studybridge.app.notification.StudyNotificationPoster
import kr.co.studybridge.app.reminder.ReminderScheduler
import kr.co.studybridge.app.reminder.ReminderStore
import kr.co.studybridge.app.reminder.StudyReminder
import kr.co.studybridge.app.study.StudyAccount
import kr.co.studybridge.app.tile.StudyQuickSettingsTileService
import kr.co.studybridge.app.widget.StudyTimeWidgetProvider

class ReminderSettingsActivity : AppCompatActivity() {

    private lateinit var store: ReminderStore
    private lateinit var scheduler: ReminderScheduler
    private lateinit var adapter: ReminderListAdapter
    private var userId: Long? = null

    private val notificationPermissionRequest =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { renderPermissionStatus() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_reminder_settings)
        setSupportActionBar(findViewById(R.id.reminder_toolbar))
        SystemBarInsets.padForSystemBars(findViewById(R.id.reminder_settings_root))
        title = getString(R.string.reminder_settings_title)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)

        store = ReminderStore.from(this)
        scheduler = ReminderScheduler.from(this)
        adapter = ReminderListAdapter(this, ReminderDisplayPreferences.from(this), ::onEnabledChanged, ::openEditor, ::confirmDelete)

        val list = findViewById<ListView>(R.id.reminder_list)
        list.adapter = adapter
        list.emptyView = findViewById(R.id.reminder_empty)

        findViewById<Button>(R.id.reminder_add_button).setOnClickListener { openEditor(null) }
        findViewById<Button>(R.id.reminder_notification_permission_button).setOnClickListener { requestNotificationPermission() }
        findViewById<Button>(R.id.reminder_exact_alarm_button).setOnClickListener { openExactAlarmSettings() }
        findViewById<Button>(R.id.reminder_add_tile_button).setOnClickListener { requestAddTile() }
        findViewById<Button>(R.id.reminder_add_widget_button).setOnClickListener { requestPinWidget() }
    }

    override fun onResume() {
        super.onResume()
        userId = StudyAccount(this).currentUserId()
        renderPermissionStatus()
        renderReminders()
    }

    override fun onSupportNavigateUp(): Boolean {
        finish()
        return true
    }

    private fun renderReminders() {
        val currentUserId = userId
        val signedIn = currentUserId != null
        findViewById<View>(R.id.reminder_signed_out).visibility = if (signedIn) View.GONE else View.VISIBLE
        findViewById<Button>(R.id.reminder_add_button).isEnabled = signedIn
        adapter.submit(if (currentUserId == null) emptyList() else store.list(currentUserId))
    }

    private fun renderPermissionStatus() {
        val canNotify = StudyNotificationPoster.canPost(this)
        findViewById<TextView>(R.id.reminder_notification_status).setText(
            if (canNotify) R.string.reminder_notification_allowed else R.string.reminder_notification_blocked,
        )
        findViewById<Button>(R.id.reminder_notification_permission_button).visibility =
            if (canNotify) View.GONE else View.VISIBLE

        val exact = scheduler.canScheduleExactAlarms()
        findViewById<TextView>(R.id.reminder_exact_alarm_status).setText(
            if (exact) R.string.reminder_exact_alarm_allowed else R.string.reminder_exact_alarm_inexact,
        )
        findViewById<Button>(R.id.reminder_exact_alarm_button).visibility =
            if (exact || Build.VERSION.SDK_INT < Build.VERSION_CODES.S) View.GONE else View.VISIBLE

        findViewById<TextView>(R.id.reminder_tile_guide).setText(
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) R.string.reminder_tile_guide_button else R.string.reminder_tile_guide_manual,
        )
        findViewById<Button>(R.id.reminder_add_tile_button).visibility =
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) View.VISIBLE else View.GONE

        val canPinWidget = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
            AppWidgetManager.getInstance(this)?.isRequestPinAppWidgetSupported == true
        findViewById<TextView>(R.id.reminder_widget_guide).setText(
            if (canPinWidget) R.string.reminder_widget_guide_button else R.string.reminder_widget_guide_manual,
        )
        findViewById<Button>(R.id.reminder_add_widget_button).visibility = if (canPinWidget) View.VISIBLE else View.GONE
    }

    private fun onEnabledChanged(reminder: StudyReminder, enabled: Boolean) {
        val currentUserId = userId ?: return
        val updated = store.setEnabled(currentUserId, reminder.id, enabled) ?: return
        val scheduled = scheduler.apply(updated)
        if (enabled && scheduled != null) {
            Toast.makeText(this, ReminderMessages.scheduled(this, scheduled), Toast.LENGTH_LONG).show()
        }
        if (enabled) requestNotificationPermissionIfNeeded()
        renderReminders()
    }

    private fun openEditor(reminder: StudyReminder?) {
        val intent = Intent(this, ReminderEditActivity::class.java)
        if (reminder != null) intent.putExtra(ReminderEditActivity.EXTRA_REMINDER_ID, reminder.id)
        startActivity(intent)
    }

    private fun confirmDelete(reminder: StudyReminder) {
        AlertDialog.Builder(this)
            .setTitle(R.string.reminder_delete_title)
            .setMessage(getString(R.string.reminder_delete_message, reminder.displayTitle))
            .setNegativeButton(R.string.reminder_cancel, null)
            .setPositiveButton(R.string.reminder_delete) { _, _ -> deleteReminder(reminder) }
            .show()
    }

    private fun deleteReminder(reminder: StudyReminder) {
        val currentUserId = userId ?: return
        scheduler.cancel(reminder.id)
        store.delete(currentUserId, reminder.id)
        renderReminders()
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (!StudyNotificationPoster.canPost(this)) requestNotificationPermission()
    }

    private fun requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && !hasNotificationRuntimePermission()) {
            notificationPermissionRequest.launch(Manifest.permission.POST_NOTIFICATIONS)
            return
        }
        openAppNotificationSettings()
    }

    private fun hasNotificationRuntimePermission(): Boolean =
        checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    private fun openAppNotificationSettings() {
        val intent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, packageName)
        } else {
            Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName"))
        }
        startActivity(intent)
    }

    private fun openExactAlarmSettings() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return
        val intent = Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM, Uri.parse("package:$packageName"))
        try {
            startActivity(intent)
        } catch (error: ActivityNotFoundException) {
            Toast.makeText(this, R.string.reminder_exact_alarm_unavailable, Toast.LENGTH_LONG).show()
        }
    }

    private fun requestPinWidget() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = AppWidgetManager.getInstance(this) ?: return
        val requested = manager.requestPinAppWidget(ComponentName(this, StudyTimeWidgetProvider::class.java), null, null)
        if (!requested) Toast.makeText(this, R.string.reminder_widget_guide_manual, Toast.LENGTH_LONG).show()
    }

    private fun requestAddTile() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        val statusBarManager = getSystemService(StatusBarManager::class.java) ?: return
        statusBarManager.requestAddTileService(
            ComponentName(this, StudyQuickSettingsTileService::class.java),
            getString(R.string.study_tile_label),
            Icon.createWithResource(this, R.drawable.ic_stat_study),
            mainExecutor,
        ) { result -> Toast.makeText(this, ReminderMessages.tileRequestResult(this, result), Toast.LENGTH_SHORT).show() }
    }
}
