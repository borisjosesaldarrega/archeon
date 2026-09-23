"""Small deterministic message catalog for all supported ARCHEON locales."""

from __future__ import annotations

from .language import normalize_locale


CORE_MESSAGES = {
    "es": ("Estado del sistema obtenido.", "Todavía no tengo una herramienta segura para esa orden.", "La herramienta no pudo verificarse.", "La inteligencia local no pudo responder.", "El modelo no produjo una respuesta.", "Todavía no puedo leer ese adjunto de forma verificada; no inventaré su contenido."),
    "en": ("System status retrieved.", "I do not have a safe tool for that request yet.", "The tool result could not be verified.", "Local intelligence could not respond.", "The model produced no response.", "I cannot read that attachment with verification yet, so I will not guess its contents."),
    "pt": ("Estado do sistema obtido.", "Ainda não tenho uma ferramenta segura para esse pedido.", "Não foi possível verificar o resultado da ferramenta.", "A inteligência local não conseguiu responder.", "O modelo não produziu uma resposta.", "Ainda não posso ler esse anexo de forma verificada; não vou inventar o conteúdo."),
    "fr": ("État du système obtenu.", "Je ne dispose pas encore d’un outil sûr pour cette demande.", "Le résultat de l’outil n’a pas pu être vérifié.", "L’intelligence locale n’a pas pu répondre.", "Le modèle n’a produit aucune réponse.", "Je ne peux pas encore lire cette pièce jointe de manière vérifiée; je n’en inventerai pas le contenu."),
    "de": ("Systemstatus abgerufen.", "Für diese Anfrage habe ich noch kein sicheres Werkzeug.", "Das Werkzeugergebnis konnte nicht verifiziert werden.", "Die lokale Intelligenz konnte nicht antworten.", "Das Modell hat keine Antwort erzeugt.", "Ich kann diesen Anhang noch nicht verifiziert lesen und werde seinen Inhalt nicht erfinden."),
    "it": ("Stato del sistema ottenuto.", "Non ho ancora uno strumento sicuro per questa richiesta.", "Non è stato possibile verificare il risultato dello strumento.", "L’intelligenza locale non è riuscita a rispondere.", "Il modello non ha prodotto una risposta.", "Non posso ancora leggere questo allegato in modo verificato; non ne inventerò il contenuto."),
    "zh": ("已获取系统状态。", "我目前还没有可安全执行此请求的工具。", "无法验证工具结果。", "本地智能无法回答。", "模型没有生成回答。", "我暂时无法可靠地读取该附件，因此不会猜测其内容。"),
    "ja": ("システム状態を取得しました。", "この依頼を安全に実行できるツールはまだありません。", "ツールの結果を検証できませんでした。", "ローカル知能が応答できませんでした。", "モデルは応答を生成しませんでした。", "この添付ファイルはまだ検証済みの方法で読めないため、内容を推測しません。"),
    "ko": ("시스템 상태를 가져왔습니다.", "이 요청을 안전하게 처리할 도구가 아직 없습니다.", "도구 결과를 검증할 수 없습니다.", "로컬 지능이 응답하지 못했습니다.", "모델이 응답을 생성하지 않았습니다.", "이 첨부 파일은 아직 검증된 방식으로 읽을 수 없으므로 내용을 추측하지 않겠습니다."),
    "ru": ("Состояние системы получено.", "У меня пока нет безопасного инструмента для этого запроса.", "Не удалось проверить результат инструмента.", "Локальный интеллект не смог ответить.", "Модель не сформировала ответ.", "Я пока не могу достоверно прочитать это вложение и не буду придумывать его содержимое."),
    "ar": ("تم الحصول على حالة النظام.", "لا أملك بعد أداة آمنة لتنفيذ هذا الطلب.", "تعذر التحقق من نتيجة الأداة.", "تعذر على الذكاء المحلي الرد.", "لم يُنتج النموذج إجابة.", "لا أستطيع بعد قراءة هذا المرفق بطريقة موثوقة، لذلك لن أخمّن محتواه."),
    "hi": ("सिस्टम की स्थिति प्राप्त हो गई।", "इस अनुरोध के लिए अभी मेरे पास कोई सुरक्षित टूल नहीं है।", "टूल के परिणाम की पुष्टि नहीं हो सकी।", "स्थानीय इंटेलिजेंस उत्तर नहीं दे सकी।", "मॉडल ने कोई उत्तर नहीं बनाया।", "मैं अभी इस अटैचमेंट को सत्यापित रूप से नहीं पढ़ सकता, इसलिए इसकी सामग्री का अनुमान नहीं लगाऊँगा।"),
}

