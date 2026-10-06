# Compatibility entry point for the production deployment.
# Keep one deployment implementation so fixes are not lost between entry points.
& "$PSScriptRoot\deploy.ps1" @args
exit $LASTEXITCODE
