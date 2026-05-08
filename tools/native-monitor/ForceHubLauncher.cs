using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Net;
using System.Web.Script.Serialization;
using System.Windows.Forms;

public class ForceHubLauncher : Form
{
    private const string BaseDir = @"D:\Scripts\ForceHubAgent";
    private const string ApiUrl = "http://127.0.0.1:18001/api/agents";
    private const string TokenFile = @"D:\Scripts\ForceHubAgent\agent_token.txt";

    private Label status;
    private Label summary;
    private Label cpuCard;
    private Label memCard;
    private Label agentCard;
    private Label liveCard;
    private DataGridView agentsGrid;
    private DataGridView tasksGrid;
    private DataGridView networkGrid;
    private Timer refreshTimer;

    private Color Bg = Color.FromArgb(8, 12, 24);
    private Color Panel = Color.FromArgb(15, 23, 42);
    private Color Panel2 = Color.FromArgb(17, 24, 39);
    private Color Border = Color.FromArgb(51, 65, 85);
    private Color TextMain = Color.FromArgb(241, 245, 249);
    private Color TextMuted = Color.FromArgb(148, 163, 184);
    private Color Accent = Color.FromArgb(59, 130, 246);
    private Color Green = Color.FromArgb(34, 197, 94);
    private Color Red = Color.FromArgb(248, 113, 113);
    private Color Amber = Color.FromArgb(245, 158, 11);

    public ForceHubLauncher()
    {
        Text = "ForceHub Native Monitor";
        Width = 1560;
        Height = 920;
        MinimumSize = new Size(1200, 760);
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Bg;
        ForeColor = TextMain;
        Font = new Font("Segoe UI", 9);

        BuildLayout();

        refreshTimer = new Timer();
        refreshTimer.Interval = 3000;
        refreshTimer.Tick += delegate { RefreshAgents(false); };

        summary.Text = "Start Server → Start Tunnel → Start Go Live → Refresh";
    }

