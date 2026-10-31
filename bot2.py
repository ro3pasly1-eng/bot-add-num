"""
IMS SMS Telegram bot
- Choose a range, enter a client username.
- Checks CDR activity before replacing numbers already in the selected range.
- Moves only that client's numbers in the selected range to OTSHAHD, then verifies the move.
- Assigns up to 25 free numbers (or all remaining if fewer).
- Verifies results by re-reading the selected range.
- Client payout rate is 0.
- Uses cursor pagination and fails closed if the API response is incomplete.

Install:
    py -m pip install "python-telegram-bot>=21,<23" "httpx>=0.27"

CDR is read through the Shahd panel API token; no browser Cookie/CSRF session is used.
Credentials are configured in this single Python file. Run with:
    py -u IMS_Telegram_Bot_AI_Ready.py
"""

import asyncio
import logging
import unicodedata
from difflib import SequenceMatcher
import re
import time
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Any

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReactionTypeEmoji, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# -------------------- Configuration --------------------

IMS_BASE_URL = "https://imssms.org/api/v1"
CLIENT_PAYOUT_RATE = "0"
TARGET_NUMBER_COUNT = 25
MIN_CDR_ACTIVITIES = 10
CDR_BASE_URL = "https://imssms.org"
CDR_PAGE_SIZE = 5000
CDR_TIMEZONE = timezone(timedelta(hours=2))
TRANSFER_USERNAME = "OTshahd"
PAGE_SIZE = 500
MAX_PAGES = 10000
REQUEST_TIMEOUT = 30.0

# -------------------- Credentials (single-file setup) --------------------
TELEGRAM_BOT_TOKEN = '9101705143:AAFAx0f1YH03W9BEMPrG_wa9jT2LP3sTw14'
IMS_TOKEN = 'ca53dt6CZ_dZGpr1uxJH9r6apV04vqCoBxdgzEuep40'


# Keep logs quiet: HTTP debug logs can expose request URLs or sensitive data.
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("ims_bot")

WAITING_FOR_RANGE, WAITING_FOR_CLIENT, WAITING_FOR_RANGE_CHOICE = range(3)


