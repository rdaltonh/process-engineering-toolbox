# Install the Process Engineering Toolbox as a desktop app (Windows, per-user).
#
#   powershell -ExecutionPolicy Bypass -File desktop\Install.ps1             # install
#   powershell -ExecutionPolicy Bypass -File desktop\Install.ps1 -Uninstall  # remove shortcuts
#
# Creates the .venv and installs dependencies if missing, then adds
# "Process Engineering Toolbox" shortcuts to the Desktop and Start menu.
# Nothing is copied: the shortcuts run the repo in place, so `git pull` updates the app.
# No admin rights needed.

param([switch]$Uninstall)
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$Name = 'Process Engineering Toolbox'
$Links = @(
    (Join-Path ([Environment]::GetFolderPath('Desktop')) "$Name.lnk"),
    (Join-Path ([Environment]::GetFolderPath('Programs')) "$Name.lnk")
)

if ($Uninstall) {
    foreach ($l in $Links) { if (Test-Path $l) { Remove-Item $l; Write-Host "Removed $l" } }
    Write-Host 'Shortcuts removed. The repo, .venv and %LOCALAPPDATA%\ProcessToolbox are untouched.'
    return
}

$Py = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Py)) {
    Write-Host 'Creating Python environment (.venv)...'
    & python -m venv (Join-Path $Root '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'python -m venv failed. Is Python 3.11+ on PATH?' }
    Write-Host 'Installing dependencies (a few minutes the first time)...'
    & $Py -m pip install -e "$Root[dev,desktop]"
    if ($LASTEXITCODE -ne 0) { throw 'pip install failed.' }
    # Same stamp the launcher checks, so the first launch skips a redundant sync.
    $hash = (Get-FileHash (Join-Path $Root 'pyproject.toml') -Algorithm SHA256).Hash.ToLower()
    Set-Content -Path (Join-Path $Root '.venv\toolbox-deps.sha256') -Value $hash -NoNewline -Encoding ascii
}

# Must match APP_ID in launch_toolbox.pyw: lets Windows match the running window
# to this shortcut (taskbar icon, pinning). WScript.Shell can't set it, so use
# the shell property store directly.
$AppId = 'ProcessEngineeringToolbox.Desktop'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class LnkAppId {
    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IPropertyStore {
        [PreserveSig] int GetCount(out uint count);
        [PreserveSig] int GetAt(uint index, out PROPERTYKEY key);
        [PreserveSig] int GetValue(ref PROPERTYKEY key, out PROPVARIANT value);
        [PreserveSig] int SetValue(ref PROPERTYKEY key, ref PROPVARIANT value);
        [PreserveSig] int Commit();
    }
    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    struct PROPERTYKEY { public Guid fmtid; public uint pid; }
    [StructLayout(LayoutKind.Explicit)]
    struct PROPVARIANT { [FieldOffset(0)] public ushort vt; [FieldOffset(8)] public IntPtr p; [FieldOffset(16)] public long pad; }
    [DllImport("shell32.dll")]
    static extern int SHGetPropertyStoreFromParsingName([MarshalAs(UnmanagedType.LPWStr)] string path,
        IntPtr bindCtx, int flags, ref Guid riid, out IPropertyStore store);

    public static void Set(string lnkPath, string appId) {
        Guid iid = new Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99");
        IPropertyStore store;
        Marshal.ThrowExceptionForHR(SHGetPropertyStoreFromParsingName(lnkPath, IntPtr.Zero, 2 /* GPS_READWRITE */, ref iid, out store));
        // PKEY_AppUserModel_ID
        PROPERTYKEY key = new PROPERTYKEY { fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 5 };
        PROPVARIANT value = new PROPVARIANT { vt = 31 /* VT_LPWSTR */, p = Marshal.StringToCoTaskMemUni(appId) };
        try {
            Marshal.ThrowExceptionForHR(store.SetValue(ref key, ref value));
            Marshal.ThrowExceptionForHR(store.Commit());
        } finally {
            Marshal.FreeCoTaskMem(value.p);
            Marshal.ReleaseComObject(store);
        }
    }
}
'@

$Shell = New-Object -ComObject WScript.Shell
foreach ($l in $Links) {
    $s = $Shell.CreateShortcut($l)
    $s.TargetPath = Join-Path $Root '.venv\Scripts\pythonw.exe'
    $s.Arguments = '"' + (Join-Path $PSScriptRoot 'launch_toolbox.pyw') + '"'
    $s.WorkingDirectory = $Root
    $s.IconLocation = (Join-Path $PSScriptRoot 'toolbox.ico') + ',0'
    $s.Description = 'Launch the Process Engineering Toolbox'
    $s.Save()
    [LnkAppId]::Set($l, $AppId)
    Write-Host "Created $l"
}
Write-Host "`nDone. Launch '$Name' from the Desktop or Start menu (right-click > Pin to taskbar if you like)."
