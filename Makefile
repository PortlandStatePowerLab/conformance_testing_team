PYTHON ?= python3
CTA_DCS_DIR ?= $(HOME)/cta_2045_controller/dcs
SENSOR_CALIBRATION ?=

.PHONY: help test validate run run-water run-water-calibrated build_cta schedule_cta run_cta test_cta clean_cta clean

help:
	@echo "Water-heater conformance test commands:"
	@echo "  make test       Run the hardware-independent automated tests"
	@echo "  make validate   Import and validate the XLSX schedule without hardware"
	@echo "  make run        Run the hardware test without scheduled valve output"
	@echo "  make run-water  Run the hardware test with scheduled valve output enabled"
	@echo "  make run-water-calibrated SENSOR_CALIBRATION=<file>  Run with water output and sensor calibration"
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

run-water-calibrated:
	@test -n "$(SENSOR_CALIBRATION)" || (echo "SENSOR_CALIBRATION is required"; exit 2)
	@test -f "$(SENSOR_CALIBRATION)" || (echo "Sensor calibration file not found: $(SENSOR_CALIBRATION)"; exit 2)
	$(PYTHON) software/conformance_test_runner.py --run-hardware --enable-water-output --sensor-calibration "$(SENSOR_CALIBRATION)"

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
