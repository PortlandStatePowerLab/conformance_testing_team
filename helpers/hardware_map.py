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

# 32-bit little-endian registers
REG_VRMS_REGISTER = 0x20   # [15:0]=VRMS(u16), [31:16]=IRMS(s16)
REG_POWER_REGISTER = 0x21 # [15:0]=PACTIVE(s16), [31:16]=PIMAG(u16)
REG_POWER_FACTOR_REGISTER = 0x22 # [15:0]=PAPP(u16), [26:16]=PF(11b signed), bit27 posangle, bit28 pospf

# Noise floors (tune if needed)
# These prevent "ghost" readings when VINP/inputs float (chip powered but mains/load removed)
NOISE_FLOOR_VRMS_CODES = 300    # raw codes near baseline treated as 0V
NOISE_FLOOR_IRMS_CODES = 80     # raw codes near baseline treated as 0A
NOISE_FLOOR_V_VOLTS    = 5.0    # Vrms below this -> show 0.0
NOISE_FLOOR_I_AMPS     = 0.20   # Irms below this -> show 0.0

# Power sign handling:
# If you want consumed power always positive, keep POWER_ABS=True
POWER_ABS = True
