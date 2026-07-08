# Shared WH1 Rev A hardware constants.

ADC_PART = "MAX1238EEE+"
ADC_VREF = 4.096

# CHx values are MAX1238 analog input channels, not Raspberry Pi GPIO pins.
CH_HOT = 0
CH_COLD = 1
CH_FLOW = 2
CH_FUTURE = 3
CH_AMBIENT = 4

# GPIO17 is a Pi GPIO carried through the ribbon cable to the PCB relay driver.
VALVE_PIN = 17

# The Pi reaches the MAX1238 over I2C through the TXS0104E level shifter.
# ACS37800 is on the PCB and communicates over Pi-side I2C.
ACS37800_I2C_ADDR = 0x60
ACS_DIO0_GPIO = 18
ACS_DIO1_GPIO = 26

# I2C Address
I2C_BUS = 1

#Sensor address
SENSOR_ADDRESS = 0x60


