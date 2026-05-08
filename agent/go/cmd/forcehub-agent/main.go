package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/shirou/gopsutil/v4/cpu"
	"github.com/shirou/gopsutil/v4/disk"
	"github.com/shirou/gopsutil/v4/host"
	"github.com/shirou/gopsutil/v4/mem"
	"github.com/shirou/gopsutil/v4/process"
)

const (
	agentName    = "ForceHubAgent-Go"
	agentVersion = "0.4.0-go"
)

type DiskInfo struct {
	Mount   string `json:"mount"`
	TotalGB uint64 `json:"total_gb"`
	FreeGB  uint64 `json:"free_gb"`
}

type TaskInfo struct {
	PID      int32   `json:"pid"`
	Name     string  `json:"name"`
	CPU      float64 `json:"cpu_percent"`
	MemoryMB uint64  `json:"memory_mb"`
}

type NetworkAdapter struct {
	Name         string   `json:"name"`
	Index        int      `json:"index"`
	MTU          int      `json:"mtu"`
	HardwareAddr string   `json:"hardware_addr"`
	Flags        []string `json:"flags"`
	Addresses    []string `json:"addresses"`
	IsUp         bool     `json:"is_up"`
}

type NetworkInfo struct {
	Adapters []NetworkAdapter `json:"adapters"`
}

type Payload struct {
	Agent             string      `json:"agent"`
	Version           string      `json:"version"`
	Target            string      `json:"target"`
	Hostname          string      `json:"hostname"`
	Username          string      `json:"username"`
	OS                string      `json:"os"`
	Arch              string      `json:"arch"`
	CPUThreads        int         `json:"cpu_threads"`
	RAMMB             uint64      `json:"ram_mb"`
	UptimeSeconds     uint64      `json:"uptime_seconds"`
	BootTimeUnix      int64       `json:"boot_time_unix"`
	ProcessCount      int         `json:"process_count"`
	Network           NetworkInfo `json:"network"`
	Disks             []DiskInfo  `json:"disks"`
	CPUUsagePercent   float64     `json:"cpu_usage_percent"`
	MemoryTotalMB     uint64      `json:"memory_total_mb"`
	MemoryAvailableMB uint64      `json:"memory_available_mb"`
	MemoryUsedMB      uint64      `json:"memory_used_mb"`
	MemoryUsedPercent float64     `json:"memory_used_percent"`
	TopTasks          []TaskInfo  `json:"top_tasks"`
	TimestampUnix     int64       `json:"timestamp_unix"`
}

func gb(v uint64) uint64 { return v / 1024 / 1024 / 1024 }
func mb(v uint64) uint64 { return v / 1024 / 1024 }

func round1(v float64) float64 {
	return float64(int(v*10)) / 10
}

func collectDisks() []DiskInfo {
	parts, err := disk.Partitions(false)
	if err != nil {
		return nil
	}

	out := make([]DiskInfo, 0, len(parts))
	seen := map[string]bool{}

	for _, p := range parts {
		if seen[p.Mountpoint] {
			continue
		}
		seen[p.Mountpoint] = true

		u, err := disk.Usage(p.Mountpoint)
		if err != nil {
			continue
		}

		totalGB := gb(u.Total)
		freeGB := gb(u.Free)

		if totalGB == 0 && freeGB == 0 {
			continue
		}

		out = append(out, DiskInfo{
			Mount:   p.Mountpoint,
			TotalGB: totalGB,
			FreeGB:  freeGB,
		})
	}

	return out
}

func collectTasks(interval time.Duration, cpuThreads int) []TaskInfo {
	procs, err := process.Processes()
	if err != nil {
		return nil
	}

	type sample struct {
		name string
		cpu  float64
		mem  uint64
	}

	before := map[int32]sample{}

	for _, p := range procs {
		name, _ := p.Name()
		times, _ := p.Times()
		memInfo, _ := p.MemoryInfo()

		totalCPU := 0.0
		if times != nil {
			totalCPU = times.User + times.System
		}

		memBytes := uint64(0)
		if memInfo != nil {
			memBytes = memInfo.RSS
		}

		before[p.Pid] = sample{name: name, cpu: totalCPU, mem: memBytes}
	}

	time.Sleep(interval)

	procs, err = process.Processes()
	if err != nil {
		return nil
	}

	out := []TaskInfo{}

	for _, p := range procs {
		prev, ok := before[p.Pid]
		if !ok {
			continue
		}

		name, _ := p.Name()
		if name == "" {
			name = prev.name
		}
		if name == "" {
			continue
		}

		times, _ := p.Times()
		memInfo, _ := p.MemoryInfo()

		nowCPU := 0.0
		if times != nil {
			nowCPU = times.User + times.System
		}

		deltaCPU := nowCPU - prev.cpu
		if deltaCPU < 0 {
			deltaCPU = 0
		}

		cpuPercent := 0.0
		if cpuThreads > 0 && interval.Seconds() > 0 {
			cpuPercent = (deltaCPU / interval.Seconds() / float64(cpuThreads)) * 100
		}

		memBytes := prev.mem
		if memInfo != nil {
			memBytes = memInfo.RSS
		}

		out = append(out, TaskInfo{
			PID:      p.Pid,
			Name:     name,
			CPU:      round1(cpuPercent),
			MemoryMB: mb(memBytes),
		})
	}

	sort.Slice(out, func(i, j int) bool {
		if out[i].CPU == out[j].CPU {
			return out[i].MemoryMB > out[j].MemoryMB
		}
		return out[i].CPU > out[j].CPU
	})

	if len(out) > 12 {
		out = out[:12]
	}

	return out
}

