# Shared WH1 Rev A hardware constants.

# region MAX1238 Configuration
ADC_PART = "MAX1238EEE+"
ADC_VREF = 4.096

# Installed ADC Connection on the station Pi
MAX1238_I2C_BUS = 1
MAX1238_I2C_ADDR = 0x35

# The Pi reaches the MAX1238 over I2C through the TXS0104E level shifter.

# endregion MAX1238 Configuration

# region MAX1238 Channels

# CHx values are MAX1238 analog input channels, not Raspberry Pi GPIO pins.
CH_HOT = 0
CH_COLD = 1
CH_FLOW = 2
CH_FUTURE = 3
CH_AMBIENT = 4

# endregion MAX1238 Channels

# region Valve GPIO

# GPIO17 is a Pi GPIO carried through the ribbon cable to the PCB relay driver.
VALVE_PIN = 17

# endregion Valve GPIO

# region ACS37800 Configuration

# ACS37800 is on the PCB and communicates over Pi-side I2C.
ACS37800_I2C_ADDR = 0x60
ACS_DIO0_GPIO = 18
ACS_DIO1_GPIO = 26

# endregion ACS37800 Configuration
