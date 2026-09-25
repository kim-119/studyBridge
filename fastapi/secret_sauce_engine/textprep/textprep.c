/*
 * secret_sauce_engine / textprep
 * PDF 추출 텍스트 정규화 + 청크 경계 계산.
 * ASCII 공백/숫자만 특수 처리, 멀티바이트(>=0x80)는 그대로 통과 → UTF-8 안전.
 * 파일/네트워크/경로 입력 없음.
 */
#include "textprep.h"

static int is_ascii_ws(char c) {
    return c == ' ' || c == '\t' || c == '\r' || c == '\f' || c == '\v';
}

static int is_cont_byte(char c) {
    return ((unsigned char)c & 0xC0) == 0x80; /* UTF-8 continuation byte */
}

/* [s,e) 가 페이지번호성 줄인지(보수적). 짧고 숫자 중심일 때만 true. */
static int is_page_like(const char *in, int s, int e) {
    /* 앞뒤 공백 트림 */
    while (s < e && is_ascii_ws(in[s])) s++;
    while (e > s && is_ascii_ws(in[e - 1])) e--;
    if (e <= s) return 0;
    int len = e - s;

    /* "page" 접두 (대소문자 무시) + 숫자 → 페이지 표기 */
    if (len <= 12) {
        const char *p = "page";
        int i = 0, k = s;
        while (i < 4 && k < e) {
            char c = in[k];
            if (c >= 'A' && c <= 'Z') c = (char)(c - 'A' + 'a');
            if (c != p[i]) break;
            i++; k++;
        }
        if (i == 4) {
            int has_digit = 0, ok = 1;
            for (; k < e; k++) {
                char c = in[k];
                if (c >= '0' && c <= '9') has_digit = 1;
                else if (!is_ascii_ws(c) && c != '-' && c != '.') { ok = 0; break; }
            }
            if (ok && has_digit) return 1;
        }
    }

    /* 숫자/공백/-,/ 만으로 구성 + 숫자 1~4개 → "1", "12", "- 1 -", "1 / 12" */
    int digit_count = 0;
    for (int i = s; i < e; i++) {
        char c = in[i];
        if (c >= '0' && c <= '9') digit_count++;
        else if (!is_ascii_ws(c) && c != '-' && c != '/' && c != '|') return 0;
    }
    if (digit_count >= 1 && digit_count <= 4 && len <= 12) return 1;
    return 0;
}

int normalize_text(
    const char *input,
    int input_len,
    char *output,
    int output_capacity,
    int *output_len) {

    if (!input || !output || !output_len) return -2;
    if (input_len < 0 || output_capacity < 1) return -1;

    int out = 0;
    int consec_blank = 0; /* 누적된 빈 줄 수(지연 처리) */
    int pos = 0;

    while (pos <= input_len) {
        /* 한 줄 [line_s, line_e) 찾기 */
        int line_s = pos;
        int line_e = pos;
        while (line_e < input_len && input[line_e] != '\n') line_e++;

        /* 페이지번호성 줄이면 통째로 버림 */
        if (is_page_like(input, line_s, line_e)) {
            /* 다음 줄로 (페이지줄은 blank 으로도 세지 않음) */
            if (line_e >= input_len) break;
            pos = line_e + 1;
            continue;
        }

        /* 줄 트림(앞/뒤) 경계 계산 */
        int s = line_s, e = line_e;
        while (s < e && is_ascii_ws(input[s])) s++;
        while (e > s && is_ascii_ws(input[e - 1])) e--;

        if (e <= s) {
            /* 빈 줄 → 지연 카운트 */
            consec_blank++;
        } else {
            /* content 줄: 구분 개행 처리 */
            if (out > 0) {
                if (out >= output_capacity - 1) return -3;
                output[out++] = '\n';
                if (consec_blank > 0) { /* 빈 줄 1개로 축소 */
                    if (out >= output_capacity - 1) return -3;
                    output[out++] = '\n';
                }
            }
            consec_blank = 0;

            /* 내부 공백 런 → 단일 공백으로 축소하며 기록 */
            int prev_ws = 0;
            for (int i = s; i < e; i++) {
                char c = input[i];
                if (is_ascii_ws(c)) {
                    if (prev_ws) continue;
                    prev_ws = 1;
                    if (out >= output_capacity - 1) return -3;
                    output[out++] = ' ';
                } else {
                    prev_ws = 0;
                    if (out >= output_capacity - 1) return -3;
                    output[out++] = c;
                }
            }
        }

        if (line_e >= input_len) break;
        pos = line_e + 1;
    }

    output[out] = '\0';
    *output_len = out;
    return 0;
}

int compute_chunk_boundaries(
    const char *input,
    int input_len,
    int chunk_size,
    int overlap,
    int *out_starts,
    int *out_ends,
    int max_chunks,
    int *out_chunk_count) {

    if (!input || !out_starts || !out_ends || !out_chunk_count) return -2;
    if (input_len < 0 || chunk_size < 1 || overlap < 0) return -1;
    if (overlap >= chunk_size) return -1;
    if (max_chunks < 1) return -1;

    if (input_len == 0) { *out_chunk_count = 0; return 0; }

    int step = chunk_size - overlap;
    if (step < 1) return -1;

    int pos = 0, count = 0;
    while (pos < input_len) {
        if (count >= max_chunks) return -3;

        int end = pos + chunk_size;
        if (end >= input_len) {
            end = input_len;
        } else {
            /* UTF-8 continuation 바이트에서 자르지 않도록 뒤로 이동 */
            while (end > pos && is_cont_byte(input[end])) end--;
            /* 개행/공백 경계 선호(window 내) */
            int win = chunk_size / 4;
            if (win > 80) win = 80;
            int b = end;
            int found = -1;
            while (b > pos && b > end - win) {
                char c = input[b - 1];
                if (c == '\n') { found = b; break; }
                if (found < 0 && c == ' ') found = b;
                b--;
            }
            if (found > pos) end = found;
            if (end <= pos) { /* 안전장치: 최소 1바이트 진행 + clean boundary */
                end = pos + 1;
                while (end < input_len && is_cont_byte(input[end])) end++;
            }
        }

        out_starts[count] = pos;
        out_ends[count] = end;
        count++;

        if (end >= input_len) break;

        int nxt = end - overlap;
        if (nxt < 0) nxt = 0;
        while (nxt < input_len && is_cont_byte(input[nxt])) nxt++;
        if (nxt <= pos) nxt = pos + 1; /* 진행 보장(무한루프 방지) */
        pos = nxt;
    }

    *out_chunk_count = count;
    return 0;
}