    private void BuildLayout()
    {
        Panel sidebar = MakePanel(0, 0, 290, ClientSize.Height, Bg);
        sidebar.Anchor = AnchorStyles.Left | AnchorStyles.Top | AnchorStyles.Bottom;
        Controls.Add(sidebar);

        Label logo = new Label();
        logo.Text = "⚡ ForceHub";
        logo.Font = new Font("Segoe UI", 22, FontStyle.Bold);
        logo.ForeColor = TextMain;
        logo.Left = 24;
        logo.Top = 24;
        logo.Width = 240;
        logo.Height = 42;
        sidebar.Controls.Add(logo);

        Label sub = new Label();
        sub.Text = "Native Go Agent Monitor";
        sub.ForeColor = TextMuted;
        sub.Left = 28;
        sub.Top = 70;
        sub.Width = 230;
        sub.Height = 24;
        sidebar.Controls.Add(sub);

        int y = 120;

        AddButton(sidebar, "Start Server", "Start-ForceHubServer.ps1", y, Accent); y += 46;
        AddButton(sidebar, "Start Tunnel", "Start-ForceHubTunnel.ps1", y, Accent); y += 46;
        AddButton(sidebar, "Start Go Live 3s", "Start-GoLive-ForceHub.ps1", y, Green); y += 46;

        Button refresh = MakeButton("Refresh Now", y, Color.FromArgb(30, 41, 59));
        refresh.Click += delegate { RefreshAgents(true); };
        sidebar.Controls.Add(refresh);
        y += 46;

        Button auto = MakeButton("Start Auto Refresh", y, Color.FromArgb(30, 41, 59));
        auto.Click += delegate {
            refreshTimer.Start();
            SetStatus("Auto refresh enabled.");
            RefreshAgents(false);
        };
        sidebar.Controls.Add(auto);
        y += 46;

        Button stopAuto = MakeButton("Stop Auto Refresh", y, Color.FromArgb(30, 41, 59));
        stopAuto.Click += delegate {
            refreshTimer.Stop();
            SetStatus("Auto refresh stopped.");
        };
        sidebar.Controls.Add(stopAuto);
        y += 58;

        AddButton(sidebar, "Stop Go Live", "Stop-Live-ForceHub.ps1", y, Color.FromArgb(120, 53, 15)); y += 46;
        AddButton(sidebar, "Stop Tunnel", "Stop-ForceHubTunnel.ps1", y, Color.FromArgb(120, 53, 15)); y += 46;
        AddButton(sidebar, "Stop Server", "Stop-ForceHubServer.ps1", y, Color.FromArgb(120, 53, 15)); y += 46;
        AddButton(sidebar, "Kill All", "Kill-All-ForceHub.ps1", y, Color.FromArgb(127, 29, 29)); y += 58;

        Button browser = MakeButton("Open Web Dashboard", y, Color.FromArgb(30, 41, 59));
        browser.Click += delegate { Process.Start("http://127.0.0.1:18001/agents"); SetStatus("Opened browser dashboard."); };
        sidebar.Controls.Add(browser);
        y += 46;

        Button folder = MakeButton("Open Agent Folder", y, Color.FromArgb(30, 41, 59));
        folder.Click += delegate { Process.Start("explorer.exe", BaseDir); SetStatus("Opened agent folder."); };
        sidebar.Controls.Add(folder);

        status = new Label();
        status.Left = 24;
        status.Top = ClientSize.Height - 46;
        status.Width = 245;
        status.Height = 30;
        status.Anchor = AnchorStyles.Left | AnchorStyles.Bottom;
        status.ForeColor = Color.FromArgb(147, 197, 253);
        status.Text = "Ready.";
        sidebar.Controls.Add(status);

        Panel header = MakePanel(315, 22, ClientSize.Width - 345, 82, Panel);
        header.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;
        Controls.Add(header);

        Label title = new Label();
        title.Text = "ForceHub Agents";
        title.Font = new Font("Segoe UI", 24, FontStyle.Bold);
        title.ForeColor = TextMain;
        title.Left = 24;
        title.Top = 10;
        title.Width = 420;
        title.Height = 40;
        header.Controls.Add(title);

        summary = new Label();
        summary.Left = 26;
        summary.Top = 52;
        summary.Width = 980;
        summary.Height = 24;
        summary.ForeColor = TextMuted;
        header.Controls.Add(summary);

        int cardTop = 125;
        int cardW = 275;
        agentCard = MakeMetricCard("Agents", "--", 315, cardTop, cardW);
        liveCard = MakeMetricCard("Live Status", "--", 315 + cardW + 18, cardTop, cardW);
        cpuCard = MakeMetricCard("CPU", "--", 315 + (cardW + 18) * 2, cardTop, cardW);
        memCard = MakeMetricCard("Memory", "--", 315 + (cardW + 18) * 3, cardTop, cardW);

        Panel agentsPanel = MakePanel(315, 245, ClientSize.Width - 345, 300, Panel);
        agentsPanel.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;
        Controls.Add(agentsPanel);

        Label agentsTitle = SectionTitle("Agents", 18, 12);
        agentsPanel.Controls.Add(agentsTitle);

        agentsGrid = MakeGrid();
        agentsGrid.Left = 18;
        agentsGrid.Top = 52;
        agentsGrid.Width = agentsPanel.Width - 36;
        agentsGrid.Height = agentsPanel.Height - 70;
        agentsGrid.Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right;
        agentsGrid.SelectionChanged += delegate { LoadSelectedAgentDetails(); };
        agentsPanel.Controls.Add(agentsGrid);

        agentsGrid.Columns.Add("hostname", "Hostname");
        agentsGrid.Columns.Add("status", "Status");
        agentsGrid.Columns.Add("agent", "Agent");
        agentsGrid.Columns.Add("version", "Version");
        agentsGrid.Columns.Add("os", "OS");
        agentsGrid.Columns.Add("cpu", "CPU %");
        agentsGrid.Columns.Add("mem", "Memory");
        agentsGrid.Columns.Add("threads", "Threads");
        agentsGrid.Columns.Add("processes", "Processes");
        agentsGrid.Columns.Add("uptime", "Uptime");
        agentsGrid.Columns.Add("network", "Network");
        agentsGrid.Columns.Add("disks", "Disks");
        agentsGrid.Columns.Add("checkin", "Last Check-In");

        agentsGrid.Columns["hostname"].Width = 150;
        agentsGrid.Columns["status"].Width = 80;
        agentsGrid.Columns["agent"].Width = 135;
        agentsGrid.Columns["version"].Width = 105;
        agentsGrid.Columns["os"].Width = 290;
        agentsGrid.Columns["cpu"].Width = 75;
        agentsGrid.Columns["mem"].Width = 160;
        agentsGrid.Columns["threads"].Width = 75;
        agentsGrid.Columns["processes"].Width = 85;
        agentsGrid.Columns["uptime"].Width = 120;
        agentsGrid.Columns["network"].Width = 240;
        agentsGrid.Columns["disks"].Width = 280;
        agentsGrid.Columns["checkin"].Width = 150;

        int bottomTop = 565;
        int bottomHeight = ClientSize.Height - 595;
        int bottomWidth = ClientSize.Width - 345;
        int gap = 18;
        int leftWidth = (bottomWidth - gap) / 2;
        int rightWidth = bottomWidth - leftWidth - gap;

        Panel tasksPanel = MakePanel(315, bottomTop, leftWidth, bottomHeight, Panel);
        tasksPanel.Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left;
        Controls.Add(tasksPanel);

        Label tasksTitle = SectionTitle("Top Tasks", 18, 12);
        tasksPanel.Controls.Add(tasksTitle);

        tasksGrid = MakeGrid();
        tasksGrid.Left = 18;
        tasksGrid.Top = 52;
        tasksGrid.Width = tasksPanel.Width - 36;
        tasksGrid.Height = tasksPanel.Height - 70;
        tasksGrid.Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right;
        tasksPanel.Controls.Add(tasksGrid);

        tasksGrid.Columns.Add("pid", "PID");
        tasksGrid.Columns.Add("name", "Process");
        tasksGrid.Columns.Add("cpu", "CPU %");
        tasksGrid.Columns.Add("mem", "Memory MB");

        tasksGrid.Columns["pid"].Width = 80;
        tasksGrid.Columns["name"].Width = 300;
        tasksGrid.Columns["cpu"].Width = 80;
        tasksGrid.Columns["mem"].Width = 100;

        Panel networkPanel = MakePanel(315 + leftWidth + gap, bottomTop, rightWidth, bottomHeight, Panel);
        networkPanel.Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right;
        Controls.Add(networkPanel);

        Label networkTitle = SectionTitle("Network Adapters", 18, 12);
        networkPanel.Controls.Add(networkTitle);

        networkGrid = MakeGrid();
        networkGrid.Left = 18;
        networkGrid.Top = 52;
        networkGrid.Width = networkPanel.Width - 36;
        networkGrid.Height = networkPanel.Height - 70;
        networkGrid.Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right;
        networkPanel.Controls.Add(networkGrid);

        networkGrid.Columns.Add("name", "Adapter");
        networkGrid.Columns.Add("status", "Status");
        networkGrid.Columns.Add("mtu", "MTU");
        networkGrid.Columns.Add("ips", "IP Addresses");

        networkGrid.Columns["name"].Width = 210;
        networkGrid.Columns["status"].Width = 75;
        networkGrid.Columns["mtu"].Width = 65;
        networkGrid.Columns["ips"].Width = 360;
    }

