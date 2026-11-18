package kr.co.studybridge.app.ui

import android.content.Context
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.BaseAdapter
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.widget.SwitchCompat
import kr.co.studybridge.app.R
import kr.co.studybridge.app.reminder.StudyReminder
import kr.co.studybridge.app.study.StudyTimeText

class ReminderListAdapter(
    context: Context,
    private val displayPreferences: ReminderDisplayPreferences,
    private val onEnabledChanged: (StudyReminder, Boolean) -> Unit,
    private val onEdit: (StudyReminder) -> Unit,
    private val onDelete: (StudyReminder) -> Unit,
) : BaseAdapter() {

    private val inflater = LayoutInflater.from(context)
    private var reminders: List<StudyReminder> = emptyList()

    fun submit(updated: List<StudyReminder>) {
        reminders = updated
        notifyDataSetChanged()
    }

    override fun getCount(): Int = reminders.size

    override fun getItem(position: Int): StudyReminder = reminders[position]

    override fun getItemId(position: Int): Long = reminders[position].id.toLong()

    override fun hasStableIds(): Boolean = true

    override fun getView(position: Int, convertView: View?, parent: ViewGroup): View {
        val view = convertView ?: inflater.inflate(R.layout.item_study_reminder, parent, false)
        val holder = (view.tag as? RowViews) ?: RowViews(view).also { view.tag = it }
        bind(holder, getItem(position))
        return view
    }

    private fun bind(holder: RowViews, reminder: StudyReminder) {
        holder.time.text = StudyTimeText.hourMinuteLabel(reminder.hour, reminder.minute, displayPreferences.uses24Hour())
        holder.title.text = reminder.displayTitle
        holder.repeat.text = ReminderMessages.repeatLabel(reminder)

        holder.enabled.setOnCheckedChangeListener(null)
        holder.enabled.isChecked = reminder.enabled
        holder.enabled.contentDescription = holder.enabled.context.getString(
            if (reminder.enabled) R.string.reminder_enabled_on else R.string.reminder_enabled_off,
        )
        holder.enabled.setOnCheckedChangeListener { _, isChecked -> onEnabledChanged(reminder, isChecked) }

        holder.edit.setOnClickListener { onEdit(reminder) }
        holder.delete.setOnClickListener { onDelete(reminder) }
    }

    private class RowViews(view: View) {
        val time: TextView = view.findViewById(R.id.reminder_item_time)
        val title: TextView = view.findViewById(R.id.reminder_item_title)
        val repeat: TextView = view.findViewById(R.id.reminder_item_repeat)
        val enabled: SwitchCompat = view.findViewById(R.id.reminder_item_enabled)
        val edit: Button = view.findViewById(R.id.reminder_item_edit)
        val delete: Button = view.findViewById(R.id.reminder_item_delete)
    }
}
