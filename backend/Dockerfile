FROM eclipse-temurin:21-jdk-alpine AS build

WORKDIR /app

COPY . .

RUN sed -i 's/\r$//' gradlew
RUN chmod +x gradlew && ./gradlew clean build -x test

FROM eclipse-temurin:21-jre-alpine

WORKDIR /app

COPY --from=build /app/build/libs/*.jar app.jar

EXPOSE 8080

CMD ["java", "-jar", "app.jar"]