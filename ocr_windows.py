"""
Розпізнавання тексту на зображеннях вбудованим в Windows 10/11 движком (Windows.Media.Ocr) через PowerShell:
нічого встановлювати не треба, працює офлайн. Мови - ті, що встановлені в системі; українські і/ї/є/ґ рушій не читає (див. ocr_rapid).
Повертає слова з координатами у форматі, який розуміє sources.tables_from_words.
"""
import json
import os
import subprocess
import sys
import tempfile
import uuid

MAX_SIDE = 2400  # обмеження движка (OcrEngine.MaxImageDimension) з запасом

PS_SCRIPT = r'''
param([string]$ImagePath, [string]$OutPath, [string]$Lang)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.FileAccessMode, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
    $task.Wait(-1) | Out-Null
    $task.Result
}
$available = [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | ForEach-Object { $_.LanguageTag }
$engine = $null
foreach ($want in @($Lang, 'ru', 'uk', 'en-US')) {
    $tag = $available | Where-Object { $want -and $_ -like ($want + '*') } | Select-Object -First 1
    if ($tag) {
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new($tag))
        if ($engine) { $used = $tag; break }
    }
}
if (-not $engine) { throw 'Немає встановленої мови розпізнавання Windows OCR' }
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ImagePath)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$words = @()
$li = 0
foreach ($line in $result.Lines) {
    foreach ($w in $line.Words) {
        $r = $w.BoundingRect
        $words += [pscustomobject]@{ t = $w.Text; x = $r.X; y = $r.Y; w = $r.Width; h = $r.Height; l = $li }
    }
    $li++
}
$out = [pscustomobject]@{ lang = $used; available = @($available); angle = $result.TextAngle; words = $words }
[System.IO.File]::WriteAllText($OutPath, ($out | ConvertTo-Json -Depth 5 -Compress), (New-Object System.Text.UTF8Encoding($false)))
'''


LIST_SCRIPT = r'''
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
[Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | ForEach-Object { $_.LanguageTag }
'''

def _powershell():
    return os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


def available_languages(timeout=30):
    """Теги мов розпізнавання, встановлених у Windows (напр. ['en-US', 'ru']). Права адміністратора не потрібні."""
    proc = subprocess.run(
        [_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", LIST_SCRIPT],
        capture_output=True, timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace").strip() or "Windows OCR недоступний")
    return [line.strip() for line in proc.stdout.decode("utf-8", errors="replace").splitlines() if line.strip()]


def has_language(tags, prefix="uk"):
    return any(t.lower().startswith(prefix) for t in tags)


def recognize(source, lang="uk", timeout=120):
    """Слова зображення (шлях до файлу або PIL.Image): {'text','x0','x1','top','bottom'} у пікселях.
    Повертає (слова, {'lang': використана_мова, 'available': [...], 'angle': кут_тексту}).
    Мова: бажана, інакше ru, uk, en-US - що встановлено в системі."""
    from PIL import Image

    tmp = tempfile.gettempdir()
    token = uuid.uuid4().hex
    script, out_json, prepared = (os.path.join(tmp, f"tc_ocr_{token}{ext}") for ext in (".ps1", ".json", ".png"))
    scale = 1.0
    try:
        img = source if isinstance(source, Image.Image) else Image.open(source)
        img = img.convert("RGB")
        if max(img.size) > MAX_SIDE:
            scale = MAX_SIDE / max(img.size)
            img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
        img.save(prepared)
        with open(script, "w", encoding="utf-8-sig") as f:
            f.write(PS_SCRIPT)
        proc = subprocess.run(
            [_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script,
             "-ImagePath", prepared, "-OutPath", out_json, "-Lang", lang],
            capture_output=True, timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if proc.returncode != 0 or not os.path.exists(out_json):
            raise RuntimeError(proc.stderr.decode("utf-8", errors="replace").strip() or "OCR не повернув результат")
        with open(out_json, encoding="utf-8") as f:
            data = json.load(f)
    finally:
        for path in (script, out_json, prepared):
            try:
                os.remove(path)
            except OSError:
                pass

    raw = data.get("words") or []
    if isinstance(raw, dict):
        raw = [raw]
    words = [
        {
            "text": w["t"],
            "x0": w["x"] / scale,
            "x1": (w["x"] + w["w"]) / scale,
            "top": w["y"] / scale,
            "bottom": (w["y"] + w["h"]) / scale,
        }
        for w in raw
    ]
    available = data.get("available") or []
    if isinstance(available, str):
        available = [available]
    return words, {"lang": data.get("lang"), "available": available, "angle": data.get("angle")}
