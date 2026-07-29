PYTHON ?= python3
CTA_DCS_DIR ?= $(HOME)/cta_2045_controller/dcs
SENSOR_CONFIGURATION ?=
SENSOR_CALIBRATION ?=

.PHONY: help test validate preflight preflight-water run run-water run-water-configured run-water-calibrated build_cta schedule_cta run_cta test_cta clean_cta clean

help:
	@echo "Water-heater conformance test commands:"
	@echo "  make test       Run the hardware-independent automated tests"
	@echo "  make validate   Import and validate the XLSX schedule without hardware"
	@echo "  make preflight  Check CTA, power, I2C, schedule, and station prerequisites"
	@echo "  make preflight-water  Also initialize GPIO17 LOW and require a water draw"
	@echo "  make run        Run the hardware test without scheduled valve output"
	@echo "  make run-water  Run the hardware test with scheduled valve output enabled"
	@echo "  make run-water-configured SENSOR_CONFIGURATION=<file>  Run with water output and sensor configuration"
	@echo "  make build_cta  Build the CTA-2045 controller"
	@echo "  make schedule_cta  Create the controller's standalone test schedule"
	@echo "  make run_cta    Build and run the CTA-2045 controller"
	@echo "  make test_cta   Build and run the controller's standalone test"
	@echo "  make clean_cta  Remove the CTA-2045 controller build directory"

test:
	$(PYTHON) -m unittest discover -s tests -v

validate:
	$(PYTHON) software/conformance_test_runner.py

preflight:
	$(PYTHON) -m software.hardware_preflight

preflight-water:
	$(PYTHON) -m software.hardware_preflight --water $(if $(SENSOR_CONFIGURATION),--sensor-configuration "$(SENSOR_CONFIGURATION)")

run: preflight
	$(PYTHON) software/conformance_test_runner.py --run-hardware

run-water: preflight-water
	$(PYTHON) software/conformance_test_runner.py --run-hardware --enable-water-output

run-water-configured:
	@test -n "$(SENSOR_CONFIGURATION)" || (echo "SENSOR_CONFIGURATION is required"; exit 2)
	@test -f "$(SENSOR_CONFIGURATION)" || (echo "Sensor configuration file not found: $(SENSOR_CONFIGURATION)"; exit 2)
	@$(MAKE) preflight-water SENSOR_CONFIGURATION="$(SENSOR_CONFIGURATION)"
	$(PYTHON) software/conformance_test_runner.py --run-hardware --enable-water-output --sensor-configuration "$(SENSOR_CONFIGURATION)"

# Backward-compatible alias for the earlier target and variable names.
run-water-calibrated:
	@$(MAKE) run-water-configured SENSOR_CONFIGURATION="$(SENSOR_CALIBRATION)"

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
