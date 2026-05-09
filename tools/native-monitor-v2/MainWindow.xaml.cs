using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Data;
using System.Windows.Media;
using WpfPolyline = System.Windows.Shapes.Polyline;
using Polyline = System.Windows.Shapes.Polyline;
using System.Windows.Threading;

namespace ForceHubNativeMonitorV2;

public partial class MainWindow : Window
{
    private const string BaseDir = @"D:\Scripts\ForceHubAgent";
    private const string ApiUrl = "http://127.0.0.1:18001/api/agents";
    private const string TokenFile = @"D:\Scripts\ForceHubAgent\agent_token.txt";

    private readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(2) };
    private readonly DispatcherTimer _timer = new();
    private readonly ObservableCollection<AgentVm> _agents = new();
    private readonly ObservableCollection<TaskVm> _selectedTasks = new();
    private readonly ObservableCollection<AdapterVm> _selectedAdapters = new();
    private readonly ObservableCollection<DiskVm> _selectedDisks = new();
    private readonly ICollectionView _agentsView;

    private readonly List<double> _cpuHistory = new();
    private readonly List<double> _memoryHistory = new();
    private bool _refreshing;

    public ObservableCollection<AgentVm> Agents => _agents;
    public ObservableCollection<TaskVm> SelectedTasks => _selectedTasks;
    public ObservableCollection<AdapterVm> SelectedAdapters => _selectedAdapters;
    public ObservableCollection<DiskVm> SelectedDisks => _selectedDisks;

    public MainWindow()
    {
        InitializeComponent();
        DataContext = this;

        _agentsView = CollectionViewSource.GetDefaultView(_agents);
        _agentsView.Filter = FilterAgent;

        _timer.Interval = TimeSpan.FromSeconds(3);
        _timer.Tick += async (_, _) => await RefreshAgents(false);

        StatusText.Text = "Ready.";
        Loaded += async (_, _) => await RefreshAgents(false);
        _timer.Start();
    }

    private bool FilterAgent(object obj)
    {
        if (obj is not AgentVm a) return false;

        string q = SearchBox?.Text?.Trim() ?? "";
        if (q.Length == 0) return true;

        return Contains(a.Hostname, q) ||
               Contains(a.OS, q) ||
               Contains(a.Version, q) ||
               Contains(a.NetworkSummary, q) ||
               Contains(a.Status, q);
    }

    private static bool Contains(string? text, string q) =>
        text?.IndexOf(q, StringComparison.OrdinalIgnoreCase) >= 0;

    private async void Refresh_Click(object sender, RoutedEventArgs e) => await RefreshAgents(true);

    private void StartAuto_Click(object sender, RoutedEventArgs e)
    {
        _timer.Start();
        SetStatus("Auto refresh enabled.");
    }

    private void StopAuto_Click(object sender, RoutedEventArgs e)
    {
        _timer.Stop();
        SetStatus("Auto refresh stopped.");
    }

    private void SearchBox_TextChanged(object sender, System.Windows.Controls.TextChangedEventArgs e)
    {
        _agentsView.Refresh();
    }

    private async Task RefreshAgents(bool showError)
    {
        if (_refreshing)
            return;

        _refreshing = true;

        try
        {
            string token = ReadToken();

            using var req = new HttpRequestMessage(HttpMethod.Get, ApiUrl);
            req.Headers.Add("X-ForceHub-Agent-Token", token);

            using var resp = await _http.SendAsync(req);
            string json = await resp.Content.ReadAsStringAsync();

            resp.EnsureSuccessStatusCode();

            var root = JsonNode.Parse(json)?.AsObject()
                ?? throw new Exception("Invalid API JSON.");

            var agents = root["agents"]?.AsArray()
                ?? throw new Exception("API returned no agents array.");

            string? selectedHost = (AgentsGrid.SelectedItem as AgentVm)?.Hostname;

            _agents.Clear();

            int online = 0;
            double maxCpu = 0;
            double maxMem = 0;

            foreach (var node in agents)
            {
                if (node is not JsonObject row) continue;

                var payload = row["payload"]?.AsObject() ?? new JsonObject();

                long last = GetLong(row, "last_checkin_unix");
                bool recent = IsRecent(last);
                if (recent) online++;

                double cpu = GetDouble(payload, "cpu_usage_percent");
                double mem = GetDouble(payload, "memory_used_percent");

                var vm = new AgentVm
                {
                    Hostname = GetString(row, "hostname", GetString(payload, "hostname")),
                    Status = recent ? "Online" : "Stale",
                    Agent = GetString(payload, "agent"),
                    Version = GetString(payload, "version"),
                    OS = GetString(payload, "os"),
                    CpuPercentValue = cpu,
                    CpuPercent = cpu.ToString("0.0"),
                    MemoryPercent = mem,
                    MemorySummary = FormatMemory(payload),
                    ProcessCount = GetLong(payload, "process_count").ToString(),
                    Uptime = FormatDuration(GetLong(payload, "uptime_seconds")),
                    NetworkSummary = FormatNetworkSummary(payload),
                    LastCheckIn = FormatUnix(last),
                    Payload = payload,
                    RawJson = payload.ToJsonString(new JsonSerializerOptions { WriteIndented = true })
                };

                maxCpu = Math.Max(maxCpu, vm.CpuPercentValue);
                maxMem = Math.Max(maxMem, vm.MemoryPercent);

                _agents.Add(vm);
            }

            _agentsView.Refresh();

            AgentsMetric.Text = _agents.Count.ToString();
            LiveMetric.Text = online + " Online";

            CpuMetric.Text = maxCpu.ToString("0.0") + "%";
            PushHistory(_cpuHistory, maxCpu);
            UpdateMiniGraph(CpuGraph, _cpuHistory);

            MemoryMetric.Text = maxMem.ToString("0.0") + "%";
            PushHistory(_memoryHistory, maxMem);
            UpdateMiniGraph(MemoryGraph, _memoryHistory);

            ApiMetric.Text = "Live";
            HeaderSubtitle.Text = $"API: {ApiUrl} | Last refresh: {DateTime.Now:HH:mm:ss}";
            SetStatus("Refreshed.");

            var restore = _agents.FirstOrDefault(a => a.Hostname == selectedHost) ?? _agents.FirstOrDefault();
            AgentsGrid.SelectedItem = restore;
            LoadSelectedAgent(restore);
        }        catch (Exception ex)
        {
            ApiMetric.Text = "Offline";
            SetStatus("Refresh failed: " + ex.Message);
        }
        finally
        {
            _refreshing = false;
        }
    }

    private void PushHistory(List<double> history, double value, int maxPoints = 60)
    {
        history.Add(Math.Max(0, Math.Min(100, value)));
        while (history.Count > maxPoints)
            history.RemoveAt(0);
    }

    private void UpdateMiniGraph(WpfPolyline line, List<double> history)
    {
        if (line == null || history.Count == 0)
            return;

        FrameworkElement? host = line.Parent as FrameworkElement;

        double width = host?.ActualWidth > 20 ? host.ActualWidth : 320;
        double height = host?.ActualHeight > 20 ? host.ActualHeight : 52;

        width = Math.Max(80, width - 4);
        height = Math.Max(30, height - 4);

        PointCollection points = new();

        if (history.Count == 1)
        {
            double y = height - (history[0] / 100.0 * height);
            points.Add(new Point(0, y));
            points.Add(new Point(width, y));
        }
        else
        {
            for (int i = 0; i < history.Count; i++)
            {
                double x = i * (width / (history.Count - 1));
                double y = height - (history[i] / 100.0 * height);
                points.Add(new Point(x, y));
            }
        }

        line.Points = points;
    }

    private void AgentsGrid_SelectionChanged(object sender, System.Windows.Controls.SelectionChangedEventArgs e)
    {
        LoadSelectedAgent(AgentsGrid.SelectedItem as AgentVm);
    }

    private void LoadSelectedAgent(AgentVm? agent)
    {
        _selectedTasks.Clear();
        _selectedAdapters.Clear();
        _selectedDisks.Clear();
        RawJsonBox.Text = "";

        if (agent == null)
        {
            SelectedSubtitle.Text = "No agent selected";
            IdentityText.Text = "";
            SystemText.Text = "";
            NetworkFocusText.Text = "";
            DiskText.Text = "";
            return;
        }

        var p = agent.Payload;

        SelectedSubtitle.Text = $"{agent.Hostname} | {agent.Status} | {agent.Version}";
        IdentityText.Text =
            $"Hostname: {agent.Hostname}\n" +
            $"User: {GetString(p, "username")}\n" +
            $"Agent: {GetString(p, "agent")}\n" +
            $"Version: {agent.Version}";

        SystemText.Text =
            $"OS: {agent.OS}\n" +
            $"Arch: {GetString(p, "arch")}\n" +
            $"CPU Threads: {GetLong(p, "cpu_threads")}\n" +
            $"Processes: {agent.ProcessCount}\n" +
            $"Uptime: {agent.Uptime}\n" +
            $"Boot: {FormatUnix(GetLong(p, "boot_time_unix"))}\n" +
            $"Memory: {agent.MemorySummary}";

        LoadTasks(p);
        LoadAdapters(p);
        LoadDisks(p);

        NetworkFocusText.Text = BuildNetworkFocus(_selectedAdapters);
        DiskText.Text = string.Join("\n", _selectedDisks.Select(d => $"{d.Mount}: {d.FreeGb}GB free / {d.TotalGb}GB total"));
        RawJsonBox.Text = agent.RawJson;
    }

    private void LoadTasks(JsonObject p)
    {
        if (p["top_tasks"] is not JsonArray tasks) return;

        foreach (var node in tasks)
        {
            if (node is not JsonObject t) continue;

            _selectedTasks.Add(new TaskVm
            {
                Pid = GetLong(t, "pid").ToString(),
                Name = GetString(t, "name"),
                CpuPercent = GetDouble(t, "cpu_percent").ToString("0.0"),
                MemoryMb = GetLong(t, "memory_mb").ToString()
            });
        }
    }

    private void LoadAdapters(JsonObject p)
    {
        if (p["network"] is not JsonObject network) return;
        if (network["adapters"] is not JsonArray adapters) return;

        foreach (var node in adapters)
        {
            if (node is not JsonObject a) continue;

            _selectedAdapters.Add(new AdapterVm
            {
                Name = GetString(a, "name"),
                Status = GetBool(a, "is_up") ? "Up" : "Down",
                Mtu = GetLong(a, "mtu").ToString(),
                Addresses = FormatStringArray(a, "addresses")
            });
        }
    }

    private void LoadDisks(JsonObject p)
    {
        if (p["disks"] is not JsonArray disks) return;

        foreach (var node in disks)
        {
            if (node is not JsonObject d) continue;

            _selectedDisks.Add(new DiskVm
            {
                Mount = GetString(d, "mount"),
                FreeGb = GetLong(d, "free_gb").ToString(),
                TotalGb = GetLong(d, "total_gb").ToString()
            });
        }
    }

    private static string BuildNetworkFocus(IEnumerable<AdapterVm> adapters)
    {
        var focus = adapters
            .Where(a =>
                Contains(a.Name, "VMnet8") ||
                Contains(a.Name, "NordLynx") ||
                Contains(a.Name, "Tailscale") ||
                string.Equals(a.Name, "Ethernet", StringComparison.OrdinalIgnoreCase))
            .Select(a => $"{a.Name}: {a.Status} | {a.Addresses}")
            .ToList();

        return focus.Count == 0 ? "No focus adapters found." : string.Join("\n", focus);
    }

    private static string ReadToken()
    {
        if (!File.Exists(TokenFile)) throw new Exception("Missing token file: " + TokenFile);
        string token = File.ReadAllText(TokenFile).Trim();
        if (token.Length == 0) throw new Exception("Token file is empty.");
        return token;
    }

    private static string FormatMemory(JsonObject p)
    {
        long used = GetLong(p, "memory_used_mb");
        long total = GetLong(p, "memory_total_mb");
        double pct = GetDouble(p, "memory_used_percent");
        return total <= 0 ? "" : $"{used} / {total} MB ({pct:0.0}%)";
    }

    private static string FormatNetworkSummary(JsonObject p)
    {
        if (p["network"] is not JsonObject network) return "";
        if (network["adapters"] is not JsonArray adapters) return "";

        int up = 0;
        var important = new List<string>();

        foreach (var node in adapters)
        {
            if (node is not JsonObject a) continue;

            bool isUp = GetBool(a, "is_up");
            if (isUp) up++;

            string name = GetString(a, "name");
            if (Contains(name, "VMnet8") || Contains(name, "NordLynx") || Contains(name, "Tailscale") || name.Equals("Ethernet", StringComparison.OrdinalIgnoreCase))
            {
                important.Add($"{name}:{(isUp ? "up" : "down")}");
            }
        }

        string prefix = $"{up} up / {adapters.Count} total";
        return important.Count == 0 ? prefix : prefix + " | " + string.Join(", ", important);
    }

    private static string FormatStringArray(JsonObject o, string key)
    {
        if (o[key] is not JsonArray arr) return "";
        return string.Join(", ", arr.Select(x => x?.ToString()).Where(x => !string.IsNullOrWhiteSpace(x)));
    }

    private static string FormatDuration(long seconds)
    {
        if (seconds <= 0) return "";

        long days = seconds / 86400;
        long hours = (seconds % 86400) / 3600;
        long minutes = (seconds % 3600) / 60;

        if (days > 0) return $"{days}d {hours}h";
        if (hours > 0) return $"{hours}h {minutes}m";
        return $"{minutes}m";
    }

    private static bool IsRecent(long unix)
    {
        if (unix <= 0) return false;
        return (DateTime.Now - UnixToLocal(unix)).TotalSeconds <= 20;
    }

    private static DateTime UnixToLocal(long unix) =>
        DateTimeOffset.FromUnixTimeSeconds(unix).LocalDateTime;

    private static string FormatUnix(long unix) =>
        unix <= 0 ? "" : UnixToLocal(unix).ToString("yyyy-MM-dd HH:mm:ss");

    private static string GetString(JsonObject o, string key, string fallback = "")
    {
        if (!o.TryGetPropertyValue(key, out var v) || v == null) return fallback;
        return v.ToString();
    }

    private static long GetLong(JsonObject o, string key)
    {
        if (!o.TryGetPropertyValue(key, out var v) || v == null) return 0;
        return long.TryParse(v.ToString(), out long n) ? n : 0;
    }

    private static double GetDouble(JsonObject o, string key)
    {
        if (!o.TryGetPropertyValue(key, out var v) || v == null) return 0;
        return double.TryParse(v.ToString(), out double n) ? n : 0;
    }

    private static bool GetBool(JsonObject o, string key)
    {
        if (!o.TryGetPropertyValue(key, out var v) || v == null) return false;
        return bool.TryParse(v.ToString(), out bool b) && b;
    }

    private void RunScript(string name)
    {
        string script = System.IO.Path.Combine(BaseDir, name);
        if (!File.Exists(script))
        {
            MessageBox.Show("Missing script:\n" + script, "ForceHub", MessageBoxButton.OK, MessageBoxImage.Error);
            return;
        }

        Process.Start(new ProcessStartInfo
        {
            FileName = "powershell.exe",
            Arguments = "-NoProfile -ExecutionPolicy Bypass -File \"" + script + "\"",
            WorkingDirectory = BaseDir,
            UseShellExecute = false,
            CreateNoWindow = true
        });

        SetStatus("Started: " + name);
    }

    private void SetStatus(string msg) => StatusText.Text = $"{DateTime.Now:HH:mm:ss}  {msg}";

    private void StartServer_Click(object sender, RoutedEventArgs e) => RunScript("Start-ForceHubServer.ps1");
    private void StartTunnel_Click(object sender, RoutedEventArgs e) => RunScript("Start-ForceHubTunnel.ps1");
    private void StartGoLive_Click(object sender, RoutedEventArgs e) => RunScript("Start-GoLive-ForceHub.ps1");
    private void StopGoLive_Click(object sender, RoutedEventArgs e) => RunScript("Stop-Live-ForceHub.ps1");
    private void StopTunnel_Click(object sender, RoutedEventArgs e) => RunScript("Stop-ForceHubTunnel.ps1");
    private void StopServer_Click(object sender, RoutedEventArgs e) => RunScript("Stop-ForceHubServer.ps1");
    private void KillAll_Click(object sender, RoutedEventArgs e) => RunScript("Kill-All-ForceHub.ps1");

    private void OpenDashboard_Click(object sender, RoutedEventArgs e) =>
        Process.Start(new ProcessStartInfo("http://127.0.0.1:18001/agents") { UseShellExecute = true });

    private void OpenFolder_Click(object sender, RoutedEventArgs e) =>
        Process.Start(new ProcessStartInfo(BaseDir) { UseShellExecute = true });
}

public sealed class AgentVm
{
    public string Hostname { get; set; } = "";
    public string Status { get; set; } = "";
    public string Agent { get; set; } = "";
    public string Version { get; set; } = "";
    public string OS { get; set; } = "";
    public string CpuPercent { get; set; } = "";
    public double CpuPercentValue { get; set; }
    public string MemorySummary { get; set; } = "";
    public double MemoryPercent { get; set; }
    public string ProcessCount { get; set; } = "";
    public string Uptime { get; set; } = "";
    public string NetworkSummary { get; set; } = "";
    public string LastCheckIn { get; set; } = "";
    public JsonObject Payload { get; set; } = new();
    public string RawJson { get; set; } = "";
}

public sealed class TaskVm
{
    public string Pid { get; set; } = "";
    public string Name { get; set; } = "";
    public string CpuPercent { get; set; } = "";
    public string MemoryMb { get; set; } = "";
}

public sealed class AdapterVm
{
    public string Name { get; set; } = "";
    public string Status { get; set; } = "";
    public string Mtu { get; set; } = "";
    public string Addresses { get; set; } = "";
}

public sealed class DiskVm
{
    public string Mount { get; set; } = "";
    public string FreeGb { get; set; } = "";
    public string TotalGb { get; set; } = "";
}







