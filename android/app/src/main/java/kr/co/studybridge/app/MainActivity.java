package kr.co.studybridge.app;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

import kr.co.studybridge.app.media.StudyBridgeMediaPlugin;

public class MainActivity extends BridgeActivity {

    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(StudyBridgeMediaPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
