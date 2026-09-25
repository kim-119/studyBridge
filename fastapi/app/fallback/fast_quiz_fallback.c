#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

/*
 * fast_quiz_fallback — PDF context concepts 기반 빠른 로컬 퀴즈 후보 생성기.
 *
 * 역할: LLM이 65초까지 지연/실패할 때 90초 제한을 지키기 위한 "후보(candidate)" 생성기다.
 *       이 출력은 화면에 직접 표시하지 않는다. 반드시 Python/Java validate_quiz_response를
 *       통과한 문항만 partial_validated로 표시한다.
 * 제약: 외부 네트워크/DB/S3 접근 없음. PDF에서 추출된 concepts 문자열만 사용한다.
 *
 * usage: ./fast_quiz_fallback <easy|normal|hard> <count> "concept1|concept2|..."
 */

#define MAX_CONCEPTS 64
#define MAX_LEN 512

static void json_escape(const char *src, char *dst, size_t dst_size) {
    size_t j = 0;
    for (size_t i = 0; src[i] != '\0' && j + 2 < dst_size; i++) {
        unsigned char c = (unsigned char)src[i];
        if (c == '"' || c == '\\') {
            if (j + 2 >= dst_size) break;
            dst[j++] = '\\';
            dst[j++] = c;
        } else if (c == '\n' || c == '\r' || c == '\t') {
            dst[j++] = ' ';
        } else if (c < 32) {
            dst[j++] = ' ';
        } else {
            dst[j++] = c;
        }
    }
    dst[j] = '\0';
}

static int split_concepts(char *input, char concepts[MAX_CONCEPTS][MAX_LEN]) {
    int count = 0;
    char *token = strtok(input, "|,;");
    while (token != NULL && count < MAX_CONCEPTS) {
        while (*token && isspace((unsigned char)*token)) token++;
        if (*token) {
            snprintf(concepts[count], MAX_LEN, "%s", token);
            count++;
        }
        token = strtok(NULL, "|,;");
    }
    return count;
}

static const char* safe_concept(char concepts[MAX_CONCEPTS][MAX_LEN], int concept_count, int index) {
    if (concept_count <= 0) return NULL;
    return concepts[index % concept_count];
}

static void print_source_trace(const char *concept) {
    char c[MAX_LEN * 2];
    json_escape(concept, c, sizeof(c));
    printf("\"source_trace\":{");
    printf("\"source_type\":\"PDF_BASED\",");
    printf("\"fallback\":\"C_LOCAL\",");
    printf("\"concepts\":[\"%s\"],", c);
    printf("\"evidence\":\"PDF context에서 추출한 핵심 개념을 기반으로 생성한 fallback 후보\"");
    printf("}");
}

static void print_easy_question(const char *concept) {
    char c[MAX_LEN * 2];
    json_escape(concept, c, sizeof(c));

    printf("{");
    printf("\"question\":\"PDF에서 설명한 %s의 기본 역할로 가장 적절한 것은 무엇인가요?\",", c);
    printf("\"choices\":[");
    printf("\"PDF에서 설명한 %s의 핵심 역할을 수행한다\",", c);
    printf("\"%s와 관련된 설정이나 흐름을 확인하지 않아도 항상 동일하게 동작한다\",", c);
    printf("\"%s는 문서의 학습 내용과 무관하게 화면 장식만 담당한다\",", c);
    printf("\"%s는 사용자가 작성한 모든 코드를 자동으로 대체한다\"", c);
    printf("],");
    printf("\"correct_answer\":\"PDF에서 설명한 %s의 핵심 역할을 수행한다\",", c);
    printf("\"explanation\":\"이 문제는 PDF에 나온 %s의 기본 역할을 확인하는 쉬움 난이도 fallback 후보입니다.\",", c);
    print_source_trace(concept);
    printf("}");
}

