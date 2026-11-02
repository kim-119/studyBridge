package kr.co.studybridge.app.study

import android.content.Context
import android.os.Handler
import android.os.Looper
import kr.co.studybridge.app.R
import kr.co.studybridge.app.notification.StudyActionSource
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

object StudyRuntime {

    private val executor: ExecutorService = Executors.newSingleThreadExecutor()
    private val mainHandler = Handler(Looper.getMainLooper())
    private val actionInFlight = AtomicBoolean(false)

    @Volatile
    private var coordinator: StudySessionCoordinator? = null

    fun account(context: Context): StudyAccount = StudyAccount(context.applicationContext)

    fun statusStore(context: Context): StudyStatusStore = StudyStatusStore.from(context)

    fun currentSnapshot(context: Context): StudySnapshot = statusStore(context).read()

    fun hasUsableSession(context: Context): Boolean =
        account(context).authorizedUser(System.currentTimeMillis()) != null

    fun perform(
        context: Context,
        action: StudyAction,
        source: StudyActionSource,
        onFinished: (StudyActionResult) -> Unit = {},
    ) {
        val appContext = context.applicationContext
        if (action != StudyAction.REFRESH && !actionInFlight.compareAndSet(false, true)) {
            onFinished(StudyActionResult.Busy)
            return
        }

        executor.execute {
            val result = try {
                coordinatorFor(appContext).perform(action)
            } finally {
                if (action != StudyAction.REFRESH) actionInFlight.set(false)
            }
            if (result == StudyActionResult.LoginRequired && action != StudyAction.REFRESH) {
                rememberPendingAction(appContext, action)
            }
            val snapshot = statusStore(appContext).read()
            if (action == StudyAction.REFRESH) {
                StudySurfaces.renderSnapshot(appContext, snapshot)
            } else {
                StudySurfaces.render(appContext, snapshot, result, source)
            }
            mainHandler.post { onFinished(result) }
        }
    }

    fun rememberPendingAction(context: Context, action: StudyAction) {
        statusStore(context).savePendingAction(PendingStudyAction(action, System.currentTimeMillis()))
    }

    fun hasPendingAction(context: Context): Boolean = statusStore(context).hasPendingAction()

    fun runPendingActionIfFresh(context: Context) {
        val pending = statusStore(context).takePendingAction() ?: return
        if (!pending.isFreshAt(System.currentTimeMillis())) return
        perform(context, pending.action, StudyActionSource.NOTIFICATION)
    }

    fun clearForSignOut(context: Context) {
        val appContext = context.applicationContext
        executor.execute {
            statusStore(appContext).clearAll()
            StudySurfaces.clearAll(appContext)
        }
    }

    private fun coordinatorFor(context: Context): StudySessionCoordinator =
        coordinator ?: synchronized(this) {
            coordinator ?: StudySessionCoordinator(
                api = HttpStudyTimerApi(context.getString(R.string.studybridge_api_base_url)),
                credentials = StudyAccount(context),
                statusRepository = StudyStatusStore.from(context),
            ).also { coordinator = it }
        }
}