    private Panel MakePanel(int x, int y, int w, int h, Color bg)
    {
        Panel p = new Panel();
        p.Left = x;
        p.Top = y;
        p.Width = w;
        p.Height = h;
        p.BackColor = bg;
        p.Paint += delegate(object sender, PaintEventArgs e) {
            using (Pen pen = new Pen(Border))
            {
                e.Graphics.DrawRectangle(pen, 0, 0, p.Width - 1, p.Height - 1);
            }
        };
        return p;
    }

    private Label SectionTitle(string text, int x, int y)
    {
        Label l = new Label();
        l.Text = text;
        l.Left = x;
        l.Top = y;
        l.Width = 400;
        l.Height = 30;
        l.Font = new Font("Segoe UI", 14, FontStyle.Bold);
        l.ForeColor = TextMain;
        return l;
    }

    private Label MakeMetricCard(string title, string value, int x, int y, int w)
    {
        Panel card = MakePanel(x, y, w, 92, Panel);
        card.Anchor = AnchorStyles.Top | AnchorStyles.Left;

        Label t = new Label();
        t.Text = title;
        t.Left = 18;
        t.Top = 14;
        t.Width = w - 36;
        t.Height = 22;
        t.ForeColor = TextMuted;
        t.Font = new Font("Segoe UI", 9, FontStyle.Bold);
        card.Controls.Add(t);

        Label v = new Label();
        v.Text = value;
        v.Left = 18;
        v.Top = 40;
        v.Width = w - 36;
        v.Height = 36;
        v.ForeColor = TextMain;
        v.Font = new Font("Segoe UI", 18, FontStyle.Bold);
        card.Controls.Add(v);

        Controls.Add(card);
        return v;
    }

