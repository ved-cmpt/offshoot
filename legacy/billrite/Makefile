# BillRite build. Runs inside cobol-runner, where the sources are read-only, so
# all output goes to BUILD_DIR (tmpfs) and OUT_DIR (bind-mounted to legacy/billrite/out).
# Compiling and running both happen under nonet: networking is disabled (ADR-009).

COBC      ?= cobc
NONET     ?= nonet
BUILD_DIR ?= /work/build
OUT_DIR   ?= /out
DATA_DIR  ?= data

COBFLAGS  := -std=default -Wall -Wno-obsolete -static -I copy
MODULES   := src/MTRVAL.cbl src/RATECALC.cbl src/LATEFEE.cbl src/STMTGEN.cbl
COPYBOOKS := $(wildcard copy/*.cpy)

export COB_LS_FIXED := Y

.PHONY: build billrun clean

build: $(BUILD_DIR)/BILLRUN $(BUILD_DIR)/BRCALL

$(BUILD_DIR)/BILLRUN: src/BILLRUN.cbl $(MODULES) $(COPYBOOKS)
	@mkdir -p $(BUILD_DIR)
	$(NONET) $(COBC) -x $(COBFLAGS) -o $@ src/BILLRUN.cbl $(MODULES)

$(BUILD_DIR)/BRCALL: harness/BRCALL.cbl $(MODULES) $(COPYBOOKS)
	@mkdir -p $(BUILD_DIR)
	$(NONET) $(COBC) -x $(COBFLAGS) -o $@ harness/BRCALL.cbl $(MODULES)

billrun: $(BUILD_DIR)/BILLRUN
	DD_CUSTFILE=$(abspath $(DATA_DIR))/CUSTFILE.dat \
	DD_READFILE=$(abspath $(DATA_DIR))/READFILE.dat \
	DD_BILLFILE=$(OUT_DIR)/BILLFILE.dat \
	DD_ERRFILE=$(OUT_DIR)/ERRFILE.dat \
	$(NONET) $(BUILD_DIR)/BILLRUN

clean:
	rm -rf $(BUILD_DIR)