static void print_normal_question(const char *concept) {
    char c[MAX_LEN * 2];
    json_escape(concept, c, sizeof(c));

    printf("{");
    printf("\"question\":\"PDF에서 설명한 %s를 구현 흐름에 적용할 때 가장 적절한 설명은 무엇인가요?\",", c);
    printf("\"choices\":[");
    printf("\"%s의 역할을 기준으로 관련 코드와 책임을 구분해 적용한다\",", c);
    printf("\"%s는 어떤 계층에서든 같은 책임을 가지므로 위치를 구분할 필요가 없다\",", c);
    printf("\"%s는 PDF에서 설명된 흐름과 관계없이 이름만 맞으면 충분하다\",", c);
    printf("\"%s는 구현 흐름보다 화면의 글꼴 크기를 결정하는 요소다\"", c);
    printf("],");
    printf("\"correct_answer\":\"%s의 역할을 기준으로 관련 코드와 책임을 구분해 적용한다\",", c);
    printf("\"explanation\":\"보통 난이도는 PDF 개념을 단순 암기보다 구현 흐름에 가볍게 적용하는 수준입니다.\",");
    print_source_trace(concept);
    printf("}");
}

static void print_hard_question(const char *concept) {
    char c[MAX_LEN * 2];
    json_escape(concept, c, sizeof(c));

    printf("{");
    printf("\"question\":\"PDF에서 설명한 %s를 프로젝트에 적용했지만 기능이 커지면서 유지보수와 테스트가 어려워지는 상황이 발생했다. 이때 PDF의 핵심 개념을 기준으로 가장 적절한 설계 판단은 무엇인가요?\",", c);
    printf("\"choices\":[");
    printf("\"%s의 책임과 사용 위치를 분리해 변경 영향 범위를 줄이고 테스트 가능성을 높인다\",", c);
    printf("\"%s와 관련된 모든 코드를 한 파일에 모아 수정 지점을 하나로 만든다\",", c);
    printf("\"%s의 역할을 확인하지 않고 호출 위치만 계속 추가한다\",", c);
    printf("\"%s와 무관한 화면 스타일만 변경해 구조 문제를 해결한다\"", c);
    printf("],");
    printf("\"correct_answer\":\"%s의 책임과 사용 위치를 분리해 변경 영향 범위를 줄이고 테스트 가능성을 높인다\",", c);
    printf("\"explanation\":\"어려움 난이도는 PDF 개념을 실무 상황, 유지보수, 테스트 가능성 관점에 적용해야 합니다. 책임 분리로 변경 영향과 결합도를 줄이는 설계 판단이 정답입니다.\",");
    printf("\"wrong_explanations\":[");
    printf("\"한 파일에 모든 코드를 모으면 변경 영향과 결합도가 커질 수 있습니다\",");
    printf("\"역할을 확인하지 않고 호출 위치만 추가하면 구조 문제를 악화시킬 수 있습니다\",");
    printf("\"화면 스타일 변경은 유지보수와 테스트 가능성 문제를 해결하지 못합니다\"");
    printf("],");
    print_source_trace(concept);
    printf("}");
}

int main(int argc, char **argv) {
    if (argc < 4) {
        fprintf(stderr, "usage: %s <easy|normal|hard> <count> <concept1|concept2|...>\n", argv[0]);
        return 1;
    }

    const char *difficulty = argv[1];
    int count = atoi(argv[2]);
    if (count < 5) count = 5;
    if (count > 20) count = 20;

    char concept_input[4096];
    snprintf(concept_input, sizeof(concept_input), "%s", argv[3]);

    char concepts[MAX_CONCEPTS][MAX_LEN];
    int concept_count = split_concepts(concept_input, concepts);

    if (concept_count <= 0) {
        fprintf(stderr, "no concepts provided\n");
        return 2;
    }

    printf("{");
    printf("\"success\":true,");
    printf("\"candidate_only\":true,");
    printf("\"source_mode\":\"PDF_BASED\",");
    printf("\"fallback_used\":true,");
    printf("\"fallback_type\":\"C_LOCAL\",");
    printf("\"difficulty_applied\":\"%s\",", difficulty);
    printf("\"applied_count\":%d,", count);
    printf("\"questions\":[");

    for (int i = 0; i < count; i++) {
        const char *concept = safe_concept(concepts, concept_count, i);
        if (i > 0) printf(",");

        if (strcmp(difficulty, "hard") == 0) {
            print_hard_question(concept);
        } else if (strcmp(difficulty, "normal") == 0) {
            print_normal_question(concept);
        } else {
            print_easy_question(concept);
        }
    }

    printf("]}");
    return 0;
}
