package com.studybridge.api.security.jwt;

import com.studybridge.api.security.exhibit.ExhibitSessionService;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpHeaders;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.util.StringUtils;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

@RequiredArgsConstructor
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    private final JwtTokenProvider jwtTokenProvider;
    private final ExhibitSessionService exhibitSessionService;

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {

        String token = resolveToken(request);

        if (StringUtils.hasText(token) && jwtTokenProvider.validateToken(token)) {
            // 체험 계정 토큰은 기기 세션 슬롯이 살아 있어야 인증된다(로그아웃·유휴 만료된 기기의 토큰 차단). 일반 사용자는 그대로 통과.
            JwtTokenProvider.TokenClaims claims = jwtTokenProvider.getTokenClaims(token);
            if (exhibitSessionService.allowsAccess(claims.email(), claims.userId(), claims.sessionId())) {
                Authentication authentication = jwtTokenProvider.getAuthentication(token);
                SecurityContextHolder.getContext().setAuthentication(authentication);
                if (claims.sessionId() != null) {
                    request.setAttribute(ExhibitSessionService.SESSION_ID_ATTRIBUTE, claims.sessionId());
                }
            }
        }

        filterChain.doFilter(request, response);
    }

    private String resolveToken(HttpServletRequest request) {
        String bearerToken = request.getHeader(HttpHeaders.AUTHORIZATION);
        if (StringUtils.hasText(bearerToken) && bearerToken.startsWith("Bearer ")) {
            return bearerToken.substring(7);
        }
        return null;
    }
}
