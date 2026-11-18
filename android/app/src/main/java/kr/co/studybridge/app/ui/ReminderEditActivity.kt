package kr.co.studybridge.app.ui

import android.app.TimePickerDialog
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.RadioGroup
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.SwitchCompat
import kr.co.studybridge.app.R
import kr.co.studybridge.app.notification.StudyNotificationChannels
import kr.co.studybridge.app.notification.StudyNotificationPoster
import kr.co.studybridge.app.reminder.MAX_REMINDER_TITLE_LENGTH
import kr.co.studybridge.app.reminder.NEW_REMINDER_ID
import kr.co.studybridge.app.reminder.ReminderAlertStyle
import kr.co.studybridge.app.reminder.ReminderDay
import kr.co.studybridge.app.reminder.ReminderScheduler
import kr.co.studybridge.app.reminder.ReminderStore
import kr.co.studybridge.app.reminder.ReminderValidationError
import kr.co.studybridge.app.reminder.ReminderValidator
import kr.co.studybridge.app.reminder.StudyReminder
import kr.co.studybridge.app.study.StudyAccount
import kr.co.studybridge.app.study.StudyTimeText

class ReminderEditActivity : AppCompatActivity() {

    private lateinit var store: ReminderStore
    private lateinit var displayPreferences: ReminderDisplayPreferences
    private lateinit var titleInput: EditText
    private lateinit var timeText: TextView
    private lateinit var use24HourCheckBox: CheckBox
    private lateinit var enabledSwitch: SwitchCompat
    private lateinit var alertStyleGroup: RadioGroup
    private lateinit var dayCheckBoxes: Map<ReminderDay, CheckBox>

