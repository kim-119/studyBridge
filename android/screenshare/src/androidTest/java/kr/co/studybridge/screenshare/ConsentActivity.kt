package kr.co.studybridge.screenshare

import android.app.Activity
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.os.Bundle
import java.util.concurrent.CompletableFuture

/** 실제 시스템 화면 녹화 동의(createScreenCaptureIntent)를 받아 결과를 테스트에 넘긴다. 앱과 같은 경로다. */
class ConsentActivity : Activity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (savedInstanceState == null) {
            val manager = getSystemService(MediaProjectionManager::class.java)
            @Suppress("DEPRECATION")
            startActivityForResult(manager.createScreenCaptureIntent(), REQUEST_CODE)
        }
    }

    @Deprecated("Activity result API 대신 테스트 전용으로 단순한 방식을 쓴다.")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        @Suppress("DEPRECATION")
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQUEST_CODE) result.complete(resultCode to data)
    }

    companion object {
        private const val REQUEST_CODE = 0x5C
        @Volatile
        var result: CompletableFuture<Pair<Int, Intent?>> = CompletableFuture()
    }
}
