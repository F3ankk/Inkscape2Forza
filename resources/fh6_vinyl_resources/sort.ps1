$root = Get-Location
$outDir = Join-Path $root "json"

if (!(Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir | Out-Null
}

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

Get-ChildItem -Directory | ForEach-Object {
    $folder = $_.FullName
    $folderName = $_.Name
    $items = @()

    Get-ChildItem -Path $folder -File | ForEach-Object {
        $name = $_.Name

        if ($name -match '^\d+$') {
            $id = [int]$name
            $jsonText = Get-Content -Path $_.FullName -Raw
            $obj = $jsonText | ConvertFrom-Json

            $flat = [PSCustomObject]@{
                id = $id
            }

            $obj.PSObject.Properties | ForEach-Object {
                $flat | Add-Member -MemberType NoteProperty -Name $_.Name -Value $_.Value
            }

            $items += $flat
        }
    }

    $sorted = $items | Sort-Object id
    $outputPath = Join-Path $outDir "$folderName.json"

    [System.IO.File]::WriteAllText($outputPath, ($sorted | ConvertTo-Json -Depth 20), $utf8NoBom)
}