# -------------------- Local country-name matching (no external AI/API) --------------------
COUNTRY_ALIASES = {'Afghanistan': 'afghanistan',
 'Albania': 'albania',
 'Algeria': 'algeria',
 'American Samoa': 'american samoa',
 'Andorra': 'andorra',
 'Angola': 'angola',
 'Anguilla': 'anguilla',
 'Antarctica': 'antarctica',
 'Antigua and Barbuda': 'antigua and barbuda',
 'Arab Republic of Egypt': 'egypt',
 'Argentina': 'argentina',
 'Argentine Republic': 'argentina',
 'Armenia': 'armenia',
 'Aruba': 'aruba',
 'Australia': 'australia',
 'Austria': 'austria',
 'Azerbaijan': 'azerbaijan',
 'Bahamas': 'bahamas',
 'Bahrain': 'bahrain',
 'Bangladesh': 'bangladesh',
 'Barbados': 'barbados',
 'Belarus': 'belarus',
 'Belgium': 'belgium',
 'Belize': 'belize',
 'Benin': 'benin',
 'Bermuda': 'bermuda',
 'Bhutan': 'bhutan',
 'Bolivarian Republic of Venezuela': 'venezuela, bolivarian republic of',
 'Bolivia': 'bolivia, plurinational state of',
 'Bolivia, Plurinational State of': 'bolivia, plurinational state of',
 'Bonaire, Sint Eustatius and Saba': 'bonaire, sint eustatius and saba',
 'Bosnia and Herzegovina': 'bosnia and herzegovina',
 'Botswana': 'botswana',
 'Bouvet Island': 'bouvet island',
 'Brazil': 'brazil',
 'British Indian Ocean Territory': 'british indian ocean territory',
 'British Virgin Islands': 'virgin islands, british',
 'Brunei Darussalam': 'brunei darussalam',
 'Bulgaria': 'bulgaria',
 'Burkina Faso': 'burkina faso',
 'Burundi': 'burundi',
 'Cabo Verde': 'cabo verde',
 'Cambodia': 'cambodia',
 'Cameroon': 'cameroon',
 'Canada': 'canada',
 'Cayman Islands': 'cayman islands',
 'Central African Republic': 'central african republic',
 'Chad': 'chad',
 'Chile': 'chile',
 'China': 'china',
 'Christmas Island': 'christmas island',
 'Cocos (Keeling) Islands': 'cocos (keeling) islands',
 'Colombia': 'colombia',
 'Commonwealth of Dominica': 'dominica',
 'Commonwealth of the Bahamas': 'bahamas',
 'Commonwealth of the Northern Mariana Islands': 'northern mariana islands',
 'Comoros': 'comoros',
 'Congo': 'congo',
 'Congo, The Democratic Republic of the': 'congo, the democratic republic of the',
 'Cook Islands': 'cook islands',
 'Costa Rica': 'costa rica',
 'Croatia': 'croatia',
 'Cuba': 'cuba',
 'Curaçao': 'curaçao',
 'Cyprus': 'cyprus',
 'Czech Republic': 'czechia',
 'Czechia': 'czechia',
 "Côte d'Ivoire": "côte d'ivoire",
 "Democratic People's Republic of Korea": "korea, democratic people's republic of",
 'Democratic Republic of Sao Tome and Principe': 'sao tome and principe',
 'Democratic Republic of Timor-Leste': 'timor-leste',
 'Democratic Socialist Republic of Sri Lanka': 'sri lanka',
 'Denmark': 'denmark',
 'Djibouti': 'djibouti',
 'Dominica': 'dominica',
 'Dominican Republic': 'dominican republic',
 'Eastern Republic of Uruguay': 'uruguay',
 'Ecuador': 'ecuador',
 'Egypt': 'egypt',
 'El Salvador': 'el salvador',
 'Equatorial Guinea': 'equatorial guinea',
 'Eritrea': 'eritrea',
 'Estonia': 'estonia',
 'Eswatini': 'eswatini',
 'Ethiopia': 'ethiopia',
 'Falkland Islands (Malvinas)': 'falkland islands (malvinas)',
 'Faroe Islands': 'faroe islands',
 'Federal Democratic Republic of Ethiopia': 'ethiopia',
 'Federal Democratic Republic of Nepal': 'nepal',
 'Federal Republic of Germany': 'germany',
 'Federal Republic of Nigeria': 'nigeria',
 'Federal Republic of Somalia': 'somalia',
 'Federated States of Micronesia': 'micronesia, federated states of',
 'Federative Republic of Brazil': 'brazil',
 'Fiji': 'fiji',
 'Finland': 'finland',
 'France': 'france',
 'French Guiana': 'french guiana',
 'French Polynesia': 'french polynesia',
 'French Republic': 'france',
 'French Southern Territories': 'french southern territories',
 'Gabon': 'gabon',
 'Gabonese Republic': 'gabon',
 'Gambia': 'gambia',
 'Georgia': 'georgia',
 'Germany': 'germany',
 'Ghana': 'ghana',
 'Gibraltar': 'gibraltar',
 'Grand Duchy of Luxembourg': 'luxembourg',
 'Greece': 'greece',
 'Greenland': 'greenland',
 'Grenada': 'grenada',
 'Guadeloupe': 'guadeloupe',
 'Guam': 'guam',
 'Guatemala': 'guatemala',
 'Guernsey': 'guernsey',
 'Guinea': 'guinea',
 'Guinea-Bissau': 'guinea-bissau',
 'Guyana': 'guyana',
 'Haiti': 'haiti',
 'Hashemite Kingdom of Jordan': 'jordan',
 'Heard Island and McDonald Islands': 'heard island and mcdonald islands',
 'Hellenic Republic': 'greece',
 'Holy See (Vatican City State)': 'holy see (vatican city state)',
 'Honduras': 'honduras',
 'Hong Kong': 'hong kong',
 'Hong Kong Special Administrative Region of China': 'hong kong',
 'Hungary': 'hungary',
 'Iceland': 'iceland',
 'Independent State of Papua New Guinea': 'papua new guinea',
 'Independent State of Samoa': 'samoa',
 'India': 'india',
 'Indonesia': 'indonesia',
 'Iran': 'iran, islamic republic of',
 'Iran, Islamic Republic of': 'iran, islamic republic of',
 'Iraq': 'iraq',
 'Ireland': 'ireland',
 'Islamic Republic of Afghanistan': 'afghanistan',
 'Islamic Republic of Iran': 'iran, islamic republic of',
 'Islamic Republic of Mauritania': 'mauritania',
 'Islamic Republic of Pakistan': 'pakistan',
 'Isle of Man': 'isle of man',
 'Israel': 'israel',
 'Italian Republic': 'italy',
 'Italy': 'italy',
 'Jamaica': 'jamaica',
 'Japan': 'japan',
 'Jersey': 'jersey',
 'Jordan': 'jordan',
 'Kazakhstan': 'kazakhstan',
 'Kenya': 'kenya',
 'Kingdom of Bahrain': 'bahrain',
 'Kingdom of Belgium': 'belgium',
 'Kingdom of Bhutan': 'bhutan',
 'Kingdom of Cambodia': 'cambodia',
 'Kingdom of Denmark': 'denmark',
 'Kingdom of Eswatini': 'eswatini',
 'Kingdom of Lesotho': 'lesotho',
 'Kingdom of Morocco': 'morocco',
 'Kingdom of Norway': 'norway',
 'Kingdom of Saudi Arabia': 'saudi arabia',
 'Kingdom of Spain': 'spain',
 'Kingdom of Sweden': 'sweden',
 'Kingdom of Thailand': 'thailand',
 'Kingdom of Tonga': 'tonga',
 'Kingdom of the Netherlands': 'netherlands',
 'Kiribati': 'kiribati',
 "Korea, Democratic People's Republic of": "korea, democratic people's republic of",
 'Korea, Republic of': 'korea, republic of',
 'Kuwait': 'kuwait',
 'Kyrgyz Republic': 'kyrgyzstan',
 'Kyrgyzstan': 'kyrgyzstan',
 "Lao People's Democratic Republic": "lao people's democratic republic",
 'Laos': "lao people's democratic republic",
 'Latvia': 'latvia',
 'Lebanese Republic': 'lebanon',
 'Lebanon': 'lebanon',
 'Lesotho': 'lesotho',
 'Liberia': 'liberia',
 'Libya': 'libya',
 'Liechtenstein': 'liechtenstein',
 'Lithuania': 'lithuania',
 'Luxembourg': 'luxembourg',
 'Macao': 'macao',
 'Macao Special Administrative Region of China': 'macao',
 'Madagascar': 'madagascar',
 'Malawi': 'malawi',
 'Malaysia': 'malaysia',
 'Maldives': 'maldives',
 'Mali': 'mali',
 'Malta': 'malta',
 'Marshall Islands': 'marshall islands',
 'Martinique': 'martinique',
 'Mauritania': 'mauritania',
 'Mauritius': 'mauritius',
 'Mayotte': 'mayotte',
 'Mexico': 'mexico',
 'Micronesia, Federated States of': 'micronesia, federated states of',
 'Moldova': 'moldova, republic of',
 'Moldova, Republic of': 'moldova, republic of',
 'Monaco': 'monaco',
 'Mongolia': 'mongolia',
 'Montenegro': 'montenegro',
 'Montserrat': 'montserrat',
 'Morocco': 'morocco',
 'Mozambique': 'mozambique',
 'Myanmar': 'myanmar',
 'Namibia': 'namibia',
 'Nauru': 'nauru',
 'Nepal': 'nepal',
 'Netherlands': 'netherlands',
 'New Caledonia': 'new caledonia',
 'New Zealand': 'new zealand',
 'Nicaragua': 'nicaragua',
 'Niger': 'niger',
 'Nigeria': 'nigeria',
 'Niue': 'niue',
 'Norfolk Island': 'norfolk island',
 'North Korea': "korea, democratic people's republic of",
 'North Macedonia': 'north macedonia',
 'Northern Mariana Islands': 'northern mariana islands',
 'Norway': 'norway',
 'Oman': 'oman',
 'Pakistan': 'pakistan',
 'Palau': 'palau',
 'Palestine, State of': 'palestine, state of',
 'Panama': 'panama',
 'Papua New Guinea': 'papua new guinea',
 'Paraguay': 'paraguay',
 "People's Democratic Republic of Algeria": 'algeria',
 "People's Republic of Bangladesh": 'bangladesh',
 "People's Republic of China": 'china',
 'Peru': 'peru',
 'Philippines': 'philippines',
 'Pitcairn': 'pitcairn',
 'Plurinational State of Bolivia': 'bolivia, plurinational state of',
 'Poland': 'poland',
 'Portugal': 'portugal',
 'Portuguese Republic': 'portugal',
 'Principality of Andorra': 'andorra',
 'Principality of Liechtenstein': 'liechtenstein',
 'Principality of Monaco': 'monaco',
 'Puerto Rico': 'puerto rico',
 'Qatar': 'qatar',
 'Republic of Albania': 'albania',
 'Republic of Angola': 'angola',
 'Republic of Armenia': 'armenia',
 'Republic of Austria': 'austria',
 'Republic of Azerbaijan': 'azerbaijan',
 'Republic of Belarus': 'belarus',
 'Republic of Benin': 'benin',
 'Republic of Bosnia and Herzegovina': 'bosnia and herzegovina',
 'Republic of Botswana': 'botswana',
 'Republic of Bulgaria': 'bulgaria',
 'Republic of Burundi': 'burundi',
 'Republic of Cabo Verde': 'cabo verde',
 'Republic of Cameroon': 'cameroon',
 'Republic of Chad': 'chad',
 'Republic of Chile': 'chile',
 'Republic of Colombia': 'colombia',
 'Republic of Costa Rica': 'costa rica',
 'Republic of Croatia': 'croatia',
 'Republic of Cuba': 'cuba',
 'Republic of Cyprus': 'cyprus',
 "Republic of Côte d'Ivoire": "côte d'ivoire",
 'Republic of Djibouti': 'djibouti',
 'Republic of Ecuador': 'ecuador',
 'Republic of El Salvador': 'el salvador',
 'Republic of Equatorial Guinea': 'equatorial guinea',
 'Republic of Estonia': 'estonia',
 'Republic of Fiji': 'fiji',
 'Republic of Finland': 'finland',
 'Republic of Ghana': 'ghana',
 'Republic of Guatemala': 'guatemala',
 'Republic of Guinea': 'guinea',
 'Republic of Guinea-Bissau': 'guinea-bissau',
 'Republic of Guyana': 'guyana',
 'Republic of Haiti': 'haiti',
 'Republic of Honduras': 'honduras',
 'Republic of Iceland': 'iceland',
 'Republic of India': 'india',
 'Republic of Indonesia': 'indonesia',
 'Republic of Iraq': 'iraq',
 'Republic of Kazakhstan': 'kazakhstan',
 'Republic of Kenya': 'kenya',
 'Republic of Kiribati': 'kiribati',
 'Republic of Latvia': 'latvia',
 'Republic of Liberia': 'liberia',
 'Republic of Lithuania': 'lithuania',
 'Republic of Madagascar': 'madagascar',
 'Republic of Malawi': 'malawi',
 'Republic of Maldives': 'maldives',
 'Republic of Mali': 'mali',
 'Republic of Malta': 'malta',
 'Republic of Mauritius': 'mauritius',
 'Republic of Moldova': 'moldova, republic of',
 'Republic of Mozambique': 'mozambique',
 'Republic of Myanmar': 'myanmar',
 'Republic of Namibia': 'namibia',
 'Republic of Nauru': 'nauru',
 'Republic of Nicaragua': 'nicaragua',
 'Republic of North Macedonia': 'north macedonia',
 'Republic of Palau': 'palau',
 'Republic of Panama': 'panama',
 'Republic of Paraguay': 'paraguay',
 'Republic of Peru': 'peru',
 'Republic of Poland': 'poland',
 'Republic of San Marino': 'san marino',
 'Republic of Senegal': 'senegal',
 'Republic of Serbia': 'serbia',
 'Republic of Seychelles': 'seychelles',
 'Republic of Sierra Leone': 'sierra leone',
 'Republic of Singapore': 'singapore',
 'Republic of Slovenia': 'slovenia',
 'Republic of South Africa': 'south africa',
 'Republic of South Sudan': 'south sudan',
 'Republic of Suriname': 'suriname',
 'Republic of Tajikistan': 'tajikistan',
 'Republic of Trinidad and Tobago': 'trinidad and tobago',
 'Republic of Tunisia': 'tunisia',
 'Republic of Türkiye': 'türkiye',
 'Republic of Uganda': 'uganda',
 'Republic of Uzbekistan': 'uzbekistan',
 'Republic of Vanuatu': 'vanuatu',
 'Republic of Yemen': 'yemen',
 'Republic of Zambia': 'zambia',
 'Republic of Zimbabwe': 'zimbabwe',
 'Republic of the Congo': 'congo',
 'Republic of the Gambia': 'gambia',
 'Republic of the Marshall Islands': 'marshall islands',
 'Republic of the Niger': 'niger',
 'Republic of the Philippines': 'philippines',
 'Republic of the Sudan': 'sudan',
 'Romania': 'romania',
 'Russian Federation': 'russian federation',
 'Rwanda': 'rwanda',
 'Rwandese Republic': 'rwanda',
 'Réunion': 'réunion',
 'Saint Barthélemy': 'saint barthélemy',
 'Saint Helena, Ascension and Tristan da Cunha': 'saint helena, ascension and tristan da cunha',
 'Saint Kitts and Nevis': 'saint kitts and nevis',
 'Saint Lucia': 'saint lucia',
 'Saint Martin (French part)': 'saint martin (french part)',
 'Saint Pierre and Miquelon': 'saint pierre and miquelon',
 'Saint Vincent and the Grenadines': 'saint vincent and the grenadines',
 'Samoa': 'samoa',
 'San Marino': 'san marino',
 'Sao Tome and Principe': 'sao tome and principe',
 'Saudi Arabia': 'saudi arabia',
 'Senegal': 'senegal',
 'Serbia': 'serbia',
 'Seychelles': 'seychelles',
 'Sierra Leone': 'sierra leone',
 'Singapore': 'singapore',
 'Sint Maarten (Dutch part)': 'sint maarten (dutch part)',
 'Slovak Republic': 'slovakia',
 'Slovakia': 'slovakia',
 'Slovenia': 'slovenia',
 'Socialist Republic of Viet Nam': 'viet nam',
 'Solomon Islands': 'solomon islands',
 'Somalia': 'somalia',
 'South Africa': 'south africa',
 'South Georgia and the South Sandwich Islands': 'south georgia and the south sandwich islands',
 'South Korea': 'korea, republic of',
 'South Sudan': 'south sudan',
 'Spain': 'spain',
 'Sri Lanka': 'sri lanka',
 'State of Israel': 'israel',
 'State of Kuwait': 'kuwait',
 'State of Qatar': 'qatar',
 'Sudan': 'sudan',
 'Sultanate of Oman': 'oman',
 'Suriname': 'suriname',
 'Svalbard and Jan Mayen': 'svalbard and jan mayen',
 'Sweden': 'sweden',
 'Swiss Confederation': 'switzerland',
 'Switzerland': 'switzerland',
 'Syria': 'syrian arab republic',
 'Syrian Arab Republic': 'syrian arab republic',
 'Taiwan': 'taiwan, province of china',
 'Taiwan, Province of China': 'taiwan, province of china',
 'Tajikistan': 'tajikistan',
 'Tanzania': 'tanzania, united republic of',
 'Tanzania, United Republic of': 'tanzania, united republic of',
 'Thailand': 'thailand',
 'Timor-Leste': 'timor-leste',
 'Togo': 'togo',
 'Togolese Republic': 'togo',
 'Tokelau': 'tokelau',
 'Tonga': 'tonga',
 'Trinidad and Tobago': 'trinidad and tobago',
 'Tunisia': 'tunisia',
 'Turkmenistan': 'turkmenistan',
 'Turks and Caicos Islands': 'turks and caicos islands',
 'Tuvalu': 'tuvalu',
 'Türkiye': 'türkiye',
 'Uganda': 'uganda',
 'Ukraine': 'ukraine',
 'Union of the Comoros': 'comoros',
 'United Arab Emirates': 'united arab emirates',
 'United Kingdom': 'united kingdom',
 'United Kingdom of Great Britain and Northern Ireland': 'united kingdom',
 'United Mexican States': 'mexico',
 'United Republic of Tanzania': 'tanzania, united republic of',
 'United States': 'united states',
 'United States Minor Outlying Islands': 'united states minor outlying islands',
 'United States of America': 'united states',
 'Uruguay': 'uruguay',
 'Uzbekistan': 'uzbekistan',
 'Vanuatu': 'vanuatu',
 'Venezuela': 'venezuela, bolivarian republic of',
 'Venezuela, Bolivarian Republic of': 'venezuela, bolivarian republic of',
 'Viet Nam': 'viet nam',
 'Vietnam': 'viet nam',
 'Virgin Islands of the United States': 'virgin islands, u.s.',
 'Virgin Islands, British': 'virgin islands, british',
 'Virgin Islands, U.S.': 'virgin islands, u.s.',
 'Wallis and Futuna': 'wallis and futuna',
 'Western Sahara': 'western sahara',
 'Yemen': 'yemen',
 'Zambia': 'zambia',
 'Zimbabwe': 'zimbabwe',
 'america': 'united states',
 'britain': 'united kingdom',
 'cote divoire': 'côte d’ivoire',
 'czechia': 'czech republic',
 'egypt': 'egypt',
 'egypte': 'egypt',
 'emirates': 'united arab emirates',
 'england': 'united kingdom',
 'ivory coast': 'côte d’ivoire',
 'ksa': 'saudi arabia',
 'kuwait': 'kuwait',
 'masr': 'egypt',
 'misr': 'egypt',
 'saudi': 'saudi arabia',
 'the State of Eritrea': 'eritrea',
 'the State of Palestine': 'palestine, state of',
 'uae': 'united arab emirates',
 'united states of america': 'united states',
 'usa': 'united states',
 'Åland Islands': 'åland islands',
 'آيسلندا': 'iceland',
 'أذربيجان': 'azerbaijan',
 'أرمينيا': 'armenia',
 'أروبا': 'aruba',
 'أستراليا': 'australia',
 'أفغانستان': 'afghanistan',
 'ألبانيا': 'albania',
 'ألمانيا': 'germany',
 'أمريكا': 'united states',
 'أنتاركتيكا': 'antarctica',
 'أنتيغوا وبربودا': 'antigua and barbuda',
 'أندورا': 'andorra',
 'أنغولا': 'angola',
 'أنغويلا': 'anguilla',
 'أورغواي': 'uruguay',
 'أوزبكستان': 'uzbekistan',
 'أوغندا': 'uganda',
 'أوكرانيا': 'ukraine',
 'أيرلندا': 'ireland',
 'إثيوبيا': 'ethiopia',
 'إريتريا': 'eritrea',
 'إسبانيا': 'spain',
 'إستونيا': 'estonia',
 'إسرائيل': 'israel',
 'إسواتيني': 'eswatini',
 'إنجلترا': 'united kingdom',
 'إندونيسيا': 'indonesia',
 'إيران': 'iran, islamic republic of',
 'إيطاليا': 'italy',
 'اثيوبيا': 'ethiopia',
 'الأراضي الفلسطينية': 'palestine, state of',
 'الأراضي المنخفضة': 'netherlands',
 'الأرجنتين': 'argentina',
 'الأردن': 'jordan',
 'الأقاليم الجنوبية الفرنسية': 'french southern territories',
 'الإقليم البريطاني في المحيط الهندي': 'british indian ocean territory',
 'الإكوادور': 'ecuador',
 'الإمارات': 'united arab emirates',
 'الإمارات العربية المتحدة': 'united arab emirates',
 'الاراضي المنخفضه': 'netherlands',
 'الارجنتين': 'argentina',
 'الاردن': 'jordan',
 'الامارات': 'united arab emirates',
 'البحرين': 'bahrain',
 'البرازيل': 'brazil',
 'البرتغال': 'portugal',
 'البوسنة والهرسك': 'bosnia and herzegovina',
 'التشيك': 'czech republic',
 'الجبل الأسود': 'montenegro',
 'الجبل الاسود': 'montenegro',
 'الجزائر': 'algeria',
 'الدانمرك': 'denmark',
 'الرأس الأخضر': 'cabo verde',
 'السعودية': 'saudi arabia',
 'السعودية العربية': 'saudi arabia',
 'السعوديه': 'saudi arabia',
 'السعوديه العربيه': 'saudi arabia',
 'السلفادور': 'el salvador',
 'السنغال': 'senegal',
 'السودان': 'sudan',
 'السويد': 'sweden',
 'الصحراء الغربية': 'western sahara',
 'الصومال': 'somalia',
 'الصين': 'china',
 'العراق': 'iraq',
 'الغابون': 'gabon',
 'الفاتيكان': 'holy see (vatican city state)',
 'الفلبين': 'philippines',
 'الكاميرون': 'cameroon',
 'الكونغو - برازافيل': 'congo',
 'الكونغو - كينشاسا': 'congo, the democratic republic of the',
 'الكويت': 'kuwait',
 'المغرب': 'morocco',
 'المكسيك': 'mexico',
 'المملكة العربية السعودية': 'saudi arabia',
 'المملكة المتحدة': 'united kingdom',
 'المملكه المتحده': 'united kingdom',
 'النرويج': 'norway',
 'النمسا': 'austria',
 'النيجر': 'niger',
 'الهند': 'india',
 'الولايات المتحدة': 'united states',
 'الولايات المتحده': 'united states',
 'اليابان': 'japan',
 'اليمن': 'yemen',
 'اليونان': 'greece',
 'امارات': 'united arab emirates',
 'امريكا': 'united states',
 'انجلترا': 'united kingdom',
 'اندونيسيا': 'indonesia',
 'بابوا غينيا الجديدة': 'papua new guinea',
 'باراغواي': 'paraguay',
 'باكستان': 'pakistan',
 'بالاو': 'palau',
 'بربادوس': 'barbados',
 'برمودا': 'bermuda',
 'بروناي': 'brunei darussalam',
 'بريطانيا': 'united kingdom',
 'بريطانيا العظمى': 'united kingdom',
 'بلجيكا': 'belgium',
 'بلغاريا': 'bulgaria',
 'بليز': 'belize',
 'بنجلاديش': 'bangladesh',
 'بنغلاديش': 'bangladesh',
 'بنما': 'panama',
 'بنين': 'benin',
 'بوتان': 'bhutan',
 'بوتسوانا': 'botswana',
 'بورتوريكو': 'puerto rico',
 'بوركينا فاسو': 'burkina faso',
 'بوروندي': 'burundi',
 'بولندا': 'poland',
 'بوليفيا': 'bolivia, plurinational state of',
 'بولينيزيا الفرنسية': 'french polynesia',
 'بيرو': 'peru',
 'بيلاروس': 'belarus',
 'تايلاند': 'thailand',
 'تايلند': 'thailand',
 'تايوان': 'taiwan, province of china',
 'تركمانستان': 'turkmenistan',
 'تركيا': 'türkiye',
 'ترينيداد وتوباغو': 'trinidad and tobago',
 'تشاد': 'chad',
 'تشيلي': 'chile',
 'تنزانيا': 'tanzania, united republic of',
 'توغو': 'togo',
 'توفالو': 'tuvalu',
 'توكيلاو': 'tokelau',
 'تونس': 'tunisia',
 'تونغا': 'tonga',
 'تيمور - ليشتي': 'timor-leste',
 'جامايكا': 'jamaica',
 'جبل طارق': 'gibraltar',
 'جزر آلاند': 'åland islands',
 'جزر البهاما': 'bahamas',
 'جزر القمر': 'comoros',
 'جزر المارتينيك': 'martinique',
 'جزر المالديف': 'maldives',
 'جزر الولايات المتحدة النائية': 'united states minor outlying islands',
 'جزر بيتكيرن': 'pitcairn',
 'جزر توركس وكايكوس': 'turks and caicos islands',
 'جزر سليمان': 'solomon islands',
 'جزر فارو': 'faroe islands',
 'جزر فوكلاند': 'falkland islands (malvinas)',
 'جزر فيرجن الأمريكية': 'virgin islands, u.s.',
 'جزر فيرجن البريطانية': 'virgin islands, british',
 'جزر كايمان': 'cayman islands',
 'جزر كوك': 'cook islands',
 'جزر كوكوس (كيلينغ)': 'cocos (keeling) islands',
 'جزر مارشال': 'marshall islands',
 'جزر ماريانا الشمالية': 'northern mariana islands',
 'جزر والس وفوتونا': 'wallis and futuna',
 'جزيرة بوفيه': 'bouvet island',
 'جزيرة كريسماس': 'christmas island',
 'جزيرة مان': 'isle of man',
 'جزيرة نورفولك': 'norfolk island',
 'جزيرة هيرد وجزر ماكدونالد': 'heard island and mcdonald islands',
 'جمهورية أفريقيا الوسطى': 'central african republic',
 'جمهورية الدومينيكان': 'dominican republic',
 'جنوب أفريقيا': 'south africa',
 'جنوب افريقيا': 'south africa',
 'جنوب السودان': 'south sudan',
 'جورجيا': 'georgia',
 'جورجيا الجنوبية وجزر ساندويتش الجنوبية': 'south georgia and the south sandwich islands',
 'جيبوتي': 'djibouti',
 'جيرسي': 'jersey',
 'دومينيكا': 'dominica',
 'رواندا': 'rwanda',
 'روسيا': 'russian federation',
 'رومانيا': 'romania',
 'روينيون': 'réunion',
 'زامبيا': 'zambia',
 'زيمبابوي': 'zimbabwe',
 'ساحل العاج': 'côte d’ivoire',
 'ساموا': 'samoa',
 'ساموا الأمريكية': 'american samoa',
 'سان بارتليمي': 'saint barthélemy',
 'سان بيير ومكويلون': 'saint pierre and miquelon',
 'سان مارتن': 'saint martin (french part)',
 'سان مارينو': 'san marino',
 'سانت فنسنت وجزر غرينادين': 'saint vincent and the grenadines',
 'سانت كيتس ونيفيس': 'saint kitts and nevis',
 'سانت لوسيا': 'saint lucia',
 'سانت مارتن': 'sint maarten (dutch part)',
 'سانت هيلينا': 'saint helena, ascension and tristan da cunha',
 'ساو تومي وبرينسيبي': 'sao tome and principe',
 'سريلانكا': 'sri lanka',
 'سفالبارد وجان ماين': 'svalbard and jan mayen',
 'سلطنة عمان': 'oman',
 'سلطنه عمان': 'oman',
 'سلوفاكيا': 'slovakia',
 'سلوفينيا': 'slovenia',
 'سنغافورة': 'singapore',
 'سنغافوره': 'singapore',
 'سوريا': 'syrian arab republic',
 'سورينام': 'suriname',
 'سويسرا': 'switzerland',
 'سيراليون': 'sierra leone',
 'سيشل': 'seychelles',
 'صربيا': 'serbia',
 'طاجيكستان': 'tajikistan',
 'عمان': 'oman',
 'عُمان': 'oman',
 'غامبيا': 'gambia',
 'غانا': 'ghana',
 'غرينادا': 'grenada',
 'غرينلاند': 'greenland',
 'غواتيمالا': 'guatemala',
 'غوادلوب': 'guadeloupe',
 'غوام': 'guam',
 'غويانا الفرنسية': 'french guiana',
 'غيانا': 'guyana',
 'غيرنزي': 'guernsey',
 'غينيا': 'guinea',
 'غينيا الاستوائية': 'equatorial guinea',
 'غينيا بيساو': 'guinea-bissau',
 'فانواتو': 'vanuatu',
 'فرنسا': 'france',
 'فنزويلا': 'venezuela, bolivarian republic of',
 'فنلندا': 'finland',
 'فيتنام': 'viet nam',
 'فيجي': 'fiji',
 'قبرص': 'cyprus',
 'قطر': 'qatar',
 'قيرغيزستان': 'kyrgyzstan',
 'كازاخستان': 'kazakhstan',
 'كاليدونيا الجديدة': 'new caledonia',
 'كرواتيا': 'croatia',
 'كمبوديا': 'cambodia',
 'كندا': 'canada',
 'كوبا': 'cuba',
 'كوراساو': 'curaçao',
 'كوريا': 'south korea',
 'كوريا الجنوبية': 'korea, republic of',
 'كوريا الشمالية': "korea, democratic people's republic of",
 'كوستاريكا': 'costa rica',
 'كولومبيا': 'colombia',
 'كيريباتي': 'kiribati',
 'كينيا': 'kenya',
 'لاتفيا': 'latvia',
 'لاوس': "lao people's democratic republic",
 'لبنان': 'lebanon',
 'لوكسمبورغ': 'luxembourg',
 'ليبيا': 'libيا',
 'ليبيريا': 'liberia',
 'ليتوانيا': 'lithuania',
 'ليختنشتاين': 'liechtenstein',
 'ليسوتو': 'lesotho',
 'مالطا': 'malta',
 'مالي': 'mali',
 'ماليزيا': 'malaysia',
 'مايوت': 'mayotte',
 'مدغشقر': 'madagascar',
 'مراكش': 'morocco',
 'مصر': 'egypt',
 'مقدونيا': 'north macedonia',
 'مقدونيا الشمالية': 'north macedonia',
 'ملاوي': 'malawi',
 'منطقة ماكاو الإدارية الخاصة': 'macao',
 'منغوليا': 'mongolia',
 'موريتانيا': 'mauritania',
 'موريشيوس': 'mauritius',
 'موزمبيق': 'mozambique',
 'مولدوفا': 'moldova, republic of',
 'موناكو': 'monaco',
 'مونتجرو': 'montenegro',
 'مونتسرات': 'montserrat',
 'مونتنيجرو': 'montenegro',
 'مونتينيجرو': 'montenegro',
 'مونتينيغرا': 'montenegro',
 'مونتينيغرو': 'montenegro',
 'ميانمار (بورما)': 'myanmar',
 'ميكرونيزيا': 'micronesia, federated states of',
 'ناميبيا': 'namibia',
 'ناورو': 'nauru',
 'نيبال': 'nepal',
 'نيجيريا': 'nigeria',
 'نيذرلاند': 'netherlands',
 'نيكاراغوا': 'nicaragua',
 'نيوزيلندا': 'new zealand',
 'نيوي': 'niue',
 'هايتي': 'haiti',
 'هندوراس': 'honduras',
 'هنغاريا': 'hungary',
 'هولندا': 'netherlands',
 'هولندا الكاريبية': 'bonaire, sint eustatius and saba',
 'هونج كونج': 'hong kong',
 'هونغ كونغ': 'hong kong',
 'هونغ كونغ الصينية (منطقة إدارية خاصة)': 'hong kong'}


