#!/usr/bin/env python3
"""
test_acs37800_shadow_gain.py

Temporarily changes only the ACS37800 shadow-register CRS_SNS field
from its current value to code 3. EEPROM is not modified.

The change is volatile and is restored when the ACS37800 loses power.

Run with the water-heater load OFF initially. After successful readback,
the program prints IRMS for 10 seconds. You can then run the normal
diagnostic program without power-cycling and test the desired load.
"""

from smbus2 import SMBus
import time


ACS37800_I2C_ADDR = 0x60
I2C_BUS = 1

REG_CURRENT_CONFIG_EEPROM = 0x0B
REG_CURRENT_CONFIG_SHADOW = 0x1B
REG_RMS = 0x20
REG_ACCESS_CODE = 0x2F
REG_CUSTOMER_ACCESS = 0x30

CUSTOMER_ACCESS_CODE = 0x4F70656E

CRS_SNS_LSB = 19
CRS_SNS_MASK = 0b111 << CRS_SNS_LSB
TARGET_CRS_SNS = 3


def read_u32_le(bus, register):
    """Read one 32-bit ACS37800 register in little-endian byte order."""
    data = bus.read_i2c_block_data(
        ACS37800_I2C_ADDR,
        register,
        4,
    )

    if len(data) != 4:
        raise OSError(
            f"Register 0x{register:02X}: expected 4 bytes, "
            f"received {len(data)}"
        )

    return (
        data[0]
        | (data[1] << 8)
        | (data[2] << 16)
        | (data[3] << 24)
    )


def write_u32_le(bus, register, value):
    """
    Write one complete 32-bit ACS37800 register, least-significant byte first.

    The transmitted data bytes are:
        bits 7:0
        bits 15:8
        bits 23:16
        bits 31:24
    """
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


def signed_16(value):
    """Interpret the lower 16 bits as signed two's-complement."""
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def extract_crs_sns(value):
    """Extract CRS_SNS from register bits 21:19."""
    return (value >> CRS_SNS_LSB) & 0b111


def main():
    print("ACS37800 temporary shadow-gain test")
    print("EEPROM will not be modified.\n")

    with SMBus(I2C_BUS) as bus:
        eeprom_value = read_u32_le(
            bus,
            REG_CURRENT_CONFIG_EEPROM,
        )
        original_shadow = read_u32_le(
            bus,
            REG_CURRENT_CONFIG_SHADOW,
        )

        print(f"EEPROM 0x0B:           0x{eeprom_value:08X}")
        print(f"Original shadow 0x1B:  0x{original_shadow:08X}")
        print(f"Original CRS_SNS:      {extract_crs_sns(original_shadow)}")

        modified_shadow = (
            (original_shadow & ~CRS_SNS_MASK)
            | (TARGET_CRS_SNS << CRS_SNS_LSB)
        )

        print(f"Proposed shadow 0x1B:  0x{modified_shadow:08X}")
        print(f"Proposed CRS_SNS:      {extract_crs_sns(modified_shadow)}")

        confirmation = input(
            "\nType YES to unlock the chip and apply this temporary "
            "shadow-register change: "
        ).strip().upper()

        if confirmation != "YES":
            print("Cancelled. Nothing was written.")
            return

        # Unlock customer writes. The access register is 32-bit and must be
        # written as four little-endian bytes.
        write_u32_le(
            bus,
            REG_ACCESS_CODE,
            CUSTOMER_ACCESS_CODE,
        )

        time.sleep(0.1)

        customer_access = read_u32_le(
            bus,
            REG_CUSTOMER_ACCESS,
        )

        print(f"\nCustomer access 0x30:  0x{customer_access:08X}")

        if (customer_access & 0x1) == 0:
            raise RuntimeError(
                "Customer write access was not enabled. "
                "No shadow configuration was changed."
            )

        print("Customer write access is enabled.")

        # Change only CRS_SNS in volatile shadow register 0x1B.
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
        print(f"Readback shadow 0x1B:  0x{verified_shadow:08X}")
        print(f"Readback CRS_SNS:      {extract_crs_sns(verified_shadow)}")

        if verified_shadow != modified_shadow:
            raise RuntimeError(
                "Shadow-register verification failed. "
                "The requested value was not accepted."
            )

        final_eeprom = read_u32_le(
            bus,
            REG_CURRENT_CONFIG_EEPROM,
        )

        print(f"EEPROM 0x0B remains:   0x{final_eeprom:08X}")

        if final_eeprom != eeprom_value:
            raise RuntimeError(
                "Unexpected EEPROM change detected. Stop testing."
            )

        print("\nTemporary gain change succeeded.")
        print("Only shadow register 0x1B was changed.")
        print("Power-cycling the ACS37800 restores the EEPROM setting.")
        print("\nReading IRMS for 10 seconds:\n")

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
