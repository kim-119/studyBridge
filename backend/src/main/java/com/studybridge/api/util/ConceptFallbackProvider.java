package com.studybridge.api.util;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/**
 * AI07 결과가 메타데이터 노이즈로 부적합할 때 사용할 "개념형 학습 항목" fallback 생성기.
 * 메타데이터(날짜/이름/표지)가 아니라 실제 학습 개념을 기반으로 한다.
 *
 * <p>자료/주제명에 안드로이드 계열 키워드가 보이면 안드로이드 개념 bank(주차별로 회전)에서 뽑고,
 * 그 외 주제는 주제명을 끼운 일반 개념 템플릿을 만든다. fallback 사용 여부는 호출부에서 로그로 남긴다.
 */
public final class ConceptFallbackProvider {

    private ConceptFallbackProvider() {}

    /** 개념형 학습 단위 한 묶음(로드맵 day / 플래너 item 공통). */
    public static final class Concept {
        public final String title;
        public final String objective;
        public final List<String> coreConcepts;
        public final List<String> tasks;
        public final List<String> reviewQuestions;
        public final String deliverable;

        Concept(String title, String objective, List<String> coreConcepts,
                List<String> tasks, List<String> reviewQuestions, String deliverable) {
            this.title = title;
            this.objective = objective;
            this.coreConcepts = coreConcepts;
            this.tasks = tasks;
            this.reviewQuestions = reviewQuestions;
            this.deliverable = deliverable;
        }
    }

    private static Concept c(String title, String objective, List<String> concepts,
                            List<String> tasks, List<String> questions, String deliverable) {
        return new Concept(title, objective, concepts, tasks, questions, deliverable);
    }

    // 안드로이드 개념 bank — 표지/날짜가 아닌 실제 학습 개념. 주차/일차 index로 회전 사용.
    private static final List<Concept> ANDROID_BANK = Arrays.asList(
        c("안드로이드 소개", "안드로이드의 기본 개념과 앱 구조를 이해한다.",
            Arrays.asList("안드로이드", "앱 구성 요소"),
            Arrays.asList("안드로이드란 무엇인지 정리한다.", "안드로이드 앱의 기본 구성 요소를 확인한다.", "Activity의 역할을 정리한다."),
            Arrays.asList("안드로이드 앱은 어떤 구성 요소로 이루어지는가?", "Activity는 어떤 역할을 하는가?"),
            "안드로이드 기본 구조 요약 노트"),
        c("Activity 생명주기", "Activity의 생명주기 콜백과 화면 전환 흐름을 이해한다.",
            Arrays.asList("Activity", "생명주기"),
            Arrays.asList("Activity의 주요 생명주기 콜백을 정리한다.", "onCreate~onDestroy 흐름을 정리한다.", "화면 회전 시 상태 보존 방법을 확인한다."),
            Arrays.asList("Activity 생명주기 콜백은 어떤 순서로 호출되는가?", "onPause와 onStop의 차이는 무엇인가?"),
            "Activity 생명주기 다이어그램 정리"),
        c("Fragment 역할", "Fragment의 개념과 Activity와의 관계를 이해한다.",
            Arrays.asList("Fragment", "FragmentManager"),
            Arrays.asList("Fragment가 필요한 이유를 정리한다.", "Activity와 Fragment의 역할을 비교한다.", "Fragment 생명주기를 확인한다."),
            Arrays.asList("Fragment는 어떤 상황에서 사용하는가?", "Activity와 Fragment의 생명주기는 어떻게 연결되는가?"),
            "Activity vs Fragment 비교 노트"),
        c("ViewModel 이해", "ViewModel이 필요한 이유와 데이터 보존 방식을 이해한다.",
            Arrays.asList("ViewModel", "상태 보존"),
            Arrays.asList("ViewModel이 필요한 이유를 정리한다.", "ViewModel의 생명주기를 확인한다.", "구성 변경 시 데이터가 유지되는 원리를 정리한다."),
            Arrays.asList("ViewModel은 왜 필요한가?", "ViewModel은 화면 회전에도 데이터를 어떻게 유지하는가?"),
            "ViewModel 동작 원리 요약"),
        c("AndroidManifest 이해", "AndroidManifest.xml의 역할과 주요 선언을 이해한다.",
            Arrays.asList("Manifest", "권한"),
            Arrays.asList("AndroidManifest.xml의 역할을 정리한다.", "컴포넌트 선언 방법을 확인한다.", "권한(permission) 선언을 정리한다."),
            Arrays.asList("AndroidManifest.xml에는 무엇을 선언하는가?", "권한은 어디에 어떻게 선언하는가?"),
            "Manifest 주요 선언 정리 노트"),
        c("Intent와 화면 이동", "Intent로 화면/데이터를 전달하는 방법을 이해한다.",
            Arrays.asList("Intent", "화면 전환"),
            Arrays.asList("명시적/암시적 Intent 차이를 정리한다.", "Intent로 데이터를 전달하는 방법을 확인한다.", "startActivity 흐름을 정리한다."),
            Arrays.asList("명시적 Intent와 암시적 Intent의 차이는 무엇인가?", "화면 간 데이터는 어떻게 전달하는가?"),
            "Intent 사용 패턴 정리"),
        c("RecyclerView 기초", "목록 화면을 위한 RecyclerView 구조를 이해한다.",
            Arrays.asList("RecyclerView", "Adapter"),
            Arrays.asList("RecyclerView의 구성 요소를 정리한다.", "Adapter와 ViewHolder의 역할을 확인한다.", "리스트 갱신 방법을 정리한다."),
            Arrays.asList("RecyclerView는 어떤 요소로 동작하는가?", "ViewHolder 패턴은 왜 사용하는가?"),
            "RecyclerView 구조 요약"),
        c("Jetpack Compose 입문", "선언형 UI인 Jetpack Compose의 기본을 이해한다.",
            Arrays.asList("Compose", "선언형 UI"),
            Arrays.asList("Composable 함수의 개념을 정리한다.", "상태(state)와 recomposition을 확인한다.", "기존 View 방식과 차이를 비교한다."),
            Arrays.asList("Composable 함수란 무엇인가?", "recomposition은 언제 일어나는가?"),
            "Compose 기본 개념 노트"),
        c("Coroutine 기초", "코루틴으로 비동기 처리를 다루는 방법을 이해한다.",
            Arrays.asList("Coroutine", "비동기"),
            Arrays.asList("코루틴이 필요한 이유를 정리한다.", "suspend 함수의 개념을 확인한다.", "Dispatchers의 종류를 정리한다."),
            Arrays.asList("코루틴은 왜 사용하는가?", "suspend 함수는 일반 함수와 무엇이 다른가?"),
            "코루틴 기본 개념 요약"),
        c("Retrofit 네트워킹", "Retrofit으로 REST API를 호출하는 방법을 이해한다.",
            Arrays.asList("Retrofit", "REST API"),
            Arrays.asList("Retrofit의 기본 구성을 정리한다.", "인터페이스 정의 방법을 확인한다.", "응답 처리 흐름을 정리한다."),
            Arrays.asList("Retrofit은 어떤 역할을 하는가?", "API 응답은 어떻게 데이터 클래스로 매핑되는가?"),
            "Retrofit 사용 흐름 정리"),
        c("Room 데이터베이스", "로컬 저장을 위한 Room의 기본 구조를 이해한다.",
            Arrays.asList("Room", "DAO"),
            Arrays.asList("Room의 구성 요소를 정리한다.", "Entity와 DAO의 역할을 확인한다.", "기본 쿼리 작성을 정리한다."),
            Arrays.asList("Room은 어떤 요소로 구성되는가?", "DAO는 어떤 역할을 하는가?"),
            "Room 구조 요약 노트"),
        c("MVVM 아키텍처", "안드로이드 권장 아키텍처인 MVVM 구조를 이해한다.",
            Arrays.asList("MVVM", "아키텍처"),
            Arrays.asList("MVVM의 각 계층 역할을 정리한다.", "ViewModel과 Repository의 관계를 확인한다.", "단방향 데이터 흐름을 정리한다."),
            Arrays.asList("MVVM은 어떤 계층으로 나뉘는가?", "Repository는 어떤 역할을 하는가?"),
            "MVVM 계층 구조 정리")
    );

