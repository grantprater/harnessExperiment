$ErrorActionPreference = 'Stop'
$taskRoot = 'C:\Users\grant\harnessExperiment'
$taskAcl = Get-Acl -LiteralPath $taskRoot
$taskRules = @($taskAcl.Access | Where-Object {
    $_.IdentityReference.Value -eq 'Desktop-1\CodexSandboxUsers' -and
    $_.AccessControlType -eq 'Deny' -and -not $_.IsInherited -and
    ($_.FileSystemRights.ToString() -eq 'Read, Synchronize' -or [int]$_.FileSystemRights -eq -2146303863)
})
foreach ($taskRule in $taskRules) { [void]$taskAcl.RemoveAccessRuleSpecific($taskRule) }
Set-Acl -LiteralPath $taskRoot -AclObject $taskAcl
Write-Output "Removed $($taskRules.Count) probe read-deny rules"