_KEY_INDEX = {
    "status": 0, "unsupported": 1, "unverified": 2, "model_error": 3,
    "empty": 4, "attachment_unavailable": 5,
}

IDENTITY_MESSAGES = {
    "es": "Mi creador es Boris Saldarrega, creador y fundador de DZKnight Company. Mi desarrollo comenzó en enero de 2020 como un chatbot con mensajes predefinidos. Desde entonces he evolucionado año tras año mediante pruebas, errores y mejoras continuas hasta convertirme en el asistente que soy hoy.",
    "en": "My creator is Boris Saldarrega, creator and founder of DZKnight Company. My development began in January 2020 as a chatbot with predefined messages. Since then, I have evolved year after year through testing, errors and continuous improvements into the assistant I am today.",
    "pt": "Meu criador é Boris Saldarrega, criador e fundador da DZKnight Company. Meu desenvolvimento começou em janeiro de 2020 como um chatbot com mensagens predefinidas. Desde então, evoluí ano após ano com testes, erros e melhorias contínuas até me tornar o assistente que sou hoje.",
    "fr": "Mon créateur est Boris Saldarrega, créateur et fondateur de DZKnight Company. Mon développement a commencé en janvier 2020 comme chatbot à messages prédéfinis. Depuis, j’évolue chaque année grâce aux essais, aux erreurs et aux améliorations continues pour devenir l’assistant que je suis aujourd’hui.",
    "de": "Mein Schöpfer ist Boris Saldarrega, Gründer von DZKnight Company. Meine Entwicklung begann im Januar 2020 als Chatbot mit vordefinierten Nachrichten. Seitdem habe ich mich durch Tests, Fehler und kontinuierliche Verbesserungen Jahr für Jahr zu dem Assistenten entwickelt, der ich heute bin.",
    "it": "Il mio creatore è Boris Saldarrega, creatore e fondatore di DZKnight Company. Il mio sviluppo è iniziato a gennaio 2020 come chatbot con messaggi predefiniti. Da allora mi sono evoluto anno dopo anno attraverso prove, errori e miglioramenti continui fino a diventare l’assistente che sono oggi.",
    "zh": "我的创建者是 DZKnight Company 的创始人 Boris Saldarrega。我的开发始于 2020 年 1 月，最初是一个使用预设消息的聊天机器人。此后，我通过逐年的测试、纠错和持续改进，逐步发展成今天的助手。",
    "ja": "私の開発者は、DZKnight Company の創設者 Boris Saldarrega です。開発は2020年1月、定型メッセージを使うチャットボットとして始まりました。それ以来、試行錯誤と継続的な改善を重ね、現在のアシスタントへと進化してきました。",
    "ko": "저의 개발자는 DZKnight Company의 창립자 Boris Saldarrega입니다. 개발은 2020년 1월 미리 정의된 메시지를 사용하는 챗봇으로 시작되었습니다. 이후 해마다 테스트와 시행착오, 지속적인 개선을 거쳐 오늘날의 어시스턴트로 발전했습니다.",
    "ru": "Мой создатель — Борис Сальдаррега, основатель DZKnight Company. Моя разработка началась в январе 2020 года с чат-бота с заранее заданными сообщениями. С тех пор благодаря тестированию, исправлению ошибок и постоянным улучшениям я развивался год за годом и стал нынешним помощником.",
    "ar": "منشئي هو بوريس سالداريغا، مؤسس شركة DZKnight Company. بدأ تطويري في يناير 2020 كروبوت محادثة يعتمد على رسائل محددة مسبقًا. ومنذ ذلك الحين تطورت عامًا بعد عام عبر الاختبارات والأخطاء والتحسين المستمر حتى أصبحت المساعد الذي أنا عليه اليوم.",
    "hi": "मेरे निर्माता Boris Saldarrega हैं, जो DZKnight Company के संस्थापक हैं। मेरा विकास जनवरी 2020 में पहले से तय संदेशों वाले चैटबॉट के रूप में शुरू हुआ था। तब से परीक्षण, गलतियों और निरंतर सुधार के माध्यम से मैं हर वर्ष विकसित होकर आज का असिस्टेंट बना हूँ।",
}

