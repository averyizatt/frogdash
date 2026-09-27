# Shared CAN contract: schema 2 plus Frogdash extension 2

`include/can_contract/can_protocol.h` preserves the complete existing CCM and
taillight schema-2 header and appends the Frogdash extension. Existing IDs,
commands, checksums and schema-2 acknowledgements are unchanged. `sources.json`
pins the audited firmware revisions and the original header SHA-256 (UTF-8 with
LF newlines). This package requires C++11 and has no Arduino dependency.

Add `hardware/can_contract/include` to a project's include path, or copy the
header into its `include/can_contract/` directory. In the standalone water/meth
checkout this replaces the forwarding header that depends on a sibling CCM
`shared/` directory. Avoid maintaining competing header copies in one build.
For the CCM shared copy, an equivalent additive patch is supplied at
[`../compat/comfort-fuel-contract.patch`](../compat/comfort-fuel-contract.patch).
Apply it from the CCM checkout with `git apply --check` before `git apply`.

## Fuel controller usage

The external controller owns measurement, calibration, filtering and fault
detection. After initializing its CAN hardware at 500000 bit/s, publish every
`FUEL_LEVEL_TX_MS` (500 ms), including unavailable/fault reports:

```cpp
#include "can_contract/can_protocol.h"

// Use calibrated tenths of a percent: 500 means 50.0%.
can_protocol::FuelLevelState level;
level.percent_x10 = 500;
level.status = can_protocol::FuelLevelStatus::VALID;
auto frame = can_protocol::packFuelLevelState(level);
// With an initialized MCP_CAN instance named CAN:
CAN.sendMsgBuf(frame.id, 0, frame.dlc, frame.data); // 0 = standard identifier
```

Use `UNAVAILABLE` while starting and `FAULT` for failed measurements. The builder
converts out-of-range valid percentages and unknown status codes into faults.
`unpackFuelLevelState` rejects malformed frames; consumers must independently
expire old readings after `FUEL_LEVEL_TIMEOUT_MS`. See the full
[fuel layout and validity rules](../../docs/fuel-can.md).

`packGpsState` implements the existing 0x203 payload. The Pi already generates
this frame using gpsd. It has no latitude/longitude fields; full GPS position
stays local for race timing and logs. Do not add a second GPS transmitter.

## Verification

`tests/can_contract_vectors.cpp` compiles the actual firmware builders and emits
wire payloads. `tests/test_can_contract.py` compares these against Python decoding,
actual dashboard command execution and GPS transmission, and checks that the
extension leaves the original schema unchanged. Run with a C++ compiler installed:

```sh
python -m unittest tests.test_can_contract -v
```

No other repository or flashed device is updated by installing this package.
See [compatibility and ownership](../../docs/can-compatibility.md) before flashing.

## Steering-wheel input

Extension 2 adds `packSteeringButtons(mask, sequence)` for CCM ID 0x205.
The five logical bits are in `steering_button`; report version 1 is separate
from the unchanged schema-2 command ACK version. See [steering-wheel integration](../../docs/steering-wheel.md)
for the payload, timing, GPIO integration hook and incremental upgrade patch.
