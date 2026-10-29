from typing import Any

#всё что зависит от страны лежит тут, контакты и реквизиты собирает код
# новая страна = новая запись, код трогать не надо
COUNTRIES: dict[str, dict[str, Any]] = {
    "DE": {
        "names": {"ru": "Германия", "de": "Deutschland"},
        "name_en": "Germany",
        #в Германии сайт и так не оферта, но так принято
        "offer_note": {
            "ru": "Сведения на сайте носят информационный характер и не являются обязывающим предложением.",
            "de": "Die Angaben auf dieser Website sind unverbindlich und stellen kein verbindliches Angebot dar.",
        },
        "people": "немецкие",
        "phone_code": "49",
        "tld": "de",
        "postal_digits": 5,
        "street_format": "{street} {number}",
        # по этому ищем право страны в условиях
        "law_markers": r"Германи|немецк|Deutschland|deutsch|German",
        #court это суд для HRB, region идёт в ИНН и ОГРН
        "cities": {
            "Berlin": {
                "area": "30", "plz": ["10", "12", "13"], "aliases": r"Берлин",
                "court": "Amtsgericht Charlottenburg (Berlin)",
            },
            "München": {"area": "89", "plz": ["80", "81"], "aliases": r"Мюнхен", "court": "Amtsgericht München"},
            "Hamburg": {"area": "40", "plz": ["20", "22"], "aliases": r"Гамбург", "court": "Amtsgericht Hamburg"},
            "Köln": {"area": "221", "plz": ["50", "51"], "aliases": r"К[её]льн", "court": "Amtsgericht Köln"},
            "Frankfurt am Main": {
                "area": "69", "plz": ["60"], "aliases": r"Франкфурт", "court": "Amtsgericht Frankfurt am Main",
            },
            "Stuttgart": {"area": "711", "plz": ["70"], "aliases": r"Штутгарт", "court": "Amtsgericht Stuttgart"},
            "Düsseldorf": {"area": "211", "plz": ["40"], "aliases": r"Дюссельдорф", "court": "Amtsgericht Düsseldorf"},
            "Leipzig": {"area": "341", "plz": ["04"], "aliases": r"Лейпциг", "court": "Amtsgericht Leipzig"},
        },
        "streets": [
            "Hauptstraße", "Bahnhofstraße", "Friedrichstraße", "Gartenstraße", "Lindenstraße",
            "Schillerstraße", "Goethestraße", "Kaiserstraße", "Mozartstraße", "Marktplatz",
            "Zimmerstraße", "Rosenthaler Straße", "Kanalstraße", "Ringstraße", "Bergstraße",
        ],
        "legal_forms": {"small": ["GmbH", "UG (haftungsbeschränkt)"], "medium": ["GmbH", "AG"]},
        "legal": {
            "law": "право Федеративной Республики Германия",
            "imprint": "выходные данные (Impressum): кто отвечает за сайт и содержание",
            "dispute": "порядок разрешения споров с потребителями, 2-3 предложения",
        },
        "privacy": {
            "law": "GDPR (DSGVO)",
            "basis_hint": (
                "у каждого пункта в основании укажи статью 6 GDPR (например, Art. 6 Abs. 1 lit. f)"
            ),
            "basis_pattern": r"(Art\.|ст\.|статья|Artikel)\s*6",
            "rights": (
                "доступ, исправление, удаление, ограничение обработки, возражение, переносимость, "
                "жалоба в надзорный орган"
            ),
            "must_mention": [],
            "sections": [],
        },
    },
    "RU": {
        "names": {"ru": "Россия", "de": "Russland"},
        "name_en": "Russia",
        # без этого цены на сайте могут счесть офертой, ст. 437 ГК
        "offer_note": {
            "ru": "Информация, размещенная на сайте, не является публичной офертой.",
            "de": "Die auf dieser Website veröffentlichten Informationen stellen kein öffentliches Angebot dar.",
        },
        "people": "русские",
        "phone_code": "7",
        "tld": "ru",
        "postal_digits": 6,
        "street_format": "{street}, д. {number}",
        "law_markers": r"Российск\w* Федераци|\bРФ\b|Russland|russisch|Russischen Föderation",
        "cities": {
            "Москва": {
                "area": "495", "plz": ["101", "105", "115", "119", "123", "125"], "aliases": r"Москв|Moskau",
                "region": "77",
            },
            "Санкт-Петербург": {
                "area": "812", "plz": ["190", "191", "196", "197"], "aliases": r"Петербург|Petersburg", "region": "78",
            },
            "Казань": {"area": "843", "plz": ["420"], "aliases": r"Казан|Kasan", "region": "16"},
            "Новосибирск": {"area": "383", "plz": ["630"], "aliases": r"Новосибирск|Nowosibirsk", "region": "54"},
            "Екатеринбург": {"area": "343", "plz": ["620"], "aliases": r"Екатеринбург|Jekaterinburg", "region": "66"},
            "Нижний Новгород": {
                "area": "831", "plz": ["603"], "aliases": r"Нижн\w+ Новгород|Nischni Nowgorod", "region": "52",
            },
        },
        "streets": [
            "ул. Ленина", "ул. Садовая", "пр-т Мира", "ул. Пушкина", "ул. Гагарина", "ул. Советская",
            "ул. Новая", "Набережная ул.", "ул. Мира", "Центральная ул.", "ул. Луговая", "ул. Строителей",
        ],
        "legal_forms": {"small": ["ООО"], "medium": ["ООО", "АО"]},
        "legal": {
            "law": "право Российской Федерации",
            "imprint": "сведения о компании: полное название, адрес, руководитель, контакты (без ИНН и ОГРН)",
            "dispute": (
                "претензионный порядок и рассмотрение споров в суде по месту нахождения компании, 2-3 предложения"
            ),
        },
        #какие разделы должны быть, как в типовых политиках
        "privacy": {
            "law": "152-ФЗ «О персональных данных»",
            "basis_hint": (
                "у каждого пункта в основании укажи норму 152-ФЗ: согласие субъекта, договор с ним "
                "или иное основание из статьи 6 152-ФЗ"
            ),
            "basis_pattern": r"152-ФЗ|согласи|договор|Einwilligung|Vertrag",
            "rights": (
                "получить сведения об обработке, требовать уточнения, блокирования или уничтожения данных, "
                "отозвать согласие, обжаловать действия оператора в Роскомнадзоре или в суде"
            ),
            # без этого политика не по 152-ФЗ
            "must_mention": [
                ("152-ФЗ", r"152-ФЗ|152-FZ"),
                ("Роскомнадзор как надзорный орган", r"Роскомнадзор|Roskomnadsor"),
                ("хранение данных граждан РФ на территории РФ",
                 r"территории Российской Федерации|территории РФ|Gebiet der Russischen"),
                ("право отозвать согласие", r"отзыв|отозвать|widerruf"),
            ],
            "sections": [
                ("Принципы обработки персональных данных", r"принцип|Grundsätze"),
                ("Условия обработки персональных данных", r"услови|Bedingungen"),
                ("Порядок сбора, хранения, передачи и уничтожения", r"хранени|Speicherung|Aufbewahrung"),
                ("Трансграничная передача персональных данных", r"трансграничн|grenzüberschreitend"),
                ("Конфиденциальность персональных данных", r"конфиденциальн|Vertraulichkeit"),
                ("Заключительные положения", r"заключительн|Schlussbestimmungen"),
            ],
        },
    },
}  # fmt: skip

