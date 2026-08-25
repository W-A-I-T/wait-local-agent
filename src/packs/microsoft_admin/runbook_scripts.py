"""Embedded, reviewed PowerShell runbooks.

The runtime never accepts caller-supplied script text or paths. Each definition
is paired with a reviewable SHA-256 digest and is materialized only inside a
private, per-execution directory.
"""

from __future__ import annotations

ENDPOINT_HEALTH_SCRIPT = r"""param(
    [Parameter(Mandatory = $true)]
    [string]$InputJsonPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$WarningPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'
$InformationPreference = 'SilentlyContinue'
$InputData = Get-Content -LiteralPath $InputJsonPath -Raw | ConvertFrom-Json

$ServiceNames = @('IntuneManagementExtension', 'wuauserv', 'BITS', 'Winmgmt')
$Services = @(
    foreach ($Name in $ServiceNames) {
        $Service = Get-Service -Name $Name -ErrorAction SilentlyContinue
        if ($null -ne $Service) {
            [ordered]@{
                name = $Service.Name
                display_name = $Service.DisplayName
                status = $Service.Status.ToString()
                start_type = $Service.StartType.ToString()
            }
        }
    }
)

$OperatingSystem = Get-CimInstance -ClassName Win32_OperatingSystem
$ComputerSystem = Get-CimInstance -ClassName Win32_ComputerSystem

$BitLocker = @()
if ($null -ne (Get-Command -Name Get-BitLockerVolume -ErrorAction SilentlyContinue)) {
    $BitLocker = @(
        Get-BitLockerVolume -ErrorAction SilentlyContinue | ForEach-Object {
            [ordered]@{
                mount_point = $_.MountPoint
                volume_status = $_.VolumeStatus.ToString()
                protection_status = $_.ProtectionStatus.ToString()
                encryption_percentage = $_.EncryptionPercentage
                protector_count = @($_.KeyProtector).Count
            }
        }
    )
}

$Tpm = $null
if ($null -ne (Get-Command -Name Get-Tpm -ErrorAction SilentlyContinue)) {
    $TpmValue = Get-Tpm -ErrorAction SilentlyContinue
    if ($null -ne $TpmValue) {
        $Tpm = [ordered]@{
            present = $TpmValue.TpmPresent
            ready = $TpmValue.TpmReady
            enabled = $TpmValue.TpmEnabled
            activated = $TpmValue.TpmActivated
        }
    }
}

$ComponentBasedServicingPath = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending'
$WindowsUpdatePath = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired'
$SessionManagerPath = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager'

$PendingReboot = [ordered]@{
    component_based_servicing = Test-Path -LiteralPath $ComponentBasedServicingPath
    windows_update = Test-Path -LiteralPath $WindowsUpdatePath
    pending_file_rename = $false
}
$SessionManager = Get-ItemProperty -LiteralPath $SessionManagerPath `
    -Name PendingFileRenameOperations -ErrorAction SilentlyContinue
if ($null -ne $SessionManager -and $null -ne $SessionManager.PendingFileRenameOperations) {
    $PendingReboot.pending_file_rename = $true
}

$Events = @()
if ([bool]$InputData.include_event_logs) {
    $StartTime = (Get-Date).AddHours(-[int]$InputData.event_hours)
    $Events = @(
        Get-WinEvent -FilterHashtable @{
            LogName = @('System', 'Application')
            Level = @(1, 2)
            StartTime = $StartTime
        } -MaxEvents ([int]$InputData.max_events) -ErrorAction SilentlyContinue | ForEach-Object {
            [ordered]@{
                log_name = $_.LogName
                provider_name = $_.ProviderName
                event_id = $_.Id
                level = $_.LevelDisplayName
                time_created = $_.TimeCreated.ToUniversalTime().ToString('o')
            }
        }
    )
}

[ordered]@{
    runbook_id = 'windows.endpoint_health'
    collected_at = (Get-Date).ToUniversalTime().ToString('o')
    computer = [ordered]@{
        name = $ComputerSystem.Name
        manufacturer = $ComputerSystem.Manufacturer
        model = $ComputerSystem.Model
        domain = $ComputerSystem.Domain
        part_of_domain = $ComputerSystem.PartOfDomain
    }
    operating_system = [ordered]@{
        caption = $OperatingSystem.Caption
        version = $OperatingSystem.Version
        build_number = $OperatingSystem.BuildNumber
        architecture = $OperatingSystem.OSArchitecture
        last_boot_time = $OperatingSystem.LastBootUpTime.ToUniversalTime().ToString('o')
    }
    services = $Services
    bitlocker = $BitLocker
    tpm = $Tpm
    pending_reboot = $PendingReboot
    critical_or_error_events = $Events
} | ConvertTo-Json -Depth 8 -Compress
"""
ENDPOINT_HEALTH_SHA256 = "48395278484857b41fc0bb61db7f65609fd993e46069891fb0e43b5269283522"

SERVICE_RESTART_SCRIPT = r"""param(
    [Parameter(Mandatory = $true)]
    [string]$InputJsonPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$WarningPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'
$InformationPreference = 'SilentlyContinue'
$InputData = Get-Content -LiteralPath $InputJsonPath -Raw | ConvertFrom-Json

$AllowedServices = @('IntuneManagementExtension', 'wuauserv', 'BITS')
$ServiceName = [string]$InputData.service_name
if ($AllowedServices -notcontains $ServiceName) {
    throw 'The requested Windows service is not allowlisted.'
}

$WaitSeconds = [int]$InputData.wait_seconds
if ($WaitSeconds -lt 1 -or $WaitSeconds -gt 30) {
    throw 'The service wait interval is outside the supported range.'
}

$Service = Get-Service -Name $ServiceName -ErrorAction Stop
$Before = $Service.Status.ToString()
Restart-Service -Name $ServiceName -Force -ErrorAction Stop
$Service.WaitForStatus('Running', [TimeSpan]::FromSeconds($WaitSeconds))
$Service.Refresh()

[ordered]@{
    runbook_id = 'windows.service_restart'
    completed_at = (Get-Date).ToUniversalTime().ToString('o')
    service_name = $Service.Name
    display_name = $Service.DisplayName
    before_status = $Before
    after_status = $Service.Status.ToString()
    wait_seconds = $WaitSeconds
} | ConvertTo-Json -Depth 4 -Compress
"""
SERVICE_RESTART_SHA256 = "146d8afb3acc54429912a856f3ac30ffed716999dfbb8b0a283978df6f3f56a9"