def normalize_country_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value).casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.translate(str.maketrans({
        "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه",
        "ؤ": "و", "ئ": "ي", "ـ": "", "پ": "ب", "چ": "ج", "ژ": "ز", "گ": "ك",
    }))
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


_NORMALIZED_ALIASES = {
    normalize_country_text(alias): canonical
    for alias, canonical in COUNTRY_ALIASES.items()
    if len(normalize_country_text(alias)) >= 3
}


def _country_key(value: str) -> str | None:
    normalized = normalize_country_text(value)
    if not normalized:
        return None
    if normalized in _NORMALIZED_ALIASES:
        return _NORMALIZED_ALIASES[normalized]

    words = normalized.split()
    candidates = {normalized}
    for width in range(1, min(6, len(words)) + 1):
        for i in range(len(words) - width + 1):
            candidates.add(" ".join(words[i:i + width]))

    best = (0.0, None)
    for candidate in candidates:
        if candidate in _NORMALIZED_ALIASES:
            return _NORMALIZED_ALIASES[candidate]
        for alias, canonical in _NORMALIZED_ALIASES.items():
            if min(len(candidate), len(alias)) < 4:
                continue
            score = SequenceMatcher(None, candidate, alias).ratio()
            threshold = 0.80 if min(len(candidate), len(alias)) <= 6 else 0.77
            if score >= threshold and score > best[0]:
                best = (score, canonical)
    return best[1]