DIRECTIONS = {
    "investment_research": "ИИ для инвестиционных исследований",
    "data_analytics": "ИИ для анализа данных",
}

SERVICE_TYPES = {
    "saas": "SaaS-платформа (веб-интерфейс по подписке)",
    "api": "API и потоки данных для интеграции",
    "managed": "управляемый сервис: ИИ плюс проверка аналитиками",
    "reports": "регулярные аналитические отчёты на основе ИИ",
    "consulting": "консалтинг и внедрение ИИ-инструментов",
}

SCALES: dict[str, dict[str, Any]] = {
    "small": {"label": "небольшая (10-30 сотрудников)", "employees": (10, 30), "age": (2, 6)},
    "medium": {"label": "средняя (60-150 сотрудников)", "employees": (60, 150), "age": (7, 15)},
}

# зерно на каждую компанию, чтоб истории не совпадали
NICHES = [
    "разбор годовой отчётности и пресс-релизов публичных компаний",
    "ESG-скоринг инвестиционных портфелей",
    "альтернативные данные: логистика, спутниковые снимки, цены в магазинах",
    "мониторинг регуляторных изменений для управляющих компаний",
    "анализ стенограмм звонков с аналитиками и встреч с инвесторами",
    "оценка кредитных рисков малого и среднего бизнеса",
    "прогноз сезонности потребительского спроса",
    "анализ рынка коммерческой недвижимости и фондов",
    "сопоставление новостных потоков с динамикой цен",
    "проверка контрагентов для частных инвесторов и семейных офисов",
    "анализ патентных данных для технологических инвесторов",
    "сведение данных от нескольких поставщиков для количественных команд",
]

