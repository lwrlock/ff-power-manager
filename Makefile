CC ?= gcc
AS ?= as
CFLAGS ?= -O2 -Wall -Wextra -D_GNU_SOURCE
NATIVE_DIR = src/native

BINARIES = ff-presence-sensor ffctl ff-tui test_native

.PHONY: all build native test test-native test-python clean install

all: build

build: native compile

native: $(BINARIES)

$(NATIVE_DIR)/sensor_asm.o: $(NATIVE_DIR)/sensor_asm.s
	$(AS) -o $@ $<

ff-presence-sensor: $(NATIVE_DIR)/sensor_native.c $(NATIVE_DIR)/sensor_asm.o
	$(CC) $(CFLAGS) -o $@ $^

ffctl: $(NATIVE_DIR)/ffctl_native.c $(NATIVE_DIR)/sensor_asm.o
	$(CC) $(CFLAGS) -o $@ $^

ff-tui: $(NATIVE_DIR)/ff_tui_native.c $(NATIVE_DIR)/sensor_asm.o
	$(CC) $(CFLAGS) -o $@ $^

test_native: $(NATIVE_DIR)/test_native.c $(NATIVE_DIR)/sensor_asm.o
	$(CC) $(CFLAGS) -o $@ $^

compile:
	python3 -m py_compile src/fpm/*.py

test: test-native test-python

test-native: test_native
	./test_native

test-python:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

install: build
	./install.sh

clean:
	rm -f $(BINARIES) $(NATIVE_DIR)/*.o
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
