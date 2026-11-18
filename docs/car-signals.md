# Car signals: turn signals, brake, lights, reverse and fuel level

In the reference car these come from Frogdash's own boards: the taillight board (0x100)
sends turn, brake, lights and reverse, and the sensor gateway (0x500) sends the fuel level.
Every other car picks a source for each in the setup wizard (**Car signals** page). The
choice is the system profile's `signals` ([presets.md](presets.md)); the dash shows the
result exactly as it shows the boards' readings, so the indicators, the reverse camera,
alerts, logs and the fuel gauge work the same.

| Source | For | What it needs |
|---|---|---|
| From the ECU | Any signal the ECU's profile broadcasts (Haltech, MaxxECU, ECUMaster and rusEFI send the brake switch; rusEFI the fuel level) | Nothing: offered only when the chosen ECU has it |
| Wired to a Pi pin | Turn, brake, lights, reverse | An optocoupler board between the car's 12 V wire and the Pi (below) |
| Fuel sender (ADS1115) | Fuel level | An ADS1115 board on the Pi's I2C pins and a divider (below) |
| A CAN message | Any | The frame's ID and the bit (for fuel: the byte, and whether full is 100 or 255) |
| Not used | Any | The reading stays blank |

Turn signals flash: the dash treats one as on while a pulse came within 0.8 s, so the arrow
stays lit through the flasher's off time.

## On/off signals on Pi pins

**Never connect a car's 12 V wire to a Pi pin.** The pins are 3.3 V; 12 V (and the spikes on
a car's wiring) destroys the Pi. Use an optocoupler board rated for a 12 V input, for
example a 4-channel PC817 module:

- Input side: the car's signal wire (the bulb's feed) to the channel's input, its other
  input terminal to the car's ground.
- Output side: the channel's output to a free Pi pin, its ground to a Pi ground pin. No
  power from the Pi is needed on that side: the dash turns on the pin's own pull-up.
- In the wizard: **Wired to a Pi pin**, the pin's GPIO number, and **On when pulled to
  ground** ticked (the opto pulls the pin low while the bulb is lit).

Free pins: GPIO 4, 5, 6, 12, 13, 16 to 27, except the CAN board's interrupt (GPIO 25 on the
Waveshare HAT). The wizard offers only free ones. Setup installs `python3-libgpiod` the
first time a pin is used.

## Fuel level on an ADS1115

A fuel sender is a variable resistor to ground in the tank. The ADS1115 (address 0x48, on
the Pi's I2C pins 3 and 5, powered from the Pi's 3.3 V) measures a voltage across it:

- **With the car's fuel gauge still in place:** read the sender wire's voltage through a
  divider that keeps it under 3.3 V at its highest (for a wire that reaches 8 V, for
  example 10 kΩ to the ADS1115 input and 4.7 kΩ from the input to ground).
- **Without a gauge:** feed the sender from the Pi's 3.3 V through a resistor (220 Ω suits
  most senders, under 15 mA) and read the voltage at the sender.

Then fill in the wizard: the ADS1115 input (A0 to A3) and the voltage it reads with the tank
empty and with it full (measure both, or work them out from the sender's ohms). The dash
averages four seconds of readings, so the needle does not swing as fuel moves in the tank.
Setup switches I2C on (a restart is needed the first time).

## Checking it

The **Car signals** page shows each signal's reading as the dash is set up at the moment
("Now: ON", "Now: 62 %"), or why there is none (no python3-libgpiod yet, no ADS1115
answering). Apply first, then come back to the page and work the switch or the lights.
