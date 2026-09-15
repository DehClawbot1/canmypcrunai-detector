# CanMyPCRunAI Local Hardware Compatibility Detector (Windows Native)
# Zero dependencies. Reads only technical system specs needed for AI compatibility.
# Does NOT collect documents, browsing history, passwords, or personal files.

param (
    [string]$PairingCode = "",
    [string]$ScanId = "",
    [string]$UploadSecret = "",
    [string]$ServerUrl = "https://canmypcrunai.online"
)

$ErrorActionPreference = "Stop"
$DetectorVersion = "1.3.2"
$SchemaVersion = "1.0.0"

function Fail-Detection([string]$Message) {
    Write-Host "`n[ERROR] $Message" -ForegroundColor Red
    Write-Host "The detector will not substitute guessed hardware values." -ForegroundColor Yellow
    exit 1
}

function Get-RegistryVramMap {
    $result = @{}
    try {
        $path = "HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\000*"
        foreach ($key in (Get-ItemProperty -Path $path -ErrorAction SilentlyContinue)) {
            if (-not $key.DriverDesc) { continue }
            $bytes = $null
            if ($null -ne $key."HardwareInformation.qwMemorySize") {
                $bytes = [int64]$key."HardwareInformation.qwMemorySize"
            } elseif ($null -ne $key."HardwareInformation.MemorySize") {
                $bytes = [int64]$key."HardwareInformation.MemorySize"
            }
            if ($bytes -and $bytes -gt 0) {
                $result[$key.DriverDesc.Trim().ToLowerInvariant()] = $bytes
            }
        }
    } catch {}
    return $result
}

function Get-SystemBackends {
    $hasVulkan = (Test-Path "$env:WINDIR\System32\vulkan-1.dll") -or [bool](Get-Command "vulkaninfo" -ErrorAction SilentlyContinue)
    $hasCuda = (Test-Path "$env:WINDIR\System32\nvcuda.dll") -or [bool](Get-Command "nvidia-smi" -ErrorAction SilentlyContinue)
    $hasRocm = (Test-Path "$env:WINDIR\System32\amdhip64.dll") -or [bool](Get-Command "rocminfo" -ErrorAction SilentlyContinue) -or ($null -ne $env:HIP_PATH) -or ($null -ne $env:ROCM_PATH)
    return @{ Vulkan = [bool]$hasVulkan; Cuda = [bool]$hasCuda; Rocm = [bool]$hasRocm }
}

if ($PairingCode) {
    if ($PairingCode -match ":") {
        $parts = $PairingCode.Split(":", 2)
        $ScanId = $parts[0].Trim()
        $UploadSecret = $parts[1].Trim()
    } else {
        $ScanId = $PairingCode.Trim()
    }
}

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "   CanMyPCRunAI Hardware Detector for Windows" -ForegroundColor Yellow
Write-Host "   Detector v$DetectorVersion (Schema v$SchemaVersion)" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Scanning technical hardware specifications..." -ForegroundColor Gray

try {
    $os = Get-CimInstance Win32_OperatingSystem
    $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
} catch {
    Fail-Detection "Windows CIM could not read operating system or CPU information: $($_.Exception.Message)"
}

if (-not $os -or -not $cpu) { Fail-Detection "Windows did not return operating system or CPU information." }

$cpuModel = (($cpu.Name -replace "\s+", " ").Trim())
$cpuVendor = "Unknown"
if ($cpuModel -match "AMD|Ryzen|Threadripper") { $cpuVendor = "AMD" }
elseif ($cpuModel -match "Intel|Core|Xeon") { $cpuVendor = "Intel" }

$osInfo = @{
    name = "Windows"
    version = ($os.Caption -replace "Microsoft Windows ", "")
    arch = "$($cpu.AddressWidth)-bit"
}
$cpuInfo = @{
    vendor = $cpuVendor
    model = $cpuModel
    physicalCores = [int]$cpu.NumberOfCores
    logicalCores = [int]$cpu.NumberOfLogicalProcessors
}

$totalRamBytes = [int64]$os.TotalVisibleMemorySize * 1024
$freeRamBytes = [int64]$os.FreePhysicalMemory * 1024
if ($totalRamBytes -le 0 -or $freeRamBytes -le 0 -or $freeRamBytes -gt $totalRamBytes) {
    Fail-Detection "Windows returned invalid physical-memory counters."
}
$memoryInfo = @{
    totalBytes = $totalRamBytes
    availableBytes = $freeRamBytes
    unified = $false
}

$systemDriveId = if ($env:SystemDrive) { $env:SystemDrive } else { "C:" }
try {
    $systemDrive = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$systemDriveId'" | Select-Object -First 1
    $freeDiskBytes = [int64]$systemDrive.FreeSpace
} catch {
    Fail-Detection "Windows could not read free disk space: $($_.Exception.Message)"
}
if ($null -eq $systemDrive -or $freeDiskBytes -lt 0) { Fail-Detection "Windows returned invalid disk-space information." }
$storageInfo = @{ freeBytes = $freeDiskBytes }

