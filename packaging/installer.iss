#define MyAppName "MailDesk"
#ifndef MyAppVersion
#define MyAppVersion "0.2.0"
#endif
#define MyAppPublisher "MailDesk"
#define MyAppExeName "MailDesk.exe"

[Setup]
AppId={{1E3911A1-4D5E-4B50-AE93-3D69B4F97398}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\MailDesk
DefaultGroupName=MailDesk
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=MailDesk-{#MyAppVersion}-Setup
SetupIconFile=..\assets\mailmerge.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Files]
Source: "..\dist\MailDesk.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\MailDesk"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\MailDesk"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch MailDesk"; Flags: nowait postinstall skipifsilent
