package com.studybridge.api.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import java.io.File;

@Configuration
public class WebConfig implements WebMvcConfigurer {

    @Override
    public void addResourceHandlers(ResourceHandlerRegistry registry) {
        String uploadPath = new File("temp-materials").getAbsolutePath();
        registry.addResourceHandler("/temp-materials/**")
                .addResourceLocations("file:" + uploadPath + "/");
    }
}