# Localized section names and concise guidance. Detailed answers can still be
# generated by ARCHI, but deterministic help never changes language unexpectedly.
HELP_CATALOG = {
    "es": ("Configuración", "General", "Personalización", "Activación", "Voz y audio", "Privacidad y datos", "ARCHI", "Abre ☰ → {settings} → {section}. {detail} Después guarda los cambios.", "Abre ☰ → Configuración. Allí encontrarás General, Personalización, Activación, Voz y audio, Privacidad y datos y ARCHI."),
    "en": ("Settings", "General", "Personalization", "Activation", "Voice and audio", "Privacy and data", "ARCHI", "Open ☰ → {settings} → {section}. {detail} Then save your changes.", "Open ☰ → Settings. You will find General, Personalization, Activation, Voice and audio, Privacy and data, and ARCHI."),
    "pt": ("Configurações", "Geral", "Personalização", "Ativação", "Voz e áudio", "Privacidade e dados", "ARCHI", "Abra ☰ → {settings} → {section}. {detail} Depois salve as alterações.", "Abra ☰ → Configurações. Lá você encontrará Geral, Personalização, Ativação, Voz e áudio, Privacidade e dados e ARCHI."),
    "fr": ("Paramètres", "Général", "Personnalisation", "Activation", "Voix et audio", "Confidentialité et données", "ARCHI", "Ouvrez ☰ → {settings} → {section}. {detail} Enregistrez ensuite les modifications.", "Ouvrez ☰ → Paramètres. Vous y trouverez Général, Personnalisation, Activation, Voix et audio, Confidentialité et données et ARCHI."),
    "de": ("Einstellungen", "Allgemein", "Personalisierung", "Aktivierung", "Sprache und Audio", "Datenschutz und Daten", "ARCHI", "Öffne ☰ → {settings} → {section}. {detail} Speichere danach die Änderungen.", "Öffne ☰ → Einstellungen. Dort findest du Allgemein, Personalisierung, Aktivierung, Sprache und Audio, Datenschutz und Daten sowie ARCHI."),
    "it": ("Impostazioni", "Generale", "Personalizzazione", "Attivazione", "Voce e audio", "Privacy e dati", "ARCHI", "Apri ☰ → {settings} → {section}. {detail} Poi salva le modifiche.", "Apri ☰ → Impostazioni. Troverai Generale, Personalizzazione, Attivazione, Voce e audio, Privacy e dati e ARCHI."),
    "zh": ("设置", "常规", "个性化", "激活", "语音和音频", "隐私和数据", "ARCHI", "打开 ☰ → {settings} → {section}。{detail} 然后保存更改。", "打开 ☰ → 设置。这里包括常规、个性化、激活、语音和音频、隐私和数据以及 ARCHI。"),
    "ja": ("設定", "一般", "カスタマイズ", "起動", "音声とオーディオ", "プライバシーとデータ", "ARCHI", "☰ → {settings} → {section} を開きます。{detail} その後、変更を保存してください。", "☰ → 設定を開きます。一般、カスタマイズ、起動、音声とオーディオ、プライバシーとデータ、ARCHIがあります。"),
    "ko": ("설정", "일반", "개인 설정", "호출", "음성 및 오디오", "개인정보 및 데이터", "ARCHI", "☰ → {settings} → {section}을 여세요. {detail} 그런 다음 변경 사항을 저장하세요.", "☰ → 설정을 여세요. 일반, 개인 설정, 호출, 음성 및 오디오, 개인정보 및 데이터, ARCHI가 있습니다."),
    "ru": ("Настройки", "Общие", "Персонализация", "Активация", "Голос и звук", "Конфиденциальность и данные", "ARCHI", "Откройте ☰ → {settings} → {section}. {detail} Затем сохраните изменения.", "Откройте ☰ → Настройки. Там находятся Общие, Персонализация, Активация, Голос и звук, Конфиденциальность и данные и ARCHI."),
    "ar": ("الإعدادات", "عام", "التخصيص", "التنشيط", "الصوت", "الخصوصية والبيانات", "ARCHI", "افتح ☰ ← {settings} ← {section}. {detail} ثم احفظ التغييرات.", "افتح ☰ ← الإعدادات. ستجد عام والتخصيص والتنشيط والصوت والخصوصية والبيانات وARCHI."),
    "hi": ("सेटिंग्स", "सामान्य", "वैयक्तिकरण", "सक्रियण", "आवाज़ और ऑडियो", "गोपनीयता और डेटा", "ARCHI", "☰ → {settings} → {section} खोलें। {detail} फिर बदलाव सहेजें।", "☰ → सेटिंग्स खोलें। यहाँ सामान्य, वैयक्तिकरण, सक्रियण, आवाज़ और ऑडियो, गोपनीयता और डेटा तथा ARCHI मिलेंगे।"),
}

