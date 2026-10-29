package kr.co.studybridge.app;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

import kr.co.studybridge.app.media.StudyBridgeMediaPlugin;
import kr.co.studybridge.app.session.SecureSessionPlugin;
import kr.co.studybridge.screenshare.ScreenSharePlugin;

public class MainActivity extends BridgeActivity {

    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(StudyBridgeMediaPlugin.class);
        registerPlugin(SecureSessionPlugin.class);
        registerPlugin(ScreenSharePlugin.class);
        super.onCreate(savedInstanceState);
    }
}
