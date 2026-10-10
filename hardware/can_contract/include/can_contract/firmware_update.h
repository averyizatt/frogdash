#pragma once

#include <stdint.h>
#include <string.h>
#include "can_protocol.h"

// ---------------------------------------------------------------------------
// Firmware update over CAN. Additive: two IDs in the block reserved for future
// use; no existing message changes, and modules without this simply ignore them.
//
//   0x680  dash -> module   commands, and the firmware itself
//   0x681  module -> dash   information and acknowledgements
//
// Not 0x600/0x601: the MicroSquirt's real-time broadcast owns 0x5F0-0x62F (base
// 1520, up to 64 groups), and a transfer must never share an ID with the ECU.
//
// A module acts only on commands that name it (byte 1 = target) and on data
// frames while it has a transfer open. Only one transfer runs at a time.
//
// 0x680, DLC 8. Bit 7 of byte 0 separates commands from data:
//   QUERY      80 tt 00 00 00 00 00 00
//   BEGIN      81 tt s2 s1 s0 46 57 00     size (24 bit, big endian), then "FW"
//   data       ii d0 d1 d2 d3 d4 d5 d6     ii = 0..63, the frame's place in the block
//   BLOCK_END  82 tt bH bL cH cL nn 00     block number, CRC-16 of its bytes, frames sent
//   END        83 tt c3 c2 c1 c0 00 00     CRC-32 of the whole image
//   ABORT      84 tt 00 00 00 00 00 00
//   CONFIRM    85 tt b3 b2 b1 b0 00 00     the build the dash expects to be running
//
// 0x681, DLC 8:
//   INFO       01 tt b3 b2 b1 b0 ff vv     build, flags, protocol version
//   ACK        02 tt op st vH vL 00 00     command answered, status, value (block number)
//
// The image goes in blocks of 64 frames (448 bytes). The module writes a block to
// flash only when every frame arrived and the CRC-16 matches, and answers each
// BLOCK_END; RESEND asks for the same block again. Nothing arrives while it is
// writing, because the dash waits for the answer. END checks the CRC-32 of
// everything written and the image's own checksum before the module restarts
// into it. The new firmware stays "on trial" until the dash sends CONFIRM: if
// that does not come, the module goes back to the firmware it had.
// ---------------------------------------------------------------------------
namespace can_protocol { namespace firmware {

constexpr uint16_t ID_COMMAND = 0x680;
constexpr uint16_t ID_REPLY = 0x681;
constexpr uint8_t VERSION = 1;

constexpr uint8_t TARGET_GATEWAY = 1;
constexpr uint8_t TARGET_TAILLIGHT = 2;
// A new module takes the next number here, in the dash's table (fwupdate.py MODULES) and
// in the Pi setup's download list; nothing else about the protocol changes.

constexpr uint8_t COMMAND_FLAG = 0x80;
constexpr uint8_t QUERY = 0x80;
constexpr uint8_t BEGIN = 0x81;
constexpr uint8_t BLOCK_END = 0x82;
constexpr uint8_t END = 0x83;
constexpr uint8_t ABORT = 0x84;
constexpr uint8_t CONFIRM = 0x85;

constexpr uint8_t INFO = 1;
constexpr uint8_t ACK = 2;

constexpr uint8_t STATUS_OK = 0;
constexpr uint8_t STATUS_RESEND = 1;        // Block incomplete or damaged: send it again.
constexpr uint8_t STATUS_BAD_STATE = 2;     // Not expected now (no transfer open, wrong block).
constexpr uint8_t STATUS_TOO_LARGE = 3;
constexpr uint8_t STATUS_FLASH_ERROR = 4;
constexpr uint8_t STATUS_CHECK_FAILED = 5;  // Whole-image CRC or the image's own checksum.
constexpr uint8_t STATUS_WRONG_BUILD = 6;   // CONFIRM named a build that is not the one running.
constexpr uint8_t STATUS_BUSY = 7;          // The module is in use and will not update now (a light input is on).

constexpr uint8_t FLAG_ON_TRIAL = 1;        // Running a new image that has not been confirmed.
constexpr uint8_t FLAG_UPDATING = 2;        // A transfer is open.

constexpr uint8_t DATA_PER_FRAME = 7;
constexpr uint8_t FRAMES_PER_BLOCK = 64;
constexpr uint16_t BLOCK_BYTES = 448;
constexpr uint8_t MAGIC_0 = 0x46;           // 'F'
constexpr uint8_t MAGIC_1 = 0x57;           // 'W'
constexpr uint32_t IDLE_ABORT_MS = 5000;    // A transfer with no frame for this long is given up.

// CRC-16/CCITT-FALSE: polynomial 0x1021, start 0xFFFF.
inline uint16_t crc16(const uint8_t* data, uint32_t length, uint16_t crc = 0xFFFF) {
  for (uint32_t i = 0; i < length; ++i) {
    crc = static_cast<uint16_t>(crc ^ (static_cast<uint16_t>(data[i]) << 8));
    for (uint8_t bit = 0; bit < 8; ++bit) {
      crc = static_cast<uint16_t>((crc & 0x8000) ? ((crc << 1) ^ 0x1021) : (crc << 1));
    }
  }
  return crc;
}

// CRC-32 as zlib computes it. Start with 0; pass the previous result to continue.
inline uint32_t crc32(const uint8_t* data, uint32_t length, uint32_t crc = 0) {
  crc = ~crc;
  for (uint32_t i = 0; i < length; ++i) {
    crc ^= data[i];
    for (uint8_t bit = 0; bit < 8; ++bit) crc = (crc & 1) ? ((crc >> 1) ^ 0xEDB88320UL) : (crc >> 1);
  }
  return ~crc;
}

inline CanFrame command(uint8_t op, uint8_t target) {
  CanFrame f{}; f.id = ID_COMMAND; f.dlc = 8; f.data[0] = op; f.data[1] = target; return f;
}
inline CanFrame packQuery(uint8_t target) { return command(QUERY, target); }
inline CanFrame packBegin(uint8_t target, uint32_t size) {
  CanFrame f = command(BEGIN, target);
  f.data[2] = static_cast<uint8_t>(size >> 16); f.data[3] = static_cast<uint8_t>(size >> 8);
  f.data[4] = static_cast<uint8_t>(size); f.data[5] = MAGIC_0; f.data[6] = MAGIC_1; return f;
}
inline CanFrame packData(uint8_t index, const uint8_t* bytes, uint8_t count) {
  CanFrame f{}; f.id = ID_COMMAND; f.dlc = 8; f.data[0] = index & 0x7F;
  for (uint8_t i = 0; i < DATA_PER_FRAME; ++i) f.data[1 + i] = i < count ? bytes[i] : 0xFF;
  return f;
}
inline CanFrame packBlockEnd(uint8_t target, uint16_t block, uint16_t crc, uint8_t frames) {
  CanFrame f = command(BLOCK_END, target);
  encodeU16BE(block, f.data[2], f.data[3]); encodeU16BE(crc, f.data[4], f.data[5]);
  f.data[6] = frames; return f;
}
inline void putU32(uint32_t value, uint8_t* out) {
  out[0] = static_cast<uint8_t>(value >> 24); out[1] = static_cast<uint8_t>(value >> 16);
  out[2] = static_cast<uint8_t>(value >> 8); out[3] = static_cast<uint8_t>(value);
}
inline uint32_t getU32(const uint8_t* in) {
  return (static_cast<uint32_t>(in[0]) << 24) | (static_cast<uint32_t>(in[1]) << 16) |
         (static_cast<uint32_t>(in[2]) << 8) | in[3];
}
inline CanFrame packEnd(uint8_t target, uint32_t crc) {
  CanFrame f = command(END, target); putU32(crc, f.data + 2); return f;
}
inline CanFrame packAbort(uint8_t target) { return command(ABORT, target); }
inline CanFrame packConfirm(uint8_t target, uint32_t build) {
  CanFrame f = command(CONFIRM, target); putU32(build, f.data + 2); return f;
}
inline CanFrame packInfo(uint8_t target, uint32_t build, uint8_t flags) {
  CanFrame f{}; f.id = ID_REPLY; f.dlc = 8; f.data[0] = INFO; f.data[1] = target;
  putU32(build, f.data + 2); f.data[6] = flags; f.data[7] = VERSION; return f;
}
inline CanFrame packAck(uint8_t target, uint8_t op, uint8_t status, uint16_t value = 0) {
  CanFrame f{}; f.id = ID_REPLY; f.dlc = 8; f.data[0] = ACK; f.data[1] = target;
  f.data[2] = op; f.data[3] = status; encodeU16BE(value, f.data[4], f.data[5]); return f;
}

// What the module should do after handling a frame.
enum class Action : uint8_t { NONE, STARTED, RESTART, CONFIRMED, STOPPED };

// The module's side of the transfer. Flash supplies:
//   bool begin(uint32_t size);  bool write(const uint8_t* data, uint32_t length);
//   bool finish();              void abort();
//   bool confirm();             makes the running image permanent
template <class Flash>
class Receiver {
 public:
  Receiver(uint8_t target, uint32_t build, Flash& flash) : target_(target), build_(build), flash_(flash) {}