    private Button MakeButton(string text, int y, Color bg)
    {
        Button b = new Button();
        b.Text = text;
        b.Left = 24;
        b.Top = y;
        b.Width = 238;
        b.Height = 36;
        b.BackColor = bg;
        b.ForeColor = Color.White;
        b.FlatStyle = FlatStyle.Flat;
        b.FlatAppearance.BorderColor = Color.FromArgb(71, 85, 105);
        b.Font = new Font("Segoe UI", 9, FontStyle.Bold);
        return b;
    }

    private void AddButton(Panel parent, string text, string scriptName, int y, Color bg)
    {
        Button b = MakeButton(text, y, bg);
        b.Click += delegate { RunScriptHidden(scriptName); };
        parent.Controls.Add(b);
    }

    private DataGridView MakeGrid()
    {
        DataGridView g = new DataGridView();
        g.BackgroundColor = Panel;
        g.BorderStyle = BorderStyle.None;
        g.GridColor = Color.FromArgb(30, 41, 59);
        g.EnableHeadersVisualStyles = false;
        g.ColumnHeadersDefaultCellStyle.BackColor = Color.FromArgb(2, 6, 23);
        g.ColumnHeadersDefaultCellStyle.ForeColor = Color.FromArgb(203, 213, 225);
        g.ColumnHeadersDefaultCellStyle.Font = new Font("Segoe UI", 9, FontStyle.Bold);
        g.ColumnHeadersHeight = 34;
        g.DefaultCellStyle.BackColor = Panel2;
        g.DefaultCellStyle.ForeColor = Color.FromArgb(226, 232, 240);
        g.DefaultCellStyle.SelectionBackColor = Color.FromArgb(37, 99, 235);
        g.DefaultCellStyle.SelectionForeColor = Color.White;
        g.RowHeadersVisible = false;
        g.AllowUserToAddRows = false;
        g.AllowUserToDeleteRows = false;
        g.ReadOnly = true;
        g.SelectionMode = DataGridViewSelectionMode.FullRowSelect;
        g.MultiSelect = false;
        g.RowTemplate.Height = 30;
        g.AutoSizeRowsMode = DataGridViewAutoSizeRowsMode.None;
        return g;
    }

