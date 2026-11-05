#define AppName "Tmusic"
#define AppVersion "3.0"
#ifndef Arch
  #define Arch "unknown"
#endif

[Setup]
AppId={{BBF1DDA3-C405-44F3-925A-31B0122CF45C}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Invaer Labs
DefaultDirName={localappdata}\Programs\Tmusic
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\Tmusic.exe
OutputDir=release
OutputBaseFilename=Tmusic-Windows-{#Arch}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64 arm64

[Files]
Source: "build\Tmusic.dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Tmusic"; Filename: "{app}\Tmusic.exe"
Name: "{autodesktop}\Tmusic"; Filename: "{app}\Tmusic.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\Tmusic.exe"; Description: "Launch Tmusic"; Flags: nowait postinstall skipifsilent
