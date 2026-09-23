$ErrorActionPreference = "Stop"
$inputPath = "C:\Users\salda\Downloads\ARCHI-Artifactos-M9\Analisis_Gastos_Mensuales_ARCHI_M9.xlsx"
$outputPath = "C:\Users\salda\Downloads\ARCHI-Artifactos-M9\Analisis_Gastos_Mensuales_ARCHI_M9.pdf"
$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false
try {
    $book = $excel.Workbooks.Open($inputPath)
    foreach ($sheet in $book.Worksheets) {
        $setup = $sheet.PageSetup
        $setup.PaperSize = 9
        $setup.Orientation = 2
        $setup.Zoom = $false
        $setup.FitToPagesWide = 1
        $setup.FitToPagesTall = 1
        $setup.LeftMargin = $excel.InchesToPoints(0.35)
        $setup.RightMargin = $excel.InchesToPoints(0.35)
        $setup.TopMargin = $excel.InchesToPoints(0.45)
        $setup.BottomMargin = $excel.InchesToPoints(0.45)
        $setup.CenterHorizontally = $true
    }
    $book.Worksheets.Item("Datos").PageSetup.PrintArea = '$A$1:$H$9'
    $book.Worksheets.Item("Datos").PageSetup.PrintTitleRows = '$1:$3'
    $book.Worksheets.Item("Informe").PageSetup.PrintArea = '$A$1:$L$20'
    $book.Save()
    $book.ExportAsFixedFormat(0, $outputPath, 0, $true, $false)
    $book.Close($true)
} finally {
    $excel.Quit()
    [System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($excel) | Out-Null
}
Write-Output $outputPath
