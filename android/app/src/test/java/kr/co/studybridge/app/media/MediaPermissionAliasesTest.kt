package kr.co.studybridge.app.media

import org.junit.Assert.assertArrayEquals
import org.junit.Test

class MediaPermissionAliasesTest {

    @Test
    fun microphoneOnlyRequestDoesNotAskForCamera() {
        val aliases = mediaPermissionAliasesToRequest(
            wantsCamera = false,
            wantsMicrophone = true,
            cameraGranted = false,
            microphoneGranted = false
        )

        assertArrayEquals(arrayOf("microphone"), aliases)
    }

    @Test
    fun cameraAndMicrophoneRequestAsksForBothWhenNeitherIsGranted() {
        val aliases = mediaPermissionAliasesToRequest(
            wantsCamera = true,
            wantsMicrophone = true,
            cameraGranted = false,
            microphoneGranted = false
        )

        assertArrayEquals(arrayOf("camera", "microphone"), aliases)
    }

    @Test
    fun alreadyGrantedPermissionsAreNotRequestedAgain() {
        val aliases = mediaPermissionAliasesToRequest(
            wantsCamera = true,
            wantsMicrophone = true,
            cameraGranted = true,
            microphoneGranted = false
        )

        assertArrayEquals(arrayOf("microphone"), aliases)
    }

    @Test
    fun nothingIsRequestedWhenEveryWantedPermissionIsGranted() {
        val aliases = mediaPermissionAliasesToRequest(
            wantsCamera = false,
            wantsMicrophone = true,
            cameraGranted = false,
            microphoneGranted = true
        )

        assertArrayEquals(emptyArray<String>(), aliases)
    }
}
