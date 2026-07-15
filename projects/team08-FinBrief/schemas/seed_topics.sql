-- FinBrief default topic seed.
-- Safe to run repeatedly after schemas/supabase.sql.
-- Generated catalog: keep in sync with data/default_topics.json.

insert into topics (name, normalized_name, type, source_mapping)
values
(
    'USD/KRW 환율',
    'usdkrw',
    'indicator',
    '[
      {
        "provider": "yfinance",
        "ticker": "KRW=X",
        "query": "USD/KRW 환율",
        "news_keywords": [
          "환율",
          "원달러",
          "달러",
          "USD/KRW"
        ],
        "notes": "시연용 원달러 환율 ticker"
      },
      {
        "provider": "fred",
        "series_id": "DEXKOUS",
        "query": "USD/KRW exchange rate",
        "news_keywords": [
          "환율",
          "원달러",
          "달러"
        ],
        "notes": "FRED daily exchange rate"
      }
    ]'::jsonb
),
(
    '미국 10년물 금리',
    'us_rate',
    'indicator',
    '[
      {
        "provider": "fred",
        "series_id": "DGS10",
        "query": "미국 10년물 국채금리",
        "news_keywords": [
          "미국 금리",
          "국채금리",
          "10년물",
          "연준"
        ],
        "notes": "FRED 10-year treasury yield"
      },
      {
        "provider": "yfinance",
        "ticker": "^TNX",
        "query": "US 10-year treasury yield",
        "news_keywords": [
          "미국 금리",
          "국채금리",
          "10년물"
        ],
        "notes": "Yahoo Finance treasury yield proxy"
      }
    ]'::jsonb
),
(
    '나스닥',
    'nasdaq',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "^IXIC",
        "query": "나스닥 지수",
        "news_keywords": [
          "나스닥",
          "기술주",
          "미국 증시"
        ],
        "notes": "NASDAQ Composite"
      }
    ]'::jsonb
),
(
    '비트코인',
    'btc',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "BTC-USD",
        "query": "비트코인 가격",
        "news_keywords": [
          "비트코인",
          "가상자산",
          "암호화폐",
          "BTC"
        ],
        "notes": "Bitcoin USD spot proxy"
      }
    ]'::jsonb
),
(
    '반도체',
    'semi',
    'sector',
    '[
      {
        "provider": "yfinance",
        "ticker": "SOXX",
        "query": "반도체 섹터",
        "news_keywords": [
          "반도체",
          "AI 반도체",
          "엔비디아",
          "메모리"
        ],
        "notes": "Semiconductor ETF proxy"
      },
      {
        "provider": "rag",
        "query": "반도체 업황과 AI 반도체 뉴스",
        "news_keywords": [
          "반도체",
          "AI 반도체",
          "엔비디아",
          "HBM"
        ],
        "notes": "News-only sector retrieval"
      }
    ]'::jsonb
),
(
    '미국 2년물 금리',
    'us_rate_2y',
    'indicator',
    '[
      {
        "provider": "fred",
        "series_id": "DGS2",
        "query": "미국 2년물 국채금리",
        "news_keywords": [
          "미국 2년물",
          "단기금리",
          "국채금리"
        ],
        "notes": "FRED 2-year treasury yield"
      }
    ]'::jsonb
),
(
    '미국 기준금리',
    'fed_funds',
    'indicator',
    '[
      {
        "provider": "fred",
        "series_id": "FEDFUNDS",
        "query": "미국 연방기금금리",
        "news_keywords": [
          "기준금리",
          "연방기금금리",
          "연준",
          "FOMC"
        ],
        "notes": "FRED effective federal funds rate"
      }
    ]'::jsonb
),
(
    '한국 기준금리',
    'kr_base_rate',
    'indicator',
    '[
      {
        "provider": "ecos",
        "query": "한국은행 기준금리",
        "news_keywords": [
          "한국 기준금리",
          "한국은행",
          "금통위"
        ],
        "notes": "ECOS policy rate"
      }
    ]'::jsonb
),
(
    '한국 10년물 금리',
    'kr_rate_10y',
    'indicator',
    '[
      {
        "provider": "ecos",
        "query": "한국 국고채 10년 금리",
        "news_keywords": [
          "한국 국채",
          "국고채",
          "10년물"
        ],
        "notes": "ECOS treasury bond yield"
      }
    ]'::jsonb
),
(
    '미국 CPI',
    'us_cpi',
    'indicator',
    '[
      {
        "provider": "fred",
        "series_id": "CPIAUCSL",
        "query": "미국 소비자물가지수",
        "news_keywords": [
          "CPI",
          "소비자물가",
          "인플레이션",
          "물가"
        ],
        "notes": "FRED CPI all items"
      }
    ]'::jsonb
),
(
    '미국 근원 CPI',
    'us_core_cpi',
    'indicator',
    '[
      {
        "provider": "fred",
        "series_id": "CPILFESL",
        "query": "미국 근원 소비자물가",
        "news_keywords": [
          "근원 CPI",
          "근원물가",
          "인플레이션"
        ],
        "notes": "FRED core CPI"
      }
    ]'::jsonb
),
(
    '미국 근원 PCE 물가',
    'us_pce',
    'indicator',
    '[
      {
        "provider": "fred",
        "series_id": "PCEPILFE",
        "query": "미국 근원 PCE 물가지수",
        "news_keywords": [
          "PCE",
          "개인소비지출",
          "물가"
        ],
        "notes": "FRED core PCE price index"
      }
    ]'::jsonb
),
(
    '한국 CPI',
    'kr_cpi',
    'indicator',
    '[
      {
        "provider": "ecos",
        "query": "한국 소비자물가지수",
        "news_keywords": [
          "한국 물가",
          "소비자물가",
          "인플레이션"
        ],
        "notes": "ECOS consumer price index"
      }
    ]'::jsonb
),
(
    '미국 실업률',
    'us_unemployment',
    'indicator',
    '[
      {
        "provider": "fred",
        "series_id": "UNRATE",
        "query": "미국 실업률",
        "news_keywords": [
          "실업률",
          "고용",
          "노동시장"
        ],
        "notes": "FRED unemployment rate"
      }
    ]'::jsonb
),
(
    '미국 비농업 고용',
    'us_payrolls',
    'indicator',
    '[
      {
        "provider": "fred",
        "series_id": "PAYEMS",
        "query": "미국 비농업 고용지표",
        "news_keywords": [
          "비농업고용",
          "고용지표",
          "일자리"
        ],
        "notes": "FRED total nonfarm payrolls"
      }
    ]'::jsonb
),
(
    '미국 GDP',
    'us_gdp',
    'indicator',
    '[
      {
        "provider": "fred",
        "series_id": "GDPC1",
        "query": "미국 실질 GDP",
        "news_keywords": [
          "GDP",
          "경제성장률",
          "성장률"
        ],
        "notes": "FRED real GDP"
      }
    ]'::jsonb
),
(
    '한국 GDP',
    'kr_gdp',
    'indicator',
    '[
      {
        "provider": "ecos",
        "query": "한국 실질 GDP 성장률",
        "news_keywords": [
          "한국 GDP",
          "경제성장률",
          "성장률"
        ],
        "notes": "ECOS real GDP"
      }
    ]'::jsonb
),
(
    'VIX 변동성지수',
    'vix',
    'indicator',
    '[
      {
        "provider": "yfinance",
        "ticker": "^VIX",
        "query": "VIX 변동성지수",
        "news_keywords": [
          "VIX",
          "변동성",
          "공포지수"
        ],
        "notes": "CBOE volatility index"
      },
      {
        "provider": "fred",
        "series_id": "VIXCLS",
        "query": "CBOE volatility index",
        "news_keywords": [
          "VIX",
          "변동성"
        ],
        "notes": "FRED VIX close"
      }
    ]'::jsonb
),
(
    'WTI 유가',
    'wti',
    'indicator',
    '[
      {
        "provider": "yfinance",
        "ticker": "CL=F",
        "query": "WTI 원유 선물",
        "news_keywords": [
          "유가",
          "WTI",
          "국제유가",
          "원유"
        ],
        "notes": "WTI crude futures"
      },
      {
        "provider": "fred",
        "series_id": "DCOILWTICO",
        "query": "WTI crude oil price",
        "news_keywords": [
          "유가",
          "WTI"
        ],
        "notes": "FRED WTI spot"
      }
    ]'::jsonb
),
(
    '브렌트유',
    'brent',
    'indicator',
    '[
      {
        "provider": "yfinance",
        "ticker": "BZ=F",
        "query": "브렌트유 선물",
        "news_keywords": [
          "브렌트유",
          "유가",
          "국제유가"
        ],
        "notes": "Brent crude futures"
      }
    ]'::jsonb
),
(
    '천연가스',
    'natgas',
    'indicator',
    '[
      {
        "provider": "yfinance",
        "ticker": "NG=F",
        "query": "천연가스 선물",
        "news_keywords": [
          "천연가스",
          "가스价",
          "에너지"
        ],
        "notes": "Henry Hub natgas futures"
      }
    ]'::jsonb
),
(
    '달러 인덱스',
    'dxy',
    'indicator',
    '[
      {
        "provider": "yfinance",
        "ticker": "DX-Y.NYB",
        "query": "달러 인덱스",
        "news_keywords": [
          "달러인덱스",
          "DXY",
          "달러 강세"
        ],
        "notes": "US dollar index"
      },
      {
        "provider": "fred",
        "series_id": "DTWEXBGS",
        "query": "broad dollar index",
        "news_keywords": [
          "달러인덱스",
          "달러"
        ],
        "notes": "FRED broad dollar index"
      }
    ]'::jsonb
),
(
    'USD/JPY 환율',
    'usdjpy',
    'indicator',
    '[
      {
        "provider": "yfinance",
        "ticker": "JPY=X",
        "query": "달러엔 환율",
        "news_keywords": [
          "엔화",
          "달러엔",
          "USD/JPY",
          "엔저"
        ],
        "notes": "USD/JPY spot"
      },
      {
        "provider": "fred",
        "series_id": "DEXJPUS",
        "query": "USD/JPY exchange rate",
        "news_keywords": [
          "엔화",
          "달러엔"
        ],
        "notes": "FRED USD/JPY"
      }
    ]'::jsonb
),
(
    'EUR/USD 환율',
    'eurusd',
    'indicator',
    '[
      {
        "provider": "yfinance",
        "ticker": "EURUSD=X",
        "query": "유로달러 환율",
        "news_keywords": [
          "유로",
          "유로달러",
          "EUR/USD"
        ],
        "notes": "EUR/USD spot"
      }
    ]'::jsonb
),
(
    'USD/CNY 환율',
    'usdcny',
    'indicator',
    '[
      {
        "provider": "yfinance",
        "ticker": "CNY=X",
        "query": "달러위안 환율",
        "news_keywords": [
          "위안화",
          "달러위안",
          "USD/CNY"
        ],
        "notes": "USD/CNY spot"
      }
    ]'::jsonb
),
(
    '미국 기대 인플레이션(10년)',
    'breakeven_10y',
    'indicator',
    '[
      {
        "provider": "fred",
        "series_id": "T10YIE",
        "query": "미국 10년 기대인플레이션",
        "news_keywords": [
          "기대인플레이션",
          "BEI",
          "물가"
        ],
        "notes": "FRED 10Y breakeven inflation"
      }
    ]'::jsonb
),
(
    '미국 장단기 금리차(10Y-2Y)',
    'yield_spread',
    'indicator',
    '[
      {
        "provider": "fred",
        "series_id": "T10Y2Y",
        "query": "미국 장단기 금리차",
        "news_keywords": [
          "장단기 금리차",
          "금리 역전",
          "침체 신호"
        ],
        "notes": "FRED 10Y-2Y spread"
      }
    ]'::jsonb
),
(
    '미국 하이일드 스프레드',
    'hy_spread',
    'indicator',
    '[
      {
        "provider": "fred",
        "series_id": "BAMLH0A0HYM2",
        "query": "미국 하이일드 신용 스프레드",
        "news_keywords": [
          "하이일드",
          "신용 스프레드",
          "회사채"
        ],
        "notes": "FRED HY OAS"
      }
    ]'::jsonb
),
(
    '미국 소매판매',
    'us_retail_sales',
    'indicator',
    '[
      {
        "provider": "fred",
        "series_id": "RSAFS",
        "query": "미국 소매판매",
        "news_keywords": [
          "소매판매",
          "소비",
          "소비지표"
        ],
        "notes": "FRED advance retail sales"
      }
    ]'::jsonb
),
(
    '미국 소비자심리지수',
    'us_sentiment',
    'indicator',
    '[
      {
        "provider": "fred",
        "series_id": "UMCSENT",
        "query": "미시간 소비자심리지수",
        "news_keywords": [
          "소비자심리",
          "소비심리",
          "미시간지수"
        ],
        "notes": "FRED U. Michigan sentiment"
      }
    ]'::jsonb
),
(
    '미국 신규 실업수당 청구',
    'us_jobless_claims',
    'indicator',
    '[
      {
        "provider": "fred",
        "series_id": "ICSA",
        "query": "미국 신규 실업수당 청구건수",
        "news_keywords": [
          "실업수당",
          "신규청구",
          "고용"
        ],
        "notes": "FRED initial claims"
      }
    ]'::jsonb
),
(
    '미국 주택착공',
    'us_housing_starts',
    'indicator',
    '[
      {
        "provider": "fred",
        "series_id": "HOUST",
        "query": "미국 주택착공 건수",
        "news_keywords": [
          "주택착공",
          "주택시장",
          "부동산"
        ],
        "notes": "FRED housing starts"
      }
    ]'::jsonb
),
(
    '한국 무역수지',
    'kr_trade_balance',
    'indicator',
    '[
      {
        "provider": "ecos",
        "query": "한국 무역수지와 수출",
        "news_keywords": [
          "무역수지",
          "수출",
          "경상수지"
        ],
        "notes": "ECOS trade balance"
      }
    ]'::jsonb
),
(
    'S&P 500',
    'sp500',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "^GSPC",
        "query": "S&P 500 지수",
        "news_keywords": [
          "S&P500",
          "미국 증시",
          "스탠더드앤드푸어스"
        ],
        "notes": "S&P 500 index"
      }
    ]'::jsonb
),
(
    '다우존스',
    'dow',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "^DJI",
        "query": "다우존스 산업평균지수",
        "news_keywords": [
          "다우존스",
          "다우",
          "미국 증시"
        ],
        "notes": "Dow Jones Industrial Average"
      }
    ]'::jsonb
),
(
    '러셀 2000',
    'russell2000',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "^RUT",
        "query": "러셀 2000 중소형주 지수",
        "news_keywords": [
          "러셀2000",
          "중소형주",
          "미국 증시"
        ],
        "notes": "Russell 2000"
      }
    ]'::jsonb
),
(
    '코스피',
    'kospi',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "^KS11",
        "query": "코스피 지수",
        "news_keywords": [
          "코스피",
          "국내 증시",
          "KOSPI"
        ],
        "notes": "KOSPI index"
      }
    ]'::jsonb
),
(
    '코스닥',
    'kosdaq',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "^KQ11",
        "query": "코스닥 지수",
        "news_keywords": [
          "코스닥",
          "국내 증시",
          "KOSDAQ"
        ],
        "notes": "KOSDAQ index"
      }
    ]'::jsonb
),
(
    '니케이 225',
    'nikkei',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "^N225",
        "query": "니케이 225 지수",
        "news_keywords": [
          "니케이",
          "일본 증시",
          "닛케이"
        ],
        "notes": "Nikkei 225"
      }
    ]'::jsonb
),
(
    '항셍지수',
    'hangseng',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "^HSI",
        "query": "항셍지수",
        "news_keywords": [
          "항셍",
          "홍콩 증시",
          "중화권"
        ],
        "notes": "Hang Seng index"
      }
    ]'::jsonb
),
(
    '독일 DAX',
    'dax',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "^GDAXI",
        "query": "독일 DAX 지수",
        "news_keywords": [
          "DAX",
          "독일 증시",
          "유럽 증시"
        ],
        "notes": "DAX index"
      }
    ]'::jsonb
),
(
    '애플',
    'apple',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "AAPL",
        "query": "애플 주가",
        "news_keywords": [
          "애플",
          "아이폰",
          "빅테크"
        ],
        "notes": "Apple Inc."
      }
    ]'::jsonb
),
(
    '마이크로소프트',
    'microsoft',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "MSFT",
        "query": "마이크로소프트 주가",
        "news_keywords": [
          "마이크로소프트",
          "MS",
          "클라우드"
        ],
        "notes": "Microsoft Corp."
      }
    ]'::jsonb
),
(
    '엔비디아',
    'nvidia',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "NVDA",
        "query": "엔비디아 주가",
        "news_keywords": [
          "엔비디아",
          "GPU",
          "AI 반도체"
        ],
        "notes": "NVIDIA Corp."
      }
    ]'::jsonb
),
(
    '아마존',
    'amazon',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "AMZN",
        "query": "아마존 주가",
        "news_keywords": [
          "아마존",
          "이커머스",
          "AWS"
        ],
        "notes": "Amazon.com"
      }
    ]'::jsonb
),
(
    '알파벳(구글)',
    'alphabet',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "GOOGL",
        "query": "알파벳 구글 주가",
        "news_keywords": [
          "구글",
          "알파벳",
          "검색"
        ],
        "notes": "Alphabet Inc."
      }
    ]'::jsonb
),
(
    '메타',
    'meta',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "META",
        "query": "메타 주가",
        "news_keywords": [
          "메타",
          "페이스북",
          "소셜미디어"
        ],
        "notes": "Meta Platforms"
      }
    ]'::jsonb
),
(
    '테슬라',
    'tesla',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "TSLA",
        "query": "테슬라 주가",
        "news_keywords": [
          "테슬라",
          "전기차",
          "일론 머스크"
        ],
        "notes": "Tesla Inc."
      }
    ]'::jsonb
),
(
    '브로드컴',
    'broadcom',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "AVGO",
        "query": "브로드컴 주가",
        "news_keywords": [
          "브로드컴",
          "반도체",
          "AI 반도체"
        ],
        "notes": "Broadcom Inc."
      }
    ]'::jsonb
),
(
    'AMD',
    'amd',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "AMD",
        "query": "AMD 주가",
        "news_keywords": [
          "AMD",
          "CPU",
          "반도체"
        ],
        "notes": "Advanced Micro Devices"
      }
    ]'::jsonb
),
(
    'TSMC',
    'tsmc',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "TSM",
        "query": "TSMC 주가",
        "news_keywords": [
          "TSMC",
          "파운드리",
          "반도체"
        ],
        "notes": "Taiwan Semiconductor"
      }
    ]'::jsonb
),
(
    'ASML',
    'asml',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "ASML",
        "query": "ASML 주가",
        "news_keywords": [
          "ASML",
          "노광장비",
          "반도체장비"
        ],
        "notes": "ASML Holding"
      }
    ]'::jsonb
),
(
    '삼성전자',
    'samsung_elec',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "005930.KS",
        "query": "삼성전자 주가",
        "news_keywords": [
          "삼성전자",
          "메모리",
          "반도체"
        ],
        "notes": "Samsung Electronics"
      }
    ]'::jsonb
),
(
    'SK하이닉스',
    'sk_hynix',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "000660.KS",
        "query": "SK하이닉스 주가",
        "news_keywords": [
          "SK하이닉스",
          "HBM",
          "메모리"
        ],
        "notes": "SK hynix"
      }
    ]'::jsonb
),
(
    '현대차',
    'hyundai_motor',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "005380.KS",
        "query": "현대차 주가",
        "news_keywords": [
          "현대차",
          "자동차",
          "완성차"
        ],
        "notes": "Hyundai Motor"
      }
    ]'::jsonb
),
(
    'LG에너지솔루션',
    'lg_energy',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "373220.KS",
        "query": "LG에너지솔루션 주가",
        "news_keywords": [
          "LG에너지솔루션",
          "2차전지",
          "배터리"
        ],
        "notes": "LG Energy Solution"
      }
    ]'::jsonb
),
(
    '삼성바이오로직스',
    'samsung_bio',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "207940.KS",
        "query": "삼성바이오로직스 주가",
        "news_keywords": [
          "삼성바이오로직스",
          "바이오",
          "위탁생산"
        ],
        "notes": "Samsung Biologics"
      }
    ]'::jsonb
),
(
    '네이버',
    'naver',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "035420.KS",
        "query": "네이버 주가",
        "news_keywords": [
          "네이버",
          "플랫폼",
          "인터넷"
        ],
        "notes": "NAVER Corp."
      }
    ]'::jsonb
),
(
    '카카오',
    'kakao',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "035720.KS",
        "query": "카카오 주가",
        "news_keywords": [
          "카카오",
          "플랫폼",
          "메신저"
        ],
        "notes": "Kakao Corp."
      }
    ]'::jsonb
),
(
    '이더리움',
    'ethereum',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "ETH-USD",
        "query": "이더리움 가격",
        "news_keywords": [
          "이더리움",
          "가상자산",
          "ETH",
          "암호화폐"
        ],
        "notes": "Ethereum USD"
      }
    ]'::jsonb
),
(
    '리플(XRP)',
    'ripple',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "XRP-USD",
        "query": "리플 가격",
        "news_keywords": [
          "리플",
          "XRP",
          "가상자산"
        ],
        "notes": "XRP USD"
      }
    ]'::jsonb
),
(
    '솔라나',
    'solana',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "SOL-USD",
        "query": "솔라나 가격",
        "news_keywords": [
          "솔라나",
          "SOL",
          "가상자산"
        ],
        "notes": "Solana USD"
      }
    ]'::jsonb
),
(
    '금',
    'gold',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "GC=F",
        "query": "금 선물 가격",
        "news_keywords": [
          "금",
          "금값",
          "안전자산"
        ],
        "notes": "Gold futures"
      }
    ]'::jsonb
),
(
    '은',
    'silver',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "SI=F",
        "query": "은 선물 가격",
        "news_keywords": [
          "은",
          "은값",
          "귀금속"
        ],
        "notes": "Silver futures"
      }
    ]'::jsonb
),
(
    '구리',
    'copper',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "HG=F",
        "query": "구리 선물 가격",
        "news_keywords": [
          "구리",
          "구리값",
          "경기민감"
        ],
        "notes": "Copper futures"
      }
    ]'::jsonb
),
(
    '나스닥100 ETF(QQQ)',
    'qqq_etf',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "QQQ",
        "query": "나스닥100 ETF",
        "news_keywords": [
          "QQQ",
          "나스닥100",
          "기술주 ETF"
        ],
        "notes": "Invesco QQQ"
      }
    ]'::jsonb
),
(
    '미국 장기국채 ETF(TLT)',
    'tlt_etf',
    'asset',
    '[
      {
        "provider": "yfinance",
        "ticker": "TLT",
        "query": "미국 장기국채 ETF",
        "news_keywords": [
          "장기국채",
          "TLT",
          "채권 ETF"
        ],
        "notes": "iShares 20+ Year Treasury"
      }
    ]'::jsonb
),
(
    '2차전지',
    'battery',
    'sector',
    '[
      {
        "provider": "yfinance",
        "ticker": "LIT",
        "query": "2차전지 배터리 섹터",
        "news_keywords": [
          "2차전지",
          "배터리",
          "리튬"
        ],
        "notes": "Global lithium & battery ETF"
      },
      {
        "provider": "rag",
        "query": "2차전지 업황 뉴스",
        "news_keywords": [
          "2차전지",
          "전기차 배터리",
          "양극재"
        ],
        "notes": "News-only"
      }
    ]'::jsonb
),
(
    '자동차',
    'auto',
    'sector',
    '[
      {
        "provider": "rag",
        "query": "자동차 산업 업황",
        "news_keywords": [
          "자동차",
          "완성차",
          "전기차"
        ],
        "notes": "News-only sector"
      }
    ]'::jsonb
),
(
    '바이오/헬스케어',
    'bio',
    'sector',
    '[
      {
        "provider": "yfinance",
        "ticker": "XLV",
        "query": "헬스케어 섹터",
        "news_keywords": [
          "바이오",
          "제약",
          "헬스케어"
        ],
        "notes": "Health Care Select Sector"
      }
    ]'::jsonb
),
(
    '금융/은행',
    'finance',
    'sector',
    '[
      {
        "provider": "yfinance",
        "ticker": "XLF",
        "query": "금융 섹터",
        "news_keywords": [
          "은행",
          "금융",
          "증권"
        ],
        "notes": "Financial Select Sector"
      }
    ]'::jsonb
),
(
    '에너지',
    'energy',
    'sector',
    '[
      {
        "provider": "yfinance",
        "ticker": "XLE",
        "query": "에너지 섹터",
        "news_keywords": [
          "에너지",
          "정유",
          "석유"
        ],
        "notes": "Energy Select Sector"
      }
    ]'::jsonb
),
(
    '유틸리티',
    'utilities',
    'sector',
    '[
      {
        "provider": "yfinance",
        "ticker": "XLU",
        "query": "유틸리티 섹터",
        "news_keywords": [
          "유틸리티",
          "전력",
          "전기요금"
        ],
        "notes": "Utilities Select Sector"
      }
    ]'::jsonb
),
(
    '필수소비재',
    'consumer_staples',
    'sector',
    '[
      {
        "provider": "yfinance",
        "ticker": "XLP",
        "query": "필수소비재 섹터",
        "news_keywords": [
          "필수소비재",
          "소비재",
          "생활필수품"
        ],
        "notes": "Consumer Staples Select"
      }
    ]'::jsonb
),
(
    '임의소비재',
    'consumer_disc',
    'sector',
    '[
      {
        "provider": "yfinance",
        "ticker": "XLY",
        "query": "임의소비재 섹터",
        "news_keywords": [
          "임의소비재",
          "유통",
          "리테일"
        ],
        "notes": "Consumer Discretionary Select"
      }
    ]'::jsonb
),
(
    '산업재',
    'industrials',
    'sector',
    '[
      {
        "provider": "yfinance",
        "ticker": "XLI",
        "query": "산업재 섹터",
        "news_keywords": [
          "산업재",
          "기계",
          "설비"
        ],
        "notes": "Industrial Select Sector"
      }
    ]'::jsonb
),
(
    '소재',
    'materials',
    'sector',
    '[
      {
        "provider": "yfinance",
        "ticker": "XLB",
        "query": "소재 섹터",
        "news_keywords": [
          "소재",
          "화학",
          "원자재"
        ],
        "notes": "Materials Select Sector"
      }
    ]'::jsonb
),
(
    '부동산/리츠',
    'realestate',
    'sector',
    '[
      {
        "provider": "yfinance",
        "ticker": "XLRE",
        "query": "부동산 리츠 섹터",
        "news_keywords": [
          "부동산",
          "리츠",
          "REITs"
        ],
        "notes": "Real Estate Select Sector"
      }
    ]'::jsonb
),
(
    '방산',
    'defense',
    'sector',
    '[
      {
        "provider": "yfinance",
        "ticker": "ITA",
        "query": "방산 국방 섹터",
        "news_keywords": [
          "방산",
          "국방",
          "무기"
        ],
        "notes": "Aerospace & Defense ETF"
      }
    ]'::jsonb
),
(
    '통신',
    'telecom',
    'sector',
    '[
      {
        "provider": "rag",
        "query": "통신 산업 업황",
        "news_keywords": [
          "통신",
          "5G",
          "통신사"
        ],
        "notes": "News-only sector"
      }
    ]'::jsonb
),
(
    '조선',
    'shipbuilding',
    'sector',
    '[
      {
        "provider": "rag",
        "query": "조선 업황과 수주",
        "news_keywords": [
          "조선",
          "선박",
          "수주"
        ],
        "notes": "News-only sector"
      }
    ]'::jsonb
),
(
    '철강',
    'steel',
    'sector',
    '[
      {
        "provider": "rag",
        "query": "철강 업황",
        "news_keywords": [
          "철강",
          "제철",
          "포스코"
        ],
        "notes": "News-only sector"
      }
    ]'::jsonb
),
(
    '화학',
    'chemical',
    'sector',
    '[
      {
        "provider": "rag",
        "query": "석유화학 업황",
        "news_keywords": [
          "화학",
          "석유화학",
          "정밀화학"
        ],
        "notes": "News-only sector"
      }
    ]'::jsonb
),
(
    '항공/여행',
    'airline_travel',
    'sector',
    '[
      {
        "provider": "yfinance",
        "ticker": "JETS",
        "query": "항공 여행 섹터",
        "news_keywords": [
          "항공",
          "여행",
          "항공사"
        ],
        "notes": "US Global Jets ETF"
      }
    ]'::jsonb
),
(
    '태양광/신재생',
    'solar',
    'sector',
    '[
      {
        "provider": "yfinance",
        "ticker": "TAN",
        "query": "태양광 신재생에너지 섹터",
        "news_keywords": [
          "태양광",
          "신재생에너지",
          "재생에너지"
        ],
        "notes": "Solar ETF"
      }
    ]'::jsonb
),
(
    '게임',
    'game',
    'sector',
    '[
      {
        "provider": "rag",
        "query": "게임 산업 업황",
        "news_keywords": [
          "게임",
          "게임주",
          "콘솔"
        ],
        "notes": "News-only sector"
      }
    ]'::jsonb
),
(
    '해운',
    'shipping',
    'sector',
    '[
      {
        "provider": "rag",
        "query": "해운 업황과 운임",
        "news_keywords": [
          "해운",
          "운임",
          "컨테이너"
        ],
        "notes": "News-only sector"
      }
    ]'::jsonb
),
(
    'AI/인공지능',
    'ai',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "AI 인공지능 관련 뉴스",
        "news_keywords": [
          "AI",
          "인공지능",
          "생성형 AI"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    '생성형 AI',
    'genai',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "생성형 AI 뉴스",
        "news_keywords": [
          "생성형 AI",
          "챗GPT",
          "LLM"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    '데이터센터',
    'datacenter',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "데이터센터 뉴스",
        "news_keywords": [
          "데이터센터",
          "서버",
          "전력수요"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    '클라우드',
    'cloud',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "클라우드 산업 뉴스",
        "news_keywords": [
          "클라우드",
          "SaaS",
          "AWS"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    '자율주행',
    'self_driving',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "자율주행 뉴스",
        "news_keywords": [
          "자율주행",
          "로보택시",
          "자율주행차"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    '로봇',
    'robotics',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "로봇 로보틱스 뉴스",
        "news_keywords": [
          "로봇",
          "로보틱스",
          "휴머노이드"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    '전기차',
    'ev',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "전기차 뉴스",
        "news_keywords": [
          "전기차",
          "EV",
          "충전인프라"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    '인플레이션',
    'inflation',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "인플레이션 뉴스",
        "news_keywords": [
          "인플레이션",
          "물가상승",
          "디스인플레이션"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    '경기침체',
    'recession',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "경기침체 뉴스",
        "news_keywords": [
          "경기침체",
          "리세션",
          "침체"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    '연준 통화정책',
    'fed_policy',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "연준 통화정책 뉴스",
        "news_keywords": [
          "연준",
          "FOMC",
          "통화정책"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    '금리인하',
    'rate_cut',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "금리인하 피벗 뉴스",
        "news_keywords": [
          "금리인하",
          "피벗",
          "통화완화"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    '지정학 리스크',
    'geopolitics',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "지정학 리스크 뉴스",
        "news_keywords": [
          "지정학",
          "지정학 리스크",
          "안보"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    '중동 정세',
    'middle_east',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "중동 정세 뉴스",
        "news_keywords": [
          "중동",
          "이스라엘",
          "호르무즈"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    '미중 갈등',
    'us_china',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "미중 갈등 뉴스",
        "news_keywords": [
          "미중갈등",
          "미중",
          "수출규제"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    '관세/무역전쟁',
    'tariff',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "관세 무역전쟁 뉴스",
        "news_keywords": [
          "관세",
          "무역전쟁",
          "무역분쟁"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    '공급망',
    'supply_chain',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "공급망 뉴스",
        "news_keywords": [
          "공급망",
          "물류",
          "리쇼어링"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    'ESG/탄소중립',
    'esg',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "ESG 탄소중립 뉴스",
        "news_keywords": [
          "ESG",
          "탄소중립",
          "친환경"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    '배당주',
    'dividend',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "배당주 뉴스",
        "news_keywords": [
          "배당",
          "배당주",
          "배당수익률"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    '실적시즌',
    'earnings',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "실적 어닝시즌 뉴스",
        "news_keywords": [
          "실적",
          "어닝시즌",
          "실적발표"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    'IPO/공모주',
    'ipo',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "IPO 공모주 뉴스",
        "news_keywords": [
          "IPO",
          "상장",
          "공모주"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    'M&A',
    'ma',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "M&A 인수합병 뉴스",
        "news_keywords": [
          "M&A",
          "인수합병",
          "합병"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    '자사주 매입',
    'buyback',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "자사주 매입 주주환원 뉴스",
        "news_keywords": [
          "자사주",
          "자사주매입",
          "주주환원"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    '스테이블코인',
    'stablecoin',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "스테이블코인 뉴스",
        "news_keywords": [
          "스테이블코인",
          "가상자산 규제",
          "CBDC"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    '사이버보안',
    'cybersecurity',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "사이버보안 뉴스",
        "news_keywords": [
          "사이버보안",
          "보안",
          "해킹"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    '우주항공',
    'space',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "우주항공 뉴스",
        "news_keywords": [
          "우주",
          "항공우주",
          "위성"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    '비만치료제(GLP-1)',
    'glp1',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "비만치료제 GLP-1 뉴스",
        "news_keywords": [
          "비만치료제",
          "GLP-1",
          "위고비"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    '전력망/전력인프라',
    'power_grid',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "전력망 전력인프라 뉴스",
        "news_keywords": [
          "전력망",
          "전력인프라",
          "송전"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    '양자컴퓨팅',
    'quantum',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "양자컴퓨팅 뉴스",
        "news_keywords": [
          "양자컴퓨팅",
          "퀀텀",
          "양자"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    '원자력/SMR',
    'nuclear',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "원자력 SMR 뉴스",
        "news_keywords": [
          "원자력",
          "원전",
          "SMR"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
),
(
    '리쇼어링',
    'reshoring',
    'keyword',
    '[
      {
        "provider": "rag",
        "query": "리쇼어링 공급망 재편 뉴스",
        "news_keywords": [
          "리쇼어링",
          "온쇼어링",
          "생산기지"
        ],
        "notes": "Theme keyword"
      }
    ]'::jsonb
)
on conflict (normalized_name) do update
set
    name = excluded.name,
    type = excluded.type,
    source_mapping = excluded.source_mapping,
    updated_at = now();
