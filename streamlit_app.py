"""
중국 플라스틱 원자재 가격 대시보드
- 데이터는 scraper.py가 매일 GitHub Actions로 수집한 data/prices.csv / data/fx.csv 를 사용합니다.
- 출처: 생의사(生意社) 실거래 플랫폼 RawMex — https://www.rawmex.cn/ (橡塑 카테고리 매물)
"""

import os
import subprocess
import sys
from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="중국 플라스틱 원자재 가격 대시보드", page_icon="♻️", layout="wide")

# ---------------------------------------------------------------------------
# 디자인: Stripe/Linear 스타일 — 화이트 배경, 절제된 인디고 액센트 하나,
# 헤어라인 보더 중심 카드, 두꺼운 그림자/알록달록한 색 지양
# ---------------------------------------------------------------------------
ACCENT = "#4F46E5"       # 메인 액센트 (CNY 라인, 활성 탭, 버튼 hover)
ACCENT_LIGHT = "#A5B4FC"  # 액센트의 옅은 톤 (USD 라인 등 보조 데이터)
INK = "#0F172A"
SUBTLE = "#6B7280"
LINE = "#E5E7EB"
UP_COLOR = "#DC2626"     # 국내 관행에 맞춰 상승=빨강
DOWN_COLOR = "#2563EB"   # 하락=파랑 (참고용, st.metric 자체는 빨강/초록만 지원)

