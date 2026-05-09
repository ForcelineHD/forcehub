using System;
using System.IO;
using System.Windows;

namespace ForceHubNativeMonitorV2;

public partial class App : Application
{
    private static readonly string LogPath = @"D:\Scripts\ForceHubAgent\ForceHubNativeMonitorV2\startup.log";

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);

        try
        {
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
