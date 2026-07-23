# Shared WH1 Rev A hardware constants.

ADC_PART = "MAX1238EEE+"
ADC_VREF = 4.096
MAX1238_I2C_BUS = 1
MAX1238_I2C_ADDR = 0x35

# CHx values are MAX1238 analog input channels, not Raspberry Pi GPIO pins.
CH_HOT = 0
CH_COLD = 1
CH_FLOW = 2
CH_FUTURE = 3
CH_AMBIENT = 4

# GPIO17 is a Pi GPIO carried through the ribbon cable to the PCB relay driver.
VALVE_PIN = 17

# The Pi reaches the MAX1238 over I2C through the TXS0104E level shifter.
# ACS37800 is the power chip on the PCB and communicates over Pi-side I2C.
ACS37800_I2C_ADDR = 0x60
ACS_DIO0_GPIO = 18
ACS_DIO1_GPIO = 26

# I2C Address
I2C_BUS = 1

# 32-bit little-endian registers
REG_VRMS_REGISTER = 0x20   # [15:0]=VRMS(u16), [31:16]=IRMS(u16) <-- datasheets says signed but it is wrong
REG_POWER_REGISTER = 0x21 # [15:0]=PACTIVE(s16) <-- real power, [31:16]=PIMAG(u16) <-- reactive power
REG_POWER_FACTOR_REGISTER = 0x22 # [15:0]=PAPPARRENT(u16) <-- apparent power, [26:16]=PF(11b signed) <-- power factor, 
                                 # bit27 posangle <-- leading(0)/lagging(1), bit28 pospf <-- positive(consuming)/negative(generating) power factor

# Noise floors (tune if needed)
# These prevent "ghost" readings when VINP/inputs float (chip powered but mains/load removed)
NOISE_FLOOR_VRMS_CODES = 300    # raw codes near baseline treated as 0V
NOISE_FLOOR_IRMS_CODES = 80     # raw codes near baseline treated as 0A
NOISE_FLOOR_V_VOLTS    = 5.0    # Vrms below this -> show 0.0
NOISE_FLOOR_I_AMPS     = 0.02   # Irms below this -> show 0.0

# Power sign handling:
# If you want consumed power always positive, keep POWER_ABS=True
POWER_ABS = True

# ACS37800_REGISTERS for reference (not used in code, but useful for debugging)
EEPROM_REGISTERS = {
    0x0B: "EEPROM_CURRENT_TRIM_AVERAGING",
    0x0C: "EEPROM_VOLTAGE_OFFSET_AVERAGING",
    0x0D: "EEPROM_PHASE_DELAY_OVERCURRENT",
    0x0E: "EEPROM_VOLTAGE_EVENTS_ZERO_CROSSING",
    0x0F: "EEPROM_RMS_WINDOW_DIO_I2C",
}

SHADOW_REGISTERS = {
    0x1B: "SHADOW_CURRENT_TRIM_AVERAGING",
    0x1C: "SHADOW_VOLTAGE_OFFSET_AVERAGING",
    0x1D: "SHADOW_PHASE_DELAY_OVERCURRENT",
    0x1E: "SHADOW_VOLTAGE_EVENTS_ZERO_CROSSING",
    0x1F: "SHADOW_RMS_WINDOW_DIO_I2C",
}

LIVE_REGISTERS = {
    0x20: "VRMS_IRMS",
    0x21: "PACTIVE_PIMAG",
    0x22: "PAPPARENT_PFACTOR_FLAGS",
    0x25: "NUMPTSOUT",
    0x26: "RMS_AVERAGE_STAGE_1",
    0x27: "RMS_AVERAGE_STAGE_2",
    0x28: "PACTIVE_AVERAGE_STAGE_1",
    0x29: "PACTIVE_AVERAGE_STAGE_2",
    0x2A: "VCODES_ICODES",
    0x2C: "PINSTANT",
    0x2D: "STATUS_FLAGS",
}
