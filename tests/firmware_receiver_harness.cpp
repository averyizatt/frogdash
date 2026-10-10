// The module's real firmware-update receiver, driven over stdin/stdout so the dash's
// Python sender can be tested against it. One answer line per input line.
//   F <16 hex>   a command frame         ->  R <16 hex> <action>   or   -
//   T <ms>       advance the clock        ->  -
//   X            check for an abandoned transfer  ->  EXPIRED or -
// On RESTART the received image is written to --out.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include "can_contract/firmware_update.h"

namespace fw = can_protocol::firmware;

struct Flash {
  std::vector<uint8_t> image;
  uint32_t capacity = 0x330000;
  bool failFinish = false, open = false;
  std::string out;
  bool begin(uint32_t size) { if (size > capacity) return false; image.clear(); open = true; return true; }
  bool write(const uint8_t* data, uint32_t length) { if (!open) return false; image.insert(image.end(), data, data + length); return true; }
  bool finish() {
    open = false;
    if (failFinish) return false;
    if (!out.empty()) { FILE* file = std::fopen(out.c_str(), "wb"); std::fwrite(image.data(), 1, image.size(), file); std::fclose(file); }
    return true;
  }
  void abort() { open = false; image.clear(); }
  bool confirm() { return true; }
};

int main(int argc, char** argv) {
  Flash flash;
  uint32_t build = 0;
  bool trial = false;
  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    if (arg == "--build" && i + 1 < argc) build = static_cast<uint32_t>(std::strtoul(argv[++i], nullptr, 16));
    else if (arg == "--capacity" && i + 1 < argc) flash.capacity = static_cast<uint32_t>(std::strtoul(argv[++i], nullptr, 10));
    else if (arg == "--out" && i + 1 < argc) flash.out = argv[++i];
    else if (arg == "--trial") trial = true;
    else if (arg == "--fail-finish") flash.failFinish = true;
  }
  fw::Receiver<Flash> module(fw::TARGET_GATEWAY, build, flash);
  module.setOnTrial(trial);
  uint32_t now = 1000;
  char line[64];
  static const char* names[] = {"NONE", "STARTED", "RESTART", "CONFIRMED", "STOPPED"};
  while (std::fgets(line, sizeof(line), stdin)) {
    if (line[0] == 'T') { now += static_cast<uint32_t>(std::strtoul(line + 2, nullptr, 10)); std::puts("-"); }
    else if (line[0] == 'X') { std::puts(module.expired(now) ? "EXPIRED" : "-"); }
    else if (line[0] == 'F' && std::strlen(line) >= 18) {
      can_protocol::CanFrame frame{}, reply{};
      frame.id = fw::ID_COMMAND; frame.dlc = 8;
      for (int i = 0; i < 8; ++i) { char byte[3] = {line[2 + i * 2], line[3 + i * 2], 0}; frame.data[i] = static_cast<uint8_t>(std::strtoul(byte, nullptr, 16)); }
      fw::Action action = fw::Action::NONE;
      ++now;
      if (module.handle(frame, reply, now, action)) {
        std::printf("R ");
        for (int i = 0; i < 8; ++i) std::printf("%02x", reply.data[i]);
        std::printf(" %s\n", names[static_cast<int>(action)]);
      } else std::puts("-");
    } else std::puts("?");
    std::fflush(stdout);
  }
  return 0;
}