$backends = Get-SystemBackends
$gpus = @()
$nvidiaDetected = $false

# NVIDIA's own management interface is authoritative for both installed capacity
# and currently free local memory, so use it before registry/WMI fallbacks.
try {
    if (Get-Command "nvidia-smi" -ErrorAction SilentlyContinue) {
        $rows = & nvidia-smi --query-gpu=name,memory.total,memory.free,driver_version --format=csv,noheader,nounits 2>$null
        foreach ($row in $rows) {
            $parts = $row.Split(",")
            if ($parts.Count -lt 2) { continue }
            $name = $parts[0].Trim()
            $total = [int64]([double]$parts[1].Trim() * 1MB)
            $free = if ($parts.Count -ge 3) { [int64]([double]$parts[2].Trim() * 1MB) } else { $null }
            if ($total -le 0) { continue }

            $detected = @("cpu")
            if ($backends.Cuda) { $detected = @("cuda") + $detected }
            if ($backends.Vulkan) { $detected = @("vulkan") + $detected }
            $accelerated = @($detected | Where-Object { $_ -ne "cpu" })
            if ($accelerated.Count -eq 0) { $accelerated = @("cpu") }

            $gpus += @{
                vendor = "NVIDIA"
                model = $name
                driverVersion = if ($parts.Count -ge 4 -and $parts[3].Trim() -match '^\d+(\.\d+)+$') { $parts[3].Trim() } else { $null }
                dedicatedVramTotalBytes = $total
                vramTotalBytes = $total
                localMemoryBudgetBytes = $total
                localMemoryCurrentUsageBytes = if ($null -ne $free) { $total - $free } else { $null }
                localMemoryAvailableBytes = $free
                vramAvailableBytes = $free
                backends = [string[]]$accelerated
                hardwareCapabilities = [string[]]@("cuda", "vulkan", "cpu")
                detectedBackends = [string[]]$detected
                detection = @{
                    totalVramSource = "nvidia-smi"
                    availabilitySource = if ($null -ne $free) { "nvidia-smi" } else { $null }
                    confidence = "HIGH"
                }
            }
            $nvidiaDetected = $true
        }
    }
} catch {}

if (-not $nvidiaDetected) {
    $registryVram = Get-RegistryVramMap
    try { $controllers = Get-CimInstance Win32_VideoController } catch { $controllers = @() }

    foreach ($controller in $controllers) {
        $name = [string]$controller.Name
        if (-not $name -or $name -match "Remote|Virtual|RDP|Basic Render|Citrix|VNC") { continue }
        $clean = $name.Trim()
        $lower = $clean.ToLowerInvariant()

        $vram = [int64]0
        $source = "UNKNOWN"
        $confidence = "LOW"
        foreach ($key in $registryVram.Keys) {
            if ($lower.Contains($key) -or $key.Contains($lower)) {
                $vram = [int64]$registryVram[$key]
                $source = "REGISTRY_64"
                $confidence = "HIGH"
                break
            }
        }

        # AdapterRAM is a 32-bit WMI field on many drivers. It is a fallback only
        # and never promoted to high confidence for modern high-VRAM cards.
        if ($vram -le 0 -and $controller.AdapterRAM) {
            $candidate = [int64]$controller.AdapterRAM
            if ($candidate -gt 0) {
                $vram = $candidate
                $source = "WMI_ADAPTER_RAM"
                $confidence = "MEDIUM"
            }
        }

        $vendor = "Unknown"
        $caps = @("vulkan", "cpu")
        if ($clean -match "NVIDIA|GeForce|RTX|GTX|Quadro") { $vendor = "NVIDIA"; $caps = @("cuda", "vulkan", "cpu") }
        elseif ($clean -match "AMD|Radeon|RX") { $vendor = "AMD"; $caps = @("rocm", "vulkan", "cpu") }
        elseif ($clean -match "Intel|Arc|Iris|UHD|HD Graphics") { $vendor = "Intel" }

        $detected = @("cpu")
        if (($caps -contains "cuda") -and $backends.Cuda) { $detected = @("cuda") + $detected }
        if (($caps -contains "rocm") -and $backends.Rocm) { $detected = @("rocm") + $detected }
        if (($caps -contains "vulkan") -and $backends.Vulkan) { $detected = @("vulkan") + $detected }
        $accelerated = @($detected | Where-Object { $_ -ne "cpu" })
        if ($accelerated.Count -eq 0) { $accelerated = @("cpu") }

        $gpus += @{
            vendor = $vendor
            model = $clean
            dedicatedVramTotalBytes = $vram
            vramTotalBytes = $vram
            localMemoryBudgetBytes = $null
            localMemoryCurrentUsageBytes = $null
            localMemoryAvailableBytes = $null
            vramAvailableBytes = $null
            backends = [string[]]$accelerated
            hardwareCapabilities = [string[]]$caps
            detectedBackends = [string[]]$detected
            detection = @{
                totalVramSource = $source
                availabilitySource = $null
                confidence = $confidence
            }
        }
    }
}