def match_country_ranges(message: str, range_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    query = normalize_country_text(message)
    if not query:
        return []

    literal = [
        item for item in range_items
        if query in normalize_country_text(str(item.get("name", "")))
    ]
    if literal:
        return literal

    wanted_country = _country_key(message)
    if wanted_country:
        country_aliases = [
            alias for alias, canonical in _NORMALIZED_ALIASES.items()
            if canonical == wanted_country and len(alias) >= 3
        ]
        country_matches = []
        for item in range_items:
            range_name = normalize_country_text(str(item.get("name", "")))
            if any(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", range_name)
                   for alias in country_aliases):
                country_matches.append(item)
        if country_matches:
            return country_matches

    scored = []
    search_terms = [query]
    if wanted_country:
        search_terms.extend(a for a, c in _NORMALIZED_ALIASES.items() if c == wanted_country)
    for item in range_items:
        name = normalize_country_text(str(item.get("name", "")))
        score = max((SequenceMatcher(None, term, name).ratio() for term in search_terms), default=0.0)
        if score >= 0.84:
            scored.append((score, item))
    if not scored:
        return []
    best = max(score for score, _ in scored)
    return [item for score, item in scored if score >= max(0.84, best - 0.04)]


# -------------------- IMS API client --------------------

class IMSAPIError(Exception):
    pass


class IMSClient:
    def __init__(self, token: str) -> None:
        self.client = httpx.AsyncClient(
            base_url=IMS_BASE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=REQUEST_TIMEOUT,
        )
        self._request_lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def close(self) -> None:
        await self.client.aclose()

    async def _throttle(self) -> None:
        async with self._request_lock:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < 1.05:
                await asyncio.sleep(1.05 - elapsed)
            self._last_request_at = time.monotonic()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        retry_get_429: bool = True,
    ) -> dict[str, Any]:
        is_get = method.upper() == "GET"

        for attempt in range(4 if is_get and retry_get_429 else 1):
            await self._throttle()
            try:
                response = await self.client.request(
                    method,
                    path,
                    params=params,
                    json=json_body,
                )
            except httpx.TimeoutException as exc:
                raise IMSAPIError(
                    "انتهت مهلة الاتصال بلوحة IMS. لم أكرر الطلب تلقائيًا "
                    "حتى لا يتم توزيع الأرقام مرتين."
                ) from exc
            except httpx.HTTPError as exc:
                raise IMSAPIError(
                    "حصل خطأ اتصال بلوحة IMS. لم أكرر طلب التوزيع تلقائيًا."
                ) from exc

            if response.status_code == 429 and is_get and attempt < 3:
                retry_after = response.headers.get("Retry-After", "2")
                try:
                    wait_seconds = max(1.0, min(float(retry_after), 60.0))
                except ValueError:
                    wait_seconds = 2.0
                await asyncio.sleep(wait_seconds)
                continue

            if response.status_code >= 400:
                body = response.text[:300].replace("\n", " ")
                raise IMSAPIError(
                    f"لوحة IMS رجّعت خطأ HTTP {response.status_code}: {body}"
                )

            try:
                data = response.json()
            except ValueError as exc:
                raise IMSAPIError("استجابة لوحة IMS ليست JSON صالحًا.") from exc

            if not isinstance(data, dict):
                raise IMSAPIError("شكل استجابة لوحة IMS غير متوقع.")
            return data

        raise IMSAPIError("تعذر قراءة البيانات من لوحة IMS بعد إعادة المحاولة.")

    async def get_ranges(self) -> list[dict[str, Any]]:
        data = await self.request("GET", "/ranges")
        ranges = data.get("ranges")
        if not isinstance(ranges, list):
            raise IMSAPIError("استجابة /ranges لا تحتوي على قائمة ranges صحيحة.")

        valid = []
        for item in ranges:
            if not isinstance(item, dict):
                raise IMSAPIError("بيانات أحد الـ Ranges غير سليمة.")
            if not item.get("id") or not item.get("name"):
                raise IMSAPIError("أحد الـ Ranges ينقصه id أو name.")
            if item.get("active") is True:
                valid.append(item)

        return valid

    async def get_all_numbers_for_range(
        self, range_id: str
    ) -> list[dict[str, Any]]:
        all_records: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()

        for _page in range(MAX_PAGES):
            params: dict[str, Any] = {
                "rangeId": range_id,
                "limit": PAGE_SIZE,
            }

            if cursor is not None:
                params["after"] = cursor

            data = await self.request("GET", "/numbers", params=params)
            records = data.get("records")

            if not isinstance(records, list):
                raise IMSAPIError(
                    "استجابة /numbers لا تحتوي على records؛ أوقفت العملية للحماية."
                )

            for record in records:
                if not isinstance(record, dict):
                    raise IMSAPIError("يوجد سجل رقم غير صالح؛ أوقفت العملية.")

                if not record.get("number"):
                    raise IMSAPIError("يوجد سجل بدون رقم؛ أوقفت العملية.")

                if str(record.get("rangeId", "")) != range_id:
                    raise IMSAPIError(
                        "أحد السجلات لا يطابق الـ Range المختار؛ "
                        "أوقفت العملية لتجنب توزيع أرقام خاطئة."
                    )

                if "client" not in record:
                    raise IMSAPIError(
                        "حقل client غير موجود في سجل الأرقام؛ "
                        "لا أستطيع التمييز بأمان بين المتاح والمخصص."
                    )

                all_records.append(record)

            next_cursor = data.get("nextCursor")

            if next_cursor is None:
                return all_records

            next_cursor = str(next_cursor)

            if not next_cursor or next_cursor in seen_cursors:
                raise IMSAPIError(
                    "ترقيم صفحات الأرقام غير سليم (cursor مكرر)؛ أوقفت العملية."
                )

            seen_cursors.add(next_cursor)
            cursor = next_cursor

        raise IMSAPIError(
            "عدد صفحات الأرقام تجاوز الحد الآمن؛ أوقفت العملية دون توزيع."
        )

    async def get_clients(self) -> list[dict[str, Any]]:
        data = await self.request("GET", "/clients", params={"limit": 500})
        clients = data.get("clients")
        if not isinstance(clients, list):
            raise IMSAPIError(
                "استجابة /clients لا تحتوي على قائمة clients صحيحة؛ "
                "لم يتم تنفيذ أي نقل أو توزيع."
            )
        count = data.get("count")
        if isinstance(count, int) and count > len(clients):
            raise IMSAPIError(
                "قائمة العملاء أكبر من الحد الذي أرجعته اللوحة؛ "
                "لا أستطيع التأكد من صحة اليوزر بأمان."
            )
        if not all(isinstance(item, dict) and isinstance(item.get("username"), str)
                   for item in clients):
            raise IMSAPIError(
                "بيانات أسماء العملاء غير مكتملة؛ لم يتم تنفيذ أي نقل أو توزيع."
            )
        return clients

    async def assign(
        self, username: str, numbers: list[str]
    ) -> dict[str, Any]:
        return await self.request(
            "POST",
            "/numbers/assign",
            json_body={
                "client": username,
                "numbers": numbers,
                "clientPayoutRate": CLIENT_PAYOUT_RATE,
            },
            retry_get_429=False,
        )


