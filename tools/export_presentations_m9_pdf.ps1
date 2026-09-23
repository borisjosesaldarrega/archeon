$ErrorActionPreference = "Stop"
$powerPoint = New-Object -ComObject PowerPoint.Application
try {
    $jobs = @(
        @{ Input = "C:\Users\salda\Downloads\ARCHI-Artifactos-M9\Presentacion_Seguridad_Web_ARCHI_M9.pptx"; Output = "C:\Users\salda\Downloads\ARCHI-Artifactos-M9\Presentacion_Seguridad_Web_ARCHI_M9.pdf" },
        @{ Input = "C:\Users\salda\Downloads\ARCHI-Artifactos-M9\Infografia_Embriologia_ARCHI_M9.pptx"; Output = "C:\Users\salda\Downloads\ARCHI-Artifactos-M9\Infografia_Embriologia_ARCHI_M9.pdf" }
    )
    foreach ($job in $jobs) {
        $deck = $powerPoint.Presentations.Open($job.Input, $true, $false, $false)
        $deck.SaveAs($job.Output, 32)
        $deck.Close()
        Write-Output $job.Output
    }
} finally {
    $powerPoint.Quit()
    [System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($powerPoint) | Out-Null
}
