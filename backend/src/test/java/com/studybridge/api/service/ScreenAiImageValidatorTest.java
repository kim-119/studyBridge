package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.studybridge.api.exception.ScreenAiException;
import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.util.Arrays;
import java.util.Base64;
import javax.imageio.ImageIO;
import org.junit.jupiter.api.Test;

/** 화면공유 프레임 검증: JPEG 만, Base64 엄격, 크기·해상도 상한(픽셀 디코딩 없이 SOF 헤더로), 손상 거부. */
class ScreenAiImageValidatorTest {

    private static final ScreenAiImageValidator.Limits LIMITS = new ScreenAiImageValidator.Limits(1024 * 1024, 1280, 32);

    static byte[] image(int w, int h, String format) throws Exception {
        BufferedImage img = new BufferedImage(w, h, BufferedImage.TYPE_INT_RGB);
        Graphics2D g = img.createGraphics();
        g.setColor(Color.WHITE);
        g.fillRect(0, 0, w, h);
        g.setColor(Color.BLACK);
        g.drawString("print(1/0)  ZeroDivisionError", 10, Math.max(12, h / 2));
        g.dispose();
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        ImageIO.write(img, format, out);
        return out.toByteArray();
    }

    static String jpegB64(int w, int h) throws Exception {
        return Base64.getEncoder().encodeToString(image(w, h, "jpg"));
    }

    @Test
    void acceptsJpeg_readsDimensionsFromHeader_andStripsDataUriPrefix() throws Exception {
        String b64 = jpegB64(1280, 720);
        ScreenAiImageValidator.ValidatedImage v = ScreenAiImageValidator.validate("data:image/jpeg;base64," + b64, "image/jpeg", LIMITS);
        assertEquals(1280, v.width());
        assertEquals(720, v.height());
        assertEquals(b64, v.base64());
        assertEquals(Base64.getDecoder().decode(b64).length, v.bytes());
        // image/jpg 도 JPEG 로 취급, toString 에 원문이 없다
        ScreenAiImageValidator.ValidatedImage portrait = ScreenAiImageValidator.validate(jpegB64(540, 1170), "image/jpg", LIMITS);
        assertEquals(540, portrait.width());
        assertFalse(portrait.toString().contains(portrait.base64().substring(0, 16)));
    }

    @Test
    void rejectsNonJpegMime_andPngBytesDeclaredAsJpeg() throws Exception {
        ScreenAiException mime = assertThrows(ScreenAiException.class, () -> ScreenAiImageValidator.validate(jpegB64(100, 100), "image/png", LIMITS));
        assertEquals(415, mime.getStatus().value());
        String png = Base64.getEncoder().encodeToString(image(100, 100, "png"));
        ScreenAiException mismatch = assertThrows(ScreenAiException.class, () -> ScreenAiImageValidator.validate(png, "image/jpeg", LIMITS));
        assertEquals(415, mismatch.getStatus().value());
        assertEquals("SCREEN_AI_IMAGE_INVALID", mismatch.getCode());
        ScreenAiException prefix = assertThrows(ScreenAiException.class,
                () -> ScreenAiImageValidator.validate("data:image/png;base64," + png, "image/jpeg", LIMITS));
        assertEquals(415, prefix.getStatus().value());
    }

    @Test
    void rejectsInvalidBase64_strictly() throws Exception {
        String b64 = jpegB64(200, 100);
        String withNewlines = b64.substring(0, 40) + "\n" + b64.substring(40);
        ScreenAiException ex = assertThrows(ScreenAiException.class, () -> ScreenAiImageValidator.validate(withNewlines, "image/jpeg", LIMITS));
        assertEquals(422, ex.getStatus().value());
        assertThrows(ScreenAiException.class, () -> ScreenAiImageValidator.validate("###not-base64###", "image/jpeg", LIMITS));
        assertThrows(ScreenAiException.class, () -> ScreenAiImageValidator.validate("", "image/jpeg", LIMITS));
        assertThrows(ScreenAiException.class, () -> ScreenAiImageValidator.validate(null, "image/jpeg", LIMITS));
    }

    @Test
    void rejectsOversizedPayload_beforeDecoding() throws Exception {
        ScreenAiImageValidator.Limits small = new ScreenAiImageValidator.Limits(2048, 1280, 32);
        ScreenAiException ex = assertThrows(ScreenAiException.class, () -> ScreenAiImageValidator.validate(jpegB64(1280, 720), "image/jpeg", small));
        assertEquals(413, ex.getStatus().value());
        assertEquals("SCREEN_AI_IMAGE_TOO_LARGE", ex.getCode());
        // 디코딩 전 길이 판단: 유효하지 않은 문자여도 길이로 먼저 거부
        char[] huge = new char[4 * 1024 * 1024];
        Arrays.fill(huge, 'A');
        assertEquals(413, assertThrows(ScreenAiException.class,
                () -> ScreenAiImageValidator.validate(new String(huge), "image/jpeg", LIMITS)).getStatus().value());
    }

    @Test
    void rejectsDimensionsOutsideContract() throws Exception {
        assertEquals(422, assertThrows(ScreenAiException.class,
                () -> ScreenAiImageValidator.validate(jpegB64(1281, 720), "image/jpeg", LIMITS)).getStatus().value());
        assertEquals(422, assertThrows(ScreenAiException.class,
                () -> ScreenAiImageValidator.validate(jpegB64(640, 31), "image/jpeg", LIMITS)).getStatus().value());
    }

    @Test
    void rejectsTruncatedJpegWithoutFrameHeader() throws Exception {
        byte[] full = image(320, 200, "jpg");
        int sof = 2;
        while (!((full[sof] & 0xFF) == 0xFF && (full[sof + 1] & 0xFF) == 0xC0)) sof++;
        byte[] head = Arrays.copyOf(full, sof + 4); // SOF 마커·길이까지만 — 가로·세로 전에 끊김
        ScreenAiException ex = assertThrows(ScreenAiException.class,
                () -> ScreenAiImageValidator.validate(Base64.getEncoder().encodeToString(head), "image/jpeg", LIMITS));
        assertEquals(422, ex.getStatus().value());
    }
}