    private static final String[] ANDROID_HINTS = {
        "안드로이드", "android", "activity", "fragment", "viewmodel", "뷰모델",
        "compose", "컴포즈", "retrofit", "coroutine", "코루틴", "kotlin", "코틀린",
        "recyclerview", "manifest", "material", "room", "mvvm", "jetpack"
    };

    private static boolean isAndroidTopic(String topic) {
        if (topic == null) return false;
        String t = topic.toLowerCase();
        for (String h : ANDROID_HINTS) {
            if (t.contains(h)) return true;
        }
        return false;
    }

    /** index(주차/일차 등)로 회전시켜 중복 없이 개념형 항목을 뽑는다. */
    public static Concept forTopicAt(String topic, int index) {
        if (isAndroidTopic(topic)) {
            int i = ((index % ANDROID_BANK.size()) + ANDROID_BANK.size()) % ANDROID_BANK.size();
            return ANDROID_BANK.get(i);
        }
        return generic(topic);
    }

    public static Concept forTopic(String topic) {
        return forTopicAt(topic, 0);
    }

    /** 안드로이드가 아닌 주제: 주제명을 끼운 일반 개념 템플릿. 주제 자체가 노이즈면 안전한 기본값 사용. */
    private static Concept generic(String topic) {
        String t = LearningContentSanitizer.isNoise(topic, null) ? "핵심 주제" : LearningContentSanitizer.clean(topic);
        return c(
            t + " 기본 개념",
            t + "의 기본 개념과 핵심 용어를 이해한다.",
            new ArrayList<>(Arrays.asList(t)),
            new ArrayList<>(Arrays.asList(
                t + "의 기본 개념을 정리한다.",
                t + "의 핵심 용어를 확인한다.",
                t + "의 주요 구성 요소를 정리한다.")),
            new ArrayList<>(Arrays.asList(
                t + "의 핵심 개념은 무엇인가?",
                t + "은(는) 어떤 상황에서 사용되는가?")),
            t + " 핵심 개념 요약 노트");
    }
}
