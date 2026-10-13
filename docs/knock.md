# Knock monitor: the page, how it listens and how to set it up

The knock sensor is read by the water/meth controller, through your amplifier, and
shown on the dash under **Knock**. The page works with both controllers:

| | Nano board (fitted now) | ESP32-S3 board |
|---|---|---|
| Level, normal level, threshold, events | yes | yes |
| Every setting changeable from the dash | all but the three below | yes |
| Spectrum of the sensor signal | no | yes |
| Knock frequency found from the engine | no, calculated from the bore | yes |
| Amplifier gain shown, automatic or held | no, fixed by the circuit | yes |
| Second resonance, how far a burst stands out | no | yes |

The dash finds out by itself which one is fitted. With the Nano, the parts it cannot
send say so and the rest works as before.

## The page

**LIVE** and **SETTINGS** are at the top right. From Controls → Knock monitor,
**ALL KNOCK SETTINGS** opens the settings directly.

### Live

Across the top: the knock-band level now, what is normal for this RPM, the threshold,
the headroom between them, where the filter is listening and why, and the amplifier
gain.

Left graph: the level over the last seven seconds against normal and the threshold.

Right graph (ESP32): the **spectrum** from 2 to 12.5 kHz, level in dB.

| On the graph | Meaning |
|---|---|
| Blue, filled | What each frequency normally carries |
| Yellow line | The loudest burst of about the last second |
| Shaded band | The band being listened in; the fainter one is the second resonance, 1.66 times higher |
| Dashed line, BORE | The knock frequency the bore suggests |
| Green line, ENGINE | Where the engine's own ringing under boost says it is |
| Red dotted line, TONE | A steady tone near the knock frequency (an alternator, or the pump's PWM) |

A knock resonance is a hump in the blue that the yellow rises well above under load.
When the green line and the shaded band sit on that hump, the filter is in the right
place.

Under the graphs:

| Reading | Meaning |
|---|---|
| **At knock frequency** | How much of the whole signal sits in the knock band. Ordinary engine noise is spread out and reads around 15%. Ringing reads 50% and up. |
| **Stands out by** | How far the loudest moment of the last pass stood above the rest of it. Knock is a burst. NOTABLE: it counted as ringing. |
| **Second resonance** | Its level against its own normal. RINGING: it rang too, which marks real knock. |
| **Sensor signal** | The swing either side of rest, and how much of the room to the nearer limit that is. With the Nano: a share of its input range. |
| **Amplifier rests at** | Where the amplifier's output sits with no signal |
| **Engine rings at** | The frequency the votes agree on, how many votes and how many agree |
| **Steady tone** | A frequency if there is one. If it appears while the pump runs, the pump's PWM is getting into the knock signal. |
| **Samples a second** | What the controller's converter really delivers |

### Settings

A field shows the controller's own value. Changing it sends the change at once and the
controller keeps it through a restart. A change made right after another waits a
moment for its turn; the line under CLEAR EVENTS shows what the controller answered.

| Setting | Range | Effect |
|---|---|---|
| Listening on / off | | The knock monitor as a whole |
| Knock is this many times normal | 1.2 to 3.8 | The learned level is multiplied by this. Raise it to be less sensitive. |
| Plus a fixed margin | 0 to 200 | Added on top. Raise it if quiet RPM ranges false-alarm. |
| A warning stays up for | 0.1 to 2.5 s | |
| Level gain | 0.1 to 20 | A software gain on the level. Leave it at 1. |
| Only above engine speed | 0 to 8000 RPM | Hits are judged only above this |
| Only above manifold pressure | 0 to 250 kPa absolute | 120 is 3 to 5 psi of boost, depending on altitude |
| Where it listens | | Found from the engine (ESP32; from the bore on the Nano), or set by hand |
| Frequency, when set by hand | 3 to 9 kHz | Choosing "Set by hand" starts from where the filter is now |
| Band width | 1500 or 900 Hz | |
| Cylinder bore (ESP32) | 40 to 200 mm | Where the search starts and how far it may go. Changing it starts the search again. |
| LEARN IT AGAIN (ESP32) | | Forgets the learned frequency |
| Amplifier gain (ESP32) | Automatic, or a position | "Hold a position" keeps the potentiometer where the slider puts it |

The threshold is *learned level × multiplier + margin*.

Settings are changed with the car stopped: above walking pace the dash refuses them
and the page says so at the top. Listening on / off and CLEAR EVENTS work at any time,
and so does everything on the Live view.

## How it listens

Knock makes the cylinder ring at a frequency set by the bore. For the 2.3 L Lima's
96 mm bore that is about **6.0 kHz**.

Both controllers learn the normal level **separately for each 1000 RPM**, because an
engine is simply louder at high revs. A hit is a level well above the learned normal
for that RPM **and** energy concentrated at the knock frequency. Two hits within 0.6 s
raise a warning; a strong, clearly narrow hit is critical at once. Knock is never
learned as normal.

Readings are judged only while armed: knock monitoring enabled, RPM above the minimum
and manifold pressure above the arming level. They are measured and shown all the
time.

**Nano:** fifty times a second it takes a burst of 64 samples at 19,200 samples a
second (3.3 ms). It has no crank or spark signal, so a single knock is caught only if
a burst happens to overlap it; sustained knock is caught within a fraction of a second.

**ESP32:** every sample is filtered, 38 thousand a second, with no gaps; a hit must
also stand out as a burst within its own 20 ms; the second resonance is checked; the
filter is moved to where the engine actually rings; and the amplifier gain is set
automatically. The details are in the controller's
[hardware guide](https://github.com/averyizatt/DIYWaterMethInjection/blob/main/docs/ESP32_HARDWARE.md).

## What it cannot do

- **It does not protect the engine.** Nothing retards timing. The MicroSquirt's own
  knock input is unused ("Knock In" and "Knock retard" are zero in your logs). Wiring
  a detected-knock signal to the ECU is the step that would protect it, once the
  detector has been checked against real driving.
- **It has not been calibrated on this engine.** The thresholds are starting values,
  and until the ESP32 has heard the engine ring under boost the frequency is the
  bore's figure.

## Check the sensor circuit first

Open **Knock** with the engine off, ignition on.

1. **Amplifier rests at** the middle of its range: about 2.5 V on the Nano's 0–5 V
   input (below about 0.7 V or above 4.3 V the Nano flags a sensor fault), about
   0.82 V on the ESP32 board with its 10 k / 10 k divider.
2. **Tap test.** Tap the block near the sensor with a wrench. *Sensor signal* and
   *Knock-band level* should jump, and on the ESP32 the yellow line of the spectrum
   lifts. Nothing at all means the sensor or amplifier is not connected.
3. **Gain.** On the Nano: *Sensor signal* roughly 5–15% at idle and under about 60% on
   a pull; 100% is clipping (the dash flags it): change the amplifier's gain resistor.
   On the ESP32 the controller does this itself: the gain reads AUTOMATIC with a
   position that moves with engine speed, and *Sensor signal* settles between about
   16 and 40% of room. "TOO LOUD AT THE LOWEST GAIN", "NOTHING HEARD AT FULL GAIN" or
   "GAIN CONTROL NOT RESPONDING" mean the circuit needs attention.

## Calibrate on the road

1. Drive normally across the rev range. **Normal** settles within a few seconds at
   each RPM; the status reads *LEARNING* until it has.
2. Watch *At knock frequency* in normal driving. It should sit around 10–25%.
3. On a pull with no knock (safe timing, good fuel), **Knock-band level** should stay
   below **Threshold**. If it crosses it with nothing wrong, raise the multiplier or
   the margin in Settings.
4. ESP32: after some driving in boost, *Engine rings at* shows a frequency and the
   note under *Listening at* changes from "FROM THE BORE, NOT LEARNED YET" to
   "LEARNED". Compare the green line with the hump in the spectrum.
5. Look at the log afterwards: level, normal, threshold and band share are recorded
   with RPM and boost, and with the ESP32 also the amplifier gain and position, the
   filter and found frequencies, and the second resonance.

## CAN

| Message | Carries |
|---|---|
| `0x307` | Level, learned level for this RPM, threshold, status, events; byte 7: share of the signal at the knock frequency |
| `0x30B` | Amplifier resting level, largest swing |
| `0x30C`, `0x30D` | The settings, as the controller holds them |
| `0x30E` (ESP32, extension 6) | Knock detail, the first byte naming the report: amplifier, frequency, engine, listening, and the two spectra in pieces of six points |
| `0x301` commands `0x40`–`0x4A` | The settings both controllers take |
| `0x301` commands `0x4B`, `0x4C`, `0x4D` (ESP32, extension 6) | Amplifier gain (0 automatic, n holds position n − 1), bore in mm, learn the frequency again |

`0x30E` and the three commands are additions; nothing existing changed. The dash
treats the controller as an ESP32 while `0x30E` has been seen in the last three
seconds, and refuses the three commands otherwise.
