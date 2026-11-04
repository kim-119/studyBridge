package com.studybridge.api.config;

import com.studybridge.api.ai.quality.AiQualityGateCoverage;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import java.io.File;

@Configuration
public class WebConfig implements WebMvcConfigurer {

    private final AiQualityGateCoverage aiQualityGateCoverage;

    public WebConfig(AiQualityGateCoverage aiQualityGateCoverage) {
        this.aiQualityGateCoverage = aiQualityGateCoverage;
    }

    @Override
    public void addResourceHandlers(ResourceHandlerRegistry registry) {
        String uploadPath = new File("temp-materials").getAbsolutePath();
        registry.addResourceHandler("/temp-materials/**")
                .addResourceLocations("file:" + uploadPath + "/");
    }

    // 품질 게이트 ON 일 때 게이트가 아직 연결되지 않은 사용자 노출 AI 경로를 503 으로 막는다(OFF 면 통과).
    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(aiQualityGateCoverage).addPathPatterns("/api/**");
    }
}
