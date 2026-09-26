"""Print a Pi SPI0 MCP2515 boot overlay; the oscillator must be confirmed first."""
import argparse


def overlay(oscillator, interrupt=25, cs=0):
    if oscillator not in (8_000_000, 16_000_000, 20_000_000):
        raise ValueError('Confirm the module oscillator: supported values are 8000000, 16000000, 20000000')
    if cs not in (0, 1) or interrupt not in set(range(2, 28)) - {7, 8, 9, 10, 11}:
        raise ValueError('Select SPI0 CE0/CE1 and a free interrupt GPIO (not an SPI pin)')
    return ('# Frogdash MCP2515; verify 3.3 V-safe logic and board oscillator before wiring.\n'
            'dtparam=spi=on\n'
            f'dtoverlay=mcp2515-can{cs},oscillator={oscillator},interrupt={interrupt},spimaxfrequency=1000000\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--oscillator', type=int, required=True)
    parser.add_argument('--interrupt', type=int, default=25, help='BCM GPIO number, not physical pin number')
    parser.add_argument('--cs', type=int, choices=(0, 1), default=0)
    args = parser.parse_args()
    try:
        print(overlay(args.oscillator, args.interrupt, args.cs), end='')
    except ValueError as exc:
        parser.error(str(exc))
