<#
.SYNOPSIS
    Archive les fichiers de donnees et les publie dans une GitHub Release "data-latest".
    A executer depuis la racine du projet quand les donnees ont change.
    Necessite le CLI GitHub (gh) : https://cli.github.com

.EXAMPLE
    .\upload_data.ps1
#>

Set-StrictMode -Version Latest

$archive = "data.tar.gz"
$tag     = "data-latest"

Write-Host "==> Compression de backend/data/ ..."
tar -czf $archive -C backend/data .
if ($LASTEXITCODE -ne 0) { throw "Echec de la compression." }

Write-Host "==> Suppression de l'ancienne release '$tag' (si elle existe) ..."
# Ignore l'erreur si la release n'existe pas encore
$prev = $ErrorActionPreference
$ErrorActionPreference = "Continue"
gh release delete $tag --yes 2>$null
$ErrorActionPreference = $prev

Write-Host "==> Creation de la release '$tag' ..."
gh release create $tag $archive `
    --title "Data snapshot (latest)" `
    --notes "Snapshot des donnees generees par les scripts locaux." `
    --prerelease
if ($LASTEXITCODE -ne 0) { throw "Echec de la creation de la release." }

Write-Host "==> Nettoyage ..."
Remove-Item $archive

Write-Host "`n[OK] Release '$tag' mise a jour avec succes."
