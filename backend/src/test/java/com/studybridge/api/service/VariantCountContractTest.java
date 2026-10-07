package com.studybridge.api.service;

import com.studybridge.api.entity.ReviewNote;
import com.studybridge.api.repository.*;
import com.sun.net.httpserver.HttpServer;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.reactive.function.client.WebClient;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class VariantCountContractTest {
 @Test void selectedThree_reachesAiAsThree_andReturnsThree() throws Exception { run(3, true); }
 @Test void shortAiAndShortFallback_isNotSuccessful() throws Exception { run(1, false); }
 private void run(int aiCount, boolean success) throws Exception {
  var mapper = new ObjectMapper(); var requested = new AtomicInteger();
  HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
  server.createContext("/api/ai/review/variant-question", exchange -> {
   var req=mapper.readTree(exchange.getRequestBody()); requested.compareAndSet(0,req.get("count").asInt());
   var questions=new ArrayList<Map<String,Object>>();
   for(int i=0;i<aiCount;i++) questions.add(Map.of("question","q"+i,"choices",List.of("a","b","c","d"),"correctAnswer","a"));
   byte[] out=mapper.writeValueAsBytes(Map.of("questions",questions));
   exchange.getResponseHeaders().add("Content-Type","application/json");exchange.sendResponseHeaders(200,out.length);exchange.getResponseBody().write(out);exchange.close();
  }); server.start();
  try {
   var repo=mock(ReviewNoteRepository.class);
   var note=ReviewNote.builder().reviewNoteId(1L).userId(2L).sourceMaterialId(3L).retryJson("[]").build();
   when(repo.findByReviewNoteIdAndUserId(1L,2L)).thenReturn(Optional.of(note));
   var service=new ReviewNoteService(repo,mock(MaterialQuizRepository.class),mock(MaterialRepository.class),mock(S3Service.class),WebClient.create("http://127.0.0.1:"+server.getAddress().getPort()),mock(LearningLoopService.class),mock(TodoRepository.class));
   ReflectionTestUtils.setField(service,"reviewTimeoutSeconds",10L);
   var response=service.variantQuestion(2L,1L,Map.of("count",3));
   assertEquals(3,requested.get());assertEquals(success,response.get("success"));assertEquals(aiCount,((List<?>)response.get("questions")).size());
  } finally {server.stop(0);}
 }
}