func collectNetwork() NetworkInfo {
	interfaces, err := net.Interfaces()
	if err != nil {
		return NetworkInfo{}
	}

	adapters := make([]NetworkAdapter, 0, len(interfaces))

	for _, iface := range interfaces {
		flags := []string{}
		for _, part := range strings.Split(iface.Flags.String(), "|") {
			part = strings.TrimSpace(part)
			if part != "" {
				flags = append(flags, part)
			}
		}

		addrs, _ := iface.Addrs()
		addresses := make([]string, 0, len(addrs))
		for _, addr := range addrs {
			if addr == nil {
				continue
			}
			addresses = append(addresses, addr.String())
		}

		// Skip empty non-useful adapters, but keep real interfaces even if currently down.
		if iface.Name == "" && iface.HardwareAddr.String() == "" && len(addresses) == 0 {
			continue
		}

		adapters = append(adapters, NetworkAdapter{
			Name:         iface.Name,
			Index:        iface.Index,
			MTU:          iface.MTU,
			HardwareAddr: iface.HardwareAddr.String(),
			Flags:        flags,
			Addresses:    addresses,
			IsUp:         iface.Flags&net.FlagUp != 0,
		})
	}

	sort.Slice(adapters, func(i, j int) bool {
		if adapters[i].IsUp == adapters[j].IsUp {
			return adapters[i].Name < adapters[j].Name
		}
		return adapters[i].IsUp && !adapters[j].IsUp
	})

	return NetworkInfo{Adapters: adapters}
}

func collectProcessCount() int {
	procs, err := process.Processes()
	if err != nil {
		return 0
	}
	return len(procs)
}

func collect() Payload {
	hostname, _ := os.Hostname()

	user := os.Getenv("USERNAME")
	if user == "" {
		user = os.Getenv("USER")
	}

	h, _ := host.Info()
	vm, _ := mem.VirtualMemory()

	cpuPercent := 0.0
	if p, err := cpu.Percent(500*time.Millisecond, false); err == nil && len(p) > 0 {
		cpuPercent = round1(p[0])
	}

	cpuThreads := runtime.NumCPU()

	osName := runtime.GOOS
	uptime := uint64(0)
	bootTimeUnix := int64(0)

	if h != nil {
		osName = fmt.Sprintf("%s %s %s", h.Platform, h.PlatformVersion, h.KernelVersion)
		if runtime.GOOS == "windows" && h.Platform != "" {
			osName = fmt.Sprintf("%s %s", h.Platform, h.PlatformVersion)
			if h.KernelVersion != "" {
				osName += " Build " + h.KernelVersion
			}
		}
		uptime = h.Uptime
		bootTimeUnix = int64(h.BootTime)
	}

	totalMB := uint64(0)
	availableMB := uint64(0)
	usedMB := uint64(0)
	usedPercent := 0.0

	if vm != nil {
		totalMB = mb(vm.Total)
		availableMB = mb(vm.Available)
		usedMB = mb(vm.Used)
		usedPercent = round1(vm.UsedPercent)
	}

	return Payload{
		Agent:             agentName,
		Version:           agentVersion,
		Target:            runtime.GOOS,
		Hostname:          hostname,
		Username:          user,
		OS:                osName,
		Arch:              runtime.GOARCH,
		CPUThreads:        cpuThreads,
		RAMMB:             totalMB,
		UptimeSeconds:     uptime,
		BootTimeUnix:      bootTimeUnix,
		ProcessCount:      collectProcessCount(),
		Network:           collectNetwork(),
		Disks:             collectDisks(),
		CPUUsagePercent:   cpuPercent,
		MemoryTotalMB:     totalMB,
		MemoryAvailableMB: availableMB,
		MemoryUsedMB:      usedMB,
		MemoryUsedPercent: usedPercent,
		TopTasks:          collectTasks(1*time.Second, cpuThreads),
		TimestampUnix:     time.Now().Unix(),
	}
}