    private var userId: Long = 0L
    private var reminderId: Int = NEW_REMINDER_ID
    private var hour: Int = DEFAULT_HOUR
    private var minute: Int = DEFAULT_MINUTE

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_reminder_edit)
        setSupportActionBar(findViewById(R.id.reminder_toolbar))
        SystemBarInsets.padForSystemBars(findViewById(R.id.reminder_edit_root))
        supportActionBar?.setDisplayHomeAsUpEnabled(true)

        val currentUserId = StudyAccount(this).currentUserId()
        if (currentUserId == null) {
            Toast.makeText(this, R.string.reminder_signed_out, Toast.LENGTH_LONG).show()
            finish()
            return
        }
        userId = currentUserId
        store = ReminderStore.from(this)
        displayPreferences = ReminderDisplayPreferences.from(this)
        bindViews()

        val existing = intent.getIntExtra(EXTRA_REMINDER_ID, NEW_REMINDER_ID)
            .takeIf { it != NEW_REMINDER_ID }
            ?.let { store.find(userId, it) }
        title = getString(if (existing == null) R.string.reminder_add_title else R.string.reminder_edit_title)
        showReminder(existing ?: newReminderDraft())

        savedInstanceState?.let {
            hour = it.getInt(STATE_HOUR, hour)
            minute = it.getInt(STATE_MINUTE, minute)
            renderTime()
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putInt(STATE_HOUR, hour)
        outState.putInt(STATE_MINUTE, minute)
    }

    override fun onSupportNavigateUp(): Boolean {
        finish()
        return true
    }

    private fun bindViews() {
        titleInput = findViewById(R.id.reminder_title_input)
        timeText = findViewById(R.id.reminder_time_text)
        use24HourCheckBox = findViewById(R.id.reminder_use_24_hour)
        enabledSwitch = findViewById(R.id.reminder_enabled_switch)
        alertStyleGroup = findViewById(R.id.reminder_alert_style_group)
        dayCheckBoxes = mapOf(
            ReminderDay.MONDAY to findViewById(R.id.reminder_day_monday),
            ReminderDay.TUESDAY to findViewById(R.id.reminder_day_tuesday),
            ReminderDay.WEDNESDAY to findViewById(R.id.reminder_day_wednesday),
            ReminderDay.THURSDAY to findViewById(R.id.reminder_day_thursday),
            ReminderDay.FRIDAY to findViewById(R.id.reminder_day_friday),
            ReminderDay.SATURDAY to findViewById(R.id.reminder_day_saturday),
            ReminderDay.SUNDAY to findViewById(R.id.reminder_day_sunday),
        )

        use24HourCheckBox.isChecked = displayPreferences.uses24Hour()
        use24HourCheckBox.setOnCheckedChangeListener { _, isChecked ->
            displayPreferences.setUses24Hour(isChecked)
            renderTime()
        }
        findViewById<Button>(R.id.reminder_pick_time_button).setOnClickListener { showTimePicker() }
        timeText.setOnClickListener { showTimePicker() }
        findViewById<Button>(R.id.reminder_channel_settings_button).setOnClickListener { openChannelSettings() }
        findViewById<Button>(R.id.reminder_save_button).setOnClickListener { saveReminder() }
        findViewById<Button>(R.id.reminder_cancel_button).setOnClickListener { finish() }
    }

    private fun newReminderDraft(): StudyReminder = StudyReminder(
        id = NEW_REMINDER_ID,
        title = "",
        hour = DEFAULT_HOUR,
        minute = DEFAULT_MINUTE,
        repeatDays = emptySet(),
        enabled = true,
        alertStyle = ReminderAlertStyle.SOUND_AND_VIBRATION,
    )

    private fun showReminder(reminder: StudyReminder) {
        reminderId = reminder.id
        hour = reminder.hour
        minute = reminder.minute
        titleInput.setText(reminder.title)
        enabledSwitch.isChecked = reminder.enabled
        dayCheckBoxes.forEach { (day, checkBox) -> checkBox.isChecked = day in reminder.repeatDays }
        alertStyleGroup.check(ReminderAlertStyleOptions.radioIdOf(reminder.alertStyle))
        renderTime()
    }

    private fun renderTime() {
        timeText.text = StudyTimeText.hourMinuteLabel(hour, minute, displayPreferences.uses24Hour())
    }

    private fun showTimePicker() {
        TimePickerDialog(
            this,
            { _, pickedHour, pickedMinute ->
                hour = pickedHour
                minute = pickedMinute
                renderTime()
            },
            hour,
            minute,
            displayPreferences.uses24Hour(),
        ).show()
    }

    private fun collectReminder(): StudyReminder = StudyReminder(
        id = reminderId,
        title = titleInput.text.toString().trim(),
        hour = hour,
        minute = minute,
        repeatDays = dayCheckBoxes.filterValues { it.isChecked }.keys,
        enabled = enabledSwitch.isChecked,
        alertStyle = ReminderAlertStyleOptions.styleOf(alertStyleGroup.checkedRadioButtonId),
    )

    private fun saveReminder() {
        val draft = collectReminder()
        val errors = ReminderValidator.validate(draft)
        if (errors.isNotEmpty()) {
            showValidationError(errors.first())
            return
        }

        val saved = store.save(userId, draft)
        val scheduled = ReminderScheduler.from(this).apply(saved)
        val message = when {
            scheduled != null -> ReminderMessages.scheduled(this, scheduled)
            saved.enabled -> getString(R.string.reminder_schedule_failed)
            else -> getString(R.string.reminder_saved_disabled)
        }
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
        if (saved.enabled && !StudyNotificationPoster.canPost(this)) {
            Toast.makeText(this, R.string.reminder_notification_blocked, Toast.LENGTH_LONG).show()
        }
        finish()
    }

    private fun showValidationError(error: ReminderValidationError) {
        when (error) {
            ReminderValidationError.TITLE_TOO_LONG ->
                titleInput.error = getString(R.string.reminder_title_too_long, MAX_REMINDER_TITLE_LENGTH)
            ReminderValidationError.HOUR_OUT_OF_RANGE,
            ReminderValidationError.MINUTE_OUT_OF_RANGE ->
                Toast.makeText(this, R.string.reminder_time_invalid, Toast.LENGTH_SHORT).show()
        }
    }

    private fun openChannelSettings() {
        val style = ReminderAlertStyleOptions.styleOf(alertStyleGroup.checkedRadioButtonId)
        val intent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            StudyNotificationChannels.registerAll(this)
            Intent(Settings.ACTION_CHANNEL_NOTIFICATION_SETTINGS)
                .putExtra(Settings.EXTRA_APP_PACKAGE, packageName)
                .putExtra(Settings.EXTRA_CHANNEL_ID, StudyNotificationChannels.reminderChannelId(style))
        } else {
            Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName"))
        }
        startActivity(intent)
    }

    companion object {
        const val EXTRA_REMINDER_ID = "kr.co.studybridge.app.extra.REMINDER_ID"
        private const val STATE_HOUR = "state_hour"
        private const val STATE_MINUTE = "state_minute"
        private const val DEFAULT_HOUR = 20
        private const val DEFAULT_MINUTE = 0
    }
}
