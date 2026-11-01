; Q-Review – Windows installer (Inno Setup 6)
; Built by GitHub Actions:  ISCC.exe /DMyAppVersion=0.2.4 installer\q-review.iss
; Installs for all users (Program Files, asks for admin) or only the current user (no admin) – the user chooses.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "Q-Review"
#define MyAppExe "Q-Review.exe"
#define MyPublisher "Mikkel Peter Larsen"

[Setup]
AppId={{6F1E8C2A-4B7D-4C1E-9A3F-2D5B8E7C1A90}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyPublisher}
AppPublisherURL=https://mikkelpeterlarsen.dk
VersionInfoVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes
CloseApplications=yes
RestartApplications=no
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
OutputDir=..\installer-out
OutputBaseFilename=Q-Review-Setup

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "danish"; MessagesFile: "compiler:Languages\Danish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\Q-Review\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Registry]
; Double-clicking a .qreview project opens it in Q-Review
Root: HKA; Subkey: "Software\Classes\.qreview"; ValueType: string; ValueName: ""; ValueData: "QReview.Project"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.qreview\OpenWithProgids"; ValueType: string; ValueName: "QReview.Project"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\QReview.Project"; ValueType: string; ValueName: ""; ValueData: "Q-Review project"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\QReview.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExe},0"
Root: HKA; Subkey: "Software\Classes\QReview.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExe}"" ""%1"""

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
