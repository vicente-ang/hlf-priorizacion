# Prepara la terminal de PowerShell (Windows) para correr el agente IA del proyecto.
# Uso, desde la carpeta del proyecto:   . .\entorno.ps1     (con el punto y el espacio al inicio)
#
# Las claves NO van en este archivo: van en credenciales_aws.ps1 (ignorado por git y Docker), que se carga aqui
# si existe. Sin ese archivo se usan las de `aws configure` o las que pegues en la terminal.

if (Test-Path .\.venv\Scripts\Activate.ps1) { . .\.venv\Scripts\Activate.ps1 }
if (Test-Path .\credenciales_aws.ps1) { . .\credenciales_aws.ps1; Write-Output "Credenciales cargadas desde credenciales_aws.ps1" }

$env:AWS_REGION = "us-east-1"
$env:AWS_DEFAULT_REGION = "us-east-1"
$env:BEDROCK_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"            # agente clinico
$env:BEDROCK_MODEL_ID_REGULADOR = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"  # regulador
$env:BEDROCK_CONCURRENCIA = "4"
$env:PYTHONUTF8 = "1"        # acentos bien en la consola

try {
    $cuenta = python -c "import boto3; print(boto3.client('sts').get_caller_identity()['Account'])" 2>$null
    if ($LASTEXITCODE -eq 0 -and $cuenta) {
        $env:HLF_BUCKET = "hlf-priorizacion-ia-$cuenta"
        Write-Output "AWS ok: cuenta $cuenta, bucket $($env:HLF_BUCKET)"
    } else {
        Write-Output "Sin credenciales de AWS: el agente corre en modo simulado o desde la cache."
    }
} catch {
    Write-Output "No se pudo consultar AWS: $_"
}
Write-Output "Modelo del agente: $($env:BEDROCK_MODEL_ID)"
