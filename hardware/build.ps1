# Повний цикл: схема → ERC → нетліст → плати → DRC. Запускати з hardware/.
$ErrorActionPreference = "Stop"
$k = "$env:LOCALAPPDATA\Programs\KiCad\10.0\bin"
Push-Location "$PSScriptRoot\schematic"
python gen.py
& "$k\kicad-cli.exe" sch erc --severity-all --format report -o erc.rpt batman.kicad_sch
& "$k\kicad-cli.exe" sch export netlist --format kicadsexpr -o batman.net batman.kicad_sch | Out-Null
& "$k\kicad-cli.exe" sch export pdf -o batman.pdf batman.kicad_sch | Out-Null
Pop-Location
Push-Location "$PSScriptRoot\pcb"
if ($args -contains "-pcb") {
    & "$k\python.exe" gen_pcb.py
}
foreach ($b in "A", "B") {
    if (Test-Path "plate_$b.kicad_pcb") {
        & "$k\kicad-cli.exe" pcb drc --severity-error --format report -o "drc_$b.rpt" "plate_$b.kicad_pcb" | Select-Object -First 1
    }
}
Pop-Location
