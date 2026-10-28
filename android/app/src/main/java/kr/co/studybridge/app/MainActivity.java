package kr.co.studybridge.app;

import android.os.Bundle;
import android.util.Log;

import com.getcapacitor.BridgeActivity;
import com.getcapacitor.Plugin;

import kr.co.studybridge.app.media.StudyBridgeMediaPlugin;
import kr.co.studybridge.app.session.SecureSessionPlugin;

public class MainActivity extends BridgeActivity {

    private static final String SCREEN_SHARE_PLUGIN = "kr.co.studybridge.screenshare.ScreenSharePlugin";

    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(StudyBridgeMediaPlugin.class);
        registerPlugin(SecureSessionPlugin.class);
        registerScreenSharePlugin();
        super.onCreate(savedInstanceState);
    }

    // 화면공유 모듈은 -PsbScreenShare=true 빌드에만 들어간다. 기본 빌드에서는 클래스가 없으므로 이름으로만 찾는다.
    private void registerScreenSharePlugin() {
        if (!BuildConfig.SCREEN_SHARE_ENABLED) return;
        try {
            registerPlugin(Class.forName(SCREEN_SHARE_PLUGIN).asSubclass(Plugin.class));
        } catch (ClassNotFoundException | ClassCastException error) {
            Log.w("StudyBridge", "screen share plugin unavailable", error);
        }
    }
}
