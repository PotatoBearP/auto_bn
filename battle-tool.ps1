param([switch]$ScanOnly,[switch]$EnterEncounter,[string]$ImagePath,[string]$Language='en-US',[switch]$AllWords)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding $false
. "$PSScriptRoot\native.ps1"
$ocrDir = Join-Path $PSScriptRoot "artifacts\runtime\ocr"
$encounterDir = Join-Path $PSScriptRoot "artifacts\runtime\encounter"
$null = New-Item -ItemType Directory -Force -Path $ocrDir,$encounterDir
$null = [Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder,Windows.Foundation,ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$null = [Windows.Globalization.Language,Windows.Globalization,ContentType=WindowsRuntime]
$script:awaiter = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
function Await-WinRT($Operation,[Type]$ResultType) {
 $task = $script:awaiter.MakeGenericMethod($ResultType).Invoke($null,@($Operation))
 if (-not $task.Wait(15000)) { throw 'OCR timeout.' }
 return $task.Result
}
function Read-Attack([string]$Path) {
 $file = Await-WinRT ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) ([Windows.Storage.StorageFile])
 $stream = Await-WinRT ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
 try {
  $decoder = Await-WinRT ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
  $bitmap = Await-WinRT ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
  try {
   $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new($Language))
   if ($null -eq $engine) { throw 'Windows English OCR is not installed.' }
   $result = Await-WinRT ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
   $result.Text | Set-Content -LiteralPath "$ocrDir\ocr.txt" -Encoding UTF8
   [pscustomobject]@{ Angle=$result.TextAngle; Width=$bitmap.PixelWidth; Height=$bitmap.PixelHeight } | ConvertTo-Json | Set-Content "$ocrDir\ocr-meta.json" -Encoding UTF8
   foreach ($line in $result.Lines) { foreach ($word in $line.Words) {
    if ($AllWords -or $word.Text -match '^attack[!.,:]*$') {
     $r = $word.BoundingRect
     $angle = 0.0
     if ($null -ne $result.TextAngle) { $angle = [double]$result.TextAngle * [Math]::PI / 180 }
     $cx = $bitmap.PixelWidth / 2.0; $cy = $bitmap.PixelHeight / 2.0
     $dx = $r.X + $r.Width / 2.0 - $cx; $dy = $r.Y + $r.Height / 2.0 - $cy
     $x = $cx + $dx * [Math]::Cos($angle) - $dy * [Math]::Sin($angle)
     $y = $cy + $dx * [Math]::Sin($angle) + $dy * [Math]::Cos($angle)
     [pscustomobject]@{ Text=$word.Text; X=[int][Math]::Round($x); Y=[int][Math]::Round($y); Left=$r.X; Top=$r.Y; Width=$r.Width; Height=$r.Height }
    }
   } }
  } finally { if ($bitmap) { $bitmap.Dispose() } }
 } finally { $stream.Dispose() }
}
function Invoke-Encounter([bool]$Click) {
 $path = Join-Path $encounterDir 'game-before.png'
 $frame = Save-GameScreen $path
 $candidates = @(Read-Attack $path | Sort-Object Y,X)
 if ($candidates.Count -eq 0) { throw '当前游戏画面没有识别到 Attack，请显示世界地图中的遭遇战后重试。' }
 $target = $candidates[0]
 $x = $frame.X+$target.X; $y = $frame.Y+$target.Y
 $desktopBounds = [Windows.Forms.SystemInformation]::VirtualScreen
 if (-not $desktopBounds.Contains($x,$y)) { throw '目标在可见桌面之外，请调整游戏窗口。' }
 if ($Click) {
  if ([Desktop]::GetForegroundWindow() -ne $frame.Handle) { throw '前台窗口改变，已取消点击。' }
  [void][Desktop]::SetCursorPos($x,$y)
  [Desktop]::mouse_event(2,0,0,0,[UIntPtr]::Zero)
  [Desktop]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
  Start-Sleep -Milliseconds 1400
  $null = Save-GameScreen (Join-Path $encounterDir 'game-after.png')
 }
 $report = [pscustomobject]@{ Candidates=$candidates.Count; Target=$target; ScreenX=$x; ScreenY=$y; Clicked=$Click; Note='Click sent; inspect game-after.png to confirm the resulting game screen.' }
 $report | ConvertTo-Json -Depth 5 | Set-Content "$encounterDir\last-result.json" -Encoding UTF8
 return $report
}
if ($ImagePath) { @(Read-Attack ([IO.Path]::GetFullPath($ImagePath))) | ConvertTo-Json; exit }
if ($ScanOnly -or $EnterEncounter) { Invoke-Encounter ([bool]$EnterEncounter) | ConvertTo-Json -Depth 5; exit }
[Windows.Forms.Application]::EnableVisualStyles()
$form = New-Object Windows.Forms.Form
$form.Text = 'Battle Nations 自动化工具'
$form.ClientSize = New-Object Drawing.Size 580,360
$form.StartPosition = 'CenterScreen'
$form.BackColor = [Drawing.Color]::FromArgb(24,29,38)
$form.ForeColor = [Drawing.Color]::White
$form.Font = New-Object Drawing.Font 'Microsoft YaHei UI',10
$title = New-Object Windows.Forms.Label
$title.Text = '遭遇战助手'; $title.Font = New-Object Drawing.Font 'Microsoft YaHei UI',20
$title.SetBounds(24,20,530,45); $form.Controls.Add($title)
$description = New-Object Windows.Forms.Label
$description.Text = '识别世界地图上的 Attack，点击进入一个遭遇战。'
$description.SetBounds(24,76,535,30); $form.Controls.Add($description)
$scan = New-Object Windows.Forms.Button
$scan.Text = '只识别'; $scan.SetBounds(24,125,160,48)
$enter = New-Object Windows.Forms.Button
$enter.Text = '识别并进入遭遇战'; $enter.SetBounds(202,125,350,48)
foreach ($button in @($scan,$enter)) { $button.FlatStyle='Flat'; $button.BackColor=[Drawing.Color]::FromArgb(42,89,135); $form.Controls.Add($button) }
$status = New-Object Windows.Forms.TextBox
$status.Multiline=$true; $status.ReadOnly=$true; $status.ScrollBars='Vertical'
$status.BackColor=[Drawing.Color]::FromArgb(15,19,26); $status.ForeColor=[Drawing.Color]::FromArgb(200,218,232)
$status.SetBounds(24,192,528,145); $status.Text='就绪。请让游戏停留在有 Attack 按钮的世界地图。'; $form.Controls.Add($status)
function Run-Action([bool]$Click) {
 $scan.Enabled=$false; $enter.Enabled=$false
 $status.Text='正在切换到游戏并识别…'; $form.Refresh(); $form.Hide()
 try {
  $report=Invoke-Encounter $Click
  $verb=if($Click){'已发送一次点击，请查看游戏中的遭遇战界面。'}else{'识别完成，没有点击。'}
  $status.Text="$verb`r`n识别到 $($report.Candidates) 个 Attack。选择最靠上方的按钮。`r`n屏幕坐标：$($report.ScreenX), $($report.ScreenY)`r`n截图和识别结果已保存到项目目录。"
 } catch { $status.Text='操作停止：'+$_.Exception.Message }
 finally { $form.Show(); $form.Activate(); $scan.Enabled=$true; $enter.Enabled=$true }
}
$scan.Add_Click({Run-Action $false})
$enter.Add_Click({Run-Action $true})
[Windows.Forms.Application]::Run($form)
