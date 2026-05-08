package main

import (
	"encoding/json"
	"fmt"
	"os"
	"runtime"
	"sort"
	"time"

	"github.com/shirou/gopsutil/v4/cpu"
	"github.com/shirou/gopsutil/v4/disk"
	"github.com/shirou/gopsutil/v4/host"
	"github.com/shirou/gopsutil/v4/mem"
	"github.com/shirou/gopsutil/v4/process"
)

type DiskInfo struct {
	Mount   string `json:"mount"`
	TotalGB uint64 `json:"total_gb"`
	FreeGB  uint64 `json:"free_gb"`
}

type TaskInfo struct {
	PID       int32   `json:"pid"`
	Name      string  `json:"name"`
	CPU       float64 `json:"cpu_percent"`
	MemoryMB uint64  `json:"memory_mb"`
}

type Payload struct {
	Agent               string     `json:"agent"`
	Version             string     `json:"version"`
	Target              string     `json:"target"`
	Hostname            string     `json:"hostname"`
	Username            string     `json:"username"`
	OS                  string     `json:"os"`
	Arch                string     `json:"arch"`
	CPUThreads          int        `json:"cpu_threads"`
	RAMMB               uint64     `json:"ram_mb"`
	UptimeSeconds       uint64     `json:"uptime_seconds"`
	Disks               []DiskInfo `json:"disks"`
	CPUUsagePercent     float64    `json:"cpu_usage_percent"`
	MemoryTotalMB       uint64     `json:"memory_total_mb"`
	MemoryAvailableMB   uint64     `json:"memory_available_mb"`
	MemoryUsedMB        uint64     `json:"memory_used_mb"`
	MemoryUsedPercent   float64    `json:"memory_used_percent"`
	TopTasks            []TaskInfo `json:"top_tasks"`
}

func gb(v uint64) uint64 { return v / 1024 / 1024 / 1024 }
func mb(v uint64) uint64 { return v / 1024 / 1024 }

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

		out = append(out, DiskInfo{
			Mount:   p.Mountpoint,
			TotalGB: gb(u.Total),
			FreeGB:  gb(u.Free),
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

		if name == "svchost.exe" && cpuPercent == 0 && mb(memBytes) < 100 {
			continue
		}

		out = append(out, TaskInfo{
			PID:       p.Pid,
			Name:      name,
			CPU:       float64(int(cpuPercent*10)) / 10,
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
		cpuPercent = float64(int(p[0]*10)) / 10
	}

	cpuThreads := runtime.NumCPU()

	osName := runtime.GOOS
	uptime := uint64(0)
	if h != nil {
		osName = fmt.Sprintf("%s %s %s", h.Platform, h.PlatformVersion, h.KernelVersion)
		uptime = h.Uptime
	}

	totalMB := uint64(0)
	availableMB := uint64(0)
	usedMB := uint64(0)
	usedPercent := 0.0

	if vm != nil {
		totalMB = mb(vm.Total)
		availableMB = mb(vm.Available)
		usedMB = mb(vm.Used)
		usedPercent = float64(int(vm.UsedPercent*10)) / 10
	}

	return Payload{
		Agent:             "ForceHubAgent-Go",
		Version:           "0.1.0-go",
		Target:            runtime.GOOS,
		Hostname:          hostname,
		Username:          user,
		OS:                osName,
		Arch:              runtime.GOARCH,
		CPUThreads:        cpuThreads,
		RAMMB:             totalMB,
		UptimeSeconds:     uptime,
		Disks:             collectDisks(),
		CPUUsagePercent:   cpuPercent,
		MemoryTotalMB:     totalMB,
		MemoryAvailableMB: availableMB,
		MemoryUsedMB:      usedMB,
		MemoryUsedPercent: usedPercent,
		TopTasks:          collectTasks(1*time.Second, cpuThreads),
	}
}

func main() {
	payload := collect()

	enc := json.NewEncoder(os.Stdout)
	enc.SetEscapeHTML(false)

	if err := enc.Encode(payload); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
