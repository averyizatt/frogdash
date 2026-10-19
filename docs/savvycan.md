# CAN recordings in SavvyCAN and cantools

`hardware/can_contract/frogdash.dbc` describes every CAN message the dash knows: the
modules' own messages, the dash's commands, the firmware channel, and the MegaSquirt
broadcast. Each signal comes with its scaling, unit and value names. It is written by
`tools/make_dbc.py` from the same layouts the dash decodes. `tests/test_dbc.py` decodes
thousands of random frames both ways and fails if a single signal differs. After
changing a message, run `python tools/make_dbc.py`.

## Getting a recording

1. On the dash, open **Sensors > Raw CAN** and press **Record CAN for 20 s**.
2. Either:
   - press **Download recording**; or
   - leave it on the Pi. The dash keeps the newest five recordings, and the next report
     (after **Update now**) takes them to GitHub as
     `pi/<date>/<time>-can-<when>.log` on the `pi-logs` branch.
3. **DBC for SavvyCAN** on the same page downloads the DBC from the dash. It is the same
   file as in this repository.

The recordings are in candump log format, one frame per line:
`(1792065000.123456) can0 300#0000550114 3C4600`.

## SavvyCAN

[SavvyCAN](https://github.com/collin80/SavvyCAN) is a free CAN analyser for Windows,
macOS and Linux.

1. Load the recording as a log file, choosing the Linux candump / socketcan format if it
   asks.
2. Load `frogdash.dbc` in its DBC file manager. Frames then show their message names
   (`METH_STATE`, `KNOCK`, `MS_RT_02`, ...) and decoded signals.
3. Use the graphing window to plot signals over time, such as boost against water/meth
   duty, or knock energy against RPM.

## cantools

On a computer with Python: `pip install -r requirements-tools.lock`.

```sh
# Every message and signal, as a table
python -m cantools dump hardware/can_contract/frogdash.dbc

# A recording, decoded line by line
python -m cantools decode hardware/can_contract/frogdash.dbc < frogdash-can.log

# Signals plotted over time (also needs: pip install matplotlib)
python -m cantools plot hardware/can_contract/frogdash.dbc '*boost*' '*duty*' < frogdash-can.log
```

## Notes

- The MegaSquirt real-time broadcast is described twice, at base 0x5F0 (`MS_RT_..`)
  and at 0x700 (`MS_RT_ALT_..`), because the ECU can use either. Only one set appears
  in a recording.
- Report messages that carry several kinds (0x103, 0x30E, 0x30F) are multiplexed on
  their first byte (`kind`).
- Bytes of flags are split into one signal per bit (the taillight inputs, the knock
  status).
