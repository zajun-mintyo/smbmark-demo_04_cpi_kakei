import json
import os
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

# --------------------------------------------------
# 1. ページ基本設定 & 最上部ホバーボタン (CSS)
# --------------------------------------------------
st.set_page_config(
    page_title="SMBMARK｜消費・物価トレンド分析ダッシュボード",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
#top-anchor {
    position: absolute;
    top: 0;
    left: 0;
}
.scroll-top-btn {
    position: fixed;
    bottom: 25px;
    right: 30px;
    z-index: 9999;
    background-color: #1f77b4;
    color: white !important;
    border: none;
    border-radius: 50%;
    width: 50px;
    height: 50px;
    font-size: 24px;
    font-weight: bold;
    cursor: pointer;
    box-shadow: 0 4px 8px rgba(0,0,0,0.3);
    transition: all 0.3s ease;
    display: flex;
    align-items: center;
    justify-content: center;
    text-decoration: none !important;
}
.scroll-top-btn:hover {
    background-color: #0d47a1;
    transform: translateY(-4px);
    box-shadow: 0 6px 12px rgba(0,0,0,0.4);
}
</style>
<div id="top-anchor"></div>
<a href="#top-anchor" class="scroll-top-btn" title="最上部へ戻る">↑</a>
""",
    unsafe_allow_html=True,
)

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
st.sidebar.title("🔍 検索・絞り込み条件")

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
st.sidebar.subheader("📦 個別分析用 品目選択")

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
st.sidebar.subheader("🌍 地域・期間の選択")

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
    # 主要品目を全ジャンルからバランスよく抽出（約100品目）
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
        # 1. 値上げ受容ランキング（支出の伸びが大きい上位10件）
        df_pass = df_rank[df_rank["cpi_yoy"] >= 0].copy()
        if len(df_pass) < 10:
            df_pass = df_rank.copy()
        df_pass = df_pass.sort_values(by="kakei_yoy", ascending=False).head(10)

        # 2. 買い控え警戒ランキング（支出の落ち込みが大きい上位10件）
        df_risk = df_rank[df_rank["cpi_yoy"] >= 0].copy()
        if len(df_risk) < 10:
            df_risk = df_rank.copy()
        df_risk = df_risk.sort_values(by="kakei_yoy", ascending=True).head(10)

        col_r1, col_r2 = st.columns(2)

        with col_r1:
            st.markdown("#### 🟩 値上げ受容ランキング TOP 10")
            st.caption("価格（CPI）が上昇しても、家計支出が落ちていない（客離れが起きにくい品目）")
            fig_pass = go.Figure()
            fig_pass.add_trace(go.Bar(
                y=df_pass["item_name"],
                x=df_pass["kakei_yoy"],
                name="支出額 伸び率 (%)",
                orientation="h",
                marker_color="#2ca02c",
                hovertemplate="%{y}<br>支出額: %{x:+.1f}%<extra></extra>"
            ))
            fig_pass.add_trace(go.Scatter(
                y=df_pass["item_name"],
                x=df_pass["cpi_yoy"],
                name="物価 (CPI) 上昇率 (%)",
                mode="markers",
                marker=dict(color="#1f77b4", size=9, symbol="diamond"),
                hovertemplate="%{y}<br>CPI上昇: %{x:+.1f}%<extra></extra>"
            ))
            fig_pass.update_layout(
                yaxis=dict(autorange="reversed", title=""),
                xaxis=dict(title="前年同月比 変化率 (%)", ticksuffix="%"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                height=480,
                bargap=0.3,
            )
            st.plotly_chart(fig_pass, use_container_width=True)

        with col_r2:
            st.markdown("#### 🟥 買い控え警戒ランキング TOP 10")
            st.caption("価格（CPI）の上昇に対し、家計支出が大きく減少している（節約・離脱リスクが高い品目）")
            fig_risk = go.Figure()
            fig_risk.add_trace(go.Bar(
                y=df_risk["item_name"],
                x=df_risk["kakei_yoy"],
                name="支出額 減少率 (%)",
                orientation="h",
                marker_color="#d62728",
                hovertemplate="%{y}<br>支出額: %{x:+.1f}%<extra></extra>"
            ))
            fig_risk.add_trace(go.Scatter(
                y=df_risk["item_name"],
                x=df_risk["cpi_yoy"],
                name="物価 (CPI) 上昇率 (%)",
                mode="markers",
                marker=dict(color="#1f77b4", size=9, symbol="diamond"),
                hovertemplate="%{y}<br>CPI上昇: %{x:+.1f}%<extra></extra>"
            ))
            fig_risk.update_layout(
                yaxis=dict(autorange="reversed", title=""),
                xaxis=dict(title="前年同月比 変化率 (%)", ticksuffix="%"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                height=480,
                bargap=0.3,
            )
            st.plotly_chart(fig_risk, use_container_width=True)

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
    if not prev_year_match.empty:
        prev_row = prev_year_match.iloc[0]
        if prev_row["cpi_national"] and prev_row["cpi_national"] != 0:
            cpi_yoy = ((latest_row["cpi_national"] - prev_row["cpi_national"]) / prev_row["cpi_national"]) * 100
        if prev_row["kakei_national"] and prev_row["kakei_national"] != 0:
            kakei_yoy = ((latest_row["kakei_national"] - prev_row["kakei_national"]) / prev_row["kakei_national"]) * 100

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("最新集計月", f"{latest_row['year']}年{latest_row['month']}月")
    kpi2.metric(
        "消費者物価指数（全国）",
        f"{latest_row['cpi_national']:.1f}",
        delta=f"{cpi_yoy:+.1f}% (前年比)" if cpi_yoy is not None else None,
    )
    kpi3.metric(
        "1世帯当たり支出額（全国）",
        f"{int(latest_row['kakei_national']):,} 円",
        delta=f"{kakei_yoy:+.1f}% (前年比)" if kakei_yoy is not None else None,
    )

    with kpi4:
        if cpi_yoy is not None and kakei_yoy is not None:
            if cpi_yoy > 0 and kakei_yoy >= 0:
                st.success("🟩 **値上げ受容型**\n\n価格上昇でも支出維持・増加（客離れ小）")
            elif cpi_yoy > 0 and kakei_yoy < -3.0:
                st.error("🟥 **買い控え警戒型**\n\n価格上昇に対し支出が急減（客離れ警戒）")
            else:
                st.warning("🟨 **様子見・選別型**\n\n支出横ばい・数量調整の可能性あり")
        else:
            st.info("判定計算中（前年データ照合中）")

    st.markdown("---")
    st.markdown("##### 2軸複合トレンド（左軸: 物価指数 ｜ 右軸: 家計支出額）")
    st.caption("※ 凡例をクリックすると系列の表示/非表示を切り替えられます（ダブルクリックで単独表示）。")

    fig_dual = go.Figure()
    fig_dual.add_trace(
        go.Scatter(
            x=df_merged["ym"],
            y=df_merged["cpi_national"],
            name="物価指数 (2020年=100)",
            mode="lines+markers",
            line=dict(color="#1f77b4", width=3),
            yaxis="y1",
            hovertemplate="%{x|%Y年%m月}<br>物価指数: %{y:.1f}<extra></extra>",
        )
    )
    fig_dual.add_trace(
        go.Bar(
            x=df_merged["ym"],
            y=df_merged["kakei_national"],
            name="家計支出額 (円)",
            marker_color="rgba(255, 127, 14, 0.4)",
            yaxis="y2",
            hovertemplate="%{x|%Y年%m月}<br>支出額: %{y:,.0f} 円<extra></extra>",
        )
    )
    fig_dual.update_layout(
        xaxis=dict(title=dict(text="年月")),
        yaxis=dict(
            title=dict(text="消費者物価指数（CPI）", font=dict(color="#1f77b4")),
            tickfont=dict(color="#1f77b4"),
        ),
        yaxis2=dict(
            title=dict(text="1世帯当たり支出額（円）", font=dict(color="#ff7f0e")),
            tickfont=dict(color="#ff7f0e"),
            overlaying="y",
            side="right",
            tickformat=",d",
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        height=480,
    )
    st.plotly_chart(fig_dual, use_container_width=True)

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
                        line=dict(color="#1f77b4", width=2),
                    )
                )
                fig_area_cpi.add_trace(
                    go.Scatter(
                        x=df_merged_area["ym"],
                        y=df_merged_area["cpi_area"],
                        name=selected_area_name,
                        mode="lines",
                        line=dict(color="#d62728", width=3),
                    )
                )
                fig_area_cpi.update_layout(
                    xaxis=dict(title=dict(text="年月")),
                    yaxis=dict(title=dict(text="物価指数 (2020年=100)")),
                    hovermode="x unified",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    height=420,
                )
                st.plotly_chart(fig_area_cpi, use_container_width=True)
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
                        line=dict(color="#1f77b4", width=2),
                    )
                )
                fig_area_kakei.add_trace(
                    go.Scatter(
                        x=df_merged_area["ym"],
                        y=df_merged_area["kakei_area"],
                        name=selected_area_name,
                        mode="lines",
                        line=dict(color="#2ca02c", width=3),
                    )
                )
                fig_area_kakei.update_layout(
                    xaxis=dict(title=dict(text="年月")),
                    yaxis=dict(title=dict(text="支出額（円）"), tickformat=",d"),
                    hovermode="x unified",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    height=420,
                )
                st.plotly_chart(fig_area_kakei, use_container_width=True)
            else:
                st.info(f"「{target_item_name}」の{selected_area_name}別支出額データは公的統計で公表されていません。")