  bool active() const { return active_; }
  void setOnTrial(bool value) { onTrial_ = value; }
  bool onTrial() const { return onTrial_; }
  uint32_t received() const { return written_; }
  uint32_t size() const { return size_; }

  // True when `reply` should be sent. `action` tells the module what changed.
  bool handle(const CanFrame& in, CanFrame& reply, uint32_t nowMs, Action& action) {
    action = Action::NONE;
    if (in.id != ID_COMMAND || in.dlc != 8) return false;
    const uint8_t op = in.data[0];
    if (!(op & COMMAND_FLAG)) {             // Data: only while a transfer is open.
      if (!active_ || op >= FRAMES_PER_BLOCK) return false;
      memcpy(buffer_ + op * DATA_PER_FRAME, in.data + 1, DATA_PER_FRAME);
      have_[op >> 3] = static_cast<uint8_t>(have_[op >> 3] | (1U << (op & 7)));
      lastMs_ = nowMs;
      return false;
    }
    if (in.data[1] != target_) return false;
    switch (op) {
      case QUERY:
        reply = packInfo(target_, build_, flags());
        return true;
      case BEGIN: {
        const uint32_t size = (static_cast<uint32_t>(in.data[2]) << 16) |
                              (static_cast<uint32_t>(in.data[3]) << 8) | in.data[4];
        if (in.data[5] != MAGIC_0 || in.data[6] != MAGIC_1) return false;   // Not a real request.
        if (active_) { flash_.abort(); active_ = false; }
        if (size == 0) { reply = packAck(target_, BEGIN, STATUS_TOO_LARGE); return true; }
        if (!flash_.begin(size)) { reply = packAck(target_, BEGIN, STATUS_TOO_LARGE); return true; }
        active_ = true; size_ = size; written_ = 0; block_ = 0; crc_ = 0; lastMs_ = nowMs;
        clearBlock();
        action = Action::STARTED;
        reply = packAck(target_, BEGIN, STATUS_OK);
        return true;
      }
      case BLOCK_END: {
        const uint16_t block = decodeU16BE(in.data[2], in.data[3]);
        const uint16_t crc = decodeU16BE(in.data[4], in.data[5]);
        const uint8_t frames = in.data[6];
        if (!active_) { reply = packAck(target_, BLOCK_END, STATUS_BAD_STATE, block); return true; }
        lastMs_ = nowMs;
        if (static_cast<uint16_t>(block + 1) == block_) {   // Our answer was lost: it is already written.
          clearBlock();
          reply = packAck(target_, BLOCK_END, STATUS_OK, block);
          return true;
        }
        const uint32_t left = size_ - written_;
        const uint32_t length = left < BLOCK_BYTES ? left : BLOCK_BYTES;
        const uint8_t expected = static_cast<uint8_t>((length + DATA_PER_FRAME - 1) / DATA_PER_FRAME);
        if (block != block_ || length == 0 || frames != expected) {
          clearBlock();
          reply = packAck(target_, BLOCK_END, STATUS_BAD_STATE, block_);
          return true;
        }
        if (!complete(expected) || crc16(buffer_, length) != crc) {
          clearBlock();
          reply = packAck(target_, BLOCK_END, STATUS_RESEND, block);
          return true;
        }
        if (!flash_.write(buffer_, length)) {
          stop();
          action = Action::STOPPED;
          reply = packAck(target_, BLOCK_END, STATUS_FLASH_ERROR, block);
          return true;
        }
        crc_ = crc32(buffer_, length, crc_);
        written_ += length; ++block_;
        clearBlock();
        reply = packAck(target_, BLOCK_END, STATUS_OK, block);
        return true;
      }
      case END: {
        if (!active_) { reply = packAck(target_, END, STATUS_BAD_STATE); return true; }
        const bool whole = written_ == size_ && getU32(in.data + 2) == crc_;
        if (!whole) {
          stop();
          action = Action::STOPPED;
          reply = packAck(target_, END, STATUS_CHECK_FAILED);
          return true;
        }
        active_ = false;
        if (!flash_.finish()) {              // The image's own checksum, and selecting it for the next start.
          action = Action::STOPPED;
          reply = packAck(target_, END, STATUS_CHECK_FAILED);
          return true;
        }
        action = Action::RESTART;
        reply = packAck(target_, END, STATUS_OK);
        return true;
      }
      case ABORT:
        if (active_) { stop(); action = Action::STOPPED; }
        reply = packAck(target_, ABORT, STATUS_OK);
        return true;
      case CONFIRM:
        if (getU32(in.data + 2) != build_) { reply = packAck(target_, CONFIRM, STATUS_WRONG_BUILD); return true; }
        if (onTrial_) {
          if (!flash_.confirm()) { reply = packAck(target_, CONFIRM, STATUS_FLASH_ERROR); return true; }
          onTrial_ = false;
          action = Action::CONFIRMED;
        }
        reply = packAck(target_, CONFIRM, STATUS_OK);
        return true;
      default:
        return false;
    }
  }

