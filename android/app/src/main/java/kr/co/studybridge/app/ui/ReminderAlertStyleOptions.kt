package kr.co.studybridge.app.ui

import kr.co.studybridge.app.R
import kr.co.studybridge.app.reminder.ReminderAlertStyle

object ReminderAlertStyleOptions {

    private val radioIdsByStyle = linkedMapOf(
        ReminderAlertStyle.SOUND_AND_VIBRATION to R.id.reminder_alert_sound_vibration,
        ReminderAlertStyle.SOUND_ONLY to R.id.reminder_alert_sound,
        ReminderAlertStyle.VIBRATION_ONLY to R.id.reminder_alert_vibration,
        ReminderAlertStyle.SILENT to R.id.reminder_alert_silent,
    )

    fun radioIdOf(style: ReminderAlertStyle): Int = radioIdsByStyle.getValue(style)

    fun styleOf(radioId: Int): ReminderAlertStyle =
        radioIdsByStyle.entries.firstOrNull { it.value == radioId }?.key ?: ReminderAlertStyle.SOUND_AND_VIBRATION
}
