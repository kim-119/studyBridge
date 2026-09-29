FROM eclipse-temurin:21-jdk

WORKDIR /app

# Copy gradle wrapper and build files first to cache dependencies
COPY gradle gradle
COPY gradlew .
COPY build.gradle .

# Fix line endings and make gradlew executable
RUN sed -i 's/\r$//' gradlew && chmod +x gradlew

# Download Gradle distribution and dependencies
RUN ./gradlew dependencies --no-daemon || true

# Copy the rest of the project source
COPY . .

# Fix line endings and make gradlew executable again (since COPY . . overwrote it)
RUN sed -i 's/\r$//' gradlew && chmod +x gradlew

# Build the project
RUN ./gradlew clean build -x test --no-daemon

EXPOSE 8080

CMD ["sh", "-c", "java -jar build/libs/*.jar"]

