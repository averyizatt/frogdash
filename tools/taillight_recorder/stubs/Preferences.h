#pragma once
#include <map>
#include <string>
#include <cstring>
#include <cstdint>
class Preferences {
    std::string ns;
    bool readOnly = true;
public:
    inline static std::map<std::string, std::string> store;
    inline static bool failWrites = false;
    bool begin(const char* name, bool read = false) { ns = std::string(name) + "/"; readOnly = read; return true; }
    void end() {}
    bool isKey(const char* key) { return store.count(ns + key); }
    bool remove(const char* key) { if (readOnly || failWrites) return false; return store.erase(ns + key) != 0; }
    uint8_t getUChar(const char* key, uint8_t fallback) { return isKey(key) ? std::stoi(store[ns+key]) : fallback; }
    uint16_t getUShort(const char* key, uint16_t fallback) { return isKey(key) ? std::stoi(store[ns+key]) : fallback; }
    size_t putUChar(const char* key, uint8_t value) { if (readOnly || failWrites) return 0; store[ns+key]=std::to_string(value); return 1; }
    size_t putUShort(const char* key, uint16_t value) { if (readOnly || failWrites) return 0; store[ns+key]=std::to_string(value); return 2; }
    size_t putString(const char* key, const char* value) { if (readOnly || failWrites) return 0; store[ns+key]=value; return strlen(value); }
    size_t getString(const char* key, char* out, size_t size) {
        if (!isKey(key)) { if (size) out[0]=0; return 0; }
        const auto& value=store[ns+key];
        if (size <= value.size()) return 0;
        strcpy(out, value.c_str()); return value.size()+1;
    }
};