    private void RunScriptHidden(string scriptName)
    {
        string scriptPath = Path.Combine(BaseDir, scriptName);

        if (!File.Exists(scriptPath))
        {
            MessageBox.Show("Missing script:\n" + scriptPath, "ForceHub Launcher", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }

        ProcessStartInfo psi = new ProcessStartInfo();
        psi.FileName = "powershell.exe";
        psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -File \"" + scriptPath + "\"";
        psi.WorkingDirectory = BaseDir;
        psi.UseShellExecute = false;
        psi.CreateNoWindow = true;
        psi.WindowStyle = ProcessWindowStyle.Hidden;

        Process.Start(psi);
        SetStatus("Started: " + scriptName);
    }

    private string ReadToken()
    {
        if (!File.Exists(TokenFile)) throw new Exception("Missing token file: " + TokenFile);
        string token = File.ReadAllText(TokenFile).Trim();
        if (token.Length == 0) throw new Exception("Token file is empty.");
        return token;
    }

    private string HttpGetAgents()
    {
        string token = ReadToken();

        HttpWebRequest req = (HttpWebRequest)WebRequest.Create(ApiUrl);
        req.Method = "GET";
        req.Timeout = 5000;
        req.Headers.Add("X-ForceHub-Agent-Token", token);

        using (HttpWebResponse resp = (HttpWebResponse)req.GetResponse())
        using (StreamReader sr = new StreamReader(resp.GetResponseStream()))
        {
            return sr.ReadToEnd();
        }
    }

    private void RefreshAgents(bool showPopupOnError)
    {
        try
        {
            string json = HttpGetAgents();

            JavaScriptSerializer js = new JavaScriptSerializer();
            Dictionary<string, object> root = js.Deserialize<Dictionary<string, object>>(json);

            object agentsObj;
            if (!root.TryGetValue("agents", out agentsObj)) throw new Exception("API returned no agents array.");

            ArrayList agents = agentsObj as ArrayList;
            if (agents == null) throw new Exception("Invalid agents payload.");

            string selectedHost = null;
            if (agentsGrid.SelectedRows.Count > 0)
                selectedHost = Convert.ToString(agentsGrid.SelectedRows[0].Cells["hostname"].Value);

            agentsGrid.Rows.Clear();

            int online = 0;
            double maxCpu = 0;
            double maxMemPct = 0;
            string liveText = "Offline";

            foreach (object item in agents)
            {
                Dictionary<string, object> agentRow = item as Dictionary<string, object>;
                if (agentRow == null) continue;

                Dictionary<string, object> payload = GetDict(agentRow, "payload");

                string hostname = GetStr(agentRow, "hostname");
                if (hostname == "") hostname = GetStr(payload, "hostname");

                long last = GetLong(agentRow, "last_checkin_unix");
                bool recent = IsRecent(last);
                string statusText = recent ? "Online" : "Stale";
                if (recent) online++;

                string agentName = GetStr(payload, "agent");
                string version = GetStr(payload, "version");
                string os = GetStr(payload, "os");
                double cpu = GetDouble(payload, "cpu_usage_percent");
                double memPct = GetDouble(payload, "memory_used_percent");

                if (cpu > maxCpu) maxCpu = cpu;
                if (memPct > maxMemPct) maxMemPct = memPct;

                string mem = FormatMemory(payload);
                string threads = GetLong(payload, "cpu_threads").ToString();
                string processes = GetLong(payload, "process_count").ToString();
                string uptime = FormatDuration(GetLong(payload, "uptime_seconds"));
                string network = FormatNetworkSummary(payload);
                string disks = FormatDisks(payload);
                string checkin = FormatUnix(last);

                int idx = agentsGrid.Rows.Add(hostname, statusText, agentName, version, os, cpu.ToString("0.0"), mem, threads, processes, uptime, network, disks, checkin);
                agentsGrid.Rows[idx].Tag = payload;

                agentsGrid.Rows[idx].Cells["status"].Style.ForeColor = recent ? Green : Red;
                agentsGrid.Rows[idx].Cells["cpu"].Style.ForeColor = cpu >= 80 ? Red : (cpu >= 50 ? Amber : TextMain);
                agentsGrid.Rows[idx].Cells["mem"].Style.ForeColor = memPct >= 90 ? Red : (memPct >= 75 ? Amber : TextMain);

                if (selectedHost != null && selectedHost == hostname)
                    agentsGrid.Rows[idx].Selected = true;
            }

            if (online > 0) liveText = "Live";
            if (agentsGrid.Rows.Count > 0 && agentsGrid.SelectedRows.Count == 0)
                agentsGrid.Rows[0].Selected = true;

            LoadSelectedAgentDetails();

            agentCard.Text = agents.Count.ToString();
            liveCard.Text = online + " Online";
            liveCard.ForeColor = online > 0 ? Green : Red;
            cpuCard.Text = maxCpu.ToString("0.0") + "%";
            memCard.Text = maxMemPct.ToString("0.0") + "%";

            summary.Text = "API: " + ApiUrl + " | Last refresh: " + DateTime.Now.ToString("HH:mm:ss") + " | Status: " + liveText;
            SetStatus("Refreshed.");
        }
        catch (Exception ex)
        {
            liveCard.Text = "Offline";
            liveCard.ForeColor = Red;
            SetStatus("Refresh failed.");

            if (showPopupOnError)
            {
                MessageBox.Show(
                    "Failed to refresh agents.\n\n" + ex.Message + "\n\nCheck:\n1. Start Server\n2. Start Tunnel\n3. agent_token.txt exists",
                    "ForceHub",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Warning
                );
            }
        }
    }

    private string FormatDuration(long seconds)
    {
        if (seconds <= 0) return "";

        long days = seconds / 86400;
        long hours = (seconds % 86400) / 3600;
        long minutes = (seconds % 3600) / 60;

        if (days > 0) return days + "d " + hours + "h";
        if (hours > 0) return hours + "h " + minutes + "m";
        return minutes + "m";
    }

    private string FormatNetworkSummary(Dictionary<string, object> payload)
    {
        Dictionary<string, object> network = GetDict(payload, "network");
        object adaptersObj;
        if (!network.TryGetValue("adapters", out adaptersObj)) return "";

        ArrayList adapters = adaptersObj as ArrayList;
        if (adapters == null) return "";

        int up = 0;
        List<string> important = new List<string>();

        foreach (object item in adapters)
        {
            Dictionary<string, object> a = item as Dictionary<string, object>;
            if (a == null) continue;

            bool isUp = GetBool(a, "is_up");
            if (isUp) up++;

            string name = GetStr(a, "name");
            if (name.IndexOf("VMnet8", StringComparison.OrdinalIgnoreCase) >= 0 ||
                name.IndexOf("NordLynx", StringComparison.OrdinalIgnoreCase) >= 0 ||
                name.IndexOf("Tailscale", StringComparison.OrdinalIgnoreCase) >= 0 ||
                name.Equals("Ethernet", StringComparison.OrdinalIgnoreCase))
            {
                important.Add(name + ":" + (isUp ? "up" : "down"));
            }
        }

        string prefix = up + " up / " + adapters.Count + " total";
        if (important.Count == 0) return prefix;
        return prefix + " | " + String.Join(", ", important.ToArray());
    }

    private void LoadSelectedAgentNetwork(Dictionary<string, object> payload)
    {
        Dictionary<string, object> network = GetDict(payload, "network");
        object adaptersObj;
        if (!network.TryGetValue("adapters", out adaptersObj)) return;

        ArrayList adapters = adaptersObj as ArrayList;
        if (adapters == null) return;

        foreach (object item in adapters)
        {
            Dictionary<string, object> a = item as Dictionary<string, object>;
            if (a == null) continue;

            string name = GetStr(a, "name");
            bool isUp = GetBool(a, "is_up");
            string statusText = isUp ? "Up" : "Down";
            string mtu = GetLong(a, "mtu").ToString();
            string ips = FormatStringArray(a, "addresses");

            int idx = networkGrid.Rows.Add(name, statusText, mtu, ips);
            networkGrid.Rows[idx].Cells["status"].Style.ForeColor = isUp ? Green : Red;

            if (name.IndexOf("VMnet8", StringComparison.OrdinalIgnoreCase) >= 0 ||
                name.IndexOf("NordLynx", StringComparison.OrdinalIgnoreCase) >= 0 ||
                name.IndexOf("Tailscale", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                networkGrid.Rows[idx].DefaultCellStyle.ForeColor = Color.FromArgb(147, 197, 253);
            }
        }
    }

    private void LoadSelectedAgentDetails()
    {
        tasksGrid.Rows.Clear();
        networkGrid.Rows.Clear();

        if (agentsGrid.SelectedRows.Count == 0) return;

        Dictionary<string, object> payload = agentsGrid.SelectedRows[0].Tag as Dictionary<string, object>;
        if (payload == null) return;

        LoadSelectedAgentNetwork(payload);

        object tasksObj;
        if (!payload.TryGetValue("top_tasks", out tasksObj)) return;

        ArrayList tasks = tasksObj as ArrayList;
        if (tasks == null) return;

        foreach (object item in tasks)
        {
            Dictionary<string, object> t = item as Dictionary<string, object>;
            if (t == null) continue;

            double cpu = GetDouble(t, "cpu_percent");
            long mem = GetLong(t, "memory_mb");

            int idx = tasksGrid.Rows.Add(GetLong(t, "pid"), GetStr(t, "name"), cpu.ToString("0.0"), mem);
            tasksGrid.Rows[idx].Cells["cpu"].Style.ForeColor = cpu >= 20 ? Red : (cpu >= 5 ? Amber : TextMain);
            tasksGrid.Rows[idx].Cells["mem"].Style.ForeColor = mem >= 1000 ? Amber : TextMain;
        }
    }

    private Dictionary<string, object> GetDict(Dictionary<string, object> d, string key)
    {
        if (d == null) return new Dictionary<string, object>();
        object val;
        if (!d.TryGetValue(key, out val)) return new Dictionary<string, object>();
        Dictionary<string, object> outDict = val as Dictionary<string, object>;
        return outDict ?? new Dictionary<string, object>();
    }

    private string GetStr(Dictionary<string, object> d, string key)
    {
        if (d == null) return "";
        object val;
        if (!d.TryGetValue(key, out val) || val == null) return "";
        return Convert.ToString(val);
    }

    private long GetLong(Dictionary<string, object> d, string key)
    {
        if (d == null) return 0;
        object val;
        if (!d.TryGetValue(key, out val) || val == null) return 0;
        try { return Convert.ToInt64(val); } catch { return 0; }
    }

    private double GetDouble(Dictionary<string, object> d, string key)
    {
        if (d == null) return 0;
        object val;
        if (!d.TryGetValue(key, out val) || val == null) return 0;
        try { return Convert.ToDouble(val); } catch { return 0; }
    }

    private bool GetBool(Dictionary<string, object> d, string key)
    {
        if (d == null) return false;
        object val;
        if (!d.TryGetValue(key, out val) || val == null) return false;
        try { return Convert.ToBoolean(val); } catch { return false; }
    }

    private string FormatStringArray(Dictionary<string, object> d, string key)
    {
        if (d == null) return "";
        object val;
        if (!d.TryGetValue(key, out val) || val == null) return "";

        ArrayList arr = val as ArrayList;
        if (arr == null) return Convert.ToString(val);

        List<string> parts = new List<string>();
        foreach (object item in arr)
        {
            if (item == null) continue;
            parts.Add(Convert.ToString(item));
        }

        return String.Join(", ", parts.ToArray());
    }

    private string FormatMemory(Dictionary<string, object> payload)
    {
        long used = GetLong(payload, "memory_used_mb");
        long total = GetLong(payload, "memory_total_mb");
        double pct = GetDouble(payload, "memory_used_percent");
        if (total <= 0) return "";
        return used + " / " + total + " MB (" + pct.ToString("0.0") + "%)";
    }

    private string FormatDisks(Dictionary<string, object> payload)
    {
        object disksObj;
        if (!payload.TryGetValue("disks", out disksObj)) return "";

        ArrayList disks = disksObj as ArrayList;
        if (disks == null) return "";

        List<string> parts = new List<string>();

        foreach (object item in disks)
        {
            Dictionary<string, object> d = item as Dictionary<string, object>;
            if (d == null) continue;

            string mount = GetStr(d, "mount");
            long free = GetLong(d, "free_gb");
            long total = GetLong(d, "total_gb");

            parts.Add(mount + " " + free + "GB / " + total + "GB");
        }

        return String.Join(", ", parts.ToArray());
    }

    private bool IsRecent(long unix)
    {
        if (unix <= 0) return false;
        DateTime dt = UnixToLocal(unix);
        return (DateTime.Now - dt).TotalSeconds <= 20;
    }

    private DateTime UnixToLocal(long unix)
    {
        DateTime epoch = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        return epoch.AddSeconds(unix).ToLocalTime();
    }

    private string FormatUnix(long unix)
    {
        if (unix <= 0) return "";
        return UnixToLocal(unix).ToString("yyyy-MM-dd HH:mm:ss");
    }

    private void SetStatus(string msg)
    {
        status.Text = DateTime.Now.ToString("HH:mm:ss") + "  " + msg;
    }

    [STAThread]
    public static void Main()
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new ForceHubLauncher());
    }
}
