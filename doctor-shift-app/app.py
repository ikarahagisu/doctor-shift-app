import streamlit as st
import pandas as pd
import json
import io
import calendar
from datetime import date, timedelta
import jpholiday

st.set_page_config(
    page_title="医師シフト管理システム",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── カスタムCSS ──────────────────────────────────────────
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #1a5276 0%, #2e86c1 100%);
        color: white;
        padding: 1.2rem 2rem;
        border-radius: 10px;
        margin-bottom: 1.5rem;
    }
    .shift-cell-weekday { background-color: #eaf4fb; border-radius:4px; padding:4px 8px; font-size:13px; }
    .shift-cell-holiday { background-color: #fef9e7; border-radius:4px; padding:4px 8px; font-size:13px; }
    .shift-cell-fixed   { background-color: #eafaf1; border-radius:4px; padding:4px 8px; font-size:13px; font-weight:600; }
    .badge-fixed { background:#27ae60; color:white; border-radius:10px; padding:2px 8px; font-size:11px; }
    .badge-ng    { background:#e74c3c; color:white; border-radius:10px; padding:2px 8px; font-size:11px; }
    .badge-wish  { background:#f39c12; color:white; border-radius:10px; padding:2px 8px; font-size:11px; }
    div[data-testid="stDataFrame"] { border-radius: 8px; overflow: hidden; }
</style>
""", unsafe_allow_html=True)

# ── セッション初期化 ─────────────────────────────────────
def init_state():
    if "doctors" not in st.session_state:
        st.session_state.doctors = []
    if "doctor_limits" not in st.session_state:
        st.session_state.doctor_limits = {}
    if "constraints" not in st.session_state:
        st.session_state.constraints = {}
    if "fixed_shifts" not in st.session_state:
        st.session_state.fixed_shifts = {}
    if "generated_shifts" not in st.session_state:
        st.session_state.generated_shifts = {}
    if "selected_year" not in st.session_state:
        st.session_state.selected_year = 2026
    if "selected_month" not in st.session_state:
        st.session_state.selected_month = 4

init_state()

SHIFT_WEEKDAY  = ["宿直A", "宿直B", "外来宿直"]
SHIFT_HOLIDAY  = ["宿直A", "宿直B", "外来宿直", "日直A", "日直B", "外来日直"]
ALL_SHIFTS     = ["宿直A", "宿直B", "外来宿直", "日直A", "日直B", "外来日直"]

# ── ユーティリティ ───────────────────────────────────────
def is_holiday(d: date) -> bool:
    return d.weekday() >= 5 or jpholiday.is_holiday(d)

def get_days_in_month(year: int, month: int):
    _, n = calendar.monthrange(year, month)
    return [date(year, month, d) for d in range(1, n+1)]

def day_label(d: date) -> str:
    w = ["月","火","水","木","金","土","日"][d.weekday()]
    holiday = jpholiday.is_holiday_name(d)
    mark = f"({holiday})" if holiday else ""
    return f"{d.month}/{d.day}({w}){mark}"

# ── シフト自動生成 ────────────────────────────────────────
def generate_shifts(year, month, doctors, doctor_limits, constraints, fixed_shifts):
    days = get_days_in_month(year, month)
    shift_result = {str(d): {} for d in days}

    # 固定シフトを先に入れる
    for key, val in fixed_shifts.items():
        parts = key.split("_", 1)
        if len(parts) == 2:
            day_str, shift_type = parts
            if day_str in shift_result:
                shift_result[day_str][shift_type] = val

    # 医師ごとのカウント・前回勤務日トラッキング
    counts = {doc: {s: 0 for s in ALL_SHIFTS} for doc in doctors}
    last_worked = {doc: None for doc in doctors}

    import random

    for d in days:
        day_str = str(d)
        shifts_today = SHIFT_HOLIDAY if is_holiday(d) else SHIFT_WEEKDAY

        for shift in shifts_today:
            # 既に固定シフトが入っている場合スキップ
            if shift in shift_result[day_str]:
                doc = shift_result[day_str][shift]
                if doc in counts:
                    counts[doc][shift] += 1
                    last_worked[doc] = d
                continue

            # 候補医師を優先度＋制約でフィルタ
            candidates = []
            for doc in doctors:
                c = constraints.get(doc, {})
                ng_days   = [date.fromisoformat(x) for x in c.get("ng_days", [])]
                wish_days = [date.fromisoformat(x) for x in c.get("wish_days", [])]
                min_gap   = c.get("min_gap", 1)
                month_min = c.get("month_min", 0)
                month_max = c.get("month_max", 99)
                priority  = c.get("priority", 5)

                lim = doctor_limits.get(doc, {})
                shift_max = lim.get(shift, 99)

                # NG日
                if d in ng_days:
                    continue
                # 最大回数チェック（シフト別）
                if counts[doc][shift] >= shift_max:
                    continue
                # 月間最大チェック
                total = sum(counts[doc].values())
                if total >= month_max:
                    continue
                # 連続勤務禁止（最低空ける日数）
                if last_worked[doc] is not None:
                    gap = (d - last_worked[doc]).days
                    if gap < min_gap:
                        continue

                # スコア計算
                score = priority * 10
                if d in wish_days:
                    score += 20
                # 均等化: 少ない人を優先
                score -= sum(counts[doc].values()) * 2

                candidates.append((score, random.random(), doc))

            if candidates:
                candidates.sort(reverse=True)
                chosen = candidates[0][2]
                shift_result[day_str][shift] = chosen
                counts[chosen][shift] += 1
                last_worked[chosen] = d
            else:
                shift_result[day_str][shift] = "（未割当）"

    return shift_result, counts

# ── サイドバー ────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🏥 医師シフト管理")
    st.markdown("---")

    menu = st.radio("メニュー", [
        "📅 シフト生成・表示",
        "👨‍⚕️ 医師設定",
        "📊 シフト制約CSV",
        "📌 固定シフト入力",
        "📈 統計・分析",
    ])

# ════════════════════════════════════════════════════════════
# ページ: 医師設定
# ════════════════════════════════════════════════════════════
if menu == "👨‍⚕️ 医師設定":
    st.markdown('<div class="main-header"><h2>👨‍⚕️ 医師設定</h2><p>医師の登録・制約条件を設定します</p></div>', unsafe_allow_html=True)

    col1, col2 = st.columns([1, 2])

    with col1:
        st.subheader("医師の追加")
        new_doc = st.text_input("医師名")
        if st.button("➕ 追加", use_container_width=True):
            if new_doc and new_doc not in st.session_state.doctors:
                st.session_state.doctors.append(new_doc)
                st.session_state.constraints[new_doc] = {
                    "ng_days": [], "wish_days": [], "wish_priority": 3,
                    "min_gap": 1, "month_min": 0, "month_max": 20, "priority": 5
                }
                st.success(f"✅ {new_doc} を追加しました")

        st.subheader("登録済み医師")
        for doc in st.session_state.doctors:
            c1, c2 = st.columns([3, 1])
            c1.write(f"👤 {doc}")
            if c2.button("削除", key=f"del_{doc}"):
                st.session_state.doctors.remove(doc)
                st.session_state.constraints.pop(doc, None)
                st.rerun()

    with col2:
        if st.session_state.doctors:
            st.subheader("制約条件設定")
            sel_doc = st.selectbox("医師を選択", st.session_state.doctors)
            c = st.session_state.constraints.get(sel_doc, {})

            year  = st.session_state.selected_year
            month = st.session_state.selected_month

            col_a, col_b = st.columns(2)
            with col_a:
                priority = st.slider("優先度（高いほど優先的に割当）", 1, 10, c.get("priority", 5))
                month_min = st.number_input("月間最小回数", 0, 31, c.get("month_min", 0))
                month_max = st.number_input("月間最大回数", 0, 31, c.get("month_max", 20))
                min_gap   = st.number_input("最低空ける日数", 1, 14, c.get("min_gap", 1))
            with col_b:
                wish_priority = st.slider("希望日の優先度", 1, 5, c.get("wish_priority", 3))
                _, n = calendar.monthrange(year, month)
                all_days = [date(year, month, d) for d in range(1, n+1)]

                ng_days_sel   = st.multiselect("NG日", all_days,
                    default=[date.fromisoformat(x) for x in c.get("ng_days", []) if date.fromisoformat(x) in all_days],
                    format_func=day_label, key=f"ng_{sel_doc}")
                wish_days_sel = st.multiselect("希望日", all_days,
                    default=[date.fromisoformat(x) for x in c.get("wish_days", []) if date.fromisoformat(x) in all_days],
                    format_func=day_label, key=f"wish_{sel_doc}")

            if st.button("💾 保存", use_container_width=True):
                st.session_state.constraints[sel_doc] = {
                    "priority": priority, "month_min": month_min, "month_max": month_max,
                    "min_gap": min_gap, "wish_priority": wish_priority,
                    "ng_days":   [str(d) for d in ng_days_sel],
                    "wish_days": [str(d) for d in wish_days_sel],
                }
                st.success("✅ 保存しました")

# ════════════════════════════════════════════════════════════
# ページ: シフト制約CSV
# ════════════════════════════════════════════════════════════
elif menu == "📊 シフト制約CSV":
    st.markdown('<div class="main-header"><h2>📊 シフト別上限回数（CSV設定）</h2><p>医師ごと・シフト種別ごとの月間最大回数を設定します</p></div>', unsafe_allow_html=True)

    doctors = st.session_state.doctors
    if not doctors:
        st.info("先に医師を登録してください。")
    else:
        st.markdown("#### CSVテンプレートのダウンロード")
        template = pd.DataFrame(
            {s: [st.session_state.doctor_limits.get(doc, {}).get(s, 5) for doc in doctors] for s in ALL_SHIFTS},
            index=doctors
        )
        template.index.name = "医師名"
        csv_buf = io.StringIO()
        template.to_csv(csv_buf)
        st.download_button("⬇️ テンプレートCSVダウンロード", csv_buf.getvalue(), "shift_limits_template.csv", "text/csv")

        st.markdown("#### CSVアップロード")
        uploaded = st.file_uploader("CSVをアップロード", type="csv")
        if uploaded:
            df = pd.read_csv(uploaded, index_col=0)
            for doc in df.index:
                if doc in doctors:
                    st.session_state.doctor_limits[doc] = {s: int(df.loc[doc, s]) for s in ALL_SHIFTS if s in df.columns}
            st.success("✅ CSVを読み込みました")

        st.markdown("#### 現在の設定（直接編集可）")
        rows = []
        for doc in doctors:
            row = {"医師名": doc}
            for s in ALL_SHIFTS:
                row[s] = st.session_state.doctor_limits.get(doc, {}).get(s, 5)
            rows.append(row)
        df_edit = pd.DataFrame(rows).set_index("医師名")
        edited = st.data_editor(df_edit, use_container_width=True, num_rows="fixed")
        if st.button("💾 変更を保存"):
            for doc in edited.index:
                st.session_state.doctor_limits[doc] = {s: int(edited.loc[doc, s]) for s in ALL_SHIFTS}
            st.success("✅ 保存しました")

# ════════════════════════════════════════════════════════════
# ページ: 固定シフト入力
# ════════════════════════════════════════════════════════════
elif menu == "📌 固定シフト入力":
    st.markdown('<div class="main-header"><h2>📌 固定シフト入力</h2><p>手動入力したシフトを絶対反映します</p></div>', unsafe_allow_html=True)

    year  = st.session_state.selected_year
    month = st.session_state.selected_month

    col1, col2 = st.columns([1, 2])
    with col1:
        st.subheader("固定シフト追加")
        _, n = calendar.monthrange(year, month)
        all_days = [date(year, month, d) for d in range(1, n+1)]
        sel_day   = st.selectbox("日付", all_days, format_func=day_label)
        available_shifts = SHIFT_HOLIDAY if is_holiday(sel_day) else SHIFT_WEEKDAY
        sel_shift = st.selectbox("シフト種別", available_shifts)
        sel_doc   = st.selectbox("担当医師", st.session_state.doctors) if st.session_state.doctors else None
        if st.button("➕ 固定シフト追加", use_container_width=True) and sel_doc:
            key = f"{sel_day}_{sel_shift}"
            st.session_state.fixed_shifts[key] = sel_doc
            st.success(f"✅ {day_label(sel_day)} {sel_shift} → {sel_doc} を固定しました")

    with col2:
        st.subheader("固定シフト一覧")
        if st.session_state.fixed_shifts:
            rows = []
            for k, v in sorted(st.session_state.fixed_shifts.items()):
                parts = k.split("_", 1)
                if len(parts) == 2:
                    rows.append({"日付": parts[0], "シフト": parts[1], "担当医師": v})
            df_fixed = pd.DataFrame(rows)
            st.dataframe(df_fixed, use_container_width=True, hide_index=True)

            del_keys = st.multiselect("削除するシフトを選択", list(st.session_state.fixed_shifts.keys()))
            if st.button("🗑️ 選択した固定シフトを削除"):
                for k in del_keys:
                    st.session_state.fixed_shifts.pop(k, None)
                st.rerun()
        else:
            st.info("固定シフトはまだありません。")

# ════════════════════════════════════════════════════════════
# ページ: シフト生成・表示
# ════════════════════════════════════════════════════════════
elif menu == "📅 シフト生成・表示":
    st.markdown('<div class="main-header"><h2>📅 シフト生成・表示</h2><p>AIが制約条件を考慮してシフトを自動生成します</p></div>', unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        year  = st.selectbox("年", [2026, 2027, 2028], index=0)
        st.session_state.selected_year = year
    with col2:
        month = st.selectbox("月", list(range(4, 13)) + list(range(1, 4)),
                             index=0, format_func=lambda x: f"{x}月")
        st.session_state.selected_month = month
    with col3:
        if st.button("🔄 シフトを自動生成", use_container_width=True, type="primary"):
            if not st.session_state.doctors:
                st.error("先に医師を登録してください。")
            else:
                with st.spinner("シフトを生成中..."):
                    result, counts = generate_shifts(
                        year, month,
                        st.session_state.doctors,
                        st.session_state.doctor_limits,
                        st.session_state.constraints,
                        st.session_state.fixed_shifts,
                    )
                    st.session_state.generated_shifts = result
                    st.session_state.shift_counts = counts
                st.success("✅ シフトを生成しました！")

    # ── シフト表示 ─────────────────────────────────────────
    if st.session_state.generated_shifts:
        days = get_days_in_month(year, month)
        rows = []
        for d in days:
            day_str = str(d)
            shifts = SHIFT_HOLIDAY if is_holiday(d) else SHIFT_WEEKDAY
            row = {"日付": day_label(d), "種別": "🔴 休日/祝日" if is_holiday(d) else "🔵 平日"}
            for s in ALL_SHIFTS:
                if s in shifts:
                    doc = st.session_state.generated_shifts.get(day_str, {}).get(s, "—")
                    fixed_key = f"{day_str}_{s}"
                    row[s] = f"🔒 {doc}" if fixed_key in st.session_state.fixed_shifts else doc
                else:
                    row[s] = "—"
            rows.append(row)

        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True, height=600)

        # ── CSV出力 ────────────────────────────────────────
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        st.download_button("⬇️ シフト表CSVダウンロード", buf.getvalue(),
                           f"shift_{year}_{month:02d}.csv", "text/csv")

# ════════════════════════════════════════════════════════════
# ページ: 統計・分析
# ════════════════════════════════════════════════════════════
elif menu == "📈 統計・分析":
    st.markdown('<div class="main-header"><h2>📈 統計・分析</h2><p>シフト割当の統計情報を確認します</p></div>', unsafe_allow_html=True)

    if not st.session_state.generated_shifts:
        st.info("先にシフトを生成してください。")
    else:
        counts = getattr(st.session_state, "shift_counts", {})
        if counts:
            df_counts = pd.DataFrame(counts).T.fillna(0).astype(int)
            df_counts["合計"] = df_counts.sum(axis=1)
            st.subheader("📊 医師別シフト割当回数")
            st.dataframe(df_counts, use_container_width=True)

            st.subheader("📈 合計割当回数（棒グラフ）")
            st.bar_chart(df_counts["合計"])

            # 制約チェック
            st.subheader("⚠️ 制約チェック")
            issues = []
            for doc in st.session_state.doctors:
                c = st.session_state.constraints.get(doc, {})
                total = sum(counts.get(doc, {}).values())
                if total < c.get("month_min", 0):
                    issues.append(f"🔴 {doc}: 最小回数未満（{total} < {c['month_min']}）")
                if total > c.get("month_max", 99):
                    issues.append(f"🔴 {doc}: 最大回数超過（{total} > {c['month_max']}）")
            if issues:
                for i in issues:
                    st.warning(i)
            else:
                st.success("✅ 全制約クリア")
