#pragma once

#include "can_protocol.h"

// Additive schema-2 extension. Existing dashboard/module frames are unchanged.
namespace can_protocol { namespace gateway {
constexpr uint16_t SENSOR_STATE = 0x500;
constexpr uint16_t BUTTON_STATE = 0x501;
constexpr uint16_t LIGHT_COMMAND = 0x502;
constexpr uint16_t LIGHT_STATE = 0x503;
constexpr uint8_t VERSION = 1;
constexpr uint8_t VSS_VALID = 1;
constexpr uint8_t RPM_VALID = 2;
constexpr uint8_t FUEL_VALID = 4;

inline CanFrame packTach(uint16_t rpm, uint8_t pulsesPerRev10, bool live) {
  CanFrame f{}; f.id = ID_TACH_RPM_STATE; f.dlc = 8;
  encodeU16BE(rpm, f.data[0], f.data[1]);
  // B2/B3 are generated tach Hz x10: zero because this build has no output.
  f.data[4] = static_cast<uint8_t>(TachSource::GPIO_INPUT);
  f.data[5] = live ? 1 : 2;
  f.data[6] = pulsesPerRev10; return f;
}

struct Sensors {
  uint16_t speedKph10 = 0;
  uint16_t rpm = 0;
  uint16_t fuelRaw = 0;
  uint8_t fuelPercent = 255; // 255 = uncalibrated/unavailable
  uint8_t valid = 0;
};
inline CanFrame packSensors(const Sensors& s) {
  CanFrame f{}; f.id = SENSOR_STATE; f.dlc = 8;
  encodeU16BE(s.speedKph10, f.data[0], f.data[1]);
  encodeU16BE(s.rpm, f.data[2], f.data[3]);
  encodeU16BE(s.fuelRaw, f.data[4], f.data[5]);
  f.data[6] = s.fuelPercent; f.data[7] = s.valid;
  return f;
}
inline bool unpackSensors(const CanFrame& f, Sensors& s) {
  if (f.id != SENSOR_STATE || f.dlc != 8 || (f.data[7] & ~7U) ||
      (f.data[6] > 100 && f.data[6] != 255)) return false;
  s = {decodeU16BE(f.data[0], f.data[1]), decodeU16BE(f.data[2], f.data[3]),
       decodeU16BE(f.data[4], f.data[5]), f.data[6], f.data[7]};
  return true;
}
constexpr uint8_t BUTTON_ON = 1U << 0;
constexpr uint8_t BUTTON_OFF = 1U << 1;
constexpr uint8_t BUTTON_COAST = 1U << 2;
constexpr uint8_t BUTTON_SET_ACCEL = 1U << 3;
constexpr uint8_t BUTTON_RESUME = 1U << 4;
struct Buttons {
  uint8_t pressed = 0; // bits 0..4; 1 = held
  uint8_t enabled = 0;
  uint8_t sequence = 0; // increments on stable state changes, wraps at 255
};
inline CanFrame packButtons(const Buttons& b) {
  CanFrame f{}; f.id = BUTTON_STATE; f.dlc = 4;
  f.data[0] = b.pressed & 31; f.data[1] = b.enabled & 31;
  f.data[2] = b.sequence; f.data[3] = VERSION; return f;
}
inline bool unpackButtons(const CanFrame& f, Buttons& b) {
  if (f.id != BUTTON_STATE || f.dlc != 4 || f.data[3] != VERSION ||
      (f.data[0] & ~31U) || (f.data[1] & ~31U) || (f.data[0] & ~f.data[1])) return false;
  b = {f.data[0], f.data[1], f.data[2]}; return true;
}
struct Light {
  uint8_t channel = 0; // 0 = both, 1 = upper, 2 = lower
  uint8_t red = 0, green = 0, blue = 0, brightness = 0;
};
inline CanFrame packLight(const Light& l) {
  CanFrame f{}; f.id = LIGHT_COMMAND; f.dlc = 6;
  f.data[0] = l.channel; f.data[1] = l.red; f.data[2] = l.green;
  f.data[3] = l.blue; f.data[4] = l.brightness; f.data[5] = VERSION;
  return f;
}
inline bool unpackLight(const CanFrame& f, Light& l) {
  if (f.id != LIGHT_COMMAND || f.dlc != 6 || f.data[0] > 2 || f.data[5] != VERSION) return false;
  l = {f.data[0], f.data[1], f.data[2], f.data[3], f.data[4]}; return true;
}
}} // namespace can_protocol::gateway
