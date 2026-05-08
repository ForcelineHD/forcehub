#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include <thread>
#include <cstdlib>
#include <cstdint>
#include <algorithm>
#include <iomanip>
#include <map>
#include <cstring>

#ifdef _WIN32
  #ifndef NOMINMAX
    #define NOMINMAX
  #endif
  #define WIN32_LEAN_AND_MEAN
  #include <windows.h>
  #include <lmcons.h>
  #include <tlhelp32.h>
  #include <psapi.h>
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

static std::string num1(double value) {
    std::ostringstream ss;
    ss << std::fixed << std::setprecision(1) << value;
    return ss.str();
}

#ifdef _WIN32

struct ProcSample {
    DWORD pid = 0;
    std::string name;
    uint64_t cpu_100ns = 0;
    uint64_t memory_bytes = 0;
};

static uint64_t filetime_to_u64(const FILETIME& ft) {
    ULARGE_INTEGER uli{};
    uli.LowPart = ft.dwLowDateTime;
    uli.HighPart = ft.dwHighDateTime;
    return uli.QuadPart;
}

static std::string wide_to_utf8(const wchar_t* ws) {
    if (!ws || !*ws) return "unknown";

    int needed = WideCharToMultiByte(CP_UTF8, 0, ws, -1, nullptr, 0, nullptr, nullptr);
    if (needed <= 0) return "unknown";

    std::string out(static_cast<size_t>(needed - 1), '\0');
    WideCharToMultiByte(CP_UTF8, 0, ws, -1, out.data(), needed, nullptr, nullptr);
    return out;
}

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
        auto proc = GetProcAddress(ntdll, "RtlGetVersion");
        if (proc) {
            auto rtl_get_version = reinterpret_cast<RtlGetVersionPtr>(reinterpret_cast<void*>(proc));
            if (rtl_get_version(&osvi) == 0) {
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
    }

    return "Windows";
}

static MEMORYSTATUSEX get_memory_status() {
    MEMORYSTATUSEX mem{};
    mem.dwLength = sizeof(mem);
    GlobalMemoryStatusEx(&mem);
    return mem;
}

static uint64_t get_total_ram_mb() {
    auto mem = get_memory_status();
    return static_cast<uint64_t>(mem.ullTotalPhys / 1024 / 1024);
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
    GetLogicalDriveStringsA(sizeof(drives), drives);

    std::ostringstream ss;
    ss << "[";

    bool first = true;
    for (char* drive = drives; drive && *drive; drive += std::strlen(drive) + 1) {
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

static uint64_t system_total_100ns() {
    FILETIME idle{}, kernel{}, user{};
    if (!GetSystemTimes(&idle, &kernel, &user)) return 0;
    return filetime_to_u64(kernel) + filetime_to_u64(user);
}

static uint64_t system_busy_100ns() {
    FILETIME idle{}, kernel{}, user{};
    if (!GetSystemTimes(&idle, &kernel, &user)) return 0;

    uint64_t k = filetime_to_u64(kernel);
    uint64_t u = filetime_to_u64(user);
    uint64_t i = filetime_to_u64(idle);

    return (k + u) > i ? (k + u - i) : 0;
}

static std::map<DWORD, ProcSample> sample_processes() {
    std::map<DWORD, ProcSample> out;

    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE) return out;

    PROCESSENTRY32W pe{};
    pe.dwSize = sizeof(pe);

    if (Process32FirstW(snap, &pe)) {
        do {
            ProcSample ps{};
            ps.pid = pe.th32ProcessID;
            ps.name = wide_to_utf8(pe.szExeFile);

            HANDLE h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, FALSE, ps.pid);
            if (h) {
                FILETIME createTime{}, exitTime{}, kernelTime{}, userTime{};
                if (GetProcessTimes(h, &createTime, &exitTime, &kernelTime, &userTime)) {
                    ps.cpu_100ns = filetime_to_u64(kernelTime) + filetime_to_u64(userTime);
                }

                PROCESS_MEMORY_COUNTERS_EX pmc{};
                if (GetProcessMemoryInfo(h, reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&pmc), sizeof(pmc))) {
                    ps.memory_bytes = static_cast<uint64_t>(pmc.WorkingSetSize);
                }

                CloseHandle(h);
            }

            out[ps.pid] = ps;
        } while (Process32NextW(snap, &pe));
    }

    CloseHandle(snap);
    return out;
}