# -------------------- CDR API client --------------------

class CDRAPIError(Exception):
    pass


class CDRClient:
    def __init__(self, token: str) -> None:
        self.token = token.strip()
        self.client = httpx.AsyncClient(
            base_url=CDR_BASE_URL,
            headers={"Accept": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def fetch_latest_records(self, limit: int = 30) -> list[dict[str, Any]]:
        if not self.token:
            raise CDRAPIError("توكن لوحة CDR غير مضبوط.")
        try:
            response = await self.client.get(
                "/api/v1/cdrs", params={"token": self.token, "limit": min(max(limit, 1), 50)}
            )
        except httpx.HTTPError as exc:
            raise CDRAPIError("تعذر الاتصال بسجل CDR.") from exc
        if response.status_code in (401, 403):
            raise CDRAPIError("توكن لوحة CDR مرفوض أو انتهت صلاحيته.")
        if response.status_code == 429:
            raise CDRAPIError("لوحة CDR طلبت تقليل معدل التحديث (HTTP 429).")
        if response.status_code >= 400:
            raise CDRAPIError(f"طلب CDR رجّع HTTP {response.status_code}.")
        try:
            data = response.json()
        except ValueError as exc:
            raise CDRAPIError("استجابة CDR ليست JSON صالحًا.") from exc
        records = data.get("records") if isinstance(data, dict) else None
        if not isinstance(records, list):
            raise CDRAPIError("استجابة CDR لا تحتوي على records صحيحة.")
        return [r for r in records if isinstance(r, dict)][:limit]

    async def count_client_range_activities(
        self, range_name: str, client_numbers: set[str]
    ) -> int:
        if not self.token:
            raise CDRAPIError("توكن لوحة شهد غير موجود في إعدادات البوت.")
        if not client_numbers:
            return 0

        params = {"token": self.token, "limit": CDR_PAGE_SIZE}
        try:
            response = await self.client.get("/api/v1/cdrs", params=params)
        except httpx.HTTPError as exc:
            raise CDRAPIError("تعذر الاتصال بسجل CDR الخاص بلوحة شهد.") from exc

        if response.status_code in (401, 403):
            raise CDRAPIError("توكن لوحة شهد مرفوض أو انتهت صلاحيته.")
        if response.status_code >= 400:
            raise CDRAPIError(f"طلب CDR رجّع HTTP {response.status_code}.")
        try:
            data = response.json()
        except ValueError as exc:
            raise CDRAPIError("استجابة CDR ليست JSON صالحًا.") from exc
        records = data.get("records") if isinstance(data, dict) else None
        if not isinstance(records, list):
            raise CDRAPIError("استجابة CDR لا تحتوي على records صحيحة.")

        wanted_numbers = {str(n).strip() for n in client_numbers}
        matched_records: set[str] = set()

        for rec in records:
            if not isinstance(rec, dict):
                continue
            rec_number = str(rec.get("number", "")).strip()
            if rec_number in wanted_numbers:
                matched_records.add(rec_number)

        return len(matched_records)


cdr = CDRClient(IMS_TOKEN)


# -------------------- Read-only public CDR Live view --------------------

LIVE_REFRESH_SECONDS = 10
LIVE_SUBSCRIBERS_KEY = "cdr_live_subscribers"
LIVE_TASK_KEY = "cdr_live_task"
LIVE_LAST_BODY_KEY = "cdr_live_last_good_body"


def _mask_live_sms(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "(لا يوجد نص رسالة)"
    text = re.sub(r"(?<!\d)\d(?:[\s-]*\d){3,}(?!\d)", "••••", text)
    text = re.sub(
        r"(?i)(\b(?:otp|code|verification|verify|pin)\b|كود|رمز|رمز التحقق)(\s*[:：-]?\s*)[A-Z0-9-]{3,}",
        r"\1\2••••", text,
    )
    return text[:240]


def _live_record_text(records: list[dict[str, Any]]) -> str:
    from html import escape

    if not records:
        return "لا توجد تسميعات حديثة في سجل CDR."

    records = sorted(records, key=lambda r: str(r.get("time", "")), reverse=True)
    blocks: list[str] = []
    markers = ("🟦", "🟩", "🟪", "🟧", "🟥", "🟨", "🔷", "🔶", "🟣", "🟢")

    def field(rec: dict[str, Any], names: tuple[str, ...], default: str = "غير محدد") -> str:
        for name in names:
            value = rec.get(name)
            if value is not None and str(value).strip():
                return str(value).strip()
        return default

    for index, rec in enumerate(records[:10]):
        stamp = field(rec, ("time", "created_at", "timestamp"), "وقت غير متاح")
        panel = field(rec, ("panel", "panel_name"), "shahd")
        source = field(rec, ("source", "source_name", "sender", "cli"))
        number = field(rec, ("number", "phone", "msisdn"))
        range_name = field(rec, ("range", "range_name", "country"))
        sms_raw = field(rec, ("content", "message", "sms", "body", "text"), "(لا يوجد نص رسالة)")
        sms = _mask_live_sms(sms_raw)
        marker = markers[index % len(markers)]

        rows = [
            f"<b>{marker} تسميعة #{index + 1}</b>",
            f"<b>Time:</b> {escape(stamp)}",
            f"<b>Panel:</b> {escape(panel)}",
            f"<b>CLI:</b> {escape(source)}",
            f"<b>Number:</b> {escape(number)}",
            f"<b>Range:</b> {escape(range_name)}",
            f"<b>SMS:</b> {escape(sms)}",
        ]
        blocks.append("\n".join(rows))

    heading = "🔴 <b>CDR LIVE — آخر 10 تسميعات</b>\n\n"
    body = heading + "\n\n━━━━━━━━━━━━━━━━━━\n\n".join(blocks)
    if len(body) > 3900:
        body = body[:3880] + "\n…"
    return body


def _live_record_fingerprint(rec: dict[str, Any]) -> tuple[str, ...]:
    event_id = rec.get("id") or rec.get("cdr_id") or rec.get("uuid")
    if event_id is not None and str(event_id).strip():
        return ("id", str(event_id).strip())
    return (
        str(rec.get("time", rec.get("created_at", rec.get("timestamp", "")))),
        str(rec.get("number", rec.get("phone", rec.get("msisdn", "")))),
        str(rec.get("range", rec.get("range_name", ""))),
        str(rec.get("cli", rec.get("source", rec.get("sender", "")))),
        str(rec.get("content", rec.get("message", rec.get("sms", rec.get("body", ""))))),
    )


def _live_single_record_text(rec: dict[str, Any]) -> str:
    from html import escape

    def field(names: tuple[str, ...], default: str = "غير محدد") -> str:
        for name in names:
            value = rec.get(name)
            if value is not None and str(value).strip():
                return str(value).strip()
        return default

    stamp = field(("time", "created_at", "timestamp"), "وقت غير متاح")
    panel = field(("panel", "panel_name"), "shahd")
    source = field(("source", "source_name", "sender", "cli"))
    number = field(("number", "phone", "msisdn"))
    range_name = field(("range", "range_name", "country"))
    sms = _mask_live_sms(field(("content", "message", "sms", "body", "text"), "(لا يوجد نص رسالة)"))
    return "\n".join((
        "🟢 <b>تسميعة جديدة — CDR LIVE</b>",
        "💬 <b>لو حابب تطلب دولة أو تغيّر الدولة، اكتب اسم الدولة مباشرة.</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"🕒 <b>Time:</b> {escape(stamp)}",
        f"🖥 <b>Panel:</b> {escape(panel)}",
        f"📡 <b>CLI:</b> {escape(source)}",
        f"📱 <b>Number:</b> {escape(number)}",
        f"🌍 <b>Range:</b> {escape(range_name)}",
        f"✉️ <b>SMS:</b> {escape(sms)}",
        "━━━━━━━━━━━━━━━━━━",
    ))


def _live_keyboard(is_live: bool = False) -> InlineKeyboardMarkup:
    if is_live:
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("⏹️  إيقاف LIVE", callback_data="cdr_live_off"),
        ]])
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔴✨  تشغيل LIVE", callback_data="cdr_live_on"),
    ]])


