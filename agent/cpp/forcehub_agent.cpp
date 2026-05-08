#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include <thread>
#include <cstdlib>
#include <cstdint>

#ifdef _WIN32
  #define NOMINMAX
  #include <windows.h>
  #include <lmcons.h>
#else
  #include <unistd.h>
  #include <sys/sysinfo.h>
  #include <sys/utsname.h>
  #include <filesystem>
#endif

static std::string json_escape(const std::string& s) {
    std::ostringstream o;
    for (char c : s) {
        switch (c) {
            case '"':  o << "\\\""; break;
            case '\\': o << "\\\\"; break;
            case '\b': o << "\\b"; break;
            case '\f': o << "\\f"; break;
            case '\n': o << "\\n"; break;
            case '\r': o << "\\r"; break;
            case '\t': o << "\\t"; break;
            default:
                if (static_cast<unsigned char>(c) < 0x20) {
                    o << "\\u" << std::hex << static_cast<int>(c);
                } else {
                    o << c;
                }
        }
    }
    return o.str();
}

static std::string q(const std::string& s) {
    return "\"" + json_escape(s) + "\"";
}

#ifdef _WIN32

static std::string get_hostname() {
    char buffer[MAX_COMPUTERNAME_LENGTH + 1] = {0};
    DWORD size = sizeof(buffer);
    if (GetComputerNameA(buffer, &size)) return std::string(buffer);
    return "unknown";
}

static std::string get_username() {
    char buffer[UNLEN + 1] = {0};
    DWORD size = sizeof(buffer);
    if (GetUserNameA(buffer, &size)) return std::string(buffer);
    return "unknown";
}

static std::string get_os_string() {
    typedef LONG (WINAPI *RtlGetVersionPtr)(OSVERSIONINFOEXW*);

    OSVERSIONINFOEXW osvi{};
    osvi.dwOSVersionInfoSize = sizeof(osvi);

    HMODULE ntdll = GetModuleHandleA("ntdll.dll");
    if (ntdll) {
        auto rtl_get_version = reinterpret_cast<RtlGetVersionPtr>(
            GetProcAddress(ntdll, "RtlGetVersion")
        );

        if (rtl_get_version && rtl_get_version(&osvi) == 0) {
            std::ostringstream ss;

            if (osvi.dwMajorVersion == 10 && osvi.dwBuildNumber >= 22000) {
                ss << "Windows 11";
            } else if (osvi.dwMajorVersion == 10) {
                ss << "Windows 10";
            } else {
                ss << "Windows " << osvi.dwMajorVersion << "." << osvi.dwMinorVersion;
            }

            ss << " build " << osvi.dwBuildNumber;
            return ss.str();
        }
    }

    return "Windows";
}

static uint64_t get_total_ram_mb() {
    MEMORYSTATUSEX mem{};
    mem.dwLength = sizeof(mem);
    if (GlobalMemoryStatusEx(&mem)) {
        return static_cast<uint64_t>(mem.ullTotalPhys / 1024 / 1024);
    }
    return 0;
}

static uint64_t get_uptime_seconds() {
    return static_cast<uint64_t>(GetTickCount64() / 1000);
}

static unsigned int get_cpu_threads() {
    SYSTEM_INFO si{};
    GetSystemInfo(&si);
    return static_cast<unsigned int>(si.dwNumberOfProcessors);
}

static std::string get_arch() {
#if defined(_M_X64) || defined(__x86_64__)
    return "x64";
#elif defined(_M_IX86) || defined(__i386__)
    return "x86";
#elif defined(_M_ARM64) || defined(__aarch64__)
    return "arm64";
#else
    return "unknown";
#endif
}

static std::string get_disks_json() {
    char drives[512] = {0};
    DWORD len = GetLogicalDriveStringsA(sizeof(drives), drives);

    std::ostringstream ss;
    ss << "[";

    bool first = true;
    for (char* drive = drives; drive && *drive; drive += strlen(drive) + 1) {
        ULARGE_INTEGER freeBytesAvailable{}, totalBytes{}, totalFreeBytes{};

        if (GetDiskFreeSpaceExA(drive, &freeBytesAvailable, &totalBytes, &totalFreeBytes)) {
            if (!first) ss << ",";
            first = false;

            ss << "{";
            ss << "\"mount\":" << q(drive) << ",";
            ss << "\"total_gb\":" << static_cast<uint64_t>(totalBytes.QuadPart / 1024 / 1024 / 1024) << ",";
            ss << "\"free_gb\":" << static_cast<uint64_t>(totalFreeBytes.QuadPart / 1024 / 1024 / 1024);
            ss << "}";
        }
    }

    ss << "]";
    return ss.str();
}

