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

st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #1a5276 0%, #2e86c1 100%);
        color: white; padding: 1.2rem 2rem;
        border-radius: 10px; margin-bottom: 1.5rem;
    }
    div[data-testid="stDataFrame"] { border-radius: 8px; overflow: hidden; }
    .hint-box {
        background: #eaf4fb; border-left: 4px solid #2e86c1;
        padding: 0.8rem 1rem; border-radius: 0 8px 8px 0;
        font-size: 13px; color: #1a3a4a; margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)

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

SHIFT_WEEKDAY = ["宿直A", "宿直B", "外来宿直"]
SHIFT_HOLIDAY = ["宿直A", "宿直B", "外来宿直", "日直A", "日直B", "外来日直"]
ALL_SHIFTS    = ["宿直A", "宿直B", "外来宿直", "日直A", "日直B", "外来日直"]

def is_holiday(d):
    return d.weekday() >= 5 or jpholiday.is_holiday(d)

def get_days_in_month(year, month):
    _, n = calendar.monthrange(year, month)
    return [date(year, month, d) for d in range(1, n+1)]

def day_label(d):
    w = ["月","火","水","木","金","土","日"][d.weekday()]
    holiday = jpholiday.is_holiday_name(d)
    mark = f"({holiday})" if holiday else ""
    return f"{d.month}/{d.day}({w}){mark}"

def parse_date_list(val):
    if pd.isna(val) or str(val).strip() == "":
        return []
    return [s.strip() for s in str(val).split(",") if s.strip()]

def export_all_constraints_csv():
    rows = []
    for doc in st.session_state.doctors:
        c   = st.session_state.constraints.get(doc, {})
        lim = st.session_state.doctor_limits.get(doc, {})
        row = {
            "医師名": doc,
            "優先度": c.get("priority", 5),
            "月間最小回数": c.get("month_min", 0),
            "月間最大回数": c.get("month_max", 20),
            "最低空ける日数": c.get("min_gap", 1),
            "希望日優先度": c.get("wish_priority", 3),
            "NG日(カンマ区切り)": ",".join(c.get("ng_days", [])),
            "希望日(カンマ区切り)": ",".join(c.get("wish_days", [])),
        }
        for s in ALL_SHIFTS:
            row[f"{s}_上限"] = lim.get(s, 5)
        rows.append(row)
    df = pd.DataFrame(rows)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()

def import_all_constraints_csv(uploaded_file):
    df = pd.read_csv(uploaded_file)
    new_doctors = []
    for _, row in df.iterrows():
        doc = str(row["医師名"]).strip()
        if not doc:
            continue
        new_doctors.append(doc)
        st.session_state.constraints[doc] = {
            "priority":      int(row.get("優先度", 5)),
            "month_min":     int(row.get("月間最小回数", 0)),
            "month_max":     int(row.get("月間最大回数", 20)),
            "min_gap":       int(row.get("最低空ける日数", 1)),
            "wish_priority": int(row.get("希望日優先度", 3)),
            "ng_days":       parse_date_list(row.get("NG日(カンマ区切り)", "")),
            "wish_days":     parse_date_list(row.get("希望日(カンマ区切り)", "")),
        }
        st.session_state.doctor_limits[doc] = {
            s: int(row.get(f"{s}_上限", 5)) for s in ALL_SHIFTS
        }
    for doc in new_doctors:
        if doc not in st.session_state.doctors:
            st.session_state.doctors.append(doc)
    return new_doctors

def make_template_csv():
    sample = {
        "医師名": ["山田 太郎", "鈴木 花子"],
        "優先度": [5, 7],
        "月間最小回数": [2, 2],
        "月間最大回数": [10, 8],
        "最低空ける日数": [1, 2],
        "希望日優先度": [3, 4],
        "NG日(カンマ区切り)": ["2026-04-05,2026-04-12", "2026-04-20"],
        "希望日(カンマ区切り)": ["2026-04-15", "2026-04-10,2026-04-17"],
    }
    for s in ALL_SHIFTS:
        sample[f"{s}_上限"] = [5, 4]
    df = pd.DataFrame(sample)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()

def generate_shifts(year, month, doctors, doctor_limits, constraints, fixed_shifts):
    import random
    days = get_days_in_month(year, month)
    shift_result = {str(d): {} for d in days}
    for key, val in fixed_shifts.items():
        parts = key.split("_", 1)
        if len(parts) == 2:
            day_str, shift_type = parts
            if day_str in shift_result:
                shift_result[day_str][shift_type] = val
    counts      = {doc: {s: 0 for s in ALL_SHIFTS} for doc in doctors}
    last_worked = {doc: None for doc in doctors}
    for d in days:
        day_str      = str(d)
        shifts_today = SHIFT_HOLIDAY if is_holiday(d) else SHIFT_WEEKDAY
        for shift in shifts_today:
            if shift in shift_result[day_str]:
                doc = shift_result[day_str][shift]
                if doc in counts:
                    counts[doc][shift] += 1
                    last_worked[doc] = d
                continue
            candidates = []
            for doc in doctors:
                c         = constraints.get(doc, {})
                ng_days   = [date.fromisoformat(x) for x in c.get("ng_days", []) if x]
                wish_days = [date.fromisoformat(x) for x in c.get("wish_days", []) if x]
                min_gap   = c.get("min_gap", 1)
                month_max = c.get("month_max", 99)
                priority  = c.get("priority", 5)
                lim       = doctor_limits.get(doc, {})
                shift_max = lim.get(shift, 99)
                if d in ng_days: continue
                if counts[doc][shift] >= shift_max: continue
                if sum(counts[doc].values()) >= month_max: continue
                if last_worked[doc] is not None:
                    if (d - last_worked[doc]).days < min_gap: continue
                score = priority * 10
                if d in wish_days: score += 20
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

with st.sidebar:
    st.markdown("## 🏥 医師シフト管理")
    st.markdown("---")
    menu = st.radio("メニュー", [
        "📅 シフト生成・表示",
        "📋 医師条件 CSV入出力",
        "👨‍⚕️ 医師設定（個別編集）",
        "📌 固定シフト入力",
        "📈 統計・分析",
    ])

# ════════════════════════════════════════════════════════════
if menu == "📋 医師条件 CSV入出力":
    st.markdown('<div class="main-header"><h2>📋 医師条件 CSV入出力</h2><p>全医師の条件をCSVで一括管理します</p></div>', unsafe_allow_html=True)

    st.subheader("① テンプレートCSVをダウンロード")
    st.markdown('<div class="hint-box">テンプレートをダウンロードしてExcelなどで記入してください。<br>日付は <b>YYYY-MM-DD</b> 形式（例: 2026-04-05）、複数はカンマ区切りです。</div>', unsafe_allow_html=True)
    st.download_button("⬇️ テンプレートCSVダウンロード", make_template_csv(),
                       "doctors_template.csv", "text/csv", use_container_width=True)

    st.markdown("---")
    st.subheader("② 入力済みCSVをアップロード")
    uploaded = st.file_uploader("CSVファイルを選択", type="csv")
    if uploaded:
        try:
            imported = import_all_constraints_csv(uploaded)
            st.success(f"✅ {len(imported)} 名を読み込みました：{', '.join(imported)}")
            st.rerun()
        except Exception as e:
            st.error(f"❌ 読み込みエラー：{e}")

    st.markdown("---")
    st.subheader("③ 現在の設定を確認・編集")

    if not st.session_state.doctors:
        st.info("まだ医師が登録されていません。テンプレートをダウンロードして入力してください。")
    else:
        rows = []
        for doc in st.session_state.doctors:
            c   = st.session_state.constraints.get(doc, {})
            lim = st.session_state.doctor_limits.get(doc, {})
            row = {
                "医師名":         doc,
                "優先度":         c.get("priority", 5),
                "月間最小":       c.get("month_min", 0),
                "月間最大":       c.get("month_max", 20),
                "最低空け日数":   c.get("min_gap", 1),
                "希望日優先度":   c.get("wish_priority", 3),
                "NG日":           ",".join(c.get("ng_days", [])),
                "希望日":         ",".join(c.get("wish_days", [])),
            }
            for s in ALL_SHIFTS:
                row[f"{s}上限"] = lim.get(s, 5)
            rows.append(row)

        df_view = pd.DataFrame(rows)
        col_config = {
            "医師名":       st.column_config.TextColumn("医師名", width="medium"),
            "優先度":       st.column_config.NumberColumn("優先度", min_value=1, max_value=10, step=1),
            "月間最小":     st.column_config.NumberColumn("月間最小", min_value=0, max_value=31, step=1),
            "月間最大":     st.column_config.NumberColumn("月間最大", min_value=0, max_value=31, step=1),
            "最低空け日数": st.column_config.NumberColumn("最低空け日数", min_value=1, max_value=14, step=1),
            "希望日優先度": st.column_config.NumberColumn("希望日優先度", min_value=1, max_value=5, step=1),
            "NG日":         st.column_config.TextColumn("NG日（YYYY-MM-DD,...）", width="large"),
            "希望日":       st.column_config.TextColumn("希望日（YYYY-MM-DD,...）", width="large"),
        }
        for s in ALL_SHIFTS:
            col_config[f"{s}上限"] = st.column_config.NumberColumn(f"{s}上限", min_value=0, max_value=31, step=1)

        edited_df = st.data_editor(df_view, column_config=col_config,
                                   use_container_width=True, hide_index=True, num_rows="dynamic")

        col_save, col_dl = st.columns(2)
        with col_save:
            if st.button("💾 変更を保存", use_container_width=True, type="primary"):
                st.session_state.doctors = []
                for _, row in edited_df.iterrows():
                    doc = str(row["医師名"]).strip()
                    if not doc: continue
                    st.session_state.doctors.append(doc)
                    st.session_state.constraints[doc] = {
                        "priority":      int(row["優先度"]),
                        "month_min":     int(row["月間最小"]),
                        "month_max":     int(row["月間最大"]),
                        "min_gap":       int(row["最低空け日数"]),
                        "wish_priority": int(row["希望日優先度"]),
                        "ng_days":       parse_date_list(row["NG日"]),
                        "wish_days":     parse_date_list(row["希望日"]),
                    }
                    st.session_state.doctor_limits[doc] = {s: int(row[f"{s}上限"]) for s in ALL_SHIFTS}
                st.success("✅ 保存しました！")
                st.rerun()
        with col_dl:
            if st.session_state.doctors:
                st.download_button("⬇️ 現在の設定をCSVで保存", export_all_constraints_csv(),
                                   "doctors_constraints.csv", "text/csv", use_container_width=True)

# ════════════════════════════════════════════════════════════
elif menu == "👨‍⚕️ 医師設定（個別編集）":
    st.markdown('<div class="main-header"><h2>👨‍⚕️ 医師設定（個別編集）</h2><p>医師を1名ずつ詳細に設定します</p></div>', unsafe_allow_html=True)

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
                st.session_state.doctor_limits[new_doc] = {s: 5 for s in ALL_SHIFTS}
                st.success(f"✅ {new_doc} を追加しました")

        st.subheader("登録済み医師")
        for doc in st.session_state.doctors:
            c1, c2 = st.columns([3, 1])
            c1.write(f"👤 {doc}")
            if c2.button("削除", key=f"del_{doc}"):
                st.session_state.doctors.remove(doc)
                st.session_state.constraints.pop(doc, None)
                st.session_state.doctor_limits.pop(doc, None)
                st.rerun()

    with col2:
        if st.session_state.doctors:
            st.subheader("制約条件設定")
            sel_doc = st.selectbox("医師を選択", st.session_state.doctors)
            c   = st.session_state.constraints.get(sel_doc, {})
            lim = st.session_state.doctor_limits.get(sel_doc, {})
            year  = st.session_state.selected_year
            month = st.session_state.selected_month

            tab1, tab2 = st.tabs(["基本条件", "シフト別上限"])
            with tab1:
                col_a, col_b = st.columns(2)
                with col_a:
                    priority  = st.slider("優先度", 1, 10, c.get("priority", 5))
                    month_min = st.number_input("月間最小回数", 0, 31, c.get("month_min", 0))
                    month_max = st.number_input("月間最大回数", 0, 31, c.get("month_max", 20))
                    min_gap   = st.number_input("最低空ける日数", 1, 14, c.get("min_gap", 1))
                with col_b:
                    wish_priority = st.slider("希望日の優先度", 1, 5, c.get("wish_priority", 3))
                    _, n = calendar.monthrange(year, month)
                    all_days = [date(year, month, d) for d in range(1, n+1)]
                    ng_days_sel = st.multiselect("NG日", all_days,
                        default=[date.fromisoformat(x) for x in c.get("ng_days", []) if x and date.fromisoformat(x) in all_days],
                        format_func=day_label, key=f"ng_{sel_doc}")
                    wish_days_sel = st.multiselect("希望日", all_days,
                        default=[date.fromisoformat(x) for x in c.get("wish_days", []) if x and date.fromisoformat(x) in all_days],
                        format_func=day_label, key=f"wish_{sel_doc}")
            with tab2:
                st.markdown("シフト種別ごとの月間上限回数を設定します。")
                shift_limits = {}
                cols = st.columns(3)
                for i, s in enumerate(ALL_SHIFTS):
                    with cols[i % 3]:
                        shift_limits[s] = st.number_input(s, 0, 31, lim.get(s, 5), key=f"lim_{sel_doc}_{s}")

            if st.button("💾 保存", use_container_width=True, type="primary"):
                st.session_state.constraints[sel_doc] = {
                    "priority": priority, "month_min": month_min, "month_max": month_max,
                    "min_gap": min_gap, "wish_priority": wish_priority,
                    "ng_days":   [str(d) for d in ng_days_sel],
                    "wish_days": [str(d) for d in wish_days_sel],
                }
                st.session_state.doctor_limits[sel_doc] = shift_limits
                st.success("✅ 保存しました")

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
        available = SHIFT_HOLIDAY if is_holiday(sel_day) else SHIFT_WEEKDAY
        sel_shift = st.selectbox("シフト種別", available)
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
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            del_keys = st.multiselect("削除するシフトを選択", list(st.session_state.fixed_shifts.keys()))
            if st.button("🗑️ 選択した固定シフトを削除"):
                for k in del_keys:
                    st.session_state.fixed_shifts.pop(k, None)
                st.rerun()
        else:
            st.info("固定シフトはまだありません。")

# ════════════════════════════════════════════════════════════
elif menu == "📅 シフト生成・表示":
    st.markdown('<div class="main-header"><h2>📅 シフト生成・表示</h2><p>制約条件を考慮してシフトを自動生成します</p></div>', unsafe_allow_html=True)

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
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        st.download_button("⬇️ シフト表CSVダウンロード", buf.getvalue(),
                           f"shift_{year}_{month:02d}.csv", "text/csv")

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
            st.subheader("📈 合計割当回数")
            st.bar_chart(df_counts["合計"])
            st.subheader("⚠️ 制約チェック")
            issues = []
            for doc in st.session_state.doctors:
                c     = st.session_state.constraints.get(doc, {})
                total = sum(counts.get(doc, {}).values())
                if total < c.get("month_min", 0):
                    issues.append(f"🔴 {doc}: 最小回数未満（{total} < {c['month_min']}）")
                if total > c.get("month_max", 99):
                    issues.append(f"🔴 {doc}: 最大回数超過（{total} > {c['month_max']}）")
            if issues:
                for i in issues: st.warning(i)
            else:
                st.success("✅ 全制約クリア")
