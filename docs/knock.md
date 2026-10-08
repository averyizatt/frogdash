# Knock monitor: how it listens and how to set it up

The knock sensor is read by the water/meth Nano (pin A5, through your amplifier) and
shown on the dash under **Knock**. This needs the current Nano firmware.

## What it does

Knock makes the cylinder ring at a frequency set by the bore. For the 2.3 L Lima's
96 mm bore that is about **6.0 kHz**.

Fifty times a second the Nano takes a burst of 64 samples at 19,200 samples a second
(3.3 ms) and measures three things:

| Reading on the dash | Meaning |
|---|---|
| **Knock-band level** | How strong the signal is between about 5.4 and 6.6 kHz. 255 is full scale. |
| **At knock frequency** | How much of the whole signal sits in that band. Ordinary engine noise is spread out and reads around 15%. Ringing reads 50% and up. |
| **Sensor swing** | The largest swing of the amplifier's output as a share of the input range. For setting the gain. |

It learns the normal level **separately for each 1000 RPM**, because an engine is
simply louder at high revs. A burst counts as a hit only when the level is well above
the learned normal for that RPM **and** the energy is concentrated at the knock
frequency. Two hits within 0.6 s raise a warning; a strong, clearly narrow hit is
critical at once. Knock is never learned as normal.

Readings are judged only while armed: knock monitoring enabled, RPM above the minimum
and manifold pressure above the arming level (120 kPa by default, about 5 psi of
boost here). They are measured and shown all the time.

## What it cannot do

- **It does not time its listening to the ignition.** The Nano has no crank or spark
  signal, so a single knock event is caught only if a burst happens to overlap it,
  roughly one time in four. Sustained knock is caught within a fraction of a second.
- **It does not protect the engine.** Nothing retards timing. The MicroSquirt's own
  knock input is unused ("Knock In" and "Knock retard" are zero in your logs). Wiring
  a detected-knock signal to the ECU is the step that would protect it, once the
  detector has been checked against real driving.
- **It has not been calibrated on this engine.** The frequency is calculated from the
  bore, not measured, and the thresholds are starting values.

## Check the sensor circuit first

Open **Knock** on the dash with the engine off, ignition on. The line under the title
shows what the detector is listening at and where the amplifier rests.

1. **Amplifier rests near 2.5 V.** The signal must swing both ways around the middle
   of the 0–5 V range. Below about 0.7 V or above 4.3 V the Nano flags a sensor fault,
   because half of the signal is being cut off.
2. **Tap test.** Tap the block near the sensor with a wrench. *Sensor swing* and
   *Knock-band level* should jump. Nothing at all means the sensor or amplifier is not
   connected.
3. **Gain at idle.** With the engine idling, *Sensor swing* should be roughly 5–15%.
   Much less and the signal is lost in the Nano's resolution: raise the amplifier gain.
4. **Gain at full load.** On a pull, *Sensor swing* should stay under about 60%. If it
   reaches 100% the amplifier is clipping (the dash flags clipping): lower the gain.

## Calibrate on the road

1. Drive normally across the rev range. **Baseline** settles within a few seconds at
   each RPM; the status reads *LEARNING* until it has.
2. Watch *At knock frequency* in normal driving. It should sit around 10–25%.
3. On a pull with no knock (safe timing, good fuel), **Knock-band level** should stay
   below **Threshold**. If it crosses it with nothing wrong, raise the multiplier or
   the offset in **Controls → Knock monitor**.
4. Look at the log afterwards: *knock energy*, *knock baseline*, *knock threshold* and
   *knock band share* are recorded with RPM and boost.

Settings (Controls → Knock monitor):

| Setting | Default | Effect |
|---|---|---|
| Threshold offset | 8 | Added to the learned level. Raise it if quiet RPM ranges false-alarm. |
| Adaptive multiplier | 2.5 | The learned level is multiplied by this. Raise it to be less sensitive. |

The threshold is *learned level × multiplier + offset*.

## If the frequency is wrong

The detector listens five bins wide (about 1.2 kHz), so a few hundred hertz of error
does not matter. The real frequency moves with engine temperature and can be found
from a recording of real knock; until then the bore calculation is the best estimate.
The firmware default is a 96 mm bore. It can be changed over CAN, in 300 Hz steps from
2.4 to 7.8 kHz.

## CAN

No new messages. The existing knock messages carry the new measurements:

| Message | Field | Now carries |
|---|---|---|
| `0x307` | energy, baseline, threshold | Knock-band level, learned level for this RPM, threshold |
| `0x307` | spare byte 7 | Share of the signal at the knock frequency, 0–255 |
| `0x30B` | bias, envelope | Amplifier resting level, largest swing in the burst |