#else

static std::string get_hostname() {
    char buffer[256] = {0};
    if (gethostname(buffer, sizeof(buffer)) == 0) return std::string(buffer);
    return "unknown";
}

static std::string get_username() {
    const char* user = std::getenv("USER");
    return user ? std::string(user) : "unknown";
}

static std::string get_os_string() {
    struct utsname u{};
    if (uname(&u) == 0) {
        std::ostringstream ss;
        ss << u.sysname << " " << u.release << " " << u.machine;
        return ss.str();
    }
    return "Linux";
}

static uint64_t get_total_ram_mb() {
    struct sysinfo info{};
    if (sysinfo(&info) == 0) {
        return static_cast<uint64_t>((info.totalram * info.mem_unit) / 1024 / 1024);
    }
    return 0;
}

static uint64_t get_uptime_seconds() {
    struct sysinfo info{};
    if (sysinfo(&info) == 0) {
        return static_cast<uint64_t>(info.uptime);
    }
    return 0;
}

static unsigned int get_cpu_threads() {
    unsigned int n = std::thread::hardware_concurrency();
    return n ? n : 1;
}

static std::string get_arch() {
#if defined(__x86_64__)
    return "x64";
#elif defined(__i386__)
    return "x86";
#elif defined(__aarch64__)
    return "arm64";
#else
    return "unknown";
#endif
}

static std::string get_disks_json() {
    std::ostringstream ss;
    ss << "[";

    try {
        auto sp = std::filesystem::space("/");
        ss << "{";
        ss << "\"mount\":\"/\",";
        ss << "\"total_gb\":" << static_cast<uint64_t>(sp.capacity / 1024 / 1024 / 1024) << ",";
        ss << "\"free_gb\":" << static_cast<uint64_t>(sp.available / 1024 / 1024 / 1024);
        ss << "}";
    } catch (...) {}

    ss << "]";
    return ss.str();
}

#endif

static void print_json() {
    std::ostringstream ss;

    ss << "{";
    ss << "\"agent\":\"ForceHubAgent\",";
    ss << "\"version\":\"0.1.0\",";
#ifdef _WIN32
    ss << "\"target\":\"windows\",";
#else
    ss << "\"target\":\"linux\",";
#endif
    ss << "\"hostname\":" << q(get_hostname()) << ",";
    ss << "\"username\":" << q(get_username()) << ",";
    ss << "\"os\":" << q(get_os_string()) << ",";
    ss << "\"arch\":" << q(get_arch()) << ",";
    ss << "\"cpu_threads\":" << get_cpu_threads() << ",";
    ss << "\"ram_mb\":" << get_total_ram_mb() << ",";
    ss << "\"uptime_seconds\":" << get_uptime_seconds() << ",";
    ss << "\"disks\":" << get_disks_json();
    ss << "}";

    std::cout << ss.str() << std::endl;
}

static void print_help() {
    std::cout
        << "ForceHubAgent 0.1.0\n"
        << "\n"
        << "Usage:\n"
        << "  ForceHubAgent.exe --json\n"
        << "  ForceHubAgent.exe --help\n"
        << "\n"
        << "Description:\n"
        << "  Local diagnostics agent for ForceHub.\n"
        << "  Current version only prints local system inventory as JSON.\n";
}

int main(int argc, char* argv[]) {
    if (argc <= 1) {
        print_json();
        return 0;
    }

    std::string arg = argv[1];

    if (arg == "--json") {
        print_json();
        return 0;
    }

    if (arg == "--help" || arg == "-h") {
        print_help();
        return 0;
    }

    std::cerr << "Unknown argument: " << arg << std::endl;
    std::cerr << "Run: ForceHubAgent.exe --help" << std::endl;
    return 2;
}