def _live_parse_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


async def _cdr_live_loop(application: Application) -> None:
    while True:
        subscribers = application.bot_data.get(LIVE_SUBSCRIBERS_KEY, {})
        if not subscribers:
            application.bot_data[LIVE_TASK_KEY] = None
            return
        try:
            records = await cdr.fetch_latest_records(30)
            ordered = sorted(records, key=lambda r: str(r.get("time", r.get("created_at", ""))))
            for chat_id, state in list(subscribers.items()):
                seen = state.setdefault("seen", set())
                for rec in ordered:
                    fingerprint = _live_record_fingerprint(rec)
                    resume_after = state.get("resume_after")
                    if resume_after is not None:
                        record_time = _live_parse_utc(
                            rec.get("time", rec.get("created_at", rec.get("timestamp")))
                        )
                        if record_time is not None and record_time <= resume_after:
                            seen.add(fingerprint)
                            continue
                    if fingerprint in seen:
                        continue
                    seen.add(fingerprint)
                    try:
                        await application.bot.send_message(
                            chat_id=chat_id,
                            text=_live_single_record_text(rec),
                            parse_mode="HTML",
                            reply_markup=_live_keyboard(is_live=True),
                            disable_web_page_preview=True,
                        )
                    except Exception:
                        logger.warning("Could not push a new CDR Live event to chat %s", chat_id)
        except CDRAPIError as exc:
            logger.info("CDR Live temporarily unavailable; waiting for next poll: %s", exc)
            await asyncio.sleep(15)
        await asyncio.sleep(LIVE_REFRESH_SECONDS)


async def cdr_live_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    chat_id = query.message.chat_id
    subscribers = context.application.bot_data.setdefault(LIVE_SUBSCRIBERS_KEY, {})
    if query.data == "cdr_live_off":
        subscribers.pop(chat_id, None)
        await query.edit_message_text(
            "⚫ تم إيقاف LIVE.\n\nيمكنك تشغيله مرة أخرى من الزر بالأسفل.",
            reply_markup=_live_keyboard(is_live=False)
        )
        return
    if query.data == "cdr_live_on":
        try:
            all_recent = await cdr.fetch_latest_records(30)
            body = _live_record_text(all_recent)
        except CDRAPIError as exc:
            logger.info("CDR Live initial fetch temporarily unavailable: %s", exc)
            all_recent = []
            body = "🔴 <b>CDR LIVE</b>\n\nجاري انتظار أول تسميعة جديدة… ستظهر تلقائيًا في رسالة مستقلة هنا."
        
        seen = {_live_record_fingerprint(rec) for rec in all_recent}
        subscribers[chat_id] = {"message_id": query.message.message_id, "seen": seen}
        
        await query.edit_message_text(
            body + "\n\n🟢 <b>LIVE شغال</b> — التسميعات الجديدة هتوصلك في رسائل منفصلة.",
            parse_mode="HTML", reply_markup=_live_keyboard(is_live=True),
            disable_web_page_preview=True,
        )
        task = context.application.bot_data.get(LIVE_TASK_KEY)
        if task is None or task.done():
            context.application.bot_data[LIVE_TASK_KEY] = context.application.create_task(
                _cdr_live_loop(context.application), name="cdr-live-poller"
            )


# -------------------- Telegram handlers --------------------

ims = IMSClient(IMS_TOKEN)


PAUSED_LIVE_SUBSCRIBERS_KEY = "cdr_live_paused_subscribers"


