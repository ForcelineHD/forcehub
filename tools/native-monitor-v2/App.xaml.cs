using System;
using System.IO;
using System.Windows;

namespace ForceHubNativeMonitorV2;

public partial class App : Application
{
    private static readonly string LogPath = Path.Combine(
        Environment.GetEnvironmentVariable("FORCEHUB_NATIVE_MONITOR_LOG_DIR")
            ?? Path.Combine(AppContext.BaseDirectory, "logs"),
        "startup.log");

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);

        try
        {
            var logDir = Path.GetDirectoryName(LogPath);
            if (!string.IsNullOrWhiteSpace(logDir))
                Directory.CreateDirectory(logDir);

            File.AppendAllText(LogPath, $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} App.OnStartup entered\n");

            ShutdownMode = ShutdownMode.OnMainWindowClose;

            var window = new MainWindow();
            MainWindow = window;

            File.AppendAllText(LogPath, $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} MainWindow created\n");

            window.Loaded += (_, _) =>
                File.AppendAllText(LogPath, $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} MainWindow loaded\n");

            window.Closed += (_, _) =>
                File.AppendAllText(LogPath, $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} MainWindow closed\n");

            window.Show();
            window.Activate();
            window.Focus();

            File.AppendAllText(LogPath, $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} MainWindow shown\n");
        }
        catch (Exception ex)
        {
            File.WriteAllText(LogPath, ex.ToString());
            MessageBox.Show(ex.ToString(), "ForceHubNativeMonitorV2 startup failed", MessageBoxButton.OK, MessageBoxImage.Error);
            Shutdown(1);
        }
    }
}
