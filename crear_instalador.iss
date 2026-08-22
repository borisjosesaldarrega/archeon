; Script para Inno Setup V6 - Archeon AI (Versión CAJA FUERTE / OneFile)
#define MyAppName "Archeon AI"
#define MyAppVersion "9.6" 
#define MyAppPublisher "DZKNIGHT COMPANY"
#define MyAppExeName "Archeo32n.exe"

[Setup]
; --- IDENTIDAD ---
AppId={{A3B9C5D1-E2F4-7890-ABCD-1234567890AB}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://www.dzknightcompany.com

; --- INSTALACIÓN ---
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Instalador_Final
OutputBaseFilename=Instalar_Archeon_v{#MyAppVersion}_Final
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=admin

; --- APARIENCIA ---
WizardStyle=modern
; Asegúrate de tener el icono, si no, pon un ; al inicio de la siguiente línea
SetupIconFile=web\logo_asitente.ico  
UninstallDisplayIcon={app}\{#MyAppExeName}

; --- COMPATIBILIDAD ---
CloseApplications=yes
RestartApplications=yes  
AppMutex=ArcheonInstance  

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
; Usamos Default.isl para evitar el error de English.isl
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; ⚠️ AQUÍ ESTÁ EL CAMBIO CLAVE ⚠️
; En lugar de buscar una carpeta con asterisco (*), apuntamos directo al .exe
Source: "dist\Archeo32n.exe"; DestDir: "{app}"; Flags: ignoreversion

; NOTA: Como es una "Caja Fuerte", el ffmpeg y la web ya están adentro del .exe.
; No hace falta copiarlos por separado.

[UninstallDelete]
; Limpieza al desinstalar
Type: filesandordirs; Name: "{app}\*"
Type: dirifempty; Name: "{app}"

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#MyAppExeName}"; Description: "Iniciar Archeon"; Flags: nowait postinstall skipifsilent