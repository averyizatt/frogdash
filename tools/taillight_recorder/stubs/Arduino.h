// Host stand-in for the few Arduino APIs the CustomTaillights animation code uses.
// The simulated clock is advanced by the recorder; random() is a fixed-seed LCG so
// recordings are reproducible (the car's ESP32 uses a hardware random source).
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cmath>
#include <cctype>
#include <algorithm>
#define IRAM_ATTR
#define PROGMEM
#define F(text) (text)
extern unsigned long recorderMillis;
// Same signatures as FastLED's host platform declarations; defined in recorder.cpp.
extern "C" uint32_t millis();
extern "C" uint32_t micros();
using std::max;
using std::min;
inline uint32_t recorderRandom() {
    static uint32_t state = 0x2545F491u;
    state = state * 1664525u + 1013904223u;
    return state >> 8;
}
inline long random(long high) { return high > 0 ? (long)(recorderRandom() % (uint32_t)high) : 0; }
inline long random(long low, long high) { return high > low ? low + random(high - low) : low; }
template<class T, class L, class H> T constrain(T value, L low, H high) {
    return value < low ? static_cast<T>(low) : (value > high ? static_cast<T>(high) : value);
}
inline long map(long x, long inMin, long inMax, long outMin, long outMax) {
    return (x - inMin) * (outMax - outMin) / (inMax - inMin) + outMin;
}
inline uint8_t pgm_read_byte(const void* p) { return *static_cast<const uint8_t*>(p); }
struct RecorderSerial {
    template<class... A> void print(A...) {}
    template<class... A> void println(A...) {}
    template<class... A> void printf(A...) {}
};
inline RecorderSerial Serial;
