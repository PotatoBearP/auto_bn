Add-Type -AssemblyName System.Windows.Forms,System.Drawing,System.Runtime.WindowsRuntime
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class Desktop {
 [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left,Top,Right,Bottom; }
 [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X,Y; }
 [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int n);
 [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h,out RECT r);
 [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h,ref POINT p);
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
 [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);
}
'@
[void][Desktop]::SetProcessDPIAware()
function Get-Game {
 $games = @(Get-Process | Where-Object { $_.ProcessName -eq 'BattleNations' -and $_.MainWindowHandle -ne 0 })
 if ($games.Count -ne 1) { throw '需要一个已打开的 Battle Nations 游戏窗口。' }
 return $games[0]
}
function Save-GameScreen([string]$Path) {
 $game = Get-Game
 [void][Desktop]::ShowWindow($game.MainWindowHandle,9)
 [void][Desktop]::SetForegroundWindow($game.MainWindowHandle)
 Start-Sleep -Milliseconds 700
 if ([Desktop]::GetForegroundWindow() -ne $game.MainWindowHandle) { throw '游戏未获得前台焦点，请切到游戏后重试。' }
 $rect = New-Object Desktop+RECT
 $point = New-Object Desktop+POINT
 [void][Desktop]::GetClientRect($game.MainWindowHandle,[ref]$rect)
 [void][Desktop]::ClientToScreen($game.MainWindowHandle,[ref]$point)
 $width = $rect.Right - $rect.Left; $height = $rect.Bottom - $rect.Top
 if ($width -le 0 -or $height -le 0) { throw '游戏窗口尺寸无效。' }
 $bitmap = New-Object Drawing.Bitmap $width,$height
 $graphics = [Drawing.Graphics]::FromImage($bitmap)
 try { $graphics.CopyFromScreen($point.X,$point.Y,0,0,$bitmap.Size); $bitmap.Save($Path) }
 finally { $graphics.Dispose(); $bitmap.Dispose() }
 return [pscustomobject]@{ Handle=$game.MainWindowHandle; X=$point.X; Y=$point.Y; Width=$width; Height=$height }
}