HELP_DETAILS = {
    "es": ("Elige las opciones de interfaz, conversación e inicio.", "Cambia tema, color, fondo, logo, reloj y accesibilidad.", "Cambia el nombre de activación y la activación local por voz.", "Elige un micrófono, dispositivo de salida y voz instalados.", "Controla la sincronización sin exponer archivos ni audio locales.", "Ajusta rapidez y personalidad; los archivos internos permanecen protegidos."),
    "en": ("Choose the interface, conversation and startup options.", "Change the theme, accent color, background, logo, clock and accessibility.", "Change the wake name and local voice activation.", "Choose an installed microphone, output device and voice.", "Control preference sync without exposing local files or audio.", "Adjust speed and personality; internal model files remain protected."),
    "pt": ("Escolha as opções de interface, conversa e inicialização.", "Altere tema, cor, fundo, logo, relógio e acessibilidade.", "Altere o nome de ativação e a ativação local por voz.", "Escolha um microfone, dispositivo de saída e voz instalados.", "Controle a sincronização sem expor arquivos ou áudio locais.", "Ajuste velocidade e personalidade; os arquivos internos permanecem protegidos."),
    "fr": ("Choisissez les options d’interface, de conversation et de démarrage.", "Modifiez le thème, la couleur, l’arrière-plan, le logo, l’horloge et l’accessibilité.", "Modifiez le nom d’activation et l’activation vocale locale.", "Choisissez un microphone, un périphérique de sortie et une voix installés.", "Contrôlez la synchronisation sans exposer les fichiers ni l’audio locaux.", "Réglez la vitesse et la personnalité; les fichiers internes restent protégés."),
    "de": ("Wähle Optionen für Oberfläche, Unterhaltung und Start.", "Ändere Design, Farbe, Hintergrund, Logo, Uhr und Barrierefreiheit.", "Ändere Aktivierungsnamen und lokale Sprachaktivierung.", "Wähle ein installiertes Mikrofon, Ausgabegerät und eine Stimme.", "Steuere die Synchronisierung, ohne lokale Dateien oder Audio offenzulegen.", "Passe Geschwindigkeit und Persönlichkeit an; interne Dateien bleiben geschützt."),
    "it": ("Scegli le opzioni di interfaccia, conversazione e avvio.", "Modifica tema, colore, sfondo, logo, orologio e accessibilità.", "Modifica il nome di attivazione e l’attivazione vocale locale.", "Scegli un microfono, un dispositivo di uscita e una voce installati.", "Controlla la sincronizzazione senza esporre file o audio locali.", "Regola velocità e personalità; i file interni rimangono protetti."),
    "zh": ("选择界面、对话和启动选项。", "更改主题、强调色、背景、徽标、时钟和无障碍选项。", "更改唤醒名称和本地语音激活。", "选择已安装的麦克风、输出设备和语音。", "控制同步，同时不暴露本地文件或音频。", "调整速度和个性；内部模型文件保持受保护状态。"),
    "ja": ("インターフェース、会話、起動の設定を選びます。", "テーマ、色、背景、ロゴ、時計、アクセシビリティを変更します。", "呼びかけ名とローカル音声起動を変更します。", "インストール済みのマイク、出力デバイス、音声を選びます。", "ローカルのファイルや音声を公開せずに同期を管理します。", "速度と個性を調整します。内部モデルファイルは保護されます。"),
    "ko": ("인터페이스, 대화 및 시작 옵션을 선택합니다.", "테마, 색상, 배경, 로고, 시계 및 접근성을 변경합니다.", "호출 이름과 로컬 음성 호출을 변경합니다.", "설치된 마이크, 출력 장치 및 음성을 선택합니다.", "로컬 파일이나 오디오를 노출하지 않고 동기화를 관리합니다.", "속도와 개성을 조절하며 내부 모델 파일은 보호됩니다."),
    "ru": ("Выберите параметры интерфейса, разговора и запуска.", "Измените тему, цвет, фон, логотип, часы и специальные возможности.", "Измените имя активации и локальную голосовую активацию.", "Выберите установленные микрофон, устройство вывода и голос.", "Управляйте синхронизацией, не раскрывая локальные файлы и аудио.", "Настройте скорость и характер; внутренние файлы модели остаются защищёнными."),
    "ar": ("اختر خيارات الواجهة والمحادثة وبدء التشغيل.", "غيّر السمة واللون والخلفية والشعار والساعة وإمكانية الوصول.", "غيّر اسم التنشيط والتنشيط الصوتي المحلي.", "اختر ميكروفونًا وجهاز إخراج وصوتًا مثبتًا.", "تحكم في المزامنة دون كشف الملفات أو الصوت المحلي.", "اضبط السرعة والشخصية؛ تبقى ملفات النموذج الداخلية محمية."),
    "hi": ("इंटरफ़ेस, बातचीत और स्टार्टअप विकल्प चुनें।", "थीम, रंग, बैकग्राउंड, लोगो, घड़ी और एक्सेसिबिलिटी बदलें।", "वेक नाम और स्थानीय वॉइस सक्रियण बदलें।", "इंस्टॉल किया हुआ माइक्रोफ़ोन, आउटपुट डिवाइस और आवाज़ चुनें।", "स्थानीय फ़ाइलें या ऑडियो उजागर किए बिना सिंक नियंत्रित करें।", "गति और व्यक्तित्व समायोजित करें; आंतरिक मॉडल फ़ाइलें सुरक्षित रहती हैं।"),
}

