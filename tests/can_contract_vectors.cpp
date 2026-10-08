// Host-only wire vectors using the actual shared firmware builders.
#include <cassert>
#include <iomanip>
#include <iostream>
#include "can_contract/can_protocol.h"
#include "can_contract/gateway_protocol.h"
using namespace can_protocol;
void emit(const char* name, const CanFrame& f) {
  std::cout << name << " " << std::hex << f.id << " ";
  for (uint8_t i = 0; i < f.dlc; ++i) std::cout << std::setw(2) << std::setfill('0') << unsigned(f.data[i]);
  std::cout << "\n";
}
int main() {
  static_assert(CAN_BITRATE == 500000 && CAN_PROTOCOL_SCHEMA_VERSION == 2, "Existing bus/schema changed");
  TaillightState lights{};
  lights.left_state=5; lights.right_state=1; lights.driver_input_flags=5; lights.passenger_input_flags=2;
  lights.brightness=128; lights.die_temp_c=70; lights.thermal_derate=16;
  emit("lights", packTaillightState(lights));
  EngineMethState meth{};
  meth.meth_state=2; meth.pump_duty=50; meth.tank_level=100; meth.flow_status=1;
  meth.boost_kpa=85; meth.iat_c=-10; meth.engine_bay_c=40;
  emit("meth", packEngineMethState(meth));
  EngineSensorExt sensors{};
  sensors.oil_pressure_psi_x2=125; sensors.fuel_pressure_psi_x2=79;
  sensors.ambient_temp_c=20; sensors.cabin_temp_c=25; sensors.analog_fault_flags=256;
  emit("sensors", packEngineSensorExt(sensors));
  EngineRuntime runtime{}; runtime.rpm=3450; runtime.map_kpa=100; runtime.valid_flags=3;
  emit("runtime", packEngineRuntime(runtime));
  EngineKnockState knock{}; knock.status_flags=19; knock.energy=20; knock.baseline=15;
  knock.threshold=180; knock.event_count=3; knock.last_event_rpm_div100=34; knock.last_event_boost_kpa=85;
  emit("knock", packEngineKnockState(knock));
  KnockLiveHook hook{}; hook.flags=3; hook.live_knock_rms=20; hook.adaptive_threshold=80;
  hook.adaptive_baseline=12; hook.event_count=4; hook.bias_adc_div16=32; hook.raw_adc_div16=40; hook.envelope_level=10;
  emit("hook", packKnockLiveHook(hook));
  KnockConfigPage1 p1{}; p1.config_flags=1; p1.threshold_offset=20; p1.adaptive_multiplier_x10=24;
  p1.min_rpm_div100=15; p1.min_map_kpa=80; p1.debounce_ms_div10=3; p1.gain_x10=10; p1.center_frequency_div100=65;
  emit("knock_config1", packKnockConfigPage1(p1));
  KnockConfigPage2 p2{}; p2.bandwidth_div100=15; p2.sample_rate_div100=200; p2.samples_per_update=64;
  p2.bias_alpha_x1000=10; p2.rms_alpha_x100=20; p2.envelope_alpha_x100=30; p2.bore_mm=87;
  emit("knock_config2", packKnockConfigPage2(p2));
  MethConfigBroadcast config{}; config.version=7; config.desired_armed=1; config.ratio_percent=50;
  config.boost_trigger_kpa=114; config.iat_threshold_offset40=90; config.max_pump_duty=100; config.failsafe_flags=3;
  emit("meth_config", packMethConfigBroadcast(config));
  emit("meth_config_ack", packMethConfigAck(7,0,0,50));
  emit("command_ack", packConfigAck(0x41,0,20,CAN_PROTOCOL_SCHEMA_VERSION));
  emit("knock_fault", packEngineKnockFault(1,2,3,4));
  emit("meth.arm", packMethArm(true));
  emit("meth.test", packMethManualTest(25));
  emit("meth.stop", packMethStopManualTest());
  emit("meth.boost", packMethSetBoostThreshold(40));
  emit("meth.clear_faults", packMethClearFaults());
  emit("knock.enable", packEngineKnockCommand(knock_command::SET_ENABLE,1));
  emit("knock.threshold", packEngineKnockCommand(knock_command::SET_THRESHOLD_OFFSET,20));
  emit("knock.multiplier", packEngineKnockCommand(knock_command::SET_ADAPTIVE_MULTIPLIER,24));
  // Nano's CLEAR_EVENTS handler accepts the one-byte no-argument command.
  CanFrame clear = packEngineKnockCommand(knock_command::CLEAR_EVENTS_AND_FAULTS); clear.dlc=1;
  emit("knock.clear_events", clear);
  emit("knock.refresh", packEngineKnockConfigRequest());
  emit("lighting.brightness", packTaillightBrightness(128));
  emit("lighting.mode", packTaillightMode(1));
  emit("lighting.show", packTaillightMode(taillight_mode::SHOW, 7));
  emit("lighting.demo", packTaillightMode(taillight_mode::DEMO, 0));
  // Override, clear and custom animations have command IDs but no shared builder;
  // frames follow CustomTaillights canbus.cpp (dd4d971).
  CanFrame taillight{}; taillight.id = ID_TAILLIGHT_COMMAND;
  taillight.dlc = 3; taillight.data[0] = taillight_command::SET_OVERRIDE; taillight.data[1] = 2; taillight.data[2] = 3;
  emit("lighting.override", taillight);
  taillight = CanFrame{}; taillight.id = ID_TAILLIGHT_COMMAND; taillight.dlc = 1; taillight.data[0] = taillight_command::CLEAR_OVERRIDE;
  emit("lighting.clear", taillight);
  taillight = CanFrame{}; taillight.id = ID_TAILLIGHT_COMMAND; taillight.dlc = 6;
  taillight.data[0] = taillight_command::TRIGGER_CUSTOM_ANIMATION; taillight.data[1] = 2; taillight.data[4] = 3; taillight.data[5] = 150;
  emit("lighting.custom", taillight);
  emit("lighting.setting", packTaillightSetting(taillight_setting::TURN_ANIM, 5));
  emit("lighting.color", packTaillightColor(taillight_color::TURN, 0xFF, 0x64, 0x00));
  emit("lighting.text", packTaillightShowText(0, "FOX", 3));
  emit("lighting.action", packTaillightAction(taillight_action::PROFILE_SAVE, 2));
  emit("meth.setting", packMethTuneSetting(meth_tune_setting::MAX_ON_MS, 1500));
  emit("meth.tune_action", packMethTuneAction(meth_tune_action::SAVE));
  emit("meth_tune_ack", packMethTuneAck(meth_tune_command::SET_SETTING, config_ack_status::VALUE_CLAMPED, meth_tune_setting::MAX_ON_MS, 2000, 7));
  emit("meth_tune_setting", packMethTuneSettingReport(meth_tune_setting::MIN_RPM, 2500, 7, meth_tune_flag::UNSAVED));
  emit("meth_tune_status", packMethTuneStatus(7, meth_tune_flag::UNSAVED | meth_tune_flag::PUMP_ON | meth_tune_flag::RPM_OK, meth_hold::DOSE_LIMIT, 1500, 4000));
  static_assert(meth_tune_setting::COUNT == 14 && meth_tune_setting::MAX_DOSE_PCT == 14, "Water/meth tuning keys changed");
  emit("meth_tune_temps", packMethTuneTemps(612, -35, 3));
  emit("meth_tune_temps_pre_only", packMethTuneTemps(612, 0, 1));
  gateway::Light interior; interior.channel = 1; interior.red = interior.green = interior.blue = 255; interior.brightness = 35;
  emit("interior.light", gateway::packLight(interior));
  emit("wheel", packSteeringButtons(steering_button::RIGHT, 255));
  FuelLevelState fuel{}; fuel.percent_x10=500; fuel.status=FuelLevelStatus::VALID;
  CanFrame frame=packFuelLevelState(fuel); emit("fuel",frame);
  FuelLevelState received{}; assert(unpackFuelLevelState(frame,received)); assert(received.percent_x10==500);
  fuel.percent_x10=1001; frame=packFuelLevelState(fuel); assert(frame.data[2]==2); emit("fuel_fault",frame);
  frame.data[2]=3; assert(!unpackFuelLevelState(frame,received));
  frame.data[2]=1; frame.data[0]=0xff; assert(!unpackFuelLevelState(frame,received));
  frame.dlc=2; assert(!unpackFuelLevelState(frame,received));
  fuel.status=FuelLevelStatus::UNAVAILABLE; emit("fuel_unavailable",packFuelLevelState(fuel));
  GpsState gps{}; gps.speed_kph_x10=756; gps.altitude_m=-10; gps.satellites=1;
  gps.fix_type=3; gps.status_flags=0x1b; gps.satellites_in_view=2; emit("gps",packGpsState(gps));
}