static std::string get_live_metrics_json() {
    auto mem = get_memory_status();

    uint64_t total_before = system_total_100ns();
    uint64_t busy_before = system_busy_100ns();
    auto proc_before = sample_processes();

    Sleep(500);

    uint64_t total_after = system_total_100ns();
    uint64_t busy_after = system_busy_100ns();
    auto proc_after = sample_processes();

    uint64_t total_delta = total_after > total_before ? total_after - total_before : 0;
    uint64_t busy_delta = busy_after > busy_before ? busy_after - busy_before : 0;

    double cpu_usage = total_delta ? (static_cast<double>(busy_delta) * 100.0 / static_cast<double>(total_delta)) : 0.0;

    struct ProcLive {
        DWORD pid;
        std::string name;
        double cpu_percent;
        uint64_t memory_mb;
    };

    std::vector<ProcLive> live;

    for (const auto& item : proc_after) {
        DWORD pid = item.first;
        const ProcSample& after = item.second;

        auto it = proc_before.find(pid);
        if (it == proc_before.end()) continue;

        uint64_t cpu_delta = after.cpu_100ns > it->second.cpu_100ns
            ? after.cpu_100ns - it->second.cpu_100ns
            : 0;

        double proc_cpu = total_delta
            ? (static_cast<double>(cpu_delta) * 100.0 / static_cast<double>(total_delta))
            : 0.0;

        live.push_back({
            pid,
            after.name,
            proc_cpu,
            static_cast<uint64_t>(after.memory_bytes / 1024 / 1024)
        });
    }

    std::sort(live.begin(), live.end(), [](const ProcLive& a, const ProcLive& b) {
        if (a.cpu_percent == b.cpu_percent) return a.memory_mb > b.memory_mb;
        return a.cpu_percent > b.cpu_percent;
    });

    std::ostringstream ss;
    ss << "{";
    ss << "\"cpu_usage_percent\":" << num1(cpu_usage) << ",";
    ss << "\"memory_total_mb\":" << static_cast<uint64_t>(mem.ullTotalPhys / 1024 / 1024) << ",";
    ss << "\"memory_available_mb\":" << static_cast<uint64_t>(mem.ullAvailPhys / 1024 / 1024) << ",";
    ss << "\"memory_used_mb\":" << static_cast<uint64_t>((mem.ullTotalPhys - mem.ullAvailPhys) / 1024 / 1024) << ",";
    ss << "\"memory_used_percent\":" << static_cast<unsigned int>(mem.dwMemoryLoad) << ",";
    ss << "\"top_tasks\":[";

    size_t limit = std::min<size_t>(live.size(), 10);
    for (size_t i = 0; i < limit; ++i) {
        if (i) ss << ",";
        ss << "{";
        ss << "\"pid\":" << live[i].pid << ",";
        ss << "\"name\":" << q(live[i].name) << ",";
        ss << "\"cpu_percent\":" << num1(live[i].cpu_percent) << ",";
        ss << "\"memory_mb\":" << live[i].memory_mb;
        ss << "}";
    }

    ss << "]";
    ss << "}";

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

static std::string get_live_metrics_json() {
    struct sysinfo info{};
    sysinfo(&info);

    uint64_t total_mb = static_cast<uint64_t>((info.totalram * info.mem_unit) / 1024 / 1024);
    uint64_t free_mb = static_cast<uint64_t>((info.freeram * info.mem_unit) / 1024 / 1024);
    uint64_t used_mb = total_mb > free_mb ? total_mb - free_mb : 0;
    uint64_t used_percent = total_mb ? (used_mb * 100 / total_mb) : 0;

    std::ostringstream ss;
    ss << "{";
    ss << "\"cpu_usage_percent\":0.0,";
    ss << "\"memory_total_mb\":" << total_mb << ",";
    ss << "\"memory_available_mb\":" << free_mb << ",";
    ss << "\"memory_used_mb\":" << used_mb << ",";
    ss << "\"memory_used_percent\":" << used_percent << ",";
    ss << "\"top_tasks\":[]";
    ss << "}";
    return ss.str();
}

#endif

static void print_json() {
    std::string metrics = get_live_metrics_json();

    std::ostringstream ss;

    ss << "{";
    ss << "\"agent\":\"ForceHubAgent\",";
    ss << "\"version\":\"0.2.0\",";
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
    ss << "\"disks\":" << get_disks_json() << ",";

    if (metrics.size() >= 2 && metrics.front() == '{' && metrics.back() == '}') {
        ss << metrics.substr(1, metrics.size() - 2);
    } else {
        ss << "\"cpu_usage_percent\":0.0,"
           << "\"memory_used_percent\":0,"
           << "\"memory_used_mb\":0,"
           << "\"memory_available_mb\":0,"
           << "\"memory_total_mb\":0,"
           << "\"top_tasks\":[]";
    }

    ss << "}";

    std::cout << ss.str() << std::endl;
}

static void print_help() {
    std::cout
        << "ForceHubAgent 0.2.0\n\n"
        << "Usage:\n"
        << "  ForceHubAgent.exe --json\n"
        << "  ForceHubAgent.exe --help\n\n"
        << "Description:\n"
        << "  Local diagnostics agent for ForceHub.\n"
        << "  Prints inventory, CPU usage, memory usage, disks, and top tasks as JSON.\n";
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
