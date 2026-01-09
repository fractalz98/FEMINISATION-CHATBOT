[Setup]
AppName=Domina
AppVersion=1.0.0
DefaultDirName={pf}\Domina
DefaultGroupName=Domina
OutputBaseFilename=DominaInstaller
Compression=lzma
SolidCompression=yes
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\Domina.exe

[Files]
Source: "..\dist\Domina\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Domina"; Filename: "{app}\Domina.exe"
Name: "{commondesktop}\Domina"; Filename: "{app}\Domina.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"; Flags: unchecked

[Run]
Filename: "{app}\Domina.exe"; Description: "Launch Domina"; Flags: nowait postinstall skipifsilent