  // The module itself calls a transfer off (its real work is needed). The running firmware is kept.
  void cancel() { if (active_) stop(); }

  // Call regularly. True when a transfer was given up because the dash went quiet.
  bool expired(uint32_t nowMs) {
    if (!active_ || static_cast<uint32_t>(nowMs - lastMs_) < IDLE_ABORT_MS) return false;
    stop();
    return true;
  }

 private:
  uint8_t flags() const {
    return static_cast<uint8_t>((onTrial_ ? FLAG_ON_TRIAL : 0) | (active_ ? FLAG_UPDATING : 0));
  }
  void clearBlock() { memset(have_, 0, sizeof(have_)); }
  bool complete(uint8_t frames) const {
    for (uint8_t i = 0; i < frames; ++i) if (!(have_[i >> 3] & (1U << (i & 7)))) return false;
    return true;
  }
  void stop() { flash_.abort(); active_ = false; clearBlock(); }

  uint8_t target_;
  uint32_t build_;
  Flash& flash_;
  bool active_ = false, onTrial_ = false;
  uint32_t size_ = 0, written_ = 0, crc_ = 0, lastMs_ = 0;
  uint16_t block_ = 0;
  uint8_t buffer_[BLOCK_BYTES];
  uint8_t have_[FRAMES_PER_BLOCK / 8];
};

}} // namespace can_protocol::firmware
