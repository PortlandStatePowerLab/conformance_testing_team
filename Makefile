PYTHON ?= python3
CTA_DCS_DIR ?= $(HOME)/cta_2045_controller/dcs

.PHONY: help test validate run run-water build_cta schedule_cta run_cta test_cta clean_cta clean

help:
	@echo "Water-heater conformance test commands:"
	@echo "  make test       Run the hardware-independent automated tests"
	@echo "  make validate   Import and validate the XLSX schedule without hardware"
	@echo "  make run        Run the hardware test without scheduled valve output"
	@echo "  make run-water  Run the hardware test with scheduled valve output enabled"
	@echo "  make build_cta  Build the CTA-2045 controller"
	@echo "  make schedule_cta  Create the controller's standalone test schedule"
	@echo "  make run_cta    Build and run the CTA-2045 controller"
	@echo "  make test_cta   Build and run the controller's standalone test"
	@echo "  make clean_cta  Remove the CTA-2045 controller build directory"

test:
	$(PYTHON) -m unittest discover -s tests -v

validate:
	$(PYTHON) software/conformance_test_runner.py

run:
	$(PYTHON) software/conformance_test_runner.py --run-hardware

run-water:
	$(PYTHON) software/conformance_test_runner.py --run-hardware --enable-water-output

build_cta:
	$(MAKE) -C $(CTA_DCS_DIR) controller

schedule_cta:
	$(MAKE) -C $(CTA_DCS_DIR) schedule

run_cta:
	$(MAKE) -C $(CTA_DCS_DIR) run

test_cta:
	$(MAKE) -C $(CTA_DCS_DIR) test

clean_cta:
	$(MAKE) -C $(CTA_DCS_DIR) clean

clean: clean_cta