func printJSON(payload Payload, pretty bool) error {
	enc := json.NewEncoder(os.Stdout)
	enc.SetEscapeHTML(false)

	if pretty {
		enc.SetIndent("", "  ")
	}

	return enc.Encode(payload)
}

func readToken(tokenFile string) (string, error) {
	if envToken := strings.TrimSpace(os.Getenv("FORCEHUB_AGENT_TOKEN")); envToken != "" {
		return envToken, nil
	}

	if strings.TrimSpace(tokenFile) == "" {
		return "", fmt.Errorf("missing token: use --token-file or FORCEHUB_AGENT_TOKEN")
	}

	raw, err := os.ReadFile(tokenFile)
	if err != nil {
		return "", err
	}

	token := strings.TrimSpace(string(raw))
	if token == "" {
		return "", fmt.Errorf("empty token file: %s", tokenFile)
	}

	return token, nil
}

func validatePostServerURL(serverURL string) error {
	parsed, err := url.Parse(serverURL)
	if err != nil {
		return fmt.Errorf("invalid server URL: %w", err)
	}

	if parsed.Scheme != "http" {
		return fmt.Errorf("invalid server URL: scheme must be http")
	}

	host := parsed.Hostname()
	if host != "127.0.0.1" && host != "localhost" {
		return fmt.Errorf("invalid server URL: host must be 127.0.0.1 or localhost")
	}

	port := parsed.Port()
	if port == "" {
		return fmt.Errorf("invalid server URL: explicit port is required")
	}

	portNumber, err := strconv.Atoi(port)
	if err != nil || portNumber < 1 || portNumber > 65535 {
		return fmt.Errorf("invalid server URL: port must be between 1 and 65535")
	}

	if parsed.Path == "" || !strings.HasPrefix(parsed.Path, "/") {
		return fmt.Errorf("invalid server URL: path is required")
	}

	if parsed.User != nil || parsed.Fragment != "" {
		return fmt.Errorf("invalid server URL: userinfo and fragments are not allowed")
	}

	return nil
}

func postPayload(payload Payload, serverURL string, tokenFile string) error {
	if err := validatePostServerURL(serverURL); err != nil {
		return err
	}

	token, err := readToken(tokenFile)
	if err != nil {
		return err
	}

	body, err := json.Marshal(payload)
	if err != nil {
		return err
	}

	req, err := http.NewRequest(http.MethodPost, serverURL, bytes.NewReader(body))
	if err != nil {
		return err
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-ForceHub-Agent-Token", token)

	client := &http.Client{Timeout: 15 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	respBody, _ := io.ReadAll(resp.Body)

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("post failed: HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(respBody)))
	}

	fmt.Println(strings.TrimSpace(string(respBody)))
	return nil
}

func usage() {
	fmt.Fprintf(os.Stderr, `%s %s

Usage:
  ForceHubAgent-Go.exe
  ForceHubAgent-Go.exe --once
  ForceHubAgent-Go.exe --watch --interval 3
  ForceHubAgent-Go.exe --post --server http://127.0.0.1:18001/api/agents/checkin --token-file D:\Scripts\ForceHubAgent\agent_token.txt
  ForceHubAgent-Go.exe --watch --post --interval 3 --server http://127.0.0.1:18001/api/agents/checkin --token-file D:\Scripts\ForceHubAgent\agent_token.txt

Options:
`, agentName, agentVersion)
	flag.PrintDefaults()
}

func main() {
	once := flag.Bool("once", false, "collect once and exit")
	watch := flag.Bool("watch", false, "collect forever")
	post := flag.Bool("post", false, "post payload to ForceHub instead of printing JSON")
	interval := flag.Int("interval", 3, "watch interval in seconds")
	server := flag.String("server", "http://127.0.0.1:18001/api/agents/checkin", "ForceHub check-in URL")
	tokenFile := flag.String("token-file", "", "file containing ForceHub agent token")
	pretty := flag.Bool("pretty", false, "pretty-print JSON")
	version := flag.Bool("version", false, "print version and exit")

	flag.Usage = usage
	flag.Parse()

	if *version {
		fmt.Printf("%s %s\n", agentName, agentVersion)
		return
	}

	if *interval < 1 {
		*interval = 1
	}

	runOnce := func() {
		payload := collect()

		if *post {
			if err := postPayload(payload, *server, *tokenFile); err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(1)
			}
			return
		}

		if err := printJSON(payload, *pretty); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
	}

	if *once || !*watch {
		runOnce()
		return
	}

	for {
		payload := collect()

		if *post {
			if err := postPayload(payload, *server, *tokenFile); err != nil {
				fmt.Fprintln(os.Stderr, err)
			}
		} else {
			if err := printJSON(payload, *pretty); err != nil {
				fmt.Fprintln(os.Stderr, err)
			}
		}

		time.Sleep(time.Duration(*interval) * time.Second)
	}
}
