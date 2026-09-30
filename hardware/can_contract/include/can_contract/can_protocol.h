#pragma once

// Shared CAN protocol contract for comfort, water-meth, and taillight modules.
// Keep IDs/packing stable across repos and bump CAN_PROTOCOL_SCHEMA_VERSION
// when a compatibility-breaking schema change is introduced.
#if defined(ARDUINO_ARCH_AVR)
#include <stdint.h>
#else
#include <cstdint>
#endif

namespace can_protocol {

// -----------------------------------------------------------------------------
// CAN network: Standard 11-bit IDs @ 500 kbit/s.
// Compatibility note: Taillight IDs 0x100, 0x101, 0x102 are preserved exactly.
// -----------------------------------------------------------------------------

constexpr uint32_t CAN_BITRATE = 500000;
constexpr uint16_t CAN_PROTOCOL_SCHEMA_VERSION = 2;

// Reserved blocks
constexpr uint16_t ID_BLOCK_TAILLIGHT_BASE = 0x100;
constexpr uint16_t ID_BLOCK_MASTER_BASE = 0x200;
constexpr uint16_t ID_BLOCK_ENGINE_METH_BASE = 0x300;
constexpr uint16_t ID_BLOCK_GPS_BASE = 0x400;
constexpr uint16_t ID_BLOCK_COMFORT_BASE = 0x500;
constexpr uint16_t ID_BLOCK_FUTURE_BASE = 0x600;

// Taillight protocol (existing, do not change)
constexpr uint16_t ID_TAILLIGHT_STATE = 0x100;   // TX every 100ms, DLC 7
constexpr uint16_t ID_TAILLIGHT_COMMAND = 0x101; // RX, DLC varies
constexpr uint16_t ID_TAILLIGHT_FAULT = 0x102;   // TX on demand, DLC 4

// Cabin master frames
constexpr uint16_t ID_MASTER_HEARTBEAT = 0x200;  // TX every 100ms, DLC 8
constexpr uint16_t ID_MASTER_COMMAND = 0x201;    // RX, DLC varies
constexpr uint16_t ID_TACH_RPM_STATE = 0x202;    // TX every 20ms, DLC 8
constexpr uint16_t ID_GPS_STATE = 0x203;         // TX every 250ms, DLC 8

// Engine/water meth frames
constexpr uint16_t ID_ENGINE_METH_STATE = 0x300;    // TX every 50ms, DLC 8
constexpr uint16_t ID_ENGINE_METH_COMMAND = 0x301;  // RX, DLC varies
constexpr uint16_t ID_ENGINE_METH_FAULT = 0x302;    // TX on demand, DLC 4
constexpr uint16_t ID_ENGINE_SENSOR_EXT = 0x303;    // TX every 250ms, DLC 8
constexpr uint16_t ID_METH_CONFIG_BROADCAST = 0x304; // TX every 500ms, DLC 8
constexpr uint16_t ID_METH_CONFIG_REQUEST = 0x305;   // RX/TX as needed, DLC 1
constexpr uint16_t ID_METH_CONFIG_ACK = 0x306;       // RX/TX as needed, DLC 4
constexpr uint16_t ID_ENGINE_KNOCK_STATE = 0x307;    // TX every 50ms, DLC 8
constexpr uint16_t ID_ENGINE_KNOCK_FAULT = 0x308;    // TX on event/fault, DLC 4
constexpr uint16_t ID_ENGINE_RUNTIME = 0x309;
constexpr uint16_t ID_ENGINE_COMMAND_ACK = 0x30A;  // command/status/value/schema; distinct from config ACK
constexpr uint16_t ID_KNOCK_LIVE_HOOK = 0x30B;
constexpr uint16_t ID_KNOCK_CONFIG_PAGE_1 = 0x30C;
constexpr uint16_t ID_KNOCK_CONFIG_PAGE_2 = 0x30D;
constexpr uint16_t ID_ENGINE_KNOCK_COMMAND = ID_ENGINE_METH_COMMAND;      // RX, command range 0x40..0x4A
constexpr uint16_t ID_KNOCK_CONFIG_REQUEST = ID_METH_CONFIG_REQUEST;      // RX/TX as needed
constexpr uint16_t ID_KNOCK_CONFIG_ACK = ID_ENGINE_COMMAND_ACK;              // RX/TX as needed, DLC 4
constexpr uint16_t ID_ENGINE_KNOCK_CONFIG_PAGE1 = ID_KNOCK_CONFIG_PAGE_1; // TX on request/change, DLC 8
constexpr uint16_t ID_ENGINE_KNOCK_CONFIG_PAGE2 = ID_KNOCK_CONFIG_PAGE_2; // TX on request/change, DLC 8

enum class MasterState : uint8_t { BOOT = 0, RUN = 1, WARN = 2, FAULT = 3, CONFIG = 4 };
enum class UiPage : uint8_t { DASH = 0, ENVIRONMENT = 1, METH = 2, LIGHTING = 3, DIAGNOSTICS = 4, SETTINGS = 5, RACE = 6 };
enum class TachSource : uint8_t { CAN = 0, GPIO_INPUT = 1, TEST = 2, DEMO = 3 };
enum class MethState : uint8_t { OFF = 0, ARMED = 1, SPRAYING = 2, FAULT = 3, TEST = 4 };
enum class FlowStatus : uint8_t { UNKNOWN = 0, OK = 1, LOW_FLOW = 2, NO_FLOW = 3 };
enum class FaultSeverity : uint8_t { INFO = 0, WARNING = 1, CRITICAL = 2 };

namespace input_flag {
constexpr uint8_t UP = 1 << 0;
constexpr uint8_t DOWN = 1 << 1;
constexpr uint8_t ENTER = 1 << 2;
constexpr uint8_t BACK = 1 << 3;
constexpr uint8_t TOUCH = 1 << 4;
}  // namespace input_flag

namespace master_command {
constexpr uint8_t SET_UI_PAGE = 0x01;          // DLC 2, B1 page
constexpr uint8_t SET_BRIGHTNESS = 0x02;       // DLC 2, B1 0..255
constexpr uint8_t TRIGGER_TACH_SWEEP = 0x03;   // DLC 1
constexpr uint8_t SET_DRIVE_MODE = 0x04;       // DLC 2, B1 mode
}  // namespace master_command

namespace taillight_command {
constexpr uint8_t SET_BRIGHTNESS = 0x01;
constexpr uint8_t SET_OVERRIDE = 0x02;
constexpr uint8_t CLEAR_OVERRIDE = 0x03;
constexpr uint8_t TRIGGER_CUSTOM_ANIMATION = 0x04;
constexpr uint8_t SET_MODE = 0x05;  // DLC 3: mode, show option (0..32)
}  // namespace taillight_command

namespace taillight_mode {
constexpr uint8_t STOCK = 0;
constexpr uint8_t SEQUENTIAL = 1;
constexpr uint8_t SHOW = 2;
constexpr uint8_t DEMO = 3;
}  // namespace taillight_mode

constexpr uint8_t TAILLIGHT_SHOW_COUNT = 33;
inline bool validTaillightMode(uint8_t mode, uint8_t option) {
  return mode <= taillight_mode::DEMO && option < TAILLIGHT_SHOW_COUNT;
}

namespace analog_sensor_fault {
constexpr uint16_t OIL = 1U << 0;
constexpr uint16_t FUEL = 1U << 1;
constexpr uint16_t METH = 1U << 2;
constexpr uint16_t BOOST_REF = 1U << 3;
constexpr uint16_t IAT = 1U << 4;
constexpr uint16_t ENGINE_BAY = 1U << 5;
constexpr uint16_t AMBIENT = 1U << 6;
constexpr uint16_t CABIN = 1U << 7;
}  // namespace analog_sensor_fault

namespace meth_command {
constexpr uint8_t ARM = 0x01;                  // DLC 2, B1 0/1
constexpr uint8_t MANUAL_TEST_DUTY = 0x02;     // DLC 2, B1 duty
constexpr uint8_t STOP_MANUAL_TEST = 0x03;     // DLC 1
constexpr uint8_t SET_BOOST_TRIGGER = 0x04;    // DLC 2, B1 kPa
constexpr uint8_t SET_IAT_THRESHOLD = 0x05;    // DLC 2, B1 temp + 40
constexpr uint8_t CLEAR_FAULTS = 0x06;         // DLC 1
constexpr uint8_t KNOCK_SET_ENABLE = 0x40;
constexpr uint8_t KNOCK_SET_THRESHOLD_OFFSET = 0x41;
constexpr uint8_t KNOCK_SET_ADAPTIVE_MULTIPLIER_X10 = 0x42;
constexpr uint8_t KNOCK_SET_MIN_RPM_DIV100 = 0x43;
constexpr uint8_t KNOCK_SET_MIN_MAP_KPA = 0x44;
constexpr uint8_t KNOCK_SET_DEBOUNCE_MS_DIV10 = 0x45;
constexpr uint8_t KNOCK_SET_GAIN_X10 = 0x46;
constexpr uint8_t KNOCK_SET_CENTER_FREQ_DIV100 = 0x47;
constexpr uint8_t KNOCK_SET_BANDWIDTH_DIV100 = 0x48;
constexpr uint8_t KNOCK_SET_AUTO_FREQ_FROM_BORE = 0x49;
constexpr uint8_t KNOCK_CLEAR_EVENTS = 0x4A;
}  // namespace meth_command

namespace config_ack_status {
constexpr uint8_t OK = 0x00;
constexpr uint8_t UNSUPPORTED_COMMAND = 0x01;
constexpr uint8_t INVALID_LENGTH = 0x02;
constexpr uint8_t VALUE_CLAMPED = 0x03;
}  // namespace config_ack_status

namespace meth_fault_code {
constexpr uint8_t LOW_TANK = 0x01;
constexpr uint8_t NO_FLOW = 0x02;
constexpr uint8_t LOW_FLOW = 0x03;
constexpr uint8_t PUMP_OVERCURRENT = 0x04;
constexpr uint8_t SENSOR_FAIL = 0x05;
constexpr uint8_t OVER_TEMP = 0x06;
constexpr uint8_t CAN_TIMEOUT = 0x07;
constexpr uint8_t CONFIG_INVALID = 0x08;
constexpr uint8_t SAFETY_SHUTDOWN = 0x09;
}  // namespace meth_fault_code

namespace knock_fault_code {
constexpr uint8_t KNOCK_WARNING = 0x01;
constexpr uint8_t KNOCK_CRITICAL = 0x02;
constexpr uint8_t SENSOR_DISCONNECTED = 0x03;
constexpr uint8_t SIGNAL_CLIPPING = 0x04;
constexpr uint8_t BASELINE_NOT_LEARNED = 0x05;
constexpr uint8_t ADC_FAULT = 0x06;
}  // namespace knock_fault_code

namespace knock_status_flag {
constexpr uint8_t ENABLED = 1U << 0;
constexpr uint8_t SIGNAL_VALID = 1U << 1;
constexpr uint8_t WARNING_ACTIVE = 1U << 2;
constexpr uint8_t CRITICAL_ACTIVE = 1U << 3;
constexpr uint8_t BASELINE_LEARNED = 1U << 4;
constexpr uint8_t SENSOR_FAULT = 1U << 5;
constexpr uint8_t CLIPPING_DETECTED = 1U << 6;
}  // namespace knock_status_flag

namespace knock_command {
constexpr uint8_t SET_ENABLE = meth_command::KNOCK_SET_ENABLE;
constexpr uint8_t SET_THRESHOLD_OFFSET = meth_command::KNOCK_SET_THRESHOLD_OFFSET;
constexpr uint8_t SET_ADAPTIVE_MULTIPLIER = meth_command::KNOCK_SET_ADAPTIVE_MULTIPLIER_X10;
constexpr uint8_t SET_MIN_RPM = meth_command::KNOCK_SET_MIN_RPM_DIV100;
constexpr uint8_t SET_MIN_MAP_KPA = meth_command::KNOCK_SET_MIN_MAP_KPA;
constexpr uint8_t SET_DEBOUNCE = meth_command::KNOCK_SET_DEBOUNCE_MS_DIV10;
constexpr uint8_t SET_GAIN = meth_command::KNOCK_SET_GAIN_X10;
constexpr uint8_t SET_CENTER_FREQUENCY = meth_command::KNOCK_SET_CENTER_FREQ_DIV100;
constexpr uint8_t SET_BANDWIDTH = meth_command::KNOCK_SET_BANDWIDTH_DIV100;
constexpr uint8_t SET_AUTO_FREQUENCY_FROM_BORE = meth_command::KNOCK_SET_AUTO_FREQ_FROM_BORE;
constexpr uint8_t CLEAR_EVENTS_AND_FAULTS = meth_command::KNOCK_CLEAR_EVENTS;
}  // namespace knock_command

namespace knock_ack_status {
constexpr uint8_t OK = config_ack_status::OK;
constexpr uint8_t UNSUPPORTED_COMMAND = config_ack_status::UNSUPPORTED_COMMAND;
constexpr uint8_t INVALID_LENGTH = config_ack_status::INVALID_LENGTH;
constexpr uint8_t VALUE_CLAMPED = config_ack_status::VALUE_CLAMPED;
}  // namespace knock_ack_status

struct CanFrame {
  uint16_t id = 0;
  uint8_t dlc = 0;
  uint8_t data[8]{};
};

inline uint8_t clampU8(int value) {
  return static_cast<uint8_t>(value < 0 ? 0 : (value > 255 ? 255 : value));
}

inline uint8_t tempToOffset40(int celsius) {
  return clampU8(celsius + 40);
}

inline int8_t offset40ToTemp(uint8_t encoded) {
  return static_cast<int8_t>(static_cast<int16_t>(encoded) - 40);
}

inline uint8_t voltsTo10(float volts) {
  const int voltsScaledBy10 = static_cast<int>(volts * 10.0f + 0.5f);
  return clampU8(voltsScaledBy10);
}

inline uint16_t decodeU16BE(uint8_t high, uint8_t low) {
  return static_cast<uint16_t>((static_cast<uint16_t>(high) << 8) | low);
}

inline void encodeU16BE(uint16_t value, uint8_t& high, uint8_t& low) {
  high = static_cast<uint8_t>((value >> 8) & 0xFF);
  low = static_cast<uint8_t>(value & 0xFF);
}

struct TaillightState {
  // 0x100, DLC 7 (compat contract)
  // B0 left, B1 right, B2 driver inputs, B3 passenger inputs,
  // B4 brightness, B5 raw die Celsius, B6 derate (0..255).
  uint8_t left_state = 0;
  uint8_t right_state = 0;
  uint8_t input_flags = 0;  // combined inputs for existing consumers
  uint8_t driver_input_flags = 0;
  uint8_t passenger_input_flags = 0;
  uint8_t brightness = 0;
  uint8_t die_temp_c = 0;
  uint8_t thermal_derate = 0;
};

inline bool unpackTaillightState(const CanFrame& frame, TaillightState& out) {
  if (frame.id != ID_TAILLIGHT_STATE || frame.dlc < 7) return false;
  out.left_state = frame.data[0];
  out.right_state = frame.data[1];
  out.driver_input_flags = frame.data[2];
  out.passenger_input_flags = frame.data[3];
  out.input_flags = frame.data[2] | frame.data[3];
  out.brightness = frame.data[4];
  out.die_temp_c = frame.data[5];
  out.thermal_derate = frame.data[6];
  return true;
}

struct TaillightFault {
  // 0x102, DLC 4: B0 code, B1 severity, B2 data0, B3 data1
  uint8_t code = 0;
  uint8_t severity = 0;
  uint8_t data0 = 0;
  uint8_t data1 = 0;
};

inline bool unpackTaillightFault(const CanFrame& frame, TaillightFault& out) {
  if (frame.id != ID_TAILLIGHT_FAULT || frame.dlc < 4) return false;
  out.code = frame.data[0];
  out.severity = frame.data[1];
  out.data0 = frame.data[2];
  out.data1 = frame.data[3];
  return true;
}

struct EngineMethState {
  // 0x300, DLC 8
  // B0 meth state, B1 pump duty, B2 tank %, B3 flow status,
  // B4 gauge boost kPa, B5 IAT+40, B6 engine bay+40, B7 fault flags.
  uint8_t meth_state = 0;
  uint8_t pump_duty = 0;
  uint8_t tank_level = 0;
  uint8_t flow_status = 0;
  uint8_t boost_kpa = 0;
  int8_t iat_c = 0;
  int8_t engine_bay_c = 0;
  uint8_t fault_flags = 0;
};

inline bool unpackEngineMethState(const CanFrame& frame, EngineMethState& out) {
  if (frame.id != ID_ENGINE_METH_STATE || frame.dlc < 8) return false;
  out.meth_state = frame.data[0];
  out.pump_duty = frame.data[1];
  out.tank_level = frame.data[2];
  out.flow_status = frame.data[3];
  out.boost_kpa = frame.data[4];
  out.iat_c = offset40ToTemp(frame.data[5]);
  out.engine_bay_c = offset40ToTemp(frame.data[6]);
  out.fault_flags = frame.data[7];
  return true;
}

struct EngineMethFault {
  // 0x302, DLC 4
  uint8_t code = 0;
  uint8_t severity = 0;
  uint8_t data0 = 0;
  uint8_t data1 = 0;
};

inline bool unpackEngineMethFault(const CanFrame& frame, EngineMethFault& out) {
  if (frame.id != ID_ENGINE_METH_FAULT || frame.dlc < 4) return false;
  out.code = frame.data[0];
  out.severity = frame.data[1];
  out.data0 = frame.data[2];
  out.data1 = frame.data[3];
  return true;
}

inline CanFrame packEngineMethState(const EngineMethState &state) {
  CanFrame frame{};
  frame.id = ID_ENGINE_METH_STATE;
  frame.dlc = 8;
  frame.data[0] = state.meth_state;
  frame.data[1] = state.pump_duty;
  frame.data[2] = state.tank_level;
  frame.data[3] = state.flow_status;
  frame.data[4] = state.boost_kpa;
  frame.data[5] = tempToOffset40(state.iat_c);
  frame.data[6] = tempToOffset40(state.engine_bay_c);
  frame.data[7] = state.fault_flags;
  return frame;
}

struct EngineSensorExt {
  // 0x303, DLC 8
  // B0 oil pressure psi * 2 (0..127.5 psi)
  // B1 fuel pressure psi * 2 (0..127.5 psi)
  // B2 meth pressure psi * 2 (0..127.5 psi)
  // B3 boost-ref pressure psi * 2 (0..127.5 psi)
  // B4 ambient temp offset40
  // B5 cabin temp offset40
  // B6 analog sensor fault flags low byte
  // B7 analog sensor fault flags high byte
  uint8_t oil_pressure_psi_x2 = 0;
  uint8_t fuel_pressure_psi_x2 = 0;
  uint8_t meth_pressure_psi_x2 = 0;
  uint8_t boost_ref_pressure_psi_x2 = 0;
  int8_t ambient_temp_c = 0;
  int8_t cabin_temp_c = 0;
  uint16_t analog_fault_flags = 0;
};

struct EngineRuntime {
  uint16_t rpm = 0;
  uint8_t map_kpa = 0;
  uint8_t valid_flags = 0;
};

inline bool unpackEngineSensorExt(const CanFrame& frame, EngineSensorExt& out) {
  if (frame.id != ID_ENGINE_SENSOR_EXT || frame.dlc < 8) return false;
  out.oil_pressure_psi_x2 = frame.data[0];
  out.fuel_pressure_psi_x2 = frame.data[1];
  out.meth_pressure_psi_x2 = frame.data[2];
  out.boost_ref_pressure_psi_x2 = frame.data[3];
  out.ambient_temp_c = offset40ToTemp(frame.data[4]);
  out.cabin_temp_c = offset40ToTemp(frame.data[5]);
  out.analog_fault_flags = static_cast<uint16_t>((static_cast<uint16_t>(frame.data[7]) << 8U) | frame.data[6]);
  return true;
}

inline CanFrame packEngineSensorExt(const EngineSensorExt& ext) {
  CanFrame frame{};
  frame.id = ID_ENGINE_SENSOR_EXT;
  frame.dlc = 8;
  frame.data[0] = ext.oil_pressure_psi_x2;
  frame.data[1] = ext.fuel_pressure_psi_x2;
  frame.data[2] = ext.meth_pressure_psi_x2;
  frame.data[3] = ext.boost_ref_pressure_psi_x2;
  frame.data[4] = tempToOffset40(ext.ambient_temp_c);
  frame.data[5] = tempToOffset40(ext.cabin_temp_c);
  frame.data[6] = static_cast<uint8_t>(ext.analog_fault_flags & 0xFFU);
  frame.data[7] = static_cast<uint8_t>((ext.analog_fault_flags >> 8U) & 0xFFU);
  return frame;
}

struct EngineKnockState {
  uint8_t status_flags = 0;          // knock_status_flag bitfield
  uint8_t energy = 0;                // processed knock energy, 0..255
  uint8_t baseline = 0;              // learned noise floor, 0..255
  uint8_t threshold = 0;             // active warning/critical threshold, 0..255
  uint8_t event_count = 0;           // wraps at 255
  uint8_t last_event_rpm_div100 = 0; // RPM / 100
  uint8_t last_event_boost_kpa = 0;  // boost/manifold pressure near event
  uint8_t reserved = 0;              // keep 0 for now
};

inline bool unpackEngineKnockState(const CanFrame& frame, EngineKnockState& out) {
  if (frame.id != ID_ENGINE_KNOCK_STATE || frame.dlc < 8) return false;
  out.status_flags = frame.data[0];
  out.energy = frame.data[1];
  out.baseline = frame.data[2];
  out.threshold = frame.data[3];
  out.event_count = frame.data[4];
  out.last_event_rpm_div100 = frame.data[5];
  out.last_event_boost_kpa = frame.data[6];
  out.reserved = frame.data[7];
  return true;
}

struct EngineKnockFault {
  uint8_t code = 0;
  uint8_t severity = 0;
  uint8_t data0 = 0;
  uint8_t data1 = 0;
};

inline bool unpackEngineKnockFault(const CanFrame& frame, EngineKnockFault& out) {
  if (frame.id != ID_ENGINE_KNOCK_FAULT || frame.dlc < 4) return false;
  out.code = frame.data[0];
  out.severity = frame.data[1];
  out.data0 = frame.data[2];
  out.data1 = frame.data[3];
  return true;
}

inline CanFrame packEngineRuntime(const EngineRuntime& runtime) {
  CanFrame frame{};
  frame.id = ID_ENGINE_RUNTIME;
  frame.dlc = 4;
  frame.data[0] = static_cast<uint8_t>(runtime.rpm & 0xFFU);
  frame.data[1] = static_cast<uint8_t>((runtime.rpm >> 8U) & 0xFFU);
  frame.data[2] = runtime.map_kpa;
  frame.data[3] = runtime.valid_flags;
  return frame;
}

struct KnockLiveHook {
  uint8_t flags = 0;
  uint8_t live_knock_rms = 0;
  uint8_t adaptive_threshold = 0;
  uint8_t adaptive_baseline = 0;
  uint8_t event_count = 0;
  uint8_t bias_adc_div16 = 0;
  uint8_t raw_adc_div16 = 0;
  uint8_t envelope_level = 0;
};

inline bool unpackKnockLiveHook(const CanFrame& frame, KnockLiveHook& out) {
  if (frame.id != ID_KNOCK_LIVE_HOOK || frame.dlc < 8) return false;
  out.flags = frame.data[0];
  out.live_knock_rms = frame.data[1];
  out.adaptive_threshold = frame.data[2];
  out.adaptive_baseline = frame.data[3];
  out.event_count = frame.data[4];
  out.bias_adc_div16 = frame.data[5];
  out.raw_adc_div16 = frame.data[6];
  out.envelope_level = frame.data[7];
  return true;
}

struct EngineKnockConfigAck {
  uint8_t command = 0;
  uint8_t status = 0;
  uint8_t applied_value = 0;
  uint8_t schema_version = 0;
};

using EngineCommandAck = EngineKnockConfigAck;
inline bool unpackEngineCommandAck(const CanFrame& frame, EngineCommandAck& out) {
  if (frame.id != ID_ENGINE_COMMAND_ACK || frame.dlc != 4 ||
      frame.data[3] != CAN_PROTOCOL_SCHEMA_VERSION) return false;
  out.command = frame.data[0];
  out.status = frame.data[1];
  out.applied_value = frame.data[2];
  out.schema_version = frame.data[3];
  return true;
}

inline CanFrame packTaillightState(const TaillightState& state) {
  CanFrame frame{};
  frame.id = ID_TAILLIGHT_STATE;
  frame.dlc = 7;
  frame.data[0] = state.left_state;
  frame.data[1] = state.right_state;
  frame.data[2] = state.driver_input_flags;
  frame.data[3] = state.passenger_input_flags;
  frame.data[4] = state.brightness;
  frame.data[5] = state.die_temp_c;
  frame.data[6] = state.thermal_derate;
  return frame;
}

inline bool unpackEngineKnockConfigAck(const CanFrame& frame, EngineKnockConfigAck& out) {
  if (frame.id != ID_KNOCK_CONFIG_ACK || frame.dlc < 4) return false;
  if (frame.data[0] < knock_command::SET_ENABLE || frame.data[0] > knock_command::CLEAR_EVENTS_AND_FAULTS) return false;
  if (frame.data[3] != CAN_PROTOCOL_SCHEMA_VERSION) return false;
  out.command = frame.data[0];
  out.status = frame.data[1];
  out.applied_value = frame.data[2];
  out.schema_version = frame.data[3];
  return true;
}

struct KnockConfigPage1 {
  uint8_t config_flags = 0;
  uint8_t threshold_offset = 0;
  uint8_t adaptive_multiplier_x10 = 0;
  uint8_t min_rpm_div100 = 0;
  uint8_t min_map_kpa = 0;
  uint8_t debounce_ms_div10 = 0;
  uint8_t gain_x10 = 0;
  uint8_t center_frequency_div100 = 0;
};

inline bool unpackKnockConfigPage1(const CanFrame& frame, KnockConfigPage1& out) {
  if (frame.id != ID_KNOCK_CONFIG_PAGE_1 || frame.dlc < 8) return false;
  out.config_flags = frame.data[0];
  out.threshold_offset = frame.data[1];
  out.adaptive_multiplier_x10 = frame.data[2];
  out.min_rpm_div100 = frame.data[3];
  out.min_map_kpa = frame.data[4];
  out.debounce_ms_div10 = frame.data[5];
  out.gain_x10 = frame.data[6];
  out.center_frequency_div100 = frame.data[7];
  return true;
}

struct KnockConfigPage2 {
  uint8_t bandwidth_div100 = 0;
  uint8_t sample_rate_div100 = 0;
  uint8_t samples_per_update = 0;
  uint8_t bias_alpha_x1000 = 0;
  uint8_t rms_alpha_x100 = 0;
  uint8_t envelope_alpha_x100 = 0;
  uint8_t bore_mm = 0;
  uint8_t reserved = 0;
};

inline bool unpackKnockConfigPage2(const CanFrame& frame, KnockConfigPage2& out) {
  if (frame.id != ID_KNOCK_CONFIG_PAGE_2 || frame.dlc < 8) return false;
  out.bandwidth_div100 = frame.data[0];
  out.sample_rate_div100 = frame.data[1];
  out.samples_per_update = frame.data[2];
  out.bias_alpha_x1000 = frame.data[3];
  out.rms_alpha_x100 = frame.data[4];
  out.envelope_alpha_x100 = frame.data[5];
  out.bore_mm = frame.data[6];
  out.reserved = frame.data[7];
  return true;
}

using EngineKnockConfigPage1 = KnockConfigPage1;
using EngineKnockConfigPage2 = KnockConfigPage2;

inline bool unpackEngineKnockConfigPage1(const CanFrame& frame, EngineKnockConfigPage1& out) {
  return unpackKnockConfigPage1(frame, out);
}

inline bool unpackEngineKnockConfigPage2(const CanFrame& frame, EngineKnockConfigPage2& out) {
  return unpackKnockConfigPage2(frame, out);
}

inline CanFrame packEngineKnockState(const EngineKnockState& state) {
  CanFrame frame{};
  frame.id = ID_ENGINE_KNOCK_STATE;
  frame.dlc = 8;
  frame.data[0] = state.status_flags;
  frame.data[1] = state.energy;
  frame.data[2] = state.baseline;
  frame.data[3] = state.threshold;
  frame.data[4] = state.event_count;
  frame.data[5] = state.last_event_rpm_div100;
  frame.data[6] = state.last_event_boost_kpa;
  frame.data[7] = state.reserved;
  return frame;
}

inline CanFrame packEngineKnockFault(uint8_t code, uint8_t severity, uint8_t data0, uint8_t data1) {
  CanFrame frame{};
  frame.id = ID_ENGINE_KNOCK_FAULT;
  frame.dlc = 4;
  frame.data[0] = code;
  frame.data[1] = severity;
  frame.data[2] = data0;
  frame.data[3] = data1;
  return frame;
}

inline CanFrame packKnockLiveHook(const KnockLiveHook& hook) {
  CanFrame frame{};
  frame.id = ID_KNOCK_LIVE_HOOK;
  frame.dlc = 8;
  frame.data[0] = hook.flags;
  frame.data[1] = hook.live_knock_rms;
  frame.data[2] = hook.adaptive_threshold;
  frame.data[3] = hook.adaptive_baseline;
  frame.data[4] = hook.event_count;
  frame.data[5] = hook.bias_adc_div16;
  frame.data[6] = hook.raw_adc_div16;
  frame.data[7] = hook.envelope_level;
  return frame;
}

inline CanFrame packKnockConfigPage1(const KnockConfigPage1& page) {
  CanFrame frame{};
  frame.id = ID_KNOCK_CONFIG_PAGE_1;
  frame.dlc = 8;
  frame.data[0] = page.config_flags;
  frame.data[1] = page.threshold_offset;
  frame.data[2] = page.adaptive_multiplier_x10;
  frame.data[3] = page.min_rpm_div100;
  frame.data[4] = page.min_map_kpa;
  frame.data[5] = page.debounce_ms_div10;
  frame.data[6] = page.gain_x10;
  frame.data[7] = page.center_frequency_div100;
  return frame;
}

inline CanFrame packKnockConfigPage2(const KnockConfigPage2& page) {
  CanFrame frame{};
  frame.id = ID_KNOCK_CONFIG_PAGE_2;
  frame.dlc = 8;
  frame.data[0] = page.bandwidth_div100;
  frame.data[1] = page.sample_rate_div100;
  frame.data[2] = page.samples_per_update;
  frame.data[3] = page.bias_alpha_x1000;
  frame.data[4] = page.rms_alpha_x100;
  frame.data[5] = page.envelope_alpha_x100;
  frame.data[6] = page.bore_mm;
  frame.data[7] = page.reserved;
  return frame;
}

inline CanFrame packEngineKnockCommand(uint8_t command, uint8_t value = 0) {
  CanFrame frame{};
  frame.id = ID_ENGINE_KNOCK_COMMAND;
  frame.dlc = 2;
  frame.data[0] = command;
  frame.data[1] = value;
  return frame;
}

inline CanFrame packEngineKnockConfigRequest() {
  CanFrame frame{};
  frame.id = ID_KNOCK_CONFIG_REQUEST;
  frame.dlc = 1;
  frame.data[0] = 0x40;
  return frame;
}

inline CanFrame packConfigAck(uint8_t command, uint8_t status, uint8_t value, uint8_t schemaVersion) {
  CanFrame frame{};
  frame.id = ID_ENGINE_COMMAND_ACK;
  frame.dlc = 4;
  frame.data[0] = command;
  frame.data[1] = status;
  frame.data[2] = value;
  frame.data[3] = schemaVersion;
  return frame;
}

inline CanFrame packTaillightBrightness(uint8_t brightness) {
  CanFrame frame{};
  frame.id = ID_TAILLIGHT_COMMAND;
  frame.dlc = 2;
  frame.data[0] = taillight_command::SET_BRIGHTNESS;
  frame.data[1] = brightness;
  return frame;
}

inline CanFrame packTaillightMode(uint8_t mode, uint8_t option = 0) {
  CanFrame frame{};
  frame.id = ID_TAILLIGHT_COMMAND;
  frame.dlc = 3;
  frame.data[0] = taillight_command::SET_MODE;
  frame.data[1] = mode;
  frame.data[2] = option;
  return frame;
}

inline CanFrame packTaillightOverride(uint8_t leftState, uint8_t rightState) {
  CanFrame frame{};
  frame.id = ID_TAILLIGHT_COMMAND;
  frame.dlc = 3;
  frame.data[0] = taillight_command::SET_OVERRIDE;
  frame.data[1] = leftState;
  frame.data[2] = rightState;
  return frame;
}

inline CanFrame packTaillightClearOverride() {
  CanFrame frame{};
  frame.id = ID_TAILLIGHT_COMMAND;
  frame.dlc = 1;
  frame.data[0] = taillight_command::CLEAR_OVERRIDE;
  return frame;
}

inline CanFrame packTaillightCustomAnimation(uint8_t animId, uint16_t durationMs, uint8_t param0, uint8_t param1) {
  CanFrame frame{};
  frame.id = ID_TAILLIGHT_COMMAND;
  frame.dlc = 6;
  frame.data[0] = taillight_command::TRIGGER_CUSTOM_ANIMATION;
  frame.data[1] = animId;
  encodeU16BE(durationMs, frame.data[2], frame.data[3]);
  frame.data[4] = param0;
  frame.data[5] = param1;
  return frame;
}

inline CanFrame packMethArm(bool armed) {
  CanFrame frame{};
  frame.id = ID_ENGINE_METH_COMMAND;
  frame.dlc = 2;
  frame.data[0] = meth_command::ARM;
  frame.data[1] = armed ? 1 : 0;
  return frame;
}

inline CanFrame packMethManualTest(uint8_t duty) {
  CanFrame frame{};
  frame.id = ID_ENGINE_METH_COMMAND;
  frame.dlc = 2;
  frame.data[0] = meth_command::MANUAL_TEST_DUTY;
  frame.data[1] = duty;
  return frame;
}

inline CanFrame packMethStopManualTest() {
  CanFrame frame{};
  frame.id = ID_ENGINE_METH_COMMAND;
  frame.dlc = 1;
  frame.data[0] = meth_command::STOP_MANUAL_TEST;
  return frame;
}

inline CanFrame packMethSetBoostThreshold(uint8_t kpa) {
  CanFrame frame{};
  frame.id = ID_ENGINE_METH_COMMAND;
  frame.dlc = 2;
  frame.data[0] = meth_command::SET_BOOST_TRIGGER;
  frame.data[1] = kpa;
  return frame;
}

inline CanFrame packMethSetIatThreshold(int iatC) {
  CanFrame frame{};
  frame.id = ID_ENGINE_METH_COMMAND;
  frame.dlc = 2;
  frame.data[0] = meth_command::SET_IAT_THRESHOLD;
  frame.data[1] = tempToOffset40(iatC);
  return frame;
}

inline CanFrame packMethClearFaults() {
  CanFrame frame{};
  frame.id = ID_ENGINE_METH_COMMAND;
  frame.dlc = 1;
  frame.data[0] = meth_command::CLEAR_FAULTS;
  return frame;
}

struct MethConfigBroadcast {
  uint8_t version = 0;
  uint8_t desired_armed = 0;
  uint8_t ratio_percent = 255;    // 255 = unknown/custom
  uint8_t boost_trigger_kpa = 0;
  uint8_t iat_threshold_offset40 = 0;
  uint8_t max_pump_duty = 0;
  uint8_t failsafe_flags = 0;
  uint8_t checksum = 0;
};

struct MethConfigRequest {
  uint8_t reason = 0;  // 0 boot, 1 config expired, 2 user requested, 3 checksum mismatch
};

struct MethConfigAck {
  uint8_t accepted_version = 0;
  uint8_t status = 0;  // 0 OK, 1 rejected, 2 partial, 3 fault locked
  uint8_t reject_reason = 0;
  uint8_t active_ratio_percent = 255;
};

inline uint8_t simpleXorChecksum(const uint8_t* data, uint8_t len) {
  uint8_t checksum = 0;
  for (uint8_t i = 0; i < len; ++i) {
    checksum ^= data[i];
  }
  return checksum;
}

inline bool validateMethConfigChecksum(const MethConfigBroadcast& cfg) {
  const uint8_t data[7] = {
      cfg.version, cfg.desired_armed, cfg.ratio_percent, cfg.boost_trigger_kpa, cfg.iat_threshold_offset40, cfg.max_pump_duty, cfg.failsafe_flags};
  return cfg.checksum == simpleXorChecksum(data, 7);
}

inline bool unpackMethConfigBroadcast(const CanFrame& frame, MethConfigBroadcast& out) {
  if (frame.id != ID_METH_CONFIG_BROADCAST || frame.dlc < 8) return false;
  out.version = frame.data[0];
  out.desired_armed = frame.data[1];
  out.ratio_percent = frame.data[2];
  out.boost_trigger_kpa = frame.data[3];
  out.iat_threshold_offset40 = frame.data[4];
  out.max_pump_duty = frame.data[5];
  out.failsafe_flags = frame.data[6];
  out.checksum = frame.data[7];
  return true;
}

inline bool unpackMethConfigRequest(const CanFrame& frame, MethConfigRequest& out) {
  if (frame.id != ID_METH_CONFIG_REQUEST || frame.dlc < 1) return false;
  out.reason = frame.data[0];
  return true;
}

inline bool unpackMethConfigAck(const CanFrame& frame, MethConfigAck& out) {
  if (frame.id != ID_METH_CONFIG_ACK || frame.dlc < 4) return false;
  out.accepted_version = frame.data[0];
  out.status = frame.data[1];
  out.reject_reason = frame.data[2];
  out.active_ratio_percent = frame.data[3];
  return true;
}

inline CanFrame packMethConfigBroadcast(const MethConfigBroadcast& cfgInput) {
  MethConfigBroadcast cfg = cfgInput;
  const uint8_t data[7] = {
      cfg.version, cfg.desired_armed, cfg.ratio_percent, cfg.boost_trigger_kpa, cfg.iat_threshold_offset40, cfg.max_pump_duty, cfg.failsafe_flags};
  cfg.checksum = simpleXorChecksum(data, 7);

  CanFrame frame{};
  frame.id = ID_METH_CONFIG_BROADCAST;
  frame.dlc = 8;
  frame.data[0] = cfg.version;
  frame.data[1] = cfg.desired_armed;
  frame.data[2] = cfg.ratio_percent;
  frame.data[3] = cfg.boost_trigger_kpa;
  frame.data[4] = cfg.iat_threshold_offset40;
  frame.data[5] = cfg.max_pump_duty;
  frame.data[6] = cfg.failsafe_flags;
  frame.data[7] = cfg.checksum;
  return frame;
}

inline CanFrame packMethConfigRequest(uint8_t reason) {
  CanFrame frame{};
  frame.id = ID_METH_CONFIG_REQUEST;
  frame.dlc = 1;
  frame.data[0] = reason;
  return frame;
}

inline CanFrame packMethConfigAck(uint8_t acceptedVersion, uint8_t status, uint8_t rejectReason, uint8_t activeRatioPercent) {
  CanFrame frame{};
  frame.id = ID_METH_CONFIG_ACK;
  frame.dlc = 4;
  frame.data[0] = acceptedVersion;
  frame.data[1] = status;
  frame.data[2] = rejectReason;
  frame.data[3] = activeRatioPercent;
  return frame;
}

// BEGIN FROGDASH ADDITIVE EXTENSION
// Existing schema-2 IDs, layouts and ACK schema remain unchanged.
constexpr uint8_t FROGDASH_EXTENSION_VERSION = 3;
constexpr uint16_t ID_FUEL_LEVEL_STATE = 0x204;
constexpr uint8_t FUEL_LEVEL_DLC = 3;
constexpr uint32_t FUEL_LEVEL_TX_MS = 500;
constexpr uint32_t FUEL_LEVEL_TIMEOUT_MS = 2000;
enum class FuelLevelStatus : uint8_t { UNAVAILABLE = 0, VALID = 1, FAULT = 2 };
struct FuelLevelState {
  uint16_t percent_x10 = 0;
  FuelLevelStatus status = FuelLevelStatus::UNAVAILABLE;
};
inline CanFrame packFuelLevelState(const FuelLevelState& value) {
  CanFrame frame{};
  frame.id = ID_FUEL_LEVEL_STATE;
  frame.dlc = FUEL_LEVEL_DLC;
  uint8_t status = static_cast<uint8_t>(value.status);
  if (status > 2 || (status == 1 && value.percent_x10 > 1000)) status = 2;
  encodeU16BE(status == 1 ? value.percent_x10 : 0, frame.data[0], frame.data[1]);
  frame.data[2] = status;
  return frame;
}
inline bool unpackFuelLevelState(const CanFrame& frame, FuelLevelState& out) {
  if (frame.id != ID_FUEL_LEVEL_STATE || frame.dlc != FUEL_LEVEL_DLC || frame.data[2] > 2) return false;
  const uint16_t level = static_cast<uint16_t>((static_cast<uint16_t>(frame.data[0]) << 8) | frame.data[1]);
  if (frame.data[2] == 1 && level > 1000) return false;
  out.percent_x10 = frame.data[2] == 1 ? level : 0;
  out.status = static_cast<FuelLevelStatus>(frame.data[2]);
  return true;
}
// Shared builder for the existing 0x203 layout used by the CCM and Pi GPS.
// Status bit 0 = live RX, bit 4 = fix valid, bit 5 = dead reckoning (not live).
struct GpsState {
  uint16_t speed_kph_x10 = 0;
  int16_t altitude_m = 0;
  uint8_t satellites = 0;
  uint8_t fix_type = 0;
  uint8_t status_flags = 0;
  uint8_t satellites_in_view = 0;
};
inline CanFrame packGpsState(const GpsState& value) {
  CanFrame frame{};
  frame.id = ID_GPS_STATE;
  frame.dlc = 8;
  encodeU16BE(value.speed_kph_x10, frame.data[0], frame.data[1]);
  encodeU16BE(static_cast<uint16_t>(value.altitude_m), frame.data[2], frame.data[3]);
  frame.data[4] = value.satellites;
  frame.data[5] = value.fix_type;
  frame.data[6] = value.status_flags;
  frame.data[7] = value.satellites_in_view;
  return frame;
}
// CCM steering pad: debounced levels on change and every 50 ms. Counter
// advances on every report, including idle. Never reuse heartbeat input_flag.
constexpr uint16_t ID_STEERING_BUTTONS = 0x205;
constexpr uint8_t STEERING_BUTTONS_VERSION = 1;
constexpr uint32_t STEERING_BUTTONS_TX_MS = 50;
namespace steering_button {
constexpr uint8_t UP = 1 << 0;
constexpr uint8_t DOWN = 1 << 1;
constexpr uint8_t LEFT = 1 << 2;
constexpr uint8_t RIGHT = 1 << 3;
constexpr uint8_t OK = 1 << 4;
}
inline CanFrame packSteeringButtons(uint8_t pressedMask, uint8_t sequence) {
  CanFrame frame{};
  frame.id = ID_STEERING_BUTTONS;
  frame.dlc = 3;
  frame.data[0] = pressedMask;
  frame.data[1] = sequence;
  frame.data[2] = STEERING_BUTTONS_VERSION;
  return frame;
}
// Taillight settings over CAN (extension 3). Existing 0x100..0x102 frames and
// taillight commands 0x01..0x05 are unchanged; these commands are new on 0x101
// and the controller reports on the new ID 0x103. Firmware that predates them
// ignores the new command bytes.
constexpr uint16_t ID_TAILLIGHT_STATUS = 0x103;  // TX by taillight controller, DLC 8
constexpr uint32_t TAILLIGHT_STATUS_TX_MS = 500;
constexpr uint8_t TAILLIGHT_SHOW_MAX = 35;        // Shows 0..35; SET_MODE still selects 0..32
namespace taillight_command {
constexpr uint8_t SET_SETTING = 0x06;      // DLC 4: key, value u16 BE (clamped to the key's range)
constexpr uint8_t SET_COLOR = 0x07;        // DLC 5: taillight_color, R, G, B
constexpr uint8_t SET_SHOW_TEXT = 0x08;    // DLC 2..8: offset, up to 6 chars; offset 0 starts a new text
constexpr uint8_t SETTINGS_ACTION = 0x09;  // DLC 2..3: taillight_action, argument
}  // namespace taillight_command
namespace taillight_setting {
constexpr uint8_t BRIGHTNESS = 1;       // 10..255 saved main brightness
constexpr uint8_t BRIGHTNESS_DIM = 2;   // 5..35 % running-light level
constexpr uint8_t TURN_BLINK_MS = 3;    // 200..1500 full blink cycle
constexpr uint8_t TURN_CUSTOM = 4;      // 0 equal on/off, 1 custom phases below
constexpr uint8_t TURN_SWEEP_MS = 5;    // 50..1500
constexpr uint8_t TURN_HOLD_MS = 6;     // 0..1500
constexpr uint8_t TURN_OFF_MS = 7;      // 50..1500
constexpr uint8_t BRAKE_SPEED = 8;      // 50..200 % animation speed
constexpr uint8_t REVERSE_SPEED = 9;    // 50..200 %
constexpr uint8_t RUN_SPEED = 10;       // 50..200 %
constexpr uint8_t FRAME_MS = 11;        // 10..100 animation frame interval
constexpr uint8_t BRAKE_ANIM = 12;      // 0..6
constexpr uint8_t TURN_ANIM = 13;       // 0..7
constexpr uint8_t REVERSE_ANIM = 14;    // 0..3
constexpr uint8_t RUN_ANIM = 15;        // 0..5
constexpr uint8_t LENS_PRESET = 16;     // 0..3
constexpr uint8_t STARTUP_ANIM = 17;    // 0..1
constexpr uint8_t REST_MODE = 18;       // 0..1
constexpr uint8_t SHOW_SPEED = 19;      // 50..200 %
constexpr uint8_t SHOW_ANIM = 20;       // 0..TAILLIGHT_SHOW_MAX (without changing show on/off)
constexpr uint8_t SHOW_MODE = 21;       // 0..1, live only: never saved
constexpr uint8_t COUNT = 21;
}  // namespace taillight_setting
namespace taillight_color {
constexpr uint8_t BRAKE = 0;
constexpr uint8_t TURN = 1;
constexpr uint8_t REVERSE = 2;
constexpr uint8_t RUNNING = 3;
constexpr uint8_t COUNT = 4;
}  // namespace taillight_color
namespace taillight_action {
constexpr uint8_t SAVE = 0;             // Persist current settings
constexpr uint8_t REVERT = 1;           // Reload the saved settings
constexpr uint8_t FACTORY_DEFAULTS = 2; // Apply defaults (not saved until SAVE)
constexpr uint8_t REPORT = 3;           // Send every setting, color and the show text
constexpr uint8_t PROFILE_LOAD = 4;     // argument: slot 0..5 (applied, not saved)
constexpr uint8_t PROFILE_SAVE = 5;     // argument: slot 0..5
constexpr uint8_t PROFILE_DELETE = 6;   // argument: slot 0..5
}  // namespace taillight_action
namespace taillight_report {
constexpr uint8_t ACK = 1;      // command, config_ack_status, key/which/action, value u16 BE, revision, schema
constexpr uint8_t SETTING = 2;  // key, value u16 BE, revision, flags
constexpr uint8_t COLOR = 3;    // which, R, G, B, revision, flags
constexpr uint8_t TEXT = 4;     // offset, 6 chars (NUL-padded after the end)
constexpr uint8_t STATUS = 5;   // revision, flags, show_anim, profile slots, phase u16 BE (x16 ms)
}  // namespace taillight_report
namespace taillight_status_flag {
constexpr uint8_t UNSAVED = 1 << 0;
constexpr uint8_t SHOW = 1 << 1;
constexpr uint8_t DEMO = 1 << 2;
constexpr uint8_t CUSTOM = 1 << 3;
constexpr uint8_t OVERRIDE = 1 << 4;
}  // namespace taillight_status_flag
constexpr uint8_t TAILLIGHT_ACK_SAVE_FAILED = 0x04;  // config_ack_status continuation
constexpr uint8_t TAILLIGHT_ACK_NOT_FOUND = 0x05;    // empty profile slot
constexpr uint8_t TAILLIGHT_PROFILE_COUNT = 6;
constexpr uint8_t TAILLIGHT_SHOW_TEXT_MAX = 63;

struct TaillightSettingRange { uint16_t low, high; };
inline bool taillightSettingRange(uint8_t key, TaillightSettingRange& range) {
  static const TaillightSettingRange ranges[taillight_setting::COUNT] = {
      {10, 255}, {5, 35}, {200, 1500}, {0, 1}, {50, 1500}, {0, 1500}, {50, 1500}, {50, 200}, {50, 200},
      {50, 200}, {10, 100}, {0, 6}, {0, 7}, {0, 3}, {0, 5}, {0, 3}, {0, 1}, {0, 1}, {50, 200},
      {0, TAILLIGHT_SHOW_MAX}, {0, 1}};
  if (key < 1 || key > taillight_setting::COUNT) return false;
  range = ranges[key - 1];
  return true;
}
inline CanFrame packTaillightSetting(uint8_t key, uint16_t value) {
  CanFrame frame{};
  frame.id = ID_TAILLIGHT_COMMAND;
  frame.dlc = 4;
  frame.data[0] = taillight_command::SET_SETTING;
  frame.data[1] = key;
  encodeU16BE(value, frame.data[2], frame.data[3]);
  return frame;
}
inline CanFrame packTaillightColor(uint8_t which, uint8_t red, uint8_t green, uint8_t blue) {
  CanFrame frame{};
  frame.id = ID_TAILLIGHT_COMMAND;
  frame.dlc = 5;
  frame.data[0] = taillight_command::SET_COLOR;
  frame.data[1] = which;
  frame.data[2] = red;
  frame.data[3] = green;
  frame.data[4] = blue;
  return frame;
}
// One chunk of up to six characters starting at offset. Send offset 0 first;
// a chunk shorter than six characters (or containing NUL) ends the text.
inline CanFrame packTaillightShowText(uint8_t offset, const char* chunk, uint8_t length) {
  CanFrame frame{};
  frame.id = ID_TAILLIGHT_COMMAND;
  if (length > 6) length = 6;
  frame.dlc = static_cast<uint8_t>(2 + length);
  frame.data[0] = taillight_command::SET_SHOW_TEXT;
  frame.data[1] = offset;
  for (uint8_t i = 0; i < length; ++i) frame.data[2 + i] = static_cast<uint8_t>(chunk[i]);
  return frame;
}
inline CanFrame packTaillightAction(uint8_t action, uint8_t argument = 0) {
  CanFrame frame{};
  frame.id = ID_TAILLIGHT_COMMAND;
  frame.dlc = 3;
  frame.data[0] = taillight_command::SETTINGS_ACTION;
  frame.data[1] = action;
  frame.data[2] = argument;
  return frame;
}
inline CanFrame packTaillightAck(uint8_t command, uint8_t status, uint8_t subject, uint16_t value, uint8_t revision) {
  CanFrame frame{};
  frame.id = ID_TAILLIGHT_STATUS;
  frame.dlc = 8;
  frame.data[0] = taillight_report::ACK;
  frame.data[1] = command;
  frame.data[2] = status;
  frame.data[3] = subject;
  encodeU16BE(value, frame.data[4], frame.data[5]);
  frame.data[6] = revision;
  frame.data[7] = CAN_PROTOCOL_SCHEMA_VERSION;
  return frame;
}
inline CanFrame packTaillightSettingReport(uint8_t key, uint16_t value, uint8_t revision, uint8_t flags) {
  CanFrame frame{};
  frame.id = ID_TAILLIGHT_STATUS;
  frame.dlc = 8;
  frame.data[0] = taillight_report::SETTING;
  frame.data[1] = key;
  encodeU16BE(value, frame.data[2], frame.data[3]);
  frame.data[4] = revision;
  frame.data[5] = flags;
  return frame;
}
inline CanFrame packTaillightColorReport(uint8_t which, uint8_t red, uint8_t green, uint8_t blue, uint8_t revision, uint8_t flags) {
  CanFrame frame{};
  frame.id = ID_TAILLIGHT_STATUS;
  frame.dlc = 8;
  frame.data[0] = taillight_report::COLOR;
  frame.data[1] = which;
  frame.data[2] = red;
  frame.data[3] = green;
  frame.data[4] = blue;
  frame.data[5] = revision;
  frame.data[6] = flags;
  return frame;
}
inline CanFrame packTaillightTextReport(uint8_t offset, const char* text) {
  CanFrame frame{};
  frame.id = ID_TAILLIGHT_STATUS;
  frame.dlc = 8;
  frame.data[0] = taillight_report::TEXT;
  frame.data[1] = offset;
  for (uint8_t i = 0; i < 6 && text[i]; ++i) frame.data[2 + i] = static_cast<uint8_t>(text[i]);
  return frame;
}
// phaseX16: milliseconds since the driver-side animation began, divided by 16.
inline CanFrame packTaillightStatus(uint8_t revision, uint8_t flags, uint8_t showAnim, uint8_t profileSlots, uint16_t phaseX16) {
  CanFrame frame{};
  frame.id = ID_TAILLIGHT_STATUS;
  frame.dlc = 8;
  frame.data[0] = taillight_report::STATUS;
  frame.data[1] = revision;
  frame.data[2] = flags;
  frame.data[3] = showAnim;
  frame.data[4] = profileSlots;
  encodeU16BE(phaseX16, frame.data[5], frame.data[6]);
  return frame;
}
// END FROGDASH ADDITIVE EXTENSION

}  // namespace can_protocol
