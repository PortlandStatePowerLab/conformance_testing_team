# Automated tests

Laptop-safe automated verification using assertions.

Tests belong here when the component under test is obvious from the filename and
hardware access can be replaced with fakes or patches. Tests must not unexpectedly
actuate GPIO, the valve, mains-connected equipment, or other live station hardware.

Test modules may import active code from `software/`.

Manually invoked station inspection tools belong in `software/commands/`, even
when they print a pass/fail result.
