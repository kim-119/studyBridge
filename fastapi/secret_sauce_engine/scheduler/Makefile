# secret_sauce_engine / scheduler
# 프로젝트 내부에만 libscheduler.so 생성. 외부 다운로드/시스템 설치 없음.
CC      ?= gcc
CFLAGS  := -O2 -fPIC -Wall -Wextra
TARGET  := libscheduler.so
SRC     := scheduler.c

.PHONY: all clean
all: $(TARGET)

$(TARGET): $(SRC) scheduler.h
	$(CC) $(CFLAGS) -shared -o $(TARGET) $(SRC)

clean:
	rm -f $(TARGET)
