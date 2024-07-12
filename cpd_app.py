import pathlib

import pandas as pd
import requests
from streamlit_folium import st_folium

import folium
import folium.plugins
import streamlit as st

labels = ["マクロセル", "ミニマクロ", "衛星エントランス", "Casa", "屋内局", "ピコセル"]


def fetch_file(url, fn):
    p = pathlib.Path(fn)
    p.parent.mkdir(parents=True, exist_ok=True)

    r = requests.get(url)
    r.raise_for_status()

    with p.open(mode="wb") as fw:
        fw.write(r.content)

    return p


@st.cache_data
def load_data():
    url = "https://44011.brave-hero.net/api/v1/csvexport?mcc=440&mnc=11&after=1704067200&mlscompatible=on&cellid_after=188743680&cellid_before=192937984"
    p = fetch_file(url, "mls.csv")

    df = pd.read_csv(p, dtype={"unit": str})
    df["created"] = pd.to_datetime(df["created"], unit="s", utc=True).dt.tz_convert("Asia/Tokyo").dt.tz_localize(None)
    df["updated"] = pd.to_datetime(df["updated"], unit="s", utc=True).dt.tz_convert("Asia/Tokyo").dt.tz_localize(None)
    df[["enb", "lcid"]] = df["cell"].apply(lambda x: pd.Series([x >> 8, x & 0xFF]))
    df["enb-lcid"] = df["enb"].astype(str) + "-" + df["lcid"].astype(str)
    df["cell_no"] = df["enb"] & 0x2FFF
    df["type"] = pd.cut(
        df["cell_no"],
        bins=[0, 4000, 4500, 5000, 10000, 15000, 16384],
        labels=labels,
    )

    return df


# 位置情報初期化
if "lat" not in st.session_state:
    st.session_state.lat = 33.8391
if "lng" not in st.session_state:
    st.session_state.lng = 132.7655


# タイトル
st.set_page_config(page_title="CDP")
st.title("CDP")


df0 = load_data()

# 期間
slider_days = st.slider("値を選択してください", min_value=0, max_value=180, value=90)

dt_now = pd.Timestamp.now(tz="Asia/Tokyo").tz_localize(None)
before_days = (dt_now - pd.Timedelta(days=slider_days)).floor("D")

df1 = df0[df0["updated"] >= before_days].copy()

# 設置タイプ
option = st.selectbox("どのタイプを選択しますか？", labels)

df2 = df1[df1["type"] == option].reset_index(drop=True).copy()


# foliumの初期化
m = folium.Map(
    location=[st.session_state.lat, st.session_state.lng],
    tiles="https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png",
    attr='&copy; <a href="https://maps.gsi.go.jp/development/ichiran.html">国土地理院</a>',
    zoom_start=12,
)

# データフレームからマーカーを追加
for _, row in df2.iterrows():
    folium.Marker(
        location=[row["lat"], row["lon"]],
        popup=folium.Popup(f'{row["enb-lcid"]}<br>{row["updated"]}', max_width=300),
        tooltip=row["enb-lcid"],
    ).add_to(m)

# 現在値
folium.plugins.LocateControl().add_to(m)

# マップをストリームリットに表示
st_data = st_folium(m, width=700, height=500)

# マップ境界内のデータフィルタリング
if st_data:
    bounds = st_data["bounds"]
    center = st_data.get("center", {"lat": st.session_state.lat, "lng": st.session_state.lng})

    southWest_lat = bounds["_southWest"]["lat"]
    southWest_lng = bounds["_southWest"]["lng"]
    northEast_lat = bounds["_northEast"]["lat"]
    northEast_lng = bounds["_northEast"]["lng"]

    # 境界内のポイントをフィルタリング
    filtered_df = df2.loc[
        (df2["lat"] >= southWest_lat)
        & (df2["lat"] <= northEast_lat)
        & (df2["lon"] >= southWest_lng)
        & (df2["lon"] <= northEast_lng)
    ].copy()

    # マップの中心位置を更新
    if st.button("現在の地図の中心を保存"):
        st.session_state.lat = center["lat"]
        st.session_state.lng = center["lng"]
        st.success("地図の中心位置を更新しました")

    # cellでソート
    filtered_df.sort_values("cell", inplace=True)

    # 結果を表示
    df3 = filtered_df[["enb-lcid", "unit", "created", "updated", "lat", "lon"]].reset_index(drop=True)

    st.dataframe(
        df3,
        width=700,
        hide_index=True,
    )
