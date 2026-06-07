#define AppName "Local Router Minimal"
#define AppVersion "0.1.0"
#define AppExe "LocalRouterMinimal.exe"

[Setup]
AppId={{A7D5B06D-27B4-43B3-9F3D-B38DD236EB15}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputBaseFilename=LocalRouterMinimalSetup
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "dist\LocalRouterMinimal\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