ACTION_MESSAGES = {
    "es": ("Reproducción detenida.", "Reproducción pausada.", "Reproducción reanudada.", "Reproduciendo la siguiente canción.", "Reproduciendo la canción anterior.", "Tarea detenida."),
    "en": ("Playback stopped.", "Playback paused.", "Playback resumed.", "Playing the next track.", "Playing the previous track.", "Task stopped."),
    "pt": ("Reprodução interrompida.", "Reprodução pausada.", "Reprodução retomada.", "Reproduzindo a próxima faixa.", "Reproduzindo a faixa anterior.", "Tarefa interrompida."),
    "fr": ("Lecture arrêtée.", "Lecture en pause.", "Lecture reprise.", "Lecture du morceau suivant.", "Lecture du morceau précédent.", "Tâche arrêtée."),
    "de": ("Wiedergabe gestoppt.", "Wiedergabe pausiert.", "Wiedergabe fortgesetzt.", "Der nächste Titel wird abgespielt.", "Der vorherige Titel wird abgespielt.", "Aufgabe gestoppt."),
    "it": ("Riproduzione interrotta.", "Riproduzione in pausa.", "Riproduzione ripresa.", "Riproduzione del brano successivo.", "Riproduzione del brano precedente.", "Attività interrotta."),
    "zh": ("播放已停止。", "播放已暂停。", "播放已继续。", "正在播放下一首。", "正在播放上一首。", "任务已停止。"),
    "ja": ("再生を停止しました。", "再生を一時停止しました。", "再生を再開しました。", "次の曲を再生します。", "前の曲を再生します。", "タスクを停止しました。"),
    "ko": ("재생을 중지했습니다.", "재생을 일시 정지했습니다.", "재생을 다시 시작했습니다.", "다음 곡을 재생합니다.", "이전 곡을 재생합니다.", "작업을 중지했습니다."),
    "ru": ("Воспроизведение остановлено.", "Воспроизведение приостановлено.", "Воспроизведение продолжено.", "Воспроизводится следующий трек.", "Воспроизводится предыдущий трек.", "Задача остановлена."),
    "ar": ("تم إيقاف التشغيل.", "تم إيقاف التشغيل مؤقتًا.", "تم استئناف التشغيل.", "يتم تشغيل المقطع التالي.", "يتم تشغيل المقطع السابق.", "تم إيقاف المهمة."),
    "hi": ("प्लेबैक बंद किया गया।", "प्लेबैक रोका गया।", "प्लेबैक फिर शुरू किया गया।", "अगला ट्रैक चल रहा है।", "पिछला ट्रैक चल रहा है।", "कार्य रोक दिया गया।"),
}

