# ♻️ 중국 플라스틱 원자재 가격 대시보드

중국 플라스틱 원자재(PP·PE·PS·ABS·PC·POM·PA6·PA66·PET·HDPE·PVC·LDPE) 가격을
매일 자동으로 수집해 보여주는 Streamlit 대시보드입니다. **두 출처를 동시에 수집**하고,
화면 왼쪽에서 어느 출처를 볼지 고를 수 있습니다.

- **출처 1 — RawMex**: [생의사(生意社) 실거래 플랫폼](https://www.rawmex.cn/trade/c-15/) ·
  橡塑 카테고리에 올라오는 실제 판매 매물(브랜드·등급·단가·물량·지역)의 평균. PA6/PA66 포함.
- **출처 2 — 금투망**: [金投网(cngold.org) 가격 채널](https://m.cngold.org/price/lm3143/) ·
  塑料 채널의 하루 대표 참고가 한 줄. PA(나일론)는 이 채널에 없음.
- **환율**: 무료 공개 API(open.er-api.com / exchangerate-api.com)에서 매일 USD/CNY 수집 (출처 공통)
- **수집 방식**: GitHub Actions가 매일 `scraper.py`를 실행해 두 출처를 모두 `data/` 폴더에 누적 저장
- **화면**: Streamlit Community Cloud에 무료로 배포 가능

⚠️ 두 출처 모두 공개 웹페이지의 가격 정보를 참고용으로 수집한 것이며, 실제
거래가격·체결가와 다를 수 있습니다. 정식 계약/구매 결정에는 반드시 직접 거래처에
견적을 확인하세요. 두 출처는 가격 산정 방식이 달라서(RawMex=실매물 평균,
금투망=하루 대표가) 같은 날짜·품목이라도 값 차이가 날 수 있습니다 — 이건 버그가
아니라 원래 두 사이트가 서로 다른 방식으로 시세를 집계하기 때문입니다.

**이전 버전(RawMex 또는 cngold 단일 출처)에서 넘어오신 경우**: `data/prices.csv`에
`source` 컬럼이 새로 추가됐습니다. 이 스크립트는 `source` 컬럼이 없는 예전 파일도
자동으로 인식해서(전부 RawMex로 간주) 문제없이 열리지만, 금투망 데이터를 함께
보시려면 `python scraper.py`를 한 번 더 실행해 금투망분을 추가로 수집해주세요.


---

## 1. 로컬에서 먼저 테스트하기

```bash
# 1) 압축 풀기 후 폴더로 이동
cd plastic-price-dashboard

# 2) 패키지 설치
pip install -r requirements.txt

# 3) 데이터 한 번 수집해보기 (며칠 반복 실행하면 그래프에 추세가 생깁니다)
python scraper.py

# 4) 대시보드 실행
streamlit run streamlit_app.py
```

브라우저에서 `http://localhost:8501` 이 열리면 성공입니다.

> 참고: 개발 샌드박스 환경에서는 외부 네트워크 접근이 제한되어 있어 rawmex.cn에
> 직접 접속하지 못하고 오류가 날 수 있습니다. 사용자의 로컬 PC나 GitHub Actions처럼
> 일반 인터넷 환경에서는 정상적으로 접속됩니다.

---

## 2. GitHub 저장소 만들기

1. GitHub에서 새 저장소(예: `plastic-price-dashboard`)를 생성합니다. (Public 권장,
   Streamlit Cloud 무료 플랜은 Public 저장소만 지원합니다)
2. 이 폴더 전체를 저장소에 업로드합니다.

```bash
git init
git add .
git commit -m "init: 플라스틱 가격 대시보드 (RawMex 기반)"
git branch -M main
git remote add origin https://github.com/<내계정>/plastic-price-dashboard.git
git push -u origin main
```

3. GitHub Actions는 별도 설정 없이 저장소에 `.github/workflows/scrape.yml`이
   포함되어 있으면 자동으로 매일 실행됩니다. (한국시간 매일 18:10)
   - Actions 탭 → 워크플로우 선택 → **Run workflow** 버튼으로 수동 실행도 가능합니다.
   - 저장소 Settings → Actions → General → Workflow permissions를
     **"Read and write permissions"** 로 설정해야 자동 커밋이 가능합니다.

---

## 3. Streamlit Community Cloud에 배포하기

1. https://share.streamlit.io 접속 → GitHub 계정으로 로그인
2. **New app** → 방금 만든 저장소 선택
3. Main file path: `streamlit_app.py`
4. **Deploy** 클릭

몇 분 후 `https://<앱이름>.streamlit.app` 주소가 생성됩니다.

---

## 4. 원자재 종류 추가/변경하기

`scraper.py`에는 두 출처의 설정이 따로 있습니다.

- **RawMex**: 상단의 `RAWMEX_MATERIAL_SID` 딕셔너리(품목 코드 → RawMex 품목 ID)에
  추가하세요. ID는 https://www.rawmex.cn/trade/c-15/ (橡塑 카테고리) 페이지의
  필터 목록에서 확인할 수 있습니다. 링크가 `.../trade/s-158/` 형태면 `158`이 ID입니다.
- **금투망**: `CNGOLD_TAG_TO_CODE` 딕셔너리에 "XX报价" 형태의 태그와 코드를 추가하세요.
  금투망 塑料 목록(https://m.cngold.org/price/lm3143/)에 매일 올라오는 태그 기준입니다.

두 곳 모두 수정했다면 `streamlit_app.py`의 `MATERIAL_LABELS`에도 같은 코드로
한국어 라벨을 추가해주세요. (RawMex 예시)

```python
RAWMEX_MATERIAL_SID = {
    ...
    "LLDPE": 69,
    "PMMA": 518,
}
MATERIAL_LABELS = {
    ...
    "LLDPE": "LLDPE (선형저밀도폴리에틸렌)",
    "PMMA": "PMMA (아크릴)",
}
```

---

## 5. 파일 구조

```
plastic-price-dashboard/
├── scraper.py                   # 가격/환율 수집 스크립트 (금투망 + RawMex 동시 수집)
├── streamlit_app.py             # 대시보드 화면 (좌측에서 출처 선택)
├── requirements.txt             # 필요 패키지
├── data/
│   ├── prices.csv               # 일별 품목별 평균/최저/최고가 (source 컬럼으로 출처 구분)
│   ├── prices_detail.csv        # 매물/기사 단위 세부 가격 (원본)
│   └── fx.csv                   # 일별 USD/CNY 환율
├── .streamlit/config.toml       # 화면 테마 설정
├── .github/workflows/scrape.yml # 매일 자동 수집 설정
└── README.md
```

---

## 6. 문제 해결

- **접속 차단/오류**: 사이트가 요청 빈도를 제한하는 경우입니다.
  `scraper.py`의 `SLEEP_BETWEEN_REQUESTS` 값을 늘리거나 User-Agent를 바꿔보세요.
- **가격이 이상하게 파싱됨 / 특정 품목이 안 보임**: 사이트가 표 구조를 바꾼 경우입니다.
  RawMex는 `rawmex_parse_listing_page()`, 금투망은 `cngold_parse_price_rows()` /
  `cngold_discover_articles()` 함수를 사이트 구조에 맞게 수정하세요.
- **한쪽 출처만 안 보임**: 대시보드 왼쪽 "데이터 출처"에서 다른 쪽을 선택했는지,
  또는 그 출처로 아직 수집된 데이터가 없는지 확인하세요. 화면에 안내 문구가 뜹니다.
- **매물 수가 너무 적음(RawMex)**: 기본값은 품목당 1페이지(최신 약 20개 매물)만
  가져옵니다. 더 많이 모으고 싶으면 `scraper.py`의 `PAGES_PER_MATERIAL` 값을 늘리세요.
- **환율이 안 들어옴**: 무료 API 두 곳(open.er-api.com, exchangerate-api.com)이
  동시에 실패한 경우로, 앱은 이전에 저장된 마지막 환율 값을 계속 사용합니다.
- **매일 자동 수집이 안 됨**: 저장소 Settings → Actions 권한 설정을 확인하세요.