async def _pause_live_for_request(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    chat = update.effective_chat
    if not chat:
        return

    subscribers = context.application.bot_data.setdefault(LIVE_SUBSCRIBERS_KEY, {})
    if chat.id in subscribers:
        if chat.id not in context.user_data.get(PAUSED_LIVE_SUBSCRIBERS_KEY, {}):
            paused_state = subscribers.pop(chat.id)
            context.user_data[PAUSED_LIVE_SUBSCRIBERS_KEY] = paused_state
            try:
                await context.bot.send_message(
                    chat_id=chat.id,
                    text="⏳ تم إيقاف وضع الـ LIVE مؤقتاً لحد لما عملية الطلب تنتهي..."
                )
            except Exception:
                pass


async def _resume_live_after_request(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """Returns True if Live was active and successfully resumed, False otherwise."""
    chat = update.effective_chat
    if not chat:
        return False

    paused = context.user_data.pop(PAUSED_LIVE_SUBSCRIBERS_KEY, None)
    if paused is None:
        return False

    try:
        latest = await cdr.fetch_latest_records(30)
        paused.setdefault("seen", set()).update(
            _live_record_fingerprint(rec) for rec in latest
        )
    except CDRAPIError as exc:
        logger.info("Could not refresh CDR snapshot while resuming Live: %s", exc)

    paused["resume_after"] = datetime.now(timezone.utc)
    subscribers = context.application.bot_data.setdefault(LIVE_SUBSCRIBERS_KEY, {})
    subscribers[chat.id] = paused

    task = context.application.bot_data.get(LIVE_TASK_KEY)
    if task is None or task.done():
        context.application.bot_data["cdr_live_cursor"] = datetime.now(timezone.utc)
        context.application.bot_data[LIVE_TASK_KEY] = context.application.create_task(
            _cdr_live_loop(context.application), name="cdr-live-poller"
        )
    return True


async def _defer_live_user_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return

    subscribers = context.application.bot_data.get(LIVE_SUBSCRIBERS_KEY, {})
    is_live_active = chat.id in subscribers
    is_live_paused = context.user_data.get(PAUSED_LIVE_SUBSCRIBERS_KEY) is not None
    if not is_live_active and not is_live_paused:
        return

    await _pause_live_for_request(update, context)

    try:
        await context.bot.set_message_reaction(
            chat_id=chat.id,
            message_id=message.message_id,
            reaction=[ReactionTypeEmoji("👍")],
        )
    except Exception:
        logger.warning(
            "Could not react to request message %s in chat %s",
            message.message_id, chat.id, exc_info=True,
        )


async def _send_workflow_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, **kwargs: Any
) -> None:
    chat = update.effective_chat
    if chat:
        await context.bot.send_message(chat_id=chat.id, text=text, **kwargs)


async def _publish_deferred_live_messages(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    was_live = await _resume_live_after_request(update, context)
    chat = update.effective_chat
    if chat:
        if was_live:
            await context.bot.send_message(
                chat_id=chat.id,
                text=(
                    "✅ انتهت العملية.\n\n"
                    "لو عايز تطلب رنج تاني، ابعت اسم الرنج مباشرة من غير /start.\n"
                    "🟢 وضع الـ LIVE شغال حاليا وهتشوف أي تسميع جديد يوصل على المنصة."
                )
            )
        else:
            await context.bot.send_message(
                chat_id=chat.id,
                text=(
                    "✅ انتهت العملية.\n\n"
                    "لو عايز تطلب رنج تاني، ابعت اسم الرنج مباشرة من غير /start.\n"
                    "اضغط الزر بالأسفل لتشغيل وضع الـ LIVE:"
                ),
                reply_markup=_live_keyboard(is_live=False)
            )


async def start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    context.user_data.pop("selected_range", None)
    context.user_data.pop("pending_range_matches", None)
    context.user_data.pop("pending_range_message", None)
    context.user_data.pop(PAUSED_LIVE_SUBSCRIBERS_KEY, None)
    
    chat_id = update.effective_chat.id if update.effective_chat else None
    subscribers = context.application.bot_data.get(LIVE_SUBSCRIBERS_KEY, {})
    is_live_running = chat_id in subscribers

    if is_live_running:
        welcome_text = (
            "ابعت اسم الـ Range كتابةً زي ما هو ظاهر في لوحة IMS.\n\n"
            "🟢✨ <b>وضع الـ LIVE شغال حالياً</b> — التسميعات الجديدة هتوصلك فوراً في رسائل مستقلة."
        )
    else:
        welcome_text = (
            "ابعت اسم الـ Range كتابةً زي ما هو ظاهر في لوحة IMS.\n\n"
            "🔴✨ LIVE CDR\nاضغط الزر بالأسفل لعرض آخر 10 تسميعات، وبعدها كل تسميعة جديدة هتوصلك في رسالة مستقلة."
        )

    await update.effective_message.reply_text(
        welcome_text,
        parse_mode="HTML",
        reply_markup=_live_keyboard(is_live=is_live_running),
    )
    return WAITING_FOR_RANGE


async def react_to_valid_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
    *, chat_id: int | None = None, message_id: int | None = None,
) -> None:
    message = update.effective_message
    chat = update.effective_chat
    target_chat_id = chat_id if chat_id is not None else (chat.id if chat else None)
    target_message_id = message_id if message_id is not None else (message.message_id if message else None)
    if target_chat_id is None or target_message_id is None:
        return
    try:
        await context.bot.set_message_reaction(
            chat_id=target_chat_id,
            message_id=target_message_id,
            reaction=[ReactionTypeEmoji("👍")],
        )
    except Exception:
        logger.warning("Could not react to a validated admin message.", exc_info=True)


async def receive_range(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await _defer_live_user_message(update, context)
    requested_name = (update.effective_message.text or "").strip()
    if not requested_name:
        await _send_workflow_message(update, context, "اكتب اسم الرنج الأول.")
        await _publish_deferred_live_messages(update, context)
        return WAITING_FOR_RANGE

    try:
        ranges = await ims.get_ranges()
    except IMSAPIError as exc:
        await _send_workflow_message(update, context, f"تعذر البحث عن الرنج: {exc}")
        await _publish_deferred_live_messages(update, context)
        return ConversationHandler.END

    matches = match_country_ranges(requested_name, ranges)

    if not matches:
        await _send_workflow_message(update, context, 
            "مش قادر أحدد الدولة من الاسم ده. جرّب تكتب اسمها بالعربي أو الإنجليزي، "
            "أو جزءًا من اسم الرنج زي ما ظاهر في IMS."
        )
        await _publish_deferred_live_messages(update, context)
        return WAITING_FOR_RANGE

    if len(matches) > 1:
        context.user_data["pending_range_matches"] = [
            {"id": str(item["id"]), "name": str(item["name"])} for item in matches
        ]
        context.user_data["pending_range_message"] = {
            "chat_id": update.effective_chat.id,
            "message_id": update.effective_message.message_id,
        }
        options = "\n".join(
            f"{index}. {item['name']}" for index, item in enumerate(matches, start=1)
        )
        await _send_workflow_message(update, context, 
            f"الدولة دي ليها أكتر من رنج، اختار رقم الرنج المطلوب:\n{options}\n\n"
            "ابعت رقم الاختيار فقط."
        )
        return WAITING_FOR_RANGE_CHOICE

    item = matches[0]
    context.user_data["selected_range"] = {
        "id": str(item["id"]),
        "name": str(item["name"]),
    }

    await react_to_valid_message(update, context)

    await _send_workflow_message(
        update, context,
        "ابعت Username العميل بالظبط زي ما هو مكتوب في لوحة IMS."
    )
    return WAITING_FOR_CLIENT


async def receive_range_choice(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await _defer_live_user_message(update, context)
    raw_choice = (update.effective_message.text or "").strip()
    matches = context.user_data.get("pending_range_matches", [])
    if not raw_choice.isdigit():
        await _send_workflow_message(update, context, "ابعت رقم الرنج من القائمة فقط.")
        return WAITING_FOR_RANGE_CHOICE

    choice = int(raw_choice)
    if choice < 1 or choice > len(matches):
        await _send_workflow_message(update, context, "رقم الاختيار غير صحيح. اختار رقم من القائمة.")
        return WAITING_FOR_RANGE_CHOICE

    item = matches[choice - 1]
    context.user_data["selected_range"] = item
    original_message = context.user_data.pop("pending_range_message", {})
    context.user_data.pop("pending_range_matches", None)

    await react_to_valid_message(
        update, context,
        chat_id=original_message.get("chat_id"),
        message_id=original_message.get("message_id"),
    )
    await _send_workflow_message(
        update, context,
        "ابعت Username العميل بالظبط زي ما هو مكتوب في لوحة IMS."
    )
    return WAITING_FOR_CLIENT


async def prompt_next_range(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await _publish_deferred_live_messages(update, context)
    return WAITING_FOR_RANGE


async def receive_client(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await _defer_live_user_message(update, context)
    username = (update.effective_message.text or "").strip()

    if (
        not username
        or len(username) > 100
        or any(ch.isspace() for ch in username)
    ):
        await _send_workflow_message(update, context, 
            "Username غير صالح. ابعته من غير مسافات، أو استخدم /cancel."
        )
        return WAITING_FOR_CLIENT

    try:
        panel_clients = await ims.get_clients()
    except IMSAPIError as exc:
        await _send_workflow_message(update, context, 
            f"تعذر التأكد من اليوزر من لوحة IMS: {exc}\n"
            "لم يتم تغيير أي أرقام. ابعت Username العميل مرة تانية."
        )
        return WAITING_FOR_CLIENT

    if not any(client["username"] == username for client in panel_clients):
        await _send_workflow_message(update, context, 
            "اليوزر غلط، برجاء كتابة اليوزر الصحيح زي ما هو موجود في لوحة IMS."
        )
        return WAITING_FOR_CLIENT

    await react_to_valid_message(update, context)

    selected = context.user_data.get("selected_range")

    if not selected:
        await _send_workflow_message(update, context, 
            "اختيار الـ Range غير موجود. ابدأ من جديد باستخدام /start."
        )
        return await prompt_next_range(update, context)

    range_id = selected["id"]
    range_name = selected["name"]

    await _send_workflow_message(update, context, 
        f"جاري فحص أرقام {range_name} للعميل {username}..."
    )

    activity_count: int | None = None

    try:
        records = await ims.get_all_numbers_for_range(range_id)

        existing_for_client = [
            record
            for record in records
            if isinstance(record.get("client"), str)
            and record["client"].strip() == username
        ]

        if existing_for_client:
            old_numbers = list(dict.fromkeys(
                str(record["number"]).strip()
                for record in existing_for_client
                if str(record.get("number", "")).strip()
            ))

            if len(old_numbers) >= TARGET_NUMBER_COUNT:
                await _send_workflow_message(update, context, 
                    "هنراجع دلوقتي أرقامك ونتأكد إذا كنت اشتغلت بيها. برجاء الانتظار..."
                )
                try:
                    client_numbers = set(old_numbers)
                    activity_count = await cdr.count_client_range_activities(
                        range_name, client_numbers
                    )
                except CDRAPIError as cdr_exc:
                    await _send_workflow_message(update, context, 
                        f"تعذر التحقق من CDR، لذلك لم يتم نقل أو توزيع أي رقم.\n{cdr_exc}"
                    )
                    return await prompt_next_range(update, context)

                if activity_count < MIN_CDR_ACTIVITIES:
                    await _send_workflow_message(update, context, 
                        f"عدد العمليات اللي عملتها باستخدام أرقامك: {activity_count} عملية.\n"
                        "اشتغل بأرقامك وتعالى اطلب تاني."
                    )
                    return await prompt_next_range(update, context)
            else:
                await _send_workflow_message(update, context, 
                    f"معاك حاليًا {len(old_numbers)} رقم في الرنج، "
                    "وده أقل من 25؛ هنجددهم من غير شرط عدد العمليات."
                )

            await _send_workflow_message(update, context, 
                "تم الانتهاء من مراجعة أرقامك، وجاري تجهيز أرقام جديدة لك. برجاء الانتظار..."
            )

            for batch_start in range(0, len(old_numbers), 1000):
                batch = old_numbers[batch_start:batch_start + 1000]
                await ims.assign(TRANSFER_USERNAME, batch)

            await asyncio.sleep(2)
            moved_records = await ims.get_all_numbers_for_range(range_id)
            moved_to_transfer = {
                str(r.get("number", "")).strip()
                for r in moved_records
                if str(r.get("number", "")).strip() in set(old_numbers)
                and isinstance(r.get("client"), str)
                and r["client"].strip() == TRANSFER_USERNAME
            }
            if len(moved_to_transfer) != len(set(old_numbers)):
                await _send_workflow_message(update, context, 
                    "توقف آمن: نقل الأرقام لم يكتمل أو لم يمكن تأكيده. "
                    f"تم التأكد من نقل {len(moved_to_transfer)} من {len(set(old_numbers))} رقمًا.\n"
                    "لم يتم توزيع أرقام جديدة. راجع لوحة IMS قبل أي محاولة أخرى."
                )
                return await prompt_next_range(update, context)

            records = moved_records

        free_records = [
            record
            for record in records
            if record.get("client") is None
            or (
                isinstance(record.get("client"), str)
                and record["client"].strip() == ""
            )
        ]

        free_numbers: list[str] = []
        seen_numbers: set[str] = set()

        for record in free_records:
            number = str(record["number"]).strip()

            if number and number not in seen_numbers:
                seen_numbers.add(number)
                free_numbers.append(number)

        if not free_numbers:
            await _send_workflow_message(update, context, 
                f"الرنج {range_name} متوزع كل أرقامه حاليًا."
            )
            return await prompt_next_range(update, context)

        chosen_numbers = free_numbers[:TARGET_NUMBER_COUNT]
        requested_count = len(chosen_numbers)

        result = await ims.assign(username, chosen_numbers)

        response_assigned = result.get("assigned", "غير متاح")
        response_reassigned = result.get("reassigned", "غير متاح")
        response_skipped = result.get("skipped", "غير متاح")

        await asyncio.sleep(2)
        try:
            verified_records = await ims.get_all_numbers_for_range(range_id)
        except IMSAPIError as verify_exc:
            await _send_workflow_message(update, context, 
                "تم إرسال طلب التوزيع إلى IMS، لكن تعذر التأكد من النتيجة "
                "بإعادة قراءة الأرقام. لا تعِد التوزيع الآن.\n"
                f"سبب فشل التحقق: {verify_exc}\n"
                f"استجابة الطلب: assigned={response_assigned}, "
                f"reassigned={response_reassigned}, skipped={response_skipped}.\n"
                "راجع العميل في لوحة IMS قبل أي محاولة جديدة."
            )
            return await prompt_next_range(update, context)

        chosen_set = set(chosen_numbers)
        owned_by_client = {
            str(record.get("number", "")).strip()
            for record in verified_records
            if str(record.get("number", "")).strip() in chosen_set
            and isinstance(record.get("client"), str)
            and record["client"].strip() == username
        }
        verified_count = len(owned_by_client)

        if verified_count == requested_count:
            if existing_for_client:
                if activity_count is not None:
                    success_message = (
                        f"📊 عدد العمليات المسجلة من أرقامك: {activity_count} عملية.\n"
                        "🎉 تم تجديد أرقامك بنجاح!"
                    )
                else:
                    success_message = "🎉 تم تجديد أرقامك بنجاح!"
            else:
                success_message = "🎉 تم إضافة أرقام جديدة بنجاح!"

            if requested_count < TARGET_NUMBER_COUNT:
                success_message += (
                    f"\nتم توزيع {requested_count} رقم، ودي آخر الأرقام المتاحة حاليًا في الرنج. "
                    "تعالى اسألنا بعد شوية، ممكن نكون طلبنا إضافة أرقام جديدة."
                )
            await _send_workflow_message(update, context, success_message)
        else:
            await _send_workflow_message(update, context, 
                "تنبيه: طلب التوزيع أُرسل، لكن التحقق لم يؤكد امتلاك العميل "
                f"لكل الأرقام المطلوبة ({requested_count}).\n"
                f"الأرقام التي تأكدنا أنها أصبحت للعميل: {verified_count} من {requested_count}.\n"
                f"قيم استجابة API: assigned={response_assigned}, "
                f"reassigned={response_reassigned}, skipped={response_skipped}.\n"
                "لم أرسل طلب توزيع آخر. لا تعِد المحاولة قبل مراجعة الأرقام "
                "في لوحة IMS."
            )

        return await prompt_next_range(update, context)

    except IMSAPIError as exc:
        await _send_workflow_message(update, context, 
            f"تم إيقاف العملية بأمان ولم أبدأ طلب توزيع آخر:\n{exc}"
        )
        return await prompt_next_range(update, context)

    except (TypeError, ValueError, KeyError):
        logger.exception("Unexpected data format while processing assignment")

        await _send_workflow_message(update, context, 
            "استجابة البيانات من IMS غير متوقعة؛ أوقفت العملية للحماية. "
            "راجع السجلات أو لوحة IMS."
        )

        return await prompt_next_range(update, context)

    finally:
        context.user_data.pop("selected_range", None)
        context.user_data.pop("available_ranges", None)


async def cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    context.user_data.pop("selected_range", None)
    context.user_data.pop("available_ranges", None)
    context.user_data.pop("pending_range_matches", None)
    context.user_data.pop("pending_range_message", None)

    await _publish_deferred_live_messages(update, context)
    if update.effective_message:
        await _send_workflow_message(update, context, "تم إلغاء العملية.")

    return ConversationHandler.END


async def post_init(application: Application) -> None:
    logger.info("IMS Telegram bot started.")


async def post_shutdown(application: Application) -> None:
    await ims.close()
    await cdr.close()


def main() -> None:
    if not TELEGRAM_BOT_TOKEN or not IMS_TOKEN:
        raise RuntimeError(
            "Fill TELEGRAM_BOT_TOKEN and IMS_TOKEN near the top of this Python file before starting the bot."
        )

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    conversation = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_FOR_RANGE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_range
                )
            ],
            WAITING_FOR_RANGE_CHOICE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_range_choice
                )
            ],
            WAITING_FOR_CLIENT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_client
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
        per_chat=True,
        per_user=True,
    )

    application.add_handler(CallbackQueryHandler(cdr_live_button, pattern=r"^cdr_live_(?:on|off)$"))
    application.add_handler(conversation)
    application.add_handler(CommandHandler("cancel", cancel))

    application.run_polling()


if __name__ == "__main__":
    main()