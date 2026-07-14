#!/usr/bin/env python3

from smbus2 import SMBus, i2c_msg
import time

ACS37800_I2C_ADDR = 0x60
I2C_BUS = 1

REG_CURRENT_CONFIG_EEPROM = 0x0B
REG_CURRENT_CONFIG_SHADOW = 0x1B
REG_RMS = 0x20

CRS_SNS_MASK = 0b111 << 19
TARGET_CRS_SNS = 3

REG_ACCESS_CODE = 0x2F
REG_CUSTOMER_ACCESS = 0x30
CUSTOMER_ACCESS_CODE = 0x4F70

def read_u32_le(bus, register):
    """Read one 32-bit little-endian ACS37800 register."""
    data = bus.read_i2c_block_data(
        ACS37800_I2C_ADDR,
        register,
        4,
    )

    if len(data) != 4:
        raise OSError(
            f"Expected 4 bytes from register 0x{register:02X}, "
            f"received {len(data)}"
        )

    return (
        data[0]
        | (data[1] << 8)
        | (data[2] << 16)
        | (data[3] << 24)
    )


def write_u32_le2(bus, register, value):
    """Write one 32-bit little-endian ACS37800 register."""
    data = [
        value & 0xFF,
        (value >> 8) & 0xFF,
        (value >> 16) & 0xFF,
        (value >> 24) & 0xFF,
    ]

    bus.write_i2c_block_data(
        ACS37800_I2C_ADDR,
        register,
        data,
    )

def write_u32_le(bus, register, value):
    """Write one ACS37800 32-bit register using a plain I2C transaction.

    The ACS37800 expects:
        register address,
        bits 7:0,
        bits 15:8,
        bits 23:16,
        bits 31:24

    i2c_msg is used instead of write_i2c_block_data because an SMBus block
    write may insert a byte-count field that the ACS37800 does not expect.
    """
    message = i2c_msg.write(
        ACS37800_I2C_ADDR,
        [
            register & 0xFF,
            value & 0xFF,
            (value >> 8) & 0xFF,
            (value >> 16) & 0xFF,
            (value >> 24) & 0xFF,
        ],
    )

    bus.i2c_rdwr(message)

def signed_16(value):
    """Interpret the lower 16 bits as signed two's complement."""
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def extract_crs_sns(value):
    """Extract CRS_SNS from bits 21:19."""
    return (value >> 19) & 0b111


def main():
    with SMBus(I2C_BUS) as bus:
        eeprom_value = read_u32_le(
            bus,
            REG_CURRENT_CONFIG_EEPROM,
        )

        original_shadow = read_u32_le(
            bus,
            REG_CURRENT_CONFIG_SHADOW,
        )

        print(f"EEPROM 0x0B:         0x{eeprom_value:08X}")
        print(f"Original shadow 0x1B: 0x{original_shadow:08X}")
        print(
            f"Original CRS_SNS:      "
            f"{extract_crs_sns(original_shadow)}"
        )
            
        # Enable customer write access.
        write_u32_le(
            bus,
            REG_ACCESS_CODE,
            CUSTOMER_ACCESS_CODE,
        )

        time.sleep(0.05)

        customer_access = read_u32_le(
            bus,
            REG_CUSTOMER_ACCESS,
        )

        print(f"Customer access register 0x30: 0x{customer_access:08X}")

        if (customer_access & 0x1) != 1:
            raise RuntimeError(
                "Customer write access was not enabled. "
                "No configuration register was written."
            )
        
        print("Shadow register changed temporarily.")
        print("EEPROM register 0x0B was not changed.")
        print("Power-cycling the chip will restore the original value.")

        # Change only bits 21:19. All other bits remain untouched.
        modified_shadow = (
            (original_shadow & ~CRS_SNS_MASK)
            | (TARGET_CRS_SNS << 19)
        )

        print(f"Proposed shadow 0x1B: 0x{modified_shadow:08X}")
        print(
            f"Proposed CRS_SNS:      "
            f"{extract_crs_sns(modified_shadow)}"
        )

        confirmation = input(
            "\nWrite this temporary shadow-register change? "
            "Type YES to continue: "
        ).strip()

        if confirmation != "YES":
            print("Cancelled. Nothing was written.")
            return

        write_u32_le(
            bus,
            REG_CURRENT_CONFIG_SHADOW,
            modified_shadow,
        )

        time.sleep(0.1)

        verified_shadow = read_u32_le(
            bus,
            REG_CURRENT_CONFIG_SHADOW,
        )

        print("\nVerification")
        print(f"Readback shadow 0x1B: 0x{verified_shadow:08X}")
        print(
            f"Readback CRS_SNS:      "
            f"{extract_crs_sns(verified_shadow)}"
        )

        if verified_shadow != modified_shadow:
            raise RuntimeError(
                "Shadow-register verification failed. "
                "Power-cycle the board before further testing."
            )

        print("\nTemporary gain change succeeded.")
        print("EEPROM was not changed.")
        print("A power cycle will restore the original setting.")

        print("\nReading IRMS for 10 seconds:")

        for _ in range(20):
            rms_register = read_u32_le(bus, REG_RMS)
            irms_field = (rms_register >> 16) & 0xFFFF
            irms_signed = signed_16(irms_field)

            print(
                f"IRMS field=0x{irms_field:04X} "
                f"signed={irms_signed}"
            )

            time.sleep(0.5)


if __name__ == "__main__":
    main()
