import json
import os
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

# --------------------------------------------------
# 1. ページ基本設定
# --------------------------------------------------
st.set_page_config(
    page_title="SMBMARK｜消費・物価トレンド分析ダッシュボード",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --------------------------------------------------
# 1-2. デザインシステム定数（v03のダークテーマを移植）
# --------------------------------------------------
BG_MAIN = "#05070B"        # ページ背景（漆黒に近いネイビー）
BG_CARD = "#1B2029"        # カード・サイドバー背景
BORDER_COLOR = "#2E3746"   # カード・区切り線
TEXT_PRIMARY = "#F2F4F8"   # 主要テキスト
TEXT_MUTED = "#8B93A1"     # 補助テキスト

ACCENT = "#22E6A0"                      # アクセントのミントグリーン
ACCENT_HOVER = "#17C989"
ACCENT_SOFT = "rgba(34,230,160,0.16)"

PRICE_COLOR = "#60A5FA"    # 物価指数（CPI）：ブルー
SPEND_COLOR = "#FBBF24"    # 家計支出額：アンバー
GOOD_COLOR = ACCENT        # 値上げ受容型：グリーン
RISK_COLOR = "#F87171"     # 買い控え警戒型：レッド
WARN_COLOR = "#FBBF24"     # 様子見・選別型：アンバー
NET_LINE_COLOR = TEXT_PRIMARY
GRID_COLOR = BORDER_COLOR
CHIP_BG = "#12161E"

# --- 立体感・光沢演出用 ---
CARD_GRAD = "linear-gradient(155deg, #2A3242 0%, #1B2029 45%, #10141B 100%)"
CARD_GRAD_HOVER = "linear-gradient(155deg, #333D50 0%, #212836 45%, #12161D 100%)"
CHIP_GRAD = "linear-gradient(180deg, #232B38 0%, #0C0F15 100%)"
GLASS_BORDER = "rgba(255,255,255,0.16)"
SHADOW_CARD = "0 20px 44px -14px rgba(0,0,0,0.85), 0 0 0 1px rgba(255,255,255,0.06) inset, 0 0 28px rgba(34,230,160,0.10)"
SHADOW_CARD_HOVER = "0 26px 54px -14px rgba(0,0,0,0.9), 0 0 0 1px rgba(34,230,160,0.45), 0 0 42px rgba(34,230,160,0.28)"
GLOW_ACCENT = "0 6px 24px rgba(34,230,160,0.55), 0 0 0 1px rgba(255,255,255,0.25) inset"
TOP_STRIPE = "linear-gradient(90deg, {0} 0%, rgba(255,255,255,0.35) 55%, transparent 100%)".format(ACCENT)

CHART_FONT = dict(family="Helvetica, Arial, sans-serif", color=TEXT_PRIMARY)
PLOTLY_CONFIG = {"displayModeBar": False}


# --- グラデーション生成ヘルパー ---
def _lerp_hex(c1: str, c2: str, t: float) -> str:
    c1, c2 = c1.lstrip('#'), c2.lstrip('#')
    r1, g1, b1 = int(c1[0:2], 16), int(c1[2:4], 16), int(c1[4:6], 16)
    r2, g2, b2 = int(c2[0:2], 16), int(c2[2:4], 16), int(c2[4:6], 16)
    r = round(r1 + (r2 - r1) * t)
    g = round(g1 + (g2 - g1) * t)
    b = round(b1 + (b2 - b1) * t)
    return f'#{r:02X}{g:02X}{b:02X}'


def gradient_colors(c_from: str, c_to: str, n: int) -> list:
    """n本の帯に、c_fromからc_toへ滑らかに変化する色を割り当てる"""
    if n <= 1:
        return [c_to]
    return [_lerp_hex(c_from, c_to, i / (n - 1)) for i in range(n)]


GOOD_GRAD = ("#0E7A4D", "#7CF7C9")    # 値上げ受容：深いグリーン → 明るいミント
RISK_GRAD = ("#8C2323", "#FF9A9A")    # 買い控え警戒：深いレッド → 明るいコーラル


def add_gradient_bar_h(fig, y_labels, values, grad, name, n_bands=24, hover_prefix=""):
    """横棒グラフに、軸側→先端へのグラデーションを帯の積み重ねで再現する（カテゴリ数が少ない棒グラフ向け）"""
    bands = gradient_colors(*grad, n_bands)
    for i in range(n_bands):
        fig.add_trace(go.Bar(
            y=y_labels,
            x=values / n_bands,
            orientation='h',
            name=name, legendgroup=name,
            showlegend=(i == 0),
            marker=dict(color=bands[i], line=dict(width=0)),
            customdata=values,
            hovertemplate=f'%{{y}}<br>{hover_prefix}: %{{customdata:+.1f}}%<extra></extra>'
        ))


def style_fig(fig, **layout_overrides):
    """v03のダークテーマに合わせたPlotlyの共通レイアウトを適用する"""
    base = dict(
        font=CHART_FONT,
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
            bgcolor="rgba(255,255,255,0.03)", bordercolor="rgba(255,255,255,0.08)", borderwidth=1
        ),
        margin=dict(t=40, l=10, r=10, b=10),
    )
    base.update(layout_overrides)
    fig.update_layout(**base)
    return fig