_ACTION_INDEX = {"media.stop": 0, "media.pause": 1, "media.resume": 2, "media.next": 3, "media.previous": 4, "agent.cancel": 5}

RESPONSE_DIRECTIVES = {
    "es": "Responde de forma natural en español y conserva el contexto aunque el usuario haya usado otro idioma antes.",
    "en": "Respond naturally in English and preserve context even when the user previously used another language.",
    "pt": "Responda naturalmente em português e preserve o contexto mesmo que o usuário tenha usado outro idioma antes.",
    "fr": "Répondez naturellement en français et conservez le contexte même si l’utilisateur a utilisé une autre langue auparavant.",
    "de": "Antworte natürlich auf Deutsch und bewahre den Kontext, auch wenn zuvor eine andere Sprache verwendet wurde.",
    "it": "Rispondi naturalmente in italiano e conserva il contesto anche se l’utente ha usato prima un’altra lingua.",
    "zh": "请使用自然的中文回答，即使用户之前使用了其他语言，也要保留对话上下文。",
    "ja": "自然な日本語で回答し、ユーザーが以前に別の言語を使っていても会話の文脈を維持してください。",
    "ko": "자연스러운 한국어로 답하고 사용자가 이전에 다른 언어를 사용했더라도 대화 맥락을 유지하세요.",
    "ru": "Отвечайте естественно на русском языке и сохраняйте контекст, даже если ранее пользователь использовал другой язык.",
    "ar": "أجب بالعربية بصورة طبيعية وحافظ على سياق المحادثة حتى إذا استخدم المستخدم لغة أخرى سابقًا.",
    "hi": "स्वाभाविक हिन्दी में उत्तर दें और उपयोगकर्ता ने पहले दूसरी भाषा इस्तेमाल की हो तब भी संदर्भ बनाए रखें।",
}


def core_message(key: str, language: str) -> str:
    code = normalize_locale(language, "en")
    return CORE_MESSAGES[code][_KEY_INDEX[key]]


def identity_message(language: str) -> str:
    return IDENTITY_MESSAGES[normalize_locale(language, "en")]


def action_message(action: str, language: str) -> str:
    return ACTION_MESSAGES[normalize_locale(language, "en")][_ACTION_INDEX[action]]


def response_directive(language: str) -> str:
    return RESPONSE_DIRECTIVES[normalize_locale(language, "en")]


def product_help_message(language: str, topic: str) -> str:
    code = normalize_locale(language, "en")
    values = HELP_CATALOG[code]
    if topic == "overview":
        return values[8]
    section_index = {"general": 1, "personalization": 2, "activation": 3, "voice": 4, "privacy": 5, "intelligence": 6}.get(topic, 1)
    # The short detail stays in English only when a deterministic translation is
    # unavailable; the section and navigation remain localized and ARCHI handles
    # richer explanations in the selected language.
    detail_index = {"general": 0, "personalization": 1, "activation": 2, "voice": 3, "privacy": 4, "intelligence": 5}[topic]
    return values[7].format(settings=values[0], section=values[section_index], detail=HELP_DETAILS[code][detail_index])
