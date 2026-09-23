#define MyAppName "ARCHEON"
#define MyAppVersion "10.0.0-rc1"
#define MyAppPublisher "DZKNIGHT COMPANY"
#define MyAppExeName "ARCHEON.exe"

[Setup]
AppId={{A3B9C5D1-E2F4-7890-ABCD-1234567890AB}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://www.dzknightcompany.com
DefaultDirName={localappdata}\Programs\ARCHEON
DisableProgramGroupPage=yes
OutputDir=Instalador_Final
OutputBaseFilename=Instalar_Archeon_v10.0_Final
Compression=lzma2/max
SolidCompression=yes
PrivilegesRequired=lowest
WizardStyle=modern
SetupIconFile=assets\logo_asitente.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=no
AppMutex=Local\ARCHEON.Core.SingleInstance
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist-release-candidate\ARCHEON\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "models\vosk-model-small-es-0.42\*"; DestDir: "{localappdata}\ARCHEON\models\vosk-model-small-es-0.42"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