# --------------------------------------------------
# 1-3. グローバルCSS（v03デザインシステム移植）
# --------------------------------------------------
st.markdown(f"""
<style>
    .stApp {{
        background:
            radial-gradient(1100px 520px at 8% -8%, rgba(34,230,160,0.20), transparent 60%),
            radial-gradient(900px 480px at 96% 4%, rgba(96,165,250,0.16), transparent 55%),
            radial-gradient(1300px 900px at 50% 115%, rgba(34,230,160,0.10), transparent 60%),
            {BG_MAIN};
    }}
    [data-testid="stSidebar"] {{
        background:
            radial-gradient(500px 260px at 10% 0%, rgba(34,230,160,0.14), transparent 55%),
            linear-gradient(180deg, #1A2029 0%, #0A0D12 100%);
        border-right: 1px solid {GLASS_BORDER};
        box-shadow: 10px 0 32px rgba(0,0,0,0.55);
    }}
    [data-testid="stSidebar"] > div:first-child {{
        background: transparent;
    }}
    .block-container {{
        padding-top: 1.5rem;
        padding-bottom: 3rem;
    }}
    h1, h2, h3, h4, h5, p, span, label, div {{
        color: {TEXT_PRIMARY};
    }}
    h1, h2, h3 {{
        font-weight: 700;
        letter-spacing: -0.01em;
    }}
    h1 {{
        background: linear-gradient(90deg, #FFFFFF 0%, {ACCENT} 120%);
        -webkit-background-clip: text;
        background-clip: text;
        -webkit-text-fill-color: transparent;
        text-shadow: 0 0 40px rgba(34,230,160,0.25);
    }}
    /* KPIカード */
    .kpi-card {{
        position: relative;
        overflow: hidden;
        background: {CARD_GRAD};
        border: 1px solid {GLASS_BORDER};
        border-radius: 16px;
        padding: 22px 22px 20px 22px;
        height: 100%;
        box-shadow: {SHADOW_CARD};
        transition: transform 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
    }}
    .kpi-card::before {{
        content: "";
        position: absolute;
        top: 0; left: 0; right: 0;
        height: 3px;
        background: {TOP_STRIPE};
        opacity: 0.9;
    }}
    .kpi-card::after {{
        content: "";
        position: absolute;
        top: -40%; left: -10%;
        width: 70%; height: 90%;
        background: radial-gradient(circle, rgba(255,255,255,0.08), transparent 70%);
        pointer-events: none;
    }}
    .kpi-card:hover {{
        background: {CARD_GRAD_HOVER};
        box-shadow: {SHADOW_CARD_HOVER};
        transform: translateY(-4px);
    }}
    .kpi-label {{
        font-size: 0.80rem;
        color: {TEXT_MUTED};
        font-weight: 600;
        margin-bottom: 6px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }}
    .kpi-value {{
        font-size: 1.75rem;
        font-weight: 700;
        color: {TEXT_PRIMARY};
        line-height: 1.2;
        text-shadow: 0 2px 12px rgba(0,0,0,0.35);
    }}
    .kpi-sub {{
        font-size: 0.78rem;
        color: {TEXT_MUTED};
        margin-top: 4px;
    }}
    .badge-green {{
        display: inline-block;
        background: linear-gradient(135deg, rgba(34,230,160,0.40), rgba(34,230,160,0.10));
        color: #B8FFE4;
        font-weight: 700;
        padding: 4px 14px;
        border-radius: 999px;
        font-size: 0.9rem;
        box-shadow: 0 0 0 1px rgba(34,230,160,0.55), 0 4px 18px rgba(34,230,160,0.35);
    }}
    .badge-red {{
        display: inline-block;
        background: linear-gradient(135deg, rgba(248,113,113,0.40), rgba(248,113,113,0.10));
        color: #FFD7D7;
        font-weight: 700;
        padding: 4px 14px;
        border-radius: 999px;
        font-size: 0.9rem;
        box-shadow: 0 0 0 1px rgba(248,113,113,0.55), 0 4px 18px rgba(248,113,113,0.30);
    }}
    .badge-amber {{
        display: inline-block;
        background: linear-gradient(135deg, rgba(251,191,36,0.40), rgba(251,191,36,0.10));
        color: #FFEDBE;
        font-weight: 700;
        padding: 4px 14px;
        border-radius: 999px;
        font-size: 0.9rem;
        box-shadow: 0 0 0 1px rgba(251,191,36,0.55), 0 4px 18px rgba(251,191,36,0.30);
    }}
    .section-caption {{
        color: {TEXT_MUTED};
        font-size: 0.85rem;
        margin-top: -6px;
        margin-bottom: 10px;
    }}
    .scroll-top-btn {{
        position: fixed;
        bottom: 25px;
        right: 30px;
        z-index: 9999;
        background: linear-gradient(155deg, #3CF4B8 0%, {ACCENT} 55%, {ACCENT_HOVER} 100%);
        color: {BG_MAIN} !important;
        border: none;
        border-radius: 50%;
        width: 48px;
        height: 48px;
        font-size: 20px;
        font-weight: bold;
        cursor: pointer;
        box-shadow: {GLOW_ACCENT};
        transition: all 0.2s ease;
        display: flex;
        align-items: center;
        justify-content: center;
        text-decoration: none !important;
    }}
    .scroll-top-btn:hover {{
        box-shadow: 0 6px 26px rgba(34,230,160,0.65), 0 0 0 1px rgba(34,230,160,0.4) inset;
        transform: translateY(-3px) scale(1.04);
    }}
    #top-anchor {{ position: absolute; top: 0; left: 0; }}

    /* タブ */
    .stTabs [data-baseweb="tab-list"] {{
        gap: 4px;
        background: linear-gradient(180deg, #151B24 0%, #10141B 100%);
        border: 1px solid {GLASS_BORDER};
        padding: 6px;
        border-radius: 14px;
        margin-bottom: 4px;
        box-shadow: inset 0 1px 3px rgba(0,0,0,0.4);
    }}
    .stTabs [data-baseweb="tab"] {{
        height: 46px;
        border-radius: 10px;
        padding: 0 22px;
        background-color: transparent;
        font-weight: 600;
        font-size: 0.95rem;
        color: {TEXT_MUTED};
        border: none;
        transition: all 0.15s ease;
    }}
    .stTabs [data-baseweb="tab"] p {{
        color: inherit;
    }}
    .stTabs [data-baseweb="tab"]:hover {{
        color: {TEXT_PRIMARY};
        background-color: rgba(255,255,255,0.04);
    }}
    .stTabs [aria-selected="true"] {{
        background: linear-gradient(155deg, rgba(34,230,160,0.35), rgba(34,230,160,0.10)) !important;
        color: #B8FFE4 !important;
        box-shadow: inset 0 0 0 1px rgba(34,230,160,0.60), 0 6px 20px rgba(34,230,160,0.35);
    }}
    .stTabs [data-baseweb="tab-highlight"] {{
        background-color: transparent;
    }}
    .stTabs [data-baseweb="tab-border"] {{
        display: none;
    }}

    /* KPIの前年比デルタ */
    .kpi-delta {{
        display: inline-flex;
        align-items: center;
        gap: 4px;
        font-size: 0.80rem;
        font-weight: 700;
        margin-top: 8px;
        padding: 3px 10px;
        border-radius: 999px;
    }}
    .delta-up {{ color: #B8FFE4; background: linear-gradient(135deg, rgba(34,230,160,0.35), rgba(34,230,160,0.08)); box-shadow: 0 0 0 1px rgba(34,230,160,0.40); }}
    .delta-down {{ color: #FFD7D7; background: linear-gradient(135deg, rgba(248,113,113,0.35), rgba(248,113,113,0.08)); box-shadow: 0 0 0 1px rgba(248,113,113,0.40); }}
    .delta-flat {{ color: {TEXT_MUTED}; background: rgba(139,147,161,0.16); box-shadow: 0 0 0 1px rgba(139,147,161,0.25); }}

    /* フィルターチップ */
    .filter-chip-label {{
        font-size: 0.78rem;
        font-weight: 700;
        color: {TEXT_MUTED};
        text-transform: uppercase;
        letter-spacing: 0.04em;
        margin-bottom: 6px;
    }}
    .stButton > button {{
        border-radius: 999px;
        border: 1px solid {GLASS_BORDER};
        background: {CHIP_GRAD};
        color: {TEXT_PRIMARY};
        font-size: 0.82rem;
        font-weight: 600;
        padding: 4px 10px;
        box-shadow: 0 6px 16px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,255,255,0.08);
        transition: all 0.15s ease;
    }}
    .stButton > button:hover {{
        border-color: rgba(34,230,160,0.65);
        color: #B8FFE4;
        background: linear-gradient(180deg, rgba(34,230,160,0.24) 0%, #0D1017 100%);
        box-shadow: 0 6px 20px rgba(34,230,160,0.35), inset 0 1px 0 rgba(255,255,255,0.08);
        transform: translateY(-1px);
    }}
    .stButton > button p {{
        color: inherit;
    }}

    /* サイドバーのセレクト・ラジオ類 */
    [data-testid="stSidebar"] [data-baseweb="select"] > div {{
        background: {CHIP_GRAD};
        border-color: {GLASS_BORDER};
        box-shadow: inset 0 1px 4px rgba(0,0,0,0.5);
    }}
    [data-baseweb="select"] input {{
        color: {TEXT_PRIMARY} !important;
        -webkit-text-fill-color: {TEXT_PRIMARY} !important;
        caret-color: {TEXT_PRIMARY} !important;
    }}
    [data-baseweb="select"] div[class*="placeholder"],
    [data-baseweb="select"] > div > div:first-child {{
        color: {TEXT_MUTED} !important;
    }}
    [data-baseweb="select"] svg {{
        fill: {TEXT_MUTED} !important;
    }}
    div[data-baseweb="popover"] [data-baseweb="menu"],
    div[data-baseweb="popover"] ul {{
        background: {BG_CARD} !important;
        border: 1px solid {GLASS_BORDER} !important;
        box-shadow: {SHADOW_CARD};
    }}
    li[role="option"] {{
        color: {TEXT_PRIMARY} !important;
        background: transparent !important;
    }}
    li[role="option"] * {{
        color: inherit !important;
    }}
    li[role="option"]:hover {{
        background: {ACCENT_SOFT} !important;
        color: #B8FFE4 !important;
    }}
    li[aria-selected="true"] {{
        background: rgba(34,230,160,0.14) !important;
        color: #B8FFE4 !important;
    }}

    /* st.info / success / warning / error をガラスカード風に統一 */
    [data-testid="stAlert"] {{
        background: {CHIP_GRAD} !important;
        border: 1px solid {GLASS_BORDER};
        border-radius: 12px;
        box-shadow: {SHADOW_CARD};
    }}
    [data-testid="stAlert"] p, [data-testid="stAlert"] span {{
        color: {TEXT_PRIMARY} !important;
    }}

    /* Plotlyチャートをガラスカードで包む */
    [data-testid="stPlotlyChart"] {{
        background: {CARD_GRAD};
        border: 1px solid {GLASS_BORDER};
        border-radius: 18px;
        padding: 14px 10px 4px 10px;
        box-shadow: {SHADOW_CARD};
    }}

    /* ポップオーバー本体 */
    div[data-baseweb="popover"] > div {{
        background: {BG_CARD} !important;
        border: 1px solid {GLASS_BORDER} !important;
        border-radius: 14px !important;
        box-shadow: {SHADOW_CARD} !important;
    }}

    /* 区切り線 */
    hr {{
        border: none;
        height: 1px;
        background: linear-gradient(90deg, transparent, {GLASS_BORDER} 20%, {GLASS_BORDER} 80%, transparent);
        margin: 1.2rem 0;
    }}
</style>
<div id="top-anchor"></div>
<a href="#top-anchor" class="scroll-top-btn" title="最上部へ戻る">↑</a>
""", unsafe_allow_html=True)


