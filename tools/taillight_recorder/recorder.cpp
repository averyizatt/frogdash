// Records CustomTaillights animation frames by running the unmodified firmware
// animation code on the host with FastLED 3.10.3 and a simulated clock.
//
// Output (little-endian, one file): for every clip, frames of both lamps.
// Each lamp frame is 590 bytes in physical wiring order: the clear top strip as
// RGB (105 x 3) followed by the red-diffused bottom strip and main panel as red
// only (275 x 1). A JSON index describes the clips. See build.py.
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "taillight.h"
#include "settings.h"
#include "animations.h"

unsigned long recorderMillis = 0;
extern "C" uint32_t millis() { return static_cast<uint32_t>(recorderMillis); }
extern "C" uint32_t micros() { return static_cast<uint32_t>(recorderMillis * 1000UL); }
// font5x.cpp's hardware self-test references the LED output layer; it is never called here.
extern "C" void delay(int) {}
void ledOutputShow(bool) {}
void ledOutputClear(bool, bool) {}

namespace {
constexpr int FPS = 20;
constexpr int CAPTURE_MS = 1000 / FPS;
constexpr int TOP_RGB = STRIP_LEDS * 3;
constexpr int RED_ONLY = LEDS_PER_SIDE - STRIP_LEDS;
constexpr int LAMP_BYTES = TOP_RGB + RED_ONLY;

struct Clip {
    std::string name, title, group;
    LightState driver, passenger;
    int seconds;
    int showAnim = -1;    // SHOW clips
    int turnAnim = -1;    // -1 keeps the firmware default
};

struct Lamp {
    CRGB buffer[LEDS_PER_SIDE];
    TailLight light;
    explicit Lamp(bool driver) : light(buffer, driver) { std::memset(buffer, 0, sizeof buffer); }
    void append(std::vector<uint8_t>& out) const {
        for (int i = 0; i < STRIP_LEDS; ++i) { out.push_back(buffer[i].r); out.push_back(buffer[i].g); out.push_back(buffer[i].b); }
        for (int i = STRIP_LEDS; i < LEDS_PER_SIDE; ++i) out.push_back(buffer[i].r);
    }
};

std::string escape(const std::string& text) {
    std::string out;
    for (char c : text) { if (c == '"' || c == '\\') out += '\\'; out += c; }
    return out;
}
}  // namespace

int main(int argc, char** argv) {
    if (argc != 3) { std::fprintf(stderr, "usage: recorder OUT.bin OUT.json\n"); return 2; }
    settings_load();  // Preferences stub is empty, so these are the firmware defaults.
    AnimationRegistry::init();
    const Settings defaults = g_settings;

    static const char* SHOW_NAMES[] = {
        "Rainbow", "Chase", "Theater", "Fire", "Meteor", "Police", "Night Rider", "Color Cycle",
        "Sparkle", "Plasma", "Matrix", "Juggle", "BPM", "Confetti", "Ocean", "Lightning",
        "Heartbeat", "Ripple", "Sunrise", "Text Scroll", "Colorwaves", "TwinkleFox", "Bouncing Balls",
        "Fireworks", "Drip", "Cylon Dual", "V8", "Drag Launch", "Neon", "Speed Streaks", "Radar",
        "Aurora", "Glitch"};
    std::vector<Clip> clips;
    for (int i = 0; i < can_protocol::TAILLIGHT_SHOW_COUNT; ++i)
        clips.push_back({"show-" + std::to_string(i), SHOW_NAMES[i], "show", LightState::SHOW, LightState::SHOW, 10, i});
    using S = LightState;
    for (auto [suffix, anim] : {std::pair{"seq", 0}, std::pair{"stock", 1}}) {
        const std::string tag = suffix;
        clips.push_back({"turn-left-" + tag, "Left turn", "state", S::TURN, S::RUNNING, 4, -1, anim});
        clips.push_back({"turn-right-" + tag, "Right turn", "state", S::RUNNING, S::TURN, 4, -1, anim});
        clips.push_back({"hazard-" + tag, "Hazard", "state", S::HAZARD, S::HAZARD, 4, -1, anim});
        clips.push_back({"brake-turn-left-" + tag, "Brake + left turn", "state", S::BRAKE_TURN, S::BRAKE, 4, -1, anim});
        clips.push_back({"brake-turn-right-" + tag, "Brake + right turn", "state", S::BRAKE, S::BRAKE_TURN, 4, -1, anim});
    }
    clips.push_back({"off", "Off", "state", S::OFF, S::OFF, 1});
    clips.push_back({"running", "Running", "state", S::RUNNING, S::RUNNING, 6});
    clips.push_back({"brake", "Brake", "state", S::BRAKE, S::BRAKE, 3});
    clips.push_back({"reverse", "Reverse", "state", S::REVERSE, S::REVERSE, 4});

    std::vector<uint8_t> data;
    std::string index = "{\"format\":1,\"fps\":" + std::to_string(FPS) + ",\"lamp_bytes\":" + std::to_string(LAMP_BYTES) + ",\"clips\":[";
    for (size_t c = 0; c < clips.size(); ++c) {
        const Clip& clip = clips[c];
        g_settings = defaults;
        if (clip.showAnim >= 0) { g_settings.show_mode = 1; g_settings.show_anim = clip.showAnim; }
        if (clip.turnAnim >= 0) g_settings.turn_anim = clip.turnAnim;
        Lamp driver(true), passenger(false);
        recorderMillis = 100000 + c * 1000;  // Fresh start per clip, as when the state begins.
        driver.light.update(S::OFF, recorderMillis);
        passenger.light.update(S::OFF, recorderMillis);
        const size_t offset = data.size();
        const int frames = clip.seconds * FPS;
        unsigned long nextCapture = recorderMillis;
        int captured = 0;
        while (captured < frames) {
            driver.light.update(clip.driver, recorderMillis);
            passenger.light.update(clip.passenger, recorderMillis);
            if (recorderMillis >= nextCapture) {
                driver.append(data);
                passenger.append(data);
                ++captured;
                nextCapture += CAPTURE_MS;
            }
            recorderMillis += g_settings.frame_ms;  // The firmware renders every frame_ms.
        }
        index += std::string(c ? "," : "") + "{\"name\":\"" + escape(clip.name) + "\",\"title\":\"" + escape(clip.title) +
                 "\",\"group\":\"" + clip.group + "\",\"frames\":" + std::to_string(frames) + ",\"offset\":" + std::to_string(offset) + "}";
    }
    index += "]}\n";
    FILE* bin = std::fopen(argv[1], "wb");
    FILE* json = std::fopen(argv[2], "wb");
    if (!bin || !json) { std::perror("open"); return 1; }
    std::fwrite(data.data(), 1, data.size(), bin);
    std::fwrite(index.data(), 1, index.size(), json);
    std::fclose(bin); std::fclose(json);
    std::printf("Recorded %zu clips, %zu bytes\n", clips.size(), data.size());
    return 0;
}