FOUNDERS = [
    "бывший аналитик крупного банка",
    "математик из университета, ушедший из академической науки",
    "разработчик ПО, строивший внутренние системы для фонда",
    "бывший управляющий фондом",
    "специалист по данным из консалтинговой компании",
    "двое сооснователей: экономист и инженер",
]


#готовые модели, свою можно вписать
MODEL_PRESETS = [
    {"id": "anthropic/claude-haiku-5.5", "label": "Claude Haiku 5.5", "note": "дёшево, аккуратные тексты"},
    {"id": "openai/gpt-4o-mini", "label": "GPT-4o mini", "note": "дёшево, хорошо пишет по-русски и по-немецки"},
    {"id": "deepseek/deepseek-v3.2", "label": "DeepSeek V3.2", "note": "дёшево, длинные ответы почти бесплатно"},
    {"id": "google/gemini-3.5-flash-lite", "label": "Gemini 3.5 Flash Lite", "note": "быстро, средняя цена"},
    {"id": "openai/gpt-5.4-mini", "label": "GPT-5.4 Mini", "note": "дороже, тексты богаче"},
    {"id": "anthropic/claude-sonnet-5.5", "label": "Claude Sonnet 5.5",
     "note": "дорого, лучшие тексты, лимит от $0.50"},
]

# кто умеет рисовать портреты
IMAGE_PRESETS = [
    {"id": "google/gemini-3.1-flash-lite-image", "label": "Gemini 3.1 Flash Lite Image", "note": "дёшево и быстро"},
    {"id": "google/gemini-2.5-flash-image", "label": "Gemini 2.5 Flash Image", "note": "проверенная, недорого"},
    {"id": "openai/gpt-5-image-mini", "label": "GPT-5 Image Mini", "note": "недорого, другой стиль портретов"},
    {"id": "google/gemini-3.1-flash-image", "label": "Gemini 3.1 Flash Image", "note": "дороже, детальнее"},
]
#на одну картинку примерно столько, для оценки цены
IMAGE_TOKENS = 1300

# лимиты в панели, плюс свой
COST_PRESETS = [0.05, 0.10, 0.50, 1.00]


def country_name(code: str, lang: str) -> str:
    return str(COUNTRIES[code]["names"][lang])


def public_catalog() -> dict[str, list[dict[str, str]]]:
    return {
        "countries": [{"key": k, "label": v["names"]["ru"]} for k, v in COUNTRIES.items()],
        "directions": [{"key": k, "label": v} for k, v in DIRECTIONS.items()],
        "service_types": [{"key": k, "label": v} for k, v in SERVICE_TYPES.items()],
        "scales": [{"key": k, "label": v["label"]} for k, v in SCALES.items()],
        "languages": [{"key": "ru", "label": "Русский"}, {"key": "de", "label": "Deutsch"}],
    }
