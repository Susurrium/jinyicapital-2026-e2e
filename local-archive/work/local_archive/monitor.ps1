param([int]$AuditProcessId)
$auditStarted = Get-Date
$peakBytes = 0L
$samples = 0
while ($true) {
    $auditProcess = Get-Process -Id $AuditProcessId -ErrorAction SilentlyContinue
    if ($null -eq $auditProcess) { break }
    $peakBytes = [Math]::Max($peakBytes, $auditProcess.PeakWorkingSet64)
    $samples += 1
    Start-Sleep -Seconds 1
}
$measurement = [ordered]@{
    process_id = $AuditProcessId
    peak_working_set_bytes = $peakBytes
    samples = $samples
    sampling_started_at = $auditStarted.ToString('o')
    measurement = 'Windows Get-Process PeakWorkingSet64; lifetime high-water mark sampled while the process remained alive'
}
$measurement | ConvertTo-Json | Set-Content -LiteralPath 'work/local_archive/resource-measurement.json' -Encoding utf8
$measurement | ConvertTo-Json
