#pragma once

#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "can_protocol.h"
#if defined(ESP_PLATFORM)
#include "miniz.h"   // The ESP32's ROM decompressor (esp_rom), for compressed transfers
#endif

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
//   RESTART    86 tt 00 00 00 00 00 00     restart the module (extension 7, October 2026):
//                                          ACK OK, then it restarts 300 ms later, as after
//                                          an update; BUSY while it is in use (a light input
//                                          on, water/meth injecting) or a transfer is open
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
//
// Version 2 (November 2026): bigger blocks, only the missing frames sent again, and
// compression. A module reports its version in INFO; the dash uses version 2 only with a
// module that reports 2 or more, and version 1, above, is still accepted unchanged.
//   BEGIN      81 tt s2 s1 s0 46 57 mm     mm = MODE_LARGE, plus MODE_COMPRESSED (0 = version 1)
//   data       iH iL d0 d1 d2 d3 d4 d5     frame 0..32767 of the block (iH below 0x80), six bytes each
//   BLOCK_END  82 tt bH bL cH cL lH lL     block number, CRC-16 of the bytes sent, how many were sent
//   ACK        02 tt 82 08 fH fL lH lL     MISSING: the first and the last frame that did not
//                                          arrive. The module keeps the rest; the dash sends
//                                          that range again, then BLOCK_END again.
// A block is CHUNK_BYTES of the image (the last one shorter). With MODE_COMPRESSED each block
// is sent as its own zlib stream, which the module unpacks into exactly its share of the
// image, so a damaged block spoils nothing after it. END's CRC-32 is over the image as written.
// INFO's flags carry FLAG_COMPRESSION when the module can unpack.
// ---------------------------------------------------------------------------
namespace can_protocol { namespace firmware {

constexpr uint16_t ID_COMMAND = 0x680;
constexpr uint16_t ID_REPLY = 0x681;
constexpr uint8_t VERSION = 2;

constexpr uint8_t TARGET_GATEWAY = 1;
constexpr uint8_t TARGET_TAILLIGHT = 2;
constexpr uint8_t TARGET_WATER_METH = 3;
// A new module takes the next number here, in the dash's table (fwupdate.py MODULES) and
// in the Pi setup's download list; nothing else about the protocol changes.

constexpr uint8_t COMMAND_FLAG = 0x80;
constexpr uint8_t QUERY = 0x80;
constexpr uint8_t BEGIN = 0x81;
constexpr uint8_t BLOCK_END = 0x82;
constexpr uint8_t END = 0x83;
constexpr uint8_t ABORT = 0x84;
constexpr uint8_t CONFIRM = 0x85;
constexpr uint8_t RESTART = 0x86;

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
constexpr uint8_t STATUS_MISSING = 8;       // Version 2: frames missing from the block; the rest is kept.

constexpr uint8_t FLAG_ON_TRIAL = 1;        // Running a new image that has not been confirmed.
constexpr uint8_t FLAG_UPDATING = 2;        // A transfer is open.
constexpr uint8_t FLAG_COMPRESSION = 4;     // Version 2: takes compressed blocks.

constexpr uint8_t DATA_PER_FRAME = 7;
constexpr uint8_t FRAMES_PER_BLOCK = 64;
constexpr uint16_t BLOCK_BYTES = 448;
constexpr uint8_t MAGIC_0 = 0x46;           // 'F'
constexpr uint8_t MAGIC_1 = 0x57;           // 'W'
constexpr uint32_t IDLE_ABORT_MS = 5000;    // A transfer with no frame for this long is given up.

// Version 2.
constexpr uint8_t MODE_LARGE = 1;
constexpr uint8_t MODE_COMPRESSED = 2;
constexpr uint16_t CHUNK_BYTES = 8192;                       // Image bytes per block
constexpr uint8_t DATA_PER_FRAME_2 = 6;
constexpr uint16_t WIRE_BYTES_MAX = CHUNK_BYTES + 64;        // zlib's most for a block that does not compress
constexpr uint16_t FRAMES_MAX_2 = (WIRE_BYTES_MAX + DATA_PER_FRAME_2 - 1) / DATA_PER_FRAME_2;

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
inline CanFrame packBegin(uint8_t target, uint32_t size, uint8_t mode = 0) {
  CanFrame f = command(BEGIN, target);
  f.data[2] = static_cast<uint8_t>(size >> 16); f.data[3] = static_cast<uint8_t>(size >> 8);
  f.data[4] = static_cast<uint8_t>(size); f.data[5] = MAGIC_0; f.data[6] = MAGIC_1; f.data[7] = mode; return f;
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
// Version 2: frame `index` of a block, six bytes.
inline CanFrame packData2(uint16_t index, const uint8_t* bytes, uint8_t count) {
  CanFrame f{}; f.id = ID_COMMAND; f.dlc = 8;
  f.data[0] = static_cast<uint8_t>((index >> 8) & 0x7F); f.data[1] = static_cast<uint8_t>(index);
  for (uint8_t i = 0; i < DATA_PER_FRAME_2; ++i) f.data[2 + i] = i < count ? bytes[i] : 0xFF;
  return f;
}
// Version 2: the end of a block of `length` bytes as sent.
inline CanFrame packBlockEnd2(uint8_t target, uint16_t block, uint16_t crc, uint16_t length) {
  CanFrame f = command(BLOCK_END, target);
  encodeU16BE(block, f.data[2], f.data[3]); encodeU16BE(crc, f.data[4], f.data[5]);
  encodeU16BE(length, f.data[6], f.data[7]); return f;
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
// Version 2: frames first..last of the block did not all arrive.
inline CanFrame packMissing(uint8_t target, uint16_t first, uint16_t last) {
  CanFrame f = packAck(target, BLOCK_END, STATUS_MISSING, first);
  encodeU16BE(last, f.data[6], f.data[7]); return f;
}

// Unpacking a compressed block: `in` must be one whole zlib stream that unpacks to exactly
// `outLength` bytes. A module without it is not offered compressed transfers.
struct NoInflate {
  static constexpr bool kAvailable = false;
  bool begin() { return false; }
  void end() {}
  bool unpack(const uint8_t*, uint32_t, uint8_t*, uint32_t) { return false; }
};
#if defined(ESP_PLATFORM)
// The decompressor in the ESP32's ROM: no flash used. Its state (about 11 KB) is taken from
// the heap for the transfer only, never the stack: the loop task's stack is 8 KB.
struct RomInflate {
  static constexpr bool kAvailable = true;
  bool begin() {
    state_ = static_cast<tinfl_decompressor*>(malloc(sizeof(tinfl_decompressor)));
    return state_ != nullptr;
  }
  void end() { free(state_); state_ = nullptr; }
  bool unpack(const uint8_t* in, uint32_t inLength, uint8_t* out, uint32_t outLength) {
    if (!state_) return false;
    tinfl_init(state_);
    size_t inBytes = inLength, outBytes = outLength;
    const tinfl_status status = tinfl_decompress(state_, in, &inBytes, out, out, &outBytes,
                                                 TINFL_FLAG_PARSE_ZLIB_HEADER | TINFL_FLAG_USING_NON_WRAPPING_OUTPUT_BUF);
    return status == TINFL_STATUS_DONE && outBytes == outLength;
  }
 private:
  tinfl_decompressor* state_ = nullptr;
};
#endif

// What the module should do after handling a frame.
enum class Action : uint8_t { NONE, STARTED, RESTART, CONFIRMED, STOPPED };

// The module's side of the transfer. Flash supplies:
//   bool begin(uint32_t size);  bool write(const uint8_t* data, uint32_t length);
//   bool finish();              void abort();
//   bool confirm();             makes the running image permanent
// Inflate unpacks compressed blocks (RomInflate on an ESP32). A version 2 transfer takes
// about 16 KB from the heap (plus Inflate's) while it runs, and gives it back after.
template <class Flash, class Inflate = NoInflate>
class Receiver {
 public:
  Receiver(uint8_t target, uint32_t build, Flash& flash) : target_(target), build_(build), flash_(flash) {}
  ~Receiver() { release(); }
  Receiver(const Receiver&) = delete;
  Receiver& operator=(const Receiver&) = delete;

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
      if (!active_) return false;
      if (large_) {
        const uint16_t index = static_cast<uint16_t>((op << 8) | in.data[1]);
        if (index >= FRAMES_MAX_2) return false;
        memcpy(wire_ + index * DATA_PER_FRAME_2, in.data + 2, DATA_PER_FRAME_2);
        mark(index);
      } else {
        if (op >= FRAMES_PER_BLOCK) return false;
        memcpy(buffer_ + op * DATA_PER_FRAME, in.data + 1, DATA_PER_FRAME);
        mark(op);
      }
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
        release();
        if (size == 0) { reply = packAck(target_, BEGIN, STATUS_TOO_LARGE); return true; }
        const uint8_t mode = in.data[7];
        const bool large = (mode & MODE_LARGE) != 0, compressed = (mode & MODE_COMPRESSED) != 0;
        if ((mode & ~(MODE_LARGE | MODE_COMPRESSED)) || (compressed && (!large || !Inflate::kAvailable))) {
          reply = packAck(target_, BEGIN, STATUS_BAD_STATE);
          return true;
        }
        if (large && !reserve(compressed)) { release(); reply = packAck(target_, BEGIN, STATUS_TOO_LARGE); return true; }
        if (!flash_.begin(size)) { release(); reply = packAck(target_, BEGIN, STATUS_TOO_LARGE); return true; }
        large_ = large; compressed_ = compressed;
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
        if (large_) return blockEnd2(in, reply, action);
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
        release();
        if (!flash_.finish()) {              // The image's own checksum, and selecting it for the next start.
          action = Action::STOPPED;
          reply = packAck(target_, END, STATUS_CHECK_FAILED);
          return true;
        }
        action = Action::RESTART;
        reply = packAck(target_, END, STATUS_OK);
        return true;
      }
      case RESTART:
        // The module's own check (in use?) comes before this and answers BUSY itself.
        if (active_) { reply = packAck(target_, RESTART, STATUS_BUSY); return true; }
        action = Action::RESTART;
        reply = packAck(target_, RESTART, STATUS_OK);
        return true;
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
    return static_cast<uint8_t>((onTrial_ ? FLAG_ON_TRIAL : 0) | (active_ ? FLAG_UPDATING : 0) |
                                (Inflate::kAvailable ? FLAG_COMPRESSION : 0));
  }
  void clearBlock() { memset(have_, 0, sizeof(have_)); }
  void mark(uint16_t index) { have_[index >> 3] = static_cast<uint8_t>(have_[index >> 3] | (1U << (index & 7))); }
  bool has(uint16_t index) const { return (have_[index >> 3] & (1U << (index & 7))) != 0; }
  bool complete(uint8_t frames) const {
    for (uint8_t i = 0; i < frames; ++i) if (!has(i)) return false;
    return true;
  }
  void stop() { flash_.abort(); active_ = false; clearBlock(); release(); }

  // Version 2's buffers, for the transfer only.
  bool reserve(bool compressed) {
    wire_ = static_cast<uint8_t*>(malloc(static_cast<size_t>(FRAMES_MAX_2) * DATA_PER_FRAME_2));
    if (!wire_) return false;
    if (!compressed) return true;
    out_ = static_cast<uint8_t*>(malloc(CHUNK_BYTES));
    inflating_ = out_ != nullptr && inflate_.begin();
    return inflating_;
  }
  void release() {
    free(wire_); wire_ = nullptr;
    free(out_); out_ = nullptr;
    if (inflating_) inflate_.end();
    inflating_ = false; large_ = compressed_ = false;
  }

  bool blockEnd2(const CanFrame& in, CanFrame& reply, Action& action) {
    const uint16_t block = decodeU16BE(in.data[2], in.data[3]);
    const uint16_t crc = decodeU16BE(in.data[4], in.data[5]);
    const uint16_t length = decodeU16BE(in.data[6], in.data[7]);
    if (static_cast<uint16_t>(block + 1) == block_) {   // Our answer was lost: it is already written.
      clearBlock();
      reply = packAck(target_, BLOCK_END, STATUS_OK, block);
      return true;
    }
    const uint32_t left = size_ - written_;
    const uint32_t expected = left < CHUNK_BYTES ? left : CHUNK_BYTES;
    if (block != block_ || expected == 0 || length == 0 || length > WIRE_BYTES_MAX || (!compressed_ && length != expected)) {
      clearBlock();
      reply = packAck(target_, BLOCK_END, STATUS_BAD_STATE, block_);
      return true;
    }
    const uint16_t frames = static_cast<uint16_t>((length + DATA_PER_FRAME_2 - 1) / DATA_PER_FRAME_2);
    uint16_t first = frames, last = 0;
    for (uint16_t i = 0; i < frames; ++i) {
      if (has(i)) continue;
      if (first == frames) first = i;
      last = i;
    }
    if (first != frames) {                   // Keep what arrived; ask for the gap.
      reply = packMissing(target_, first, last);
      return true;
    }
    if (crc16(wire_, length) != crc) {
      clearBlock();
      reply = packAck(target_, BLOCK_END, STATUS_RESEND, block);
      return true;
    }
    const uint8_t* image = wire_;
    if (compressed_) {
      // The bytes arrived as sent (the CRC matched), so a block that does not unpack to
      // its share of the image never will: the transfer is called off.
      if (!inflate_.unpack(wire_, length, out_, expected)) {
        stop();
        action = Action::STOPPED;
        reply = packAck(target_, BLOCK_END, STATUS_CHECK_FAILED, block);
        return true;
      }
      image = out_;
    }
    if (!flash_.write(image, expected)) {
      stop();
      action = Action::STOPPED;
      reply = packAck(target_, BLOCK_END, STATUS_FLASH_ERROR, block);
      return true;
    }
    crc_ = crc32(image, expected, crc_);
    written_ += expected; ++block_;
    clearBlock();
    reply = packAck(target_, BLOCK_END, STATUS_OK, block);
    return true;
  }

  uint8_t target_;
  uint32_t build_;
  Flash& flash_;
  Inflate inflate_;
  bool active_ = false, onTrial_ = false, large_ = false, compressed_ = false, inflating_ = false;
  uint32_t size_ = 0, written_ = 0, crc_ = 0, lastMs_ = 0;
  uint16_t block_ = 0;
  uint8_t buffer_[BLOCK_BYTES];
  uint8_t* wire_ = nullptr;   // Version 2: the block as sent
  uint8_t* out_ = nullptr;    // Version 2, compressed: the block unpacked
  uint8_t have_[(FRAMES_MAX_2 + 7) / 8];
};

}} // namespace can_protocol::firmware
