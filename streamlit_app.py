import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium


def enblcid_split(df0):
    df1 = df0.copy()

    df1["eNB-LCID"] = df1["eNB-LCID"].str.split()
    df2 = df1.explode("eNB-LCID")

    df2[["eNB", "LCID"]] = df2["eNB-LCID"].str.split("-", expand=True)
    df2["LCID"] = df2["LCID"].str.split(",")
    df3 = df2.explode("LCID").astype({"eNB": int, "LCID": int})

    df3["cell_id"] = df3.apply(lambda x: (x["eNB"] << 8) | x["LCID"], axis=1)

    result = df3.sort_values(["cell_id"]).reset_index(drop=True)

    return result


def highlight_max(s):
    is_max = s == s.max()
    return ["background-color: yellow" if v else "" for v in is_max.fillna(False)]


def highlight_min(s):
    is_min = s == s.min()
    return ["background-color: yellow" if v else "" for v in is_min.fillna(False)]


st.set_page_config(page_title="TowerCollectorファイル分析")
st.title("TowerCollectorファイル分析")

st.subheader("ファイル")
uploaded_files = st.file_uploader("TowerCollector CSV", type="csv", key="csv", accept_multiple_files=True)

st.subheader("TA設定")
ta_radius = st.number_input("TA", 0, 999, 150, step=1)
ta_satellite = st.number_input("衛星エントランスTA調整", 0, 150, 4, step=1)


if uploaded_files:
    dfs = [
        pd.read_csv(uploaded_file, parse_dates=["measured_at", "discovered_at"], dtype={"ta": str}).dropna(
            how="all", axis=1
        )
        for uploaded_file in uploaded_files
    ]

    # CSV結合
    df0 = pd.concat(dfs, ignore_index=True)

    # 日時変換
    df0["measured_at"] = df0["measured_at"].dt.tz_convert("Asia/Tokyo").dt.tz_localize(None)
    df0["discovered_at"] = df0["discovered_at"].dt.tz_convert("Asia/Tokyo").dt.tz_localize(None)

    df0["cell_no"] = df0["short_cell_id"] & 0x3FFF

    # タイプ別
    df0["type"] = pd.cut(
        df0["cell_no"],
        bins=[0, 4000, 4500, 5000, 10000, 15000, 16384],
        labels=["マクロセル", "ミニマクロ", "衛星エントランス", "Casa", "屋内局", "ピコセル"],
    )

    # TA調整
    df0["calibration"] = (
        df0["type"]
        .replace(
            {"マクロセル": 0, "ミニマクロ": 0, "衛星エントランス": ta_satellite, "Casa": 0, "屋内局": 0, "ピコセル": 0}
        )
        .astype(int)
    )

    df0["short_cell_id"] = df0["short_cell_id"].astype(int)
    df0["rnc"] = df0["rnc"].astype(int)

    # 範囲指定
    df1 = df0.query("188743680 <= cell_id < 190023680").copy()

    df1["id"] = df1["short_cell_id"].astype(str) + "-" + df1["rnc"].astype(str)
    df1["ta"] = pd.to_numeric(df1["ta"], errors="coerce").astype("Int64")

    rsrp_max = df1.dropna(subset=["rsrp"]).groupby(["cell_id", "id", "psc"])["rsrp"].max()
    ta_min = df1.dropna(subset=["ta"]).groupby(["cell_id", "id", "psc"])["ta"].min()

    df2 = pd.concat([rsrp_max, ta_min], axis=1).sort_values("cell_id").reset_index()

    df1["ta_adjusted"] = df1["ta"] - df1["calibration"]

    df1["radius"] = (df1["ta_adjusted"] * ta_radius).fillna(0)

    # 愛媛県の基地局

    df_ehime = pd.read_csv(
        "https://raku10ehime.github.io/map/ehime.csv",
        index_col=0,
        dtype={"sector": "Int64", "sub6": "Int64", "ミリ波": "Int64"},
    )

    df3 = df_ehime.dropna(subset=["eNB-LCID"])
    df4 = enblcid_split(df3)

    df5 = df2[~df2["cell_id"].isin(df4["cell_id"])].copy()
    df6 = df1[~df1["cell_id"].isin(df4["cell_id"])].copy()

    if len(df5) > 0:
        st.subheader("基地局一覧")
        st.dataframe(df5[["id", "psc", "rsrp", "ta"]], width=700, hide_index=True)

        st.subheader("地図表示")

        option = df5["id"].tolist()

        # ストリームリットセレクトボックスの作成
        chois = st.multiselect("どのeNB-LCIDを選択しますか？", option, max_selections=3, placeholder="選んでください")

        colors = ["red", "green", "blue"]

        if chois:
            df7 = df6[df6["id"].isin(chois)].copy()

            color_number = {k: v for v, k in enumerate(chois)}

            df7["color"] = df7["id"].map(color_number)

            # 半径0m未満は0に修正
            df7["radius"] = df7["radius"].mask(df7["radius"] < 0, 0)

            m = folium.Map(
                location=[df7["lat"].mean(), df7["lon"].mean()],
                tiles="https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png",
                attr='&copy; <a href="https://maps.gsi.go.jp/development/ichiran.html">国土地理院</a>',
                zoom_start=14,
            )

            # 既存基地局
            for _, r in df_ehime.iterrows():
                folium.Marker(
                    location=[r["緯度"], r["経度"]],
                    popup=folium.Popup(f'<p>{r["場所"]}</p>', max_width=300),
                    tooltip=r["場所"],
                    icon=folium.Icon(color=r["color"], icon=r["icon"]),
                ).add_to(m)

            # TAサークル
            for _, r in df7.iterrows():
                if r["radius"] > 0:
                    folium.Circle(
                        location=[r["lat"], r["lon"]],
                        radius=r["radius"],
                        color=colors[r["color"]],
                    ).add_to(m)

            # マップをストリームリットに表示
            st_data = st_folium(m, width=700, height=500, returned_objects=[])

            df_view = df7[["id", "psc", "type", "rsrp", "ta", "ta_adjusted", "radius"]]

            styled_df = df_view.style.apply(highlight_max, subset=["rsrp"]).apply(highlight_min, subset=["ta"])

            st.dataframe(
                styled_df,
                width=700,
                hide_index=True,
            )