DELTA_ARROW = {"up": "▲", "down": "▼", "flat": "ー"}
DELTA_CLASS = {"up": "delta-up", "down": "delta-down", "flat": "delta-flat"}


def calc_delta(curr, prev):
    """前年同月比の方向とラベルを計算。比較対象がなければNoneを返す。"""
    if curr is None or prev is None or prev == 0:
        return None
    pct = (curr - prev) / abs(prev) * 100
    direction = "up" if pct > 0.05 else ("down" if pct < -0.05 else "flat")
    return direction, f"前年比 {pct:+.1f}%"


def kpi_card(label, value, sub="", delta=None):
    delta_html = ""
    if delta is not None:
        direction, delta_text = delta
        delta_html = (
            f'<div class="kpi-delta {DELTA_CLASS[direction]}">'
            f'{DELTA_ARROW[direction]} {delta_text}</div>'
        )
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{value}</div>
        <div class="kpi-sub">{sub}</div>
        {delta_html}
    </div>
    """, unsafe_allow_html=True)


# --------------------------------------------------
# 2. 定数・マスター定義（Secretsから安全に取得）
# --------------------------------------------------
if "ESTAT_APP_ID" in st.secrets:
    APP_ID = st.secrets["ESTAT_APP_ID"]
else:
    APP_ID = os.environ.get("ESTAT_APP_ID", "")

if not APP_ID or APP_ID == "YOUR_APP_ID":
    st.error(
        "⚠️ **e-StatのAPIキーが読み込めていません。**\n\n"
        "`.streamlit/secrets.toml` に `ESTAT_APP_ID = \"あなたのキー\"` が正しく記載されているか確認してください。"
    )
    st.stop()

CPI_STATS_ID = "0003427113"  # 2020年基準 消費者物価指数（月次）
KAKEI_STATS_ID = "0003343671"  # 家計調査 二人以上の世帯（月次）
DATA_URL = "https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData"

AREA_MASTER = {
    "全国": "00000",
    "東京都区部": "13100",
    "大阪市": "27100",
    "名古屋市": "23100",
    "福岡市": "40130",
    "札幌市": "01100",
    "仙台市": "04100",
    "広島市": "34100",
}


@st.cache_data
def load_hierarchy_tree():
    json_path = "item_hierarchy_tree.json"
    if not os.path.exists(json_path):
        st.error(
            f"マスターファイル `{json_path}` が見つかりません。先に `create_master.py` を実行してください。"
        )
        st.stop()
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


hierarchy_tree = load_hierarchy_tree()

# --------------------------------------------------
# 3. サイドバー（検索条件・安全な階層連動）
# --------------------------------------------------
st.sidebar.markdown("### 🔍 検索・絞り込み条件")

if st.sidebar.button("🔄 検索条件をリセット", use_container_width=True):
    for key in [
        "sel_major",
        "sel_middle",
        "sel_item_key",
        "sel_area",
        "sel_period_years",
    ]:
        if key in st.session_state:
            del st.session_state[key]
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("**📦 個別分析用 品目選択**")

major_options = sorted(list(hierarchy_tree.keys()))
default_major = (
    "食料"
    if "食料" in major_options
    else ("穀類" if "穀類" in major_options else major_options[0])
)
current_major = st.session_state.get("sel_major", default_major)
if current_major not in major_options:
    current_major = default_major

selected_major = st.sidebar.selectbox(
    "1. 大分類（10大費目）",
    options=major_options,
    index=major_options.index(current_major),
    key="sel_major",
)

middle_dict = hierarchy_tree.get(selected_major, {})
middle_options = sorted(list(middle_dict.keys()))
if not middle_options:
    st.sidebar.warning("選択可能な中分類がありません。")
    st.stop()

current_middle = st.session_state.get("sel_middle", middle_options[0])
if current_middle not in middle_options:
    current_middle = middle_options[0]

selected_middle = st.sidebar.selectbox(
    "2. 中分類",
    options=middle_options,
    index=middle_options.index(current_middle),
    key="sel_middle",
)

items_list = middle_dict.get(selected_middle, [])
if not items_list:
    st.sidebar.warning("選択可能な品目がありません。")
    st.stop()

item_options_map = {}
for it in items_list:
    display_label = f"{it['item_name']} (コード: {it['cpi_code']})"
    item_options_map[display_label] = it

item_display_list = list(item_options_map.keys())
current_item_key = st.session_state.get("sel_item_key", item_display_list[0])
if current_item_key not in item_display_list:
    current_item_key = item_display_list[0]

selected_item_label = st.sidebar.selectbox(
    "3. 詳細品目名",
    options=item_display_list,
    index=item_display_list.index(current_item_key),
    key="sel_item_key",
)

target_item_info = item_options_map[selected_item_label]
target_item_name = target_item_info["item_name"]

st.sidebar.markdown("---")
st.sidebar.markdown("**🌍 地域・期間の選択**")

selected_area_name = st.sidebar.selectbox(
    "比較対象地域（自社商圏）",
    options=list(AREA_MASTER.keys()),
    index=1,
    key="sel_area",
)

period_years = st.sidebar.radio(
    "分析期間",
    ["直近3年間", "直近5年間", "全期間"],
    index=0,
    key="sel_period_years",
    horizontal=True,
)

# --------------------------------------------------
# 3-2. アクティブフィルターの解除コールバック
# --------------------------------------------------
def _reset_major():
    for k in ["sel_major", "sel_middle", "sel_item_key"]:
        st.session_state.pop(k, None)


def _reset_middle():
    for k in ["sel_middle", "sel_item_key"]:
        st.session_state.pop(k, None)


def _reset_item():
    st.session_state.pop("sel_item_key", None)


def _reset_area():
    st.session_state.pop("sel_area", None)


def _reset_period():
    st.session_state.pop("sel_period_years", None)


def _clear_all_filters():
    for k in ["sel_major", "sel_middle", "sel_item_key", "sel_area", "sel_period_years"]:
        st.session_state.pop(k, None)


# --------------------------------------------------
# 4. APIデータ取得関数（堅牢化版）
# --------------------------------------------------
EMPTY_DF = pd.DataFrame(columns=["ym", "year", "month", "val"])


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_stat_data(stats_data_id, cat_code, area_code, tab_code=None):
    """e-Stat APIから指定品目・地域の月次推移を取得する"""
    params = {
        "appId": APP_ID,
        "statsDataId": stats_data_id,
        "cdCat01": cat_code,
        "cdArea": area_code,
    }
    if tab_code:
        params["cdTab"] = tab_code

    try:
        res = requests.get(DATA_URL, params=params, timeout=12)
        data = res.json()

        result_inf = data.get("GET_STATS_DATA", {}).get("RESULT", {})
        if result_inf.get("STATUS") != 0 and result_inf.get("STATUS") != "0":
            err_msg = result_inf.get("ERROR_MSG", "不明なAPIエラー")
            return EMPTY_DF.copy(), f"APIエラー: {err_msg}"

        data_inf = data.get("GET_STATS_DATA", {}).get("STATISTICAL_DATA", {}).get("DATA_INF", {})
        values = data_inf.get("VALUE", [])
        if isinstance(values, dict):
            values = [values]
        if not values:
            return EMPTY_DF.copy(), "該当するデータが存在しませんでした。"

        df = pd.DataFrame(values)

        if "@tab" in df.columns and tab_code is None:
            df_tab1 = df[df["@tab"] == "1"]
            if not df_tab1.empty:
                df = df_tab1

        if "@unit" in df.columns:
            df_yen = df[df["@unit"] == "円"]
            if not df_yen.empty:
                df = df_yen

        df = df[df["@time"].str.len() == 10].copy()
        df["month_str"] = df["@time"].str[6:8]
        valid_months = [f"{m:02d}" for m in range(1, 13)]
        df = df[df["month_str"].isin(valid_months)].copy()

        if df.empty:
            return EMPTY_DF.copy(), "月次データが見つかりませんでした。"

        df["year"] = df["@time"].str[:4].astype(int)
        df["month"] = df["month_str"].astype(int)
        df["ym_str"] = df["year"].astype(str) + "-" + df["month_str"] + "-01"
        df["ym"] = pd.to_datetime(df["ym_str"], format="%Y-%m-%d")
        df["val"] = pd.to_numeric(df["$"], errors="coerce")
        df = df.dropna(subset=["val"]).sort_values("ym").drop_duplicates(subset=["ym"]).reset_index(drop=True)

        return df[["ym", "year", "month", "val"]], None
    except Exception as e:
        return EMPTY_DF.copy(), f"通信例外エラー: {str(e)}"


# --------------------------------------------------
# ランキング用：母数を拡大して確実に10品目を抽出
# --------------------------------------------------
@st.cache_data(ttl=86400, show_spinner=False)
def get_ranking_data():
    """主要品目の直近前年比（CPI・家計支出）を計算してランキング用データを生成"""
    ranking_records = []
    sampled_items = []
    for maj, mids in hierarchy_tree.items():
        for mid, its in mids.items():
            for it in its:
                sampled_items.append(it)
                if len(sampled_items) >= 100:
                    break
            if len(sampled_items) >= 100:
                break
        if len(sampled_items) >= 100:
            break

    for it in sampled_items:
        df_c, _ = fetch_stat_data(CPI_STATS_ID, it["cpi_code"], "00000", tab_code="1")
        df_k, _ = fetch_stat_data(KAKEI_STATS_ID, it["kakei_code"], "00000", tab_code="01")
        if df_c.empty or df_k.empty:
            continue
        m = pd.merge(df_c, df_k, on=["ym", "year", "month"], suffixes=("_cpi", "_kakei"))
        if len(m) < 13:
            continue
        latest = m.iloc[-1]
        prev = m[(m["year"] == latest["year"] - 1) & (m["month"] == latest["month"])]
        if prev.empty:
            continue
        prev_row = prev.iloc[0]
        if prev_row["val_cpi"] > 0 and prev_row["val_kakei"] > 0:
            cpi_diff = ((latest["val_cpi"] - prev_row["val_cpi"]) / prev_row["val_cpi"]) * 100
            kakei_diff = ((latest["val_kakei"] - prev_row["val_kakei"]) / prev_row["val_kakei"]) * 100
            ranking_records.append({
                "item_name": it["item_name"],
                "cpi_yoy": cpi_diff,
                "kakei_yoy": kakei_diff,
            })
    return pd.DataFrame(ranking_records)


# --------------------------------------------------
# 5. メイン画面ヘッダー ＆ CPI解説ポップオーバー
# --------------------------------------------------
col_title, col_help = st.columns([4, 1.2])
with col_title:
    st.title("📊 SMBMARK｜消費・物価トレンド分析ダッシュボード")
    st.caption("物価（CPI）× 家計消費から読み解く、中小企業のための値上げ・需要予測インテリジェンス")

with col_help:
    st.write("")
    with st.popover("❓ 物価指数（CPI）とは？", use_container_width=True):
        st.markdown(
            """
        ### 📖 消費者物価指数（CPI）とは？

        全国の世帯が購入するモノやサービスの「**価格の平均的な変動**」を測定する国の公的指標です。

        ---
        #### 🔢 数値の見方（2020年＝100）
        基準年である **2020年の価格を『100』** として計算しています。

        - **113.6 の場合**：
          2020年に100円だったものが、現在は約113.6円（**+13.6% 値上がり**）している状態。
        - **100.0 の場合**：
          2020年と同水準の価格。
        - **95.0 の場合**：
          2020年よりも約5% 値下がり（デフレ）している状態。

        ---
        #### 💡 このダッシュボードでの使い方
        - **CPI（価格）が上がっているのに、家計支出額も落ちていない場合**：
          ➔ お客さんが値上げを受け入れている（値上げ余力あり）強力な証拠です！
        """
        )

# --------------------------------------------------
# 5-2. 対象条件の表示 ＆ アクティブフィルターチップ
# --------------------------------------------------
st.markdown(
    f'<div class="section-caption">対象品目: <b>{selected_major} ＞ {selected_middle} ＞ {target_item_name}</b>'
    f' ｜ 比較地域: <b>{selected_area_name}</b> ｜ 分析期間: <b>{period_years}</b></div>',
    unsafe_allow_html=True
)

chip_items = [
    ("sel_major", f"大分類: {selected_major}", _reset_major),
    ("sel_middle", f"中分類: {selected_middle}", _reset_middle),
    ("sel_item_key", f"品目: {target_item_name}", _reset_item),
    ("sel_area", f"地域: {selected_area_name}", _reset_area),
    ("sel_period_years", f"期間: {period_years}", _reset_period),
]

st.markdown('<div class="filter-chip-label">絞り込み中の条件（クリックで単項目のみリセット）</div>', unsafe_allow_html=True)
cols = st.columns(len(chip_items))
for col, (skey, label, callback) in zip(cols, chip_items):
    with col:
        st.button(f"{label}  ✕", key=f"chip_{skey}", use_container_width=True, on_click=callback)
st.button("すべて解除", key="clear_all_chips", on_click=_clear_all_filters)
st.write("")

# --------------------------------------------------
# 6. タブ切り替えレイアウト（3タブ構成）
# --------------------------------------------------
tab_rank, tab_single, tab_area = st.tabs([
    "🏆 タブ1: 値上げ耐性・買い控えランキング",
    "📈 タブ2: 個別品目分析（CPI × 家計消費）",
    "🌍 タブ3: 地域間格差・商圏比較（全国 vs 自社商圏）"
])

# ==================================================
# タブ1: 値上げ耐性・買い控えランキング
# ==================================================
with tab_rank:
    st.subheader("🏆 全品目トレンド：値上げ耐性 vs 買い控えランキング")
    st.markdown("全国の主要消費品目の中から、**「値上げが通用している品目」** と **「買い控えが直撃している品目」** を自動集計して対比します。")

    with st.spinner("代表品目の最新前年比データを集計中（初回のみ15秒程度かかります）..."):
        df_rank = get_ranking_data()

    if df_rank.empty:
        st.info("ランキングデータを集計中です。しばらくお待ちいただくか、タブ2の個別分析をご覧ください。")
    else:
        df_pass = df_rank[df_rank["cpi_yoy"] >= 0].copy()
        if len(df_pass) < 10:
            df_pass = df_rank.copy()
        df_pass = df_pass.sort_values(by="kakei_yoy", ascending=False).head(10)

        df_risk = df_rank[df_rank["cpi_yoy"] >= 0].copy()
        if len(df_risk) < 10:
            df_risk = df_rank.copy()
        df_risk = df_risk.sort_values(by="kakei_yoy", ascending=True).head(10)

        col_r1, col_r2 = st.columns(2)

        with col_r1:
            st.markdown("#### 🟩 値上げ受容ランキング TOP 10")
            st.caption("価格（CPI）が上昇しても、家計支出が落ちていない（客離れが起きにくい品目）")
            fig_pass = go.Figure()
            add_gradient_bar_h(
                fig_pass, df_pass["item_name"], df_pass["kakei_yoy"],
                GOOD_GRAD, "支出額 伸び率 (%)", hover_prefix="支出額"
            )
            fig_pass.add_trace(go.Scatter(
                y=df_pass["item_name"],
                x=df_pass["cpi_yoy"],
                name="物価 (CPI) 上昇率 (%)",
                mode="markers",
                marker=dict(color=PRICE_COLOR, size=10, symbol="diamond",
                            line=dict(color="rgba(255,255,255,0.4)", width=1)),
                hovertemplate="%{y}<br>CPI上昇: %{x:+.1f}%<extra></extra>"
            ))
            style_fig(
                fig_pass,
                barmode="stack", bargap=0.3, hovermode="closest", height=480,
                yaxis=dict(autorange="reversed", title="", gridcolor=GRID_COLOR),
                xaxis=dict(title="前年同月比 変化率 (%)", ticksuffix="%", gridcolor=GRID_COLOR),
            )
            st.plotly_chart(fig_pass, use_container_width=True, config=PLOTLY_CONFIG)

        with col_r2:
            st.markdown("#### 🟥 買い控え警戒ランキング TOP 10")
            st.caption("価格（CPI）の上昇に対し、家計支出が大きく減少している（節約・離脱リスクが高い品目）")
            fig_risk = go.Figure()
            add_gradient_bar_h(
                fig_risk, df_risk["item_name"], df_risk["kakei_yoy"],
                RISK_GRAD, "支出額 減少率 (%)", hover_prefix="支出額"
            )
            fig_risk.add_trace(go.Scatter(
                y=df_risk["item_name"],
                x=df_risk["cpi_yoy"],
                name="物価 (CPI) 上昇率 (%)",
                mode="markers",
                marker=dict(color=PRICE_COLOR, size=10, symbol="diamond",
                            line=dict(color="rgba(255,255,255,0.4)", width=1)),
                hovertemplate="%{y}<br>CPI上昇: %{x:+.1f}%<extra></extra>"
            ))
            style_fig(
                fig_risk,
                barmode="stack", bargap=0.3, hovermode="closest", height=480,
                yaxis=dict(autorange="reversed", title="", gridcolor=GRID_COLOR),
                xaxis=dict(title="前年同月比 変化率 (%)", ticksuffix="%", gridcolor=GRID_COLOR),
            )
            st.plotly_chart(fig_risk, use_container_width=True, config=PLOTLY_CONFIG)

        st.info("💡 **見方のポイント**: 緑のバー（支出）が右に伸びている品目は、値上げしても購入され続けている生活必需品や高付加価値品です。赤のバーが左に伸びている品目は、価格上昇に伴い消費者の節約・買い控えが起きているため、価格据え置きやお得なセット化などの対策が求められます。")

# ==================================================
# タブ2: 個別品目分析（CPI × 家計消費）
# ==================================================
with tab_single:
    cpi_code = target_item_info["cpi_code"]
    kakei_code = target_item_info["kakei_code"]
    target_area_code = AREA_MASTER[selected_area_name]

    with st.spinner(f"「{target_item_name}」の公的データを取得中..."):
        df_cpi_nat, err_cpi = fetch_stat_data(CPI_STATS_ID, cpi_code, "00000", tab_code="1")
        df_kakei_nat, err_kakei = fetch_stat_data(KAKEI_STATS_ID, kakei_code, "00000", tab_code="01")

        if target_area_code != "00000":
            df_cpi_area, _ = fetch_stat_data(CPI_STATS_ID, cpi_code, target_area_code, tab_code="1")
            df_kakei_area, _ = fetch_stat_data(KAKEI_STATS_ID, kakei_code, target_area_code, tab_code="01")
        else:
            df_cpi_area, df_kakei_area = df_cpi_nat, df_kakei_nat

    if df_cpi_nat.empty or df_kakei_nat.empty:
        err_detail = err_cpi or err_kakei or "データが見つかりませんでした。"
        st.error(f"⚠️ **データ取得に失敗しました**: {err_detail}")
        st.info("別の品目（例: 食パン、清酒、ビール、キャベツなど）を選択してお試しください。")
        st.stop()

    df_merged = pd.merge(
        df_cpi_nat.rename(columns={"val": "cpi_national"}),
        df_kakei_nat.rename(columns={"val": "kakei_national"}),
        on=["ym", "year", "month"],
        how="inner",
    )

    if df_merged.empty:
        st.warning(f"「{target_item_name}」は物価指数と家計調査で共通する集計期間がありません。")
        st.stop()

    max_year = df_merged["year"].max()
    if period_years == "直近3年間":
        df_merged = df_merged[df_merged["year"] >= max_year - 2].reset_index(drop=True)
    elif period_years == "直近5年間":
        df_merged = df_merged[df_merged["year"] >= max_year - 4].reset_index(drop=True)

    st.subheader(f"💡「{target_item_name}」の値上げ耐性・需要弾力性診断")

    latest_row = df_merged.iloc[-1]
    prev_year_match = df_merged[
        (df_merged["year"] == latest_row["year"] - 1) & (df_merged["month"] == latest_row["month"])
    ]

    cpi_yoy = None
    kakei_yoy = None
    delta_cpi = None
    delta_kakei = None
    if not prev_year_match.empty:
        prev_row = prev_year_match.iloc[0]
        if prev_row["cpi_national"] and prev_row["cpi_national"] != 0:
            cpi_yoy = ((latest_row["cpi_national"] - prev_row["cpi_national"]) / prev_row["cpi_national"]) * 100
            delta_cpi = calc_delta(latest_row["cpi_national"], prev_row["cpi_national"])
        if prev_row["kakei_national"] and prev_row["kakei_national"] != 0:
            kakei_yoy = ((latest_row["kakei_national"] - prev_row["kakei_national"]) / prev_row["kakei_national"]) * 100
            delta_kakei = calc_delta(latest_row["kakei_national"], prev_row["kakei_national"])

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    with kpi1:
        kpi_card("最新集計月", f"{latest_row['year']}年{latest_row['month']}月")
    with kpi2:
        kpi_card("消費者物価指数（全国）", f"{latest_row['cpi_national']:.1f}", delta=delta_cpi)
    with kpi3:
        kpi_card("1世帯当たり支出額（全国）", f"{int(latest_row['kakei_national']):,} 円", delta=delta_kakei)
    with kpi4:
        if cpi_yoy is not None and kakei_yoy is not None:
            if cpi_yoy > 0 and kakei_yoy >= 0:
                badge_html = '<span class="badge-green">値上げ受容型</span>'
                sub_text = "価格上昇でも支出維持・増加（客離れ小）"
            elif cpi_yoy > 0 and kakei_yoy < -3.0:
                badge_html = '<span class="badge-red">買い控え警戒型</span>'
                sub_text = "価格上昇に対し支出が急減（客離れ警戒）"
            else:
                badge_html = '<span class="badge-amber">様子見・選別型</span>'
                sub_text = "支出横ばい・数量調整の可能性あり"
            kpi_card("値上げ耐性診断", badge_html, sub_text)
        else:
            kpi_card("値上げ耐性診断", "判定中", "前年データ照合中")

    st.write("")
    st.markdown("##### 2軸複合トレンド（左軸: 物価指数 ｜ 右軸: 家計支出額）")
    st.markdown(
        '<div class="section-caption">凡例をクリックすると系列の表示/非表示を切り替えられます（ダブルクリックで単独表示）。</div>',
        unsafe_allow_html=True
    )

    fig_dual = go.Figure()
    fig_dual.add_trace(
        go.Scatter(
            x=df_merged["ym"],
            y=df_merged["cpi_national"],
            name="物価指数 (2020年=100)",
            mode="lines+markers",
            line=dict(color=PRICE_COLOR, width=2.5, shape="spline"),
            marker=dict(size=5, color=BG_MAIN, line=dict(color=PRICE_COLOR, width=2)),
            fill="tozeroy",
            fillcolor="rgba(96,165,250,0.10)",
            yaxis="y1",
            hovertemplate="%{x|%Y年%m月}<br>物価指数: %{y:.1f}<extra></extra>",
        )
    )
    fig_dual.add_trace(
        go.Bar(
            x=df_merged["ym"],
            y=df_merged["kakei_national"],
            name="家計支出額 (円)",
            marker=dict(color="rgba(251,191,36,0.45)", line=dict(color="rgba(255,255,255,0.12)", width=0.5)),
            yaxis="y2",
            hovertemplate="%{x|%Y年%m月}<br>支出額: %{y:,.0f} 円<extra></extra>",
        )
    )
    style_fig(
        fig_dual,
        hovermode="x unified", height=480,
        xaxis=dict(title="年月", gridcolor=GRID_COLOR),
        yaxis=dict(
            title=dict(text="消費者物価指数（CPI）", font=dict(color=PRICE_COLOR)),
            tickfont=dict(color=PRICE_COLOR),
            gridcolor=GRID_COLOR,
        ),
        yaxis2=dict(
            title=dict(text="1世帯当たり支出額（円）", font=dict(color=SPEND_COLOR)),
            tickfont=dict(color=SPEND_COLOR),
            overlaying="y", side="right", tickformat=",d",
        ),
    )
    st.plotly_chart(fig_dual, use_container_width=True, config=PLOTLY_CONFIG)

    st.subheader("💡 経営者のためのアクション示唆")
    col_act1, col_act2, col_act3 = st.columns(3)
    with col_act1:
        st.info(
            "**1. 価格転嫁の余力判断**\n\n"
            "物価指数が上昇しても支出額が落ちていない品目は、顧客が値上げを許容している強力なサインです。"
            "原価高騰分の価格改定を前向きに検討してください。"
        )
    with col_act2:
        st.warning(
            "**2. 単価と数量のバランス注視**\n\n"
            "支出額が横ばいの場合、単価上昇によって購入点数（買い控え）が起きている可能性があります。"
            "大容量パックやセット割など客単価維持の工夫が有効です。"
        )
    with col_act3:
        st.success(
            "**3. 顧客向け告知・納得感の醸成**\n\n"
            "『全国的に物価指数が〇%上昇している』公的統計エビデンスを店頭告知や商談資料に添えることで、顧客や取引先の納得感が高まります。"
        )

# ==================================================
# タブ3: 地域間格差・商圏比較
# ==================================================
with tab_area:
    st.subheader(f"🌍 地域間格差分析：全国平均 vs {selected_area_name}")

    if selected_area_name == "全国":
        st.info("サイドバーで「東京都区部」「大阪市」などの地方都市を選択すると、全国平均との比較が表示されます。")
    elif df_cpi_area.empty and df_kakei_area.empty:
        st.warning(
            f"ℹ️ **地域別データの公表状況について**\n\n"
            f"「{selected_area_name}」では、「{target_item_name}」の月次詳細データは国の公的統計において公表対象外（または大分類・年平均のみの集計）となっています。\n\n"
            f"タブ2の全国データをご参照いただくか、「東京都区部」などの主要都市を選択してお試しください。"
        )
    else:
        df_merged_area = df_merged.copy()

        if not df_cpi_area.empty:
            df_merged_area = pd.merge(
                df_merged_area,
                df_cpi_area.rename(columns={"val": "cpi_area"}),
                on=["ym", "year", "month"],
                how="left",
            )
        else:
            df_merged_area["cpi_area"] = np.nan

        if not df_kakei_area.empty:
            df_merged_area = pd.merge(
                df_merged_area,
                df_kakei_area.rename(columns={"val": "kakei_area"}),
                on=["ym", "year", "month"],
                how="left",
            )
        else:
            df_merged_area["kakei_area"] = np.nan

        col_area1, col_area2 = st.columns(2)
        with col_area1:
            st.markdown("##### 1. 物価指数（CPI）比較")
            if not df_cpi_area.empty and df_merged_area["cpi_area"].notna().any():
                fig_area_cpi = go.Figure()
                fig_area_cpi.add_trace(
                    go.Scatter(
                        x=df_merged_area["ym"],
                        y=df_merged_area["cpi_national"],
                        name="全国平均",
                        mode="lines",
                        line=dict(color=PRICE_COLOR, width=2, shape="spline"),
                    )
                )
                fig_area_cpi.add_trace(
                    go.Scatter(
                        x=df_merged_area["ym"],
                        y=df_merged_area["cpi_area"],
                        name=selected_area_name,
                        mode="lines",
                        line=dict(color=RISK_COLOR, width=3, shape="spline"),
                    )
                )
                style_fig(
                    fig_area_cpi,
                    hovermode="x unified", height=420,
                    xaxis=dict(title="年月", gridcolor=GRID_COLOR),
                    yaxis=dict(title="物価指数 (2020年=100)", gridcolor=GRID_COLOR),
                )
                st.plotly_chart(fig_area_cpi, use_container_width=True, config=PLOTLY_CONFIG)
            else:
                st.info(f"「{target_item_name}」の{selected_area_name}別物価指数データは公的統計で公表されていません。")

        with col_area2:
            st.markdown("##### 2. 家計支出金額（円）比較")
            if not df_kakei_area.empty and df_merged_area["kakei_area"].notna().any():
                fig_area_kakei = go.Figure()
                fig_area_kakei.add_trace(
                    go.Scatter(
                        x=df_merged_area["ym"],
                        y=df_merged_area["kakei_national"],
                        name="全国平均",
                        mode="lines",
                        line=dict(color=PRICE_COLOR, width=2, shape="spline"),
                    )
                )
                fig_area_kakei.add_trace(
                    go.Scatter(
                        x=df_merged_area["ym"],
                        y=df_merged_area["kakei_area"],
                        name=selected_area_name,
                        mode="lines",
                        line=dict(color=GOOD_COLOR, width=3, shape="spline"),
                    )
                )
                style_fig(
                    fig_area_kakei,
                    hovermode="x unified", height=420,
                    xaxis=dict(title="年月", gridcolor=GRID_COLOR),
                    yaxis=dict(title="支出額（円）", tickformat=",d", gridcolor=GRID_COLOR),
                )
                st.plotly_chart(fig_area_kakei, use_container_width=True, config=PLOTLY_CONFIG)
            else:
                st.info(f"「{target_item_name}」の{selected_area_name}別支出額データは公的統計で公表されていません。")
