// JVM(javax.crypto.Mac — Spring 과 같은 런타임) 로 서명 벡터를 독립 재계산한다.
//   docker run --rm -v "$PWD/app/contracts/fixtures:/v:ro" -v "$PWD/scripts:/s:ro" eclipse-temurin:21-jdk \
//     java /s/verify_signing_vectors.java /v/signing-vectors.v1.tsv <keys as ENV=VALUE ...>
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

public class verify_signing_vectors {
    public static void main(String[] args) throws Exception {
        Map<String, String> keys = new HashMap<>();
        for (int i = 1; i < args.length; i++) { String[] kv = args[i].split("=", 2); keys.put(kv[0], kv[1]); }
        int ok = 0, bad = 0;
        for (String line : Files.readAllLines(Path.of(args[0]), StandardCharsets.UTF_8)) {
            if (line.isBlank()) continue;
            String[] f = line.split("\t");
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(keys.get(f[1]).getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            byte[] raw = mac.doFinal(Base64.getDecoder().decode(f[2]));
            String got = f[0].equals("HEX") ? HexFormat.of().formatHex(raw)
                                             : Base64.getUrlEncoder().withoutPadding().encodeToString(raw);
            boolean eq = java.security.MessageDigest.isEqual(got.getBytes(), f[3].getBytes());
            System.out.println((eq ? "OK   " : "FAIL ") + f[0] + " " + f[1]);
            if (eq) ok++; else bad++;
        }
        System.out.println("java=" + System.getProperty("java.version") + " ok=" + ok + " fail=" + bad);
        System.exit(bad == 0 ? 0 : 1);
    }
}
