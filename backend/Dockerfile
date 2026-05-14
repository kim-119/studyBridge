FROM eclipse-temurin:21-jdk

WORKDIR /app

COPY . .

RUN sed -i 's/\r$//' gradlew
RUN chmod +x gradlew

RUN ./gradlew clean build -x test

EXPOSE 8080

CMD ["sh", "-c", "java -jar build/libs/*.jar"]
