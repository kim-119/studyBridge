# secret_sauce_engine / textprep
# 프로젝트 내부에만 libtextprep.so 생성. 외부 다운로드/시스템 설치 없음.
CC      ?= gcc
CFLAGS  := -O2 -fPIC -Wall -Wextra
TARGET  := libtextprep.so
SRC     := textprep.c

.PHONY: all clean
all: $(TARGET)

$(TARGET): $(SRC) textprep.h
	$(CC) $(CFLAGS) -shared -o $(TARGET) $(SRC)

clean:
	rm -f $(TARGET)
