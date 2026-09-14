# Run All Tests - Execute all test scripts in sequence
# This master script runs all the tests and provides a summary

Write-Host "╔════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║     BEEZEY BACKEND - COMPLETE TEST SUITE                      ║" -ForegroundColor Cyan
Write-Host "║     Testing: Job Listing New Fields & Booking Validations     ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

$testResults = @()

# Test 1: Update Booking Dates Fix
Write-Host "┌─────────────────────────────────────────────────────────────┐" -ForegroundColor White
Write-Host "│ TEST 1: Update Booking Dates - Date Format Fix             │" -ForegroundColor White
Write-Host "└─────────────────────────────────────────────────────────────┘" -ForegroundColor White
try {
    & ".\scripts\test-update-booking-dates-fix.ps1"
    $testResults += @{ Name = "Test 1: Update Booking Dates"; Status = "PASSED"; Color = "Green" }
} catch {
    Write-Host "Test 1 FAILED" -ForegroundColor Red
    $testResults += @{ Name = "Test 1: Update Booking Dates"; Status = "FAILED"; Color = "Red" }
}

Write-Host "`n`n"

# Test 2: Create Job Listing with New Fields
Write-Host "┌─────────────────────────────────────────────────────────────┐" -ForegroundColor White
Write-Host "│ TEST 2: Create Job Listing - New Fields                    │" -ForegroundColor White
Write-Host "└─────────────────────────────────────────────────────────────┘" -ForegroundColor White
try {
    & ".\scripts\test-create-joblisting-new-fields.ps1"
    $testResults += @{ Name = "Test 2: Create Job Listing"; Status = "PASSED"; Color = "Green" }
} catch {
    Write-Host "Test 2 FAILED" -ForegroundColor Red
    $testResults += @{ Name = "Test 2: Create Job Listing"; Status = "FAILED"; Color = "Red" }
}

Write-Host "`n`n"

# Test 3: Create Booking with Validations
Write-Host "┌─────────────────────────────────────────────────────────────┐" -ForegroundColor White
Write-Host "│ TEST 3: Create Booking - Validation Rules                  │" -ForegroundColor White
Write-Host "└─────────────────────────────────────────────────────────────┘" -ForegroundColor White
try {
    & ".\scripts\test-create-booking-validation.ps1"
    $testResults += @{ Name = "Test 3: Create Booking Validation"; Status = "PASSED"; Color = "Green" }
} catch {
    Write-Host "Test 3 FAILED" -ForegroundColor Red
    $testResults += @{ Name = "Test 3: Create Booking Validation"; Status = "FAILED"; Color = "Red" }
}

# Summary
Write-Host "`n`n"
Write-Host "╔════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║                      TEST SUMMARY                              ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

$passedCount = ($testResults | Where-Object { $_.Status -eq "PASSED" }).Count
$failedCount = ($testResults | Where-Object { $_.Status -eq "FAILED" }).Count

foreach ($result in $testResults) {
    $statusIcon = if ($result.Status -eq "PASSED") { "[OK]" } else { "[FAIL]" }
    Write-Host "  $statusIcon $($result.Name): " -NoNewline
    Write-Host $result.Status -ForegroundColor $result.Color
}

Write-Host ""
Write-Host "Total Tests: $($testResults.Count)" -ForegroundColor White
Write-Host "Passed: $passedCount" -ForegroundColor Green
Write-Host "Failed: $failedCount" -ForegroundColor $(if ($failedCount -eq 0) { "Green" } else { "Red" })

if ($failedCount -eq 0) {
    Write-Host "`nALL TESTS PASSED!" -ForegroundColor Green
    exit 0
} else {
    Write-Host "`nSOME TESTS FAILED!" -ForegroundColor Red
    exit 1
}
