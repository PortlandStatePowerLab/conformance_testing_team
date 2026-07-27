PYTHON ?= python3
BUILD_DIR := ~/cta_2045_controller/dcs/build/debug
PROGRAM := $(BUILD_DIR)/cta2045_controller

.PHONY: help test validate run run-water build_cta test_cta

help:
	@echo "Water-heater conformance test commands:"
	@echo "  make test       Run the hardware-independent automated tests"
	@echo "  make validate   Import and validate the XLSX schedule without hardware"
	@echo "  make run        Run the hardware test without scheduled valve output"
	@echo "  make run-water  Run the hardware test with scheduled valve output enabled"

test:
	$(PYTHON) -m unittest discover -s tests -v

validate:
	$(PYTHON) software/conformance_test_runner.py

run:
	$(PYTHON) software/conformance_test_runner.py --run-hardware

run-water:
	$(PYTHON) software/conformance_test_runner.py --run-hardware --enable-water-output

build_cta:
	cmake -S . -B $(BUILD_DIR) -DCONTROLLER=ON -DCMAKE_BUILD_TYPE=Debug
	cmake --build $(BUILD_DIR) --target cta2045_controller

test_cta: controller
	bash controller/create_schedule.sh
	cd controller && ../$(PROGRAM)

clean:
	cmake -E remove_directory $(BUILD_DIR)