$runtimes = @{}
$ollamaInstalled = $false
$ollamaVersion = $null
$ollamaModels = $null
$ollamaCmd = Get-Command "ollama" -ErrorAction SilentlyContinue
$ollamaPath = if ($ollamaCmd) { "ollama" } else { Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe" }
if ($ollamaCmd -or (Test-Path $ollamaPath)) {
    $ollamaInstalled = $true
    try {
        $versionOut = (& $ollamaPath --version 2>&1 | Out-String)
        if ($versionOut -match "(\d+\.\d+\.\d+[^\s]*)") { $ollamaVersion = $matches[1] }
    } catch {}
    try {
        $list = & $ollamaPath list 2>$null
        if ($list) {
            $ollamaModels = @($list | Select-Object -Skip 1 | ForEach-Object {
                $line = ($_ -replace "\s+", " ").Trim()
                if ($line) { $line.Split(" ")[0] }
            } | Where-Object { $_ })
        }
    } catch {}
}
$runtimes["ollama"] = @{
    installed = [bool]$ollamaInstalled
    version = $ollamaVersion
    models = $ollamaModels
}

$hardware = @{
    schemaVersion = $SchemaVersion
    detectorVersion = $DetectorVersion
    os = $osInfo
    cpu = $cpuInfo
    memory = $memoryInfo
    gpus = $gpus
    storage = $storageInfo
    runtimes = $runtimes
}

Write-Host "`nDetected Specifications:" -ForegroundColor Green
Write-Host "  CPU:  $($cpuInfo.model)"
Write-Host "  RAM:  $([math]::Round($totalRamBytes / 1GB, 1)) GB installed"
foreach ($gpu in $gpus) {
    if ($gpu.vramTotalBytes -gt 0) {
        Write-Host "  GPU:  $($gpu.model) ($([math]::Round($gpu.vramTotalBytes / 1GB, 1)) GB dedicated VRAM)" -ForegroundColor Yellow
    } else {
        Write-Host "  GPU:  $($gpu.model) (dedicated VRAM could not be measured)" -ForegroundColor Yellow
    }
}
Write-Host "  Disk: $([math]::Round($freeDiskBytes / 1GB, 1)) GB free"

if (-not $ScanId) {
    Write-Host "`nEnter the pairing code shown by CanMyPCRunAI, or press Enter to save locally." -ForegroundColor Cyan
    $typed = Read-Host "Pairing Code"
    if ($typed) {
        if ($typed -match ":") {
            $parts = $typed.Split(":", 2)
            $ScanId = $parts[0].Trim()
            $UploadSecret = $parts[1].Trim()
        } else {
            $ScanId = $typed.Trim()
            $UploadSecret = (Read-Host "Upload Secret").Trim()
        }
    }
}

if ($ScanId) {
    if (-not $UploadSecret) { Fail-Detection "An upload secret is required to pair this scan." }
    $targetUrl = "$($ServerUrl.TrimEnd('/'))/api/scan/$ScanId"
    $payload = @{
        schemaVersion = $SchemaVersion
        detectorVersion = $DetectorVersion
        uploadSecret = $UploadSecret
        hardware = $hardware
    }
    $json = $payload | ConvertTo-Json -Depth 10
    $headers = @{
        "User-Agent" = "CanMyPCRunAI-Detector/$DetectorVersion"
        "x-upload-secret" = $UploadSecret
        "Authorization" = "Bearer $UploadSecret"
    }

    try {
        $response = Invoke-RestMethod -Uri $targetUrl -Method Post -Body ([Text.Encoding]::UTF8.GetBytes($json)) -ContentType "application/json; charset=utf-8" -Headers $headers -TimeoutSec 20
        if (-not $response.success) { throw "Server rejected the scan." }
        Write-Host "`nSUCCESS! Hardware received and verified." -ForegroundColor Green
        $resultsUrl = "$($ServerUrl.TrimEnd('/'))/results/$ScanId"
        try { Start-Process $resultsUrl } catch { Write-Host "Open: $resultsUrl" -ForegroundColor Cyan }
    } catch {
        Write-Host "`n[ERROR] Could not upload the hardware profile to $targetUrl" -ForegroundColor Red
        Write-Host $_.Exception.Message -ForegroundColor Yellow
        exit 1
    }
} else {
    $outPath = Join-Path (Get-Location) "hardware_profile.json"
    $hardware | ConvertTo-Json -Depth 10 | Out-File -FilePath $outPath -Encoding utf8
    Write-Host "`nHardware profile saved to $outPath" -ForegroundColor Cyan
}
