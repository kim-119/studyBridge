package kr.co.studybridge.app.media

const val CAMERA_ALIAS = "camera"
const val MICROPHONE_ALIAS = "microphone"

fun mediaPermissionAliasesToRequest(
    wantsCamera: Boolean,
    wantsMicrophone: Boolean,
    cameraGranted: Boolean,
    microphoneGranted: Boolean
): Array<String> {
    val aliases = mutableListOf<String>()
    if (wantsCamera && !cameraGranted) aliases.add(CAMERA_ALIAS)
    if (wantsMicrophone && !microphoneGranted) aliases.add(MICROPHONE_ALIAS)
    return aliases.toTypedArray()
}