st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"], [data-testid="stHeader"] {{
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }}

    /* 상단 여백 축소 */
    .block-container {{
        padding-top: 2rem;
        padding-bottom: 2rem;
    }}
    [data-testid="stSidebar"] .block-container {{
        padding-top: 1.5rem;
    }}
    [data-testid="stHeader"] {{
        height: 2.5rem;
    }}

    h1, h2, h3 {{
        letter-spacing: -0.02em;
        font-weight: 700;
        color: {INK};
    }}

    [data-testid="stSidebar"] {{
        background-color: #FAFAFA;
        border-right: 1px solid {LINE};
    }}

    /* 사이드바 컴팩트 레이아웃: 위젯 간 여백을 적당히 축소 (너무 빡빡하지 않게) */
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{
        gap: 0.75rem;
    }}

    /* 사이드바 안내 문구(수집 안내) 글씨 크기 축소 */
    [data-testid="stAlert"] {{
        padding: 0.5rem 0.75rem;
    }}
    [data-testid="stAlert"] p {{
        font-size: 0.78rem;
        line-height: 1.4;
        margin-bottom: 0;
    }}

    [data-testid="stMetricValue"] {{
        font-weight: 700;
        color: {INK};
    }}
    [data-testid="stMetricLabel"] {{
        color: {SUBTLE};
        font-size: 0.82rem;
    }}

    div[data-testid="stVerticalBlockBorderWrapper"] {{
        border-radius: 10px !important;
        border-color: {LINE} !important;
    }}

    .stButton > button {{
        border-radius: 8px;
        border: 1px solid {LINE};
        background-color: #FFFFFF;
        color: {INK};
        font-weight: 500;
        box-shadow: none;
    }}
    .stButton > button:hover {{
        border-color: {ACCENT};
        color: {ACCENT};
    }}

    .stTabs [data-baseweb="tab-list"] {{
        gap: 4px;
        border-bottom: 1px solid {LINE};
    }}
    .stTabs [data-baseweb="tab"] {{
        background-color: transparent;
        border-radius: 0px;
        padding: 8px 14px;
        color: {SUBTLE};
        font-weight: 500;
    }}
    .stTabs [aria-selected="true"] {{
        color: {ACCENT} !important;
        border-bottom: 2px solid {ACCENT};
        background-color: transparent !important;
    }}

    [data-testid="stDataFrame"] {{
        border: 1px solid {LINE};
        border-radius: 8px;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

PRICES_CSV = "data/prices.csv"
FX_CSV = "data/fx.csv"

MATERIAL_LABELS = {
    "PP": "PP (폴리프로필렌)",
    "PE": "PE (폴리에틸렌, 범용)",
    "PS": "PS (폴리스티렌)",
    "ABS": "ABS 수지",
    "PC": "PC (폴리카보네이트)",
    "POM": "POM (폴리아세탈)",
    "PA6": "PA6 (나일론6)",
    "PA66": "PA66 (나일론66)",
    "PET": "PET (페트)",
    "HDPE": "HDPE (고밀도폴리에틸렌)",
    "PVC": "PVC (폴리염화비닐)",
    "LDPE": "LDPE (저밀도폴리에틸렌)",
}

DEFAULT_FX = 7.15  # fx.csv가 아직 없을 때 쓰는 임시 환율(참고용)


# ---------------------------------------------------------------------------
# 데이터 로드
# ---------------------------------------------------------------------------
@st.cache_data(ttl=600)
def load_prices() -> pd.DataFrame:
    try:
        df = pd.read_csv(PRICES_CSV, parse_dates=["date"])
    except FileNotFoundError:
        return pd.DataFrame(
            columns=["date", "material", "source", "avg_price", "min_price", "max_price", "spec_count", "unit", "source_url"]
        )
    if "source" not in df.columns:
        # 이전 버전(단일 출처) 데이터와의 호환 — 출처 정보가 없으면 rawmex로 간주
        df["source"] = "rawmex"
    return df.sort_values(["material", "date"]).reset_index(drop=True)


@st.cache_data(ttl=600)
def load_fx() -> pd.DataFrame:
    try:
        df = pd.read_csv(FX_CSV, parse_dates=["date"])
        return df.sort_values("date").reset_index(drop=True)
    except FileNotFoundError:
        return pd.DataFrame(columns=["date", "usd_cny"])


BASELINE_CSV = "data/order_baseline.csv"


def load_baselines() -> pd.DataFrame:
    try:
        df = pd.read_csv(BASELINE_CSV, parse_dates=["baseline_date"])
    except FileNotFoundError:
        df = pd.DataFrame(columns=["material", "source", "baseline_date", "baseline_price"])
    return df


def get_baseline(material, source):
    df = load_baselines()
    row = df[(df["material"] == material) & (df["source"] == source)]
    if row.empty:
        return None
    return row.iloc[-1]


def save_baseline(material, source, baseline_date, baseline_price):
    df = load_baselines()
    df = df[~((df["material"] == material) & (df["source"] == source))]
    new_row = pd.DataFrame(
        [{"material": material, "source": source, "baseline_date": baseline_date, "baseline_price": baseline_price}]
    )
    df = pd.concat([df, new_row], ignore_index=True)
    os.makedirs(os.path.dirname(BASELINE_CSV), exist_ok=True)
    df.to_csv(BASELINE_CSV, index=False)


def run_scraper_now():
    with st.spinner("금투망 + RawMex 두 출처에서 최신 가격을 수집하는 중입니다... (1~2분 내외 소요)"):
        result = subprocess.run([sys.executable, "scraper.py"], capture_output=True, text=True)
    if result.returncode == 0:
        st.success("수집 완료!")
        st.code(result.stdout[-2500:] or "(출력 없음)")
        st.cache_data.clear()
    else:
        st.error("수집 중 오류가 발생했습니다.")
        st.code(result.stderr[-2500:])


def fmt_cny(v):
    return f"{v:,.0f}위안/톤"


def fmt_usd(v):
    return f"${v:,.0f}/톤"


def to_usd(cny_series, fx_series):
    return cny_series / fx_series


def render_highlight_table(df: pd.DataFrame, highlight_cols):
    """표 헤더에 옅은 인디고 배경을 주고, highlight_cols로 지정한 컬럼(메인 포인트)은
    헤더/셀 모두 진한 인디고로 강조해 렌더링합니다. (st.dataframe은 캔버스 렌더링이라
    헤더 색을 직접 못 입혀서 순수 HTML 표로 그립니다)"""
    header_cells = ""
    for col in df.columns:
        if col in highlight_cols:
            style = f"background:{ACCENT}; color:#FFFFFF; font-weight:700;"
        else:
            style = f"background:#EEF2FF; color:#3730A3; font-weight:600;"
        header_cells += (
            f'<th style="{style} padding:10px 12px; text-align:left; '
            f'white-space:nowrap; border-bottom:1px solid {LINE};">{col}</th>'
        )

    body_rows = ""
    for _, r in df.iterrows():
        cells = ""
        for col in df.columns:
            if col in highlight_cols:
                cell_style = f"background:#EEF2FF; color:{ACCENT}; font-weight:700;"
            else:
                cell_style = f"color:{INK};"
            cells += (
                f'<td style="{cell_style} padding:9px 12px; white-space:nowrap; '
                f'border-bottom:1px solid {LINE};">{r[col]}</td>'
            )
        body_rows += f"<tr>{cells}</tr>"

    html = f"""
    <div style="overflow-x:auto; border:1px solid {LINE}; border-radius:8px;">
    <table style="width:100%; border-collapse:collapse; font-size:0.88rem; font-family:'Inter',sans-serif;">
      <thead><tr>{header_cells}</tr></thead>
      <tbody>{body_rows}</tbody>
    </table>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 사이드바
# ---------------------------------------------------------------------------
with st.sidebar:
    SOURCE_INFO = {
        "rawmex": {
            "label": "RawMex (생의사 실매물)",
            "info": "데이터는 매일 자동으로 수집됩니다 (RawMex, rawmex.cn)",
            "main_caption": "기준: 생의사 RawMex(rawmex.cn) 橡塑 카테고리 · 품목별 실매물 평균가 · 元/吨(CNY/ton) 기준",
            "warn_caption": "⚠️ 공개 웹페이지에 등록된 판매 매물(호가)을 참고용으로 집계한 가격이며, 실제 체결가와 다를 수 있습니다.",
        },
        "cngold": {
            "label": "금투망 (cngold 참고가)",
            "info": "데이터는 매일 자동으로 수집됩니다 (금투망, cngold.org)",
            "main_caption": "기준: 금투망(cngold.org) 塑料 채널 · 원료별 하루 대표가 · 元/吨(CNY/ton) 기준",
            "warn_caption": "⚠️ 공개 웹페이지를 참고용으로 수집한 가격이며, 실제 거래가와 다를 수 있습니다. PA(나일론)는 이 채널에 없습니다.",
        },
    }

    def side_label(text):
        st.markdown(f"**{text}**")

    side_label("데이터 출처")
    source_choice = st.radio(
        "어느 출처의 데이터를 볼까요?",
        options=["cngold", "rawmex"],
        format_func=lambda k: SOURCE_INFO[k]["label"],
        index=0,
        label_visibility="collapsed",
    )
    src = SOURCE_INFO[source_choice]
    st.caption(src["info"])

    if st.button("🔄 지금 즉시 수집 (두 출처 모두)", width="stretch"):
        run_scraper_now()

    st.divider()
    side_label("기간 선택")
    quick = st.radio("빠른 선택", ["1개월", "3개월", "6개월", "전체"], index=1, horizontal=True, label_visibility="collapsed")
    c_start, c_end = st.columns(2)
    custom_start = c_start.date_input("시작일", value=None)
    custom_end = c_end.date_input("종료일", value=None)

    st.divider()
    side_label("⚖️ 무게로 가격 계산")
    c_w, c_u = st.columns([2, 1])
    weight_value = c_w.number_input("무게 입력", min_value=0.0, value=1000.0, step=1.0, label_visibility="collapsed")
    weight_unit = c_u.selectbox("단위", ["g", "kg", "톤(ton)"], index=1, label_visibility="collapsed")
    if weight_unit == "g":
        weight_ton = weight_value / 1_000_000
    elif weight_unit == "kg":
        weight_ton = weight_value / 1_000
    else:
        weight_ton = weight_value
    st.caption(f"{weight_value:,.0f}{weight_unit} = {weight_ton:,.6f}톤 기준")

    st.divider()
    side_label("통화 선택 (동시 선택 가능)")
    c_cny, c_usd = st.columns(2)
    show_cny = c_cny.checkbox("위안화 (CNY)", value=True)
    show_usd = c_usd.checkbox("달러 (USD)", value=False)
    if not show_cny and not show_usd:
        st.warning("최소 하나의 통화는 선택되어야 합니다. 위안화를 기본으로 표시합니다.")
        show_cny = True
    st.caption(f"환율 자동 수집 (없을 시 참고값 1 USD ≈ {DEFAULT_FX} CNY)")


# ---------------------------------------------------------------------------
# 데이터 준비
# ---------------------------------------------------------------------------
prices_df_all = load_prices()
fx_df = load_fx()

st.title("중국 플라스틱 원자재 가격 대시보드")
narrow_col, _ = st.columns([3, 2])
with narrow_col:
    st.caption(src["main_caption"])
    st.caption(src["warn_caption"])

prices_df = prices_df_all[prices_df_all["source"] == source_choice].reset_index(drop=True)

if prices_df.empty:
    other = "cngold" if source_choice == "rawmex" else "rawmex"
    extra = ""
    if not prices_df_all[prices_df_all["source"] == other].empty:
        extra = f" (참고: {SOURCE_INFO[other]['label']} 데이터는 있습니다 — 왼쪽에서 출처를 바꿔보세요)"
    st.warning(
        "이 출처로 수집된 데이터가 아직 없습니다. 왼쪽의 **'지금 즉시 수집'** 버튼을 눌러 "
        f"첫 데이터를 가져오거나, GitHub Actions가 실행될 때까지 기다려주세요.{extra}"
    )
    st.stop()

# 기간 계산
end_date_all = prices_df["date"].max()
if custom_start and custom_end:
    start_date = pd.Timestamp(custom_start)
    end_date = pd.Timestamp(custom_end)
else:
    end_date = end_date_all
    if quick == "1개월":
        start_date = end_date - timedelta(days=30)
    elif quick == "3개월":
        start_date = end_date - timedelta(days=90)
    elif quick == "6개월":
        start_date = end_date - timedelta(days=180)
    else:
        start_date = prices_df["date"].min()

# 환율 시리즈를 날짜별로 정리 (없는 날짜는 직전 값으로 채움)
if not fx_df.empty:
    fx_series = fx_df.set_index("date")["usd_cny"].sort_index()
else:
    fx_series = pd.Series(dtype=float)


def fx_for_date(d):
    if fx_series.empty:
        return DEFAULT_FX
    sub = fx_series[fx_series.index <= d]
    if sub.empty:
        return float(fx_series.iloc[0])
    return float(sub.iloc[-1])


# 사이드바에 "현재 적용 환율" 표시 (fx.csv 로드가 끝난 뒤라 여기서 계산)
with st.sidebar:
    st.divider()
    if not fx_series.empty:
        latest_fx_date = fx_series.index.max()
        latest_fx_rate = float(fx_series.iloc[-1])
        st.markdown(
            f"**현재 적용 환율**  \n1 USD = {latest_fx_rate:,.4f} CNY "
            f"<span style='color:{SUBTLE}; font-size:0.8rem;'>(기준일 {latest_fx_date.strftime('%m/%d')})</span>",
            unsafe_allow_html=True,
        )
    else:
        st.caption(f"현재 적용 환율: 아직 수집 전이라 참고값 1 USD ≈ {DEFAULT_FX} CNY 사용 중")


# ---------------------------------------------------------------------------
# 품목 탭
# ---------------------------------------------------------------------------
available_codes = [c for c in MATERIAL_LABELS if c in prices_df["material"].unique()]
missing_codes = [c for c in MATERIAL_LABELS if c not in available_codes]
if missing_codes:
    m_col, _ = st.columns([3, 2])
    m_col.caption("아직 데이터가 없는 품목: " + ", ".join(missing_codes) + " (며칠 뒤 자동 수집되면 나타납니다)")

# ---------------------------------------------------------------------------
# 위안/달러 환율 변동 별도 추적 — 원자재가 변동과 환율 변동을 구분해서 보기 위함
# ---------------------------------------------------------------------------
fx_period = fx_series[(fx_series.index >= start_date) & (fx_series.index <= end_date)]
if not fx_series.empty:
    with st.expander("📈 위안/달러 환율(USD/CNY) 추이 — 원자재가 변동과 환율 변동을 구분해서 보기", expanded=False):
        if len(fx_period) >= 2:
            fx_start_v = float(fx_period.iloc[0])
            fx_end_v = float(fx_period.iloc[-1])
            fx_change_pct = (fx_end_v - fx_start_v) / fx_start_v * 100

            fx1, fx2, fx3 = st.columns(3)
            with fx1:
                with st.container(border=True):
                    st.metric("기간 시작 환율", f"{fx_start_v:,.4f}", delta=fx_period.index[0].strftime("%m/%d"), delta_color="off")
            with fx2:
                with st.container(border=True):
                    st.metric("기간 종료(최신) 환율", f"{fx_end_v:,.4f}", delta=fx_period.index[-1].strftime("%m/%d"), delta_color="off")
            with fx3:
                with st.container(border=True):
                    st.metric(
                        "기간 중 환율 변동", f"{fx_change_pct:+.2f}%",
                        delta="위안 약세(달러 원가 하락 요인)" if fx_change_pct > 0 else "위안 강세(달러 원가 상승 요인)",
                        delta_color="off",
                    )

            fx_fig = go.Figure()
            fx_fig.add_trace(
                go.Scatter(
                    x=fx_period.index, y=fx_period.values, name="USD/CNY",
                    line=dict(color=ACCENT, width=2), fill="tozeroy", fillcolor="rgba(79,70,229,0.06)",
                )
            )
            fx_fig.update_layout(
                height=260,
                margin=dict(l=10, r=10, t=10, b=10),
                xaxis=dict(showgrid=False),
                yaxis=dict(title="1 USD = ? CNY", gridcolor=LINE, zeroline=False),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(family="Inter, -apple-system, sans-serif", color=INK),
                showlegend=False,
            )
            st.plotly_chart(fx_fig, width="stretch", key="fx_trend_chart")
        else:
            latest_fx_v = float(fx_series.iloc[-1])
            latest_fx_d = fx_series.index[-1]
            st.metric("현재 환율", f"{latest_fx_v:,.4f}", delta=latest_fx_d.strftime("%m/%d"), delta_color="off")
            st.caption(
                "아직 환율 데이터가 하루치(또는 선택한 기간 안에 1일치)뿐이라 추이 그래프는 며칠 더 "
                "쌓인 뒤 보여드릴 수 있어요. `python scraper.py`를 며칠 반복 실행해보세요."
            )

        st.caption(
            "💡 위안화가 약세(숫자가 커짐)면 같은 위안화 원자재가라도 달러 환산 원가는 내려가고, "
            "위안화가 강세(숫자가 작아짐)면 달러 환산 원가는 올라갑니다. 품목 탭의 '달러(USD)' 가격이 "
            "위안화 원자재가와 다르게 움직인다면 이 환율 변동 때문일 수 있습니다."
        )

# ---------------------------------------------------------------------------
# 무게 입력 기준 전체 품목 가격 계산 (왼쪽 사이드바에서 입력한 무게 사용)
# ---------------------------------------------------------------------------
st.subheader(f"⚖️ {weight_value:,.0f}{weight_unit} 구매 시 예상 가격 (품목별, 최신가 기준)")

weight_rows = []
weight_col_cny = f"{weight_value:,.0f}{weight_unit} 가격(위안)"
weight_col_usd = f"{weight_value:,.0f}{weight_unit} 가격(USD)"
for code in available_codes:
    mdf_w = prices_df[prices_df["material"] == code].sort_values("date")
    latest_w = mdf_w.iloc[-1]
    fx_w = fx_for_date(latest_w["date"])
    unit_cny = latest_w["avg_price"]
    unit_usd = unit_cny / fx_w
    row = {
        "품목": MATERIAL_LABELS[code],
        "기준일": latest_w["date"].strftime("%m/%d"),
    }
    if show_cny:
        row["단가(위안/톤)"] = f"{unit_cny:,.0f}"
        row[weight_col_cny] = f"{unit_cny * weight_ton:,.2f}"
    if show_usd:
        row["단가(USD/톤)"] = f"{unit_usd:,.0f}"
        row[weight_col_usd] = f"{unit_usd * weight_ton:,.2f}"
    weight_rows.append(row)

render_highlight_table(pd.DataFrame(weight_rows), highlight_cols={weight_col_cny, weight_col_usd})
st.divider()

tabs = st.tabs([MATERIAL_LABELS[c] for c in available_codes])

for tab, code in zip(tabs, available_codes):
    with tab:
        mdf = prices_df[prices_df["material"] == code].sort_values("date").reset_index(drop=True)
        mdf = mdf.drop_duplicates(subset="date", keep="last")
        mdf["fx"] = mdf["date"].apply(fx_for_date)
        mdf["usd_price"] = mdf["avg_price"] / mdf["fx"]

        latest = mdf.iloc[-1]
        prev = mdf.iloc[-2] if len(mdf) > 1 else None

        # ---- 요약 카드 -----------------------------------------------------
        c1, c2, c3, c4, c5 = st.columns(5)

        with c1:
            with st.container(border=True):
                st.metric(
                    f"전일 가격 ({latest['date'].strftime('%m/%d')})",
                    fmt_cny(latest["avg_price"]) if show_cny else fmt_usd(latest["usd_price"]),
                    delta=(
                        f"{latest['avg_price'] - prev['avg_price']:+,.0f}위안"
                        if prev is not None and show_cny
                        else (f"{latest['usd_price'] - prev['usd_price']:+,.0f}달러" if prev is not None else None)
                    ),
                    delta_color="inverse",
                )
                if show_cny and show_usd:
                    st.caption(fmt_usd(latest["usd_price"]))

        with c2:
            with st.container(border=True):
                recent3 = mdf.tail(3)
                avg3 = recent3["avg_price"].mean()
                avg3_usd = recent3["usd_price"].mean()
                st.metric("직전 3거래일 평균", fmt_cny(avg3) if show_cny else fmt_usd(avg3_usd))
                if show_cny and show_usd:
                    st.caption(fmt_usd(avg3_usd))

        with c3:
            with st.container(border=True):
                recent5 = mdf.tail(5)
                avg5 = recent5["avg_price"].mean()
                avg5_usd = recent5["usd_price"].mean()
                st.metric("주간평균 (최근 5거래일)", fmt_cny(avg5) if show_cny else fmt_usd(avg5_usd))
                if show_cny and show_usd:
                    st.caption(fmt_usd(avg5_usd))

        with c4:
            with st.container(border=True):
                yoy_target = latest["date"] - pd.Timedelta(days=364)
                hist = mdf[mdf["date"] <= yoy_target]
                if not hist.empty:
                    yoy_price = hist.iloc[-1]["avg_price"]
                    yoy_pct = (latest["avg_price"] - yoy_price) / yoy_price * 100
                    st.metric("전년 동기대비", f"{yoy_pct:+.1f}%", delta=f"전년 {yoy_price:,.0f}위안", delta_color="off")
                else:
                    st.metric("전년 동기대비", "데이터 부족")
                    st.caption("아직 1년치 데이터가 쌓이지 않았습니다")

        with c5:
            with st.container(border=True):
                baseline = get_baseline(code, source_choice)
                if baseline is not None:
                    base_price = float(baseline["baseline_price"])
                    base_date = baseline["baseline_date"]
                    base_date_str = base_date.strftime("%m/%d") if hasattr(base_date, "strftime") else str(base_date)
                    change_pct = (latest["avg_price"] - base_price) / base_price * 100
                    st.metric(
                        "발주 기준가 대비",
                        f"{change_pct:+.1f}%",
                        delta=f"기준 {base_date_str} · {base_price:,.0f}위안",
                        delta_color="inverse",
                    )
                    if st.button("📌 기준점 갱신", key=f"reset_baseline_{source_choice}_{code}", width="stretch"):
                        save_baseline(code, source_choice, latest["date"].date().isoformat(), latest["avg_price"])
                        st.rerun()
                else:
                    st.caption("발주 기준가 없음")
                    if st.button("📌 지금가로 저장", key=f"set_baseline_{source_choice}_{code}", width="stretch"):
                        save_baseline(code, source_choice, latest["date"].date().isoformat(), latest["avg_price"])
                        st.rerun()

        st.divider()

        # ---- 최근 2주 표 ----------------------------------------------------
        st.subheader("최근 2주 가격")
        recent14 = mdf.tail(14).copy()
        recent14["표시일"] = recent14["date"].dt.strftime("%m/%d (%a)")
        show_cols = ["표시일"]
        table_df = pd.DataFrame({"표시일": recent14["표시일"]})
        if show_cny:
            table_df["위안화(CNY/톤)"] = recent14["avg_price"].map(lambda v: f"{v:,.0f}")
        if show_usd:
            table_df["달러(USD/톤)"] = recent14["usd_price"].map(lambda v: f"{v:,.0f}")
        table_df["스펙 수"] = recent14["spec_count"].values
        st.dataframe(table_df, hide_index=True, width="stretch", key=f"table_{source_choice}_{code}")

        # ---- 차트 -----------------------------------------------------------
        st.subheader(f"{MATERIAL_LABELS[code]} 가격 추이")
        col_a, col_b = st.columns(2)
        show_ma = col_a.checkbox("3일 이동평균", value=True, key=f"ma_{code}")
        show_yoy = col_b.checkbox("전년 동기 비교", value=False, key=f"yoy_{code}")

        chart_df = mdf[(mdf["date"] >= start_date) & (mdf["date"] <= end_date)].copy()
        chart_df["ma3"] = mdf["avg_price"].rolling(3, min_periods=1).mean().loc[chart_df.index]

        fig = go.Figure()
        if show_cny:
            fig.add_trace(
                go.Scatter(
                    x=chart_df["date"], y=chart_df["avg_price"], name="가격(위안/톤)",
                    line=dict(color=ACCENT, width=2), yaxis="y1",
                )
            )
            if show_ma:
                fig.add_trace(
                    go.Scatter(
                        x=chart_df["date"], y=chart_df["ma3"], name="3거래일 평균(위안)",
                        line=dict(color=SUBTLE, width=1.5, dash="dash"), yaxis="y1",
                    )
                )
        if show_usd:
            fig.add_trace(
                go.Scatter(
                    x=chart_df["date"], y=chart_df["usd_price"], name="가격(USD/톤)",
                    line=dict(color=ACCENT_LIGHT, width=2), yaxis="y2",
                )
            )
        if show_yoy:
            yoy_dates = chart_df["date"] - pd.Timedelta(days=364)
            yoy_vals = []
            for d in yoy_dates:
                hist = mdf[mdf["date"] <= d]
                yoy_vals.append(hist.iloc[-1]["avg_price"] if not hist.empty else None)
            fig.add_trace(
                go.Scatter(
                    x=chart_df["date"], y=yoy_vals, name="전년 동기(위안)",
                    line=dict(color=LINE, width=1.3, dash="dot"), yaxis="y1",
                )
            )

        layout_kwargs = dict(
            height=420,
            margin=dict(l=10, r=10, t=30, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            xaxis=dict(title=None, showgrid=False),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter, -apple-system, sans-serif", color=INK),
        )
        if show_cny:
            layout_kwargs["yaxis"] = dict(title="위안/톤", gridcolor=LINE, zeroline=False)
        if show_usd:
            layout_kwargs["yaxis2"] = dict(title="USD/톤", overlaying="y", side="right", gridcolor=LINE, zeroline=False)
        fig.update_layout(**layout_kwargs)

        st.plotly_chart(fig, width="stretch", key=f"chart_{source_choice}_{code}")

        with st.expander("원본 매물 링크 보기"):
            st.dataframe(
                mdf[["date", "avg_price", "min_price", "max_price", "spec_count", "source_url"]].tail(20),
                hide_index=True,
                width="stretch",
                key=f"detail_{source_choice}_{code}",
            )


# ---------------------------------------------------------------------------
# 레시피 원가 계산기 — 제품별 원자재 배합비를 등록하면 오늘 시세로 원가/마진을 계산
# (입력값은 파일로 저장되지 않고, 현재 브라우저 세션에서만 유지됩니다)
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 레시피 원가 계산기 — 부위별 원자재 배합비를 등록하면 오늘 시세로 원가/마진을 계산
# 전부 달러(USD) 기준. (입력값은 파일로 저장되지 않고, 현재 브라우저 세션에서만 유지됩니다)
# ---------------------------------------------------------------------------
st.divider()
st.header("🧪 레시피 원가 계산기")
st.caption(
    f"부위별로 어떤 원료가 몇 g 들어가는지 등록하면, 지금 선택된 출처({src['label']})의 최신 시세로 "
    "제품 1개당 원자재 원가와 마진율을 달러(USD) 기준으로 계산합니다. "
    "(입력한 표는 새로고침하면 초기화됩니다)"
)

empty_recipe_df = pd.DataFrame(columns=["part", "material", "weight_g", "selling_price_usd"])

edited_recipe = st.data_editor(
    empty_recipe_df,
    num_rows="dynamic",
    width="stretch",
    key="recipe_editor",
    column_config={
        "part": st.column_config.TextColumn("부위/설명 (선택)"),
        "material": st.column_config.SelectboxColumn("원료", options=list(MATERIAL_LABELS.keys()), required=True),
        "weight_g": st.column_config.NumberColumn("무게(g)", min_value=0.0, step=1.0, required=True),
        "selling_price_usd": st.column_config.NumberColumn(
            "제품 판매가($, 선택)", min_value=0.0, step=0.001, format="%.3f"
        ),
    },
)

valid_recipe_rows = edited_recipe.dropna(subset=["material", "weight_g"])

if valid_recipe_rows.empty:
    st.caption("아직 등록된 부위가 없습니다. 위 표에 원료·무게(g)를 입력해보세요.")
else:
    # 원료별 최신 단가(USD/g) — 현재 선택된 출처(prices_df) 기준
    latest_price_per_g_usd = {}
    missing_materials = []
    for code in valid_recipe_rows["material"].unique():
        mdf_code = prices_df[prices_df["material"] == code].sort_values("date")
        if mdf_code.empty:
            missing_materials.append(code)
            continue
        last = mdf_code.iloc[-1]
        fx_rate = fx_for_date(last["date"])
        price_per_ton_usd = last["avg_price"] / fx_rate
        latest_price_per_g_usd[code] = price_per_ton_usd / 1_000_000  # USD/톤 -> USD/g

    total_weight = 0.0
    total_usd = 0.0
    for _, r in valid_recipe_rows.iterrows():
        ppg = latest_price_per_g_usd.get(r["material"])
        total_weight += float(r["weight_g"])
        if ppg is not None:
            total_usd += ppg * float(r["weight_g"])

    selling_series = valid_recipe_rows["selling_price_usd"].dropna()
    selling_price = float(selling_series.iloc[0]) if len(selling_series) else None

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        with st.container(border=True):
            st.metric("총 무게(g)", f"{total_weight:,.1f}")
    with m2:
        with st.container(border=True):
            st.metric("원자재 원가($)", f"${total_usd:,.4f}")
    if selling_price:
        cost_pct = total_usd / selling_price * 100
        margin_pct = (selling_price - total_usd) / selling_price * 100
        with m3:
            with st.container(border=True):
                st.metric("판매가($)", f"${selling_price:,.3f}")
        with m4:
            with st.container(border=True):
                st.metric("원가율(%)", f"{cost_pct:,.1f}%", delta=f"마진율 {margin_pct:.1f}%", delta_color="off")

    if missing_materials:
        st.caption(
            "⚠️ 시세 없음: " + ", ".join(sorted(set(missing_materials))) +
            " — 왼쪽에서 다른 데이터 출처를 선택해보세요 (예: PA6/PA66은 RawMex에만 있습니다)."
        )
    st.caption("💡 판매가($)를 입력하면, 원자재 원가가 판매가의 몇 %를 차지하는지(원가율) 계산됩니다.")
